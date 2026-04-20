"""
PTQ Scalping Bot - Entry Signal Engine
SMART SCALP v3.4 - Multi-Factor Scoring System
"""

from typing import Dict, Tuple, List

from utils.greeks import GreeksCalculator
from config.constants import CONFIG, PAPER_TRADING
from core.risk.validators import (
    validate_price_ptq, validate_time_ptq, 
    validate_quantity_ptq, greek_gate
)
from core.risk.session_trend import (
    start_trading_session, update_market_price, 
    can_trade_ce, can_trade_pe, get_trend_display
)
from config.constants import (
    MIN_CONFIDENCE, MIN_CONFIDENCE_AFTER_3SL,
    MIN_ENTRY_PREMIUM, MAX_ENTRY_PREMIUM
)

# Import SMART SCALP v3.4 Strategy
try:
    from strategies.smart_scalp_v3 import smart_scalp_signal, get_strategy
    HAS_SMART_SCALP = True
except ImportError:
    HAS_SMART_SCALP = False
    import logging
    logging.warning("⚠️ SMART SCALP v3.4 not available, falling back to PTQ")


# Track recent ticks for analysis
MAX_RECENT_TICKS = 120  # 2 minutes of data

# Last signal params (for use by other modules)
last_signal_params = {}


def entry_signal(tick: Dict, recent_ticks: List[Dict], day_type: str, instrument_type: str = "") -> Tuple[bool, str]:
    """
    Entry Signal Generator - SMART SCALP v3.4 + Session Trend + PTQ validation
    
    Uses multi-factor scoring system:
    - 9 bullish factors + 9 bearish factors
    - Requires 4+ score and 70%+ confidence
    - Fixed SL 6pts / TP 12pts (R:R 1:2)
    
    Session Trend Logic:
    - If price > opening: BULLISH (CE allowed)
    - If price < opening: BEARISH (PE allowed)
    - If price ≈ opening: SIDEWAYS (both allowed v3.3)
    """
    global last_signal_params
    
    # Need minimum history - reduced since strategy uses Yahoo data
    if len(recent_ticks) < 10:
        return False, "Warming up..."
    
    # Update session trend with current price
    current_price = tick.get('ltp', tick.get('price', 0))
    update_market_price(current_price)
    trend_str = get_trend_display()
    
    # === SMART SCALP v3.0 STRATEGY ===
    if HAS_SMART_SCALP:
        should_enter, message, params = smart_scalp_signal(recent_ticks)
        
        if should_enter:
            # Get instrument type from strategy params
            instrument = params.get('direction', 'CE')
            confidence = params.get('confidence', 0)
            
            # ═══════════════════════════════════════════════════════════════
            # CONFIDENCE FILTER (v3.4) - Minimum 70%, 85% after 3 consecutive SL
            # ═══════════════════════════════════════════════════════════════
            try:
                from core.engines.state_machine import trading_state
                consecutive_losses = trading_state.consecutive_losses
            except:
                consecutive_losses = 0
            
            # After 3 consecutive SL, require higher confidence
            required_conf = MIN_CONFIDENCE_AFTER_3SL if consecutive_losses >= 3 else MIN_CONFIDENCE
            
            if confidence < required_conf:
                if consecutive_losses >= 3:
                    return False, f"Low conf {confidence}% < {required_conf}% (3+ SL streak)"
                return False, f"Low confidence {confidence}% < {required_conf}%"
            
            # ═══════════════════════════════════════════════════════════════
            # ENTRY PRICE FILTER (v3.1) - ATM nearby ₹90-150 range
            # ═══════════════════════════════════════════════════════════════
            current_premium = tick.get('ltp', 0)
            if current_premium < MIN_ENTRY_PREMIUM:
                return False, f"Premium too low ₹{current_premium:.0f} < ₹{MIN_ENTRY_PREMIUM:.0f}"
            if current_premium > MAX_ENTRY_PREMIUM:
                return False, f"Premium too high ₹{current_premium:.0f} > ₹{MAX_ENTRY_PREMIUM:.0f}"
            
            # Get RSI from strategy details for reversal detection
            details = params.get('details', {})
            rsi = details.get('rsi', 50)
            
            # Check session trend gate (now with RSI for reversal trades)
            if instrument == 'CE':
                ce_ok, ce_msg = can_trade_ce(rsi)
                if not ce_ok:
                    return False, f"{ce_msg}"
            else:  # PE
                pe_ok, pe_msg = can_trade_pe(rsi)
                if not pe_ok:
                    return False, f"{pe_msg}"
            
            # Add trend info to message
            full_message = f"{message} | {trend_str}"
            
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
            
            return True, full_message
        else:
            last_signal_params = {}
            return False, message
    
    # === FALLBACK: Original PTQ Strategy ===
    return _ptq_entry_signal(tick, recent_ticks, day_type)


def _calculate_greeks(tick: Dict) -> Dict:
    """Calculate Greeks for validation (uses smart caching for optimization)"""
    option_price = tick['ltp']
    # BUG FIX: Use NIFTY spot price (~23000), not option premium (~200)
    spot_price = tick.get('spot_price', 0)
    if spot_price < 10000:  # Fallback if spot_price missing
        spot_price = option_price * 100  # Rough estimate
    
    strike = round(spot_price / 50) * 50  # ATM strike from spot
    
    # Use cached Greeks calculation (5-sec TTL + 1% spot move invalidation)
    return GreeksCalculator.calculate_cached(
        spot_price=spot_price,
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
    from config.constants import CE_QUANTITY
    return last_signal_params.get('quantity', CE_QUANTITY)


def get_signal_sl_points() -> float:
    """Get SL points from last signal"""
    from config.constants import SL_POINTS_FIXED
    return last_signal_params.get('sl_points', SL_POINTS_FIXED)


def get_signal_tp_points() -> float:
    """Get TP points from last signal"""
    from config.constants import TP_POINTS_FIXED
    return last_signal_params.get('tp_points', TP_POINTS_FIXED)
