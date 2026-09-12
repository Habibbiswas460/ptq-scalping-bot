"""core/market_data/tick_store.py: monthly-partitioned raw-tick + 5-min-candle storage."""

from core.market_data.tick_store import TickStore


def _tick(token, ts_ms, ltp, **extra):
    row = {
        "source_broker": "angel_one", "token": token, "exchange": "NFO", "symbol": "NIFTYTEST",
        "mode": 3, "sequence": None, "timestamp_ms": ts_ms, "ltp": ltp, "volume": None,
        "open": None, "high": None, "low": None, "close": None, "oi": None,
        "best_bid_price": None, "best_ask_price": None, "best_bid_qty": None, "best_ask_qty": None,
    }
    row.update(extra)
    return row


def _candle(token, bucket_ms, **extra):
    row = {
        "token": token, "bucket_start_ms": bucket_ms,
        "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
        "volume": 0, "tick_count": 1,
    }
    row.update(extra)
    return row


def test_write_and_query_ticks_round_trip(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    ts = 1_757_000_000_000  # some fixed epoch ms
    store.write_ticks([_tick("T1", ts, 100.5), _tick("T1", ts + 60_000, 101.0)])

    rows = list(store.query_ticks("T1", ts - 1, ts + 120_000))
    assert [r["ltp"] for r in rows] == [100.5, 101.0]


def test_duplicate_tick_is_ignored_not_overwritten(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    ts = 1_757_000_000_000
    store.write_ticks([_tick("T1", ts, 100.0, sequence=1)])
    store.write_ticks([_tick("T1", ts, 999.0, sequence=1)])  # same (token, ts, sequence)

    rows = list(store.query_ticks("T1", ts - 1, ts + 1))
    assert len(rows) == 1
    assert rows[0]["ltp"] == 100.0  # first write wins, not the second


def test_ticks_with_no_timestamp_are_skipped(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    written = store.write_ticks([{"token": "T1", "ltp": 100.0}])  # no timestamp_ms
    assert written == 0


def test_query_ticks_is_scoped_to_the_requested_token(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    ts = 1_757_000_000_000
    store.write_ticks([_tick("T1", ts, 100.0), _tick("T2", ts, 200.0)])

    rows = list(store.query_ticks("T1", ts - 1, ts + 1))
    assert len(rows) == 1 and rows[0]["token"] == "T1"


def test_write_and_query_candles_round_trip(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    bucket = 1_757_000_000_000
    store.write_candles([_candle("T1", bucket, close=105.0)])

    rows = list(store.query_candles("T1", bucket - 1, bucket + 1))
    assert len(rows) == 1
    assert rows[0]["close"] == 105.0


def test_rewriting_a_candle_for_the_same_bucket_replaces_it(tmp_path):
    """Unlike ticks, an in-progress bucket's candle is expected to be resubmitted as
    later ticks extend it — the latest write for a bucket must win."""
    store = TickStore(store_dir=str(tmp_path))
    bucket = 1_757_000_000_000
    store.write_candles([_candle("T1", bucket, close=100.0, tick_count=1)])
    store.write_candles([_candle("T1", bucket, close=110.0, tick_count=5)])

    rows = list(store.query_candles("T1", bucket - 1, bucket + 1))
    assert len(rows) == 1
    assert rows[0]["close"] == 110.0
    assert rows[0]["tick_count"] == 5


def test_ticks_land_in_the_correct_monthly_file(tmp_path):
    store = TickStore(store_dir=str(tmp_path))
    # 2026-01-15 and 2026-02-15 in epoch ms (UTC)
    jan_ts = 1768435200000
    feb_ts = 1771113600000
    store.write_ticks([_tick("T1", jan_ts, 1.0), _tick("T1", feb_ts, 2.0)])

    months = store.months_available()
    assert "2026-01" in months and "2026-02" in months


def test_months_available_is_empty_for_a_fresh_store_dir(tmp_path):
    store = TickStore(store_dir=str(tmp_path / "does_not_exist_yet"))
    assert store.months_available() == []
