"""
PTQ Scalping Bot - State Machine
Trading state management (IDLE, ENTRY_READY, IN_TRADE, COOLDOWN)
"""

import os
import csv
import re
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
    EXPIRY_ONLY_SESSIONS, BLACKOUT_SESSIONS,
    TRADING_START_TIME
)
from utils.helpers import now, calculate_position_size

# Strike rotation interval (seconds)
STRIKE_ROTATION_INTERVAL = 60

# v3.4: Intraday spike detection — pause after sudden price jumps
SPIKE_THRESHOLD_PCT = 1.5   # 1.5% spot move in ≤10 seconds = spike
SPIKE_PAUSE_SEC = 60         # Pause 60s after spike detected
_last_spot_prices = []        # Ring buffer of (timestamp, spot_price)
_spike_pause_until = None     # datetime when spike pause expires


def _check_intraday_spike(tick: dict, logger) -> bool:
    """
    v3.4: Detect sudden intraday price spikes (news events, flash crashes).
    Tracks spot price over last 10 seconds; if move > SPIKE_THRESHOLD_PCT%, 
    pauses trading for SPIKE_PAUSE_SEC seconds.
    
    Returns True if trading should be paused.
    """
    global _last_spot_prices, _spike_pause_until
    from datetime import datetime, timedelta
    
    current = datetime.now()
    
    # If already in spike pause, check if expired
    if _spike_pause_until and current < _spike_pause_until:
        return True
    elif _spike_pause_until and current >= _spike_pause_until:
        _spike_pause_until = None  # Pause expired, resume
    
    spot = tick.get('spot_price', 0)
    if spot <= 0:
        return False
    
    # Add current price to ring buffer
    _last_spot_prices.append((current, spot))
    
    # Keep only last 30 entries (~10-15 seconds at 2-3 ticks/sec)
    if len(_last_spot_prices) > 30:
        _last_spot_prices = _last_spot_prices[-30:]
    
    # Need at least 3 data points
    if len(_last_spot_prices) < 3:
        return False
    
    # Compare current price vs oldest in buffer (within last 10s)
    cutoff = current - timedelta(seconds=10)
    old_prices = [(t, p) for t, p in _last_spot_prices if t >= cutoff]
    if len(old_prices) < 2:
        return False
    
    oldest_price = old_prices[0][1]
    if oldest_price <= 0:
        return False
    
    move_pct = abs(spot - oldest_price) / oldest_price * 100
    
    if move_pct >= SPIKE_THRESHOLD_PCT:
        _spike_pause_until = current + timedelta(seconds=SPIKE_PAUSE_SEC)
        logger.warning(
            f"🚨 SPIKE DETECTED: Spot ₹{oldest_price:.0f} → ₹{spot:.0f} "
            f"({move_pct:+.2f}% in <10s) | Pausing {SPIKE_PAUSE_SEC}s"
        )
        try:
            from core.services.telegram_bot import send_alert
            send_alert(f"🚨 SPIKE: ₹{oldest_price:.0f}→₹{spot:.0f} ({move_pct:.1f}%) | Paused {SPIKE_PAUSE_SEC}s")
        except Exception:
            pass
        return True
    
    return False


def _calculate_rsi(recent_ticks: list, period: int = 14) -> float:
    """Calculate RSI from recent ticks for momentum exit"""
    if not recent_ticks or len(recent_ticks) < period + 1:
        return 50  # Neutral if not enough data
    
    prices = [t.get('ltp', 0) for t in recent_ticks if t.get('ltp')]
    if len(prices) < period + 1:
        return 50
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return 50
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class TradingState:
    """Global trading state management"""
    
    def __init__(self):
        self.state = "IDLE"  # IDLE | ENTRY_READY | IN_TRADE | COOLDOWN | KILL_SWITCH
        self.day_type = "NORMAL"  # NORMAL | EXPIRY
        
        # Current trade
        self.current_trade: Optional[Dict] = None
        self.cooldown_until: Optional[datetime] = None
        self.manual_intervention_required = False
        
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
        
        # ═══════════════════════════════════════════════════════════════
        # PHASE 4: Per-Direction Loss Tracking (v3.2)
        # ═══════════════════════════════════════════════════════════════
        self.consecutive_ce_losses = 0
        self.consecutive_pe_losses = 0
        self.last_trade_direction: Optional[str] = None
        
        # Direction-specific cooldown (prevents permanent blocking)
        self.ce_blocked_until: Optional[datetime] = None
        self.pe_blocked_until: Optional[datetime] = None
        self.DIRECTION_COOLDOWN_MIN = 30  # 30 minutes cooldown after 2 losses
        
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
        # Phase 4: Reset per-direction counters
        self.consecutive_ce_losses = 0
        self.consecutive_pe_losses = 0
        self.ce_blocked_until = None
        self.pe_blocked_until = None
        self.last_trade_direction = None
        self.manual_intervention_required = False
    
    def is_direction_blocked(self, direction: str) -> tuple:
        """
        Check if a direction (CE/PE) is blocked due to consecutive losses.
        Returns (is_blocked, reason) tuple.
        
        Logic:
        - If 2+ consecutive losses AND cooldown not expired → blocked
        - If cooldown expired → reset counter and allow trading
        """
        now = datetime.now()
        
        if direction == 'CE':
            if self.consecutive_ce_losses >= 2:
                if self.ce_blocked_until and now < self.ce_blocked_until:
                    remaining = (self.ce_blocked_until - now).seconds // 60
                    return True, f"CE blocked ({self.consecutive_ce_losses} losses, {remaining}min cooldown)"
                else:
                    # Cooldown expired - reset counter and allow recovery trade
                    self.consecutive_ce_losses = 1  # Reset to 1 (still cautious)
                    self.ce_blocked_until = None
                    print(f"✅ CE cooldown expired - allowing recovery trade")
                    return False, "CE cooldown expired"
            return False, ""
        
        elif direction == 'PE':
            if self.consecutive_pe_losses >= 2:
                if self.pe_blocked_until and now < self.pe_blocked_until:
                    remaining = (self.pe_blocked_until - now).seconds // 60
                    return True, f"PE blocked ({self.consecutive_pe_losses} losses, {remaining}min cooldown)"
                else:
                    # Cooldown expired - reset counter and allow recovery trade
                    self.consecutive_pe_losses = 1  # Reset to 1 (still cautious)
                    self.pe_blocked_until = None
                    print(f"✅ PE cooldown expired - allowing recovery trade")
                    return False, "PE cooldown expired"
            return False, ""
        
        return False, ""

    def restore_from_trades(self, total_capital: float = 100000.0) -> bool:
        """
        Restore PnL and counters from today's trades.csv after bot restart.
        This ensures PnL is preserved when bot is stopped and restarted.
        
        Returns:
            True if restored from existing trades, False if no trades found
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        trades_file = os.path.join("logs", today_str, "trades.csv")
        
        if not os.path.exists(trades_file):
            return False
        
        try:
            total_pnl = 0.0
            wins = 0
            losses = 0
            ce_losses = 0
            pe_losses = 0
            last_direction = None
            trade_count = 0
            
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                
                # Track consecutive losses at end
                recent_trades = []
                
                for row in reader:
                    if row.get('event') == 'EXIT':
                        trade_count += 1
                        
                        # Get PnL - try CSV value first, then parse from exit_reason
                        pnl = 0.0
                        csv_pnl = float(row.get('pnl', 0)) if row.get('pnl') else 0
                        exit_reason = row.get('exit_reason', '')
                        
                        # Check for corrupted PnL and parse from exit_reason
                        if csv_pnl != 0 and abs(csv_pnl) < 50000:
                            pnl = csv_pnl
                        else:
                            # Parse from exit_reason text
                            profit_match = re.search(r'Profit:\s*₹?([0-9,]+)', exit_reason)
                            loss_match = re.search(r'Loss:\s*₹?-?([0-9,]+)', exit_reason)
                            
                            if profit_match:
                                pnl = float(profit_match.group(1).replace(',', ''))
                            elif loss_match:
                                pnl = -float(loss_match.group(1).replace(',', ''))
                            else:
                                pnl = csv_pnl  # Use CSV value as fallback
                        
                        total_pnl += pnl
                        
                        # Determine direction from symbol
                        symbol = row.get('symbol', '')
                        direction = 'CE' if 'CE' in symbol else 'PE'
                        
                        if pnl > 0:
                            wins += 1
                            recent_trades.append({'pnl': pnl, 'dir': direction, 'loss': False})
                        else:
                            losses += 1
                            recent_trades.append({'pnl': pnl, 'dir': direction, 'loss': True})
            
            if trade_count == 0:
                return False
            
            # Calculate consecutive losses from recent trades
            # Only reset on win of SAME direction, independent tracking per direction
            for trade in recent_trades:
                if trade['loss']:
                    if trade['dir'] == 'CE':
                        ce_losses += 1
                        # DON'T reset pe_losses
                    else:
                        pe_losses += 1
                        # DON'T reset ce_losses
                else:
                    # Only reset the winning direction's counter
                    if trade['dir'] == 'CE':
                        ce_losses = 0
                    else:
                        pe_losses = 0
                last_direction = trade['dir']
            
            # Apply restored values
            self.daily_pnl_inr = total_pnl
            self.daily_pnl_pct = (total_pnl / total_capital) * 100
            self.total_trades_today = trade_count
            self.winning_trades = wins
            self.losing_trades = losses
            self.consecutive_ce_losses = ce_losses
            self.consecutive_pe_losses = pe_losses
            self.last_trade_direction = last_direction
            
            # Count overall consecutive losses
            consec_losses = 0
            for trade in reversed(recent_trades):
                if trade['loss']:
                    consec_losses += 1
                else:
                    break
            self.consecutive_losses = consec_losses
            
            print(f"✅ Restored from {trade_count} trades: PnL ₹{total_pnl:+,.0f} ({wins}W/{losses}L)")
            return True
            
        except Exception as e:
            print(f"⚠️ Could not restore trades: {e}")
            return False
    
    def update_pnl(self, pnl_inr: float, total_capital: float, is_loss: bool, direction: str = None):
        """Update PnL and counters after trade exit"""
        self.daily_pnl_inr += pnl_inr
        self.daily_pnl_pct = (self.daily_pnl_inr / total_capital) * 100
        
        if is_loss:
            self.consecutive_losses += 1
            self.losing_trades += 1
            # Phase 4: Track per-direction losses (DON'T reset other direction!)
            if direction == 'CE':
                self.consecutive_ce_losses += 1
                # Set cooldown after 2 consecutive losses (prevents permanent blocking)
                if self.consecutive_ce_losses >= 2:
                    self.ce_blocked_until = datetime.now() + timedelta(minutes=self.DIRECTION_COOLDOWN_MIN)
                    print(f"⏸️ CE direction on cooldown for {self.DIRECTION_COOLDOWN_MIN}min (after {self.consecutive_ce_losses} losses)")
            elif direction == 'PE':
                self.consecutive_pe_losses += 1
                # Set cooldown after 2 consecutive losses
                if self.consecutive_pe_losses >= 2:
                    self.pe_blocked_until = datetime.now() + timedelta(minutes=self.DIRECTION_COOLDOWN_MIN)
                    print(f"⏸️ PE direction on cooldown for {self.DIRECTION_COOLDOWN_MIN}min (after {self.consecutive_pe_losses} losses)")
        else:
            self.consecutive_losses = 0
            self.winning_trades += 1
            # Only reset the WINNING direction's counter and cooldown
            if direction == 'CE':
                self.consecutive_ce_losses = 0
                self.ce_blocked_until = None
            elif direction == 'PE':
                self.consecutive_pe_losses = 0
                self.pe_blocked_until = None
        
        self.last_trade_direction = direction
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
            logger.info("✅ Pause ended. Resetting consecutive losses.")
            state.consecutive_loss_pause_until = None
            state.consecutive_losses = 0  # FIX: Reset consecutive losses after pause
            state.consecutive_ce_losses = 0
            state.consecutive_pe_losses = 0
    
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
    # ============================================
    # STRIKE ROTATION: Check every 60 seconds
    # Ensures ATM strike is updated even if no trades
    # ============================================
    from core.trading.broker import broker
    current = now()
    
    if not hasattr(state, '_last_strike_rotation'):
        state._last_strike_rotation = None
    
    should_rotate = (
        state._last_strike_rotation is None or 
        (current - state._last_strike_rotation).total_seconds() >= STRIKE_ROTATION_INTERVAL
    )
    
    if should_rotate and tick.get('spot_price'):
        try:
            rotated = broker.check_and_rotate_strike()
            state._last_strike_rotation = current
            if rotated:
                logger.info(f"🔄 Strike rotated to ATM @ spot {tick.get('spot_price', 0):.0f}")
        except Exception as e:
            logger.debug(f"Strike rotation check failed: {e}")
    
    # Session filter
    session_ok, session_msg = is_trading_session_allowed(state.day_type)
    if not session_ok:
        return "IDLE"
    
    # Trade limits
    limits_ok, limits_msg = check_trade_limits(state, logger)
    if not limits_ok:
        return "IDLE"
    
    # ============================================
    # PULLBACK & PROTECT: No trades before configured start time
    # Uses TRADING_START_TIME from config (default 09:20)
    # ============================================
    try:
        start_h, start_m = map(int, TRADING_START_TIME.split(':'))
    except (ValueError, AttributeError):
        start_h, start_m = 9, 20
    if current.hour < start_h or (current.hour == start_h and current.minute < start_m):
        if state.loop_count % 1000 == 0:
            logger.info(f"⏱ Morning volatility filter: Waiting until {TRADING_START_TIME} (now {current.strftime('%H:%M')})")
        return "IDLE"
    
    # ============================================
    # v3.4: INTRADAY SPIKE DETECTION
    # Pauses trading after sudden spot price jumps (news/flash crash)
    # ============================================
    if _check_intraday_spike(tick, logger):
        if state.loop_count % 200 == 0:
            logger.info("🚨 Spike pause active — waiting for market to settle")
        return "IDLE"
    
    # Entry signal check
    has_signal, signal_reason = entry_signal_func(tick)
    
    # 🎯 SIGNAL CHECKING — reduced noise
    if has_signal:
        # Always show signals immediately
        logger.info(f"🎯 SIGNAL: {signal_reason}")
    elif state.loop_count % 300 == 0:
        # Show rejection reason every ~30s (not every 1s)
        if "warming" in signal_reason.lower():
            logger.info(f"⏳ Warming up… {signal_reason}")
        elif "score" in signal_reason.lower() or "conf" in signal_reason.lower():
            logger.info(f"📊 {signal_reason}")
        else:
            logger.debug(f"No signal: {signal_reason}")
    
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
    """Handle ENTRY_READY state - Place order using SMART SCALP v3.4 params"""
    state.consecutive_entry_signals = 0
    
    # ── RISK MANAGER CHECK (FINAL FIX) ──
    try:
        from core.risk.risk_manager import get_risk_manager
        rm = get_risk_manager()
        can_trade, risk_details = rm.can_trade(spot_price=tick.get('spot_price'))
        
        if not can_trade:
            reasons = risk_details.get('reasons', ['Risk check failed'])
            logger.warning(f"⚠ RISK BLOCKED: {', '.join(reasons)}")
            logger.state_change("ENTRY_READY", "COOLDOWN", f"Risk: {reasons[0]}")
            return "COOLDOWN"
        
        size_multiplier = risk_details.get('size_multiplier', 1.0)
        if size_multiplier != 1.0:
            logger.info(f"📊 Risk size multiplier: {size_multiplier:.2f}")
    except Exception as e:
        logger.warning(f"⚠ RiskManager check error: {e} — proceeding with default")
        size_multiplier = 1.0
    
    # Get SMART SCALP v3.4 signal params
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
    
    # Apply risk manager size multiplier
    if size_multiplier != 1.0:
        original_qty = adjusted_qty
        adjusted_qty = max(1, int(adjusted_qty * size_multiplier))
        logger.info(f"📊 Risk adjusted qty: {original_qty} → {adjusted_qty} (×{size_multiplier:.2f})")
    
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
                   exit_check_func, broker, total_capital: float, logger,
                   recent_ticks: list = None) -> str:
    """Handle IN_TRADE state - Monitor and exit"""
    from utils.helpers import estimate_vix_from_ticks
    from core.engines.entry_engine import MAX_RECENT_TICKS
    
    # ═══════════════════════════════════════════════════════════════════
    # CRITICAL FIX: Verify tick is for the CORRECT symbol before exit check
    # After symbol switch, WebSocket may still be sending old symbol's ticks
    # ═══════════════════════════════════════════════════════════════════
    if state.current_trade:
        trade_symbol = state.current_trade.get('symbol', '')
        tick_symbol = tick.get('symbol', '')
        
        # Skip exit check if tick is from wrong symbol
        if tick_symbol and trade_symbol and tick_symbol != trade_symbol:
            # Log only once per minute to avoid spam
            if not hasattr(state, '_last_symbol_mismatch_log'):
                state._last_symbol_mismatch_log = 0
            
            import time
            if time.time() - state._last_symbol_mismatch_log > 60:
                logger.warning(f"⚠ Tick symbol mismatch: got {tick_symbol}, need {trade_symbol} — waiting...")
                state._last_symbol_mismatch_log = time.time()
            
            return "IN_TRADE"  # Wait for correct tick
        
        # Also validate tick has reasonable price relative to entry
        entry_price = state.current_trade.get('entry_price', 0)
        tick_ltp = tick.get('ltp', 0)
        
        if entry_price > 0 and tick_ltp > 0:
            price_diff_pct = abs(tick_ltp - entry_price) / entry_price * 100
            
            # If price differs by >50% from entry, likely wrong symbol data
            if price_diff_pct > 50:
                if not hasattr(state, '_last_price_mismatch_log'):
                    state._last_price_mismatch_log = 0
                
                import time
                if time.time() - state._last_price_mismatch_log > 60:
                    logger.warning(f"⚠ Suspicious tick: Entry ₹{entry_price:.2f} vs LTP ₹{tick_ltp:.2f} ({price_diff_pct:.0f}% diff) — skipping")
                    state._last_price_mismatch_log = time.time()
                
                return "IN_TRADE"  # Wait for valid tick
    
    # Calculate RSI for momentum exit
    rsi = _calculate_rsi(recent_ticks) if recent_ticks else None
    
    # Check exit conditions (now includes RSI for momentum exit)
    should_exit, exit_reason = exit_check_func(
        state.current_trade, tick, greeks, state.day_type, logger, rsi
    )
    
    if should_exit:
        # FIX: Pass the SAME tick that triggered exit to exit_position
        # This prevents PnL mismatch from calling get_tick() again
        result = broker.exit_position(
            state.current_trade, exit_reason, 
            state.daily_pnl_inr, total_capital,
            current_tick=tick
        )
        if not result.get('exit_confirmed', True):
            logger.error("🚨 Exit was not confirmed. Holding trade state and blocking new entries.")
            state.state = "KILL_SWITCH"
            state.manual_intervention_required = True
            state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
            return "KILL_SWITCH"
        
        # Get direction BEFORE clearing trade
        trade_direction = state.current_trade.get('direction', 'CE') if state.current_trade else None
        
        is_loss = result['pnl_inr'] < 0
        state.update_pnl(result['pnl_inr'], total_capital, is_loss, trade_direction)
        
        # 🔄 STRIKE ROTATION after trade exit (Gemini recommendation)
        # Check if spot has moved 50+ pts from current strike
        if broker.check_and_rotate_strike(trade_direction):
            logger.info("📍 Strike rotated to stay ATM")
        
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
