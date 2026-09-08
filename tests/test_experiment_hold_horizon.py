"""Guards for the holding-horizon measurement.

The claim under test — that the bot loses because it holds for 47 seconds rather
than because its signal is wrong — turns entirely on two numbers being computed
honestly: the friction charged against an excursion, and the number of INDEPENDENT
observations behind a mean. Both have gone wrong in this project before (every
published P&L was gross until 2026-09-07; a p=0.0042 finding collapsed to p=0.54
when the look-ahead was removed), so both are pinned here.
"""
import datetime as dt

import pytest

from research import costs
from research.experiments import hold_horizon as H
from research.experiments.hold_policy import OFF_EARLY, OFF_SOFT, patched


# ── friction ─────────────────────────────────────────────────────────────────

def test_friction_reproduces_the_published_figures():
    """0.999 pts at Rs57.4 and 1.634 pts at Rs190.8, from strategy_sources §3.4."""
    assert H.friction_points(57.4) == pytest.approx(0.999, abs=0.002)
    assert H.friction_points(190.8) == pytest.approx(1.634, abs=0.002)


def test_friction_is_statutory_charges_plus_spread_charged_once():
    """costs.points() deliberately excludes the spread; exactly one spread is added.

    A candle is a mid, so a measurement taken from candles has not crossed the
    book and must pay it. The live bot's fills already have, which is why
    research/costs.py leaves it out — double-charging here would be the mirror of
    the error this project spent a session removing.
    """
    for p in (40.0, 145.55, 400.0):
        assert H.friction_points(p) == pytest.approx(
            costs.DEFAULT.points(p) + H.SPREAD_PCT_RT * p)


def test_friction_rises_with_premium_by_more_than_a_rounding():
    """The 0.884-point bar was set at one premium and is wrong at another.

    Deep-ITM friction is ~63% higher than ATM, so a term structure quoted against
    a single pooled friction number is wrong by up to 85%.
    """
    assert H.friction_points(190.8) / H.friction_points(57.4) > 1.6


def test_friction_of_a_worthless_option_is_zero_not_negative():
    assert H.friction_points(0.0) == 0.0
    assert H.friction_points(-5.0) == 0.0


# ── sampling: the overlap trap ───────────────────────────────────────────────

def _series(n=120, start=1_700_000_000):
    return H.Series(session_date="2026-09-01", symbol="X", kind="CE", strike=24000.0,
                    epochs=[start + 60 * i for i in range(n)],
                    open=[100.0 + i for i in range(n)],
                    high=[100.5 + i for i in range(n)],
                    low=[99.5 + i for i in range(n)],
                    close=[100.0 + i for i in range(n)])


def _spot(s):
    row = {"open": 24000.0, "high": 24000.0, "low": 24000.0, "close": 24000.0}
    return {s.session_date: {e: row for e in s.epochs}}


def test_default_stride_produces_windows_that_share_no_bar():
    """The stride is the whole point: at a 30-minute horizon a 1-minute grid
    reuses 29/30 of every path, and the resulting n is not a count of facts."""
    s = _series()
    got = H.collect([s], _spot(s), 30)
    idx = sorted(x.idx for x in got)
    assert idx, "no samples"
    assert all(b - a >= 30 for a, b in zip(idx, idx[1:]))


def test_stride_one_reproduces_the_overlapping_grid_and_inflates_n():
    s = _series()
    indep = H.collect([s], _spot(s), 30)
    grid = H.collect([s], _spot(s), 30, stride=1)
    assert len(grid) > 10 * len(indep)


def test_a_missing_minute_is_never_bridged():
    """store.py rule 1: a minute the source did not return is not filled in. A
    window straddling one is dropped, not silently stretched over a longer span."""
    s = _series(n=60)
    del s.epochs[30], s.open[30], s.high[30], s.low[30], s.close[30]
    assert not H._contiguous(s.epochs, 25, 10)
    assert H._contiguous(s.epochs, 0, 10)


def test_windows_may_not_run_past_the_live_force_close():
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    start = int(dt.datetime(2026, 9, 1, 15, 0, tzinfo=ist).timestamp())
    s = _series(n=40, start=start)
    got = H.collect([s], _spot(s), 10)
    for x in got:
        end = dt.datetime.fromtimestamp(x.entry_epoch + 60 * 9, ist)
        assert end.time() <= H.LAST_ENTRY_CLOSE


def test_mfe_and_mae_are_forward_only():
    """A window starting at bar j must not see bar j-1, which is where a
    completed-candle artifact would enter."""
    s = _series(n=20)
    s.high[0] = 10_000.0          # a spike strictly before the sampled window
    got = H.collect([s], _spot(s), 5)
    first = [x for x in got if x.idx == 0]
    later = [x for x in got if x.idx > 0]
    assert later and all(x.mfe < 100 for x in later)
    assert first and first[0].mfe > 9_000     # the spike is inside ITS own window


# ── first touch ──────────────────────────────────────────────────────────────

def test_barrier_takes_the_target_when_only_the_target_is_reachable():
    s = _series(n=20)          # rises 1 point a minute, never falls
    r = H.barrier_outcomes([s], _spot(s), 10, target=5.0, stop=5.0)
    assert r["wins"] == r["n"] and r["losses"] == 0
    # Two non-overlapping windows, opening at Rs100 and Rs110 — each pays its own
    # friction, which is the behaviour being pinned.
    expected = 5.0 - (H.friction_points(100.0) + H.friction_points(110.0)) / 2
    assert r["net_expectancy_pts"] == pytest.approx(expected, abs=0.001)


def test_intrabar_order_decides_a_bar_that_touches_both_barriers():
    """A 1-minute bar says the high and the low both happened, not in what order.
    The two orderings must give different answers, or the ambiguity is being
    hidden rather than reported."""
    s = _series(n=10)
    s.high[1] = s.open[0] + 20.0
    s.low[1] = s.open[0] - 20.0
    adverse = H.barrier_outcomes([s], _spot(s), 5, 5.0, 5.0, adverse_first=True)
    favour = H.barrier_outcomes([s], _spot(s), 5, 5.0, 5.0, adverse_first=False)
    assert adverse["losses"] == 1 and favour["wins"] == 1


def test_barrier_charges_the_sample_premium_not_a_pooled_mean():
    cheap = _series(n=20)
    rich = _series(n=20)
    rich.open = [400.0 + i for i in range(20)]
    rich.high = [400.5 + i for i in range(20)]
    rich.low = [399.5 + i for i in range(20)]
    rich.close = [400.0 + i for i in range(20)]
    a = H.barrier_outcomes([cheap], _spot(cheap), 10, 5.0, 5.0)
    b = H.barrier_outcomes([rich], _spot(rich), 10, 5.0, 5.0)
    assert b["net_expectancy_pts"] < a["net_expectancy_pts"] - 0.4


# ── the policy patch ─────────────────────────────────────────────────────────

def test_the_off_sentinels_actually_switch_the_branch_off():
    """`hold_time > EARLY_LOSS_CUT_TIME_SEC` is already true at hold_time 0 only
    if the limit is negative — 0 would leave the branch live on the first
    evaluation, which is exactly when it fires."""
    from core.engines import exit_engine as ee
    entry = dt.datetime(2026, 9, 1, 10, 0)
    trade = {"entry_time": entry, "price_diff": -50.0, "qty": 65, "direction": "CE"}
    ee._clock_override = entry
    try:
        with patched({"EARLY_LOSS_CUT_TIME_SEC": OFF_EARLY}):
            assert ee.early_momentum_loss_cut(trade, {})[0] is False
        with patched({"SOFT_LOSS_TIME_SEC": OFF_SOFT}):
            assert ee.soft_loss_time_exit(trade)[0] is False
        assert ee.early_momentum_loss_cut(trade, {})[0] is True
    finally:
        ee._clock_override = None


def test_patch_restores_every_attribute_it_touched():
    from core.engines import exit_engine as ee
    before = {k: getattr(ee, k) for k in
              ("EARLY_LOSS_CUT_TIME_SEC", "SOFT_LOSS_TIME_SEC",
               "MAX_HOLD_TIME_WINNING", "TRAILING_ENABLED")}
    with patched({k: 0 for k in before}):
        pass
    assert {k: getattr(ee, k) for k in before} == before


def test_patching_an_unknown_name_raises_rather_than_doing_nothing_quietly():
    with pytest.raises(AttributeError):
        with patched({"NO_SUCH_EXIT_KNOB": 1}):
            pass
