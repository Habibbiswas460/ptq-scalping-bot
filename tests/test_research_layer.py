"""Research layer: correctness of the derived definitions, and the look-ahead guards.

These charts are only worth reading if "a leg", "movement available", "transmission" and
"capture" mean the same thing every time. The numbers asserted here are the ones established
by hand during the 2026-09-03/04 forensics; a refactor that silently moves them fails.

The look-ahead tests are the important ones. A completed-candle artifact once produced a
p=0.0042 "finding" in this project that collapsed to p=0.54 when recomputed causally, so the
guard is structural and tested rather than documented.
"""
import datetime as dt

import pytest

from research import provenance as prov
from research.candles import as_of, atr, build, frame
from research.compare import delta, session_row
from research.db import Book
from research.entries import cascade, causal_features
from research.execution import modelled_cost, quote_quality
from research.ledger import FIELDS, load
from research.market import legs, max_move, movement_map, session_profile
from research.opportunities import excursions
from research.prefilters import classify, ladder_counts
from research.replay import Ladder, half_spread, replay, tick_rsi
from research.signals import component_stats
from research.transmission import regress

T0 = dt.datetime(2026, 9, 4, 10, 0, 0)


def ramp(n, step_sec, fn, start=T0):
    return [(start + dt.timedelta(seconds=i * step_sec), float(fn(i))) for i in range(n)]


# ── candles: aggregation and the as-of guard ──────────────────────────────
def test_ohlc_and_structure_fields():
    ser = [(T0, 100.0), (T0 + dt.timedelta(seconds=10), 105.0),
           (T0 + dt.timedelta(seconds=20), 98.0), (T0 + dt.timedelta(seconds=59), 101.0),
           (T0 + dt.timedelta(seconds=61), 110.0)]
    bars = build(ser, 60)
    assert len(bars) == 2
    b = bars[0]
    assert (b["o"], b["h"], b["l"], b["c"]) == (100.0, 105.0, 98.0, 101.0)
    assert b["range"] == 7.0 and b["body"] == 1.0
    assert b["upper_wick"] == pytest.approx(4.0)
    assert b["lower_wick"] == pytest.approx(2.0)
    assert b["dir"] == "UP"


def test_every_timeframe_derives_from_one_series():
    ser = ramp(600, 1, lambda i: 100 + (i % 7))
    f = frame(ser)
    assert set(f) == {"10s", "30s", "1m", "5m"}
    assert len(f["10s"]) > len(f["30s"]) > len(f["1m"]) > len(f["5m"])
    # the coarsest bar must span the same extremes as the ticks it came from
    assert max(b["h"] for b in f["5m"]) == max(p for _, p in ser)
    assert min(b["l"] for b in f["5m"]) == min(p for _, p in ser)


def test_partial_bar_excludes_post_entry_ticks():
    """The guard: the entry bar must contain nothing from after the entry second."""
    entry = T0 + dt.timedelta(seconds=20)
    ser = [(T0, 100.0), (T0 + dt.timedelta(seconds=10), 101.0),
           (entry, 102.0), (T0 + dt.timedelta(seconds=40), 80.0)]
    partial = build(ser, 60, upto=entry)[-1]
    assert partial["partial"] is True
    assert partial["l"] == 100.0, "post-entry low leaked into the as-of bar"
    assert partial["c"] == 102.0
    # and the completed bar DOES contain it — which is precisely why it must not be used
    assert build(ser, 60)[-1]["l"] == 80.0


def test_as_of_cannot_return_the_future():
    ser = ramp(30, 10, lambda i: i)
    t = T0 + dt.timedelta(seconds=100)
    got = as_of(ser, t)
    assert got and max(ts for ts, _ in got) <= t
    assert max(v for _, v in got) == 10.0


def test_causal_features_are_blind_to_what_follows():
    """Same pre-entry history, wildly different future: the features must be identical."""
    pre = ramp(60, 1, lambda i: 100 + i * 0.1)
    entry = pre[-1][0]
    up = pre + ramp(60, 1, lambda i: 200 + i, start=entry + dt.timedelta(seconds=1))
    down = pre + ramp(60, 1, lambda i: 10 - i, start=entry + dt.timedelta(seconds=1))
    a = causal_features(up, up, entry)
    b = causal_features(down, down, entry)
    assert a == b, "a causal feature changed when only post-entry data changed"


def test_atr_is_none_until_it_has_enough_bars():
    """A silent zero ATR is the defect that pinned the live early-cut to its tightest branch."""
    bars = build(ramp(300, 1, lambda i: 100 + (i % 5)), 10)
    a = atr(bars, period=14)
    assert a[0] is None and a[5] is None
    assert a[-1] is not None and a[-1] > 0


# ── market: legs and extremes ─────────────────────────────────────────────
def test_leg_needs_size_and_a_retrace():
    up = ramp(40, 10, lambda i: 100 + i)
    assert legs(up, 15.0) == [], "a leg must not be declared before it retraces"
    back = ramp(20, 10, lambda i: 139 - i, start=up[-1][0])
    out = legs(up + back, 15.0)
    assert len(out) == 1
    assert out[0]["dir"] == "UP" and out[0]["move"] == pytest.approx(39.0)
    assert out[0]["vel_ppm"] > 0


def test_max_move_finds_the_window_extreme():
    ser = [(T0, 100.0), (T0 + dt.timedelta(seconds=30), 130.0),
           (T0 + dt.timedelta(seconds=90), 90.0)]
    assert max_move(ser, 60)["up"] == pytest.approx(30.0)
    assert max_move(ser, 60)["down"] == pytest.approx(40.0)


def test_movement_map_reports_no_data_rather_than_zero():
    ser = ramp(20, 60, lambda i: 100 + i, start=dt.datetime(2026, 9, 4, 13, 0, 0))
    rows = {r["window"]: r for r in movement_map(ser)}
    assert rows["09:15-09:30"]["range"] is None, "an empty window must not read as zero range"
    assert rows["13:00-14:00"]["range"] is not None


# ── excursions and cascade ────────────────────────────────────────────────
def test_excursions_are_not_truncated_by_an_exit():
    opt = [(T0, 100.0), (T0 + dt.timedelta(seconds=10), 101.0),
           (T0 + dt.timedelta(seconds=120), 108.0)]
    ex = excursions(opt, T0, 100.0, horizons=(30, 180))
    assert ex["mfe_30"] == pytest.approx(1.0)
    assert ex["mfe_180"] == pytest.approx(8.0), "movement after a 30s exit must still count"


def test_pe_excursion_uses_the_trade_direction():
    spot = [(T0, 24000.0), (T0 + dt.timedelta(seconds=60), 23960.0)]
    ce = excursions(spot, T0, 24000.0, sign=1, horizons=(180,))
    pe = excursions(spot, T0, 24000.0, sign=-1, horizons=(180,))
    assert pe["mfe_180"] == pytest.approx(40.0), "a fall is favourable for PE"
    assert ce["mfe_180"] <= 0


def test_cascade_separates_transmission_from_capture():
    prof = {"id": 1, "side": "CE", "win": True, "captured": 1.49, "mfe_in_trade": 1.72,
            "after_spot": {"mfe_180": 12.10}, "after_option": {"mfe_180": 3.47}}
    c = cascade(prof, 180)
    assert c["transmission"] == pytest.approx(0.287, abs=0.001)
    assert c["capture_of_available"] == pytest.approx(0.429, abs=0.001)
    assert c["capture_of_mfe"] == pytest.approx(0.866, abs=0.001)


# ── replay ────────────────────────────────────────────────────────────────
def test_replay_fires_the_loss_rules_at_their_thresholds():
    opt = [(T0 + dt.timedelta(seconds=i), 100.0 - i * 0.5) for i in range(60)]
    r = replay(opt, T0, 100.0, "CE", Ladder())
    assert r["reason"] == "EARLY_CUT"
    assert r["hold"] <= 45


def test_replay_never_looks_before_the_entry():
    opt = [(T0 - dt.timedelta(seconds=30), 90.0), (T0, 100.0),
           (T0 + dt.timedelta(seconds=5), 100.5)]
    r = replay(opt, T0, 100.0, "CE", Ladder())
    assert r["exit_ltp"] >= 100.0, "a pre-entry tick was used as an exit"


def test_tick_rsi_matches_the_exit_path_not_the_spot_path():
    assert tick_rsi([1.0] * 10) is None, "needs 15 observations"
    rising = list(range(20))
    assert tick_rsi([float(x) for x in rising]) == 100.0


def test_half_spread_is_the_production_fallback():
    assert half_spread(120.0) == pytest.approx(0.18, abs=0.001)
    assert modelled_cost(120.0, 121.0)["round_trip_pts"] == pytest.approx(0.3615, abs=0.001)


# ── transmission ──────────────────────────────────────────────────────────
def test_regression_recovers_a_known_slope():
    spot = ramp(400, 1, lambda i: 24000 + i * 0.5)
    by_ts = {t: p for t, p in spot}
    opt = [(t, 100.0 + (p - 24000) * 0.4) for t, p in spot]
    r = regress(opt, by_ts, 30)
    assert r["beta"] == pytest.approx(0.4, abs=0.01)
    assert r["r2"] > 0.99


def test_regression_refuses_a_thin_sample():
    spot = ramp(5, 1, lambda i: 24000 + i)
    assert regress([(t, 100.0 + i) for i, (t, _) in enumerate(spot)],
                   {t: p for t, p in spot}, 10) is None


# ── provenance ────────────────────────────────────────────────────────────
def test_fabricated_and_missing_fields_are_labelled():
    # bid and oi were ESTIMATED / MISSING until 2026-09-07 13:28:53, when the mode-3
    # subscription was switched on mid-session and the same table began holding both. A single
    # state for either is now a false statement about a third of that day's rows, so they read
    # MIXED and the per-row answer comes from research.depth — see test_depth_instrument.py.
    assert prov.state("bid") == prov.MIXED
    assert prov.state("oi") == prov.MIXED
    assert prov.state("regime") == prov.MISSING
    assert prov.state("delta") == prov.RECONSTRUCTED
    assert prov.state("spot") == prov.REAL


def test_stored_mfe_is_flagged_exit_censored():
    assert "CENSORED" in prov.reason("mfe_stored").upper()


def test_unknown_field_defaults_to_missing_not_real():
    assert prov.state("some_field_nobody_registered") == prov.MISSING


# ── against the real database ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def book():
    return Book()


def test_sessions_are_discovered_not_hardcoded(book):
    ss = book.sessions()
    assert {s["kind"] for s in ss} <= {"tick", "coarse", "trades-only"}
    assert any(s["kind"] == "tick" for s in ss)


def test_prefilter_attribution_covers_the_unscored_rows(book):
    lc = ladder_counts(book, "2026-09-02")
    assert lc["scored"] + sum(lc["pre"].values()) == lc["total"], \
        "every evaluation must be attributed to scoring or to a named pre-filter"
    assert lc["pct_scored"] < 20, "09-02 is the session where the chop filter took almost all"


def test_classify_maps_reasons_to_gates():
    assert classify("Chop filter: EMA squeeze") == "Chop filter"
    assert classify("Low confidence 82% < 85%") == "Confidence gate"
    assert classify("something nobody has seen") == "other"


def test_score_components_report_constants(book):
    comps = component_stats(book, "2026-09-04")
    names = {c["component"] for c in comps}
    assert {"delta", "oi", "greeks"} <= names
    assert any(c["constant"] for c in comps), "the constant components must be detectable"


def test_quote_quality_detects_the_fabrication(book):
    q = quote_quality(book, "2026-09-04")
    assert q["midpoint_exact_pct"] >= 95
    assert "FABRICATED" in q["verdict"]


def test_ce_pe_coverage_gap_is_visible(book):
    ce = sum(n for _, n in book.option_symbols("2026-09-04", "CE"))
    pe = sum(n for _, n in book.option_symbols("2026-09-04", "PE"))
    assert ce > 0 and pe < ce / 10, "PE scarcity must stay visible, not be averaged away"


def test_session_row_and_delta_shape(book):
    a, b = session_row(book, "2026-09-03"), session_row(book, "2026-09-04")
    assert a["kind"] == "tick" and b["kind"] == "tick"
    d = {r["metric"]: r for r in delta(a, b)}
    assert "capture_ratio" in d and "midpoint_exact_pct" in d, \
        "before/after must carry data-health metrics beside outcome metrics"


def test_session_profile_matches_the_hand_forensics(book):
    spot, src = book.spot("2026-09-04")
    p = session_profile(spot, book.trades("2026-09-04"))
    assert src == "tick"
    # 107.80 is the true high-low across all 25,055 ticks of the session. The hand
    # forensics recorded 107.70 because Book.spot() silently dropped ~20% of ticks,
    # keeping the first of each same-second group and losing the extremes with them.
    assert p["range"] == pytest.approx(107.80, abs=0.01)
    assert p["legs_25"] == 11


# ── ledger ────────────────────────────────────────────────────────────────
def test_ledger_keeps_retractions():
    entries = load()
    assert entries, "the ledger must not be empty"
    assert all(set(e) <= set(FIELDS) for e in entries)
    assert any(e.get("retracted") for e in entries), \
        "an overturned finding must remain visible in the ledger"
    assert any(e.get("superseded_by") for e in entries)
