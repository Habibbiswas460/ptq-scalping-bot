"""
PTQ Scalping Bot - Enhanced Logger
Comprehensive logging for analysis and debugging
"""

import os
import json
import csv
from datetime import datetime
from typing import Optional, Dict, Any, List


class BotLogger:
    """Enhanced structured logger for bot events"""
    
    def __init__(self, log_dir: str = "logs", enable_console: bool = True):
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
        self.tick_log = os.path.join(self.today_dir, "ticks.log")
        
        # JSON log files for analysis
        self.trades_json = os.path.join(self.today_dir, "trades.json")
        self.ticks_json = os.path.join(self.today_dir, "ticks.json")
        self.events_json = os.path.join(self.today_dir, "events.json")
        
        # CSV for Excel analysis
        self.trades_csv = os.path.join(self.today_dir, "trades.csv")
        
        # Session tracking
        self.session_start = datetime.now()
        self.tick_count = 0
        self.entry_count = 0
        self.exit_count = 0
        
        # Initialize files
        self._init_log_files()
        self._init_csv()
    
    def _init_log_files(self):
        """Initialize log files"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for log_file in [self.main_log, self.trade_log, self.state_log, self.error_log, self.tick_log]:
            if not os.path.exists(log_file):
                with open(log_file, 'w') as f:
                    f.write(f"# Log started at {timestamp}\n")
    
    def _init_csv(self):
        """Initialize CSV file with headers"""
        if not os.path.exists(self.trades_csv):
            headers = [
                'trade_id', 'timestamp', 'event', 'symbol', 'side', 'qty',
                'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'hold_time_sec',
                'entry_reason', 'exit_reason', 'delta', 'gamma', 'theta', 'vega',
                'spot_price', 'strike', 'tte_sec'
            ]
            with open(self.trades_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
    
    def _write_log(self, filepath: str, message: str, level: str = "INFO"):
        """Write to log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}\n"
        
        with open(filepath, 'a') as f:
            f.write(log_line)
        
        if self.enable_console:
            print(f"[{level}] {message}")
    
    def _write_json(self, filepath: str, data: Dict):
        """Append JSON entry"""
        with open(filepath, 'a') as f:
            f.write(json.dumps(data) + '\n')
    
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
    
    def debug(self, message: str):
        """Log debug message (file only, no console)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(self.main_log, 'a') as f:
            f.write(f"[{timestamp}] [DEBUG] {message}\n")
    
    def state_change(self, old_state: str, new_state: str, reason: str = ""):
        """Log state machine transition"""
        msg = f"STATE: {old_state} → {new_state}"
        if reason:
            msg += f" | Reason: {reason}"
        self._write_log(self.state_log, msg, "STATE")
        
        # JSON event
        self._write_json(self.events_json, {
            'timestamp': datetime.now().isoformat(),
            'type': 'state_change',
            'old_state': old_state,
            'new_state': new_state,
            'reason': reason
        })
    
    def trade_entry(self, trade_data: Dict[str, Any]):
        """Log trade entry with full details"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.entry_count += 1
        
        log_entry = {
            'timestamp': timestamp,
            'event': 'ENTRY',
            'trade_number': self.entry_count,
            **trade_data
        }
        
        # Formatted message
        msg = (f"ENTRY #{self.entry_count} | OrderID: {trade_data.get('order_id')} | "
               f"Symbol: {trade_data.get('symbol')} | "
               f"Side: {trade_data.get('side')} | "
               f"Qty: {trade_data.get('qty')} | "
               f"Price: ₹{trade_data.get('entry_price', 0):.2f} | "
               f"Reason: {trade_data.get('entry_reason', 'N/A')}")
        
        self._write_log(self.trade_log, msg, "ENTRY")
        self._write_json(self.trades_json, log_entry)
        
        # CSV entry row
        greeks = trade_data.get('greeks', {})
        csv_row = [
            trade_data.get('order_id', ''),
            timestamp,
            'ENTRY',
            trade_data.get('symbol', ''),
            trade_data.get('side', ''),
            trade_data.get('qty', 0),
            trade_data.get('entry_price', 0),
            '',  # exit_price
            '',  # pnl
            '',  # pnl_pct
            '',  # hold_time
            trade_data.get('entry_reason', ''),
            '',  # exit_reason
            greeks.get('delta', 0),
            greeks.get('gamma', 0),
            greeks.get('theta', 0),
            greeks.get('vega', 0),
            trade_data.get('spot_price', 0),
            trade_data.get('strike', 0),
            greeks.get('tte', 0)
        ]
        with open(self.trades_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(csv_row)
    
    def trade_exit(self, exit_data: Dict[str, Any]):
        """Log trade exit with full details"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.exit_count += 1
        
        log_entry = {
            'timestamp': timestamp,
            'event': 'EXIT',
            **exit_data
        }
        
        # Formatted message
        pnl = exit_data.get('pnl', 0)
        pnl_symbol = "+" if pnl >= 0 else ""
        emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
        
        msg = (f"EXIT {emoji} | OrderID: {exit_data.get('order_id')} | "
               f"Price: ₹{exit_data.get('exit_price', 0):.2f} | "
               f"PnL: {pnl_symbol}₹{pnl:.2f} ({pnl_symbol}{exit_data.get('pnl_pct', 0):.2f}%) | "
               f"Hold: {exit_data.get('hold_time_sec', 0):.1f}s | "
               f"Reason: {exit_data.get('exit_reason', 'N/A')}")
        
        self._write_log(self.trade_log, msg, "EXIT")
        self._write_json(self.trades_json, log_entry)
        
        # CSV exit row
        csv_row = [
            exit_data.get('order_id', ''),
            timestamp,
            'EXIT',
            '',  # symbol
            '',  # side
            '',  # qty
            '',  # entry_price
            exit_data.get('exit_price', 0),
            exit_data.get('pnl', 0),
            exit_data.get('pnl_pct', 0),
            exit_data.get('hold_time_sec', 0),
            '',  # entry_reason
            exit_data.get('exit_reason', ''),
            '', '', '', '',  # greeks
            '', '', ''  # spot, strike, tte
        ]
        with open(self.trades_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(csv_row)
    
    def tick_data(self, tick: Dict[str, Any], accepted: bool = True, reject_reason: str = ""):
        """Log tick data for analysis (sampled)"""
        self.tick_count += 1
        
        # Only log every 100th tick to avoid massive files
        if self.tick_count % 100 != 0 and accepted:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        tick_entry = {
            'timestamp': timestamp,
            'tick_number': self.tick_count,
            'accepted': accepted,
            'reject_reason': reject_reason if not accepted else '',
            'ltp': tick.get('ltp', 0),
            'bid': tick.get('bid', 0),
            'ask': tick.get('ask', 0),
            'volume': tick.get('volume', 0),
            'spread': tick.get('ask', 0) - tick.get('bid', 0),
            'spread_pct': ((tick.get('ask', 0) - tick.get('bid', 0)) / tick.get('ask', 1)) * 100
        }
        
        self._write_json(self.ticks_json, tick_entry)
    
    def kill_switch(self, trigger: str, details: Dict[str, Any]):
        """Log kill switch activation"""
        msg = f"🛑 KILL_SWITCH ACTIVATED | Trigger: {trigger} | Details: {json.dumps(details)}"
        self._write_log(self.error_log, msg, "KILL")
        self._write_log(self.main_log, msg, "KILL")
        
        self._write_json(self.events_json, {
            'timestamp': datetime.now().isoformat(),
            'type': 'kill_switch',
            'trigger': trigger,
            'details': details
        })
    
    def tick_rejected(self, reason: str, tick_data: Optional[Dict] = None):
        """Log rejected tick"""
        msg = f"TICK_REJECTED | Reason: {reason}"
        
        if tick_data:
            msg += f" | LTP: {tick_data.get('ltp', 0):.2f}"
            self.tick_data(tick_data, accepted=False, reject_reason=reason)
        
        # Only write to file, not console (too noisy)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(self.tick_log, 'a') as f:
            f.write(f"[{timestamp}] [REJECT] {msg}\n")
    
    def signal_event(self, signal_type: str, passed: bool, reason: str, details: Dict = None):
        """Log entry signal events for debugging"""
        self._write_json(self.events_json, {
            'timestamp': datetime.now().isoformat(),
            'type': 'signal',
            'signal_type': signal_type,
            'passed': passed,
            'reason': reason,
            'details': details or {}
        })
    
    def daily_summary(self, summary_data: Dict[str, Any]):
        """Log end-of-day summary"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session_duration = (datetime.now() - self.session_start).total_seconds()
        
        # Enhance summary
        summary_data['session_duration_sec'] = session_duration
        summary_data['ticks_processed'] = self.tick_count
        summary_data['entries'] = self.entry_count
        summary_data['exits'] = self.exit_count
        
        # Calculate win rate
        total = summary_data.get('total_trades', 0)
        wins = summary_data.get('winning_trades', 0)
        win_rate = (wins / total * 100) if total > 0 else 0
        
        msg = (f"\n{'='*60}\n"
               f"📊 DAILY SUMMARY - {timestamp}\n"
               f"{'='*60}\n"
               f"Total Trades: {total}\n"
               f"Winners: {wins} | "
               f"Losers: {summary_data.get('losing_trades', 0)}\n"
               f"Win Rate: {win_rate:.1f}%\n"
               f"Total PnL: ₹{summary_data.get('total_pnl', 0):+,.2f}\n"
               f"Max Drawdown: ₹{summary_data.get('max_drawdown', 0):,.2f}\n"
               f"Kill Switch: {summary_data.get('kill_switch_count', 0)} times\n"
               f"Session Duration: {session_duration/3600:.1f} hours\n"
               f"Ticks Processed: {self.tick_count:,}\n"
               f"{'='*60}\n")
        
        self._write_log(self.main_log, msg, "SUMMARY")
        
        # Write JSON summary
        with open(os.path.join(self.today_dir, "summary.json"), 'w') as f:
            json.dump(summary_data, f, indent=2)
    
    def get_session_stats(self) -> Dict:
        """Get current session statistics"""
        return {
            'session_start': self.session_start.isoformat(),
            'duration_sec': (datetime.now() - self.session_start).total_seconds(),
            'ticks_processed': self.tick_count,
            'entries': self.entry_count,
            'exits': self.exit_count
        }
