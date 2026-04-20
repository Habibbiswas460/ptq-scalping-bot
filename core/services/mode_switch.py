"""
PTQ Scalping Bot - Adaptive Mode Switch System
Auto-switches between AGGRESSIVE ↔ SAFE based on market conditions
Professional prop-style trading control
"""

from datetime import datetime
from typing import Dict, List, Tuple
import threading

from config.constants import CONFIG, MAX_DAILY_LOSS_AMOUNT

# Thread lock for mode state
_mode_lock = threading.Lock()


# =============================================================================
# TRADING MODES
# =============================================================================

MODE_AGGRESSIVE = "AGGRESSIVE"
MODE_SAFE = "SAFE"
MODE_LOCKDOWN = "LOCKDOWN"

# Current mode (global state)
_current_mode = MODE_AGGRESSIVE


# =============================================================================
# MODE THRESHOLDS
# =============================================================================

from config.constants import PAPER_TRADING

# Paper trading = relaxed thresholds for testing
if PAPER_TRADING:
    AGGRESSIVE_THRESHOLDS = {
        'min_volume_ratio': 0.5,      # Relaxed for paper
        'delta_min': 0.15,
        'delta_max': 0.90,
        'gamma_normal_max': 0.15,
        'gamma_expiry_max': 0.20,
        'theta_sec_limit': 0.35,
        'spread_limit_pct': 2.5,      # Relaxed for paper - options can have wide spreads
        'chop_threshold': 0.00005,
    }
    
    SAFE_THRESHOLDS = {
        'min_volume_ratio': 0.6,      # Relaxed for paper
        'delta_min': 0.20,
        'delta_max': 0.80,
        'gamma_normal_max': 0.12,
        'gamma_expiry_max': 0.18,
        'theta_sec_limit': 0.30,
        'spread_limit_pct': 2.0,      # Relaxed for paper
        'chop_threshold': 0.0001,
    }
else:
    # Live trading = strict thresholds
    AGGRESSIVE_THRESHOLDS = {
        'min_volume_ratio': 0.8,
        'delta_min': 0.20,
        'delta_max': 0.85,
        'gamma_normal_max': 0.10,
        'gamma_expiry_max': 0.15,
        'theta_sec_limit': 0.25,
        'spread_limit_pct': 1.5,      # Live trading needs tighter spreads
        'chop_threshold': 0.0001,
    }

    SAFE_THRESHOLDS = {
        'min_volume_ratio': 1.1,
        'delta_min': 0.35,
        'delta_max': 0.65,
        'gamma_normal_max': 0.07,
        'gamma_expiry_max': 0.10,
        'theta_sec_limit': 0.15,
        'spread_limit_pct': 1.0,      # Tight spread in safe mode
        'chop_threshold': 0.00015,
    }

# Active thresholds (changes with mode)
active_thresholds = AGGRESSIVE_THRESHOLDS.copy()


# =============================================================================
# SWITCH CONDITION PARAMETERS
# =============================================================================

# Switch to SAFE triggers
CONSECUTIVE_LOSS_TRIGGER = 1          # 1 loss = go safe
VOLUME_DETERIORATION_THRESHOLD = 0.9  # avg ratio < 0.9 = go safe
CHOP_DETECTION_THRESHOLD = 0.0002     # range < 0.02% = chop
THETA_DETERIORATION = 0.30            # theta/sec > 0.30 = go safe
SAFE_HOUR_NORMAL = 13                 # After 1 PM on normal days = safe

# Switch to AGGRESSIVE triggers (ALL must be true)
VOLUME_RECOVERY_THRESHOLD = 1.1       # avg ratio >= 1.1
RANGE_RECOVERY_THRESHOLD = 0.0004     # range > 0.04%
THETA_RECOVERY_THRESHOLD = 0.20       # theta/sec < 0.20

# Lockdown trigger - use 90% of MAX_DAILY_LOSS from settings
# Only lockdown when approaching the user's configured limit
LOCKDOWN_LOSS_THRESHOLD = -MAX_DAILY_LOSS_AMOUNT * 0.9  # e.g., -2700 for ₹3000 max


# =============================================================================
# STATE TRACKING
# =============================================================================

class ModeState:
    """Track state for mode switching decisions"""
    
    def __init__(self):
        self.consecutive_losses = 0
        self.recent_volume_ratios: List[float] = []
        self.recent_ranges: List[float] = []
        self.last_switch_time: datetime = None
        self.switch_cooldown_sec = 60  # Don't switch too fast
        self.mode_history: List[Tuple[datetime, str]] = []
        
    def add_volume_ratio(self, ratio: float):
        """Track volume ratios (keep last 10)"""
        self.recent_volume_ratios.append(ratio)
        if len(self.recent_volume_ratios) > 10:
            self.recent_volume_ratios.pop(0)
    
    def add_range(self, price_range: float):
        """Track price ranges (keep last 10)"""
        self.recent_ranges.append(price_range)
        if len(self.recent_ranges) > 10:
            self.recent_ranges.pop(0)
    
    def avg_volume_ratio(self) -> float:
        """Get average of last 10 volume ratios
        
        BUG FIX #17: Return None-like value (0.0) when no data
        This prevents false assumptions about volume being 'normal'
        """
        if not self.recent_volume_ratios:
            return 0.0  # No data = assume low volume, not normal
        return sum(self.recent_volume_ratios) / len(self.recent_volume_ratios)
    
    def avg_range(self) -> float:
        """Get average of last 10 ranges"""
        if not self.recent_ranges:
            return 0.001
        return sum(self.recent_ranges) / len(self.recent_ranges)
    
    def record_trade_result(self, is_win: bool):
        """Track consecutive losses"""
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
    
    def can_switch(self) -> bool:
        """Check if enough time passed since last switch"""
        if self.last_switch_time is None:
            return True
        elapsed = (datetime.now() - self.last_switch_time).total_seconds()
        return elapsed >= self.switch_cooldown_sec
    
    def record_switch(self, new_mode: str):
        """Record mode switch"""
        self.last_switch_time = datetime.now()
        self.mode_history.append((datetime.now(), new_mode))


# Global state instance
_mode_state = ModeState()


# =============================================================================
# SWITCH LOGIC
# =============================================================================

def should_go_safe(tick: Dict, greeks: Dict, day_type: str, daily_pnl: float) -> Tuple[bool, str]:
    """
    Check if we should switch to SAFE mode
    Returns: (should_switch, reason)
    
    Trigger ANY ONE = switch to SAFE
    """
    global _mode_state
    
    # Paper trading = stay AGGRESSIVE for testing
    if PAPER_TRADING:
        return False, ""
    
    # 1. Consecutive losses
    if _mode_state.consecutive_losses >= CONSECUTIVE_LOSS_TRIGGER:
        return True, f"Consecutive losses: {_mode_state.consecutive_losses}"
    
    # 2. Volume deterioration
    # BUG FIX #17 update: Skip check if no volume data yet (avg=0 means no data collected)
    avg_vol = _mode_state.avg_volume_ratio()
    if avg_vol > 0 and avg_vol < VOLUME_DETERIORATION_THRESHOLD:
        return True, f"Volume deterioration: {avg_vol:.2f}"
    
    # 3. Chop detection (price compression)
    spot_price = tick.get('spot_price', tick.get('ltp', 100) * 100)
    avg_range = _mode_state.avg_range()
    if spot_price > 0 and avg_range < spot_price * CHOP_DETECTION_THRESHOLD:
        return True, f"Chop detected: range {avg_range:.2f}"
    
    # 4. Greeks deterioration
    theta_sec = greeks.get('theta_sec', 0)
    if theta_sec > THETA_DETERIORATION:
        return True, f"Theta spike: {theta_sec:.4f}"
    
    # 5. Time-based decay (after 1 PM on normal days)
    now = datetime.now()
    if now.hour >= SAFE_HOUR_NORMAL and day_type == "NORMAL":
        return True, f"Late session (after {SAFE_HOUR_NORMAL}:00)"
    
    return False, ""


def should_go_aggressive(tick: Dict, greeks: Dict, day_type: str, daily_pnl: float) -> Tuple[bool, str]:
    """
    Check if we should switch to AGGRESSIVE mode
    Returns: (should_switch, reason)
    
    ALL conditions must be true
    """
    global _mode_state
    
    # ALL must be true for aggressive
    conditions = []
    
    # 1. No consecutive losses
    if _mode_state.consecutive_losses > 0:
        return False, "Still in loss streak"
    conditions.append("No losses")
    
    # 2. Volume recovered
    avg_vol = _mode_state.avg_volume_ratio()
    if avg_vol < VOLUME_RECOVERY_THRESHOLD:
        return False, f"Volume not recovered: {avg_vol:.2f}"
    conditions.append(f"Volume OK: {avg_vol:.2f}")
    
    # 3. Range recovered
    spot_price = tick.get('spot_price', tick.get('ltp', 100) * 100)
    avg_range = _mode_state.avg_range()
    if spot_price > 0 and avg_range <= spot_price * RANGE_RECOVERY_THRESHOLD:
        return False, f"Range not recovered: {avg_range:.2f}"
    conditions.append(f"Range OK: {avg_range:.2f}")
    
    # 4. Theta recovered
    theta_sec = greeks.get('theta_sec', 0)
    if theta_sec >= THETA_RECOVERY_THRESHOLD:
        return False, f"Theta still high: {theta_sec:.4f}"
    conditions.append(f"Theta OK: {theta_sec:.4f}")
    
    # 5. Prefer EXPIRY days for aggressive (optional boost)
    # if day_type != "EXPIRY":
    #     return False, "Not expiry day"
    
    return True, " | ".join(conditions)


def should_lockdown(daily_pnl: float) -> Tuple[bool, str]:
    """Check if we should enter LOCKDOWN mode"""
    if daily_pnl <= LOCKDOWN_LOSS_THRESHOLD:
        return True, f"Daily loss limit: ₹{daily_pnl:.2f}"
    return False, ""


# =============================================================================
# MAIN UPDATE FUNCTION
# =============================================================================

def update_trading_mode(tick: Dict, greeks: Dict, day_type: str, 
                        daily_pnl: float, recent_ticks: List[Dict] = None) -> str:
    """
    Update trading mode based on market conditions.
    Call this ONCE per loop, before state_idle().
    
    Args:
        tick: Current tick data
        greeks: Current Greeks
        day_type: "NORMAL" or "EXPIRY"
        daily_pnl: Current daily PnL in ₹
        recent_ticks: List of recent ticks for calculations
        
    Returns:
        Current mode string
    """
    global _current_mode, active_thresholds, _mode_state
    
    with _mode_lock:
        # Update rolling observations
        if recent_ticks and len(recent_ticks) > 5:
            # Calculate volume ratio
            current_vol = tick.get('volume', 0)
            recent_vols = [t.get('volume', 0) for t in recent_ticks[-60:]]
            avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
            if avg_vol > 0:
                _mode_state.add_volume_ratio(current_vol / avg_vol)
            
            # Calculate price range
            prices = [t.get('ltp', 0) for t in recent_ticks[-60:]]
            if prices:
                _mode_state.add_range(max(prices) - min(prices))
        
        # Check switch cooldown
        if not _mode_state.can_switch():
            return _current_mode
        
        old_mode = _current_mode
        
        # Priority 1: Check for LOCKDOWN
        lockdown, lockdown_reason = should_lockdown(daily_pnl)
        if lockdown and _current_mode != MODE_LOCKDOWN:
            _current_mode = MODE_LOCKDOWN
            _mode_state.record_switch(MODE_LOCKDOWN)
            _log_mode_switch(old_mode, MODE_LOCKDOWN, lockdown_reason)
            return _current_mode
        
        # Already in lockdown - stay there
        if _current_mode == MODE_LOCKDOWN:
            return _current_mode
        
        # Priority 2: Check for SAFE
        if _current_mode == MODE_AGGRESSIVE:
            go_safe, safe_reason = should_go_safe(tick, greeks, day_type, daily_pnl)
            if go_safe:
                _current_mode = MODE_SAFE
                active_thresholds = SAFE_THRESHOLDS.copy()
                _mode_state.record_switch(MODE_SAFE)
                _log_mode_switch(old_mode, MODE_SAFE, safe_reason)
                return _current_mode
        
        # Priority 3: Check for AGGRESSIVE
        if _current_mode == MODE_SAFE:
            go_aggressive, agg_reason = should_go_aggressive(tick, greeks, day_type, daily_pnl)
            if go_aggressive:
                _current_mode = MODE_AGGRESSIVE
                active_thresholds = AGGRESSIVE_THRESHOLDS.copy()
                _mode_state.record_switch(MODE_AGGRESSIVE)
                _log_mode_switch(old_mode, MODE_AGGRESSIVE, agg_reason)
                return _current_mode
        
        return _current_mode


def _log_mode_switch(old_mode: str, new_mode: str, reason: str):
    """Log mode switch using logging module"""
    import logging
    logging.info(f"[MODE] 🔄 {old_mode} → {new_mode} | Reason: {reason}")


# =============================================================================
# PUBLIC API
# =============================================================================

def get_current_mode() -> str:
    """Get current trading mode"""
    return _current_mode


def get_active_thresholds() -> Dict:
    """Get active thresholds based on current mode"""
    return active_thresholds.copy()


def get_threshold(key: str) -> float:
    """Get a specific threshold value"""
    return active_thresholds.get(key, 0)


def record_trade_result(is_win: bool):
    """Record trade result for mode switching logic"""
    with _mode_lock:
        _mode_state.record_trade_result(is_win)


def reset_mode():
    """Reset to aggressive mode (for new day)"""
    global _current_mode, active_thresholds, _mode_state
    with _mode_lock:
        _current_mode = MODE_AGGRESSIVE
        active_thresholds = AGGRESSIVE_THRESHOLDS.copy()
        _mode_state = ModeState()


def is_entries_allowed() -> bool:
    """Check if new entries are allowed (not in lockdown)"""
    return _current_mode != MODE_LOCKDOWN


def get_mode_emoji() -> str:
    """Get emoji for current mode"""
    if _current_mode == MODE_AGGRESSIVE:
        return "🔴"
    elif _current_mode == MODE_SAFE:
        return "🟢"
    else:
        return "🔒"
