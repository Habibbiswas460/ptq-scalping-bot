"""Experiment-branch guard: the exit experiment flags must default to EXACTLY the frozen
baseline's behaviour, and must do what they claim when switched on.

Rationale: the baseline (8b7490e / tag baseline-pre-exit-experiment-20260904) is the
comparison point for every exit experiment. If a default ever drifts, every before/after
measurement silently becomes meaningless.
"""
import importlib
import pytest

import config.constants as C
from core.engines import exit_engine


def _reload(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(C)
    importlib.reload(exit_engine)
    return exit_engine


@pytest.fixture(autouse=True)
def _restore():
    yield
    importlib.reload(C)
    importlib.reload(exit_engine)


# ── defaults must reproduce the baseline ──────────────────────────────────
def test_defaults_are_production():
    assert C.EXIT_PROFIT_MODE == 'rsi'
    assert C.EXIT_LOSS_MODE == 'static'
    assert C.EXIT_REALISED_ATR_ENABLED is False
    assert C.EXIT_PROFIT_FLOOR_POINTS == C.RSI_REVERSAL_MIN_PROFIT_POINTS


def test_profit_floor_exit_is_noop_by_default():
    hit, reason = exit_engine.profit_floor_exit(
        {'price_diff': 50.0, 'direction': 'CE', 'current_pnl': 3250})
    assert hit is False and reason == ""


def test_static_threshold_matches_baseline_low_vol_path():
    # `atr` is never populated in production, so the baseline always used the low-vol value
    assert exit_engine._early_cut_threshold({}, {}) == float(C.EXIT_EARLY_CUT_ATR_LOW_POINTS)


def test_static_threshold_still_honours_atr_branch_when_atr_present():
    assert exit_engine._early_cut_threshold({}, {'atr': 7.0}) == float(C.EXIT_EARLY_CUT_ATR_HIGH_POINTS)
    assert exit_engine._early_cut_threshold({}, {'atr': 4.0}) == float(C.EXIT_EARLY_LOSS_CUT_POINTS)


# ── flags must actually work when enabled ─────────────────────────────────
def test_profit_floor_mode_fires_past_the_floor(monkeypatch):
    e = _reload(monkeypatch, EXIT_PROFIT_MODE='floor', EXIT_PROFIT_FLOOR_POINTS='1.0')
    assert e.profit_floor_exit({'price_diff': 0.99, 'direction': 'CE', 'current_pnl': 0})[0] is False
    hit, reason = e.profit_floor_exit({'price_diff': 1.01, 'direction': 'CE', 'current_pnl': 65})
    assert hit is True and 'PROFIT FLOOR' in reason


def test_atr_adaptive_mode_scales_and_clamps(monkeypatch):
    e = _reload(monkeypatch, EXIT_LOSS_MODE='atr_adaptive', EXIT_ATR_MULT='0.75',
                EXIT_ATR_FLOOR_POINTS='1.5', EXIT_ATR_CAP_POINTS='6.0')
    assert e._early_cut_threshold({}, {'atr': 4.0}) == 3.0      # 0.75 x 4.0
    assert e._early_cut_threshold({}, {'atr': 1.0}) == 1.5      # clamped up to the floor
    assert e._early_cut_threshold({}, {'atr': 20.0}) == 6.0     # clamped down to the cap
    # with no atr available it must fall back to the production branch, not a tighter stop
    assert e._early_cut_threshold({}, {}) == float(C.EXIT_EARLY_CUT_ATR_LOW_POINTS)


def test_mfe_aware_mode_tightens_only_for_trades_that_never_worked(monkeypatch):
    e = _reload(monkeypatch, EXIT_LOSS_MODE='mfe_aware', EXIT_MFE_ARM_POINTS='1.0',
                EXIT_MFE_TIGHT_POINTS='1.5', EXIT_MFE_ROOM_POINTS='4.0')
    assert e._early_cut_threshold({'qty': 65, 'mfe_inr': 0.0}, {}) == 1.5
    assert e._early_cut_threshold({'qty': 65, 'mfe_inr': 1.5 * 65}, {}) == 4.0


def test_realised_atr_is_off_by_default_and_computes_range_when_on():
    from core.engines import state_machine as sm
    ticks = [{'ltp': 100.0}, {'ltp': 103.5}, {'ltp': 99.0}, {'ltp': 101.0}, {'ltp': 102.0}]
    assert sm._realised_option_atr(ticks, 60) == 4.5
    assert sm._realised_option_atr([{'ltp': 100.0}], 60) == 0.0   # too few samples
    assert C.EXIT_REALISED_ATR_ENABLED is False                   # not live unless opted in
