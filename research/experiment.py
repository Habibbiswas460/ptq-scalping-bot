"""Experiment ledger view.

    python -m research.experiment            # the whole ledger
    python -m research.experiment EXP-11     # one experiment

Retractions and supersessions render as prominently as confirmations. Three findings in this
project have already been overturned; a ledger that showed only successes would have hidden
all three.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Sequence

from research.ledger import get, load
from research.render import Page, esc, finding, kv, table

OUT_DIR = os.path.join("claude_code", "research_output")


def _status(e: Dict) -> str:
    if e.get("retracted"):
        return '<span class="chip c-invalid">retracted</span>'
    if e.get("superseded_by"):
        return f'<span class="chip c-missing">superseded by {esc(e["superseded_by"])}</span>'
    return '<span class="chip c-real">standing</span>'


def _entry_block(e: Dict) -> str:
    rows = [("Hypothesis", e.get("hypothesis")),
            ("Variable changed", e.get("variable")),
            ("Control", e.get("control")),
            ("Treatment", e.get("treatment")),
            ("Dataset", e.get("dataset")),
            ("Sample size", e.get("n")),
            ("Baseline", e.get("baseline")),
            ("Commit", e.get("commit"))]
    out = [f"<p class='cap'>{_status(e)} &nbsp; <b>{esc(e['id'])}</b> · {esc(e.get('date'))}</p>",
           kv([(k, v) for k, v in rows if v]),
           "<div class='find'><dl>"
           f"<dt>Result</dt><dd>{esc(e.get('result',''))}</dd>"
           f"<dt>Confidence</dt><dd class='soft'>{esc(e.get('confidence',''))}</dd>"
           f"<dt>Decision</dt><dd>{esc(e.get('decision',''))}</dd>"
           f"<dt>Next test</dt><dd class='soft'>{esc(e.get('next',''))}</dd></dl></div>"]
    return "".join(out)


def build_experiment(exp_id: Optional[str] = None, out_dir: str = OUT_DIR) -> str:
    entries = load()
    if exp_id:
        e = get(exp_id)
        if not e:
            raise SystemExit(f"no such experiment: {exp_id} "
                             f"(have: {', '.join(x['id'] for x in entries)})")
        page = Page(title=f"PTQ {e['id']}", h1=f"{e['id']} · experiment record",
                    standfirst=esc(e.get("hypothesis", "")),
                    meta=[("Date", e.get("date")), ("Baseline", e.get("baseline")),
                          ("Commit", e.get("commit") or "—")])
        page.add("Record", _entry_block(e))
        return page.write(os.path.join(out_dir, f"experiment_{e['id']}.html"))

    live = [e for e in entries if not e.get("retracted") and not e.get("superseded_by")]
    page = Page(
        title="PTQ Experiment Ledger",
        h1="Experiment ledger",
        standfirst="Every controlled experiment this project has run, with its decision — "
                   "including the ones that were withdrawn. A ledger that recorded only "
                   "confirmations would misrepresent the work.",
        meta=[("Entries", len(entries)), ("Standing", len(live)),
              ("Retracted", sum(1 for e in entries if e.get("retracted"))),
              ("Superseded", sum(1 for e in entries if e.get("superseded_by")))])
    rows = [(e["id"], e.get("date"),
             (e.get("hypothesis") or "")[:88],
             (e.get("decision") or "")[:80],
             "retracted" if e.get("retracted") else
             (f"superseded by {e['superseded_by']}" if e.get("superseded_by") else "standing"))
            for e in entries]
    page.add("All experiments",
             table(["ID", "Date", "Hypothesis", "Decision", "Status"], rows),
             [finding(
                 f"{len(entries)} experiments recorded; {len(live)} still standing, "
                 f"{sum(1 for e in entries if e.get('retracted'))} retracted, "
                 f"{sum(1 for e in entries if e.get('superseded_by'))} superseded.",
                 "The ledger is append-only and stored with the research code, so an "
                 "overturned finding stays visible rather than disappearing.",
                 "N/A — this is a record, not a measurement.",
                 "Before proposing a change, check whether this question has already been "
                 "asked and answered here.",
                 "Every new experiment appends a row; nothing is edited away.")])
    for e in entries:
        page.add(f"{e['id']} · {(e.get('hypothesis') or '')[:60]}", _entry_block(e))
    return page.write(os.path.join(out_dir, "experiments.html"))


def main(argv: Sequence[str]) -> int:
    exp = argv[0] if argv and not argv[0].startswith("--") else None
    p = build_experiment(exp)
    print(f"wrote {p} ({os.path.getsize(p):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
