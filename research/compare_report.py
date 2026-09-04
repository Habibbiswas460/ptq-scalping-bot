"""Cross-session comparison and before/after.

    python -m research.compare_report                       # every session
    python -m research.compare_report 2026-09-03 2026-09-04 # two sessions, before/after

Every session joins automatically through discovery. Data-health metrics sit beside outcome
metrics on purpose: a repair can succeed by restoring observability while P&L is unchanged,
and comparing only P&L would call that a failure.
"""
from __future__ import annotations

import os
import statistics as _st
import sys
from typing import Dict, List, Optional, Sequence

from research.compare import delta, session_row, table as rows_for
from research.db import Book
from research.render import Page, chip, esc, finding, kv, table
from research.svg import Chart, heatmap

OUT_DIR = os.path.join("claude_code", "research_output")
KIND_CHIP = {"tick": "c-real", "coarse": "c-reconstructed", "trades-only": "c-missing"}


def _trend_chart(rows: Sequence[Dict], key: str, title: str, fmt="{:.0f}") -> Optional[str]:
    pts = [(i, r[key]) for i, r in enumerate(rows) if r.get(key) is not None]
    if len(pts) < 2:
        return None
    c = Chart(h=160, ml=56, mt=22, mb=30, title=title,
              subtitle="one point per session, in date order")
    c.set_x(-0.4, len(rows) - 0.6)
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    c.set_y(min(0, lo), max(0, hi))
    c.grid(3, lambda v: fmt.format(v))
    c.x_axis_labels([(i, r["day"][5:]) for i, r in enumerate(rows)])
    if lo < 0 < hi:
        c.hline(0, "var(--grid-strong)", "2 2")
    d = " ".join(("M" if i == 0 else "L") + f"{c.x(x):.1f},{c.y(v):.1f}"
                 for i, (x, v) in enumerate(pts))
    c.parts.append(f'<path d="{d}" fill="none" stroke="var(--accent)" stroke-width="1.8"/>')
    for x, v in pts:
        col = "var(--up)" if v >= 0 else "var(--dn)"
        c.dot(x, v, 3.6, col, 1.0, f"{rows[int(x)]['day']}: {fmt.format(v)}")
    return c.render()


def build_compare(days: Optional[Sequence[str]] = None, out_dir: str = OUT_DIR) -> str:
    book = Book()
    rows = rows_for(book, days)
    page = Page(
        title="PTQ Session Comparison",
        h1="Session comparison",
        standfirst="Every session that carries data, on one scale — market, selection, capture "
                   "and data health together, so a change can be told apart from a market.",
        meta=[("Sessions", len(rows)),
              ("Tick", sum(1 for r in rows if r["kind"] == "tick")),
              ("Coarse", sum(1 for r in rows if r["kind"] == "coarse")),
              ("Trades-only", sum(1 for r in rows if r["kind"] == "trades-only"))])

    head = ["Session", "Data", "Range", "Net", "Legs ≥25", "Signals", "% scored", "Accepted",
            "Trades", "WR%", "P&L ₹", "Opt avail 3m", "Captured", "δ 1m", "Mid-exact %",
            "OI %", "PE ticks"]
    body = []
    attrs = {}
    for i, r in enumerate(rows):
        attrs[i] = f'data-event="session-{r["day"]}"'
        body.append((r["day"],
                     f"<CHIP:{r['kind']}>", r.get("range"), r.get("net"), r.get("legs_25"),
                     r.get("n_signals"), r.get("pct_scored"), r.get("accepted"),
                     r.get("n_trades"), r.get("wr"), r.get("pnl"), r.get("opt_available_3m"),
                     r.get("captured"), r.get("delta_1m"), r.get("midpoint_exact_pct"),
                     r.get("oi_pct"), r.get("pe_ticks")))
    html = table(head, body, num_cols=tuple(range(2, 17)), row_attrs=attrs)
    for kind, cls in KIND_CHIP.items():
        html = html.replace(f"&lt;CHIP:{kind}&gt;",
                            f'<span class="chip {cls}">{kind}</span>')
    sec = [html]
    for key, title, fmt in (("range", "Market range by session (spot pts)", "{:.0f}"),
                            ("pct_scored", "Share of evaluations reaching the scoring stack (%)", "{:.0f}"),
                            ("opt_available_3m", "Option movement offered in 3 minutes (pts)", "{:.1f}"),
                            ("captured", "Movement captured per trade (pts)", "{:.1f}")):
        ch = _trend_chart(rows, key, title, fmt)
        if ch:
            sec.append(ch)
    tick = [r for r in rows if r["kind"] == "tick"]
    finds = [finding(
        f"{len(rows)} sessions carry data: {len(tick)} with ticks, "
        f"{sum(1 for r in rows if r['kind']=='coarse')} coarse, "
        f"{sum(1 for r in rows if r['kind']=='trades-only')} with trades but no market context.",
        "Discovered from ticks, dvf_signals and trades rather than listed.",
        "High for coverage. Any metric mixing the three kinds is not comparable across them.",
        "Read trends within one data kind only, and treat the trades-only era as unstudied "
        "rather than as evidence.",
        "Trends become readable at roughly ten tick sessions; each new one joins automatically.")]
    page.add("All sessions", "".join(sec), finds)

    if days and len(days) == 2:
        a, b = session_row(book, days[0]), session_row(book, days[1])
        d = delta(a, b)
        page.add(f"Before / after · {days[0]} → {days[1]}",
                 table(["Metric", days[0], days[1], "Δ"],
                       [(r["metric"], r["a"], r["b"], r["delta"]) for r in d],
                       num_cols=(1, 2, 3)),
                 [finding(
                     "Data-health metrics are shown beside outcome metrics deliberately.",
                     f"{len(d)} metrics compared across the two sessions.",
                     "Two sessions is not a trend; this is a difference, not a result.",
                     "Judge a repair on whether coverage and variance improved, not only on "
                     "P&L. A repair that restores observability has succeeded even if P&L is "
                     "flat.",
                     "Repeat once several post-change sessions exist.")])
    return page.write(os.path.join(out_dir, "comparison.html"))


def main(argv: Sequence[str]) -> int:
    days = [a for a in argv if not a.startswith("--")]
    p = build_compare(days or None)
    print(f"wrote {p} ({os.path.getsize(p):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
