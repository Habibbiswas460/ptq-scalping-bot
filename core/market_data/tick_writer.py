"""Buffers ticks and completed candles in memory and flushes them to a TickStore on a
background thread, so a disk write never happens on the hot WebSocket callback.

`enqueue_tick()`/`enqueue_candle()` are O(1) and never raise or block: a full queue
(the writer thread stalled, or a genuinely sustained tick burst) drops the newest item
and counts it rather than ever pushing backpressure onto the caller — that caller is
core/trading/broker.py's `_on_ws_tick`, running under its own tick lock.
"""

import queue
import threading
from typing import Dict, List, Optional

from core.market_data.tick_store import TickStore

DEFAULT_FLUSH_INTERVAL_SEC = 5.0
DEFAULT_MAX_QUEUE_SIZE = 20000


class BatchedTickWriter:

    def __init__(
        self,
        store: Optional[TickStore] = None,
        flush_interval_sec: float = DEFAULT_FLUSH_INTERVAL_SEC,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        logger=None,
    ):
        self.store = store or TickStore()
        self._flush_interval_sec = flush_interval_sec
        self._tick_queue: "queue.Queue[Dict]" = queue.Queue(maxsize=max_queue_size)
        self._candle_queue: "queue.Queue[Dict]" = queue.Queue(maxsize=max_queue_size)
        self.logger = logger
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.dropped_tick_count = 0
        self.dropped_candle_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TickStoreWriter")
        self._thread.start()

    def stop(self, flush: bool = True) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._flush_interval_sec + 2.0)
        if flush:
            self._flush_once()

    def enqueue_tick(self, tick: Dict) -> None:
        """Non-blocking. `tick` must already be in TickStore's canonical shape
        (brokers/angel_one/normalizer.normalize_tick() output) — this class doesn't
        know how to normalize a broker's wire format itself."""
        try:
            self._tick_queue.put_nowait(tick)
        except queue.Full:
            self.dropped_tick_count += 1

    def enqueue_candle(self, candle: Dict) -> None:
        """`candle` is a core/market_data/ohlcv_aggregator.py Candle.as_dict()."""
        try:
            self._candle_queue.put_nowait(candle)
        except queue.Full:
            self.dropped_candle_count += 1

    def _run(self) -> None:
        while not self._stop_event.wait(self._flush_interval_sec):
            self._flush_once()
        # stop() does its own post-join flush; no final drain here to avoid racing it.

    def _flush_once(self) -> None:
        ticks = self._drain(self._tick_queue)
        if ticks:
            try:
                self.store.write_ticks(ticks)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"TickStore write_ticks failed, {len(ticks)} ticks lost: {e}")

        candles = self._drain(self._candle_queue)
        if candles:
            try:
                self.store.write_candles(candles)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"TickStore write_candles failed, {len(candles)} candles lost: {e}")

    @staticmethod
    def _drain(q: "queue.Queue[Dict]") -> List[Dict]:
        items: List[Dict] = []
        while True:
            try:
                items.append(q.get_nowait())
            except queue.Empty:
                break
        return items
