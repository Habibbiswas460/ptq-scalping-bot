"""Page composition over the persisted visual records.

This module arranges; `research.visual.charts` draws; `research.visual.store.Reader` supplies.
It never opens the trading database and never derives a research value — every number on the
page was written by the builder and is read back unchanged. A future dashboard replaces this
file and keeps the other two.

The page is built so the four things a reader must keep apart stay apart: a market event, the
strategy observing, the strategy deciding, and an order actually being placed. They get their
own lanes, their own marks and their own words.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from research.render import Page, Raw, esc, kv, table
from research.visual import charts
from research.visual.schema import TF_LABELS
from research.visual.store import DB_PATH, Reader, parse_ts

OUT_DIR = os.path.join("claude_code", "research_output", "visual")
DEFAULT_TF = charts.PRIMARY_TIMEFRAME
# a page above this is a sign the renderer is dumping rather than presenting; the budget is
# asserted by the test suite so it cannot drift unnoticed
PAGE_BUDGET_KB = 1200

TABS_CSS = """
.tfbar{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}
.tfbar button{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
 background:var(--surface);color:var(--ink2);border:1px solid var(--rule);
 padding:4px 10px;cursor:pointer}
.tfbar button[aria-selected="true"]{border-color:var(--accent);color:var(--accent);
 background:var(--accent-soft)}
.tfpane[hidden]{display:none}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2);margin:0 0 10px}
.legend i{display:inline-block;width:9px;height:9px;margin-right:5px;vertical-align:baseline}
.casc{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:8px 0 4px}
.casc .card{border:1px solid var(--rule);background:var(--surface);padding:10px 12px}
.casc .card.is-sel{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.casc h4{margin:0 0 6px;font-size:.9rem}
.drill{border:1px solid var(--rule);background:var(--surface);padding:10px 12px;margin:0 0 10px}
.drill.is-sel{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.drill h4{margin:0 0 6px;font-size:.92rem}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 22px}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--ink2)}
.refused{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;color:var(--ink3);
 border-left:2px solid var(--rule);padding:3px 0 3px 9px;margin:3px 0}
tr.is-sel td{background:var(--sel)}
svg [data-event].is-sel{stroke:var(--accent);stroke-width:2.4}
"""

TABS_JS = """
(function(){
  document.querySelectorAll('[data-tabs]').forEach(function(bar){
    var group=bar.getAttribute('data-tabs');
    bar.addEventListener('click',function(e){
      var b=e.target.closest('button[data-tf]'); if(!b){return;}
      var tf=b.getAttribute('data-tf');
      bar.querySelectorAll('button[data-tf]').forEach(function(x){
        x.setAttribute('aria-selected', x===b ? 'true':'false');});
      document.querySelectorAll('.tfpane[data-group="'+group+'"]').forEach(function(p){
        p.hidden = p.getAttribute('data-tf')!==tf;});
    });
  });
})();
"""


def chip(label: str, state: str) -> Raw:
    return Raw(f'<span class="chip c-{esc(state)}">{esc(label)}</span>')


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _gaps_dt(gaps: Sequence[Dict]) -> List[Dict]:
    return [dict(g, start=parse_ts(g["start_ts"]), end=parse_ts(g["end_ts"])) for g in gaps]


def _declared(t: Dict) -> Raw:
    """The bracket the position recorded at open — REAL, and shown with whether it governed."""
    if t.get("declared_stop_loss") is None and t.get("declared_take_profit") is None:
        return chip("not recorded for this trade", "missing")
    gov = t.get("declared_governed_exit")
    note = ("exit reached it" if gov else "exit did not reach it") if gov is not None else ""
    unreachable = ("" if t.get("declared_reachable_stop") in (None, 1)
                   else " · declared stop is below zero premium and was unreachable")
    return Raw(f"{chip('REAL', 'real')} SL {_fmt(t['declared_stop_loss'])} / "
               f"TP {_fmt(t['declared_take_profit'])} "
               f"<span class='mono'>({note}{unreachable})</span>")


def _linked_eval(link: Optional[Dict]) -> Raw:
    if not link or not link.get("linked"):
        return chip("no accepted evaluation matched", "missing")
    e = link["linked"]
    return Raw(f"{chip('RECONSTRUCTED', 'reconstructed')} {esc(e['ts'][11:])} "
               f"(+{link['link_delta_sec']:.0f}s) · score {_fmt(e['score'], 0)} · "
               f"confidence {_fmt(e['confidence'], 0)} "
               f"<span class='mono'>({esc(link['link_method'])})</span>")


def _tab_group(name: str, panes: Dict[str, str], default: str = DEFAULT_TF) -> str:
    have = [tf for tf in TF_LABELS if tf in panes]
    if not have:
        return "<p class='mono'>no timeframe persisted</p>"
    sel = default if default in have else have[0]
    bar = "".join(f'<button data-tf="{tf}" aria-selected="{str(tf == sel).lower()}">{tf}</button>'
                  for tf in have)
    body = "".join(f'<div class="tfpane" data-group="{name}" data-tf="{tf}"'
                   f'{"" if tf == sel else " hidden"}>{panes[tf]}</div>' for tf in have)
    return f'<div class="tfbar" data-tabs="{name}">{bar}</div>{body}'


# ── the page ─────────────────────────────────────────────────────────────
def session_page(reader: Reader, session_id: str) -> Page:
    s = reader.session(session_id)
    if not s:
        raise KeyError(f"no visual record for {session_id}")
    series = reader.series(session_id)
    trades = reader.trades(session_id)
    quality = reader.quality(session_id)
    coverage = reader.coverage(session_id)
    legs10 = reader.legs(session_id, 10.0)
    sig = reader.signals(session_id)
    states = reader.strategy_state(session_id)
    gaps = _gaps_dt(reader.evaluation_gaps(session_id))

    spot_name = next((r["series"] for r in series if r["role"] == "spot"), None)
    ce_names = [r["series"] for r in series if r["role"] == "ce"][:charts.MAX_SERIES_PER_ROLE]
    pe_names = [r["series"] for r in series if r["role"] == "pe"][:charts.MAX_SERIES_PER_ROLE]

    page = Page(
        title=f"PTQ visual record · {session_id}",
        h1=f"Visual record · {session_id}",
        standfirst=(
            "One session's decision chain, drawn from persisted records only. A market event, "
            "the strategy observing, the strategy deciding and an order being placed are four "
            "different things here and are never collapsed into one."),
        meta=[("kind", s["kind"]), ("spot source", s["spot_source"] or "—"),
              ("window", f"{(s['first_ts'] or '—')[11:]}–{(s['last_ts'] or '—')[11:]}"),
              ("ticks", f"{s['n_ticks']:,}"), ("evaluations", f"{s['n_signals']:,}"),
              ("trades", s["n_trades"]), ("P&L", _fmt(s["pnl"])),
              ("schema", f"v{s['schema_version']} · builder {s['builder_version']}"),
              ("built", s["built_at"])])

    # 01 session and series
    chips = " ".join(chip(q["field"], q["state"]) for q in quality
                     if q["field"] in ("spot", "option_ltp", "volume", "oi", "bid", "delta",
                                       "rsi_entry", "sl_price", "declared_stop_loss",
                                       "pe_coverage", "costs"))
    page.add("Session and series",
             f"<style>{TABS_CSS}</style>{charts.gap_defs()}"
             + kv([("session kind", s["kind"]),
                   ("spot", f"{s['spot_open']} → {s['spot_close']} "
                            f"(range {_fmt(s['spot_range'])}, net {_fmt(s['spot_net'])})"
                            if s["spot_open"] is not None else "no spot series"),
                   ("contracts", f"{s['n_ce_symbols']} CE · {s['n_pe_symbols']} PE"),
                   ("price series persisted", len(series))])
             + f"<p>{chips}</p>"
             + table(["series", "role", "source", "provenance", "points", "first", "last",
                      "median gap s", "max gap s"],
                     [[r["series"], r["role"], r["source"], r["provenance"], f"{r['n_points']:,}",
                       (r["first_ts"] or "")[11:], (r["last_ts"] or "")[11:],
                       _fmt(r["median_gap_sec"], 2), _fmt(r["max_gap_sec"], 1)] for r in series],
                     num_cols=(4, 7, 8)))

    # 02 the decision chain
    chain = ""
    if spot_name:
        bars = reader.candles(session_id, spot_name, DEFAULT_TF)
        acts = [r for r in reader.indicators(session_id, DEFAULT_TF)
                if r["field"] == "evaluations"]
        acc = [x for x in sig if x["kind"] == "accepted"]
        # mark which accepted decisions became a trade, so a dense session still shows those
        linked_ts = {t["entry_ts"][:19] for t in trades if t.get("entry_ts")}
        acc = [dict(a, linked_trade_id=(a["ts"][:19] in linked_ts)) for a in acc]
        chain = charts.render_decision_chain(bars, acts, acc, trades, gaps)
    page.add("The decision chain",
             "<p>Top lane is the market. Below it, in order: that the strategy <b>observed</b> "
             "(an evaluation happened at all), that it <b>decided</b> (a gate accepted or "
             "rejected), and that an order was <b>executed</b>. Hatched bands are stretches "
             "with no evaluation persisted — nothing is drawn across them. Click any mark to "
             "follow the same event through the rest of the page; Esc clears.</p>"
             + (chain or "<p class='mono'>no market series for this session</p>"))

    # 03 market and strategy by timeframe
    panes: Dict[str, str] = {}
    refusals: List[str] = []
    for tf in TF_LABELS:
        blocks: List[str] = []
        if spot_name:
            bars = reader.candles(session_id, spot_name, tf)
            blocks.append(charts.render_price(
                bars, title=f"Spot · {tf}", provenance="reconstructed",
                trades=trades, legs=legs10, gaps=gaps, height=270, mark_trades=False))
        for name, lab in [(n, "CE") for n in ce_names] + [(n, "PE") for n in pe_names]:
            bars = reader.candles(session_id, name, tf)
            symbol = name.split(":", 1)[1]
            tr = [t for t in trades if t["symbol"] == symbol]
            blocks.append(charts.render_price(
                bars, title=f"{lab} · {symbol} · {tf}", provenance="reconstructed",
                trades=tr, gaps=(), height=250))
            if tf == DEFAULT_TF:
                # volume is drawn on the primary timeframe only: at 10s it costs more bytes
                # than every price chart combined and says the same thing. Every bucket stays
                # queryable through the reader.
                blocks.append(charts.render_volume(bars, title=f"{lab} volume · {tf}"))
        if tf == DEFAULT_TF:
            # indicator panels are drawn on the primary timeframe only; the 5m buckets are
            # persisted and queryable, they are simply not duplicated into the page
            ind = reader.indicators(session_id, tf)
            blocks.append(charts.render_activity(
                [r for r in ind if r["field"] == "evaluations"],
                title=f"Strategy activity · {tf}", gaps=gaps))
            for field, ttl, band in (("rsi", "RSI", (30.0, 70.0)), ("vwap", "VWAP", ()),
                                     ("ema9", "EMA9", ()), ("ema21", "EMA21", ()),
                                     ("macd_hist", "MACD histogram", (0.0,)),
                                     ("delta", "Delta", ()), ("score", "Score", ()),
                                     ("confidence", "Confidence", ()),
                                     ("market_quality", "Market quality", ()),
                                     ("volume_spike", "Volume spike", ()),
                                     ("regime", "Regime", ()),
                                     ("oi_change_pct", "OI change", ()),
                                     ("oi_direction", "OI direction", ())):
                svg, refused = charts.render_indicator(
                    ind, field, title=f"{ttl} · {tf}", bands=band,
                    marks_only=(field == "volume_spike"))
                if svg:
                    blocks.append(svg)
                elif refused:
                    refusals.append(refused)
        if any("<svg" in b for b in blocks):
            panes[tf] = "".join(b for b in blocks if b)
    if panes:
        market_body = (
            "<p>Shaded bands are 10-point market legs; triangles and squares on the option are "
            "entries and exits. Bar buckets are exactly the ones the causal builder persisted — "
            "nothing is re-aggregated here.</p>"
            + (f"<div class='refused'>Not drawn, because drawing them would assert something "
               f"the record does not contain: {esc('; '.join(sorted(set(refusals))))}</div>"
               if refusals else "")
            + _tab_group("tf", panes))
    else:
        market_body = (f"<p>This session carries no market series — "
                       f"{chip('no candles', 'missing')} at every timeframe. Its trades below "
                       "are real and preserved; the market context around them was never "
                       "recorded, and no timeframe is offered here rather than drawing one "
                       "from nothing.</p>")
    page.add("Market and strategy, by timeframe", market_body)

    # 04 strategy state
    st_rows = [[r["state_type"], r["state_value"] or "—", _fmt(r["numeric_value"], 0),
                r["side"] or "—", (r["start_ts"] or "")[11:] or "—",
                (r["end_ts"] or "")[11:] or "—", _fmt(r["n_evaluations"]),
                r["provenance"].upper(), r["evidence"] or ""] for r in states]
    missing_states = [r for r in states if r["provenance"] == "missing"]
    page.add("Strategy state",
             "<p>What the strategy was in the middle of at a given instant. Session type is "
             "REAL; the cooldown and confidence floor exist only inside the rejection text and "
             "are RECONSTRUCTED from it; the loss streak is counted from closed trades as of "
             "each exit, so it never knows how a still-open position ended. No "
             "<code>three_loss_lock</code> state is recorded — the live system never declared "
             "one.</p>"
             + (charts.render_state(states) or "<p class='mono'>no state recovered</p>")
             + (f"<div class='flag note'><h4>Not recoverable</h4><p>"
                + "; ".join(esc(r["state_type"]) + " — " + esc(r["evidence"] or "")
                            for r in missing_states) + "</p></div>" if missing_states else "")
             + table(["state", "value", "number", "side", "from", "to", "evaluations",
                      "provenance", "evidence"], st_rows, num_cols=(2, 6)))

    # 05 the as-of evaluation layer
    n_eval = reader.con.execute(
        "SELECT count(*), sum(context_provenance='real'), sum(accepted) "
        "FROM visual_evaluations WHERE session_id=?", (session_id,)).fetchone()
    if n_eval and n_eval[0]:
        total, with_view, accepted_n = n_eval[0], n_eval[1] or 0, n_eval[2] or 0
        eval_body = (
            "<p>One row per decision the live system recorded, keyed by its "
            "<code>decision_id</code> — unique where the timestamp is not, so two decisions in "
            "one second stay two rows. An as-of lookup cuts the record in SQL, and the trade an "
            "evaluation became is held in <code>posthoc_</code> columns no as-of answer "
            "returns.</p>"
            + kv([("evaluations persisted", f"{total:,}"),
                  ("carried a market view",
                   f"{with_view:,} ({100.0 * with_view / total:.1f}%) — the rest were rejected "
                   f"before one was built"),
                  ("accepted", f"{accepted_n:,}"),
                  ("blind stretches",
                   f"{len(gaps)} gap(s), {sum(g['seconds'] for g in gaps) / 60:.0f} min")]))
        if gaps:
            eval_body += table(
                ["from", "to", "seconds", "provenance", "what this means"],
                [[(g["start_ts"] or "")[11:], (g["end_ts"] or "")[11:], _fmt(g["seconds"], 0),
                  g["provenance"].upper(), g["reason"]] for g in gaps], num_cols=(2,))
    else:
        eval_body = (f"<p>{chip('no evaluation record', 'missing')} This session persisted no "
                     "decision at all, so no market evaluation is reconstructed for it. Its "
                     "trades below remain real.</p>")
    page.add("What the strategy knew, instant by instant", eval_body)

    # 06 capture cascade
    cards = "".join(
        f"<div class='card' data-event='t{t['trade_id']}'>"
        f"<h4>#{t['trade_id']} · {esc(t['direction'] or '')} · "
        f"{'WIN' if (t['pnl'] or 0) > 0 else 'LOSS'}</h4>"
        + kv([("spot offered (3m)", _fmt(t["spot_available"])),
              ("option offered (3m)", _fmt(t["option_available"])),
              ("captured", _fmt(t["captured"])),
              ("transmission", _fmt(t["transmission"], 3)),
              ("capture of offered", _fmt(t["capture_of_available"], 3)),
              ("MFE in trade", _fmt(t["mfe_in_trade"]))])
        + "</div>"
        for t in trades if t["option_available"] is not None)
    page.add("Capture cascade",
             "<p>What the market offered, what the option transmitted, what the strategy kept. "
             "The gaps localise the problem: a small option bar under a large spot bar is "
             "transmission; a small captured bar under a large option bar is holding or "
             "exit.</p>"
             + (charts.render_cascade(trades)
                or "<p class='mono'>no trade carries a cascade for this session</p>")
             + f"<div class='casc'>{cards}</div>")

    # 07 trade drill-down, with the entry boundary
    focus_series = {}
    for t in trades:
        if not t.get("symbol"):
            continue
        name = next((r["series"] for r in series
                     if r["symbol"] == t["symbol"]), None)
        if name:
            focus_series.setdefault(name, reader.candles(session_id, name, "10s"))
    links = {t["trade_id"]: reader.evaluations_for_trade(session_id, t["trade_id"])
             for t in trades}
    rows = []
    attrs = {}
    for i, t in enumerate(trades):
        attrs[i] = f"data-event='t{t['trade_id']}'"
        rows.append([t["trade_id"], (t["entry_ts"] or "")[11:], (t["exit_ts"] or "")[11:],
                     t["direction"], t["symbol"], _fmt(t["entry_price"]), _fmt(t["exit_price"]),
                     _fmt(t["captured"]), _fmt(t["pnl"]), t["hold_sec"], t["score"],
                     t["confidence"], t["exit_class"]])
    drill = []
    for t in trades:
        name = next((r["series"] for r in series if r["symbol"] == t.get("symbol")), None)
        focus = charts.render_trade_focus(t, focus_series.get(name, [])) if name else ""
        drill.append(
            f"<div class='drill' data-event='t{t['trade_id']}'>"
            f"<h4>#{t['trade_id']} · {esc(t['symbol'] or '')} · {esc(t['direction'] or '')} · "
            f"{esc((t['entry_ts'] or '')[11:])} → {esc((t['exit_ts'] or '')[11:])}</h4>"
            + focus
            + "<div class='split'>"
            + kv([("entry context (as-of entry)", "causal — nothing after the entry second"),
                  ("spot momentum 1m", _fmt((t["entry_context"] or {}).get("spot_mom_1m"))),
                  ("option momentum 1m", _fmt((t["entry_context"] or {}).get("opt_mom_1m"))),
                  ("bar direction", (t["entry_context"] or {}).get("bar_dir") or "—"),
                  ("bar close position", _fmt((t["entry_context"] or {}).get("bar_close_pos"), 3)),
                  ("score / confidence", f"{t['score']} / {t['confidence']}"),
                  ("state at entry (as-of)",
                   (t.get("state_at_entry") or {}).get("summary") or "not recorded"),
                  ("linked evaluation", _linked_eval(links.get(t["trade_id"])))])
            + kv([("after entry (uncensored)", "post-entry layer — never used for entry logic"),
                  ("option MFE 180s",
                   _fmt(((t["post_entry"] or {}).get("option") or {}).get("mfe_180"))),
                  ("option MAE 180s",
                   _fmt(((t["post_entry"] or {}).get("option") or {}).get("mae_180"))),
                  ("MFE inside the trade", _fmt(t["mfe_in_trade"])),
                  ("operative stop / target",
                   Raw(f"{chip('SL MISSING', 'missing')} "
                       f"{chip('TP MISSING', 'missing')}")),
                  ("declared bracket", _declared(t)),
                  ("exit", t["exit_reason"] or "—")])
            + "</div></div>")
    page.add("Trade drill-down",
             table(["#", "entry", "exit", "dir", "symbol", "entry px", "exit px", "captured",
                    "P&L", "hold s", "score", "conf", "exit class"], rows,
                   num_cols=(5, 6, 7, 8, 9, 10, 11), row_attrs=attrs)
             + "<p>Each close-up puts a wall at the entry second: left of it is what an observer "
               "could see, right of it is outcome. The <b>operative</b> stop and target are "
               "MISSING — the live system never wrote them per trade. The <b>declared</b> "
               "bracket it did write is dotted and labelled, together with whether the exit ever "
               "reached it. On this record none did.</p>"
             + "".join(drill))

    # 08 selection
    acc = [x for x in sig if x["kind"] == "accepted"]
    rej_svg, legend = charts.render_rejections(
        [x for x in sig if x["kind"] == "rejected_bucket"])
    page.add("Selection — what was blocked, and where",
             rej_svg + (f"<div class='legend'>{legend}</div>" if legend else "")
             + table(["time", "dir", "score", "confidence"],
                     [[(a["ts"] or "")[11:], a["direction"], _fmt(a["score_mean"], 0),
                       _fmt(a["conf_mean"], 0)] for a in acc], num_cols=(2, 3))
             + f"<p class='mono'>{len(acc)} accepted evaluations · "
               f"{sum(x['n'] for x in sig if x['kind'] == 'rejected_bucket'):,} rejections in "
               f"{len([x for x in sig if x['kind'] == 'rejected_bucket']):,} persisted buckets · "
               f"of those rejections "
               f"{sum(x['n'] for x in sig if x.get('state_gate') == 'strategy_state'):,} were "
               f"caused by the strategy's own state rather than by a market condition</p>")

    # 09 coverage and quality
    page.add("Coverage and data quality",
             table(["series", "timeframe", "state", "bars", "expected", "coverage %",
                    "thin bars", "note"],
                   [[c["series"], c["timeframe"], c["state"], _fmt(c["n_bars"]),
                     _fmt(c["expected_bars"]), _fmt(c["coverage_pct"], 1), _fmt(c["thin_bars"]),
                     c["note"] or ""] for c in coverage], num_cols=(3, 4, 5, 6))
             + table(["field", "state", "coverage %", "reason", "measured"],
                     [[q["field"], q["state"].upper(), _fmt(q["coverage_pct"], 1), q["reason"],
                       q["detail"] or ""] for q in quality], num_cols=(2,)))

    # 10 the record itself
    page.add("What is persisted",
             "<p>Everything above is read back through "
             "<code>research.visual.store.Reader</code> and drawn by "
             "<code>research.visual.charts</code>. A dashboard added later replaces this page "
             "and keeps both — there is no second data model.</p>"
             + kv([("reader", "research.visual.store.Reader"),
                   ("renderer", "research.visual.charts"),
                   ("session", session_id),
                   ("display thinning",
                    f"candles up to {charts.CANDLE_LIMIT} bars, then a high/low envelope with "
                    f"the close; polyline points sharing a {charts.PIXEL_GRID}px cell are "
                    f"dropped; volume and indicator panels are drawn on the {DEFAULT_TF} "
                    f"timeframe only, and a trade close-up spans "
                    f"{charts.FOCUS_LEAD_MIN}m before to {charts.FOCUS_TRAIL_MIN}m after. "
                    f"Every other bucket stays queryable through the reader, and no persisted "
                    f"record is touched."),
                   ("legs", f"{len(reader.legs(session_id)):,} rows"),
                   ("trade overlays", f"{len(trades):,} rows"),
                   ("strategy state", f"{len(states):,} rows"),
                   ("evaluation gaps", f"{len(gaps):,} rows")])
             + f"<script>{TABS_JS}</script>")
    return page


def write_session(reader: Reader, session_id: str, out_dir: str = OUT_DIR) -> str:
    return session_page(reader, session_id).write(os.path.join(out_dir, f"{session_id}.html"))


def write_index(reader: Reader, out_dir: str = OUT_DIR) -> str:
    ss = reader.sessions()
    page = Page(
        title="PTQ visual records",
        h1="Visual records",
        standfirst="Every session the database carries, preserved in one structure. Sessions "
                   "are discovered from the data, so a new one appears here as soon as it has "
                   "been built.",
        meta=[("sessions", len(ss)), ("store", DB_PATH)])
    rows = [[f"<a href='{s['session_id']}.html'>{s['session_id']}</a>", s["kind"],
             s["spot_source"] or "—", f"{s['n_ticks']:,}", f"{s['n_signals']:,}",
             s["n_trades"], _fmt(s["pnl"]), _fmt(s["spot_range"]), s["built_at"]] for s in ss]
    html = ("<div class='scroller'><table><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in ("session", "kind", "spot source", "ticks",
                                                "evaluations", "trades", "P&L", "spot range",
                                                "built"))
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "</tbody></table></div>")
    page.add("Sessions", html)
    return page.write(os.path.join(out_dir, "index.html"))
