"""As-of-safe candle engine.

The rule this module exists to enforce: a candle used to explain a decision at time T may
contain nothing that happened after T. That is enforced structurally — `as_of()` filters the
tick series before any aggregation, and the resulting final bar is flagged `partial`. Code that
wants the completed bar has to ask for it by name.

Every timeframe is derived from the same tick series, so the views can never disagree.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from typing import Dict, List, Optional, Sequence, Tuple

TIMEFRAMES = (("10s", 10), ("30s", 30), ("1m", 60), ("5m", 300))
Series = Sequence[Tuple[_dt.datetime, float]]


def as_of(series: Series, t: _dt.datetime, lookback_sec: Optional[int] = None) -> List[Tuple]:
    """Every observation at or before `t`. Nothing later can be returned, by construction."""
    lo = t - _dt.timedelta(seconds=lookback_sec) if lookback_sec else None
    return [(ts, p) for ts, p in series if ts <= t and (lo is None or ts >= lo)]


def build(series: Series, seconds: int, upto: Optional[_dt.datetime] = None) -> List[Dict]:
    """OHLC bars with structure fields. `upto` makes the last bar the partial one an observer
    at that instant would have seen."""
    src = as_of(series, upto) if upto is not None else list(series)
    out: List[Dict] = []
    if not src:
        return out
    origin = src[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    key = None
    for t, p in src:
        k = int((t - origin).total_seconds()) // seconds
        if k != key:
            out.append({"t": origin + _dt.timedelta(seconds=k * seconds),
                        "o": p, "h": p, "l": p, "c": p, "n": 1, "partial": False,
                        "first_t": t, "last_t": t})
            key = k
        else:
            b = out[-1]
            b["h"] = max(b["h"], p)
            b["l"] = min(b["l"], p)
            b["c"] = p
            b["n"] += 1
            b["last_t"] = t
    if upto is not None:
        out[-1]["partial"] = True
    for b in out:
        _decorate(b, seconds)
    return out


def _decorate(b: Dict, seconds: int) -> None:
    rng = b["h"] - b["l"]
    body = b["c"] - b["o"]
    b["range"] = round(rng, 4)
    b["body"] = round(body, 4)
    b["upper_wick"] = round(b["h"] - max(b["o"], b["c"]), 4)
    b["lower_wick"] = round(min(b["o"], b["c"]) - b["l"], 4)
    b["dir"] = "UP" if body > 0 else ("DOWN" if body < 0 else "FLAT")
    b["body_pct"] = round(abs(body) / rng, 3) if rng else None
    b["close_pos"] = round((b["c"] - b["l"]) / rng, 3) if rng else None
    span = (b["last_t"] - b["first_t"]).total_seconds() or seconds
    b["velocity_ppm"] = round(abs(body) / (span / 60.0), 3)


def atr(bars: Sequence[Dict], period: int = 14) -> List[Optional[float]]:
    """True-range average. None until `period` bars exist — never a silent zero, because a
    zero ATR is exactly the defect that pinned the live early-cut to its tightest branch."""
    trs: List[Optional[float]] = [None]
    for i in range(1, len(bars)):
        pc = bars[i - 1]["c"]
        trs.append(max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - pc), abs(bars[i]["l"] - pc)))
    out: List[Optional[float]] = []
    for i in range(len(bars)):
        w = [x for x in trs[max(0, i - period + 1): i + 1] if x is not None]
        out.append(round(sum(w) / len(w), 4) if len(w) >= period else None)
    return out


def rolling_range(bars: Sequence[Dict], window: int = 10) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(bars)):
        w = bars[max(0, i - window + 1): i + 1]
        out.append(round(max(b["h"] for b in w) - min(b["l"] for b in w), 4) if w else None)
    return out


def frame(series: Series, upto: Optional[_dt.datetime] = None) -> Dict[str, List[Dict]]:
    """All four timeframes from one series, so views cannot disagree."""
    return {name: build(series, sec, upto) for name, sec in TIMEFRAMES}


def window_stats(series: Series, a: _dt.datetime, b: _dt.datetime) -> Optional[Dict]:
    seg = [(t, p) for t, p in series if a <= t <= b]
    if len(seg) < 2:
        return None
    ps = [p for _, p in seg]
    return {"n": len(seg), "open": ps[0], "close": ps[-1], "high": max(ps), "low": min(ps),
            "range": round(max(ps) - min(ps), 2), "net": round(ps[-1] - ps[0], 2),
            "stdev": round(_st.pstdev(ps), 3) if len(ps) > 1 else 0.0}
