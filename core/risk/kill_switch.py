"""
PTQ Scalping Bot - Kill Switch
Emergency checks and safety mechanisms
"""

from datetime import datetime
from typing import Dict, Tuple, Optional

from config.constants import (
    TICK_TIMEOUT_SEC, KILL_SWITCH_LATENCY, KILL_SWITCH_SPREAD,
    KILL_SWITCH_DAILY_LOSS, MAX_DAILY_LOSS_AMOUNT, MAX_TRADES_PER_DAY
)
from utils.helpers import calc_latency_ms, spread_pct


# Track tick freeze
tick_freeze_count = 0

# Track consecutive wide spreads (don't kill on single spike)
wide_spread_count = 0
WIDE_SPREAD_CONSECUTIVE_LIMIT = 5  # Need 5 consecutive wide spreads to trigger

# Track kill switch recovery
kill_switch_cooldown_until: Optional[datetime] = None
KILL_SWITCH_SPREAD_COOLDOWN_SEC = 30  # Wait 30s then retry


def emergency_check(tick: Dict, daily_pnl_inr: float, total_trades_today: int,
                    last_valid_tick_time: Optional[datetime]) -> Tuple[bool, str, Dict]:
    """Emergency conditions check - STAGE-9: Kill Switch
    
    Spread kill switch is RECOVERABLE - pauses for 30s then retries.
    Loss-based kill switch is PERMANENT for the day.
    """
    global tick_freeze_count, wide_spread_count, kill_switch_cooldown_until
    
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
    
    # Latency check
    latency = calc_latency_ms(tick)
    if latency > KILL_SWITCH_LATENCY:
        return True, "High latency KILL", {'latency_ms': latency}
    
    # Spread check - RECOVERABLE, requires consecutive wide spreads
    spread = spread_pct(tick)
    if spread > KILL_SWITCH_SPREAD:
        wide_spread_count += 1
        if wide_spread_count >= WIDE_SPREAD_CONSECUTIVE_LIMIT:
            # Set cooldown instead of permanent kill
            kill_switch_cooldown_until = datetime.now() + __import__('datetime').timedelta(seconds=KILL_SWITCH_SPREAD_COOLDOWN_SEC)
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
