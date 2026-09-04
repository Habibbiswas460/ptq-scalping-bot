"""Pin the research layer's derived definitions.

These charts are only worth reading if "a leg", "movement available" and "capture" mean the
same thing every time. The numbers asserted below are the ones established by hand during the
2026-09-03/04 forensics; a refactor that silently moves them fails here.
"""
import datetime as dt

import pytest

from research.data import (Book, as_of, candles, capture, legs, max_move, nearest_before,
                           parse_ts, available_move)
from research import provenance as prov


def _ramp(start, n, step_sec, fn):
    return [(start + dt.timedelta(seconds=i * step_sec), fn(i)) for i in range(n)]


# ── candles ───────────────────────────────────────────────────────────────
def test_candles_derive_ohlc_from_ticks():
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    ser = [(t0, 100.0), (t0 + dt.timedelta(seconds=10), 105.0),
           (t0 + dt.timedelta(seconds=20), 98.0), (t0 + dt.timedelta(seconds=59), 101.0),
           (t0 + dt.timedelta(seconds=61), 110.0)]
    bars = candles(ser, 60)
    assert len(bars) == 2
    assert (bars[0]["o"], bars[0]["h"], bars[0]["l"], bars[0]["c"]) == (100.0, 105.0, 98.0, 101.0)


def test_partial_bar_contains_no_post_entry_ticks():
    """The look-ahead guard: the entry bar must be built only from ticks up to the entry."""
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    entry = t0 + dt.timedelta(seconds=20)
    ser = [(t0, 100.0), (t0 + dt.timedelta(seconds=10), 101.0),
           (entry, 102.0), (t0 + dt.timedelta(seconds=40), 80.0)]
    bars = candles(ser, 60, upto=entry)
    assert bars[-1]["partial"] is True
    assert bars[-1]["l"] == 100.0, "the post-entry low must not appear in the entry bar"
    assert bars[-1]["c"] == 102.0
    # the completed bar, by contrast, does contain it — which is exactly why it must not be used
    assert candles(ser, 60)[-1]["l"] == 80.0


# ── legs ──────────────────────────────────────────────────────────────────
def test_leg_needs_both_size_and_retrace():
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    up = _ramp(t0, 40, 10, lambda i: 100.0 + i)          # +39, no retrace yet
    assert legs(up, 15.0) == []
    back = _ramp(up[-1][0], 20, 10, lambda i: 139.0 - i)  # retraces 19
    out = legs(up + back, 15.0)
    assert len(out) == 1
    assert out[0]["dir"] == "UP" and out[0]["move"] == pytest.approx(39.0)


def test_max_move_finds_the_window_extreme():
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    ser = [(t0, 100.0), (t0 + dt.timedelta(seconds=30), 130.0),
           (t0 + dt.timedelta(seconds=90), 90.0)]
    assert max_move(ser, 60)["up"] == pytest.approx(30.0)
    assert max_move(ser, 60)["down"] == pytest.approx(40.0)


# ── causality ─────────────────────────────────────────────────────────────
def test_as_of_cannot_return_the_future():
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    ser = _ramp(t0, 30, 10, lambda i: float(i))
    t = t0 + dt.timedelta(seconds=100)
    vals = as_of(ser, t, 60)
    assert max(vals) == 10.0
    assert all(v <= 10.0 for v in vals)


def test_nearest_before_never_looks_forward():
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    ser = [(t0, 5.0), (t0 + dt.timedelta(seconds=30), 9.0)]
    assert nearest_before(ser, t0 + dt.timedelta(seconds=10)) == 5.0


# ── capture ───────────────────────────────────────────────────────────────
def test_capture_splits_transmission_from_capture():
    tr = {"entry_time": "2026-09-04 10:00:00", "entry_price": 100.0, "exit_price": 101.49,
          "direction": "CE"}
    avail = {"sMFE_180": 12.10, "oMFE_180": 3.47}
    c = capture(tr, avail, 180)
    assert c["captured"] == pytest.approx(1.49)
    assert c["transmission"] == pytest.approx(0.287, abs=0.001)
    assert c["capture_ratio"] == pytest.approx(0.429, abs=0.001)


def test_available_move_is_not_truncated_by_the_exit():
    """The stored mfe column stops at the exit; this must not."""
    t0 = dt.datetime(2026, 9, 4, 10, 0, 0)
    opt = [(t0, 100.0), (t0 + dt.timedelta(seconds=10), 101.0),
           (t0 + dt.timedelta(seconds=120), 108.0)]
    spot = [(t0, 24000.0), (t0 + dt.timedelta(seconds=120), 24020.0)]
    tr = {"entry_time": "2026-09-04 10:00:00", "entry_price": 100.0, "direction": "CE"}
    av = available_move(opt, spot, tr, horizons_sec=(30, 180))
    assert av["oMFE_30"] == pytest.approx(1.0)
    assert av["oMFE_180"] == pytest.approx(8.0), "movement after a 30s exit must still count"


# ── provenance ────────────────────────────────────────────────────────────
def test_fabricated_and_missing_fields_are_labelled_as_such():
    assert prov.state("bid") == prov.ESTIMATED
    assert prov.state("ask") == prov.ESTIMATED
    assert prov.state("oi") == prov.MISSING
    assert prov.state("regime") == prov.MISSING
    assert prov.state("delta") == prov.RECONSTRUCTED
    assert prov.state("spot") == prov.REAL


def test_stored_mfe_is_flagged_as_exit_censored():
    assert "CENSORED" in prov.reason("mfe_stored").upper()


# ── session discovery ─────────────────────────────────────────────────────
def test_sessions_are_discovered_not_hardcoded():
    kinds = {s["kind"] for s in Book().sessions()}
    assert kinds <= {"tick", "coarse", "trades-only"}
    assert "tick" in kinds
