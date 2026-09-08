"""Hold the entry signal fixed; vary only how long the trade is allowed to live.

The hypothesis is that this bot's holding horizon, not its signal, is what makes
it lose: friction is a fixed toll per round trip and the available excursion grows
roughly as sqrt(t), so a 47-second hold is structurally unable to clear a cost that
equals the whole 60-second excursion.

That is a statement about the EXIT, so this varies the exit and nothing else. The
same `smart_scalp_signal` fires at the same minutes in every configuration; the
strike is the same; the fills are the same; only the branches that end the trade
change. Any difference in the table is therefore attributable to holding time.

HOW THE VARIANTS ARE APPLIED
============================
By rebinding module attributes on `core.engines.exit_engine` for the duration of
one run and restoring them afterwards. Nothing on disk is edited — `config/`,
`core/` and `strategies/` are untouched, and a live session is running against
them. `exit_engine` reads every threshold through its own module globals
(`from config.constants import ...` binds them into that namespace), so rebinding
there is exactly equivalent to changing the config for this process, and reaches
no other process.

TWO THINGS THE SHIPPING LADDER DOES THAT ARE NOT "HOLD TIME", AND ARE VARIED
SEPARATELY
---------------------------------------------------------------------------
  * The STEP TRAILING ladder ends a winner as soon as it retraces to a locked
    rung. Leaving it on while extending the maximum hold does not test a longer
    hold — it tests a longer hold on losers only, because winners still exit at
    the same place. Variants that switch it off are marked TRAIL=off, and there
    the declared TP14/SL7 pair becomes live for the first time.
  * The GREEKS KILL (theta/gamma/delta) fires on elapsed decay, so on 0DTE it
    behaves like a time exit wearing a different name. Variants that disable it
    are marked GK=off. Those are no longer the shipping system and are labelled
    as bounds, not proposals.

COST TREATMENT — the spread is charged ONCE, and it is already charged
---------------------------------------------------------------------
`research/backtest/harness.py` fills the entry at `bar + half_spread` and the exit
at `bar - half_spread`, so the crossed book is inside `Trade.gross_pnl` before any
charge is added. `research/costs.py` covers only brokerage/STT/exchange/SEBI/
stamp/GST and deliberately excludes spread. Adding `costs.round_trip()` on top of
that gross figure therefore charges the spread once and only once. NOTHING EXTRA
IS ADDED HERE. The harness default is 0.246% round trip (measured on this
project's recorded ticks); `--spread-pct 0.239` reruns it at the SnapQuote figure
from 2026-09-07, and the difference is about Rs0.66 per round trip.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research import costs as _costs                                  # noqa: E402
from research.backtest import store                                   # noqa: E402
from research.backtest.harness import Config, Replay, exit_breakdown, summarise  # noqa: E402

ANGEL = "angelone_smartapi"

# Values that switch a branch off without editing it.
#   early cut:  `if hold_time > EARLY_LOSS_CUT_TIME_SEC: return False` — a
#               negative limit is already exceeded at hold_time 0, so the branch
#               returns on its first line. 0 would NOT work: the first evaluation
#               lands at exactly hold_time 0 and 0 > 0 is False.
#   soft loss:  `if hold_time < SOFT_LOSS_TIME_SEC: return False` — an
#               unreachable limit keeps it returning.
OFF_EARLY = -1
OFF_SOFT = 10 ** 9
NO_KILL = {"THETA_SEC_KILL_LIMIT": 1e9, "DELTA_KILL_MIN": 0.0,
           "GAMMA_NORMAL_MAX": 1e9, "GAMMA_EXPIRY_MAX": 1e9}


@dataclass
class Variant:
    label: str
    patch: Dict[str, object] = field(default_factory=dict)
    note: str = ""


def _variants() -> List[Variant]:
    def hold(sec):
        return {"MAX_HOLD_TIME_WINNING": sec, "MAX_HOLD_TIME_LOSING": sec}

    no_cuts = {"EARLY_LOSS_CUT_TIME_SEC": OFF_EARLY, "SOFT_LOSS_TIME_SEC": OFF_SOFT}
    no_trail = {"TRAILING_ENABLED": False}
    return [
        Variant("A  baseline (shipping ladder)", {},
                "early cut 45s, soft loss 75s, step trailing on, max hold 900s"),
        Variant("B  early cut OFF", {"EARLY_LOSS_CUT_TIME_SEC": OFF_EARLY}),
        Variant("C  soft loss OFF", {"SOFT_LOSS_TIME_SEC": OFF_SOFT}),
        Variant("D  both time cuts OFF", dict(no_cuts)),
        Variant("E  cuts OFF + max hold 30min", {**no_cuts, **hold(1800)}),
        Variant("F  cuts OFF + max hold 60min", {**no_cuts, **hold(3600)}),
        Variant("G  cuts OFF + hold to 15:25", {**no_cuts, **hold(10 ** 9)}),
        Variant("H  cuts OFF, TRAIL=off, TP14/SL7, 30min", {**no_cuts, **no_trail, **hold(1800)},
                "the DECLARED ladder, which has never fired live"),
        Variant("I  cuts OFF, TRAIL=off, TP14/SL7, to 15:25", {**no_cuts, **no_trail, **hold(10 ** 9)}),
        Variant("J  cuts OFF, TRAIL=off, SL7 only, 30min",
                {**no_cuts, **no_trail, "TP_POINTS_FIXED": 10 ** 6, **hold(1800)},
                "stop kept, target removed: pure 'let it run to the horizon'"),
        Variant("K  pure horizon 30min (GK=off, no SL, no TP)",
                {**no_cuts, **no_trail, "TP_POINTS_FIXED": 10 ** 6,
                 "EXIT_HARD_SL_POINTS": 10 ** 6, "HARD_SL_POINTS": 1e6, **NO_KILL, **hold(1800)},
                "NOT the shipping system — an upper bound on what horizon alone can do"),
        Variant("L  pure horizon 60min (GK=off, no SL, no TP)",
                {**no_cuts, **no_trail, "TP_POINTS_FIXED": 10 ** 6,
                 "EXIT_HARD_SL_POINTS": 10 ** 6, "HARD_SL_POINTS": 1e6, **NO_KILL, **hold(3600)}),
        Variant("M  pure horizon 5min (GK=off, no SL, no TP)",
                {**no_cuts, **no_trail, "TP_POINTS_FIXED": 10 ** 6,
                 "EXIT_HARD_SL_POINTS": 10 ** 6, "HARD_SL_POINTS": 1e6, **NO_KILL, **hold(300)}),
        Variant("N  pure horizon 1min (GK=off, no SL, no TP)",
                {**no_cuts, **no_trail, "TP_POINTS_FIXED": 10 ** 6,
                 "EXIT_HARD_SL_POINTS": 10 ** 6, "HARD_SL_POINTS": 1e6, **NO_KILL, **hold(60)}),
    ]


@contextlib.contextmanager
def patched(patch: Dict[str, object]):
    from core.engines import exit_engine as ee
    missing = [k for k in patch if not hasattr(ee, k)]
    if missing:
        raise AttributeError(f"exit_engine has no {missing} — the patch would be silent")
    old = {k: getattr(ee, k) for k in patch}
    for k, v in patch.items():
        setattr(ee, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(ee, k, v)


def run_variant(con, index_key: str, days: List[str], expiry: str,
                v: Variant, cfg: Config) -> Dict:
    rep = Replay(cfg)
    with patched(v.patch):
        for d in days:
            rep.run_session(con, index_key, d, expiry)
    s = summarise(rep.trades, cfg.cost_model)
    s["label"] = v.label
    s["note"] = v.note
    s["exits"] = {k: b["n"] for k, b in exit_breakdown(rep.trades).items()}
    s["by_direction"] = {}
    for side in ("CE", "PE"):
        sub = [t for t in rep.trades if t.direction == side]
        if sub:
            d2 = summarise(sub, cfg.cost_model)
            s["by_direction"][side] = {"n": d2["n"], "gross": d2["gross_total"],
                                       "net": d2["net_total"]}
    s["by_day"] = {}
    for d in days:
        sub = [t for t in rep.trades if t.session_date == d]
        s["by_day"][d] = round(sum(t.net_pnl(cfg.cost_model) for t in sub), 2)
    return s


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="research.experiments.hold_policy")
    p.add_argument("--expiry", default="2026-09-08")
    p.add_argument("--spread-pct", type=float, default=None)
    p.add_argument("--optimistic", action="store_true")
    p.add_argument("--only", default=None, help="comma-separated variant letters")
    args = p.parse_args(argv)

    from config.constants import NIFTY_SPOT_TOKEN
    index_key = f"NSE:{NIFTY_SPOT_TOKEN}"
    con = store.connect()
    days = [r[0] for r in con.execute(
        """SELECT DISTINCT c.session_date FROM candles c
           JOIN instruments i ON i.instrument_key=c.instrument_key
           WHERE c.source=? AND i.kind IN ('CE','PE') AND i.expiry=?
           ORDER BY c.session_date""", (ANGEL, args.expiry))]

    cfg = Config(optimistic_intrabar=args.optimistic)
    if args.spread_pct is not None:
        cfg.spread_pct = args.spread_pct

    want = set(args.only.upper().split(",")) if args.only else None
    print(f"{len(days)} sessions {days[0]}..{days[-1]} | expiry {args.expiry} | "
          f"spread {cfg.spread_pct}% round trip inside the fill | "
          f"intrabar {'high-first' if args.optimistic else 'low-first'}")
    print("spread is charged ONCE, in the fill; costs.round_trip() adds only "
          "brokerage/STT/exchange/SEBI/stamp/GST on top.\n")
    hdr = (f"{'variant':<44} {'n':>4} {'hold':>7} {'gross':>10} {'net':>10} "
           f"{'netE':>8} {'win%':>6} {'MFE':>6} {'MAE':>6}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for v in _variants():
        if want and v.label.split()[0] not in want:
            continue
        s = run_variant(con, index_key, days, args.expiry, v, cfg)
        rows.append(s)
        if not s.get("n"):
            print(f"{v.label:<44} {'0':>4}  no trades")
            continue
        print(f"{v.label:<44} {s['n']:>4} {s['mean_hold_sec']:>6.0f}s "
              f"{s['gross_total']:>10,.0f} {s['net_total']:>10,.0f} "
              f"{s['net_expectancy']:>8,.0f} {s['net_win_rate']:>5.1f}% "
              f"{s['mean_mfe_pts']:>6.2f} {s['mean_mae_pts']:>6.2f}")
    print("\nexit branch counts")
    for s in rows:
        if s.get("n"):
            print(f"  {s['label']:<44} {s['exits']}")
    print("\nby direction (n / gross / net)")
    for s in rows:
        if s.get("n"):
            print(f"  {s['label']:<44} {s['by_direction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
