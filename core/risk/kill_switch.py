"""
PTQ Scalping Bot - Kill Switch
Emergency checks and safety mechanisms
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import threading

from config.constants import (
    TICK_TIMEOUT_SEC, KILL_SWITCH_LATENCY, KILL_SWITCH_SPREAD,
    KILL_SWITCH_DAILY_LOSS, MAX_DAILY_LOSS_AMOUNT, MAX_TRADES_PER_DAY
)
from utils.helpers import calc_latency_ms, spread_pct

# Thread lock for all mutable global state
_lock = threading.Lock()

# Track tick freeze
tick_freeze_count = 0

# Track consecutive rejected ticks (stale/invalid data kill switch)
consecutive_rejected_ticks = 0
CONSECUTIVE_REJECTED_TICK_LIMIT = 100  # ~50 seconds of bad data at 0.5s loop (was 50)
STALE_DATA_WARNED = False

# Stale data kill switch recovery - require cooldown + consecutive valid ticks
stale_data_cooldown_until: Optional[datetime] = None
STALE_DATA_COOLDOWN_SEC = 30  # Wait 30s before allowing recovery (was 60)
consecutive_valid_ticks = 0
CONSECUTIVE_VALID_TICKS_TO_CLEAR = 5  # Need 5 consecutive valid ticks to clear (was 10)

# Track consecutive wide spreads (don't kill on single spike)
wide_spread_count = 0
WIDE_SPREAD_CONSECUTIVE_LIMIT = 10  # Need 10 consecutive wide spreads to trigger (was 5)

# Track kill switch recovery
kill_switch_cooldown_until: Optional[datetime] = None
KILL_SWITCH_SPREAD_COOLDOWN_SEC = 15  # Wait 15s then retry (was 30)

# Track high latency (RECOVERABLE - pause trading when high, resume when low)
high_latency_count = 0
HIGH_LATENCY_CONSECUTIVE_LIMIT = 5  # Need 5 consecutive high latency to trigger pause (was 3)
HIGH_LATENCY_THRESHOLD_MS = 500  # Above 500ms = high latency (was 400)
high_latency_paused = False  # Track if we're in high latency pause mode
consecutive_low_latency = 0
LOW_LATENCY_RECOVERY_COUNT = 3  # Need 3 consecutive low latency to resume (was 5)


def track_rejected_tick():
    """Track consecutive rejected ticks. Returns (should_kill, reason, details).
    Called from main loop when is_data_valid() returns False.
    If too many consecutive ticks are rejected, stop trading."""
    global consecutive_rejected_ticks, STALE_DATA_WARNED, consecutive_valid_ticks, stale_data_cooldown_until
    with _lock:
        consecutive_rejected_ticks += 1
        consecutive_valid_ticks = 0  # Reset valid tick counter on any rejected tick
        
        if consecutive_rejected_ticks >= CONSECUTIVE_REJECTED_TICK_LIMIT and not STALE_DATA_WARNED:
            STALE_DATA_WARNED = True
            # Set cooldown to prevent immediate recovery from single good tick
            stale_data_cooldown_until = datetime.now() + timedelta(seconds=STALE_DATA_COOLDOWN_SEC)
            return True, "Stale data KILL", {'consecutive_rejected': consecutive_rejected_ticks, 'cooldown_sec': STALE_DATA_COOLDOWN_SEC}
        
        return False, "", {}


def reset_rejected_tick_counter():
    """Track valid tick received. Returns (can_clear_kill_switch, info).
    Kill switch only clears after cooldown expires + consecutive valid ticks."""
    global consecutive_rejected_ticks, STALE_DATA_WARNED, consecutive_valid_ticks, stale_data_cooldown_until
    with _lock:
        # Always track valid tick
        consecutive_valid_ticks += 1
        consecutive_rejected_ticks = 0  # Reset rejected counter
        
        # If not in stale data kill state, nothing special needed
        if not STALE_DATA_WARNED:
            return True, {}
        
        # We're in stale data kill state - check if we can recover
        now = datetime.now()
        
        # Check cooldown first
        if stale_data_cooldown_until and now < stale_data_cooldown_until:
            remaining = (stale_data_cooldown_until - now).total_seconds()
            return False, {'reason': 'cooldown', 'remaining_sec': remaining, 'valid_ticks': consecutive_valid_ticks}
        
        # Cooldown expired - check if we have enough consecutive valid ticks
        if consecutive_valid_ticks < CONSECUTIVE_VALID_TICKS_TO_CLEAR:
            return False, {'reason': 'need_more_valid', 'valid_ticks': consecutive_valid_ticks, 'required': CONSECUTIVE_VALID_TICKS_TO_CLEAR}
        
        # OK to clear - reset everything
        STALE_DATA_WARNED = False
        stale_data_cooldown_until = None
        consecutive_valid_ticks = 0
        return True, {'reason': 'recovered', 'valid_ticks': consecutive_valid_ticks}


def is_stale_data_kill_active():
    """Check if stale data kill switch is still active (in cooldown or waiting for valid ticks)."""
    return STALE_DATA_WARNED


def is_high_latency_paused():
    """Check if trading is paused due to high latency."""
    return high_latency_paused


def get_latency_status():
    """Get current latency status for logging."""
    return {
        'paused': high_latency_paused,
        'high_count': high_latency_count,
        'low_count': consecutive_low_latency,
        'threshold_ms': HIGH_LATENCY_THRESHOLD_MS
    }


def emergency_check(tick: Dict, daily_pnl_inr: float, total_trades_today: int,
                    last_valid_tick_time: Optional[datetime]) -> Tuple[bool, str, Dict]:
    """Emergency conditions check - STAGE-9: Kill Switch
    
    Spread kill switch is RECOVERABLE - pauses for 30s then retries.
    Loss-based kill switch is PERMANENT for the day.
    """
    global tick_freeze_count, wide_spread_count, kill_switch_cooldown_until
    global high_latency_count, high_latency_paused, consecutive_low_latency
    
    with _lock:
        # Check if we're in spread cooldown (recoverable kill switch)
        if kill_switch_cooldown_until:
            if datetime.now() < kill_switch_cooldown_until:
                remaining = (kill_switch_cooldown_until - datetime.now()).total_seconds()
                return True, "Spread cooldown", {'remaining_sec': remaining}
            else:
                # Cooldown expired - reset and retry
                kill_switch_cooldown_until = None
                wide_spread_count = 0
        
        # Tick freeze check
        if last_valid_tick_time:
            time_since_tick = (datetime.now() - last_valid_tick_time).total_seconds()
            if time_since_tick > TICK_TIMEOUT_SEC:
                tick_freeze_count += 1
                if tick_freeze_count > 3:
                    return True, "Data feed frozen", {'freeze_duration': time_since_tick}
        
        # Latency check - RECOVERABLE (pause when high, resume when low)
        latency = calc_latency_ms(tick)
        
        if latency > HIGH_LATENCY_THRESHOLD_MS:
            high_latency_count += 1
            consecutive_low_latency = 0  # Reset low latency counter
            
            if high_latency_count >= HIGH_LATENCY_CONSECUTIVE_LIMIT:
                high_latency_paused = True
                return True, "High latency PAUSE", {'latency_ms': latency, 'consecutive': high_latency_count, 'recoverable': True}
            # Not enough consecutive - just skip this tick
            return False, "", {}
        else:
            # Latency is OK
            high_latency_count = 0  # Reset high latency counter
            consecutive_low_latency += 1
            
            # If we were paused due to high latency, check if we can resume
            if high_latency_paused:
                if consecutive_low_latency >= LOW_LATENCY_RECOVERY_COUNT:
                    high_latency_paused = False
                    # Return False to indicate we can trade again
                else:
                    # Still need more low latency ticks before resuming
                    return True, "Latency recovery", {'latency_ms': latency, 'low_latency_count': consecutive_low_latency, 'need': LOW_LATENCY_RECOVERY_COUNT}
        
        # Spread check - RECOVERABLE, requires consecutive wide spreads
        # BUG FIX #18: Use >= for boundary condition (exactly at limit should also trigger)
        spread = spread_pct(tick)
        if spread >= KILL_SWITCH_SPREAD:
            wide_spread_count += 1
            if wide_spread_count >= WIDE_SPREAD_CONSECUTIVE_LIMIT:
                # Set cooldown instead of permanent kill
                kill_switch_cooldown_until = datetime.now() + timedelta(seconds=KILL_SWITCH_SPREAD_COOLDOWN_SEC)
                return True, "Wide spread KILL", {'spread_pct': spread, 'consecutive': wide_spread_count, 'cooldown_sec': KILL_SWITCH_SPREAD_COOLDOWN_SEC}
            # Not enough consecutive - skip this tick but don't kill
            return False, "", {}
        else:
            # Spread is OK - reset counter
            wide_spread_count = 0
        
        # Daily loss limit (kill switch) - PERMANENT
        if abs(daily_pnl_inr) >= KILL_SWITCH_DAILY_LOSS and daily_pnl_inr < 0:
            return True, "Kill switch daily loss", {'daily_pnl_inr': daily_pnl_inr}
        
        # Max daily loss - PERMANENT
        if abs(daily_pnl_inr) >= MAX_DAILY_LOSS_AMOUNT and daily_pnl_inr < 0:
            return True, "Max daily loss hit", {'daily_pnl_inr': daily_pnl_inr}
        
        # Max trades per day - PERMANENT
        if total_trades_today >= MAX_TRADES_PER_DAY:
            return True, "Max daily trades hit", {'trades': total_trades_today}
        
        # Reset freeze counter if all good
        tick_freeze_count = 0
        
        return False, "", {}


def check_daily_loss_alert(daily_pnl_inr: float, already_alerted: bool, 
                            logger) -> Tuple[bool, bool]:
    """
    Check daily loss alert threshold
    Returns: (should_continue_trading, alerted)
    """
    from config.constants import CONFIG
    
    max_loss = CONFIG['capital']['max_daily_loss_amount']
    alert_threshold = CONFIG['capital']['daily_loss_alert_threshold']
    
    # Kill switch - stop trading
    if daily_pnl_inr <= -max_loss:
        logger.error(f"🛑 DAILY LOSS LIMIT! PnL: ₹{daily_pnl_inr:.2f}")
        return False, already_alerted
    
    # Alert threshold
    if daily_pnl_inr <= -alert_threshold and not already_alerted:
        logger.warning(f"⚠️ Daily loss alert! PnL: ₹{daily_pnl_inr:.2f}")
        return True, True
    
    return True, already_alerted
