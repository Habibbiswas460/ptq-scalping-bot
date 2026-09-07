"""EXP-14 — the break-even hit rate every exit geometry needs, and what the market supplies.

This is the measurement that explains the whole record, and it needs no signal at all.

Priced at real costs (research/costs.py: 1.162 option points per round trip on one lot), a
target/stop pair has an arithmetic break-even hit rate:

    net win  = target - cost          net loss = stop + cost
    break-even P(target first) = net_loss / (net win + net loss)

For the ladder the bot ACTUALLY ran — the RSI profit floor at ~1.65 points against the early
loss cut at 2.5 — that is **88.3%**. For the bracket the config DECLARES (TP 14 / SL 7) it is
38.9%. The audit's finding #10 was that the declared bracket never governed a single exit
(0 of 34); this says why that mattered: a viable geometry was configured and a non-viable one
was running, and the RSI/loss-cut pair fired first every time.

Then the second half: what the market actually supplies. Walking real option ticks forward from
arbitrary instants — no signal, no selection — and asking which level is touched first inside a
900-second hold:

    ladder        needs    09-02  09-03  09-04  09-07   mean
    +1.65/-2.5    88.3%     62.2   54.5   57.3   54.7   57.2%
    +2.00/-2.5    81.4%     59.0   49.6   53.1   50.5   53.0%
    +4.00/-2.5    56.3%     44.4   35.2   36.7   30.4   36.6%
    +6.00/-3.0    46.2%     38.9   22.5   32.0   23.5   29.2%
    +8.00/-4.0    43.0%     37.9   16.5   27.2   16.5   24.5%
    +14.0/-7.0    38.9%     31.3    9.9   13.8    0.2   13.8%

**No geometry clears its own break-even.** Widening the target lowers what you need, but it
lowers what you get faster, so the gap widens rather than closes — which is what a long option
position should look like when the premium it pays is the premium someone else is collecting,
and holding costs theta.

So the bar for an entry signal is explicit: on +6/-3 it would have to lift the hit rate from
29.2% to above 46.2%, a ~58% relative improvement over arbitrary timing. EXP-05 found no
evidence the current signal beats arbitrary timing at all.

Caveats, which matter: four sessions; one contract per day (the most-ticked); long the option
only; unresolved paths (neither level touched inside the hold) are excluded, which FLATTERS
every row, since a real trade would exit on time at whatever price then stood. Costs are
Zerodha's published rates at a Rs184 premium.

Usage:  python claude_code/experiments/exp14_ladder_geometry.py [DAY ...]
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
from typing import List, Sequence, Tuple

sys.path.insert(0, __file__.rsplit("/claude_code/", 1)[0])

from research.costs import DEFAULT                      # noqa: E402
from research.db import DB_PATH                         # noqa: E402

LADDERS: Sequence[Tuple[float, float, str]] = (
    (1.65, 2.5, "the ladder that actually ran (RSI floor vs early cut)"),
    (2.00, 2.5, "RSI-exit minimum vs early cut"),
    (4.00, 2.5, ""),
    (6.00, 3.0, ""),
    (8.00, 4.0, ""),
    (14.0, 7.0, "the DECLARED bracket, which never governed an exit"),
)
MAX_HOLD_SEC = 900
PREMIUM = 184.0


def breakeven_hit_rate(target: float, stop: float, cost_pts: float) -> float:
    win, loss = target - cost_pts, stop + cost_pts
    return 100.0 * loss / (win + loss) if (win + loss) > 0 else float("nan")


def series(con, day: str) -> List[Tuple[_dt.datetime, float]]:
    sym = con.execute(
        "SELECT symbol, count(*) n FROM ticks WHERE date(timestamp)=? "
        "GROUP BY symbol ORDER BY n DESC LIMIT 1", (day,)).fetchone()
    if not sym:
        return []
    rows = con.execute(
        "SELECT timestamp, ltp FROM ticks WHERE date(timestamp)=? AND symbol=? ORDER BY id",
        (day, sym[0])).fetchall()
    return [(_dt.datetime.strptime(t.split(".")[0], "%Y-%m-%d %H:%M:%S"), p) for t, p in rows]


def hit_rate(ser, target: float, stop: float, samples: int = 1200) -> float:
    """P(target touched before stop) from arbitrary instants. Paths that touch neither inside
    MAX_HOLD_SEC are excluded — which flatters the result, deliberately and visibly."""
    n = len(ser)
    if n < 50:
        return float("nan")
    step = max(1, n // samples)
    wins = resolved = 0
    for i in range(0, n, step):
        t0, p0 = ser[i]
        j, outcome = i, None
        while j < n and (ser[j][0] - t0).total_seconds() <= MAX_HOLD_SEC:
            d = ser[j][1] - p0
            if d >= target:
                outcome = True
                break
            if d <= -stop:
                outcome = False
                break
            j += 1
        if outcome is None:
            continue
        resolved += 1
        wins += outcome
    return 100.0 * wins / resolved if resolved else float("nan")


def main(argv: Sequence[str]) -> int:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    days = list(argv[1:]) or [r[0] for r in con.execute(
        "SELECT date(timestamp) d FROM ticks GROUP BY d HAVING count(*)>500 ORDER BY d")]
    sers = {d: series(con, d) for d in days}
    days = [d for d in days if sers[d]]

    for lots in (1, 2, 8):
        cost = DEFAULT.points(PREMIUM, lots=lots)
        print(f"\n{'='*86}\n{lots} lot(s) — round trip {cost:.3f} option points"
              f"  (margin ~Rs{15000*lots:,})\n{'='*86}")
        print(f"{'ladder':<14}{'needs':>8}" + "".join(f"{d[5:]:>9}" for d in days)
              + f"{'mean':>9}   verdict")
        for tp, sl, note in LADDERS:
            need = breakeven_hit_rate(tp, sl, cost)
            got = [hit_rate(sers[d], tp, sl) for d in days]
            mean = sum(got) / len(got)
            verdict = "VIABLE" if mean >= need else "no"
            line = (f"{f'+{tp}/-{sl}':<14}{need:>7.1f}%"
                    + "".join(f"{g:>8.1f}%" for g in got)
                    + f"{mean:>8.1f}%   {verdict}")
            print(line + (f"   <- {note}" if note else ""))
    print("\nUnresolved paths are excluded, which flatters every row above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
