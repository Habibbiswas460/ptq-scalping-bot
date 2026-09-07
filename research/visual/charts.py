"""The chart layer: persisted rows in, SVG out.

This module renders and does nothing else. It never opens a database — it takes the plain dicts
`research.visual.store.Reader` returns — and it never derives a research value: a leg, a
cascade, a streak or a candle means here exactly what the builder wrote down. That is what lets
a future dashboard reuse it: swap the page composition, keep the reader and these functions.

Four rules the marks obey, because the record they draw obeys them:

**Nothing constant is drawn as if it varied.** `render_indicator` refuses a series whose
provenance is MISSING or whose values never change, and returns the reason instead. On this
database that silently removes regime, OI direction and OI change — three fields that would
otherwise draw a confident flat line across the session.

**Gaps stay gaps.** A stretch with no evaluation is drawn as a hatched band with its own label.
No line is carried across it.

**The entry boundary is a wall.** `render_trade_focus` shades everything after the entry and
labels it, so a chart cannot be read as though the outcome informed the decision.

**A declared bracket is never drawn as a stop.** It is dotted, labelled "declared", and carries
whether the exit ever reached it.

Display thinning — the one place presentation departs from the record, stated explicitly:

* `CANDLE_LIMIT` (700) bars: above it, bodies would be narrower than a line, so the series is
  drawn as a high/low envelope with the close over it. Every bar still contributes; only the
  mark changes.
* Polyline points that land on the same `PIXEL_GRID` (0.5 px) coordinate as their predecessor
  are dropped, because they would paint the same pixel. The shape is identical; the bytes are
  not. Interior extremes are never dropped, so a spike cannot be flattened by thinning.

Neither rule touches persisted data, and neither is ever applied to a number shown as text.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from research.svg import Chart, esc

PRIMARY_TIMEFRAME = "1m"
CANDLE_LIMIT = 700
PIXEL_GRID = 0.5
# how many contracts per side get a chart; the rest are listed rather than drawn
MAX_SERIES_PER_ROLE = 1
# how far a trade close-up reaches either side of the entry
FOCUS_LEAD_MIN = 3
FOCUS_TRAIL_MIN = 6
# above this many accepted decisions, the decision lane switches from one mark per decision to
# a per-minute density with the trade-linked decisions still marked individually. The lane never
# merges with another lane; only its own marks are summarised, and the record keeps every row.
ACCEPTED_MARK_LIMIT = 300

LANE_COLOURS = {
    "market": "var(--ink3)",
    "observation": "var(--heat)",
    "decision": "var(--warn)",
    "execution": "var(--accent)",
}


# ── thinning ─────────────────────────────────────────────────────────────
def thin(points: Sequence[Tuple], project) -> List[Tuple]:
    """Drop points that would paint the pixel their predecessor already painted.

    The first and last point always survive, and so does any point whose projected position
    differs from the one before it, so a one-bar spike is never removed.
    """
    out: List[Tuple] = []
    last: Optional[Tuple[float, float]] = None
    for i, p in enumerate(points):
        x, y = project(p)
        key = (round(x / PIXEL_GRID), round(y / PIXEL_GRID))
        if i == 0 or i == len(points) - 1 or key != last:
            out.append(p)
            last = key
    return out


def thinning_note(n_bars: int, drawn: int) -> str:
    if n_bars <= CANDLE_LIMIT:
        return f"{n_bars} bars, drawn as candles"
    saved = f", {n_bars - drawn} co-located points dropped for display" if drawn < n_bars else ""
    return (f"{n_bars} bars, drawn as a high/low envelope with the close over it{saved} — "
            f"the record is unchanged")


# ── price ────────────────────────────────────────────────────────────────
def render_price(bars: Sequence[Dict], *, title: str, provenance: str,
                 trades: Sequence[Dict] = (), legs: Sequence[Dict] = (),
                 gaps: Sequence[Dict] = (), height: int = 270,
                 mark_trades: bool = True) -> str:
    """OHLC for one series and timeframe, with legs behind and trades on top."""
    if not bars:
        return ""
    t0, t1 = bars[0]["t"], bars[-1]["t"]
    ch = Chart(h=height, title=title, subtitle="")
    ch.set_time_x(t0, t1)
    ch.set_y(min(b["l"] for b in bars), max(b["h"] for b in bars))
    ch.grid(4, lambda v: f"{v:,.1f}")
    ch.time_axis(t0, t1, 30 if (t1 - t0).total_seconds() > 7200 else 15)
    for lg in legs:
        if lg.get("start") and lg.get("end"):
            ch.vspan(lg["start"], lg["end"],
                     "var(--up)" if lg["dir"] == "UP" else "var(--dn)", 0.10)
            ch.parts[-1] = ch.parts[-1].replace(
                "<rect ", f"<rect data-event=\"leg{int(lg['threshold'])}-{lg['leg_id']}\" ")
    _draw_gaps(ch, gaps)
    drawn = len(bars)
    if len(bars) <= CANDLE_LIMIT:
        ch.candles(bars, width_px=max(1.2, min(5.0, 640.0 / max(1, len(bars)))))
    else:
        proj = lambda p: (ch.X(p[0]), ch.y(p[1]))
        hi = thin([(b["t"], b["h"]) for b in bars], proj)
        lo = thin([(b["t"], b["l"]) for b in bars], proj)
        cl = thin([(b["t"], b["c"]) for b in bars], proj)
        drawn = max(len(hi), len(lo), len(cl))
        ch.line(hi, "var(--ink3)", 0.7, 0.45)
        ch.line(lo, "var(--ink3)", 0.7, 0.45)
        ch.line(cl, "var(--accent)", 1.2)
    if mark_trades:
        _mark_trades(ch, trades)
    ch.subtitle = f"{provenance.upper()} · {thinning_note(len(bars), drawn)}"
    return ch.render()


def _draw_gaps(ch: Chart, gaps: Sequence[Dict]) -> None:
    for g in gaps:
        a, b = g.get("start"), g.get("end")
        if not a or not b:
            continue
        x0, x1 = ch.X(a), ch.X(b)
        ch.parts.append(
            f'<rect x="{x0:.1f}" y="{ch.py0}" width="{max(1.0, x1 - x0):.1f}" '
            f'height="{ch.py1 - ch.py0}" fill="url(#gapfill)" opacity="0.85">'
            f'<title>no evaluation persisted here · {esc(str(a)[11:19])}-{esc(str(b)[11:19])} '
            f'· MISSING</title></rect>')


def _mark_trades(ch: Chart, trades: Sequence[Dict]) -> None:
    for tr in trades:
        if tr.get("entry_t") and tr.get("entry_price") is not None:
            ch.marker(tr["entry_t"], tr["entry_price"], "entry", "var(--accent)", 5.0,
                      f"#{tr['trade_id']} ENTRY {tr.get('direction')} @ {tr['entry_price']}")
            ch.parts[-1] = ch.parts[-1].replace(
                "<path ", f"<path data-event=\"t{tr['trade_id']}\" ")
        if tr.get("exit_t") and tr.get("exit_price") is not None:
            col = "var(--up)" if (tr.get("pnl") or 0) > 0 else "var(--dn)"
            ch.marker(tr["exit_t"], tr["exit_price"], "exit", col, 4.5,
                      f"#{tr['trade_id']} EXIT {tr.get('exit_class') or ''} "
                      f"P&L {tr.get('pnl')}")
            ch.parts[-1] = ch.parts[-1].replace(
                "<rect ", f"<rect data-event=\"t{tr['trade_id']}\" ")


def render_volume(bars: Sequence[Dict], *, title: str, height: int = 110) -> str:
    """Per-bar traded volume. Absent where the feed gave none — never zero-filled."""
    pts = [(b["t"], b["volume_delta"]) for b in bars if b.get("volume_delta") is not None]
    if len(pts) < 2:
        return ""
    ch = Chart(h=height, title=title, subtitle="per-bar increment · REAL")
    ch.set_time_x(bars[0]["t"], bars[-1]["t"])
    ch.set_y(0, max(v for _, v in pts))
    ch.grid(2, lambda v: f"{v:,.0f}")
    ch.time_axis(bars[0]["t"], bars[-1]["t"], 30)
    w = max(1.0, min(5.0, 620.0 / max(1, len(pts))))
    for t, v in pts:
        ch.parts.append(
            f'<rect x="{ch.X(t) - w / 2:.1f}" y="{ch.y(v):.1f}" width="{w:.1f}" '
            f'height="{max(0.6, ch.py1 - ch.y(v)):.1f}" fill="var(--heat)" opacity="0.55"/>')
    return ch.render()


# ── indicators ───────────────────────────────────────────────────────────
def render_indicator(rows: Sequence[Dict], field: str, *, title: str,
                     bands: Sequence[float] = (), height: int = 120,
                     marks_only: bool = False) -> Tuple[str, Optional[str]]:
    """(svg, refusal). A constant or MISSING series is refused, with the reason.

    Drawing a flat line for a field that was never populated is the single easiest way for a
    chart to assert something the data does not contain, so the refusal is structural.
    """
    series = [r for r in rows if r["field"] == field]
    if not series:
        return "", f"{field}: not persisted for this session"
    prov = series[0].get("provenance", "missing")
    values = [r["value"] for r in series if r["value"] is not None]
    if prov == "missing":
        return "", (f"{field}: MISSING — {len({r['text_value'] for r in series}) } distinct "
                    f"value(s); not drawn")
    if prov == "mixed":
        # One line cannot honestly carry both. On 2026-09-07 the mode-3 subscription came up
        # at 13:28:53, so bid/ask/oi and everything downstream are measured after it and
        # fabricated before it, in the same column. Drawn as a single series the fabricated
        # two-thirds would read exactly like the measured third.
        return "", (f"{field}: MIXED — measured and fabricated rows in one column; split on "
                    f"research.depth.quote_origin() before drawing it")
    if len(values) < 2:
        return "", f"{field}: fewer than two observations; not drawn"
    if len(set(values)) <= 1:
        return "", f"{field}: constant at {values[0]}; not drawn"
    pts = [(r["t"], r["value"]) for r in series if r["value"] is not None]
    ch = Chart(h=height, title=title, subtitle=prov.upper())
    ch.set_time_x(pts[0][0], pts[-1][0])
    lo, hi = min(values), max(values)
    ch.set_y(lo, hi)
    ch.grid(2, lambda v: f"{v:,.1f}")
    ch.time_axis(pts[0][0], pts[-1][0], 30)
    for lvl in bands:
        if lo <= lvl <= hi:
            ch.hline(lvl, "var(--ink3)", "2 4")
    if marks_only:
        for t, v in pts:
            if v:
                ch.dot(_secs(t), v, 2.0, "var(--warn)", 0.8, f"{t:%H:%M} {v}")
        ch.x = ch.x  # keep the time scale; dots use the same projection
    else:
        ch.line(thin(pts, lambda p: (ch.X(p[0]), ch.y(p[1]))), "var(--heat)", 1.1)
    return ch.render(), None


def _secs(t: _dt.datetime) -> float:
    return t.hour * 3600 + t.minute * 60 + t.second


# ── the decision chain ───────────────────────────────────────────────────
def render_decision_chain(bars: Sequence[Dict], evaluations: Sequence[Dict],
                          accepted: Sequence[Dict], trades: Sequence[Dict],
                          gaps: Sequence[Dict] = (), height: int = 300) -> str:
    """Four lanes, deliberately not merged into one notion of "signal".

    market event      — where price actually went
    strategy observation — that an evaluation happened at all
    strategy decision — what the gate ruled, accepted or rejected
    trade execution   — that an order was actually placed and closed

    A rejected evaluation is not a signal, and an accepted signal is not a trade: on this
    record thousands of the first became none of the second, and eight of the second became
    none of the third.
    """
    if not bars:
        return ""
    t0, t1 = bars[0]["t"], bars[-1]["t"]
    ch = Chart(h=height, title="The decision chain",
               subtitle="market event · strategy observation · strategy decision · "
                        "trade execution — four different things, four lanes")
    dense_note = ""
    ch.set_time_x(t0, t1)
    ch.set_y(min(b["l"] for b in bars), max(b["h"] for b in bars))
    ch.grid(3, lambda v: f"{v:,.0f}")
    ch.time_axis(t0, t1, 30)
    _draw_gaps(ch, gaps)
    ch.line(thin([(b["t"], b["c"]) for b in bars], lambda p: (ch.X(p[0]), ch.y(p[1]))),
            LANE_COLOURS["market"], 1.0, 0.8)

    base = ch.py1 + 2
    lanes = [("observation", 10.0), ("decision", 20.0), ("execution", 30.0)]
    ch.h = int(base + 46)
    ch.mb = 0
    for name, off in lanes:
        y = base + off
        ch.parts.append(f'<text x="{ch.px0 - 6:.1f}" y="{y + 3:.1f}" text-anchor="end" '
                        f'class="ax">{esc(name)}</text>')
        ch.parts.append(f'<line x1="{ch.px0}" y1="{y:.1f}" x2="{ch.px1}" y2="{y:.1f}" '
                        f'stroke="var(--grid)" stroke-width="1"/>')
    for e in evaluations:
        ch.parts.append(
            f'<rect x="{ch.X(e["t"]) - 0.6:.1f}" y="{base + 6:.1f}" width="1.2" height="8" '
            f'fill="{LANE_COLOURS["observation"]}" opacity="{min(1.0, 0.15 + e["n"] / 60.0):.2f}">'
            f'<title>{esc(e["t"].strftime("%H:%M"))} · {e["n"]} evaluations</title></rect>')
    dense = len(accepted) > ACCEPTED_MARK_LIMIT
    if dense:
        per_min: Dict = {}
        for a in accepted:
            per_min[a["t"].replace(second=0)] = per_min.get(a["t"].replace(second=0), 0) + 1
        peak = max(per_min.values())
        for t, n in sorted(per_min.items()):
            h = 2 + 8.0 * n / peak
            ch.parts.append(
                f'<rect x="{ch.X(t) - 1.0:.1f}" y="{base + 24 - h:.1f}" width="2.0" '
                f'height="{h:.1f}" fill="{LANE_COLOURS["decision"]}" opacity="0.8">'
                f'<title>{esc(t.strftime("%H:%M"))} · {n} accepted</title></rect>')
    for a in accepted:
        if dense and not a.get("linked_trade_id"):
            continue
        ch.parts.append(
            f'<circle data-event="e{esc(str(a.get("decision_id") or a.get("row_id")))}" '
            f'cx="{ch.X(a["t"]):.1f}" cy="{base + 20:.1f}" r="3" '
            f'fill="{LANE_COLOURS["decision"]}" stroke="var(--surface)" stroke-width="0.6">'
            f'<title>ACCEPTED {esc(a.get("direction") or "")} {esc(str(a["t"])[11:19])} · '
            f'score {a.get("score_mean") or a.get("score")} · '
            f'confidence {a.get("conf_mean") or a.get("confidence")}</title></circle>')
    for tr in trades:
        if not tr.get("entry_t"):
            continue
        x0 = ch.X(tr["entry_t"])
        x1 = ch.X(tr["exit_t"]) if tr.get("exit_t") else x0 + 2
        col = "var(--up)" if (tr.get("pnl") or 0) > 0 else "var(--dn)"
        ch.parts.append(
            f'<rect data-event="t{tr["trade_id"]}" x="{x0:.1f}" y="{base + 26:.1f}" '
            f'width="{max(2.0, x1 - x0):.1f}" height="8" fill="{col}" opacity="0.8">'
            f'<title>#{tr["trade_id"]} {esc(tr.get("direction") or "")} '
            f'{esc(str(tr.get("entry_ts") or "")[11:19])}-'
            f'{esc(str(tr.get("exit_ts") or "")[11:19])} · P&L {tr.get("pnl")}</title></rect>')
    if dense:
        ch.parts.append(
            f'<text x="{ch.px1:.1f}" y="{base + 44:.1f}" text-anchor="end" class="ax">'
            f'{len(accepted):,} accepted decisions — drawn as a per-minute density; '
            f'trade-linked ones keep their own mark</text>')
    return ch.render()


# ── one trade, with the entry boundary made structural ───────────────────
def render_trade_focus(trade: Dict, bars: Sequence[Dict], *, lead_min: int = FOCUS_LEAD_MIN,
                       trail_min: int = FOCUS_TRAIL_MIN, height: int = 240) -> str:
    """One trade in close-up, with everything after the entry shaded and labelled.

    The boundary is the point of the chart. Left of it is what an observer at the entry second
    could see; right of it is outcome. The declared bracket, where one exists, is dotted and
    labelled as declared — it is not the level that ended the trade, and on this record no exit
    ever reached it.
    """
    e = trade.get("entry_t")
    if not e or not bars:
        return ""
    a = e - _dt.timedelta(minutes=lead_min)
    b = (trade.get("exit_t") or e) + _dt.timedelta(minutes=trail_min)
    win = [x for x in bars if a <= x["t"] <= b]
    if len(win) < 2:
        return ""
    ch = Chart(h=height, title=f"Trade #{trade['trade_id']} · entry boundary",
               subtitle="left of the wall is as-of context · right of it is outcome and never "
                        "informs it")
    ch.set_time_x(win[0]["t"], win[-1]["t"])
    lows = [x["l"] for x in win]
    highs = [x["h"] for x in win]
    extra = [v for v in (trade.get("declared_stop_loss"), trade.get("declared_take_profit"))
             if v is not None]
    ch.set_y(min(lows + extra), max(highs + extra))
    ch.grid(4, lambda v: f"{v:,.1f}")
    ch.time_axis(win[0]["t"], win[-1]["t"], 5)
    # post-entry region
    x_entry = ch.X(e)
    ch.parts.append(
        f'<rect x="{x_entry:.1f}" y="{ch.py0}" width="{max(1.0, ch.px1 - x_entry):.1f}" '
        f'height="{ch.py1 - ch.py0}" fill="var(--ink3)" opacity="0.07"/>')
    ch.parts.append(f'<line x1="{x_entry:.1f}" y1="{ch.py0}" x2="{x_entry:.1f}" '
                    f'y2="{ch.py1}" stroke="var(--accent)" stroke-width="1.6"/>')
    ch.parts.append(f'<text x="{x_entry - 5:.1f}" y="{ch.py0 + 11:.1f}" text-anchor="end" '
                    f'class="ax-em">AS-OF ENTRY</text>')
    ch.parts.append(f'<text x="{x_entry + 5:.1f}" y="{ch.py0 + 11:.1f}" text-anchor="start" '
                    f'class="ax-em">POST-ENTRY OUTCOME</text>')
    ch.candles(win, width_px=max(1.4, min(6.0, 620.0 / max(1, len(win)))))
    for key, label in (("declared_stop_loss", "declared SL"),
                       ("declared_take_profit", "declared TP")):
        v = trade.get(key)
        if v is None:
            continue
        ch.hline(v, "var(--warn)", "2 5")
        reached = trade.get("declared_governed_exit")
        note = "exit reached it" if reached else "exit never reached it"
        ch.text(ch.px1 - 4, ch.y(v) - 4, f"{label} {v:.2f} — {note}", "end", "ax", raw_xy=True)
    _mark_trades(ch, [trade])
    return ch.render()


def gap_defs() -> str:
    """The hatch a gap is painted with, defined once per page."""
    return ('<svg width="0" height="0" style="position:absolute"><defs>'
            '<pattern id="gapfill" width="6" height="6" patternUnits="userSpaceOnUse" '
            'patternTransform="rotate(45)">'
            '<rect width="6" height="6" fill="var(--nodata)"/>'
            '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink3)" stroke-width="1.2" '
            'opacity="0.5"/></pattern></defs></svg>')


# ── activity, state, selection and cascade ───────────────────────────────
def render_activity(rows: Sequence[Dict], *, title: str, gaps: Sequence[Dict] = (),
                    height: int = 130) -> str:
    """How often the strategy looked. Gaps are drawn as gaps, never bridged."""
    pts = [(r["t"], r["value"]) for r in rows if r.get("value") is not None]
    if len(pts) < 2:
        return ""
    ch = Chart(h=height, title=title, subtitle="evaluations per bucket · REAL")
    ch.set_time_x(pts[0][0], pts[-1][0])
    ch.set_y(0, max(v for _, v in pts))
    ch.grid(2)
    ch.time_axis(pts[0][0], pts[-1][0], 30)
    _draw_gaps(ch, gaps)
    # segments are broken at each gap so no line spans a stretch nothing was observed in
    for seg in _split_on_gaps(pts, gaps):
        if len(seg) > 1:
            ch.area(seg, LANE_COLOURS["observation"], 0.16)
            ch.line(seg, LANE_COLOURS["observation"], 1.0)
    return ch.render()


def _split_on_gaps(points: Sequence[Tuple], gaps: Sequence[Dict]) -> List[List[Tuple]]:
    if not gaps:
        return [list(points)]
    edges = sorted((g["start"], g["end"]) for g in gaps if g.get("start") and g.get("end"))
    out: List[List[Tuple]] = [[]]
    for t, v in points:
        if any(a < t < b for a, b in edges):
            if out[-1]:
                out.append([])
            continue
        if out[-1] and any(out[-1][-1][0] <= a and t >= b for a, b in edges):
            out.append([])
        out[-1].append((t, v))
    return [s for s in out if s]


def render_state(states: Sequence[Dict], height: int = 210) -> str:
    """One lane per state type, plus the loss streak as a step line."""
    windows = [r for r in states if r.get("start")
               and r["state_type"] != "consecutive_loss_streak"]
    streak = [r for r in states if r["state_type"] == "consecutive_loss_streak" and r.get("start")]
    if not windows and not streak:
        return ""
    ts = [r["start"] for r in windows + streak] + [r["end"] for r in windows if r.get("end")]
    t0, t1 = min(ts), max(ts)
    lanes = [lt for lt in ("session_type", "confidence_floor", "directional_cooldown")
             if any(r["state_type"] == lt for r in windows)]
    ch = Chart(h=height, title="Strategy state",
               subtitle="session type REAL · cooldown and floor RECONSTRUCTED from the "
                        "rejection text · loss streak RECONSTRUCTED as of each exit")
    ch.set_time_x(t0, t1)
    ch.set_y(0, max(3.0, max([r["numeric_value"] or 0 for r in streak] or [3.0])))
    ch.time_axis(t0, t1, 30)
    lane_h, colour = 16.0, {"session_type": "var(--heat)", "confidence_floor": "var(--warn)",
                            "directional_cooldown": "var(--dn)"}
    for i, lt in enumerate(lanes):
        y = ch.py0 + 6 + i * (lane_h + 5)
        ch.parts.append(f'<text x="{ch.px0 - 6:.1f}" y="{y + 11:.1f}" text-anchor="end" '
                        f'class="ax">{esc(lt.replace("_", " "))}</text>')
        for r in windows:
            if r["state_type"] != lt:
                continue
            x0, x1 = ch.X(r["start"]), ch.X(r.get("end") or r["start"])
            label = r.get("state_value") or ""
            if r.get("numeric_value") is not None:
                label = f"{r['numeric_value']:.0f}% {label}"
            if r.get("side"):
                label = f"{r['side']} {label}"
            ch.parts.append(
                f'<rect data-event="st{r["row_id"]}" x="{x0:.1f}" y="{y:.1f}" '
                f'width="{max(1.5, x1 - x0):.1f}" height="{lane_h}" fill="{colour[lt]}" '
                f'opacity="0.5" stroke="{colour[lt]}" stroke-width="0.6">'
                f'<title>{esc(label)} · {esc(str(r["start"])[11:19])}-'
                f'{esc(str(r.get("end") or "")[11:19])} · {esc(r["provenance"].upper())} · '
                f'{esc(r.get("evidence") or "")}</title></rect>')
    if streak:
        pts: List[Tuple] = []
        for r in streak:
            if pts:
                pts.append((r["start"], pts[-1][1]))
            pts.append((r["start"], r["numeric_value"] or 0))
        pts.append((t1, pts[-1][1]))
        ch.line(pts, "var(--accent)", 1.4)
        ch.text(ch.px0 + 4, ch.py1 - 6, "consecutive loss streak", "start", "ax", raw_xy=True)
    return ch.render()


def render_rejections(buckets: Sequence[Dict], height: int = 180) -> Tuple[str, str]:
    """(svg, legend). Stacked rejection counts, split by what caused them."""
    if not buckets:
        return "", ""
    gates = sorted({b["gate"] for b in buckets})
    by_t: Dict = {}
    for b in buckets:
        by_t.setdefault(b["t"], {}).setdefault(b["gate"], 0)
        by_t[b["t"]][b["gate"]] += b["n"]
    ts = sorted(by_t)
    ch = Chart(h=height, title="Where evaluations died, minute by minute",
               subtitle="stacked rejection counts by gate · REAL")
    ch.set_time_x(ts[0], ts[-1])
    ch.set_y(0, max(sum(v.values()) for v in by_t.values()))
    ch.grid(3)
    ch.time_axis(ts[0], ts[-1], 30)
    palette = ["var(--dn)", "var(--warn)", "var(--heat)", "var(--ink3)", "var(--up)",
               "var(--accent)", "var(--c-invalid)"]
    for t in ts:
        base = 0.0
        for i, g in enumerate(gates):
            v = by_t[t].get(g, 0)
            if not v:
                continue
            ch.parts.append(
                f'<rect x="{ch.X(t) - 1.2:.1f}" y="{ch.y(base + v):.1f}" width="2.4" '
                f'height="{max(0.6, abs(ch.y(base) - ch.y(base + v))):.1f}" '
                f'fill="{palette[i % len(palette)]}" opacity="0.85">'
                f'<title>{esc(t.strftime("%H:%M"))} {esc(g)}: {v}</title></rect>')
            base += v
    legend = " ".join(f'<span><i style="background:{palette[i % len(palette)]}"></i>{esc(g)}</span>'
                      for i, g in enumerate(gates))
    return ch.render(), legend


def render_cascade(trades: Sequence[Dict], height: int = 220) -> str:
    """Spot offered → option transmitted → strategy captured, three bars per trade."""
    rows = [t for t in trades if t.get("option_available") is not None
            or t.get("captured") is not None]
    if not rows:
        return ""
    ch = Chart(h=height, title="Capture cascade",
               subtitle="spot offered → option offered → strategy captured (points) · "
                        "RECONSTRUCTED over a fixed 180s horizon, never from the stored MFE")
    ch.set_x(0, max(1, len(rows)))
    top = max([abs(t.get("spot_available") or 0) for t in rows]
              + [abs(t.get("option_available") or 0) for t in rows]
              + [abs(t.get("captured") or 0) for t in rows] + [1])
    ch.set_y(min(0, min((t.get("captured") or 0) for t in rows)), top)
    ch.grid(4, lambda v: f"{v:,.1f}")
    ch.hline(0, "var(--grid-strong)", "")
    for i, t in enumerate(rows):
        for off, key, col in ((-0.26, "spot_available", "var(--ink3)"),
                              (0.0, "option_available", "var(--heat)"),
                              (0.26, "captured", "var(--up)")):
            v = t.get(key)
            if v is None:
                continue
            c = col if (key != "captured" or v >= 0) else "var(--dn)"
            ch.bar(i + 0.5 + off, 0, v, 7.5, c, 0.92,
                   f"#{t['trade_id']} {key.replace('_', ' ')}: {v}")
            ch.parts[-1] = ch.parts[-1].replace(
                "<rect ", f"<rect data-event=\"t{t['trade_id']}\" ")
    ch.x_axis_labels([(i + 0.5, f"#{t['trade_id']}") for i, t in enumerate(rows)])
    return ch.render()


# ── comparison marks ─────────────────────────────────────────────────────
INSUFFICIENT_LABEL = "INSUFFICIENT"


def render_group_bars(groups: Sequence[Dict], metric: str, *, title: str, subtitle: str,
                      height: int = 210, colour: str = "var(--heat)",
                      fmt=lambda v: f"{v:,.1f}") -> str:
    """One bar per comparison group, for one metric.

    A group whose value was withheld gets a hatched placeholder and its label, never a bar of
    height zero: a missing measurement and a measured zero must not look alike. A group is
    never reordered by size — the order is the record's, so the chart cannot be read as a
    ranking.
    """
    if not groups:
        return ""
    values = []
    for g in groups:
        v = g.get("metrics", {}).get(metric)
        values.append(None if (v is None or v == INSUFFICIENT_LABEL) else float(v))
    if not any(v is not None for v in values):
        return ""
    ch = Chart(h=height, title=title, subtitle=subtitle)
    ch.set_x(0, max(1, len(groups)))
    lo = min([v for v in values if v is not None] + [0.0])
    hi = max([v for v in values if v is not None] + [0.0])
    ch.set_y(lo, hi)
    ch.grid(4, fmt)
    ch.hline(0, "var(--grid-strong)", "")
    width = min(46.0, 620.0 / max(1, len(groups)))
    for i, (g, v) in enumerate(zip(groups, values)):
        x = i + 0.5
        if v is None:
            y0, y1 = ch.y(lo), ch.y(hi)
            ch.parts.append(
                f'<rect x="{ch.x(x) - width / 2:.1f}" y="{min(y0, y1):.1f}" '
                f'width="{width:.1f}" height="{abs(y1 - y0):.1f}" fill="url(#gapfill)" '
                f'opacity="0.7"><title>{esc(g["label"])}: withheld — {g["n"]} row(s), below '
                f'the reporting floor</title></rect>')
            ch.text(ch.x(x), ch.py0 + 12, INSUFFICIENT_LABEL, "middle", "ax", raw_xy=True)
            continue
        col = colour if v >= 0 else "var(--dn)"
        ch.bar(x, 0, v, width, col, 0.85,
               f"{g['label']}: {fmt(v)} · n={g['n']} · {g['sessions_covered']} session(s) · "
               f"{g['provenance'].upper()}")
    ch.x_axis_labels([(i + 0.5, g["label"]) for i, g in enumerate(groups)])
    return ch.render()


def render_group_cascade(groups: Sequence[Dict], *, title: str, subtitle: str,
                         keys: Sequence[Tuple[str, str, str]] = (
                             ("spot_offered_mean", "spot offered", "var(--ink3)"),
                             ("option_offered_mean", "option offered", "var(--heat)"),
                             ("captured_mean", "captured", "var(--up)")),
                         height: int = 220) -> str:
    """Several metrics side by side per group — the cascade shape, applied to comparisons."""
    usable = [g for g in groups
              if any(g.get("metrics", {}).get(k) not in (None, INSUFFICIENT_LABEL)
                     for k, _, _ in keys)]
    if not usable:
        return ""
    ch = Chart(h=height, title=title, subtitle=subtitle)
    ch.set_x(0, max(1, len(usable)))
    vals = [float(g["metrics"][k]) for g in usable for k, _, _ in keys
            if g["metrics"].get(k) not in (None, INSUFFICIENT_LABEL)]
    ch.set_y(min(vals + [0.0]), max(vals + [0.0]))
    ch.grid(4, lambda v: f"{v:,.1f}")
    ch.hline(0, "var(--grid-strong)", "")
    span = 0.62 / max(1, len(keys))
    for i, g in enumerate(usable):
        for j, (k, name, col) in enumerate(keys):
            v = g["metrics"].get(k)
            if v in (None, INSUFFICIENT_LABEL):
                continue
            v = float(v)
            off = (j - (len(keys) - 1) / 2.0) * span
            c = col if v >= 0 else "var(--dn)"
            ch.bar(i + 0.5 + off, 0, v, 16.0, c, 0.88,
                   f"{g['label']} · {name}: {v:,.2f} · n={g['n']}")
    ch.x_axis_labels([(i + 0.5, g["label"]) for i, g in enumerate(usable)])
    legend = " ".join(f'<span><i style="background:{c}"></i>{esc(n)}</span>'
                      for _, n, c in keys)
    return ch.render() + f"<div class='legend'>{legend}</div>"
