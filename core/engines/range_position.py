"""Where the entry price sits inside the contract's own recent range.

A measurement over 2,968 arbitrary-timing entries on 98,434 of this project's own
option ticks (claude_code/report/strategy_research_20260908.md §4.3) found the
strongest signal-shaped result the project has: on this book, *buying strength is
the worst-priced entry available and buying weakness is the best*.

    top 20% of the 60-second range   -0.359 gross points   (worst of 27 cells)
    60s momentum > +1.5 points       -0.261 gross points   (second worst)
    bottom 20% of the range          +0.192 gross points   (the only positive cell)

The bot's scoring stack is EMA-alignment + RSI + volume-spike shaped — a
momentum/breakout detector. If that result is real, the stack is not merely unable
to rank; it is aimed at the worst cell measured.

This module computes the quantity, and nothing else. It is deliberately not wired
on by default:

  * the samples overlap (a 30-second grid over a 300-second horizon shares up to
    90% of its path), so the reported error bands are too narrow and no
    block-bootstrap was run — it is a hypothesis, not a finding; and
  * even if real it does not clear the bar. +0.192 points against a 0.884-point
    net requirement is 22% of what is needed. It is a diagnosis, not a cure.

It exists so the controlled experiment can be run as one variable against a
pre-registered threshold, which is the only way this project accepts an entry
change after retracting two that were fitted in-sample.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def range_position(
    ticks: Sequence[Dict[str, Any]],
    symbol: str,
    now_ms: Optional[float] = None,
    window_sec: float = 60.0,
    min_ticks: int = 10,
) -> Tuple[Optional[float], str]:
    """Fraction of the recent high-low range the latest price sits at.

    0.0 = at the low of the window, 1.0 = at the high. Returns (None, reason)
    rather than a number whenever the answer would be invented:

      * no tick in the window carries `symbol` — the rolling buffer holds
        whichever contract was subscribed, which is not always the one about to
        be traded, and a range measured on the wrong contract is worse than none;
      * fewer than `min_ticks` usable samples;
      * a degenerate range (high == low), where every position is simultaneously
        0 and 1.

    Callers must treat None as "unknown" and fail open. A gate that blocks entries
    because it could not measure something is a halt wearing a filter's clothing.
    """
    if not symbol:
        return None, "no symbol to attribute ticks to"
    if not ticks:
        return None, "no ticks"

    rows: List[Tuple[float, float]] = []
    for t in ticks:
        if t.get("symbol") != symbol:
            continue
        try:
            ltp = float(t.get("ltp") or 0)
            ts = float(t.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if ltp > 0 and ts > 0:
            rows.append((ts, ltp))

    if not rows:
        return None, f"no ticks for {symbol} in the buffer"

    rows.sort(key=lambda r: r[0])
    latest_ts = float(now_ms) if now_ms is not None else rows[-1][0]
    cutoff = latest_ts - window_sec * 1000.0
    window = [p for ts, p in rows if ts >= cutoff]

    if len(window) < min_ticks:
        return None, f"only {len(window)} ticks in {window_sec:.0f}s (need {min_ticks})"

    hi, lo, last = max(window), min(window), window[-1]
    if hi <= lo:
        return None, f"flat range at {lo:.2f} over {len(window)} ticks"

    return (last - lo) / (hi - lo), (
        f"{(last - lo) / (hi - lo):.2f} of [{lo:.2f}, {hi:.2f}] over "
        f"{len(window)} ticks / {window_sec:.0f}s"
    )
