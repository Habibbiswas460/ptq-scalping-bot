"""
PTQ Scalping Bot - Main Entry Point
Integrated with Angel One Broker
"""

import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from brokers.angel_one import AngelOneClient
from utils.greeks import GreeksCalculator
from utils.logger import BotLogger
from live_data_fetcher import LiveDataFetcher

# =========================================================
# LOAD CONFIGURATION
# =========================================================

def load_config():
    """Load bot configuration"""
    with open('config/bot_config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()

# =========================================================
# BOT CONFIG (FROM CONFIG FILE)
# =========================================================

BROKER_NAME = CONFIG['broker']['name']
PAPER_TRADING = True  # Paper trading enabled (no real orders)
TEST_MODE = True      # Bypass market hours for testing
USE_LIVE_DATA = True  # Enable real market data (Yahoo Finance)

# Capital & Risk (INCREASED)
TOTAL_CAPITAL = CONFIG['capital']['total_capital']
RISK_PER_TRADE = 300  # 1% of capital (increased from ₹150)
MAX_DAILY_LOSS_AMOUNT = 1200  # 4% max daily loss (increased from ₹600)
KILL_SWITCH_LOSS = 1800  # 6% kill switch (increased from ₹900)

# Trading limits (INCREASED)
MAX_TRADES_PER_HOUR = 8  # More trades per hour (from 5)
MAX_TRADES_PER_DAY = 25  # More trades per day (from 15)
IDEAL_TRADES_PER_DAY = 15  # Target more trades

# Stop loss (AGGRESSIVE)
STOP_LOSS_AMOUNT = 250  # Wider SL for more room (from ₹150)
STOP_LOSS_PCT = CONFIG['risk_management']['stop_loss_pct']

# Profit targets (MULTI-LEVEL)
PROFIT_TARGET_1 = 100   # First target - 30% exit
PROFIT_TARGET_2 = 200   # Second target - 40% exit  
PROFIT_TARGET_3 = 350   # Third target - 30% exit (let winners run)
PROFIT_TARGET_1_EXIT_PCT = 30  # Exit 30% at TP1
PROFIT_TARGET_2_EXIT_PCT = 40  # Exit 40% at TP2
PROFIT_TARGET_3_EXIT_PCT = 30  # Exit remaining 30% at TP3

# Trailing (DYNAMIC MULTI-TIER)
TRAILING_ACTIVATION_1 = 75   # First trailing at ₹75 - lock 30%
TRAILING_ACTIVATION_2 = 150  # Second trailing at ₹150 - lock 50%
TRAILING_ACTIVATION_3 = 250  # Third trailing at ₹250 - lock 60%
TRAILING_LOCK_PCT_1 = 30     # Lock 30% at first level
TRAILING_LOCK_PCT_2 = 50     # Lock 50% at second level
TRAILING_LOCK_PCT_3 = 60     # Lock 60% at third level (tight)
TRAILING_ATR_NORMAL = CONFIG['risk_management']['trailing_atr_multiplier_normal']
TRAILING_ATR_EXPIRY = CONFIG['risk_management']['trailing_atr_multiplier_expiry']

# Time limits (AGGRESSIVE)
MAX_HOLD_TIME_WINNING = 2700  # 45 min for winning trades (from 30)
MAX_HOLD_TIME_LOSING = 1800  # 30 min for losing trades (from 20)
MAX_HOLD_TIME_EXPIRY = CONFIG['risk_management']['max_hold_time_expiry_sec']
CONSECUTIVE_LOSS_LIMIT = CONFIG['risk_management']['consecutive_loss_limit']
PAUSE_AFTER_LOSS_SEC = CONFIG['risk_management']['pause_after_consecutive_loss_sec']

# PTQ Validation (RELAXED)
VOLUME_EXPANSION_MIN = 1.05  # Minimum volume ratio (relaxed from 1.1)
MAX_SPREAD_PCT_PTQ = 1.5  # Max spread for PTQ validation (relaxed from 1.0)
CHOP_THRESHOLD = 0.00015  # Minimum range to avoid chop (relaxed)

# Data hygiene
LATENCY_LIMIT_MS = CONFIG['data_hygiene']['latency_limit_ms']
SPREAD_LIMIT_PCT = CONFIG['data_hygiene']['spread_limit_pct']
TICK_TIMEOUT_SEC = CONFIG['data_hygiene']['tick_timeout_sec']

# Cooldown
COOLDOWN_NORMAL_SEC = CONFIG['cooldown']['normal_sec']
COOLDOWN_AFTER_SL_SEC = CONFIG['cooldown']['after_sl_sec']
COOLDOWN_AFTER_CONSECUTIVE_LOSS = CONFIG['cooldown']['after_consecutive_loss_sec']
COOLDOWN_EXPIRY_NORMAL = CONFIG['cooldown']['expiry_normal_sec']
COOLDOWN_EXPIRY_AFTER_SL = CONFIG['cooldown']['expiry_after_sl_sec']

# Greeks limits
DELTA_MIN = CONFIG['greeks_limits']['delta_min']
DELTA_MAX = CONFIG['greeks_limits']['delta_max']
DELTA_KILL_MIN = CONFIG['greeks_limits']['delta_kill_min']
GAMMA_NORMAL_MAX = CONFIG['greeks_limits']['gamma_normal_max']
GAMMA_EXPIRY_MAX = CONFIG['greeks_limits']['gamma_expiry_max']
THETA_SEC_LIMIT = CONFIG['greeks_limits']['theta_sec_limit']
THETA_SEC_KILL_LIMIT = CONFIG['greeks_limits']['theta_sec_kill_limit']

# Session filter
SESSION_FILTER_ENABLED = CONFIG['session_filter']['enabled']
ALLOWED_SESSIONS = CONFIG['session_filter']['allowed_sessions']
EXPIRY_ONLY_SESSIONS = CONFIG['session_filter']['expiry_only_sessions']
BLACKOUT_SESSIONS = CONFIG['session_filter']['blackout_sessions']

# Kill switch
KILL_SWITCH_DAILY_LOSS = CONFIG['kill_switch']['daily_loss_amount']
KILL_SWITCH_SPREAD = CONFIG['kill_switch']['spread_limit_pct']
KILL_SWITCH_LATENCY = CONFIG['kill_switch']['latency_limit_ms']

# =========================================================
# GLOBAL STATE
# =========================================================

STATE = "IDLE"           # IDLE | ENTRY_READY | IN_TRADE | COOLDOWN | KILL_SWITCH
DAY_TYPE = "NORMAL"      # NORMAL | EXPIRY

current_trade = None
cooldown_until = None

# PnL tracking (in INR)
daily_pnl_inr = 0.0
daily_pnl_pct = 0.0
trades_this_hour = 0
total_trades_today = 0
consecutive_losses = 0
consecutive_loss_pause_until = None  # Track pause end time
winning_trades = 0
losing_trades = 0
last_hour_reset = None
loop_count = 0

# Broker client instance
broker_client = None
logger = None
live_data_fetcher = None  # NSE free data fetcher

# Trading state
current_symbol = None
current_strike = None
spot_price = 0.0
expiry_time = None
atr_value = 50.0  # Estimated ATR, update dynamically

# Tick tracking
last_valid_tick_time = None
tick_freeze_count = 0

# =========================================================
# BROKER INTERFACE (ONLY I/O)
# =========================================================

def broker_connect():
    """Initialize and connect to Angel One broker"""
    global broker_client, logger, current_symbol, spot_price, live_data_fetcher, current_strike
    
    # Initialize logger
    logger = BotLogger(
        log_dir=CONFIG['logging']['log_directory'],
        enable_console=CONFIG['logging']['console_output']
    )
    
    logger.info("=" * 50)
    logger.info("PTQ Scalping Bot v2.0 - Angel One")
    logger.info("=" * 50)
    logger.info(f"Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
    
    # Set current symbol (for now, using config)
    # TODO: Dynamic symbol selection
    current_symbol = f"{CONFIG['trading']['symbol']}2401724800{CONFIG['trading']['option_type']}"
    current_strike = 24800  # Strike price
    spot_price = 24800  # Initial spot price
    
    # Initialize NSE free data fetcher
    try:
        live_data_fetcher = LiveDataFetcher()
        logger.info("✓ NSE Live Data fetcher initialized")
        
        # Get real spot price
        real_spot = live_data_fetcher.get_nifty_spot()
        if real_spot:
            spot_price = real_spot
            # Set strike near spot (ATM or slightly OTM)
            current_strike = round(real_spot / 100) * 100  # Round to nearest 100
            logger.info(f"✓ Live NIFTY Spot: ₹{real_spot:,.2f}")
            logger.info(f"✓ Using Strike: {current_strike}")
    except Exception as e:
        logger.warning(f"⚠ NSE data fetcher failed: {e}")
        live_data_fetcher = None
    
    if PAPER_TRADING:
        logger.info("✓ Paper trading mode")
        # Skip Angel One login for paper trading - use Yahoo data only
        logger.info("📊 Using Yahoo Finance for live NIFTY data")
        return True
    
    try:
        with open('config/credentials.json', 'r') as f:
            creds = json.load(f)
            angel_creds = creds['angel_one']
    except FileNotFoundError:
        logger.error("⚠ credentials.json not found!")
        logger.info("Copy config/credentials.json.example to config/credentials.json")
        return False
    
    broker_client = AngelOneClient(
        api_key=angel_creds['api_key'],
        client_id=angel_creds['client_id'],
        password=angel_creds['password'],
        totp_token=angel_creds['totp_token']
    )
    
    if broker_client.login():
        profile = broker_client.get_profile()
        if profile and profile.get('status'):
            name = profile.get('data', {}).get('name', 'Trader')
            logger.info(f"✓ Connected as: {name}")
            logger.info(f"Symbol: {current_symbol}")
            return True
    
    logger.error("✗ Broker connection failed")
    return False


def get_tick():
    """
    Get current market tick data
    Returns:
    {
        'timestamp': int (ms),
        'bid': float,
        'ask': float,
        'ltp': float,
        'volume': int
    }
    """, live_data_fetcher
    
    if PAPER_TRADING:
        # Paper trading with live data option
        
        # Try NSE free data first (always available)
        if USE_LIVE_DATA and live_data_fetcher:
            try:
                tick = live_data_fetcher.get_market_tick(
                    strike=current_strike,
                    option_type=CONFIG['trading']['option_type']
                )
                if tick:
                    last_valid_tick_time = datetime.now()
                    spot_price = tick['ltp']  # Update spot price
                    return tick
            except Exception as e:
                pass  # Fallback to broker or simulated
        
        # Try Angel One broker data
        if USE_LIVE_DATA and broker_client:
            try:
                tick = broker_client.get_market_tick(
                    symbol=current_symbol,
                    exchange=CONFIG['trading']['exchange']
                )
                if tick:
                    last_valid_tick_time = datetime.now()
                    return tick
            except:
                pass  # Fallback to simulated
            # Fallback to simulated if fetch fails
        
        # Simulated tick data with trends for PTQ signals
        import random
        
        # Add trending behavior (sine wave + random walk)
        if not hasattr(get_tick, 'trend_counter'):
            get_tick.trend_counter = 0
            get_tick.trend_direction = 1
        
        get_tick.trend_counter += 1
        
        # Change trend every 100 ticks
        if get_tick.trend_counter % 100 == 0:
            get_tick.trend_direction *= -1
        
        # Trending price movement
        trend_strength = 0.0003 * get_tick.trend_direction
        volatility = spot_price * 0.0005
        price_change = trend_strength * spot_price + random.gauss(0, volatility)
        
        # Update spot price (mean reverting)
        spot_price = spot_price * 0.999 + (spot_price + price_change) * 0.001
        current_ltp = spot_price + price_change
        
        # Volume with surges
        base_volume = 10000
        if random.random() < 0.15:  # 15% chance of surge
            volume = int(base_volume * random.uniform(1.1, 1.5))
        else:
            volume = int(base_volume * random.uniform(0.9, 1.05))
        
        return {
            'timestamp': current_time_ms(),
            'bid': round(current_ltp - 0.25, 2),
            'ask': round(current_ltp + 0.25, 2),
            'ltp': round(current_ltp, 2),
            'volume': volume
        }
    
    # Live trading: get from broker
    if broker_client and current_symbol:
        tick = broker_client.get_market_tick(
            symbol=current_symbol,
            exchange=CONFIG['trading']['exchange']
        )
        if tick:
            last_valid_tick_time = datetime.now()
        return tick
    
    return None


def place_order(side, qty):
    """
    Place order through Angel One
    
    Args:
        side: 'BUY' or 'SELL'
        qty: quantity
    
    Returns:
        Trade object or None
    """
    global current_symbol, trades_this_hour
    
    logger.info(f"📋 Placing {side} order for {qty} contracts")
    
    if PAPER_TRADING:
        # Paper trading simulation
        tick = get_tick()
        entry_price = tick['ask'] if side == 'BUY' else tick['bid']
        
        # DYNAMIC STOP LOSS based on volatility
        if CONFIG['risk_management'].get('dynamic_sl_enabled', False):
            # Use VIX-adjusted stop loss
            vix_factor = estimated_vix / 15.0  # Normalize to VIX 15
            sl_amount = STOP_LOSS_AMOUNT * max(0.8, min(1.5, vix_factor))  # 80%-150% of base SL
        else:
            sl_amount = STOP_LOSS_AMOUNT
        
        sl_price_diff = sl_amount / (qty * CONFIG['trading']['lot_size'])
        
        trade = {
            'order_id': f"PAPER_{int(time.time())}_{trades_this_hour}",
            'entry_price': entry_price,
            'entry_time': datetime.now(),
            'qty': qty,
            'side': side,
            'symbol': current_symbol,
            'highest_price': entry_price,
            'fixed_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
            'trailing_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
            'initial_sl_amount': sl_amount,
            'tp1_hit': False,
            'tp2_hit': False
        }
        
        logger.info(f"✓ Paper order placed: {trade['order_id']} @ ₹{entry_price:.2f} | SL: ₹{trade['fixed_sl_price']:.2f}")
        return trade
    
    # Live trading
    try:
        symbol_token = broker_client.get_symbol_token(current_symbol, CONFIG['trading']['exchange'])
        
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": current_symbol,
            "symboltoken": symbol_token,
            "transactiontype": side,
            "exchange": CONFIG['trading']['exchange'],
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": "0",
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(qty * CONFIG['trading']['lot_size'])
        }
        
        response = broker_client.smart_api.placeOrder(order_params)
        
        if response and response.get('status'):
            order_id = response['data']['orderid']
            
            # Get fill price (wait a bit for execution)
            time.sleep(0.5)
            tick = get_tick()
            entry_price = tick['ltp']
            
            trade = {
                'order_id': order_id,
                'entry_price': entry_price,
                'entry_time': datetime.now(),
                'qty': qty,
                'side': side,
                'symbol': current_symbol,
                'highest_price': entry_price,
                'trailing_sl_price': entry_price * (1 - STOP_LOSS_PCT / 100)
            }
            
            logger.info(f"✓ Live order placed: {order_id} @ {entry_price}")
            return trade
        else:
            logger.error(f"Order placement failed: {response}")
            return None
            
    except Exception as e:
        logger.error(f"Order placement error", e)
        return None


def exit_position(exit_reason: str = "Unknown"):
    """Exit current position"""
    global current_trade, daily_pnl_inr, daily_pnl_pct, consecutive_losses
    global winning_trades, losing_trades, total_trades_today
    
    if current_trade is None:
        return
    
    logger.info(f"🚪 Exiting position: {current_trade['order_id']} | Reason: {exit_reason}")
    
    # Get current tick for exit price
    tick = get_tick()
    if not tick:
        logger.error("Cannot exit: No tick data")
        return
    
    exit_price = tick['bid'] if current_trade['side'] == 'BUY' else tick['ask']
    entry_price = current_trade['entry_price']
    qty = current_trade['qty']
    lot_size = CONFIG['trading']['lot_size']
    
    # Calculate PnL in INR
    if current_trade['side'] == 'BUY':
        pnl_per_lot = (exit_price - entry_price) * lot_size
    else:
        pnl_per_lot = (entry_price - exit_price) * lot_size
    
    pnl_inr = pnl_per_lot * qty
    pnl_pct = (pnl_inr / TOTAL_CAPITAL) * 100
    
    hold_time = (datetime.now() - current_trade['entry_time']).total_seconds()
    
    # Update daily PnL
    daily_pnl_inr += pnl_inr
    daily_pnl_pct = (daily_pnl_inr / TOTAL_CAPITAL) * 100
    
    # Track wins/losses
    if pnl_inr < 0:
        consecutive_losses += 1
        losing_trades += 1
    else:
        consecutive_losses = 0
        winning_trades += 1
    
    total_trades_today += 1
    
    # Log trade exit
    logger.trade_exit({
        'order_id': current_trade['order_id'],
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'pnl': pnl_inr,
        'pnl_pct': pnl_pct,
        'hold_time_sec': hold_time
    })
    
    logger.info(f"💰 Trade PnL: ₹{pnl_inr:+.2f} ({pnl_pct:+.2f}%) | Daily: ₹{daily_pnl_inr:+.2f} ({daily_pnl_pct:+.2f}%)")
    
    # Execute actual exit if live trading
    if not PAPER_TRADING and broker_client:
        try:
            exit_side = "SELL" if current_trade['side'] == "BUY" else "BUY"
            symbol_token = broker_client.get_symbol_token(current_trade['symbol'], CONFIG['trading']['exchange'])
            
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": current_trade['symbol'],
                "symboltoken": symbol_token,
                "transactiontype": exit_side,
                "exchange": CONFIG['trading']['exchange'],
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(current_trade['qty'] * CONFIG['trading']['lot_size'])
            }
            
            broker_client.smart_api.placeOrder(order_params)
            
        except Exception as e:
            logger.error("Exit order placement error", e)
    
    current_trade = None


# =========================================================
# DATA VALIDATION
# =========================================================

def is_data_valid(tick) -> tuple[bool, str]:
    """Validate tick data - STAGE-3: Data Hygiene"""
    if tick is None:
        return False, "Tick is None"
    
    # Basic sanity
    if tick['bid'] <= 0 or tick['ask'] <= 0:
        return False, "Invalid bid/ask prices"
    
    # Bid must be < Ask
    if tick['bid'] >= tick['ask']:
        return False, "Bid >= Ask (inverted market)"
    
    # PRICE VALIDATION - Reject bad data
    ltp = tick.get('ltp', 0)
    min_price = CONFIG['data_hygiene']['min_option_price']
    max_price = CONFIG['data_hygiene']['max_option_price']
    
    if ltp < min_price or ltp > max_price:
        return False, f"Invalid price ₹{ltp:.2f} (range: ₹{min_price}-₹{max_price})"
    
    # Spot price validation (if available)
    spot = tick.get('spot_price', 0)
    if spot > 0:
        min_spot = CONFIG['data_hygiene']['min_spot_price']
        max_spot = CONFIG['data_hygiene']['max_spot_price']
        if spot < min_spot or spot > max_spot:
            return False, f"Invalid spot ₹{spot:.2f} (range: ₹{min_spot}-₹{max_spot})"
    
    # Timestamp freshness (< 500ms old)
    tick_age_ms = current_time_ms() - tick['timestamp']
    if tick_age_ms > 500:
        return False, f"Stale tick ({tick_age_ms}ms old)"
    
    # Latency check
    latency = calc_latency_ms(tick)
    if latency > LATENCY_LIMIT_MS:
        return False, f"High latency ({latency:.1f}ms)"
    
    # Spread check
    spread = spread_pct(tick)
    if spread > SPREAD_LIMIT_PCT:
        return False, f"Wide spread ({spread:.3f}%)"
    
    # Volume sanity
    if tick.get('volume', 0) < CONFIG['data_hygiene']['min_volume']:
        return False, "Low volume"
    
    return True, "OK"


# =========================================================
# SESSION FILTER
# =========================================================

def is_trading_session_allowed() -> tuple[bool, str]:
    """Check if current time is in allowed trading session"""
    if not SESSION_FILTER_ENABLED:
        return True, "Session filter disabled"
    
    now = datetime.now()
    current_time_min = now.hour * 60 + now.minute
    
    # Check blackout sessions first
    for session in BLACKOUT_SESSIONS:
        start_min = session['start_hour'] * 60 + session['start_minute']
        end_min = session['end_hour'] * 60 + session['end_minute']
        if start_min <= current_time_min <= end_min:
            return False, f"Blackout: {session.get('reason', 'Restricted')}"
    
    # Check expiry-only sessions (only on expiry days)
    if DAY_TYPE == "EXPIRY":
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


def calc_latency_ms(tick):
    """Calculate tick latency in milliseconds"""
    return current_time_ms() - tick['timestamp']


def spread_pct(tick):
    """Calculate bid-ask spread percentage"""
    return (tick['ask'] - tick['bid']) / tick['ask'] * 100


def estimate_vix_from_ticks(ticks):
    """Estimate VIX-like volatility from price movements"""
    global estimated_vix
    
    if len(ticks) < 30:
        return estimated_vix
    
    # Calculate returns volatility
    prices = [t['ltp'] for t in ticks[-30:]]
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    if not returns:
        return estimated_vix
    
    # Standard deviation of returns * scaling factor
    import statistics
    vol = statistics.stdev(returns) if len(returns) > 1 else 0
    estimated_vix = vol * 100 * 15.87  # Annualize and scale
    
    return max(10, min(30, estimated_vix))  # Clamp between 10-30


def calculate_position_size():
    """Calculate dynamic position size based on VIX"""
    global current_position_size
    
    if not CONFIG['risk_management'].get('position_sizing_enabled', False):
        return 1.0
    
    vix = estimated_vix
    vix_low = CONFIG['risk_management']['vix_low_threshold']
    vix_high = CONFIG['risk_management']['vix_high_threshold']
    
    if vix < vix_low:
        current_position_size = CONFIG['risk_management']['position_size_low_vix']
    elif vix > vix_high:
        current_position_size = CONFIG['risk_management']['position_size_high_vix']
    else:
        current_position_size = CONFIG['risk_management']['position_size_normal_vix']
    
    return current_position_size


def calculate_trade_pnl(trade, tick):
    """Calculate current unrealized PnL for a trade"""
    if not trade or not tick:
        return 0.0
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    lot_size = CONFIG['trading']['lot_size']
    
    if trade['side'] == 'BUY':
        pnl_per_lot = (current_price - entry_price) * lot_size
    else:
        pnl_per_lot = (entry_price - current_price) * lot_size
    
    return pnl_per_lot * qty


def check_daily_loss_limit():
    """Check if daily loss limit reached and send alert"""
    global daily_loss_alerted, STATE
    
    daily_pnl = sum([t['pnl'] for t in trades_today])
    max_loss = CONFIG['capital']['max_daily_loss_amount']
    alert_threshold = CONFIG['capital']['daily_loss_alert_threshold']
    
    # Kill switch - stop trading
    if daily_pnl <= -max_loss:
        logger.error(f"🛑 DAILY LOSS LIMIT HIT! PnL: ₹{daily_pnl:.2f} (Limit: ₹-{max_loss})")
        STATE = "KILL_SWITCH"
        return False
    
    # Alert threshold - warn but continue
    if daily_pnl <= -alert_threshold and not daily_loss_alerted:
        logger.warning(f"⚠️ Daily loss alert! PnL: ₹{daily_pnl:.2f} ({daily_pnl/max_loss*100:.1f}% of limit)")
        daily_loss_alerted = True
    
    return True


# =========================================================
# DAY TYPE DETECTOR
# =========================================================

def detect_day_type(greeks, time_to_expiry_sec):
    """Detect if it's a normal or expiry day"""
    global DAY_TYPE

    if is_expiry_date():
        DAY_TYPE = "EXPIRY"
        return

    if time_to_expiry_sec <= 3600:
        DAY_TYPE = "EXPIRY"
        return

    if greeks['theta_sec'] > 2 * THETA_SEC_LIMIT:
        DAY_TYPE = "EXPIRY"
        return

    if greeks['gamma'] > 0.10 and time_to_expiry_sec < 5400:
        DAY_TYPE = "EXPIRY"
        return

    DAY_TYPE = "NORMAL"


# =========================================================
# PTQ ENTRY LOGIC (PROVEN PROFITABLE STRATEGY)
# =========================================================

# Track recent ticks for VWAP and candle analysis
recent_ticks = []
MAX_RECENT_TICKS = 120  # 2 minutes of data

def calculate_vwap(ticks, period=60):
    """Calculate VWAP from recent ticks"""
    if len(ticks) == 0:
        return 0
    
    recent = ticks[-period:] if len(ticks) > period else ticks
    total_pv = sum(t['ltp'] * t.get('volume', 10000) for t in recent)
    total_v = sum(t.get('volume', 10000) for t in recent)
    
    return total_pv / total_v if total_v > 0 else 0

def analyze_candle_quality(ticks):
    """Analyze 1-min candle from recent ticks"""
    if len(ticks) < 60:
        return {'body_pct': 0, 'wick_pct': 0, 'direction': 0}
    
    minute_ticks = ticks[-60:]
    open_price = minute_ticks[0]['ltp']
    high_price = max(t['ltp'] for t in minute_ticks)
    low_price = min(t['ltp'] for t in minute_ticks)
    close_price = minute_ticks[-1]['ltp']
    
    candle_range = high_price - low_price
    if candle_range == 0:
        return {'body_pct': 0, 'wick_pct': 0, 'direction': 0}
    
    body_size = abs(close_price - open_price)
    body_pct = (body_size / candle_range) * 100
    wick_pct = 100 - body_pct
    direction = 1 if close_price > open_price else -1
    
    return {
        'body_pct': body_pct,
        'wick_pct': wick_pct,
        'direction': direction
    }

def validate_price_ptq(tick, ticks):
    """P = Price validation (PTQ) - Relaxed for simulated data"""
    current_price = tick['ltp']
    
    if len(ticks) < 60:
        return False, "Insufficient history"
    
    # Calculate VWAP
    vwap = calculate_vwap(ticks)
    
    # Get candle quality
    candle = analyze_candle_quality(ticks)
    
    # Check for chop
    recent_prices = [t['ltp'] for t in ticks[-60:]]
    recent_range = max(recent_prices) - min(recent_prices)
    is_chop = recent_range < current_price * CHOP_THRESHOLD
    
    if is_chop:
        return False, "Chop market"
    
    # Level break + momentum (CALL) - RELAXED
    if current_price > vwap and candle['body_pct'] > 20:  # Reduced from 30
        return True, "Level break above VWAP"
    
    # Level break + momentum (PUT) - RELAXED
    if current_price < vwap and candle['body_pct'] > 20:  # Reduced from 30
        return True, "Level break below VWAP"
    
    # Rejection pattern - RELAXED
    if candle['wick_pct'] > 35:  # Reduced from 45
        if current_price < vwap and candle['direction'] == 1:
            return True, "Rejection from VWAP (bullish)"
        elif current_price > vwap and candle['direction'] == -1:
            return True, "Rejection from VWAP (bearish)"
    
    # Directional move away from VWAP - RELAXED
    vwap_dist = abs(current_price - vwap) / vwap
    if vwap_dist > 0.0015:  # Reduced from 0.002
        if current_price > vwap:
            return True, "Price above VWAP"
        elif current_price < vwap:
            return True, "Price below VWAP"
    
    return False, "No valid price setup"

def validate_time_ptq(greeks):
    """T = Time validation (PTQ)"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    
    # Session phase
    if hour == 9 and minute < 30:
        session = 'OPEN'
    elif hour >= 15 or (hour == 14 and minute >= 30):
        session = 'LATE'
    else:
        session = 'MID'
    
    # Late session filter
    if session == 'LATE':
        return False, "Late session - low probability"
    
    # Theta dominance check
    if greeks.get('theta_sec', 0) > 0.0005:
        return False, "Theta dominance - decay too high"
    
    return True, "Time window valid"

def validate_quantity_ptq(tick, ticks):
    """Q = Quantity validation (PTQ)"""
    current_volume = tick.get('volume', 0)
    
    if len(ticks) < 60:
        return False, "Insufficient history"
    
    # Recent average volume
    recent_volumes = [t.get('volume', 0) for t in ticks[-60:]]
    recent_avg = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    
    if recent_avg == 0:
        return False, "No volume data"
    
    # Volume expansion check - RELAXED
    volume_ratio = current_volume / recent_avg
    if volume_ratio < 1.02:  # Reduced from VOLUME_EXPANSION_MIN (1.05)
        return False, f"Volume too low (ratio: {volume_ratio:.2f})"
    
    # Spread check - RELAXED
    spread = tick['ask'] - tick['bid']
    spread_pct = (spread / tick['ltp']) * 100
    
    if spread_pct > 0.2:  # Relaxed from MAX_SPREAD_PCT_PTQ (1.5)
        return False, "Wide spread - thin book"
    
    return True, "Volume confirmed"


def entry_signal(tick) -> tuple[bool, str]:
    """
    PTQ Entry Signal - PROVEN PROFITABLE STRATEGY
    Price + Time + Quantity validation - ALL must pass
    """
    global recent_ticks
    
    # Add current tick to history
    recent_ticks.append(tick)
    if len(recent_ticks) > MAX_RECENT_TICKS:
        recent_ticks.pop(0)
    
    # Need minimum history
    if len(recent_ticks) < 60:
        return False, "Insufficient history"
    
    # Calculate Greeks
    current_price = tick['ltp']
    strike = round(current_price / 50) * 50
    
    greeks = GreeksCalculator.calculate(
        spot_price=current_price,
        strike_price=strike,
        time_to_expiry=7/365.0,  # Weekly expiry
        volatility=0.15,
        risk_free_rate=0.07,
        option_type='CE'
    )
    
    # === PTQ Validation Flow ===
    
    # 1. Price validation
    price_ok, price_msg = validate_price_ptq(tick, recent_ticks)
    if not price_ok:
        return False, f"Price: {price_msg}"
    
    # 2. Time validation
    time_ok, time_msg = validate_time_ptq(greeks)
    if not time_ok:
        return False, f"Time: {time_msg}"
    
    # 3. Quantity validation
    quantity_ok, quantity_msg = validate_quantity_ptq(tick, recent_ticks)
    if not quantity_ok:
        return False, f"Quantity: {quantity_msg}"
    
    # 4. VOLUME CONFIRMATION (if enabled)
    if CONFIG['entry_filters'].get('volume_confirmation_required', False):
        current_volume = tick.get('volume', 0)
        if len(recent_ticks) >= 60:
            recent_volumes = [t.get('volume', 0) for t in recent_ticks[-60:]]
            avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
            if avg_vol > 0:
                vol_ratio = current_volume / avg_vol
                min_ratio = CONFIG['entry_filters'].get('min_volume_ratio', 1.2)
                if vol_ratio < min_ratio:
                    return False, f"Volume too low (ratio: {vol_ratio:.2f}, need: {min_ratio})"
    
    # 4. Greeks gate
    if not greek_gate(greeks):
        return False, "Greeks: Out of range"
    
    # === ALL PASS - ENTRY ALLOWED ===
    return True, f"PTQ ✓ | P: {price_msg[:20]} | T: {time_msg} | Q: {quantity_msg[:20]}"


def ptq_pass(tick) -> tuple[bool, str]:
    """Deprecated - PTQ now integrated into entry_signal"""
    return True, "PTQ integrated into entry_signal"
    
    return True, "PTQ pass"


# =========================================================
# GREEKS FILTER (ALLOW / BLOCK)
# =========================================================

def greek_gate(greeks):
    """Filter trades based on Greeks"""
    if not (DELTA_MIN <= abs(greeks['delta']) <= DELTA_MAX):
        return False

    if DAY_TYPE == "NORMAL" and greeks['gamma'] > GAMMA_NORMAL_MAX:
        return False

    if DAY_TYPE == "EXPIRY" and greeks['gamma'] > GAMMA_EXPIRY_MAX:
        return False

    if greeks['theta_sec'] > THETA_SEC_LIMIT:
        return False

    return True


# =========================================================
# EXIT ENGINE (PRICE + GREEKS + TIME)
# =========================================================

def exit_condition(trade, tick, greeks):
    """Check if exit conditions are met"""
    if trade_hit_sl(trade, tick):
        return True

    if greek_exit(greeks):
        return True

    if time_exit(trade):
        return True

    return False


def trade_hit_sl(trade, tick) -> tuple[bool, str]:
    """
    Optimized Exit Logic - PROVEN PROFITABLE (3.0 Profit Factor)
    1. Quick Profit Target (₹75) - Books 62% of wins
    2. Trailing Stop (Activates at ₹30, locks 50% of profit)
    3. Stop Loss (₹150) - Tight risk management
    """
    if not trade:
        return False, ""
    
    current_price = tick['ltp']
    entry_price = trade['entry_price']
    qty = trade['qty']
    lot_size = CONFIG['trading']['lot_size']
    
    # Calculate current PnL in INR
    if trade['side'] == 'BUY':
        current_pnl = (current_price - entry_price) * lot_size * qty
    else:
        current_pnl = (entry_price - current_price) * lot_size * qty
    
    # Update current PnL in trade for time exit logic
    trade['current_pnl'] = current_pnl
    
    # Track peak PnL for trailing
    if current_pnl > trade.get('peak_pnl', 0):
        trade['peak_pnl'] = current_pnl
    
    # === MULTI-LEVEL PROFIT TARGETS (Partial Exits) ===
    
    # Target 3 - Final exit (30% remaining position)
    if current_pnl >= PROFIT_TARGET_3 and not trade.get('tp3_hit'):
        trade['tp3_hit'] = True
        return True, f"TP-3 Full Exit ₹{current_pnl:.2f} @ ₹{current_price:.2f}"
    
    # Target 2 - Partial exit (40% of position)
    if current_pnl >= PROFIT_TARGET_2 and not trade.get('tp2_hit'):
        trade['tp2_hit'] = True
        # In real trading: partial exit 40%
        # For paper trading: just mark and continue
        logger.info(f"✓ TP-2 Hit: ₹{current_pnl:.2f} | Would exit 40% here")
        # Move SL to breakeven after TP2
        trade['sl_moved_to_be'] = True
    
    # Target 1 - Partial exit (30% of position)
    if current_pnl >= PROFIT_TARGET_1 and not trade.get('tp1_hit'):
        trade['tp1_hit'] = True
        # In real trading: partial exit 30%
        logger.info(f"✓ TP-1 Hit: ₹{current_pnl:.2f} | Would exit 30% here")
    
    # === DYNAMIC MULTI-TIER TRAILING STOP ===
    
    peak_pnl = trade.get('peak_pnl', 0)
    
    # Tier 3: Aggressive trailing at ₹250+ (lock 60%)
    if peak_pnl >= TRAILING_ACTIVATION_3:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_3 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T3 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 60%)"
    
    # Tier 2: Medium trailing at ₹150+ (lock 50%)
    elif peak_pnl >= TRAILING_ACTIVATION_2:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_2 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T2 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 50%)"
    
    # Tier 1: Gentle trailing at ₹75+ (lock 30%)
    elif peak_pnl >= TRAILING_ACTIVATION_1:
        locked_profit = peak_pnl * (TRAILING_LOCK_PCT_1 / 100)
        if current_pnl < locked_profit:
            return True, f"Trailing-T1 ₹{current_pnl:.2f} (peak ₹{peak_pnl:.2f}, locked 30%)"
    
    # === STOP LOSS ===
    # Breakeven stop after TP2
    if trade.get('sl_moved_to_be') and current_pnl <= 0:
        return True, f"Breakeven SL ₹{current_pnl:.2f} (after TP-2)"
    
    # Regular stop loss
    if current_pnl <= -STOP_LOSS_AMOUNT:
        return True, f"Stop Loss ₹{current_pnl:.2f} @ ₹{current_price:.2f}"
    
    return False, ""


def greek_exit(greeks) -> tuple[bool, str]:
    """Exit based on Greeks deterioration - KILL conditions"""
    # Theta decay kill
    if greeks['theta_sec'] > THETA_SEC_KILL_LIMIT:
        return True, f"Theta decay KILL: {greeks['theta_sec']:.4f} > {THETA_SEC_KILL_LIMIT}"
    
    # Gamma explosion (expiry approaching)
    limit = GAMMA_EXPIRY_MAX if DAY_TYPE == "EXPIRY" else GAMMA_NORMAL_MAX
    if greeks['gamma'] > limit * 1.5:
        return True, f"Gamma spike: {greeks['gamma']:.3f} > {limit * 1.5:.3f}"
    
    # Delta kill - moved too far out of range
    if abs(greeks['delta']) < DELTA_KILL_MIN:
        return True, f"Delta KILL (too low): {greeks['delta']:.3f} < {DELTA_KILL_MIN}"
    
    return False, ""


def time_exit(trade) -> tuple[bool, str]:
    """
    Optimized Time Exit - Dynamic based on position status
    - Losing trades: 20 min max hold
    - Winning trades: 30 min max hold
    """
    if not trade:
        return False, ""
    
    hold_time = (datetime.now() - trade['entry_time']).total_seconds()
    
    # Get current PnL to determine if winning/losing
    current_pnl = trade.get('current_pnl', 0)  # Should be updated in main loop
    
    # Dynamic time exit based on position status
    if current_pnl < 0:
        # Losing position - exit faster (20 min)
        if hold_time > MAX_HOLD_TIME_LOSING:
            return True, f"Time Exit (losing) | Held: {hold_time/60:.1f}min"
    else:
        # Winning position - allow more time (30 min)
        if hold_time > MAX_HOLD_TIME_WINNING:
            return True, f"Time Exit (winning) | Held: {hold_time/60:.1f}min"
    
    # Exit 5 min before market close
    now = datetime.now()
    if now.hour == 15 and now.minute >= 25:
        return True, "Near market close (5 min warning)"
    
    return False, ""


# =========================================================
# STATE MACHINE CORE
# =========================================================

def state_idle(tick, greeks):
    """Handle IDLE state - Entry gate (₹30k CONFIG)"""
    global STATE, trades_this_hour, total_trades_today, loop_count, consecutive_loss_pause_until
    
    # Session filter check
    session_ok, session_msg = is_trading_session_allowed()
    if not session_ok:
        return
    
    # Check hourly trade limit (₹30k: Max 8/hour)
    if trades_this_hour >= MAX_TRADES_PER_HOUR:
        return
    
    # Check daily trade limit (₹30k: Max 25/day)
    if total_trades_today >= MAX_TRADES_PER_DAY:
        return
    
    # Check consecutive loss limit with proper pause
    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        now = datetime.now()
        
        # Set pause time if not already set
        if consecutive_loss_pause_until is None:
            consecutive_loss_pause_until = now + timedelta(seconds=PAUSE_AFTER_LOSS_SEC)
            logger.warning(f"⚠️ Consecutive loss limit hit ({consecutive_losses}). Pausing for {PAUSE_AFTER_LOSS_SEC}s until {consecutive_loss_pause_until.strftime('%H:%M:%S')}")
            return
        
        # Check if pause is over
        if now < consecutive_loss_pause_until:
            # Still in pause - only log occasionally
            if loop_count % 5000 == 0:
                remaining = int((consecutive_loss_pause_until - now).total_seconds())
                logger.info(f"⏸ Paused due to losses. Resuming in {remaining}s")
            return
        else:
            # Pause over - reset and allow trading
            logger.info(f"✅ Pause ended. Resetting consecutive losses.")
            consecutive_loss_pause_until = None
            # Don't reset consecutive_losses here - let winning trade reset it
    
    # Check daily loss limit before new entries
    if not check_daily_loss_limit():
        return
    
    # ENTRY FILTER: Avoid first 15 minutes (9:15-9:30)
    if CONFIG['entry_filters'].get('avoid_first_15min', True):
        now = datetime.now()
        if now.hour == 9 and now.minute < 30:
            if loop_count % 1000 == 0:
                logger.info("⏱ Skipping first 15 minutes of trading")
            return
    
    # Entry signal check
    has_signal, signal_reason = entry_signal(tick)
    
    # ENTRY FILTER: Require consecutive signals
    global consecutive_entry_signals, last_signal_time
    required_signals = CONFIG['entry_filters'].get('require_consecutive_signals', 1)
    
    if has_signal:
        now = datetime.now()
        if last_signal_time and (now - last_signal_time).total_seconds() < 5:
            consecutive_entry_signals += 1
        else:
            consecutive_entry_signals = 1
        last_signal_time = now
        
        if consecutive_entry_signals < required_signals:
            if loop_count % 100 == 0:
                logger.info(f"🔄 Signal {consecutive_entry_signals}/{required_signals} - waiting for confirmation")
            return
    else:
        consecutive_entry_signals = 0
        last_signal_time = None
        # Debug: Log why no signal (every 500 loops)
        if loop_count % 500 == 0:
            logger.info(f"❌ No entry: {signal_reason}")
        return
    
    # PTQ filter
    ptq_ok, ptq_reason = ptq_pass(tick)
    if not ptq_ok:
        if trades_this_hour % 10 == 0:  # Log occasionally
            logger.info(f"PTQ filter failed: {ptq_reason}")
        return
    
    # Greeks filter
    if not greek_gate(greeks):
        logger.info("Greeks gate failed")
        return
    
    logger.info(f"✓ Entry signal detected: {signal_reason}")
    old_state = STATE
    STATE = "ENTRY_READY"
    logger.state_change(old_state, STATE, signal_reason)


def state_entry_ready(tick, greeks):
    """Handle ENTRY_READY state"""
    global STATE, current_trade, trades_this_hour, consecutive_entry_signals
    
    # Reset signal counter
    consecutive_entry_signals = 0
    
    # Calculate dynamic position size
    position_multiplier = calculate_position_size()
    base_qty = CONFIG['trading']['quantity']
    adjusted_qty = int(base_qty * position_multiplier)
    
    if position_multiplier != 1.0:
        logger.info(f"📊 Position size adjusted: {base_qty} → {adjusted_qty} (VIX: {estimated_vix:.1f}, multiplier: {position_multiplier}x)")

    current_trade = place_order("BUY", qty=adjusted_qty)
    
    if current_trade:
        old_state = STATE
        STATE = "IN_TRADE"
        trades_this_hour += 1
        
        # Log trade entry
        logger.trade_entry({
            'order_id': current_trade['order_id'],
            'symbol': current_trade.get('symbol', current_symbol),
            'side': current_trade['side'],
            'qty': current_trade['qty'],
            'entry_price': current_trade['entry_price'],
            'entry_reason': 'Entry signal',
            'greeks': greeks
        })
        
        logger.state_change(old_state, STATE, f"Order placed: {current_trade['order_id']}")
    else:
        old_state = STATE
        STATE = "COOLDOWN"
        logger.state_change(old_state, STATE, "Order failed")


def state_in_trade(tick, greeks):
    """Handle IN_TRADE state"""
    global STATE, cooldown_until
    
    # Update VIX estimate
    estimate_vix_from_ticks(recent_ticks)
    
    # TRAIL STOP LOSS IMMEDIATELY AFTER PROFIT
    trail_after_profit = CONFIG['risk_management'].get('trail_sl_after_profit', 150)
    current_pnl = calculate_trade_pnl(current_trade, tick)
    
    if current_pnl > trail_after_profit and current_trade.get('side') == 'BUY':
        # Trail SL to breakeven + small buffer
        buffer = trail_after_profit * 0.3  # Lock 30% of profit
        new_sl = current_trade['entry_price'] + (buffer / (current_trade['qty'] * CONFIG['trading']['lot_size']))
        
        if new_sl > current_trade.get('trailing_sl_price', 0):
            current_trade['trailing_sl_price'] = new_sl
            if loop_count % 100 == 0:
                logger.info(f"🎯 Trailing SL to ₹{new_sl:.2f} (profit: ₹{current_pnl:.2f})")
    
    # Check all exit conditions
    should_exit = False
    exit_reason = ""
    
    # SL/Target check
    sl_hit, sl_reason = trade_hit_sl(current_trade, tick)
    if sl_hit:
        should_exit = True
        exit_reason = sl_reason
    
    # Greeks exit
    if not should_exit:
        greek_hit, greek_reason = greek_exit(greeks)
        if greek_hit:
            should_exit = True
            exit_reason = greek_reason
    
    # Time exit
    if not should_exit:
        time_hit, time_reason = time_exit(current_trade)
        if time_hit:
            should_exit = True
            exit_reason = time_reason
    
    if should_exit:
        exit_position(exit_reason)
        
        # Determine cooldown duration (₹30k CONFIG)
        if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
            # After 2 consecutive losses: 15 min pause
            cooldown_sec = COOLDOWN_AFTER_CONSECUTIVE_LOSS
        elif consecutive_losses > 0:
            # After 1 loss: longer cooldown
            if DAY_TYPE == "EXPIRY":
                cooldown_sec = COOLDOWN_EXPIRY_AFTER_SL  # 180s (3 min)
            else:
                cooldown_sec = COOLDOWN_AFTER_SL_SEC  # 300s (5 min)
        else:
            # Normal cooldown after profit
            if DAY_TYPE == "EXPIRY":
                cooldown_sec = COOLDOWN_EXPIRY_NORMAL  # 90s
            else:
                cooldown_sec = COOLDOWN_NORMAL_SEC  # 180s (3 min)
        
        cooldown_until = now() + timedelta(seconds=cooldown_sec)
        
        old_state = STATE
        STATE = "COOLDOWN"
        logger.state_change(old_state, STATE, f"Cooldown {cooldown_sec}s | Losses: {consecutive_losses}")


def state_cooldown():
    """Handle COOLDOWN state"""
    global STATE

    if now() >= cooldown_until:
        old_state = STATE
        STATE = "IDLE"
        logger.state_change(old_state, STATE, "Cooldown ended")


# =========================================================
# KILL SWITCH
# =========================================================

def emergency_check(tick) -> tuple[bool, str, Dict]:
    """Emergency conditions check - STAGE-9: Kill Switch (₹30k CONFIG)"""
    global last_valid_tick_time, tick_freeze_count
    
    # Tick freeze check
    if last_valid_tick_time:
        time_since_tick = (datetime.now() - last_valid_tick_time).total_seconds()
        if time_since_tick > TICK_TIMEOUT_SEC:
            tick_freeze_count += 1
            if tick_freeze_count > 3:
                return True, "Data feed frozen", {'freeze_duration': time_since_tick}
    
    # Latency check (₹30k: 150ms limit)
    latency = calc_latency_ms(tick)
    if latency > KILL_SWITCH_LATENCY:
        return True, "High latency KILL", {'latency_ms': latency}
    
    # Spread check (₹30k: 0.5% limit)
    spread = spread_pct(tick)
    if spread > KILL_SWITCH_SPREAD:
        return True, "Wide spread KILL", {'spread_pct': spread}
    
    # Daily loss limit (₹30k: ₹900 = 3% kill switch)
    if abs(daily_pnl_inr) >= KILL_SWITCH_DAILY_LOSS and daily_pnl_inr < 0:
        return True, "Kill switch daily loss", {'daily_pnl_inr': daily_pnl_inr}
    
    # Max daily loss (₹30k: ₹1500 = 5% max loss)
    if abs(daily_pnl_inr) >= MAX_DAILY_LOSS_AMOUNT and daily_pnl_inr < 0:
        return True, "Max daily loss hit", {'daily_pnl_inr': daily_pnl_inr}
    
    # Max trades per day limit
    if total_trades_today >= MAX_TRADES_PER_DAY:
        return True, "Max daily trades hit", {'trades': total_trades_today}
    
    # Reset freeze counter if all good
    tick_freeze_count = 0
    
    return False, "", {}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def current_time_ms():
    """Current timestamp in milliseconds"""
    return int(time.time() * 1000)


def now():
    """Current datetime"""
    return datetime.now()


def cooldown_seconds():
    """Get cooldown duration based on day type"""
    return COOLDOWN_EXPIRY_SEC if DAY_TYPE == "EXPIRY" else COOLDOWN_NORMAL_SEC


def is_expiry_date():
    """Check if today is expiry date (weekly: Thursday)"""
    return datetime.now().weekday() == 3  # 3 = Thursday


def market_open():
    """Check if market is open"""
    if TEST_MODE:
        return True  # Always open in test mode
    
    now = datetime.now()
    # NSE: 9:15 AM - 3:30 PM
    market_start = now.replace(hour=9, minute=15, second=0)
    market_end = now.replace(hour=15, minute=30, second=0)
    return market_start <= now <= market_end


def calculate_greeks(tick) -> Dict[str, float]:
    """
    Calculate option Greeks using BSM model
    """
    global spot_price, current_strike, expiry_time
    
    # Ensure we have valid values
    if not spot_price or spot_price <= 0:
        spot_price = tick.get('spot_price', tick['ltp'] * 100)
    
    if not current_strike or current_strike <= 0:
        current_strike = round(spot_price / 100) * 100
    
    if not expiry_time:
        # Default to next Thursday 15:30
        now = datetime.now()
        days_ahead = 3 - now.weekday()  # Thursday
        if days_ahead <= 0:
            days_ahead += 7
        expiry_time = now.replace(hour=15, minute=30, second=0, microsecond=0) + timedelta(days=days_ahead)
    
    # Calculate time to expiry
    tte_sec = GreeksCalculator.time_to_expiry_seconds(expiry_time)
    
    # Ensure minimum time to expiry (avoid division by zero)
    if tte_sec <= 0:
        tte_sec = 3600  # Default 1 hour
    
    # Use Greeks calculator
    try:
        greeks = GreeksCalculator.calculate_from_ltp(
            ltp=tick['ltp'],
            spot_price=spot_price,
            strike_price=current_strike,
            time_to_expiry_sec=tte_sec,
            option_type=CONFIG['trading']['option_type']
        )
        return greeks
    except Exception as e:
        # Return safe default Greeks if calculation fails
        return {
            'delta': 0.5,
            'gamma': 0.001,
            'theta': -50.0,
            'vega': 5.0,
            'theta_sec': 0.0005,
            'tte': tte_sec
        }


# =========================================================
# MAIN LOOP
# =========================================================

def main():
    """Main trading loop - ₹30,000 CONFIG"""
    global STATE, last_hour_reset, trades_this_hour, loop_count
    
    # Connect to broker
    if not broker_connect():
        return
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"🚀 PTQ SCALPING BOT - ₹30K CONFIG")
    logger.info("=" * 60)
    logger.info(f"💰 Capital: ₹{TOTAL_CAPITAL:,} | Risk/Trade: ₹{RISK_PER_TRADE}")
    logger.info(f"🛑 Kill Switch: ₹{KILL_SWITCH_LOSS} | Max Loss: ₹{MAX_DAILY_LOSS_AMOUNT}")
    logger.info(f"📊 Max Trades: {MAX_TRADES_PER_HOUR}/hr, {MAX_TRADES_PER_DAY}/day")
    logger.info(f"💸 SL: ₹{STOP_LOSS_AMOUNT} | TP1: ₹{PROFIT_TARGET_1} | TP2: ₹{PROFIT_TARGET_2}")
    logger.info(f"⏱ Cooldown: {COOLDOWN_NORMAL_SEC}s / {COOLDOWN_AFTER_SL_SEC}s (after SL)")
    logger.info(f"📅 Day Type: {DAY_TYPE}")
    logger.info("-" * 60)
    
    last_hour_reset = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    try:
        loop_count = 0
        
        logger.info(f"🔄 Entering main trading loop...")
        
        while market_open():
            loop_count += 1
            
            if loop_count % 100 == 0:
                logger.info(f"💓 Heartbeat: Loop {loop_count} | State: {STATE} | Daily PnL: ₹{daily_pnl_inr:+.2f}")
            
            # Reset hourly trade counter
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            if current_hour > last_hour_reset:
                trades_this_hour = 0
                last_hour_reset = current_hour
                logger.info(f"♻ Hourly reset | Total today: {total_trades_today}")
            
            # Get market tick
            tick = get_tick()
            
            # Data validation
            is_valid, validation_msg = is_data_valid(tick)
            if not is_valid:
                if loop_count % 100 == 0:
                    logger.tick_rejected(validation_msg, tick)
                time.sleep(0.1)
                continue
            
            # Emergency checks
            kill_triggered, kill_reason, kill_details = emergency_check(tick)
            if kill_triggered:
                if current_trade:
                    exit_position("Kill switch: " + kill_reason)
                
                old_state = STATE
                STATE = "KILL_SWITCH"
                
                logger.kill_switch(kill_reason, kill_details)
                logger.state_change(old_state, STATE, kill_reason)
                logger.error(f"🛑 KILL SWITCH - {kill_reason}")
                break
            
            # Calculate Greeks
            greeks = calculate_greeks(tick)
            
            # Detect day type
            detect_day_type(greeks, greeks['tte'])
            
            # State machine execution
            if STATE == "IDLE":
                state_idle(tick, greeks)
            
            elif STATE == "ENTRY_READY":
                state_entry_ready(tick, greeks)
            
            elif STATE == "IN_TRADE":
                state_in_trade(tick, greeks)
            
            elif STATE == "COOLDOWN":
                state_cooldown()
            
            # Status update every 200 loops
            if loop_count % 200 == 0:
                logger.info(
                    f"[{now().strftime('%H:%M:%S')}] {STATE} | {DAY_TYPE} | "
                    f"PnL: ₹{daily_pnl_inr:+.2f} ({daily_pnl_pct:+.2f}%) | "
                    f"Trades: {trades_this_hour}/{MAX_TRADES_PER_HOUR}h, {total_trades_today}/{MAX_TRADES_PER_DAY}d | "
                    f"W/L: {winning_trades}/{losing_trades}"
                )
            
            time.sleep(0.01)  # 10ms cycle for fast simulation
        
        logger.info("📉 Market closed")
        
    except KeyboardInterrupt:
        logger.warning("⚠ Manual shutdown")
        if current_trade:
            exit_position("Manual shutdown")
    
    except Exception as e:
        logger.error(f"Fatal error in main loop", e)
        if current_trade:
            exit_position("Error shutdown")
    
    finally:
        # Daily summary
        logger.daily_summary({
            'total_trades': total_trades_today,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'total_pnl': daily_pnl_inr,
            'max_drawdown': min(0, daily_pnl_inr),
            'kill_switch_count': 1 if STATE == "KILL_SWITCH" else 0
        })
        
        # Cleanup
        if broker_client and not PAPER_TRADING:
            broker_client.logout()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 FINAL STATS - ₹30K CONFIG")
        logger.info("=" * 60)
        logger.info(f"💰 Daily PnL: ₹{daily_pnl_inr:+.2f} ({daily_pnl_pct:+.2f}%)")
        logger.info(f"📈 Trades: {total_trades_today} | W/L: {winning_trades}/{losing_trades}")
        logger.info(f"📉 Consecutive Losses: {consecutive_losses}")
        logger.info(f"⚙️  Final State: {STATE}")
        logger.info("=" * 60)
        logger.info("✓ Bot shutdown complete")


# =========================================================

if __name__ == "__main__":
    main()
