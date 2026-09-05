"""One command to run after a live-paper session.

    python -m research.after_session 2026-09-07
    python -m research.after_session            # newest session with data

Runs the whole pipeline in order and prints a short console summary, so nothing has to be
remembered or reconstructed by hand. Data quality is checked and reported first: when it has
regressed, that is the headline, not the P&L.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Sequence

from research.compare import session_row
from research.db import Book
from research.execution import quote_quality
from research.prefilters import ladder_counts
from research.signals import component_stats

OUT_DIR = os.path.join("claude_code", "research_output")


def _run(mod: str, args: Sequence[str] = ()) -> Optional[str]:
    cmd = [sys.executable, "-m", mod, *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ! {mod} failed:\n{r.stderr.strip()[-600:]}")
        return None
    line = (r.stdout.strip().splitlines() or [""])[-1]
    print(f"  {line}")
    return line


def summary(book: Book, day: str, prev: Optional[str]) -> None:
    q = quote_quality(book, day)
    lc = ladder_counts(book, day)
    comps = component_stats(book, day)
    dead = [c["component"] for c in comps if c["constant"]]
    row = session_row(book, day)

    print()
    print("DATA QUALITY FIRST — a regression here outranks any P&L")
    if q.get("n"):
        print(f"  quotes        : {q['midpoint_exact_pct']}% midpoint-exact  "
              f"({'FABRICATED' if q['midpoint_exact_pct'] >= 95 else 'inspect — some may be real'})")
        print(f"  open interest : {q['oi_populated_pct']}% populated"
              f"{'  <-- repair landed' if q['oi_populated_pct'] > 0 else '  (still absent)'}")
        print(f"  timestamps    : {q['collision_pct']}% same-second collisions")
        print(f"  PE coverage   : {q['pe_ticks']:,} PE ticks"
              f"{'  <-- still a coverage failure' if q['pe_ticks'] < 2000 else ''}")
    else:
        print("  no tick rows for this session")

    print()
    print("SELECTION")
    print(f"  evaluations   : {lc['total']:,}")
    print(f"  reached score : {lc['scored']:,} ({lc['pct_scored']}%)")
    print(f"  accepted      : {lc['accepted']}")
    print(f"  constant comps: {len(dead)} of {len(comps)}"
          + (f"  ({', '.join(dead)})" if dead else "")
          + ("  <-- delta/greeks/oi still constant"
             if {"delta", "greeks", "oi"} & set(dead) else
             "  <-- delta/greeks/oi now vary"))

    print()
    print("OUTCOME")
    for k, lab in (("n_trades", "trades"), ("wr", "win rate %"), ("pnl", "P&L Rs"),
                   ("opt_available_3m", "option offered 3m"), ("captured", "captured"),
                   ("delta_1m", "realised delta 1m")):
        if row.get(k) is not None:
            print(f"  {lab:<18}: {row[k]}")

    if prev:
        p = session_row(book, prev)
        print()
        print(f"VS {prev}")
        for k, lab in (("pct_scored", "% reached scoring"), ("score_pairs", "score/conf pairs"),
                       ("oi_pct", "OI populated %"), ("opt_available_3m", "option offered 3m"),
                       ("captured", "captured"), ("pnl", "P&L Rs")):
            a, b = p.get(k), row.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                print(f"  {lab:<20}: {a}  ->  {b}   ({b - a:+.2f})")

    print()
    print("NOT ANSWERED HERE — read the reports, then decide")
    print("  did the opening window hold?      section 'Movement by time of day' + EXP-11")
    print("  did the repair restore ranking?   section 'Scoring stack'")
    print("  what did the gates cost?          rerun with --deep, or exp11_prefilters.py")


def main(argv: Sequence[str]) -> int:
    book = Book()
    with_data = [s["day"] for s in book.sessions() if s["kind"] in ("tick", "coarse")]
    args = [a for a in argv if not a.startswith("--")]
    day = args[0] if args else (with_data[-1] if with_data else None)
    if not day:
        print("no session with market data found")
        return 1
    prev = None
    if day in with_data and with_data.index(day) > 0:
        prev = with_data[with_data.index(day) - 1]

    print(f"PTQ post-session research · {day}" + (f"  (previous: {prev})" if prev else ""))
    print("=" * 72)
    _run("research.session", [day] + (["--deep"] if "--deep" in argv else []))
    _run("research.compare_report", [prev, day] if prev else [])
    _run("research.synthesis")
    _run("research.experiment")
    print("=" * 72)
    summary(book, day, prev)
    print()
    print(f"reports in {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
