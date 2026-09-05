"""The bracket a position declared at open — matched to trades only where the match is proven.

`active_positions` is the one place the live system wrote a stop and a target per position. Two
facts about those values decide how this module treats them, and both were measured rather than
assumed:

1. The join is genuine. `order_id` is unique on both sides and, on every matched pair, symbol,
   direction, quantity, entry price and entry time agree exactly. A pair that disagrees on any
   of them is refused here rather than merged on the strength of a shared id.

2. The declared bracket did not govern any exit. It is `entry - 8.0` and `entry + 16.0` on every
   row, and no exit in the record reached either level: losses ended at the early-cut and hard-SL
   rules instead, and two declared stops sit below zero premium, which no option can reach.

So the numbers are REAL — persisted by the live system, read back unchanged — but they are
`declared_*`, never `sl_price`/`tp_price`. The level that actually ended a trade was never
written down and stays MISSING. Naming them apart is the whole point: a chart that drew this
bracket as "the stop" would assert something the evidence contradicts.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import Book, parse_ts

# every field that must agree before a position row is accepted as the same event as a trade
IDENTITY_FIELDS = ("symbol", "direction", "qty")
PRICE_TOLERANCE = 1e-6


def _same_event(trade: Dict, pos: Dict) -> Tuple[bool, Optional[str]]:
    for f in IDENTITY_FIELDS:
        if trade.get(f) != pos.get(f):
            return False, f
    try:
        if abs(float(trade["entry_price"]) - float(pos["entry_price"])) > PRICE_TOLERANCE:
            return False, "entry_price"
    except (TypeError, ValueError):
        return False, "entry_price"
    if str(trade.get("entry_time"))[:19] != str(pos.get("entry_time"))[:19]:
        return False, "entry_time"
    return True, None


def declared_brackets(book: Book, day: str) -> Dict[int, Dict]:
    """trade id -> the bracket that trade's position declared, or nothing when unmatched."""
    by_order: Dict[str, List[Dict]] = {}
    for p in book.positions():
        by_order.setdefault(p.get("order_id"), []).append(p)
    out: Dict[int, Dict] = {}
    for tr in book.trades(day):
        cands = by_order.get(tr.get("order_id")) or []
        if len(cands) != 1:
            continue                       # absent, or ambiguous: neither is a supported join
        pos = cands[0]
        ok, mismatch = _same_event(tr, pos)
        if not ok:
            continue                       # shares an id but not the facts — refuse the join
        sl, tp = pos.get("stop_loss"), pos.get("take_profit")
        if sl is None and tp is None:
            continue
        entry = float(tr["entry_price"])
        out[tr["id"]] = {
            "declared_stop_loss": round(float(sl), 4) if sl is not None else None,
            "declared_take_profit": round(float(tp), 4) if tp is not None else None,
            "declared_stop_distance": round(entry - float(sl), 4) if sl is not None else None,
            "declared_target_distance": round(float(tp) - entry, 4) if tp is not None else None,
            "declared_source": "active_positions.order_id",
            "declared_reachable_stop": (None if sl is None else bool(float(sl) > 0.0)),
        }
    return out


def governed_exit(trade: Dict, bracket: Optional[Dict]) -> Optional[bool]:
    """Did the exit actually reach the declared bracket? None when there is no bracket to test.

    This is the check that keeps the record honest: it is recorded per trade, so the viewer can
    state that the bracket was declared without implying it was operative.
    """
    if not bracket or trade.get("exit_price") is None:
        return None
    x = float(trade["exit_price"])
    sl, tp = bracket.get("declared_stop_loss"), bracket.get("declared_take_profit")
    hit_sl = sl is not None and x <= sl
    hit_tp = tp is not None and x >= tp
    return bool(hit_sl or hit_tp)


def coverage(book: Book, days: Sequence[str]) -> Dict:
    """How far the declared bracket reaches, and how often it explained an exit."""
    n_trades = n_matched = n_governed = n_unreachable = 0
    for d in days:
        br = declared_brackets(book, d)
        trades = book.trades(d)
        n_trades += len(trades)
        n_matched += len(br)
        for tr in trades:
            b = br.get(tr["id"])
            if not b:
                continue
            if governed_exit(tr, b):
                n_governed += 1
            if b.get("declared_reachable_stop") is False:
                n_unreachable += 1
    return {"trades": n_trades, "matched": n_matched, "governed_an_exit": n_governed,
            "unreachable_stop": n_unreachable}
