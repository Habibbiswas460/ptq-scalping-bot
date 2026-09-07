"""EXP-12 — the out-of-sample test of the opening-window finding.

EXP-11 measured 09:15-09:45 at +Rs114.06/trade against -Rs34.41 for 09:45-15:10, permutation
p=0.0057, on three sessions in which that window was *blocked* — every number came from
counterfactual entries the strategy never took. Its own `next` field asked for one thing:
re-run it on the first session that actually trades the opening. 2026-09-07 is that session.

Two arms are reported, and they answer different questions:

  counterfactual — arbitrary entries on a 30s grid inside each window, priced through the
                   production exit ladder. Directly comparable to EXP-11's numbers, and the
                   only arm that exists for the earlier sessions.
  realised       — what the bot's own trades in each window actually earned. This is the arm
                   that did not exist before today, and it is the out-of-sample test.

Unlike claude_code/experiments/exp01..exp11, this script defines no exit ladder of its own.
Every price path goes through research.replay, the DB is opened read-only by research.db.Book,
and the permutation test is research.prefilters.permutation_p. Audit finding #16 (a third,
untested ladder implementation living in this directory) does not apply to this file.

Caveats that bound every number below, unchanged from EXP-11:
  * bid/ask is fabricated at ltp +/- 0.3%, so the cost side is a model, not a measurement
  * the counterfactual arm replays persisted ticks, which are a subsample of what the live
    indicator saw, so RSI-timed exits are directional rather than exact
  * the realised arm is whatever n the session produced; it is reported, never padded

Usage:  python claude_code/experiments/exp12_opening_oos.py [DAY ...]
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
import sys
from typing import Dict, List, Sequence

sys.path.insert(0, __file__.rsplit("/claude_code/", 1)[0])

from research.db import LOT, Book, parse_ts          # noqa: E402
from research.prefilters import permutation_p, window_arms  # noqa: E402
from research.replay import Ladder                   # noqa: E402

OPEN_WINDOW = ("09:15", "09:45")
REST_WINDOW = ("09:45", "15:10")


def realised_trades(book: Book, day: str) -> List[Dict]:
    """The bot's own trades for `day`, with the entry clock time each one belongs to."""
    rows = []
    for r in book.cur.execute(
        "SELECT id, direction, entry_time, exit_time, entry_price, exit_price, pnl, "
        "exit_reason, hold_time_sec, score, confidence FROM trades "
        "WHERE date(entry_time)=? AND pnl IS NOT NULL ORDER BY entry_time",
        (day,),
    ):
        d = dict(r)
        d["t"] = parse_ts(d["entry_time"])
        rows.append(d)
    return rows


def in_window(t: _dt.datetime, lo: str, hi: str) -> bool:
    hm = t.strftime("%H:%M")
    return lo <= hm < hi


def _stat(pnls: Sequence[float]) -> Dict:
    if not pnls:
        return {"n": 0, "exp": None, "total": 0.0, "wr": None}
    wins = [p for p in pnls if p > 0]
    return {
        "n": len(pnls),
        "exp": round(_st.mean(pnls), 2),
        "total": round(sum(pnls), 2),
        "wr": round(100.0 * len(wins) / len(pnls), 1),
    }


def realised_arm(book: Book, days: Sequence[str]) -> Dict:
    opens, rest, skipped = [], [], []
    for d in days:
        for tr in realised_trades(book, d):
            if in_window(tr["t"], *OPEN_WINDOW):
                opens.append(tr["pnl"])
            elif in_window(tr["t"], *REST_WINDOW):
                rest.append(tr["pnl"])
            else:
                skipped.append(tr["pnl"])
    out = {"open": _stat(opens), "rest": _stat(rest), "outside_both": _stat(skipped)}
    # permutation_p answers "is the arm worse than the base"; the EXP-11 claim is that the
    # opening is BETTER, so the reported p is for that direction.
    if len(opens) >= 3 and len(rest) >= 3:
        p_worse = permutation_p(opens, rest)
        out["p_open_better"] = round(1.0 - p_worse, 4)
        out["gap"] = round(out["open"]["exp"] - out["rest"]["exp"], 2)
    else:
        out["p_open_better"] = None
        out["gap"] = (round(out["open"]["exp"] - out["rest"]["exp"], 2)
                      if opens and rest else None)
    return out


def counterfactual_arm(book: Book, days: Sequence[str], side: str = "CE") -> Dict:
    arms = window_arms(
        book, days,
        [("open", *OPEN_WINDOW), ("rest", *REST_WINDOW)],
        side=side, lad=Ladder(),
    )
    by = {a["window"]: a for a in arms}
    out = {"side": side}
    for k in ("open", "rest"):
        a = by.get(k)
        out[k] = a["stats"] if a else {"n": 0}
        out[f"{k}_per_day"] = a["per_day"] if a else {}
    o, r = by.get("open"), by.get("rest")
    if o and r and o["stats"]["n"] >= 3 and r["stats"]["n"] >= 3:
        p_worse = permutation_p([x["pnl"] for x in o["rows"]], [x["pnl"] for x in r["rows"]])
        out["p_open_better"] = round(1.0 - p_worse, 4)
        out["gap"] = round(o["stats"]["exp"] - r["stats"]["exp"], 2)
    else:
        out["p_open_better"] = None
        out["gap"] = None
    return out


def _fmt(s: Dict) -> str:
    if not s or not s.get("n"):
        return "n=0"
    exp = s.get("exp")
    wr = s.get("wr")
    return (f"n={s['n']:<4} exp=Rs{exp:>8}  total=Rs{s.get('total', s.get('pnl')):>9}"
            + (f"  wr={wr}%" if wr is not None else ""))


def report(days: Sequence[str]) -> int:
    book = Book()
    print("=" * 78)
    print(f"EXP-12  out-of-sample opening window   days={list(days)}   lot={LOT}")
    print("=" * 78)

    print("\n-- REALISED ARM (the bot's own trades) " + "-" * 38)
    rea = realised_arm(book, days)
    print(f"  09:15-09:45  {_fmt(rea['open'])}")
    print(f"  09:45-15:10  {_fmt(rea['rest'])}")
    if rea["outside_both"]["n"]:
        print(f"  outside both {_fmt(rea['outside_both'])}")
    print(f"  gap          {rea['gap']}")
    print(f"  p(open better) {rea['p_open_better']}"
          f"{'   [n<3 in an arm - not computed]' if rea['p_open_better'] is None else ''}")

    for side in ("CE", "PE"):
        print(f"\n-- COUNTERFACTUAL ARM ({side}, 30s grid, production ladder) " + "-" * 16)
        try:
            cf = counterfactual_arm(book, days, side)
        except Exception as e:                      # a day with no series for this side
            print(f"  unavailable: {e}")
            continue
        print(f"  09:15-09:45  {_fmt(cf['open'])}")
        print(f"  09:45-15:10  {_fmt(cf['rest'])}")
        print(f"  gap          {cf['gap']}")
        print(f"  p(open better) {cf['p_open_better']}")
        if cf["open_per_day"]:
            print(f"  per-day open: {cf['open_per_day']}")
            print(f"  per-day rest: {cf['rest_per_day']}")

    print("\n" + "=" * 78)
    print("EXP-11 for comparison: open +Rs114.06/trade, rest -Rs34.41, p=0.0057")
    print("(counterfactual only, 3 sessions, window blocked in all of them)")
    print("=" * 78)
    return 0


def main(argv: Sequence[str]) -> int:
    days = list(argv[1:]) or [_dt.date.today().isoformat()]
    return report(days)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
