"""Pre-filter forensics.

Most evaluations never reach the scoring stack: they are rejected earlier by binary gates that
are not scored, weighted or measured anywhere. This module makes each one observable and prices
what it rejected, by entering anyway at those instants under the production ladder.

A gate earns its place if entering where it blocked is WORSE than the benchmark. Every arm
ignores the other gates, so each figure is an upper bound on what that one gate alone did.
"""
from __future__ import annotations

import datetime as _dt
import random
import statistics as _st
from collections import Counter
from typing import Dict, List, Optional, Sequence

from research.db import Book
from research.opportunities import Universe
from research.replay import Ladder, summarise

# label -> substrings that identify it in reject_reason
GATES = {
    "Time filter": ("Time filter",),
    "Chop filter": ("Chop filter",),
    "CE directional block": ("CE signal blocked", "CE blocked"),
    "PE directional block": ("PE signal blocked", "PE blocked"),
    "Pullback condition": ("No CE pullback", "No PE pullback"),
    "Warm-up": ("Warming up",),
    "Confidence gate": ("Low confidence", "Low conf"),
    "SL-streak gate": ("SL streak",),
    "Spread gate": ("Spread too wide",),
    "Premium band": ("Premium too",),
}
PRE_SCORING = ("Time filter", "Chop filter", "CE directional block", "PE directional block",
               "Pullback condition", "Warm-up")


def classify(reason: Optional[str]) -> str:
    r = (reason or "").strip()
    for label, pats in GATES.items():
        if any(p in r for p in pats):
            return label
    return "other"


def ladder_counts(book: Book, day: str) -> Dict:
    """Where evaluations die. `weighted_score IS NULL` marks the ones rejected before scoring."""
    sig = book.signals(day)
    pre, scored, conf_blocked, accepted = Counter(), 0, 0, 0
    for s in sig:
        if s["weighted_score"] is None:
            pre[classify(s["reject_reason"])] += 1
        else:
            scored += 1
            if s["accepted"]:
                accepted += 1
            elif classify(s["reject_reason"]) in ("Confidence gate", "SL-streak gate"):
                conf_blocked += 1
    return {"day": day, "total": len(sig), "pre": dict(pre), "scored": scored,
            "conf_blocked": conf_blocked, "accepted": accepted,
            "pct_scored": round(100 * scored / len(sig), 1) if sig else None}


def blocked_instants(book: Book, day: str) -> Dict[str, List[_dt.datetime]]:
    out: Dict[str, List[_dt.datetime]] = {}
    for s in book.signals(day):
        if s["weighted_score"] is not None:
            continue
        out.setdefault(classify(s["reject_reason"]), []).append(s["t"])
    return out


def permutation_p(arm: Sequence[float], base: Sequence[float], iters: int = 20000,
                  seed: int = 17) -> float:
    """One-sided p for 'the arm is worse than the benchmark'."""
    if len(arm) < 3 or len(base) < 3:
        return float("nan")
    obs = _st.mean(arm) - _st.mean(base)
    pool = list(arm) + list(base)
    n = len(arm)
    rng = random.Random(seed)
    c = 0
    for _ in range(iters):
        rng.shuffle(pool)
        if _st.mean(pool[:n]) - _st.mean(pool[n:]) <= obs:
            c += 1
    return c / iters


def benchmark(book: Book, days: Sequence[str], side: str = "CE",
              lad: Ladder = Ladder()) -> Dict:
    rows = []
    for d in days:
        u = Universe(book, d)
        rows += u.priced(u.instants(), side, lad)
    return {"rows": rows, "stats": summarise(rows)}


def gate_report(book: Book, days: Sequence[str], side: str = "CE",
                lad: Ladder = Ladder()) -> Dict:
    """Price every pre-filter against the arbitrary-timing benchmark."""
    base = benchmark(book, days, side, lad)
    base_pnl = [r["pnl"] for r in base["rows"]]
    per_gate = {}
    raw_counts = Counter()
    for d in days:
        for g, ts in blocked_instants(book, d).items():
            raw_counts[g] += len(ts)
    for gate in PRE_SCORING:
        rows = []
        for d in days:
            ts = blocked_instants(book, d).get(gate, [])
            if not ts:
                continue
            u = Universe(book, d)
            rows += u.priced(ts, side, lad)
        if len(rows) < 8:
            per_gate[gate] = {"rows": rows, "stats": summarise(rows), "p": None,
                              "raw": raw_counts.get(gate, 0), "verdict": "too few episodes"}
            continue
        st_ = summarise(rows)
        p = permutation_p([r["pnl"] for r in rows], base_pnl)
        gap = st_["exp"] - base["stats"]["exp"]
        verdict = ("protective" if gap < 0 and p < 0.10 else
                   "costly" if gap > 0 and (1 - p) < 0.10 else
                   "no measurable effect")
        per_gate[gate] = {"rows": rows, "stats": st_, "p": round(p, 4), "gap": round(gap, 2),
                          "raw": raw_counts.get(gate, 0), "verdict": verdict,
                          "per_day": {d: summarise([r for r in rows if r["day"] == d])["exp"]
                                      for d in days
                                      if len([r for r in rows if r["day"] == d]) >= 4}}
    return {"benchmark": base["stats"], "gates": per_gate, "days": list(days)}


def window_arms(book: Book, days: Sequence[str], windows: Sequence, side: str = "CE",
                lad: Ladder = Ladder()) -> List[Dict]:
    """Arbitrary entries confined to given clock windows — the test that separates a window
    effect from a selection effect."""
    out = []
    for label, a, b in windows:
        rows = []
        for d in days:
            u = Universe(book, d, start=f"{a}:00", end=f"{b}:00")
            rows += u.priced(u.instants(), side, lad)
        if rows:
            out.append({"window": label, "stats": summarise(rows), "rows": rows,
                        "per_day": {d: summarise([r for r in rows if r["day"] == d])["exp"]
                                    for d in days
                                    if len([r for r in rows if r["day"] == d]) >= 3}})
    return out
