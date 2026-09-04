"""Exit-ladder replay — the counterfactual engine.

Answers "what would this instant have produced?" by walking real ticks under the production
exit rules. Used by the opportunity universe, the pre-filter forensics and the exit layer, so
they all price a hypothetical entry the same way.

Fidelity, measured against the 24 recorded exits of 2026-09-03/04: 22 reproduce by reason and
second. Both misses are RSI-timing — the live indicator saw 42,965 ticks where 25,055 were
persisted, so the replayed tick-RSI is smoother than the live one. Loss-side rules are time-
and-price driven and reproduce exactly. Treat loss-side conclusions as high confidence and
RSI-timing conclusions as directional.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import LOT, parse_ts

SYNTHETIC_SPREAD_PCT = 0.3   # what production actually filled at; NOT a measured spread


def half_spread(ltp: float, pct: float = SYNTHETIC_SPREAD_PCT) -> float:
    return max(0.05, ltp * pct / 100.0) / 2.0


@dataclass(frozen=True)
class Ladder:
    """The production exit ladder. Defaults mirror the effective live values, including the
    2.5 early cut that the unpopulated `atr` key pins the live system to."""
    name: str = "production"
    hard_sl: float = 7.0
    tp: float = 14.0
    max_hold: float = 900.0
    early_pts: float = 2.5
    early_sec: float = 45.0
    soft_pts: float = 1.8
    soft_sec: float = 75.0
    rsi_ob: float = 80.0
    rsi_os: float = 20.0
    rsi_exit_min_profit: float = 2.0
    rev_extreme_ce: float = 75.0
    rev_exit_ce: float = 60.0
    rev_extreme_pe: float = 25.0
    rev_exit_pe: float = 40.0
    rev_min_profit: float = 1.65
    spread_pct: float = SYNTHETIC_SPREAD_PCT


def tick_rsi(window: Sequence[float]) -> Optional[float]:
    """Mirror of state_machine._calculate_rsi: a simple RSI(14) over the last 15 option LTP
    ticks. This is NOT the 5-minute spot RSI — the exit path uses this one."""
    if len(window) < 15:
        return None
    g = l = 0.0
    for i in range(len(window) - 14, len(window)):
        c = window[i] - window[i - 1]
        if c > 0:
            g += c
        else:
            l += -c
    ag, al = g / 14.0, l / 14.0
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def replay(opt: Sequence[Tuple[_dt.datetime, float]], entry_dt: _dt.datetime,
           entry_price: float, direction: str, lad: Ladder = Ladder()) -> Dict:
    """Walk ticks from the entry and return the exit the ladder would have produced."""
    max_rsi, min_rsi = 0.0, 100.0
    mfe = mae = 0.0

    def close(px, reason, held, idx):
        fill = round(px - half_spread(px, lad.spread_pct), 2)
        return {"exit_ltp": px, "exit_fill": fill, "reason": reason, "hold": held,
                "pts": round(fill - entry_price, 2),
                "pnl": round((fill - entry_price) * LOT, 2),
                "mfe": round(mfe, 2), "mae": round(mae, 2), "idx": idx}

    for i, (t, px) in enumerate(opt):
        if t <= entry_dt:
            continue
        held = (t - entry_dt).total_seconds()
        diff = px - entry_price
        mfe = max(mfe, diff)
        mae = min(mae, diff)
        if diff <= -lad.hard_sl:
            return close(px, "HARD_SL", held, i)
        if diff >= lad.tp:
            return close(px, "TP", held, i)
        if held <= lad.early_sec and diff <= -lad.early_pts:
            return close(px, "EARLY_CUT", held, i)
        if held >= lad.soft_sec and diff <= -lad.soft_pts:
            return close(px, "SOFT_LOSS", held, i)
        r = tick_rsi([q for _, q in opt[max(0, i - 20): i + 1]][-15:])
        if r is not None:
            max_rsi = max(max_rsi, r)
            min_rsi = min(min_rsi, r)
            if diff >= lad.rsi_exit_min_profit:
                if direction == "CE" and r > lad.rsi_ob:
                    return close(px, "RSI_EXIT", held, i)
                if direction == "PE" and r < lad.rsi_os:
                    return close(px, "RSI_EXIT", held, i)
            if diff >= lad.rev_min_profit:
                if direction == "CE" and max_rsi > lad.rev_extreme_ce and r < lad.rev_exit_ce:
                    return close(px, "RSI_REVERSAL", held, i)
                if direction == "PE" and min_rsi < lad.rev_extreme_pe and r > lad.rev_exit_pe:
                    return close(px, "RSI_REVERSAL", held, i)
        if held >= lad.max_hold:
            return close(px, "TIME", held, i)
    if not opt:
        return close(entry_price, "NO_DATA", 0.0, 0)
    return close(opt[-1][1], "EOD", (opt[-1][0] - entry_dt).total_seconds(), len(opt) - 1)


def summarise(rows: Sequence[Dict]) -> Dict:
    import statistics as st
    from collections import Counter
    pnls = [r["pnl"] for r in rows]
    if not pnls:
        return {"n": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp, gl = sum(wins), abs(sum(losses))
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"n": len(pnls), "wr": round(100 * len(wins) / len(pnls), 1),
            "avg_win": round(st.mean(wins) / LOT, 2) if wins else 0.0,
            "avg_loss": round(st.mean(losses) / LOT, 2) if losses else 0.0,
            "exp": round(st.mean(pnls), 2), "pnl": round(sum(pnls), 0),
            "pf": round(gp / gl, 2) if gl else 0.0, "mdd": round(mdd, 0),
            "hold": round(st.mean([r["hold"] for r in rows]), 0),
            "exits": dict(Counter(r["reason"] for r in rows))}
