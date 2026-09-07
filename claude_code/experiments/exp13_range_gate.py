"""EXP-13 — does realised spot range predict whether an entry is worth taking?

EXP-11 found the 09:15-09:45 window profitable and the rest of the day not, but gave no
mechanism. Measuring 30-minute NIFTY range across 2026-09-03/04 supplies a candidate one: the
opening half hour carries 56.8 points of range against a 36.2-point day mean (1.57x), the
largest of the twelve windows on both days independently. The bot's captured move has been
stuck at 1-2 points, so a window with more movement in it is exactly where its ladder should
do better.

If that is the mechanism, then realised range — not the clock — is the thing worth gating on,
and it should work *inside* the rest of the day too. That is the test this script runs:

  overall   expectancy by trailing-range bucket, all instants
  split     the same buckets computed separately for 09:15-09:45 and 09:45-15:10

A gate that only separates in the overall view but not inside 09:45-15:10 is just the clock
finding wearing a different hat, and should not be deployed as a new gate. One that separates
within 09:45-15:10 is a genuinely new lever.

Causality: the range at instant t is computed with research.candles.as_of, which cannot return
an observation later than t. OBS-01 was retracted for exactly this class of error, so the
lookback is structural here rather than a convention.

Exit pricing is research.replay (the production ladder), the DB is opened read-only by
research.db.Book. No ladder is defined in this file.

Caveats: n=2 sessions until today's data lands; spot range is a proxy for option movement, not
a measurement of it; bid/ask remains fabricated at ltp +/- 0.3%.

Usage:  python claude_code/experiments/exp13_range_gate.py [DAY ...]
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
import sys
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, __file__.rsplit("/claude_code/", 1)[0])

from research.candles import as_of                   # noqa: E402
from research.db import Book                         # noqa: E402
from research.opportunities import Universe          # noqa: E402
from research.prefilters import permutation_p        # noqa: E402
from research.replay import Ladder                   # noqa: E402

LOOKBACKS = (300, 900, 1800)          # 5, 15, 30 minutes
DEFAULT_LOOKBACK = 900
BUCKETS = (0, 10, 20, 30, 40, 60, 10_000)


def trailing_range(spot: Sequence, t: _dt.datetime, lookback_sec: int) -> Optional[float]:
    """Realised high-low of spot over the `lookback_sec` ending at t. As-of by construction."""
    w = as_of(spot, t, lookback_sec)
    if len(w) < 5:
        return None
    ps = [p for _, p in w]
    return round(max(ps) - min(ps), 2)


def collect(book: Book, days: Sequence[str], side: str = "CE",
            lad: Ladder = Ladder()) -> List[Dict]:
    """Every counterfactual entry on the grid, tagged with its trailing ranges."""
    rows: List[Dict] = []
    for d in days:
        u = Universe(book, d)
        spot = u.spot
        if not spot:
            continue
        for r in u.priced(u.instants(), side, lad):
            for lb in LOOKBACKS:
                r[f"range_{lb}"] = trailing_range(spot, r["t"], lb)
            r["window"] = "open" if r["t"].strftime("%H:%M") < "09:45" else "rest"
            rows.append(r)
    return rows


def _bucket(v: Optional[float]) -> Optional[str]:
    if v is None:
        return None
    for lo, hi in zip(BUCKETS, BUCKETS[1:]):
        if lo <= v < hi:
            return f"{lo}-{hi if hi < 10_000 else '+'}"
    return None


def _line(label: str, pnls: Sequence[float], width: int = 14) -> str:
    if not pnls:
        return f"  {label:<{width}} n=0"
    wins = sum(1 for p in pnls if p > 0)
    return (f"  {label:<{width}} n={len(pnls):<5} exp=Rs{_st.mean(pnls):>8.2f} "
            f" wr={100.0 * wins / len(pnls):>5.1f}%  total=Rs{sum(pnls):>9.0f}")


def by_bucket(rows: Sequence[Dict], key: str, subset: Optional[str] = None) -> None:
    sel = [r for r in rows if subset is None or r["window"] == subset]
    groups: Dict[str, List[float]] = {}
    for r in sel:
        b = _bucket(r.get(key))
        if b is None:
            continue
        groups.setdefault(b, []).append(r["pnl"])
    order = [f"{lo}-{hi if hi < 10_000 else '+'}" for lo, hi in zip(BUCKETS, BUCKETS[1:])]
    for b in order:
        if b in groups:
            print(_line(f"range {b}", groups[b]))


def sweep(rows: Sequence[Dict], key: str, subset: Optional[str] = None) -> None:
    """Expectancy of 'only trade when trailing range >= threshold'."""
    sel = [r for r in rows if (subset is None or r["window"] == subset) and r.get(key) is not None]
    if not sel:
        print("  (no rows)")
        return
    base = [r["pnl"] for r in sel]
    print(_line("no gate", base, width=16))
    for thr in (10, 15, 20, 25, 30, 40, 50):
        kept = [r["pnl"] for r in sel if r[key] >= thr]
        if len(kept) < 5:
            continue
        p = permutation_p(kept, base)
        line = _line(f">= {thr} pts", kept, width=16)
        print(f"{line}  p(better)={1.0 - p:.3f}")


def report(days: Sequence[str], side: str = "CE") -> int:
    book = Book()
    print("=" * 92)
    print(f"EXP-13  realised-range gate   days={list(days)}  side={side}"
          f"  lookback={DEFAULT_LOOKBACK}s")
    print("=" * 92)

    rows = collect(book, days, side)
    if not rows:
        print("no counterfactual rows for these days/side")
        return 1
    key = f"range_{DEFAULT_LOOKBACK}"

    n_open = sum(1 for r in rows if r["window"] == "open")
    print(f"\ncollected {len(rows)} counterfactual entries "
          f"({n_open} in 09:15-09:45, {len(rows) - n_open} in 09:45-15:10)")

    print("\n-- expectancy by trailing-range bucket, ALL instants " + "-" * 36)
    by_bucket(rows, key)

    print("\n-- the same buckets, 09:15-09:45 ONLY " + "-" * 51)
    by_bucket(rows, key, "open")

    print("\n-- the same buckets, 09:45-15:10 ONLY  <-- the decisive one " + "-" * 29)
    by_bucket(rows, key, "rest")

    print("\n-- gate sweep, 09:45-15:10 only (does range separate away from the open?) " + "-" * 15)
    sweep(rows, key, "rest")

    print("\n-- gate sweep, whole day " + "-" * 64)
    sweep(rows, key)

    print("\n-- sensitivity to the lookback, 09:45-15:10 " + "-" * 45)
    for lb in LOOKBACKS:
        sel = [r for r in rows if r["window"] == "rest" and r.get(f"range_{lb}") is not None]
        if not sel:
            continue
        base = [r["pnl"] for r in sel]
        best = None
        for thr in (10, 15, 20, 25, 30, 40):
            kept = [r["pnl"] for r in sel if r[f"range_{lb}"] >= thr]
            if len(kept) < 5:
                continue
            e = _st.mean(kept)
            if best is None or e > best[1]:
                best = (thr, e, len(kept))
        if best:
            print(f"  lookback {lb:>4}s: base exp=Rs{_st.mean(base):>7.2f}   "
                  f"best thr={best[0]:>3} pts -> exp=Rs{best[1]:>7.2f} (n={best[2]})")

    print("\n" + "=" * 92)
    return 0


def main(argv: Sequence[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    side = "PE" if "--pe" in argv else "CE"
    days = args or [_dt.date.today().isoformat()]
    return report(days, side)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
