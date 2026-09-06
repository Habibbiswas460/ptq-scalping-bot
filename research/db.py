"""Data access. The only module that talks to SQLite.

Historical data is immutable here: every statement is a SELECT. Nothing in research/ writes to
the trading database, so a research bug can never corrupt a session's record.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "core", "data", "trades.db")
LOT = 65

# Rows below this are noise, not a series - the same floor session.py, execution.py and
# signals.py apply before they will read a spot series at all.
MIN_SERIES = 10


def parse_ts(s) -> _dt.datetime:
    if isinstance(s, _dt.datetime):
        return s
    return _dt.datetime.strptime(str(s).split(".")[0].replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")


class Book:
    """Read-only accessor with per-process caching of the heavy series."""

    def __init__(self, db: str = DB_PATH):
        self.path = db
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self._c: Dict = {}

    # ── discovery ────────────────────────────────────────────────────
    def sessions(self) -> List[Dict]:
        days = set()
        for q in ("SELECT DISTINCT date(timestamp) FROM ticks",
                  "SELECT DISTINCT date(timestamp) FROM dvf_signals",
                  "SELECT DISTINCT date(entry_time) FROM trades"):
            days |= {r[0] for r in self.cur.execute(q) if r[0]}
        out = []
        for d in sorted(days):
            nt = self.cur.execute("SELECT count(*) FROM ticks WHERE date(timestamp)=?", (d,)).fetchone()[0]
            ns = self.cur.execute("SELECT count(*) FROM dvf_signals WHERE date(timestamp)=?", (d,)).fetchone()[0]
            ntr = self.cur.execute("SELECT count(*) FROM trades WHERE date(entry_time)=?", (d,)).fetchone()[0]

            # A handful of rows is not a series. This used to read `"tick" if nt`, so a
            # single stray tick made a day the newest "tick session" in the book - which is
            # exactly what happened on 2026-09-06, when an accidental 38-second paper run
            # wrote one row and every consumer that asks for "the latest tick session"
            # picked a day with no evaluations and no trades. MIN_SERIES is the threshold
            # research/session.py, execution.py and signals.py already use for the same
            # question ("is there a usable series here").
            kind = ("tick" if nt >= MIN_SERIES
                    else "coarse" if ns >= MIN_SERIES
                    else "trades-only")
            if kind == "trades-only" and not ntr:
                # Nothing usable and nothing traded: not a session, however it got here.
                continue
            out.append({"day": d, "kind": kind, "n_ticks": nt, "n_signals": ns, "n_trades": ntr})
        return out

    def session_kind(self, day: str) -> str:
        for s in self.sessions():
            if s["day"] == day:
                return s["kind"]
        return "unknown"

    # ── series ───────────────────────────────────────────────────────
    def spot(self, day: str) -> Tuple[List[Tuple[_dt.datetime, float]], str]:
        """(series, provenance-source). 'tick' is a real feed series; 'coarse' is the
        per-evaluation spot samples in dvf_signals, which start at 09:45 on historical
        sessions because the strategy's opening block returned before writing a snapshot."""
        k = ("spot", day)
        if k in self._c:
            return self._c[k]
        rows = self.cur.execute(
            "SELECT timestamp, spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 "
            "ORDER BY timestamp, id", (day,)).fetchall()
        if rows:
            # Every tick, including several inside the same second. Timestamps are stored
            # to the second, so ~20% collide (5,146 of 25,055 on 2026-09-04) and 89% of
            # those pairs carry a genuinely different price. This used to keep the first of
            # each group and drop the rest, which is not a sampling choice - it loses real
            # prices, including extremes. Measured on 2026-09-04: the true range over all
            # ticks is 107.80; keeping the first gave 107.70 and keeping the last 107.35.
            # Consumers bucket, iterate or thin this series; none of them requires the
            # timestamps to be unique.
            res = ([(parse_ts(ts), float(p)) for ts, p in rows], "tick")
        else:
            seen, ser = set(), []
            for ts, blob in self.cur.execute(
                    "SELECT timestamp, indicators_snapshot FROM dvf_signals "
                    "WHERE date(timestamp)=? ORDER BY timestamp", (day,)):
                try:
                    c = json.loads(blob).get("close")
                except Exception:
                    continue
                if not c:
                    continue
                d = parse_ts(ts)
                if d not in seen:
                    seen.add(d)
                    ser.append((d, float(c)))
            res = (ser, "coarse")
        self._c[k] = res
        return res

    def option_symbols(self, day: str, side: Optional[str] = None) -> List[Tuple[str, int]]:
        q = ("SELECT symbol, count(*) FROM ticks WHERE date(timestamp)=?"
             + (" AND symbol LIKE ?" if side else "") + " GROUP BY symbol ORDER BY 2 DESC")
        args = (day, f"%{side}") if side else (day,)
        return [(r[0], r[1]) for r in self.cur.execute(q, args)]

    def option(self, symbol: str, day: str) -> List[Tuple[_dt.datetime, float]]:
        k = ("opt", symbol, day)
        if k not in self._c:
            self._c[k] = [(parse_ts(t), float(p)) for t, p in self.cur.execute(
                "SELECT timestamp, ltp FROM ticks WHERE symbol=? AND date(timestamp)=? "
                "ORDER BY timestamp, id", (symbol, day))]
        return self._c[k]

    def option_quotes(self, symbol: str, day: str) -> List[Dict]:
        """Full quote rows. bid/ask are fabricated — see provenance before using them."""
        k = ("q", symbol, day)
        if k not in self._c:
            self._c[k] = [{"t": parse_ts(r["timestamp"]), "ltp": r["ltp"], "bid": r["bid"],
                           "ask": r["ask"], "volume": r["volume"], "oi": r["oi"]}
                          for r in self.cur.execute(
                              "SELECT timestamp,ltp,bid,ask,volume,oi FROM ticks "
                              "WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp, id",
                              (symbol, day))]
        return self._c[k]

    def trades(self, day: Optional[str] = None) -> List[Dict]:
        q = "SELECT * FROM trades" + (" WHERE date(entry_time)=?" if day else "") + " ORDER BY entry_time"
        return [dict(r) for r in self.cur.execute(q, (day,) if day else ())]

    def positions(self, day: Optional[str] = None) -> List[Dict]:
        """Rows from `active_positions`, which is where the live system recorded the bracket it
        declared when a position opened. The values are real records; whether they governed the
        exit is a separate question the visual layer answers with evidence, not assumption."""
        q = ("SELECT * FROM active_positions"
             + (" WHERE date(entry_time)=?" if day else "") + " ORDER BY entry_time")
        return [dict(r) for r in self.cur.execute(q, (day,) if day else ())]

    def signals(self, day: str) -> List[Dict]:
        k = ("sig", day)
        if k in self._c:
            return self._c[k]
        out = []
        for r in self.cur.execute(
                "SELECT timestamp, weighted_score, confidence, accepted, reject_reason, direction,"
                "       indicators_snapshot, score_breakdown, confidence_breakdown,"
                "       market_quality_score, market_quality_grade, regime, session_type,"
                "       decision_id, strategy_name "
                "FROM dvf_signals WHERE date(timestamp)=? ORDER BY timestamp", (day,)):
            d = dict(r)
            for key in ("indicators_snapshot", "score_breakdown", "confidence_breakdown"):
                try:
                    d[key] = json.loads(d[key]) if d[key] else {}
                except Exception:
                    d[key] = {}
            d["t"] = parse_ts(d["timestamp"])
            out.append(d)
        self._c[k] = out
        return out
