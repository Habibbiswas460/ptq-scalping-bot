"""Market-side sections: session structure, multi-timeframe candles, legs, time-of-day,
data quality. Each builder returns (html, findings) where findings is a list of dicts with
the fixed keys the report renders: finding / evidence / confidence / interpretation / next.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from typing import Dict, List

from research import provenance as prov
from research.data import TIMEFRAMES, candles, legs, max_move, parse_ts, window
from research.svg import Chart, esc, heatmap

BUCKETS = [("09:15-10:00", "09:15", "10:00"), ("10:00-11:00", "10:00", "11:00"),
           ("11:00-12:00", "11:00", "12:00"), ("12:00-13:00", "12:00", "13:00"),
           ("13:00-14:00", "13:00", "14:00"), ("14:00-15:30", "14:00", "15:30")]


def thin(series, max_pts: int = 1400):
    """Downsample for RENDERING only. Analysis always runs on the full tick series; this
    exists so a 20,000-point path does not become a 500 KB SVG. Extremes are preserved so the
    drawn line still reaches the session high and low."""
    if len(series) <= max_pts:
        return list(series)
    step = len(series) / max_pts
    keep, i = [], 0.0
    while int(i) < len(series):
        a, b = int(i), min(len(series), int(i + step))
        chunk = series[a:b] or [series[a]]
        keep.append(max(chunk, key=lambda x: x[1]) if len(keep) % 2 else min(chunk, key=lambda x: x[1]))
        i += step
    keep[0] = series[0]; keep[-1] = series[-1]
    keep.sort(key=lambda x: x[0])
    return keep


def f(finding, evidence, confidence, interpretation, nxt):
    return {"finding": finding, "evidence": evidence, "confidence": confidence,
            "interpretation": interpretation, "next": nxt}


# ───────────────── 1. session market structure ─────────────────
def session_structure(book, day: str) -> tuple:
    spot, src = book.spot(day)
    if len(spot) < 10:
        return "<p class='none'>No usable spot series for this session.</p>", []
    trades = book.trades(day)
    t0, t1 = spot[0][0], spot[-1][0]
    hi = max(spot, key=lambda x: x[1]); lo = min(spot, key=lambda x: x[1])
    lg25 = legs(spot, 25.0)

    c = Chart(h=300, title=f"{day} · NIFTY spot",
              subtitle=f"{'tick series' if src=='tick' else 'coarse per-evaluation samples'} · "
                       f"{len(spot):,} points · range {hi[1]-lo[1]:.2f} pts")
    c.set_time_x(t0, t1)
    c.set_y(lo[1], hi[1])
    c.grid(4, lambda v: f"{v:,.0f}")
    c.time_axis(t0, t1, 30)

    for lg in sorted(lg25, key=lambda l: -abs(l["move"]))[:6]:
        c.vspan(lg["start"], lg["end"], "var(--up)" if lg["move"] > 0 else "var(--dn)", 0.10)
    drawn = thin(spot)
    c.area(drawn, "var(--accent)", 0.07)
    c.line(drawn, "var(--accent)", 1.2)
    c.hline(hi[1], "var(--grid-strong)"); c.hline(lo[1], "var(--grid-strong)")
    c.text(c.px1 - 2, c.y(hi[1]) - 4, f"session high {hi[1]:,.2f}", "end", "ax", raw_xy=True)
    c.text(c.px1 - 2, c.y(lo[1]) + 12, f"session low {lo[1]:,.2f}", "end", "ax", raw_xy=True)

    for tr in trades:
        e = parse_ts(tr["entry_time"])
        sp = next((p for t, p in spot if t >= e), None)
        if sp is None:
            continue
        win = tr["pnl"] > 0
        c.marker(e, sp, "entry", "var(--up)" if win else "var(--dn)", 4.5,
                 f"#{tr['id']} {tr['direction']} entry {e:%H:%M:%S} pnl Rs{tr['pnl']:.0f}")

    body = [c.render()]

    rows = [("Session open", f"{spot[0][1]:,.2f}"), ("Session close", f"{spot[-1][1]:,.2f}"),
            ("Net movement", f"{spot[-1][1]-spot[0][1]:+,.2f} pts"),
            ("Session high", f"{hi[1]:,.2f} @ {hi[0]:%H:%M:%S}"),
            ("Session low", f"{lo[1]:,.2f} @ {lo[0]:%H:%M:%S}"),
            ("Total range", f"{hi[1]-lo[1]:,.2f} pts")]
    for lab, sec in (("Max 10s move", 10), ("Max 30s move", 30), ("Max 1m move", 60),
                     ("Max 5m move", 300), ("Max 10m move", 600)):
        m = max_move(spot, sec)
        rows.append((lab, f"+{m['up']:.2f} / −{m['down']:.2f} pts"))
    rows.append(("Legs ≥10 pts", str(len(legs(spot, 10.0)))))
    rows.append(("Legs ≥25 pts", str(len(lg25))))
    body.append(_kv_table(rows))

    covered = sum(1 for tr in trades for lg in lg25
                  if lg["start"] <= parse_ts(tr["entry_time"]) <= lg["end"])
    big = sorted(lg25, key=lambda l: -abs(l["move"]))[:5]
    untouched = sum(1 for lg in big if not any(lg["start"] <= parse_ts(t["entry_time"]) <= lg["end"]
                                               for t in trades))
    finds = [f(
        f"{day}: the market offered {hi[1]-lo[1]:.0f} pts of range across {len(lg25)} legs of "
        f"25 pts or more; {untouched} of the 5 largest had no entry inside them.",
        f"Spot {'ticks' if src=='tick' else 'coarse samples'}, n={len(spot):,}. "
        f"{len(trades)} trades, {covered} of them inside a ≥25pt leg.",
        "High for the range and leg counts (measured). "
        + ("Medium for participation — coarse series starts 09:45." if src != "tick"
           else "High for participation on this session."),
        "Range is not the constraint. Whether the strategy was present where the movement "
        "was is the question the next two sections answer.",
        "Compare participation across sessions once more days carry tick data.")]
    return "".join(body), finds


# ───────────────── 2. synchronized timeframes ─────────────────
def multi_timeframe(book, day: str) -> tuple:
    spot, src = book.spot(day)
    if src != "tick":
        return ("<p class='none'>Derived candles need the tick series; this session has only "
                "coarse per-evaluation samples.</p>", [])
    t0, t1 = spot[0][0], spot[-1][0]
    lg = sorted(legs(spot, 25.0), key=lambda l: -abs(l["move"]))
    focus = lg[0] if lg else None
    a = (focus["start"] - _dt.timedelta(minutes=4)) if focus else t0
    b = (focus["end"] + _dt.timedelta(minutes=4)) if focus else t0 + _dt.timedelta(minutes=40)
    seg = [(t, p) for t, p in spot if a <= t <= b]
    if len(seg) < 20:
        seg = spot[:600]; a, b = seg[0][0], seg[-1][0]
    # keep the window to something the 10s view can render legibly
    if (b - a).total_seconds() > 2400:
        b = a + _dt.timedelta(seconds=2400)
        seg = [(t, p) for t, p in seg if t <= b]

    out = []
    for name, sec in TIMEFRAMES:
        bars = candles(seg, sec)
        if len(bars) < 3:
            continue
        c = Chart(h=150, mt=20, mb=22, title=f"{name} candles",
                  subtitle=f"{len(bars)} bars · derived from {len(seg):,} ticks")
        c.set_time_x(a, b)
        c.set_y(min(x["l"] for x in bars), max(x["h"] for x in bars))
        c.grid(3, lambda v: f"{v:,.0f}")
        c.time_axis(a, b, 5 if sec <= 60 else 10)
        width = max(1.6, min(7.0, (c.px1 - c.px0) / max(1, len(bars)) * 0.62))
        c.candles(bars, width)
        out.append(c.render())

    head = (f"<p class='cap'>All four views are derived from the same tick series over "
            f"<b>{a:%H:%M:%S}–{b:%H:%M:%S}</b>"
            + (f", the session's largest leg ({focus['move']:+.2f} pts in "
               f"{focus['dur_min']:.1f} min)." if focus else ".")
            + " The tick series stays underneath; nothing is resampled away.</p>")
    finds = [f(
        "The same movement changes character with timeframe: what is a clean impulse at 5m is "
        f"{len(candles(seg,10))} separate 10s bars with visible retracement.",
        f"{a:%H:%M}–{b:%H:%M} rendered at 10s/30s/1m/5m from one tick series.",
        "High — mechanical, no inference.",
        "A strategy holding 0.9–1.8 min is operating at the 10s–30s view, where the leg is "
        "not yet visible as a leg. That is a timeframe mismatch, not a signal failure.",
        "Test whether any causal 10s/30s feature anticipates the 5m leg direction.")]
    return head + "".join(out), finds


# ───────────────── 3. major legs ─────────────────
def leg_forensics(book, day: str) -> tuple:
    spot, src = book.spot(day)
    if len(spot) < 10:
        return "<p class='none'>No spot series.</p>", []
    trades = book.trades(day)
    lg = legs(spot, 10.0)
    big = sorted(lg, key=lambda l: -abs(l["move"]))[:12]
    rows = []
    for l in big:
        inside = [t for t in trades if l["start"] <= parse_ts(t["entry_time"]) <= l["end"]]
        aligned = sum(1 for t in inside
                      if (t["direction"] == "CE" and l["move"] > 0)
                      or (t["direction"] == "PE" and l["move"] < 0))
        pnl = sum(t["pnl"] for t in inside)
        pos = ""
        if inside:
            first = parse_ts(inside[0]["entry_time"])
            frac = (first - l["start"]).total_seconds() / max(1.0, (l["end"] - l["start"]).total_seconds())
            pos = f"{100*frac:.0f}% in"
        rows.append((f"{l['start']:%H:%M:%S}", f"{l['end']:%H:%M:%S}", l["dir"],
                     f"{l['move']:+.2f}", f"{l['dur_min']:.1f}", f"{l['vel_ppm']:.1f}",
                     str(len(inside)), f"{aligned}/{len(inside)}" if inside else "—",
                     pos or "—", f"{pnl:+.0f}" if inside else "—"))
    head = ["<div class='scroller'><table><thead><tr>"
            "<th>Start</th><th>End</th><th>Dir</th><th class='num'>Points</th>"
            "<th class='num'>Min</th><th class='num'>pts/min</th><th class='num'>Entries</th>"
            "<th>Aligned</th><th>Entry position</th><th class='num'>P&L</th>"
            "</tr></thead><tbody>"]
    for r in rows:
        head.append("<tr>" + "".join(
            f"<td class='{'num' if i in (3,4,5,6,9) else ''}'>{esc(v)}</td>"
            for i, v in enumerate(r)) + "</tr>")
    head.append("</tbody></table></div>")

    n_in = sum(int(r[6]) for r in rows)
    al = sum(int(r[7].split("/")[0]) for r in rows if r[7] != "—")
    finds = [f(
        f"Of the 12 largest legs, {n_in} entries fell inside them and {al} were on the leg's side.",
        f"Legs ≥10 pts, zigzag with a 10-pt retrace confirmation, {len(lg)} legs total on {day}.",
        "Medium — leg membership is a hindsight label; it measures alignment, not foresight. "
        "n is small per session.",
        "Alignment near half means the entry is not selecting the direction of the move it "
        "sits inside. That is an entry-direction problem, not an exit problem.",
        "Pool alignment across all tick sessions and test against a 50% null.")]
    return "".join(head), finds


# ───────────────── 4. time-of-day map ─────────────────
def time_of_day(book, days: List[str]) -> tuple:
    metrics = ["spot range", "max 1m move", "legs ≥10", "signals", "entries", "P&L ₹"]
    vals, cols = {}, [b[0] for b in BUCKETS]
    for m in metrics:
        for lab, a, bnd in BUCKETS:
            vals[(m, lab)] = None
    agg = {lab: {"range": [], "m1": [], "legs": 0, "sig": 0, "ent": 0, "pnl": 0.0} for lab, _, _ in BUCKETS}
    for day in days:
        spot, src = book.spot(day)
        if not spot:
            continue
        trades = book.trades(day)
        sig = book.signals(day)
        for lab, a, bnd in BUCKETS:
            seg = [(t, p) for t, p in spot if a <= t.strftime("%H:%M") < bnd]
            if len(seg) > 3:
                agg[lab]["range"].append(max(p for _, p in seg) - min(p for _, p in seg))
                agg[lab]["m1"].append(max_move(seg, 60)["up"] + max_move(seg, 60)["down"])
                agg[lab]["legs"] += len(legs(seg, 10.0))
            agg[lab]["sig"] += sum(1 for s in sig if a <= s["t"].strftime("%H:%M") < bnd)
            for tr in trades:
                if a <= parse_ts(tr["entry_time"]).strftime("%H:%M") < bnd:
                    agg[lab]["ent"] += 1
                    agg[lab]["pnl"] += tr["pnl"]
    for lab, _, _ in BUCKETS:
        d = agg[lab]
        vals[("spot range", lab)] = round(_st.mean(d["range"]), 1) if d["range"] else None
        vals[("max 1m move", lab)] = round(_st.mean(d["m1"]), 1) if d["m1"] else None
        vals[("legs ≥10", lab)] = d["legs"] or None
        vals[("signals", lab)] = d["sig"] or None
        vals[("entries", lab)] = d["ent"] or None
        vals[("P&L ₹", lab)] = round(d["pnl"]) if d["ent"] else None

    hm = heatmap(metrics, cols, vals, lambda v: f"{v:,.0f}" if abs(v) >= 10 else f"{v:.1f}",
                 title="Time-of-day map · mean per session across all sessions with spot data",
                 legend="same buckets on every session · blank = no data")
    r0 = max(BUCKETS, key=lambda b: vals[("spot range", b[0])] or 0)[0]
    e0 = max(BUCKETS, key=lambda b: vals[("entries", b[0])] or 0)[0]
    finds = [f(
        f"The widest average range sits in <b>{r0}</b>; the most entries sit in <b>{e0}</b>.",
        f"{len(days)} sessions, identical buckets, spot range and entry counts measured per bucket.",
        "Medium — few sessions, and the two traded sessions barely overlap in clock time, which "
        "is itself a confound.",
        "If the busiest entry bucket is not the widest range bucket, the strategy is spending "
        "its activity where there is least to capture.",
        "Recheck once the 09:15–09:45 window produces signals — it has no signal history at all.")]
    return hm, finds


# ───────────────── 14. data quality ─────────────────
def data_quality(book, day: str) -> tuple:
    cur = book.cur
    n = cur.execute("SELECT count(*) FROM ticks WHERE date(timestamp)=?", (day,)).fetchone()[0]
    rows = []
    if n:
        uniq = cur.execute("SELECT count(DISTINCT timestamp||symbol) FROM ticks "
                           "WHERE date(timestamp)=?", (day,)).fetchone()[0]
        mid = cur.execute("SELECT sum(CASE WHEN bid IS NOT NULL AND ask IS NOT NULL "
                          "AND abs(ltp-(bid+ask)/2.0)<0.005 THEN 1 ELSE 0 END) FROM ticks "
                          "WHERE date(timestamp)=?", (day,)).fetchone()[0] or 0
        oi = cur.execute("SELECT sum(oi IS NOT NULL AND oi>0) FROM ticks WHERE date(timestamp)=?",
                         (day,)).fetchone()[0] or 0
        pe = cur.execute("SELECT sum(symbol LIKE '%PE') FROM ticks WHERE date(timestamp)=?",
                         (day,)).fetchone()[0] or 0
        rows += [("option_ltp", "option_ltp", f"{n:,} rows"),
                 ("spot", "spot", f"{n:,} rows carrying spot"),
                 ("bid / ask", "bid", f"{100*mid/n:.1f}% midpoint-exact"),
                 ("timestamps", "timestamps", f"{n-uniq:,} same-second collisions ({100*(n-uniq)/n:.1f}%)"),
                 ("oi", "oi", f"{oi:,} rows with oi>0"),
                 ("PE coverage", "option_ltp", f"{pe:,} PE ticks of {n:,}")]
    sig = book.signals(day)
    if sig:
        const = []
        for k in ("regime", "oi_direction", "oi_change_pct", "delta", "rsi", "vwap"):
            vs = {str(s["indicators_snapshot"].get(k)) for s in sig}
            if len(vs) <= 1:
                const.append(k)
        rows.append(("signal inputs", "score",
                     f"{len(sig):,} evaluations · constant: {', '.join(const) if const else 'none'}"))
        rows.append(("signal window", "score",
                     f"{sig[0]['t']:%H:%M} – {sig[-1]['t']:%H:%M}"))
    rows.append(("transaction costs", "costs", "no field exists anywhere"))

    out = ["<div class='scroller'><table><thead><tr><th>Field</th><th>Status</th>"
           "<th>Measured on this session</th><th class='wrap-cell'>Limit</th></tr></thead><tbody>"]
    for label, key, measured in rows:
        lab, st = prov.chip(key)
        out.append(f"<tr><td class='mono'>{esc(label)}</td>"
                   f"<td><span class='chip c-{st}'>{esc(lab)}</span></td>"
                   f"<td class='mono'>{esc(measured)}</td>"
                   f"<td class='wrap-cell'>{esc(prov.reason(key))}</td></tr>")
    out.append("</tbody></table></div>")

    finds = [f(
        "Every rupee figure on this page inherits a fabricated spread; no chart here shows a "
        "measured execution cost.",
        "bid/ask midpoint-exact on effectively every row; quote_source is not persisted; no "
        "cost fields exist.",
        "High — this is a property of the schema, not an inference.",
        "Point-based conclusions (movement, transmission, capture) stand on real LTP. "
        "Rupee-based conclusions do not, and must be read as gross of an unknown cost.",
        "The collector's solo run is the only thing that resolves this.")]
    return "".join(out), finds


def _kv_table(rows) -> str:
    out = ["<div class='kv'>"]
    for k, v in rows:
        out.append(f"<div class='kv-row'><span class='kv-k'>{esc(k)}</span>"
                   f"<span class='kv-v'>{esc(v)}</span></div>")
    out.append("</div>")
    return "".join(out)
