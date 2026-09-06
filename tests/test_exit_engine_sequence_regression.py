from datetime import datetime, timedelta

import pytest

from core.engines import exit_engine
from core.engines.exit_engine import check_exit_conditions
from config.constants import MAX_LOSS_PER_TRADE_CE

# Mid-session, so the end-of-day cutoff is not what this test measures. It used to run
# against the wall clock, which made it pass or fail on the time of day: after the 15:25
# force close every tick exits with "MARKET CLOSE EXIT" and the first assertion below
# fails, for reasons that have nothing to do with the loss cap it is checking.
SESSION_TIME = datetime(2026, 9, 8, 11, 30)


@pytest.fixture
def pinned_clock():
    """Pin exit_engine's clock, the way core/backtest.py does when replaying history."""
    exit_engine._clock_override = SESSION_TIME
    try:
        yield SESSION_TIME
    finally:
        exit_engine._clock_override = None


def test_real_trade_sequence_caps_loss(monkeypatch, pinned_clock):
    """Simulate sequence [+79, +27, -780] to verify exit PnL is capped."""
    entry_price = 100.0
    trade = {
        'entry_time': pinned_clock - timedelta(seconds=10),
        'entry_price': entry_price,
        'qty': 1,
        'side': 'BUY',
        'direction': 'CE',
        # initialize tracking fields
        'max_profit_points': 0,
        'highest_sl': -6,
    }

    greeks = {'theta_sec': 0.0, 'gamma': 0.0, 'delta': 0.5}

    # Prevent immediate TP exit by raising TP threshold
    monkeypatch.setattr(exit_engine, 'TP_POINTS_FIXED', 9999)
    # Disable trailing for this regression sequence.
    monkeypatch.setattr(exit_engine, 'TRAILING_ENABLED', False)

    # Tick 1: +79
    tick1 = {'ltp': entry_price + 79, 'atr': 1.0}
    hit1, reason1 = check_exit_conditions(trade, tick1, greeks, 'NORMAL', logger=None, rsi=None)
    assert hit1 is False

    # Tick 2: +27 (still profitable, updates max_profit but not exit)
    tick2 = {'ltp': entry_price + 27, 'atr': 1.0}
    hit2, reason2 = check_exit_conditions(trade, tick2, greeks, 'NORMAL', logger=None, rsi=None)
    assert hit2 is False

    # Tick 3: -780 (huge adverse move)
    tick3 = {'ltp': entry_price - 780, 'atr': 1.0}
    hit3, reason3 = check_exit_conditions(trade, tick3, greeks, 'NORMAL', logger=None, rsi=None)
    assert hit3 is True

    # Verify PnL was capped to configured per-trade max
    pnl = trade.get('current_pnl')
    assert pnl is not None
    assert pnl <= 0
    assert abs(pnl) <= MAX_LOSS_PER_TRADE_CE


def test_the_cutoff_still_fires_after_the_close():
    """The companion to pinning the clock: the end-of-day exit must still work.

    Pinning could otherwise hide a regression in the very rule that made this file flaky.
    """
    exit_engine._clock_override = datetime(2026, 9, 8, 15, 45)
    try:
        trade = {
            'entry_time': datetime(2026, 9, 8, 15, 44),
            'entry_price': 100.0, 'qty': 1, 'side': 'BUY', 'direction': 'CE',
            'max_profit_points': 0, 'highest_sl': -6,
        }
        hit, reason = check_exit_conditions(
            trade, {'ltp': 179.0, 'atr': 1.0},
            {'theta_sec': 0.0, 'gamma': 0.0, 'delta': 0.5},
            'NORMAL', logger=None, rsi=None)
        assert hit is True
        assert 'MARKET CLOSE' in reason
    finally:
        exit_engine._clock_override = None
