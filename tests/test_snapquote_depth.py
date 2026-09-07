"""Tests for the SnapQuote best-5 depth parser and its warm-up disk cache.

The depth block is the part of the tick that decides whether the recorded spread is a quote
or a guess, so the failure that matters is not "it raised" — it is "it returned a plausible
but inverted book". These tests pin the side-detection down, because the vendored SmartApi SDK
assigns the two sides the opposite way round from the flag and the documentation does not
settle which is right.
"""
from __future__ import annotations

import os
import struct
import tempfile
from datetime import datetime

import pytest

from brokers.angel_one.client import AngelOneClient


def _rec(flag: int, qty: int, price_paise: int, orders: int = 1) -> bytes:
    return (struct.pack("<H", flag) + struct.pack("<q", qty)
            + struct.pack("<q", price_paise) + struct.pack("<H", orders))


def _block(buy_flag: int, bids, asks) -> bytes:
    """200 bytes: five records for each side, padded with empty levels."""
    sell_flag = 1 - buy_flag
    recs = [_rec(buy_flag, 50, int(p * 100)) for p in bids]
    recs += [_rec(sell_flag, 50, int(p * 100)) for p in asks]
    while len(recs) < 10:
        recs.append(_rec(buy_flag, 0, 0))       # unfilled level: qty and price both zero
    return b"".join(recs[:10])


@pytest.fixture
def client():
    c = AngelOneClient.__new__(AngelOneClient)   # no login, no network
    c._best5_warned = False

    class _L:
        def warning(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
    c.logger = _L()
    return c


def test_reads_the_book_when_flag_zero_is_the_buy_side(client):
    block = _block(0, [100.0, 99.5, 99.0], [100.4, 100.9, 101.4])
    out = client._parse_best5(block, ltp=100.2)
    assert out["best_bid_price"] == 100.0
    assert out["best_ask_price"] == 100.4
    assert out["depth_source"] == "ws_best5"


def test_reads_the_same_book_when_flag_zero_is_the_sell_side(client):
    """The SDK swaps these two, so the parser must not trust the flag's meaning."""
    block = _block(1, [100.0, 99.5, 99.0], [100.4, 100.9, 101.4])
    out = client._parse_best5(block, ltp=100.2)
    assert out["best_bid_price"] == 100.0
    assert out["best_ask_price"] == 100.4


def test_picks_the_best_level_on_each_side_not_the_first(client):
    block = _block(0, [99.0, 100.0, 99.5], [101.4, 100.4, 100.9])
    out = client._parse_best5(block, ltp=100.2)
    assert out["best_bid_price"] == 100.0      # highest bid
    assert out["best_ask_price"] == 100.4      # lowest ask


def test_rejects_a_book_that_does_not_contain_the_last_trade(client):
    """A quote whose own ltp sits outside it is not understood, so the caller keeps its
    estimate rather than publishing a wrong spread."""
    block = _block(0, [100.0, 99.5], [100.4, 100.9])
    assert client._parse_best5(block, ltp=105.0) is None


def test_warns_only_once_for_a_rejected_book(client):
    seen = []
    client.logger.warning = lambda msg, *a, **k: seen.append(msg)
    block = _block(0, [100.0], [100.4])
    for _ in range(5):
        client._parse_best5(block, ltp=105.0)
    assert len(seen) == 1


def test_empty_levels_are_not_quotes(client):
    """Zero price/quantity records are unfilled levels; a block of them yields nothing."""
    block = b"".join(_rec(0, 0, 0) for _ in range(10))
    assert client._parse_best5(block, ltp=100.0) is None


def test_one_sided_book_is_not_a_book(client):
    block = b"".join([_rec(0, 50, 10000) for _ in range(5)]
                     + [_rec(0, 0, 0) for _ in range(5)])
    assert client._parse_best5(block, ltp=100.0) is None


def test_short_block_is_refused(client):
    assert client._parse_best5(b"\x00" * 100, ltp=100.0) is None


def test_quote_mode_packet_carries_no_depth_or_oi(client):
    """Mode 2 is what the bot subscribed with all along: the fields simply are not there,
    which is why TICK_OI_ENABLED only ever wrote zeros."""
    data = bytearray(200)
    data[0] = 2                                     # subscription mode
    struct.pack_into("<q", data, 43, 10000)         # ltp
    tick = client._parse_ws_binary(bytes(data))
    assert tick is not None
    assert "open_interest" not in tick
    assert "best_bid_price" not in tick


def test_snapquote_packet_carries_oi_and_depth(client):
    data = bytearray(379)
    data[0] = 3
    struct.pack_into("<q", data, 43, 10020)         # ltp 100.20
    struct.pack_into("<q", data, 131, 4321)         # open interest
    data[147:347] = _block(0, [100.0, 99.5], [100.4, 100.9])
    tick = client._parse_ws_binary(bytes(data))
    assert tick["open_interest"] == 4321
    assert tick["best_bid_price"] == 100.0
    assert tick["best_ask_price"] == 100.4


def test_candle_cache_survives_a_new_process():
    """The in-memory cache is empty exactly when warm-up needs it — at startup."""
    from core.trading.broker import BrokerInterface

    b = BrokerInterface.__new__(BrokerInterface)
    b.logger = None
    candles = [{"timestamp": "2026-09-07T09:00:00", "open": 1.0, "high": 2.0,
                "low": 0.5, "close": 1.5, "volume": 10}]
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            b._save_candle_cache("NSE:1:FIVE_MINUTE", candles, datetime(2026, 9, 7, 9, 0, 0))

            fresh = BrokerInterface.__new__(BrokerInterface)   # a different "process"
            fresh.logger = None
            got = fresh._load_candle_cache("NSE:1:FIVE_MINUTE")
            assert got is not None
            assert got[0] == candles
            assert got[1] == "2026-09-07 09:00:00"
            assert fresh._load_candle_cache("NSE:2:FIVE_MINUTE") is None
        finally:
            os.chdir(cwd)


def test_candle_cache_write_failure_is_not_fatal():
    """A cache write must never break a fetch that actually succeeded. Runs inside a temp
    cwd because _candle_cache_path is relative -- an earlier version of this test wrote its
    junk straight into the project's real data/candle_cache/."""
    from core.trading.broker import BrokerInterface

    b = BrokerInterface.__new__(BrokerInterface)
    b.logger = None
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            b._save_candle_cache("bad/../key:x", [{"a": 1}], datetime.now())   # must not raise
        finally:
            os.chdir(cwd)


# ── cross-direction strike selection ────────────────────────────────────────
# The bug: current_strike is chosen to put the SUBSCRIBED option type in the premium
# band, and both the validation path and the order path reused it for the opposite
# direction — which is the opposite moneyness, and therefore the wrong price.

def _broker(monkeypatch, *, enabled=True, symbol="NIFTY08SEP2623800CE",
            strike=23800, spot=23850.0, found=(23900, 180.0)):
    import importlib
    # core.trading's __init__ exports the singleton under the name `broker`, which shadows
    # the submodule — import it explicitly or you get the instance.
    bmod = importlib.import_module("core.trading.broker")

    b = bmod.BrokerInterface.__new__(bmod.BrokerInterface)
    b.current_symbol = symbol
    b.current_strike = strike
    b.spot_price = spot
    b._cross_strike_cache = {}
    b.calls = []

    class _L:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
    b.logger = _L()

    def _find(option_type="CE"):
        b.calls.append(option_type)
        return found
    b._find_strike_by_premium = _find

    monkeypatch.setattr(bmod, "CROSS_DIRECTION_STRIKE_ENABLED", enabled)
    monkeypatch.setattr(bmod, "CROSS_DIRECTION_STRIKE_TTL_SEC", 60)
    return b


def test_opposite_direction_gets_its_own_strike(monkeypatch):
    b = _broker(monkeypatch)
    assert b.resolve_strike_for_direction("PE") == 23900
    assert b.calls == ["PE"]


def test_subscribed_direction_never_triggers_a_search(monkeypatch):
    b = _broker(monkeypatch)
    assert b.resolve_strike_for_direction("CE") == 23800
    assert b.calls == []


def test_disabled_flag_reproduces_the_old_behaviour(monkeypatch):
    b = _broker(monkeypatch, enabled=False)
    assert b.resolve_strike_for_direction("PE") == 23800
    assert b.calls == []


def test_result_is_cached_so_rest_calls_stay_bounded(monkeypatch):
    b = _broker(monkeypatch)
    for _ in range(25):
        b.resolve_strike_for_direction("PE")
    assert b.calls == ["PE"], "the premium search costs 5 REST calls; it must not repeat"


def test_cache_is_dropped_when_spot_moves_to_a_new_atm(monkeypatch):
    b = _broker(monkeypatch)
    b.resolve_strike_for_direction("PE")
    b.spot_price = 23950.0                     # ATM 23850 -> 23950
    b.resolve_strike_for_direction("PE")
    assert b.calls == ["PE", "PE"]


def test_cache_expires_with_the_ttl(monkeypatch):
    import importlib
    bmod = importlib.import_module("core.trading.broker")
    b = _broker(monkeypatch)
    b.resolve_strike_for_direction("PE")
    monkeypatch.setattr(bmod, "CROSS_DIRECTION_STRIKE_TTL_SEC", 0)
    b.resolve_strike_for_direction("PE")
    assert b.calls == ["PE", "PE"]


def test_a_failed_search_falls_back_to_the_current_strike(monkeypatch):
    b = _broker(monkeypatch)

    def _boom(option_type="CE"):
        raise RuntimeError("LTP timeout")
    b._find_strike_by_premium = _boom
    assert b.resolve_strike_for_direction("PE") == 23800


def test_no_strike_in_band_falls_back_to_the_current_strike(monkeypatch):
    b = _broker(monkeypatch, found=(None, 0))
    assert b.resolve_strike_for_direction("PE") == 23800


def test_unknown_spot_falls_back_to_the_current_strike(monkeypatch):
    b = _broker(monkeypatch, spot=0.0)
    assert b.resolve_strike_for_direction("PE") == 23800
    assert b.calls == []


# ── streak pause: it must start when the streak happens ─────────────────────

def _rm(monkeypatch, pause_sec=900, loss_limit=2):
    from core.risk.risk_manager import RiskManager

    r = RiskManager.__new__(RiskManager)
    r.config = {"risk_management": {"pause_after_consecutive_loss_sec": pause_sec,
                                    "consecutive_loss_limit": loss_limit,
                                    "consecutive_win_limit": 5}}
    r.consecutive_losses = 0
    r.consecutive_wins = 0
    r.streak_pause_until = None
    r._log = lambda *a, **k: None
    return r


def test_pause_is_armed_at_the_moment_the_streak_completes(monkeypatch):
    """Not when check_streak_limits() first looks. The state machine sits in its own
    COOLDOWN until then, so a late-arming clock runs back to back with it instead of
    together -- 30 minutes for a 15-minute setting, as happened on 2026-09-07."""
    from datetime import datetime, timedelta

    r = _rm(monkeypatch)
    r.update_streak(-100.0)
    assert r.streak_pause_until is None, "one loss is not a streak"
    before = datetime.now()
    r.update_streak(-100.0)
    assert r.streak_pause_until is not None
    assert r.streak_pause_until - before <= timedelta(seconds=901)


def test_a_later_check_does_not_push_the_pause_further_out():
    from datetime import datetime, timedelta

    r = _rm(_rm)
    r.update_streak(-100.0)
    r.update_streak(-100.0)
    armed = r.streak_pause_until
    r.streak_pause_until = datetime.now() - timedelta(seconds=1)   # pretend it expired
    ok, _ = r.check_streak_limits()
    assert ok, "an expired pause must release, not re-arm"
    assert r.consecutive_losses == 0
    assert r.streak_pause_until is None
    assert armed is not None


def test_pause_blocks_while_active():
    r = _rm(_rm)
    r.update_streak(-100.0)
    r.update_streak(-100.0)
    ok, msg = r.check_streak_limits()
    assert not ok and "remaining" in msg


def test_a_win_clears_the_loss_streak_without_arming():
    r = _rm(_rm)
    r.update_streak(-100.0)
    r.update_streak(50.0)
    assert r.consecutive_losses == 0
    assert r.streak_pause_until is None


def test_idle_block_is_logged_once_per_reason():
    from core.engines.state_machine import _log_idle_block

    class S: pass
    class L:
        def __init__(self): self.msgs = []
        def info(self, m): self.msgs.append(m)
    s, lg = S(), L()
    for _ in range(5):
        _log_idle_block(s, lg, "limits", "Streak pause active, 9min remaining")
    assert len(lg.msgs) == 1
    _log_idle_block(s, lg, "limits", "Streak pause active, 3min remaining")
    assert len(lg.msgs) == 2


# ── the daily loss ceiling must survive a restart ───────────────────────────

def _rm_with_state(tmpdir, config=None):
    """A RiskManager rooted at tmpdir, so it reads/writes logs/risk_state.json there."""
    from core.risk.risk_manager import RiskManager

    cfg = config or {
        "capital": {"total_capital": 30000},
        "risk_management": {"pause_after_consecutive_loss_sec": 900,
                            "consecutive_loss_limit": 2, "consecutive_win_limit": 5},
    }
    return RiskManager(cfg, logger=None)


def test_daily_pnl_survives_a_restart_on_the_same_day():
    """MAX_DAILY_LOSS_AMOUNT and the kill switch are measured against daily_pnl. It was
    never persisted, so each restart handed the bot a fresh full loss budget."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_with_state(tmp)
            r.daily_pnl = -2900.0
            r._save_state()

            again = _rm_with_state(tmp)                      # "restart"
            assert again.daily_pnl == -2900.0
        finally:
            os.chdir(cwd)


def test_a_new_day_starts_the_ceiling_at_zero():
    import json as _json
    from datetime import date, timedelta

    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_with_state(tmp)
            r.daily_pnl = -2900.0
            r._save_state()

            path = os.path.join(tmp, "logs", "risk_state.json")
            with open(path) as fh:
                blob = _json.load(fh)
            blob["daily_date"] = (date.today() - timedelta(days=1)).isoformat()
            with open(path, "w") as fh:
                _json.dump(blob, fh)

            again = _rm_with_state(tmp)
            assert again.daily_pnl == 0.0, "yesterday's loss must not eat today's budget"
        finally:
            os.chdir(cwd)
