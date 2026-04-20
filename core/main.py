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
    COOLDOWN_NORMAL_SEC, COOLDOWN_AFTER_SL_SEC,
    SL_POINTS_FIXED, TP_POINTS_FIXED, CE_QUANTITY, PE_QUANTITY
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
from core.risk.kill_switch import emergency_check, track_rejected_tick, reset_rejected_tick_counter, is_stale_data_kill_active, is_high_latency_paused
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
    Uses multiple DNS servers for fallback (v3.3).
    """
    dns_servers = [
        ("8.8.8.8", 53),       # Google DNS
        ("1.1.1.1", 53),       # Cloudflare DNS
        ("208.67.222.222", 53), # OpenDNS
    ]
    
    for dns_host, dns_port in dns_servers:
        try:
            socket.setdefaulttimeout(timeout)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((dns_host, dns_port))
            s.close()
            return True
        except (socket.error, socket.timeout, OSError):
            continue
    
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
    """Initialize Telegram, Database, RiskManager and Live Logs features"""
    
    # ============================================
    # CRITICAL FIX: Initialize RiskManager globally
    # ============================================
    try:
        from core.risk.risk_manager import RiskManager, set_risk_manager
        rm = RiskManager(CONFIG, logger)
        set_risk_manager(rm)
        logger.info("✓ RiskManager initialized (globally active)")
    except Exception as e:
        logger.warning(f"⚠ RiskManager init failed: {e} — risk checks may be skipped")
    
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
            'ce_qty': CE_QUANTITY,
            'pe_qty': PE_QUANTITY,
            'sl_points': SL_POINTS_FIXED,
            'tp_points': TP_POINTS_FIXED
        })
        logger.info("✓ Telegram dashboard initialized")


def close_current_trade(state, reason, logger, current_tick=None) -> bool:
    """
    Close the active trade and update accounting exactly once.
    Returns False when live exit was not confirmed, leaving current_trade intact.
    """
    if not state.current_trade:
        return True

    trade_direction = state.current_trade.get('direction', 'CE')
    result = broker.exit_position(
        state.current_trade, reason,
        state.daily_pnl_inr, TOTAL_CAPITAL, current_tick
    )

    if not result.get('exit_confirmed', True):
        logger.error("🚨 Exit was not confirmed. Blocking new entries until manual review.")
        state.state = "KILL_SWITCH"
        state.manual_intervention_required = True
        state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
        return False

    is_loss = result['pnl_inr'] < 0
    state.update_pnl(result['pnl_inr'], TOTAL_CAPITAL, is_loss, trade_direction)
    state.current_trade = None
    state.manual_intervention_required = False
    return True


def main():
    """Main trading loop - SMART SCALP v3.4"""
    global recent_ticks
    
    # ════════════════════════════════════════════════════════════════════════
    # PRE-MARKET STANDBY MODE
    # If started before 09:10 AM, sleep until 09:10 then connect
    # This ensures fresh ScripMaster + WebSocket connection
    # ════════════════════════════════════════════════════════════════════════
    from datetime import timedelta
    current = datetime.now()
    pre_market_time = current.replace(hour=9, minute=10, second=0, microsecond=0)
    market_close_time = current.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # Check if we need to wait for next trading day
    if current > market_close_time:
        # Market closed - wait for next day
        next_day = current + timedelta(days=1)
        while next_day.weekday() >= 5:  # Skip weekends
            next_day += timedelta(days=1)
        pre_market_time = next_day.replace(hour=9, minute=10, second=0, microsecond=0)
    
    if current < pre_market_time:
        wait_seconds = (pre_market_time - current).total_seconds()
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)
        
        print()
        print("╔═══════════════════════════════════════════════════════════════╗")
        print("║            🌙 PRE-MARKET STANDBY MODE                         ║")
        print("╠═══════════════════════════════════════════════════════════════╣")
        print(f"║  Current Time: {current.strftime('%Y-%m-%d %H:%M:%S')}                        ║")
        print(f"║  Connect At:   {pre_market_time.strftime('%Y-%m-%d')} 09:10:00                        ║")
        print(f"║  Wait Time:    {hours}h {minutes}m                                       ║")
        print("╠═══════════════════════════════════════════════════════════════╣")
        print("║  Bot will sleep and wake up 5 minutes before market open.    ║")
        print("║  This ensures fresh ScripMaster + WebSocket connection.      ║")
        print("╚═══════════════════════════════════════════════════════════════╝")
        print()
        
        # Sleep with periodic status updates
        while datetime.now() < pre_market_time:
            remaining = (pre_market_time - datetime.now()).total_seconds()
            
            if remaining > 3600:
                # More than 1 hour - sleep 30 min, show status
                hours_left = int(remaining // 3600)
                mins_left = int((remaining % 3600) // 60)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\033[2m{ts}\033[0m  💤 Standby: {hours_left}h {mins_left}m until connect...")
                time.sleep(1800)  # 30 min sleep
            elif remaining > 300:
                # 5-60 min - sleep 5 min
                mins_left = int(remaining // 60)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\033[2m{ts}\033[0m  ⏳ Standby: {mins_left}m until connect...")
                time.sleep(300)  # 5 min sleep
            else:
                # Less than 5 min - sleep remaining
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\033[2m{ts}\033[0m  🔔 Waking up in {int(remaining)}s...")
                time.sleep(remaining)
                break
        
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\033[2m{ts}\033[0m  🌅 Pre-market wake up! Connecting to broker...")
        print()
    # ════════════════════════════════════════════════════════════════════════
    
    # Connect to broker (NOW with fresh connection)
    if not broker.connect():
        return
    
    logger = broker.logger
    state = trading_state
    
    # ════════════════════════════════════════════════════════════════════════
    # RESTORE PnL FROM TODAY'S TRADES (on bot restart)
    # ════════════════════════════════════════════════════════════════════════
    if state.restore_from_trades(TOTAL_CAPITAL):
        logger.info(f"📊 Restored: {state.total_trades_today} trades, PnL ₹{state.daily_pnl_inr:+,.0f}")
    
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
            STRATEGY_NAME, STRATEGY_VERSION,
            MIN_SCORE_TO_TRADE, MIN_CONFIDENCE
        )
        has_smart_scalp = True
    except ImportError:
        has_smart_scalp = False
        MIN_SCORE_TO_TRADE, MIN_CONFIDENCE = 4, 70
    
    logger.info("")
    logger.info("┌──────────────────────────────────────────────────────────────┐")
    logger.info("│           SMART SCALP v3.4  ·  ₹30K Configuration          │")
    logger.info("├──────────────────────────────────────────────────────────────┤")
    logger.info(f"│  Capital: ₹{TOTAL_CAPITAL:>6,}  │  CE: {CE_QUANTITY:>3} qty  │  PE: {PE_QUANTITY:>3} qty      │")
    logger.info(f"│  SL: {SL_POINTS_FIXED} pts      │  TP: {TP_POINTS_FIXED} pts    │  Score: {MIN_SCORE_TO_TRADE}+/{MIN_CONFIDENCE}%+   │")
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
            
            # ============================================
            # GLOBAL NETWORK CIRCUIT BREAKER (v3.3 - Exponential Backoff)
            # If tick is None = Internet/API down
            # Retry with backoff: 5s, 10s, 20s, 40s, 60s (max)
            # ============================================
            if tick is None:
                # Initialize circuit breaker state
                if not hasattr(state, '_network_sleep_count'):
                    state._network_sleep_count = 0
                    state._network_backoff = 5  # Start at 5 seconds
                
                state._network_sleep_count += 1
                
                # Log ONCE at start of outage
                if state._network_sleep_count == 1:
                    logger.warning("🛑 Network/API Down! Retrying with exponential backoff...")
                    state._network_backoff = 5  # Reset backoff
                    # Exit any open trade safely
                    if state.current_trade:
                        logger.warning("   ⚠ Exiting open trade due to network failure")
                        if close_current_trade(state, "Network down - emergency exit", logger):
                            state.state = "COOLDOWN"
                
                # Check internet with DNS fallback
                if state._network_sleep_count % 3 == 0:
                    if check_internet_connection():
                        logger.info(f"🌐 Internet OK but API down - retrying broker connection...")
                        state._network_backoff = 5  # Reset backoff on internet recovery
                
                # Log retry attempt
                logger.info(f"🔄 Network retry #{state._network_sleep_count} (backoff: {state._network_backoff}s)")
                
                # Sleep with exponential backoff (max 60 seconds)
                time.sleep(state._network_backoff)
                state._network_backoff = min(60, state._network_backoff * 2)
                
                # After 10 retries (~10 min with backoff), log warning
                if state._network_sleep_count >= 10:
                    logger.warning(f"🔄 Still no network after {state._network_sleep_count} retries. Continuing...")
                    state._network_sleep_count = 0
                    state._network_backoff = 5
                
                continue  # Skip rest of loop, retry get_tick()
            
            # Network is back - reset counter and log recovery
            if hasattr(state, '_network_sleep_count') and state._network_sleep_count > 0:
                sleep_time = state._network_sleep_count * 60
                logger.info(f"✅ Network restored after {sleep_time}s - resuming trading")
                state._network_sleep_count = 0
            
            # BUG FIX #13: Count ALL ticks received (before validation)
            # This ensures summary.json shows actual tick count, not just valid ones
            state.total_ticks_received = getattr(state, 'total_ticks_received', 0) + 1
            
            # Data validation
            is_valid, validation_msg = is_data_valid(tick)
            if not is_valid:
                state.invalid_ticks = getattr(state, 'invalid_ticks', 0) + 1
                if state.loop_count % 100 == 0:
                    logger.tick_rejected(validation_msg, tick)
                
                # FIX: Track consecutive rejected ticks — stale data kill switch
                stale_kill, stale_reason, stale_details = track_rejected_tick()
                if stale_kill:
                    logger.warning(f"🚨 {stale_reason}: {stale_details['consecutive_rejected']} consecutive rejected ticks")
                    logger.warning("   → Data feed is broken. BLOCKING new entries until valid data returns.")
                    if state.current_trade:
                        close_current_trade(state, f"Kill switch: {stale_reason}", logger, tick)
                    if state.state != "KILL_SWITCH":
                        state.state = "KILL_SWITCH"
                        state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
                        logger.kill_switch(stale_reason, stale_details)
                
                time.sleep(0.1)
                continue
            
            # Valid tick received — check if we can clear stale data kill switch
            can_clear_stale, clear_info = reset_rejected_tick_counter()
            
            # If stale data kill is still in effect (cooldown or need more valid ticks), stay in kill state
            if getattr(state, 'manual_intervention_required', False):
                if state.loop_count % 20 == 0:
                    logger.error("🚨 Manual intervention required - bot will not resume entries")
                time.sleep(1)
                continue

            if not can_clear_stale and state.state == "KILL_SWITCH" and is_stale_data_kill_active():
                reason = clear_info.get('reason', 'unknown')
                if reason == 'cooldown':
                    remaining = clear_info.get('remaining_sec', 0)
                    if state.loop_count % 20 == 0:  # Log every ~10 seconds
                        logger.info(f"⏳ Stale data cooldown: {remaining:.0f}s remaining ({clear_info.get('valid_ticks', 0)} valid ticks)")
                elif reason == 'need_more_valid':
                    valid = clear_info.get('valid_ticks', 0)
                    required = clear_info.get('required', 10)
                    if state.loop_count % 10 == 0:  # Log every ~5 seconds
                        logger.info(f"⏳ Stale data recovery: {valid}/{required} consecutive valid ticks")
                time.sleep(0.5)
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
                    close_current_trade(state, "Kill switch: " + kill_reason, logger, tick)
                
                # Check if this is a recoverable kill switch
                is_spread_cooldown = kill_reason in ("Wide spread KILL", "Spread cooldown")
                is_latency_pause = kill_reason in ("High latency PAUSE", "Latency recovery")
                is_recoverable = is_spread_cooldown or is_latency_pause or kill_details.get('recoverable', False)
                
                if is_latency_pause:
                    # Latency pause - recoverable when latency improves
                    if state.state != "KILL_SWITCH":
                        state.state = "KILL_SWITCH"
                        state.kill_switch_count = getattr(state, 'kill_switch_count', 0) + 1
                        logger.kill_switch(kill_reason, kill_details)
                        logger.warning(f"⚠ HIGH LATENCY PAUSE - {kill_details.get('latency_ms', 0):.0f}ms - Waiting for network to stabilize")
                    elif kill_reason == "Latency recovery":
                        # Still recovering - show progress
                        if state.loop_count % 10 == 0:
                            logger.info(f"⏳ Latency recovery: {kill_details.get('low_latency_count', 0)}/{kill_details.get('need', 5)} low latency ticks")
                elif is_spread_cooldown:
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
                if clear_info.get('reason') == 'recovered':
                    logger.info(f"✅ Stale data recovered - {clear_info.get('valid_ticks', 10)} consecutive valid ticks - resuming trading")
                else:
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
                    broker, TOTAL_CAPITAL, logger, recent_ticks
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
            close_current_trade(state, "Manual shutdown", logger)
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
            close_current_trade(state, "Error shutdown", logger)
        return "ERROR"
    
    finally:
        # Daily summary
        total_ticks = getattr(state, 'total_ticks_received', 0)
        valid_ticks = getattr(state, 'ticks_processed', 0)
        invalid_ticks = getattr(state, 'invalid_ticks', 0)
        
        logger.daily_summary({
            'total_trades': state.total_trades_today,
            'winning_trades': state.winning_trades,
            'losing_trades': state.losing_trades,
            'total_pnl': state.daily_pnl_inr,
            'max_drawdown': min(0, state.daily_pnl_inr),
            'kill_switch_count': getattr(state, 'kill_switch_count', 0),
            'ticks_received': total_ticks,
            'ticks_valid': valid_ticks,
            'ticks_invalid': invalid_ticks
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
