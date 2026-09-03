"""Unit tests for core/historical/quality_checks.py.

All rows here are synthetic TEST FIXTURES built to exercise one failure
mode at a time — none of this is real market data, and these fixtures are
never used as input to a strategy backtest.
"""

from core.historical.quality_checks import (
    check_bid_ask_validity,
    check_contract_identity,
    check_duplicate_ticks,
    check_expiry_strike_consistency,
    check_missing_ticks,
    check_option_chain_coverage,
    check_session_boundaries,
    check_spot_option_alignment,
    check_timestamp_integrity,
    run_all_checks,
)


def _opt_row(ts, symbol="NIFTY14AUG2624000CE", expiry="2026-08-14", strike=24000,
             itype="CE", ltp=100.0, bid=99.5, ask=100.9, spot_ref=24000.0):
    # NOTE: ask deliberately not symmetric around ltp — a midpoint-exact quote
    # is the signature of synthetic bid/ask and now trips check_quote_authenticity.
    return {
        "timestamp": ts, "instrument_type": itype, "symbol": symbol,
        "expiry": expiry, "strike": strike, "ltp": ltp, "bid": bid, "ask": ask,
        "volume": 100, "oi": 1000, "delta": 0.5, "gamma": 0.001, "theta": -5.0,
        "vega": 10.0, "iv": 15.0, "spot_ref": spot_ref,
    }


def _spot_row(ts, ltp=24000.0):
    return {
        "timestamp": ts, "instrument_type": "SPOT", "symbol": "NIFTY",
        "expiry": None, "strike": None, "ltp": ltp, "bid": None, "ask": None,
        "volume": None, "oi": None, "delta": None, "gamma": None, "theta": None,
        "vega": None, "iv": None, "spot_ref": ltp,
    }


def test_timestamp_integrity_passes_on_monotonic_rows():
    rows = [_opt_row("2026-08-14 09:15:00"), _opt_row("2026-08-14 09:15:01")]
    result = check_timestamp_integrity(rows)
    assert result.passed
    assert result.failed == 0


def test_timestamp_integrity_fails_on_out_of_order():
    rows = [_opt_row("2026-08-14 09:15:05"), _opt_row("2026-08-14 09:15:01")]
    result = check_timestamp_integrity(rows)
    assert not result.passed
    assert result.failed == 1


def test_duplicate_ticks_detected():
    rows = [_opt_row("2026-08-14 09:15:00"), _opt_row("2026-08-14 09:15:00")]
    result = check_duplicate_ticks(rows)
    assert not result.passed
    assert result.failed == 1


def test_duplicate_ticks_passes_when_unique():
    rows = [_opt_row("2026-08-14 09:15:00"), _opt_row("2026-08-14 09:15:01")]
    result = check_duplicate_ticks(rows)
    assert result.passed


def test_missing_ticks_flags_large_gap():
    rows = [_opt_row("2026-08-14 09:15:00"), _opt_row("2026-08-14 09:25:00")]
    result = check_missing_ticks(rows, max_gap_sec=5.0)
    assert not result.passed
    assert result.failed == 1


def test_missing_ticks_passes_within_tolerance():
    rows = [_opt_row("2026-08-14 09:15:00"), _opt_row("2026-08-14 09:15:03")]
    result = check_missing_ticks(rows, max_gap_sec=5.0)
    assert result.passed


def test_missing_ticks_ignores_cross_day_gap():
    """The overnight boundary must not count as an intraday gap. Each day
    carries real intraday pairs so the vacuous-pass guard (checked==0) isn't
    what's being exercised here."""
    rows = [
        _opt_row("2026-08-14 15:29:00"), _opt_row("2026-08-14 15:29:01"),
        _opt_row("2026-08-17 09:15:00"), _opt_row("2026-08-17 09:15:01"),
    ]
    result = check_missing_ticks(rows, max_gap_sec=5.0)
    assert result.passed  # cross-day boundary skipped, intraday pairs all fine
    assert result.checked == 2  # only the two same-day pairs were evaluated


def test_contract_identity_passes_on_matching_symbol():
    rows = [_opt_row("2026-08-14 09:15:00", symbol="NIFTY14AUG2624000CE", expiry="2026-08-14", strike=24000, itype="CE")]
    result = check_contract_identity(rows)
    assert result.passed


def test_contract_identity_fails_on_mismatched_symbol():
    rows = [_opt_row("2026-08-14 09:15:00", symbol="NIFTY14AUG2623000CE", expiry="2026-08-14", strike=24000, itype="CE")]
    result = check_contract_identity(rows)
    assert not result.passed
    assert result.failed == 1


def test_expiry_strike_consistency_fails_on_bad_strike_step():
    rows = [_opt_row("2026-08-14 09:15:00", strike=24013)]
    result = check_expiry_strike_consistency(rows)
    assert not result.passed


def test_expiry_strike_consistency_passes_on_valid_strike():
    rows = [_opt_row("2026-08-14 09:15:00", strike=24000)]
    result = check_expiry_strike_consistency(rows)
    assert result.passed


def test_bid_ask_validity_fails_when_bid_exceeds_ask():
    rows = [_opt_row("2026-08-14 09:15:00", bid=101.0, ask=100.0, ltp=100.5)]
    result = check_bid_ask_validity(rows)
    assert not result.passed


def test_bid_ask_validity_passes_on_sane_quote():
    rows = [_opt_row("2026-08-14 09:15:00", bid=99.5, ask=100.5, ltp=100.0)]
    result = check_bid_ask_validity(rows)
    assert result.passed


def test_bid_ask_validity_fails_on_missing_bid():
    rows = [_opt_row("2026-08-14 09:15:00", bid=None, ask=100.5, ltp=100.0)]
    result = check_bid_ask_validity(rows)
    assert not result.passed


def test_session_boundaries_fails_outside_market_hours():
    rows = [_opt_row("2026-08-14 20:00:00")]
    result = check_session_boundaries(rows)
    assert not result.passed


def test_session_boundaries_passes_within_market_hours():
    rows = [_opt_row("2026-08-14 10:00:00")]
    result = check_session_boundaries(rows)
    assert result.passed


def test_option_chain_coverage_fails_when_strikes_missing():
    # Only ATM strike present, band requires ATM+/-200 (5 strikes) on both sides.
    rows = [
        _spot_row("2026-08-14 09:15:00", ltp=24000.0),
        _opt_row("2026-08-14 09:15:00", symbol="NIFTY14AUG2624000CE", strike=24000, itype="CE"),
        _opt_row("2026-08-14 09:15:00", symbol="NIFTY14AUG2624000PE", strike=24000, itype="PE"),
    ]
    result = check_option_chain_coverage(rows, band_points=200)
    assert not result.passed


def test_option_chain_coverage_passes_with_full_band():
    rows = [_spot_row("2026-08-14 09:15:00", ltp=24000.0)]
    for strike in range(23800, 24201, 50):
        rows.append(_opt_row("2026-08-14 09:15:00", symbol=f"NIFTY14AUG26{strike}CE", strike=strike, itype="CE"))
        rows.append(_opt_row("2026-08-14 09:15:00", symbol=f"NIFTY14AUG26{strike}PE", strike=strike, itype="PE"))
    result = check_option_chain_coverage(rows, band_points=200)
    assert result.passed


def test_spot_option_alignment_fails_without_matching_spot_row():
    rows = [_opt_row("2026-08-14 09:15:00", spot_ref=24000.0)]  # no SPOT row at all
    result = check_spot_option_alignment(rows, tolerance_sec=1.0)
    assert not result.passed


def test_spot_option_alignment_passes_with_matching_spot_row():
    rows = [
        _spot_row("2026-08-14 09:15:00", ltp=24000.0),
        _opt_row("2026-08-14 09:15:00", spot_ref=24000.0),
    ]
    result = check_spot_option_alignment(rows, tolerance_sec=1.0)
    assert result.passed


def test_run_all_checks_aggregates_and_fails_on_any_failure():
    rows = [_opt_row("2026-08-14 09:15:00", bid=None)]  # missing bid -> bid_ask_validity fails
    report = run_all_checks(rows)
    assert not report.all_passed
    assert report.row_count == 1
    failing_names = {c.name for c in report.checks if not c.passed}
    assert "bid_ask_validity" in failing_names


def test_run_all_checks_passes_on_a_fully_clean_fixture():
    """A realistic clean fixture: 1-second spacing (satisfies the resolution
    check) and non-midpoint quotes (satisfies quote authenticity)."""
    import datetime
    base = datetime.datetime(2026, 8, 14, 9, 15, 0)
    rows = []
    for i in range(15):
        ts = (base + datetime.timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(_spot_row(ts, ltp=24000.0))
        for strike in range(23800, 24201, 50):
            ltp = 99.5 if i % 2 == 0 else 100.9  # prints at bid / at ask
            for itype in ("CE", "PE"):
                rows.append(_opt_row(ts, symbol=f"NIFTY14AUG26{strike}{itype}",
                                     strike=strike, itype=itype, ltp=ltp))
    report = run_all_checks(rows)
    assert report.all_passed, [c.name for c in report.checks if not c.passed]
