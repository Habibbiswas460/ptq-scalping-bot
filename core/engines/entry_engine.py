"""
PTQ Scalping Bot - Entry Signal Engine
SMART SCALP v3.0 - Multi-Factor Scoring System
"""

from typing import Dict, Tuple, List

from utils.greeks import GreeksCalculator
from config.constants import CONFIG, PAPER_TRADING
from core.risk.validators import (
    validate_price_ptq, validate_time_ptq, 
    validate_quantity_ptq, greek_gate
)

# Import SMART SCALP v3.0 Strategy
try:
    from strategies.smart_scalp_v3 import smart_scalp_signal, get_strategy
    HAS_SMART_SCALP = True
except ImportError:
    HAS_SMART_SCALP = False
    import logging
    logging.warning("⚠️ SMART SCALP v3.0 not available, falling back to PTQ")


# Track recent ticks for analysis
MAX_RECENT_TICKS = 120  # 2 minutes of data

# Last signal params (for use by other modules)
last_signal_params = {}


def entry_signal(tick: Dict, recent_ticks: List[Dict], day_type: str) -> Tuple[bool, str]:
    """
    Entry Signal Generator - SMART SCALP v3.0 + PTQ validation
    
    Uses multi-factor scoring system:
    - 10 bullish factors + 10 bearish factors
    - Requires 5+ score and 60%+ confidence
    - Dynamic SL/TP based on ATR and confidence
    
    NOTE: Strategy now fetches real NIFTY data from Yahoo internally,
    so we don't need many ticks for warmup.
    """
    global last_signal_params
    
    # Need minimum history - reduced since strategy uses Yahoo data
    if len(recent_ticks) < 10:
        return False, "Warming up..."
    
    # === SMART SCALP v3.0 STRATEGY ===
    if HAS_SMART_SCALP:
        should_enter, message, params = smart_scalp_signal(recent_ticks)
        
        if should_enter:
            # Store params for use by trade_manager
            last_signal_params = params
            
            # Additional PTQ validation (optional - for extra safety)
            if not PAPER_TRADING:
                # Time validation
                greeks = _calculate_greeks(tick)
                time_ok, time_msg = validate_time_ptq(greeks)
                if not time_ok:
                    return False, f"Time: {time_msg}"
                
                # Greeks gate
                greek_pass, greek_msg = greek_gate(greeks, day_type)
                if not greek_pass:
                    return False, f"Greeks: {greek_msg}"
            
            return True, message
        else:
            last_signal_params = {}
            return False, message
    
    # === FALLBACK: Original PTQ Strategy ===
    return _ptq_entry_signal(tick, recent_ticks, day_type)


def _calculate_greeks(tick: Dict) -> Dict:
    """Calculate Greeks for validation"""
    current_price = tick['ltp']
    strike = round(current_price / 50) * 50
    
    return GreeksCalculator.calculate(
        spot_price=current_price,
        strike_price=strike,
        time_to_expiry=7/365.0,
        volatility=0.15,
        risk_free_rate=0.07,
        option_type='CE'
    )


def _ptq_entry_signal(tick: Dict, recent_ticks: List[Dict], day_type: str) -> Tuple[bool, str]:
    """
    Fallback PTQ Entry Signal - Original PROVEN PROFITABLE STRATEGY
    Price + Time + Quantity validation - ALL must pass
    """
    greeks = _calculate_greeks(tick)
    
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
    greek_pass, greek_msg = greek_gate(greeks, day_type)
    if not greek_pass:
        return False, f"Greeks: {greek_msg}"
    
    # === ALL PASS - ENTRY ALLOWED ===
    return True, f"PTQ ✓ | P: {price_msg[:20]} | T: {time_msg} | Q: {quantity_msg[:20]}"


def get_last_signal_params() -> Dict:
    """Get params from last successful signal (used by trade_manager)"""
    return last_signal_params.copy()


def get_signal_direction() -> str:
    """Get direction from last signal: CE or PE"""
    return last_signal_params.get('direction', 'CE')


def get_signal_quantity() -> int:
    """Get quantity from last signal"""
    return last_signal_params.get('quantity', 260)


def get_signal_sl_points() -> float:
    """Get SL points from last signal"""
    return last_signal_params.get('sl_points', 9)


def get_signal_tp_points() -> float:
    """Get TP points from last signal"""
    return last_signal_params.get('tp_points', 18)
