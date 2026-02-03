"""
PTQ Scalping Bot - Exit Engine
With Trailing Stop Loss (TSL) Support
Updated: 2026-01-28 - TSL enabled
"""

from datetime import datetime
from typing import Dict, Tuple

from config.constants import (
    CONFIG,
    SL_POINTS_FIXED, TP_POINTS_FIXED,
    MAX_LOSS_PER_TRADE_CE, MAX_LOSS_PER_TRADE_PE,
    PROFIT_TARGET_CE, PROFIT_TARGET_PE,
    MAX_HOLD_TIME_WINNING, MAX_HOLD_TIME_LOSING,
    THETA_SEC_KILL_LIMIT, DELTA_KILL_MIN,
    GAMMA_NORMAL_MAX, GAMMA_EXPIRY_MAX
)

# TSL Configuration from bot_config.json
TSL_CONFIG = CONFIG.get('risk_management', {}).get('trailing_sl', {})
TSL_ENABLED = TSL_CONFIG.get('enabled', False)
TSL_BREAKEVEN = TSL_CONFIG.get('breakeven', {})
TSL_STEP_LEVELS = TSL_CONFIG.get('step_levels', [])


def get_trailing_sl(trade: Dict, price_diff: float) -> float:
    """
    Calculate trailing stop loss based on current profit.
    Returns the SL level in points (from entry).
    
    TSL Logic:
    1. Initial SL = -8 points (fixed)
    2. Breakeven: When profit >= 5 pts, move SL to +1 pt (lock ₹65)
    3. Step levels: Lock progressively more profit as price moves up
    """
    if not TSL_ENABLED:
        return -SL_POINTS_FIXED  # Fixed SL
    
    # Get max profit seen in this trade
    max_profit = trade.get('max_profit_points', 0)
    
    # Update max profit if current is higher
    if price_diff > max_profit:
        trade['max_profit_points'] = price_diff
        max_profit = price_diff
    
    # Start with fixed SL
    trailing_sl = -SL_POINTS_FIXED  # -8 points
    
    # Breakeven activation
    be_activation = TSL_BREAKEVEN.get('activation_points', 5)
    be_buffer = TSL_BREAKEVEN.get('buffer_points', 1)
    
    if max_profit >= be_activation:
        trailing_sl = be_buffer  # Move SL to +1 (breakeven + buffer)
    
    # Step levels - find highest applicable level
    for level in TSL_STEP_LEVELS:
        profit_trigger = level.get('profit_points', 0)
        lock_points = level.get('lock_points', 0)
        
        if max_profit >= profit_trigger:
            trailing_sl = lock_points  # Lock this much profit
    
    return trailing_sl


def trade_hit_sl(trade: Dict, tick: Dict, logger) -> Tuple[bool, str]:
    """
    Exit Logic with Trailing Stop Loss (TSL)
    
    TSL Flow:
    1. Initial: SL = -8 pts, TP = +16 pts
    2. At +5 pts: Move SL to +1 pt (breakeven)
    3. At +8 pts: Lock +4 pts profit
    4. At +12 pts: Lock +7 pts profit
    5. At +16 pts: Lock +11 pts profit (or hit TP)
    """
    if not trade:
        return False, ""
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    direction = trade.get('direction', 'CE')
    
    # Fixed TP
    tp_points = TP_POINTS_FIXED  # 16 points
    
    # Max loss capped
    max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
    
    # Calculate price difference (points)
    if trade['side'] == 'BUY':
        price_diff = current_price - entry_price
    else:
        price_diff = entry_price - current_price
    
    # Calculate current PnL in INR
    current_pnl = price_diff * qty
    
    # === CAP PnL TO MAX LOSS (CRITICAL FIX) ===
    # Never let actual loss exceed the max allowed
    if current_pnl < 0:
        current_pnl = max(-max_loss, current_pnl)
    
    # Update trade state
    trade['current_pnl'] = current_pnl
    trade['price_diff'] = price_diff
    
    # === TRAILING STOP LOSS ===
    trailing_sl = get_trailing_sl(trade, price_diff)
    trade['current_tsl'] = trailing_sl  # Store for logging
    
    # Check TSL hit
    if price_diff <= trailing_sl:
        if trailing_sl > 0:
            # TSL hit in profit - we locked some profit
            locked_pnl = trailing_sl * qty
            return True, f"TSL Hit | {direction} | Locked +{trailing_sl}pts @ ₹{current_price:.2f} | Profit: ₹{locked_pnl:.0f}"
        elif trailing_sl == 0:
            # Breakeven exit
            return True, f"TSL Breakeven | {direction} @ ₹{current_price:.2f} | P&L: ₹0"
        else:
            # Regular SL hit - ALWAYS cap to max loss
            capped_pnl = max(-max_loss, current_pnl)
            trade['current_pnl'] = capped_pnl  # Update with capped value
            return True, f"SL Hit | {direction} | {trailing_sl}pts @ ₹{current_price:.2f} | Loss: ₹{capped_pnl:.0f}"
    
    # TAKE PROFIT - FIXED 16 points
    if price_diff >= tp_points:
        return True, f"TP Hit | {direction} | +{tp_points}pts @ ₹{current_price:.2f} | Profit: ₹{current_pnl:.0f}"
    
    # Log TSL status periodically
    max_profit = trade.get('max_profit_points', 0)
    if logger and max_profit >= 5 and TSL_ENABLED:
        if not trade.get('_tsl_logged'):
            logger.info(f"📈 TSL Active | Max: +{max_profit:.1f}pts | SL now: {trailing_sl:+.1f}pts")
            trade['_tsl_logged'] = True
    
    return False, ""


def greek_exit(greeks: Dict, day_type: str) -> Tuple[bool, str]:
    """Exit based on Greeks deterioration - KILL conditions"""
    # Theta decay kill
    if greeks['theta_sec'] > THETA_SEC_KILL_LIMIT:
        return True, f"Theta decay KILL: {greeks['theta_sec']:.4f} > {THETA_SEC_KILL_LIMIT}"
    
    # Gamma explosion
    limit = GAMMA_EXPIRY_MAX if day_type == "EXPIRY" else GAMMA_NORMAL_MAX
    if greeks['gamma'] > limit * 1.5:
        return True, f"Gamma spike: {greeks['gamma']:.3f} > {limit * 1.5:.3f}"
    
    # Delta kill - too far out of range
    if abs(greeks['delta']) < DELTA_KILL_MIN:
        return True, f"Delta KILL (too low): {greeks['delta']:.3f} < {DELTA_KILL_MIN}"
    
    return False, ""


def time_exit(trade: Dict) -> Tuple[bool, str]:
    """
    Time Exit - Dynamic based on position status
    - Losing trades: 30 min max hold
    - Winning trades: 45 min max hold
    """
    if not trade:
        return False, ""
    
    hold_time = (datetime.now() - trade['entry_time']).total_seconds()
    current_pnl = trade.get('current_pnl', 0)
    
    # Dynamic time exit based on position status
    if current_pnl < 0:
        # Losing position - exit faster
        if hold_time > MAX_HOLD_TIME_LOSING:
            return True, f"Time Exit (losing) | Held: {hold_time/60:.1f}min"
    else:
        # Winning position - allow more time
        if hold_time > MAX_HOLD_TIME_WINNING:
            return True, f"Time Exit (winning) | Held: {hold_time/60:.1f}min"
    
    # Exit 5 min before market close
    now = datetime.now()
    if now.hour == 15 and now.minute >= 25:
        return True, "Near market close (5 min warning)"
    
    return False, ""


def check_exit_conditions(trade: Dict, tick: Dict, greeks: Dict, 
                          day_type: str, logger) -> Tuple[bool, str]:
    """Check all exit conditions"""
    # SL/Target check
    sl_hit, sl_reason = trade_hit_sl(trade, tick, logger)
    if sl_hit:
        return True, sl_reason
    
    # Greeks exit
    greek_hit, greek_reason = greek_exit(greeks, day_type)
    if greek_hit:
        return True, greek_reason
    
    # Time exit
    time_hit, time_reason = time_exit(trade)
    if time_hit:
        return True, time_reason
    
    return False, ""
