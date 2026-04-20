"""
PTQ Scalping Bot - Monitoring Metrics v3.4
==========================================
Real-time monitoring and health metrics for algo trading.

Tracks:
- Bot health (latency, tick delay, WebSocket status, API errors)
- Trade metrics (win rate, profit factor, max drawdown)
- System performance (CPU, memory)
"""

import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import deque
import threading


class BotMonitor:
    """
    Real-time monitoring for PTQ Scalping Bot.
    Thread-safe singleton pattern.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Health metrics
        self._tick_latencies: deque = deque(maxlen=100)  # Last 100 tick latencies
        self._api_latencies: deque = deque(maxlen=100)
        self._last_tick_time: float = 0
        self._tick_gaps: deque = deque(maxlen=100)
        self._ws_status: Dict = {
            'connected': False,
            'reconnect_count': 0,
            'last_reconnect': None,
            'uptime_pct': 100.0
        }
        self._api_errors: int = 0
        self._api_calls: int = 0
        
        # Trade metrics
        self._trades: List[Dict] = []
        self._daily_pnl: float = 0.0
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0
        self._win_count: int = 0
        self._loss_count: int = 0
        self._total_profit: float = 0.0
        self._total_loss: float = 0.0
        
        # Session tracking
        self._session_start: datetime = datetime.now()
        self._ticks_received: int = 0
        self._signals_generated: int = 0
        self._trades_executed: int = 0
        
        # Alerts
        self._alerts: deque = deque(maxlen=50)
        
        self._initialized = True
    
    # =========================================================================
    # HEALTH METRICS
    # =========================================================================
    
    def record_tick(self, tick: Dict):
        """Record tick data for latency monitoring"""
        now = time.time()
        
        # Calculate tick latency
        tick_timestamp = tick.get('timestamp', 0)
        if tick_timestamp > 0:
            if tick_timestamp > 1e12:  # Milliseconds
                tick_timestamp = tick_timestamp / 1000
            latency_ms = (now - tick_timestamp) * 1000
            self._tick_latencies.append(latency_ms)
        
        # Calculate tick gap
        if self._last_tick_time > 0:
            gap = now - self._last_tick_time
            self._tick_gaps.append(gap)
        self._last_tick_time = now
        
        self._ticks_received += 1
    
    def record_api_call(self, latency_ms: float, success: bool = True):
        """Record API call for performance monitoring"""
        self._api_latencies.append(latency_ms)
        self._api_calls += 1
        if not success:
            self._api_errors += 1
    
    def update_ws_status(self, connected: bool, reconnect: bool = False):
        """Update WebSocket connection status"""
        self._ws_status['connected'] = connected
        if reconnect:
            self._ws_status['reconnect_count'] += 1
            self._ws_status['last_reconnect'] = datetime.now().isoformat()
    
    def get_health_metrics(self) -> Dict:
        """Get current health metrics"""
        avg_tick_latency = sum(self._tick_latencies) / len(self._tick_latencies) if self._tick_latencies else 0
        avg_api_latency = sum(self._api_latencies) / len(self._api_latencies) if self._api_latencies else 0
        avg_tick_gap = sum(self._tick_gaps) / len(self._tick_gaps) if self._tick_gaps else 0
        
        # Calculate uptime
        session_duration = (datetime.now() - self._session_start).total_seconds()
        ticks_per_sec = self._ticks_received / session_duration if session_duration > 0 else 0
        
        return {
            'tick_latency_avg_ms': round(avg_tick_latency, 2),
            'tick_latency_max_ms': round(max(self._tick_latencies) if self._tick_latencies else 0, 2),
            'tick_gap_avg_sec': round(avg_tick_gap, 3),
            'tick_gap_max_sec': round(max(self._tick_gaps) if self._tick_gaps else 0, 3),
            'api_latency_avg_ms': round(avg_api_latency, 2),
            'api_error_rate': round(self._api_errors / self._api_calls * 100 if self._api_calls > 0 else 0, 2),
            'websocket': self._ws_status.copy(),
            'ticks_per_sec': round(ticks_per_sec, 2),
            'session_duration_min': round(session_duration / 60, 1)
        }
    
    # =========================================================================
    # TRADE METRICS
    # =========================================================================
    
    def record_trade(self, trade: Dict):
        """Record completed trade for metrics"""
        self._trades.append(trade)
        self._trades_executed += 1
        
        pnl = trade.get('pnl', 0)
        self._daily_pnl += pnl
        
        # Update win/loss counts
        if pnl > 0:
            self._win_count += 1
            self._total_profit += pnl
        elif pnl < 0:
            self._loss_count += 1
            self._total_loss += abs(pnl)
        
        # Update peak equity and drawdown
        if self._daily_pnl > self._peak_equity:
            self._peak_equity = self._daily_pnl
        
        current_dd = self._peak_equity - self._daily_pnl
        if current_dd > self._max_drawdown:
            self._max_drawdown = current_dd
            # Alert on significant drawdown
            if current_dd > 500:  # ₹500 threshold
                self.add_alert('DRAWDOWN', f'Max drawdown reached ₹{current_dd:.0f}')
    
    def record_signal(self):
        """Record signal generation"""
        self._signals_generated += 1
    
    def get_trade_metrics(self) -> Dict:
        """Get current trade metrics"""
        total_trades = self._win_count + self._loss_count
        win_rate = (self._win_count / total_trades * 100) if total_trades > 0 else 0
        avg_win = self._total_profit / self._win_count if self._win_count > 0 else 0
        avg_loss = self._total_loss / self._loss_count if self._loss_count > 0 else 0
        profit_factor = self._total_profit / self._total_loss if self._total_loss > 0 else float('inf') if self._total_profit > 0 else 0
        expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss) if total_trades > 0 else 0
        
        return {
            'total_trades': total_trades,
            'win_rate_pct': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
            'daily_pnl': round(self._daily_pnl, 2),
            'max_drawdown': round(self._max_drawdown, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'expectancy': round(expectancy, 2),
            'signals_generated': self._signals_generated,
            'win_count': self._win_count,
            'loss_count': self._loss_count
        }
    
    # =========================================================================
    # ALERTS
    # =========================================================================
    
    def add_alert(self, alert_type: str, message: str):
        """Add monitoring alert"""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'type': alert_type,
            'message': message
        }
        self._alerts.append(alert)
    
    def get_alerts(self, limit: int = 10) -> List[Dict]:
        """Get recent alerts"""
        return list(self._alerts)[-limit:]
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    
    def get_full_status(self) -> Dict:
        """Get full monitoring status"""
        return {
            'timestamp': datetime.now().isoformat(),
            'health': self.get_health_metrics(),
            'trades': self.get_trade_metrics(),
            'alerts': self.get_alerts(5)
        }
    
    def save_status(self, filepath: str = 'logs/monitor_status.json'):
        """Save current status to file"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            status = self.get_full_status()
            with open(filepath, 'w') as f:
                json.dump(status, f, indent=2, default=str)
        except Exception as e:
            pass  # Silent fail for non-critical operation
    
    def reset_daily(self):
        """Reset daily metrics (call at market close)"""
        self._daily_pnl = 0.0
        self._peak_equity = 0.0
        self._max_drawdown = 0.0
        self._win_count = 0
        self._loss_count = 0
        self._total_profit = 0.0
        self._total_loss = 0.0
        self._trades.clear()
        self._signals_generated = 0
        self._trades_executed = 0
        self._session_start = datetime.now()


# Singleton accessor
def get_monitor() -> BotMonitor:
    """Get the singleton monitor instance"""
    return BotMonitor()


# Convenience functions
def record_tick(tick: Dict):
    """Record tick for monitoring"""
    get_monitor().record_tick(tick)


def record_trade(trade: Dict):
    """Record trade for monitoring"""
    get_monitor().record_trade(trade)


def get_status() -> Dict:
    """Get current monitoring status"""
    return get_monitor().get_full_status()
