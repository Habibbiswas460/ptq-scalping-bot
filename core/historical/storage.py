"""Canonical historical-data storage: one SQLite file per calendar month.

Per the approved plan (Section 5): monthly files keep individual DBs a
manageable size while keeping the file count small, mirror the live
core/services/database.py `ticks` table's indexing pattern
(symbol, timestamp), and are queried one range at a time rather than
loaded wholesale into memory — the loader in this module streams rows via
a generator, it never materializes a full 6-month range as a list.

This is explicitly a first pass per the plan: SQLite here, with room left
for a measured Parquet/columnar comparison once real, representative data
volume exists. Nothing here is a final architecture decision.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterable, Iterator, List, Optional

from core.historical.schema import CANONICAL_COLUMNS

DEFAULT_STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "historical", "canonical")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS historical_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expiry TEXT,
    strike INTEGER,
    ltp REAL NOT NULL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    oi INTEGER,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    iv REAL,
    spot_ref REAL,
    UNIQUE(timestamp, symbol)
)
"""
_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_historical_symbol_timestamp "
    "ON historical_ticks(symbol, timestamp)"
)


def _month_key(date_str: str) -> str:
    """'2026-08-14' -> '2026-08'. Accepts a date or datetime string."""
    return date_str[:7]


def _db_path_for_month(month_key: str, store_dir: str = DEFAULT_STORE_DIR) -> str:
    return os.path.join(store_dir, f"historical_{month_key}.db")


class HistoricalStore:
    """Monthly-partitioned canonical historical-tick store."""

    def __init__(self, store_dir: str = DEFAULT_STORE_DIR):
        self.store_dir = store_dir
        os.makedirs(self.store_dir, exist_ok=True)

    def _db_path(self, month_key: str) -> str:
        return _db_path_for_month(month_key, self.store_dir)

    @contextmanager
    def _connect(self, month_key: str):
        path = self._db_path(month_key)
        conn = sqlite3.connect(path, timeout=30)
        try:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            yield conn
        finally:
            conn.close()

    def write_rows(self, rows: Iterable[Dict]) -> int:
        """Insert canonical rows, grouped by month so each row lands in its
        correct monthly file. Duplicate (timestamp, symbol) rows are
        rejected by the UNIQUE constraint rather than silently overwritten —
        callers that intend to re-ingest a corrected file should delete the
        affected month's DB explicitly first."""
        by_month: Dict[str, List[Dict]] = {}
        for row in rows:
            month_key = _month_key(row["timestamp"])
            by_month.setdefault(month_key, []).append(row)

        written = 0
        for month_key, month_rows in by_month.items():
            with self._connect(month_key) as conn:
                cur = conn.cursor()
                cols = CANONICAL_COLUMNS
                placeholders = ",".join(["?"] * len(cols))
                sql = f"INSERT OR IGNORE INTO historical_ticks ({','.join(cols)}) VALUES ({placeholders})"
                for row in month_rows:
                    cur.execute(sql, tuple(row.get(c) for c in cols))
                conn.commit()
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return written

    def months_available(self) -> List[str]:
        if not os.path.isdir(self.store_dir):
            return []
        out = []
        for name in os.listdir(self.store_dir):
            if name.startswith("historical_") and name.endswith(".db"):
                out.append(name[len("historical_"):-len(".db")])
        return sorted(out)

    def query_range(
        self,
        start_date: str,
        end_date: str,
        symbols: Optional[List[str]] = None,
    ) -> Iterator[Dict]:
        """Stream rows for [start_date, end_date] (inclusive, 'YYYY-MM-DD')
        across whichever monthly files overlap the range, one month's
        connection open at a time — never loads the full range into memory
        at once."""
        start_month = _month_key(start_date)
        end_month = _month_key(end_date)
        for month_key in self.months_available():
            if month_key < start_month or month_key > end_month:
                continue
            with self._connect(month_key) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                where = "WHERE date(timestamp) BETWEEN ? AND ?"
                params: List = [start_date, end_date]
                if symbols:
                    placeholders = ",".join(["?"] * len(symbols))
                    where += f" AND symbol IN ({placeholders})"
                    params.extend(symbols)
                cur.execute(
                    f"SELECT {','.join(CANONICAL_COLUMNS)} FROM historical_ticks "
                    f"{where} ORDER BY timestamp",
                    params,
                )
                for row in cur:
                    yield dict(row)

    def coverage_dates(self) -> List[str]:
        """Distinct trading dates present anywhere in the store."""
        dates = set()
        for month_key in self.months_available():
            with self._connect(month_key) as conn:
                cur = conn.execute("SELECT DISTINCT date(timestamp) FROM historical_ticks")
                dates.update(r[0] for r in cur.fetchall() if r[0])
        return sorted(dates)

    def row_count(self) -> int:
        total = 0
        for month_key in self.months_available():
            with self._connect(month_key) as conn:
                total += conn.execute("SELECT COUNT(*) FROM historical_ticks").fetchone()[0]
        return total
