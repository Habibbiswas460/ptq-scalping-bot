"""Long-term storage for raw WebSocket ticks and their aggregated 5-min candles, for
later offline strategy backtesting — monthly-partitioned SQLite, same pattern as
core/historical/storage.py's HistoricalStore, but its own table and file namespace.

Why not extend core/historical/storage.py directly, as originally sketched: that
module's CANONICAL_COLUMNS schema is the single source of truth shared with two
offline ingestion paths (utils/ingest_cepe_and_audit.py, utils/phase1_data_audit.py —
see schema.py's own docstring) that never carry a WS sequence number, a full
best-bid/ask book, or circuit limits. Adding those columns there would put
broker-wire-only fields into a schema also written by non-WS sources, and
core/historical/collector.py states an explicit isolation contract (imports nothing
from the live broker stack) that a live-tick-shaped schema sits awkwardly next to.
Reusing the *pattern* (monthly files, streamed queries, INSERT OR IGNORE dedup)
without touching that shared schema avoids both the isolation-contract conflict and a
migration hazard for the historical DBs that already hold real collected data.

Not wired into the live tick path: writing to SQLite on every tick would add disk I/O
to the hot WebSocket callback, working directly against the latency goal this whole
layer split was for. Wiring this in needs a batched/async writer (buffer ticks, flush
on a background thread or interval) — a separate decision, not bundled into this file.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Optional

DEFAULT_STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "tick_store")

RAW_TICK_COLUMNS = (
    "source_broker", "token", "exchange", "symbol", "mode", "sequence",
    "timestamp_ms", "ltp", "volume", "open", "high", "low", "close", "oi",
    "best_bid_price", "best_ask_price", "best_bid_qty", "best_ask_qty",
)

CANDLE_COLUMNS = ("token", "bucket_start_ms", "open", "high", "low", "close", "volume", "tick_count")

_CREATE_RAW_TICKS_SQL = """
CREATE TABLE IF NOT EXISTS raw_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_broker TEXT NOT NULL,
    token TEXT NOT NULL,
    exchange TEXT,
    symbol TEXT,
    mode INTEGER,
    sequence INTEGER,
    timestamp_ms INTEGER NOT NULL,
    ltp REAL NOT NULL,
    volume INTEGER,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    oi INTEGER,
    best_bid_price REAL,
    best_ask_price REAL,
    best_bid_qty INTEGER,
    best_ask_qty INTEGER,
    UNIQUE(token, timestamp_ms, sequence)
)
"""

_CREATE_CANDLES_SQL = """
CREATE TABLE IF NOT EXISTS candles_5m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    bucket_start_ms INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER,
    tick_count INTEGER,
    UNIQUE(token, bucket_start_ms)
)
"""

_CREATE_RAW_TICKS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_raw_ticks_token_ts ON raw_ticks(token, timestamp_ms)"
)
_CREATE_CANDLES_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_candles_token_bucket ON candles_5m(token, bucket_start_ms)"
)


def _month_key_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m")


class TickStore:
    """Monthly-partitioned SQLite store for raw ticks + their 5-min candles, keyed by token."""

    def __init__(self, store_dir: str = DEFAULT_STORE_DIR):
        self.store_dir = store_dir
        os.makedirs(self.store_dir, exist_ok=True)

    def _db_path(self, month_key: str) -> str:
        return os.path.join(self.store_dir, f"ticks_{month_key}.db")

    @contextmanager
    def _connect(self, month_key: str):
        conn = sqlite3.connect(self._db_path(month_key), timeout=30)
        try:
            conn.execute(_CREATE_RAW_TICKS_SQL)
            conn.execute(_CREATE_CANDLES_SQL)
            conn.execute(_CREATE_RAW_TICKS_INDEX_SQL)
            conn.execute(_CREATE_CANDLES_INDEX_SQL)
            yield conn
        finally:
            conn.close()

    def write_ticks(self, ticks: Iterable[Dict]) -> int:
        """Insert canonical-shaped ticks (brokers/base/tick_schema.py), grouped by
        month. Duplicate (token, timestamp_ms, sequence) rows are ignored rather than
        overwritten."""
        by_month: Dict[str, List[Dict]] = {}
        for tick in ticks:
            ts = tick.get("timestamp_ms")
            if ts is None:
                continue
            by_month.setdefault(_month_key_from_ms(int(ts)), []).append(tick)

        written = 0
        for month_key, rows in by_month.items():
            with self._connect(month_key) as conn:
                cur = conn.cursor()
                placeholders = ",".join(["?"] * len(RAW_TICK_COLUMNS))
                sql = f"INSERT OR IGNORE INTO raw_ticks ({','.join(RAW_TICK_COLUMNS)}) VALUES ({placeholders})"
                for row in rows:
                    cur.execute(sql, tuple(row.get(c) for c in RAW_TICK_COLUMNS))
                conn.commit()
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return written

    def write_candles(self, candles: Iterable[Dict]) -> int:
        """Upsert 5-min candles (ohlcv_aggregator.py's Candle.as_dict() shape), grouped
        by month. A resubmitted candle for the same (token, bucket) replaces the
        earlier one — unlike ticks, a candle for an in-progress bucket is expected to
        be rewritten as later ticks extend it."""
        by_month: Dict[str, List[Dict]] = {}
        for candle in candles:
            bucket = candle.get("bucket_start_ms")
            if bucket is None:
                continue
            by_month.setdefault(_month_key_from_ms(int(bucket)), []).append(candle)

        written = 0
        for month_key, rows in by_month.items():
            with self._connect(month_key) as conn:
                cur = conn.cursor()
                placeholders = ",".join(["?"] * len(CANDLE_COLUMNS))
                sql = f"INSERT OR REPLACE INTO candles_5m ({','.join(CANDLE_COLUMNS)}) VALUES ({placeholders})"
                for row in rows:
                    cur.execute(sql, tuple(row.get(c) for c in CANDLE_COLUMNS))
                conn.commit()
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return written

    def months_available(self) -> List[str]:
        if not os.path.isdir(self.store_dir):
            return []
        out = []
        for name in os.listdir(self.store_dir):
            if name.startswith("ticks_") and name.endswith(".db"):
                out.append(name[len("ticks_"):-len(".db")])
        return sorted(out)

    def query_ticks(self, token: str, start_ms: int, end_ms: int) -> Iterator[Dict]:
        for month_key in self.months_available():
            with self._connect(month_key) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    f"SELECT {','.join(RAW_TICK_COLUMNS)} FROM raw_ticks "
                    "WHERE token = ? AND timestamp_ms BETWEEN ? AND ? ORDER BY timestamp_ms",
                    (token, start_ms, end_ms),
                )
                for row in cur:
                    yield dict(row)

    def query_candles(self, token: str, start_ms: int, end_ms: int) -> Iterator[Dict]:
        for month_key in self.months_available():
            with self._connect(month_key) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    f"SELECT {','.join(CANDLE_COLUMNS)} FROM candles_5m "
                    "WHERE token = ? AND bucket_start_ms BETWEEN ? AND ? ORDER BY bucket_start_ms",
                    (token, start_ms, end_ms),
                )
                for row in cur:
                    yield dict(row)
