"""Session model: discovery, loading, derived series and causal feature access.

Two eras load into one shape:
  TICK  sessions (2026-09-02 onward) have real option + spot ticks.
  COARSE sessions have only the per-evaluation spot samples inside
         dvf_signals.indicators_snapshot['close'], and only from 09:45 because the strategy's
         old hard-coded opening block returned before writing a snapshot.

Nothing here resamples away detail: candles at every timeframe are derived from the tick
series on demand, and the tick series stays available underneath.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import statistics as _st
from collections import Counter, deque
from typing import Dict, List, Optional, Sequence, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "core", "data", "trades.db")
LOT = 65
TIMEFRAMES = (("10s", 10), ("30s", 30), ("1m", 60), ("5m", 300))


def parse_ts(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(str(s).split(".")[0].replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")


# ───────────────────────────── loading ─────────────────────────────
class Book:
    def __init__(self, db: str = DB_PATH):
        self.con = sqlite3.connect(db)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self._cache: Dict = {}

    # -- discovery ---------------------------------------------------
    def sessions(self) -> List[Dict]:
        """Every session with any usable market context, newest last."""
        days = set()
        for q in ("SELECT DISTINCT date(timestamp) FROM ticks",
                  "SELECT DISTINCT date(timestamp) FROM dvf_signals",
                  "SELECT DISTINCT date(entry_time) FROM trades"):
            days |= {r[0] for r in self.cur.execute(q) if r[0]}
        out = []
        for d in sorted(days):
            n_tick = self.cur.execute("SELECT count(*) FROM ticks WHERE date(timestamp)=?", (d,)).fetchone()[0]
            n_sig = self.cur.execute("SELECT count(*) FROM dvf_signals WHERE date(timestamp)=?", (d,)).fetchone()[0]
            n_tr = self.cur.execute("SELECT count(*) FROM trades WHERE date(entry_time)=?", (d,)).fetchone()[0]
            if not (n_tick or n_sig):
                kind = "trades-only"
            elif n_tick:
                kind = "tick"
            else:
                kind = "coarse"
            out.append({"day": d, "kind": kind, "n_ticks": n_tick, "n_signals": n_sig, "n_trades": n_tr})
        return out

    # -- series ------------------------------------------------------
    def spot(self, day: str) -> Tuple[List[Tuple[_dt.datetime, float]], str]:
        """(series, source). Tick spot when available, else the coarse dvf close series."""
        key = ("spot", day)
        if key in self._cache:
            return self._cache[key]
        rows = self.cur.execute(
            "SELECT timestamp, spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 "
            "ORDER BY timestamp, id", (day,)).fetchall()
        if rows:
            seen, ser = set(), []
            for ts, p in rows:                       # second-resolution: keep the first print
                d = parse_ts(ts)
                if d not in seen:
                    seen.add(d)
                    ser.append((d, float(p)))
            res = (ser, "tick")
        else:
            ser, seen = [], set()
            for ts, blob in self.cur.execute(
                    "SELECT timestamp, indicators_snapshot FROM dvf_signals WHERE date(timestamp)=? "
                    "ORDER BY timestamp", (day,)):
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
        self._cache[key] = res
        return res

    def option_symbols(self, day: str) -> List[Tuple[str, int]]:
        return [(r[0], r[1]) for r in self.cur.execute(
            "SELECT symbol, count(*) FROM ticks WHERE date(timestamp)=? GROUP BY symbol "
            "ORDER BY 2 DESC", (day,))]

    def option(self, symbol: str, day: str) -> List[Tuple[_dt.datetime, float]]:
        key = ("opt", symbol, day)
        if key not in self._cache:
            self._cache[key] = [(parse_ts(t), float(p)) for t, p in self.cur.execute(
                "SELECT timestamp, ltp FROM ticks WHERE symbol=? AND date(timestamp)=? "
                "ORDER BY timestamp, id", (symbol, day))]
        return self._cache[key]

    def trades(self, day: Optional[str] = None) -> List[Dict]:
        q = ("SELECT * FROM trades" + (" WHERE date(entry_time)=?" if day else "") +
             " ORDER BY entry_time")
        rows = self.cur.execute(q, (day,) if day else ()).fetchall()
        return [dict(r) for r in rows]

    def signals(self, day: str) -> List[Dict]:
        """dvf_signals joined with the plain signals row, snapshots parsed."""
        key = ("sig", day)
        if key in self._cache:
            return self._cache[key]
        out = []
        for r in self.cur.execute(
                "SELECT d.timestamp, d.weighted_score, d.confidence, d.accepted, d.reject_reason, "
                "       d.indicators_snapshot, d.score_breakdown, d.confidence_breakdown, "
                "       d.market_quality_score, d.market_quality_grade, d.regime, d.direction "
                "FROM dvf_signals d WHERE date(d.timestamp)=? ORDER BY d.timestamp", (day,)):
            d = dict(r)
            for k in ("indicators_snapshot", "score_breakdown", "confidence_breakdown"):
                try:
                    d[k] = json.loads(d[k]) if d[k] else {}
                except Exception:
                    d[k] = {}
            d["t"] = parse_ts(d["timestamp"])
            out.append(d)
        self._cache[key] = out
        return out


# ───────────────────────── derived series ─────────────────────────
def candles(series: Sequence[Tuple[_dt.datetime, float]], seconds: int,
            upto: Optional[_dt.datetime] = None) -> List[Dict]:
    """OHLC derived from the tick series. `upto` builds the final bar from ticks at or before
    that instant only — the partial bar an entry actually saw, with no post-entry ticks."""
    out: List[Dict] = []
    if not series:
        return out
    origin = series[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    cur_key = None
    for t, p in series:
        if upto is not None and t > upto:
            break
        k = int((t - origin).total_seconds()) // seconds
        if k != cur_key:
            out.append({"t": origin + _dt.timedelta(seconds=k * seconds),
                        "o": p, "h": p, "l": p, "c": p, "n": 1, "partial": False})
            cur_key = k
        else:
            b = out[-1]
            b["h"] = max(b["h"], p); b["l"] = min(b["l"], p); b["c"] = p; b["n"] += 1
    if upto is not None and out:
        out[-1]["partial"] = True
    return out


def legs(series: Sequence[Tuple[_dt.datetime, float]], threshold: float) -> List[Dict]:
    """Zigzag swing legs: a leg pivot->extreme is confirmed once price retraces `threshold`
    from that extreme and the leg itself is at least `threshold` long."""
    out: List[Dict] = []
    if len(series) < 2:
        return out
    pivot = hi = lo = series[0]
    for t, p in series[1:]:
        if p > hi[1]:
            hi = (t, p)
        if p < lo[1]:
            lo = (t, p)
        if hi[1] - p >= threshold and hi[1] - pivot[1] >= threshold and hi[0] > pivot[0]:
            out.append(_leg(pivot, hi, series))
            pivot = hi; hi = lo = (t, p); continue
        if p - lo[1] >= threshold and pivot[1] - lo[1] >= threshold and lo[0] > pivot[0]:
            out.append(_leg(pivot, lo, series))
            pivot = lo; hi = lo = (t, p)
    return out


def _leg(a, b, series) -> Dict:
    move = round(b[1] - a[1], 2)
    dur = (b[0] - a[0]).total_seconds()
    seg = [p for t, p in series if a[0] <= t <= b[0]]
    vel = round(abs(move) / (dur / 60.0), 2) if dur > 0 else 0.0
    return {"start": a[0], "end": b[0], "move": move, "dur_min": round(dur / 60.0, 1),
            "dir": "UP" if move > 0 else "DOWN", "vel_ppm": vel,
            "hi": max(seg) if seg else b[1], "lo": min(seg) if seg else b[1]}


def max_move(series: Sequence[Tuple[_dt.datetime, float]], seconds: int) -> Dict:
    """Largest up and down excursion inside any rolling window of `seconds`."""
    best_up = best_dn = 0.0
    at_up = at_dn = None
    mins: deque = deque(); maxs: deque = deque()
    j = 0
    for i, (t, p) in enumerate(series):
        while mins and series[mins[-1]][1] >= p: mins.pop()
        mins.append(i)
        while maxs and series[maxs[-1]][1] <= p: maxs.pop()
        maxs.append(i)
        while (t - series[j][0]).total_seconds() > seconds:
            j += 1
            if mins[0] < j: mins.popleft()
            if maxs[0] < j: maxs.popleft()
        up = p - series[mins[0]][1]
        dn = series[maxs[0]][1] - p
        if up > best_up: best_up, at_up = up, (series[mins[0]][0], t)
        if dn > best_dn: best_dn, at_dn = dn, (series[maxs[0]][0], t)
    return {"up": round(best_up, 2), "up_at": at_up,
            "down": round(best_dn, 2), "down_at": at_dn}


def window(series: Sequence[Tuple[_dt.datetime, float]], a: _dt.datetime,
           b: _dt.datetime) -> List[float]:
    return [p for t, p in series if a < t <= b]


def as_of(series: Sequence[Tuple[_dt.datetime, float]], t: _dt.datetime,
          lookback_sec: int) -> List[float]:
    """Strictly causal read: nothing after `t` can be returned."""
    lo = t - _dt.timedelta(seconds=lookback_sec)
    return [p for ts, p in series if lo <= ts <= t]


def nearest_before(series: Sequence[Tuple[_dt.datetime, float]], t: _dt.datetime,
                   tol_sec: int = 5) -> Optional[float]:
    best = None
    for ts, p in series:
        if ts > t:
            break
        best = (ts, p)
    if best and (t - best[0]).total_seconds() <= tol_sec:
        return best[1]
    return best[1] if best else None


# ───────────────────────── trade metrics ─────────────────────────
def available_move(opt: Sequence, spot: Sequence, tr: Dict,
                   horizons_sec=(30, 60, 180, 300, 600)) -> Dict:
    """Movement offered AFTER entry, measured from ticks over fixed horizons and therefore
    NOT truncated by the exit the way the stored mfe column is."""
    e = parse_ts(tr["entry_time"])
    sgn = 1 if tr["direction"] == "CE" else -1
    s0 = nearest_before(spot, e)
    out = {}
    for h in horizons_sec:
        b = e + _dt.timedelta(seconds=h)
        ow, sw = window(opt, e, b), window(spot, e, b)
        out[f"oMFE_{h}"] = round(max(ow) - tr["entry_price"], 2) if ow else None
        out[f"oMAE_{h}"] = round(min(ow) - tr["entry_price"], 2) if ow else None
        if sw and s0 is not None:
            fav = [(p - s0) * sgn for p in sw]
            out[f"sMFE_{h}"] = round(max(fav), 2)
            out[f"sMAE_{h}"] = round(min(fav), 2)
        else:
            out[f"sMFE_{h}"] = out[f"sMAE_{h}"] = None
    out["spot_at_entry"] = s0
    return out


def capture(tr: Dict, avail: Dict, horizon: int = 180) -> Dict:
    """The cascade: spot offered -> option offered -> captured, with both ratios."""
    s = avail.get(f"sMFE_{horizon}")
    o = avail.get(f"oMFE_{horizon}")
    got = round(tr["exit_price"] - tr["entry_price"], 2)
    return {
        "spot_avail": s, "opt_avail": o, "captured": got,
        "transmission": round(o / s, 3) if (s and o is not None and s > 0) else None,
        "capture_ratio": round(got / o, 3) if (o and o > 0) else None,
    }


def transmission_regression(opt: Sequence, spot_by_ts: Dict, horizon_sec: int) -> Optional[Dict]:
    """Realised delta as the slope of d(option) on d(spot) through the origin."""
    xs, ys = [], []
    n = len(opt)
    j = 0
    for i in range(n):
        while j < n and (opt[j][0] - opt[i][0]).total_seconds() < horizon_sec:
            j += 1
        if j >= n:
            break
        s0, s1 = spot_by_ts.get(opt[i][0]), spot_by_ts.get(opt[j][0])
        if s0 is None or s1 is None:
            continue
        dx = s1 - s0
        if dx == 0:
            continue
        xs.append(dx); ys.append(opt[j][1] - opt[i][1])
    if len(xs) < 30:
        return None
    beta = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    ss_res = sum((y - beta * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum(y * y for y in ys)
    return {"n": len(xs), "beta": round(beta, 3),
            "r2": round(1 - ss_res / ss_tot, 3) if ss_tot else 0.0,
            "med_dspot": round(_st.median([abs(x) for x in xs]), 2),
            "med_dopt": round(_st.median([abs(y) for y in ys]), 2)}
