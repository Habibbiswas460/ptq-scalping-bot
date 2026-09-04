"""Scoring-stack forensics: variance, coverage, contribution, outcome.

A weight is only worth tuning if the component it multiplies actually varies, is actually
populated, and actually moves the total. This measures all three before anyone touches a
number — and separately asks whether high values of a component precede better opportunity.
"""
from __future__ import annotations

import statistics as _st
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence

from research.db import Book

DERIVED = ("raw_score", "total_weight", "normalized_score_pct", "score_input_pct",
           "raw_confidence", "final_confidence")


def component_stats(book: Book, day: str, which: str = "score_breakdown") -> List[Dict]:
    """Per-component variance, coverage and contribution to the total."""
    sig = book.signals(day)
    vals = defaultdict(list)
    nulls = Counter()
    n = 0
    for s in sig:
        d = s.get(which) or {}
        if not d:
            continue
        n += 1
        for k, v in d.items():
            if k in DERIVED:
                continue
            if isinstance(v, (int, float)):
                vals[k].append(float(v))
            else:
                nulls[k] += 1
    out = []
    for k in sorted(vals):
        xs = vals[k]
        distinct = len(set(round(x, 4) for x in xs))
        out.append({
            "component": k,
            "n": len(xs),
            "coverage": round(100 * len(xs) / n, 1) if n else 0.0,
            "distinct": distinct,
            "min": round(min(xs), 3), "max": round(max(xs), 3),
            "mean": round(_st.mean(xs), 3),
            "stdev": round(_st.pstdev(xs), 4) if len(xs) > 1 else 0.0,
            "constant": distinct <= 1,
            "near_constant": distinct > 1 and Counter(round(x, 4) for x in xs).most_common(1)[0][1] / len(xs) >= 0.95,
            "contribution": round(max(xs) - min(xs), 3),
        })
    return sorted(out, key=lambda r: (r["distinct"], r["component"]))


def score_pairs(book: Book, day: str) -> Dict:
    sig = [s for s in book.signals(day) if s["weighted_score"] is not None]
    pairs = Counter((s["weighted_score"], s["confidence"]) for s in sig)
    top = pairs.most_common(1)[0] if pairs else (None, 0)
    return {"scored": len(sig), "distinct_pairs": len(pairs),
            "top_pair": top[0], "top_share": round(100 * top[1] / len(sig), 1) if sig else None,
            "pairs": pairs.most_common(8)}


def component_outcome(book: Book, day: str, universe, component: str,
                      horizon: int = 180, side: str = "CE") -> Optional[Dict]:
    """Does a high value of this component precede more available movement?

    Uses the opportunity universe's uncensored MFE, not trade outcomes, so it measures the
    component against what the market offered rather than against the exit ladder.
    """
    sig = [s for s in book.signals(day)
           if isinstance((s.get("score_breakdown") or {}).get(component), (int, float))]
    if len(sig) < 40:
        return None
    xs = [(s["t"], float(s["score_breakdown"][component])) for s in sig]
    lo_v = min(v for _, v in xs)
    hi_v = max(v for _, v in xs)
    if hi_v == lo_v:
        return {"component": component, "verdict": "constant — nothing to correlate"}
    mid = (hi_v + lo_v) / 2
    buckets = {"high": [], "low": []}
    seen = set()
    for t, v in xs:
        key = t.replace(second=(t.second // 30) * 30)
        if key in seen:
            continue
        seen.add(key)
        cand = universe.candidate(t, side)
        if not cand:
            continue
        m = cand.get(f"opt_mfe_{horizon}")
        if m is None:
            continue
        buckets["high" if v >= mid else "low"].append(m)
    if len(buckets["high"]) < 10 or len(buckets["low"]) < 10:
        return {"component": component, "verdict": "too few paired observations"}
    return {"component": component,
            "high_n": len(buckets["high"]), "low_n": len(buckets["low"]),
            "high_mfe": round(_st.mean(buckets["high"]), 3),
            "low_mfe": round(_st.mean(buckets["low"]), 3),
            "gap": round(_st.mean(buckets["high"]) - _st.mean(buckets["low"]), 3),
            "verdict": "discriminates" if abs(_st.mean(buckets["high"]) - _st.mean(buckets["low"])) > 0.25
                       else "no separation"}


def indicator_variance(book: Book, day: str) -> List[Dict]:
    """Variance of the raw strategy inputs, upstream of any weighting."""
    sig = book.signals(day)
    vals = defaultdict(list)
    nulls = Counter()
    for s in sig:
        d = s.get("indicators_snapshot") or {}
        for k, v in d.items():
            if v is None:
                nulls[k] += 1
            elif isinstance(v, (int, float)):
                vals[k].append(float(v))
            else:
                vals[k].append(v)
    out = []
    keys = set(vals) | set(nulls)
    for k in sorted(keys):
        xs = vals.get(k, [])
        distinct = len(set(xs))
        out.append({"input": k, "n": len(xs), "null": nulls.get(k, 0),
                    "distinct": distinct,
                    "state": ("all null" if not xs else
                              "constant" if distinct <= 1 else
                              f"{distinct} values")})
    return sorted(out, key=lambda r: (r["distinct"], r["input"]))
