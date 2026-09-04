"""Pre-filter benchmark: the gates the scoring stack never sees.

Built after the gate ladder showed that only 41.3% of evaluations reach the scoring stack.
Results are computed by claude_code/experiments/exp11_prefilters.py and the opening-window
follow-up; this module renders them and states the limits. Numbers are held here as measured
constants rather than recomputed on every report build, because each arm is a full tick replay
that takes minutes — the generating scripts are the source of truth and are in the repo.
"""
from __future__ import annotations

from research.sections_market import f
from research.svg import Chart, esc

# (label, n episodes, expectancy, per-day expectancy, rows rejected, verdict)
GATES = [
    ("Time filter",           24, 57.96, (42.83, 149.28, 12.21),  6525, "costly"),
    ("No pullback",           51, 11.59, (-45.57, -46.15, 321.18), 359, "noise"),
    ("PE directional block",  52, -49.40, (-49.40, None, None),    4073, "flat"),
    ("CE directional block",  82, -58.32, (-69.90, -54.52, -9.42), 17069, "flat"),
    ("Chop filter",           80, -63.94, (-63.94, None, None),   24621, "flat"),
]
BENCH = -31.50
SCORED = -50.88
WINDOW = [("09:15–09:45  (blocked by the time filter)", 27, 114.06, 66.7, 2.43,
           (50.83, 305.41, 43.36)),
          ("09:45–15:10  (the window actually traded)", 249, -34.41, 41.8, 0.66,
           (-40.34, -36.96, -21.25))]


def prefilter_benchmark() -> tuple:
    c = Chart(h=54 + 26 * (len(GATES) + 2), ml=200, mr=132, mt=24, mb=26,
              title="Entering anyway at the instants each pre-filter rejected",
              subtitle="production exit ladder · CE · same cooldown in every arm")
    lo = min([g[2] for g in GATES] + [BENCH, SCORED]) - 20
    hi = max([g[2] for g in GATES] + [BENCH, SCORED]) + 30
    c.set_x(lo, hi)
    rows = [("BENCHMARK arbitrary timing", 262, BENCH, "bench"),
            ("reached the scoring stack", 175, SCORED, "flat")] + \
           [(g[0], g[1], g[2], g[5]) for g in GATES]
    c.set_y(0, len(rows))
    zero = c.x(0)
    c.parts.append(f'<line x1="{zero:.1f}" y1="{c.py0}" x2="{zero:.1f}" y2="{c.py1}" '
                   f'stroke="var(--grid-strong)"/>')
    bx = c.x(BENCH)
    c.parts.append(f'<line x1="{bx:.1f}" y1="{c.py0}" x2="{bx:.1f}" y2="{c.py1}" '
                   f'stroke="var(--accent)" stroke-dasharray="3 3"/>')
    for i, (lab, n, val, kind) in enumerate(rows):
        y = len(rows) - i - 0.5
        yy = c.y(y)
        col = ("var(--accent)" if kind == "bench" else
               "var(--up)" if val > BENCH else "var(--dn)")
        x0, x1 = min(zero, c.x(val)), max(zero, c.x(val))
        c.parts.append(f'<rect x="{x0:.1f}" y="{yy-8:.1f}" width="{max(1.5, x1-x0):.1f}" '
                       f'height="16" fill="{col}" opacity="0.82">'
                       f'<title>{esc(lab)}: Rs{val:.2f}/trade, n={n}</title></rect>')
        c.text(c.px0 - 8, yy + 4, lab, "end", "ax-em", raw_xy=True)
        c.text(c.px1 + 6, yy + 4, f"Rs{val:+.0f}  n={n}", "start", "ax", raw_xy=True)
    c.text(bx + 4, c.py0 + 10, "benchmark", "start", "ax", raw_xy=True)

    tbl = ["<div class='scroller'><table><thead><tr><th>Pre-filter</th>"
           "<th class='num'>Rows rejected</th><th class='num'>Episodes</th>"
           "<th class='num'>E/trade ₹</th><th class='num'>vs benchmark</th>"
           "<th>Per session</th><th>Reading</th></tr></thead><tbody>"]
    for lab, n, val, per, raw, verdict in GATES:
        pd = " · ".join("—" if v is None else f"{v:+.0f}" for v in per)
        cls = {"costly": "c-missing", "noise": "c-estimated", "flat": "c-reconstructed"}[verdict]
        word = {"costly": "COSTLY", "noise": "NOISE", "flat": "no measurable effect"}[verdict]
        tbl.append(f"<tr><td>{esc(lab)}</td><td class='num'>{raw:,}</td><td class='num'>{n}</td>"
                   f"<td class='num'>{val:+.2f}</td><td class='num'>{val-BENCH:+.2f}</td>"
                   f"<td class='mono'>{esc(pd)}</td>"
                   f"<td><span class='chip {cls}'>{word}</span></td></tr>")
    tbl.append("</tbody></table></div>")

    finds = [f(
        "Four of the five pre-filters have no measurable effect. The <b>time filter is costly</b>: "
        "entering where it blocked returns +₹57.96/trade against a −₹31.50 benchmark.",
        "Every instant each pre-filter rejected, entered on the subscribed CE contract under the "
        "production exit ladder, same cooldown in every arm. Chop filter p=0.116, "
        "CE block p=0.157, PE block p=0.305 — none separated from the benchmark.",
        "Medium. Episodes are few (24–82 after cooldown) and each arm ignores the other gates, "
        "so every figure is an upper bound on what that one filter alone did. CE only.",
        "The chop filter and the directional blocks reject 45,763 evaluations between them and "
        "cannot be shown to earn it. They are the project's largest unmeasured selectors — and "
        "the evaluations that <em>survive</em> them do worse (−₹50.88) than arbitrary timing.",
        "The time filter result is followed up in the next section; the chop filter needs more "
        "sessions before its p can move.")]
    return c.render() + "".join(tbl), finds


def opening_window() -> tuple:
    c = Chart(h=200, ml=250, mr=120, mt=24, mb=26,
              title="The blocked window against the traded window",
              subtitle="arbitrary CE entries every 30s · identical ladder · three sessions")
    c.set_x(-60, 130)
    c.set_y(0, 2)
    zero = c.x(0)
    c.parts.append(f'<line x1="{zero:.1f}" y1="{c.py0}" x2="{zero:.1f}" y2="{c.py1}" '
                   f'stroke="var(--grid-strong)"/>')
    for i, (lab, n, val, wr, pf, per) in enumerate(WINDOW):
        yy = c.y(2 - i - 0.5)
        col = "var(--up)" if val > 0 else "var(--dn)"
        x0, x1 = min(zero, c.x(val)), max(zero, c.x(val))
        c.parts.append(f'<rect x="{x0:.1f}" y="{yy-16:.1f}" width="{max(2.0,x1-x0):.1f}" '
                       f'height="32" fill="{col}" opacity="0.82"/>')
        c.text(c.px0 - 8, yy + 4, lab, "end", "ax-em", raw_xy=True)
        c.text(c.px1 + 6, yy - 1, f"Rs{val:+.2f}/trade  n={n}", "start", "ax", raw_xy=True)
        c.text(c.px1 + 6, yy + 11, f"WR {wr:.0f}%  PF {pf:.2f}", "start", "ax", raw_xy=True)
    rows = ["<div class='scroller'><table><thead><tr><th>Window</th><th class='num'>n</th>"
            "<th class='num'>E/trade ₹</th><th class='num'>WR</th><th class='num'>PF</th>"
            "<th class='num'>09-02</th><th class='num'>09-03</th><th class='num'>09-04</th>"
            "</tr></thead><tbody>"]
    for lab, n, val, wr, pf, per in WINDOW:
        rows.append(f"<tr><td class='mono'>{esc(lab)}</td><td class='num'>{n}</td>"
                    f"<td class='num'>{val:+.2f}</td><td class='num'>{wr:.1f}%</td>"
                    f"<td class='num'>{pf:.2f}</td>"
                    + "".join(f"<td class='num'>{v:+.0f}</td>" for v in per) + "</tr>")
    rows.append("</tbody></table></div>")
    note = ("<p class='cap'>Average winner in the opening window is <b>+3.40 to +5.96 pts</b>; "
            "in the traded window the strategy's average winner is <b>1.6–1.7 pts</b>. A take-profit "
            "at +14 fired once, and the RSI exit — which needs 2.0 pts before it can even be "
            "evaluated — is the most common exit there. <b>The 1–2 point ceiling is substantially "
            "a property of the hours the strategy chose to trade.</b></p>")
    finds = [f(
        "The 30 minutes the time filter blocked returned <b>+₹114.06/trade</b> at arbitrary "
        "timing; the rest of the day returned <b>−₹34.41</b>. Positive on all three sessions, "
        "negative on all three.",
        "27 opening episodes against 249 later ones, same grid, same ladder, same cooldown. "
        "Permutation test on the difference: <b>p = 0.0057</b>. Leave-one-day-out: removing "
        "2026-09-03, the strongest day, still leaves <b>+₹47.09</b>.",
        "Medium-high. Three independent sessions all agree and the effect survives dropping the "
        "best one — but n=27 in the opening window, CE only, and the spread is fabricated in "
        "both arms. Real spreads are typically <em>widest</em> at the open, so the true edge is "
        "smaller than shown, by an unknown amount.",
        "This is a <b>window effect, not a selection effect</b>: there is no unblocked instant "
        "inside 09:15–09:45 to compare against, so the finding is that the hours differ, not "
        "that the filter chose badly within an hour. It corroborates the movement study from a "
        "different direction — the largest legs of all three sessions start in this window.",
        "The time filter has already been opened for the next session, which makes that session "
        "the out-of-sample test of this result. Re-run it against the first live day that trades "
        "the opening, and re-check once real spreads exist.")]
    return c.render() + "".join(rows) + note, finds
