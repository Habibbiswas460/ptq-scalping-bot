"""The master view: one chain, quantified end to end, across every session that carries data.

    python -m research.synthesis

Answers the question the instrument exists for — the market gave X points, where did that
stop becoming P&L — by pricing each link and reporting every result as
Finding → Evidence → Confidence → Action → Next test.
"""
from __future__ import annotations

import os
import statistics as _st
import sys
from typing import Dict, List, Sequence

from research.db import Book, parse_ts
from research.entries import cascade, profiles
from research.execution import quote_quality
from research.ledger import load as load_ledger
from research.market import legs, session_profile
from research.prefilters import ladder_counts
from research.render import Page, chip, esc, finding, kv, table
from research.signals import component_stats
from research.svg import Chart
from research.transmission import session_transmission

OUT_DIR = os.path.join("claude_code", "research_output")


def chain(book: Book) -> Dict:
    sessions = book.sessions()
    spot_days = [s["day"] for s in sessions if s["kind"] in ("tick", "coarse")]
    tick_days = [s["day"] for s in sessions if s["kind"] == "tick"]
    out: Dict = {"sessions": sessions, "spot_days": spot_days, "tick_days": tick_days}

    ranges, l10, l25 = [], 0, 0
    for d in spot_days:
        s, _ = book.spot(d)
        if len(s) > 10:
            p = session_profile(s, book.trades(d))
            ranges.append(p["range"])
            l10 += p["legs_10"]
            l25 += p["legs_25"]
    out["market"] = {"n": len(ranges), "mean_range": round(_st.mean(ranges), 1),
                     "legs10": l10, "legs25": l25}

    zero = tot = 0
    for d in tick_days:
        s, _ = book.spot(d)
        trs = book.trades(d)
        for l in sorted(legs(s, 25.0), key=lambda x: -abs(x["move"]))[:5]:
            tot += 1
            if not any(l["start"] <= parse_ts(t["entry_time"]) <= l["end"] for t in trs):
                zero += 1
    out["participation"] = {"empty": zero, "of": tot}

    T = S = A = 0
    pre_tot: Dict[str, int] = {}
    for d in spot_days:
        lc = ladder_counts(book, d)
        T += lc["total"]
        S += lc["scored"]
        A += lc["accepted"]
        for k, v in lc["pre"].items():
            pre_tot[k] = pre_tot.get(k, 0) + v
    out["prefilter"] = {"total": T, "scored": S, "accepted": A,
                        "pct": round(100 * S / T, 1) if T else None,
                        "top": sorted(pre_tot.items(), key=lambda kv: -kv[1])[:4]}

    comps = component_stats(book, tick_days[-1]) if tick_days else []
    out["scoring"] = {"n": len(comps),
                      "dead": [c["component"] for c in comps if c["constant"]],
                      "day": tick_days[-1] if tick_days else None}

    tr: List[Dict] = []
    for d in tick_days:
        tr += session_transmission(book, d)
    short = [r for r in tr if r["horizon"] in ("10s", "30s")]
    long_ = [r for r in tr if r["horizon"] in ("3m", "5m")]
    out["transmission"] = {
        "short_beta": round(_st.mean([r["beta"] for r in short]), 2) if short else None,
        "long_beta": round(_st.mean([r["beta"] for r in long_]), 2) if long_ else None,
        "short_r2": round(_st.mean([r["r2"] for r in short]), 2) if short else None,
        "n": sum(r["n"] for r in tr), "sides": sorted({r["side"] for r in tr})}

    cs = []
    for d in tick_days:
        for p in profiles(book, d):
            c = cascade(p, 180)
            if c["spot_avail"] is not None and c["opt_avail"] is not None:
                cs.append(c)
    w = [c for c in cs if c["win"]]
    l = [c for c in cs if not c["win"]]
    out["capture"] = {
        "n": len(cs),
        "w": {"n": len(w),
              "spot": round(_st.mean([c["spot_avail"] for c in w]), 2) if w else None,
              "opt": round(_st.mean([c["opt_avail"] for c in w]), 2) if w else None,
              "got": round(_st.mean([c["captured"] for c in w]), 2) if w else None},
        "l": {"n": len(l),
              "spot": round(_st.mean([c["spot_avail"] for c in l]), 2) if l else None,
              "opt": round(_st.mean([c["opt_avail"] for c in l]), 2) if l else None,
              "got": round(_st.mean([c["captured"] for c in l]), 2) if l else None}}

    pn = [t["pnl"] for d in tick_days for t in book.trades(d)]
    out["outcome"] = {"n": len(pn), "total": round(sum(pn)),
                      "mean": round(_st.mean(pn), 2) if pn else None}
    out["quality"] = {d: quote_quality(book, d) for d in tick_days}
    return out


def _chain_chart(c: Dict) -> str:
    """The winner-side cascade drawn once, as the spine of the argument."""
    w = c["capture"]["w"]
    l = c["capture"]["l"]
    ch = Chart(h=210, ml=150, mr=132, mt=26, mb=26,
               title="Where the movement stops · mean per trade, 3-minute horizon",
               subtitle="option points, except the spot row which is spot points")
    rows = [("spot offered (W)", w["spot"], "var(--ink3)"),
            ("option offered (W)", w["opt"], "var(--warn)"),
            ("captured (W)", w["got"], "var(--accent)"),
            ("spot offered (L)", l["spot"], "var(--ink3)"),
            ("option offered (L)", l["opt"], "var(--warn)"),
            ("captured (L)", l["got"], "var(--dn)")]
    mx = max(abs(v or 0) for _, v, _ in rows)
    ch.set_x(min(0, min((v or 0) for _, v, _ in rows) * 1.1), mx * 1.05)
    ch.set_y(0, len(rows))
    zero = ch.x(0)
    ch.parts.append(f'<line x1="{zero:.1f}" y1="{ch.py0}" x2="{zero:.1f}" y2="{ch.py1}" '
                    f'stroke="var(--grid-strong)"/>')
    for i, (lab, v, col) in enumerate(rows):
        yy = ch.y(len(rows) - i - 0.5)
        x0, x1 = min(zero, ch.x(v or 0)), max(zero, ch.x(v or 0))
        ch.parts.append(f'<rect x="{x0:.1f}" y="{yy-9:.1f}" width="{max(1.5,x1-x0):.1f}" '
                        f'height="18" fill="{col}" opacity="0.82"/>')
        ch.text(ch.px0 - 8, yy + 4, lab, "end", "ax-em", raw_xy=True)
        ch.text(ch.px1 + 6, yy + 4, f"{v:+.2f}" if v is not None else "—", "start", "ax",
                raw_xy=True)
    return ch.render()


def build_synthesis(out_dir: str = OUT_DIR) -> str:
    book = Book()
    c = chain(book)
    m, pf, sc, tx, cap, oc = (c["market"], c["prefilter"], c["scoring"],
                              c["transmission"], c["capture"], c["outcome"])
    page = Page(
        title="Where the Move Goes Missing",
        h1="Where the move goes missing",
        standfirst="One chain across every session that carries data — market, participation, "
                   "pre-filter, scoring, transmission, capture, outcome — with each link priced "
                   "and each result carrying its own confidence.",
        meta=[("Sessions", f"{len(c['sessions'])} discovered"),
              ("Tick", len(c["tick_days"])), ("Coarse", len(c["spot_days"]) - len(c["tick_days"])),
              ("Trades studied", oc["n"]), ("Baseline", "8b7490e untouched")])

    page.add("The chain", _chain_chart(c) + kv([
        ("1 · Market offered", f"{m['mean_range']:.0f} pts mean range over {m['n']} sessions · "
                               f"{m['legs10']} legs ≥10 · {m['legs25']} legs ≥25"),
        ("2 · Strategy present", f"{c['participation']['empty']} of "
                                 f"{c['participation']['of']} largest legs had no entry"),
        ("3 · Reached scoring", f"{pf['pct']}% of {pf['total']:,} evaluations · "
                                f"{pf['accepted']} accepted"),
        ("4 · Score could rank", f"{len(sc['dead'])} of {sc['n']} components constant"),
        ("5 · Option transmitted", f"delta {tx['short_beta']} at 10–30s → {tx['long_beta']} at "
                                   f"3–5m · R² {tx['short_r2']} short"),
        ("6 · Captured", f"winners offered {cap['w']['opt']:.2f} kept {cap['w']['got']:.2f} · "
                         f"losers offered {cap['l']['opt']:.2f}"),
        ("7 · Outcome", f"{oc['n']} trades, ₹{oc['total']:,}, mean ₹{oc['mean']:.2f}"),
    ]), [finding(
        f"The market offered {m['mean_range']:.0f} points of range per session and "
        f"{m['legs25']} legs of 25 points or more. Of the trades that resulted, winners were "
        f"offered {cap['w']['opt']:.2f} option points in three minutes and kept "
        f"{cap['w']['got']:.2f}; losers were offered {cap['l']['opt']:.2f} and lost "
        f"{abs(cap['l']['got']):.2f}.",
        f"{len(c['spot_days'])} sessions with market context, {c['participation']['of']} largest "
        f"legs checked for participation, {pf['total']:,} evaluations, {tx['n']:,} paired "
        f"spot/option observations, {cap['n']} trades with tick coverage.",
        "High for each individual measurement. Low for any single explanation of the whole "
        "chain: three tick sessions, CE only, and every rupee figure gross of an unmeasured "
        "execution cost.",
        "Attribute per link rather than to one cause. The loss side is dominated by entries "
        "with nothing on offer; the winner side is limited by transmission and hold length "
        "together; the exit's share is roughly half of an already small number.",
        "The next session tests two of these links at once: the opening window is now open, "
        "and the delta/OI repair is live.")])

    page.add("Link 2 · participation", kv([
        ("Largest legs with no entry", f"{c['participation']['empty']} of {c['participation']['of']}"),
        ("Legs ≥25 pts across sessions", str(m["legs25"])),
    ]), [finding(
        f"{c['participation']['empty']} of the {c['participation']['of']} largest legs across "
        "the tick sessions carried no entry at all.",
        "Leg membership by timestamp against recorded entries; legs are retrace-confirmed.",
        "Medium — leg membership is a hindsight label, and it measures alignment rather than "
        "foresight.",
        "For each empty leg read the blocked-evaluation count in the session view: signals but "
        "no entries is a gate decision, no signals is a detection failure, and they need "
        "different fixes.",
        "Repeat with the opening window open — most of the largest legs start there.")])

    page.add("Link 3 · the pre-filters", kv(
        [("Evaluations", f"{pf['total']:,}"),
         ("Reached scoring", f"{pf['scored']:,} ({pf['pct']}%)"),
         ("Accepted", str(pf["accepted"]))] +
        [(f"Rejected by {k}", f"{v:,}") for k, v in pf["top"]]
    ), [finding(
        f"Only {pf['pct']}% of evaluations reach the scoring stack; the rest die on binary "
        f"pre-filters, chiefly {pf['top'][0][0]} ({pf['top'][0][1]:,}).",
        f"{pf['total']:,} evaluations across {len(c['spot_days'])} sessions; `weighted_score` "
        "is NULL exactly when a pre-filter rejected the row before scoring ran.",
        "High — a direct count, and each reject reason names its gate.",
        "Do not tune score weights to change selection. The pre-filters are the selector and "
        "none of them is scored, weighted or measured anywhere.",
        "EXP-11 priced them: the time filter was costly, the others showed no measurable "
        "effect and remain unresolved rather than cleared.")])

    page.add("Link 4 · the scoring stack", kv([
        ("Components", str(sc["n"])),
        ("Constant on " + str(sc["day"]), f"{len(sc['dead'])} — {', '.join(sc['dead'])}"),
    ]), [finding(
        f"{len(sc['dead'])} of {sc['n']} score components have a single value.",
        f"Distinct-value counts over the evaluations of {sc['day']}.",
        "High — counts, not tests.",
        "A weight cannot rank on a constant. Fix the input, re-measure variance, and only then "
        "consider a coefficient.",
        "Re-run after the first session with the delta/OI repair live and check whether delta, "
        "greeks and oi leave the constant list.")])

    page.add("Link 5 · transmission", kv([
        ("Realised delta 10–30s", str(tx["short_beta"])),
        ("Realised delta 3–5m", str(tx["long_beta"])),
        ("R² at 10–30s", str(tx["short_r2"])),
        ("Paired observations", f"{tx['n']:,}"),
        ("Sides measured", ", ".join(tx["sides"]) + "  " +
         ("(PE has no contract with enough ticks)" if tx["sides"] == ["CE"] else "")),
    ]), [finding(
        f"Realised delta is {tx['short_beta']} at 10–30 seconds and {tx['long_beta']} at 3–5 "
        f"minutes, with R² of {tx['short_r2']} at the short end.",
        f"{tx['n']:,} paired observations, regression of Δoption on Δspot through the origin.",
        "High within these sessions and strikes; CE only.",
        "Expect roughly a third to a half of spot movement at the horizon the strategy holds "
        "for, and treat the rest of the option's short-horizon movement as noise rather than "
        "signal.",
        "Repeat per strike once PE exists and test whether transmission varies with moneyness.")])

    ql = [(d, q.get("midpoint_exact_pct"), q.get("oi_populated_pct"), q.get("collision_pct"),
           q.get("pe_ticks")) for d, q in c["quality"].items()]
    page.add("Data quality gate", table(
        ["Session", "Midpoint-exact %", "OI populated %", "Timestamp collisions %", "PE ticks"],
        ql, num_cols=(1, 2, 3, 4)) +
        "<div class='flag'><h4>Execution conclusions are blocked on every session studied</h4>"
        "<p>Every quote sits exactly on the midpoint, which real prints never do — the bid/ask "
        "is the production fallback. Movement, transmission and capture rest on LTP and stand; "
        "no net-of-cost figure does.</p></div>",
        [finding(
            "All three tick sessions have fabricated quotes, no OI, ~20% same-second "
            "collisions and effectively no PE coverage.",
            "Midpoint-exactness, OI fill, timestamp uniqueness and PE counts, per session.",
            "High — schema counts.",
            "Report point-based results; report rupee results as a range across spread "
            "assumptions, never as a number.",
            "Collector solo run resolves the spread; the OI repair lands with the next session.")])

    led = load_ledger()
    page.add("What the ledger already settles", table(
        ["ID", "Decision", "Status"],
        [(e["id"], (e.get("decision") or "")[:90],
          "retracted" if e.get("retracted") else
          (f"superseded by {e['superseded_by']}" if e.get("superseded_by") else "standing"))
         for e in led]),
        [finding(
            f"{len(led)} experiments are on record, including one retraction and one "
            "supersession.",
            "The append-only ledger stored with the research code.",
            "N/A — a record.",
            "Check the ledger before proposing a change; several of these questions are closed.",
            "Every new experiment appends a row.")])
    return page.write(os.path.join(out_dir, "synthesis.html"))


def main(argv: Sequence[str]) -> int:
    p = build_synthesis()
    print(f"wrote {p} ({os.path.getsize(p):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
