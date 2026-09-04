"""Strategy-side sections: signal stack, CE/PE, entry windows, entry→MFE, transmission,
capture cascade, exits, blocked signals, the dvf_trades verdict, and cross-session comparison.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from collections import Counter, defaultdict
from typing import Dict, List

from research import provenance as prov
from research.data import (LOT, available_move, candles, capture, legs, nearest_before,
                           parse_ts, transmission_regression, window)
from research.sections_market import f, thin
from research.svg import Chart, esc, heatmap

HORIZONS = [(30, "30s"), (60, "1m"), (180, "3m"), (300, "5m"), (600, "10m")]


# ───────────────── 5. signal stack ─────────────────
def signal_stack(book, day: str) -> tuple:
    sig = book.signals(day)
    if not sig:
        return "<p class='none'>No signal rows for this session.</p>", []
    comps = defaultdict(Counter)
    for s in sig:
        for k, v in (s["score_breakdown"] or {}).items():
            if isinstance(v, (int, float)) and k not in ("raw_score", "total_weight",
                                                         "normalized_score_pct"):
                comps[k][round(float(v), 2)] += 1
    order = sorted(comps, key=lambda k: (len(comps[k]), k))
    c = Chart(h=44 + 20 * len(order), ml=132, mt=22, mb=26,
              title="Score components · distinct values in this session",
              subtitle="a component with one value cannot rank anything")
    c.set_x(0, max(4, max(len(v) for v in comps.values())))
    c.set_y(0, len(order))
    for i, k in enumerate(order):
        nv = len(comps[k])
        y = len(order) - i - 0.5
        col = "var(--dn)" if nv <= 1 else ("var(--warn)" if nv <= 2 else "var(--up)")
        yy = c.y(y)
        c.parts.append(f'<rect x="{c.px0}" y="{yy-6:.1f}" width="{max(2.0, c.x(nv)-c.px0):.1f}" '
                       f'height="12" fill="{col}" opacity="0.85"><title>{esc(k)}: {nv} distinct'
                       f'</title></rect>')
        c.text(c.px0 - 8, yy + 4, k, "end", "ax-em", raw_xy=True)
        c.text(c.x(nv) + 6, yy + 4, f"{nv}" + (" — CONSTANT" if nv <= 1 else ""), "start",
               "ax", raw_xy=True)
    dead = [k for k in order if len(comps[k]) <= 1]

    scored = [s for s in sig if s["weighted_score"] is not None]
    pairs = Counter((s["weighted_score"], s["confidence"]) for s in scored)
    top, topn = pairs.most_common(1)[0] if pairs else ((None, None), 0)
    rows = [("Signal evaluations", f"{len(sig):,}"),
            ("Reached the scoring stack", f"{len(scored):,} ({100*len(scored)/len(sig):.1f}%) — "
                                          f"the rest were rejected by a pre-filter before any "
                                          f"score was computed"),
            ("Distinct (score, confidence) pairs", str(len(pairs)) if pairs else "—"),
            ("Most common pair", (f"score {top[0]}, confidence {top[1]} — "
                                  f"{100*topn/len(scored):.1f}% of scored rows")
                                 if pairs else "no evaluation reached the scoring stack"),
            ("Constant score components", f"{len(dead)} of {len(order)}: {', '.join(dead) or 'none'}"),
            ("First / last evaluation", f"{sig[0]['t']:%H:%M:%S} – {sig[-1]['t']:%H:%M:%S}")]

    html = [c.render(), _kv(rows)]
    finds = [f(
        f"{len(dead)} of {len(order)} score components are constant, and "
        f"{100*topn/len(sig):.0f}% of evaluations produce the identical (score, confidence) pair.",
        f"{len(sig):,} dvf_signals rows on {day}; distinct-value counts per component.",
        "High — a count of distinct values, not a statistical test.",
        "A stack with no variance cannot rank moments. Any weight tuning would be moving "
        "coefficients on terms that never change.",
        "Re-run on the first session after the delta/OI repair: the test is whether delta, "
        "greeks and oi leave the constant list.")]
    return "".join(html), finds


# ───────────────── 6. CE / PE ─────────────────
def ce_pe(book, day: str) -> tuple:
    cur = book.cur
    rows = []
    for side in ("CE", "PE"):
        n_tick = cur.execute("SELECT count(*) FROM ticks WHERE date(timestamp)=? AND symbol LIKE ?",
                             (day, f"%{side}")).fetchone()[0]
        syms = cur.execute("SELECT count(DISTINCT symbol) FROM ticks WHERE date(timestamp)=? "
                           "AND symbol LIKE ?", (day, f"%{side}")).fetchone()[0]
        trs = [t for t in book.trades(day) if t["direction"] == side]
        wins = sum(1 for t in trs if t["pnl"] > 0)
        pnl = sum(t["pnl"] for t in trs)
        rows.append((side, f"{n_tick:,}", str(syms), str(len(trs)),
                     f"{wins}/{len(trs)}" if trs else "—",
                     f"{pnl:+,.0f}" if trs else "—"))
    out = ["<div class='scroller'><table><thead><tr><th>Side</th><th class='num'>Option ticks</th>"
           "<th class='num'>Contracts</th><th class='num'>Trades</th><th>W/L</th>"
           "<th class='num'>P&L ₹</th></tr></thead><tbody>"]
    for r in rows:
        out.append("<tr>" + "".join(f"<td class='{'num' if i in (1,2,3,5) else ''}'>{esc(v)}</td>"
                                    for i, v in enumerate(r)) + "</tr>")
    out.append("</tbody></table></div>")
    pe_ticks = int(rows[1][1].replace(",", ""))
    if pe_ticks < 2000:
        out.append("<div class='flag'><h4>PE coverage is insufficient on this session</h4>"
                   f"<p>{pe_ticks:,} PE ticks. Nothing about PE behaviour — including whether "
                   "the repaired negative-delta scoring works — can be tested from this data. "
                   "The gap is left visible rather than filled.</p></div>")
    finds = [f(
        f"PE has {pe_ticks:,} option ticks on {day} against {rows[0][1]} for CE.",
        "Tick counts by symbol suffix; one contract is subscribed at a time and it was CE.",
        "High — a coverage count.",
        "Half the directional space has no option-side history. Any pooled CE+PE statistic "
        "would be a CE statistic wearing a different label.",
        "Dual CE/PE subscription is the only fix; until then PE stays labelled insufficient.")]
    return "".join(out), finds


# ───────────────── 7+8. entry windows and entry→MFE ─────────────────
def entry_windows(book, day: str, limit: int = 6) -> tuple:
    trades = book.trades(day)
    spot, src = book.spot(day)
    if src != "tick" or not trades:
        return ("<p class='none'>Entry windows need the tick series and at least one trade.</p>", [])
    html, cascade_rows = [], []
    for tr in trades[:limit]:
        opt = book.option(tr["symbol"], day)
        if not opt:
            continue
        e, x = parse_ts(tr["entry_time"]), parse_ts(tr["exit_time"])
        a, b = e - _dt.timedelta(minutes=5), e + _dt.timedelta(minutes=10)
        seg = [(t, p) for t, p in opt if a <= t <= b]
        if len(seg) < 20:
            continue
        pre = candles([(t, p) for t, p in opt if t <= e], 60, upto=e)
        post = [c for c in candles([(t, p) for t, p in opt if t > e and t <= b], 60)]
        bars = pre[-6:] + post
        c = Chart(h=210, mt=22, mb=24,
                  title=f"#{tr['id']} {tr['direction']} {tr['symbol'][-9:]} · entry {e:%H:%M:%S}",
                  subtitle=f"{tr['exit_reason'].split('|')[0].strip()} · "
                           f"{tr['exit_price']-tr['entry_price']:+.2f} pts · ₹{tr['pnl']:+,.0f}")
        c.set_time_x(a, b)
        lo = min(min(p for _, p in seg), tr["entry_price"], tr["exit_price"])
        hi = max(max(p for _, p in seg), tr["entry_price"], tr["exit_price"])
        c.set_y(lo, hi); c.grid(3, lambda v: f"{v:,.1f}"); c.time_axis(a, b, 2)
        c.vspan(e, x, "var(--accent)", 0.09, "in trade")
        c.line(thin(seg, 500), "var(--ink3)", 0.9, 0.55)
        c.candles(bars, 4.0)
        c.hline(tr["entry_price"], "var(--grid-strong)")
        c.marker(e, tr["entry_price"], "entry", "var(--accent)", 5.5,
                 f"entry {tr['entry_price']}")
        c.marker(x, tr["exit_price"], "exit",
                 "var(--up)" if tr["pnl"] > 0 else "var(--dn)", 5.0,
                 f"exit {tr['exit_price']}")
        av = available_move(opt, spot, tr)
        mx = max((p for t, p in opt if e < t <= e + _dt.timedelta(minutes=3)), default=None)
        if mx:
            c.hline(mx, "var(--up)")
            c.text(c.px1 - 2, c.y(mx) - 4, f"3m high {mx:.2f}", "end", "ax", raw_xy=True)
        html.append(c.render())
        html.append(_horizon_table(tr, av))
        cascade_rows.append((tr, av))
    note = ("<p class='cap'>The bar containing the entry is drawn <b>dashed and hollow</b>: it is "
            "built only from ticks up to the entry second. Solid bars are completed. Using the "
            "finished entry candle would import post-entry ticks into the picture — the artifact "
            "that produced a p=0.004 finding earlier in this project which collapsed to p=0.54 "
            "once recomputed causally.</p>")
    finds = [f(
        "Across these entries the 3-minute option high sits close above the entry line while the "
        "exit sits between the two — the visual signature of a small available move, not a cut one.",
        f"{len(cascade_rows)} entries on {day} with 5 min of pre-entry and 10 min of post-entry ticks.",
        "Medium — per-trade illustration, n small; the aggregate version is the cascade section.",
        "Whether the exit is early can only be judged against what was available, which is why "
        "every window carries its horizon table.",
        "Read this together with the capture cascade rather than on its own.")]
    return note + "".join(html), finds


def _horizon_table(tr, av) -> str:
    got = tr["exit_price"] - tr["entry_price"]
    out = ["<div class='scroller'><table class='mini'><thead><tr><th>Horizon</th>"
           "<th class='num'>Δspot fav</th><th class='num'>Δspot adv</th>"
           "<th class='num'>option MFE</th><th class='num'>option MAE</th>"
           "<th class='num'>captured</th><th class='num'>% of option MFE</th>"
           "</tr></thead><tbody>"]
    for sec, lab in HORIZONS:
        s, sa = av.get(f"sMFE_{sec}"), av.get(f"sMAE_{sec}")
        o, oa = av.get(f"oMFE_{sec}"), av.get(f"oMAE_{sec}")
        pct = f"{100*got/o:.0f}%" if (o and o > 0) else "—"
        out.append(f"<tr><td class='mono'>{lab}</td>"
                   f"<td class='num'>{'—' if s is None else f'{s:+.2f}'}</td>"
                   f"<td class='num'>{'—' if sa is None else f'{sa:+.2f}'}</td>"
                   f"<td class='num'>{'—' if o is None else f'{o:+.2f}'}</td>"
                   f"<td class='num'>{'—' if oa is None else f'{oa:+.2f}'}</td>"
                   f"<td class='num'>{got:+.2f}</td><td class='num'>{pct}</td></tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


# ───────────────── 9. transmission ─────────────────
def transmission(book, day: str) -> tuple:
    spot, src = book.spot(day)
    if src != "tick":
        return "<p class='none'>Transmission needs tick spot and option series.</p>", []
    by_ts = {t: p for t, p in spot}
    rows, series = [], {}
    for sym, n in book.option_symbols(day):
        if n < 800:
            continue
        opt = book.option(sym, day)
        res = {}
        for sec, lab in ((10, "10s"), (30, "30s"), (60, "1m"), (180, "3m"), (300, "5m")):
            r = transmission_regression(opt, by_ts, sec)
            if r:
                res[lab] = r
        if res:
            series[sym] = res
            for lab, r in res.items():
                rows.append((sym[-9:], lab, r["n"], r["beta"], r["r2"], r["med_dspot"], r["med_dopt"]))
    if not rows:
        return "<p class='none'>Not enough overlapping spot/option ticks.</p>", []

    c = Chart(h=250, ml=52, title="Realised delta by horizon",
              subtitle="slope of Δoption on Δspot through the origin · CE only")
    labs = ["10s", "30s", "1m", "3m", "5m"]
    c.set_x(-0.4, len(labs) - 0.6)
    c.set_y(0, max(r[3] for r in rows) * 1.1)
    c.grid(4, lambda v: f"{v:.2f}")
    c.x_axis_labels([(i, l) for i, l in enumerate(labs)])
    cols = ["var(--accent)", "var(--up)", "var(--warn)", "var(--dn)"]
    for k, (sym, res) in enumerate(series.items()):
        pts = [(i, res[l]["beta"]) for i, l in enumerate(labs) if l in res]
        col = cols[k % len(cols)]
        if len(pts) > 1:
            d = " ".join(("M" if i == 0 else "L") + f"{c.x(x):.1f},{c.y(y):.1f}"
                         for i, (x, y) in enumerate(pts))
            c.parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>')
        for x, y in pts:
            c.dot(x, y, 3.4, col, 1.0, f"{sym[-9:]} {labs[int(x)]}: delta {y}")
        if pts:
            c.text(c.x(pts[-1][0]) + 6, c.y(pts[-1][1]) + 4, sym[-9:], "start", "ax", raw_xy=True)
    c.hline(0.5, "var(--grid-strong)")
    c.text(c.px0 + 4, c.y(0.5) - 4, "0.50 — textbook ATM", "start", "ax", raw_xy=True)

    out = [c.render(), "<div class='scroller'><table><thead><tr><th>Contract</th><th>Horizon</th>"
           "<th class='num'>n</th><th class='num'>realised delta</th><th class='num'>R²</th>"
           "<th class='num'>median |Δspot|</th><th class='num'>median |Δopt|</th>"
           "</tr></thead><tbody>"]
    for r in rows:
        out.append("<tr>" + "".join(f"<td class='{'num' if i >= 2 else 'mono'}'>{esc(v)}</td>"
                                    for i, v in enumerate(r)) + "</tr>")
    out.append("</tbody></table></div>")

    short = [r for r in rows if r[1] in ("10s", "30s")]
    long_ = [r for r in rows if r[1] in ("3m", "5m")]
    b_s = _st.mean([r[3] for r in short]) if short else 0
    b_l = _st.mean([r[3] for r in long_]) if long_ else 0
    r2_s = _st.mean([r[4] for r in short]) if short else 0
    finds = [f(
        f"Realised delta averages {b_s:.2f} at 10–30s and {b_l:.2f} at 3–5m, with R² of only "
        f"{r2_s:.2f} at the short end.",
        f"{sum(r[2] for r in rows):,} paired observations across "
        f"{len(series)} contracts on {day}, regression through the origin.",
        "High within this session and these strikes. CE only — no PE contract carried enough ticks.",
        "At the horizon the strategy actually trades, most option movement is not explained by "
        "spot at all. Transmission is not a fixed multiplier; it improves with holding time, "
        "which is the same axis the strategy is shortest on.",
        "Repeat per strike once PE exists, and check whether transmission varies with moneyness.")]
    return "".join(out), finds


# ───────────────── 10. capture cascade ─────────────────
def capture_cascade(book, days: List[str], horizon: int = 180) -> tuple:
    items = []
    for day in days:
        spot, src = book.spot(day)
        if src != "tick":
            continue
        for tr in book.trades(day):
            opt = book.option(tr["symbol"], day)
            if not opt:
                continue
            av = available_move(opt, spot, tr)
            cap = capture(tr, av, horizon)
            if cap["spot_avail"] is None or cap["opt_avail"] is None:
                continue
            items.append((day, tr, cap))
    if not items:
        return "<p class='none'>No trades with tick coverage.</p>", []

    out = []
    for group, want_win in (("Winners", True), ("Losers", False)):
        grp = [i for i in items if (i[1]["pnl"] > 0) == want_win]
        if not grp:
            continue
        c = Chart(h=42 + 26 * len(grp), ml=74, mr=150, mt=24, mb=26,
                  title=f"Capture cascade · {group} · {horizon//60}-minute horizon",
                  subtitle="spot offered → option offered → captured (option points)")
        mx = max(max(abs(i[2]["spot_avail"]), abs(i[2]["opt_avail"]), abs(i[2]["captured"]))
                 for i in grp)
        c.set_x(0, mx * 1.05)
        c.set_y(0, len(grp))
        c.grid(4, lambda v: "")
        for i, (day, tr, cap) in enumerate(grp):
            y = len(grp) - i - 0.5
            yy = c.y(y)
            for val, col, hgt, op in ((cap["spot_avail"], "var(--ink3)", 13, 0.30),
                                      (cap["opt_avail"], "var(--warn)", 9, 0.75),
                                      (cap["captured"], "var(--accent)", 5, 1.0)):
                wpx = max(1.0, c.x(max(0.0, val)) - c.px0)
                c.parts.append(f'<rect x="{c.px0}" y="{yy-hgt/2:.1f}" width="{wpx:.1f}" '
                               f'height="{hgt}" fill="{col}" opacity="{op}"/>')
            c.text(c.px0 - 8, yy + 4, f"#{tr['id']} {tr['direction']}", "end", "ax-em", raw_xy=True)
            tx = f"spot {cap['spot_avail']:+.1f} → opt {cap['opt_avail']:+.1f} → got {cap['captured']:+.1f}"
            if cap["transmission"] is not None:
                tx += f"  (τ {cap['transmission']:.2f}"
                tx += f", κ {cap['capture_ratio']:.2f})" if cap["capture_ratio"] is not None else ")"
            c.text(c.px1 + 6, yy + 4, tx, "start", "ax", raw_xy=True)
        out.append(c.render())

    wins = [i[2] for i in items if i[1]["pnl"] > 0]
    loss = [i[2] for i in items if i[1]["pnl"] <= 0]
    rows = []
    for lab, grp in (("Winners", wins), ("Losers", loss)):
        if not grp:
            continue
        rows.append((lab, str(len(grp)),
                     f"{_st.mean([g['spot_avail'] for g in grp]):.2f}",
                     f"{_st.mean([g['opt_avail'] for g in grp]):.2f}",
                     f"{_st.mean([g['captured'] for g in grp]):+.2f}",
                     f"{_st.median([g['transmission'] for g in grp if g['transmission'] is not None]):.2f}"
                     if any(g['transmission'] is not None for g in grp) else "—"))
    out.append("<div class='scroller'><table><thead><tr><th>Group</th><th class='num'>n</th>"
               "<th class='num'>spot offered</th><th class='num'>option offered</th>"
               "<th class='num'>captured</th><th class='num'>median τ</th>"
               "</tr></thead><tbody>"
               + "".join("<tr>" + "".join(f"<td class='{'num' if i else ''}'>{esc(v)}</td>"
                                          for i, v in enumerate(r)) + "</tr>" for r in rows)
               + "</tbody></table></div>")

    lo_avail = _st.mean([g["opt_avail"] for g in loss]) if loss else 0
    wi_avail = _st.mean([g["opt_avail"] for g in wins]) if wins else 0
    wi_got = _st.mean([g["captured"] for g in wins]) if wins else 0
    finds = [f(
        f"Losers were offered {lo_avail:.2f} option points in three minutes; winners were offered "
        f"{wi_avail:.2f} and kept {wi_got:.2f}.",
        f"{len(items)} trades across {len([d for d in days])} sessions. Available movement "
        "recomputed from ticks over a fixed horizon, so it is not truncated by the exit the way "
        "the stored mfe column is.",
        "High for the arithmetic; medium for generalisation — two traded sessions, CE only.",
        "The loss side is an entry problem: there was nothing there to capture. The winner side "
        "is where the exit's share lives, and it is roughly half of a small number.",
        "Recompute after the first post-repair session and compare the loser-side offered "
        "movement — that is the number an entry improvement must move.")]
    return "".join(out), finds


# ───────────────── 11. exit behaviour ─────────────────
def exit_behaviour(book, days: List[str]) -> tuple:
    rows = []
    for day in days:
        spot, src = book.spot(day)
        if src != "tick":
            continue
        for tr in book.trades(day):
            opt = book.option(tr["symbol"], day)
            if not opt:
                continue
            e, x = parse_ts(tr["entry_time"]), parse_ts(tr["exit_time"])
            in_tr = [p for t, p in opt if e <= t <= x]
            mfe_before = round(max(in_tr) - tr["entry_price"], 2) if in_tr else None
            after = {}
            for sec, lab in ((30, "30s"), (60, "1m"), (300, "5m")):
                w = window(opt, x, x + _dt.timedelta(seconds=sec))
                after[lab] = (round(max(w) - tr["exit_price"], 2) if w else None,
                              round(min(w) - tr["exit_price"], 2) if w else None)
            rows.append((day, tr, mfe_before, after))
    if not rows:
        return "<p class='none'>No exits with tick coverage.</p>", []

    out = ["<div class='scroller'><table><thead><tr><th>Trade</th><th>Exit reason</th>"
           "<th class='num'>captured</th><th class='num'>MFE before exit</th>"
           "<th class='num'>+30s</th><th class='num'>+1m</th><th class='num'>+5m up</th>"
           "<th class='num'>+5m down</th></tr></thead><tbody>"]
    for day, tr, mb, af in rows:
        got = tr["exit_price"] - tr["entry_price"]
        left = af["5m"][0]
        cls = " class='row-warn'" if (left is not None and left > 2.0 and got > 0) else ""
        def num(v):
            return "—" if v is None else f"{v:+.2f}"
        out.append(f"<tr{cls}><td class='mono'>#{tr['id']} {tr['direction']}</td>"
                   f"<td>{esc(tr['exit_reason'].split('|')[0].strip())}</td>"
                   f"<td class='num'>{got:+.2f}</td>"
                   f"<td class='num'>{num(mb)}</td>"
                   f"<td class='num'>{num(af['30s'][0])}</td>"
                   f"<td class='num'>{num(af['1m'][0])}</td>"
                   f"<td class='num'>{num(af['5m'][0])}</td>"
                   f"<td class='num'>{num(af['5m'][1])}</td></tr>")
    out.append("</tbody></table></div>")

    winners = [(tr, mb, af) for _, tr, mb, af in rows if tr["pnl"] > 0]
    left5 = [af["5m"][0] for _, _, af in winners if af["5m"][0] is not None]
    saved5 = [af["5m"][1] for _, _, af in winners if af["5m"][1] is not None]
    by_reason = Counter(tr["exit_reason"].split("|")[0].strip() for _, tr, _, _ in rows)
    finds = [f(
        f"After a winning exit the option went a further {_st.mean(left5):+.2f} pts in five "
        f"minutes on average — and {_st.mean(saved5):+.2f} pts against.",
        f"{len(rows)} exits with tick coverage. Exit mix: "
        + ", ".join(f"{k} {v}" for k, v in by_reason.most_common()),
        "Medium — n small, and post-exit paths are counterfactual only if the position would "
        "have been held, which the loss rules would often have prevented.",
        "Continuation after exit is roughly symmetric with adverse movement, so 'the exit cut "
        "the winner' is not free money: holding captures both sides.",
        "Only a replay that keeps the full ladder can price this, which is what the exit lab does.")]
    return "".join(out), finds


# ───────────────── 12. blocked signals ─────────────────
def blocked_signals(book, day: str) -> tuple:
    sig = book.signals(day)
    if not sig:
        return "<p class='none'>No signal rows.</p>", []
    reasons = Counter()
    for s in sig:
        if s["accepted"]:
            continue
        r = (s["reject_reason"] or "unknown").strip()
        for pat in ("Low confidence", "Low conf", "CE blocked", "PE blocked", "Time filter",
                    "Chop filter", "Spread too wide", "Premium too"):
            if r.startswith(pat) or pat in r:
                r = pat
                break
        reasons[r[:44]] += 1
    top = reasons.most_common(9)
    c = Chart(h=40 + 22 * len(top), ml=210, mr=70, mt=22, mb=24,
              title="Why signals did not become trades",
              subtitle=f"{sum(reasons.values()):,} rejected of {len(sig):,} evaluations")
    c.set_x(0, max(v for _, v in top) * 1.05)
    c.set_y(0, len(top))
    for i, (r, v) in enumerate(top):
        y = len(top) - i - 0.5
        yy = c.y(y)
        c.parts.append(f'<rect x="{c.px0}" y="{yy-7:.1f}" '
                       f'width="{max(2.0, c.x(v)-c.px0):.1f}" height="14" '
                       f'fill="var(--accent)" opacity="0.8"><title>{esc(r)}: {v:,}</title></rect>')
        c.text(c.px0 - 8, yy + 4, r, "end", "ax-em", raw_xy=True)
        c.text(c.x(v) + 6, yy + 4, f"{v:,}", "start", "ax", raw_xy=True)
    acc = sum(1 for s in sig if s["accepted"])
    finds = [f(
        f"{sum(reasons.values()):,} of {len(sig):,} evaluations were rejected; "
        f"{acc} were accepted. Top reason: {top[0][0]} ({top[0][1]:,}).",
        f"dvf_signals.reject_reason on {day}, grouped by leading pattern.",
        "High for the counts. The counts are per-evaluation, not per-opportunity — the same "
        "condition persisting for minutes produces thousands of rows.",
        "Gate accounting has to be read per distinct opportunity, not per row, or a persistent "
        "condition looks like thousands of missed trades.",
        "Collapse consecutive identical rejections into episodes before drawing any conclusion "
        "about what the gates cost.")]
    return c.render(), finds


# ───────────────── dvf_trades verdict ─────────────────
def dvf_verdict(book) -> tuple:
    cur = book.cur
    n = cur.execute("SELECT count(*) FROM dvf_trades").fetchone()[0]
    slip = Counter(r[0] for r in cur.execute("SELECT slippage_model FROM dvf_trades"))
    reasons = Counter(r[0] for r in cur.execute("SELECT exit_reason FROM dvf_trades"))
    dirs = Counter(r[0] for r in cur.execute("SELECT direction FROM dvf_trades"))
    holds = [r[0] for r in cur.execute("SELECT hold_time_sec FROM dvf_trades WHERE hold_time_sec IS NOT NULL")]
    zero = cur.execute("SELECT count(*) FROM dvf_trades WHERE pnl=0").fetchone()[0]
    rows = [("Rows", f"{n:,} — against 131 real trades"),
            ("Slippage model", ", ".join(f"{k}: {v:,}" for k, v in slip.most_common())),
            ("Exit reasons", ", ".join(f"{k}: {v:,}" for k, v in reasons.most_common(4))),
            ("Direction mix", ", ".join(f"{k}: {v:,}" for k, v in dirs.most_common())),
            ("Median hold", f"{_st.median(holds):,.0f}s — real trades: 25s"),
            ("Longest hold", f"{max(holds):,.0f}s ({max(holds)/86400:.0f} days)"),
            ("Exactly zero P&L", f"{zero:,} rows ({100*zero/n:.0f}%)")]
    finds = [f(
        "dvf_trades is a shadow-execution harness, not a research sample, and must stay "
        "separate from real trades.",
        f"{slip.most_common(1)[0][1]:,} of {n:,} rows have <b>no slippage model at all</b>. Every "
        "exit reason is a virtual rule (Virtual max hold, SL/TP (virtual)) — <b>none of the "
        "strategy's real exit ladder appears</b>. Median hold is "
        f"{_st.median(holds):,.0f}s against 25s for real trades, the longest is "
        f"{max(holds)/86400:.0f} days (a restart-reconciliation artifact), {100*zero/n:.0f}% of "
        f"rows have exactly zero P&L, and the direction mix is "
        f"{dirs.most_common(1)[0][0]}-dominated where real trades are the opposite.",
        "High — every one of these is a direct count over the full table.",
        "It answers a different question (what would a naive fill have done) with a different "
        "exit policy and no costs. Using it as a larger sample would import a different "
        "strategy's behaviour under the name of this one.",
        "Keep it excluded from every chart. If a larger sample is wanted, the replay lab "
        "generates one under the real ladder, which is the honest way to get n up.")]
    return _kv(rows), finds


# ───────────────── 13. cross-session comparison ─────────────────
def comparison(book) -> tuple:
    sessions = book.sessions()
    rows = []
    for s in sessions:
        day = s["day"]
        spot, src = book.spot(day)
        trades = book.trades(day)
        sig = book.signals(day)
        rng = (max(p for _, p in spot) - min(p for _, p in spot)) if len(spot) > 3 else None
        net = (spot[-1][1] - spot[0][1]) if len(spot) > 3 else None
        big = len(legs(spot, 25.0)) if len(spot) > 3 else None
        wins = sum(1 for t in trades if t["pnl"] > 0)
        pnl = sum(t["pnl"] for t in trades)
        pairs = len(Counter((x["weighted_score"], x["confidence"]) for x in sig)) if sig else None
        rows.append({
            "day": day, "kind": s["kind"], "range": rng, "net": net, "legs": big,
            "sig": len(sig) or None, "trades": len(trades) or None,
            "wr": (100 * wins / len(trades)) if trades else None,
            "pnl": pnl if trades else None, "pairs": pairs,
        })
    out = ["<div class='scroller'><table><thead><tr><th>Session</th><th>Data</th>"
           "<th class='num'>Range</th><th class='num'>Net</th><th class='num'>Legs ≥25</th>"
           "<th class='num'>Signals</th><th class='num'>Trades</th><th class='num'>WR%</th>"
           "<th class='num'>P&L ₹</th><th class='num'>score/conf pairs</th>"
           "</tr></thead><tbody>"]
    def cell(v, fmt="{:.0f}"):
        return "<td class='num none-cell'>—</td>" if v is None else f"<td class='num'>{fmt.format(v)}</td>"
    for r in rows:
        kind_cls = {"tick": "c-real", "coarse": "c-reconstructed", "trades-only": "c-missing"}[r["kind"]]
        out.append(f"<tr><td class='mono'>{esc(r['day'])}</td>"
                   f"<td><span class='chip {kind_cls}'>{esc(r['kind'])}</span></td>"
                   + cell(r["range"], "{:,.0f}") + cell(r["net"], "{:+,.0f}") + cell(r["legs"])
                   + cell(r["sig"], "{:,.0f}") + cell(r["trades"]) + cell(r["wr"], "{:.0f}")
                   + cell(r["pnl"], "{:+,.0f}") + cell(r["pairs"]) + "</tr>")
    out.append("</tbody></table></div>")
    tick = [r for r in rows if r["kind"] == "tick"]
    finds = [f(
        f"{len(rows)} sessions exist; {len(tick)} carry tick data, "
        f"{sum(1 for r in rows if r['kind']=='coarse')} carry coarse spot only, and "
        f"{sum(1 for r in rows if r['kind']=='trades-only')} have trades with no market context at all.",
        "Discovered from ticks, dvf_signals and trades rather than assumed.",
        "High for coverage. Any cross-session metric mixing the three kinds is not comparable.",
        "Most of the trade history cannot be studied against the market it traded in. The "
        "comparison layer is therefore about the last handful of sessions, growing forward.",
        "Every new session lands in this table automatically; the trends become readable at "
        "roughly ten tick sessions.")]
    return "".join(out), finds


def _kv(rows) -> str:
    out = ["<div class='kv'>"]
    for k, v in rows:
        out.append(f"<div class='kv-row'><span class='kv-k'>{esc(k)}</span>"
                   f"<span class='kv-v'>{esc(v)}</span></div>")
    out.append("</div>")
    return "".join(out)


# ───────────────── gate ladder ─────────────────
PRE_GATES = ("Time filter", "Chop filter", "CE signal blocked", "PE signal blocked",
             "CE blocked", "PE blocked", "No CE pullback", "No PE pullback", "Warming up")


def gate_ladder(book, days: List[str]) -> tuple:
    """Where evaluations die, and how few ever reach the scoring stack.

    Found while rendering the signal-stack section: weighted_score is NULL on most rows. Those
    are not missing data — they are evaluations rejected by a pre-filter BEFORE scoring ran.
    The score and confidence stack therefore only ever sees the survivors, which changes what
    'the scoring stack cannot rank' means.
    """
    rows = []
    for day in days:
        sig = book.signals(day)
        if not sig:
            continue
        pre = Counter()
        scored = 0
        conf_blocked = 0
        accepted = 0
        for s in sig:
            r = (s["reject_reason"] or "").strip()
            if s["weighted_score"] is None:
                lab = next((p for p in PRE_GATES if p in r), "other pre-filter")
                pre[lab] += 1
            else:
                scored += 1
                if s["accepted"]:
                    accepted += 1
                elif "conf" in r.lower():
                    conf_blocked += 1
        rows.append((day, len(sig), dict(pre), scored, conf_blocked, accepted))

    out = []
    for day, n, pre, scored, conf_blocked, accepted in rows:
        stages = [("evaluations", n)]
        running = n
        for lab, v in sorted(pre.items(), key=lambda kv: -kv[1]):
            running -= v
            stages.append((f"− {lab}", running))
        stages.append(("reached scoring", scored))
        stages.append(("− confidence gate", scored - conf_blocked))
        stages.append(("accepted", accepted))
        c = Chart(h=40 + 21 * len(stages), ml=196, mr=96, mt=22, mb=22,
                  title=f"{day} · gate ladder",
                  subtitle=f"{100*scored/n:.1f}% of evaluations ever reached the scoring stack")
        c.set_x(0, n)
        c.set_y(0, len(stages))
        for i, (lab, v) in enumerate(stages):
            y = len(stages) - i - 0.5
            yy = c.y(y)
            col = ("var(--ink3)" if i == 0 else
                   "var(--up)" if lab == "accepted" else
                   "var(--accent)" if lab == "reached scoring" else "var(--dn)")
            c.parts.append(f'<rect x="{c.px0}" y="{yy-7:.1f}" '
                           f'width="{max(1.5, c.x(max(v,0))-c.px0):.1f}" height="14" '
                           f'fill="{col}" opacity="0.78"><title>{esc(lab)}: {v:,}</title></rect>')
            c.text(c.px0 - 8, yy + 4, lab, "end", "ax-em", raw_xy=True)
            c.text(c.x(max(v, 0)) + 6, yy + 4, f"{v:,}", "start", "ax", raw_xy=True)
        out.append(c.render())

    tot = sum(r[1] for r in rows)
    sc = sum(r[3] for r in rows)
    top_pre = Counter()
    for r in rows:
        top_pre.update(r[2])
    finds = [f(
        f"Only {100*sc/tot:.1f}% of evaluations ever reach the scoring stack. The rest are "
        f"rejected by unscored pre-filters — chiefly {top_pre.most_common(1)[0][0]} "
        f"({top_pre.most_common(1)[0][1]:,}).",
        f"{tot:,} dvf_signals rows across {len(rows)} sessions. weighted_score is NULL exactly "
        "when a pre-filter rejected the evaluation before scoring ran.",
        "High — a direct count, and the reject reasons name the gate.",
        "This reframes the earlier finding. The score and confidence stack is not the "
        "selection mechanism; it only ranks what the binary pre-filters already let through. "
        "Chop filter, the directional blocks and the time filter do the real selecting, and "
        "<b>none of them is scored, weighted or measured anywhere</b>.",
        "Benchmark the pre-filters the way the scoring stack was benchmarked: for each, compare "
        "outcomes on the evaluations it blocked against arbitrary entries at the same instants.")]
    return "".join(out), finds
