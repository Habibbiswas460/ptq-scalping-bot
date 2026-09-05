"""Command line for the visual record layer.

    python -m research.visual audit                  # what the source data can support
    python -m research.visual backfill --all         # build every session that carries data
    python -m research.visual backfill 2026-09-04    # build or rebuild one session
    python -m research.visual view --all             # render the viewer from persisted records
    python -m research.visual view 2026-09-04
    python -m research.visual list                   # what is persisted
    python -m research.visual compare                # cross-session evidence page
    python -m research.visual compare --print        # ...and print the dimensions to stdout

Sessions are always discovered from the database. No date is hardcoded anywhere in this
package, so a session recorded next month is picked up by the same command.
"""
from __future__ import annotations

import sys
import time
from typing import List, Sequence

from research.db import Book
from research.visual.audit import audit_all, buildable, print_audit
from research.visual.build import build_all
from research.visual.schema import DB_PATH
from research.visual.store import Reader, Store
from research.visual.viewer import OUT_DIR, write_index, write_session

USAGE = __doc__


def cmd_audit(args: Sequence[str]) -> int:
    rows = audit_all(Book(), [a for a in args if not a.startswith("-")] or None)
    print_audit(rows)
    return 0


def cmd_backfill(args: Sequence[str]) -> int:
    book = Book()
    days = [a for a in args if not a.startswith("-")]
    rows = audit_all(book, days or None)
    targets = days or buildable(rows)
    skipped = [r["day"] for r in rows if r["day"] not in targets]
    print(f"building {len(targets)} session(s) into {DB_PATH}")
    t0 = time.time()
    totals = {}
    with Store() as store:
        def progress(d):
            print(f"  {d} ...", end=" ", flush=True)
        out = {}
        for d in targets:
            progress(d)
            s = time.time()
            c = build_all(book, store, [d])[d]
            out[d] = c
            print(f"{c['_kind']:<12} candles {c['visual_candles']:>6,}  "
                  f"legs {c['visual_market_legs']:>4}  trades {c['visual_trade_overlays']:>3}  "
                  f"signals {c['visual_signal_overlays']:>5}  ({time.time() - s:.1f}s)")
            for k, v in c.items():
                if not k.startswith("_"):
                    totals[k] = totals.get(k, 0) + v
    print(f"\ndone in {time.time() - t0:.1f}s")
    for k in sorted(totals):
        print(f"  {k:<28} {totals[k]:>8,}")
    if skipped:
        print(f"  skipped (no market data and no trades): {', '.join(skipped)}")
    return 0


def cmd_view(args: Sequence[str]) -> int:
    with Reader() as r:
        days = [a for a in args if not a.startswith("-")] or [s["session_id"] for s in r.sessions()]
        for d in days:
            print(f"  {write_session(r, d)}")
        print(f"  {write_index(r)}")
    print(f"\nviewer written to {OUT_DIR}/")
    return 0


def cmd_compare(args: Sequence[str]) -> int:
    """Render the cross-session evidence page. Nothing is persisted: the comparison is read
    from the records at request time and written only into the HTML."""
    from research.visual import query as Q
    from research.visual.compare import write_compare

    with Reader() as r:
        if "--print" in args:
            out = Q.run_all(r)
            for name, d in out.items():
                if d["excluded"]:
                    print(f"{name}: EXCLUDED — {d['excluded']}")
                    continue
                print(f"{name}: {d['question']}  [{d['provenance'].upper()}]")
                for g in d["groups"]:
                    withheld = any(v == Q.INSUFFICIENT for v in g["metrics"].values())
                    print(f"    {g['label']:<28} n={g['n']:>8,} sessions={g['sessions_covered']:<3}"
                          + ("  VALUES WITHHELD (below the floor)" if withheld else ""))
                for c in d["caveats"]:
                    print(f"    · {c}")
                print()
        path = write_compare(r)
    print(f"  {path}")
    return 0


def cmd_list(args: Sequence[str]) -> int:
    with Reader() as r:
        ss = r.sessions()
        print(f"{len(ss)} session(s) persisted in {DB_PATH}")
        print(f"{'session':<12} {'kind':<12} {'spot src':<38} {'trades':>6} {'P&L':>9}  built")
        for s in ss:
            print(f"{s['session_id']:<12} {s['kind']:<12} {(s['spot_source'] or '—'):<38} "
                  f"{s['n_trades']:>6} {(s['pnl'] if s['pnl'] is not None else 0):>9,.2f}  "
                  f"{s['built_at']}")
        print()
        for k, v in r.stats().items():
            print(f"  {k:<28} {v:>9,}")
    return 0


def main(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd, args = argv[0], argv[1:]
    fn = {"audit": cmd_audit, "backfill": cmd_backfill, "view": cmd_view,
          "list": cmd_list, "compare": cmd_compare}.get(cmd)
    if not fn:
        print(USAGE)
        return 2
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
