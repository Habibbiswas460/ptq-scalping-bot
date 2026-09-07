"""The order-book / open-interest instrument.

What is pinned here is mostly one thing: that "this quote is not the fallback formula" is never
allowed to mean "this quote is real". The first version of `quote_origin()` made exactly that
inference and reported a real order book on three sessions that predate the parser capable of
producing one.
"""
import datetime as _dt

import pytest

from research import depth, provenance as prov


# ── the fallback formula ──────────────────────────────────────────────────────────────────

def test_the_fallback_quote_is_recognised():
    """broker.py: spread = max(0.05, ltp*0.003), bid/ask = ltp -/+ half, rounded to 2dp."""
    bid, ask = depth._estimated_pair(120.0)
    assert (bid, ask) == (119.82, 120.18)
    assert depth.quote_origin(120.0, bid, ask) == depth.ESTIMATE


def test_the_five_paisa_floor_is_part_of_the_formula():
    """Below ltp 16.67 a plain 0.3% is finer than a tick, so the fallback floors the spread at
    0.05. Ignoring the floor would classify every cheap option's fallback quote as a real book.

    The stored pair is 9.97/10.03 — 0.06 wide, not 0.05, because each side is rounded to 2dp
    away from the midpoint. That widening is the fallback's, not the market's, which is exactly
    why the classifier reproduces the formula instead of testing the spread's width."""
    assert depth._estimated_pair(10.0) == (9.97, 10.03)
    assert depth.quote_origin(10.0, 9.97, 10.03) == depth.ESTIMATE


def test_float_slack_at_the_stored_precision():
    """69.89 against 69.90 differs by 0.010000000000005 in binary floating point. A tolerance
    of exactly 0.01 misses it and calls a fabricated quote real — which it did."""
    assert depth.quote_origin(70.0, 69.89, 70.11) == depth.ESTIMATE


# ── the rule that matters ─────────────────────────────────────────────────────────────────

def test_not_the_formula_is_not_the_same_as_real():
    """A quote that matches nothing known, with no open interest to corroborate it, is
    UNRECOGNISED. On 2026-09-02/03/04 there are 4-5 such rows and the best-5 parser did not
    exist yet, so calling them a market quote would be a fabrication of the instrument's own."""
    assert depth.quote_origin(151.85, 151.77, 151.93, has_oi=False) == depth.UNRECOGNISED


def test_open_interest_corroborates_a_real_book():
    """Real quotes and OI ride the same mode-3 packet: 8,433 of 8,441 non-fallback rows on
    2026-09-07 carry OI, against 0 of 14 across the three earlier sessions."""
    assert depth.quote_origin(151.85, 151.77, 151.93, has_oi=True) == depth.BOOK


def test_a_missing_or_crossed_quote_is_absent_not_estimated():
    assert depth.quote_origin(120.0, None, None) == depth.ABSENT
    assert depth.quote_origin(120.0, 0, 0) == depth.ABSENT
    assert depth.quote_origin(120.0, 121.0, 119.0) == depth.ABSENT      # crossed
    assert depth.quote_origin(0, 1.0, 2.0) == depth.ABSENT


def test_open_interest_presence_treats_zero_as_absent():
    """Before the fix the column was NULL; with the flag on but mode 2 it was written as 0.
    Neither is an observation."""
    assert depth.has_open_interest(None) is False
    assert depth.has_open_interest(0) is False
    assert depth.has_open_interest(12345) is True


# ── spread, never pooled ──────────────────────────────────────────────────────────────────

class _FakeBook:
    """Minimal stand-in for research.db.Book — the instrument only calls two methods."""

    def __init__(self, rows):
        self._rows = rows

    def option_symbols(self, day):
        return [("NIFTY24500CE", len(self._rows))]

    def option_quotes(self, symbol, day):
        return self._rows


def _row(t, ltp, bid, ask, oi=None):
    return {"t": _dt.datetime(2026, 9, 7, 10, 0, t), "ltp": ltp, "bid": bid, "ask": ask,
            "volume": 0, "oi": oi}


def _mixed_book():
    est_bid, est_ask = depth._estimated_pair(120.0)
    return _FakeBook([
        _row(1, 120.0, est_bid, est_ask),                 # fabricated
        _row(2, 120.0, 119.95, 120.05, oi=5_000),         # real book, corroborated
        _row(3, 120.0, 119.90, 120.10, oi=5_100),         # real book
        _row(4, 151.85, 151.77, 151.93),                  # unrecognised
    ])


def test_a_real_spread_is_never_pooled_with_a_fabricated_one():
    profile = depth.spread_profile(_mixed_book(), "2026-09-07")

    assert profile.real_stats()["n"] == 2
    assert profile.estimated_stats()["n"] == 1
    assert profile.real_stats()["p50"] == pytest.approx(0.15)
    # the unrecognised row lands in neither distribution
    assert len(profile.real) + len(profile.estimated) == 3


def test_crossing_cost_is_unknown_rather_than_fabricated():
    """A session with no real book must not answer this question with the estimate — that is
    the mistake that put a fabricated spread into the cost of a trade."""
    est_bid, est_ask = depth._estimated_pair(120.0)
    only_estimates = _FakeBook([_row(1, 120.0, est_bid, est_ask)])

    assert depth.spread_profile(only_estimates, "2026-09-04").crossing_cost_points() is None
    assert depth.spread_profile(_mixed_book(), "2026-09-07").crossing_cost_points() == 0.075


# ── coverage ──────────────────────────────────────────────────────────────────────────────

def test_coverage_counts_every_origin_and_flags_a_mixed_session():
    cov = depth.coverage(_mixed_book(), "2026-09-07")

    assert (cov.rows, cov.book, cov.estimate, cov.unrecognised) == (4, 2, 1, 0 + 1)
    assert cov.with_oi == 2
    assert cov.mixed is True
    assert "MIXED" in cov.summary()
    assert cov.first_book_at.second == 2


def test_an_estimate_only_session_is_not_called_mixed():
    est_bid, est_ask = depth._estimated_pair(120.0)
    cov = depth.coverage(_FakeBook([_row(1, 120.0, est_bid, est_ask)]), "2026-09-04")

    assert cov.mixed is False
    assert cov.book_pct == 0.0
    assert "estimate only" in cov.summary()


# ── open interest, observed not enforced ──────────────────────────────────────────────────

def test_the_buildup_label_mirrors_the_live_rule():
    """SmartScalpV3.update_oi_data(): +/-1% band, then price direction picks the side."""
    assert depth.classify_buildup(2.0, price_up=True) == depth.LONG_BUILDUP
    assert depth.classify_buildup(2.0, price_up=False) == depth.SHORT_BUILDUP
    assert depth.classify_buildup(-2.0, price_up=True) == depth.SHORT_COVERING
    assert depth.classify_buildup(-2.0, price_up=False) == depth.LONG_UNWINDING
    assert depth.classify_buildup(0.5, price_up=True) == depth.NEUTRAL
    assert depth.classify_buildup(1.0, price_up=True) == depth.NEUTRAL, "the band is exclusive"


def test_a_constant_label_is_reported_as_carrying_no_information():
    flat = _FakeBook([_row(t, 120.0, 119.95, 120.05, oi=5_000) for t in range(1, 5)])

    profile = depth.oi_profile(flat, "2026-09-07")

    assert profile.rows_with_oi == 4
    assert profile.steps == 0
    assert profile.discriminates is False


def test_rows_without_open_interest_are_not_invented_into_the_series():
    profile = depth.oi_profile(_mixed_book(), "2026-09-07")
    assert profile.rows_with_oi == 2
    assert profile.distinct_values == 2


# ── the instrument's contract with the rest of the research layer ─────────────────────────

def test_provenance_no_longer_claims_one_state_for_a_mixed_field():
    """A field-level answer is a false statement about a session that holds both."""
    for field in ("bid", "ask", "spread", "oi"):
        assert prov.state(field) == prov.MIXED, field
        assert prov.reason(field), f"{field} carries no explanation"
    # and the registry says where the per-row answer lives, so a reader is not left guessing
    assert "research.depth" in prov.__doc__


def test_the_mixed_state_can_be_rendered():
    label, state = prov.chip("bid")
    assert state == prov.MIXED and "MIXED" in label

    from research import render
    assert "c-mixed" in str(render.chip("bid"))
    assert ".c-mixed{" in render.CSS if hasattr(render, "CSS") else True


def test_the_instrument_never_writes_to_the_trading_database():
    """Every statement this module issues goes through research.db.Book, which is read-only."""
    import inspect
    source = inspect.getsource(depth)
    for forbidden in ("INSERT", "UPDATE ", "DELETE", "DROP", "CREATE TABLE", "commit("):
        assert forbidden not in source, f"{forbidden} in a read-only instrument"


# ── the rule the instrument broke on itself ───────────────────────────────────────────────

def test_a_session_with_no_ticks_is_not_described_as_fabricated():
    """20 of the 24 recorded sessions carry trades but no tick rows. Reporting those as
    "estimated quotes throughout" states something about data that does not exist — the exact
    fabrication this module forbids everywhere else. The first draft did it for all 20."""
    empty = _FakeBook([])
    report = depth.session_report(empty, "2026-07-07")

    assert "no option ticks recorded" in str(report["provenance_note"])
    assert report["crossing_cost_points"] is None
    text = depth.render_text(report)
    assert "estimated" not in text.lower()
    assert "crossing cost" not in text.lower(), "no claim may be made about absent data"


def test_the_live_oi_window_default_is_measured_not_assumed():
    """OI_CHANGE_WINDOW_SEC=0 compares tick to tick. The broker republishes OI in steps, so
    across 2026-09-07's 8,516 real-OI rows that default lands 99.6% NEUTRAL — the component
    carries almost nothing — while a 60s window separates the same series into five labels.
    This pins the mechanism, not the session: a flat series under a tight window and a varying
    one under a wide window."""
    rows = []
    for i in range(1, 21):
        # OI creeps by one step every 10 rows; price alternates.
        oi = 100_000 + (i // 10) * 5_000
        rows.append(_row(i, 120.0 + (i % 2), 119.95, 120.05, oi=oi))
    book = _FakeBook(rows)

    tick_to_tick = depth.oi_profile(book, "2026-09-07", window_sec=0)
    windowed = depth.oi_profile(book, "2026-09-07", window_sec=12)

    assert tick_to_tick.labels.get(depth.NEUTRAL, 0) > windowed.labels.get(depth.NEUTRAL, 0)
