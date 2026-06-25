from datetime import datetime, timedelta

from core.engines import exit_engine
from core.engines.exit_engine import check_exit_conditions
from config.constants import MAX_LOSS_PER_TRADE_CE


def test_real_trade_sequence_caps_loss(monkeypatch):
    """Simulate sequence [+79, +27, -780] to verify exit PnL is capped."""
    entry_price = 100.0
    trade = {
        'entry_time': datetime.now() - timedelta(seconds=10),
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
    # Prevent aggressive trailing SL lock from max profit
    monkeypatch.setattr(exit_engine, 'TRAILING_DISTANCE', 1000)

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
