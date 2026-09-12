"""Null/token/sequence/book-sanity checks on a tick.

Deliberately a classifier, not a gate: it returns a verdict, it never drops a tick
itself. Wiring a REJECTED verdict into anything that actually withholds a tick from a
trading decision is a behaviour change and gets decided separately from adding the
check itself.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ValidationResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)


class SequenceTracker:
    """Per-token last-seen sequence number.

    Sequence numbers are only comparable within one WebSocket connection's stream for
    one token — call reset() when a connection drops so the old high-water mark doesn't
    reject every tick on the new connection as 'out of order'.
    """

    def __init__(self):
        self._last_sequence: Dict[str, int] = {}

    def check(self, token: str, sequence: Optional[int]) -> Optional[str]:
        """Returns a reason string if non-monotonic, else records `sequence` and
        returns None. A missing sequence field is not an error — not every broker's
        wire format carries one."""
        if sequence is None:
            return None
        last = self._last_sequence.get(token)
        if last is not None and sequence <= last:
            return f"sequence {sequence} <= last seen {last} for token {token}"
        self._last_sequence[token] = sequence
        return None

    def reset(self, token: Optional[str] = None) -> None:
        if token is None:
            self._last_sequence.clear()
        else:
            self._last_sequence.pop(token, None)


def validate_tick(tick: Dict, sequence_tracker: Optional[SequenceTracker] = None) -> ValidationResult:
    reasons: List[str] = []

    token = tick.get("token")
    if not token:
        reasons.append("missing token")

    ltp = tick.get("ltp")
    if ltp is None:
        reasons.append("missing ltp")
    elif ltp <= 0:
        reasons.append(f"non-positive ltp {ltp}")

    bid, ask = tick.get("best_bid_price"), tick.get("best_ask_price")
    if bid is not None and ask is not None and bid > ask:
        reasons.append(f"crossed book: bid {bid} > ask {ask}")

    if sequence_tracker is not None and token:
        seq_reason = sequence_tracker.check(token, tick.get("sequence"))
        if seq_reason:
            reasons.append(seq_reason)

    return ValidationResult(ok=not reasons, reasons=reasons)
