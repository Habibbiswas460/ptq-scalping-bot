"""Tests for core/historical/data_interface.py — the future real-data
backtest data source. These tests exist specifically to prove the
synthetic-data protection the plan required: mode is mandatory and
explicit, real mode never silently substitutes, synthetic mode never
activates by accident, and every result is provenance-stamped.
"""

import pytest

from core.historical.data_interface import (
    BacktestDataSource,
    InvalidDataModeError,
    RealDataMissingError,
)
from core.historical.storage import HistoricalStore


def _row(ts, symbol="NIFTY14AUG2624000CE", ltp=100.0):
    return {
        "timestamp": ts, "instrument_type": "CE", "symbol": symbol,
        "expiry": "2026-08-14", "strike": 24000, "ltp": ltp, "bid": 99.5,
        "ask": 100.5, "volume": 100, "oi": 1000, "delta": 0.5, "gamma": 0.001,
        "theta": -5.0, "vega": 10.0, "iv": 15.0, "spot_ref": 24000.0,
    }


def test_mode_is_mandatory_and_rejects_invalid_values(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    with pytest.raises(InvalidDataModeError):
        BacktestDataSource(store, mode="fast_and_loose")


def test_synthetic_mode_requires_explicit_resolver(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    with pytest.raises(InvalidDataModeError):
        BacktestDataSource(store, mode="synthetic")  # no synthetic_resolver given


def test_real_mode_resolves_existing_row_with_real_provenance(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-14 09:15:00")])
    source = BacktestDataSource(store, mode="real")

    tick = source.resolve_tick("2026-08-14 09:15:00", "NIFTY14AUG2624000CE")

    assert tick.ltp == 100.0
    assert tick.data_mode == "real"


def test_real_mode_raises_instead_of_substituting_when_missing(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    source = BacktestDataSource(store, mode="real")

    with pytest.raises(RealDataMissingError):
        source.resolve_tick("2026-08-14 09:15:00", "NIFTY14AUG2624000CE")


def test_synthetic_mode_only_activates_via_explicit_resolver(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))

    def fake_synthetic_resolver(timestamp, symbol):
        return {"ltp": 42.0, "bid": 41.5, "ask": 42.5}

    source = BacktestDataSource(store, mode="synthetic", synthetic_resolver=fake_synthetic_resolver)
    tick = source.resolve_tick("2026-08-14 09:15:00", "NIFTY14AUG2624000CE")

    assert tick.ltp == 42.0
    assert tick.data_mode == "synthetic"


def test_real_mode_never_calls_synthetic_resolver(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows([_row("2026-08-14 09:15:00")])

    calls = []

    def spy_resolver(timestamp, symbol):
        calls.append((timestamp, symbol))
        return {"ltp": 999.0}

    # mode='real' with a resolver passed anyway (e.g. caller reused config) —
    # the resolver must never be invoked in real mode.
    source = BacktestDataSource(store, mode="real", synthetic_resolver=spy_resolver)
    tick = source.resolve_tick("2026-08-14 09:15:00", "NIFTY14AUG2624000CE")

    assert tick.ltp == 100.0
    assert calls == []


def test_is_ready_delegates_to_gate(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    source = BacktestDataSource(store, mode="real")

    result = source.is_ready("2026-08-17", "2026-08-17")

    assert result.ready is False  # empty store
    assert "2026-08-17" in result.missing_dates
