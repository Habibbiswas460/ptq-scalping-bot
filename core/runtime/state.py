from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Dict, List, Optional


@dataclass
class RuntimeState:
    """Shared in-memory runtime state for startup and live loop reuse."""

    recent_ticks: List[Dict[str, Any]] = field(default_factory=list)
    candle_history: List[Dict[str, Any]] = field(default_factory=list)
    indicators: Dict[str, Any] = field(default_factory=dict)
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    session_info: Dict[str, Any] = field(default_factory=dict)
    broker_session: Dict[str, Any] = field(default_factory=dict)
    telemetry: Dict[str, Any] = field(
        default_factory=lambda: {
            "startup_time": datetime.now().isoformat(),
            "ws_health": {},
            "ack_stats": {},
            "latency": {},
            "counters": {},
        }
    )
    caches: Dict[str, Any] = field(default_factory=dict)

    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def add_tick(self, tick: Dict[str, Any], max_ticks: int = 240) -> None:
        with self._lock:
            self.recent_ticks.append(tick)
            if len(self.recent_ticks) > max_ticks:
                self.recent_ticks = self.recent_ticks[-max_ticks:]

    def extend_ticks(self, ticks: List[Dict[str, Any]], max_ticks: int = 240) -> None:
        if not ticks:
            return
        with self._lock:
            self.recent_ticks.extend(ticks)
            if len(self.recent_ticks) > max_ticks:
                self.recent_ticks = self.recent_ticks[-max_ticks:]

    def get_recent_ticks(self, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            data = list(self.recent_ticks)
        if max_items is None:
            return data
        return data[-max_items:]

    def clear_ticks(self) -> None:
        with self._lock:
            self.recent_ticks = []
            self.candle_history = []

    def rebuild_candles(self, source_ticks: Optional[List[Dict[str, Any]]] = None) -> None:
        ticks = source_ticks if source_ticks is not None else self.get_recent_ticks()
        candles: Dict[str, Dict[str, Any]] = {}

        for tick in ticks:
            price = float(tick.get("spot_price") or tick.get("ltp") or 0)
            if price <= 0:
                continue

            ts = tick.get("original_timestamp") or tick.get("timestamp")
            if isinstance(ts, (int, float)):
                ts_sec = float(ts) / 1000.0 if float(ts) > 1e10 else float(ts)
                minute = datetime.fromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M")
            else:
                minute = datetime.now().strftime("%Y-%m-%d %H:%M")

            volume = int(tick.get("volume") or 0)
            bucket = candles.get(minute)
            if bucket is None:
                candles[minute] = {
                    "minute": minute,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "count": 1,
                }
                continue

            bucket["high"] = max(float(bucket["high"]), price)
            bucket["low"] = min(float(bucket["low"]), price)
            bucket["close"] = price
            bucket["volume"] = int(bucket["volume"]) + volume
            bucket["count"] = int(bucket["count"]) + 1

        with self._lock:
            self.candle_history = [candles[key] for key in sorted(candles.keys())]

    def set_indicators(self, indicators: Dict[str, Any]) -> None:
        with self._lock:
            self.indicators = dict(indicators or {})

    def get_indicators(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.indicators)

    def update_market_snapshot(self, patch: Dict[str, Any]) -> None:
        with self._lock:
            self.market_snapshot.update(patch or {})

    def update_session_info(self, patch: Dict[str, Any]) -> None:
        with self._lock:
            self.session_info.update(patch or {})

    def update_broker_session(self, patch: Dict[str, Any]) -> None:
        with self._lock:
            self.broker_session.update(patch or {})

    def set_strategy_decision(
        self,
        *,
        signal: bool,
        direction: str,
        score: Optional[Any],
        confidence: Optional[Any],
        reject_reason: str,
        mq_grade: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.caches.setdefault("decision", {})
            self.caches["decision"].update(
                {
                    "last_signal": bool(signal),
                    "last_direction": direction or "",
                    "last_score": score,
                    "last_confidence": confidence,
                    "last_reject_reason": reject_reason,
                    "last_mq_grade": mq_grade,
                    "updated_at": datetime.now().isoformat(),
                }
            )

    def increment_counter(self, name: str, value: int = 1) -> None:
        with self._lock:
            counters = self.telemetry.setdefault("counters", {})
            counters[name] = int(counters.get(name, 0)) + value


runtime_state = RuntimeState()
