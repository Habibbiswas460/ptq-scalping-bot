import time
from datetime import datetime

from core.engines.exit_engine import early_momentum_loss_cut
from config.constants import MAX_LOSS_PER_TRADE_CE


def test_early_momentum_loss_cut_caps_pnl():
    """Regression: ensure early_momentum_loss_cut caps PnL to per-trade max."""
    now = datetime.now()

    # Simulate a trade with a large adverse move within initial 30s
    trade = {
        'entry_time': now,
        'qty': 100,
        'side': 'BUY',
        'direction': 'CE',
        'price_diff': -10.0,  # -10 pts adverse move
    }

    tick = {'atr': 1.0}

    hit, reason = early_momentum_loss_cut(trade, tick)

    assert hit is True
    assert 'EARLY LOSS CUT' in reason

    expected_loss = min(abs(trade['price_diff'] * trade['qty']), MAX_LOSS_PER_TRADE_CE)
    assert trade.get('current_pnl') == -expected_loss
    assert trade.get('_early_cut_applied') is True
