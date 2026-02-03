"""
PTQ Scalping Bot - State Machine
Trading state management (IDLE, ENTRY_READY, IN_TRADE, COOLDOWN)
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from config.constants import (
    CONFIG,
    MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
    CONSECUTIVE_LOSS_LIMIT, PAUSE_AFTER_LOSS_SEC,
    COOLDOWN_NORMAL_SEC, COOLDOWN_AFTER_SL_SEC,
    COOLDOWN_AFTER_CONSECUTIVE_LOSS,
    COOLDOWN_EXPIRY_NORMAL, COOLDOWN_EXPIRY_AFTER_SL,
    SESSION_FILTER_ENABLED, ALLOWED_SESSIONS,
    EXPIRY_ONLY_SESSIONS, BLACKOUT_SESSIONS
)
from utils.helpers import now, calculate_position_size


class TradingState:
    """Global trading state management"""
    
    def __init__(self):
        self.state = "IDLE"  # IDLE | ENTRY_READY | IN_TRADE | COOLDOWN | KILL_SWITCH
        self.day_type = "NORMAL"  # NORMAL | EXPIRY
        
        # Current trade
        self.current_trade: Optional[Dict] = None
        self.cooldown_until: Optional[datetime] = None
        
        # PnL tracking
        self.daily_pnl_inr = 0.0
        self.daily_pnl_pct = 0.0
        
        # Trade counters
        self.trades_this_hour = 0
        self.total_trades_today = 0
        self.consecutive_losses = 0
        self.consecutive_loss_pause_until: Optional[datetime] = None
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Entry signal tracking
        self.consecutive_entry_signals = 0
        self.last_signal_time: Optional[datetime] = None
        
        # VIX tracking
        self.estimated_vix = 15.0
        
        # Loop counter
        self.loop_count = 0
        self.last_hour_reset: Optional[datetime] = None
    
    def reset_daily(self):
        """Reset daily counters"""
        self.daily_pnl_inr = 0.0
        self.daily_pnl_pct = 0.0
        self.total_trades_today = 0
        self.trades_this_hour = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.consecutive_losses = 0
    
    def update_pnl(self, pnl_inr: float, total_capital: float, is_loss: bool):
        """Update PnL and counters after trade exit"""
        self.daily_pnl_inr += pnl_inr
        self.daily_pnl_pct = (self.daily_pnl_inr / total_capital) * 100
        
        if is_loss:
            self.consecutive_losses += 1
            self.losing_trades += 1
        else:
            self.consecutive_losses = 0
            self.winning_trades += 1
        
        self.total_trades_today += 1
        
        # Record trade result for mode switching
        try:
            from core.services.mode_switch import record_trade_result
            record_trade_result(is_win=not is_loss)
        except ImportError:
            pass


# Singleton state instance
trading_state = TradingState()


def is_trading_session_allowed(day_type: str) -> Tuple[bool, str]:
    """Check if current time is in allowed trading session"""
    if not SESSION_FILTER_ENABLED:
        return True, "Session filter disabled"
    
    current = datetime.now()
    current_time_min = current.hour * 60 + current.minute
    
    # Check blackout sessions first
    for session in BLACKOUT_SESSIONS:
        start_min = session['start_hour'] * 60 + session['start_minute']
        end_min = session['end_hour'] * 60 + session['end_minute']
        if start_min <= current_time_min <= end_min:
            return False, f"Blackout: {session.get('reason', 'Restricted')}"
    
    # Check expiry-only sessions
    if day_type == "EXPIRY":
        for session in EXPIRY_ONLY_SESSIONS:
            start_min = session['start_hour'] * 60 + session['start_minute']
            end_min = session['end_hour'] * 60 + session['end_minute']
            if start_min <= current_time_min <= end_min:
                return True, "Expiry session"
    
    # Check allowed sessions
    for session in ALLOWED_SESSIONS:
        start_min = session['start_hour'] * 60 + session['start_minute']
        end_min = session['end_hour'] * 60 + session['end_minute']
        if start_min <= current_time_min <= end_min:
            return True, "Allowed session"
    
    return False, "Outside trading hours"


def check_trade_limits(state: TradingState, logger) -> Tuple[bool, str]:
    """Check if trade limits allow new entry"""
    # Hourly limit
    if state.trades_this_hour >= MAX_TRADES_PER_HOUR:
        return False, "Hourly limit reached"
    
    # Daily limit
    if state.total_trades_today >= MAX_TRADES_PER_DAY:
        return False, "Daily limit reached"
    
    # Consecutive loss limit with pause
    if state.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        current = now()
        
        if state.consecutive_loss_pause_until is None:
            state.consecutive_loss_pause_until = current + timedelta(seconds=PAUSE_AFTER_LOSS_SEC)
            logger.warning(f"⚠️ Consecutive loss limit hit ({state.consecutive_losses}). Pausing until {state.consecutive_loss_pause_until.strftime('%H:%M:%S')}")
            return False, "Consecutive loss pause"
        
        if current < state.consecutive_loss_pause_until:
            remaining = int((state.consecutive_loss_pause_until - current).total_seconds())
            if state.loop_count % 5000 == 0:
                logger.info(f"⏸ Paused. Resuming in {remaining}s")
            return False, "Consecutive loss pause"
        else:
            logger.info("✅ Pause ended. Resetting.")
            state.consecutive_loss_pause_until = None
    
    return True, "OK"


def get_cooldown_duration(state: TradingState) -> int:
    """Get appropriate cooldown duration"""
    if state.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        return COOLDOWN_AFTER_CONSECUTIVE_LOSS
    elif state.consecutive_losses > 0:
        if state.day_type == "EXPIRY":
            return COOLDOWN_EXPIRY_AFTER_SL
        else:
            return COOLDOWN_AFTER_SL_SEC
    else:
        if state.day_type == "EXPIRY":
            return COOLDOWN_EXPIRY_NORMAL
        else:
            return COOLDOWN_NORMAL_SEC


def state_idle(tick: Dict, greeks: Dict, state: TradingState, 
               entry_signal_func, logger) -> str:
    """Handle IDLE state - Entry gate"""
    # Session filter
    session_ok, session_msg = is_trading_session_allowed(state.day_type)
    if not session_ok:
        return "IDLE"
    
    # Trade limits
    limits_ok, limits_msg = check_trade_limits(state, logger)
    if not limits_ok:
        return "IDLE"
    
    # Skip first 15 minutes
    if CONFIG['entry_filters'].get('avoid_first_15min', True):
        current = now()
        if current.hour == 9 and current.minute < 30:
            if state.loop_count % 1000 == 0:
                logger.info("⏱ Skipping first 15 minutes")
            return "IDLE"
    
    # Entry signal check
    has_signal, signal_reason = entry_signal_func(tick)
    
    # 🎯 SIGNAL CHECKING - Show every 10 loops for better visibility
    if state.loop_count % 10 == 0:
        if has_signal:
            logger.info(f"🎯 SIGNAL FOUND: {signal_reason}")
        else:
            # Show different messages based on reason
            if "warming" in signal_reason.lower():
                logger.info(f"🔄 WARMING UP: {signal_reason}")
            elif "score" in signal_reason.lower() or "conf" in signal_reason.lower():
                logger.info(f"📊 SCORE LOW: {signal_reason}")
            else:
                logger.info(f"❌ NO SIGNAL: {signal_reason}")
    
    # Require consecutive signals
    required_signals = CONFIG['entry_filters'].get('require_consecutive_signals', 1)
    
    if has_signal:
        current = now()
        if state.last_signal_time and (current - state.last_signal_time).total_seconds() < 5:
            state.consecutive_entry_signals += 1
        else:
            state.consecutive_entry_signals = 1
        state.last_signal_time = current
        
        if state.consecutive_entry_signals < required_signals:
            if state.loop_count % 50 == 0:
                logger.info(f"🔄 WAITING FOR CONSECUTIVE: {state.consecutive_entry_signals}/{required_signals} signals")
            return "IDLE"
    else:
        state.consecutive_entry_signals = 0
        state.last_signal_time = None
        return "IDLE"
    
    logger.info(f"✓ Entry signal detected: {signal_reason}")
    logger.state_change("IDLE", "ENTRY_READY", signal_reason)
    return "ENTRY_READY"


def state_entry_ready(tick: Dict, greeks: Dict, state: TradingState,
                      broker, logger) -> str:
    """Handle ENTRY_READY state - Place order using SMART SCALP v3.0 params"""
    state.consecutive_entry_signals = 0
    
    # Get SMART SCALP v3.0 signal params
    try:
        from core.engines.entry_engine import get_last_signal_params, get_signal_direction, get_signal_quantity
        signal_params = get_last_signal_params()
        direction = get_signal_direction()
        signal_qty = get_signal_quantity()
    except ImportError:
        signal_params = {}
        direction = "CE"
        signal_qty = CONFIG['trading']['quantity']
    
    # Use signal quantity or calculate from VIX
    if signal_params and 'quantity' in signal_params:
        adjusted_qty = signal_params['quantity']
        logger.info(f"🎯 SMART SCALP: {direction} | Qty: {adjusted_qty} | Conf: {signal_params.get('confidence', 0)}%")
    else:
        position_multiplier = calculate_position_size(state.estimated_vix)
        base_qty = CONFIG['trading']['quantity']
        adjusted_qty = int(base_qty * position_multiplier)
        if position_multiplier != 1.0:
            logger.info(f"📊 Position adjusted: {base_qty} → {adjusted_qty}")
    
    # Store direction in trade for exit reference
    trade = broker.place_order("BUY", qty=adjusted_qty, trades_this_hour=state.trades_this_hour, 
                                direction=direction, signal_params=signal_params)
    
    if trade:
        state.current_trade = trade
        state.trades_this_hour += 1
        
        logger.trade_entry({
            'order_id': trade['order_id'],
            'symbol': trade.get('symbol', ''),
            'side': trade['side'],
            'qty': trade['qty'],
            'entry_price': trade['entry_price'],
            'entry_reason': 'Entry signal',
            'greeks': greeks
        })
        
        logger.state_change("ENTRY_READY", "IN_TRADE", f"Order: {trade['order_id']}")
        return "IN_TRADE"
    else:
        logger.state_change("ENTRY_READY", "COOLDOWN", "Order failed")
        return "COOLDOWN"


def state_in_trade(tick: Dict, greeks: Dict, state: TradingState,
                   exit_check_func, broker, total_capital: float, logger) -> str:
    """Handle IN_TRADE state - Monitor and exit"""
    from utils.helpers import estimate_vix_from_ticks
    from core.engines.entry_engine import MAX_RECENT_TICKS
    
    # Check exit conditions
    should_exit, exit_reason = exit_check_func(
        state.current_trade, tick, greeks, state.day_type, logger
    )
    
    if should_exit:
        result = broker.exit_position(
            state.current_trade, exit_reason, 
            state.daily_pnl_inr, total_capital
        )
        
        is_loss = result['pnl_inr'] < 0
        state.update_pnl(result['pnl_inr'], total_capital, is_loss)
        state.current_trade = None
        
        # Set cooldown
        cooldown_sec = get_cooldown_duration(state)
        state.cooldown_until = now() + timedelta(seconds=cooldown_sec)
        
        logger.state_change("IN_TRADE", "COOLDOWN", f"Cooldown {cooldown_sec}s")
        return "COOLDOWN"
    
    return "IN_TRADE"


def state_cooldown(state: TradingState, logger) -> str:
    """Handle COOLDOWN state"""
    if now() >= state.cooldown_until:
        logger.state_change("COOLDOWN", "IDLE", "Cooldown ended")
        return "IDLE"
    return "COOLDOWN"
