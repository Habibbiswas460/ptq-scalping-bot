"""
PTQ Scalping Bot - Helper Functions
Utility functions used across the bot
"""

import time
from datetime import datetime
from typing import Dict, Any

from config.constants import TEST_MODE, LOT_SIZE


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


def wait_for_market_open():
    """Wait until market opens (9:15 AM). Waits overnight if needed."""
    import time as t
    from datetime import timedelta
    
    def _log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\033[2m{ts}\033[0m  {msg}")
    
    current = datetime.now()
    market_start = current.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = current.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # If already past market close, wait for NEXT DAY's market open
    if current > market_end:
        next_day = current + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        market_start = next_day.replace(hour=9, minute=15, second=0, microsecond=0)
        
        wait_seconds = (market_start - current).total_seconds()
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)
        _log(f"Market closed. Next open: {market_start.strftime('%Y-%m-%d')} 09:15 ({hours}h {minutes}m)")
    
    elif current < market_start:
        wait_seconds = (market_start - current).total_seconds()
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)
        _log(f"Waiting for 09:15 ({hours}h {minutes}m)")
    else:
        return True
    
    # Wait with periodic status updates
    while datetime.now() < market_start:
        remaining = (market_start - datetime.now()).total_seconds()
        if remaining > 3600:
            hours_left = int(remaining // 3600)
            mins_left = int((remaining % 3600) // 60)
            _log(f"💤 {hours_left}h {mins_left}m to open…")
            t.sleep(600)
        elif remaining > 60:
            mins_left = int(remaining // 60)
            if mins_left % 5 == 0:
                _log(f"⏳ {mins_left}m to open…")
            t.sleep(60)
        else:
            _log(f"🔔 Opening in {int(remaining)}s!")
            t.sleep(remaining)
            break
    
    _log("🔔 Market open!")
    return True


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
    lot_size = LOT_SIZE
    
    if trade['side'] == 'BUY':
        pnl_per_lot = (current_price - entry_price) * lot_size
    else:
        pnl_per_lot = (entry_price - current_price) * lot_size
    
    return pnl_per_lot * qty


# Global VIX cache
_vix_cache = {
    'value': 15.0,
    'last_fetch': None,
    'broker_client': None
}


def set_vix_broker_client(broker_client):
    """Set broker client for fetching real India VIX"""
    global _vix_cache
    _vix_cache['broker_client'] = broker_client


def fetch_real_vix() -> float:
    """Fetch real India VIX from Angel One API
    
    Note: Angel One API doesn't seem to support VIX LTP fetch.
    Using estimation from price volatility instead.
    """
    global _vix_cache
    from datetime import datetime
    
    # Return cached value - VIX API not working, skip fetching
    # Real VIX fetch is disabled due to Angel One API limitations
    return _vix_cache['value']


def estimate_vix_from_ticks(ticks: list, current_vix: float = 15.0) -> float:
    """
    Calculate VIX from price volatility (optimized)
    Real VIX API disabled - using price-based estimation only
    """
    if len(ticks) < 30:
        return current_vix
    
    prices = [t['ltp'] for t in ticks[-30:]]
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    if not returns:
        return current_vix
    
    import statistics
    vol = statistics.stdev(returns) if len(returns) > 1 else 0
    estimated_vix = vol * 100 * 14.5  # Optimized scaling for NIFTY
    
    # Dynamic adjustment: recent extreme moves increase VIX
    recent_moves = [abs(r) for r in returns[-5:]]
    if recent_moves and max(recent_moves) > 0.01:
        estimated_vix *= (1 + max(recent_moves) * 2)
    
    return max(10, min(35, estimated_vix))  # Clamp: 10-35 for NIFTY


def calculate_position_size(estimated_vix: float) -> float:
    """Calculate dynamic position size based on VIX
    Returns multiplier (0.5 to 1.25) based on VIX level
    """
    # VIX-based position sizing thresholds
    vix_low = 12.0
    vix_high = 20.0
    
    if estimated_vix < vix_low:
        return 1.25  # Bigger positions in low vol
    elif estimated_vix > vix_high:
        return 0.5   # Smaller positions in high vol
    else:
        return 1.0   # Normal position size
