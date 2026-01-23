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
    
    # Timestamp freshness (< 500ms old)
    tick_age_ms = current_time_ms() - tick['timestamp']
    if tick_age_ms > 500:
        return False, f"Stale tick ({tick_age_ms}ms old)"
    
    # Latency check
    latency = calc_latency_ms(tick)
    if latency > LATENCY_LIMIT_MS:
        return False, f"High latency ({latency:.1f}ms)"
    
    # Spread check
    spread = spread_pct(tick)
    if spread > SPREAD_LIMIT_PCT:
        return False, f"Wide spread ({spread:.3f}%)"
    
    # Volume sanity
    if tick.get('volume', 0) < CONFIG['data_hygiene']['min_volume']:
        return False, "Low volume"
    
    return True, "OK"


# =========================================================
# PTQ VALIDATION
# =========================================================

def calculate_vwap(ticks: List[Dict], period: int = 60) -> float:
    """Calculate VWAP from recent ticks"""
    if len(ticks) == 0:
        return 0
    
    recent = ticks[-period:] if len(ticks) > period else ticks
    total_pv = sum(t['ltp'] * t.get('volume', 10000) for t in recent)
    total_v = sum(t.get('volume', 10000) for t in recent)
    
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
    current_price = tick['ltp']
    
    if len(ticks) < 60:
        return False, "Insufficient history"
    
    vwap = calculate_vwap(ticks)
    candle = analyze_candle_quality(ticks)
    
    # Check for chop
    recent_prices = [t['ltp'] for t in ticks[-60:]]
    recent_range = max(recent_prices) - min(recent_prices)
    is_chop = recent_range < current_price * CHOP_THRESHOLD
    
    if is_chop:
        return False, "Chop market"
    
    # Level break + momentum (CALL)
    if current_price > vwap and candle['body_pct'] > 20:
        return True, "Level break above VWAP"
    
    # Level break + momentum (PUT)
    if current_price < vwap and candle['body_pct'] > 20:
        return True, "Level break below VWAP"
    
    # Rejection pattern
    if candle['wick_pct'] > 35:
        if current_price < vwap and candle['direction'] == 1:
            return True, "Rejection from VWAP (bullish)"
        elif current_price > vwap and candle['direction'] == -1:
            return True, "Rejection from VWAP (bearish)"
    
    # Directional move away from VWAP
    vwap_dist = abs(current_price - vwap) / vwap
    if vwap_dist > 0.0015:
        if current_price > vwap:
            return True, "Price above VWAP"
        elif current_price < vwap:
            return True, "Price below VWAP"
    
    return False, "No valid price setup"


def validate_time_ptq(greeks: Dict) -> Tuple[bool, str]:
    """T = Time validation (PTQ)"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    
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
    """Q = Quantity validation (PTQ)"""
    current_volume = tick.get('volume', 0)
    
    if len(ticks) < 60:
        return False, "Insufficient history"
    
    recent_volumes = [t.get('volume', 0) for t in ticks[-60:]]
    recent_avg = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    
    if recent_avg == 0:
        return False, "No volume data"
    
    # Volume expansion check - use config value
    min_ratio = CONFIG.get('entry_filters', {}).get('min_volume_ratio', 0.8)
    volume_ratio = current_volume / recent_avg
    if volume_ratio < min_ratio:
        return False, f"Volume too low (ratio: {volume_ratio:.2f})"
    
    # Spread check - use config value (relaxed to 0.5% for normal liquidity)
    spread = tick['ask'] - tick['bid']
    spread_pct_val = (spread / tick['ltp']) * 100
    max_spread = CONFIG.get('data_hygiene', {}).get('spread_limit_pct', 0.5)
    
    if spread_pct_val > max_spread:
        return False, f"Wide spread ({spread_pct_val:.2f}%)"
    
    return True, "Volume confirmed"


# =========================================================
# GREEKS FILTER
# =========================================================

def greek_gate(greeks: Dict, day_type: str) -> bool:
    """Filter trades based on Greeks"""
    if not (DELTA_MIN <= abs(greeks['delta']) <= DELTA_MAX):
        return False

    if day_type == "NORMAL" and greeks['gamma'] > GAMMA_NORMAL_MAX:
        return False

    if day_type == "EXPIRY" and greeks['gamma'] > GAMMA_EXPIRY_MAX:
        return False

    if greeks['theta_sec'] > THETA_SEC_LIMIT:
        return False

    return True


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
