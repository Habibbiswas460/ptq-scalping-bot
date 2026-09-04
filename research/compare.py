"""Session comparison. Every session joins automatically; nothing is keyed to a date."""
from __future__ import annotations

import statistics as _st
from collections import Counter
from typing import Dict, List, Optional, Sequence

from research.db import Book
from research.entries import cascade, profiles
from research.execution import quote_quality
from research.market import legs, session_profile
from research.prefilters import ladder_counts
from research.signals import score_pairs
from research.transmission import session_transmission


def session_row(book: Book, day: str) -> Dict:
    kind = book.session_kind(day)
    spot, src = book.spot(day)
    trades = book.trades(day)
    row: Dict = {"day": day, "kind": kind, "spot_src": src if spot else None,
                 "n_trades": len(trades) or None}
    if len(spot) > 3:
        prof = session_profile(spot, trades)
        row.update({"range": prof["range"], "net": prof["net"],
                    "legs_10": prof["legs_10"], "legs_25": prof["legs_25"],
                    "max_1m": max(prof["max_1m"]["up"], prof["max_1m"]["down"]),
                    "max_5m": max(prof["max_5m"]["up"], prof["max_5m"]["down"])})
    if trades:
        wins = sum(1 for t in trades if t["pnl"] > 0)
        row.update({"wr": round(100 * wins / len(trades), 1),
                    "pnl": round(sum(t["pnl"] for t in trades), 0),
                    "avg_hold": round(_st.mean([t["hold_time_sec"] for t in trades]), 0)})
    if kind == "tick":
        ps = profiles(book, day)
        cs = [cascade(p) for p in ps]
        av = [c["opt_avail"] for c in cs if c["opt_avail"] is not None]
        got = [c["captured"] for c in cs]
        row["opt_available_3m"] = round(_st.mean(av), 2) if av else None
        row["captured"] = round(_st.mean(got), 2) if got else None
        row["capture_ratio"] = (round(sum(g for g in got if g > 0) / sum(a for a in av if a > 0), 3)
                                if any(a > 0 for a in av) else None)
        tr = [t for t in session_transmission(book, day) if t["horizon_sec"] == 60]
        row["delta_1m"] = round(_st.mean([t["beta"] for t in tr]), 3) if tr else None
        q = quote_quality(book, day)
        row["midpoint_exact_pct"] = q.get("midpoint_exact_pct")
        row["oi_pct"] = q.get("oi_populated_pct")
        row["pe_ticks"] = q.get("pe_ticks")
    if book.signals(day):
        lc = ladder_counts(book, day)
        sp = score_pairs(book, day)
        row.update({"n_signals": lc["total"], "pct_scored": lc["pct_scored"],
                    "accepted": lc["accepted"], "score_pairs": sp["distinct_pairs"]})
    return row


def table(book: Book, days: Optional[Sequence[str]] = None) -> List[Dict]:
    days = days or [s["day"] for s in book.sessions()]
    return [session_row(book, d) for d in days]


def delta(a: Dict, b: Dict, keys: Optional[Sequence[str]] = None) -> List[Dict]:
    """Before/after on any two sessions. Reports data-health metrics alongside outcome, because
    a repair can succeed by restoring observability while P&L is unchanged."""
    keys = keys or ["range", "legs_25", "n_signals", "pct_scored", "score_pairs", "accepted",
                    "n_trades", "wr", "pnl", "opt_available_3m", "captured", "capture_ratio",
                    "delta_1m", "midpoint_exact_pct", "oi_pct", "pe_ticks"]
    out = []
    for k in keys:
        va, vb = a.get(k), b.get(k)
        d = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = round(vb - va, 3)
        out.append({"metric": k, "a": va, "b": vb, "delta": d})
    return out
