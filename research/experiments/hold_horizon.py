"""Does the available excursion outgrow the friction if the bot simply holds longer?

THE CLAIM UNDER TEST
====================
A third-party review of this project reported, from the bot's own recorded ticks,
that mean favourable excursion rises from 1.7 points at a 1-minute hold to 7.9
points at 30 minutes while friction falls from 64% to 21% of it, cutting the
required hit rate from 82% to 61%. That measurement was taken on a book that was
~95% CE over a window in which NIFTY fell 218.6 points, so a directional loss and
a horizon effect are not separated in it.

This module re-measures the same term structure on `data/historical/candles.db`
(exchange 1-minute OHLC, 46 contracts of the 2026-09-08 expiry over 13 sessions),
which carries 23 CE and 23 PE strikes rather than one side, and therefore CAN
separate them.

THREE THINGS IT DOES DIFFERENTLY, EACH OF WHICH MOVES THE ANSWER
---------------------------------------------------------------
1. NON-OVERLAPPING SAMPLES. Entries on a 60-second grid measured over a 30-minute
   forward window share 29/30 of their path. The resulting "n" is not a count of
   independent observations and any interval computed from it is far too narrow.
   Here every horizon gets its own stride: entries are spaced H minutes apart
   inside a contract-session, so no two windows for that horizon overlap. n falls
   by a factor of H and that is the honest number.

   Windows still overlap ACROSS strikes at the same instant, because 46 contracts
   on one index are one bet wearing 46 hats. That residual dependence is handled
   by the bootstrap below, not by the stride.

2. A CLUSTER BOOTSTRAP OVER SESSIONS. The resample unit is the whole session, so
   both the within-contract serial correlation the stride does not remove and the
   cross-strike correlation it cannot remove are carried into the interval. There
   are 13 sessions, so the intervals are wide. That is the sample, not a defect of
   the method.

3. DIRECTION IS REPORTED SEPARATELY, AND THE INDEX DRIFT WITH IT. A CE and a PE on
   the same minute are close to mirror images; the mean of the two is a
   drift-neutralised estimate in a way neither one alone is. Every table carries
   the index's own move over the same windows so the reader can see how much of
   the option's excursion is simply the index.

FRICTION
--------
`research/costs.py` covers brokerage/STT/exchange/SEBI/stamp/GST and deliberately
excludes the bid/ask spread, because the live bot crosses the book in its fill and
the spread is therefore already inside its gross P&L. A measurement taken from
mid-price candles has NOT paid it, so it is added here, once:

    friction(P) = costs.DEFAULT.points(P) + SPREAD_PCT_RT * P

with SPREAD_PCT_RT = 0.00239, the round-trip spread measured on this project's own
mode-3 SnapQuote rows on 2026-09-07 (0.239% of premium, flat across delta
0.52-0.64). Reproduces the published figures exactly: 0.999 pts at a Rs57.4
premium, 1.634 pts at Rs190.8.

Friction is evaluated AT EACH SAMPLE'S OWN PREMIUM, never at a pooled mean. The
same signal is worth 1.00 points on a Rs57 contract and 1.63 on a Rs191 one, so a
term structure quoted against a single friction number is wrong by up to 85%.

WHAT THE 1-MINUTE BARS CANNOT SAY
---------------------------------
A bar reports that its high and its low both happened. It does not report in which
order. Mean MFE and mean MAE do not care. The first-touch test in
`barrier_outcomes` does, so it is run under both orderings and both are reported;
the truth is between them.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import random
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research import costs as _costs  # noqa: E402

ANGEL = "angelone_smartapi"
DB_PATH = os.path.join(_ROOT, "data", "historical", "candles.db")

# Round-trip bid/ask, as a fraction of premium. Measured, not assumed — see the
# module docstring. research/backtest/harness.py uses 0.246% from a larger but
# older tick sample; the difference is 0.007% of premium (~Rs0.66 on a 65 lot) and
# changes no conclusion here. The smaller (more charitable) figure is used.
SPREAD_PCT_RT = 0.00239

HORIZONS_MIN = (1, 2, 5, 10, 15, 30, 45, 60)

# 15:25 is the live force-close. A window that would still be open then could not
# have been held in production, so it is not sampled.
LAST_ENTRY_CLOSE = _dt.time(15, 25)


def friction_points(premium: float) -> float:
    """Round-trip cost of one lot at this premium, in option points."""
    if premium <= 0:
        return 0.0
    return _costs.DEFAULT.points(premium) + SPREAD_PCT_RT * premium


# ── data ─────────────────────────────────────────────────────────────────────

@dataclass
class Series:
    session_date: str
    symbol: str
    kind: str          # CE | PE
    strike: float
    epochs: List[int]
    open: List[float]
    high: List[float]
    low: List[float]
    close: List[float]


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_spot(con, source: str = ANGEL) -> Dict[str, Dict[int, sqlite3.Row]]:
    out: Dict[str, Dict[int, sqlite3.Row]] = defaultdict(dict)
    q = ("SELECT c.session_date, c.epoch, c.open, c.high, c.low, c.close "
         "FROM candles c JOIN instruments i ON i.instrument_key=c.instrument_key "
         "WHERE c.source=? AND c.interval='1m' AND i.kind='INDEX'")
    for r in con.execute(q, (source,)):
        out[r["session_date"]][r["epoch"]] = r
    return out


def load_options(con, expiry: str, source: str = ANGEL) -> List[Series]:
    q = ("SELECT c.session_date, c.symbol, c.epoch, c.open, c.high, c.low, c.close, "
         "       i.kind, i.strike "
         "FROM candles c JOIN instruments i ON i.instrument_key=c.instrument_key "
         "WHERE c.source=? AND c.interval='1m' AND i.kind IN ('CE','PE') AND i.expiry=? "
         "ORDER BY c.session_date, c.symbol, c.epoch")
    buckets: Dict[Tuple[str, str], Series] = {}
    for r in con.execute(q, (source, expiry)):
        key = (r["session_date"], r["symbol"])
        s = buckets.get(key)
        if s is None:
            s = buckets[key] = Series(r["session_date"], r["symbol"], r["kind"],
                                      r["strike"], [], [], [], [], [])
        s.epochs.append(r["epoch"])
        s.open.append(r["open"])
        s.high.append(r["high"])
        s.low.append(r["low"])
        s.close.append(r["close"])
    return list(buckets.values())


# ── sampling ─────────────────────────────────────────────────────────────────

@dataclass
class Sample:
    session_date: str
    symbol: str
    kind: str
    strike: float
    idx: int                # index into the Series
    entry_epoch: int
    entry: float            # mid at the fill (bar open), NOT spread-adjusted
    spot_entry: float
    spot_exit: float
    mfe: float              # points, forward window only
    mae: float              # points, <= 0
    close_pts: float        # close of the last bar in the window, minus entry
    friction: float


def _contiguous(epochs: Sequence[int], j: int, h: int) -> bool:
    """The h bars starting at j are h consecutive exchange minutes.

    A missing minute is a minute in which the contract did not print. It is not
    filled in (research/backtest/store.py rule 1), so a window straddling one is
    simply not sampled rather than being quietly stretched over a longer span.
    """
    e0 = epochs[j]
    for k in range(h):
        if epochs[j + k] != e0 + 60 * k:
            return False
    return True


def collect(series: Iterable[Series], spot: Dict[str, Dict[int, sqlite3.Row]],
            horizon_min: int, *, min_premium: float = 0.0,
            max_premium: float = float("inf"),
            atm_band: Optional[float] = None,
            stride: Optional[int] = None) -> List[Sample]:
    """Non-overlapping forward windows of `horizon_min` bars.

    `stride=None` means stride == horizon, i.e. no two sampled windows for this
    horizon share a bar inside one contract-session. Pass stride=1 to reproduce
    the overlapping grid and see the difference.
    """
    h = horizon_min
    step = h if stride is None else stride
    out: List[Sample] = []
    for s in series:
        sp = spot.get(s.session_date) or {}
        n = len(s.epochs)
        j = 0
        while j + h <= n:
            if not _contiguous(s.epochs, j, h):
                j += 1
                continue
            entry = s.open[j]
            if entry < min_premium or entry > max_premium:
                j += step
                continue
            sb = sp.get(s.epochs[j])
            se = sp.get(s.epochs[j + h - 1])
            if sb is None or se is None:
                j += step
                continue
            ts = _dt.datetime.fromtimestamp(s.epochs[j + h - 1], _dt.timezone(_dt.timedelta(hours=5, minutes=30)))
            if ts.time() > LAST_ENTRY_CLOSE:
                break
            if atm_band is not None and abs(s.strike - sb["open"]) > atm_band:
                j += step
                continue
            hi = max(s.high[j:j + h])
            lo = min(s.low[j:j + h])
            out.append(Sample(
                session_date=s.session_date, symbol=s.symbol, kind=s.kind,
                strike=s.strike, idx=j, entry_epoch=s.epochs[j], entry=entry,
                spot_entry=sb["open"], spot_exit=se["close"],
                mfe=hi - entry, mae=lo - entry,
                close_pts=s.close[j + h - 1] - entry,
                friction=friction_points(entry)))
            j += step
    return out


# ── statistics ───────────────────────────────────────────────────────────────

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def describe(samples: Sequence[Sample]) -> Dict:
    if not samples:
        return {"n": 0}
    mfe = [s.mfe for s in samples]
    mae = [abs(s.mae) for s in samples]
    fr = [s.friction for s in samples]
    clears = [1.0 if s.mfe > s.friction else 0.0 for s in samples]
    m_mfe, m_mae, m_fr = _mean(mfe), _mean(mae), _mean(fr)
    return {
        "n": len(samples),
        "mean_premium": _mean([s.entry for s in samples]),
        "mean_mfe": m_mfe,
        "mean_mae": m_mae,
        "mfe_over_mae": (m_mfe / m_mae) if m_mae else float("nan"),
        "mean_friction": m_fr,
        "friction_pct_of_mfe": 100.0 * m_fr / m_mfe if m_mfe else float("nan"),
        "frac_mfe_gt_friction": _mean(clears),
        "mean_close_pts": _mean([s.close_pts for s in samples]),
        "mean_spot_drift": _mean([s.spot_exit - s.spot_entry for s in samples]),
        # Required hit rate for a symmetric TP=SL=X ladder with X set to the
        # horizon's own mean MFE, no directional edge assumed:
        #     p > 0.5 + friction / (2X)
        "required_hit_rate": (50.0 + 100.0 * m_fr / (2.0 * m_mfe)) if m_mfe > 0 else float("nan"),
    }


def cluster_bootstrap(samples: Sequence[Sample], stat, reps: int = 2000,
                      seed: int = 20260908) -> Tuple[float, float]:
    """95% percentile interval, resampling whole SESSIONS with replacement.

    The session is the cluster because everything inside one — every strike, every
    minute — is driven by one index path. Resampling individual windows would
    treat 46 views of the same afternoon as 46 independent facts.
    """
    by_day: Dict[str, List[Sample]] = defaultdict(list)
    for s in samples:
        by_day[s.session_date].append(s)
    days = sorted(by_day)
    if len(days) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals: List[float] = []
    for _ in range(reps):
        pool: List[Sample] = []
        for _ in days:
            pool.extend(by_day[days[rng.randrange(len(days))]])
        try:
            vals.append(stat(pool))
        except (ZeroDivisionError, ValueError):
            continue
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return lo, hi


# ── first touch: what a symmetric barrier actually pays ──────────────────────

def barrier_outcomes(series: Iterable[Series], spot: Dict[str, Dict[int, sqlite3.Row]],
                     horizon_min: int, target: float, stop: float, *,
                     adverse_first: bool = True, min_premium: float = 0.0,
                     max_premium: float = float("inf"),
                     atm_band: Optional[float] = None) -> Dict:
    """Walk each non-overlapping window bar by bar until a barrier is touched.

    Mean MFE says how far price went. It does not say whether it went there before
    or after it went the other way, and a ladder only ever collects the first of
    the two. This resolves that at the only granularity available, with the
    intrabar order stated rather than assumed away.

    Net points are charged the sample's own friction, so a Rs400 contract pays
    more than a Rs40 one, as it does in the market.
    """
    h = horizon_min
    wins = losses = timeouts = 0
    net_pts: List[float] = []
    per_day: Dict[str, List[float]] = defaultdict(list)
    for s in series:
        sp = spot.get(s.session_date) or {}
        n = len(s.epochs)
        j = 0
        while j + h <= n:
            if not _contiguous(s.epochs, j, h):
                j += 1
                continue
            entry = s.open[j]
            if entry < min_premium or entry > max_premium:
                j += h
                continue
            sb = sp.get(s.epochs[j])
            if sb is None:
                j += h
                continue
            ts = _dt.datetime.fromtimestamp(
                s.epochs[j + h - 1], _dt.timezone(_dt.timedelta(hours=5, minutes=30)))
            if ts.time() > LAST_ENTRY_CLOSE:
                break
            if atm_band is not None and abs(s.strike - sb["open"]) > atm_band:
                j += h
                continue
            outcome = None
            exit_pts = 0.0
            for k in range(h):
                hi, lo = s.high[j + k] - entry, s.low[j + k] - entry
                order = ((lo, "loss"), (hi, "win")) if adverse_first else ((hi, "win"), (lo, "loss"))
                for val, kind in order:
                    if kind == "loss" and val <= -stop:
                        outcome, exit_pts = "loss", -stop
                        break
                    if kind == "win" and val >= target:
                        outcome, exit_pts = "win", target
                        break
                if outcome:
                    break
            if outcome is None:
                outcome, exit_pts = "timeout", s.close[j + h - 1] - entry
            wins += outcome == "win"
            losses += outcome == "loss"
            timeouts += outcome == "timeout"
            v = exit_pts - friction_points(entry)
            net_pts.append(v)
            per_day[s.session_date].append(v)
            j += h
    n = len(net_pts)
    if not n:
        return {"n": 0}
    resolved = wins + losses
    return {
        "n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
        "hit_rate_resolved": (100.0 * wins / resolved) if resolved else float("nan"),
        "hit_rate_all": 100.0 * wins / n,
        "net_expectancy_pts": _mean(net_pts),
        "net_total_pts": sum(net_pts),
        "profitable_days": sum(1 for d in per_day if sum(per_day[d]) > 0),
        "days": len(per_day),
        "per_day": {d: sum(v) for d, v in sorted(per_day.items())},
        # Kept whole, not summed, so the caller can resample SESSIONS: 46 strikes
        # over one afternoon are one index path, and a bootstrap over individual
        # windows would count them as 46 independent facts.
        "per_day_values": {d: list(v) for d, v in sorted(per_day.items())},
    }
