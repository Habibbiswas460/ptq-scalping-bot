"""The as-of evaluation layer: one persisted row per decision the strategy actually made.

The question this answers is "at time T, what did the strategy know and what decision context
did it have" — and the honest answer is only ever built from the row the live system wrote at
T. Three properties make that structural rather than a matter of care:

**One row per `decision_id`.** The live system can write two evaluations inside the same second,
and `(timestamp, direction)` is not unique — on a full session roughly 30,000 evaluations occupy
only about 16,000 distinct timestamp/direction pairs. Distinct decisions are kept distinct;
nothing is merged because it shares a second, still less a minute.

**No aggregation across time.** Every field on a row comes from that one source row. The market
context is the strategy's *own* `indicators_snapshot` — what it was looking at when it decided —
so it cannot contain a later observation. The only field computed from other rows is the loss
streak, and that counts trades by their **exit** time, so it can never include an outcome that
had not happened yet.

**Post-hoc knowledge is quarantined.** Which trade an evaluation turned into is knowledge from
after the instant. Those columns are prefixed `posthoc_` and are excluded from every as-of
answer, the same way post-entry excursions are kept out of entry context.

Where the source has nothing, the record says so: 9.4% of evaluations carry no snapshot at all
(the strategy returned at a pre-scoring gate before building one), and stretches longer than a
minute with no evaluation are written down as explicit gaps rather than covered by extending the
last row forward.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import Book, parse_ts
from research.prefilters import classify
from research.visual.schema import (EVALUATION_GAP_SEC, MISSING, REAL, RECONSTRUCTED)
from research.visual.strategy_state import classify_state, parse_cooldown, parse_floor

# a trade is linked to the accepted evaluation that precedes it by no more than this
TRADE_LINK_WINDOW_SEC = 2.0
# columns that carry knowledge from after the instant and never travel with an as-of answer
POSTHOC_FIELDS = ("posthoc_trade_id", "posthoc_link_method", "posthoc_link_delta_sec")


def blob_id(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _canonical(value) -> Optional[str]:
    if value is None or value == "" or value == {}:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


class _Blobs:
    """Content-addressed store for the repeated payloads.

    Across the whole database there are 23 distinct score breakdowns and 42 confidence
    breakdowns behind 180,005 evaluations. Referencing them keeps every evaluation's context
    complete while storing each distinct payload once.
    """

    def __init__(self) -> None:
        self.rows: Dict[str, Dict] = {}

    def ref(self, kind: str, value, provenance: str = REAL) -> Optional[str]:
        payload = _canonical(value)
        if payload is None:
            return None
        bid = blob_id(payload)
        row = self.rows.get(bid)
        if row is None:
            self.rows[bid] = {"blob_id": bid, "kind": kind, "payload": payload,
                              "n_uses": 1, "provenance": provenance}
        else:
            row["n_uses"] += 1
        return bid


def _loss_streak_series(book: Book, day: str) -> List[Tuple[_dt.datetime, int]]:
    """(exit time, streak after that exit). Causal by construction: a trade counts only once
    it has closed."""
    trades = [t for t in book.trades(day) if t.get("exit_time")]
    trades.sort(key=lambda t: str(t["exit_time"]))
    out: List[Tuple[_dt.datetime, int]] = []
    streak = 0
    for t in trades:
        streak = 0 if (t.get("pnl") or 0) > 0 else streak + 1
        out.append((parse_ts(t["exit_time"]), streak))
    return out


def _streak_at(series: Sequence[Tuple[_dt.datetime, int]], t: _dt.datetime) -> float:
    v = 0
    for x, s in series:
        if x > t:
            break
        v = s
    return float(v)


def _trade_links(book: Book, day: str, signals: Sequence[Dict]) -> Dict[str, Dict]:
    """decision_id -> the trade that followed it, matched one-to-one and never assumed.

    `trades` carries no decision id, so the link is RECONSTRUCTED: the nearest preceding
    accepted evaluation within two seconds whose direction does not contradict the trade. Every
    accepted evaluation that never became a trade simply stays unlinked — on this record eight
    of them do, and inventing a link for them would misstate what the strategy did.
    """
    accepted = [s for s in signals if s.get("accepted")]
    out: Dict[str, Dict] = {}
    used = set()
    for tr in sorted(book.trades(day), key=lambda t: str(t.get("entry_time"))):
        if not tr.get("entry_time"):
            continue
        e = parse_ts(tr["entry_time"])
        best = None
        for s in accepted:
            if s["decision_id"] in used:
                continue
            if s.get("direction") and tr.get("direction") and s["direction"] != tr["direction"]:
                continue
            d = (e - s["t"]).total_seconds()
            if 0 <= d <= TRADE_LINK_WINDOW_SEC and (best is None or d < best[0]):
                best = (d, s)
        if best:
            used.add(best[1]["decision_id"])
            out[best[1]["decision_id"]] = {
                "posthoc_trade_id": tr["id"],
                "posthoc_link_method": f"nearest accepted evaluation within "
                                       f"{TRADE_LINK_WINDOW_SEC:.0f}s, direction-compatible",
                "posthoc_link_delta_sec": best[0]}
    return out


def evaluation_rows(book: Book, day: str, session_id: str) -> Tuple[List[Dict], List[Dict]]:
    """(evaluation rows, blob rows). One evaluation row per persisted decision."""
    signals = book.signals(day)
    if not signals:
        return [], []
    blobs = _Blobs()
    streaks = _loss_streak_series(book, day)
    links = _trade_links(book, day, signals)
    rows: List[Dict] = []
    for seq, s in enumerate(signals):
        reason = s.get("reject_reason")
        fl = parse_floor(reason) or {}
        cd = parse_cooldown(reason) or {}
        kind_, detail = classify_state(reason)
        snap = s.get("indicators_snapshot") or {}
        # a snapshot object exists on more rows than actually carry a market view: on the
        # pre-scoring rejections every field inside it is null. The blob is still stored, but
        # the row is marked MISSING, because "an empty envelope was written" is not knowledge.
        has_view = any(v is not None for v in snap.values()) if isinstance(snap, dict) else False
        ctx = blobs.ref("indicators_snapshot", snap,
                        REAL if has_view else MISSING)
        row = {
            "session_id": session_id, "decision_id": s["decision_id"], "seq": seq,
            "ts": s["t"].strftime("%Y-%m-%d %H:%M:%S"),
            "direction": s.get("direction") or None,
            "strategy_name": s.get("strategy_name"),
            "accepted": int(bool(s.get("accepted"))),
            "score": s.get("weighted_score"), "confidence": s.get("confidence"),
            "market_quality_score": s.get("market_quality_score"),
            "market_quality_grade": s.get("market_quality_grade"),
            "gate": classify(reason), "state_gate": kind_, "state_detail": detail,
            "reject_reason_id": blobs.ref("reject_reason", reason),
            "floor_value": float(fl["floor"]) if fl else None,
            "floor_path": fl.get("path"),
            "floor_confidence": float(fl["confidence"]) if fl else None,
            "cooldown_side": cd.get("side"),
            "cooldown_losses": cd.get("losses"),
            "cooldown_remaining_min": (float(cd["remaining_min"]) if cd else None),
            "session_type": s.get("session_type"),
            "loss_streak": _streak_at(streaks, s["t"]),
            "context_id": ctx,
            "score_breakdown_id": blobs.ref("score_breakdown", s.get("score_breakdown")),
            "confidence_breakdown_id": blobs.ref("confidence_breakdown",
                                                 s.get("confidence_breakdown")),
            # the strategy either had a market view here or it did not; absence is recorded
            "context_provenance": REAL if has_view else MISSING,
            "posthoc_trade_id": None, "posthoc_link_method": None,
            "posthoc_link_delta_sec": None,
            "source": "dvf_signals", "provenance": REAL,
        }
        row.update(links.get(s["decision_id"], {}))
        rows.append(row)
    blob_rows = [dict(b, session_id=session_id) for b in blobs.rows.values()]
    return rows, blob_rows


def gap_rows(book: Book, day: str, session_id: str,
             threshold_sec: int = EVALUATION_GAP_SEC) -> List[Dict]:
    """Stretches inside the session where no evaluation exists at all."""
    signals = book.signals(day)
    out: List[Dict] = []
    for i in range(1, len(signals)):
        a, b = signals[i - 1]["t"], signals[i]["t"]
        gap = (b - a).total_seconds()
        if gap > threshold_sec:
            out.append({
                "session_id": session_id, "gap_id": len(out),
                "start_ts": a.strftime("%Y-%m-%d %H:%M:%S"),
                "end_ts": b.strftime("%Y-%m-%d %H:%M:%S"),
                "seconds": gap, "provenance": MISSING,
                "reason": "no evaluation was persisted in this stretch; an as-of lookup here "
                          "has no decision to report and does not carry the previous one "
                          "forward",
            })
    return out


def as_of(rows: Sequence[Dict], t: _dt.datetime,
          direction: Optional[str] = None) -> Optional[Dict]:
    """The last evaluation at or before `t`, with post-hoc columns removed.

    Nothing after `t` is consulted and nothing from after `t` is returned — the trade an
    evaluation eventually became is not part of what was known at `t`.
    """
    best = None
    for r in rows:
        ts = r["ts"] if isinstance(r["ts"], _dt.datetime) else parse_ts(r["ts"])
        if ts > t:
            continue
        if direction and r.get("direction") and r["direction"] != direction:
            continue
        if best is None or (ts, r["seq"]) >= (best[0], best[1]["seq"]):
            best = (ts, r)
    if best is None:
        return None
    return {k: v for k, v in best[1].items() if k not in POSTHOC_FIELDS}
