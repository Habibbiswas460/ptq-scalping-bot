"""Tests for core/historical/gate.py's hard BACKTEST READY/NOT READY gate.

Every fixture here is synthetic test data built to exercise the gate's
logic — not real market data, and never used to run a strategy backtest.
2026-08-17 is used as the single-day range because it is a real Monday
(confirmed via `date -d 2026-08-17`), so the gate's weekday-coverage check
has exactly one required date to satisfy.
"""

from core.historical.gate import check_backtest_ready
from core.historical.storage import HistoricalStore


def _opt_row(ts, symbol, strike, itype, bid=99.5, ask=100.9, ltp=100.0, spot_ref=24000.0):
    # ask deliberately not symmetric around ltp: midpoint-exact quotes are the
    # signature of synthetic bid/ask and now trip check_quote_authenticity.
    return {
        "timestamp": ts, "instrument_type": itype, "symbol": symbol,
        "expiry": "2026-08-20", "strike": strike, "ltp": ltp, "bid": bid,
        "ask": ask, "volume": 100, "oi": 1000, "delta": 0.5, "gamma": 0.001,
        "theta": -5.0, "vega": 10.0, "iv": 15.0, "spot_ref": spot_ref,
    }


def _spot_row(ts, ltp=24000.0):
    return {
        "timestamp": ts, "instrument_type": "SPOT", "symbol": "NIFTY",
        "expiry": None, "strike": None, "ltp": ltp, "bid": None, "ask": None,
        "volume": None, "oi": None, "delta": None, "gamma": None, "theta": None,
        "vega": None, "iv": None, "spot_ref": ltp,
    }


def _full_clean_day(date="2026-08-17", n=15):
    """Realistic clean intraday fixture: 1-second spacing across the full
    ATM+/-200 chain, with prints alternating at bid/ask rather than sitting
    exactly at the midpoint."""
    import datetime
    base = datetime.datetime.strptime(f"{date} 09:15:00", "%Y-%m-%d %H:%M:%S")
    rows = []
    for i in range(n):
        ts = (base + datetime.timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(_spot_row(ts, ltp=24000.0))
        ltp = 99.5 if i % 2 == 0 else 100.9
        for strike in range(23800, 24201, 50):
            rows.append(_opt_row(ts, f"NIFTY20AUG26{strike}CE", strike, "CE", ltp=ltp))
            rows.append(_opt_row(ts, f"NIFTY20AUG26{strike}PE", strike, "PE", ltp=ltp))
    return rows


def test_gate_not_ready_on_empty_store(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    result = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert result.ready is False
    assert "2026-08-17" in result.missing_dates


def test_gate_ready_on_a_fully_clean_single_day(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows(_full_clean_day("2026-08-17"))

    result = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert result.ready is True
    assert result.missing_dates == []
    assert all(c.passed for c in result.checks)


def test_gate_not_ready_when_a_required_weekday_has_no_data(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows(_full_clean_day("2026-08-17"))  # Monday populated
    # 2026-08-18 (Tuesday) requested but never written

    result = check_backtest_ready(store, "2026-08-17", "2026-08-18")
    assert result.ready is False
    assert "2026-08-18" in result.missing_dates


def test_gate_not_ready_when_bid_ask_invalid(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    rows = _full_clean_day("2026-08-17")
    rows[1]["bid"] = None  # corrupt one option row's bid
    store.write_rows(rows)

    result = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert result.ready is False
    failing_names = {c.name for c in result.failing_checks}
    assert "bid_ask_validity" in failing_names


def test_gate_not_ready_on_incomplete_option_chain_coverage(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    # Only ATM strike present, not the full +/-200 band.
    rows = [
        _spot_row("2026-08-17 09:15:00", ltp=24000.0),
        _opt_row("2026-08-17 09:15:00", "NIFTY20AUG2624000CE", 24000, "CE"),
        _opt_row("2026-08-17 09:15:00", "NIFTY20AUG2624000PE", 24000, "PE"),
    ]
    store.write_rows(rows)

    result = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert result.ready is False
    failing_names = {c.name for c in result.failing_checks}
    assert "option_chain_coverage" in failing_names


def test_gate_result_reports_holiday_calendar_caveat(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    result = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert "holiday" in result.holiday_calendar_caveat.lower()
