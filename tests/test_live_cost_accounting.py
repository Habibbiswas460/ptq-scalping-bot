"""Costs must be charged in the live path, not only in offline experiments.

Until 2026-09-08 the bot computed `(exit - entry) x qty` and stopped. There was no
brokerage, STT, exchange transaction charge, GST or stamp duty anywhere in the
running code. Every P&L figure the project produced was therefore GROSS — and so
was every risk limit measured against one. On the 143 trades recorded to
2026-09-07 that gap is Rs63.80 per trade, which turns -Rs1,644 gross into
-Rs10,767 net and makes a "Rs3,000 daily ceiling" really about Rs3,800 of losses.

`RiskManager.record_trade()` is the single point every exit path funnels through,
so the charge is applied there.
"""

import copy
import os
import tempfile

from core.risk.risk_manager import RiskManager
from research.costs import CostModel


BASE = {
    "capital": {
        "total_capital": 30000,
        "max_daily_loss_amount": 3000,
        "max_drawdown_amount": 9000,
        "max_drawdown_pct": 30.0,
        "drawdown_peak_lookback_sessions": 10,
    },
    "trading": {"symbol": "NIFTY", "lot_size": 65},
    "risk_management": {"pause_after_consecutive_loss_sec": 900,
                        "consecutive_loss_limit": 2, "consecutive_win_limit": 5,
                        "capital_utilization_pct": 80},
    "recovery_mode": {"size_reduction_pct": 50},
    "costs": {"enabled": True, "brokerage_per_order": 20.0},
}


def _cfg(**over):
    c = copy.deepcopy(BASE)
    c["costs"].update(over)
    return c


def _in_tmp(fn):
    """record_trade() persists state, so every test runs rooted in a tmpdir."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            return fn(tmp)
        finally:
            os.chdir(cwd)


def test_a_winning_trade_is_recorded_net_of_its_cost():
    def body(_):
        r = RiskManager(_cfg(), logger=None)
        r.record_trade({"pnl": 130.0, "direction": "CE",
                        "entry_price": 150.0, "exit_price": 152.0, "qty": 65})
        expected = 130.0 - CostModel().round_trip(150.0, 152.0, 65)
        assert abs(r.daily_pnl - expected) < 0.01
        assert r.daily_pnl < 130.0, "the win must shrink"
    _in_tmp(body)


def test_a_losing_trade_is_recorded_deeper_not_shallower():
    def body(_):
        r = RiskManager(_cfg(), logger=None)
        r.record_trade({"pnl": -455.0, "direction": "CE",
                        "entry_price": 150.0, "exit_price": 143.0, "qty": 65})
        assert r.daily_pnl < -455.0, "costs add to a loss, they do not offset it"
    _in_tmp(body)


def test_the_gross_figure_is_kept_alongside_the_net_one():
    def body(_):
        r = RiskManager(_cfg(), logger=None)
        t = {"pnl": 130.0, "direction": "CE",
             "entry_price": 150.0, "exit_price": 152.0, "qty": 65}
        r.record_trade(t)
        assert t["gross_pnl"] == 130.0
        assert t["cost"] > 0
        assert abs(t["pnl"] - (t["gross_pnl"] - t["cost"])) < 0.01
    _in_tmp(body)


def test_an_unpriced_trade_is_not_charged_an_invented_cost():
    """Kill-switch and emergency paths may not carry entry/exit/qty. A missing
    price must record gross, not a guess."""
    def body(_):
        r = RiskManager(_cfg(), logger=None)
        r.record_trade({"pnl": 50.0, "direction": "CE"})
        assert r.daily_pnl == 50.0
    _in_tmp(body)


def test_costs_can_be_switched_off_and_then_nothing_changes():
    def body(_):
        r = RiskManager(_cfg(enabled=False), logger=None)
        r.record_trade({"pnl": 130.0, "direction": "CE",
                        "entry_price": 150.0, "exit_price": 152.0, "qty": 65})
        assert r.daily_pnl == 130.0
    _in_tmp(body)


def test_a_cheaper_broker_is_a_smaller_charge():
    """The largest single lever this project has found: Rs20 -> Rs5 per order."""
    def body(_):
        a = RiskManager(_cfg(brokerage_per_order=20.0), logger=None)
        b = RiskManager(_cfg(brokerage_per_order=5.0), logger=None)
        t = {"pnl": 0.0, "direction": "CE",
             "entry_price": 150.0, "exit_price": 150.0, "qty": 65}
        ca = a.transaction_cost(dict(t))
        cb = b.transaction_cost(dict(t))
        assert cb < ca
        # two orders per round trip, so the saving is 2 x the per-order difference
        assert abs((ca - cb) - 2 * 15.0 * 1.18) < 0.01, (ca, cb)
    _in_tmp(body)


def test_the_daily_ceiling_is_reached_sooner_once_costs_count():
    """This is the point of the change: the limit now means what it says."""
    def body(_):
        gross_only = RiskManager(_cfg(enabled=False), logger=None)
        with_costs = RiskManager(_cfg(enabled=True), logger=None)
        trade = {"pnl": -300.0, "direction": "CE",
                 "entry_price": 150.0, "exit_price": 145.4, "qty": 65}
        for _ in range(10):
            gross_only.record_trade(dict(trade))
            with_costs.record_trade(dict(trade))
        assert with_costs.daily_pnl < gross_only.daily_pnl
        # ten trades' worth of cost is not a rounding difference
        assert gross_only.daily_pnl - with_costs.daily_pnl > 600
    _in_tmp(body)
