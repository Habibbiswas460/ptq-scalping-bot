from datetime import datetime, timedelta, timezone

from core.backtest import BacktestTrade, Backtester
from core.engines import state_machine


def test_backtest_reports_data_window_when_no_trades():
    backtester = Backtester(initial_capital=30000)
    backtester.process_candle = lambda candle, ticks: None

    data = [
        {
            "timestamp": datetime(2026, 4, 2, 9, 15, tzinfo=timezone.utc),
            "open": 22000,
            "high": 22010,
            "low": 21990,
            "close": 22005,
            "volume": 100,
        },
        {
            "timestamp": datetime(2026, 4, 2, 15, 25, tzinfo=timezone.utc),
            "open": 22100,
            "high": 22110,
            "low": 22095,
            "close": 22105,
            "volume": 100,
        },
    ]

    result = backtester.run_backtest(data)

    assert result.start_date == "2026-04-02"
    assert result.end_date == "2026-04-02"
    assert result.first_trade_date == ""
    assert result.last_trade_date == ""


def test_backtest_end_of_data_exit_uses_option_resolved_price():
    backtester = Backtester(initial_capital=30000, slippage_pct=0.0)
    backtester.process_candle = lambda candle, ticks: None

    entry_time = datetime(2026, 4, 2, 9, 15, tzinfo=timezone.utc)
    backtester.current_trade = BacktestTrade(
        trade_id=1,
        entry_time=entry_time,
        direction="CE",
        entry_price=180.0,
        qty=1,
        sl_price=-1_000_000.0,
        tp_price=1_000_000.0,
    )

    data = [
        {
            "timestamp": datetime(2026, 4, 2, 15, 25, tzinfo=timezone.utc),
            "open": 25000,
            "high": 25020,
            "low": 24980,
            "close": 25010,
            "spot_price": 25010,
            "volume": 100,
        }
    ]

    result = backtester.run_backtest(data)

    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "END_OF_DATA"
    assert trade.exit_price < 1000


def test_signal_execution_guard_handles_mixed_timestamp_formats():
    signal_time = datetime(2026, 8, 8, 10, 0, 0)
    tick_time = datetime(2026, 8, 8, 10, 0, 1, tzinfo=timezone.utc)

    ok, reason, details = state_machine._signal_execution_guard(
        {
            "signal_ltp": 100.0,
            "signal_timestamp": signal_time.isoformat(),
        },
        {
            "ltp": 100.1,
            "timestamp": tick_time.isoformat(),
        },
    )

    assert ok is True
    assert reason == "ok"
    assert details["check"] == "pass"


def test_signal_execution_guard_blocks_future_dated_signal():
    signal_time = datetime(2026, 8, 8, 10, 0, 5, tzinfo=timezone.utc)
    tick_time = datetime(2026, 8, 8, 10, 0, 0, tzinfo=timezone.utc)

    ok, reason, details = state_machine._signal_execution_guard(
        {
            "signal_ltp": 100.0,
            "signal_timestamp": signal_time.isoformat(),
        },
        {
            "ltp": 100.0,
            "timestamp": tick_time.isoformat(),
        },
    )

    assert ok is False
    assert "future" in reason.lower()
    assert details["check"] == "future_signal"


def test_signal_execution_guard_blocks_stale_signal():
    signal_time = datetime(2026, 8, 8, 10, 0, 0, tzinfo=timezone.utc)
    tick_time = signal_time + timedelta(milliseconds=float(state_machine.ENTRY_SIGNAL_MAX_AGE_MS) + 500)

    ok, reason, details = state_machine._signal_execution_guard(
        {
            "signal_ltp": 100.0,
            "signal_timestamp": signal_time.isoformat(),
        },
        {
            "ltp": 100.0,
            "timestamp": tick_time.isoformat(),
        },
    )

    assert ok is False
    assert "stale" in reason.lower()
    assert details["check"] == "stale"
