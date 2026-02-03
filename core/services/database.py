"""
PTQ Scalping Bot - SQLite Database Manager
Replaces JSON logging with proper database for better performance
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import json
import threading

# Database file path
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades.db')


class DatabaseManager:
    """SQLite database manager for trade logging and analytics"""
    
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
        
        self._initialized = True
        self._local = threading.local()
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        
        # Initialize database schema
        self._init_schema()
    
    @contextmanager
    def _get_connection(self):
        """Thread-safe connection management"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        try:
            yield self._local.conn
        except Exception as e:
            self._local.conn.rollback()
            raise e
    
    def _init_schema(self):
        """Initialize database tables"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Trades table - main trade log
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    entry_time TIMESTAMP,
                    exit_time TIMESTAMP,
                    entry_reason TEXT,
                    exit_reason TEXT,
                    pnl REAL DEFAULT 0,
                    pnl_pct REAL DEFAULT 0,
                    hold_time_sec INTEGER DEFAULT 0,
                    score INTEGER,
                    confidence INTEGER,
                    factors TEXT,
                    greeks TEXT,
                    status TEXT DEFAULT 'OPEN',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Daily summary table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    max_profit REAL DEFAULT 0,
                    max_loss REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    avg_win REAL DEFAULT 0,
                    avg_loss REAL DEFAULT 0,
                    best_trade_pnl REAL DEFAULT 0,
                    worst_trade_pnl REAL DEFAULT 0,
                    avg_hold_time_sec INTEGER DEFAULT 0,
                    ce_trades INTEGER DEFAULT 0,
                    pe_trades INTEGER DEFAULT 0,
                    ce_pnl REAL DEFAULT 0,
                    pe_pnl REAL DEFAULT 0,
                    kill_switch_triggered INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tick data table (for analysis)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT,
                    ltp REAL NOT NULL,
                    bid REAL,
                    ask REAL,
                    volume INTEGER,
                    spot_price REAL,
                    oi INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Bot state table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    daily_pnl REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    consecutive_losses INTEGER DEFAULT 0,
                    state TEXT DEFAULT 'IDLE',
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Signals table (for strategy analysis)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    direction TEXT,
                    score INTEGER,
                    confidence INTEGER,
                    bull_score INTEGER,
                    bear_score INTEGER,
                    factors TEXT,
                    regime TEXT,
                    rsi REAL,
                    macd_hist REAL,
                    was_taken INTEGER DEFAULT 0,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date(entry_time))')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ticks_timestamp ON ticks(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)')
            
            conn.commit()
    
    # ==========================================
    # TRADE OPERATIONS
    # ==========================================
    
    def log_entry(self, trade: Dict) -> int:
        """Log trade entry to database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades (
                    order_id, symbol, direction, side, qty,
                    entry_price, entry_time, entry_reason,
                    score, confidence, factors, greeks, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            ''', (
                trade.get('order_id'),
                trade.get('symbol'),
                trade.get('direction', 'CE'),
                trade.get('side', 'BUY'),
                trade.get('qty'),
                trade.get('entry_price'),
                trade.get('entry_time', datetime.now()),
                trade.get('entry_reason'),
                trade.get('score'),
                trade.get('confidence'),
                json.dumps(trade.get('factors', [])),
                json.dumps(trade.get('greeks', {}))
            ))
            conn.commit()
            return cursor.lastrowid
    
    def log_exit(self, order_id: str, exit_data: Dict) -> bool:
        """Log trade exit to database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE trades SET
                    exit_price = ?,
                    exit_time = ?,
                    exit_reason = ?,
                    pnl = ?,
                    pnl_pct = ?,
                    hold_time_sec = ?,
                    status = 'CLOSED'
                WHERE order_id = ?
            ''', (
                exit_data.get('exit_price'),
                exit_data.get('exit_time', datetime.now()),
                exit_data.get('exit_reason'),
                exit_data.get('pnl', 0),
                exit_data.get('pnl_pct', 0),
                exit_data.get('hold_time_sec', 0),
                order_id
            ))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_trade(self, order_id: str) -> Optional[Dict]:
        """Get trade by order_id"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM trades WHERE order_id = ?', (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_open_trade(self) -> Optional[Dict]:
        """Get current open trade"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM trades WHERE status = "OPEN" ORDER BY entry_time DESC LIMIT 1')
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_todays_trades(self) -> List[Dict]:
        """Get all trades for today"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM trades 
                WHERE date(entry_time) = ? 
                ORDER BY entry_time DESC
            ''', (today,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_trades_by_date(self, date: str) -> List[Dict]:
        """Get all trades for a specific date"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM trades 
                WHERE date(entry_time) = ? 
                ORDER BY entry_time DESC
            ''', (date,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ==========================================
    # DAILY SUMMARY OPERATIONS
    # ==========================================
    
    def update_daily_summary(self) -> Dict:
        """Calculate and update today's summary"""
        today = datetime.now().strftime('%Y-%m-%d')
        trades = self.get_todays_trades()
        
        if not trades:
            return {}
        
        closed_trades = [t for t in trades if t['status'] == 'CLOSED']
        
        if not closed_trades:
            return {}
        
        winners = [t for t in closed_trades if t['pnl'] > 0]
        losers = [t for t in closed_trades if t['pnl'] < 0]
        
        total_pnl = sum(t['pnl'] for t in closed_trades)
        ce_trades = [t for t in closed_trades if t['direction'] == 'CE']
        pe_trades = [t for t in closed_trades if t['direction'] == 'PE']
        
        win_pnls = [t['pnl'] for t in winners]
        loss_pnls = [abs(t['pnl']) for t in losers]
        
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
        profit_factor = sum(win_pnls) / sum(loss_pnls) if loss_pnls and sum(loss_pnls) > 0 else 0
        
        summary = {
            'date': today,
            'total_trades': len(closed_trades),
            'winning_trades': len(winners),
            'losing_trades': len(losers),
            'total_pnl': total_pnl,
            'max_profit': max([t['pnl'] for t in closed_trades]) if closed_trades else 0,
            'max_loss': min([t['pnl'] for t in closed_trades]) if closed_trades else 0,
            'win_rate': (len(winners) / len(closed_trades) * 100) if closed_trades else 0,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'best_trade_pnl': max(win_pnls) if win_pnls else 0,
            'worst_trade_pnl': min([t['pnl'] for t in losers]) if losers else 0,
            'avg_hold_time_sec': sum(t['hold_time_sec'] for t in closed_trades) // len(closed_trades) if closed_trades else 0,
            'ce_trades': len(ce_trades),
            'pe_trades': len(pe_trades),
            'ce_pnl': sum(t['pnl'] for t in ce_trades),
            'pe_pnl': sum(t['pnl'] for t in pe_trades)
        }
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO daily_summary (
                    date, total_trades, winning_trades, losing_trades,
                    total_pnl, max_profit, max_loss, win_rate, profit_factor,
                    avg_win, avg_loss, best_trade_pnl, worst_trade_pnl,
                    avg_hold_time_sec, ce_trades, pe_trades, ce_pnl, pe_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                summary['date'], summary['total_trades'], summary['winning_trades'],
                summary['losing_trades'], summary['total_pnl'], summary['max_profit'],
                summary['max_loss'], summary['win_rate'], summary['profit_factor'],
                summary['avg_win'], summary['avg_loss'], summary['best_trade_pnl'],
                summary['worst_trade_pnl'], summary['avg_hold_time_sec'],
                summary['ce_trades'], summary['pe_trades'], summary['ce_pnl'], summary['pe_pnl']
            ))
            conn.commit()
        
        return summary
    
    def get_daily_summary(self, date: str = None) -> Optional[Dict]:
        """Get daily summary"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM daily_summary WHERE date = ?', (date,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_weekly_summary(self) -> List[Dict]:
        """Get last 7 days summary"""
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM daily_summary 
                WHERE date >= ? 
                ORDER BY date DESC
            ''', (week_ago,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ==========================================
    # BOT STATE OPERATIONS
    # ==========================================
    
    def save_bot_state(self, state: Dict) -> bool:
        """Save current bot state"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO bot_state (
                    date, daily_pnl, total_trades, winning_trades,
                    losing_trades, consecutive_losses, state, last_update
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                today,
                state.get('daily_pnl', 0),
                state.get('total_trades', 0),
                state.get('winning_trades', 0),
                state.get('losing_trades', 0),
                state.get('consecutive_losses', 0),
                state.get('state', 'IDLE'),
                datetime.now()
            ))
            conn.commit()
            return True
    
    def load_bot_state(self) -> Optional[Dict]:
        """Load today's bot state"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bot_state WHERE date = ?', (today,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ==========================================
    # SIGNAL LOGGING (for strategy analysis)
    # ==========================================
    
    def log_signal(self, signal: Dict) -> int:
        """Log trading signal for analysis"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO signals (
                    timestamp, direction, score, confidence,
                    bull_score, bear_score, factors, regime,
                    rsi, macd_hist, was_taken
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal.get('timestamp', datetime.now()),
                signal.get('direction'),
                signal.get('score'),
                signal.get('confidence'),
                signal.get('bull_score'),
                signal.get('bear_score'),
                json.dumps(signal.get('factors', [])),
                signal.get('regime'),
                signal.get('rsi'),
                signal.get('macd_hist'),
                1 if signal.get('was_taken') else 0
            ))
            conn.commit()
            return cursor.lastrowid
    
    # ==========================================
    # ANALYTICS QUERIES
    # ==========================================
    
    def get_performance_by_hour(self, days: int = 30) -> List[Dict]:
        """Get performance breakdown by hour"""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    strftime('%H', entry_time) as hour,
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl
                FROM trades 
                WHERE date(entry_time) >= ? AND status = 'CLOSED'
                GROUP BY hour
                ORDER BY hour
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_performance_by_direction(self, days: int = 30) -> Dict:
        """Get CE vs PE performance"""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    direction,
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl
                FROM trades 
                WHERE date(entry_time) >= ? AND status = 'CLOSED'
                GROUP BY direction
            ''', (start_date,))
            rows = cursor.fetchall()
            return {row['direction']: dict(row) for row in rows}
    
    def get_win_streak(self) -> Dict:
        """Get current and max win/loss streaks"""
        trades = self.get_todays_trades()
        closed = [t for t in trades if t['status'] == 'CLOSED']
        
        if not closed:
            return {'current_streak': 0, 'streak_type': None, 'max_win_streak': 0, 'max_loss_streak': 0}
        
        # Sort by exit time
        closed.sort(key=lambda x: x['exit_time'] or x['entry_time'])
        
        current_streak = 0
        streak_type = None
        max_win_streak = 0
        max_loss_streak = 0
        temp_streak = 0
        temp_type = None
        
        for trade in closed:
            is_win = trade['pnl'] > 0
            
            if temp_type is None:
                temp_type = 'win' if is_win else 'loss'
                temp_streak = 1
            elif (is_win and temp_type == 'win') or (not is_win and temp_type == 'loss'):
                temp_streak += 1
            else:
                if temp_type == 'win':
                    max_win_streak = max(max_win_streak, temp_streak)
                else:
                    max_loss_streak = max(max_loss_streak, temp_streak)
                temp_type = 'win' if is_win else 'loss'
                temp_streak = 1
            
            current_streak = temp_streak
            streak_type = temp_type
        
        # Update max streaks with final streak
        if temp_type == 'win':
            max_win_streak = max(max_win_streak, temp_streak)
        else:
            max_loss_streak = max(max_loss_streak, temp_streak)
        
        return {
            'current_streak': current_streak,
            'streak_type': streak_type,
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak
        }


# Singleton instance
db = DatabaseManager()


# Convenience functions
def log_trade_entry(trade: Dict) -> int:
    return db.log_entry(trade)

def log_trade_exit(order_id: str, exit_data: Dict) -> bool:
    return db.log_exit(order_id, exit_data)

def get_todays_summary() -> Dict:
    return db.update_daily_summary()

def get_todays_trades() -> List[Dict]:
    return db.get_todays_trades()

def save_state(state: Dict) -> bool:
    return db.save_bot_state(state)

def load_state() -> Optional[Dict]:
    return db.load_bot_state()
