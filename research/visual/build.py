"""Builder: trading database -> persisted visual records.

Reads through `research.db.Book` (read-only) and the existing derivation modules, then writes
the result once. Nothing here invents data. Where a series, a timeframe or a field has no
source, the absence is written down — a coverage row with state MISSING, or a data-quality row
with the reason — and no bar is emitted to stand in for it.

The as-of discipline of `research.candles` carries through: a trade's `entry_context` is
computed from `as_of(entry_time)` and cannot contain a later tick, while post-entry movement is
kept in `post_entry`, named so a chart cannot confuse the two.
"""
from __future__ import annotations

import datetime as _dt
import json
import statistics as _st
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from research import provenance as prov
from research.candles import build as build_bars
from research.db import Book, parse_ts
from research.entries import cascade, trade_profile
from research.execution import quote_quality
from research.market import annotate_participation, legs
from research.prefilters import classify
from research.visual.evaluations import evaluation_rows, gap_rows
from research.visual.positions import declared_brackets, governed_exit
from research.visual.strategy_state import classify_state, describe, state_at, state_rows
from research.visual.schema import (BUILDER_VERSION, ESTIMATED, INDICATOR_TIMEFRAMES,
                                    LEG_THRESHOLDS, MISSING, REAL, RECONSTRUCTED,
                                    SCHEMA_VERSION, TF_SECONDS, TIMEFRAMES)
from research.visual.store import Store, ts_str

CASCADE_HORIZON = 180

# Per-field provenance for a trade overlay. One row mixes states — an executed price is REAL
# while the movement it is compared against is RECONSTRUCTED — so the state is recorded per
# field and never collapsed into a single label for the row.
TRADE_FIELD_PROVENANCE = {
    # persisted by the live system exactly as it stands
    "entry_price": REAL, "exit_price": REAL, "entry_ts": REAL, "exit_ts": REAL,
    "qty": REAL, "pnl": REAL, "pnl_pct": REAL, "hold_sec": REAL,
    "score": REAL, "confidence": REAL, "score_breakdown": REAL,
    "confidence_breakdown": REAL, "entry_reason": REAL, "exit_reason": REAL,
    "mfe_stored": REAL, "mae_stored": REAL, "spot_at_entry": REAL,
    "market_quality_score": REAL, "market_quality_grade": REAL,
    # derived here from real observations, with no model
    "captured": RECONSTRUCTED, "exit_class": RECONSTRUCTED,
    "mfe_in_trade": RECONSTRUCTED, "mae_in_trade": RECONSTRUCTED,
    "spot_available": RECONSTRUCTED, "option_available": RECONSTRUCTED,
    "transmission": RECONSTRUCTED, "capture_of_available": RECONSTRUCTED,
    "capture_of_mfe": RECONSTRUCTED, "entry_context": RECONSTRUCTED,
    "post_entry": RECONSTRUCTED,
    # the level that actually ended the trade was never written down anywhere
    "sl_price": MISSING, "tp_price": MISSING,
}


# indicators_snapshot field -> (provenance registry key, is_numeric)
INDICATOR_FIELDS = {
    "rsi": ("rsi_entry", True),
    "vwap": ("vwap", True),
    "ema9": ("ema9", True),
    "ema21": ("ema21", True),
    "macd_hist": ("macd_hist", True),
    "delta": ("delta", True),
    "volume_spike": ("volume", True),
    "oi_change_pct": ("oi", True),
    "oi_direction": ("oi_direction", False),
    "regime": ("regime", False),
}
# fields taken from the dvf_signals row itself rather than the snapshot
SIGNAL_FIELDS = {
    "score": ("score", "weighted_score"),
    "confidence": ("confidence", "confidence"),
    "market_quality": ("score", "market_quality_score"),
}


def _gaps(points: Sequence[Tuple[_dt.datetime, float]]) -> Tuple[Optional[float], Optional[float]]:
    if len(points) < 2:
        return None, None
    d = [(points[i][0] - points[i - 1][0]).total_seconds() for i in range(1, len(points))]
    return round(_st.median(d), 3), round(max(d), 3)


# ── 1. normalized market series ──────────────────────────────────────────
def normalized_series(book: Book, day: str) -> Dict[str, Dict]:
    """Every price series the session actually carries, named and labelled once.

    `spot` comes from the tick feed when the session has one and from the per-evaluation
    snapshots otherwise; the difference is recorded in `source`, never smoothed over.
    """
    out: Dict[str, Dict] = {}
    spot, src = book.spot(day)
    if spot:
        med, mx = _gaps(spot)
        out["spot"] = {
            "role": "spot", "symbol": None, "points": spot, "quotes": None,
            "source": "ticks" if src == "tick" else "dvf_signals.indicators_snapshot.close",
            "provenance": REAL, "median_gap_sec": med, "max_gap_sec": mx,
        }
    for symbol, n in book.option_symbols(day):
        pts = book.option(symbol, day)
        if not pts:
            continue
        role = "pe" if symbol.upper().endswith("PE") else "ce"
        med, mx = _gaps(pts)
        out[f"{role}:{symbol}"] = {
            "role": role, "symbol": symbol, "points": pts,
            "quotes": book.option_quotes(symbol, day),
            "source": "ticks", "provenance": REAL,
            "median_gap_sec": med, "max_gap_sec": mx,
        }
    return out


def series_rows(session_id: str, series: Dict[str, Dict]) -> List[Dict]:
    rows = []
    for name, meta in series.items():
        pts = meta["points"]
        rows.append({
            "session_id": session_id, "series": name, "role": meta["role"],
            "symbol": meta["symbol"], "source": meta["source"],
            "provenance": meta["provenance"], "n_points": len(pts),
            "first_ts": ts_str(pts[0][0]) if pts else None,
            "last_ts": ts_str(pts[-1][0]) if pts else None,
            "median_gap_sec": meta["median_gap_sec"], "max_gap_sec": meta["max_gap_sec"],
        })
    return rows


# ── 2. candles, per timeframe, with coverage ─────────────────────────────
def _volume_by_bar(quotes: Optional[Sequence[Dict]], bars: Sequence[Dict],
                   seconds: int) -> Dict[_dt.datetime, Dict]:
    """Last cumulative volume and OI inside each bar, plus the per-bar increment.

    The increment of the first bar is left NULL: with no previous cumulative reading there is
    no honest value for it, and 0 would be a fabricated one.
    """
    if not quotes:
        return {}
    by: Dict[_dt.datetime, Dict] = {}
    for b in bars:
        by[b["t"]] = {"volume": None, "oi": None}
    origin = bars[0]["t"].replace(hour=0, minute=0, second=0, microsecond=0)
    for q in quotes:
        k = origin + _dt.timedelta(seconds=(int((q["t"] - origin).total_seconds()) // seconds) * seconds)
        if k not in by:
            continue
        if q.get("volume") is not None:
            by[k]["volume"] = float(q["volume"])
        if q.get("oi") is not None:
            by[k]["oi"] = float(q["oi"])
    prev = None
    for b in bars:
        cur = by[b["t"]]["volume"]
        by[b["t"]]["volume_delta"] = round(cur - prev, 2) if (cur is not None and prev is not None) else None
        if cur is not None:
            prev = cur
    return by


def candle_rows(session_id: str, name: str, meta: Dict) -> Tuple[List[Dict], List[Dict]]:
    pts = meta["points"]
    rows: List[Dict] = []
    cov: List[Dict] = []
    for tf, seconds in TIMEFRAMES:
        bars = build_bars(pts, seconds)
        if not bars:
            cov.append({
                "session_id": session_id, "series": name, "timeframe": tf, "state": MISSING,
                "n_bars": 0, "n_source_points": len(pts), "expected_bars": None,
                "coverage_pct": None, "thin_bars": None, "first_ts": None, "last_ts": None,
                "note": "no source observations for this series",
            })
            continue
        vol = _volume_by_bar(meta.get("quotes"), bars, seconds)
        for b in bars:
            v = vol.get(b["t"], {})
            rows.append({
                "session_id": session_id, "series": name, "timeframe": tf,
                "ts": ts_str(b["t"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                "n": b["n"], "range": b["range"], "body": b["body"],
                "upper_wick": b["upper_wick"], "lower_wick": b["lower_wick"], "dir": b["dir"],
                "body_pct": b["body_pct"], "close_pos": b["close_pos"],
                "velocity_ppm": b["velocity_ppm"],
                "volume": v.get("volume"), "volume_delta": v.get("volume_delta"),
                "oi": v.get("oi"),
                "source": meta["source"], "provenance": RECONSTRUCTED,
            })
        span = (pts[-1][0] - pts[0][0]).total_seconds()
        expected = max(1, int(span // seconds) + 1)
        thin = sum(1 for b in bars if b["n"] <= 1)
        note = None
        if meta["source"].startswith("dvf_signals"):
            note = "built from per-evaluation spot snapshots, not the tick feed"
        elif thin and thin >= 0.5 * len(bars):
            note = f"{thin} of {len(bars)} bars rest on a single observation"
        cov.append({
            "session_id": session_id, "series": name, "timeframe": tf,
            "state": RECONSTRUCTED, "n_bars": len(bars), "n_source_points": len(pts),
            "expected_bars": expected,
            "coverage_pct": round(100.0 * len(bars) / expected, 1),
            "thin_bars": thin, "first_ts": ts_str(bars[0]["t"]),
            "last_ts": ts_str(bars[-1]["t"]), "note": note,
        })
    return rows, cov


# ── 3. indicators ────────────────────────────────────────────────────────
def indicator_rows(book: Book, day: str, session_id: str) -> List[Dict]:
    """Indicator series bucketed to 1m and 5m, per direction.

    The bucket value is the last observation inside the bucket, so a bucket never contains a
    reading from after the time it is drawn at.
    """
    sig = book.signals(day)
    if not sig:
        return []
    rows: List[Dict] = []
    for tf in INDICATOR_TIMEFRAMES:
        seconds = TF_SECONDS[tf]
        buckets: Dict[Tuple, Dict] = defaultdict(dict)
        counts: Dict[Tuple, int] = defaultdict(int)
        origin = sig[0]["t"].replace(hour=0, minute=0, second=0, microsecond=0)
        for s in sig:
            k = origin + _dt.timedelta(
                seconds=(int((s["t"] - origin).total_seconds()) // seconds) * seconds)
            direction = s.get("direction") or "?"
            counts[(k, direction)] += 1
            snap = s.get("indicators_snapshot") or {}
            slot = buckets[(k, direction)]
            for field in INDICATOR_FIELDS:
                v = snap.get(field)
                if v is not None:
                    slot[field] = v
            for field, (_reg, col) in SIGNAL_FIELDS.items():
                v = s.get(col)
                if v is not None:
                    slot[field] = v
        for (k, direction), slot in buckets.items():
            rows.append({
                "session_id": session_id, "timeframe": tf, "ts": ts_str(k),
                "direction": direction, "field": "evaluations",
                "value": float(counts[(k, direction)]), "text_value": None,
                "n": counts[(k, direction)], "source": "dvf_signals", "provenance": REAL,
            })
            for field, value in slot.items():
                if field in INDICATOR_FIELDS:
                    reg, numeric = INDICATOR_FIELDS[field]
                else:
                    reg, numeric = SIGNAL_FIELDS[field][0], True
                state = prov.state(reg)
                num = None
                text = None
                if numeric:
                    try:
                        num = float(value)
                    except (TypeError, ValueError):
                        text = str(value)
                else:
                    text = str(value)
                rows.append({
                    "session_id": session_id, "timeframe": tf, "ts": ts_str(k),
                    "direction": direction, "field": field, "value": num, "text_value": text,
                    "n": counts[(k, direction)], "source": "dvf_signals.indicators_snapshot",
                    "provenance": state if state != REAL else REAL,
                })
    return rows


# ── 4. market legs ───────────────────────────────────────────────────────
def leg_rows(book: Book, day: str, session_id: str, spot: Sequence) -> List[Dict]:
    if not spot:
        return []
    trades = book.trades(day)
    sig = book.signals(day)
    rows = []
    for thr in LEG_THRESHOLDS:
        for i, lg in enumerate(legs(spot, thr)):
            a = annotate_participation(lg, trades, sig)
            rows.append({
                "session_id": session_id, "threshold": thr, "leg_id": i,
                "start_ts": ts_str(a["start"]), "end_ts": ts_str(a["end"]),
                "dur_min": a["dur_min"], "move": a["move"], "dir": a["dir"],
                "vel_ppm": a["vel_ppm"], "mfe": a["mfe"], "mae": a["mae"],
                "hi": a["hi"], "lo": a["lo"], "vol_before": a["vol_before"],
                "vol_during": a["vol_during"], "entries": a["entries"],
                "aligned": a["aligned"], "signals": a["signals"], "blocked": a["blocked"],
                "pnl": a["pnl"], "entry_position_pct": a["entry_position_pct"],
                "trade_ids": json.dumps(a["trade_ids"]),
                "source": "spot series", "provenance": RECONSTRUCTED,
            })
    return rows


# ── 5. trade overlays, with the capture cascade ──────────────────────────
def _match_signal(sig: Sequence[Dict], t: _dt.datetime, direction: Optional[str]) -> Optional[Dict]:
    """The last evaluation at or before the entry — never one from after it."""
    best = None
    for s in sig:
        if s["t"] > t:
            break
        if direction and s.get("direction") and s["direction"] != direction:
            continue
        best = s
    return best


def trade_rows(book: Book, day: str, session_id: str) -> List[Dict]:
    sig = book.signals(day)
    brackets = declared_brackets(book, day)
    states = state_rows(book, day)
    rows = []
    for tr in book.trades(day):
        entry_t = parse_ts(tr["entry_time"]) if tr["entry_time"] else None
        exit_t = parse_ts(tr["exit_time"]) if tr["exit_time"] else None
        row = {
            "session_id": session_id, "trade_id": tr["id"], "symbol": tr["symbol"],
            "direction": tr["direction"], "side": tr["side"], "qty": tr["qty"],
            "entry_ts": ts_str(entry_t), "exit_ts": ts_str(exit_t),
            "entry_price": tr["entry_price"], "exit_price": tr["exit_price"],
            "hold_sec": tr["hold_time_sec"], "pnl": tr["pnl"], "pnl_pct": tr["pnl_pct"],
            "captured": (round(tr["exit_price"] - tr["entry_price"], 2)
                         if tr["exit_price"] is not None and tr["entry_price"] is not None else None),
            "mfe_in_trade": None, "mae_in_trade": None,
            "mfe_stored": tr.get("mfe"), "mae_stored": tr.get("mae"),
            # the operative stop and target — the levels that actually ended the trade — were
            # never persisted by the live system, so they stay absent rather than being
            # reconstructed from config or from the declared bracket below
            "sl_price": None, "tp_price": None,
            "sl_provenance": MISSING, "tp_provenance": MISSING,
            "declared_stop_loss": None, "declared_take_profit": None,
            "declared_stop_distance": None, "declared_target_distance": None,
            "declared_source": None, "declared_provenance": MISSING,
            "declared_governed_exit": None, "declared_reachable_stop": None,
            "field_provenance": None, "state_at_entry": None,
            "score": tr["score"], "confidence": tr["confidence"],
            # recorded on the trade by the live system; absent stays absent
            "market_quality_score": tr.get("market_quality_score"),
            "market_quality_grade": tr.get("market_quality_grade"),
            "score_breakdown": None, "confidence_breakdown": None,
            "entry_reason": tr.get("entry_reason"), "exit_reason": tr.get("exit_reason"),
            "exit_class": ((tr.get("exit_reason") or "").split("|")[0].strip() or None),
            "spot_at_entry": None, "spot_source": None,
            "cascade_horizon_sec": CASCADE_HORIZON,
            "spot_available": None, "option_available": None, "transmission": None,
            "capture_of_available": None, "capture_of_mfe": None,
            "entry_context": None, "post_entry": None,
            "source": "trades", "provenance": REAL,
        }
        if entry_t is not None:
            # as-of the entry second: `state_at` consults nothing that starts after it
            active = state_at(states, entry_t)
            row["state_at_entry"] = json.dumps(
                {"summary": describe(active),
                 "states": {k: [{"value": x["state_value"], "numeric": x["numeric_value"],
                                 "side": x["side"], "provenance": x["provenance"]} for x in v]
                            for k, v in active.items()}},
                default=str, separators=(",", ":"))
            m = _match_signal(sig, entry_t, tr["direction"])
            if m:
                row["score_breakdown"] = json.dumps(m.get("score_breakdown") or {},
                                                    separators=(",", ":"))
                row["confidence_breakdown"] = json.dumps(m.get("confidence_breakdown") or {},
                                                         separators=(",", ":"))
        prof = trade_profile(book, day, tr) if tr["symbol"] and exit_t else None
        if prof:
            c = cascade(prof, CASCADE_HORIZON)
            row.update({
                "mfe_in_trade": prof.get("mfe_in_trade"), "mae_in_trade": prof.get("mae_in_trade"),
                "spot_at_entry": prof.get("spot_at_entry"), "spot_source": prof.get("spot_src"),
                "spot_available": c["spot_avail"], "option_available": c["opt_avail"],
                "transmission": c["transmission"],
                "capture_of_available": c["capture_of_available"],
                "capture_of_mfe": c["capture_of_mfe"],
                "entry_context": json.dumps(prof["before"], default=str, separators=(",", ":")),
                "post_entry": json.dumps(
                    {"option": prof.get("after_option"), "spot": prof.get("after_spot"),
                     "post_exit": {k: v for k, v in prof.items() if k.startswith("post_exit_")}},
                    default=str, separators=(",", ":")),
                "provenance": RECONSTRUCTED,
            })
        br = brackets.get(tr["id"])
        if br:
            gov = governed_exit(tr, br)
            row.update({
                "declared_stop_loss": br["declared_stop_loss"],
                "declared_take_profit": br["declared_take_profit"],
                "declared_stop_distance": br["declared_stop_distance"],
                "declared_target_distance": br["declared_target_distance"],
                "declared_source": br["declared_source"],
                # REAL: the live system wrote these values when the position opened. Whether
                # they governed the exit is recorded beside them, not folded into them.
                "declared_provenance": REAL,
                "declared_governed_exit": None if gov is None else int(gov),
                "declared_reachable_stop": (None if br["declared_reachable_stop"] is None
                                            else int(br["declared_reachable_stop"])),
            })
        fp = dict(TRADE_FIELD_PROVENANCE)
        fp["declared_stop_loss"] = REAL if br else MISSING
        fp["declared_take_profit"] = REAL if br else MISSING
        for f in ("market_quality_score", "market_quality_grade"):
            fp[f] = REAL if row[f] is not None else MISSING
        if not prof:
            for k in ("mfe_in_trade", "mae_in_trade", "spot_available", "option_available",
                      "transmission", "capture_of_available", "capture_of_mfe",
                      "entry_context", "post_entry", "spot_at_entry"):
                fp[k] = MISSING
        row["field_provenance"] = json.dumps(fp, separators=(",", ":"))
        rows.append(row)
    return rows


# ── 5b. strategy state ───────────────────────────────────────────────────
def strategy_state_rows(book: Book, day: str, session_id: str) -> List[Dict]:
    """Persist the state series exactly as `strategy_state` recovered them, provenance intact."""
    rows = []
    for i, r in enumerate(state_rows(book, day)):
        rows.append({
            "session_id": session_id, "row_id": i, "state_type": r["state_type"],
            "state_value": r["state_value"], "numeric_value": r["numeric_value"],
            "side": r["side"], "start_ts": ts_str(r["start"]) if r["start"] else None,
            "end_ts": ts_str(r["end"]) if r["end"] else None, "n_evaluations": r["n"],
            "loss_count": r["loss_count"],
            "remaining_start_min": r["remaining_start_min"],
            "remaining_end_min": r["remaining_end_min"],
            "source": r["source"], "provenance": r["provenance"], "evidence": r["evidence"],
        })
    return rows


# ── 6. signal overlays ───────────────────────────────────────────────────
def signal_rows(book: Book, day: str, session_id: str, bucket_sec: int = 60) -> List[Dict]:
    """Accepted evaluations individually; rejections aggregated per bucket and reason.

    Keeping every one of 30,000 rejections would defeat the purpose of this layer: the point is
    a compact record that answers "what was blocked here, and why" without loading a session's
    whole evaluation stream.
    """
    sig = book.signals(day)
    if not sig:
        return []
    rows: List[Dict] = []
    rid = 0
    origin = sig[0]["t"].replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: Dict[Tuple, Dict] = {}
    for s in sig:
        if s["accepted"]:
            rid += 1
            rows.append({
                "session_id": session_id, "row_id": rid, "kind": "accepted",
                "state_gate": None, "state_detail": None,
                "ts": ts_str(s["t"]), "bucket_sec": None, "direction": s.get("direction"),
                "accepted": 1, "reject_reason": None, "gate": None, "n": 1,
                "score_min": s.get("weighted_score"), "score_max": s.get("weighted_score"),
                "score_mean": s.get("weighted_score"), "conf_min": s.get("confidence"),
                "conf_max": s.get("confidence"), "conf_mean": s.get("confidence"),
                "score_breakdown": json.dumps(s.get("score_breakdown") or {}, separators=(",", ":")),
                "confidence_breakdown": json.dumps(s.get("confidence_breakdown") or {},
                                                   separators=(",", ":")),
                "source": "dvf_signals", "provenance": REAL,
            })
            continue
        k = origin + _dt.timedelta(
            seconds=(int((s["t"] - origin).total_seconds()) // bucket_sec) * bucket_sec)
        gate = classify(s.get("reject_reason"))
        # a rejection caused by the strategy's own state is a different event from one caused by
        # a market condition, even when the live text nests the first inside the second
        kind_, detail = classify_state(s.get("reject_reason"))
        key = (k, s.get("direction") or "?", gate, kind_, detail)
        b = buckets.setdefault(key, {"n": 0, "scores": [], "confs": [],
                                     "reason": (s.get("reject_reason") or "").strip()[:200]})
        b["n"] += 1
        if s.get("weighted_score") is not None:
            b["scores"].append(float(s["weighted_score"]))
        if s.get("confidence") is not None:
            b["confs"].append(float(s["confidence"]))
    for (k, direction, gate, kind_, detail), b in sorted(
            buckets.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], str(kv[0][4]))):
        rid += 1
        sc, cf = b["scores"], b["confs"]
        rows.append({
            "session_id": session_id, "row_id": rid, "kind": "rejected_bucket",
            "ts": ts_str(k), "bucket_sec": bucket_sec, "direction": direction,
            "accepted": 0, "reject_reason": b["reason"], "gate": gate,
            "state_gate": kind_, "state_detail": detail, "n": b["n"],
            "score_min": min(sc) if sc else None, "score_max": max(sc) if sc else None,
            "score_mean": round(_st.mean(sc), 2) if sc else None,
            "conf_min": min(cf) if cf else None, "conf_max": max(cf) if cf else None,
            "conf_mean": round(_st.mean(cf), 2) if cf else None,
            "score_breakdown": None, "confidence_breakdown": None,
            "source": "dvf_signals", "provenance": REAL,
        })
    return rows


# ── 7. data quality ──────────────────────────────────────────────────────
def quality_rows(book: Book, day: str, session_id: str, series: Dict[str, Dict]) -> List[Dict]:
    """The provenance registry, plus what this session actually measures against it."""
    brackets = declared_brackets(book, day)
    trades = book.trades(day)
    n_gov = sum(1 for t in trades if governed_exit(t, brackets.get(t["id"])))
    n_unreach = sum(1 for t in trades
                    if (brackets.get(t["id"]) or {}).get("declared_reachable_stop") is False)
    q = quote_quality(book, day) or {}
    sig = book.signals(day)
    n_sig = len(sig)
    measured: Dict[str, Dict] = {}
    if q.get("n"):
        measured["bid"] = {"n_present": q["n"], "n_total": q["n"],
                           "coverage_pct": q.get("midpoint_exact_pct"),
                           "detail": f"{q.get('midpoint_exact_pct')}% of quotes sit exactly at "
                                     f"the synthetic midpoint"}
        measured["ask"] = dict(measured["bid"])
        measured["oi"] = {"n_present": int(q["n"] * (q.get("oi_populated_pct") or 0) / 100.0),
                          "n_total": q["n"], "coverage_pct": q.get("oi_populated_pct"),
                          "detail": f"{q.get('oi_populated_pct')}% of tick rows carry OI"}
        measured["timestamps"] = {"n_present": q["n"], "n_total": q["n"],
                                  "coverage_pct": round(100.0 - (q.get("collision_pct") or 0), 1),
                                  "detail": f"{q.get('collision_pct')}% same-second collisions"}
    ce = sum(1 for k, m in series.items() if m["role"] == "ce" for _ in [0])
    pe = sum(1 for k, m in series.items() if m["role"] == "pe" for _ in [0])
    pe_pts = sum(len(m["points"]) for m in series.values() if m["role"] == "pe")
    ce_pts = sum(len(m["points"]) for m in series.values() if m["role"] == "ce")
    rows = []
    for field, (state, reason) in prov.REGISTRY.items():
        m = measured.get(field, {})
        rows.append({
            "session_id": session_id, "field": field, "state": state, "reason": reason,
            "n_present": m.get("n_present"), "n_total": m.get("n_total"),
            "coverage_pct": m.get("coverage_pct"), "detail": m.get("detail"),
        })
    n_tr = len(trades)
    n_br = len(brackets)
    for field, state, reason, detail in (
            ("sl_price", MISSING,
             "the operative stop — the level that actually ended a trade — was never persisted; "
             "exits fired from the early-cut and hard-SL rules, whose thresholds live in config",
             f"absent on all {n_tr} trades; not reconstructed from config, and not taken from "
             f"the declared bracket, which governed {n_gov} of {n_br} matched exits"),
            ("tp_price", MISSING,
             "no operative take-profit was persisted per trade", None),
            ("declared_stop_loss", REAL if n_br else MISSING,
             "written by the live system into active_positions when the position opened; "
             "joined on order_id only where symbol, direction, qty, entry price and entry time "
             "all agree",
             f"{n_br} of {n_tr} trades matched; distance is a constant 8.0 points from entry; "
             f"{n_gov} of {n_br} exits reached it; {n_unreach} declared stops sit below zero "
             f"premium and were unreachable"),
            ("declared_take_profit", REAL if n_br else MISSING,
             "same source and join as the declared stop",
             f"{n_br} of {n_tr} trades matched; distance is a constant 16.0 points from entry; "
             f"{n_gov} of {n_br} exits reached it"),
            ("trade_market_quality",
             REAL if any(t.get("market_quality_score") is not None for t in trades)
             else MISSING,
             "market_quality_score and grade as the live system wrote them on the trade row; "
             "never taken from a nearby evaluation",
             f"{sum(1 for t in trades if t.get('market_quality_score') is not None)} of {n_tr} "
             f"trades carry a grade"),
            ("ce_coverage", REAL if ce_pts else MISSING, f"{ce} CE contract series", f"{ce_pts:,} CE ticks"),
            ("pe_coverage", REAL if pe_pts >= 2000 else (ESTIMATED if pe_pts else MISSING),
             f"{pe} PE contract series", f"{pe_pts:,} PE ticks"),
            ("evaluations", REAL if n_sig else MISSING, "dvf_signals rows for this session",
             f"{n_sig:,} evaluations"),
    ) + _state_quality(book, day) + _evaluation_quality(book, day, session_id):
        rows.append({"session_id": session_id, "field": field, "state": state,
                     "reason": reason, "n_present": None, "n_total": None,
                     "coverage_pct": None, "detail": detail})
    return rows


def _evaluation_quality(book: Book, day: str, session_id: str) -> tuple:
    """What the evaluation layer can and cannot say for this session."""
    rows, _ = evaluation_rows(book, day, session_id)
    gaps = gap_rows(book, day, session_id)
    if not rows:
        return (("evaluation_layer", MISSING,
                 "this session persisted no evaluation at all",
                 "no decision record exists; no market evaluation is reconstructed for it"),)
    real_ctx = sum(1 for r in rows if r["context_provenance"] == REAL)
    linked = sum(1 for r in rows if r["posthoc_trade_id"])
    accepted = sum(1 for r in rows if r["accepted"])
    blind = sum(g["seconds"] for g in gaps) / 60.0
    return (
        ("evaluation_layer", REAL,
         "one row per persisted decision_id; decision_id is unique where "
         "(timestamp, direction) is not, so decisions inside one second stay separate",
         f"{len(rows):,} evaluations"),
        ("evaluation_context", REAL if real_ctx else MISSING,
         "the strategy's own indicators_snapshot at that decision — what it was looking at",
         f"{real_ctx:,} of {len(rows):,} carry a market view "
         f"({100.0 * real_ctx / len(rows):.1f}%); the rest were rejected before one was built"),
        ("evaluation_coverage", RECONSTRUCTED if gaps else REAL,
         "stretches with no evaluation are recorded as gaps, never bridged",
         f"{len(gaps)} gap(s) totalling {blind:.0f} min"),
        ("evaluation_trade_link", RECONSTRUCTED if linked else MISSING,
         "trades carry no decision id, so the link is the nearest preceding accepted "
         "evaluation within 2s with a compatible direction",
         f"{linked} of {accepted} accepted evaluations became a trade; "
         f"{accepted - linked} accepted evaluations produced none"),
    )


def _state_quality(book: Book, day: str) -> tuple:
    """Quality rows for the strategy-state series, including the one association worth naming.

    The elevated confidence floor and the three-loss streak are reported side by side with the
    measured delay between them. That is evidence a reader can weigh; it is deliberately not
    written as a `three_loss_lock` state, because the live system never declared one.
    """
    rows = state_rows(book, day)
    by_type: Dict[str, List[Dict]] = {}
    for r in rows:
        by_type.setdefault(r["state_type"], []).append(r)

    floors = sorted({r["numeric_value"] for r in by_type.get("confidence_floor", [])
                     if r["numeric_value"] is not None})
    elevated = [r for r in by_type.get("confidence_floor", []) if (r["numeric_value"] or 0) >= 85]
    streak3 = [r for r in by_type.get("consecutive_loss_streak", [])
               if (r["numeric_value"] or 0) >= 3]
    assoc = "no elevated floor observed in this session"
    if elevated and streak3:
        delay = (elevated[0]["start"] - streak3[0]["start"]).total_seconds() / 60.0
        assoc = (f"the {elevated[0]['numeric_value']:.0f}% floor is first observed "
                 f"{delay:.0f} min after the third consecutive loss closed; reported as an "
                 f"observation, not as a declared lock")
    elif elevated:
        assoc = "an elevated floor is observed with no three-loss streak recorded"

    cd = by_type.get("directional_cooldown", [])
    sides = sorted({r["side"] for r in cd if r["side"]})
    return (
        ("state_session_type", REAL if by_type.get("session_type") else MISSING,
         "written as a column on every evaluation",
         f"{len(by_type.get('session_type', []))} observed windows"),
        ("state_directional_cooldown", RECONSTRUCTED if cd else MISSING,
         "parsed from the rejection text; the side is in the text, not in the direction column",
         (f"{len(cd)} window(s) on {', '.join(sides) or 'no side'}; "
          f"{sum(r['n'] or 0 for r in cd):,} evaluations") if cd
         else "no cooldown rejection in this session"),
        ("state_confidence_floor",
         RECONSTRUCTED if by_type.get("confidence_floor") else MISSING,
         "the floor each evaluation states it was measured against; two code paths write it "
         "and both can be active in the same minute",
         f"floors seen: {', '.join(f'{f:.0f}%' for f in floors) or 'none'}; {assoc}"),
        ("state_consecutive_loss_streak",
         RECONSTRUCTED if by_type.get("consecutive_loss_streak") else MISSING,
         "counted here from closed trades, as of each exit time",
         f"{len(by_type.get('consecutive_loss_streak', []))} step(s); "
         f"maximum {max([r['numeric_value'] for r in by_type.get('consecutive_loss_streak', [])] or [0]):.0f}"),
        ("state_warm_up", MISSING,
         "no evaluation carries a warm-up rejection anywhere in the record",
         "not recoverable; not inferred from session timing"),
        ("state_live_counter", MISSING,
         "bot_state.consecutive_losses exists as a column but the table holds no rows",
         "the live system's own counter was never persisted"),
    )


# ── build one session ────────────────────────────────────────────────────
def build_session(book: Book, day: str, store: Store) -> Dict:
    session_id = day
    series = normalized_series(book, day)
    spot = series.get("spot", {}).get("points", [])
    trades = book.trades(day)
    sig_n = len(book.signals(day))
    tick_n = sum(len(m["points"]) for m in series.values() if m["role"] != "spot")

    candles: List[Dict] = []
    coverage: List[Dict] = []
    for name, meta in series.items():
        c, cov = candle_rows(session_id, name, meta)
        candles += c
        coverage += cov

    evals, blobs = evaluation_rows(book, day, session_id)

    ps = [p for _, p in spot]
    session = {
        "session_id": session_id, "day": day, "kind": book.session_kind(day),
        "spot_source": series.get("spot", {}).get("source"),
        "spot_provenance": series.get("spot", {}).get("provenance"),
        "first_ts": ts_str(spot[0][0]) if spot else None,
        "last_ts": ts_str(spot[-1][0]) if spot else None,
        "n_ticks": tick_n, "n_signals": sig_n, "n_trades": len(trades),
        "n_symbols": sum(1 for m in series.values() if m["role"] != "spot"),
        "n_ce_symbols": sum(1 for m in series.values() if m["role"] == "ce"),
        "n_pe_symbols": sum(1 for m in series.values() if m["role"] == "pe"),
        "spot_open": ps[0] if ps else None, "spot_high": max(ps) if ps else None,
        "spot_low": min(ps) if ps else None, "spot_close": ps[-1] if ps else None,
        "spot_range": round(max(ps) - min(ps), 2) if ps else None,
        "spot_net": round(ps[-1] - ps[0], 2) if ps else None,
        "pnl": round(sum(t["pnl"] for t in trades if t["pnl"] is not None), 2) if trades else None,
        "schema_version": SCHEMA_VERSION, "builder_version": BUILDER_VERSION,
        "source_db": book.path,
        "source_rowcounts": json.dumps({"ticks": tick_n, "signals": sig_n, "trades": len(trades)}),
        "built_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    rows = {
        "visual_sessions": [session],
        "visual_series": series_rows(session_id, series),
        "visual_candles": candles,
        "visual_timeframe_coverage": coverage,
        "visual_indicators": indicator_rows(book, day, session_id),
        "visual_market_legs": leg_rows(book, day, session_id, spot),
        "visual_trade_overlays": trade_rows(book, day, session_id),
        "visual_strategy_state": strategy_state_rows(book, day, session_id),
        "visual_evaluations": evals,
        "visual_evaluation_blobs": blobs,
        "visual_evaluation_gaps": gap_rows(book, day, session_id),
        "visual_signal_overlays": signal_rows(book, day, session_id),
        "visual_data_quality": quality_rows(book, day, session_id, series),
    }
    counts = store.write_session(session_id, rows)
    counts["_kind"] = session["kind"]
    return counts


def build_all(book: Book, store: Store, days: Optional[Sequence[str]] = None,
              progress=None) -> Dict[str, Dict]:
    """Build every session the database carries. Sessions are discovered, never hardcoded."""
    targets = list(days) if days else [s["day"] for s in book.sessions()]
    out: Dict[str, Dict] = {}
    for d in targets:
        if progress:
            progress(d)
        out[d] = build_session(book, d, store)
    return out
