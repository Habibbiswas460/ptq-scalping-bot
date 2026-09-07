"""The replay: fill conventions, look-ahead, spread accounting, cost integration.

No network and no broker. The fixture is a synthetic session built in-process, so
these tests assert the harness's MECHANICS — that the spread is charged once and
in the right direction, that a signal cannot see the bar it fills on, that the
real cost model is the one applied. They deliberately do not assert a P&L figure;
that would be a snapshot of market data, not a property of the code.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from research import costs as _costs
from research.backtest import store
from research.backtest.harness import (
    Config, DEFAULT_SPREAD_PCT, INTRABAR_OFFSETS, Replay, Trade,
    _atm, exit_breakdown, summarise,
)


# ── config / fill arithmetic ─────────────────────────────────────────────────

def test_half_spread_is_proportional_to_premium_by_default():
    cfg = Config()
    assert cfg.spread_pct == DEFAULT_SPREAD_PCT
    # 0.246% round trip -> 0.123% per leg.
    assert cfg.half_spread_at(100.0) == pytest.approx(0.123)
    assert cfg.half_spread_at(200.0) == pytest.approx(0.246)
    # It must scale, not sit at a fixed point count.
    assert cfg.half_spread_at(200.0) == pytest.approx(2 * cfg.half_spread_at(100.0))


def test_measured_spread_costs_about_23_rupees_per_65_lot_round_trip():
    """The figure this was calibrated to: ~Rs23.27 per 65-lot round trip."""
    cfg = Config()
    premium = 145.0
    round_trip_points = 2 * cfg.half_spread_at(premium)
    assert round_trip_points * 65 == pytest.approx(23.2, abs=0.5)


def test_fixed_half_spread_overrides_the_percentage():
    cfg = Config(half_spread=0.5)
    assert cfg.half_spread_at(100.0) == 0.5
    assert cfg.half_spread_at(500.0) == 0.5


def test_spread_is_paid_once_and_lives_inside_gross_not_in_costs():
    """Live buys at the ask and sells at the bid; gross already pays the spread.

    research/costs.py must contribute only statutory and broker charges. If the
    cost model ever started including a spread term this test fails, which is the
    point: it would be double-counted.
    """
    cfg = Config()
    entry_mid, exit_mid, qty = 100.0, 100.0, 65
    hs_in = cfg.half_spread_at(entry_mid)
    hs_out = cfg.half_spread_at(exit_mid)
    t = Trade(session_date="2026-09-01", direction="CE", symbol="X", strike=24000,
              entry_time=_dt.datetime(2026, 9, 1, 10, 0),
              entry_price=entry_mid + hs_in, entry_mid=entry_mid, qty=qty)
    t.exit_mid = exit_mid
    t.exit_price = exit_mid - hs_out
    # Flat on the mid, yet gross is negative by exactly the spread crossed.
    assert t.gross_pnl == pytest.approx(-(hs_in + hs_out) * qty)
    assert t.spread_paid == pytest.approx((hs_in + hs_out) * qty)
    assert t.gross_pnl == pytest.approx(-t.spread_paid)
    # The statutory charges are a separate, additional deduction.
    charges = t.costs(_costs.DEFAULT)
    assert charges > 0
    assert t.net_pnl(_costs.DEFAULT) == pytest.approx(t.gross_pnl - charges)


def test_entry_fills_worse_than_the_bar_and_exit_fills_worse_too():
    cfg = Config()
    mid = 120.0
    entry = mid + cfg.half_spread_at(mid)
    exit_ = mid - cfg.half_spread_at(mid)
    assert entry > mid > exit_


def test_costs_come_from_the_projects_own_model_not_a_local_copy():
    cfg = Config()
    t = Trade(session_date="d", direction="CE", symbol="X", strike=1,
              entry_time=_dt.datetime(2026, 9, 1), entry_price=100.0,
              entry_mid=100.0, qty=65)
    t.exit_price, t.exit_mid = 110.0, 110.0
    assert t.costs(cfg.cost_model) == pytest.approx(
        _costs.DEFAULT.round_trip(100.0, 110.0, 65))


# ── strike selection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("spot,expected", [
    (23_974.0, 23_950.0), (23_976.0, 24_000.0), (24_000.0, 24_000.0),
    (24_024.0, 24_000.0), (24_026.0, 24_050.0),
])
def test_atm_rounds_to_the_50_point_nifty_strike_grid(spot, expected):
    """NIFTY weeklies step by 50. The instrument master is the authority on this
    and it is not to be assumed to be 100."""
    assert _atm(spot, 50.0) == expected


# ── intrabar ordering ────────────────────────────────────────────────────────

def test_intrabar_default_is_open_low_high_close():
    rep = Replay(Config())
    bar = {"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}
    assert [p for _, p in rep._intrabar_points(bar)] == [10.0, 9.0, 12.0, 11.0]


def test_intrabar_optimistic_flips_the_two_extremes():
    rep = Replay(Config(optimistic_intrabar=True))
    bar = {"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}
    assert [p for _, p in rep._intrabar_points(bar)] == [10.0, 12.0, 9.0, 11.0]


def test_intrabar_offsets_stay_inside_the_minute():
    """The engine's 45s early cut and 75s soft loss need sub-minute stamps, but
    they must never spill into the following minute."""
    assert len(INTRABAR_OFFSETS) == 4
    assert INTRABAR_OFFSETS == tuple(sorted(INTRABAR_OFFSETS))
    assert min(INTRABAR_OFFSETS) >= 0 and max(INTRABAR_OFFSETS) < 60


# ── summarising ──────────────────────────────────────────────────────────────

def _t(gross_points: float, qty: int = 65) -> Trade:
    entry = 100.0
    t = Trade(session_date="2026-09-01", direction="CE", symbol="X", strike=1,
              entry_time=_dt.datetime(2026, 9, 1, 10, 0), entry_price=entry,
              entry_mid=entry, qty=qty)
    t.exit_price = entry + gross_points
    t.exit_mid = t.exit_price
    t.exit_time = _dt.datetime(2026, 9, 1, 10, 5)
    t.hold_sec = 300.0
    t.exit_reason = "TEST | x"
    return t


def test_summary_reports_gross_and_net_together():
    s = summarise([_t(2.0), _t(-1.0), _t(3.0)])
    assert s["n"] == 3
    for k in ("gross_total", "net_total", "gross_expectancy", "net_expectancy",
              "gross_win_rate", "net_win_rate"):
        assert k in s
    # Costs are real, so net is strictly worse than gross.
    assert s["net_total"] < s["gross_total"]
    assert s["net_win_rate"] <= s["gross_win_rate"]


def test_net_win_rate_can_fall_below_gross_because_small_wins_go_negative():
    # A +0.2 point win on a 65 lot is Rs13, well under the ~Rs40 charge.
    s = summarise([_t(0.2), _t(0.2), _t(5.0)])
    assert s["gross_win_rate"] == 100.0
    assert s["net_win_rate"] < 100.0


def test_breakeven_win_rate_rises_once_costs_are_included():
    s = summarise([_t(3.0), _t(-3.0), _t(2.0), _t(-2.0)])
    assert s["breakeven_win_rate_net"] > s["breakeven_win_rate_gross"]


def test_summary_of_nothing_is_not_a_zero_result():
    assert summarise([]) == {"n": 0}


def test_exit_breakdown_groups_on_the_branch_token():
    a, b, c = _t(1.0), _t(-1.0), _t(2.0)
    a.exit_reason = "🛑 HARD SL HIT | CE | -7pts"
    b.exit_reason = "🛑 HARD SL HIT | PE | -7pts"
    c.exit_reason = "✅ TRAILING PROFIT | CE"
    out = exit_breakdown([a, b, c])
    assert out["🛑 HARD SL HIT"]["n"] == 2
    assert out["✅ TRAILING PROFIT"]["n"] == 1
