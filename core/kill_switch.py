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


def emergency_check(tick: Dict, daily_pnl_inr: float, total_trades_today: int,
                    last_valid_tick_time: Optional[datetime]) -> Tuple[bool, str, Dict]:
    """Emergency conditions check - STAGE-9: Kill Switch"""
    global tick_freeze_count
    
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
    
    # Spread check
    spread = spread_pct(tick)
    if spread > KILL_SWITCH_SPREAD:
        return True, "Wide spread KILL", {'spread_pct': spread}
    
    # Daily loss limit (kill switch)
    if abs(daily_pnl_inr) >= KILL_SWITCH_DAILY_LOSS and daily_pnl_inr < 0:
        return True, "Kill switch daily loss", {'daily_pnl_inr': daily_pnl_inr}
    
    # Max daily loss
    if abs(daily_pnl_inr) >= MAX_DAILY_LOSS_AMOUNT and daily_pnl_inr < 0:
        return True, "Max daily loss hit", {'daily_pnl_inr': daily_pnl_inr}
    
    # Max trades per day
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
