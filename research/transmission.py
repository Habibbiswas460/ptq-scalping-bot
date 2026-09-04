"""Spot → option transmission.

Answers "the market moved X, why did the option move only Y" by measuring the realised delta
directly: regress the option's change on spot's change through the origin, at every horizon
the strategy might operate on. Residual and R² are reported alongside, because a slope without
its R² hides how much of the option's movement spot does not explain at all.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import Book

HORIZONS = ((10, "10s"), (30, "30s"), (60, "1m"), (180, "3m"), (300, "5m"), (600, "10m"))


def regress(opt: Sequence[Tuple], spot_by_ts: Dict, horizon_sec: int,
            min_n: int = 30) -> Optional[Dict]:
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
        xs.append(dx)
        ys.append(opt[j][1] - opt[i][1])
    if len(xs) < min_n:
        return None
    beta = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    resid = [y - beta * x for x, y in zip(xs, ys)]
    ss_res = sum(r * r for r in resid)
    ss_tot = sum(y * y for y in ys)
    return {"n": len(xs), "beta": round(beta, 3),
            "r2": round(1 - ss_res / ss_tot, 3) if ss_tot else 0.0,
            "resid_sd": round(_st.pstdev(resid), 3) if len(resid) > 1 else 0.0,
            "med_dspot": round(_st.median([abs(x) for x in xs]), 2),
            "med_dopt": round(_st.median([abs(y) for y in ys]), 2)}


def session_transmission(book: Book, day: str, min_ticks: int = 800) -> List[Dict]:
    spot, src = book.spot(day)
    if src != "tick":
        return []
    by_ts = {t: p for t, p in spot}
    out = []
    for sym, n in book.option_symbols(day):
        if n < min_ticks:
            continue
        opt = book.option(sym, day)
        side = sym[-2:]
        for sec, lab in HORIZONS:
            r = regress(opt, by_ts, sec)
            if r:
                out.append(dict(r, symbol=sym, side=side, horizon=lab, horizon_sec=sec,
                                ticks=n, day=day))
    return out


def expected_vs_actual(prof: Dict, delta: Optional[float], horizon: int = 180) -> Optional[Dict]:
    """Theoretical option movement from the reconstructed delta against what was observed.

    delta here is Black-Scholes solved from LTP (RECONSTRUCTED), never a broker-quoted Greek.
    """
    s = (prof.get("after_spot") or {}).get(f"mfe_{horizon}")
    o = (prof.get("after_option") or {}).get(f"mfe_{horizon}")
    if s is None or o is None or delta is None:
        return None
    expected = round(abs(delta) * s, 2)
    return {"id": prof["id"], "spot_move": s, "delta": round(delta, 3),
            "expected_option": expected, "actual_option": o,
            "residual": round(o - expected, 2),
            "ratio": round(o / expected, 3) if expected else None}
