"""One compact reading of a live session: what was entered, why, and what it cost.

Watching a session by tailing app.log does not answer the questions that matter —
which contract was actually traded, what its delta was, which signal component
fired, how long it was held, and whether the trade made money *after* costs. Those
live in three different files (trades.csv, events.json, summary.json) in three
different shapes.

    ./venv/bin/python -m research.session_digest [YYYY-MM-DD]

Costs are charged from research/costs.py, the same model the live risk manager
uses, so the net column here and the bot's own accounting cannot disagree. Trades
still open are shown as open rather than marked to anything.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import sys
from collections import Counter
from typing import Dict, List, Optional

from research.costs import CostModel


def _load_trades(day_dir: str) -> List[Dict]:
    """Pair ENTRY and EXIT rows by trade_id. A trade with no EXIT row is open."""
    path = os.path.join(day_dir, "trades.csv")
    if not os.path.exists(path):
        return []
    legs: Dict[str, Dict] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            tid = row.get("trade_id")
            if not tid:
                continue
            t = legs.setdefault(tid, {"trade_id": tid})
            if row.get("event") == "ENTRY":
                t.update(entry_time=row.get("timestamp"), symbol=row.get("symbol"),
                         qty=row.get("qty"), entry_price=row.get("entry_price"),
                         entry_reason=row.get("entry_reason"), delta=row.get("delta"),
                         strike=row.get("strike"), spot=row.get("spot_price"))
            elif row.get("event") == "EXIT":
                t.update(exit_time=row.get("timestamp"), exit_price=row.get("exit_price"),
                         pnl=row.get("pnl"), hold=row.get("hold_time_sec"),
                         exit_reason=row.get("exit_reason"))
    return [legs[k] for k in sorted(legs, key=lambda k: legs[k].get("entry_time") or "")]


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _signal_reasons(day_dir: str) -> List[str]:
    """The state_change into ENTRY_READY carries the signal that fired."""
    path = os.path.join(day_dir, "events.json")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:                       # one JSON object per line
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "state_change" and ev.get("new_state") == "ENTRY_READY":
                out.append(ev.get("reason", ""))
    return out


def digest(day: Optional[datetime.date] = None, brokerage: float = 20.0) -> int:
    day = day or datetime.date.today()
    day_dir = os.path.join("logs", day.isoformat())
    if not os.path.isdir(day_dir):
        print(f"no session directory: {day_dir}")
        return 1

    model = CostModel(brokerage_per_order=brokerage)
    trades = _load_trades(day_dir)

    print(f"\nSESSION {day}   ({len(trades)} trades)\n" + "=" * 108)
    if trades:
        print(f"{'entry':<9}{'contract':<22}{'delta':>6}{'in':>8}{'out':>8}"
              f"{'hold':>6}{'gross':>9}{'cost':>8}{'net':>9}  exit")
        print("-" * 108)

    g_tot = c_tot = n_tot = 0.0
    wins = closed = 0
    exit_reasons: Counter = Counter()

    for t in trades:
        entry, qty = _f(t.get("entry_price")), int(_f(t.get("qty")))
        if "exit_price" not in t:
            print(f"{(t.get('entry_time') or '')[11:19]:<9}{t.get('symbol', ''):<22}"
                  f"{_f(t.get('delta')):>6.2f}{entry:>8.2f}{'OPEN':>8}")
            continue
        exit_, gross = _f(t.get("exit_price")), _f(t.get("pnl"))
        cost = model.round_trip(entry, exit_, qty) if entry > 0 and exit_ > 0 and qty > 0 else 0.0
        net = gross - cost
        g_tot, c_tot, n_tot = g_tot + gross, c_tot + cost, n_tot + net
        closed += 1
        wins += 1 if net > 0 else 0
        reason = (t.get("exit_reason") or "")[:34]
        exit_reasons[reason.split(":")[0][:24]] += 1
        print(f"{(t.get('entry_time') or '')[11:19]:<9}{t.get('symbol', ''):<22}"
              f"{_f(t.get('delta')):>6.2f}{entry:>8.2f}{exit_:>8.2f}"
              f"{_f(t.get('hold')):>6.0f}{gross:>+9.2f}{cost:>8.2f}{net:>+9.2f}  {reason}")

    print("=" * 108)
    if closed:
        print(f"{'TOTAL':<9}{'':<22}{'':>6}{'':>8}{'':>8}{'':>6}"
              f"{g_tot:>+9.2f}{c_tot:>8.2f}{n_tot:>+9.2f}")
        print(f"\n  closed {closed}   net winners {wins} ({wins / closed * 100:.1f}%)   "
              f"net expectancy Rs{n_tot / closed:+.2f}/trade   "
              f"cost is {c_tot / abs(g_tot) * 100:.0f}% of gross magnitude"
              if g_tot else "")
        if exit_reasons:
            print("\n  exits: " + ", ".join(f"{k}={v}" for k, v in exit_reasons.most_common()))

    sigs = _signal_reasons(day_dir)
    if sigs:
        comp: Counter = Counter()
        for s in sigs:
            for part in s.split("|"):
                part = part.strip()
                if part and not part.startswith(("Conf:", "Score:")):
                    comp[part[:26]] += 1
        print(f"\n  {len(sigs)} signals reached ENTRY_READY; components fired:")
        for k, v in comp.most_common(12):
            print(f"      {v:>4}x  {k}")
    return 0


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    day = None
    if argv:
        try:
            day = datetime.date.fromisoformat(argv[0])
        except ValueError:
            print(f"usage: python -m research.session_digest [YYYY-MM-DD] (got {argv[0]!r})")
            return 2
    return digest(day)


if __name__ == "__main__":
    raise SystemExit(main())
