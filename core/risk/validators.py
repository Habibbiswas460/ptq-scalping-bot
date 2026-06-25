"""
PTQ Scalping Bot - Data Validators
Data hygiene, PTQ validation, Greeks filtering
"""

from datetime import datetime
from typing import Dict, Tuple, List

from config.constants import (
    CONFIG, LATENCY_LIMIT_MS, SPREAD_LIMIT_PCT,
    CHOP_THRESHOLD, DELTA_MIN, DELTA_MAX,
    GAMMA_NORMAL_MAX, GAMMA_EXPIRY_MAX, THETA_SEC_LIMIT
)
from utils.helpers import current_time_ms, calc_latency_ms, spread_pct

# Import mode switch for dynamic thresholds
try:
    from core.services.mode_switch import get_threshold, get_current_mode
    HAS_MODE_SWITCH = True
except ImportError:
    HAS_MODE_SWITCH = False
    def get_threshold(key): return None
    def get_current_mode(): return "AGGRESSIVE"


# =========================================================
# DATA VALIDATION
# =========================================================

def is_data_valid(tick: Dict) -> Tuple[bool, str]:
    """Validate tick data - STAGE-3: Data Hygiene"""
    if tick is None:
        return False, "Tick is None"
    
    # Basic sanity
    if tick['bid'] <= 0 or tick['ask'] <= 0:
        return False, "Invalid bid/ask prices"
    
    # Bid must be < Ask
    if tick['bid'] >= tick['ask']:
        return False, "Bid >= Ask (inverted market)"
    
    # PRICE VALIDATION
    ltp = tick.get('ltp', 0)
    min_price = CONFIG['data_hygiene']['min_option_price']
    max_price = CONFIG['data_hygiene']['max_option_price']
    
    if ltp < min_price or ltp > max_price:
        return False, f"Invalid price ₹{ltp:.2f} (range: ₹{min_price}-₹{max_price})"
    
    # Spot price validation
    spot = tick.get('spot_price', 0)
    if spot > 0:
        min_spot = CONFIG['data_hygiene']['min_spot_price']
        max_spot = CONFIG['data_hygiene']['max_spot_price']
        if spot < min_spot or spot > max_spot:
            return False, f"Invalid spot ₹{spot:.2f} (range: ₹{min_spot}-₹{max_spot})"
    
    # Timestamp freshness - use original tick arrival time when available
    original_ts = tick.get('original_timestamp', tick['timestamp'])
    tick_age_ms = current_time_ms() - original_ts
    data_source = tick.get('data_source', '')
    if data_source.startswith('WEBSOCKET'):
        max_age_ms = 10000  # Allow slightly older WS ticks when no price change occurs
    elif data_source in ('REST', 'REST_REFRESH'):
        max_age_ms = 5000
    else:
        max_age_ms = 2000
    if tick_age_ms > max_age_ms:
        return False, f"Stale tick ({tick_age_ms}ms old)"
    
    # Latency check - SKIP since timestamp freshness check above is more appropriate
    # The latency check was redundant (same calculation as stale tick check)
    # latency = calc_latency_ms(tick)
    # if latency > LATENCY_LIMIT_MS:
    #     return False, f"High latency ({latency:.1f}ms)"
    
    # Spread check
    spread = spread_pct(tick)
    if spread > SPREAD_LIMIT_PCT:
        return False, f"Wide spread ({spread:.3f}%)"
    
    # Volume sanity - Skip if volume data not available (WebSocket may not send volume)
    # Volume check is optional - many WebSocket feeds don't include accurate volume
    min_volume = CONFIG['data_hygiene'].get('min_volume', 0)
    tick_volume = tick.get('volume', -1)  # -1 means no volume data
    
    # Only reject if volume is explicitly 0 AND min_volume is set high
    # If volume is -1 (not provided) or min_volume is 0, skip this check
    if tick_volume == 0 and min_volume > 0:
        # Check if we're in first 30 min - volume often 0 at market open
        current_time = datetime.now()
        market_start = current_time.replace(hour=9, minute=15, second=0)
        time_since_open = (current_time - market_start).total_seconds()
        
        if time_since_open > 1800:  # After first 30 minutes
            return False, "Low volume"
    
    return True, "OK"


# =========================================================
# PTQ VALIDATION
# =========================================================

def calculate_vwap(ticks: List[Dict], period: int = 60) -> float:
    """Calculate VWAP from recent ticks
    
    Note: Skips ticks without valid volume (no arbitrary defaults)
    """
    if len(ticks) == 0:
        return 0
    
    recent = ticks[-period:] if len(ticks) > period else ticks
    
    # Only use ticks with actual volume data
    ticks_with_vol = [(t['ltp'], t.get('volume', 0)) for t in recent if t.get('volume', 0) > 0]
    
    if not ticks_with_vol:
        # Fallback: simple average price if no volume data
        return sum(t['ltp'] for t in recent) / len(recent) if recent else 0
    
    total_pv = sum(ltp * vol for ltp, vol in ticks_with_vol)
    total_v = sum(vol for _, vol in ticks_with_vol)
    
    return total_pv / total_v if total_v > 0 else 0


def analyze_candle_quality(ticks: List[Dict]) -> Dict:
    """Analyze 1-min candle from recent ticks"""
    if len(ticks) < 60:
        return {'body_pct': 0, 'wick_pct': 0, 'direction': 0}
    
    minute_ticks = ticks[-60:]
    open_price = minute_ticks[0]['ltp']
    high_price = max(t['ltp'] for t in minute_ticks)
    low_price = min(t['ltp'] for t in minute_ticks)
    close_price = minute_ticks[-1]['ltp']
    
    candle_range = high_price - low_price
    if candle_range == 0:
        return {'body_pct': 0, 'wick_pct': 0, 'direction': 0}
    
    body_size = abs(close_price - open_price)
    body_pct = (body_size / candle_range) * 100
    wick_pct = 100 - body_pct
    direction = 1 if close_price > open_price else -1
    
    return {
        'body_pct': body_pct,
        'wick_pct': wick_pct,
        'direction': direction
    }


def validate_price_ptq(tick: Dict, ticks: List[Dict]) -> Tuple[bool, str]:
    """P = Price validation (PTQ)"""
    from config.constants import PAPER_TRADING
    
    current_price = tick['ltp']
    
    # Paper trading = always valid (for testing)
    if PAPER_TRADING:
        return True, "Paper mode - price OK"
    
    if len(ticks) < 30:  # Reduced from 60
        return False, "Insufficient history"
    
    vwap = calculate_vwap(ticks)
    candle = analyze_candle_quality(ticks)
    
    # Check for chop - relaxed threshold
    recent_prices = [t['ltp'] for t in ticks[-30:]]
    recent_range = max(recent_prices) - min(recent_prices)
    is_chop = recent_range < current_price * 0.0001  # Relaxed from CHOP_THRESHOLD
    
    if is_chop:
        return False, "Chop market"
    
    # Level break + momentum (CALL) - relaxed body requirement
    if current_price > vwap and candle['body_pct'] > 10:  # Was 20
        return True, "Level break above VWAP"
    
    # Level break + momentum (PUT) - relaxed body requirement
    if current_price < vwap and candle['body_pct'] > 10:  # Was 20
        return True, "Level break below VWAP"
    
    # Rejection pattern - relaxed wick requirement
    if candle['wick_pct'] > 25:  # Was 35
        if current_price < vwap and candle['direction'] == 1:
            return True, "Rejection from VWAP (bullish)"
        elif current_price > vwap and candle['direction'] == -1:
            return True, "Rejection from VWAP (bearish)"
    
    # Directional move away from VWAP - relaxed distance
    vwap_dist = abs(current_price - vwap) / vwap
    if vwap_dist > 0.001:  # Was 0.0015 (0.1% now)
        if current_price > vwap:
            return True, "Price above VWAP"
        elif current_price < vwap:
            return True, "Price below VWAP"
    
    # NEW: Any movement from VWAP is valid if volume is good
    if vwap_dist > 0.0005:  # 0.05% minimum
        return True, "Minor VWAP deviation"
    
    return False, "No valid price setup"


def validate_time_ptq(greeks: Dict) -> Tuple[bool, str]:
    """T = Time validation (PTQ)"""
    from config.constants import PAPER_TRADING
    
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    
    # Paper trading = always valid (for testing)
    if PAPER_TRADING:
        return True, "Paper mode - time OK"
    
    # Session phase
    if hour == 9 and minute < 30:
        session = 'OPEN'
    elif hour >= 15 or (hour == 14 and minute >= 30):
        session = 'LATE'
    else:
        session = 'MID'
    
    # Late session filter
    if session == 'LATE':
        return False, "Late session - low probability"
    
    # Theta dominance check
    if greeks.get('theta_sec', 0) > 0.0005:
        return False, "Theta dominance - decay too high"
    
    return True, "Time window valid"


def validate_quantity_ptq(tick: Dict, ticks: List[Dict]) -> Tuple[bool, str]:
    """Q = Quantity validation (PTQ)
    Uses dynamic thresholds based on current trading mode
    """
    from config.constants import PAPER_TRADING
    
    # Paper trading = always valid (for testing)
    if PAPER_TRADING:
        return True, "Paper mode - qty OK"
    
    current_volume = tick.get('volume', 0)
    
    if len(ticks) < 60:
        return False, "Insufficient history"
    
    recent_volumes = [t.get('volume', 0) for t in ticks[-60:]]
    recent_avg = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    
    if recent_avg == 0:
        return False, "No volume data"
    
    # Volume expansion check - use mode-specific threshold
    min_ratio = get_threshold('min_volume_ratio') or CONFIG.get('entry_filters', {}).get('min_volume_ratio', 0.8)
    volume_ratio = current_volume / recent_avg
    if volume_ratio < min_ratio:
        mode = get_current_mode()
        return False, f"Volume too low (ratio: {volume_ratio:.2f}, need: {min_ratio}) [{mode}]"
    
    # Spread check - use mode-specific threshold
    spread = tick['ask'] - tick['bid']
    spread_pct_val = (spread / tick['ltp']) * 100
    max_spread = get_threshold('spread_limit_pct') or CONFIG.get('data_hygiene', {}).get('spread_limit_pct', 0.5)
    
    if spread_pct_val > max_spread:
        return False, f"Wide spread ({spread_pct_val:.2f}%)"
    
    return True, "Volume confirmed"


# =========================================================
# GREEKS FILTER
# =========================================================

def greek_gate(greeks: Dict, day_type: str) -> Tuple[bool, str]:
    """Filter trades based on Greeks - returns (pass, reason)
    Uses dynamic thresholds based on current trading mode
    """
    delta = abs(greeks.get('delta', 0))
    gamma = greeks.get('gamma', 0)
    theta_sec = greeks.get('theta_sec', 0)
    
    # Get thresholds (dynamic from mode_switch or static from config)
    delta_min = get_threshold('delta_min') or CONFIG.get('greeks_limits', {}).get('delta_min', 0.20)
    delta_max = get_threshold('delta_max') or CONFIG.get('greeks_limits', {}).get('delta_max', 0.85)
    
    if not (delta_min <= delta <= delta_max):
        mode = get_current_mode()
        return False, f"Delta {delta:.3f} out of range ({delta_min}-{delta_max}) [{mode}]"

    # Gamma check - use mode-specific thresholds
    if day_type == "EXPIRY":
        gamma_max = get_threshold('gamma_expiry_max') or GAMMA_EXPIRY_MAX
    else:
        gamma_max = get_threshold('gamma_normal_max') or GAMMA_NORMAL_MAX
    
    if gamma > gamma_max:
        return False, f"Gamma {gamma:.4f} > {gamma_max}"

    # Theta check - use mode-specific threshold
    theta_limit = get_threshold('theta_sec_limit') or CONFIG.get('greeks_limits', {}).get('theta_sec_limit', 0.25)
    if theta_sec > theta_limit:
        return False, f"Theta/sec {theta_sec:.5f} > {theta_limit}"

    return True, "Greeks OK"


def detect_day_type(greeks: Dict, time_to_expiry_sec: float) -> str:
    """Detect if it's a normal or expiry day"""
    from utils.helpers import is_expiry_date
    
    if is_expiry_date():
        return "EXPIRY"

    if time_to_expiry_sec <= 3600:
        return "EXPIRY"

    if greeks['theta_sec'] > 2 * THETA_SEC_LIMIT:
        return "EXPIRY"

    if greeks['gamma'] > 0.10 and time_to_expiry_sec < 5400:
        return "EXPIRY"

    return "NORMAL"
