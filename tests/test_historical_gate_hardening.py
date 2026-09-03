"""Regression tests for the Phase-1 gate hardening.

These exist because a real-data test (a genuine NSE EOD bhavcopy) exposed
three vacuous-pass defects that synthetic fixtures never caught: checks that
returned PASS while having evaluated zero rows, and a gate with no
resolution requirement at all. A fourth check was added after discovering
that this project's own persisted ticks carry synthetic bid/ask.

Every test here asserts the gate REFUSES data it must refuse. All fixtures
are synthetic test data, never real market data.
"""

import datetime

from core.historical.gate import check_backtest_ready
from core.historical.quality_checks import (
    check_missing_ticks,
    check_option_chain_coverage,
    check_quote_authenticity,
    check_resolution,
    run_all_checks,
)
from core.historical.storage import HistoricalStore


def _opt_row(ts, symbol, strike, itype="CE", ltp=100.0, bid=99.5, ask=100.9, spot_ref=24000.0):
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


def _second_series(base="2026-08-17 09:15:00", n=30, step_sec=1):
    base_dt = datetime.datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    return [(base_dt + datetime.timedelta(seconds=i * step_sec)).strftime("%Y-%m-%d %H:%M:%S")
            for i in range(n)]


def _realistic_day(date="2026-08-17", n=30, step_sec=1):
    """A clean intraday fixture: 1-second spacing, full ATM+/-200 chain,
    and NON-midpoint quotes (so it reads as authentic)."""
    stamps = _second_series(f"{date} 09:15:00", n=n, step_sec=step_sec)
    rows = []
    for i, ts in enumerate(stamps):
        rows.append(_spot_row(ts, ltp=24000.0))
        for strike in range(23800, 24201, 50):
            for itype in ("CE", "PE"):
                # ltp alternates toward bid/ask so it is not always the midpoint
                ltp = 100.0 if i % 2 == 0 else 100.8
                rows.append(_opt_row(ts, f"NIFTY20AUG26{strike}{itype}", strike, itype,
                                     ltp=ltp, bid=99.5, ask=100.9))
    return rows


# ---------------------------------------------------------------------------
# Defect 1: missing_ticks must not pass vacuously on EOD/daily data
# ---------------------------------------------------------------------------

def test_missing_ticks_fails_when_nothing_to_check():
    """EOD shape: one row per symbol per day -> no intraday pairs at all."""
    rows = [
        _opt_row("2026-08-17 15:30:00", "NIFTY20AUG2624000CE", 24000, "CE"),
        _opt_row("2026-08-18 15:30:00", "NIFTY20AUG2624000CE", 24000, "CE"),
    ]
    result = check_missing_ticks(rows)
    assert result.passed is False
    assert result.checked == 0
    assert "EOD" in " ".join(result.details) or "one row per day" in " ".join(result.details)


def test_missing_ticks_still_passes_on_real_intraday_shape():
    rows = [_opt_row(ts, "NIFTY20AUG2624000CE", 24000) for ts in _second_series(n=20)]
    result = check_missing_ticks(rows)
    assert result.passed is True
    assert result.checked > 0


# ---------------------------------------------------------------------------
# Defect 2: option_chain_coverage must not pass vacuously without spot data
# ---------------------------------------------------------------------------

def test_option_chain_coverage_fails_without_any_spot_reference():
    rows = [_opt_row(ts, "NIFTY20AUG2624000CE", 24000, spot_ref=None)
            for ts in _second_series(n=15)]
    result = check_option_chain_coverage(rows)
    assert result.passed is False
    assert result.checked == 0
    assert "no ATM reference" in " ".join(result.details) or "no SPOT rows" in " ".join(result.details)


# ---------------------------------------------------------------------------
# Defect 3: explicit resolution enforcement
# ---------------------------------------------------------------------------

def test_resolution_fails_on_one_minute_data():
    rows = [_opt_row(ts, "NIFTY20AUG2624000CE", 24000)
            for ts in _second_series(n=20, step_sec=60)]
    result = check_resolution(rows)
    assert result.passed is False
    assert "not 1-second resolution" in " ".join(result.details)


def test_resolution_passes_on_one_second_data():
    rows = [_opt_row(ts, "NIFTY20AUG2624000CE", 24000) for ts in _second_series(n=30)]
    result = check_resolution(rows)
    assert result.passed is True


def test_resolution_fails_on_too_few_rows_to_characterise():
    rows = [_opt_row(ts, "NIFTY20AUG2624000CE", 24000) for ts in _second_series(n=3)]
    result = check_resolution(rows)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Defect 4: synthetic (formula-derived) quote detection
# ---------------------------------------------------------------------------

def test_quote_authenticity_detects_synthetic_midpoint_quotes():
    """Reproduces this project's own collector bug shape: bid/ask built as
    ltp -/+ (ltp*0.003)/2, which puts ltp exactly at the midpoint every time."""
    rows = []
    for i, ts in enumerate(_second_series(n=150)):
        ltp = 100.0 + i * 0.05
        spread = ltp * 0.003
        rows.append(_opt_row(ts, "NIFTY20AUG2624000CE", 24000, ltp=round(ltp, 2),
                             bid=round(ltp - spread / 2, 2), ask=round(ltp + spread / 2, 2)))
    result = check_quote_authenticity(rows)
    assert result.passed is False
    assert "synthetic" in " ".join(result.details)


def test_quote_authenticity_passes_on_realistic_quotes():
    rows = []
    for i, ts in enumerate(_second_series(n=150)):
        # prints alternate at bid and ask, as real trades do
        ltp = 99.5 if i % 2 == 0 else 100.9
        rows.append(_opt_row(ts, "NIFTY20AUG2624000CE", 24000, ltp=ltp, bid=99.5, ask=100.9))
    result = check_quote_authenticity(rows)
    assert result.passed is True


# ---------------------------------------------------------------------------
# The point of it all: none of these may reach READY
# ---------------------------------------------------------------------------

def test_gate_refuses_eod_data(tmp_path):
    """The exact shape of the real NSE bhavcopy that previously scored
    PASS on missing_ticks and option_chain_coverage."""
    store = HistoricalStore(store_dir=str(tmp_path))
    rows = []
    for strike in range(23800, 24201, 50):
        for itype in ("CE", "PE"):
            rows.append({
                "timestamp": "2026-08-17 15:30:00", "instrument_type": itype,
                "symbol": f"NIFTY20AUG26{strike}{itype}", "expiry": "2026-08-20",
                "strike": strike, "ltp": 100.0, "bid": None, "ask": None,
                "volume": 500, "oi": 1000, "delta": None, "gamma": None,
                "theta": None, "vega": None, "iv": None, "spot_ref": None,
            })
    store.write_rows(rows)

    gate = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert gate.ready is False
    failing = {c.name for c in gate.failing_checks}
    assert "missing_ticks" in failing
    assert "option_chain_coverage" in failing
    assert "resolution" in failing


def test_gate_refuses_one_minute_data(tmp_path):
    """A 1-minute dataset with everything else valid must NOT be READY."""
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows(_realistic_day(n=20, step_sec=60))

    gate = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert gate.ready is False
    assert "resolution" in {c.name for c in gate.failing_checks}


def test_gate_refuses_synthetic_quotes(tmp_path):
    store = HistoricalStore(store_dir=str(tmp_path))
    rows = _realistic_day(n=30, step_sec=1)
    for r in rows:
        if r["instrument_type"] in ("CE", "PE"):
            spread = r["ltp"] * 0.003
            r["bid"] = round(r["ltp"] - spread / 2, 2)
            r["ask"] = round(r["ltp"] + spread / 2, 2)
    store.write_rows(rows)

    gate = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert gate.ready is False
    assert "quote_authenticity" in {c.name for c in gate.failing_checks}


def test_gate_still_ready_on_genuinely_valid_intraday_data(tmp_path):
    """The hardening must not make READY unreachable for good data."""
    store = HistoricalStore(store_dir=str(tmp_path))
    store.write_rows(_realistic_day(n=30, step_sec=1))

    gate = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert gate.ready is True, f"failing: {[(c.name, c.details[:1]) for c in gate.failing_checks]}"


def test_run_all_checks_includes_new_checks():
    report = run_all_checks(_realistic_day(n=15, step_sec=1))
    names = {c.name for c in report.checks}
    assert "resolution" in names
    assert "quote_authenticity" in names
