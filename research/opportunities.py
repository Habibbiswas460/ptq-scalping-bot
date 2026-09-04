"""The opportunity universe: every valid instant, not only the ones traded.

Actual entries can only be judged against what else was on offer. This builds the comparison
set — a regular grid of candidate instants with the movement that followed each — so
"entered", "blocked" and "never considered" can be priced on the same scale.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from research.candles import as_of
from research.db import Book, parse_ts
from research.replay import Ladder, half_spread, replay

HORIZONS = (10, 30, 60, 180, 300, 600)
PREMIUM_BAND = (70.0, 350.0)
COOLDOWN_SEC = 120


def excursions(series: Sequence[Tuple[_dt.datetime, float]], t: _dt.datetime, ref: float,
               sign: int = 1, horizons=HORIZONS) -> Dict:
    """Uncensored MFE/MAE after `t`. Measured over fixed horizons from ticks, so it is never
    truncated by an exit the way the stored mfe column is."""
    out = {}
    for h in horizons:
        w = [p for ts, p in series if t < ts <= t + _dt.timedelta(seconds=h)]
        out[f"mfe_{h}"] = round(max((p - ref) * sign for p in w), 2) if w else None
        out[f"mae_{h}"] = round(min((p - ref) * sign for p in w), 2) if w else None
        out[f"n_{h}"] = len(w)
    return out


class Universe:
    """Candidate entry instants on a fixed grid, with the contract actually subscribed."""

    def __init__(self, book: Book, day: str, step_sec: int = 30,
                 start: str = "09:15:00", end: str = "15:10:00"):
        self.book = book
        self.day = day
        self.step = step_sec
        self.spot, self.spot_src = book.spot(day)
        self.symbols = {side: [s for s, _ in book.option_symbols(day, side)]
                        for side in ("CE", "PE")}
        self._idx = {}
        for side, syms in self.symbols.items():
            for s in syms:
                self._idx[s] = {t: p for t, p in book.option(s, day)}
        self.start = parse_ts(f"{day} {start}")
        self.end = parse_ts(f"{day} {end}")

    def quote(self, t: _dt.datetime, side: str) -> Optional[Tuple[str, float]]:
        for s in self.symbols.get(side, []):
            for off in (0, -1, 1, -2, 2):
                p = self._idx[s].get(t + _dt.timedelta(seconds=off))
                if p and PREMIUM_BAND[0] <= p <= PREMIUM_BAND[1]:
                    return s, p
        return None

    def instants(self) -> List[_dt.datetime]:
        out, t = [], self.start
        while t <= self.end:
            out.append(t)
            t += _dt.timedelta(seconds=self.step)
        return out

    def candidate(self, t: _dt.datetime, side: str) -> Optional[Dict]:
        q = self.quote(t, side)
        if not q:
            return None
        sym, ltp = q
        opt = self.book.option(sym, self.day)
        spot_now = next((p for ts, p in reversed(self.spot) if ts <= t), None)
        sgn = 1 if side == "CE" else -1
        row = {"t": t, "side": side, "symbol": sym, "ltp": ltp, "spot": spot_now}
        row.update({f"opt_{k}": v for k, v in excursions(opt, t, ltp).items()})
        if spot_now is not None:
            row.update({f"spot_{k}": v for k, v in
                        excursions(self.spot, t, spot_now, sgn).items()})
        return row

    def priced(self, times: Sequence[_dt.datetime], side: str = "CE",
               lad: Ladder = Ladder(), cooldown: int = COOLDOWN_SEC) -> List[Dict]:
        """Run the exit ladder at each instant, honouring a cooldown so a persistent condition
        becomes episodes rather than one row per evaluation."""
        out, last = [], None
        for t in sorted(times):
            if last and (t - last).total_seconds() < cooldown:
                continue
            q = self.quote(t, side)
            if not q:
                continue
            sym, ltp = q
            entry = round(ltp + half_spread(ltp, lad.spread_pct), 2)
            r = replay(self.book.option(sym, self.day), t, entry, side, lad)
            r.update(t=t, side=side, symbol=sym, entry=entry, day=self.day)
            out.append(r)
            last = t + _dt.timedelta(seconds=r["hold"])
        return out
