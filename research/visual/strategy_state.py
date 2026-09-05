"""What state the strategy was in at a given instant — only where the source supports it.

Four states can be recovered from this database and one cannot. The distinction was measured
before it was written down, and it decides the provenance of every row this module produces:

* `session_type` is a **column** on every evaluation (OPEN / MID / CLOSE, changing at 10:30 and
  14:30). The live system wrote it, so it is REAL.
* `directional_cooldown` exists only inside the rejection text — `"CE blocked (2 losses, 11min
  cooldown)"`. The side is in the text, not in the `direction` column, which is empty on all of
  those rows. Parsed, therefore RECONSTRUCTED.
* `confidence_floor` is likewise stated by the text: `"Low confidence 82% < 85%"`. Two distinct
  code paths write it — one carries a direction and no market-quality grade, the other carries a
  grade and no direction — and they run side by side within the same minute, so the floor is
  recorded per path rather than as one global setting.
* `consecutive_loss_streak` is counted here from closed trades. It is strictly as-of: a trade
  contributes only from its **exit** time onward, so the streak at `t` never knows an outcome
  that had not happened at `t`.
* `warm_up` has no support at all — no evaluation in the record carries a warm-up reason — so it
  is written as MISSING rather than guessed from timing.

What is deliberately NOT written: a "3-loss lock" state. The elevated 85% floor does appear only
after a three-loss streak in all three sessions that show it, but the live system never declared
such a state, the delay between the two varies, and the ordinary floor keeps appearing alongside
the elevated one. The two series are recorded separately and their association is reported as
evidence in the data-quality rows; asserting the lock as a state would be an inference dressed
as a record.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import Book, parse_ts
from research.visual.schema import MISSING, REAL, RECONSTRUCTED

COOLDOWN_RE = re.compile(r"\((\d+)\s+losses?,\s*(\d+)\s*min\s+cooldown\)", re.I)
SIDE_RE = re.compile(r"\b(CE|PE)\s+blocked\b", re.I)
FLOOR_RE = re.compile(r"Low confidence\s+(\d+)%\s*<\s*(\d+)%(?:\s*\(MQ\s*([A-Z+]+)\))?", re.I)

# a rejection is either a market/pre-filter condition or the strategy's own state; the two are
# different events and are never merged into one bucket
STATE_GATES = ("directional_cooldown", "confidence_floor")


def parse_cooldown(reason: Optional[str]) -> Optional[Dict]:
    """`"CE signal blocked: CE blocked (2 losses, 11min cooldown)"` -> side, losses, remaining."""
    if not reason:
        return None
    m = COOLDOWN_RE.search(reason)
    if not m:
        return None
    side = SIDE_RE.search(reason)
    return {"side": side.group(1).upper() if side else None,
            "losses": int(m.group(1)), "remaining_min": int(m.group(2))}


def parse_floor(reason: Optional[str]) -> Optional[Dict]:
    """`"Low confidence 82% < 85%"` -> the value measured and the floor it was measured against."""
    if not reason:
        return None
    m = FLOOR_RE.search(reason)
    if not m:
        return None
    return {"confidence": int(m.group(1)), "floor": int(m.group(2)),
            "mq_grade": m.group(3), "path": "market_quality" if m.group(3) else "directional"}


def classify_state(reason: Optional[str]) -> Tuple[str, Optional[str]]:
    """('strategy_state'|'market', detail) — which kind of thing rejected this evaluation.

    A cooldown rejection is not a directional-signal rejection even though the live text nests
    one inside the other, so it is reported under its own name rather than being counted as a
    generic CE/PE block.
    """
    cd = parse_cooldown(reason)
    if cd:
        return "strategy_state", "directional_cooldown"
    fl = parse_floor(reason)
    if fl:
        return "strategy_state", "confidence_floor"
    return "market", None


def _windows(points: Sequence[Tuple[_dt.datetime, Dict]], key,
             max_gap_sec: int = 120) -> List[Dict]:
    """Group observations that share `key` into windows, one stream per key.

    Streams are separated before windowing because two of these states genuinely run side by
    side — the two confidence paths appear within the same minute — and interleaving them in one
    chronological pass would chop each into hundreds of fragments that mean nothing.

    Inside a stream a gap longer than `max_gap_sec` closes the window: the record then says the
    state was observed here and here, not that it continued through a stretch nothing was seen
    in.
    """
    streams: Dict = {}
    for t, obs in points:
        streams.setdefault(key(obs), []).append((t, obs))
    out: List[Dict] = []
    for k, pts in streams.items():
        cur: Optional[Dict] = None
        for t, obs in pts:
            if cur is None or (t - cur["last"]).total_seconds() > max_gap_sec:
                if cur:
                    out.append(cur)
                cur = {"key": k, "start": t, "last": t, "n": 1,
                       "first_obs": obs, "last_obs": obs}
            else:
                cur["last"] = t
                cur["n"] += 1
                cur["last_obs"] = obs
        if cur:
            out.append(cur)
    out.sort(key=lambda w: w["start"])
    return out


# ── the five state series ────────────────────────────────────────────────
def session_type_windows(book: Book, day: str) -> List[Dict]:
    pts = [(s["t"], {"v": s.get("session_type")}) for s in book.signals(day)
           if s.get("session_type")]
    return [{"state_type": "session_type", "state_value": w["key"], "numeric_value": None,
             "side": None, "start": w["start"], "end": w["last"], "n": w["n"],
             "loss_count": None, "remaining_start_min": None, "remaining_end_min": None,
             "source": "dvf_signals.session_type", "provenance": REAL,
             "evidence": "column written on every evaluation"}
            for w in _windows(pts, lambda o: o["v"], max_gap_sec=600)]


def cooldown_windows(book: Book, day: str) -> List[Dict]:
    pts = []
    for s in book.signals(day):
        cd = parse_cooldown(s.get("reject_reason"))
        if cd:
            pts.append((s["t"], cd))
    out = []
    for w in _windows(pts, lambda o: (o["side"], o["losses"])):
        side, losses = w["key"]
        out.append({"state_type": "directional_cooldown", "state_value": "active",
                    "numeric_value": None, "side": side, "start": w["start"], "end": w["last"],
                    "n": w["n"], "loss_count": losses,
                    "remaining_start_min": w["first_obs"]["remaining_min"],
                    "remaining_end_min": w["last_obs"]["remaining_min"],
                    "source": "dvf_signals.reject_reason (text)", "provenance": RECONSTRUCTED,
                    "evidence": f"{w['n']} evaluations rejected with "
                                f"'{side} blocked ({losses} losses, N min cooldown)'"})
    return out


def confidence_floor_windows(book: Book, day: str) -> List[Dict]:
    pts = []
    for s in book.signals(day):
        fl = parse_floor(s.get("reject_reason"))
        if fl:
            pts.append((s["t"], fl))
    out = []
    for w in _windows(pts, lambda o: (o["floor"], o["path"])):
        floor, path = w["key"]
        out.append({"state_type": "confidence_floor", "state_value": path,
                    "numeric_value": float(floor), "side": None,
                    "start": w["start"], "end": w["last"], "n": w["n"],
                    "loss_count": None, "remaining_start_min": None, "remaining_end_min": None,
                    "source": "dvf_signals.reject_reason (text)", "provenance": RECONSTRUCTED,
                    "evidence": f"{w['n']} evaluations measured against {floor}% on the "
                                f"{path} path"})
    return out


def loss_streak_points(book: Book, day: str) -> List[Dict]:
    """Consecutive-loss count, as of each trade's exit. Strictly causal.

    A trade changes the streak from the moment it **closes**, never from the moment it opened:
    at 11:00 the strategy could not know how a position still open would end.
    """
    trades = [t for t in book.trades(day) if t.get("exit_time")]
    trades.sort(key=lambda t: str(t["exit_time"]))
    out = []
    streak = 0
    for t in trades:
        won = (t.get("pnl") or 0) > 0
        streak = 0 if won else streak + 1
        x = parse_ts(t["exit_time"])
        out.append({"state_type": "consecutive_loss_streak", "state_value": str(streak),
                    "numeric_value": float(streak), "side": t.get("direction"),
                    "start": x, "end": None, "n": None, "loss_count": streak,
                    "remaining_start_min": None, "remaining_end_min": None,
                    "source": "trades.exit_time + trades.pnl", "provenance": RECONSTRUCTED,
                    "evidence": f"trade #{t['id']} closed {'in profit' if won else 'at a loss'} "
                                f"at {x:%H:%M:%S}"})
    return out


def warm_up_row(book: Book, day: str) -> List[Dict]:
    """Recorded so the absence is explicit rather than merely unmentioned."""
    return [{"state_type": "warm_up", "state_value": None, "numeric_value": None, "side": None,
             "start": None, "end": None, "n": 0, "loss_count": None,
             "remaining_start_min": None, "remaining_end_min": None,
             "source": "dvf_signals.reject_reason", "provenance": MISSING,
             "evidence": "no evaluation in this session carries a warm-up rejection; the state "
                         "is not recoverable and is not inferred from session timing"}]


def state_rows(book: Book, day: str) -> List[Dict]:
    rows: List[Dict] = []
    for fn in (session_type_windows, cooldown_windows, confidence_floor_windows,
               loss_streak_points, warm_up_row):
        rows += fn(book, day)
    rows.sort(key=lambda r: (r["start"] or _dt.datetime.min, r["state_type"]))
    return rows


def state_at(rows: Sequence[Dict], t: _dt.datetime) -> Dict[str, List[Dict]]:
    """The states active at `t`, from persisted rows. Nothing later than `t` is consulted.

    A state type maps to a **list**, because more than one can genuinely be active at once: the
    two confidence paths run side by side, and a cooldown can hold on one side while the other
    is free. Collapsing them to one value per type would invent a single global state the system
    never had.

    Window states are active while `start <= t <= end`; the loss streak is a step function and
    takes the value of the most recent point at or before `t`.
    """
    out: Dict[str, List[Dict]] = {}
    latest_streak: Optional[Dict] = None
    for r in rows:
        start = r.get("start", r.get("start_ts"))
        end = r.get("end", r.get("end_ts"))
        start = parse_ts(start) if isinstance(start, str) else start
        end = parse_ts(end) if isinstance(end, str) else end
        if start is None or start > t:
            continue
        st = r["state_type"]
        if st == "consecutive_loss_streak":
            if latest_streak is None or start >= latest_streak["_at"]:
                latest_streak = dict(r, _at=start)
            continue
        if end is not None and t > end:
            continue
        out.setdefault(st, []).append(dict(r, _at=start))
    if latest_streak is not None:
        out["consecutive_loss_streak"] = [latest_streak]
    return out


def describe(active: Dict[str, List[Dict]]) -> str:
    """One line for a viewer: what was in force, with each value's provenance kept visible."""
    if not active:
        return "no state recorded at this instant"
    parts = []
    for st in ("session_type", "consecutive_loss_streak", "directional_cooldown",
               "confidence_floor"):
        for r in active.get(st, []):
            if st == "session_type":
                parts.append(f"session {r['state_value']}")
            elif st == "consecutive_loss_streak":
                parts.append(f"loss streak {r['numeric_value']:.0f}")
            elif st == "directional_cooldown":
                parts.append(f"{r['side']} cooldown active")
            else:
                parts.append(f"floor {r['numeric_value']:.0f}% ({r['state_value']})")
    return " · ".join(parts)
