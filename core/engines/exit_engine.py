"""
PTQ Scalping Bot - Exit Engine
PULLBACK & PROTECT Strategy - Step Trailing + Smart Exit
Updated: 2026-02-12 - New exit logic
"""

from datetime import datetime
from typing import Dict, Optional, Tuple

from config.constants import (
    CONFIG,
    SL_POINTS_FIXED, TP_POINTS_FIXED,
    MAX_LOSS_PER_TRADE_CE, MAX_LOSS_PER_TRADE_PE,
    PROFIT_TARGET_CE, PROFIT_TARGET_PE,
    MAX_HOLD_TIME_WINNING, MAX_HOLD_TIME_LOSING,
    THETA_SEC_KILL_LIMIT, DELTA_KILL_MIN,
    GAMMA_NORMAL_MAX, GAMMA_EXPIRY_MAX,
    TRAILING_ENABLED,
    EXIT_ONLY_SL_TP_TRAILING,
    TSL_STEP_LEVELS,
    EXIT_HARD_SL_POINTS,
    EXIT_BREAKEVEN_TRIGGER_POINTS,
    EXIT_BREAKEVEN_BUFFER_POINTS,
    EXIT_TRAILING_DISTANCE_POINTS,
    EXIT_EARLY_LOSS_CUT_POINTS,
    EXIT_EARLY_LOSS_CUT_TIME_SEC,
    EXIT_EARLY_CUT_ATR_LOW_POINTS,
    EXIT_EARLY_CUT_ATR_HIGH_POINTS,
    EXIT_SOFT_LOSS_TIME_SEC,
    EXIT_SOFT_LOSS_POINTS,
    RSI_REVERSAL_MIN_PROFIT_POINTS,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_EXIT_MIN_PROFIT_POINTS,
    RSI_REVERSAL_CE_EXIT,
    RSI_REVERSAL_PE_EXIT,
    RSI_REVERSAL_CE_EXTREME,
    RSI_REVERSAL_PE_EXTREME,
    EXIT_PROFIT_MODE,
    EXIT_PROFIT_FLOOR_POINTS,
    EXIT_LOSS_MODE,
    EXIT_ATR_MULT,
    EXIT_ATR_FLOOR_POINTS,
    EXIT_ATR_CAP_POINTS,
    EXIT_MFE_ARM_POINTS,
    EXIT_MFE_TIGHT_POINTS,
    EXIT_MFE_ROOM_POINTS,
)
from core.risk.greeks_validator import validate_greeks

# ============================================
# PULLBACK & PROTECT EXIT CONFIGURATION (v3.3 - Improved R:R)
# ============================================
# Hard SL: 6 points (exit immediately) - reduced from 8 for better R:R
HARD_SL_POINTS = float(EXIT_HARD_SL_POINTS)

# PHASE 6: Earlier trailing activation (v3.3)
# Breakeven trigger: Move SL to +2 when profit >= 5 points
BREAKEVEN_TRIGGER = float(EXIT_BREAKEVEN_TRIGGER_POINTS)
BREAKEVEN_BUFFER = float(EXIT_BREAKEVEN_BUFFER_POINTS)

# Dynamic trailing: Keep SL 3 points below current price after breakeven
# Tighter trail = lock more profit when running
TRAILING_DISTANCE = float(EXIT_TRAILING_DISTANCE_POINTS)

# Early Momentum Loss Cut (v3.3)
EARLY_LOSS_CUT_POINTS = float(EXIT_EARLY_LOSS_CUT_POINTS)
EARLY_LOSS_CUT_TIME_SEC = int(EXIT_EARLY_LOSS_CUT_TIME_SEC)
SOFT_LOSS_TIME_SEC = int(EXIT_SOFT_LOSS_TIME_SEC)
SOFT_LOSS_POINTS = float(EXIT_SOFT_LOSS_POINTS)

DEFAULT_TTE_SEC = 7 * 24 * 3600

# Overridable clock for exit-timing decisions (early loss cut, soft loss,
# time exit, end-of-day cutoff). Live trading never sets this — _now() falls
# through to the real wall clock exactly as before. Backtesting sets it to
# the current historical candle's timestamp before each exit check, since
# replaying history against real datetime.now() would make every hold-time
# calculation nonsensical (see findings.md §2.1).
_clock_override: Optional[datetime] = None


def _now() -> datetime:
    return _clock_override if _clock_override is not None else datetime.now()


def _audit_exit_event(logger, stage: str, trade: Dict, details: Dict):
    """Emit lightweight audit logs for exit decisions without changing strategy behavior."""
    if not logger:
        return
    try:
        detail_text = " | ".join(f"{k}={v}" for k, v in details.items())
        logger.info(f"EXIT_AUDIT | stage={stage} | direction={trade.get('direction', 'CE')} | {detail_text}")
    except Exception:
        pass


def get_step_trailing_sl(trade: Dict, price_diff: float) -> Tuple[float, str]:
    """
    STEP TRAILING STOP LOSS - Pullback & Protect Strategy (OPTIMIZED)
    
     Logic:
     1. Initial SL = -HARD_SL_POINTS
     2. If trailing is enabled, apply configured TSL step levels from constants.
         Example step table: 8:4,12:7 means if max profit >= 12, SL locks at +7.
     3. SL never decreases (highest_sl lock).
    
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
    trailing_sl = -HARD_SL_POINTS
    sl_status = "HARD_SL"

    # Step trailing from configured map (single source of truth: TSL_STEP_LEVELS),
    # plus an earlier breakeven-lock rung so profit isn't fully unprotected
    # between entry and the first real TSL step.
    if TRAILING_ENABLED:
        step_sl = trailing_sl
        effective_levels = list(TSL_STEP_LEVELS)
        if BREAKEVEN_TRIGGER > 0:
            effective_levels.append((BREAKEVEN_TRIGGER, BREAKEVEN_BUFFER))
        for trigger_profit, lock_sl in sorted(effective_levels):
            if max_profit >= float(trigger_profit):
                step_sl = max(step_sl, float(lock_sl))
        if step_sl > trailing_sl:
            trailing_sl = step_sl
            sl_status = f"STEP_TSL(+{trailing_sl:.1f})"
    else:
        sl_status = "TRAILING_DISABLED"
    
    # CRITICAL: SL should NEVER decrease!
    if trailing_sl > highest_sl:
        trade['highest_sl'] = trailing_sl
        highest_sl = trailing_sl
    else:
        trailing_sl = highest_sl
        if trailing_sl > 0:
            sl_status = f"LOCKED(+{trailing_sl:.1f})"
    
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

    # Trade-scoped max favorable / adverse excursion (tracked on the trade
    # dict itself, unlike compute_trade_mfe_mae_from_ticks which reads a
    # global rolling tick buffer that isn't scoped to this specific trade
    # and is unreliable for short-lived trades).
    current_pnl_now = trade['current_pnl']
    if current_pnl_now > trade.get('mfe_inr', 0.0):
        trade['mfe_inr'] = current_pnl_now
    if current_pnl_now < trade.get('mae_inr', 0.0):
        trade['mae_inr'] = current_pnl_now

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
    
    # Fixed take profit — only applies when trailing is disabled. With
    # trailing on, the step ladder already handles profit-taking and can
    # capture rungs above this fixed target instead of being cut short here.
    if not TRAILING_ENABLED and price_diff >= TP_POINTS_FIXED:
        profit = price_diff * qty
        return True, f"🎯 TAKE PROFIT | {direction} | +{price_diff:.1f}pts @ ₹{current_price:.2f} | Profit: ₹{profit:.0f}"
    
    return False, ""


def smart_rsi_exit(trade: Dict, rsi: float = None, logger=None) -> Tuple[bool, str]:
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
    if price_diff < RSI_EXIT_MIN_PROFIT_POINTS:
        _audit_exit_event(logger, "RSI_EVAL", trade, {
            "reason": "profit_threshold_not_met",
            "price_diff": round(price_diff, 2),
            "rsi": round(rsi, 2),
        })
        return False, ""
    
    # CE trade: Exit on extreme overbought
    if direction == 'CE' and rsi > RSI_OVERBOUGHT:
        return True, f"\U0001f4ca RSI EXIT | CE | RSI={rsi:.0f} (OB>{RSI_OVERBOUGHT:.0f}) | Lock profit: \u20b9{current_pnl:.0f}"

    # PE trade: Exit on extreme oversold
    if direction == 'PE' and rsi < RSI_OVERSOLD:
        return True, f"\U0001f4ca RSI EXIT | PE | RSI={rsi:.0f} (OS<{RSI_OVERSOLD:.0f}) | Lock profit: \u20b9{current_pnl:.0f}"
    
    return False, ""


def rsi_reversal_exit(trade: Dict, rsi: float = None, logger=None) -> Tuple[bool, str]:
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
    
    # PE trade: If RSI was deeply oversold and now recovering, momentum reversing
    if direction == 'PE' and min_rsi_seen < RSI_REVERSAL_PE_EXTREME and rsi > RSI_REVERSAL_PE_EXIT:
        if price_diff >= RSI_REVERSAL_MIN_PROFIT_POINTS:  # Only if profit clears the floor
            return True, f"\U0001f504 RSI REVERSAL EXIT | PE | RSI {min_rsi_seen:.0f}\u2192{rsi:.0f} | Lock: \u20b9{current_pnl:.0f}"

    # CE trade: If RSI was deeply overbought and now dropping, momentum reversing
    if direction == 'CE' and max_rsi_seen > RSI_REVERSAL_CE_EXTREME and rsi < RSI_REVERSAL_CE_EXIT:
        if price_diff >= RSI_REVERSAL_MIN_PROFIT_POINTS:  # Only if profit clears the floor
            return True, f"\U0001f504 RSI REVERSAL EXIT | CE | RSI {max_rsi_seen:.0f}\u2192{rsi:.0f} | Lock: \u20b9{current_pnl:.0f}"
    
    return False, ""


def _early_cut_threshold(trade: Dict, tick: Dict) -> float:
    """Early-cut distance in points.

    'static' reproduces production exactly: the ATR branch below. Note that `atr` is only
    populated when EXIT_REALISED_ATR_ENABLED is on, so by default this still resolves to the
    low-volatility value — that is the frozen baseline's real behaviour, deliberately kept.

    The experimental modes were selected by replaying the recorded 2026-09-03/04 entries
    (claude_code/experiments/exp02_loss.py). Both point the same way: TIGHTER for a trade
    that never worked, not wider.
    """
    atr = tick.get('atr', trade.get('atr', 0)) or 0

    if EXIT_LOSS_MODE == 'atr_adaptive' and atr > 0:
        return min(float(EXIT_ATR_CAP_POINTS),
                   max(float(EXIT_ATR_FLOOR_POINTS), float(EXIT_ATR_MULT) * float(atr)))

    if EXIT_LOSS_MODE == 'mfe_aware':
        qty = trade.get('qty', 0) or 0
        mfe_pts = (trade.get('mfe_inr', 0.0) / qty) if qty else 0.0
        return (float(EXIT_MFE_ROOM_POINTS) if mfe_pts >= float(EXIT_MFE_ARM_POINTS)
                else float(EXIT_MFE_TIGHT_POINTS))

    if atr > 6:
        return float(EXIT_EARLY_CUT_ATR_HIGH_POINTS)
    if atr < 3:
        return float(EXIT_EARLY_CUT_ATR_LOW_POINTS)
    return EARLY_LOSS_CUT_POINTS


def profit_floor_exit(trade: Dict) -> Tuple[bool, str]:
    """EXPERIMENTAL (EXIT_PROFIT_MODE='floor'): take profit on the first tick past the floor.

    Replay of the recorded entries showed the tick-RSI reversal condition was already
    satisfied when the floor was crossed on 8/8 profitable RSI exits, so the RSI added delay
    rather than information. Off by default; production keeps the RSI path.
    """
    if not trade or EXIT_PROFIT_MODE != 'floor':
        return False, ""
    price_diff = trade.get('price_diff', 0)
    if price_diff < float(EXIT_PROFIT_FLOOR_POINTS):
        return False, ""
    direction = trade.get('direction', 'CE')
    current_pnl = trade.get('current_pnl', 0)
    return True, (f"\U0001f3af PROFIT FLOOR EXIT | {direction} | "
                  f"+{price_diff:.1f}pts >= {float(EXIT_PROFIT_FLOOR_POINTS):.2f} | "
                  f"Lock: \u20b9{current_pnl:.0f}")


def early_momentum_loss_cut(trade: Dict, tick: Dict) -> Tuple[bool, str]:
    """
    PRIORITY 2b: Early Momentum Loss Cut (v3.4 — ATR-adaptive)
    
    Exits early if price moves adversely within first 30 seconds.
        Threshold adapts to volatility:
            - Low vol (ATR < 3): tighter early cut threshold
            - Normal vol:         configured default threshold
            - High vol (ATR > 6): wider threshold to avoid false exits
    """
    if not trade:
        return False, ""
    
    hold_time = (_now() - trade['entry_time']).total_seconds()
    
    # Only active in first 30 seconds
    if hold_time > EARLY_LOSS_CUT_TIME_SEC:
        return False, ""
    
    price_diff = trade.get('price_diff', 0)
    direction = trade.get('direction', 'CE')
    qty = trade.get('qty', 0)
    
    cut_threshold = _early_cut_threshold(trade, tick)
    
    # Fast adverse move: lost threshold+ pts within 30 seconds
    if price_diff <= -cut_threshold:
        # Cap loss to configured per-trade maximum to avoid extreme P&L mismatch
        max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
        actual_loss = min(abs(price_diff * qty), max_loss)

        # Store capped PnL in trade so exit handler can use the capped value
        try:
            trade['current_pnl'] = -actual_loss
            trade['_early_cut_applied'] = True
        except Exception:
            pass

        return True, f"\u26a1 EARLY LOSS CUT | {direction} | {price_diff:+.1f}pts in {hold_time:.0f}s (ATR-thresh:{cut_threshold}) | Loss: \u20b9{actual_loss:.0f} (saved {HARD_SL_POINTS - abs(price_diff):.1f}pts vs SL)"
    
    return False, ""


def soft_loss_time_exit(trade: Dict) -> Tuple[bool, str]:
    """
    PRIORITY 2c: Soft loss timeout exit.

    If a trade stays mildly negative for too long, exit before hard SL escalation.
    """
    if not trade:
        return False, ""

    hold_time = (_now() - trade['entry_time']).total_seconds()
    if hold_time < SOFT_LOSS_TIME_SEC:
        return False, ""

    price_diff = trade.get('price_diff', 0)
    direction = trade.get('direction', 'CE')
    qty = trade.get('qty', 0)

    if price_diff <= -SOFT_LOSS_POINTS:
        max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
        actual_loss = min(abs(price_diff * qty), max_loss)
        try:
            trade['current_pnl'] = -actual_loss
            trade['_soft_time_cut_applied'] = True
        except Exception:
            pass
        return True, (
            f"⏳ SOFT LOSS EXIT | {direction} | {price_diff:+.1f}pts after {hold_time:.0f}s"
            f" | Loss: ₹{actual_loss:.0f}"
        )

    return False, ""


def time_exit_15min(trade: Dict) -> Tuple[bool, str]:
    """
    PRIORITY 4: Time Exit (15 Minutes Max)
    
    Exit if trade is stagnant after 15 minutes (900 seconds).
    This is a last resort - ideally trades exit via SL/TP/RSI.
    """
    if not trade:
        return False, ""
    
    hold_time = (_now() - trade['entry_time']).total_seconds()
    current_pnl = trade.get('current_pnl', 0)
    price_diff = trade.get('price_diff', 0)
    tsl_status = trade.get('tsl_status', 'HARD_SL')

    # Max hold time (.env-configurable, separate winning/losing thresholds)
    is_winning = price_diff >= 0
    max_hold_sec = MAX_HOLD_TIME_WINNING if is_winning else MAX_HOLD_TIME_LOSING
    # The max-hold timeout is a discretionary exit and is suppressed with the rest of
    # them; the market-close branch below is not, because an unclosed position on an
    # expiry day expires and that is not a strategy question.
    if not EXIT_ONLY_SL_TP_TRAILING and hold_time > max_hold_sec:
        status = "winning" if is_winning else "losing"
        return True, f"⏰ TIME EXIT ({status}) | Held: {hold_time/60:.1f}min | TSL: {tsl_status} | P&L: ₹{current_pnl:.0f}"
    
    # Exit 5 min before market close
    now = _now()
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


def _validated_greeks_for_exit(greeks: Dict, tick: Dict, trade: Dict, logger=None) -> Dict:
    """Cross-validate greeks against API when possible and return best-effort values for exit checks."""
    if not greeks:
        return {}

    try:
        spot = float((tick or {}).get('spot_price') or 0)
        if spot <= 0:
            return greeks

        strike = int(round(spot / 50.0) * 50)
        direction = str((trade or {}).get('direction', 'CE') or 'CE')
        option_type = 'PE' if direction == 'PE' else 'CE'
        iv = float((tick or {}).get('iv') or 0.20)
        tte_sec = float((tick or {}).get('tte_sec') or DEFAULT_TTE_SEC)

        validation = validate_greeks(
            spot=spot,
            strike=strike,
            tte_sec=tte_sec,
            iv=iv,
            option_type=option_type,
            underlying='NIFTY',
        )

        verdict = validation.get('verdict', 'API_UNAVAILABLE')
        api_greeks = validation.get('api') or {}
        if logger and verdict in ('WARNING', 'ERROR'):
            logger.warning(f"⚠ Greeks divergence verdict={verdict} | using BSM fallback for exits")

        # Use API values only when validator marks them reliable.
        if verdict == 'OK' and api_greeks:
            merged = dict(greeks)
            for k in ('delta', 'gamma', 'theta', 'vega'):
                if k in api_greeks and api_greeks[k] is not None:
                    merged[k] = api_greeks[k]
            return merged
    except Exception:
        # Validation is safety enhancement only, never block exits.
        pass

    return greeks


def check_exit_conditions(trade: Dict, tick: Dict, greeks: Dict, 
                          day_type: str, logger, rsi: float = None) -> Tuple[bool, str]:
    """
    PULLBACK & PROTECT - Exit Priority Order (v3.3):

    1. HARD SL / STEP TRAILING (highest priority)
    2. Early momentum loss cut (fast adverse move in first 30s)
    2c. Soft loss timeout exit (lingering adverse move)
    3. Greeks deterioration (theta/gamma/delta kill)
    4. Smart RSI exit (momentum exhaustion)
    4b. RSI reversal exit (momentum shift from extreme)
    5. Time exit (15 min max hold)
    """
    def _cap_negative_pnl(trade: Dict):
        """Ensure negative PnL is capped to per-trade max loss and mark it."""
        if not trade:
            return
        direction = trade.get('direction', 'CE')
        max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
        if 'current_pnl' in trade and trade['current_pnl'] < 0:
            capped = min(abs(trade['current_pnl']), max_loss)
            trade['current_pnl'] = -capped
            trade['_pnl_capped'] = True
            # Log and send urgent alert if logger available
            try:
                if logger:
                    logger.warning(f"🔒 PnL CAPPED: {direction} | Capped to ₹{-trade['current_pnl']:.0f}")
                # Send Telegram alert if bot available
                try:
                    from core.services.telegram_bot import send_alert
                    send_alert(f"PnL CAPPED: {direction} | Capped to ₹{-trade['current_pnl']:.0f} | Entry: ₹{trade.get('entry_price', 0):.2f}")
                except Exception:
                    pass
            except Exception:
                pass

    # Priority 1: SL/TP/Trailing check
    sl_hit, sl_reason = check_hard_sl(trade, tick, logger)
    if sl_hit:
        _cap_negative_pnl(trade)
        return True, sl_reason
    
    # Everything below this point is a discretionary exit that fires in FRONT of the
    # declared SL/TP ladder. Across 27 live trades the ladder fired zero times because
    # of them. With EXIT_ONLY_SL_TP_TRAILING on, they are skipped so the ladder can
    # actually be evaluated; only the mandatory market-close exit still runs.
    if EXIT_ONLY_SL_TP_TRAILING:
        close_hit, close_reason = time_exit_15min(trade)
        if close_hit:
            _cap_negative_pnl(trade)
            return True, close_reason
        return False, ""

    # Priority 2: Early momentum loss cut (v3.3 - fast adverse move)
    early_hit, early_reason = early_momentum_loss_cut(trade, tick)
    if early_hit:
        _cap_negative_pnl(trade)
        return True, early_reason

    # Priority 2c: Soft loss timeout cut
    soft_hit, soft_reason = soft_loss_time_exit(trade)
    if soft_hit:
        _cap_negative_pnl(trade)
        return True, soft_reason
    
    # Priority 3: Greeks exit (validated/reconciled)
    effective_greeks = _validated_greeks_for_exit(greeks, tick, trade, logger)
    greek_hit, greek_reason = greek_exit(effective_greeks, day_type)
    if greek_hit:
        _cap_negative_pnl(trade)
        return True, greek_reason
    
    # Priority 4-pre: experimental profit-floor exit (no-op unless EXIT_PROFIT_MODE='floor')
    floor_hit, floor_reason = profit_floor_exit(trade)
    if floor_hit:
        _audit_exit_event(logger, "PROFIT_FLOOR", trade, {"reason": floor_reason})
        return True, floor_reason

    # Priority 4: Smart RSI exit (lock profits when momentum exhausted)
    rsi_hit, rsi_reason = smart_rsi_exit(trade, rsi, logger)
    if rsi_hit:
        _cap_negative_pnl(trade)
        return True, rsi_reason
    
    # Priority 4b: RSI reversal exit (v3.3 - momentum shift)
    reversal_hit, reversal_reason = rsi_reversal_exit(trade, rsi, logger)
    if reversal_hit:
        _cap_negative_pnl(trade)
        return True, reversal_reason
    
    # Priority 5: Time exit (15 min max hold)
    time_hit, time_reason = time_exit_15min(trade)
    if time_hit:
        _cap_negative_pnl(trade)
        return True, time_reason
    
    # Log trailing status periodically
    first_tsl_trigger = TSL_STEP_LEVELS[0][0] if TSL_STEP_LEVELS else BREAKEVEN_TRIGGER
    if logger and trade.get('max_profit_points', 0) >= float(first_tsl_trigger):
        if not trade.get('_tsl_logged'):
            tsl = trade.get('current_tsl', -HARD_SL_POINTS)
            status = trade.get('tsl_status', 'HARD_SL')
            logger.info(f"📈 TSL Active | Status: {status} | SL now: {tsl:+.1f}pts")
            trade['_tsl_logged'] = True
    
    return False, ""
