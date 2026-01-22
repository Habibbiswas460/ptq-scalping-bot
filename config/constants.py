"""
PTQ Scalping Bot - Configuration Constants
All trading parameters in one place
"""

import json
from typing import Dict, Any

# =========================================================
# LOAD CONFIGURATION
# =========================================================

def load_config() -> Dict[str, Any]:
    """Load bot configuration from JSON file"""
    with open('config/bot_config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()

# =========================================================
# MODE FLAGS
# =========================================================

BROKER_NAME = CONFIG['broker']['name']
PAPER_TRADING = True   # Paper trading enabled (no real orders)
TEST_MODE = True       # Bypass market hours for testing
USE_LIVE_DATA = True   # Enable real market data (Yahoo Finance)

# =========================================================
# CAPITAL & RISK (₹30K CONFIG)
# =========================================================

TOTAL_CAPITAL = CONFIG['capital']['total_capital']
RISK_PER_TRADE = 300              # 1% of capital
MAX_DAILY_LOSS_AMOUNT = 1200      # 4% max daily loss
KILL_SWITCH_LOSS = 1800           # 6% kill switch

# =========================================================
# TRADING LIMITS
# =========================================================

MAX_TRADES_PER_HOUR = 8           # Max trades per hour
MAX_TRADES_PER_DAY = 25           # Max trades per day
IDEAL_TRADES_PER_DAY = 15         # Target trades

# =========================================================
# STOP LOSS SETTINGS
# =========================================================

STOP_LOSS_AMOUNT = 250            # Wider SL for more room
STOP_LOSS_PCT = CONFIG['risk_management']['stop_loss_pct']

# =========================================================
# PROFIT TARGETS (MULTI-LEVEL)
# =========================================================

PROFIT_TARGET_1 = 100             # First target - 30% exit
PROFIT_TARGET_2 = 200             # Second target - 40% exit
PROFIT_TARGET_3 = 350             # Third target - 30% exit

PROFIT_TARGET_1_EXIT_PCT = 30     # Exit 30% at TP1
PROFIT_TARGET_2_EXIT_PCT = 40     # Exit 40% at TP2
PROFIT_TARGET_3_EXIT_PCT = 30     # Exit remaining 30% at TP3

# =========================================================
# TRAILING STOP (DYNAMIC MULTI-TIER)
# =========================================================

TRAILING_ACTIVATION_1 = 75        # First trailing at ₹75
TRAILING_ACTIVATION_2 = 150       # Second trailing at ₹150
TRAILING_ACTIVATION_3 = 250       # Third trailing at ₹250

TRAILING_LOCK_PCT_1 = 30          # Lock 30% at first level
TRAILING_LOCK_PCT_2 = 50          # Lock 50% at second level
TRAILING_LOCK_PCT_3 = 60          # Lock 60% at third level

TRAILING_ATR_NORMAL = CONFIG['risk_management'].get('trailing_atr_multiplier_normal', 1.5)
TRAILING_ATR_EXPIRY = CONFIG['risk_management'].get('trailing_atr_multiplier_expiry', 1.0)

# =========================================================
# TIME LIMITS
# =========================================================

MAX_HOLD_TIME_WINNING = 2700      # 45 min for winning trades
MAX_HOLD_TIME_LOSING = 1800       # 30 min for losing trades
MAX_HOLD_TIME_EXPIRY = CONFIG['risk_management']['max_hold_time_expiry_sec']
CONSECUTIVE_LOSS_LIMIT = CONFIG['risk_management']['consecutive_loss_limit']
PAUSE_AFTER_LOSS_SEC = CONFIG['risk_management']['pause_after_consecutive_loss_sec']

# =========================================================
# PTQ VALIDATION
# =========================================================

VOLUME_EXPANSION_MIN = 1.05       # Minimum volume ratio
MAX_SPREAD_PCT_PTQ = 1.5          # Max spread for PTQ validation
CHOP_THRESHOLD = 0.00015          # Minimum range to avoid chop

# =========================================================
# DATA HYGIENE
# =========================================================

LATENCY_LIMIT_MS = CONFIG['data_hygiene']['latency_limit_ms']
SPREAD_LIMIT_PCT = CONFIG['data_hygiene']['spread_limit_pct']
TICK_TIMEOUT_SEC = CONFIG['data_hygiene']['tick_timeout_sec']

# =========================================================
# COOLDOWN
# =========================================================

COOLDOWN_NORMAL_SEC = CONFIG['cooldown']['normal_sec']
COOLDOWN_AFTER_SL_SEC = CONFIG['cooldown']['after_sl_sec']
COOLDOWN_AFTER_CONSECUTIVE_LOSS = CONFIG['cooldown']['after_consecutive_loss_sec']
COOLDOWN_EXPIRY_NORMAL = CONFIG['cooldown']['expiry_normal_sec']
COOLDOWN_EXPIRY_AFTER_SL = CONFIG['cooldown']['expiry_after_sl_sec']

# =========================================================
# GREEKS LIMITS
# =========================================================

DELTA_MIN = CONFIG['greeks_limits']['delta_min']
DELTA_MAX = CONFIG['greeks_limits']['delta_max']
DELTA_KILL_MIN = CONFIG['greeks_limits']['delta_kill_min']
GAMMA_NORMAL_MAX = CONFIG['greeks_limits']['gamma_normal_max']
GAMMA_EXPIRY_MAX = CONFIG['greeks_limits']['gamma_expiry_max']
THETA_SEC_LIMIT = CONFIG['greeks_limits']['theta_sec_limit']
THETA_SEC_KILL_LIMIT = CONFIG['greeks_limits']['theta_sec_kill_limit']

# =========================================================
# SESSION FILTER
# =========================================================

SESSION_FILTER_ENABLED = CONFIG['session_filter']['enabled']
ALLOWED_SESSIONS = CONFIG['session_filter']['allowed_sessions']
EXPIRY_ONLY_SESSIONS = CONFIG['session_filter']['expiry_only_sessions']
BLACKOUT_SESSIONS = CONFIG['session_filter']['blackout_sessions']

# =========================================================
# KILL SWITCH
# =========================================================

KILL_SWITCH_DAILY_LOSS = CONFIG['kill_switch']['daily_loss_amount']
KILL_SWITCH_SPREAD = CONFIG['kill_switch']['spread_limit_pct']
KILL_SWITCH_LATENCY = CONFIG['kill_switch']['latency_limit_ms']
