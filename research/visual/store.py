"""The persistence layer and the read API over it.

Two classes, deliberately separated:

* `Store`  — opens the visual database read/write. Only the builder uses it.
* `Reader` — opens it read-only and returns plain dicts. The viewer, and any dashboard added
  later, use this and nothing else. That is what makes the dashboard a rendering change rather
  than a data-layer rewrite.

A session rebuild is idempotent: every row for that `session_id` is deleted and rewritten
inside one transaction, so a half-finished build can never be read as a complete one.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from typing import Dict, Iterable, List, Optional, Sequence

from research.visual.schema import ADDED_COLUMNS, DB_PATH, DDL, SCHEMA_VERSION, TABLES


def ts_str(t) -> str:
    if isinstance(t, _dt.datetime):
        return t.strftime("%Y-%m-%d %H:%M:%S")
    return str(t)[:19] if t is not None else None


def parse_ts(s):
    if s is None or isinstance(s, _dt.datetime):
        return s
    return _dt.datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")


def _jd(v) -> Optional[str]:
    return None if v is None else json.dumps(v, default=str, separators=(",", ":"))


def _jl(s):
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


class Store:
    """Read/write access to the visual database. Used by the builder only."""

    def __init__(self, path: str = DB_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(DDL)
        self.migrate()

    def migrate(self) -> List[str]:
        """Bring an existing database up to the current schema, additively.

        Only ADD COLUMN is ever issued. Nothing is dropped, renamed, retyped or back-filled:
        a value written under an earlier schema keeps its own meaning and provenance, and a
        column added today is NULL on those rows until that session is rebuilt from source.
        """
        applied = []
        for table, column, decl in ADDED_COLUMNS:
            have = {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}
            if column in have:
                continue
            self.con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            applied.append(f"{table}.{column}")
        if applied:
            self.con.commit()
        return applied

    def close(self) -> None:
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── writing ──────────────────────────────────────────────────────
    def drop_session(self, session_id: str) -> None:
        for t in TABLES:
            self.con.execute(f"DELETE FROM {t} WHERE session_id=?", (session_id,))

    def write_session(self, session_id: str, rows: Dict[str, List[Dict]]) -> Dict[str, int]:
        """Replace every record for one session, atomically. Returns rows written per table."""
        counts: Dict[str, int] = {}
        with self.con:
            self.drop_session(session_id)
            for table in reversed(TABLES):
                data = rows.get(table) or []
                if not data:
                    counts[table] = 0
                    continue
                cols = list(data[0].keys())
                sql = (f"INSERT INTO {table} ({','.join(cols)}) "
                       f"VALUES ({','.join('?' * len(cols))})")
                self.con.executemany(sql, [[r.get(c) for c in cols] for r in data])
                counts[table] = len(data)
        return counts

    def built_sessions(self) -> List[str]:
        return [r[0] for r in self.con.execute(
            "SELECT session_id FROM visual_sessions ORDER BY day")]


class Reader:
    """Read-only access to the persisted records.

    This is the whole contract a viewer or a dashboard is allowed to depend on. Nothing here
    derives a value: every number returned was computed by the builder and written down, so
    two views of the same session cannot disagree.
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"no visual records at {path} — run `python -m research.visual backfill --all`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row

    def close(self) -> None:
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _rows(self, sql: str, args: Sequence = ()) -> List[Dict]:
        return [dict(r) for r in self.con.execute(sql, args)]

    # ── discovery ────────────────────────────────────────────────────
    def sessions(self) -> List[Dict]:
        return self._rows("SELECT * FROM visual_sessions ORDER BY day")

    def session(self, session_id: str) -> Optional[Dict]:
        r = self._rows("SELECT * FROM visual_sessions WHERE session_id=?", (session_id,))
        return r[0] if r else None

    def series(self, session_id: str) -> List[Dict]:
        return self._rows(
            "SELECT * FROM visual_series WHERE session_id=? ORDER BY role, n_points DESC",
            (session_id,))

    # ── the visual records ───────────────────────────────────────────
    def candles(self, session_id: str, series: str, timeframe: str) -> List[Dict]:
        rows = self._rows(
            "SELECT * FROM visual_candles WHERE session_id=? AND series=? AND timeframe=? "
            "ORDER BY ts", (session_id, series, timeframe))
        for r in rows:
            r["t"] = parse_ts(r["ts"])
        return rows

    def coverage(self, session_id: str, timeframe: Optional[str] = None) -> List[Dict]:
        q = "SELECT * FROM visual_timeframe_coverage WHERE session_id=?"
        a: List = [session_id]
        if timeframe:
            q += " AND timeframe=?"
            a.append(timeframe)
        return self._rows(q + " ORDER BY series, timeframe", a)

    def indicators(self, session_id: str, timeframe: str = "1m",
                   field: Optional[str] = None, direction: Optional[str] = None) -> List[Dict]:
        q = "SELECT * FROM visual_indicators WHERE session_id=? AND timeframe=?"
        a: List = [session_id, timeframe]
        if field:
            q += " AND field=?"
            a.append(field)
        if direction:
            q += " AND direction=?"
            a.append(direction)
        rows = self._rows(q + " ORDER BY ts", a)
        for r in rows:
            r["t"] = parse_ts(r["ts"])
        return rows

    def indicator_fields(self, session_id: str, timeframe: str = "1m") -> List[str]:
        return [r[0] for r in self.con.execute(
            "SELECT DISTINCT field FROM visual_indicators WHERE session_id=? AND timeframe=? "
            "ORDER BY field", (session_id, timeframe))]

    def legs(self, session_id: str, threshold: Optional[float] = None) -> List[Dict]:
        q = "SELECT * FROM visual_market_legs WHERE session_id=?"
        a: List = [session_id]
        if threshold is not None:
            q += " AND threshold=?"
            a.append(threshold)
        rows = self._rows(q + " ORDER BY threshold, leg_id", a)
        for r in rows:
            r["start"] = parse_ts(r["start_ts"])
            r["end"] = parse_ts(r["end_ts"])
            r["trade_ids"] = _jl(r["trade_ids"]) if r["trade_ids"] else []
        return rows

    def trades(self, session_id: str) -> List[Dict]:
        rows = self._rows(
            "SELECT * FROM visual_trade_overlays WHERE session_id=? ORDER BY entry_ts",
            (session_id,))
        for r in rows:
            r["entry_t"] = parse_ts(r["entry_ts"])
            r["exit_t"] = parse_ts(r["exit_ts"])
            r["entry_context"] = _jl(r["entry_context"])
            r["post_entry"] = _jl(r["post_entry"])
            r["score_breakdown"] = _jl(r["score_breakdown"])
            r["confidence_breakdown"] = _jl(r["confidence_breakdown"])
            r["field_provenance"] = _jl(r.get("field_provenance"))
            r["state_at_entry"] = _jl(r.get("state_at_entry"))
        return rows

    def field_state(self, trade: Dict, field: str) -> str:
        """Provenance of one field on one trade row. A view asks this rather than assuming the
        row's state applies to every column in it."""
        return (trade.get("field_provenance") or {}).get(field, "missing")

    def signals(self, session_id: str, kind: Optional[str] = None) -> List[Dict]:
        q = "SELECT * FROM visual_signal_overlays WHERE session_id=?"
        a: List = [session_id]
        if kind:
            q += " AND kind=?"
            a.append(kind)
        rows = self._rows(q + " ORDER BY ts, row_id", a)
        for r in rows:
            r["t"] = parse_ts(r["ts"])
        return rows

    def strategy_state(self, session_id: str,
                       state_type: Optional[str] = None) -> List[Dict]:
        q = "SELECT * FROM visual_strategy_state WHERE session_id=?"
        a: List = [session_id]
        if state_type:
            q += " AND state_type=?"
            a.append(state_type)
        rows = self._rows(q + " ORDER BY start_ts, row_id", a)
        for r in rows:
            r["start"] = parse_ts(r["start_ts"])
            r["end"] = parse_ts(r["end_ts"])
        return rows

    def state_at(self, session_id: str, t) -> Dict[str, List[Dict]]:
        """States in force at `t`, read from persisted rows only.

        The as-of rule lives in `research.visual.strategy_state.state_at`; this is the reader
        path a viewer or a dashboard uses so both get the same answer from the same rows.
        """
        from research.visual.strategy_state import state_at as _at
        return _at(self.strategy_state(session_id), parse_ts(t) if isinstance(t, str) else t)

    # ── the as-of evaluation layer ───────────────────────────────────
    def _strip_posthoc(self, row: Dict) -> Dict:
        from research.visual.evaluations import POSTHOC_FIELDS
        return {k: v for k, v in row.items() if k not in POSTHOC_FIELDS}

    def as_of_evaluation(self, session_id: str, t, direction: Optional[str] = None,
                         with_context: bool = True) -> Optional[Dict]:
        """The decision in force at `t`: the last evaluation at or before it.

        The cut is made in SQL — `ts <= ?` — so rows after `t` are never fetched, not merely
        ignored. Post-hoc columns are removed before returning: which trade the evaluation
        became is not part of what was known at `t`. If `t` falls inside a recorded gap the
        answer carries `in_gap`, because the previous decision is not carried forward across a
        stretch where the strategy was not observed deciding anything.
        """
        ts = ts_str(t)
        q = ("SELECT * FROM visual_evaluations WHERE session_id=? AND ts<=?"
             + (" AND (direction IS NULL OR direction=?)" if direction else "")
             + " ORDER BY ts DESC, seq DESC LIMIT 1")
        a = [session_id, ts] + ([direction] if direction else [])
        rows = self._rows(q, a)
        if not rows:
            return None
        out = self._strip_posthoc(rows[0])
        out["t"] = parse_ts(out["ts"])
        out["in_gap"] = self.in_gap(session_id, ts)
        if with_context:
            out["context"] = _jl(self.blob(session_id, out.get("context_id")))
            out["score_breakdown"] = _jl(self.blob(session_id, out.get("score_breakdown_id")))
            out["confidence_breakdown"] = _jl(
                self.blob(session_id, out.get("confidence_breakdown_id")))
            out["reject_reason"] = self.blob(session_id, out.get("reject_reason_id"))
        return out

    def evaluation_slice(self, session_id: str, start, end,
                         direction: Optional[str] = None) -> List[Dict]:
        """Every evaluation in [start, end], in the order the live system wrote them."""
        q = ("SELECT * FROM visual_evaluations WHERE session_id=? AND ts>=? AND ts<=?"
             + (" AND direction=?" if direction else "") + " ORDER BY ts, seq")
        a = [session_id, ts_str(start), ts_str(end)] + ([direction] if direction else [])
        rows = self._rows(q, a)
        for r in rows:
            r["t"] = parse_ts(r["ts"])
        return rows

    def evaluations_for_trade(self, session_id: str, trade_id: int,
                              lead_sec: int = 60) -> Dict:
        """The evaluation a trade was linked to, plus the run-up that preceded it.

        The link itself is RECONSTRUCTED — `trades` carries no decision id — so it is reported
        with the method that produced it rather than as a fact of the source.
        """
        linked = self._rows(
            "SELECT * FROM visual_evaluations WHERE session_id=? AND posthoc_trade_id=?",
            (session_id, trade_id))
        out: Dict = {"trade_id": trade_id, "linked": None, "lead_up": [],
                     "link_provenance": "missing"}
        if not linked:
            return out
        row = linked[0]
        t = parse_ts(row["ts"])
        linked_row = self._strip_posthoc(row)
        linked_row["t"] = t
        out["linked"] = linked_row
        out["link_method"] = row["posthoc_link_method"]
        out["link_delta_sec"] = row["posthoc_link_delta_sec"]
        out["link_provenance"] = "reconstructed"
        out["lead_up"] = self.evaluation_slice(
            session_id, t - _dt.timedelta(seconds=lead_sec), t)
        return out

    def evaluation_gaps(self, session_id: str) -> List[Dict]:
        return self._rows(
            "SELECT * FROM visual_evaluation_gaps WHERE session_id=? ORDER BY start_ts",
            (session_id,))

    def in_gap(self, session_id: str, t) -> bool:
        ts = ts_str(t)
        return bool(self.con.execute(
            "SELECT 1 FROM visual_evaluation_gaps WHERE session_id=? AND start_ts<? "
            "AND end_ts>? LIMIT 1", (session_id, ts, ts)).fetchone())

    def blob(self, session_id: str, blob_id: Optional[str]) -> Optional[str]:
        if not blob_id:
            return None
        r = self.con.execute(
            "SELECT payload FROM visual_evaluation_blobs WHERE session_id=? AND blob_id=?",
            (session_id, blob_id)).fetchone()
        return r[0] if r else None

    def quality(self, session_id: str) -> List[Dict]:
        return self._rows(
            "SELECT * FROM visual_data_quality WHERE session_id=? ORDER BY state, field",
            (session_id,))

    # ── cross-session reads ──────────────────────────────────────────
    # Every method here is a SELECT across sessions. They exist so a comparison layer never
    # has to invent its own access path; the column allowed in a GROUP BY is whitelisted, so a
    # caller cannot reach a field the record does not track.
    GROUPABLE_EVALUATION_COLUMNS = (
        "session_type", "gate", "state_gate", "state_detail", "direction",
        "market_quality_grade", "floor_path", "context_provenance", "accepted",
    )

    def all_trades(self) -> List[Dict]:
        """Every trade overlay, with the kind and window of the session it belongs to."""
        rows = self._rows(
            "SELECT t.*, s.kind AS session_kind, s.spot_source, s.first_ts AS session_first_ts "
            "FROM visual_trade_overlays t JOIN visual_sessions s USING (session_id) "
            "ORDER BY t.session_id, t.trade_id")
        for r in rows:
            r["entry_t"] = parse_ts(r["entry_ts"])
            r["exit_t"] = parse_ts(r["exit_ts"])
            r["field_provenance"] = _jl(r.get("field_provenance"))
            r["state_at_entry"] = _jl(r.get("state_at_entry"))
        return rows

    def all_legs(self, threshold: Optional[float] = None) -> List[Dict]:
        q = ("SELECT l.*, s.kind AS session_kind FROM visual_market_legs l "
             "JOIN visual_sessions s USING (session_id)")
        a: List = []
        if threshold is not None:
            q += " WHERE l.threshold=?"
            a.append(threshold)
        rows = self._rows(q + " ORDER BY l.session_id, l.threshold, l.leg_id", a)
        for r in rows:
            r["start"] = parse_ts(r["start_ts"])
            r["end"] = parse_ts(r["end_ts"])
        return rows

    def all_quality(self) -> List[Dict]:
        return self._rows("SELECT q.*, s.kind AS session_kind FROM visual_data_quality q "
                          "JOIN visual_sessions s USING (session_id) ORDER BY q.field, q.session_id")

    def evaluation_counts(self, column: str, where: str = "") -> List[Dict]:
        """Per session, counts grouped by one whitelisted evaluation column."""
        if column not in self.GROUPABLE_EVALUATION_COLUMNS:
            raise ValueError(f"{column} is not a groupable evaluation column; "
                             f"allowed: {', '.join(self.GROUPABLE_EVALUATION_COLUMNS)}")
        clause = f" WHERE {where}" if where else ""
        return self._rows(
            f"SELECT session_id, {column} AS value, count(*) AS n, "
            f"sum(accepted) AS accepted, "
            f"sum(context_provenance='real') AS with_context "
            f"FROM visual_evaluations{clause} GROUP BY session_id, {column} "
            f"ORDER BY session_id, n DESC")

    def evaluations_in_window(self, start_hhmmss: str, end_hhmmss: str) -> List[Dict]:
        """Evaluations whose clock time falls in [start, end), per session."""
        return self._rows(
            "SELECT session_id, count(*) AS n, sum(accepted) AS accepted, "
            "min(ts) AS first_ts, max(ts) AS last_ts "
            "FROM visual_evaluations WHERE time(ts) >= ? AND time(ts) < ? "
            "GROUP BY session_id ORDER BY session_id", (start_hhmmss, end_hhmmss))

    def candles_in_window(self, timeframe: str, start_hhmmss: str,
                          end_hhmmss: str, series: str = "spot") -> List[Dict]:
        return self._rows(
            "SELECT session_id, count(*) AS n_bars, sum(abs(body)) AS abs_body, "
            "max(h) AS high, min(l) AS low, sum(range) AS sum_range "
            "FROM visual_candles WHERE timeframe=? AND series=? "
            "AND time(ts) >= ? AND time(ts) < ? GROUP BY session_id ORDER BY session_id",
            (timeframe, series, start_hhmmss, end_hhmmss))

    # ── convenience for a viewer ─────────────────────────────────────
    def price_series_names(self, session_id: str) -> List[str]:
        return [r["series"] for r in self.series(session_id)]

    def timeframes_present(self, session_id: str, series: str) -> List[str]:
        return [r[0] for r in self.con.execute(
            "SELECT DISTINCT timeframe FROM visual_candles WHERE session_id=? AND series=?",
            (session_id, series))]

    def stats(self) -> Dict[str, int]:
        out = {}
        for t in TABLES:
            out[t] = self.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        return out
