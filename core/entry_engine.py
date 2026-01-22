"""
PTQ Scalping Bot - Entry Signal Engine
PTQ validation and entry signal generation
"""

from typing import Dict, Tuple, List

from utils.greeks import GreeksCalculator
from config.constants import CONFIG
from core.validators import (
    validate_price_ptq, validate_time_ptq, 
    validate_quantity_ptq, greek_gate
)


# Track recent ticks for analysis
MAX_RECENT_TICKS = 120  # 2 minutes of data


def entry_signal(tick: Dict, recent_ticks: List[Dict], day_type: str) -> Tuple[bool, str]:
    """
    PTQ Entry Signal - PROVEN PROFITABLE STRATEGY
    Price + Time + Quantity validation - ALL must pass
    """
    # Need minimum history
    if len(recent_ticks) < 60:
        return False, "Insufficient history"
    
    # Calculate Greeks
    current_price = tick['ltp']
    strike = round(current_price / 50) * 50
    
    greeks = GreeksCalculator.calculate(
        spot_price=current_price,
        strike_price=strike,
        time_to_expiry=7/365.0,  # Weekly expiry
        volatility=0.15,
        risk_free_rate=0.07,
        option_type='CE'
    )
    
    # === PTQ Validation Flow ===
    
    # 1. Price validation
    price_ok, price_msg = validate_price_ptq(tick, recent_ticks)
    if not price_ok:
        return False, f"Price: {price_msg}"
    
    # 2. Time validation
    time_ok, time_msg = validate_time_ptq(greeks)
    if not time_ok:
        return False, f"Time: {time_msg}"
    
    # 3. Quantity validation
    quantity_ok, quantity_msg = validate_quantity_ptq(tick, recent_ticks)
    if not quantity_ok:
        return False, f"Quantity: {quantity_msg}"
    
    # 4. Volume confirmation (if enabled)
    if CONFIG['entry_filters'].get('volume_confirmation_required', False):
        current_volume = tick.get('volume', 0)
        if len(recent_ticks) >= 60:
            recent_volumes = [t.get('volume', 0) for t in recent_ticks[-60:]]
            avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
            if avg_vol > 0:
                vol_ratio = current_volume / avg_vol
                min_ratio = CONFIG['entry_filters'].get('min_volume_ratio', 1.2)
                if vol_ratio < min_ratio:
                    return False, f"Volume too low (ratio: {vol_ratio:.2f}, need: {min_ratio})"
    
    # 5. Greeks gate
    if not greek_gate(greeks, day_type):
        return False, "Greeks: Out of range"
    
    # === ALL PASS - ENTRY ALLOWED ===
    return True, f"PTQ ✓ | P: {price_msg[:20]} | T: {time_msg} | Q: {quantity_msg[:20]}"
