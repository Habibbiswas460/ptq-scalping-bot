"""Tests for core/historical/storage.py's monthly-partitioned SQLite store.

Uses pytest's tmp_path for an isolated store directory per test — never
touches data/historical/canonical.
"""

from core.historical.storage import HistoricalStore


def _row(ts, symbol="NIFTY14AUG2624000CE", ltp=100.0):
    return {
        "timestamp": ts, "instrument_type": "CE", "symbol": symbol,
        "expiry": "2026-08-14", "strike": 24000, "ltp": ltp, "bid": 99.5,
        "ask": 100.5, "volume": 100, "oi": 1000, "delta": 0.5, "gamma": 0.001,
        "theta": -5.0, "vega": 10.0, "iv": 15.0, "spot_ref": 24000.0,
    }


def test_write_and_query_roundtrip(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    rows = [_row("2026-08-14 09:15:00"), _row("2026-08-14 09:15:01")]
    store.write_rows(rows)

    result = list(store.query_range("2026-08-14", "2026-08-14"))
    assert len(result) == 2
    assert result[0]["timestamp"] == "2026-08-14 09:15:00"


def test_rows_partition_across_monthly_files(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    rows = [_row("2026-08-14 09:15:00"), _row("2026-09-01 09:15:00")]
    store.write_rows(rows)

    months = store.months_available()
    assert "2026-08" in months
    assert "2026-09" in months


def test_query_range_spans_multiple_months(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-31 09:15:00"), _row("2026-09-01 09:15:00")])

    result = list(store.query_range("2026-08-31", "2026-09-01"))
    assert len(result) == 2


def test_duplicate_timestamp_symbol_is_ignored_not_overwritten(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-14 09:15:00", ltp=100.0)])
    store.write_rows([_row("2026-08-14 09:15:00", ltp=999.0)])  # same (ts, symbol)

    result = list(store.query_range("2026-08-14", "2026-08-14"))
    assert len(result) == 1
    assert result[0]["ltp"] == 100.0  # first write wins, no silent overwrite


def test_query_range_filters_by_symbol(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([
        _row("2026-08-14 09:15:00", symbol="NIFTY14AUG2624000CE"),
        _row("2026-08-14 09:15:00", symbol="NIFTY14AUG2624000PE"),
    ])

    result = list(store.query_range("2026-08-14", "2026-08-14", symbols=["NIFTY14AUG2624000CE"]))
    assert len(result) == 1
    assert result[0]["symbol"] == "NIFTY14AUG2624000CE"


def test_coverage_dates(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-14 09:15:00"), _row("2026-08-17 09:15:00")])

    dates = store.coverage_dates()
    assert dates == ["2026-08-14", "2026-08-17"]


def test_row_count(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-14 09:15:00"), _row("2026-08-14 09:15:01")])
    assert store.row_count() == 2


def test_empty_store_has_no_months_or_coverage(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    assert store.months_available() == []
    assert store.coverage_dates() == []
    assert store.row_count() == 0
