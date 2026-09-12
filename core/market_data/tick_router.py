"""Per-token dispatch: send a tick to whichever handler registered interest in that
exact token. Broker-agnostic — keyed only by `token`.

Not wired into core/trading/broker.py's live WebSocket callback yet: that callback
currently does a lenient two-way split (spot token vs. "anything else, self-filtered
against the currently-subscribed option token inside the handler") because the option
token changes on every strike rotation, and strict registry-style routing would need a
register()/unregister() call at every rotation — a real behaviour change (a missed
re-register silently drops ticks, where today's fallback-to-else does not), not a
same-output refactor. This is available for the case that actually needs strict
per-token dispatch — multiple simultaneously-live instruments, or a second broker —
rather than forced into today's single-instrument-with-fallback design.
"""

from typing import Callable, Dict, Optional


class TickRouter:
    def __init__(self):
        self._handlers: Dict[str, Callable[[Dict], None]] = {}
        self._default_handler: Optional[Callable[[Dict], None]] = None

    def register(self, token: str, handler: Callable[[Dict], None]) -> None:
        self._handlers[token] = handler

    def unregister(self, token: str) -> None:
        self._handlers.pop(token, None)

    def set_default(self, handler: Optional[Callable[[Dict], None]]) -> None:
        """Handler for a tick whose token has no registration. None (the default)
        means an unrouted tick is silently dropped."""
        self._default_handler = handler

    def route(self, tick: Dict) -> bool:
        """Returns True if the tick was delivered to a handler."""
        token = tick.get("token")
        handler = self._handlers.get(token) if token else None
        if handler is None:
            handler = self._default_handler
        if handler is None:
            return False
        handler(tick)
        return True
