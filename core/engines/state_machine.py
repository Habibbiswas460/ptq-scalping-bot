"""
PTQ Scalping Bot - State Machine
Trading state management (IDLE, ENTRY_READY, IN_TRADE, COOLDOWN)
"""

import os
import csv
import json
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from config.constants import (
    CONFIG,
    MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
    CONSECUTIVE_LOSS_LIMIT,
    COOLDOWN_NORMAL_SEC, COOLDOWN_AFTER_SL_SEC,
    COOLDOWN_AFTER_CONSECUTIVE_LOSS, COOLDOWN_AFTER_PROFIT_SEC,
    COOLDOWN_NON_TRADE_BLOCK_SEC,
    COOLDOWN_EXPIRY_NORMAL, COOLDOWN_EXPIRY_AFTER_SL,
    SESSION_FILTER_ENABLED, ALLOWED_SESSIONS,
    EXPIRY_ONLY_SESSIONS, BLACKOUT_SESSIONS,
    TRADING_START_TIME,
    ENTRY_SIGNAL_MAX_AGE_MS, ENTRY_MAX_DRIFT_PCT,
    EXIT_REALISED_ATR_ENABLED,
    EXIT_REALISED_ATR_WINDOW_SEC,
)
from utils.helpers import now, calculate_position_size
from core.runtime import runtime_state

# Strike rotation interval (seconds)
STRIKE_ROTATION_INTERVAL = 60

# v3.4: Intraday spike detection — pause after sudden price jumps
SPIKE_THRESHOLD_PCT = 1.5   # 1.5% spot move in ≤10 seconds = spike
SPIKE_PAUSE_SEC = 60         # Pause 60s after spike detected
_last_spot_prices = []        # Ring buffer of (timestamp, spot_price)
_spike_pause_until = None     # datetime when spike pause expires
_FUTURE_SIGNAL_TOLERANCE_MS = 250.0
_module_logger = logging.getLogger(__name__)


def _record_execution_guard_metric(status: str, reason: str, details: Dict, tick: Dict) -> None:
    """Persist execution-guard metrics for paper/live tuning and post-run analysis."""
    try:
        runtime_state.increment_counter("exec_guard_total", 1)
        runtime_state.increment_counter(f"exec_guard_{status}", 1)
        if reason:
            runtime_state.increment_counter(f"exec_guard_reason_{reason}", 1)

        event = {
            "recorded_at": datetime.now().isoformat(),
            "status": status,
            "reason": reason,
            "details": details or {},
            "tick_time": str((tick or {}).get("original_timestamp") or (tick or {}).get("timestamp") or ""),
            "ltp": float((tick or {}).get("ltp", 0) or 0),
            "spot_price": float((tick or {}).get("spot_price", 0) or 0),
        }

        day = datetime.now().strftime("%Y-%m-%d")
        out_dir = os.path.join("logs", "readiness", day)
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, "execution_guard_metrics.jsonl")
        with open(out_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
    except Exception:
        # Metrics should never block trading transitions.
        pass


def _parse_signal_dt(raw_value) -> Optional[datetime]:
    """Parse supported timestamp formats for signal freshness checks."""
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value if raw_value.tzinfo else raw_value.replace(tzinfo=timezone.utc)
    if isinstance(raw_value, (int, float)):
        try:
            ts = float(raw_value)
            # Handle milliseconds or microseconds
            if ts > 1e15:
                ts /= 1_000_000.0
            elif ts > 1e12:
                ts /= 1_000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(raw_value, str):
        try:
            parsed = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _signal_execution_guard(signal_params: Dict, tick: Dict) -> Tuple[bool, str, Dict]:
    """Block entries when signal is stale or market moved too far before execution."""
    signal_price = float(signal_params.get('signal_ltp', 0) or 0)
    current_price = float(tick.get('ltp', tick.get('price', 0)) or 0)

    # Price drift guard to avoid chasing moved premiums.
    if signal_price > 0 and current_price > 0:
        drift_pct = abs(current_price - signal_price) / signal_price * 100.0
        if drift_pct > float(ENTRY_MAX_DRIFT_PCT):
            return False, (
                f"Execution drift too high {drift_pct:.2f}% > {ENTRY_MAX_DRIFT_PCT:.2f}% "
                f"(sig ₹{signal_price:.2f} -> now ₹{current_price:.2f})"
            ), {
                "check": "drift",
                "drift_pct": round(drift_pct, 4),
                "signal_price": signal_price,
                "current_price": current_price,
                "max_drift_pct": float(ENTRY_MAX_DRIFT_PCT),
            }

    # Signal age guard for delayed loop/order placement.
    signal_dt = _parse_signal_dt(signal_params.get('signal_timestamp'))
    tick_dt = _parse_signal_dt(tick.get('original_timestamp') or tick.get('timestamp'))
    if signal_dt and tick_dt:
        age_ms = (tick_dt - signal_dt).total_seconds() * 1000.0
        if age_ms < -_FUTURE_SIGNAL_TOLERANCE_MS:
            return False, (
                f"Signal timestamp is in future by {abs(age_ms):.0f}ms "
                f"(tolerance {_FUTURE_SIGNAL_TOLERANCE_MS:.0f}ms)"
            ), {
                "check": "future_signal",
                "age_ms": round(age_ms, 2),
                "future_tolerance_ms": _FUTURE_SIGNAL_TOLERANCE_MS,
            }
        if age_ms > float(ENTRY_SIGNAL_MAX_AGE_MS):
            return False, f"Signal stale {age_ms:.0f}ms > {ENTRY_SIGNAL_MAX_AGE_MS}ms", {
                "check": "stale",
                "age_ms": round(age_ms, 2),
                "max_age_ms": float(ENTRY_SIGNAL_MAX_AGE_MS),
            }

    return True, "ok", {
        "check": "pass",
        "signal_price": signal_price,
        "current_price": current_price,
    }


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


def _realised_option_atr(recent_ticks: list, window_sec: int) -> float:
    """Realised range of the option's own premium over the trailing window, in points.

    The `atr` key the early-cut branch reads has never been populated anywhere in the
    codebase, so that branch has always taken its low-volatility path. This computes a real
    volatility figure from the tick buffer the bot already holds. Enabling it CHANGES LIVE
    BEHAVIOUR, so it is gated behind EXIT_REALISED_ATR_ENABLED and measured on its own.
    """
    if not recent_ticks:
        return 0.0
    prices = []
    for t in recent_ticks[-int(max(window_sec, 1)):]:
        ltp = t.get('ltp')
        if ltp:
            prices.append(ltp)
    if len(prices) < 5:
        return 0.0
    return round(max(prices) - min(prices), 2)


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
        self.daily_loss_alerted = False  # DAILY_LOSS_ALERT pre-warning, see check_daily_loss_alert()
        
        # Trade counters
        self.trades_this_hour = 0
        self.total_trades_today = 0
        self.consecutive_losses = 0
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
        self.vix_source = "estimate"
        
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
                    _module_logger.info("✅ CE cooldown expired - allowing recovery trade")
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
                    _module_logger.info("✅ PE cooldown expired - allowing recovery trade")
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
            
            _module_logger.info(f"✅ Restored from {trade_count} trades: PnL ₹{total_pnl:+,.0f} ({wins}W/{losses}L)")
            return True
            
        except Exception as e:
            _module_logger.warning(f"⚠️ Could not restore trades: {e}")
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
                    _module_logger.info(
                        f"⏸️ CE direction on cooldown for {self.DIRECTION_COOLDOWN_MIN}min "
                        f"(after {self.consecutive_ce_losses} losses)"
                    )
            elif direction == 'PE':
                self.consecutive_pe_losses += 1
                # Set cooldown after 2 consecutive losses
                if self.consecutive_pe_losses >= 2:
                    self.pe_blocked_until = datetime.now() + timedelta(minutes=self.DIRECTION_COOLDOWN_MIN)
                    _module_logger.info(
                        f"⏸️ PE direction on cooldown for {self.DIRECTION_COOLDOWN_MIN}min "
                        f"(after {self.consecutive_pe_losses} losses)"
                    )
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


def _log_idle_block(state, logger, kind: str, msg: str) -> None:
    """Say why IDLE produced nothing, once per distinct reason.

    Both gates above return "IDLE" with no output, so a bot that is awake, ticking and
    evaluating nothing looks exactly like a bot with no signals. On 2026-09-07 that hid a
    30-minute streak pause: `dvf_signals` simply stopped at 10:19:20 with no line anywhere
    saying why. Logged on change rather than every loop, since these gates hold for minutes
    at a time and the loop runs ~10x a second.
    """
    key = f"{kind}:{msg}"
    if getattr(state, "_last_idle_block", None) == key:
        return
    state._last_idle_block = key
    logger.info(f"⏸ Entries held ({kind}): {msg}")


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
    
    # Consecutive loss limit with pause — delegated entirely to
    # RiskManager.check_streak_limits(), the single source of truth for this
    # gate. This function used to run its own independent pause/reset clock
    # in parallel with RiskManager's, so every trigger paused trading twice
    # as long as intended, since RiskManager's clock only started once this
    # one's cleared and let a signal through to reach it (see findings.md
    # §2.9). TradingState's own consecutive_losses/consecutive_ce_losses/
    # consecutive_pe_losses counters are unaffected — still maintained by
    # update_pnl() and still used for cooldown-duration selection,
    # per-direction blocking, and the dashboard; only the pause gate itself
    # moved to RiskManager.
    try:
        from core.risk.risk_manager import get_risk_manager
        rm = get_risk_manager()
    except Exception:
        rm = None

    if rm:
        streak_ok, streak_msg = rm.check_streak_limits()
        if not streak_ok:
            if state.loop_count % 5000 == 0:
                logger.info(f"⏸ {streak_msg}")
            return False, streak_msg

    return True, "OK"


def get_cooldown_duration(state: TradingState, is_win: bool = False) -> int:
    """Get appropriate cooldown duration after a real trade exit.

    `is_win` only matters when there's no active loss streak — a losing
    streak's cooldown always takes priority regardless of the trade that
    just closed (mirrors the pre-existing priority order)."""
    if state.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        return COOLDOWN_AFTER_CONSECUTIVE_LOSS
    elif state.consecutive_losses > 0:
        if state.day_type == "EXPIRY":
            return COOLDOWN_EXPIRY_AFTER_SL
        else:
            return COOLDOWN_AFTER_SL_SEC
    elif is_win:
        return COOLDOWN_AFTER_PROFIT_SEC
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
        _log_idle_block(state, logger, "session", session_msg)
        return "IDLE"

    # Trade limits
    limits_ok, limits_msg = check_trade_limits(state, logger)
    if not limits_ok:
        _log_idle_block(state, logger, "limits", limits_msg)
        return "IDLE"

    # Past both gates: forget the last hold reason so the next one is reported even if it
    # repeats a message seen earlier in the session.
    state._last_idle_block = None
    
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
        from core.engines.position_size_engine import PositionSizeEngine
        rm = get_risk_manager()
        can_trade, risk_details = rm.can_trade(spot_price=tick.get('spot_price'))
        
        if not can_trade:
            reasons = risk_details.get('reasons', ['Risk check failed'])
            logger.warning(f"⚠ RISK BLOCKED: {', '.join(reasons)}")
            logger.state_change("ENTRY_READY", "COOLDOWN", f"Risk: {reasons[0]}")
            state.cooldown_until = now() + timedelta(seconds=COOLDOWN_NON_TRADE_BLOCK_SEC)
            return "COOLDOWN"

        risk_budget = risk_details.get('risk_budget', {})
        
        if isinstance(risk_budget, dict):
            logger.info(
                "📊 Risk budget: "
                f"capital=₹{risk_budget.get('capital', 0)} | "
                f"per_trade=₹{risk_budget.get('per_trade_risk_amount', 0)} | "
                f"daily_cap=₹{risk_budget.get('daily_risk_budget_amount', 0)} | "
                f"remaining=₹{risk_budget.get('remaining_risk_amount', 0)} | "
                f"daily_loss_state={risk_budget.get('daily_loss_state', {})} | "
                f"recovery={risk_budget.get('recovery_mode', {})}"
            )

        for warning in risk_details.get('warnings', []):
            logger.info(f"📊 Risk sizing context: {warning}")
    except Exception as e:
        logger.warning(f"⚠ RiskManager check error: {e} — proceeding with default")
        risk_budget = {}
    
    # Get SMART SCALP v3.4 signal params
    try:
        from core.engines.entry_engine import get_last_signal_params, get_signal_direction
        signal_params = get_last_signal_params()
        direction = get_signal_direction()
    except ImportError:
        signal_params = {}
        direction = "CE"

    details = signal_params.get('details', {}) if isinstance(signal_params, dict) else {}

    # The drift guard must compare the traded contract's price against
    # itself. `tick` here reflects whatever is currently subscribed, which
    # can be the opposite instrument from `direction` (place_order() only
    # switches subscription at order time) — same cross-direction mismatch
    # entry_engine.py already resolves for signal_ltp. Without this, the
    # guard compares e.g. a PE signal price to a CE "current" price and
    # reports a bogus 30-60% drift, blocking every cross-direction entry.
    guard_tick = tick
    try:
        current_symbol = getattr(broker, 'current_symbol', '') or ''
        if current_symbol and not current_symbol.endswith(direction):
            fresh_tick = broker.get_tick_for_direction(direction)
            if fresh_tick:
                guard_tick = fresh_tick
    except Exception:
        pass

    exec_ok, exec_reason, exec_details = _signal_execution_guard(signal_params if isinstance(signal_params, dict) else {}, guard_tick)
    if exec_ok:
        _record_execution_guard_metric("pass", "ok", exec_details, guard_tick)
    else:
        reason_tag = str(exec_details.get("check", "blocked")) if isinstance(exec_details, dict) else "blocked"
        _record_execution_guard_metric("blocked", reason_tag, exec_details, guard_tick)
    if not exec_ok:
        logger.warning(f"⚠ ENTRY SKIPPED: {exec_reason}")
        logger.state_change("ENTRY_READY", "COOLDOWN", f"Exec guard: {exec_reason}")
        state.cooldown_until = now() + timedelta(seconds=COOLDOWN_NON_TRADE_BLOCK_SEC)
        return "COOLDOWN"

    weighted_score = signal_params.get('score', details.get('weighted_score', 0)) if isinstance(signal_params, dict) else 0
    confidence = signal_params.get('confidence', 0) if isinstance(signal_params, dict) else 0
    market_quality = details.get('market_quality', details.get('market_quality_score', 0))
    regime = signal_params.get('regime', details.get('regime', 'UNKNOWN')) if isinstance(signal_params, dict) else details.get('regime', 'UNKNOWN')
    sl_points = signal_params.get('sl_points', CONFIG['risk_management'].get('stop_loss_amount', 0) / max(1, CONFIG['trading'].get('lot_size', 1))) if isinstance(signal_params, dict) else 0
    lot_size = int(CONFIG['trading'].get('lot_size', 1))

    size_engine = PositionSizeEngine()
    allocation = size_engine.calculate(
        capital=risk_budget.get('capital', CONFIG['capital']['total_capital']) if isinstance(risk_budget, dict) else CONFIG['capital']['total_capital'],
        risk_budget=risk_budget,
        weighted_score=weighted_score,
        confidence=confidence,
        market_quality=market_quality,
        regime=regime,
        volatility={'vix': state.estimated_vix},
        recovery_mode=risk_budget.get('recovery_mode', {'active': False}) if isinstance(risk_budget, dict) else {'active': False},
        daily_loss_state=risk_budget.get('daily_loss_state', {'loss_utilization': 0.0}) if isinstance(risk_budget, dict) else {'loss_utilization': 0.0},
        sl_points=sl_points,
        lot_size=lot_size,
    )
    adjusted_qty = int(allocation.get('position_size', 0) or 0)

    if adjusted_qty <= 0:
        cap_reason = allocation.get('cap_reason') or 'allocator_zero_quantity'
        logger.warning(f"⚠ POSITION SIZE BLOCKED: qty=0 | reason={cap_reason}")
        logger.state_change("ENTRY_READY", "COOLDOWN", f"Allocator: {cap_reason}")
        state.cooldown_until = now() + timedelta(seconds=COOLDOWN_NON_TRADE_BLOCK_SEC)
        return "COOLDOWN"

    logger.info(
        f"🎯 SMART SCALP: {direction} | Qty: {adjusted_qty} | Conf: {confidence}% | "
        f"Alloc: {allocation.get('allocation_grade')} | Risk ₹{allocation.get('risk_amount', 0):.0f}"
    )
    
    # Store direction in trade for exit reference
    trade = broker.place_order("BUY", qty=adjusted_qty, trades_this_hour=state.trades_this_hour, 
                                direction=direction, signal_params=signal_params)
    
    if trade:
        trade.update({
            'risk_budget_used': allocation.get('risk_budget_used'),
            'risk_amount': allocation.get('risk_amount'),
            'allocation_grade': allocation.get('allocation_grade'),
            'position_size_breakdown': allocation.get('breakdown', {}),
        })
        state.current_trade = trade
        state.trades_this_hour += 1

        try:
            from core.services.database import log_trade_entry
            log_trade_entry({
                'order_id': trade.get('order_id'),
                'symbol': trade.get('symbol'),
                'direction': trade.get('direction', direction),
                'side': trade.get('side', 'BUY'),
                'qty': trade.get('qty', adjusted_qty),
                'entry_price': trade.get('entry_price'),
                'entry_time': trade.get('entry_time'),
                'entry_reason': details.get('reason', 'Entry signal'),
                'score': signal_params.get('score') if isinstance(signal_params, dict) else None,
                'confidence': signal_params.get('confidence') if isinstance(signal_params, dict) else None,
                'market_quality_score': details.get('market_quality_score'),
                'market_quality_grade': details.get('market_quality_grade'),
                'market_quality_components': details.get('market_quality_components', {}),
                'hard_reject_reason': details.get('hard_reject_reason'),
                'risk_budget_used': allocation.get('risk_budget_used'),
                'risk_amount': allocation.get('risk_amount'),
                'allocation_grade': allocation.get('allocation_grade'),
                'position_size_breakdown': allocation.get('breakdown', {}),
                'factors': signal_params.get('factors', []) if isinstance(signal_params, dict) else [],
                'greeks': greeks,
            })
        except Exception as e:
            logger.warning(f"⚠ DB trade entry logging failed: {e}")

        try:
            # Position-recovery record (findings.md/fixed.md §10.1 — this
            # table previously had zero callers anywhere, so a crash/restart
            # mid-trade left the position completely unmonitored with no
            # trace of it ever having existed. main()'s startup now checks
            # this table and refuses to trade if it finds a leftover ACTIVE
            # row — see the check right after broker.connect().
            from core.services.database import save_position
            save_position({
                'order_id': trade.get('order_id'),
                'symbol': trade.get('symbol'),
                'direction': trade.get('direction', direction),
                'side': trade.get('side', 'BUY'),
                'qty': trade.get('qty', adjusted_qty),
                'entry_price': trade.get('entry_price'),
                'entry_time': trade.get('entry_time'),
                'stop_loss': trade.get('fixed_sl_price'),
                'take_profit': trade.get('tp_price'),
                'current_price': trade.get('entry_price'),
                'unrealized_pnl': 0,
                'broker_order_id': trade.get('broker_order_id') or trade.get('order_id'),
            })
        except Exception as e:
            logger.warning(f"⚠ Active-position recovery record failed: {e}")

        if CONFIG['telegram'].get('notify_entries'):
            try:
                from core.services.telegram_bot import notify_entry
                notify_entry(trade)
            except Exception as e:
                logger.debug(f"Telegram entry notify failed: {e}")

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
        state.cooldown_until = now() + timedelta(seconds=COOLDOWN_NON_TRADE_BLOCK_SEC)
        return "COOLDOWN"


def finalize_trade_exit_accounting(order_id, trade_direction, result, exit_reason,
                                    current_trade, logger, state=None):
    """Post-exit accounting shared by every exit path — the normal SL/TP/RSI
    exit below in state_in_trade(), and kill-switch/emergency exits in
    core/main.py's close_current_trade(). Previously only the normal-exit
    path ran this (see fixed.md §17), so any kill-switch/stale-data/manual
    exit left RiskManager's daily PnL and consecutive-loss counters
    undercounted, the trade's DB row stuck 'OPEN' with no exit data, and its
    active_positions row stuck 'ACTIVE' forever — the last of which is what
    §15.11's crash-recovery halt reads on the next restart, so a stale row
    there triggers a false-positive halt for a position that already closed
    correctly.
    """
    try:
        from core.risk.risk_manager import get_risk_manager
        rm = get_risk_manager()
        if rm:
            rm.record_trade({'pnl': result['pnl_inr'], 'direction': trade_direction})
    except Exception as e:
        # Not a cosmetic failure: RiskManager's daily/weekly PnL and
        # consecutive-loss counters (used by can_trade()'s risk gates) are
        # only ever updated here. A swallowed exception means this trade's
        # loss silently never counts toward those limits, so log it loudly
        # and track the miss instead of a quiet warning.
        if state is not None:
            state.risk_tracking_failures = getattr(state, 'risk_tracking_failures', 0) + 1
            miss_no = state.risk_tracking_failures
        else:
            miss_no = '?'
        logger.error(
            f"🚨 RiskManager trade recording FAILED (miss #{miss_no}) - "
            f"pnl={result.get('pnl_inr')} direction={trade_direction} not counted toward "
            f"risk limits: {e}",
            exc_info=True,
        )

    try:
        from core.services.database import log_trade_exit

        # Trade-scoped MFE/MAE (tracked live in exit_engine.check_hard_sl on
        # this exact trade dict) instead of the global rolling tick buffer,
        # which isn't scoped to a single trade and was wrong ~15-19% of the
        # time on short-lived trades.
        log_trade_exit(order_id, {
            'exit_price': result.get('exit_price'),
            'exit_time': now(),
            'exit_reason': result.get('exit_reason', exit_reason),
            'pnl': result.get('pnl_inr', 0),
            'pnl_pct': result.get('pnl_pct', 0),
            'hold_time_sec': result.get('hold_time', 0),
            'mfe': (current_trade or {}).get('mfe_inr', 0.0),
            'mae': (current_trade or {}).get('mae_inr', 0.0),
        })
    except Exception as e:
        logger.warning(f"⚠ DB trade exit logging failed: {e}")

    try:
        from core.services.database import close_position
        close_position(order_id)
    except Exception as e:
        logger.warning(f"⚠ Active-position recovery record close failed: {e}")


def state_in_trade(tick: Dict, greeks: Dict, state: TradingState,
                   exit_check_func, broker, total_capital: float, logger) -> str:
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
    recent_ticks = runtime_state.get_recent_ticks(max_items=MAX_RECENT_TICKS)
    rsi = _calculate_rsi(recent_ticks) if recent_ticks else None

    # Experimental: populate the `atr` the early-cut branch reads (no-op unless enabled)
    if EXIT_REALISED_ATR_ENABLED and recent_ticks:
        tick['atr'] = _realised_option_atr(recent_ticks, EXIT_REALISED_ATR_WINDOW_SEC)
    
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

        finalize_trade_exit_accounting(
            state.current_trade.get('order_id'), trade_direction, result, exit_reason,
            state.current_trade, logger, state=state
        )

        if CONFIG['telegram'].get('notify_exits'):
            try:
                from core.services.telegram_bot import notify_exit
                notify_exit(state.current_trade, result.get('pnl_inr', 0), result.get('exit_reason', exit_reason))
            except Exception as e:
                logger.debug(f"Telegram exit notify failed: {e}")

        # 🔄 STRIKE ROTATION after trade exit (Gemini recommendation)
        # Check if spot has moved 50+ pts from current strike
        if broker.check_and_rotate_strike(trade_direction):
            logger.info("📍 Strike rotated to stay ATM")
        
        state.current_trade = None

        # Set cooldown
        cooldown_sec = get_cooldown_duration(state, is_win=not is_loss)
        state.cooldown_until = now() + timedelta(seconds=cooldown_sec)
        
        logger.state_change("IN_TRADE", "COOLDOWN", f"Cooldown {cooldown_sec}s")
        return "COOLDOWN"
    
    return "IN_TRADE"

def state_cooldown(state: TradingState, logger) -> str:
    """Handle COOLDOWN state"""
    if state.cooldown_until is None:
        cooldown_sec = get_cooldown_duration(state)
        state.cooldown_until = now() + timedelta(seconds=cooldown_sec)
        logger.warning(
            f"⚠ COOLDOWN timestamp missing; initialized fallback cooldown {cooldown_sec}s"
        )
    if now() >= state.cooldown_until:
        logger.state_change("COOLDOWN", "IDLE", "Cooldown ended")
        return "IDLE"
    return "COOLDOWN"