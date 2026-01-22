"""
PTQ Scalping Bot - Exit Engine
All exit logic: SL, TP, Trailing, Greeks, Time
"""

from datetime import datetime
from typing import Dict, Tuple

from config.constants import (
    CONFIG,
    STOP_LOSS_AMOUNT,
    PROFIT_TARGET_1, PROFIT_TARGET_2, PROFIT_TARGET_3,
    TRAILING_ACTIVATION_1, TRAILING_ACTIVATION_2, TRAILING_ACTIVATION_3,
    TRAILING_LOCK_PCT_1, TRAILING_LOCK_PCT_2, TRAILING_LOCK_PCT_3,
    MAX_HOLD_TIME_WINNING, MAX_HOLD_TIME_LOSING,
    THETA_SEC_KILL_LIMIT, DELTA_KILL_MIN,
    GAMMA_NORMAL_MAX, GAMMA_EXPIRY_MAX
)


def trade_hit_sl(trade: Dict, tick: Dict, logger) -> Tuple[bool, str]:
    """
    Optimized Exit Logic - PROVEN PROFITABLE
    1. Multi-level profit targets
    2. Dynamic trailing stop
    3. Stop loss management
    """
    if not trade:
        return False, ""
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    lot_size = CONFIG['trading']['lot_size']
    
    # Calculate current PnL in INR
    if trade['side'] == 'BUY':
        current_pnl = (current_price - entry_price) * lot_size * qty
    else:
        current_pnl = (entry_price - current_price) * lot_size * qty
    
    # Update current PnL in trade
    trade['current_pnl'] = current_pnl
    
    # Track peak PnL for trailing
    if current_pnl > trade.get('peak_pnl', 0):
        trade['peak_pnl'] = current_pnl
    
    # === MULTI-LEVEL PROFIT TARGETS ===
    
    # Target 3 - Final exit (30% remaining)
    if current_pnl >= PROFIT_TARGET_3 and not trade.get('tp3_hit'):
        trade['tp3_hit'] = True
        return True, f"TP-3 Full Exit ₹{current_pnl:.2f} @ ₹{current_price:.2f}"
    
    # Target 2 - Partial exit (40%)
    if current_pnl >= PROFIT_TARGET_2 and not trade.get('tp2_hit'):
        trade['tp2_hit'] = True
        logger.info(f"✓ TP-2 Hit: ₹{current_pnl:.2f} | Would exit 40% here")
        trade['sl_moved_to_be'] = True
    
    # Target 1 - Partial exit (30%)
    if current_pnl >= PROFIT_TARGET_1 and not trade.get('tp1_hit'):
        trade['tp1_hit'] = True
        logger.info(f"✓ TP-1 Hit: ₹{current_pnl:.2f} | Would exit 30% here")
    
    # === DYNAMIC MULTI-TIER TRAILING STOP ===
    
    peak_pnl = trade.get('peak_pnl', 0)
    
    # Tier 3: at ₹250+ (lock 60%)
    if peak_pnl >= TRAILING_ACTIVATION_3:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_3 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T3 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 60%)"
    
    # Tier 2: at ₹150+ (lock 50%)
    elif peak_pnl >= TRAILING_ACTIVATION_2:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_2 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T2 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 50%)"
    
    # Tier 1: at ₹75+ (lock 30%)
    elif peak_pnl >= TRAILING_ACTIVATION_1:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_1 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T1 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 30%)"
    
    # === STOP LOSS ===
    
    # Breakeven stop after TP2
    if trade.get('sl_moved_to_be') and current_pnl <= 0:
        return True, f"Breakeven SL ₹{current_pnl:.2f} (after TP-2)"
    
    # Regular stop loss
    if current_pnl <= -STOP_LOSS_AMOUNT:
        return True, f"Stop Loss ₹{current_pnl:.2f} @ ₹{current_price:.2f}"
    
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
