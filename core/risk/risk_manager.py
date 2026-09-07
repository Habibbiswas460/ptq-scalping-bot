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

# Module-level lazy import cache for VIX function
_fetch_real_vix_fn = None


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
        self.streak_pause_until = None
        self.trades_today = []
        self.trades_this_week = []
        
        # Mode tracking
        self.recovery_mode = False
        self.recovery_start_date = None
        
        # VIX cache
        self.vix_value = None
        self.vix_last_fetch = None
        
        # Equity curve
        self.equity_history = []
        
        # Gap tracking
        self.previous_close = None
        self.gap_detected = False
        self.gap_wait_until = None

        # Load state if exists
        self._last_active_date = None
        self._load_state()

        # The bot restarts fresh each trading day, so a new week's first
        # session is the only reliable point to reset weekly PnL — detect it
        # by comparing the persisted last-active date's ISO week to today's.
        today = datetime.now().date()
        if self._last_active_date and self._last_active_date.isocalendar()[:2] != today.isocalendar()[:2]:
            self._log('info', f"📅 New week detected (last active {self._last_active_date}) — resetting weekly PnL")
            self.end_of_week()

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
                    last_updated = state.get('last_updated')
                    if last_updated:
                        self._last_active_date = datetime.fromisoformat(last_updated).date()

                    # daily_pnl is what MAX_DAILY_LOSS_AMOUNT and the kill switch are
                    # measured against, and it used to be neither saved nor loaded — so
                    # every process restart handed the bot a fresh full-size daily loss
                    # budget. In paper trading that is only untidy; with real money a bot
                    # that had lost most of its ceiling, died and came back would be
                    # allowed to lose it again. Restored only when the saved date is
                    # today, so a normal overnight start still begins at zero.
                    saved_day = state.get('daily_date')
                    if saved_day == datetime.now().date().isoformat():
                        self.daily_pnl = state.get('daily_pnl', 0.0)
                        if self.daily_pnl:
                            self._log('info',
                                      f"↩ Restored today's P&L from a previous run: "
                                      f"Rs{self.daily_pnl:+.2f} (daily loss ceiling continues "
                                      f"from here, it does not restart)")
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
                'daily_pnl': self.daily_pnl,
                'daily_date': datetime.now().date().isoformat(),
                'last_updated': datetime.now().isoformat()
            }
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self._log('warning', f"Could not save risk state: {e}")

    # ==================== VIX FILTER ====================

    def get_vix(self) -> float:
        """Get India VIX value
        
        Uses real India VIX when available via helpers API path,
        otherwise falls back to cached/estimated value.
        """
        global _fetch_real_vix_fn
        
        # Lazy import with caching (avoids import on every call)
        if _fetch_real_vix_fn is None:
            from utils.helpers import fetch_real_vix
            _fetch_real_vix_fn = fetch_real_vix
        
        estimated_vix = _fetch_real_vix_fn()
        
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
        """Check consecutive win/loss limits.

        Once a streak limit is hit, entries are paused for a fixed cooldown
        (mirrors state_machine.check_trade_limits()'s pattern) rather than
        indefinitely — resetting a streak previously required a win/loss,
        which could never happen while blocked from trading at all.
        """
        rm = self.config['risk_management']
        current = datetime.now()

        if self.streak_pause_until is not None:
            if current < self.streak_pause_until:
                remaining_min = int((self.streak_pause_until - current).total_seconds() // 60) + 1
                return False, f"Streak pause active, {remaining_min}min remaining"
            self._log('info', "✅ Streak pause ended. Resetting win/loss streak.")
            self.streak_pause_until = None
            self.consecutive_losses = 0
            self.consecutive_wins = 0

        pause_sec = rm.get('pause_after_consecutive_loss_sec', 900)

        if self.consecutive_losses >= rm.get('consecutive_loss_limit', 2):
            self.streak_pause_until = current + timedelta(seconds=pause_sec)
            return False, f"Consecutive losses: {self.consecutive_losses}, PAUSE for {pause_sec // 60}min"

        if self.consecutive_wins >= rm.get('consecutive_win_limit', 5):
            self.streak_pause_until = current + timedelta(seconds=pause_sec)
            return False, f"Win streak: {self.consecutive_wins}, PAUSE for {pause_sec // 60}min (overconfidence)"

        return True, ""
    
    def update_streak(self, pnl: float):
        """Update win/loss streak. A breakeven trade (pnl == 0) is neutral -
        it neither extends nor resets either streak.

        The pause starts HERE, when the streak actually happens, not when
        check_streak_limits() first gets to look at it. Those are not the same
        instant: after a streak the state machine goes into its own
        COOLDOWN_AFTER_CONSECUTIVE_LOSS, and while it is in COOLDOWN it never
        reaches check_trade_limits() at all -- so the pause clock used to start
        only once that cooldown had already expired, and the two ran back to
        back instead of together.

        Measured on 2026-09-07: two losses closed at 10:19:44, the state machine
        held COOLDOWN until 10:34:44, and the streak pause then set itself to
        10:49:44. A configured 15-minute pause cost 30 minutes of session, and
        nothing logged it, because state_idle()'s limit check returns "IDLE"
        silently. findings.md 2.9 removed the state machine's duplicate pause
        clock; the duplication survived through the cooldown *duration* instead.
        """
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

        rm = self.config['risk_management']
        pause_sec = rm.get('pause_after_consecutive_loss_sec', 900)
        hit_losses = self.consecutive_losses >= rm.get('consecutive_loss_limit', 2)
        hit_wins = self.consecutive_wins >= rm.get('consecutive_win_limit', 5)
        if (hit_losses or hit_wins) and self.streak_pause_until is None:
            self.streak_pause_until = datetime.now() + timedelta(seconds=pause_sec)
            self._log('info',
                      f"⏸ Streak pause armed for {pause_sec // 60}min "
                      f"(losses={self.consecutive_losses}, wins={self.consecutive_wins})")

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
            'legacy_size_multiplier': 1.0,
            'risk_budget': {},
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

        details['legacy_size_multiplier'] = details['size_multiplier']
        details['risk_budget'] = self.get_risk_budget()
        details['risk_budget']['legacy_size_multiplier'] = round(details['size_multiplier'], 4)
        details['risk_budget']['sizing_context'] = list(details['warnings'])
        
        return details['can_trade'], details

    def get_risk_budget(self) -> Dict:
        """Build a risk-budget payload for the position size engine."""
        capital_cfg = self.config['capital']
        trading_cfg = self.config['trading']
        rm_cfg = self.config.get('risk_management', {})
        recovery_cfg = self.config.get('recovery_mode', {})

        current_equity = capital_cfg['total_capital'] + self.total_pnl
        capital_utilization_pct = rm_cfg.get('capital_utilization_pct', 80) / 100
        available_capital = max(0.0, current_equity * capital_utilization_pct)

        per_trade_risk_amount = float(capital_cfg.get('risk_per_trade_amount', 0))
        daily_risk_budget_amount = float(capital_cfg.get('max_daily_loss_amount', per_trade_risk_amount))
        max_daily_loss_amount = float(capital_cfg.get('max_daily_loss_amount', 0))
        consumed_daily_loss = max(0.0, -float(self.daily_pnl))
        remaining_daily_loss_capacity = max(0.0, max_daily_loss_amount - consumed_daily_loss) if max_daily_loss_amount > 0 else daily_risk_budget_amount
        remaining_risk_amount = max(0.0, min(per_trade_risk_amount, remaining_daily_loss_capacity, available_capital))

        loss_utilization = (consumed_daily_loss / max_daily_loss_amount) if max_daily_loss_amount > 0 else 0.0
        recovery_severity = (recovery_cfg.get('size_reduction_pct', 50) / 100) if self.recovery_mode else 0.0

        return {
            'capital': round(current_equity, 2),
            'available_capital': round(available_capital, 2),
            'per_trade_risk_amount': round(per_trade_risk_amount, 2),
            'daily_risk_budget_amount': round(daily_risk_budget_amount, 2),
            'daily_risk_budget_pct': round((daily_risk_budget_amount / current_equity), 6) if current_equity > 0 else 0.0,
            'remaining_risk_amount': round(remaining_risk_amount, 2),
            'remaining_risk_pct': round((remaining_risk_amount / current_equity), 6) if current_equity > 0 else 0.0,
            'daily_loss_state': {
                'loss_utilization': round(min(1.0, max(0.0, loss_utilization)), 4)
            },
            'recovery_mode': {
                'active': bool(self.recovery_mode),
                'severity': round(min(1.0, max(0.0, recovery_severity)), 4)
            },
            'lot_size': int(trading_cfg.get('lot_size', 1)),
        }
    
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
        
        self.update_streak(pnl)
        
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


# ==================== SINGLETON & LEGACY FUNCTIONS ====================

_risk_manager = None

def set_risk_manager(rm: RiskManager):
    """Set the global risk manager instance (call after initialization)"""
    global _risk_manager
    _risk_manager = rm
    return _risk_manager


def get_risk_manager(config: Dict = None, logger=None) -> RiskManager:
    """Get or create risk manager singleton"""
    global _risk_manager
    if _risk_manager is None and config:
        _risk_manager = RiskManager(config, logger)
    return _risk_manager


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

