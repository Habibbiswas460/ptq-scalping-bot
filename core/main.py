"""
PTQ Scalping Bot - Main Entry Point
₹30,000 Configuration
"""

import time
from datetime import datetime

# Import configuration
from config.constants import (
    CONFIG, TOTAL_CAPITAL, RISK_PER_TRADE, KILL_SWITCH_LOSS,
    MAX_DAILY_LOSS_AMOUNT, MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
    STOP_LOSS_AMOUNT, PROFIT_TARGET_1, PROFIT_TARGET_2,
    COOLDOWN_NORMAL_SEC, COOLDOWN_AFTER_SL_SEC
)

# Import core modules
from core.broker import broker
from core.validators import is_data_valid, detect_day_type
from core.entry_engine import entry_signal, MAX_RECENT_TICKS
from core.exit_engine import check_exit_conditions
from core.state_machine import (
    trading_state, state_idle, state_entry_ready, 
    state_in_trade, state_cooldown
)
from core.kill_switch import emergency_check
from core.greeks_calc import calculate_greeks, init_greeks_fetcher
from utils.helpers import now, market_open, estimate_vix_from_ticks


# Recent ticks for analysis
recent_ticks = []


def main():
    """Main trading loop - ₹30,000 CONFIG"""
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
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"🚀 PTQ SCALPING BOT - ₹30K CONFIG")
    logger.info("=" * 60)
    logger.info(f"💰 Capital: ₹{TOTAL_CAPITAL:,} | Risk/Trade: ₹{RISK_PER_TRADE}")
    logger.info(f"🛑 Kill Switch: ₹{KILL_SWITCH_LOSS} | Max Loss: ₹{MAX_DAILY_LOSS_AMOUNT}")
    logger.info(f"📊 Max Trades: {MAX_TRADES_PER_HOUR}/hr, {MAX_TRADES_PER_DAY}/day")
    logger.info(f"💸 SL: ₹{STOP_LOSS_AMOUNT} | TP1: ₹{PROFIT_TARGET_1} | TP2: ₹{PROFIT_TARGET_2}")
    logger.info(f"⏱ Cooldown: {COOLDOWN_NORMAL_SEC}s / {COOLDOWN_AFTER_SL_SEC}s (after SL)")
    logger.info(f"📅 Day Type: {state.day_type}")
    logger.info("-" * 60)
    
    state.last_hour_reset = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    try:
        logger.info(f"🔄 Entering main trading loop...")
        
        while market_open():
            state.loop_count += 1
            
            # Heartbeat
            if state.loop_count % 100 == 0:
                logger.info(f"💓 Loop {state.loop_count} | State: {state.state} | PnL: ₹{state.daily_pnl_inr:+.2f}")
            
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
                
                state.state = "KILL_SWITCH"
                logger.kill_switch(kill_reason, kill_details)
                logger.error(f"🛑 KILL SWITCH - {kill_reason}")
                break
            
            # Calculate Greeks
            greeks = calculate_greeks(tick, broker.spot_price, broker.current_strike)
            
            # Detect day type
            state.day_type = detect_day_type(greeks, greeks['tte'])
            
            # Update VIX
            state.estimated_vix = estimate_vix_from_ticks(recent_ticks, state.estimated_vix)
            
            # State machine execution
            if state.state == "IDLE":
                def entry_func(t):
                    return entry_signal(t, recent_ticks, state.day_type)
                state.state = state_idle(tick, greeks, state, entry_func, logger)
            
            elif state.state == "ENTRY_READY":
                state.state = state_entry_ready(tick, greeks, state, broker, logger)
            
            elif state.state == "IN_TRADE":
                state.state = state_in_trade(
                    tick, greeks, state, check_exit_conditions, 
                    broker, TOTAL_CAPITAL, logger
                )
            
            elif state.state == "COOLDOWN":
                state.state = state_cooldown(state, logger)
            
            # Status update
            if state.loop_count % 200 == 0:
                logger.info(
                    f"[{now().strftime('%H:%M:%S')}] {state.state} | {state.day_type} | "
                    f"PnL: ₹{state.daily_pnl_inr:+.2f} ({state.daily_pnl_pct:+.2f}%) | "
                    f"Trades: {state.trades_this_hour}/{MAX_TRADES_PER_HOUR}h, {state.total_trades_today}/{MAX_TRADES_PER_DAY}d | "
                    f"W/L: {state.winning_trades}/{state.losing_trades}"
                )
            
            time.sleep(0.01)  # 10ms cycle
        
        logger.info("📉 Market closed")
        
    except KeyboardInterrupt:
        logger.warning("⚠ Manual shutdown")
        if state.current_trade:
            broker.exit_position(
                state.current_trade, "Manual shutdown",
                state.daily_pnl_inr, TOTAL_CAPITAL
            )
    
    except Exception as e:
        logger.error(f"Fatal error in main loop", e)
        if state.current_trade:
            broker.exit_position(
                state.current_trade, "Error shutdown",
                state.daily_pnl_inr, TOTAL_CAPITAL
            )
    
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
        logger.info("=" * 60)
        logger.info("📊 FINAL STATS - ₹30K CONFIG")
        logger.info("=" * 60)
        logger.info(f"💰 Daily PnL: ₹{state.daily_pnl_inr:+.2f} ({state.daily_pnl_pct:+.2f}%)")
        logger.info(f"📈 Trades: {state.total_trades_today} | W/L: {state.winning_trades}/{state.losing_trades}")
        logger.info(f"📉 Consecutive Losses: {state.consecutive_losses}")
        logger.info(f"⚙️  Final State: {state.state}")
        logger.info("=" * 60)
        logger.info("✓ Bot shutdown complete")


if __name__ == "__main__":
    main()
