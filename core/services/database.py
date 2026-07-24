"""
PTQ Scalping Bot - SQLite Database Manager
Replaces JSON logging with proper database for better performance
"""

import sqlite3
import os
import sys
import time
import atexit
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import json
import threading

# Database file path
# Resolution order:
# 1) Pre-set global DB_PATH (tests may monkeypatch before reload)
# 2) PTQ_DB_PATH environment override
# 3) Pytest session -> isolated test database file
# 4) Default production database file
_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades.db')
_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades_test.db')

if 'DB_PATH' in globals():
    DB_PATH = globals()['DB_PATH']
elif os.getenv('PTQ_DB_PATH'):
    DB_PATH = os.getenv('PTQ_DB_PATH')
elif 'pytest' in sys.modules or os.getenv('PYTEST_CURRENT_TEST') is not None:
    DB_PATH = os.getenv('PTQ_TEST_DB_PATH', _TEST_DB_PATH)
else:
    DB_PATH = _DEFAULT_DB_PATH


# SQLite lock handling tuned for runtime startup safety.
SQLITE_CONNECT_TIMEOUT_SEC = 30
SQLITE_BUSY_TIMEOUT_MS = 30000
SCHEMA_INIT_MAX_RETRIES = 8
SCHEMA_INIT_RETRY_DELAY_SEC = 0.75


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
        self._init_schema_with_retry()
    
    @contextmanager
    def _get_connection(self):
        """Thread-safe connection management"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                DB_PATH,
                check_same_thread=False,
                timeout=SQLITE_CONNECT_TIMEOUT_SEC,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute('PRAGMA foreign_keys = ON')
            self._local.conn.execute(f'PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}')
            self._local.conn.execute('PRAGMA journal_mode = WAL')
        try:
            yield self._local.conn
        except Exception as e:
            self._local.conn.rollback()
            raise e

    def close(self):
        """Close current thread-local SQLite connection if it exists."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            return
        try:
            conn.close()
        finally:
            self._local.conn = None

    @staticmethod
    def _db_timestamp(value: Any) -> Any:
        """Convert datetime objects to ISO strings for SQLite writes."""
        if isinstance(value, datetime):
            return value.isoformat(sep=' ', timespec='seconds')
        return value
    
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
                    market_quality_score INTEGER,
                    market_quality_grade TEXT,
                    market_quality_components TEXT,
                    hard_reject_reason TEXT,
                    risk_budget_used REAL,
                    risk_amount REAL,
                    allocation_grade TEXT,
                    position_size_breakdown TEXT,
                    factors TEXT,
                    greeks TEXT,
                    status TEXT DEFAULT 'OPEN',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add any missing market-quality columns for existing trade tables.
            self._ensure_table_columns(cursor, 'trades', [
                ('market_quality_score', 'INTEGER'),
                ('market_quality_grade', 'TEXT'),
                ('market_quality_components', 'TEXT'),
                ('hard_reject_reason', 'TEXT'),
                ('risk_budget_used', 'REAL'),
                ('risk_amount', 'REAL'),
                ('allocation_grade', 'TEXT'),
                ('position_size_breakdown', 'TEXT')
            ])
            
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
                    weighted_score INTEGER,
                    score INTEGER,
                    confidence INTEGER,
                    market_quality_pass INTEGER,
                    market_quality_pct INTEGER,
                    market_quality_score INTEGER,
                    market_quality_grade TEXT,
                    market_quality_components TEXT,
                    hard_reject_reason TEXT,
                    bull_score INTEGER,
                    bear_score INTEGER,
                    factors TEXT,
                    regime TEXT,
                    rsi REAL,
                    macd_hist REAL,
                    score_breakdown TEXT,
                    confidence_breakdown TEXT,
                    was_taken INTEGER DEFAULT 0,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add any missing analytics columns for existing databases.
            self._ensure_table_columns(cursor, 'signals', [
                ('weighted_score', 'INTEGER'),
                ('market_quality_pass', 'INTEGER'),
                ('market_quality_pct', 'INTEGER'),
                ('market_quality_score', 'INTEGER'),
                ('market_quality_grade', 'TEXT'),
                ('market_quality_components', 'TEXT'),
                ('hard_reject_reason', 'TEXT'),
                ('score_breakdown', 'TEXT'),
                ('confidence_breakdown', 'TEXT')
            ])

            # DVF signal capture table - read-only decision observation.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dvf_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT UNIQUE,
                    parent_decision_id TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    direction TEXT,
                    session_type TEXT,
                    strategy_name TEXT,
                    strategy_version TEXT,
                    engine_version TEXT,
                    config_hash TEXT,
                    weighted_score INTEGER,
                    confidence INTEGER,
                    market_quality_score INTEGER,
                    market_quality_grade TEXT,
                    position_size_recommendation INTEGER,
                    allocation_grade TEXT,
                    regime TEXT,
                    regime_snapshot TEXT,
                    spread REAL,
                    volume INTEGER,
                    greeks TEXT,
                    indicators_snapshot TEXT,
                    score_breakdown TEXT,
                    confidence_breakdown TEXT,
                    market_quality_components TEXT,
                    position_size_breakdown TEXT,
                    accepted INTEGER DEFAULT 0,
                    rejected INTEGER DEFAULT 0,
                    reject_reason TEXT,
                    hard_reject INTEGER DEFAULT 0,
                    hard_reject_reason TEXT,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self._ensure_table_columns(cursor, 'dvf_signals', [
                ('decision_id', 'TEXT'),
                ('parent_decision_id', 'TEXT'),
                ('session_type', 'TEXT'),
                ('strategy_name', 'TEXT'),
                ('strategy_version', 'TEXT'),
                ('engine_version', 'TEXT'),
                ('config_hash', 'TEXT'),
                ('weighted_score', 'INTEGER'),
                ('confidence', 'INTEGER'),
                ('market_quality_score', 'INTEGER'),
                ('market_quality_grade', 'TEXT'),
                ('position_size_recommendation', 'INTEGER'),
                ('allocation_grade', 'TEXT'),
                ('regime', 'TEXT'),
                ('regime_snapshot', 'TEXT'),
                ('spread', 'REAL'),
                ('volume', 'INTEGER'),
                ('greeks', 'TEXT'),
                ('indicators_snapshot', 'TEXT'),
                ('score_breakdown', 'TEXT'),
                ('confidence_breakdown', 'TEXT'),
                ('market_quality_components', 'TEXT'),
                ('position_size_breakdown', 'TEXT'),
                ('accepted', 'INTEGER'),
                ('rejected', 'INTEGER'),
                ('reject_reason', 'TEXT'),
                ('hard_reject', 'INTEGER'),
                ('hard_reject_reason', 'TEXT'),
                ('result', 'TEXT')
            ])

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dvf_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    status TEXT DEFAULT 'OPEN',
                    direction TEXT,
                    session_type TEXT,
                    strategy_version TEXT,
                    engine_version TEXT,
                    config_hash TEXT,
                    position_size INTEGER,
                    allocation_grade TEXT,
                    market_quality_grade TEXT,
                    risk_amount REAL DEFAULT 0,
                    virtual_entry_time TIMESTAMP,
                    virtual_entry_price REAL,
                    virtual_exit_time TIMESTAMP,
                    virtual_exit_price REAL,
                    pnl REAL DEFAULT 0,
                    pnl_pct REAL DEFAULT 0,
                    hold_time_sec INTEGER DEFAULT 0,
                    mfe REAL DEFAULT 0,
                    mae REAL DEFAULT 0,
                    slippage_model TEXT,
                    exit_reason TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self._ensure_table_columns(cursor, 'dvf_trades', [
                ('decision_id', 'TEXT'),
                ('status', 'TEXT'),
                ('direction', 'TEXT'),
                ('session_type', 'TEXT'),
                ('strategy_version', 'TEXT'),
                ('engine_version', 'TEXT'),
                ('config_hash', 'TEXT'),
                ('position_size', 'INTEGER'),
                ('allocation_grade', 'TEXT'),
                ('market_quality_grade', 'TEXT'),
                ('risk_amount', 'REAL'),
                ('virtual_entry_time', 'TIMESTAMP'),
                ('virtual_entry_price', 'REAL'),
                ('virtual_exit_time', 'TIMESTAMP'),
                ('virtual_exit_price', 'REAL'),
                ('pnl', 'REAL'),
                ('pnl_pct', 'REAL'),
                ('hold_time_sec', 'INTEGER'),
                ('mfe', 'REAL'),
                ('mae', 'REAL'),
                ('slippage_model', 'TEXT'),
                ('exit_reason', 'TEXT'),
                ('notes', 'TEXT')
            ])

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dvf_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_type TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self._ensure_table_columns(cursor, 'dvf_reports', [
                ('report_type', 'TEXT'),
                ('report_date', 'TEXT'),
                ('payload', 'TEXT')
            ])

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dvf_calibration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    calibration_type TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self._ensure_table_columns(cursor, 'dvf_calibration', [
                ('calibration_type', 'TEXT'),
                ('as_of_date', 'TEXT'),
                ('payload', 'TEXT')
            ])
            
            # Active positions table (for position recovery on restart)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    current_price REAL,
                    unrealized_pnl REAL DEFAULT 0,
                    session_id TEXT,
                    broker_order_id TEXT,
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'ACTIVE'
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date(entry_time))')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ticks_timestamp ON ticks(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dvf_signals_timestamp ON dvf_signals(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dvf_signals_decision_id ON dvf_signals(decision_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dvf_trades_decision_id ON dvf_trades(decision_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dvf_reports_date ON dvf_reports(report_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dvf_calibration_date ON dvf_calibration(as_of_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_positions_status ON active_positions(status)')
            
            conn.commit()

    def _init_schema_with_retry(self):
        """Initialize schema with retries for transient SQLite locks."""
        for attempt in range(1, SCHEMA_INIT_MAX_RETRIES + 1):
            try:
                self._init_schema()
                return
            except sqlite3.OperationalError as e:
                err = str(e).lower()
                if 'database is locked' not in err:
                    raise

                if attempt >= SCHEMA_INIT_MAX_RETRIES:
                    raise

                # Keep output minimal but explicit during startup lock contention.
                print(
                    f"[DB] SQLite locked during schema init (attempt {attempt}/{SCHEMA_INIT_MAX_RETRIES}); retrying..."
                )
                time.sleep(SCHEMA_INIT_RETRY_DELAY_SEC)

    def _ensure_table_columns(self, cursor, table_name: str, columns):
        """Ensure required columns exist on a table."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row[1] for row in cursor.fetchall()}
        for name, datatype in columns:
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {datatype}")
    
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
                    score, confidence, market_quality_score, market_quality_grade,
                    market_quality_components, hard_reject_reason,
                    risk_budget_used, risk_amount, allocation_grade, position_size_breakdown,
                    factors, greeks, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            ''', (
                trade.get('order_id'),
                trade.get('symbol'),
                trade.get('direction', 'CE'),
                trade.get('side', 'BUY'),
                trade.get('qty'),
                trade.get('entry_price'),
                    self._db_timestamp(trade.get('entry_time', datetime.now())),
                trade.get('entry_reason'),
                trade.get('score'),
                trade.get('confidence'),
                trade.get('market_quality_score'),
                trade.get('market_quality_grade'),
                json.dumps(trade.get('market_quality_components', {})),
                trade.get('hard_reject_reason'),
                trade.get('risk_budget_used'),
                trade.get('risk_amount'),
                trade.get('allocation_grade'),
                json.dumps(trade.get('position_size_breakdown', {})),
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
                    self._db_timestamp(exit_data.get('exit_time', datetime.now())),
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
                    timestamp, direction, weighted_score, score, confidence,
                    market_quality_pass, market_quality_pct,
                    market_quality_score, market_quality_grade, market_quality_components, hard_reject_reason,
                    bull_score, bear_score, factors, regime,
                    rsi, macd_hist, score_breakdown, confidence_breakdown,
                    was_taken, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self._db_timestamp(signal.get('timestamp', datetime.now())),
                signal.get('direction'),
                signal.get('weighted_score'),
                signal.get('score'),
                signal.get('confidence'),
                int(signal.get('market_quality_pass', False)),
                signal.get('market_quality_pct'),
                signal.get('market_quality_score', signal.get('market_quality_pct')),
                signal.get('market_quality_grade'),
                json.dumps(signal.get('market_quality_components', {})),
                signal.get('hard_reject_reason'),
                signal.get('bull_score'),
                signal.get('bear_score'),
                json.dumps(signal.get('factors', [])),
                signal.get('regime'),
                signal.get('rsi'),
                signal.get('macd_hist'),
                json.dumps(signal.get('score_breakdown', {})),
                json.dumps(signal.get('confidence_breakdown', {})),
                1 if signal.get('was_taken') else 0,
                signal.get('result')
            ))
            conn.commit()
            return cursor.lastrowid

    def log_dvf_signal(self, signal: Dict) -> int:
        """Log a read-only DVF decision record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            decision_id = signal.get('decision_id')
            if decision_id:
                cursor.execute('SELECT id FROM dvf_signals WHERE decision_id = ?', (decision_id,))
                existing = cursor.fetchone()
                if existing:
                    return int(existing['id'])
            cursor.execute('''
                INSERT INTO dvf_signals (
                    decision_id, parent_decision_id,
                    timestamp, direction, session_type, strategy_name, strategy_version, engine_version, config_hash,
                    weighted_score, confidence, market_quality_score, market_quality_grade,
                    position_size_recommendation, allocation_grade, regime, regime_snapshot, spread, volume,
                    greeks, indicators_snapshot, score_breakdown, confidence_breakdown,
                    market_quality_components, position_size_breakdown,
                    accepted, rejected, reject_reason, hard_reject, hard_reject_reason, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal.get('decision_id'),
                signal.get('parent_decision_id'),
                self._db_timestamp(signal.get('timestamp', datetime.now())),
                signal.get('direction'),
                signal.get('session_type'),
                signal.get('strategy_name'),
                signal.get('strategy_version'),
                signal.get('engine_version'),
                signal.get('config_hash'),
                signal.get('weighted_score'),
                signal.get('confidence'),
                signal.get('market_quality_score'),
                signal.get('market_quality_grade'),
                signal.get('position_size_recommendation'),
                signal.get('allocation_grade'),
                signal.get('regime'),
                json.dumps(signal.get('regime_snapshot', {})),
                signal.get('spread'),
                signal.get('volume'),
                json.dumps(signal.get('greeks', {})),
                json.dumps(signal.get('indicators_snapshot', {})),
                json.dumps(signal.get('score_breakdown', {})),
                json.dumps(signal.get('confidence_breakdown', {})),
                json.dumps(signal.get('market_quality_components', {})),
                json.dumps(signal.get('position_size_breakdown', {})),
                1 if signal.get('accepted') else 0,
                1 if signal.get('rejected') else 0,
                signal.get('reject_reason'),
                1 if signal.get('hard_reject') else 0,
                signal.get('hard_reject_reason'),
                signal.get('result')
            ))
            conn.commit()
            return cursor.lastrowid

    def get_dvf_signals(self, limit: int = 100) -> List[Dict]:
        """Get recent DVF decision records."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM dvf_signals
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_dvf_signal_by_decision_id(self, decision_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM dvf_signals WHERE decision_id = ?', (decision_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def log_dvf_trade_entry(self, trade: Dict) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            decision_id = trade.get('decision_id')
            if decision_id:
                cursor.execute(
                    "SELECT id FROM dvf_trades WHERE decision_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1",
                    (decision_id,),
                )
                existing = cursor.fetchone()
                if existing:
                    return int(existing['id'])
            cursor.execute('''
                INSERT INTO dvf_trades (
                    decision_id, status, direction, session_type,
                    strategy_version, engine_version, config_hash,
                    position_size, allocation_grade, market_quality_grade, risk_amount,
                    virtual_entry_time, virtual_entry_price, slippage_model, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.get('decision_id'),
                trade.get('status', 'OPEN'),
                trade.get('direction'),
                trade.get('session_type'),
                trade.get('strategy_version'),
                trade.get('engine_version'),
                trade.get('config_hash'),
                trade.get('position_size'),
                trade.get('allocation_grade'),
                trade.get('market_quality_grade'),
                trade.get('risk_amount', 0),
                self._db_timestamp(trade.get('virtual_entry_time', datetime.now())),
                trade.get('virtual_entry_price'),
                trade.get('slippage_model'),
                trade.get('notes')
            ))
            conn.commit()
            return cursor.lastrowid

    def log_dvf_trade_exit(self, trade_id: int, trade: Dict) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE dvf_trades SET
                    status = ?,
                    virtual_exit_time = ?,
                    virtual_exit_price = ?,
                    pnl = ?,
                    pnl_pct = ?,
                    hold_time_sec = ?,
                    mfe = ?,
                    mae = ?,
                    exit_reason = ?,
                    notes = ?
                WHERE id = ?
            ''', (
                trade.get('status', 'CLOSED'),
                self._db_timestamp(trade.get('virtual_exit_time', datetime.now())),
                trade.get('virtual_exit_price'),
                trade.get('pnl', 0),
                trade.get('pnl_pct', 0),
                trade.get('hold_time_sec', 0),
                trade.get('mfe', 0),
                trade.get('mae', 0),
                trade.get('exit_reason'),
                trade.get('notes'),
                trade_id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def get_dvf_trade(self, trade_id: int) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM dvf_trades WHERE id = ?', (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_dvf_trade_by_decision_id(self, decision_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM dvf_trades WHERE decision_id = ? ORDER BY id DESC LIMIT 1', (decision_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_dvf_trades(self, limit: int = 100) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM dvf_trades ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def save_dvf_report(self, report_type: str, report_date: str, payload: Dict) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM dvf_reports WHERE report_type = ? AND report_date = ? ORDER BY id DESC LIMIT 1',
                (report_type, report_date),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    '''
                    UPDATE dvf_reports
                    SET payload = ?, created_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''',
                    (json.dumps(payload), int(existing['id']))
                )
                conn.commit()
                return int(existing['id'])
            cursor.execute('''
                INSERT INTO dvf_reports (report_type, report_date, payload)
                VALUES (?, ?, ?)
            ''', (report_type, report_date, json.dumps(payload)))
            conn.commit()
            return cursor.lastrowid

    def get_dvf_reports(self, report_type: Optional[str] = None, limit: int = 30) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if report_type:
                cursor.execute('SELECT * FROM dvf_reports WHERE report_type = ? ORDER BY created_at DESC LIMIT ?', (report_type, limit))
            else:
                cursor.execute('SELECT * FROM dvf_reports ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def save_dvf_calibration(self, calibration_type: str, as_of_date: str, payload: List[Dict]) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM dvf_calibration WHERE calibration_type = ? AND as_of_date = ? ORDER BY id DESC LIMIT 1',
                (calibration_type, as_of_date),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    '''
                    UPDATE dvf_calibration
                    SET payload = ?, created_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''',
                    (json.dumps(payload), int(existing['id']))
                )
                conn.commit()
                return int(existing['id'])
            cursor.execute('''
                INSERT INTO dvf_calibration (calibration_type, as_of_date, payload)
                VALUES (?, ?, ?)
            ''', (calibration_type, as_of_date, json.dumps(payload)))
            conn.commit()
            return cursor.lastrowid

    def get_dvf_calibration(self, calibration_type: Optional[str] = None, limit: int = 30) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if calibration_type:
                cursor.execute('SELECT * FROM dvf_calibration WHERE calibration_type = ? ORDER BY created_at DESC LIMIT ?', (calibration_type, limit))
            else:
                cursor.execute('SELECT * FROM dvf_calibration ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
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

    def get_market_quality_distribution(self, days: int = 30) -> List[Dict]:
        """Get market-quality grade distribution from signal logs."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(market_quality_grade, 'UNKNOWN') AS grade,
                    COUNT(*) AS count
                FROM signals
                WHERE date(timestamp) >= ?
                  AND market_quality_score IS NOT NULL
                GROUP BY COALESCE(market_quality_grade, 'UNKNOWN')
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_hard_reject_stats(self, days: int = 30) -> List[Dict]:
        """Get hard reject reason counts from signal logs."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    hard_reject_reason AS reason,
                    COUNT(*) AS count
                FROM signals
                WHERE date(timestamp) >= ?
                  AND hard_reject_reason IS NOT NULL
                  AND hard_reject_reason != ''
                GROUP BY hard_reject_reason
                ORDER BY count DESC
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_market_quality_win_rate_bands(self, days: int = 30) -> List[Dict]:
        """Get win-rate grouped by market-quality bands from closed trades."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN market_quality_score >= 90 THEN '90+'
                        WHEN market_quality_score >= 80 THEN '80-89'
                        WHEN market_quality_score >= 70 THEN '70-79'
                        WHEN market_quality_score >= 60 THEN '60-69'
                        ELSE '<60'
                    END AS quality_band,
                    COUNT(*) AS trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                        2
                    ) AS win_rate_pct
                FROM trades
                WHERE date(entry_time) >= ?
                  AND status = 'CLOSED'
                  AND market_quality_score IS NOT NULL
                GROUP BY quality_band
                ORDER BY
                    CASE quality_band
                        WHEN '90+' THEN 1
                        WHEN '80-89' THEN 2
                        WHEN '70-79' THEN 3
                        WHEN '60-69' THEN 4
                        ELSE 5
                    END
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_market_quality_grade_win_rate(self, days: int = 30) -> List[Dict]:
        """Get win-rate grouped by market-quality grades from closed trades."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(market_quality_grade, 'UNKNOWN') AS grade,
                    COUNT(*) AS trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                        2
                    ) AS win_rate_pct
                FROM trades
                WHERE date(entry_time) >= ?
                  AND status = 'CLOSED'
                  AND market_quality_grade IS NOT NULL
                  AND market_quality_grade != ''
                GROUP BY COALESCE(market_quality_grade, 'UNKNOWN')
                ORDER BY
                    CASE COALESCE(market_quality_grade, 'UNKNOWN')
                        WHEN 'A+' THEN 1
                        WHEN 'A' THEN 2
                        WHEN 'B' THEN 3
                        WHEN 'C' THEN 4
                        WHEN 'REJECT' THEN 5
                        ELSE 6
                    END
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_confidence_win_rate_bands(self, days: int = 30) -> List[Dict]:
        """Get win-rate grouped by confidence bands from closed trades."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN confidence >= 90 THEN '90+'
                        WHEN confidence >= 80 THEN '80-89'
                        WHEN confidence >= 70 THEN '70-79'
                        ELSE '<70'
                    END AS confidence_band,
                    COUNT(*) AS trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                        2
                    ) AS win_rate_pct
                FROM trades
                WHERE date(entry_time) >= ?
                  AND status = 'CLOSED'
                  AND confidence IS NOT NULL
                GROUP BY confidence_band
                ORDER BY
                    CASE confidence_band
                        WHEN '90+' THEN 1
                        WHEN '80-89' THEN 2
                        WHEN '70-79' THEN 3
                        ELSE 4
                    END
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_confidence_calibration(self, days: int = 30) -> List[Dict]:
        """Get confidence calibration by comparing confidence vs realized win-rate."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN confidence >= 90 THEN '90+'
                        WHEN confidence >= 80 THEN '80-89'
                        WHEN confidence >= 70 THEN '70-79'
                        WHEN confidence >= 60 THEN '60-69'
                        ELSE '<60'
                    END AS confidence_band,
                    COUNT(*) AS trades,
                    ROUND(AVG(confidence), 2) AS avg_confidence_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                        2
                    ) AS realized_win_rate_pct,
                    ROUND(
                        AVG(confidence) - (100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)),
                        2
                    ) AS calibration_error_pct
                FROM trades
                WHERE date(entry_time) >= ?
                  AND status = 'CLOSED'
                  AND confidence IS NOT NULL
                GROUP BY confidence_band
                ORDER BY
                    CASE confidence_band
                        WHEN '90+' THEN 1
                        WHEN '80-89' THEN 2
                        WHEN '70-79' THEN 3
                        WHEN '60-69' THEN 4
                        ELSE 5
                    END
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_market_quality_grade_avg_pnl(self, days: int = 30) -> List[Dict]:
        """Get average PnL grouped by market-quality grades from closed trades."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(market_quality_grade, 'UNKNOWN') AS grade,
                    COUNT(*) AS trades,
                    ROUND(AVG(pnl), 2) AS avg_pnl,
                    ROUND(SUM(pnl), 2) AS total_pnl
                FROM trades
                WHERE date(entry_time) >= ?
                  AND status = 'CLOSED'
                  AND market_quality_grade IS NOT NULL
                  AND market_quality_grade != ''
                GROUP BY COALESCE(market_quality_grade, 'UNKNOWN')
                ORDER BY
                    CASE COALESCE(market_quality_grade, 'UNKNOWN')
                        WHEN 'A+' THEN 1
                        WHEN 'A' THEN 2
                        WHEN 'B' THEN 3
                        WHEN 'C' THEN 4
                        WHEN 'REJECT' THEN 5
                        ELSE 6
                    END
            ''', (start_date,))
            return [dict(row) for row in cursor.fetchall()]
    
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

    # ==========================================
    # POSITION RECOVERY OPERATIONS
    # ==========================================
    
    def save_active_position(self, position: Dict) -> int:
        """Save/update active position for recovery"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO active_positions (
                    order_id, symbol, direction, side, qty,
                    entry_price, entry_time, stop_loss, take_profit,
                    current_price, unrealized_pnl, session_id,
                    broker_order_id, last_update, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'ACTIVE')
            ''', (
                position.get('order_id'),
                position.get('symbol'),
                position.get('direction'),
                position.get('side', 'BUY'),
                position.get('qty', 1),
                position.get('entry_price'),
                self._db_timestamp(position.get('entry_time', datetime.now().isoformat())),
                position.get('stop_loss'),
                position.get('take_profit'),
                position.get('current_price'),
                position.get('unrealized_pnl', 0),
                position.get('session_id'),
                position.get('broker_order_id')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_active_positions(self) -> List[Dict]:
        """Get all active positions (for recovery)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM active_positions 
                WHERE status = 'ACTIVE'
                ORDER BY entry_time DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def close_position_in_db(self, order_id: str) -> bool:
        """Mark a position as closed in the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE active_positions 
                SET status = 'CLOSED', last_update = CURRENT_TIMESTAMP
                WHERE order_id = ?
            ''', (order_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def check_orphan_positions(self) -> List[Dict]:
        """
        Check for orphan positions (positions that weren't properly closed).
        An orphan is an active position older than current session.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Consider positions from previous days as potential orphans
            cursor.execute('''
                SELECT * FROM active_positions 
                WHERE status = 'ACTIVE'
                AND date(entry_time) < date('now')
                ORDER BY entry_time ASC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_positions_from_last_session(self) -> List[Dict]:
        """Get positions that may need recovery (today's active positions)"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM active_positions 
                WHERE status = 'ACTIVE'
                AND date(entry_time) = ?
                ORDER BY entry_time DESC
            ''', (today,))
            return [dict(row) for row in cursor.fetchall()]
    
    def clear_all_active_positions(self) -> int:
        """Clear all active positions (use with caution)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE active_positions 
                SET status = 'CLEARED', last_update = CURRENT_TIMESTAMP
                WHERE status = 'ACTIVE'
            ''')
            conn.commit()
            return cursor.rowcount
    
    def update_position_price(self, order_id: str, current_price: float, unrealized_pnl: float) -> bool:
        """Update current price and PnL for an active position"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE active_positions 
                SET current_price = ?, unrealized_pnl = ?, last_update = CURRENT_TIMESTAMP
                WHERE order_id = ? AND status = 'ACTIVE'
            ''', (current_price, unrealized_pnl, order_id))
            conn.commit()
            return cursor.rowcount > 0


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

def log_dvf_signal(signal: Dict) -> int:
    return db.log_dvf_signal(signal)

def get_dvf_signals(limit: int = 100) -> List[Dict]:
    return db.get_dvf_signals(limit=limit)

def get_dvf_signal_by_decision_id(decision_id: str) -> Optional[Dict]:
    return db.get_dvf_signal_by_decision_id(decision_id)

def log_dvf_trade_entry(trade: Dict) -> int:
    return db.log_dvf_trade_entry(trade)

def log_dvf_trade_exit(trade_id: int, trade: Dict) -> bool:
    return db.log_dvf_trade_exit(trade_id, trade)

def get_dvf_trade(trade_id: int) -> Optional[Dict]:
    return db.get_dvf_trade(trade_id)

def get_dvf_trade_by_decision_id(decision_id: str) -> Optional[Dict]:
    return db.get_dvf_trade_by_decision_id(decision_id)

def get_dvf_trades(limit: int = 100) -> List[Dict]:
    return db.get_dvf_trades(limit=limit)

def save_dvf_report(report_type: str, report_date: str, payload: Dict) -> int:
    return db.save_dvf_report(report_type, report_date, payload)

def get_dvf_reports(report_type: Optional[str] = None, limit: int = 30) -> List[Dict]:
    return db.get_dvf_reports(report_type=report_type, limit=limit)

def save_dvf_calibration(calibration_type: str, as_of_date: str, payload: List[Dict]) -> int:
    return db.save_dvf_calibration(calibration_type, as_of_date, payload)

def get_dvf_calibration(calibration_type: Optional[str] = None, limit: int = 30) -> List[Dict]:
    return db.get_dvf_calibration(calibration_type=calibration_type, limit=limit)

def get_market_quality_distribution(days: int = 30) -> List[Dict]:
    return db.get_market_quality_distribution(days=days)

def get_hard_reject_stats(days: int = 30) -> List[Dict]:
    return db.get_hard_reject_stats(days=days)

def get_market_quality_win_rate_bands(days: int = 30) -> List[Dict]:
    return db.get_market_quality_win_rate_bands(days=days)

def get_market_quality_grade_win_rate(days: int = 30) -> List[Dict]:
    return db.get_market_quality_grade_win_rate(days=days)

def get_confidence_win_rate_bands(days: int = 30) -> List[Dict]:
    return db.get_confidence_win_rate_bands(days=days)

def get_confidence_calibration(days: int = 30) -> List[Dict]:
    return db.get_confidence_calibration(days=days)

def get_market_quality_grade_avg_pnl(days: int = 30) -> List[Dict]:
    return db.get_market_quality_grade_avg_pnl(days=days)

def save_state(state: Dict) -> bool:
    return db.save_bot_state(state)

def load_state() -> Optional[Dict]:
    return db.load_bot_state()


# Position recovery convenience functions
def save_position(position: Dict) -> int:
    """Save active position for recovery"""
    return db.save_active_position(position)

def get_active_positions() -> List[Dict]:
    """Get all active positions"""
    return db.get_active_positions()

def close_position(order_id: str) -> bool:
    """Mark position as closed"""
    return db.close_position_in_db(order_id)

def check_for_orphans() -> List[Dict]:
    """Check for orphan positions from previous sessions"""
    return db.check_orphan_positions()

def recover_last_session_positions() -> List[Dict]:
    """Get positions that may need recovery"""
    return db.get_positions_from_last_session()

def clear_positions() -> int:
    """Clear all active positions"""
    return db.clear_all_active_positions()

def update_position(order_id: str, price: float, pnl: float) -> bool:
    """Update position price and PnL"""
    return db.update_position_price(order_id, price, pnl)


def close_db() -> None:
    """Close DB connection for the current thread."""
    db.close()


atexit.register(close_db)
