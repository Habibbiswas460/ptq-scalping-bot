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
