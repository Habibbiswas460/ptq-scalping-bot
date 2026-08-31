"""Regression coverage for core.backtest's exit-engine integration
(findings.md/fixed.md §14.1 / §2.1) — backtest must drive exits through the
same core.engines.exit_engine.check_exit_conditions() the live bot uses,
not a separate simulation.
"""

from datetime import datetime, timedelta, timezone

from core.backtest import Backtester
from core.engines import exit_engine


def _make_backtester():
    return Backtester(initial_capital=30000, slippage_pct=0.0, commission_per_trade=0.0)


def _open_trade(bt, entry_time, direction="CE", entry_price=100.0, qty=65):
    bt.current_trade = {
        "trade_id": 1,
        "entry_time": entry_time,
        "direction": direction,
        "side": "BUY",
        "entry_price": entry_price,
        "qty": qty,
    }
    bt.daily_trades = 1
    bt.current_date = entry_time.date()


def test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware():
    bt = _make_backtester()
    entry_time = datetime(2026, 4, 2, 9, 15, tzinfo=timezone.utc)
    _open_trade(bt, entry_time)

    price = 100.0
    ticks_history = [{"ltp": price, "timestamp": entry_time}]
    result = None
    for i in range(1, 10):
        price -= 0.3
        candle = {
            "timestamp": entry_time + timedelta(seconds=15 * i),
            "open": price, "high": price, "low": price, "close": price,
            "volume": 12000, "spot_price": 24000, "option_ltp": price,
        }
        result = bt.process_candle(candle, ticks_history)
        ticks_history.append({"ltp": price, "timestamp": candle["timestamp"]})
        if result:
            break

    assert result is not None
    assert "SOFT LOSS" in result["exit_reason"]
    assert bt.current_trade is None
    # The clock override must not leak past the check that used it.
    assert exit_engine._clock_override is None


def test_naive_timestamps_also_work_no_tz_mismatch_crash():
    bt = _make_backtester()
    entry_time = datetime(2026, 4, 2, 9, 15)  # naive, no tzinfo
    _open_trade(bt, entry_time)

    price = 100.0
    ticks_history = [{"ltp": price, "timestamp": entry_time}]
    result = None
    for i in range(1, 60):
        price += 0.5  # steady rise -> should eventually trip an RSI-based exit
        candle = {
            "timestamp": entry_time + timedelta(seconds=15 * i),
            "open": price, "high": price, "low": price, "close": price,
            "volume": 12000, "spot_price": 24000, "option_ltp": price,
        }
        result = bt.process_candle(candle, ticks_history)
        ticks_history.append({"ltp": price, "timestamp": candle["timestamp"]})
        if result:
            break

    assert result is not None
    assert bt.current_trade is None


def test_exit_decision_goes_through_the_real_exit_engine(monkeypatch):
    """Directly confirm _check_exit() calls exit_engine.check_exit_conditions()
    rather than a separate/duplicated simulation."""
    bt = _make_backtester()
    entry_time = datetime(2026, 4, 2, 9, 15, tzinfo=timezone.utc)
    _open_trade(bt, entry_time)

    calls = []
    real_check = exit_engine.check_exit_conditions

    def spy(trade, tick, greeks, day_type, logger, rsi=None):
        calls.append((trade is bt.current_trade, tick["ltp"], day_type))
        return real_check(trade, tick, greeks, day_type, logger, rsi=rsi)

    monkeypatch.setattr("core.backtest.check_exit_conditions", spy)

    ticks_history = [{"ltp": 100.0, "timestamp": entry_time}]
    bt._check_exit(entry_time + timedelta(seconds=15), 100.0, 24000, ticks_history)

    assert len(calls) == 1
    assert calls[0][0] is True  # same trade dict object, not a copy
    assert calls[0][2] == bt.day_type
