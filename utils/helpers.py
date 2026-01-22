"""
PTQ Scalping Bot - Helper Functions
Utility functions used across the bot
"""

import time
from datetime import datetime
from typing import Dict, Any

from config.constants import CONFIG, TEST_MODE


def current_time_ms() -> int:
    """Current timestamp in milliseconds"""
    return int(time.time() * 1000)


def now() -> datetime:
    """Current datetime"""
    return datetime.now()


def is_expiry_date() -> bool:
    """Check if today is expiry date (weekly: Thursday)"""
    return datetime.now().weekday() == 3  # 3 = Thursday


def market_open() -> bool:
    """Check if market is open"""
    if TEST_MODE:
        return True  # Always open in test mode
    
    current = datetime.now()
    # NSE: 9:15 AM - 3:30 PM
    market_start = current.replace(hour=9, minute=15, second=0)
    market_end = current.replace(hour=15, minute=30, second=0)
    return market_start <= current <= market_end


def calc_latency_ms(tick: Dict) -> float:
    """Calculate tick latency in milliseconds"""
    return current_time_ms() - tick['timestamp']


def spread_pct(tick: Dict) -> float:
    """Calculate bid-ask spread percentage"""
    return (tick['ask'] - tick['bid']) / tick['ask'] * 100


def calculate_trade_pnl(trade: Dict, tick: Dict) -> float:
    """Calculate current unrealized PnL for a trade"""
    if not trade or not tick:
        return 0.0
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    lot_size = CONFIG['trading']['lot_size']
    
    if trade['side'] == 'BUY':
        pnl_per_lot = (current_price - entry_price) * lot_size
    else:
        pnl_per_lot = (entry_price - current_price) * lot_size
    
    return pnl_per_lot * qty


def estimate_vix_from_ticks(ticks: list, current_vix: float = 15.0) -> float:
    """Estimate VIX-like volatility from price movements"""
    if len(ticks) < 30:
        return current_vix
    
    # Calculate returns volatility
    prices = [t['ltp'] for t in ticks[-30:]]
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    if not returns:
        return current_vix
    
    # Standard deviation of returns * scaling factor
    import statistics
    vol = statistics.stdev(returns) if len(returns) > 1 else 0
    estimated_vix = vol * 100 * 15.87  # Annualize and scale
    
    return max(10, min(30, estimated_vix))  # Clamp between 10-30


def calculate_position_size(estimated_vix: float) -> float:
    """Calculate dynamic position size based on VIX"""
    if not CONFIG['risk_management'].get('position_sizing_enabled', False):
        return 1.0
    
    vix_low = CONFIG['risk_management']['vix_low_threshold']
    vix_high = CONFIG['risk_management']['vix_high_threshold']
    
    if estimated_vix < vix_low:
        return CONFIG['risk_management']['position_size_low_vix']
    elif estimated_vix > vix_high:
        return CONFIG['risk_management']['position_size_high_vix']
    else:
        return CONFIG['risk_management']['position_size_normal_vix']
