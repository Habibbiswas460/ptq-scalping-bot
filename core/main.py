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
from core.risk.kill_switch import emergency_check
from core.risk.greeks_calc import calculate_greeks, init_greeks_fetcher
from core.services.mode_switch import (
    update_trading_mode, get_current_mode, get_mode_emoji,
    is_entries_allowed, record_trade_result, reset_mode
)
from utils.helpers import now, market_open, estimate_vix_from_ticks, wait_for_market_open
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

try:
    from core.services.dashboard import start_dashboard_background, set_state_reference
    HAS_DASHBOARD = True
except ImportError:
    HAS_DASHBOARD = False


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
    """Initialize Telegram, Dashboard, and Database features"""
    
    # Initialize Database
    if HAS_DATABASE and CONFIG.get('database', {}).get('enabled', True):
        logger.info("✓ Database initialized (SQLite)")
    
    # Initialize Telegram
    telegram_config = CONFIG.get('telegram', {})
    if HAS_TELEGRAM and telegram_config.get('enabled', False):
        telegram = init_telegram(
            token=telegram_config.get('bot_token', ''),
            chat_id=telegram_config.get('chat_id', ''),
            enabled=True
        )
        telegram.set_state_reference(state, broker)
        telegram.notify_startup({
            'capital': TOTAL_CAPITAL,
            'paper_trading': CONFIG['broker'].get('paper_trading', True),
            'ce_qty': CONFIG.get('strategy', {}).get('ce_entry', {}).get('quantity', 260),
            'pe_qty': CONFIG.get('strategy', {}).get('pe_entry', {}).get('quantity', 156),
            'sl_points': 8,
            'tp_points': 16
        })
        logger.info("✓ Telegram bot initialized")
    
    # Initialize Dashboard
    dashboard_config = CONFIG.get('dashboard', {})
    if HAS_DASHBOARD and dashboard_config.get('enabled', True):
        set_state_reference(state, broker, recent_ticks)
        if dashboard_config.get('auto_start', True):
            port = dashboard_config.get('port', 8080)
            start_dashboard_background(port=port)
            logger.info(f"✓ Dashboard started at http://localhost:{port}")


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
        logger.info("✓ Greeks API fetcher initialized")
    
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
    logger.info("╔══════════════════════════════════════════════════════════════════════════════╗")
    logger.info("║                          🏆 SMART SCALP v3.0 🏆                           ║")
    logger.info("║                           ₹30K CONFIGURATION                             ║")
    logger.info("╚══════════════════════════════════════════════════════════════════════════════╝")
    logger.info("")
    logger.info("🎯 STRATEGY: Multi-factor Scoring System")
    logger.info(f"💰 CAPITAL: ₹{TOTAL_CAPITAL:,} | RISK/TRADE: ₹{RISK_PER_TRADE}")
    logger.info(f"📊 QUANTITIES: CE {CE_QUANTITY} qty | PE {PE_QUANTITY} qty")
    logger.info(f"🎯 REQUIREMENTS: {MIN_SCORE_TO_TRADE}+ Score | {MIN_CONFIDENCE}%+ Confidence")
    logger.info(f"🛡️ RISK MANAGEMENT: SL {SL_POINTS_MIN}-{SL_POINTS_MAX} pts | TP 2.0-2.5x")
    logger.info(f"🛑 KILL SWITCH: ₹{KILL_SWITCH_LOSS} | MAX DAILY LOSS: ₹{MAX_DAILY_LOSS_AMOUNT}")
    logger.info(f"⏱ COOLDOWN: {COOLDOWN_NORMAL_SEC}s / {COOLDOWN_AFTER_SL_SEC}s (after SL)")
    logger.info(f"📅 DAY TYPE: {state.day_type}")
    logger.info(f"🎛 TRADING MODE: {get_current_mode()} {get_mode_emoji()}")
    logger.info("")
    logger.info("─" * 78)
    
    state.last_hour_reset = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    try:
        # Wait for market to open if before 9:15 AM
        if not market_open():
            logger.info("⏰ Market not open yet...")
            if not wait_for_market_open():
                logger.info("📉 Market closed for today")
                return
            logger.info("🔔 MARKET IS NOW OPEN! 🚀")
            logger.info("🎯 Starting signal scanning and trade execution...")
            logger.info("")
            logger.info("╔══════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                        🎯 TRADING SESSION ACTIVE 🎯                        ║")
            logger.info("╚══════════════════════════════════════════════════════════════════════════════╝")
        
        logger.info(f"🔄 Entering main trading loop...")
        
        while market_open():
            state.loop_count += 1
            
            # Heartbeat - More beautiful and informative
            if state.loop_count % 100 == 0:
                mode_emoji = get_mode_emoji()
                current_mode = get_current_mode()
                day_type_emoji = "🎯" if state.day_type == "EXPIRY" else "📅"
                
                logger.info(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ 💓 HEARTBEAT #{state.loop_count:4d} | {mode_emoji} {current_mode:>10} | {day_type_emoji} {state.day_type:>6} ║
║ 💰 PnL: ₹{state.daily_pnl_inr:+8.2f} ({state.daily_pnl_pct:+5.2f}%) ║
║ 📊 Trades: {state.total_trades_today:2d} total | {state.winning_trades:2d}W/{state.losing_trades:2d}L ║
║ 🎯 VIX: {state.estimated_vix:4.1f}% | ⏱ {datetime.now().strftime('%H:%M:%S')} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".strip())
            
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
                
                # Don't shutdown - just block new entries and continue monitoring
                if state.state != "KILL_SWITCH":
                    state.state = "KILL_SWITCH"
                    logger.kill_switch(kill_reason, kill_details)
                    logger.warning(f"⚠ KILL SWITCH - {kill_reason} - NO NEW ENTRIES (bot continues)")
                
                # Continue running but skip entry logic
                time.sleep(1)
                continue
            
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
                    
                    # Show tick count progress every 500 loops
                    if state.loop_count % 500 == 0:
                        logger.info(f"📈 Tick buffer: {len(recent_ticks)}/{MAX_RECENT_TICKS} | Spot: ₹{broker.spot_price:,.2f}")
                    
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
            
            # Status update - More detailed and beautiful
            if state.loop_count % 200 == 0:
                mode_info = f"{get_mode_emoji()} {get_current_mode()}"
                day_info = f"{'🎯' if state.day_type == 'EXPIRY' else '📅'} {state.day_type}"
                
                logger.info(f"""
🌟 STATUS UPDATE 🌟
├─ Mode: {mode_info}
├─ Day: {day_info}
├─ State: {state.state}
├─ PnL: ₹{state.daily_pnl_inr:+.2f} ({state.daily_pnl_pct:+.2f}%)
├─ Trades: {state.trades_this_hour}/{MAX_TRADES_PER_HOUR}h, {state.total_trades_today}/{MAX_TRADES_PER_DAY}d
├─ W/L: {state.winning_trades}W/{state.losing_trades}L ({(state.winning_trades/(state.winning_trades+state.losing_trades)*100) if (state.winning_trades+state.losing_trades) > 0 else 0:.1f}% WR)
├─ VIX: {state.estimated_vix:.1f}%
└─ Time: {now().strftime('%H:%M:%S')}
""".strip())
            
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
        error_str = str(e).lower()
        # Check if it's a network-related error
        if any(x in error_str for x in ['name resolution', 'connection', 'network', 'timeout', 'unreachable']):
            logger.error(f"🌐 Network error detected: {e}")
            return "RECONNECT"
        
        logger.error(f"Fatal error in main loop", e)
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
            'kill_switch_count': 1 if state.state == "KILL_SWITCH" else 0
        })
        
        # Cleanup
        broker.logout()
        
        logger.info("")
        logger.info("╔══════════════════════════════════════════════════════════════════════════════╗")
        logger.info("║                           📊 FINAL SESSION STATS 📊                        ║")
        logger.info("║                           ₹30K CONFIGURATION                              ║")
        logger.info("╚══════════════════════════════════════════════════════════════════════════════╝")
        logger.info(f"💰 DAILY P&L: ₹{state.daily_pnl_inr:+.2f} ({state.daily_pnl_pct:+.2f}%)")
        logger.info(f"📊 TRADES: {state.total_trades_today} total | {state.winning_trades}W/{state.losing_trades}L")
        logger.info(f"🎯 WIN RATE: {state.total_trades_today and (state.winning_trades/state.total_trades_today*100):.1f}%")
        logger.info(f"📉 CONSECUTIVE LOSSES: {state.consecutive_losses}")
        logger.info(f"⚙️ FINAL STATE: {state.state}")
        logger.info("=" * 78)
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
    temp_logger.info("=" * 60)
    temp_logger.info("🚀 PTQ SCALPING BOT - AUTO-RECONNECT ENABLED")
    temp_logger.info("=" * 60)
    temp_logger.info(f"Max reconnect attempts: {MAX_RECONNECT_ATTEMPTS}")
    temp_logger.info(f"Wait between reconnects: {RECONNECT_WAIT_SECONDS}s")
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
    temp_logger.info("=" * 60)
    temp_logger.info("🏁 BOT SESSION ENDED")
    temp_logger.info("=" * 60)


if __name__ == "__main__":
    run_with_auto_reconnect()
