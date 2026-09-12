"""Rolling 5-minute OHLCV builder, per token, built directly from the tick stream.

This is a NEW capability, not a replacement: core/trading/broker.py's
get_historical_candles() keeps fetching 5-min candles from Angel One's REST
getCandleData() exactly as before, and strategies keep reading from there. This
aggregator's output is for tick_store.py / offline backtesting until it's explicitly
asked to replace the REST source for a live decision.

Pure in-memory, no I/O — cheap enough to call on every tick without adding latency.

Volume assumption: `volume` on a tick is the exchange's cumulative day volume (Angel
One's Quote/SnapQuote convention), not a per-tick incremental count — a bucket's volume
is therefore (last cumulative reading in the bucket - first), floored at 0 to survive a
session-boundary reset. This is the standard reading of that field but hasn't been
checked against a live session yet; treat it as provisional, the way this codebase
treats every other unverified-against-live-data number.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

FIVE_MIN_MS = 5 * 60 * 1000


def bucket_start_ms(timestamp_ms: int, bucket_ms: int = FIVE_MIN_MS) -> int:
    return (int(timestamp_ms) // bucket_ms) * bucket_ms


@dataclass
class _Candle:
    token: str
    bucket_start_ms: int
    open: float
    high: float
    low: float
    close: float
    first_volume: Optional[int]
    last_volume: Optional[int]
    tick_count: int

    @property
    def volume(self) -> int:
        if self.first_volume is None or self.last_volume is None:
            return 0
        return max(0, self.last_volume - self.first_volume)

    def as_dict(self) -> Dict:
        return {
            "token": self.token,
            "bucket_start_ms": self.bucket_start_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
        }


class OHLCVAggregator:
    """One rolling in-progress candle per token. Each closed bucket is handed to
    `on_candle_close` (if given) and kept in `.completed[token]` either way."""

    def __init__(self, bucket_ms: int = FIVE_MIN_MS, on_candle_close: Optional[Callable[[Dict], None]] = None):
        self._bucket_ms = bucket_ms
        self._on_candle_close = on_candle_close
        self._current: Dict[str, _Candle] = {}
        self.completed: Dict[str, List[Dict]] = {}

    def add_tick(self, tick: Dict) -> None:
        """Accepts a canonical tick, or any dict carrying `token`/`ltp` plus either
        `timestamp_ms` (canonical) or `timestamp` (a raw broker tick, epoch ms)."""
        token = tick.get("token")
        ltp = tick.get("ltp")
        timestamp_ms = tick.get("timestamp_ms", tick.get("timestamp"))
        if not token or ltp is None or timestamp_ms is None:
            return

        bucket = bucket_start_ms(int(timestamp_ms), self._bucket_ms)
        volume = tick.get("volume")
        current = self._current.get(token)

        if current is None or current.bucket_start_ms != bucket:
            if current is not None:
                self._close(current)
            current = _Candle(
                token=token, bucket_start_ms=bucket,
                open=ltp, high=ltp, low=ltp, close=ltp,
                first_volume=volume, last_volume=volume, tick_count=0,
            )
            self._current[token] = current

        current.high = max(current.high, ltp)
        current.low = min(current.low, ltp)
        current.close = ltp
        current.tick_count += 1
        if volume is not None:
            current.last_volume = volume

    def _close(self, candle: _Candle) -> None:
        record = candle.as_dict()
        self.completed.setdefault(candle.token, []).append(record)
        if self._on_candle_close:
            self._on_candle_close(record)

    def flush(self, token: Optional[str] = None) -> None:
        """Force-close the in-progress candle(s) — e.g. at end of day, so the last
        partial bucket isn't silently dropped."""
        tokens = [token] if token else list(self._current.keys())
        for tok in tokens:
            current = self._current.pop(tok, None)
            if current is not None:
                self._close(current)

    def current_candle(self, token: str) -> Optional[Dict]:
        current = self._current.get(token)
        return current.as_dict() if current else None
