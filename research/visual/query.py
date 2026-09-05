"""Cross-session slices over the persisted records — evidence, never conclusions.

Every function here answers "what does the record contain for these groups", and every answer
carries the things that decide whether it can be read at all: how many rows, how many sessions,
what is missing, and what provenance the numbers have. Nothing is pooled that the audit found
un-poolable, nothing is dropped for being thin — a group below `MIN_GROUP_N` reports
`INSUFFICIENT` with its count rather than disappearing — and three dimensions the record cannot
support are returned as explicit refusals rather than quietly omitted.

What this module will never do, by construction rather than by convention:

* no significance test, no p-value, no confidence interval
* no ranking, no "better", no "should", no threshold suggestion
* no causal statement — a group difference is a group difference
* no pooling across sessions where acceptance rates differ by two orders of magnitude

Comparisons are not persisted. A comparison is a question asked of the record, not a fact about
a session; writing it back would give it the standing of a record and let it drift from the rows
it came from. Every function here reads and returns.
"""
from __future__ import annotations

import statistics as _st
from typing import Dict, List, Optional, Sequence

from research.visual.schema import ESTIMATED, MISSING, REAL, RECONSTRUCTED
from research.visual.store import Reader

# a group thinner than this reports INSUFFICIENT instead of a number
MIN_GROUP_N = 5
INSUFFICIENT = "INSUFFICIENT"

# Dimensions the audit found the record cannot support. They are returned, not omitted, so the
# reason survives next to everything that can be compared.
EXCLUDED = {
    "ce_vs_pe_movement": (
        "PE option ticks exist on one session only (297 ticks), so movement evidence is 23 CE "
        "trades against 1 PE trade. A one-sided comparison would read as a finding."),
    "regime": (
        "regime holds a single value on every session in the record; there is nothing to "
        "compare and a chart of it would assert variation that does not exist."),
    "pooled_confidence_band": (
        "accepted evaluations carry 6 distinct confidence values and 5 distinct scores across "
        "the whole database. Banding them would manufacture structure; the cardinality is "
        "reported instead."),
    "cooldown_at_entry": (
        "no trade in the record was entered while a directional cooldown was active — the gate "
        "blocks entry by construction — so there is no traded population to compare."),
}


# ── helpers ──────────────────────────────────────────────────────────────
def _mean(values: Sequence, nd: int = 2):
    vals = [v for v in values if v is not None]
    return round(_st.mean(vals), nd) if vals else None


def cell(label: str, rows: Sequence[Dict], metrics: Dict, *,
         provenance: str, sessions: Optional[Sequence[str]] = None,
         missing_n: int = 0, caveats: Sequence[str] = (),
         n_override: Optional[int] = None, facts: Optional[Dict] = None) -> Dict:
    """One comparison group, with everything needed to judge whether to read it.

    `metrics` are comparison quantities and are withheld below `MIN_GROUP_N`: a mean of two
    trades invites a reading it cannot support. `facts` are recorded properties of the group
    itself — a session's kind, its window, how many evaluations it holds — and are **never**
    withheld, because suppressing a value the record plainly contains would hide data just as
    surely as dropping a thin group would.

    `n_override` exists because some groups are built from per-session summary rows: there the
    evidence is the number of evaluations behind them, not the handful of rows carrying the
    totals, and the sufficiency floor must be applied to the evidence.
    """
    n = len(rows) if n_override is None else n_override
    sess = sorted({r.get("session_id") for r in rows if r.get("session_id")}) \
        if sessions is None else sorted(set(sessions))
    out = {
        "label": label, "n": n, "sessions_covered": len(sess), "sessions": sess,
        "missing_n": missing_n, "provenance": provenance,
        "caveats": list(caveats), "metrics": metrics, "facts": dict(facts or {}),
    }
    if n < MIN_GROUP_N:
        out["metrics"] = {k: INSUFFICIENT for k in metrics}
        out["caveats"] = list(caveats) + [
            f"{n} row(s) — below the {MIN_GROUP_N}-row floor; comparison values withheld rather "
            f"than shown as if they carried weight. Recorded facts are still shown."]
    return out


def result(dimension: str, question: str, groups: Sequence[Dict], *,
           provenance: str, caveats: Sequence[str] = (),
           per_session_only: bool = False, coverage: Optional[Dict] = None) -> Dict:
    return {"dimension": dimension, "question": question, "groups": list(groups),
            "provenance": provenance, "caveats": list(caveats),
            "per_session_only": per_session_only, "coverage": coverage or {},
            "excluded": None}


def excluded(dimension: str) -> Dict:
    return {"dimension": dimension, "question": None, "groups": [], "provenance": MISSING,
            "caveats": [], "per_session_only": False, "coverage": {},
            "excluded": EXCLUDED[dimension]}


def _outcome_metrics(rows: Sequence[Dict]) -> Dict:
    pnl = [r["pnl"] for r in rows if r["pnl"] is not None]
    return {
        "trades": len(rows),
        "wins": sum(1 for r in rows if (r["pnl"] or 0) > 0),
        "losses": sum(1 for r in rows if (r["pnl"] or 0) <= 0),
        "gross_pnl_sum": round(sum(pnl), 2) if pnl else None,
        "gross_pnl_mean": _mean(pnl),
        "hold_sec_mean": _mean([r["hold_sec"] for r in rows], 0),
    }


def _movement_metrics(rows: Sequence[Dict]) -> Dict:
    have = [r for r in rows if r["option_available"] is not None]
    return {
        "with_movement_evidence": len(have),
        "spot_offered_mean": _mean([r["spot_available"] for r in have]),
        "option_offered_mean": _mean([r["option_available"] for r in have]),
        "captured_mean": _mean([r["captured"] for r in have]),
        "transmission_mean": _mean([r["transmission"] for r in have], 3),
    }


GROSS_PNL_CAVEAT = ("all P&L is gross: no brokerage, STT or slippage field exists anywhere in "
                    "the record, so no statement about net profitability follows from it")
MOVEMENT_CAVEAT = ("movement figures are RECONSTRUCTED over a fixed 180s horizon and exist for "
                   "24 of 131 trades, 23 of them CE, across 3 sessions")


# ── 1. session vs session ────────────────────────────────────────────────
def by_session(reader: Reader) -> Dict:
    sessions = reader.sessions()
    trades = reader.all_trades()
    by = {}
    for t in trades:
        by.setdefault(t["session_id"], []).append(t)
    groups = []
    for s in sessions:
        rows = by.get(s["session_id"], [])
        m = _outcome_metrics(rows)
        m.update(_movement_metrics(rows))
        facts = {"kind": s["kind"], "evaluations": s["n_signals"], "ticks": s["n_ticks"],
                 "window": f"{(s['first_ts'] or '—')[11:16]}–{(s['last_ts'] or '—')[11:16]}",
                 "spot_source": s["spot_source"] or "—"}
        groups.append(cell(s["session_id"], rows, m, provenance=REAL, facts=facts,
                           sessions=[s["session_id"]],
                           caveats=([f"{s['kind']}: no market series, so movement and "
                                     f"evaluation columns are MISSING"]
                                    if s["kind"] == "trades-only" else [])))
    return result("session_vs_session",
                  "what each session's record contains, side by side",
                  groups, provenance=REAL,
                  caveats=[GROSS_PNL_CAVEAT,
                           "three kinds of session sit in this table (17 trades-only, 3 coarse, "
                           "3 tick) with different windows and spot sources; rows are comparable "
                           "only within a kind",
                           "the 23 sessions are not consecutive trading days, so this is not a "
                           "time series"])


# ── 2. opening window vs the rest ────────────────────────────────────────
def opening_window(reader: Reader, start: str = "09:15:00", end: str = "09:45:00") -> Dict:
    ev_in = {r["session_id"]: r for r in reader.evaluations_in_window(start, end)}
    ev_out = {r["session_id"]: r for r in reader.evaluations_in_window(end, "23:59:59")}
    mk_in = {r["session_id"]: r for r in reader.candles_in_window("1m", start, end)}
    mk_out = {r["session_id"]: r for r in reader.candles_in_window("1m", end, "23:59:59")}
    trades = reader.all_trades()
    in_window = [t for t in trades if t["entry_ts"] and start <= t["entry_ts"][11:19] < end]

    def side(label, ev, mk):
        rows = [{"session_id": k} for k in ev]
        m = {"sessions_with_evaluations": len(ev),
             "evaluations": sum(r["n"] for r in ev.values()),
             "accepted": sum(r["accepted"] or 0 for r in ev.values()),
             "sessions_with_market": len(mk),
             "market_bars_1m": sum(r["n_bars"] for r in mk.values()),
             "sum_abs_body": round(sum(r["abs_body"] or 0 for r in mk.values()), 2) if mk else None,
             "sum_range": round(sum(r["sum_range"] or 0 for r in mk.values()), 2) if mk else None}
        return cell(label, rows, m, provenance=RECONSTRUCTED,
                    sessions=sorted(set(ev) | set(mk)),
                    n_override=sum(r["n"] for r in ev.values()))

    groups = [side(f"opening window {start[:5]}–{end[:5]}", ev_in, mk_in),
              side(f"rest of session after {end[:5]}", ev_out, mk_out)]
    return result(
        "opening_window_vs_rest",
        "what the record holds inside the blocked opening window against the rest of the day",
        groups, provenance=RECONSTRUCTED,
        caveats=[
            f"no trade in the record was entered in this window — {len(in_window)} of "
            f"{len(trades)}; the earliest entry anywhere is 09:45:17, so nothing about "
            f"traded outcome can be compared here",
            "evaluations exist in the window on 6 sessions, but none of them carries a market "
            "view: before the filter released, the strategy returned before building a "
            "snapshot, so evaluation content in the window is MISSING everywhere",
            "market bars in the window exist on the 3 tick sessions only; the 3 coarse sessions "
            "have no spot series before 09:45, which is MISSING and not zero movement"],
        coverage={"sessions_with_window_market": len(mk_in),
                  "sessions_with_window_evaluations": len(ev_in),
                  "trades_in_window": len(in_window)})


# ── 3. CE vs PE ──────────────────────────────────────────────────────────
def ce_vs_pe_outcome(reader: Reader) -> Dict:
    trades = reader.all_trades()
    groups = []
    for d in ("CE", "PE"):
        rows = [t for t in trades if t["direction"] == d]
        m = _outcome_metrics(rows)
        m["with_market_context"] = sum(1 for r in rows if r["entry_context"])
        groups.append(cell(d, rows, m, provenance=REAL))
    return result("ce_vs_pe_outcome",
                  "recorded outcome by contract side, price fields only",
                  groups, provenance=REAL,
                  caveats=[GROSS_PNL_CAVEAT,
                           "most PE trades come from trades-only sessions, where no market "
                           "context exists at all; the sides are not matched on session kind",
                           "movement evidence is excluded here — see ce_vs_pe_movement"])


def ce_vs_pe_movement(reader: Reader) -> Dict:
    return excluded("ce_vs_pe_movement")


# ── 4. win vs loss ───────────────────────────────────────────────────────
def win_vs_loss_price(reader: Reader) -> Dict:
    trades = reader.all_trades()
    groups = []
    for label, keep in (("win", lambda t: (t["pnl"] or 0) > 0),
                        ("loss", lambda t: (t["pnl"] or 0) <= 0)):
        rows = [t for t in trades if keep(t)]
        m = _outcome_metrics(rows)
        m.update({"score_mean": _mean([r["score"] for r in rows], 1),
                  "confidence_mean": _mean([r["confidence"] for r in rows], 1),
                  "market_quality_mean": _mean([r["market_quality_score"] for r in rows], 1)})
        groups.append(cell(label, rows, m, provenance=REAL))
    return result("win_vs_loss_price",
                  "recorded price-side fields for trades that made money and trades that did not",
                  groups, provenance=REAL,
                  caveats=[GROSS_PNL_CAVEAT,
                           "only trades that were actually taken appear here; evaluations that "
                           "were accepted and never became a trade are not in either group",
                           "win and loss are defined by gross P&L, so a trade whose costs would "
                           "have taken it negative still counts as a win"])


def win_vs_loss_movement(reader: Reader) -> Dict:
    trades = [t for t in reader.all_trades() if t["option_available"] is not None]
    groups = []
    for label, keep in (("win", lambda t: (t["pnl"] or 0) > 0),
                        ("loss", lambda t: (t["pnl"] or 0) <= 0)):
        rows = [t for t in trades if keep(t)]
        groups.append(cell(label, rows, _movement_metrics(rows), provenance=RECONSTRUCTED))
    return result("win_vs_loss_movement",
                  "how much movement was offered and kept, for winners against losers",
                  groups, provenance=RECONSTRUCTED,
                  caveats=[MOVEMENT_CAVEAT,
                           "the 24 trades carrying movement evidence are almost entirely CE and "
                           "come from 3 sessions, so this is not a sample of the strategy"])


# ── 5. accepted vs rejected — per session only ───────────────────────────
def accepted_vs_rejected(reader: Reader, pooled: bool = False) -> Dict:
    if pooled:
        raise ValueError(
            "accepted-vs-rejected must not be pooled across sessions: acceptance rates in this "
            "record range from 7.3% to 0.03%, so a pooled figure would be dominated by one "
            "session. Read the per-session rows instead.")
    rows = reader.evaluation_counts("accepted")
    by = {}
    for r in rows:
        by.setdefault(r["session_id"], {})[int(r["value"] or 0)] = r
    groups = []
    for sid, d in sorted(by.items()):
        acc, rej = d.get(1), d.get(0)
        n_acc = acc["n"] if acc else 0
        n_rej = rej["n"] if rej else 0
        total = n_acc + n_rej
        groups.append(cell(sid, [{"session_id": sid}] * max(1, total),
                           {"accepted": n_acc, "rejected": n_rej,
                            "accept_rate_pct": round(100.0 * n_acc / total, 3) if total else None,
                            "accepted_with_market_view": acc["with_context"] if acc else 0},
                           provenance=REAL, sessions=[sid]))
    return result("accepted_vs_rejected",
                  "how many evaluations each session accepted and rejected",
                  groups, provenance=REAL, per_session_only=True,
                  caveats=["acceptance rate varies by two orders of magnitude between sessions, "
                           "so these rows must not be summed",
                           "every accepted evaluation in the record sits in the 'no floor "
                           "stated' path: comparing acceptance across gate categories is "
                           "tautological, because the gated categories accept nothing by "
                           "construction"])


# ── 6. what caused a rejection ───────────────────────────────────────────
def rejection_cause(reader: Reader) -> Dict:
    rows = reader.evaluation_counts("state_gate", where="accepted=0")
    by_cause: Dict[str, List[Dict]] = {}
    for r in rows:
        by_cause.setdefault(r["value"] or "unclassified", []).append(r)
    groups = []
    for cause, rs in sorted(by_cause.items()):
        groups.append(cell(cause, [{"session_id": r["session_id"]} for r in rs],
                           {"evaluations": sum(r["n"] for r in rs),
                            "sessions": len({r["session_id"] for r in rs})},
                           provenance=RECONSTRUCTED,
                           sessions=[r["session_id"] for r in rs],
                           n_override=sum(r["n"] for r in rs)))
    detail = reader.evaluation_counts("state_detail", where="accepted=0")
    sub = [cell(r0 or "—", [{"session_id": x["session_id"]} for x in rs],
                {"evaluations": sum(x["n"] for x in rs)}, provenance=RECONSTRUCTED,
                sessions=[x["session_id"] for x in rs],
                n_override=sum(x["n"] for x in rs))
           for r0, rs in sorted(
               {d["value"]: [y for y in detail if y["value"] == d["value"]]
                for d in detail if d["value"]}.items())]
    return result("rejection_cause",
                  "whether an evaluation was stopped by a market condition or by the strategy's "
                  "own state",
                  groups + sub, provenance=RECONSTRUCTED,
                  caveats=["the split is RECONSTRUCTED by parsing the rejection text; the "
                           "original gate label is preserved separately and unchanged"])


# ── 7. score and confidence cardinality (not bands) ──────────────────────
def score_confidence_cardinality(reader: Reader) -> Dict:
    trades = reader.all_trades()
    ev = reader.con.execute(
        "SELECT count(DISTINCT score), count(DISTINCT confidence), count(*) "
        "FROM visual_evaluations WHERE accepted=1").fetchone()
    groups = [
        cell("trades", trades,
             {"distinct_score": len({t["score"] for t in trades if t["score"] is not None}),
              "distinct_confidence": len({t["confidence"] for t in trades
                                          if t["confidence"] is not None}),
              "score_values": sorted({t["score"] for t in trades if t["score"] is not None}),
              "confidence_values": sorted({t["confidence"] for t in trades
                                           if t["confidence"] is not None})},
             provenance=REAL),
        cell("accepted evaluations", [{"session_id": None}] * (ev[2] or 0),
             {"distinct_score": ev[0], "distinct_confidence": ev[1], "n": ev[2]},
             provenance=REAL, sessions=[]),
    ]
    return result("score_confidence_cardinality",
                  "how many distinct score and confidence values the record actually holds",
                  groups, provenance=REAL,
                  caveats=["reported as cardinality rather than bands on purpose — see the "
                           "pooled_confidence_band exclusion"])


def pooled_confidence_band(reader: Reader) -> Dict:
    return excluded("pooled_confidence_band")


# ── 8. leg size ──────────────────────────────────────────────────────────
def leg_size(reader: Reader, thresholds: Sequence[float] = (5.0, 10.0, 15.0, 25.0)) -> Dict:
    groups = []
    for thr in thresholds:
        legs = reader.all_legs(thr)
        with_entry = [l for l in legs if l["entries"]]
        groups.append(cell(f"{thr:.0f}pt legs", legs,
                           {"legs": len(legs),
                            "legs_with_a_trade": len(with_entry),
                            "participation_pct": round(100.0 * len(with_entry) / len(legs), 1)
                            if legs else None,
                            "move_mean": _mean([abs(l["move"]) for l in legs]),
                            "dur_min_mean": _mean([l["dur_min"] for l in legs], 1),
                            "aligned_entries": sum(l["aligned"] or 0 for l in legs),
                            "blocked_evaluations": sum(l["blocked"] or 0 for l in legs)},
                           provenance=RECONSTRUCTED))
    return result("leg_size",
                  "how large the market's moves were and how often the strategy was inside one",
                  groups, provenance=RECONSTRUCTED,
                  caveats=["legs exist on the 6 sessions that carry a spot series; the 17 "
                           "trades-only sessions contribute none",
                           "'aligned' is a hindsight label: it records whether an entry sat on "
                           "the leg's side, not whether it could have known"])


# ── 9. session type ──────────────────────────────────────────────────────
def session_type(reader: Reader) -> Dict:
    ev = reader.evaluation_counts("session_type")
    by_type: Dict[str, List[Dict]] = {}
    for r in ev:
        by_type.setdefault(r["value"] or "not recorded", []).append(r)
    groups = []
    trades = reader.all_trades()
    for label, rs in sorted(by_type.items()):
        tr = []
        for t in trades:
            got = ((t.get("state_at_entry") or {}).get("states") or {}).get("session_type") or []
            if got and got[0].get("value") == label:
                tr.append(t)
        m = {"evaluations": sum(r["n"] for r in rs),
             "accepted": sum(r["accepted"] or 0 for r in rs),
             "trades_entered": len(tr)}
        m.update(_outcome_metrics(tr))
        groups.append(cell(label, rs, m, provenance=REAL,
                           sessions=[r["session_id"] for r in rs],
                           n_override=sum(r["n"] for r in rs)))
    not_recorded = sum(1 for t in trades if not (t.get("state_at_entry") or {}).get("states"))
    return result("session_type",
                  "how evaluation, acceptance and trading are distributed across the session's "
                  "own OPEN/MID/CLOSE phases",
                  groups, provenance=REAL,
                  caveats=[f"{not_recorded} of {len(trades)} trades carry no session type: they "
                           f"come from sessions with no evaluation record",
                           "OPEN here is the strategy's own phase (09:20–10:30) and is not the "
                           "09:15–09:45 opening window",
                           GROSS_PNL_CAVEAT],
                  coverage={"trades_without_session_type": not_recorded})


# ── 10. strategy-state conditions ────────────────────────────────────────
def state_at_entry(reader: Reader) -> Dict:
    trades = reader.all_trades()
    by_streak: Dict[str, List[Dict]] = {}
    for t in trades:
        st = ((t.get("state_at_entry") or {}).get("states") or {}).get(
            "consecutive_loss_streak")
        key = f"streak {st[0]['numeric']:.0f}" if st else "not recorded"
        by_streak.setdefault(key, []).append(t)
    groups = [cell(k, rows, _outcome_metrics(rows), provenance=RECONSTRUCTED)
              for k, rows in sorted(by_streak.items())]
    return result("state_at_entry",
                  "what state the strategy was in when each trade was entered",
                  groups, provenance=RECONSTRUCTED,
                  caveats=["the streak is RECONSTRUCTED from closed trades as of each exit, so a "
                           "trade never counts its own outcome",
                           "'not recorded' is not a zero streak: it marks entries with no streak "
                           "observation at that instant — the session's first trade, or a "
                           "session with no evaluation record at all. Reading it as zero would "
                           "be an inference, not a reading",
                           "cooldown is excluded as a trade-level condition — see the "
                           "cooldown_at_entry exclusion",
                           GROSS_PNL_CAVEAT])


def cooldown_at_entry(reader: Reader) -> Dict:
    return excluded("cooldown_at_entry")


def regime(reader: Reader) -> Dict:
    return excluded("regime")


# ── 11. market-quality bands ─────────────────────────────────────────────
def market_quality_bands(reader: Reader) -> Dict:
    trades = reader.all_trades()
    by_grade: Dict[str, List[Dict]] = {}
    for t in trades:
        by_grade.setdefault(t["market_quality_grade"] or "not recorded", []).append(t)
    groups = []
    for grade, rows in sorted(by_grade.items()):
        m = _outcome_metrics(rows)
        m["mq_score_range"] = (
            f"{min(r['market_quality_score'] for r in rows):.0f}–"
            f"{max(r['market_quality_score'] for r in rows):.0f}"
            if all(r["market_quality_score"] is not None for r in rows) else None)
        groups.append(cell(grade, rows, m, provenance=REAL))
    ev = reader.evaluation_counts("market_quality_grade")
    ev_groups = {}
    for r in ev:
        ev_groups.setdefault(r["value"] or "not recorded", 0)
        ev_groups[r["value"] or "not recorded"] += r["n"]
    return result("market_quality_bands",
                  "recorded outcome by the market-quality grade the live system wrote on the "
                  "trade",
                  groups, provenance=REAL,
                  caveats=[GROSS_PNL_CAVEAT,
                           "the grade is the trade's own recorded value, never taken from a "
                           "nearby evaluation",
                           "grade populations are very uneven and each grade spans only a few "
                           "distinct scores"],
                  coverage={"evaluation_grade_counts": ev_groups})


# ── 12. coverage and missingness ─────────────────────────────────────────
def coverage_matrix(reader: Reader) -> Dict:
    rows = reader.all_quality()
    by_field: Dict[str, Dict[str, int]] = {}
    for r in rows:
        by_field.setdefault(r["field"], {}).setdefault(r["state"], 0)
        by_field[r["field"]][r["state"]] += 1
    varying = {f: d for f, d in by_field.items() if len(d) > 1}
    constant = {f: d for f, d in by_field.items() if len(d) == 1}
    groups = [cell(f, [{"session_id": None}] * sum(d.values()), dict(d),
                   provenance=REAL, sessions=[], n_override=sum(d.values()))
              for f, d in sorted(varying.items())]
    return result("coverage_matrix",
                  "which fields the record holds, and how their state differs between sessions",
                  groups, provenance=REAL,
                  caveats=["this is the denominator for every other dimension: a field MISSING "
                           "on a session cannot contribute a comparison from it"],
                  coverage={"fields_tracked": len(by_field),
                            "fields_varying_by_session": len(varying),
                            "fields_constant": {f: list(d)[0] for f, d in constant.items()}})


# ── the registry ─────────────────────────────────────────────────────────
DIMENSIONS = {
    "session_vs_session": by_session,
    "opening_window_vs_rest": opening_window,
    "ce_vs_pe_outcome": ce_vs_pe_outcome,
    "ce_vs_pe_movement": ce_vs_pe_movement,
    "win_vs_loss_price": win_vs_loss_price,
    "win_vs_loss_movement": win_vs_loss_movement,
    "accepted_vs_rejected": accepted_vs_rejected,
    "rejection_cause": rejection_cause,
    "score_confidence_cardinality": score_confidence_cardinality,
    "pooled_confidence_band": pooled_confidence_band,
    "leg_size": leg_size,
    "session_type": session_type,
    "state_at_entry": state_at_entry,
    "cooldown_at_entry": cooldown_at_entry,
    "regime": regime,
    "market_quality_bands": market_quality_bands,
    "coverage_matrix": coverage_matrix,
}


def run_all(reader: Reader) -> Dict[str, Dict]:
    return {name: fn(reader) for name, fn in DIMENSIONS.items()}
