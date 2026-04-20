"""
PTQ Scalping Bot - Exit Engine
PULLBACK & PROTECT Strategy - Step Trailing + Smart Exit
Updated: 2026-02-12 - New exit logic
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

# ============================================
# PULLBACK & PROTECT EXIT CONFIGURATION (v3.3 - Improved R:R)
# ============================================
# Hard SL: 6 points (exit immediately) - reduced from 8 for better R:R
HARD_SL_POINTS = 6

# PHASE 6: Earlier trailing activation (v3.3)
# Breakeven trigger: Move SL to +2 when profit >= 5 points
BREAKEVEN_TRIGGER = 5
BREAKEVEN_BUFFER = 2  # Lock +2 point profit

# Dynamic trailing: Keep SL 3 points below current price after breakeven
# Tighter trail = lock more profit when running
TRAILING_DISTANCE = 3

# Smart RSI Exit thresholds
RSI_OVERBOUGHT = 80  # Exit CE when RSI > 80
RSI_OVERSOLD = 20    # Exit PE when RSI < 20

# RSI Reversal Exit thresholds (v3.3 - exit on momentum shift)
RSI_REVERSAL_CE_EXIT = 60   # CE: exit if RSI drops from >75 to <60
RSI_REVERSAL_PE_EXIT = 40   # PE: exit if RSI rises from <25 to >40

# Early Momentum Loss Cut (v3.3)
EARLY_LOSS_CUT_POINTS = 4    # Exit early if price drops 4 pts quickly
EARLY_LOSS_CUT_TIME_SEC = 30 # Within 30 seconds of entry

# Max hold time: 15 minutes (900 seconds)
MAX_HOLD_TIME_SEC = 900


def get_step_trailing_sl(trade: Dict, price_diff: float) -> Tuple[float, str]:
    """
    STEP TRAILING STOP LOSS - Pullback & Protect Strategy (OPTIMIZED)
    
    Logic:
    1. Initial SL = -6 points (hard SL)
    2. If profit >= 5 pts → Move SL to +2 (breakeven lock)
    3. If profit > 5 pts → Trail SL 3 points below MAX profit (never decreases!)
    
    Returns:
        (sl_level, sl_status)
        sl_level: SL in points from entry (negative = loss, positive = locked profit)
        sl_status: Human-readable status
    """
    # Track max profit seen
    max_profit = trade.get('max_profit_points', 0)
    if price_diff > max_profit:
        trade['max_profit_points'] = price_diff
        max_profit = price_diff
    
    # Track highest SL level (SL should NEVER decrease!)
    highest_sl = trade.get('highest_sl', -HARD_SL_POINTS)
    
    # Start with hard SL
    trailing_sl = -HARD_SL_POINTS  # -6 points
    sl_status = "HARD_SL"
    
    # Step 1: Breakeven activation (when we've seen +5 profit)
    if max_profit >= BREAKEVEN_TRIGGER:
        # Calculate SL based on max profit (not current price!)
        # SL = max_profit - trailing_distance, but minimum is BREAKEVEN_BUFFER
        trailing_sl = max(BREAKEVEN_BUFFER, max_profit - TRAILING_DISTANCE)
        sl_status = f"TRAILING(+{trailing_sl:.1f})" if trailing_sl > BREAKEVEN_BUFFER else "BREAKEVEN"
    
    # CRITICAL: SL should NEVER decrease!
    if trailing_sl > highest_sl:
        trade['highest_sl'] = trailing_sl
        highest_sl = trailing_sl
    else:
        trailing_sl = highest_sl
        if trailing_sl > BREAKEVEN_BUFFER:
            sl_status = f"LOCKED(+{trailing_sl:.1f})"
        elif trailing_sl > 0:
            sl_status = "BREAKEVEN"
    
    return trailing_sl, sl_status


def check_hard_sl(trade: Dict, tick: Dict, logger) -> Tuple[bool, str]:
    """
    PRIORITY 1: Hard Stop Loss Check
    Exit immediately if loss >= 6 points
    """
    if not trade:
        return False, ""
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    direction = trade.get('direction', 'CE')
    
    # Calculate price difference
    if trade['side'] == 'BUY':
        price_diff = current_price - entry_price
    else:
        price_diff = entry_price - current_price
    
    # Update trade state
    trade['price_diff'] = price_diff
    trade['current_pnl'] = price_diff * qty
    
    # Get step trailing SL
    trailing_sl, sl_status = get_step_trailing_sl(trade, price_diff)
    trade['current_tsl'] = trailing_sl
    trade['tsl_status'] = sl_status
    
    # Max loss cap
    max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
    
    # Check if SL hit
    if price_diff <= trailing_sl:
        if trailing_sl > 0:
            # Trailing SL hit in profit - locked profit!
            locked_pnl = trailing_sl * qty
            return True, f"✅ TRAILING PROFIT | {direction} | Locked +{trailing_sl:.1f}pts @ ₹{current_price:.2f} | Profit: ₹{locked_pnl:.0f}"
        elif trailing_sl >= 0:
            # Breakeven exit
            return True, f"⚖️ BREAKEVEN EXIT | {direction} @ ₹{current_price:.2f}"
        else:
            # Hard SL hit - cap to max loss
            actual_loss = min(abs(price_diff * qty), max_loss)
            trade['current_pnl'] = -actual_loss
            return True, f"🛑 HARD SL HIT | {direction} | -{HARD_SL_POINTS}pts @ ₹{current_price:.2f} | Loss: ₹{actual_loss:.0f}"
    
    # Check take profit (20 points)
    if price_diff >= TP_POINTS_FIXED:
        profit = price_diff * qty
        return True, f"🎯 TAKE PROFIT | {direction} | +{price_diff:.1f}pts @ ₹{current_price:.2f} | Profit: ₹{profit:.0f}"
    
    return False, ""


def smart_rsi_exit(trade: Dict, rsi: float = None) -> Tuple[bool, str]:
    """
    PRIORITY 3: Smart RSI Exit
    
    Exit when momentum exhausted:
    - CE trade: Exit if RSI > 80 (overbought - likely reversal)
    - PE trade: Exit if RSI < 20 (oversold - likely bounce)
    
    Only triggers if in profit to lock gains.
    """
    if not trade or rsi is None:
        return False, ""
    
    direction = trade.get('direction', 'CE')
    price_diff = trade.get('price_diff', 0)
    current_pnl = trade.get('current_pnl', 0)
    
    # Only exit on RSI if we're in profit
    if price_diff < 2:
        return False, ""
    
    # CE trade: Exit on extreme overbought
    if direction == 'CE' and rsi > RSI_OVERBOUGHT:
        return True, f"\U0001f4ca RSI EXIT | CE | RSI={rsi:.0f} (OB>{RSI_OVERBOUGHT}) | Lock profit: \u20b9{current_pnl:.0f}"
    
    # PE trade: Exit on extreme oversold
    if direction == 'PE' and rsi < RSI_OVERSOLD:
        return True, f"\U0001f4ca RSI EXIT | PE | RSI={rsi:.0f} (OS<{RSI_OVERSOLD}) | Lock profit: \u20b9{current_pnl:.0f}"
    
    return False, ""


def rsi_reversal_exit(trade: Dict, rsi: float = None) -> Tuple[bool, str]:
    """
    PRIORITY 3b: RSI Reversal Exit (v3.3)
    
    Exit when RSI shifts from extreme back to neutral:
    - PE: RSI was <25 (oversold), now rises to >40 → momentum reversing, exit
    - CE: RSI was >75 (overbought), now drops to <60 → momentum reversing, exit
    
    Tracks RSI extremes per trade and exits on reversal.
    """
    if not trade or rsi is None:
        return False, ""
    
    direction = trade.get('direction', 'CE')
    price_diff = trade.get('price_diff', 0)
    current_pnl = trade.get('current_pnl', 0)
    
    # Track extreme RSI seen during this trade
    min_rsi_seen = trade.get('_min_rsi_seen', 100)
    max_rsi_seen = trade.get('_max_rsi_seen', 0)
    
    if rsi < min_rsi_seen:
        trade['_min_rsi_seen'] = rsi
        min_rsi_seen = rsi
    if rsi > max_rsi_seen:
        trade['_max_rsi_seen'] = rsi
        max_rsi_seen = rsi
    
    # PE trade: If RSI was deeply oversold (<25) and now recovering (>40), momentum reversing
    if direction == 'PE' and min_rsi_seen < 25 and rsi > RSI_REVERSAL_PE_EXIT:
        if price_diff > 0:  # Only if in profit
            return True, f"\U0001f504 RSI REVERSAL EXIT | PE | RSI {min_rsi_seen:.0f}\u2192{rsi:.0f} | Lock: \u20b9{current_pnl:.0f}"
    
    # CE trade: If RSI was deeply overbought (>75) and now dropping (<60), momentum reversing
    if direction == 'CE' and max_rsi_seen > 75 and rsi < RSI_REVERSAL_CE_EXIT:
        if price_diff > 0:  # Only if in profit
            return True, f"\U0001f504 RSI REVERSAL EXIT | CE | RSI {max_rsi_seen:.0f}\u2192{rsi:.0f} | Lock: \u20b9{current_pnl:.0f}"
    
    return False, ""


def early_momentum_loss_cut(trade: Dict, tick: Dict) -> Tuple[bool, str]:
    """
    PRIORITY 2b: Early Momentum Loss Cut (v3.4 — ATR-adaptive)
    
    Exits early if price moves adversely within first 30 seconds.
    Threshold adapts to volatility:
      - Low vol (ATR < 3): -3 pts  (tight, save more)
      - Normal vol:         -4 pts  (default)
      - High vol (ATR > 6): -5 pts  (wider, avoid false exits)
    """
    if not trade:
        return False, ""
    
    hold_time = (datetime.now() - trade['entry_time']).total_seconds()
    
    # Only active in first 30 seconds
    if hold_time > EARLY_LOSS_CUT_TIME_SEC:
        return False, ""
    
    price_diff = trade.get('price_diff', 0)
    direction = trade.get('direction', 'CE')
    qty = trade.get('qty', 0)
    
    # v3.4: ATR-adaptive early cut threshold
    atr = tick.get('atr', trade.get('atr', 0))
    if atr > 6:
        cut_threshold = 5  # High vol: wider threshold avoids false exits
    elif atr < 3:
        cut_threshold = 3  # Low vol: tighter threshold saves more
    else:
        cut_threshold = EARLY_LOSS_CUT_POINTS  # Normal: default 4 pts
    
    # Fast adverse move: lost threshold+ pts within 30 seconds
    if price_diff <= -cut_threshold:
        actual_loss = abs(price_diff * qty)
        return True, f"\u26a1 EARLY LOSS CUT | {direction} | {price_diff:+.1f}pts in {hold_time:.0f}s (ATR-thresh:{cut_threshold}) | Loss: \u20b9{actual_loss:.0f} (saved {HARD_SL_POINTS - abs(price_diff):.1f}pts vs SL)"
    
    return False, ""


def time_exit_15min(trade: Dict) -> Tuple[bool, str]:
    """
    PRIORITY 4: Time Exit (15 Minutes Max)
    
    Exit if trade is stagnant after 15 minutes (900 seconds).
    This is a last resort - ideally trades exit via SL/TP/RSI.
    """
    if not trade:
        return False, ""
    
    hold_time = (datetime.now() - trade['entry_time']).total_seconds()
    current_pnl = trade.get('current_pnl', 0)
    price_diff = trade.get('price_diff', 0)
    tsl_status = trade.get('tsl_status', 'HARD_SL')
    
    # 15 minute max hold time
    if hold_time > MAX_HOLD_TIME_SEC:
        status = "winning" if price_diff >= 0 else "losing"
        return True, f"⏰ TIME EXIT ({status}) | Held: {hold_time/60:.1f}min | TSL: {tsl_status} | P&L: ₹{current_pnl:.0f}"
    
    # Exit 5 min before market close
    now = datetime.now()
    if now.hour == 15 and now.minute >= 25:
        return True, f"⏰ MARKET CLOSE EXIT | P&L: ₹{current_pnl:.0f}"
    
    return False, ""


def greek_exit(greeks: Dict, day_type: str) -> Tuple[bool, str]:
    """Exit based on Greeks deterioration - KILL conditions"""
    # Theta decay kill
    if greeks['theta_sec'] > THETA_SEC_KILL_LIMIT:
        return True, f"⚠️ THETA KILL: {greeks['theta_sec']:.4f} > {THETA_SEC_KILL_LIMIT}"
    
    # Gamma explosion
    limit = GAMMA_EXPIRY_MAX if day_type == "EXPIRY" else GAMMA_NORMAL_MAX
    if greeks['gamma'] > limit * 1.5:
        return True, f"⚠️ GAMMA SPIKE: {greeks['gamma']:.3f} > {limit * 1.5:.3f}"
    
    # Delta kill - too far out of range
    if abs(greeks['delta']) < DELTA_KILL_MIN:
        return True, f"⚠️ DELTA KILL (OTM): {greeks['delta']:.3f} < {DELTA_KILL_MIN}"
    
    return False, ""


def check_exit_conditions(trade: Dict, tick: Dict, greeks: Dict, 
                          day_type: str, logger, rsi: float = None) -> Tuple[bool, str]:
    """
    PULLBACK & PROTECT - Exit Priority Order (v3.3):
    
    1. HARD SL / STEP TRAILING (highest priority)
    2. Early momentum loss cut (fast adverse move in first 30s)
    3. Greeks deterioration (theta/gamma/delta kill)
    4. Smart RSI exit (momentum exhaustion)
    4b. RSI reversal exit (momentum shift from extreme)
    5. Time exit (15 min max hold)
    """
    # Priority 1: SL/TP/Trailing check
    sl_hit, sl_reason = check_hard_sl(trade, tick, logger)
    if sl_hit:
        return True, sl_reason
    
    # Priority 2: Early momentum loss cut (v3.3 - fast adverse move)
    early_hit, early_reason = early_momentum_loss_cut(trade, tick)
    if early_hit:
        return True, early_reason
    
    # Priority 3: Greeks exit
    greek_hit, greek_reason = greek_exit(greeks, day_type)
    if greek_hit:
        return True, greek_reason
    
    # Priority 4: Smart RSI exit (lock profits when momentum exhausted)
    rsi_hit, rsi_reason = smart_rsi_exit(trade, rsi)
    if rsi_hit:
        return True, rsi_reason
    
    # Priority 4b: RSI reversal exit (v3.3 - momentum shift)
    reversal_hit, reversal_reason = rsi_reversal_exit(trade, rsi)
    if reversal_hit:
        return True, reversal_reason
    
    # Priority 5: Time exit (15 min max hold)
    time_hit, time_reason = time_exit_15min(trade)
    if time_hit:
        return True, time_reason
    
    # Log trailing status periodically
    if logger and trade.get('max_profit_points', 0) >= BREAKEVEN_TRIGGER:
        if not trade.get('_tsl_logged'):
            tsl = trade.get('current_tsl', -HARD_SL_POINTS)
            status = trade.get('tsl_status', 'HARD_SL')
            logger.info(f"📈 TSL Active | Status: {status} | SL now: {tsl:+.1f}pts")
            trade['_tsl_logged'] = True
    
    return False, ""
