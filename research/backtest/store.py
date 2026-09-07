"""Where imported candles land, with a receipt for every request and a row for every hole.

Three rules, inherited from research/visual/schema.py and enforced here:

  1. NO FABRICATION. A minute the source did not return is never interpolated,
     forward-filled or averaged into existence. It is written to `gaps` and the
     `candles` table simply has no row for it. Consumers that need continuity must
     ask for it explicitly and will be told where the discontinuities are.

  2. EVERY ROW CARRIES ITS SOURCE. `candles.source` is part of the primary key, so
     the same minute fetched from Angel One and from Upstox coexists as two rows
     and can be compared, rather than one silently overwriting the other.

  3. EVERY FETCH LEAVES A RECEIPT. `fetch_runs` records what was asked for, what
     came back, when, and — for the SmartAPI 30-day clamp — whether the answer was
     narrower than the question.

The database is `data/historical/candles.db`, which the repository's .gitignore
already excludes via the global `*.db` rule.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_ROOT, "data", "historical")
DB_PATH = os.path.join(DATA_DIR, "candles.db")

SCHEMA_VERSION = 1

# NSE regular session: 375 one-minute bars, 09:15 through 15:29 inclusive.
SESSION_OPEN = _dt.time(9, 15)
SESSION_CLOSE = _dt.time(15, 30)
BARS_PER_SESSION = 375

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per HTTP/SDK request. The audit trail for every candle below.
CREATE TABLE IF NOT EXISTS fetch_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    endpoint_url    TEXT NOT NULL,
    instrument_key  TEXT NOT NULL,
    symbol          TEXT,
    interval        TEXT NOT NULL,
    requested_from  TEXT NOT NULL,
    requested_to    TEXT NOT NULL,
    returned_from   TEXT,
    returned_to     TEXT,
    rows_returned   INTEGER NOT NULL,
    clamped         INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    fetched_at_utc  TEXT NOT NULL
);

-- The bars themselves. `source` is in the key on purpose: two vendors' views of
-- the same minute are two rows, so they can be compared instead of colliding.
CREATE TABLE IF NOT EXISTS candles (
    instrument_key  TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    interval        TEXT NOT NULL,
    epoch           INTEGER NOT NULL,
    ts_ist          TEXT NOT NULL,
    session_date    TEXT NOT NULL,
    open            REAL NOT NULL,
    high            REAL NOT NULL,
    low             REAL NOT NULL,
    close           REAL NOT NULL,
    volume          INTEGER,
    oi              INTEGER,
    source          TEXT NOT NULL,
    run_id          INTEGER,
    PRIMARY KEY (instrument_key, interval, epoch, source)
);
CREATE INDEX IF NOT EXISTS ix_candles_day
    ON candles (source, interval, session_date, instrument_key);

-- Every minute of a trading session the source did not return. Written, never filled.
CREATE TABLE IF NOT EXISTS gaps (
    instrument_key  TEXT NOT NULL,
    interval        TEXT NOT NULL,
    source          TEXT NOT NULL,
    session_date    TEXT NOT NULL,
    expected_bars   INTEGER NOT NULL,
    actual_bars     INTEGER NOT NULL,
    missing_minutes TEXT NOT NULL,   -- JSON list of HH:MM, truncated with a count
    detected_at_utc TEXT NOT NULL,
    PRIMARY KEY (instrument_key, interval, source, session_date)
);

-- Tradable contracts, as resolved from an instrument master at import time.
CREATE TABLE IF NOT EXISTS instruments (
    instrument_key  TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    kind            TEXT NOT NULL,      -- INDEX | CE | PE
    strike          REAL,
    expiry          TEXT,
    lot_size        INTEGER,
    tick_size       REAL,
    source          TEXT NOT NULL,
    fetched_at_utc  TEXT NOT NULL
);
"""

# Field-level provenance for what this package imports, in the vocabulary of
# research/provenance.py. Vendor OHLCV is a REAL exchange record; everything this
# package derives from it is RECONSTRUCTED; anything absent stays MISSING.
PROVENANCE = {
    "spot_ohlc":   ("real", "exchange 1-minute OHLC via Angel One SmartAPI getCandleData; "
                            "independently corroborated against Upstox and Yahoo"),
    "option_ohlc": ("real", "exchange 1-minute OHLC for the option contract, same endpoint; "
                            "only for contracts still listed — expired weeklies are unreachable"),
    "spot_volume": ("missing", "the index has no traded volume; the feed returns 0 and it "
                               "means 'not applicable', not 'no trades'"),
    "option_volume": ("real", "traded contracts in the minute, from the exchange"),
    "oi":          ("missing", "getCandleData carries no open interest field at any interval"),
    "bid":         ("missing", "no historical book at any granularity from any source reached"),
    "ask":         ("missing", "same"),
    "spread":      ("missing", "unmeasurable historically; the backtest charges a modelled "
                               "slippage instead and labels it as an assumption, not a reading"),
    "candles_5m":  ("reconstructed", "aggregated here from the 1-minute bars, not fetched"),
}


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('provenance', ?)",
                (json.dumps(PROVENANCE),))
    con.commit()
    return con


def record_run(con: sqlite3.Connection, receipt: Dict, symbol: str = "") -> int:
    cur = con.execute(
        """INSERT INTO fetch_runs
           (source, endpoint_url, instrument_key, symbol, interval, requested_from,
            requested_to, returned_from, returned_to, rows_returned, clamped, error,
            fetched_at_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (receipt["source"], receipt["endpoint_url"], receipt["instrument_key"], symbol,
         receipt["interval"], receipt["requested_from"], receipt["requested_to"],
         receipt.get("returned_from"), receipt.get("returned_to"),
         receipt.get("rows_returned", 0), int(bool(receipt.get("clamped"))),
         receipt.get("error"), receipt["fetched_at_utc"]))
    con.commit()
    return cur.lastrowid


def write_candles(con: sqlite3.Connection, instrument_key: str, symbol: str, interval: str,
                  bars: Sequence[Dict], source: str, run_id: Optional[int] = None) -> int:
    rows = []
    for b in bars:
        ts = b["ts"].astimezone(IST)
        rows.append((instrument_key, symbol, interval, b["epoch"], ts.isoformat(),
                     ts.date().isoformat(), b["open"], b["high"], b["low"], b["close"],
                     b.get("volume"), b.get("oi"), source, run_id))
    con.executemany(
        """INSERT OR IGNORE INTO candles
           (instrument_key, symbol, interval, epoch, ts_ist, session_date,
            open, high, low, close, volume, oi, source, run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    return len(rows)


def write_instruments(con: sqlite3.Connection, instruments: Iterable[Dict], source: str) -> int:
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    rows = [(i["instrument_key"], i["symbol"], i["kind"], i.get("strike"),
             i.get("expiry"), i.get("lot_size"), i.get("tick_size"), source, now)
            for i in instruments]
    con.executemany(
        """INSERT OR REPLACE INTO instruments
           (instrument_key, symbol, kind, strike, expiry, lot_size, tick_size,
            source, fetched_at_utc) VALUES (?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    return len(rows)


def session_minutes() -> List[str]:
    """The 375 HH:MM labels of a full NSE session."""
    base = _dt.datetime(2000, 1, 1, SESSION_OPEN.hour, SESSION_OPEN.minute)
    return [(base + _dt.timedelta(minutes=i)).strftime("%H:%M") for i in range(BARS_PER_SESSION)]


def detect_gaps(con: sqlite3.Connection, instrument_key: str, interval: str, source: str,
                max_listed: int = 40) -> List[Dict]:
    """Record, per session present in the data, which session minutes are absent.

    Only days the source returned SOMETHING are examined. A day with no rows at all
    is not a gap in this sense — it is either a holiday or a day the contract was
    not listed, and this function has no basis to tell those apart, so it declines
    to guess. `research/backtest/fetch.py` reports the day-level coverage instead.
    """
    if interval != "1m":
        return []
    grid = session_minutes()
    found: Dict[str, set] = {}
    for r in con.execute(
            """SELECT session_date, ts_ist FROM candles
               WHERE instrument_key=? AND interval=? AND source=?""",
            (instrument_key, interval, source)):
        found.setdefault(r["session_date"], set()).add(r["ts_ist"][11:16])
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    # Recomputed from scratch every time. A day that was short because of the
    # SmartAPI row cap and has since been refetched whole must stop being a gap;
    # leaving a stale row would keep asserting a hole that no longer exists.
    con.execute("DELETE FROM gaps WHERE instrument_key=? AND interval=? AND source=?",
                (instrument_key, interval, source))
    out = []
    for day in sorted(found):
        missing = [m for m in grid if m not in found[day]]
        if not missing:
            continue
        listed = missing[:max_listed]
        payload = json.dumps({"count": len(missing), "first": listed,
                              "truncated": len(missing) > max_listed})
        con.execute(
            """INSERT OR REPLACE INTO gaps
               (instrument_key, interval, source, session_date, expected_bars,
                actual_bars, missing_minutes, detected_at_utc) VALUES (?,?,?,?,?,?,?,?)""",
            (instrument_key, interval, source, day, BARS_PER_SESSION,
             len(found[day]), payload, now))
        out.append({"session_date": day, "missing": len(missing),
                    "actual": len(found[day])})
    con.commit()
    return out


# ── reading back ─────────────────────────────────────────────────────────────

def load_candles(con: sqlite3.Connection, instrument_key: str, source: str,
                 interval: str = "1m", session_date: Optional[str] = None,
                 frm: Optional[str] = None, to: Optional[str] = None) -> List[Dict]:
    q = ("SELECT * FROM candles WHERE instrument_key=? AND source=? AND interval=?")
    args: List = [instrument_key, source, interval]
    if session_date:
        q += " AND session_date=?"
        args.append(session_date)
    if frm:
        q += " AND session_date>=?"
        args.append(frm)
    if to:
        q += " AND session_date<=?"
        args.append(to)
    q += " ORDER BY epoch"
    return [dict(r) for r in con.execute(q, args)]


def sessions(con: sqlite3.Connection, instrument_key: str, source: str,
             interval: str = "1m") -> List[str]:
    return [r[0] for r in con.execute(
        """SELECT DISTINCT session_date FROM candles
           WHERE instrument_key=? AND source=? AND interval=? ORDER BY session_date""",
        (instrument_key, source, interval))]


def aggregate(bars: Sequence[Dict], minutes: int) -> List[Dict]:
    """1-minute bars -> N-minute bars, RECONSTRUCTED (see PROVENANCE).

    Buckets are aligned to the wall clock, not to the first bar, so a session that
    starts late still lands on the same 09:15/09:20/... grid the live strategy
    uses. A bucket is emitted from whatever minutes are present; it is never
    padded, and a bucket with no minutes is simply absent.
    """
    out: List[Dict] = []
    cur_key = None
    for b in bars:
        ts = _dt.datetime.fromisoformat(b["ts_ist"]) if isinstance(b.get("ts_ist"), str) else b["ts"]
        key = ts.replace(minute=ts.minute - (ts.minute % minutes), second=0, microsecond=0)
        if key != cur_key:
            out.append({"timestamp": key.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                        "open": b["open"], "high": b["high"], "low": b["low"],
                        "close": b["close"], "volume": b.get("volume") or 0,
                        "bars": 1})
            cur_key = key
        else:
            c = out[-1]
            c["high"] = max(c["high"], b["high"])
            c["low"] = min(c["low"], b["low"])
            c["close"] = b["close"]
            c["volume"] += (b.get("volume") or 0)
            c["bars"] += 1
    return out
