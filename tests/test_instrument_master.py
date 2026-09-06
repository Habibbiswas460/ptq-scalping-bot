"""Expiry must come from the broker's contract list, never from a weekday rule.

The bug these guard: utils.helpers.is_expiry_date() returned `weekday() == 3`, and every
NIFTY weekly Angel One lists is a Tuesday - so it was true only on days that are never
expiry, and false on every day that is. core/risk/greeks_calc.py derived time-to-expiry
the same way, putting theta, gamma and detect_day_type()'s classification two days out.
"""
import json
from datetime import date, datetime

import pytest

from utils import instruments as expiry


# Real shape of core/data/scripmaster_nifty_nfo.json: the broker's symbol -> token map.
TUESDAYS = ["08SEP26", "15SEP26", "22SEP26", "29SEP26"]


def _write_master(tmp_path, expiries=TUESDAYS, extra=()):
    symbols = {}
    for e in expiries:
        for strike in (24500, 24600, 24700):
            for side in ("CE", "PE"):
                symbols[f"NIFTY{e}{strike}{side}"] = str(len(symbols) + 1)
    for sym in extra:
        symbols[sym] = "0"
    p = tmp_path / "scripmaster.json"
    p.write_text(json.dumps({"saved_at": "x", "token_map": symbols}), encoding="utf-8")
    return str(p)


def test_expiries_are_read_from_the_contract_list(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.expiry_dates(path) == [
        date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]


def test_the_expiry_weekday_is_learned_not_declared(tmp_path):
    # Tuesday is weekday 1. Nothing in the code says so; it is counted from the dump,
    # so an exchange moving expiry again needs no code change.
    assert expiry.expiry_weekday(_write_master(tmp_path)) == 1


def test_a_listed_date_is_expiry_and_a_thursday_is_not(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.is_expiry_date(date(2026, 9, 8), path) is True      # Tuesday, listed
    assert expiry.is_expiry_date(date(2026, 9, 10), path) is False    # Thursday, not listed
    assert date(2026, 9, 10).weekday() == 3                           # the old rule's answer


def test_nearest_and_next_differ_on_expiry_day(tmp_path):
    path = _write_master(tmp_path)
    on_expiry = date(2026, 9, 8)
    assert expiry.nearest_expiry(on_expiry, path) == on_expiry
    # Angel One serves no Greeks for a contract expiring today, so the Greeks path needs
    # the one after it.
    assert expiry.next_expiry_after(on_expiry, path) == date(2026, 9, 15)


def test_expiry_datetime_lands_on_the_close(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.expiry_datetime(date(2026, 9, 8), path) == datetime(2026, 9, 8, 15, 30)


def test_dates_after_the_last_listed_contract_are_unknown(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.nearest_expiry(date(2026, 12, 1), path) is None
    assert expiry.expiry_datetime(date(2026, 12, 1), path) is None


def test_a_missing_master_is_reported_as_unknown_not_guessed(tmp_path):
    absent = str(tmp_path / "does_not_exist.json")
    assert expiry.expiry_dates(absent) == []
    assert expiry.is_expiry_date(date(2026, 9, 10), absent) is False
    assert expiry.nearest_expiry(date(2026, 9, 8), absent) is None
    assert expiry.expiry_weekday(absent) is None
    assert "no instrument master" in expiry.describe(absent)


def test_unreadable_master_is_unknown_rather_than_an_exception(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert expiry.expiry_dates(str(p)) == []


def test_symbols_that_are_not_nifty_options_are_ignored(tmp_path):
    path = _write_master(tmp_path, extra=("BANKNIFTY08SEP2650000CE", "NIFTY", "NIFTYNOTADATE1CE"))
    assert expiry.expiry_dates(path) == [
        date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]


def test_a_rewritten_master_is_re_read(tmp_path):
    # broker startup rewrites this file; a cached parse must not outlive it.
    path = _write_master(tmp_path, ["08SEP26"])
    assert expiry.expiry_dates(path) == [date(2026, 9, 8)]
    _write_master(tmp_path, ["15SEP26"])
    assert expiry.expiry_dates(path) == [date(2026, 9, 15)]


def test_helpers_delegates_to_the_master(tmp_path, monkeypatch):
    from utils import helpers

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))

    class _On(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 9, 8, 10, 0)      # a listed Tuesday

    class _Off(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 9, 10, 10, 0)     # the Thursday the old rule liked

    monkeypatch.setattr(expiry, "datetime", _On)
    assert helpers.is_expiry_date() is True
    monkeypatch.setattr(expiry, "datetime", _Off)
    assert helpers.is_expiry_date() is False


def test_greeks_asks_for_a_date_that_exists(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))
    got = greeks_calc.GreeksFetcher().get_expiry_date_str()
    # Whatever it returns must be a real listed expiry, formatted for the API.
    assert got == "" or datetime.strptime(got, "%d%b%Y").date() in expiry.expiry_dates(
        expiry.SCRIP_MASTER_CACHE_FILE)


def test_greeks_skips_the_api_when_expiry_is_unknown(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", str(tmp_path / "absent.json"))
    fetcher = greeks_calc.GreeksFetcher(broker_client=object())
    assert fetcher.get_expiry_date_str() == ""


def test_resolve_expiry_time_never_lands_on_a_weekday_rule(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))
    when = greeks_calc._resolve_expiry_time()
    assert when.date() in expiry.expiry_dates(expiry.SCRIP_MASTER_CACHE_FILE)
    assert (when.hour, when.minute) == (15, 30)


# ── contract mechanics: the fields the loader used to discard ────────────────
def _write_contracts(tmp_path, lot="65", tick="5.000000", freeze="1801",
                     step=50, futures=True):
    """A cache in the shape broker.py now writes: the exchange's own record per symbol.
    Strike and tick arrive in paise, as they do in the published master."""
    contracts = {}
    for e in TUESDAYS:
        for strike in range(24000, 24000 + step * 6, step):
            for side in ("CE", "PE"):
                contracts[f"NIFTY{e}{strike}{side}"] = {
                    "token": str(len(contracts) + 1), "expiry": f"{e[:5]}20{e[5:]}",
                    "strike": f"{strike * 100}.000000", "lotsize": lot,
                    "tick_size": tick, "freeze_qty": freeze, "instrumenttype": "OPTIDX"}
    if futures:
        # Index futures sit under the same name and quote in a different tick. They must
        # not be averaged into the option figures.
        contracts["NIFTY29SEP26FUT"] = {
            "token": "999", "expiry": "29SEP2026", "strike": "0.000000",
            "lotsize": lot, "tick_size": "10.000000", "freeze_qty": freeze,
            "instrumenttype": "FUTIDX"}
    p = tmp_path / "master.json"
    p.write_text(json.dumps({"saved_at": "x", "contracts": contracts}), encoding="utf-8")
    return str(p)


def test_contract_mechanics_come_from_the_exchange(tmp_path):
    path = _write_contracts(tmp_path)
    assert expiry.lot_size(path) == 65
    assert expiry.tick_size(path) == 0.05          # 5 paise, not the raw 5
    assert expiry.freeze_quantity(path) == 1801
    assert expiry.strike_step(path) == 50


def test_futures_do_not_pollute_the_option_tick(tmp_path):
    # The futures row carries tick 0.10; the options' 0.05 must win.
    assert expiry.tick_size(_write_contracts(tmp_path, futures=True)) == 0.05


def test_a_changed_lot_size_is_visible(tmp_path):
    assert expiry.lot_size(_write_contracts(tmp_path, lot="75")) == 75


def test_strike_step_follows_what_is_listed(tmp_path):
    assert expiry.strike_step(_write_contracts(tmp_path, step=100)) == 100


def test_expiry_is_taken_from_the_field_not_the_symbol(tmp_path):
    path = _write_contracts(tmp_path)
    assert date(2026, 9, 8) in expiry.expiry_dates(path)


def test_an_old_cache_still_answers_expiry_but_not_mechanics(tmp_path):
    # Caches written before the loader kept contract fields hold symbol -> token only.
    path = _write_master(tmp_path)
    assert expiry.expiry_dates(path) == [
        date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]
    assert expiry.lot_size(path) is None
    assert expiry.tick_size(path) is None
    assert expiry.strike_step(path) is None


def test_round_to_tick_never_moves_against_the_trader(tmp_path):
    path = _write_contracts(tmp_path)
    # round(x, 2) produced these; none of them is a tradable price at a 0.05 tick.
    assert expiry.round_to_tick(123.47, "BUY", path) == 123.45     # pays less
    assert expiry.round_to_tick(123.47, "SELL", path) == 123.50    # receives more
    assert expiry.round_to_tick(98.13, "BUY", path) == 98.10
    assert expiry.round_to_tick(87.62, "SELL", path) == 87.65
    # An on-tick price is left exactly where it is, either way.
    assert expiry.round_to_tick(150.00, "BUY", path) == 150.00
    assert expiry.round_to_tick(149.75, "SELL", path) == 149.75


def test_round_to_tick_falls_back_to_two_decimals_without_a_master(tmp_path):
    absent = str(tmp_path / "nothing.json")
    assert expiry.round_to_tick(123.4567, "BUY", absent) == 123.46


def test_every_rounded_price_sits_on_the_grid(tmp_path):
    path = _write_contracts(tmp_path)
    tick = expiry.tick_size(path)
    for raw in (123.47, 98.13, 87.62, 150.004, 99.999, 0.07):
        for side in ("BUY", "SELL"):
            price = expiry.round_to_tick(raw, side, path)
            assert abs(price / tick - round(price / tick)) < 1e-6, (raw, side, price)


def test_the_validator_reports_a_lot_size_that_no_longer_matches(tmp_path, monkeypatch):
    from config.validator import ConfigValidator

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_contracts(tmp_path))
    v = ConfigValidator()
    v.warnings = []
    monkeypatch.setattr(v, "get_env_value",
                        lambda key, default='': {"LOT_SIZE": "75", "CE_QUANTITY": "65",
                                                 "PE_QUANTITY": "9000"}.get(key, default))
    v._validate_against_instrument_master()
    joined = " ".join(v.warnings)
    assert "LOT_SIZE=75" in joined and "65" in joined
    assert "freeze quantity" in joined


def test_the_validator_is_silent_when_config_and_exchange_agree(tmp_path, monkeypatch):
    from config.validator import ConfigValidator

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_contracts(tmp_path))
    v = ConfigValidator()
    v.warnings = []
    monkeypatch.setattr(v, "get_env_value",
                        lambda key, default='': {"LOT_SIZE": "65", "CE_QUANTITY": "65",
                                                 "PE_QUANTITY": "65"}.get(key, default))
    v._validate_against_instrument_master()
    assert v.warnings == []


def test_no_master_leaves_the_validator_quiet_rather_than_wrong(tmp_path, monkeypatch):
    from config.validator import ConfigValidator

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", str(tmp_path / "absent.json"))
    v = ConfigValidator()
    v.warnings = []
    monkeypatch.setattr(v, "get_env_value", lambda key, default='': "75")
    v._validate_against_instrument_master()
    assert v.warnings == []


def test_the_loader_writes_what_this_module_reads(tmp_path, monkeypatch):
    """The contract between broker.py and utils/instruments.py.

    _load_scrip_master() used to keep symbol -> token and drop the rest, so every figure
    below had to be restated as a constant somewhere. This pins the round trip: what the
    loader persists is exactly what the accessors can answer from.
    """
    from unittest.mock import MagicMock, patch
    import importlib

    broker = importlib.import_module("core.trading.broker")
    published = [
        {"exch_seg": "NFO", "name": "NIFTY", "symbol": "NIFTY08SEP2624500CE", "token": "1",
         "expiry": "08SEP2026", "strike": "2450000.000000", "lotsize": "65",
         "tick_size": "5.000000", "freeze_qty": "1801", "instrumenttype": "OPTIDX"},
        {"exch_seg": "NFO", "name": "NIFTY", "symbol": "NIFTY08SEP2624550PE", "token": "2",
         "expiry": "08SEP2026", "strike": "2455000.000000", "lotsize": "65",
         "tick_size": "5.000000", "freeze_qty": "1801", "instrumenttype": "OPTIDX"},
        {"exch_seg": "NSE", "name": "RELIANCE", "symbol": "RELIANCE-EQ", "token": "3"},
    ]

    cache = tmp_path / "cache.json"
    iface = broker.BrokerInterface.__new__(broker.BrokerInterface)
    iface.token_map, iface.contracts, iface.logger = {}, {}, MagicMock()
    response = MagicMock()
    response.json.return_value = published
    response.raise_for_status = lambda: None

    with patch.object(broker, "SCRIP_MASTER_CACHE_FILE", cache), \
         patch.object(broker.requests, "get", return_value=response):
        broker.BrokerInterface._load_scrip_master(iface)

    written = json.loads(cache.read_text(encoding="utf-8"))
    assert set(written) == {"saved_at", "token_map", "contracts"}
    assert len(written["contracts"]) == 2          # the equity row is not ours

    path = str(cache)
    assert expiry.lot_size(path) == 65
    assert expiry.tick_size(path) == 0.05
    assert expiry.freeze_quantity(path) == 1801
    assert expiry.strike_step(path) == 50
    assert expiry.expiry_dates(path) == [date(2026, 9, 8)]
