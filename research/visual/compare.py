"""The cross-session evidence page.

It arranges what `research.visual.query` returns and nothing else: no number on this page is
computed here, none is persisted, and none is a conclusion. Every group carries its row count,
how many sessions it drew on, its provenance and its caveats, because those are what decide
whether a difference between two groups can be read at all.

Three things this page does that a dashboard would not:

* a group below the reporting floor is drawn as a hatched placeholder labelled INSUFFICIENT,
  never as a bar of height zero, and its recorded facts are still printed
* four dimensions the record cannot support get a section of their own stating why, rather than
  being silently absent
* nothing is sorted by size, so no chart can be read as a ranking

Where two groups differ, the page says they differ. It does not say why, and it never says one
is better.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from research.render import Page, esc, kv, table
from research.svg import heatmap
from research.visual import charts
from research.visual import query as Q
from research.visual.store import DB_PATH, Reader
from research.visual.viewer import OUT_DIR, TABS_CSS, chip

PAGE_BUDGET_KB = 900


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if v == Q.INSUFFICIENT:
        return Q.INSUFFICIENT
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def _caveats(items: Sequence[str]) -> str:
    if not items:
        return ""
    return ("<div class='flag note'><h4>Read this first</h4><p>"
            + "; ".join(esc(c) for c in items) + "</p></div>")


def _group_table(groups: Sequence[Dict], metric_keys: Optional[Sequence[str]] = None) -> str:
    """Groups as rows: identity and coverage first, then facts, then comparison metrics."""
    if not groups:
        return ""
    facts = sorted({k for g in groups for k in g.get("facts", {})})
    keys = list(metric_keys) if metric_keys else sorted(
        {k for g in groups for k in g["metrics"]})
    head = ["group", "n", "sessions", "provenance"] + facts + keys
    rows = []
    for g in groups:
        row = [g["label"], f"{g['n']:,}", g["sessions_covered"],
               chip(g["provenance"].upper(), g["provenance"])]
        row += [_fmt(g.get("facts", {}).get(f)) for f in facts]
        row += [_fmt(g["metrics"].get(k)) for k in keys]
        rows.append(row)
    num = tuple(range(1, 3)) + tuple(range(4 + len(facts), 4 + len(facts) + len(keys)))
    return table(head, rows, num_cols=num)


def _section(page: Page, name: str, d: Dict, *, body: str = "",
             metric_keys: Optional[Sequence[str]] = None) -> None:
    if d["excluded"]:
        page.add(name,
                 f"<p>{chip('EXCLUDED', 'missing')} This comparison is not offered, because the "
                 f"record cannot support it: {esc(d['excluded'])}</p>")
        return
    head = f"<p>{esc(d['question'])}</p>" if d["question"] else ""
    if d.get("per_session_only"):
        head += (f"<p>{chip('PER SESSION ONLY', 'reconstructed')} These rows must not be "
                 f"summed; the query layer refuses to pool them.</p>")
    page.add(name, head + _caveats(d["caveats"]) + body + _group_table(d["groups"], metric_keys))


def compare_page(reader: Reader) -> Page:
    out = Q.run_all(reader)
    sessions = reader.sessions()
    n_excluded = sum(1 for d in out.values() if d["excluded"])
    n_insufficient = sum(1 for d in out.values() if not d["excluded"]
                         for g in d["groups"]
                         if any(v == Q.INSUFFICIENT for v in g["metrics"].values()))

    page = Page(
        title="PTQ cross-session evidence",
        h1="Cross-session evidence",
        standfirst=(
            "The same persisted records, sliced several ways. Every group carries its size, its "
            "session coverage and its provenance, because a difference between two groups means "
            "nothing without them. Nothing here is a conclusion, nothing is ranked, and no "
            "significance is computed."),
        meta=[("sessions", len(sessions)),
              ("dimensions", len(out)),
              ("excluded", n_excluded),
              ("groups withheld as INSUFFICIENT", n_insufficient),
              ("store", DB_PATH),
              ("persisted", "no — comparisons are read, never written")])

    page.add("How to read this",
             f"<style>{TABS_CSS}</style>{charts.gap_defs()}"
             "<p>Three marks carry the weight here. "
             f"{chip('REAL', 'real')} a value the live system wrote; "
             f"{chip('RECONSTRUCTED', 'reconstructed')} derived from real rows by this layer; "
             f"{chip('MISSING', 'missing')} absent from the source and never filled in. "
             "A group with fewer rows than the reporting floor shows "
             f"<b>{Q.INSUFFICIENT}</b> instead of a number and a hatched placeholder instead of "
             "a bar — its recorded facts are still printed, because withholding a value the "
             "record plainly contains would hide data as surely as dropping the group.</p>"
             "<p>Charts keep the record's order, never size order, so none of them can be read "
             "as a ranking. Where a comparison cannot be supported at all it appears as its own "
             "section explaining why, rather than being left out.</p>"
             + kv([("reporting floor", f"{Q.MIN_GROUP_N} rows"),
                   ("dimensions offered", len(out) - n_excluded),
                   ("dimensions refused", n_excluded),
                   ("comparison results persisted", "none")]))

    _section(page, "Session by session", out["session_vs_session"],
             metric_keys=["trades", "wins", "losses", "gross_pnl_sum", "gross_pnl_mean",
                          "with_movement_evidence"])

    d = out["opening_window_vs_rest"]
    _section(page, "Opening window against the rest of the day", d,
             body=charts.render_group_bars(
                 d["groups"], "evaluations", title="Evaluations by part of day",
                 subtitle="REAL counts · the window holds no accepted evaluation and no trade",
                 fmt=lambda v: f"{v:,.0f}"))

    _section(page, "CE against PE — recorded outcome", out["ce_vs_pe_outcome"],
             body=charts.render_group_bars(
                 out["ce_vs_pe_outcome"]["groups"], "gross_pnl_sum",
                 title="Gross P&L by side", subtitle="REAL · gross, costs are MISSING"))
    _section(page, "CE against PE — movement", out["ce_vs_pe_movement"])

    _section(page, "Winners against losers — price fields", out["win_vs_loss_price"])
    d = out["win_vs_loss_movement"]
    _section(page, "Winners against losers — movement", d,
             body=charts.render_group_cascade(
                 d["groups"], title="Movement offered and kept",
                 subtitle="RECONSTRUCTED over 180s · 24 trades, 23 of them CE, 3 sessions"))

    _section(page, "Accepted against rejected", out["accepted_vs_rejected"],
             metric_keys=["accepted", "rejected", "accept_rate_pct",
                          "accepted_with_market_view"])

    d = out["rejection_cause"]
    _section(page, "What stopped an evaluation", d,
             body=charts.render_group_bars(
                 d["groups"], "evaluations", title="Rejections by cause",
                 subtitle="RECONSTRUCTED from the rejection text · the original gate label is "
                          "preserved unchanged elsewhere",
                 fmt=lambda v: f"{v:,.0f}"))

    d = out["leg_size"]
    _section(page, "Market moves and whether the strategy was in them", d,
             body=charts.render_group_bars(
                 d["groups"], "participation_pct",
                 title="Share of legs containing a trade",
                 subtitle="RECONSTRUCTED · 6 sessions carry a spot series; 17 carry none",
                 fmt=lambda v: f"{v:,.1f}%"))

    d = out["session_type"]
    _section(page, "The session's own phases", d,
             body=charts.render_group_bars(
                 d["groups"], "accepted", title="Accepted evaluations by phase",
                 subtitle="REAL · OPEN here is 09:20–10:30, not the 09:15–09:45 window",
                 fmt=lambda v: f"{v:,.0f}"))

    d = out["state_at_entry"]
    _section(page, "What state the strategy was in at entry", d,
             body=charts.render_group_bars(
                 d["groups"], "trades", title="Trades by loss streak at entry",
                 subtitle="RECONSTRUCTED as of each exit · withheld groups are hatched",
                 fmt=lambda v: f"{v:,.0f}"))
    _section(page, "Cooldown at entry", out["cooldown_at_entry"])

    d = out["market_quality_bands"]
    _section(page, "Market-quality grade the trade recorded", d,
             body=charts.render_group_bars(
                 d["groups"], "trades", title="Trades by recorded grade",
                 subtitle="REAL · taken from the trade row, never from a nearby evaluation",
                 fmt=lambda v: f"{v:,.0f}"))

    _section(page, "How much the score and confidence actually vary",
             out["score_confidence_cardinality"])
    _section(page, "Confidence bands", out["pooled_confidence_band"])
    _section(page, "Regime", out["regime"])

    d = out["coverage_matrix"]
    fields = [g["label"] for g in d["groups"]]
    states = sorted({s for g in d["groups"] for s in g["metrics"]})
    values = {(f, s): (g["metrics"].get(s) or None)
              for f, g in zip(fields, d["groups"]) for s in states}
    _section(page, "Coverage — the denominator for everything above", d,
             body=heatmap(fields, states, values,
                          fmt=lambda v: f"{v:.0f}",
                          title="Sessions per field and provenance state",
                          legend="how many of the 23 sessions hold each field in each state; "
                                 "an empty cell is no session, not a zero measurement"))

    page.add("What this page is not",
             "<p>It computes no significance and offers no ranking, threshold or "
             "recommendation. A gap between two groups here is a gap in the record, not a "
             "cause: the sessions differ in kind, window, coverage and sample size all at once, "
             "and nothing on this page separates those. Where a comparison would need an "
             "experiment — a stated hypothesis, a controlled change, a replay — that experiment "
             "belongs in the experiment ledger, not here.</p>"
             + kv([("comparisons persisted", "none — read at request time from the records"),
                   ("records written by this page", "none"),
                   ("reader", "research.visual.store.Reader"),
                   ("query layer", "research.visual.query"),
                   ("renderer", "research.visual.charts")]))
    return page


def write_compare(reader: Reader, out_dir: str = OUT_DIR) -> str:
    return compare_page(reader).write(os.path.join(out_dir, "compare.html"))
