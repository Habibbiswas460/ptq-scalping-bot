"""
PTQ Scalping Bot - Main Entry Point
₹30,000 Configuration
With Auto-Reconnect, Telegram, Dashboard & Database
"""

import time
import socket
from datetime import datetime

# Import configuration
from config.constants import (
    CONFIG, TOTAL_CAPITAL, RISK_PER_TRADE, KILL_SWITCH_LOSS,
    MAX_DAILY_LOSS_AMOUNT, MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
    STOP_LOSS_AMOUNT, PROFIT_TARGET_1, PROFIT_TARGET_2,
    COOLDOWN_NORMAL_SEC, COOLDOWN_AFTER_SL_SEC
)

# Import core modules (new organized paths)
from core.trading.broker import broker
from core.risk.validators import is_data_valid, detect_day_type
from core.engines.entry_engine import entry_signal, MAX_RECENT_TICKS
from core.engines.exit_engine import check_exit_conditions
from core.engines.state_machine import (
    trading_state, state_idle, state_entry_ready, 
    state_in_trade, state_cooldown
)
from core.risk.session_trend import start_trading_session
from core.risk.kill_switch import emergency_check
from core.risk.greeks_calc import calculate_greeks, init_greeks_fetcher
from core.services.mode_switch import (
    update_trading_mode, get_current_mode, get_mode_emoji,
    is_entries_allowed, record_trade_result, reset_mode
)
from utils.helpers import now, market_open, estimate_vix_from_ticks, wait_for_market_open, set_vix_broker_client
from utils.logger import BotLogger

# New feature imports
try:
    from core.services.database import db, log_trade_entry, log_trade_exit, save_state
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False

try:
    from core.services.telegram_bot import init_telegram, get_telegram, notify_entry, notify_exit, notify_kill_switch, notify_daily_summary
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False

# Auto-reconnect settings
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_WAIT_SECONDS = 30
NETWORK_CHECK_INTERVAL = 60  # Check network every 60 seconds


def check_internet_connection(host="8.8.8.8", port=53, timeout=3):
    """
    Check if internet connection is available.
    Uses Google's DNS server for quick check.
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except (socket.error, socket.timeout):
        return False


def wait_for_internet(logger, max_wait_minutes=30):
    """
    Wait for internet connection to be restored.
    Returns True when connected, False if timeout.
    """
    start_time = time.time()
    max_wait_seconds = max_wait_minutes * 60
    check_count = 0
    
    while time.time() - start_time < max_wait_seconds:
        check_count += 1
        
        if check_internet_connection():
            logger.info(f"✅ Internet connection restored after {check_count} checks")
            return True
        
        if check_count % 6 == 1:  # Log every ~30 seconds
            elapsed = int(time.time() - start_time)
            logger.warning(f"⏳ Waiting for internet... ({elapsed}s elapsed)")
        
        time.sleep(5)  # Check every 5 seconds
    
    logger.error(f"✗ Internet not restored within {max_wait_minutes} minutes")
    return False


# Recent ticks for analysis
recent_ticks = []


def init_features(logger, state):
    """Initialize Telegram, Database, and Live Logs features"""
    
    # Initialize Database
    if HAS_DATABASE and CONFIG.get('database', {}).get('enabled', True):
        logger.info("✓ Database initialized (SQLite)")
    
    # Initialize Telegram Dashboard
    telegram_config = CONFIG.get('telegram', {})
    telegram_instance = None
    if HAS_TELEGRAM and telegram_config.get('enabled', False):
        telegram_instance = init_telegram(
            token=telegram_config.get('bot_token', ''),
            chat_id=telegram_config.get('chat_id', ''),
            enabled=True
        )
        telegram_instance.set_state_reference(state, broker)
        telegram_instance.set_logger(logger)
        telegram_instance.notify_startup({
            'capital': TOTAL_CAPITAL,
            'paper_trading': CONFIG['broker'].get('paper_trading', True),
            'ce_qty': CONFIG.get('strategy', {}).get('ce_entry', {}).get('quantity', 260),
            'pe_qty': CONFIG.get('strategy', {}).get('pe_entry', {}).get('quantity', 156),
            'sl_points': 8,
            'tp_points': 16
        })
        logger.info("✓ Telegram dashboard initialized")


def main():
    """Main trading loop - SMART SCALP v3.0"""
    global recent_ticks
    
    # Connect to broker
    if not broker.connect():
        return
    
    logger = broker.logger
    state = trading_state
    
    # Initialize Greeks fetcher with broker client (for API Greeks)
    if broker.broker_client:
        init_greeks_fetcher(broker.broker_client)
        set_vix_broker_client(broker.broker_client)  # Enable real India VIX fetching
        logger.info("✓ Greeks API fetcher initialized")
        logger.info("✓ India VIX fetcher initialized (real-time)")
    
    # Initialize new features (Telegram, Dashboard, Database)
    init_features(logger, state)
    
    # Import SMART SCALP config
    try:
        from config.constants import (
            STRATEGY_NAME, STRATEGY_VERSION, CE_QUANTITY, PE_QUANTITY,
            MIN_SCORE_TO_TRADE, MIN_CONFIDENCE, SL_POINTS_MIN, SL_POINTS_MAX
        )
        has_smart_scalp = True
    except ImportError:
        has_smart_scalp = False
        CE_QUANTITY, PE_QUANTITY = 260, 156
        MIN_SCORE_TO_TRADE, MIN_CONFIDENCE = 5, 60
        SL_POINTS_MIN, SL_POINTS_MAX = 7, 10
    
    logger.info("")
    logger.info("┌──────────────────────────────────────────────────────────────┐")
    logger.info("│           SMART SCALP v3.0  ·  ₹30K Configuration          │")
    logger.info("├──────────────────────────────────────────────────────────────┤")
    logger.info(f"│  Capital: ₹{TOTAL_CAPITAL:>6,}  │  CE: {CE_QUANTITY:>3} qty  │  PE: {PE_QUANTITY:>3} qty      │")
    logger.info(f"│  SL: {SL_POINTS_MIN}-{SL_POINTS_MAX} pts    │  TP: 2.0-2.5x   │  Score: {MIN_SCORE_TO_TRADE}+/{MIN_CONFIDENCE}%+   │")
    logger.info(f"│  Kill: ₹{KILL_SWITCH_LOSS:<5}   │  Max Loss: ₹{MAX_DAILY_LOSS_AMOUNT:<5} │  Mode: {get_current_mode():<10} │")
    logger.info(f"│  Cooldown: {COOLDOWN_NORMAL_SEC}s/{COOLDOWN_AFTER_SL_SEC}s │  Day: {state.day_type:<7}  │                  │")
    logger.info("└──────────────────────────────────────────────────────────────┘")
    
    state.last_hour_reset = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    try:
        # Wait for market to open if before 9:15 AM
        if not market_open():
            logger.info("⏰ Waiting for market open (09:15)...")
            if not wait_for_market_open():
                logger.info("Market closed for today")
                return
            logger.info("🔔 MARKET OPEN — Scanning started")
            logger.info("── SESSION ACTIVE ──")
        
        # Initialize session trend tracker with opening price
        # Get first tick to establish opening price reference
        opening_tick = broker.get_tick()
        if opening_tick and 'ltp' in opening_tick:
            # Use spot_price (NIFTY index) not ltp (option premium)
            opening_price = opening_tick.get('spot_price', opening_tick.get('ltp', 0))
            start_trading_session(opening_price)
            logger.info(f"📈 Session ref: NIFTY ₹{opening_price:,.2f}")
        
        logger.info("🔄 Main loop started")
        
        while market_open():
            state.loop_count += 1
            
            # Heartbeat — compact one-liner every 30s (~300 loops)
            if state.loop_count % 300 == 0:
                tick_now = broker.get_tick()
                ltp_str = f"₹{tick_now['ltp']:.2f}" if tick_now else "--"
                spot_str = f"₹{broker.spot_price:,.0f}" if broker.spot_price > 1000 else "--"
                wr = f"{(state.winning_trades/(state.winning_trades+state.losing_trades)*100):.0f}%" if (state.winning_trades+state.losing_trades) > 0 else "--"
                
                logger.info(
                    f"💓 #{state.loop_count} │ "
                    f"NIFTY {spot_str} │ "
                    f"LTP {ltp_str} │ "
                    f"PnL ₹{state.daily_pnl_inr:+.0f} │ "
                    f"Trades {state.total_trades_today} ({state.winning_trades}W/{state.losing_trades}L {wr}) │ "
                    f"Ticks {len(recent_ticks)}/{MAX_RECENT_TICKS} │ "
                    f"{get_current_mode()} │ "
                    f"{datetime.now().strftime('%H:%M:%S')}"
                )
            
            # Reset hourly counter
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            if current_hour > state.last_hour_reset:
                state.trades_this_hour = 0
                state.last_hour_reset = current_hour
                logger.info(f"♻ Hourly reset | Total today: {state.total_trades_today}")
            
            # Get market tick
            tick = broker.get_tick()
            
            # Data validation
            is_valid, validation_msg = is_data_valid(tick)
            if not is_valid:
                if state.loop_count % 100 == 0:
                    logger.tick_rejected(validation_msg, tick)
                time.sleep(0.1)
                continue
            
            # Update recent ticks
            recent_ticks.append(tick)
            if len(recent_ticks) > MAX_RECENT_TICKS:
                recent_ticks.pop(0)
            
            # Track ticks processed
            state.ticks_processed = getattr(state, 'ticks_processed', 0) + 1
            
            # Emergency checks
            kill_triggered, kill_reason, kill_details = emergency_check(
                tick, state.daily_pnl_inr, state.total_trades_today,
                broker.last_valid_tick_time
            )
            
            if kill_triggered:
                if state.current_trade:
                    broker.exit_position(
                        state.current_trade, "Kill switch: " + kill_reason,
                        state.daily_pnl_inr, TOTAL_CAPITAL
                    )
                    state.current_trade = None
                
                # Check if this is a recoverable kill switch (spread cooldown)
                is_spread_cooldown = kill_reason in ("Wide spread KILL", "Spread cooldown")
                
                if is_spread_cooldown:
                    # Recoverable - pause briefly then retry
                    if state.state != "KILL_SWITCH":
                        state.state = "KILL_SWITCH"
                        state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
                        logger.kill_switch(kill_reason, kill_details)
                        logger.warning(f"⚠ SPREAD KILL - {kill_reason} - Pausing {kill_details.get('cooldown_sec', 30)}s then retrying")
                    elif kill_reason == "Spread cooldown":
                        # Still in cooldown, just wait
                        pass
                    else:
                        # Cooldown expired, spread is now OK -> recover!
                        state.state = "IDLE"
                        logger.info("✅ Spread recovered - resuming trading")
                else:
                    # Permanent kill switch (loss, max trades)
                    if state.state != "KILL_SWITCH":
                        state.state = "KILL_SWITCH"
                        state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
                        logger.kill_switch(kill_reason, kill_details)
                        logger.warning(f"⚠ KILL SWITCH - {kill_reason} - NO NEW ENTRIES (bot continues)")
                
                # Continue running but skip entry logic
                time.sleep(1)
                continue
            
            # If we were in KILL_SWITCH but kill check passed, recover to IDLE
            if state.state == "KILL_SWITCH":
                state.state = "IDLE"
                logger.info("✅ Kill switch cleared - resuming trading")
            
            # Calculate Greeks
            greeks = calculate_greeks(tick, broker.spot_price, broker.current_strike)
            
            # Detect day type
            state.day_type = detect_day_type(greeks, greeks['tte'])
            
            # Update VIX
            state.estimated_vix = estimate_vix_from_ticks(recent_ticks, state.estimated_vix)
            
            # 🎛 UPDATE TRADING MODE (Aggressive ↔ Safe)
            current_mode = update_trading_mode(
                tick, greeks, state.day_type, 
                state.daily_pnl_inr, recent_ticks
            )
            
            # Check if entries allowed (not in LOCKDOWN)
            entries_allowed = is_entries_allowed()
            
            # State machine execution
            if state.state == "IDLE":
                if entries_allowed:
                    def entry_func(t):
                        return entry_signal(t, recent_ticks, state.day_type)
                    
                    # Tick buffer progress — every 50s (~500 loops)
                    if state.loop_count % 500 == 0:
                        logger.info(f"📊 Buffer: {len(recent_ticks)}/{MAX_RECENT_TICKS} ticks | VIX: {state.estimated_vix:.1f}%")
                    
                    state.state = state_idle(tick, greeks, state, entry_func, logger)
                else:
                    # In lockdown - no new entries
                    if state.loop_count % 1000 == 0:
                        logger.info("🔒 LOCKDOWN mode - entries blocked")
            
            elif state.state == "ENTRY_READY":
                state.state = state_entry_ready(tick, greeks, state, broker, logger)
            
            elif state.state == "IN_TRADE":
                state.state = state_in_trade(
                    tick, greeks, state, check_exit_conditions, 
                    broker, TOTAL_CAPITAL, logger
                )
            
            elif state.state == "COOLDOWN":
                state.state = state_cooldown(state, logger)
            
            # Detailed status — every 2 min (~1200 loops)
            if state.loop_count % 1200 == 0:
                mode_info = f"{get_mode_emoji()} {get_current_mode()}"
                day_info = f"{'🎯' if state.day_type == 'EXPIRY' else '📅'} {state.day_type}"
                trades_h = state.trades_this_hour
                trades_d = state.total_trades_today
                
                logger.info(
                    f"\n── STATUS ──────────────────────────────────────────\n"
                    f"  Mode: {mode_info}  │  Day: {day_info}  │  State: {state.state}\n"
                    f"  PnL: ₹{state.daily_pnl_inr:+.2f} ({state.daily_pnl_pct:+.2f}%)\n"
                    f"  Trades: {trades_h}/{MAX_TRADES_PER_HOUR} this hour, {trades_d}/{MAX_TRADES_PER_DAY} today\n"
                    f"  VIX: {state.estimated_vix:.1f}% │ Consec Losses: {state.consecutive_losses}\n"
                    f"────────────────────────────────────────────────────"
                )
            
            time.sleep(0.5)  # 500ms cycle - optimized for API limits
        
        logger.info("📉 Market closed")
        
    except KeyboardInterrupt:
        logger.warning("⚠ Manual shutdown")
        if state.current_trade:
            broker.exit_position(
                state.current_trade, "Manual shutdown",
                state.daily_pnl_inr, TOTAL_CAPITAL
            )
        return "SHUTDOWN"
    
    except (ConnectionError, socket.error, OSError) as e:
        logger.error(f"🌐 Network error: {e}")
        if state.current_trade:
            logger.warning("⚠ Open position during network error - will try to exit on reconnect")
        return "RECONNECT"
    
    except Exception as e:
        import traceback
        error_str = str(e).lower()
        # Check if it's a network-related error
        if any(x in error_str for x in ['name resolution', 'connection', 'network', 'timeout', 'unreachable']):
            logger.error(f"🌐 Network error detected: {e}")
            return "RECONNECT"
        
        logger.error(f"Fatal error in main loop | Exception: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        if state.current_trade:
            broker.exit_position(
                state.current_trade, "Error shutdown",
                state.daily_pnl_inr, TOTAL_CAPITAL
            )
        return "ERROR"
    
    finally:
        # Daily summary
        logger.daily_summary({
            'total_trades': state.total_trades_today,
            'winning_trades': state.winning_trades,
            'losing_trades': state.losing_trades,
            'total_pnl': state.daily_pnl_inr,
            'max_drawdown': min(0, state.daily_pnl_inr),
            'kill_switch_count': getattr(state, 'kill_switch_count', 0),
            'ticks_processed': getattr(state, 'ticks_processed', 0)
        })
        
        # Cleanup
        broker.logout()
        
        logger.info("")
        logger.info("┌─────────── SESSION SUMMARY ───────────┐")
        logger.info(f"│  P&L: ₹{state.daily_pnl_inr:+8.2f} ({state.daily_pnl_pct:+.2f}%)       │")
        logger.info(f"│  Trades: {state.total_trades_today:2d} total ({state.winning_trades}W / {state.losing_trades}L)       │")
        logger.info(f"│  Win Rate: {state.total_trades_today and (state.winning_trades/state.total_trades_today*100):.1f}%                       │")
        logger.info(f"│  Consec Losses: {state.consecutive_losses}                    │")
        logger.info(f"│  State: {state.state:<12}                    │")
        logger.info("└───────────────────────────────────────┘")
        logger.info("✓ Bot shutdown complete")
    
    return "COMPLETED"


def run_with_auto_reconnect():
    """
    Run main() with auto-reconnect on network failures.
    Handles power/internet outages gracefully.
    """
    reconnect_count = 0
    temp_logger = BotLogger(enable_console=True)
    
    temp_logger.info("")
    temp_logger.info("── PTQ SCALPING BOT ── Auto-Reconnect ON ──")
    temp_logger.info(f"   Reconnects: {MAX_RECONNECT_ATTEMPTS} max │ Wait: {RECONNECT_WAIT_SECONDS}s")
    temp_logger.info("")
    
    while reconnect_count < MAX_RECONNECT_ATTEMPTS:
        try:
            # Check internet before starting
            if not check_internet_connection():
                temp_logger.warning("🌐 No internet connection detected")
                if wait_for_internet(temp_logger):
                    temp_logger.info("✅ Internet restored, starting bot...")
                    time.sleep(2)
                else:
                    temp_logger.error("✗ Could not establish internet connection")
                    break
            
            # Run main trading loop
            result = main()
            
            if result == "SHUTDOWN":
                temp_logger.info("✓ Clean shutdown requested")
                break
            
            elif result == "COMPLETED":
                temp_logger.info("✓ Trading day completed")
                break
            
            elif result == "RECONNECT":
                reconnect_count += 1
                temp_logger.warning(f"🔄 Reconnect attempt {reconnect_count}/{MAX_RECONNECT_ATTEMPTS}")
                
                # Wait for internet to be restored
                if not wait_for_internet(temp_logger, max_wait_minutes=15):
                    temp_logger.error("✗ Internet not restored, will retry...")
                
                # Additional wait before reconnect
                temp_logger.info(f"⏳ Waiting {RECONNECT_WAIT_SECONDS}s before reconnect...")
                time.sleep(RECONNECT_WAIT_SECONDS)
                
                # Reset global state for fresh start
                global recent_ticks
                recent_ticks = []
                
                temp_logger.info("🔄 Attempting to reconnect...")
                continue
            
            elif result == "ERROR":
                temp_logger.error("✗ Fatal error occurred")
                break
            
            else:
                # Unknown result, exit
                break
                
        except KeyboardInterrupt:
            temp_logger.warning("⚠ Manual interrupt")
            break
        except Exception as e:
            error_str = str(e).lower()
            if any(x in error_str for x in ['name resolution', 'connection', 'network', 'timeout']):
                reconnect_count += 1
                temp_logger.warning(f"🌐 Network error: {e}")
                temp_logger.warning(f"🔄 Reconnect attempt {reconnect_count}/{MAX_RECONNECT_ATTEMPTS}")
                
                if wait_for_internet(temp_logger, max_wait_minutes=15):
                    time.sleep(RECONNECT_WAIT_SECONDS)
                    continue
            else:
                temp_logger.error(f"✗ Unexpected error: {e}")
                break
    
    if reconnect_count >= MAX_RECONNECT_ATTEMPTS:
        temp_logger.error(f"✗ Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded")
    
    temp_logger.info("")
    temp_logger.info("── SESSION ENDED ──")


if __name__ == "__main__":
    run_with_auto_reconnect()
