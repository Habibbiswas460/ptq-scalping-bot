"""
PTQ Scalping Bot - Advanced Risk Manager
Comprehensive risk management with all features:
- Trailing Stop Loss (ATR-based)
- Dynamic Position Sizing
- Drawdown Protection
- VIX Filter
- Gap Protection
- Recovery Mode
- Equity Curve Trading
- Win/Loss Streak Management
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, List


class RiskManager:
    """Advanced Risk Management System"""
    
    def __init__(self, config: Dict, logger=None):
        self.config = config
        self.logger = logger
        
        # State tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.total_pnl = 0.0
        self.peak_equity = config['capital']['total_capital']
        self.current_equity = config['capital']['total_capital']
        
        # Streak tracking
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.trades_today = []
        self.trades_this_week = []
        
        # Mode tracking
        self.recovery_mode = False
        self.recovery_start_date = None
        
        # VIX cache
        self.vix_value = None
        self.vix_last_fetch = None
        
        # ATR cache
        self.atr_value = None
        self.atr_last_fetch = None
        
        # Equity curve
        self.equity_history = []
        
        # Gap tracking
        self.previous_close = None
        self.gap_detected = False
        self.gap_wait_until = None
        
        # Load state if exists
        self._load_state()
    
    def _log(self, level: str, msg: str):
        """Log message"""
        if self.logger:
            getattr(self.logger, level)(msg)
        else:
            print(f"[{level.upper()}] {msg}")
    
    def _load_state(self):
        """Load persisted state"""
        state_file = "logs/risk_state.json"
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    self.weekly_pnl = state.get('weekly_pnl', 0)
                    self.total_pnl = state.get('total_pnl', 0)
                    self.peak_equity = state.get('peak_equity', self.current_equity)
                    self.recovery_mode = state.get('recovery_mode', False)
                    self.equity_history = state.get('equity_history', [])[-30:]
            except Exception as e:
                self._log('warning', f"Could not load risk state: {e}")
    
    def _save_state(self):
        """Persist state"""
        state_file = "logs/risk_state.json"
        try:
            os.makedirs("logs", exist_ok=True)
            state = {
                'weekly_pnl': self.weekly_pnl,
                'total_pnl': self.total_pnl,
                'peak_equity': self.peak_equity,
                'recovery_mode': self.recovery_mode,
                'equity_history': self.equity_history[-30:],
                'last_updated': datetime.now().isoformat()
            }
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self._log('warning', f"Could not save risk state: {e}")

    # ==================== VIX FILTER ====================
    
    def set_broker_client(self, broker_client):
        """Set broker client for fetching VIX from Angel One"""
        self._broker_client = broker_client
    
    def get_vix(self) -> float:
        """Get India VIX value
        
        Note: Angel One API doesn't support India VIX LTP fetch.
        Using estimation from helpers module instead.
        """
        # Use VIX estimation from helpers (based on price volatility)
        from utils.helpers import fetch_real_vix
        estimated_vix = fetch_real_vix()
        
        if estimated_vix and 5 <= estimated_vix <= 100:
            self.vix_value = estimated_vix
            self.vix_last_fetch = datetime.now()
        
        return self.vix_value or 15.0
    
    def check_vix_filter(self) -> Tuple[bool, float, str]:
        """Check VIX and return trading decision"""
        if not self.config.get('volatility_filter', {}).get('vix_enabled', False):
            return True, 1.0, ""
        
        vix = self.get_vix()
        vf = self.config['volatility_filter']
        
        if vix <= vf['vix_normal_max']:
            return True, 1.0, f"VIX normal ({vix:.1f})"
        elif vix <= vf['vix_caution_max']:
            mult = 1.0 - (vf['size_reduce_pct_caution'] / 100)
            return True, mult, f"VIX caution ({vix:.1f}), size {mult*100:.0f}%"
        elif vix <= vf['vix_high_max']:
            mult = 1.0 - (vf['size_reduce_pct_high'] / 100)
            return True, mult, f"VIX high ({vix:.1f}), size {mult*100:.0f}%"
        else:
            if vf['vix_extreme_action'] == 'stop':
                return False, 0.0, f"VIX extreme ({vix:.1f}), NO TRADE"
            else:
                return True, 0.25, f"VIX extreme ({vix:.1f}), size 25%"

    # ==================== ATR & POSITION SIZING ====================
    
    def get_atr(self, lookback: int = 14) -> float:
        """
        Get NIFTY ATR (Average True Range)
        Uses cached value or default since live ATR calculation requires historical data.
        In live trading, ATR is estimated from recent price volatility.
        """
        if self.atr_last_fetch and (datetime.now() - self.atr_last_fetch).seconds < 3600:
            return self.atr_value or 150.0
        
        # Default ATR for NIFTY (~0.6% of spot)
        # Typical NIFTY ATR ranges from 100-300 points
        self.atr_value = 150.0
        self.atr_last_fetch = datetime.now()
        
        return self.atr_value
    
    def calculate_position_size(self, entry_price: float = 100) -> int:
        """
        Calculate position size (lots) based on capital
        
        Logic:
        - 1 lot = 65 qty (NIFTY)
        - Margin per lot ~ ₹15,000
        - Capital: ₹30,000 = max 2 lots (with buffer)
        
        Methods:
        1. capital_based: Based on available margin
        2. risk_based: Based on risk per trade / SL
        3. atr_based: Based on ATR volatility
        """
        rm = self.config['risk_management']
        capital_cfg = self.config['capital']
        trading_cfg = self.config['trading']
        
        if not rm.get('position_sizing_enabled', False):
            return trading_cfg.get('quantity', 1)
        
        lot_size = trading_cfg.get('lot_size', 65)  # 65 qty = 1 lot
        total_capital = capital_cfg['total_capital'] + self.total_pnl  # Current equity
        margin_per_lot = capital_cfg.get('margin_per_lot', 15000)
        
        method = rm.get('position_sizing_method', 'capital_based')
        
        if method == 'capital_based':
            # Capital-based: How many lots can we afford?
            utilization_pct = rm.get('capital_utilization_pct', 80) / 100
            available_capital = total_capital * utilization_pct
            
            # Calculate max lots based on margin
            max_affordable_lots = int(available_capital / margin_per_lot)
            
            # Also check option premium cost
            option_cost_per_lot = entry_price * lot_size
            max_lots_by_premium = int(available_capital / option_cost_per_lot) if option_cost_per_lot > 0 else 1
            
            # Take the minimum
            lots = min(max_affordable_lots, max_lots_by_premium)
            
            self._log('debug', f"Capital sizing: ₹{total_capital:,.0f} * {utilization_pct*100:.0f}% = ₹{available_capital:,.0f}")
            self._log('debug', f"Margin lots: {max_affordable_lots}, Premium lots: {max_lots_by_premium}")
        
        elif method == 'risk_based':
            # Risk-based: How many lots with given SL?
            risk_amount = capital_cfg['risk_per_trade_amount']
            sl_amount = rm.get('stop_loss_amount', 250)
            
            # Risk per lot = SL points * lot_size
            # But for options, SL is in option price, not points
            risk_per_lot = sl_amount  # Already in rupees
            
            lots = int(risk_amount / risk_per_lot) if risk_per_lot > 0 else 1
            
            self._log('debug', f"Risk sizing: ₹{risk_amount} / ₹{risk_per_lot} = {lots} lots")
        
        elif method == 'atr':
            # ATR-based: Volatility adjusted
            atr = self.get_atr()
            atr_multiplier = rm.get('atr_risk_multiplier', 2.0)
            risk_amount = capital_cfg['risk_per_trade_amount']
            
            # Higher ATR = lower position size
            risk_per_lot = (atr * atr_multiplier / 100) * lot_size  # Convert ATR to option movement
            lots = int(risk_amount / risk_per_lot) if risk_per_lot > 0 else 1
            
            self._log('debug', f"ATR sizing: ATR={atr:.0f}, Risk/lot=₹{risk_per_lot:.0f}, Lots={lots}")
        
        else:
            lots = trading_cfg.get('quantity', 1)
        
        # Apply min/max limits
        min_lots = rm.get('min_lots', 1)
        max_lots = rm.get('max_lots', 5)
        
        lots = max(min_lots, lots)
        lots = min(max_lots, lots)
        
        # Final safety check: never risk more than available
        final_cost = lots * entry_price * lot_size
        if final_cost > total_capital * 0.9:  # 90% safety
            lots = max(1, int((total_capital * 0.9) / (entry_price * lot_size)))
        
        self._log('info', f"📊 Position Size: {lots} lot(s) = {lots * lot_size} qty")
        
        return lots
    
    def get_quantity(self, lots: int = None) -> int:
        """Convert lots to quantity"""
        lot_size = self.config['trading'].get('lot_size', 65)
        if lots is None:
            lots = self.calculate_position_size()
        return lots * lot_size
    
    def calculate_trailing_sl(self, entry_price: float, current_price: float, 
                              current_sl: float, highest_price: float) -> float:
        """Calculate trailing stop loss"""
        rm = self.config['risk_management']
        
        if not rm.get('trailing_sl_enabled', False):
            return current_sl
        
        profit = current_price - entry_price
        activation = rm.get('trailing_activation_amount', 50)
        
        if profit < activation:
            return current_sl
        
        atr = self.get_atr()
        atr_multiplier = rm.get('trailing_atr_multiplier', 1.5)
        
        new_sl = highest_price - (atr * atr_multiplier / 100)
        
        lock_pct = rm.get('trailing_lock_pct', 40) / 100
        min_locked_profit = profit * lock_pct
        min_sl = entry_price + min_locked_profit
        
        new_sl = max(new_sl, min_sl)
        
        if new_sl > current_sl:
            self._log('info', f"📈 Trailing SL: ₹{current_sl:.2f} → ₹{new_sl:.2f}")
            return new_sl
        
        return current_sl

    # ==================== GAP PROTECTION ====================
    
    def set_previous_close(self, close_price: float):
        """Set previous day's close for gap detection"""
        self.previous_close = close_price
    
    def check_gap_protection(self, current_open: float) -> Tuple[bool, str]:
        """Check for gap up/down at market open"""
        gp = self.config.get('gap_protection', {})
        
        if not gp.get('enabled', False):
            return True, ""
        
        if self.gap_wait_until and datetime.now() < self.gap_wait_until:
            remaining = (self.gap_wait_until - datetime.now()).seconds // 60
            return False, f"Gap protection: wait {remaining} min"
        
        # If no previous close set, allow trading
        if self.previous_close is None:
            return True, ""
        
        if self.previous_close and current_open:
            gap_pct = ((current_open - self.previous_close) / self.previous_close) * 100
            
            if gap_pct >= gp['gap_up_threshold_pct']:
                self.gap_wait_until = datetime.now() + timedelta(minutes=gp['wait_after_gap_min'])
                return False, f"Gap UP {gap_pct:.2f}%, wait {gp['wait_after_gap_min']}min"
            elif gap_pct <= -gp['gap_down_threshold_pct']:
                self.gap_wait_until = datetime.now() + timedelta(minutes=gp['wait_after_gap_min'])
                return False, f"Gap DOWN {gap_pct:.2f}%, wait {gp['wait_after_gap_min']}min"
        
        return True, ""

    # ==================== DRAWDOWN PROTECTION ====================
    
    def check_drawdown(self) -> Tuple[bool, str]:
        """Check max drawdown limits"""
        capital_cfg = self.config['capital']
        
        self.current_equity = capital_cfg['total_capital'] + self.total_pnl
        
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        
        drawdown = self.peak_equity - self.current_equity
        drawdown_pct = (drawdown / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        
        max_dd_amount = capital_cfg.get('max_drawdown_amount', 3000)
        max_dd_pct = capital_cfg.get('max_drawdown_pct', 10.0)
        
        if drawdown >= max_dd_amount:
            return False, f"Max drawdown ₹{drawdown:.0f} hit (limit: ₹{max_dd_amount})"
        
        if drawdown_pct >= max_dd_pct:
            return False, f"Max drawdown {drawdown_pct:.1f}% hit (limit: {max_dd_pct}%)"
        
        return True, ""
    
    def check_weekly_loss(self) -> Tuple[bool, str]:
        """Check weekly loss limit"""
        max_weekly = self.config['capital'].get('max_weekly_loss_amount', 2500)
        
        if self.weekly_pnl <= -max_weekly:
            return False, f"Weekly loss limit ₹{abs(self.weekly_pnl):.0f} (max: ₹{max_weekly})"
        
        return True, ""

    # ==================== RECOVERY MODE ====================
    
    def check_recovery_mode(self) -> Tuple[bool, float, str]:
        """Check and manage recovery mode"""
        rm = self.config.get('recovery_mode', {})
        
        if not rm.get('enabled', False):
            return False, 1.0, ""
        
        capital = self.config['capital']['total_capital']
        loss_pct = (abs(self.total_pnl) / capital) * 100 if self.total_pnl < 0 else 0
        
        if not self.recovery_mode and loss_pct >= rm['trigger_loss_pct']:
            self.recovery_mode = True
            self.recovery_start_date = datetime.now()
            self._log('warning', f"⚠️ Entering RECOVERY MODE (loss: {loss_pct:.1f}%)")
        
        if self.recovery_mode:
            if loss_pct <= rm['recovery_threshold_pct']:
                if self.recovery_start_date:
                    days_in_recovery = (datetime.now() - self.recovery_start_date).days
                    if days_in_recovery >= rm['min_recovery_days']:
                        self.recovery_mode = False
                        self._log('info', "✅ Exiting RECOVERY MODE")
                        return False, 1.0, ""
            
            size_mult = 1.0 - (rm['size_reduction_pct'] / 100)
            return True, size_mult, f"RECOVERY MODE: size {size_mult*100:.0f}%"
        
        return False, 1.0, ""

    # ==================== EQUITY CURVE TRADING ====================
    
    def check_equity_curve(self) -> Tuple[bool, float, str]:
        """Equity curve trading - reduce size when below SMA"""
        ec = self.config.get('equity_curve_trading', {})
        
        if not ec.get('enabled', False):
            return True, 1.0, ""
        
        if len(self.equity_history) < ec['sma_period']:
            return True, 1.0, "Not enough equity history"
        
        sma = sum(self.equity_history[-ec['sma_period']:]) / ec['sma_period']
        
        if self.current_equity < sma:
            pct_below = ((sma - self.current_equity) / sma) * 100
            
            if pct_below >= ec['pause_if_below_pct']:
                return False, 0.0, f"Equity {pct_below:.1f}% below SMA, PAUSED"
            
            size_mult = 1.0 - (ec['size_reduce_pct'] / 100)
            return True, size_mult, f"Equity below SMA, size {size_mult*100:.0f}%"
        
        return True, 1.0, ""

    # ==================== WIN/LOSS STREAK ====================
    
    def check_streak_limits(self) -> Tuple[bool, str]:
        """Check consecutive win/loss limits"""
        rm = self.config['risk_management']
        
        if self.consecutive_losses >= rm.get('consecutive_loss_limit', 2):
            return False, f"Consecutive losses: {self.consecutive_losses}, PAUSE"
        
        if self.consecutive_wins >= rm.get('consecutive_win_limit', 5):
            return False, f"Win streak: {self.consecutive_wins}, PAUSE (overconfidence)"
        
        return True, ""
    
    def update_streak(self, is_winner: bool):
        """Update win/loss streak"""
        if is_winner:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

    # ==================== TIME-BASED SIZING ====================
    
    def get_time_based_multiplier(self) -> float:
        """Get position size multiplier based on time of day"""
        ef = self.config.get('entry_filters', {})
        
        if not ef.get('time_based_sizing_enabled', False):
            return 1.0
        
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        
        if hour == 9 and minute < 30:
            return ef.get('opening_15min_size_pct', 50) / 100
        
        if hour >= 15:
            return ef.get('closing_30min_size_pct', 75) / 100
        
        return 1.0

    # ==================== DAILY PROFIT LOCK ====================
    
    def check_profit_lock(self) -> Tuple[bool, float, str]:
        """If daily profit exceeds threshold, reduce size to lock gains"""
        capital_cfg = self.config['capital']
        threshold = capital_cfg.get('profit_lock_threshold', 1500)
        reduce_pct = capital_cfg.get('profit_lock_reduce_pct', 50)
        
        if self.daily_pnl >= threshold:
            mult = 1.0 - (reduce_pct / 100)
            return True, mult, f"Daily profit ₹{self.daily_pnl:.0f}, size {mult*100:.0f}%"
        
        return False, 1.0, ""

    # ==================== MASTER CHECK ====================
    
    def can_trade(self, spot_price: float = None) -> Tuple[bool, Dict]:
        """Master risk check - combines all filters"""
        details = {
            'can_trade': True,
            'size_multiplier': 1.0,
            'reasons': [],
            'warnings': []
        }
        
        # 1. Drawdown check
        can, reason = self.check_drawdown()
        if not can:
            details['can_trade'] = False
            details['reasons'].append(reason)
            return False, details
        
        # 2. Weekly loss check
        can, reason = self.check_weekly_loss()
        if not can:
            details['can_trade'] = False
            details['reasons'].append(reason)
            return False, details
        
        # 3. Streak limits
        can, reason = self.check_streak_limits()
        if not can:
            details['can_trade'] = False
            details['reasons'].append(reason)
            return False, details
        
        # 4. VIX filter
        can, mult, reason = self.check_vix_filter()
        if not can:
            details['can_trade'] = False
            details['reasons'].append(reason)
            return False, details
        if mult < 1.0:
            details['size_multiplier'] *= mult
            details['warnings'].append(reason)
        
        # 5. Gap protection
        if spot_price:
            can, reason = self.check_gap_protection(spot_price)
            if not can:
                details['can_trade'] = False
                details['reasons'].append(reason)
                return False, details
        
        # 6. Recovery mode
        is_recovery, mult, reason = self.check_recovery_mode()
        if mult < 1.0:
            details['size_multiplier'] *= mult
            details['warnings'].append(reason)
        
        # 7. Equity curve
        can, mult, reason = self.check_equity_curve()
        if not can:
            details['can_trade'] = False
            details['reasons'].append(reason)
            return False, details
        if mult < 1.0:
            details['size_multiplier'] *= mult
            details['warnings'].append(reason)
        
        # 8. Time-based sizing
        time_mult = self.get_time_based_multiplier()
        if time_mult < 1.0:
            details['size_multiplier'] *= time_mult
            details['warnings'].append(f"Time-based: {time_mult*100:.0f}%")
        
        # 9. Profit lock
        locked, mult, reason = self.check_profit_lock()
        if locked:
            details['size_multiplier'] *= mult
            details['warnings'].append(reason)
        
        return details['can_trade'], details
    
    def get_final_position_size(self, entry_price: float = 100, spot_price: float = None) -> int:
        """Get final position size after all adjustments"""
        base_size = self.calculate_position_size(entry_price)
        
        can_trade, details = self.can_trade(spot_price)
        
        if not can_trade:
            return 0
        
        final_size = int(base_size * details['size_multiplier'])
        final_size = max(self.config['risk_management'].get('min_position_size', 1), final_size)
        
        return final_size

    # ==================== TRADE RECORDING ====================
    
    def record_trade(self, trade: Dict):
        """Record a completed trade"""
        pnl = trade.get('pnl', 0)
        
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.total_pnl += pnl
        
        self.current_equity = self.config['capital']['total_capital'] + self.total_pnl
        
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        
        self.update_streak(pnl > 0)
        
        self.trades_today.append(trade)
        self.trades_this_week.append(trade)
        
        self._save_state()
        
        self._log('info', f"📊 Trade recorded: PnL ₹{pnl:+.2f} | Daily: ₹{self.daily_pnl:+.2f}")
    
    def end_of_day(self):
        """End of day processing"""
        self.equity_history.append(self.current_equity)
        self.daily_pnl = 0.0
        self.trades_today = []
        self.previous_close = None
        self.gap_wait_until = None
        self._save_state()
    
    def end_of_week(self):
        """End of week processing"""
        self.weekly_pnl = 0.0
        self.trades_this_week = []
        self._save_state()

    # ==================== STATUS ====================
    
    def get_status(self) -> Dict:
        """Get current risk status"""
        return {
            'daily_pnl': self.daily_pnl,
            'weekly_pnl': self.weekly_pnl,
            'total_pnl': self.total_pnl,
            'current_equity': self.current_equity,
            'peak_equity': self.peak_equity,
            'drawdown': self.peak_equity - self.current_equity,
            'drawdown_pct': ((self.peak_equity - self.current_equity) / self.peak_equity * 100) if self.peak_equity > 0 else 0,
            'consecutive_wins': self.consecutive_wins,
            'consecutive_losses': self.consecutive_losses,
            'recovery_mode': self.recovery_mode,
            'vix': self.vix_value,
            'atr': self.atr_value,
            'trades_today': len(self.trades_today),
            'trades_this_week': len(self.trades_this_week)
        }


# ==================== SINGLETON & LEGACY FUNCTIONS ====================

_risk_manager = None

def get_risk_manager(config: Dict = None, logger=None) -> RiskManager:
    """Get or create risk manager singleton"""
    global _risk_manager
    if _risk_manager is None and config:
        _risk_manager = RiskManager(config, logger)
    return _risk_manager


def check_daily_loss_limit(trades_today, CONFIG, logger, STATE, daily_loss_alerted):
    """Legacy compatibility function"""
    rm = get_risk_manager(CONFIG, logger)
    if rm:
        rm.trades_today = trades_today
        rm.daily_pnl = sum([t.get('pnl', 0) for t in trades_today])
    
    daily_pnl = sum([t['pnl'] for t in trades_today])
    max_loss = CONFIG['capital']['max_daily_loss_amount']
    alert_threshold = CONFIG['capital']['daily_loss_alert_threshold']
    
    if daily_pnl <= -max_loss:
        logger.error(f"🚑 DAILY LOSS LIMIT HIT! PnL: ₹{daily_pnl:.2f}")
        STATE = "KILL_SWITCH"
        return False, STATE, daily_loss_alerted
    
    if daily_pnl <= -alert_threshold and not daily_loss_alerted:
        logger.warning(f"⚠️ Daily loss alert! PnL: ₹{daily_pnl:.2f}")
        daily_loss_alerted = True
    
    return True, STATE, daily_loss_alerted


def calculate_trade_pnl(trade, tick, CONFIG):
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

