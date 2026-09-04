"""Execution and quote quality.

Kept deliberately separate from every other layer, because the bid/ask this reads is
fabricated: production falls back to `ltp ± 0.3%/2` whenever the feed's depth is missing, and
the depth block is never parsed, so the fallback fires on every tick. Nothing here may be
labelled a measured execution cost until the collector returns real quotes.
"""
from __future__ import annotations

import statistics as _st
from typing import Dict, List, Optional, Sequence

from research.db import Book
from research.replay import SYNTHETIC_SPREAD_PCT

MIDPOINT_TOL = 0.005


def quote_quality(book: Book, day: str) -> Dict:
    """Detect fabricated quotes rather than assume them: real prints do not sit exactly at the
    midpoint on every tick."""
    rows = book.cur.execute(
        "SELECT count(*), "
        "  sum(CASE WHEN bid IS NOT NULL AND ask IS NOT NULL "
        "           AND abs(ltp-(bid+ask)/2.0)<? THEN 1 ELSE 0 END), "
        "  sum(oi IS NOT NULL AND oi>0), "
        "  count(DISTINCT timestamp||symbol), "
        "  sum(symbol LIKE '%PE') "
        "FROM ticks WHERE date(timestamp)=?", (MIDPOINT_TOL, day)).fetchone()
    n, mid, oi, uniq, pe = [x or 0 for x in rows]
    if not n:
        return {"day": day, "n": 0, "verdict": "no tick data"}
    ratios = [r[0] for r in book.cur.execute(
        "SELECT round((ask-bid)/ltp,5) FROM ticks WHERE date(timestamp)=? AND ltp>0 "
        "AND bid IS NOT NULL AND ask IS NOT NULL GROUP BY 1", (day,))]
    return {"day": day, "n": n,
            "midpoint_exact_pct": round(100 * mid / n, 2),
            "distinct_spread_ratios": len(ratios),
            "oi_populated_pct": round(100 * oi / n, 2),
            "timestamp_collisions": n - uniq,
            "collision_pct": round(100 * (n - uniq) / n, 1),
            "pe_ticks": pe,
            "verdict": ("FABRICATED — every quote sits on the midpoint"
                        if 100 * mid / n >= 95 else "mixed / inspect")}


def modelled_cost(entry_ltp: float, exit_ltp: float,
                  spread_pct: float = SYNTHETIC_SPREAD_PCT) -> Dict:
    """Round-trip cost implied by an assumed spread. An assumption, never a measurement."""
    he = max(0.05, entry_ltp * spread_pct / 100.0) / 2.0
    hx = max(0.05, exit_ltp * spread_pct / 100.0) / 2.0
    return {"assumed_spread_pct": spread_pct, "entry_half": round(he, 3),
            "exit_half": round(hx, 3), "round_trip_pts": round(he + hx, 3)}


def cost_sensitivity(profiles: Sequence[Dict],
                     assumptions=(0.20, 0.30, 0.45, 0.60, 0.90)) -> List[Dict]:
    """What the same trades are worth under different spread assumptions. Since the recorded
    fills already carry the 0.3% fabrication, this reprices the difference."""
    out = []
    for pct in assumptions:
        extra = (pct - SYNTHETIC_SPREAD_PCT) / 100.0
        adj = []
        for p in profiles:
            bump = extra * (p["exit"] or 0) / 2.0 + extra * (p["entry"] or 0) / 2.0
            adj.append(p["captured"] - bump)
        if not adj:
            continue
        out.append({"assumed_spread_pct": pct,
                    "mean_captured_pts": round(_st.mean(adj), 3),
                    "winners": sum(1 for a in adj if a > 0), "n": len(adj)})
    return out


def freshness(book: Book, day: str, symbol: Optional[str] = None) -> Optional[Dict]:
    """Frozen runs and gaps in the spot series — a stale feed can masquerade as a quiet market."""
    spot, src = book.spot(day)
    if len(spot) < 10:
        return None
    unchanged = sum(1 for i in range(1, len(spot)) if spot[i][1] == spot[i - 1][1])
    runs, cur = [], 1
    longest = 1
    for i in range(1, len(spot)):
        if spot[i][1] == spot[i - 1][1]:
            cur += 1
        else:
            runs.append(cur)
            longest = max(longest, cur)
            cur = 1
    gaps = [(spot[i][0] - spot[i - 1][0]).total_seconds() for i in range(1, len(spot))]
    big = [g for g in gaps if g > 20]
    return {"source": src, "n": len(spot),
            "unchanged_pct": round(100 * unchanged / (len(spot) - 1), 1),
            "longest_frozen_run": longest,
            "median_gap_sec": round(_st.median(gaps), 1) if gaps else None,
            "gaps_over_20s": len(big),
            "largest_gap_sec": round(max(gaps), 0) if gaps else None}
