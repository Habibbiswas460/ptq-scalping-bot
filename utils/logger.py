"""
Lightweight logging system for PTQ Scalping Bot
Structured logging for trades, states, and events
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any


class BotLogger:
    """Structured logger for bot events"""
    
    def __init__(self, log_dir: str = "logs", enable_console: bool = True):
        """
        Initialize logger
        
        Args:
            log_dir: Directory for log files
            enable_console: Also print to console
        """
        self.log_dir = log_dir
        self.enable_console = enable_console
        
        # Create log directory with today's date
        today = datetime.now().strftime("%Y-%m-%d")
        self.today_dir = os.path.join(log_dir, today)
        os.makedirs(self.today_dir, exist_ok=True)
        
        # Log file paths
        self.main_log = os.path.join(self.today_dir, "bot.log")
        self.trade_log = os.path.join(self.today_dir, "trades.log")
        self.state_log = os.path.join(self.today_dir, "states.log")
        self.error_log = os.path.join(self.today_dir, "errors.log")
        
        # Initialize files
        self._init_log_files()
    
    def _init_log_files(self):
        """Initialize log files if they don't exist"""
        for log_file in [self.main_log, self.trade_log, self.state_log, self.error_log]:
            if not os.path.exists(log_file):
                with open(log_file, 'w') as f:
                    f.write(f"# Log started at {datetime.now()}\n")
    
    def _write_log(self, filepath: str, message: str, level: str = "INFO"):
        """Write to log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}\n"
        
        with open(filepath, 'a') as f:
            f.write(log_line)
        
        if self.enable_console:
            print(f"[{level}] {message}")
    
    def info(self, message: str):
        """Log info message"""
        self._write_log(self.main_log, message, "INFO")
    
    def warning(self, message: str):
        """Log warning message"""
        self._write_log(self.main_log, message, "WARN")
    
    def error(self, message: str, exception: Optional[Exception] = None):
        """Log error message"""
        if exception:
            message = f"{message} | Exception: {str(exception)}"
        self._write_log(self.error_log, message, "ERROR")
        self._write_log(self.main_log, message, "ERROR")
    
    def state_change(self, old_state: str, new_state: str, reason: str = ""):
        """Log state machine transition"""
        msg = f"STATE: {old_state} → {new_state}"
        if reason:
            msg += f" | Reason: {reason}"
        self._write_log(self.state_log, msg, "STATE")
    
    def trade_entry(self, trade_data: Dict[str, Any]):
        """
        Log trade entry
        
        Expected trade_data:
        {
            'order_id': str,
            'symbol': str,
            'side': str,
            'qty': int,
            'entry_price': float,
            'entry_reason': str,
            'greeks': dict
        }
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        log_entry = {
            'timestamp': timestamp,
            'event': 'ENTRY',
            **trade_data
        }
        
        # Formatted message
        msg = (f"ENTRY | OrderID: {trade_data.get('order_id')} | "
               f"Symbol: {trade_data.get('symbol')} | "
               f"Side: {trade_data.get('side')} | "
               f"Qty: {trade_data.get('qty')} | "
               f"Price: {trade_data.get('entry_price')} | "
               f"Reason: {trade_data.get('entry_reason', 'N/A')}")
        
        self._write_log(self.trade_log, msg, "ENTRY")
        
        # Also write JSON for analysis
        with open(os.path.join(self.today_dir, "trades.json"), 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def trade_exit(self, exit_data: Dict[str, Any]):
        """
        Log trade exit
        
        Expected exit_data:
        {
            'order_id': str,
            'exit_price': float,
            'exit_reason': str,
            'pnl': float,
            'pnl_pct': float,
            'hold_time_sec': float
        }
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        log_entry = {
            'timestamp': timestamp,
            'event': 'EXIT',
            **exit_data
        }
        
        # Formatted message
        pnl_symbol = "+" if exit_data.get('pnl', 0) >= 0 else ""
        msg = (f"EXIT | OrderID: {exit_data.get('order_id')} | "
               f"Price: {exit_data.get('exit_price')} | "
               f"PnL: {pnl_symbol}{exit_data.get('pnl_pct', 0):.2f}% | "
               f"Hold: {exit_data.get('hold_time_sec', 0):.1f}s | "
               f"Reason: {exit_data.get('exit_reason', 'N/A')}")
        
        self._write_log(self.trade_log, msg, "EXIT")
        
        # Write JSON
        with open(os.path.join(self.today_dir, "trades.json"), 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def kill_switch(self, trigger: str, details: Dict[str, Any]):
        """
        Log kill switch activation
        
        Args:
            trigger: What triggered kill switch
            details: Additional details
        """
        msg = f"KILL_SWITCH ACTIVATED | Trigger: {trigger} | Details: {json.dumps(details)}"
        self._write_log(self.error_log, msg, "KILL")
        self._write_log(self.main_log, msg, "KILL")
    
    def tick_rejected(self, reason: str, tick_data: Optional[Dict] = None):
        """Log rejected tick"""
        msg = f"TICK_REJECTED | Reason: {reason}"
        if tick_data:
            msg += f" | Latency: {tick_data.get('latency_ms', 0):.1f}ms | Spread: {tick_data.get('spread_pct', 0):.3f}%"
        self._write_log(self.main_log, msg, "REJECT")
    
    def daily_summary(self, summary_data: Dict[str, Any]):
        """
        Log end-of-day summary
        
        Expected summary_data:
        {
            'total_trades': int,
            'winning_trades': int,
            'losing_trades': int,
            'total_pnl': float,
            'max_drawdown': float,
            'kill_switch_count': int
        }
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        msg = (f"\n{'='*60}\n"
               f"DAILY SUMMARY - {timestamp}\n"
               f"{'='*60}\n"
               f"Total Trades: {summary_data.get('total_trades', 0)}\n"
               f"Winners: {summary_data.get('winning_trades', 0)} | "
               f"Losers: {summary_data.get('losing_trades', 0)}\n"
               f"Total PnL: {summary_data.get('total_pnl', 0):.2f}%\n"
               f"Max Drawdown: {summary_data.get('max_drawdown', 0):.2f}%\n"
               f"Kill Switch: {summary_data.get('kill_switch_count', 0)} times\n"
               f"{'='*60}\n")
        
        self._write_log(self.main_log, msg, "SUMMARY")
        
        # Write JSON summary
        with open(os.path.join(self.today_dir, "summary.json"), 'w') as f:
            json.dump(summary_data, f, indent=2)
