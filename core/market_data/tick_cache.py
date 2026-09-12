"""Latest-tick-per-token, thread-safe. Broker-agnostic — keyed only by `token`.

Distinct from core/trading/broker.py's `self.last_tick`: that field carries PTQ's own
trading-decision metadata (spot_price, strike, direction, quote_source) for whichever
one contract is currently subscribed, and stays the source of truth for entry/exit
decisions. This cache is a plain mirror of every tick that arrives, by token, useful
once something needs "what was the last tick for token X" for more than one token at a
time (a second broker, multi-instrument monitoring) without touching that decision path.
"""

import threading
from typing import Dict, Optional


class TickCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest: Dict[str, Dict] = {}

    def update(self, tick: Dict) -> None:
        token = tick.get("token")
        if not token:
            return
        with self._lock:
            self._latest[token] = tick

    def get(self, token: str) -> Optional[Dict]:
        with self._lock:
            tick = self._latest.get(token)
            return dict(tick) if tick is not None else None

    def all_tokens(self) -> Dict[str, Dict]:
        with self._lock:
            return {token: dict(tick) for token, tick in self._latest.items()}

    def clear(self, token: Optional[str] = None) -> None:
        with self._lock:
            if token is None:
                self._latest.clear()
            else:
                self._latest.pop(token, None)
