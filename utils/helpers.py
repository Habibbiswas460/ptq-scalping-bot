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
    
    current = datetime.now()
    market_start = current.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = current.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # If already past market close, wait for NEXT DAY's market open
    if current > market_end:
        # Calculate next trading day's market open
        next_day = current + timedelta(days=1)
        # Skip weekends
        while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
            next_day += timedelta(days=1)
        market_start = next_day.replace(hour=9, minute=15, second=0, microsecond=0)
        
        wait_seconds = (market_start - current).total_seconds()
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)
        print(f"⏰ Market closed. Waiting for next trading day...")
        print(f"   Current time: {current.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Next market open: {market_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Time to wait: {hours}h {minutes}m")
        print(f"   💤 Bot will auto-start at 9:15 AM")
        print("-" * 50)
    
    # If before market open today, wait
    elif current < market_start:
        wait_seconds = (market_start - current).total_seconds()
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)
        print(f"⏰ Waiting for market open at 9:15 AM...")
        print(f"   Current time: {current.strftime('%H:%M:%S')}")
        print(f"   Time to wait: {hours}h {minutes}m")
        print(f"   Bot will auto-start trading at 9:15 AM")
        print("-" * 50)
    else:
        # Market is already open
        return True
    
    # Wait with periodic status updates
    while datetime.now() < market_start:
        remaining = (market_start - datetime.now()).total_seconds()
        if remaining > 3600:  # More than 1 hour
            hours_left = int(remaining // 3600)
            mins_left = int((remaining % 3600) // 60)
            print(f"   💤 {hours_left}h {mins_left}m to market open...")
            t.sleep(600)  # Sleep 10 minutes
        elif remaining > 60:
            mins_left = int(remaining // 60)
            if mins_left % 5 == 0:  # Print every 5 minutes
                print(f"   ⏳ {mins_left} minutes to market open...")
            t.sleep(60)  # Sleep 1 minute
        else:
            print(f"   🔔 Market opening in {int(remaining)} seconds!")
            t.sleep(remaining)
            break
    
    print("🔔 MARKET OPEN! Starting trading...")
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
