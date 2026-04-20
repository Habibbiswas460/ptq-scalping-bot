"""
PTQ Scalping Bot - Configuration Constants
SMART SCALP v3.4 - 4 Lot Configuration
All settings from .env file ONLY (no JSON dependency)
"""

import os
from typing import List, Tuple
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# =========================================================
# ENVIRONMENT HELPERS
# =========================================================

def env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment"""
    val = os.getenv(key, str(default)).lower()
    return val in ('true', '1', 'yes', 'on')

def env_int(key: str, default: int = 0) -> int:
    """Get integer from environment"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def env_float(key: str, default: float = 0.0) -> float:
    """Get float from environment"""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def env_str(key: str, default: str = '') -> str:
    """Get string from environment"""
    return os.getenv(key, default)

def parse_tsl_levels(levels_str: str) -> List[Tuple[int, int]]:
    """Parse TSL levels from comma-separated string
    Format: "8:4,12:7,16:11" -> [(8,4), (12,7), (16,11)]
    """
    if not levels_str:
        return [(8, 4), (12, 7), (16, 11), (20, 15), (25, 20), (30, 25), (40, 35), (50, 45)]
    
    levels = []
    for pair in levels_str.split(','):
        if ':' in pair:
            profit, lock = pair.strip().split(':')
            levels.append((int(profit), int(lock)))
    return levels if levels else [(8, 4), (12, 7), (16, 11), (20, 15)]

# =========================================================
# 🔐 BROKER CREDENTIALS
# =========================================================

ANGEL_CLIENT_ID = env_str('ANGEL_CLIENT_ID')
ANGEL_PASSWORD = env_str('ANGEL_PASSWORD')
ANGEL_API_KEY = env_str('ANGEL_API_KEY')
ANGEL_TOTP_SECRET = env_str('ANGEL_TOTP_SECRET')

# =========================================================
# 💰 TRADING MODE
# =========================================================

BROKER_NAME = 'angel_one'
PAPER_TRADING = env_bool('PAPER_TRADING', True)
TEST_MODE = env_bool('TEST_MODE', False)
USE_LIVE_DATA = env_bool('USE_LIVE_DATA', False)
ENABLE_WEBSOCKET = env_bool('ENABLE_WEBSOCKET', True)

# =========================================================
# 💵 CAPITAL & RISK (UPDATED v3.1 - Institutional Risk Limits)
# =========================================================

TOTAL_CAPITAL = env_int('TOTAL_CAPITAL', 30000)
# RISK IMPROVEMENT: Reduced from 7% to 1.5% (Professional: 0.5-2%)
# 3 consecutive losses = 4.5% drawdown (vs 21% before)
RISK_PER_TRADE = env_float('RISK_PER_TRADE_PCT', 1.5)
MAX_DAILY_LOSS_PCT = env_float('MAX_DAILY_LOSS_PCT', 5.0)  # 5% max daily loss (₹1500 for 30k)
MAX_DAILY_LOSS_AMOUNT = env_int('MAX_DAILY_LOSS', 1500)  # Changed from 25000 to 1500
DAILY_LOSS_ALERT = env_int('DAILY_LOSS_ALERT', 1000)      # Alert at ₹1000 loss
PROFIT_LOCK_THRESHOLD = env_int('PROFIT_LOCK_THRESHOLD', 1000)  # Lock profit at ₹1000

# =========================================================
# 📊 TRADING INSTRUMENT
# =========================================================

SYMBOL = env_str('SYMBOL', 'NIFTY')
EXCHANGE = env_str('EXCHANGE', 'NFO')
OPTION_TYPE = env_str('OPTION_TYPE', 'CE')
LOT_SIZE = env_int('LOT_SIZE', 65)
NUM_LOTS = env_int('NUM_LOTS', 4)

# =========================================================
# 🎯 POSITION SIZING (UPDATED v3.1 - Risk-Based)
# =========================================================

CE_QUANTITY = env_int('CE_QUANTITY', 65)   # Reduced from 260 to 1 lot
PE_QUANTITY = env_int('PE_QUANTITY', 65)   # Reduced from 156 to 1 lot
POSITION_SIZING_ENABLED = env_bool('POSITION_SIZING_ENABLED', True)  # ENABLED

# Risk-based position sizing formula:
# position_size = (capital × risk_pct / SL_amount)
# Example: (30000 × 1.5% / 520) = 0.86 lots → 1 lot (65 qty)
POSITION_SIZING_METHOD = env_str('POSITION_SIZING_METHOD', 'risk_based')
MAX_LOTS = env_int('MAX_LOTS', 2)  # Max 2 lots for 30k capital
MIN_LOTS = env_int('MIN_LOTS', 1)  # Min 1 lot

# =========================================================
# 🛑 STOP LOSS SETTINGS (v3.3 - Improved R:R ratio)
# =========================================================

SL_POINTS_FIXED = env_int('SL_POINTS', 6)  # Reduced from 8 to 6 (better R:R)
SL_POINTS_MIN = SL_POINTS_FIXED
SL_POINTS_MAX = SL_POINTS_FIXED
SL_AMOUNT = env_int('SL_AMOUNT', SL_POINTS_FIXED * LOT_SIZE)  # 6 pts × 65 qty = ₹390
MAX_LOSS_PER_TRADE_CE = SL_POINTS_FIXED * CE_QUANTITY
MAX_LOSS_PER_TRADE_PE = SL_POINTS_FIXED * PE_QUANTITY
STOP_LOSS_AMOUNT = SL_AMOUNT
STOP_LOSS_PCT = 8.0

# =========================================================
# 🎯 PROFIT TARGETS (v3.3 - R:R = 1:2 minimum)
# =========================================================

TP_POINTS_FIXED = env_int('TP_POINTS', 12)  # Reduced from 16 to 12 (SL=6, R:R=1:2)
TP_MULTIPLIER = env_float('TP_MULTIPLIER', 2.0)
TP_MULTIPLIER_LOW = TP_MULTIPLIER
TP_MULTIPLIER_MED = TP_MULTIPLIER
TP_MULTIPLIER_HIGH = TP_MULTIPLIER

PROFIT_TARGET_CE = env_int('PROFIT_TARGET_CE', TP_POINTS_FIXED * CE_QUANTITY)
PROFIT_TARGET_PE = env_int('PROFIT_TARGET_PE', TP_POINTS_FIXED * PE_QUANTITY)
PROFIT_TARGET_1 = PROFIT_TARGET_CE
PROFIT_TARGET_2 = PROFIT_TARGET_CE
PROFIT_TARGET_3 = PROFIT_TARGET_CE

PROFIT_TARGET_1_EXIT_PCT = 100
PROFIT_TARGET_2_EXIT_PCT = 0
PROFIT_TARGET_3_EXIT_PCT = 0

# =========================================================
# 📈 TRAILING STOP LOSS (TSL)
# =========================================================

TRAILING_ENABLED = env_bool('TSL_ENABLED', True)
TSL_STEP_LEVELS = parse_tsl_levels(env_str('TSL_LEVELS', '8:4,12:7,16:11,20:15,25:20,30:25,40:35,50:45'))

# Breakeven settings
TRAILING_ACTIVATION_1 = env_int('TSL_BREAKEVEN_ACTIVATION', 5)
TRAILING_LOCK_PCT_1 = 12
TRAILING_ACTIVATION_2 = 8
TRAILING_LOCK_PCT_2 = 50
TRAILING_ACTIVATION_3 = 12
TRAILING_LOCK_PCT_3 = 58

TRAILING_ATR_NORMAL = 1.2
TRAILING_ATR_EXPIRY = 1.0

# =========================================================
# 📊 STRATEGY SCORING
# =========================================================

STRATEGY_NAME = 'smart_scalp_institutional'
STRATEGY_VERSION = '3.4'
MIN_SCORE_TO_TRADE = env_int('MIN_SCORE', 5)
MIN_CONFIDENCE = env_int('MIN_CONFIDENCE', 70)  # Balanced: 70% (was 80, too strict)
MIN_CONFIDENCE_AFTER_3SL = env_int('MIN_CONFIDENCE_AFTER_3SL', 85)  # After 3 consecutive SL (was 92)
CONFIDENCE_MULTIPLIER = env_int('CONFIDENCE_MULTIPLIER', 12)

# Entry Price Filter (ATM nearby range)
MIN_ENTRY_PREMIUM = env_float('MIN_ENTRY_PREMIUM', 90.0)   # Min ₹90
MAX_ENTRY_PREMIUM = env_float('MAX_ENTRY_PREMIUM', 350.0)  # Max ₹350 (was 150, blocked all ATM options)

# =========================================================
# ⏱️ TRADING LIMITS
# =========================================================

MAX_TRADES_PER_DAY = env_int('MAX_TRADES_PER_DAY', 15)
MAX_TRADES_PER_HOUR = env_int('MAX_TRADES_PER_HOUR', 10)
IDEAL_TRADES_PER_DAY = env_int('IDEAL_TRADES_PER_DAY', 8)

# =========================================================
# ⏰ TIME LIMITS
# =========================================================

# PULLBACK & PROTECT: Max hold time 15 minutes (900 seconds)
MAX_HOLD_TIME_WINNING = env_int('MAX_HOLD_TIME_SEC', 900)
MAX_HOLD_TIME_LOSING = MAX_HOLD_TIME_WINNING
MAX_HOLD_TIME_EXPIRY = env_int('MAX_HOLD_TIME_EXPIRY_SEC', 600)
CONSECUTIVE_LOSS_LIMIT = env_int('CONSECUTIVE_LOSS_LIMIT', 2)
PAUSE_AFTER_LOSS_SEC = env_int('COOLDOWN_AFTER_CONSEC_LOSS', 1200)

# =========================================================
# ⏸️ COOLDOWN
# =========================================================

COOLDOWN_NORMAL_SEC = env_int('COOLDOWN_NORMAL', 180)
COOLDOWN_AFTER_PROFIT_SEC = env_int('COOLDOWN_AFTER_PROFIT', 120)
COOLDOWN_AFTER_SL_SEC = env_int('COOLDOWN_AFTER_SL', 300)
COOLDOWN_AFTER_CONSECUTIVE_LOSS = env_int('COOLDOWN_AFTER_CONSEC_LOSS', 1200)
COOLDOWN_EXPIRY_NORMAL = 120
COOLDOWN_EXPIRY_AFTER_SL = 180

# =========================================================
# 🚨 KILL SWITCH (UPDATED v3.1 - Tighter Risk Control)
# =========================================================

KILL_SWITCH_ENABLED = env_bool('KILL_SWITCH_ENABLED', True)
# Reduced from 900 to 450 (1.5% of 30k capital)
KILL_SWITCH_LOSS = env_int('KILL_SWITCH_LOSS', 450)
KILL_SWITCH_DAILY_LOSS = KILL_SWITCH_LOSS
KILL_SWITCH_CONSEC_LOSS = env_int('KILL_SWITCH_CONSEC_LOSS', 3)
KILL_SWITCH_SPREAD = env_float('KILL_SWITCH_SPREAD_PCT', 0.6)
KILL_SWITCH_LATENCY = env_int('KILL_SWITCH_LATENCY_MS', 100)

# =========================================================
# ⏰ MARKET HOURS
# =========================================================

MARKET_OPEN_TIME = env_str('MARKET_OPEN', '09:15')
MARKET_CLOSE_TIME = env_str('MARKET_CLOSE', '15:30')
TRADING_START_TIME = env_str('TRADING_START', '09:20')
TRADING_END_TIME = env_str('TRADING_END', '15:10')
AVOID_FIRST_15MIN = env_bool('AVOID_FIRST_15MIN', True)

# =========================================================
# 📐 GREEKS LIMITS
# =========================================================

DELTA_MIN = env_float('DELTA_MIN', 0.25)
DELTA_MAX = env_float('DELTA_MAX', 0.75)
DELTA_KILL_MIN = env_float('DELTA_KILL_MIN', 0.15)
GAMMA_NORMAL_MAX = env_float('GAMMA_NORMAL_MAX', 0.08)
GAMMA_EXPIRY_MAX = env_float('GAMMA_EXPIRY_MAX', 0.12)
THETA_SEC_LIMIT = env_float('THETA_SEC_LIMIT', 0.2)
THETA_SEC_KILL_LIMIT = env_float('THETA_SEC_KILL', 0.3)

# =========================================================
# 📊 INDICATORS
# =========================================================

EMA_FAST = env_int('EMA_FAST', 5)
EMA_SIGNAL = env_int('EMA_SIGNAL', 9)
EMA_MEDIUM = env_int('EMA_MEDIUM', 21)
EMA_SLOW = env_int('EMA_SLOW', 50)
RSI_PERIOD = env_int('RSI_PERIOD', 14)
MACD_FAST = env_int('MACD_FAST', 12)
MACD_SLOW = env_int('MACD_SLOW', 26)
MACD_SIGNAL = env_int('MACD_SIGNAL', 9)
BB_PERIOD = env_int('BB_PERIOD', 20)
BB_STD = env_float('BB_STD', 2.0)
ATR_PERIOD = env_int('ATR_PERIOD', 14)
KC_PERIOD = 20
KC_ATR_MULT = 1.5

# =========================================================
# 🧹 DATA HYGIENE
# =========================================================

LATENCY_LIMIT_MS = env_int('LATENCY_LIMIT_MS', 100)
SPREAD_LIMIT_PCT = env_float('SPREAD_LIMIT_PCT', 2.5)  # Options have 0.5-2.5% spread, especially near expiry/EOD
TICK_TIMEOUT_SEC = env_int('TICK_TIMEOUT_SEC', 2)
MIN_VOLUME = env_int('MIN_VOLUME', 100)
MIN_OPTION_PRICE = env_int('MIN_OPTION_PRICE', 5)
MAX_OPTION_PRICE = env_int('MAX_OPTION_PRICE', 500)

# PTQ Validation
VOLUME_EXPANSION_MIN = 0.8
MAX_SPREAD_PCT_PTQ = 2.5  # Match the data hygiene limit
CHOP_THRESHOLD = 0.00015

# =========================================================
# � ORDER EXECUTION (v3.1 - Smart LIMIT Orders)
# =========================================================

# Use LIMIT orders instead of MARKET for better fill prices
USE_LIMIT_ORDERS = env_bool('USE_LIMIT_ORDERS', True)

# Limit order price offset from LTP (in points)
# BUY: limit = ask - offset, SELL: limit = bid + offset
LIMIT_ORDER_OFFSET = env_float('LIMIT_ORDER_OFFSET', 0.25)

# Maximum slippage allowed (will fall back to MARKET if exceeded)
MAX_SLIPPAGE_PCT = env_float('MAX_SLIPPAGE_PCT', 0.5)

# Order retry settings
ORDER_RETRY_ENABLED = env_bool('ORDER_RETRY_ENABLED', True)
ORDER_MAX_RETRIES = env_int('ORDER_MAX_RETRIES', 3)
ORDER_RETRY_DELAY_MS = env_int('ORDER_RETRY_DELAY_MS', 500)  # Wait between retries
ORDER_PRICE_CHASE_STEP = env_float('ORDER_PRICE_CHASE_STEP', 0.5)  # Increase limit price by this each retry

# =========================================================
# �📱 TELEGRAM
# =========================================================

TELEGRAM_ENABLED = env_bool('TELEGRAM_ENABLED', False)
TELEGRAM_BOT_TOKEN = env_str('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = env_str('TELEGRAM_CHAT_ID', '')
TELEGRAM_NOTIFY_ENTRIES = env_bool('TELEGRAM_NOTIFY_ENTRIES', True)
TELEGRAM_NOTIFY_EXITS = env_bool('TELEGRAM_NOTIFY_EXITS', True)
TELEGRAM_NOTIFY_KILL_SWITCH = env_bool('TELEGRAM_NOTIFY_KILL_SWITCH', True)
TELEGRAM_DAILY_SUMMARY = env_bool('TELEGRAM_DAILY_SUMMARY', True)

# =========================================================
#  DATABASE
# =========================================================

DATABASE_ENABLED = env_bool('DATABASE_ENABLED', True)
DATABASE_PATH = env_str('DATABASE_PATH', 'data/trades.db')
DATABASE_LOG_SIGNALS = env_bool('DATABASE_LOG_SIGNALS', True)
DATABASE_LOG_TICKS = env_bool('DATABASE_LOG_TICKS', False)

# =========================================================
# 📝 LOGGING
# =========================================================

LOG_ENABLED = env_bool('LOG_ENABLED', True)
LOG_CONSOLE = env_bool('LOG_CONSOLE', True)
LOG_DIRECTORY = env_str('LOG_DIRECTORY', 'logs')
LOG_VERBOSE = env_bool('LOG_VERBOSE', False)

# =========================================================
# SESSION FILTER (Advanced)
# =========================================================

SESSION_FILTER_ENABLED = env_bool('SESSION_FILTER_ENABLED', True)

# Define sessions as dictionaries with time ranges
# FULL DAY coverage - no gaps between sessions
ALLOWED_SESSIONS = [
    {'name': 'morning_1', 'start_hour': 9, 'start_minute': 20, 'end_hour': 10, 'end_minute': 30, 'reason': 'Morning session 1'},
    {'name': 'morning_2', 'start_hour': 10, 'start_minute': 30, 'end_hour': 11, 'end_minute': 30, 'reason': 'Morning session 2'},
    {'name': 'late_morning', 'start_hour': 11, 'start_minute': 30, 'end_hour': 12, 'end_minute': 30, 'reason': 'Late morning session'},
    {'name': 'midday', 'start_hour': 12, 'start_minute': 30, 'end_hour': 14, 'end_minute': 0, 'reason': 'Midday session'},
    {'name': 'afternoon', 'start_hour': 14, 'start_minute': 0, 'end_hour': 15, 'end_minute': 15, 'reason': 'Afternoon session'},
]
EXPIRY_ONLY_SESSIONS = [
    {'name': 'expiry_morning_1', 'start_hour': 9, 'start_minute': 20, 'end_hour': 10, 'end_minute': 30, 'reason': 'Expiry morning 1'},
    {'name': 'expiry_morning_2', 'start_hour': 10, 'start_minute': 30, 'end_hour': 11, 'end_minute': 30, 'reason': 'Expiry morning 2'},
]
BLACKOUT_SESSIONS = [
    # {'name': 'lunch', 'start_hour': 11, 'start_minute': 30, 'end_hour': 12, 'end_minute': 30, 'reason': 'Lunch break - choppy market'},
]

# =========================================================
# 📦 CONFIG DICTIONARY (Backwards Compatibility)
# Allows old code using CONFIG['section']['key'] to work
# =========================================================

CONFIG = {
    'broker': {
        'name': BROKER_NAME,
        'paper_trading': PAPER_TRADING,
        'use_live_data': USE_LIVE_DATA,
    },
    'capital': {
        'total_capital': TOTAL_CAPITAL,
        'risk_per_trade_pct': RISK_PER_TRADE,
        'risk_per_trade_amount': TOTAL_CAPITAL * RISK_PER_TRADE / 100,  # e.g. 30000 * 1.5% = 450
        'max_daily_loss_amount': MAX_DAILY_LOSS_AMOUNT,
        'daily_loss_alert_threshold': DAILY_LOSS_ALERT,
        'margin_per_lot': 15000,
        'max_drawdown_amount': int(TOTAL_CAPITAL * 0.10),  # 10% of capital
        'max_drawdown_pct': 10.0,
        'max_weekly_loss_amount': int(TOTAL_CAPITAL * 0.08),  # 8% of capital
        'profit_lock_threshold': PROFIT_LOCK_THRESHOLD,
        'profit_lock_reduce_pct': 50,  # Reduce size by 50% after profit lock
    },
    'trading': {
        'symbol': SYMBOL,
        'exchange': EXCHANGE,
        'option_type': OPTION_TYPE,
        'lot_size': LOT_SIZE,
        'quantity': NUM_LOTS,
    },
    'risk_management': {
        'stop_loss_pct': STOP_LOSS_PCT,
        'stop_loss_amount': SL_POINTS_FIXED * LOT_SIZE,  # SL in rupees per lot
        'max_trades_per_hour': MAX_TRADES_PER_HOUR,
        'max_trades_per_day': MAX_TRADES_PER_DAY,
        'ideal_trades_per_day': IDEAL_TRADES_PER_DAY,
        'max_hold_time_normal_sec': MAX_HOLD_TIME_WINNING,
        'max_hold_time_expiry_sec': MAX_HOLD_TIME_EXPIRY,
        'consecutive_loss_limit': CONSECUTIVE_LOSS_LIMIT,
        'consecutive_win_limit': 8,
        'pause_after_consecutive_loss_sec': PAUSE_AFTER_LOSS_SEC,
        'position_sizing_enabled': POSITION_SIZING_ENABLED,
        'position_sizing_method': POSITION_SIZING_METHOD,
        'min_lots': MIN_LOTS,
        'max_lots': MAX_LOTS,
        'min_position_size': 1,
        'capital_utilization_pct': 80,
        'atr_risk_multiplier': 2.0,
        'vix_low_threshold': 12.0,
        'vix_high_threshold': 20.0,
        'position_size_low_vix': 1.25,
        'position_size_high_vix': 0.5,
        'position_size_normal_vix': 1.0,
        # Trailing SL (risk_manager version)
        'trailing_sl_enabled': TRAILING_ENABLED,
        'trailing_activation_amount': 50,
        'trailing_atr_multiplier': 1.5,
        'trailing_lock_pct': 40,
    },
    'entry_filters': {
        'avoid_first_15min': AVOID_FIRST_15MIN,
        'min_volume_ratio': 1.2,
        'volume_confirmation_required': False,
        'require_consecutive_signals': 1,
        'time_based_sizing_enabled': False,
        'opening_15min_size_pct': 50,
        'closing_30min_size_pct': 75,
    },
    'data_hygiene': {
        'latency_limit_ms': LATENCY_LIMIT_MS,
        'spread_limit_pct': SPREAD_LIMIT_PCT,
        'tick_timeout_sec': TICK_TIMEOUT_SEC,
        'min_volume': MIN_VOLUME,
        'min_option_price': MIN_OPTION_PRICE,
        'max_option_price': MAX_OPTION_PRICE,
        'min_spot_price': 15000,
        'max_spot_price': 35000,
    },
    'cooldown': {
        'normal_sec': COOLDOWN_NORMAL_SEC,
        'after_sl_sec': COOLDOWN_AFTER_SL_SEC,
        'after_consecutive_loss_sec': COOLDOWN_AFTER_CONSECUTIVE_LOSS,
        'expiry_normal_sec': COOLDOWN_EXPIRY_NORMAL,
        'expiry_after_sl_sec': COOLDOWN_EXPIRY_AFTER_SL,
    },
    'greeks_limits': {
        'delta_min': DELTA_MIN,
        'delta_max': DELTA_MAX,
        'delta_kill_min': DELTA_KILL_MIN,
        'gamma_normal_max': GAMMA_NORMAL_MAX,
        'gamma_expiry_max': GAMMA_EXPIRY_MAX,
        'theta_sec_limit': THETA_SEC_LIMIT,
        'theta_sec_kill_limit': THETA_SEC_KILL_LIMIT,
    },
    'kill_switch': {
        'enabled': KILL_SWITCH_ENABLED,
        'daily_loss_amount': KILL_SWITCH_LOSS,
        'spread_limit_pct': KILL_SWITCH_SPREAD,
        'latency_limit_ms': KILL_SWITCH_LATENCY,
    },
    'session_filter': {
        'enabled': SESSION_FILTER_ENABLED,
        'allowed_sessions': ALLOWED_SESSIONS,
        'expiry_only_sessions': EXPIRY_ONLY_SESSIONS,
        'blackout_sessions': BLACKOUT_SESSIONS,
    },
    'logging': {
        'enabled': LOG_ENABLED,
        'console_output': LOG_CONSOLE,
        'log_directory': LOG_DIRECTORY,
        'verbose': LOG_VERBOSE,
    },
    'telegram': {
        'enabled': TELEGRAM_ENABLED,
        'bot_token': TELEGRAM_BOT_TOKEN,
        'chat_id': TELEGRAM_CHAT_ID,
    },
    'database': {
        'enabled': DATABASE_ENABLED,
        'path': DATABASE_PATH,
        'log_signals': DATABASE_LOG_SIGNALS,
        'log_ticks': DATABASE_LOG_TICKS,
    },
    # v3.3: Advanced risk features (used by risk_manager.py)
    'volatility_filter': {
        'vix_enabled': True,
        'vix_normal_max': 15.0,
        'vix_caution_max': 20.0,
        'vix_high_max': 30.0,
        'vix_extreme_action': 'reduce',  # 'stop' or 'reduce'
        'size_reduce_pct_caution': 25,
        'size_reduce_pct_high': 50,
    },
    'gap_protection': {
        'enabled': True,
        'gap_up_threshold_pct': 1.0,
        'gap_down_threshold_pct': 1.0,
        'wait_after_gap_min': 15,
    },
    'recovery_mode': {
        'enabled': True,
        'trigger_loss_pct': 8.0,
        'recovery_threshold_pct': 3.0,
        'min_recovery_days': 2,
        'size_reduction_pct': 50,
    },
    'equity_curve_trading': {
        'enabled': False,  # Disabled until enough equity history accumulated
        'sma_period': 10,
        'pause_if_below_pct': 5.0,
        'size_reduce_pct': 30,
    },
}

# =========================================================
# PRINT LOADED CONFIG (for debugging)
# =========================================================

def print_config():
    """Print loaded configuration for verification"""
    print("\n" + "=" * 60)
    print("📋 LOADED CONFIGURATION FROM .env")
    print("=" * 60)
    print(f"💰 Capital: ₹{TOTAL_CAPITAL:,}")
    print(f"📊 Trading: {SYMBOL} {OPTION_TYPE} | Lot Size: {LOT_SIZE}")
    print(f"🎯 Quantities: CE {CE_QUANTITY} | PE {PE_QUANTITY}")
    print(f"🛑 SL: {SL_POINTS_FIXED} pts | TP: {TP_POINTS_FIXED} pts")
    print(f"📈 TSL Levels: {len(TSL_STEP_LEVELS)} steps")
    print(f"⏰ Market: {MARKET_OPEN_TIME} - {MARKET_CLOSE_TIME}")
    print(f"⏱️ Trading: {TRADING_START_TIME} - {TRADING_END_TIME}")
    print(f"🚨 Kill Switch: ₹{KILL_SWITCH_LOSS}")
    print(f"📊 Min Score: {MIN_SCORE_TO_TRADE} | Min Confidence: {MIN_CONFIDENCE}%")
    print(f"📱 Telegram: {'✅' if TELEGRAM_ENABLED else '❌'}")
    print(f" Database: {'✅' if DATABASE_ENABLED else '❌'}")
    print(f"🔄 Paper Trading: {'✅' if PAPER_TRADING else '❌ LIVE'}")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    print_config()
