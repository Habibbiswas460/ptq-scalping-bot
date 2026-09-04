"""
PTQ Scalping Bot - Configuration Constants
SMART SCALP v3.4 - 4 Lot Configuration
All settings from .env file ONLY (no JSON dependency)
"""

from config.configuration import env_bool, env_float, env_int, env_str, parse_tsl_levels

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
RISK_PER_TRADE = env_float('RISK_PER_TRADE_PCT', 3)
MAX_DAILY_LOSS_PCT = env_float('MAX_DAILY_LOSS_PCT', 10.0)  # 10% max daily loss (₹300 for 30k)
MAX_DAILY_LOSS_AMOUNT = env_int('MAX_DAILY_LOSS', 3000)  # Owner's real ceiling — matches KILL_SWITCH_LOSS's default
DAILY_LOSS_ALERT = env_int('DAILY_LOSS_ALERT', 1500)      # Alert at ₹1500 loss
PROFIT_LOCK_THRESHOLD = env_int('PROFIT_LOCK_THRESHOLD', 1000)  # Lock profit at ₹1000

# =========================================================
# 📊 TRADING INSTRUMENT
# =========================================================

SYMBOL = env_str('SYMBOL', 'NIFTY')
EXCHANGE = env_str('EXCHANGE', 'NFO')
OPTION_TYPE = env_str('OPTION_TYPE', 'CE')
LOT_SIZE = env_int('LOT_SIZE', 65)
NUM_LOTS = env_int('NUM_LOTS', 4)

# Canonical India VIX contract (SmartAPI/OpenAPIScripMaster)
INDIA_VIX_SYMBOL = 'INDIAVIX'
INDIA_VIX_EXCHANGE = 'NSE'
INDIA_VIX_TOKEN = '99926017'
INDIA_VIX_INSTRUMENTTYPE = 'AMXIDX'

# =========================================================
# 🎯 POSITION SIZING (UPDATED v3.1 - Risk-Based)
# =========================================================

CE_QUANTITY = env_int('CE_QUANTITY', 65)   # Reduced from 260 to 1 lot
PE_QUANTITY = env_int('PE_QUANTITY', 65)   # Reduced from 156 to 1 lot

# Risk-based position sizing formula:
# position_size = (capital × risk_pct / SL_amount)
# Example: (capital × 3% / 520) = 0.86 lots → 1 lot (65 qty)

# =========================================================
# 🛑 STOP LOSS SETTINGS (v3.3 - Improved R:R ratio)
# =========================================================

SL_POINTS_FIXED = env_int('SL_POINTS', 7)  # Reduced from 8 to 7 (better R:R)
SL_POINTS_MIN = SL_POINTS_FIXED
SL_POINTS_MAX = SL_POINTS_FIXED
SL_AMOUNT = env_int('SL_AMOUNT', SL_POINTS_FIXED * LOT_SIZE)  # 7 pts × 65 qty = ₹455
MAX_LOSS_PER_TRADE_CE = SL_POINTS_FIXED * CE_QUANTITY
MAX_LOSS_PER_TRADE_PE = SL_POINTS_FIXED * PE_QUANTITY
STOP_LOSS_AMOUNT = SL_AMOUNT
STOP_LOSS_PCT = 8.0

# =========================================================
# 🎯 PROFIT TARGETS (v3.3 - R:R = 1:2 minimum)
# =========================================================

TP_POINTS_FIXED = env_int('TP_POINTS', 14)  # Reduced from 16 to 14 (SL=7, R:R=1:2)
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

# Exit engine optimization knobs
EXIT_HARD_SL_POINTS = env_float('EXIT_HARD_SL_POINTS', float(SL_POINTS_FIXED))
EXIT_BREAKEVEN_TRIGGER_POINTS = env_float('EXIT_BREAKEVEN_TRIGGER_POINTS', 4.0)
EXIT_BREAKEVEN_BUFFER_POINTS = env_float('EXIT_BREAKEVEN_BUFFER_POINTS', 2.0)
EXIT_TRAILING_DISTANCE_POINTS = env_float('EXIT_TRAILING_DISTANCE_POINTS', 2.5)
EXIT_EARLY_LOSS_CUT_POINTS = env_float('EXIT_EARLY_LOSS_CUT_POINTS', 3.5)
EXIT_EARLY_LOSS_CUT_TIME_SEC = env_int('EXIT_EARLY_LOSS_CUT_TIME_SEC', 45)
EXIT_EARLY_CUT_ATR_LOW_POINTS = env_float('EXIT_EARLY_CUT_ATR_LOW_POINTS', 2.5)
EXIT_EARLY_CUT_ATR_HIGH_POINTS = env_float('EXIT_EARLY_CUT_ATR_HIGH_POINTS', 4.5)
EXIT_SOFT_LOSS_TIME_SEC = env_int('EXIT_SOFT_LOSS_TIME_SEC', 75)
EXIT_SOFT_LOSS_POINTS = env_float('EXIT_SOFT_LOSS_POINTS', 1.8)
# Minimum profit (in option points) before an RSI-reversal exit is allowed to
# lock in gains. Without this floor the exit fires on any price_diff > 0,
# locking wins of a few rupees while early-loss-cut losses average ~2.7pts.
RSI_REVERSAL_MIN_PROFIT_POINTS = env_float('RSI_REVERSAL_MIN_PROFIT_POINTS', 1.5)

# Smart RSI exit thresholds — force-close on RSI extremes / reversals.
# Previously hardcoded module constants in exit_engine.py; now owner-tunable.
RSI_OVERBOUGHT = env_float('RSI_OVERBOUGHT', 80)      # Exit CE when RSI > this
RSI_OVERSOLD = env_float('RSI_OVERSOLD', 20)          # Exit PE when RSI < this
RSI_EXIT_MIN_PROFIT_POINTS = env_float('RSI_EXIT_MIN_PROFIT_POINTS', 2.0)  # Min profit before RSI overbought/oversold exit is even evaluated

# ═══════════════════════════════════════════════════════════════════════════
# EXIT EXPERIMENT (experiment/exit-strategy-20260904)
# Every value below defaults to the CURRENT production behaviour, so with no
# .env entries the exit ladder is byte-for-byte what the frozen baseline does.
# Enable one variable at a time and measure — see claude_code/experiments/.
# ═══════════════════════════════════════════════════════════════════════════
# 'rsi'   = production: profit is taken by smart-RSI / RSI-reversal (floor-gated)
# 'floor' = experimental: take profit on the first tick past the floor, no RSI condition
EXIT_PROFIT_MODE = env_str('EXIT_PROFIT_MODE', 'rsi').strip().lower()
EXIT_PROFIT_FLOOR_POINTS = env_float('EXIT_PROFIT_FLOOR_POINTS', RSI_REVERSAL_MIN_PROFIT_POINTS)

# 'static'       = production: fixed early-cut threshold (see the ATR branch below)
# 'atr_adaptive' = experimental: threshold = mult x the option's own realised range
# 'mfe_aware'    = experimental: tighter for a trade that never traded above entry
EXIT_LOSS_MODE = env_str('EXIT_LOSS_MODE', 'static').strip().lower()
EXIT_ATR_MULT = env_float('EXIT_ATR_MULT', 0.75)
EXIT_ATR_FLOOR_POINTS = env_float('EXIT_ATR_FLOOR_POINTS', 1.5)
EXIT_ATR_CAP_POINTS = env_float('EXIT_ATR_CAP_POINTS', 6.0)
EXIT_MFE_ARM_POINTS = env_float('EXIT_MFE_ARM_POINTS', 1.0)
EXIT_MFE_TIGHT_POINTS = env_float('EXIT_MFE_TIGHT_POINTS', 1.5)
EXIT_MFE_ROOM_POINTS = env_float('EXIT_MFE_ROOM_POINTS', 4.0)

# The `atr` key has never been populated on any tick, so the ATR branch of the
# early cut has always taken its low-volatility path. Enabling this computes a
# real realised range from the tick buffer and puts it on the tick. It CHANGES
# LIVE BEHAVIOUR, so it is opt-in and measured separately from the above.
EXIT_REALISED_ATR_ENABLED = env_bool('EXIT_REALISED_ATR_ENABLED', False)
EXIT_REALISED_ATR_WINDOW_SEC = env_int('EXIT_REALISED_ATR_WINDOW_SEC', 60)

# ═══════════════════════════════════════════════════════════════════════════
# TICK INPUT REPAIR (experiment/exit-strategy-20260904)
# `delta` and `oi` are read by the scoring engines but were never written onto
# the tick dict, so weighted_score_engine's delta(10) + greeks(5) and oi(10)
# components — 25 of the 105 total weight — could never be earned, and the
# persisted ticks.oi column was NULL on every row. Same failure mode as the
# `atr` key. Each flag is separate so each repair can be measured on its own.
# Both default OFF: enabling either CHANGES LIVE SCORING.
# ═══════════════════════════════════════════════════════════════════════════
TICK_DELTA_ENABLED = env_bool('TICK_DELTA_ENABLED', False)
TICK_OI_ENABLED = env_bool('TICK_OI_ENABLED', False)
RSI_REVERSAL_CE_EXIT = env_float('RSI_REVERSAL_CE_EXIT', 60)      # CE: exit once RSI drops back below this
RSI_REVERSAL_PE_EXIT = env_float('RSI_REVERSAL_PE_EXIT', 40)      # PE: exit once RSI rises back above this
RSI_REVERSAL_CE_EXTREME = env_float('RSI_REVERSAL_CE_EXTREME', 75)  # CE: must have seen RSI above this before a reversal counts
RSI_REVERSAL_PE_EXTREME = env_float('RSI_REVERSAL_PE_EXTREME', 25)  # PE: must have seen RSI below this before a reversal counts

# ATR-adaptive SL/TP widening (strategies/smart_scalp_v3.py get_entry_params)
ATR_SL_HIGH_THRESHOLD = env_float('ATR_SL_HIGH_THRESHOLD', 8)   # ATR above this widens SL/TP
ATR_SL_LOW_THRESHOLD = env_float('ATR_SL_LOW_THRESHOLD', 4)     # ATR below this tightens SL/TP
ATR_HIGH_SL_ADJUSTMENT = env_float('ATR_HIGH_SL_ADJUSTMENT', 1)  # Points added to SL when ATR is high
ATR_HIGH_TP_ADJUSTMENT = env_float('ATR_HIGH_TP_ADJUSTMENT', 2)  # Points added to TP when ATR is high
ATR_LOW_SL_ADJUSTMENT = env_float('ATR_LOW_SL_ADJUSTMENT', 1)    # Points removed from SL when ATR is low
ATR_LOW_TP_ADJUSTMENT = env_float('ATR_LOW_TP_ADJUSTMENT', 2)    # Points removed from TP when ATR is low
ATR_SL_MIN_POINTS = env_float('ATR_SL_MIN_POINTS', 4)            # SL floor when ATR is low
ATR_TP_MIN_POINTS = env_float('ATR_TP_MIN_POINTS', 10)           # TP floor when ATR is low

# Strike selection premium band (which strike gets chosen — separate from
# MIN_ENTRY_PREMIUM/MAX_ENTRY_PREMIUM, which gate whether an already-chosen
# strike is allowed to enter). Previously hardcoded in core/trading/broker.py.
# Matched to MIN_ENTRY_PREMIUM/MAX_ENTRY_PREMIUM (findings.md §2.6) — this band
# used to be narrower (90-150) than the entry gate (70-350), so strike
# selection could rotate away from an ATM strike the entry gate would have
# allowed, for the same reason MAX_ENTRY_PREMIUM itself was widened from 150.
STRIKE_PREMIUM_MIN = env_float('STRIKE_PREMIUM_MIN', 70.0)
STRIKE_PREMIUM_MAX = env_float('STRIKE_PREMIUM_MAX', 350.0)

# Number of consecutive same-direction signals (within a 5s window) required
# before an entry is taken. Previously a literal inside the CONFIG dict below.
REQUIRE_CONSECUTIVE_SIGNALS = env_int('REQUIRE_CONSECUTIVE_SIGNALS', 1)

# =========================================================
# 💰 POSITION SIZE ENGINE (core/engines/position_size_engine.py)
# =========================================================
# Previously a Python-only DEFAULT_CONFIG dict with no .env override at all —
# every value below mirrors that dict's defaults exactly, so this is a pure
# config-location change unless you edit values here.
POSITION_SIZE_ENV_CONFIG = {
    "base": {
        "default_risk_budget_pct": env_float('POS_SIZE_DEFAULT_RISK_PCT', 0.01),
        "min_risk_budget_pct": env_float('POS_SIZE_MIN_RISK_PCT', 0.002),
        "max_risk_budget_pct": env_float('POS_SIZE_MAX_RISK_PCT', 0.02),
    },
    "soft_adjustment": {
        "weights": {
            "score": env_float('POS_SIZE_WEIGHT_SCORE', 0.18),
            "confidence": env_float('POS_SIZE_WEIGHT_CONFIDENCE', 0.18),
            "market_quality": env_float('POS_SIZE_WEIGHT_MARKET_QUALITY', 0.18),
            "regime": env_float('POS_SIZE_WEIGHT_REGIME', 0.12),
            "volatility": env_float('POS_SIZE_WEIGHT_VOLATILITY', 0.14),
            "recovery": env_float('POS_SIZE_WEIGHT_RECOVERY', 0.10),
            "daily_loss": env_float('POS_SIZE_WEIGHT_DAILY_LOSS', 0.10),
        },
        "final_allocation_clamp": [
            env_float('POS_SIZE_ALLOC_CLAMP_MIN', 0.40),
            env_float('POS_SIZE_ALLOC_CLAMP_MAX', 1.10),
        ],
    },
    "ranges": {
        "score": [env_float('POS_SIZE_RANGE_SCORE_MIN', 0.80), env_float('POS_SIZE_RANGE_SCORE_MAX', 1.10)],
        "confidence": [env_float('POS_SIZE_RANGE_CONFIDENCE_MIN', 0.80), env_float('POS_SIZE_RANGE_CONFIDENCE_MAX', 1.10)],
        "market_quality": [env_float('POS_SIZE_RANGE_MARKET_QUALITY_MIN', 0.75), env_float('POS_SIZE_RANGE_MARKET_QUALITY_MAX', 1.10)],
        "regime": [env_float('POS_SIZE_RANGE_REGIME_MIN', 0.85), env_float('POS_SIZE_RANGE_REGIME_MAX', 1.05)],
        "volatility": [env_float('POS_SIZE_RANGE_VOLATILITY_MIN', 0.70), env_float('POS_SIZE_RANGE_VOLATILITY_MAX', 1.00)],
        "recovery": [env_float('POS_SIZE_RANGE_RECOVERY_MIN', 0.50), env_float('POS_SIZE_RANGE_RECOVERY_MAX', 1.00)],
        "daily_loss": [env_float('POS_SIZE_RANGE_DAILY_LOSS_MIN', 0.40), env_float('POS_SIZE_RANGE_DAILY_LOSS_MAX', 1.00)],
    },
    "safety_caps": {
        "max_capital_allocation_pct": env_float('POS_SIZE_MAX_CAPITAL_ALLOCATION_PCT', 0.20),
        "max_symbol_daily_risk_pct": env_float('POS_SIZE_MAX_SYMBOL_DAILY_RISK_PCT', 0.40),
        "max_lots": env_int('POS_SIZE_MAX_LOTS', 8),
        "min_executable_quantity": env_int('POS_SIZE_MIN_EXECUTABLE_QTY', 1),
        "enforce_lot_rounding": env_bool('POS_SIZE_ENFORCE_LOT_ROUNDING', True),
        "daily_risk_cap_pct": env_float('POS_SIZE_DAILY_RISK_CAP_PCT', 0.03),
        "recovery_mode_cap_pct": env_float('POS_SIZE_RECOVERY_MODE_CAP_PCT', 0.50),
        "min_lot_rounding_tolerance_pct": env_float('POS_SIZE_MIN_LOT_ROUNDING_TOLERANCE_PCT', 0.05),
    },
    "allocation_grades": {
        "A+": env_float('POS_SIZE_GRADE_A_PLUS', 1.02),
        "A": env_float('POS_SIZE_GRADE_A', 0.95),
        "B": env_float('POS_SIZE_GRADE_B', 0.85),
        "C": env_float('POS_SIZE_GRADE_C', 0.70),
    },
}

# =========================================================
# 📊 STRATEGY SCORING
# =========================================================

STRATEGY_NAME = 'smart_scalp_institutional'
STRATEGY_VERSION = '3.4'
MIN_SCORE_TO_TRADE = env_int('MIN_SCORE', 4)  # v3.4 entry gate lowered to 4
MIN_CONFIDENCE = env_int('MIN_CONFIDENCE', 70)  # Balanced: 70% (was 80, too strict)
MIN_CONFIDENCE_AFTER_3SL = env_int('MIN_CONFIDENCE_AFTER_3SL', 85)  # After 5 consecutive SL (was 92)
MAX_CONFIDENCE_SCORE = env_int('MAX_CONFIDENCE_SCORE', 11)  # 11-factor scoring model

# Entry Price Filter (ATM nearby range)
MIN_ENTRY_PREMIUM = env_float('MIN_ENTRY_PREMIUM', 70.0)   # Min ₹70
MAX_ENTRY_PREMIUM = env_float('MAX_ENTRY_PREMIUM', 350.0)  # Max ₹350 (was 150, blocked all ATM options)

# =========================================================
# ⏱️ TRADING LIMITS
# =========================================================

MAX_TRADES_PER_DAY = env_int('MAX_TRADES_PER_DAY', 30)
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
PAUSE_AFTER_LOSS_SEC = env_int('COOLDOWN_AFTER_CONSEC_LOSS', 900)

# =========================================================
# ⏸️ COOLDOWN
# =========================================================

COOLDOWN_NORMAL_SEC = env_int('COOLDOWN_NORMAL', 120)
COOLDOWN_AFTER_PROFIT_SEC = env_int('COOLDOWN_AFTER_PROFIT', 30)
COOLDOWN_AFTER_SL_SEC = env_int('COOLDOWN_AFTER_SL', 120)
COOLDOWN_AFTER_CONSECUTIVE_LOSS = env_int('COOLDOWN_AFTER_CONSEC_LOSS', 900)
COOLDOWN_EXPIRY_NORMAL = 120
COOLDOWN_EXPIRY_AFTER_SL = 180
# No capital was ever at risk on these blocks (risk-gate block, execution-drift
# skip, position-size-zero, order failure) — much shorter than a real trade's
# cooldown so the bot can retry once conditions change, not sit out a full
# post-trade cooldown for a trade that never happened.
COOLDOWN_NON_TRADE_BLOCK_SEC = env_int('COOLDOWN_NON_TRADE_BLOCK', 15)

# =========================================================
# 🔀 MODE SWITCH (AGGRESSIVE <-> SAFE) — switch-condition scalars only.
# The two full per-mode threshold dicts (AGGRESSIVE_THRESHOLDS/SAFE_THRESHOLDS
# in mode_switch.py, 8 keys x paper/live variant) stay hardcoded — lower
# priority since the whole subsystem doesn't activate in paper mode anyway
# (mode_switch.should_go_safe() always returns False under PAPER_TRADING).
# =========================================================
MODE_SWITCH_CONSECUTIVE_LOSS_TRIGGER = env_int('MODE_SWITCH_CONSECUTIVE_LOSS_TRIGGER', 1)
MODE_SWITCH_VOLUME_DETERIORATION_THRESHOLD = env_float('MODE_SWITCH_VOLUME_DETERIORATION_THRESHOLD', 0.9)
MODE_SWITCH_CHOP_DETECTION_THRESHOLD = env_float('MODE_SWITCH_CHOP_DETECTION_THRESHOLD', 0.0002)
MODE_SWITCH_THETA_DETERIORATION = env_float('MODE_SWITCH_THETA_DETERIORATION', 0.30)
MODE_SWITCH_SAFE_HOUR_NORMAL = env_int('MODE_SWITCH_SAFE_HOUR_NORMAL', 13)
MODE_SWITCH_VOLUME_RECOVERY_THRESHOLD = env_float('MODE_SWITCH_VOLUME_RECOVERY_THRESHOLD', 1.1)
MODE_SWITCH_RANGE_RECOVERY_THRESHOLD = env_float('MODE_SWITCH_RANGE_RECOVERY_THRESHOLD', 0.0004)
MODE_SWITCH_THETA_RECOVERY_THRESHOLD = env_float('MODE_SWITCH_THETA_RECOVERY_THRESHOLD', 0.20)

# =========================================================
# 🚨 KILL SWITCH (UPDATED v3.1 - Tighter Risk Control)
# =========================================================

KILL_SWITCH_ENABLED = env_bool('KILL_SWITCH_ENABLED', True)
# Owner's explicit decision (findings.md/fixed.md §13): ₹3,000 is the real
# daily loss ceiling, and the kill switch must equal MAX_DAILY_LOSS_AMOUNT's
# default exactly — not a tighter value — so emergency_check()'s two checks
# agree by construction instead of one silently pre-empting the other.
KILL_SWITCH_LOSS = env_int('KILL_SWITCH_LOSS', 3000)
KILL_SWITCH_DAILY_LOSS = KILL_SWITCH_LOSS
KILL_SWITCH_CONSEC_LOSS = env_int('KILL_SWITCH_CONSEC_LOSS', 5)
KILL_SWITCH_SPREAD = env_float('KILL_SWITCH_SPREAD_PCT', 0.6)
KILL_SWITCH_LATENCY = env_int('KILL_SWITCH_LATENCY_MS', 1500)

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
DELTA_MAX = env_float('DELTA_MAX', 0.80)
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
RSI_PERIOD = env_int('RSI_PERIOD', 18)
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
TICK_TIMEOUT_SEC = env_int('TICK_TIMEOUT_SEC', 3)
MIN_VOLUME = env_int('MIN_VOLUME', 100)
MIN_OPTION_PRICE = env_int('MIN_OPTION_PRICE', 1)
MAX_OPTION_PRICE = env_int('MAX_OPTION_PRICE', 500)
STALE_THRESHOLD_MS_WEBSOCKET = env_int('WS_STALE_MS', 10000)
STALE_THRESHOLD_MS_REST = env_int('REST_STALE_MS', 5000)
STALE_THRESHOLD_MS_UNKNOWN = env_int('UNKNOWN_STALE_MS', 2000)

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

# Execution guard: skip entries when signal becomes stale or price drifts too far.
ENTRY_SIGNAL_MAX_AGE_MS = env_int('ENTRY_SIGNAL_MAX_AGE_MS', 2500)
ENTRY_MAX_DRIFT_PCT = env_float('ENTRY_MAX_DRIFT_PCT', 0.75)

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
        'capital_utilization_pct': 80,
        'atr_risk_multiplier': 2.0,
        'vix_low_threshold': 12.0,
        'vix_high_threshold': 20.0,
    },
    'entry_filters': {
        'avoid_first_15min': AVOID_FIRST_15MIN,
        'min_volume_ratio': 1.2,
        'volume_confirmation_required': False,
        'require_consecutive_signals': REQUIRE_CONSECUTIVE_SIGNALS,
        'signal_max_age_ms': ENTRY_SIGNAL_MAX_AGE_MS,
        'max_entry_drift_pct': ENTRY_MAX_DRIFT_PCT,
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
        'stale_threshold_ms_websocket': STALE_THRESHOLD_MS_WEBSOCKET,
        'stale_threshold_ms_rest': STALE_THRESHOLD_MS_REST,
        'stale_threshold_ms_unknown': STALE_THRESHOLD_MS_UNKNOWN,
        'min_spot_price': 15000,
        'max_spot_price': 35000,
    },
    'cooldown': {
        'normal_sec': COOLDOWN_NORMAL_SEC,
        'after_profit_sec': COOLDOWN_AFTER_PROFIT_SEC,
        'after_sl_sec': COOLDOWN_AFTER_SL_SEC,
        'after_consecutive_loss_sec': COOLDOWN_AFTER_CONSECUTIVE_LOSS,
        'expiry_normal_sec': COOLDOWN_EXPIRY_NORMAL,
        'expiry_after_sl_sec': COOLDOWN_EXPIRY_AFTER_SL,
        'non_trade_block_sec': COOLDOWN_NON_TRADE_BLOCK_SEC,
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
        'notify_entries': TELEGRAM_NOTIFY_ENTRIES,
        'notify_exits': TELEGRAM_NOTIFY_EXITS,
        'notify_kill_switch': TELEGRAM_NOTIFY_KILL_SWITCH,
        'daily_summary': TELEGRAM_DAILY_SUMMARY,
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
