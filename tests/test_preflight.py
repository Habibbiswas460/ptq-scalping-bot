"""The pre-open check must catch the failure that actually happened.

On 2026-09-08 the bot was healthy, connected and warm, and could not have placed a
single trade: a persisted risk gate had latched shut Rs28 short of its limit. The
live readiness checker could not see it — that one needs a market session, and this
was decided the night before. So the value of this module is entirely in whether it
would have caught that, and in whether it stays read-only while doing so.
"""

import datetime
import json
import os
import tempfile

from utils import preflight


LATCHED = {
    "weekly_pnl": -952.25, "total_pnl": -2790.45, "peak_equity": 30237.9,
    "recovery_mode": True, "recovery_start_date": "2026-09-07T13:53:47.105901",
    "equity_history": [30000] * 10, "daily_pnl": 0.0, "daily_date": "2026-09-07",
    "last_updated": "2026-09-07T15:28:36.517010",
}


def _cfg(max_dd, lookback):
    return {
        "capital": {"total_capital": 30000, "max_daily_loss_amount": 3000,
                    "max_drawdown_amount": max_dd, "max_drawdown_pct": 30.0,
                    "drawdown_peak_lookback_sessions": lookback,
                    "risk_per_trade_amount": 900},
        "trading": {"symbol": "NIFTY", "lot_size": 65},
        "risk_management": {"pause_after_consecutive_loss_sec": 900,
                            "consecutive_loss_limit": 2, "consecutive_win_limit": 5,
                            "capital_utilization_pct": 80},
        "recovery_mode": {"size_reduction_pct": 50},
        "costs": {"enabled": True, "brokerage_per_order": 20.0},
    }


def _in_tmp_with_state(state, fn):
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            os.makedirs("logs", exist_ok=True)
            with open("logs/risk_state.json", "w") as fh:
                json.dump(state, fh)
            return fn(tmp)
        finally:
            os.chdir(cwd)


def _blocking_failures(checks):
    return [name for name, ok, blocking, _ in checks if blocking and not ok]


def test_it_catches_the_latch_that_the_live_checker_could_not_see():
    def body(_):
        checks = preflight._risk_state_checks(_cfg(max_dd=3000, lookback=0))
        failed = _blocking_failures(checks)
        assert "Risk gates open" in failed
        assert "Drawdown gate is escapable" in failed, (
            "a halt that cannot be escaped is an outage, not a limit, and the "
            "difference is the whole point of reporting it"
        )
        escape = [d for n, _, _, d in checks if n == "Drawdown gate is escapable"][0]
        assert "needs +Rs28" in escape, escape
    _in_tmp_with_state(LATCHED, body)


def test_it_passes_on_the_shipped_configuration():
    def body(_):
        checks = preflight._risk_state_checks(_cfg(max_dd=9000, lookback=10))
        assert _blocking_failures(checks) == []
    _in_tmp_with_state(LATCHED, body)


def test_it_flags_a_lifetime_ceiling_that_is_only_one_bad_day():
    def body(_):
        checks = preflight._risk_state_checks(_cfg(max_dd=3000, lookback=10))
        names = _blocking_failures(checks)
        assert "Lifetime ceiling > daily ceiling" in names
    _in_tmp_with_state(LATCHED, body)


def test_it_never_writes_to_the_state_it_reads():
    """A check that mutates the thing it is checking is worse than no check."""
    def body(tmp):
        path = os.path.join(tmp, "logs", "risk_state.json")
        before = open(path).read()
        preflight._risk_state_checks(_cfg(max_dd=9000, lookback=10))
        preflight._sizing_checks(_cfg(max_dd=9000, lookback=10))
        assert open(path).read() == before
    _in_tmp_with_state(LATCHED, body)


def test_sizing_check_reports_whether_one_lot_can_be_funded():
    """87 accepted signals produced no orders on 2026-09-07 because a soft
    multiplier rounded the position to zero — a stop that never called itself one."""
    def body(_):
        checks = preflight._sizing_checks(_cfg(max_dd=9000, lookback=10))
        assert len(checks) == 1
        name, ok, blocking, detail = checks[0]
        assert ok and blocking and "qty=65" in detail
    _in_tmp_with_state(LATCHED, body)


def test_costs_off_is_reported_as_a_warning_not_silence():
    cfg = _cfg(max_dd=9000, lookback=10)
    cfg["costs"]["enabled"] = False
    name, ok, blocking, detail = preflight._cost_checks(cfg)[0]
    assert ok is False and blocking is False
    assert "GROSS" in detail


def test_a_known_holiday_is_reported_as_not_a_trading_day():
    checks = preflight._calendar_checks(datetime.date(2026, 1, 26))
    assert _blocking_failures(checks), "2026-01-26 is a declared NSE holiday"


def test_the_run_helper_agrees_with_its_own_checks():
    checks, ok = preflight.run(datetime.date(2026, 9, 9))
    assert ok == (not _blocking_failures(checks))
