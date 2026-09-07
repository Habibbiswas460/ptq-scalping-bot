"""Run the replay and print gross vs net.

    ./venv/bin/python -m research.backtest.run --expiry 2026-09-08
    ./venv/bin/python -m research.backtest.run --expiry 2026-09-08 --optimistic
    ./venv/bin/python -m research.backtest.run --expiry 2026-09-08 --split

`--split` reports the first and second halves of the sessions separately. It is
not a walk-forward validation and is not presented as one; it is the cheapest
available check on whether a single session is carrying the whole result.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from typing import List, Optional

from research.backtest import store
from research.backtest.harness import Config, Replay, exit_breakdown, summarise

ANGEL = "angelone_smartapi"


def _index_key() -> str:
    from config.constants import NIFTY_SPOT_TOKEN
    return f"NSE:{NIFTY_SPOT_TOKEN}"


def _fmt(label: str, s: dict) -> str:
    if not s.get("n"):
        return f"{label}: no trades"
    return (
        f"{label}\n"
        f"  trades {s['n']} over {s['sessions']} sessions | "
        f"mean hold {s['mean_hold_sec']:.0f}s\n"
        f"  GROSS  total Rs{s['gross_total']:>10,.2f} | expectancy Rs{s['gross_expectancy']:>8,.2f} | "
        f"win rate {s['gross_win_rate']:.1f}%\n"
        f"  SPREAD total Rs{s['spread_total']:>10,.2f} | mean       Rs{s['mean_spread']:>8,.2f} | "
        f"(already inside GROSS above)\n"
        f"  CHARGES total Rs{s['cost_total']:>9,.2f} | mean       Rs{s['mean_cost']:>8,.2f} | "
        f"{s['cost_points_per_lot']:.3f} pts/lot\n"
        f"  NET    total Rs{s['net_total']:>10,.2f} | expectancy Rs{s['net_expectancy']:>8,.2f} | "
        f"win rate {s['net_win_rate']:.1f}%\n"
        f"  avg win Rs{s['avg_win']:,.2f} | avg loss Rs{s['avg_loss']:,.2f} | "
        f"break-even win rate {s['breakeven_win_rate_gross']:.1f}% gross -> "
        f"{s['breakeven_win_rate_net']:.1f}% net\n"
        f"  mean MFE {s['mean_mfe_pts']:+.3f} pts | mean MAE {s['mean_mae_pts']:+.3f} pts"
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="research.backtest.run", description=__doc__)
    p.add_argument("--expiry", required=True, help="option expiry, e.g. 2026-09-08")
    p.add_argument("--from", dest="frm")
    p.add_argument("--to", dest="to")
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--spread-pct", type=float, default=None,
                   help="round-trip spread as %% of premium (default 0.246, measured)")
    p.add_argument("--half-spread", type=float, default=None,
                   help="fixed points per side, overrides --spread-pct")
    p.add_argument("--optimistic", action="store_true",
                   help="intrabar high before low (the favourable assumption)")
    p.add_argument("--split", action="store_true")
    args = p.parse_args(argv)

    con = store.connect()
    index_key = _index_key()

    days = [r[0] for r in con.execute(
        """SELECT DISTINCT c.session_date FROM candles c
           JOIN instruments i ON i.instrument_key=c.instrument_key
           WHERE c.source=? AND i.kind IN ('CE','PE') AND i.expiry=?
           ORDER BY c.session_date""", (ANGEL, args.expiry))]
    if args.frm:
        days = [d for d in days if d >= args.frm]
    if args.to:
        days = [d for d in days if d <= args.to]
    if not days:
        print(f"no option candles for expiry {args.expiry}", file=sys.stderr)
        return 1

    cfg = Config(lots=args.lots, optimistic_intrabar=args.optimistic)
    if args.spread_pct is not None:
        cfg.spread_pct = args.spread_pct
    if args.half_spread is not None:
        cfg.half_spread = args.half_spread

    print(f"replaying {len(days)} sessions ({days[0]}..{days[-1]}) on expiry {args.expiry}")
    # Measured, not assumed: adverse-first turns out to be the FLATTERING order
    # for this ladder, because stopping out early beats arming a trailing stop
    # that then gives the move back. Labelled by what it does, not by intent.
    print("intrabar ordering: " + ("high before low" if args.optimistic
                                   else "low before high (the FLATTERING order for this ladder)"))
    if cfg.half_spread is not None:
        sp = f"fixed {cfg.half_spread} pts/side"
    else:
        sp = f"{cfg.spread_pct}% of premium round trip (measured on this project's ticks)"
    print(f"spread crossed in the fill: {sp} | lots {cfg.lots} x {cfg.lot_size}")
    print("spread is inside GROSS (fills cross the book, as live does); "
          "brokerage/STT/GST are added on top, so spread is charged once.\n")

    rep = Replay(cfg)
    for d in days:
        n_before = len(rep.trades)
        rep.run_session(con, index_key, d, args.expiry)
        got = rep.trades[n_before:]
        gross = sum(t.gross_pnl for t in got)
        net = sum(t.net_pnl(cfg.cost_model) for t in got)
        print(f"  {d}  trades={len(got):>2}  gross Rs{gross:>9,.2f}  net Rs{net:>9,.2f}")

    print(f"\nsignal evaluations: {rep.evaluations:,} | signals fired: {rep.signals} | "
          f"entries lost to an unlisted/untraded contract: {rep.entries_blocked_no_contract}")
    print("\ntop rejection reasons (why the stack said no):")
    for reason, n in sorted(rep.rejections.items(), key=lambda kv: -kv[1])[:8]:
        print(f"   {n:>6}  {reason}")

    print()
    print(_fmt("ALL SESSIONS", summarise(rep.trades, cfg.cost_model)))

    if rep.trades:
        print("\nexits by branch:")
        for reason, b in exit_breakdown(rep.trades).items():
            print(f"   {b['n']:>3}  Rs{b['gross']:>10,.2f} gross   {reason}")

    if args.split and len(days) >= 4:
        mid = len(days) // 2
        first = [t for t in rep.trades if t.session_date in set(days[:mid])]
        second = [t for t in rep.trades if t.session_date in set(days[mid:])]
        print("\n" + _fmt(f"FIRST HALF ({days[0]}..{days[mid-1]})",
                          summarise(first, cfg.cost_model)))
        print("\n" + _fmt(f"SECOND HALF ({days[mid]}..{days[-1]})",
                          summarise(second, cfg.cost_model)))
        print("\nThis split is a sanity check on concentration, NOT an out-of-sample "
              "validation: nothing was fitted on the first half.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
