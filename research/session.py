"""Per-session research view.

    python -m research.session 2026-09-04
    python -m research.session 2026-09-04 --deep      # also price what each pre-filter blocked
    python -m research.session --all

Data quality is reported first and deliberately gates the reading: when the quality panel
fails, the strategy sections stay available for forensics but say so at the top.
"""
from __future__ import annotations

import datetime as _dt
import os
import statistics as _st
import sys
from collections import Counter
from typing import Dict, List, Optional, Sequence

from research import provenance as prov
from research.candles import TIMEFRAMES, frame
from research.candles import build as bars_of
from research.db import Book, parse_ts
from research.entries import cascade, causal_features, compare_groups, profiles
from research.execution import cost_sensitivity, freshness, quote_quality
from research.market import (DEFAULT_WINDOWS, annotate_participation, legs, max_move,
                             movement_map, session_profile)
from research.opportunities import Universe
from research.prefilters import PRE_SCORING, blocked_instants, gate_report, ladder_counts
from research.render import Page, chip, esc, finding, kv, table
from research.signals import component_stats, indicator_variance, score_pairs
from research.svg import Chart, heatmap
from research.transmission import expected_vs_actual, session_transmission

OUT_DIR = os.path.join("claude_code", "research_output")


def thin(series, max_pts: int = 1400):
    """Render-only downsampling. Analysis always runs on the full series."""
    if len(series) <= max_pts:
        return list(series)
    step = len(series) / max_pts
    keep, i = [], 0.0
    while int(i) < len(series):
        a, b = int(i), min(len(series), int(i + step))
        chunk = series[a:b] or [series[a]]
        keep.append(max(chunk, key=lambda x: x[1]) if len(keep) % 2 else min(chunk, key=lambda x: x[1]))
        i += step
    keep[0], keep[-1] = series[0], series[-1]
    keep.sort(key=lambda x: x[0])
    return keep


# ─────────────────────────── sections ───────────────────────────
def sec_quality(book: Book, day: str) -> tuple:
    q = quote_quality(book, day)
    fr = freshness(book, day)
    sig = book.signals(day)
    rows = []
    if q.get("n"):
        rows += [("option + spot ticks", chip("option_ltp"), f"{q['n']:,}"),
                 ("bid / ask", chip("bid"), f"{q['midpoint_exact_pct']}% midpoint-exact · "
                                            f"{q['distinct_spread_ratios']} distinct ratios"),
                 ("quote_source", chip("quote_source"), "not persisted per row"),
                 ("open interest", chip("oi"), f"{q['oi_populated_pct']}% populated"),
                 ("timestamps", chip("timestamps"),
                  f"{q['timestamp_collisions']:,} same-second collisions ({q['collision_pct']}%)"),
                 ("PE coverage", chip("option_ltp"), f"{q['pe_ticks']:,} PE ticks")]
    if fr:
        rows.append(("spot freshness", chip("spot"),
                     f"{fr['unchanged_pct']}% unchanged · longest frozen run "
                     f"{fr['longest_frozen_run']}s · {fr['gaps_over_20s']} gaps >20s"))
    if sig:
        iv = indicator_variance(book, day)
        const = [r["input"] for r in iv if r["state"] in ("constant", "all null")]
        rows.append(("signal inputs", chip("score"),
                     f"{len(sig):,} evaluations · constant: {', '.join(const) or 'none'}"))
        rows.append(("signal window", chip("score"),
                     f"{sig[0]['t']:%H:%M} – {sig[-1]['t']:%H:%M}"))
    rows.append(("transaction costs", chip("costs"), "no field exists in the schema"))
    body = table(["Field", "Provenance", "Measured on this session"],
                 [(a, b, c) for a, b, c in rows])
    blocked = q.get("midpoint_exact_pct", 0) >= 95
    if blocked:
        body = ("<div class='flag'><h4>Execution conclusions are blocked on this session</h4>"
                "<p>Every quote sits exactly on the midpoint, which real prints never do. The "
                "bid/ask is the <code>ltp ± 0.3%/2</code> fallback, so no spread, slippage or "
                "net-of-cost figure below is a measurement. Movement, transmission and capture "
                "rest on LTP and are unaffected.</p></div>") + body
    if not q.get("n"):
        # No tick row exists for this day, so midpoint-exactness, OI fill and timestamp
        # uniqueness have nothing to count. Reporting them as "0%" would state a
        # measurement the session cannot support - say the data is absent instead.
        finds = [finding(
            f"No option or spot tick row exists for {day}, so quote quality, OI fill and "
            f"timestamp uniqueness are not measurable on this session.",
            f"The tick table holds no row for this date ({q.get('verdict', 'no tick data')}); "
            "anything else in this report comes from dvf_signals and trades alone.",
            "High — the absence is itself a count; nothing about quote quality is claimed.",
            "Read no execution, spread or cost figure from this session, and no data-quality "
            "trend that includes it.",
            "Only a session recorded by the tick collector can answer these.")]
    else:
        finds = [finding(
            f"Quote data on {day} is fabricated; OI is {q['oi_populated_pct']}% populated; "
            f"{q['collision_pct']}% of ticks share a second with another.",
            "Midpoint-exactness, OI fill rate and timestamp uniqueness counted directly over the "
            "session's tick rows.",
            "High — these are counts over the schema, not inferences.",
            "Read every rupee figure in this report as gross of an unknown execution cost. "
            "Point-based results stand.",
            "Collector solo run for real quotes; the OI repair lands from the next live session.")]
    return body, finds


def sec_market(book: Book, day: str) -> tuple:
    spot, src = book.spot(day)
    if len(spot) < 10:
        return "<p class='none'>No usable spot series.</p>", []
    trades = book.trades(day)
    prof = session_profile(spot, trades)
    lg25 = legs(spot, 25.0)
    t0, t1 = spot[0][0], spot[-1][0]
    c = Chart(h=300, title=f"{day} · NIFTY spot",
              subtitle=f"{'tick series' if src == 'tick' else 'coarse per-evaluation samples'}"
                       f" · {len(spot):,} points · range {prof['range']:.2f} pts")
    c.set_time_x(t0, t1)
    c.set_y(prof["low"], prof["high"])
    c.grid(4, lambda v: f"{v:,.0f}")
    c.time_axis(t0, t1, 30)
    for l in sorted(lg25, key=lambda x: -abs(x["move"]))[:6]:
        c.vspan(l["start"], l["end"], "var(--up)" if l["move"] > 0 else "var(--dn)", 0.10)
    drawn = thin(spot)
    c.area(drawn, "var(--accent)", 0.07)
    c.line(drawn, "var(--accent)", 1.2)
    c.hline(prof["high"], "var(--grid-strong)")
    c.hline(prof["low"], "var(--grid-strong)")
    for tr in trades:
        e = parse_ts(tr["entry_time"])
        sp = next((p for t, p in spot if t >= e), None)
        if sp is None:
            continue
        c.parts.append(f'<g data-event="trade-{tr["id"]}">')
        c.marker(e, sp, "entry", "var(--up)" if tr["pnl"] > 0 else "var(--dn)", 4.5,
                 f"#{tr['id']} {tr['direction']} {e:%H:%M:%S} Rs{tr['pnl']:.0f}")
        c.parts.append("</g>")
    rows = [("Open / close", f"{prof['open']:,.2f} → {prof['close']:,.2f}"),
            ("Net movement", f"{prof['net']:+,.2f} pts"),
            ("High", f"{prof['high']:,.2f} @ {prof['high_at']:%H:%M:%S}"),
            ("Low", f"{prof['low']:,.2f} @ {prof['low_at']:%H:%M:%S}"),
            ("Total range", f"{prof['range']:,.2f} pts")]
    for key, lab in (("max_10s", "10s"), ("max_30s", "30s"), ("max_1m", "1m"),
                     ("max_5m", "5m"), ("max_10m", "10m"), ("max_30m", "30m")):
        rows.append((f"Max {lab} move", f"+{prof[key]['up']:.2f} / −{prof[key]['down']:.2f}"))
    for thr in (5, 10, 15, 25):
        rows.append((f"Legs ≥{thr} pts", str(prof[f"legs_{thr}"])))
    if prof.get("largest_up_leg"):
        l = prof["largest_up_leg"]
        rows.append(("Largest up leg", f"{l['move']:+.2f} pts / {l['dur_min']:.1f} min"))
    if prof.get("largest_down_leg"):
        l = prof["largest_down_leg"]
        rows.append(("Largest down leg", f"{l['move']:+.2f} pts / {l['dur_min']:.1f} min"))
    big = sorted(lg25, key=lambda x: -abs(x["move"]))[:5]
    untouched = sum(1 for l in big
                    if not any(l["start"] <= parse_ts(t["entry_time"]) <= l["end"] for t in trades))
    finds = [finding(
        f"{prof['range']:.0f} pts of range across {prof['legs_25']} legs of 25 pts or more; "
        f"{untouched} of the 5 largest carried no entry.",
        f"Spot {'ticks' if src == 'tick' else 'coarse samples'}, n={len(spot):,}, "
        f"{len(trades)} trades.",
        "High for the market numbers. "
        + ("Participation is measured only from 09:45 on this session — the coarse series has "
           "no earlier samples." if src != "tick" else "High for participation."),
        "Treat range as available, not as captured; the capture cascade section prices the gap.",
        "Compare participation across sessions once more days carry tick data.")]
    return c.render() + kv(rows), finds


def sec_timeframes(book: Book, day: str) -> tuple:
    spot, src = book.spot(day)
    if src != "tick":
        return ("<p class='none'>Derived candles need the tick series; this session carries "
                "only coarse per-evaluation samples.</p>", [])
    lg = sorted(legs(spot, 25.0), key=lambda l: -abs(l["move"]))
    focus = lg[0] if lg else None
    a = (focus["start"] - _dt.timedelta(minutes=4)) if focus else spot[0][0]
    b = (focus["end"] + _dt.timedelta(minutes=4)) if focus else a + _dt.timedelta(minutes=30)
    if (b - a).total_seconds() > 2400:
        b = a + _dt.timedelta(seconds=2400)
    seg = [(t, p) for t, p in spot if a <= t <= b]
    out = []
    for name, sec in TIMEFRAMES:
        bars = bars_of(seg, sec)
        if len(bars) < 3:
            continue
        c = Chart(h=150, mt=20, mb=22, title=f"{name} candles",
                  subtitle=f"{len(bars)} bars derived from {len(seg):,} ticks")
        c.set_time_x(a, b)
        c.set_y(min(x["l"] for x in bars), max(x["h"] for x in bars))
        c.grid(3, lambda v: f"{v:,.0f}")
        c.time_axis(a, b, 5 if sec <= 60 else 10)
        c.candles(bars, max(1.6, min(7.0, (c.px1 - c.px0) / max(1, len(bars)) * 0.62)))
        out.append(c.render())
    head = (f"<p class='cap'>One tick series, four derived views, "
            f"<b>{a:%H:%M:%S}–{b:%H:%M:%S}</b>"
            + (f" — the session's largest leg ({focus['move']:+.2f} pts in "
               f"{focus['dur_min']:.1f} min)." if focus else ".") +
            " Nothing is resampled away: the ticks stay underneath and every higher timeframe "
            "is rebuilt from them on demand.</p>")
    finds = [finding(
        "The same movement reads differently by timeframe: a clean 5m impulse is a sequence of "
        "retracements at 10s.",
        f"{a:%H:%M}–{b:%H:%M} rendered at 10s/30s/1m/5m from one series.",
        "High — mechanical aggregation, no inference.",
        "Judge entry timing at the timeframe the strategy actually holds for, not at the one "
        "where the leg is visible.",
        "Test whether any causal 10s/30s feature anticipates the 5m leg direction.")]
    return head + "".join(out), finds


def sec_movement_map(book: Book, day: str) -> tuple:
    spot, _ = book.spot(day)
    if len(spot) < 10:
        return "<p class='none'>No spot series.</p>", []
    mm = movement_map(spot)
    trades = book.trades(day)
    sig = book.signals(day)
    rows, cols = ["range", "max 1m", "legs ≥10", "signals", "entries", "P&L ₹"], []
    vals = {}
    for w in mm:
        lab = w["window"]
        cols.append(lab)
        a, b = lab.split("-")
        ent = [t for t in trades if a <= parse_ts(t["entry_time"]).strftime("%H:%M") < b]
        nsig = sum(1 for s in sig if a <= s["t"].strftime("%H:%M") < b)
        vals[("range", lab)] = w["range"]
        vals[("max 1m", lab)] = w["max_1m"]
        vals[("legs ≥10", lab)] = w["legs10"] or None
        vals[("signals", lab)] = nsig or None
        vals[("entries", lab)] = len(ent) or None
        vals[("P&L ₹", lab)] = round(sum(t["pnl"] for t in ent)) if ent else None
    hm = heatmap(rows, cols, vals,
                 lambda v: f"{v:,.0f}" if abs(v) >= 10 else f"{v:.1f}",
                 title=f"{day} · movement by time of day",
                 legend="blank = no data, never zero")
    widest = max(mm, key=lambda w: w["range"] or 0)["window"]
    busiest = max(cols, key=lambda c: vals[("entries", c)] or 0)
    finds = [finding(
        f"Widest range sits in <b>{widest}</b>; most entries sit in <b>{busiest}</b>.",
        "Per-window range, 1-minute extreme, leg count, signal count and entries, same buckets "
        "on every session.",
        "Medium — one session, and windows are conventional rather than derived.",
        "If the busiest window is not the widest, activity is concentrated where least is on "
        "offer; the pre-filter section shows which gate produced that concentration.",
        "Pool across sessions and test whether the pattern is stable or session-specific.")]
    return hm, finds


def sec_legs(book: Book, day: str) -> tuple:
    spot, _ = book.spot(day)
    if len(spot) < 10:
        return "<p class='none'>No spot series.</p>", []
    trades, sig = book.trades(day), book.signals(day)
    lg = [annotate_participation(l, trades, sig) for l in legs(spot, 10.0)]
    big = sorted(lg, key=lambda l: -abs(l["move"]))[:14]
    rows = []
    for l in big:
        rows.append((f"{l['start']:%H:%M:%S}", f"{l['end']:%H:%M:%S}", l["dir"],
                     f"{l['move']:+.2f}", f"{l['dur_min']:.1f}", f"{l['vel_ppm']:.1f}",
                     f"{l['mae']:+.2f}",
                     (f"{l['vol_before']:.2f}→{l['vol_during']:.2f}"
                      if l["vol_before"] is not None and l["vol_during"] is not None else None),
                     l["signals"] or None, l["blocked"] or None, l["entries"] or None,
                     f"{l['aligned']}/{l['entries']}" if l["entries"] else None,
                     f"{l['entry_position_pct']:.0f}%" if l["entry_position_pct"] is not None else None))
    body = table(["Start", "End", "Dir", "Points", "Min", "pts/min", "MAE", "Vol before→during",
                  "Signals", "Blocked", "Entries", "Aligned", "Entry at"],
                 rows, num_cols=(3, 4, 5, 6, 8, 9, 10))
    zero = [l for l in big if l["entries"] == 0]
    finds = [finding(
        f"{len(zero)} of the 14 largest legs carried no entry at all"
        + (f"; the largest of those moved {max(zero, key=lambda l: abs(l['move']))['move']:+.2f} pts."
           if zero else "."),
        f"Legs ≥10 pts, retrace-confirmed, {len(lg)} on this session, annotated with signals, "
        "blocked evaluations and entries inside each.",
        "Medium — leg membership is a hindsight label measuring alignment, not foresight.",
        "For each empty leg, read the Blocked column: a leg with signals but no entries is a "
        "gate decision, one with no signals is a detection failure. They need different fixes.",
        "Pool leg participation across sessions and test alignment against a 50% null.")]
    return body, finds


def sec_gates(book: Book, day: str, deep: bool = False) -> tuple:
    lc = ladder_counts(book, day)
    if not lc["total"]:
        return "<p class='none'>No signal rows.</p>", []
    stages = [("evaluations", lc["total"])]
    running = lc["total"]
    for g, v in sorted(lc["pre"].items(), key=lambda kv: -kv[1]):
        running -= v
        stages.append((f"− {g}", running))
    stages += [("reached scoring", lc["scored"]),
               ("− confidence gate", lc["scored"] - lc["conf_blocked"]),
               ("accepted", lc["accepted"])]
    c = Chart(h=40 + 21 * len(stages), ml=210, mr=92, mt=22, mb=22,
              title=f"{day} · gate ladder",
              subtitle=f"{lc['pct_scored']}% of evaluations reached the scoring stack")
    c.set_x(0, lc["total"])
    c.set_y(0, len(stages))
    for i, (lab, v) in enumerate(stages):
        yy = c.y(len(stages) - i - 0.5)
        col = ("var(--ink3)" if i == 0 else "var(--up)" if lab == "accepted"
               else "var(--accent)" if lab == "reached scoring" else "var(--dn)")
        c.parts.append(f'<rect x="{c.px0}" y="{yy-7:.1f}" '
                       f'width="{max(1.5, c.x(max(v,0))-c.px0):.1f}" height="14" fill="{col}" '
                       f'opacity="0.78"><title>{esc(lab)}: {v:,}</title></rect>')
        c.text(c.px0 - 8, yy + 4, lab, "end", "ax-em", raw_xy=True)
        c.text(c.x(max(v, 0)) + 6, yy + 4, f"{v:,}", "start", "ax", raw_xy=True)
    body = [c.render()]
    finds = [finding(
        f"Only {lc['pct_scored']}% of evaluations reached the scoring stack; "
        f"{lc['accepted']} were accepted.",
        f"{lc['total']:,} evaluations. `weighted_score` is NULL exactly when a pre-filter "
        f"rejected the evaluation before scoring ran. Largest: "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(lc["pre"].items(), key=lambda kv: -kv[1])[:3]),
        "High — a direct count, and the reject reason names the gate.",
        "Do not tune score weights to fix selection: the binary pre-filters are the selector, "
        "and none of them is scored or weighted anywhere.",
        "Price each pre-filter against arbitrary timing (run with --deep, or "
        "`python -m research.experiment EXP-11`).")]
    if deep:
        rep = gate_report(book, [day])
        rows = []
        for g, r in sorted(rep["gates"].items(), key=lambda kv: (kv[1]["stats"].get("exp") or 0)):
            s = r["stats"]
            rows.append((g, f"{r['raw']:,}", s.get("n"), s.get("wr"), s.get("exp"),
                         r.get("gap"), r.get("p"), r["verdict"]))
        body.append(table(["Pre-filter", "Rows rejected", "Episodes", "WR%", "E/trade ₹",
                           "vs benchmark", "p", "Reading"], rows, num_cols=(1, 2, 3, 4, 5, 6)))
        body.append(f"<p class='cap'>Benchmark: arbitrary timing on the same grid, "
                    f"E=₹{rep['benchmark']['exp']:.2f} over n={rep['benchmark']['n']}. Each arm "
                    f"ignores the other gates, so every figure is an upper bound on what that "
                    f"one gate alone did.</p>")
    return "".join(body), finds


def sec_signals(book: Book, day: str) -> tuple:
    sig = book.signals(day)
    if not sig:
        return "<p class='none'>No signal rows.</p>", []
    comps = component_stats(book, day)
    sp = score_pairs(book, day)
    c = Chart(h=44 + 20 * len(comps), ml=132, mt=22, mb=26,
              title="Score components · distinct values",
              subtitle="a component with one value cannot rank anything")
    c.set_x(0, max(4, max(r["distinct"] for r in comps)))
    c.set_y(0, len(comps))
    for i, r in enumerate(comps):
        yy = c.y(len(comps) - i - 0.5)
        col = ("var(--dn)" if r["constant"] else
               "var(--warn)" if r["near_constant"] or r["distinct"] <= 2 else "var(--up)")
        c.parts.append(f'<rect x="{c.px0}" y="{yy-6:.1f}" '
                       f'width="{max(2.0, c.x(r["distinct"])-c.px0):.1f}" height="12" '
                       f'fill="{col}" opacity="0.85"><title>{esc(r["component"])}: '
                       f'{r["distinct"]} distinct, contribution {r["contribution"]}</title></rect>')
        c.text(c.px0 - 8, yy + 4, r["component"], "end", "ax-em", raw_xy=True)
        c.text(c.x(r["distinct"]) + 6, yy + 4,
               f"{r['distinct']}" + (" — CONSTANT" if r["constant"] else ""), "start", "ax",
               raw_xy=True)
    iv = indicator_variance(book, day)
    body = [c.render(),
            table(["Component", "Distinct", "Coverage %", "Min", "Max", "Contribution", "State"],
                  [(r["component"], r["distinct"], r["coverage"], r["min"], r["max"],
                    r["contribution"],
                    "CONSTANT" if r["constant"] else ("near-constant" if r["near_constant"] else "varies"))
                   for r in comps], num_cols=(1, 2, 3, 4, 5)),
            table(["Raw input", "Distinct", "Null rows", "State"],
                  [(r["input"], r["distinct"], r["null"], r["state"]) for r in iv],
                  num_cols=(1, 2)),
            kv([("Evaluations", f"{len(sig):,}"),
                ("Reached scoring", f"{sp['scored']:,}"),
                ("Distinct (score, confidence) pairs", str(sp["distinct_pairs"])),
                ("Most common pair", f"{sp['top_pair']} — {sp['top_share']}% of scored rows"
                 if sp["top_pair"] else "—")])]
    dead = [r["component"] for r in comps if r["constant"]]
    finds = [finding(
        f"{len(dead)} of {len(comps)} score components are constant on this session; "
        f"{sp['top_share']}% of scored evaluations produce one (score, confidence) pair.",
        f"Distinct-value counts over {len(sig):,} evaluations. Constant: "
        f"{', '.join(dead) or 'none'}.",
        "High — counts, not tests.",
        "Do not tune a weight whose component has one value. Fix the input first, then "
        "re-measure variance before touching any coefficient.",
        "Re-run on the first session after the delta/OI repair and check whether delta, greeks "
        "and oi leave the constant list.")]
    return "".join(body), finds


def sec_entries(book: Book, day: str, limit: int = 8) -> tuple:
    ps = profiles(book, day)
    spot, src = book.spot(day)
    if not ps or src != "tick":
        return "<p class='none'>Entry windows need tick data and at least one trade.</p>", []
    out = []
    for p in ps[:limit]:
        opt = book.option(p["symbol"], day)
        e, x = p["entry_t"], p["exit_t"]
        a, b = e - _dt.timedelta(minutes=5), e + _dt.timedelta(minutes=10)
        seg = [(t, q) for t, q in opt if a <= t <= b]
        if len(seg) < 20:
            continue
        pre = bars_of(opt, 60, upto=e)[-6:]
        post = bars_of([(t, q) for t, q in opt if e < t <= b], 60)
        c = Chart(h=210, mt=22, mb=24,
                  title=f"#{p['id']} {p['side']} {p['symbol'][-9:]} · entry {e:%H:%M:%S}",
                  subtitle=f"{p['reason']} · {p['captured']:+.2f} pts · ₹{p['pnl']:+,.0f} · "
                           f"score {p['score']} conf {p['confidence']}")
        c.set_time_x(a, b)
        lo = min(min(q for _, q in seg), p["entry"], p["exit"])
        hi = max(max(q for _, q in seg), p["entry"], p["exit"])
        c.set_y(lo, hi)
        c.grid(3, lambda v: f"{v:,.1f}")
        c.time_axis(a, b, 2)
        c.vspan(e, x, "var(--accent)", 0.09, "in trade")
        c.line(thin(seg, 500), "var(--ink3)", 0.9, 0.55)
        c.candles(pre + post, 4.0)
        c.hline(p["entry"], "var(--grid-strong)")
        c.parts.append(f'<g data-event="trade-{p["id"]}">')
        c.marker(e, p["entry"], "entry", "var(--accent)", 5.5, f"entry {p['entry']}")
        c.marker(x, p["exit"], "exit", "var(--up)" if p["win"] else "var(--dn)", 5.0,
                 f"exit {p['exit']}")
        c.parts.append("</g>")
        mx = max((q for t, q in opt if e < t <= e + _dt.timedelta(minutes=3)), default=None)
        if mx:
            c.hline(mx, "var(--up)")
        out.append(c.render())
        bf = p["before"]
        out.append(kv([
            ("as-of momentum 10s / 30s / 1m",
             f"{bf.get('spot_mom_10s')} / {bf.get('spot_mom_30s')} / {bf.get('spot_mom_1m')} spot pts"),
            ("as-of option momentum 1m", str(bf.get("opt_mom_1m"))),
            ("as-of position in 1m range", f"{bf.get('spot_pos_1m')}%"),
            ("distance from 1m high / low",
             f"{bf.get('dist_from_hi_1m')} / {bf.get('dist_from_lo_1m')}"),
            ("entry bar (partial)",
             f"{bf.get('bar_dir')} body {bf.get('bar_body')} close at {bf.get('bar_close_pos')}"),
            ("consecutive prior bars", str(bf.get("consecutive_bars"))),
        ]))
        ao, asp = p["after_option"], p.get("after_spot") or {}
        rows = [(lab, asp.get(f"mfe_{h}"), asp.get(f"mae_{h}"), ao.get(f"mfe_{h}"),
                 ao.get(f"mae_{h}"), p["captured"],
                 f"{100*p['captured']/ao[f'mfe_{h}']:.0f}%"
                 if ao.get(f"mfe_{h}") and ao[f"mfe_{h}"] > 0 else None)
                for h, lab in ((30, "30s"), (60, "1m"), (180, "3m"), (300, "5m"), (600, "10m"))]
        out.append(table(["Horizon", "spot MFE", "spot MAE", "option MFE", "option MAE",
                          "captured", "% of option MFE"], rows, num_cols=(1, 2, 3, 4, 5, 6)))
    note = ("<p class='cap'>The bar holding the entry is drawn <b>dashed and hollow</b>: it is "
            "built from ticks up to the entry second only. Everything under “as-of” is computed "
            "the same way and cannot see past the entry. The MFE/MAE table is the opposite — "
            "deliberately uncensored, measured over fixed horizons regardless of when the exit "
            "fired, because exit-truncated MFE cannot be used to judge an exit.</p>")
    gaps = [compare_groups(ps, k) for k in
            ("spot_mom_1m", "spot_mom_5m", "opt_mom_1m", "spot_pos_1m", "spot_accel")]
    gaps = [g for g in gaps if g]
    finds = [finding(
        "Causal entry features do not separate winners from losers on this session.",
        "Winners vs losers on as-of features: "
        + "; ".join(f"{g['feature']} {g['winners']} vs {g['losers']}" for g in gaps[:4])
        + f" (n={len(ps)}).",
        "Low on its own — one session, few trades. Descriptive only; no test is implied here.",
        "Do not build an entry rule from a single session's gap. Pool across sessions before "
        "testing any of these.",
        "Run the same comparison pooled over every tick session, with an exact permutation test.")]
    return note + "".join(out), finds


def sec_transmission(book: Book, day: str) -> tuple:
    rows = session_transmission(book, day)
    if not rows:
        return "<p class='none'>Transmission needs tick spot and option series.</p>", []
    labs = [l for _, l in (("", "10s"), ("", "30s"), ("", "1m"), ("", "3m"), ("", "5m"), ("", "10m"))]
    labs = ["10s", "30s", "1m", "3m", "5m", "10m"]
    syms = sorted({r["symbol"] for r in rows})
    c = Chart(h=250, ml=52, title="Realised delta by horizon",
              subtitle="slope of Δoption on Δspot through the origin")
    c.set_x(-0.4, len(labs) - 0.6)
    c.set_y(0, max(r["beta"] for r in rows) * 1.15)
    c.grid(4, lambda v: f"{v:.2f}")
    c.x_axis_labels(list(enumerate(labs)))
    cols = ["var(--accent)", "var(--up)", "var(--warn)", "var(--dn)"]
    for k, sym in enumerate(syms):
        pts = [(labs.index(r["horizon"]), r["beta"]) for r in rows if r["symbol"] == sym]
        pts.sort()
        col = cols[k % len(cols)]
        if len(pts) > 1:
            d = " ".join(("M" if i == 0 else "L") + f"{c.x(x):.1f},{c.y(y):.1f}"
                         for i, (x, y) in enumerate(pts))
            c.parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>')
        for x, y in pts:
            c.dot(x, y, 3.4, col, 1.0, f"{sym[-9:]} {labs[int(x)]}: {y}")
        if pts:
            c.text(c.x(pts[-1][0]) + 6, c.y(pts[-1][1]) + 4, sym[-9:], "start", "ax", raw_xy=True)
    c.hline(0.5, "var(--grid-strong)")
    body = [c.render(),
            table(["Contract", "Side", "Horizon", "n", "realised delta", "R²", "resid σ",
                   "med |Δspot|", "med |Δopt|"],
                  [(r["symbol"][-9:], r["side"], r["horizon"], r["n"], r["beta"], r["r2"],
                    r["resid_sd"], r["med_dspot"], r["med_dopt"]) for r in rows],
                  num_cols=(3, 4, 5, 6, 7, 8))]
    short = [r for r in rows if r["horizon"] in ("10s", "30s")]
    long_ = [r for r in rows if r["horizon"] in ("3m", "5m")]
    finds = [finding(
        f"Realised delta averages {_st.mean([r['beta'] for r in short]):.2f} at 10–30s and "
        f"{_st.mean([r['beta'] for r in long_]):.2f} at 3–5m; R² at the short end is "
        f"{_st.mean([r['r2'] for r in short]):.2f}.",
        f"{sum(r['n'] for r in rows):,} paired observations across {len(syms)} contracts, "
        "regression through the origin, residual σ reported alongside.",
        "High within this session and these strikes. "
        + ("CE only — no PE contract carried enough ticks."
           if all(r["side"] == "CE" for r in rows) else "Both sides present."),
        "Size expectations by horizon, not by a nominal delta: at the horizon the strategy "
        "holds for, most option movement is not explained by spot at all.",
        "Repeat per strike once PE exists and test whether transmission varies with moneyness.")]
    return "".join(body), finds


def sec_cascade(book: Book, day: str, horizon: int = 180) -> tuple:
    ps = profiles(book, day)
    cs = [cascade(p, horizon) for p in ps]
    cs = [c for c in cs if c["spot_avail"] is not None and c["opt_avail"] is not None]
    if not cs:
        return "<p class='none'>No trades with tick coverage.</p>", []
    out = []
    for label, want in (("Winners", True), ("Losers", False)):
        grp = [c for c in cs if c["win"] == want]
        if not grp:
            continue
        c = Chart(h=42 + 26 * len(grp), ml=74, mr=190, mt=24, mb=26,
                  title=f"Capture cascade · {label} · {horizon//60}-minute horizon",
                  subtitle="spot offered → option offered → captured (option points)")
        mx = max(max(abs(g["spot_avail"]), abs(g["opt_avail"]), abs(g["captured"])) for g in grp)
        c.set_x(0, mx * 1.05)
        c.set_y(0, len(grp))
        c.grid(4, lambda v: "")
        for i, g in enumerate(grp):
            yy = c.y(len(grp) - i - 0.5)
            c.parts.append(f'<g data-event="trade-{g["id"]}">')
            for val, col, hgt, op in ((g["spot_avail"], "var(--ink3)", 13, 0.30),
                                      (g["opt_avail"], "var(--warn)", 9, 0.75),
                                      (g["captured"], "var(--accent)", 5, 1.0)):
                w = max(1.0, c.x(max(0.0, val)) - c.px0)
                c.parts.append(f'<rect x="{c.px0}" y="{yy-hgt/2:.1f}" width="{w:.1f}" '
                               f'height="{hgt}" fill="{col}" opacity="{op}"/>')
            c.parts.append("</g>")
            c.text(c.px0 - 8, yy + 4, f"#{g['id']} {g['side']}", "end", "ax-em", raw_xy=True)
            tx = (f"spot {g['spot_avail']:+.1f} → opt {g['opt_avail']:+.1f} → "
                  f"got {g['captured']:+.1f}")
            if g["transmission"] is not None:
                tx += f"  τ {g['transmission']:.2f}"
            if g["capture_of_available"] is not None:
                tx += f"  κ {g['capture_of_available']:.2f}"
            c.text(c.px1 + 6, yy + 4, tx, "start", "ax", raw_xy=True)
        out.append(c.render())
    rows = []
    for lab, want in (("Winners", True), ("Losers", False)):
        grp = [c for c in cs if c["win"] == want]
        if not grp:
            continue
        rows.append((lab, len(grp),
                     round(_st.mean([g["spot_avail"] for g in grp]), 2),
                     round(_st.mean([g["opt_avail"] for g in grp]), 2),
                     round(_st.mean([g["captured"] for g in grp]), 2),
                     round(_st.median([g["transmission"] for g in grp
                                       if g["transmission"] is not None]), 2)
                     if any(g["transmission"] is not None for g in grp) else None))
    out.append(table(["Group", "n", "spot offered", "option offered", "captured", "median τ"],
                     rows, num_cols=(1, 2, 3, 4, 5)))
    loss = [c for c in cs if not c["win"]]
    win = [c for c in cs if c["win"]]
    finds = [finding(
        (f"Losers were offered {_st.mean([c['opt_avail'] for c in loss]):.2f} option points in "
         f"{horizon//60} minutes; winners were offered "
         f"{_st.mean([c['opt_avail'] for c in win]):.2f} and kept "
         f"{_st.mean([c['captured'] for c in win]):.2f}.") if loss and win else
        "Not enough of both groups on this session to split the cascade.",
        f"{len(cs)} trades. Available movement recomputed from ticks over a fixed horizon, so "
        "it is not truncated by the exit the way the stored mfe column is.",
        "High for the arithmetic; low for generalisation from one session.",
        "Attribute the shortfall before acting: a low τ is a transmission or strike problem, a "
        "low κ is an exit or hold problem, and a small option-offered figure is an entry problem.",
        "Pool the cascade across sessions and track the loser-side offered movement — that is "
        "the number an entry improvement has to move.")]
    return "".join(out), finds


def sec_exits(book: Book, day: str) -> tuple:
    ps = profiles(book, day)
    if not ps:
        return "<p class='none'>No trades with tick coverage.</p>", []
    rows, attrs = [], {}
    for i, p in enumerate(ps):
        attrs[i] = f'data-event="trade-{p["id"]}"'
        rows.append((f"#{p['id']} {p['side']}", p["reason"], f"{p['hold']:.0f}s",
                     f"{p['captured']:+.2f}", p["mfe_in_trade"], p["mae_in_trade"],
                     p["post_exit_up_30s"], p["post_exit_up_1m"], p["post_exit_up_5m"],
                     p["post_exit_dn_5m"]))
    body = table(["Trade", "Exit reason", "Hold", "Captured", "MFE in trade", "MAE in trade",
                  "+30s", "+1m", "+5m up", "+5m down"], rows, num_cols=(3, 4, 5, 6, 7, 8, 9),
                 row_attrs=attrs)
    wins = [p for p in ps if p["win"]]
    up5 = [p["post_exit_up_5m"] for p in wins if p["post_exit_up_5m"] is not None]
    dn5 = [p["post_exit_dn_5m"] for p in wins if p["post_exit_dn_5m"] is not None]
    mix = Counter(p["reason"] for p in ps)
    finds = [finding(
        (f"After a winning exit the option went a further {_st.mean(up5):+.2f} pts in five "
         f"minutes on average, and {_st.mean(dn5):+.2f} against.") if up5 and dn5 else
        "Too few winners on this session to characterise post-exit movement.",
        f"{len(ps)} exits. Mix: " + ", ".join(f"{k} {v}" for k, v in mix.most_common()),
        "Low–medium — n small, and post-exit paths are counterfactual only if the position "
        "would actually have been held, which the loss rules would often have prevented.",
        "Do not read continuation as forgone profit: holding captures the adverse side too. "
        "Only a full-ladder replay prices the alternative.",
        "Replay the alternative exit policies on this session and compare against control.")]
    return body, finds


def sec_execution(book: Book, day: str) -> tuple:
    ps = profiles(book, day)
    if not ps:
        return "<p class='none'>No trades.</p>", []
    sens = cost_sensitivity(ps)
    body = [("<div class='flag'><h4>Everything in this section is an assumption</h4>"
             "<p>The spread used here is the production fallback, not a measured quote. The "
             "table shows how the same trades reprice under different assumptions — which is "
             "the honest form of an execution analysis until real quotes exist.</p></div>"),
            table(["Assumed round-trip spread %", "mean captured pts", "winners", "n"],
                  [(r["assumed_spread_pct"], r["mean_captured_pts"], r["winners"], r["n"])
                   for r in sens], num_cols=(0, 1, 2, 3))]
    base = next((r for r in sens if r["assumed_spread_pct"] == 0.30), None)
    worst = sens[-1] if sens else None
    finds = [finding(
        (f"At the assumed 0.30% spread the mean captured move is "
         f"{base['mean_captured_pts']:+.2f} pts; at {worst['assumed_spread_pct']}% it is "
         f"{worst['mean_captured_pts']:+.2f}.") if base and worst else "No trades to reprice.",
        "Recorded fills already carry the 0.3% fabrication; the table reprices the difference.",
        "The sensitivity is exact arithmetic. The true spread is UNKNOWN, so the level is not "
        "a measurement.",
        "Never quote a net expectancy from this session as a result. Quote the range across "
        "assumptions instead.",
        "Collector solo run, with the trading bot stopped, is the only thing that resolves it.")]
    return "".join(body), finds


def sec_cepe(book: Book, day: str) -> tuple:
    rows = []
    for side in ("CE", "PE"):
        syms = book.option_symbols(day, side)
        n = sum(c for _, c in syms)
        trs = [t for t in book.trades(day) if t["direction"] == side]
        tr_ = session_transmission(book, day)
        beta = [r["beta"] for r in tr_ if r["side"] == side and r["horizon"] == "1m"]
        rows.append((side, f"{n:,}", len(syms), len(trs) or None,
                     f"{sum(1 for t in trs if t['pnl']>0)}/{len(trs)}" if trs else None,
                     round(sum(t["pnl"] for t in trs)) if trs else None,
                     round(_st.mean(beta), 3) if beta else None))
    body = [table(["Side", "Option ticks", "Contracts", "Trades", "W/L", "P&L ₹",
                   "realised delta 1m"], rows, num_cols=(1, 2, 3, 5, 6))]
    pe_ticks = int(rows[1][1].replace(",", ""))
    if pe_ticks < 2000:
        body.append("<div class='flag'><h4>DATA COVERAGE FAILURE — PE</h4>"
                    f"<p>{pe_ticks:,} PE option ticks on this session. This is a collection "
                    "problem, not a statement about PE performance: one contract is subscribed "
                    "at a time and it was CE. Nothing about PE — including whether the repaired "
                    "negative-delta scoring works — is testable from this session.</p></div>")
    finds = [finding(
        f"PE carries {pe_ticks:,} option ticks against {rows[0][1]} for CE.",
        "Tick counts by symbol suffix.",
        "High — a coverage count.",
        "Label every pooled statistic on this session as CE-only. Do not report PE performance.",
        "Dual CE/PE subscription is the fix; until then PE stays marked as a coverage failure.")]
    return "".join(body), finds


def sec_questions(book: Book, day: str) -> tuple:
    """Investigation candidates the session surfaces. Candidates, never conclusions."""
    spot, src = book.spot(day)
    ps = profiles(book, day)
    items = []
    if len(spot) > 10:
        trades = book.trades(day)
        sig = book.signals(day)
        lg = [annotate_participation(l, trades, sig) for l in legs(spot, 10.0)]
        empty = [l for l in lg if l["entries"] == 0]
        if empty:
            w = max(empty, key=lambda l: abs(l["move"]))
            items.append(("Largest leg with zero entries",
                          f"{w['move']:+.2f} pts, {w['start']:%H:%M:%S}–{w['end']:%H:%M:%S}, "
                          f"{w['signals']} signals of which {w['blocked']} blocked"))
        withsig = [l for l in empty if l["signals"] > 0]
        if withsig:
            w = max(withsig, key=lambda l: abs(l["move"]))
            items.append(("Largest leg seen but not entered",
                          f"{w['move']:+.2f} pts with {w['blocked']} blocked evaluations inside"))
    if ps:
        cs = [cascade(p) for p in ps]
        got = [c for c in cs if c["opt_avail"] is not None]
        if got:
            w = max(got, key=lambda c: (c["opt_avail"] or 0) - c["captured"])
            items.append(("Largest offered-but-not-captured",
                          f"#{w['id']}: {w['opt_avail']:+.2f} offered, {w['captured']:+.2f} kept"))
        worst = min(ps, key=lambda p: p["pnl"])
        items.append(("Worst entry", f"#{worst['id']} {worst['side']} "
                                     f"{worst['entry_t']:%H:%M:%S}, ₹{worst['pnl']:+,.0f}, "
                                     f"{worst['reason']}"))
        rec = [p for p in ps if p["mae_in_trade"] is not None and p["mae_in_trade"] < -2
               and p["win"]]
        if rec:
            items.append(("Deepest drawdown that still won",
                          f"#{rec[0]['id']} MAE {rec[0]['mae_in_trade']:+.2f} → "
                          f"{rec[0]['captured']:+.2f}"))
    comps = component_stats(book, day)
    dead = [r["component"] for r in comps if r["constant"]]
    if dead:
        items.append(("Components with zero variance", ", ".join(dead)))
    mm = movement_map(spot) if len(spot) > 10 else []
    if mm:
        best = max((w for w in mm if w["range"]), key=lambda w: w["range"], default=None)
        if best:
            items.append(("Window with the most movement",
                          f"{best['window']} — {best['range']:.1f} pts range, "
                          f"{best['legs10']} legs ≥10"))
    body = table(["Question", "This session"], items)
    finds = [finding(
        "These are the session's investigation candidates, surfaced automatically.",
        "Derived from legs, cascades, component variance and the movement map on this session.",
        "None — a candidate is not a result.",
        "Pick one and run it through the loop: hypothesis, controlled experiment, out-of-sample "
        "check, decision. Do not act on a candidate directly.",
        "Whichever candidate recurs across sessions is the one worth an experiment.")]
    return body, finds


# ─────────────────────────── assembly ───────────────────────────
def build_session(day: str, deep: bool = False, out_dir: str = OUT_DIR) -> str:
    book = Book()
    kind = book.session_kind(day)
    trades = book.trades(day)
    spot, src = book.spot(day)
    page = Page(
        title=f"PTQ Session {day}",
        h1=f"Session forensics · {day}",
        standfirst="Market movement traced through opportunity, pre-filter, signal, entry, "
                   "option transmission, position and exit — with every field labelled by what "
                   "it actually is.",
        meta=[("Session", day), ("Data", kind), ("Spot", src if spot else "none"),
              ("Trades", len(trades)), ("Signals", f"{len(book.signals(day)):,}"),
              ("Baseline", "8b7490e untouched")])
    page.add("Data quality", *sec_quality(book, day))
    page.add("Market structure", *sec_market(book, day))
    page.add("Synchronized timeframes", *sec_timeframes(book, day))
    page.add("Movement by time of day", *sec_movement_map(book, day))
    page.add("Major legs and participation", *sec_legs(book, day))
    page.add("Pre-filter gate ladder", *sec_gates(book, day, deep))
    page.add("Scoring stack", *sec_signals(book, day))
    page.add("Entry forensics", *sec_entries(book, day))
    page.add("Spot → option transmission", *sec_transmission(book, day))
    page.add("Capture cascade", *sec_cascade(book, day))
    page.add("Exit behaviour", *sec_exits(book, day))
    page.add("Execution and spread", *sec_execution(book, day))
    page.add("CE / PE symmetry", *sec_cepe(book, day))
    page.add("Open questions from this session", *sec_questions(book, day))
    return page.write(os.path.join(out_dir, f"session_{day}.html"))


def main(argv: Sequence[str]) -> int:
    deep = "--deep" in argv
    args = [a for a in argv if not a.startswith("--")]
    book = Book()
    if "--all" in argv or not args:
        days = [s["day"] for s in book.sessions() if s["kind"] in ("tick", "coarse")]
    else:
        days = args
    for d in days:
        p = build_session(d, deep)
        print(f"wrote {p} ({os.path.getsize(p):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
