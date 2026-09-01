"""
Regression tests: consecutive-loss pause has a single source of truth.

Guards against reintroducing the double-pause bug fixed in fixed.md §14.7 —
state_machine.check_trade_limits() used to run its own independent
pause/reset clock (state.consecutive_loss_pause_until) in parallel with
RiskManager.check_streak_limits(). Because the two clocks were unsynced,
every consecutive-loss trigger paused trading for roughly twice the
configured duration: state_machine's pause would clear and let a signal
through, at which point RiskManager's own stale, untouched counter would
immediately impose a second, independent pause.

The fix removed state_machine's clock entirely and made it delegate purely
to RiskManager.check_streak_limits() — the same function can_trade() already
calls. These tests protect that invariant.
"""
from datetime import datetime, timedelta

import pytest

import core.risk.risk_manager as risk_manager_module
from core.engines.state_machine import TradingState, check_trade_limits
from core.risk.risk_manager import RiskManager, set_risk_manager


@pytest.fixture(autouse=True)
def _reset_risk_manager_singleton(monkeypatch):
    """set_risk_manager() below writes the real module-level singleton with
    no built-in restore — reset it after each test so these tests can't leak
    a RiskManager instance into whatever test runs next."""
    monkeypatch.setattr(risk_manager_module, "_risk_manager", None)


class _NullLogger:
    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _make_risk_manager(consecutive_loss_limit=2, pause_after_consecutive_loss_sec=900):
    config = {
        'capital': {'total_capital': 100000},
        'risk_management': {
            'consecutive_loss_limit': consecutive_loss_limit,
            'consecutive_win_limit': 5,
            'pause_after_consecutive_loss_sec': pause_after_consecutive_loss_sec,
        },
    }
    return RiskManager(config, logger=None)


class TestNoIndependentPauseClock:
    def test_trading_state_has_no_independent_pause_clock(self):
        """`consecutive_loss_pause_until` was removed entirely from
        TradingState in §14.7 — its reintroduction, under this name or a new
        one holding the same role, would resurrect the second, independent
        clock that caused the double-pause bug."""
        state = TradingState()
        assert not hasattr(state, 'consecutive_loss_pause_until')

    def test_check_trade_limits_delegates_purely_to_risk_manager(self):
        """check_trade_limits() must not independently block on
        state.consecutive_losses — only RiskManager.check_streak_limits() may
        gate entries. A high state.consecutive_losses next to a fresh,
        never-triggered RiskManager must still allow trading, proving there
        is no parallel gate reading state.consecutive_losses directly."""
        state = TradingState()
        state.consecutive_losses = 99  # would have tripped the old, removed clock
        rm = _make_risk_manager()
        set_risk_manager(rm)

        ok, _reason = check_trade_limits(state, logger=_NullLogger())

        assert ok is True

    def test_pause_ends_cleanly_with_no_second_pause(self):
        """Once RiskManager's pause naturally expires, the very next call
        must return OK immediately — not trigger a second, independent
        pause. This is the exact symptom described in fixed.md §14.7:
        RiskManager's own stale counter re-firing the instant a cleared,
        independent state_machine pause let a signal back through."""
        state = TradingState()
        rm = _make_risk_manager(consecutive_loss_limit=2, pause_after_consecutive_loss_sec=900)
        rm.consecutive_losses = 2
        rm.streak_pause_until = datetime.now() - timedelta(seconds=1)  # already expired
        set_risk_manager(rm)

        ok, _reason = check_trade_limits(state, logger=_NullLogger())

        assert ok is True
        assert rm.consecutive_losses == 0
        assert rm.streak_pause_until is None

    def test_repeated_calls_during_active_pause_do_not_extend_it(self):
        """check_trade_limits() runs on every IDLE tick, and can_trade() calls
        check_streak_limits() again later in state_entry_ready() — neither
        call may push streak_pause_until further out or otherwise compound
        into a longer effective pause."""
        state = TradingState()
        rm = _make_risk_manager(consecutive_loss_limit=2, pause_after_consecutive_loss_sec=900)
        rm.consecutive_losses = 2
        pause_until = datetime.now() + timedelta(seconds=300)
        rm.streak_pause_until = pause_until
        set_risk_manager(rm)

        ok1, _ = check_trade_limits(state, logger=_NullLogger())
        ok2, _ = check_trade_limits(state, logger=_NullLogger())

        assert ok1 is False
        assert ok2 is False
        assert rm.streak_pause_until == pause_until  # unchanged, not re-extended
