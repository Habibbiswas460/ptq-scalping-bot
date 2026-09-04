"""Market movement: legs, movement map, arbitrary time windows.

A leg is a first-class research object here, not a chart annotation: it carries its own
excursions, velocity and the strategy's participation, so "was the strategy present for this
move" is answerable without re-deriving anything.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from collections import deque
from typing import Dict, List, Optional, Sequence, Tuple

from research.candles import Series, window_stats
from research.db import parse_ts

DEFAULT_WINDOWS = [("09:15-09:30", "09:15", "09:30"), ("09:30-09:45", "09:30", "09:45"),
                   ("09:45-10:00", "09:45", "10:00"), ("10:00-10:30", "10:00", "10:30"),
                   ("10:30-11:00", "10:30", "11:00"), ("11:00-12:00", "11:00", "12:00"),
                   ("12:00-13:00", "12:00", "13:00"), ("13:00-14:00", "13:00", "14:00"),
                   ("14:00-15:10", "14:00", "15:10")]
LEG_THRESHOLDS = (5.0, 10.0, 15.0, 25.0)


def max_move(series: Series, seconds: int) -> Dict:
    """Largest up and down excursion inside any rolling window of `seconds`."""
    best_up = best_dn = 0.0
    at_up = at_dn = None
    mins: deque = deque()
    maxs: deque = deque()
    j = 0
    for i, (t, p) in enumerate(series):
        while mins and series[mins[-1]][1] >= p:
            mins.pop()
        mins.append(i)
        while maxs and series[maxs[-1]][1] <= p:
            maxs.pop()
        maxs.append(i)
        while (t - series[j][0]).total_seconds() > seconds:
            j += 1
            if mins[0] < j:
                mins.popleft()
            if maxs[0] < j:
                maxs.popleft()
        up = p - series[mins[0]][1]
        dn = series[maxs[0]][1] - p
        if up > best_up:
            best_up, at_up = up, (series[mins[0]][0], t)
        if dn > best_dn:
            best_dn, at_dn = dn, (series[maxs[0]][0], t)
    return {"up": round(best_up, 2), "up_at": at_up, "down": round(best_dn, 2), "down_at": at_dn}


def legs(series: Series, threshold: float) -> List[Dict]:
    """Zigzag swings. A leg pivot→extreme is confirmed only once price retraces `threshold`
    from that extreme, so a leg is never declared from information the moment did not have."""
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
            pivot = hi
            hi = lo = (t, p)
            continue
        if p - lo[1] >= threshold and pivot[1] - lo[1] >= threshold and lo[0] > pivot[0]:
            out.append(_leg(pivot, lo, series))
            pivot = lo
            hi = lo = (t, p)
    return out


def _leg(a, b, series: Series) -> Dict:
    move = round(b[1] - a[1], 2)
    dur = (b[0] - a[0]).total_seconds()
    seg = [p for t, p in series if a[0] <= t <= b[0]]
    sgn = 1 if move > 0 else -1
    mfe = round(max((p - a[1]) * sgn for p in seg), 2) if seg else 0.0
    mae = round(min((p - a[1]) * sgn for p in seg), 2) if seg else 0.0
    before = [p for t, p in series if a[0] - _dt.timedelta(minutes=10) <= t < a[0]]
    return {"start": a[0], "end": b[0], "dur_min": round(dur / 60.0, 1), "move": move,
            "dir": "UP" if move > 0 else "DOWN",
            "vel_ppm": round(abs(move) / (dur / 60.0), 2) if dur > 0 else 0.0,
            "mfe": mfe, "mae": mae,
            "vol_before": round(_st.pstdev(before), 2) if len(before) > 2 else None,
            "vol_during": round(_st.pstdev(seg), 2) if len(seg) > 2 else None,
            "hi": max(seg) if seg else b[1], "lo": min(seg) if seg else b[1]}


def annotate_participation(lg: Dict, trades: Sequence[Dict], signals: Sequence[Dict]) -> Dict:
    """Attach the strategy's behaviour inside a leg. Direction alignment is a hindsight label —
    it measures whether the entry sat on the leg's side, not whether it could have known."""
    inside = [t for t in trades if lg["start"] <= parse_ts(t["entry_time"]) <= lg["end"]]
    sig = [s for s in signals if lg["start"] <= s["t"] <= lg["end"]]
    aligned = sum(1 for t in inside
                  if (t["direction"] == "CE" and lg["move"] > 0)
                  or (t["direction"] == "PE" and lg["move"] < 0))
    blocked = sum(1 for s in sig if not s["accepted"])
    pos = None
    if inside:
        first = parse_ts(inside[0]["entry_time"])
        span = max(1.0, (lg["end"] - lg["start"]).total_seconds())
        pos = round(100 * (first - lg["start"]).total_seconds() / span, 1)
    return dict(lg, entries=len(inside), aligned=aligned, signals=len(sig), blocked=blocked,
                pnl=round(sum(t["pnl"] for t in inside), 2) if inside else None,
                entry_position_pct=pos, trade_ids=[t["id"] for t in inside])


def movement_map(series: Series, windows=None) -> List[Dict]:
    """Per-window market statistics. Windows are arbitrary; the default set is a convention,
    not a constraint."""
    out = []
    for label, a, b in (windows or DEFAULT_WINDOWS):
        seg = [(t, p) for t, p in series if a <= t.strftime("%H:%M") < b]
        if len(seg) < 3:
            out.append({"window": label, "n": len(seg), "range": None, "net": None,
                        "max_1m": None, "legs10": None})
            continue
        ps = [p for _, p in seg]
        m1 = max_move(seg, 60)
        out.append({"window": label, "n": len(seg),
                    "range": round(max(ps) - min(ps), 2),
                    "net": round(ps[-1] - ps[0], 2),
                    "max_1m": round(max(m1["up"], m1["down"]), 2),
                    "legs10": len(legs(seg, 10.0)),
                    "stdev": round(_st.pstdev(ps), 2)})
    return out


def session_profile(series: Series, trades: Sequence[Dict]) -> Dict:
    """The daily numbers the movement map is read against."""
    if len(series) < 3:
        return {}
    ps = [p for _, p in series]
    hi = max(series, key=lambda x: x[1])
    lo = min(series, key=lambda x: x[1])
    prof = {"open": ps[0], "close": ps[-1], "high": hi[1], "high_at": hi[0],
            "low": lo[1], "low_at": lo[0], "range": round(hi[1] - lo[1], 2),
            "net": round(ps[-1] - ps[0], 2), "n": len(series)}
    for sec, key in ((10, "max_10s"), (30, "max_30s"), (60, "max_1m"),
                     (300, "max_5m"), (600, "max_10m"), (1800, "max_30m")):
        m = max_move(series, sec)
        prof[key] = {"up": m["up"], "down": m["down"]}
    for thr in LEG_THRESHOLDS:
        prof[f"legs_{int(thr)}"] = len(legs(series, thr))
    ups = [l for l in legs(series, 5.0) if l["move"] > 0]
    dns = [l for l in legs(series, 5.0) if l["move"] < 0]
    prof["largest_up_leg"] = max(ups, key=lambda l: l["move"]) if ups else None
    prof["largest_down_leg"] = min(dns, key=lambda l: l["move"]) if dns else None
    return prof
