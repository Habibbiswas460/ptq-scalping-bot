"""The lifetime drawdown gate must not be a one-way latch.

Background: `check_drawdown()` is gate #1 in `can_trade()` and returns early. Its
ceiling was hardcoded to 10% of capital, which for the configured Rs30,000 account
is Rs3,000 — the same number as MAX_DAILY_LOSS. `peak_equity` is a monotone
all-time high that never decays. Those three facts together mean a single day that
spends its full *permitted* loss budget also trips the lifetime halt, and the only
thing that can lift that halt is profit the halt itself forbids earning.

It fired for real. On 2026-09-07 the persisted state was total_pnl -2790.45 against
a peak of 30237.90: a drawdown of Rs3028 against a Rs3000 ceiling, needing +Rs28.35
that could never be earned. Every session after that would have placed zero trades.

These tests pin the deadlock and the two properties that resolve it.
"""

import json
import os
import tempfile

from core.risk.risk_manager import RiskManager


def _cfg(max_dd=3000, max_dd_pct=10.0, lookback=0, daily=3000, capital=30000):
    return {
        "capital": {
            "total_capital": capital,
            "max_daily_loss_amount": daily,
            "max_drawdown_amount": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "drawdown_peak_lookback_sessions": lookback,
        },
        "trading": {"symbol": "NIFTY", "lot_size": 65},
        "risk_management": {
            "pause_after_consecutive_loss_sec": 900,
            "consecutive_loss_limit": 2,
            "consecutive_win_limit": 5,
            "capital_utilization_pct": 80,
        },
        "recovery_mode": {"size_reduction_pct": 50},
    }


def _rm_in(tmp, cfg, state=None):
    """A RiskManager rooted at tmp so it reads/writes logs/risk_state.json there."""
    if state is not None:
        os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
        with open(os.path.join(tmp, "logs", "risk_state.json"), "w") as fh:
            json.dump(state, fh)
    return RiskManager(cfg, logger=None)


# The state that actually latched the account, verbatim.
LATCHED = {
    "weekly_pnl": -952.25,
    "total_pnl": -2790.45,
    "peak_equity": 30237.9,
    "recovery_mode": True,
    "recovery_start_date": "2026-09-07T13:53:47.105901",
    "equity_history": [30000, 30000, 30000, 30000, 27705.5,
                       27495.55, 27495.55, 27495.55, 27495.55, 27209.55],
    "daily_pnl": 0.0,
    "daily_date": "2026-09-07",
    "last_updated": "2026-09-07T15:28:36.517010",
}


def test_the_2026_09_07_state_latched_under_the_old_settings():
    """Regression anchor: with an all-time peak and a Rs3000 ceiling this state is dead."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_in(tmp, _cfg(max_dd=3000, max_dd_pct=10.0, lookback=0), LATCHED)
            ok, reason = r.check_drawdown()
            assert ok is False
            # and the message now says how far from re-opening it is, which is the
            # fact that distinguishes a protective halt from a permanent one
            assert "needs +" in reason
        finally:
            os.chdir(cwd)


def test_a_rolling_peak_gives_the_same_state_a_way_back():
    """With the peak measured over recent sessions the old high ages out."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_in(tmp, _cfg(max_dd=3000, max_dd_pct=10.0, lookback=10), LATCHED)
            ok, reason = r.check_drawdown()
            assert ok is True, reason
            # peak comes from the window, not from the all-time 30237.90
            assert r.effective_peak_equity() == 30000
            assert r.peak_equity == 30237.9, "the all-time high is still recorded"
        finally:
            os.chdir(cwd)


def test_lookback_zero_preserves_the_original_all_time_behaviour():
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_in(tmp, _cfg(lookback=0), LATCHED)
            assert r.effective_peak_equity() == 30237.9
        finally:
            os.chdir(cwd)


def test_the_shipped_config_lets_the_latched_account_trade_again():
    """End-to-end through can_trade(), which is what the bot actually calls."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            r = _rm_in(tmp, _cfg(max_dd=9000, max_dd_pct=30.0, lookback=10), LATCHED)
            can, details = r.can_trade(spot_price=None)
            assert can is True, details.get("reasons")
        finally:
            os.chdir(cwd)


def test_a_genuinely_deep_drawdown_still_halts():
    """The gate must still be a gate — this is not a removal of the protection."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            deep = dict(LATCHED, total_pnl=-9500.0,
                        equity_history=[30000] * 10, peak_equity=30000)
            r = _rm_in(tmp, _cfg(max_dd=9000, max_dd_pct=30.0, lookback=10), deep)
            ok, reason = r.check_drawdown()
            assert ok is False and "Max drawdown" in reason
        finally:
            os.chdir(cwd)


def test_a_lifetime_ceiling_at_or_below_the_daily_ceiling_is_warned_about():
    """Two independently-derived defaults happened to evaluate to the same number,
    which grants the account exactly one bad day for its whole life. Nobody chose
    that, so it must at least be said out loud at startup."""
    class _Log:
        def __init__(self):
            self.msgs = []

        def __getattr__(self, level):
            def _rec(msg):
                self.msgs.append((level, msg))
            return _rec

    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            lg = _Log()
            RiskManager(_cfg(max_dd=3000, daily=3000, lookback=0), logger=lg)
            warned = [m for lvl, m in lg.msgs if "drawdown ceiling" in m]
            assert warned, lg.msgs
            assert "never lifts" in warned[0]

            lg2 = _Log()
            RiskManager(_cfg(max_dd=9000, daily=3000, lookback=10), logger=lg2)
            assert not [m for lvl, m in lg2.msgs if "drawdown ceiling" in m]
        finally:
            os.chdir(cwd)
