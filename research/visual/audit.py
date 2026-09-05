"""Source audit — what the historical data can actually support, before anything is built.

Answers, per session and without writing anything: is it tick-complete, coarse or trades-only;
which timeframes can be reconstructed from what is there; how far CE and PE coverage reaches;
and where delta, OI and spread come from. The backfill uses this to decide what to build, and
the answer is printed rather than assumed so a thin session is never quietly charted as a
complete one.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from research import provenance as prov
from research.db import Book
from research.execution import quote_quality
from research.visual.schema import MISSING, TIMEFRAMES

# a timeframe is reconstructable when the source carries at least this many observations
# per bar on average; below it the bars exist but rest on single points
MIN_POINTS_PER_BAR = 1.0


def audit_session(book: Book, day: str) -> Dict:
    kind = book.session_kind(day)
    spot, src = book.spot(day)
    syms = book.option_symbols(day)
    ce = [(s, n) for s, n in syms if s.upper().endswith("CE")]
    pe = [(s, n) for s, n in syms if s.upper().endswith("PE")]
    sig = book.signals(day)
    trades = book.trades(day)
    q = quote_quality(book, day) or {}

    span = (spot[-1][0] - spot[0][0]).total_seconds() if len(spot) > 1 else 0.0
    tfs: Dict[str, Dict] = {}
    for tf, seconds in TIMEFRAMES:
        if not spot:
            tfs[tf] = {"state": MISSING, "bars": 0, "pts_per_bar": None}
            continue
        bars = max(1, int(span // seconds) + 1)
        tfs[tf] = {"state": "reconstructable" if len(spot) / bars >= MIN_POINTS_PER_BAR
                            else "sparse",
                   "bars": bars, "pts_per_bar": round(len(spot) / bars, 2)}

    delta_present = sum(1 for s in sig if (s.get("indicators_snapshot") or {}).get("delta") is not None)
    return {
        "day": day, "kind": kind,
        "spot_points": len(spot), "spot_source": src,
        "span_min": round(span / 60.0, 1),
        "first": spot[0][0].strftime("%H:%M:%S") if spot else None,
        "last": spot[-1][0].strftime("%H:%M:%S") if spot else None,
        "ce_symbols": len(ce), "ce_ticks": sum(n for _, n in ce),
        "pe_symbols": len(pe), "pe_ticks": sum(n for _, n in pe),
        "signals": len(sig), "trades": len(trades),
        "timeframes": tfs,
        "delta_source": (f"{prov.state('delta')} · {delta_present:,}/{len(sig):,} evaluations"
                         if sig else "no evaluations"),
        "oi_source": (f"{prov.state('oi')} · {q.get('oi_populated_pct', 0)}% of tick rows"
                      if q.get("n") else prov.state("oi")),
        "spread_source": (f"{prov.state('spread')} · {q.get('midpoint_exact_pct')}% midpoint-exact"
                          if q.get("n") else prov.state("spread")),
    }


def audit_all(book: Book, days: Optional[Sequence[str]] = None) -> List[Dict]:
    targets = list(days) if days else [s["day"] for s in book.sessions()]
    return [audit_session(book, d) for d in targets]


def buildable(rows: Sequence[Dict]) -> List[str]:
    """Sessions with something to draw: a spot series, trades, or both."""
    return [r["day"] for r in rows if r["spot_points"] or r["trades"]]


def print_audit(rows: Sequence[Dict]) -> None:
    print(f"{'session':<12} {'kind':<12} {'spot':>7} {'src':<8} {'window':<14} "
          f"{'CE':>8} {'PE':>7} {'evals':>8} {'trades':>6}  timeframes")
    print("-" * 118)
    for r in rows:
        tf = " ".join(f"{k}{'+' if v['state'] == 'reconstructable' else ('~' if v['bars'] else '-')}"
                      for k, v in r["timeframes"].items())
        win = f"{r['first']}-{r['last']}" if r["first"] else "—"
        print(f"{r['day']:<12} {r['kind']:<12} {r['spot_points']:>7,} {r['spot_source']:<8} "
              f"{win:<14} {r['ce_ticks']:>8,} {r['pe_ticks']:>7,} {r['signals']:>8,} "
              f"{r['trades']:>6}  {tf}")
    print()
    print("timeframes: + reconstructable   ~ sparse (bars rest on single observations)   - none")
    tick = [r for r in rows if r["kind"] == "tick"]
    coarse = [r for r in rows if r["kind"] == "coarse"]
    only = [r for r in rows if r["kind"] == "trades-only"]
    print(f"{len(tick)} tick-complete · {len(coarse)} coarse · {len(only)} trades-only "
          f"· {len(rows)} total")
    if tick:
        r = tick[-1]
        print(f"delta  : {r['delta_source']}")
        print(f"oi     : {r['oi_source']}")
        print(f"spread : {r['spread_source']}")
