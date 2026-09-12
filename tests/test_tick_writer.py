"""core/market_data/tick_writer.py: batched, non-blocking writes to TickStore."""

import queue
import time

from core.market_data.tick_store import TickStore
from core.market_data.tick_writer import BatchedTickWriter


class _FakeStore:
    def __init__(self):
        self.tick_batches = []
        self.candle_batches = []
        self.raise_on_write_ticks = False

    def write_ticks(self, ticks):
        if self.raise_on_write_ticks:
            raise RuntimeError("boom")
        self.tick_batches.append(list(ticks))
        return len(ticks)

    def write_candles(self, candles):
        self.candle_batches.append(list(candles))
        return len(candles)


def _tick(token="T1", ltp=100.0):
    return {"token": token, "ltp": ltp, "timestamp_ms": 0}


def _candle(token="T1"):
    return {"token": token, "bucket_start_ms": 0, "open": 100, "high": 100, "low": 100, "close": 100}


# -- buffering + manual flush --------------------------------------------------

def test_enqueued_ticks_are_not_written_until_flushed():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer.enqueue_tick(_tick())
    assert store.tick_batches == []


def test_flush_writes_every_buffered_tick_in_one_batch():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer.enqueue_tick(_tick(ltp=1))
    writer.enqueue_tick(_tick(ltp=2))
    writer.enqueue_tick(_tick(ltp=3))
    writer._flush_once()
    assert len(store.tick_batches) == 1
    assert [t["ltp"] for t in store.tick_batches[0]] == [1, 2, 3]


def test_flush_with_nothing_buffered_writes_nothing():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer._flush_once()
    assert store.tick_batches == []
    assert store.candle_batches == []


def test_flush_drains_the_queue_so_a_second_flush_is_empty():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer.enqueue_tick(_tick())
    writer._flush_once()
    writer._flush_once()
    assert len(store.tick_batches) == 1


def test_candles_and_ticks_are_flushed_independently():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer.enqueue_tick(_tick())
    writer.enqueue_candle(_candle())
    writer._flush_once()
    assert len(store.tick_batches) == 1
    assert len(store.candle_batches) == 1


# -- overflow handling -----------------------------------------------------------

def test_a_full_queue_drops_the_tick_and_counts_it_instead_of_raising():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999, max_queue_size=2)
    writer.enqueue_tick(_tick())
    writer.enqueue_tick(_tick())
    writer.enqueue_tick(_tick())  # queue is full, must not raise
    assert writer.dropped_tick_count == 1


def test_a_full_candle_queue_drops_and_counts_too():
    store = _FakeStore()
    writer = BatchedTickWriter(store=store, flush_interval_sec=999, max_queue_size=1)
    writer.enqueue_candle(_candle())
    writer.enqueue_candle(_candle())
    assert writer.dropped_candle_count == 1


# -- write failure is swallowed, never propagates to the caller -----------------

def test_a_store_write_failure_is_caught_not_raised():
    store = _FakeStore()
    store.raise_on_write_ticks = True
    writer = BatchedTickWriter(store=store, flush_interval_sec=999)
    writer.enqueue_tick(_tick())
    writer._flush_once()  # must not raise


# -- background thread lifecycle, against a real TickStore ----------------------

def test_start_flushes_on_the_interval_against_a_real_store(tmp_path):
    real_store = TickStore(store_dir=str(tmp_path))
    writer = BatchedTickWriter(store=real_store, flush_interval_sec=0.05)
    writer.start()
    try:
        writer.enqueue_tick({"source_broker": "angel_one", "token": "T1", "ltp": 100.0,
                              "timestamp_ms": 1_757_000_000_000})
        deadline = time.time() + 2.0
        rows = []
        while time.time() < deadline:
            rows = list(real_store.query_ticks("T1", 0, 2_000_000_000_000))
            if rows:
                break
            time.sleep(0.02)
        assert len(rows) == 1
    finally:
        writer.stop()


def test_stop_flushes_whatever_is_still_buffered(tmp_path):
    real_store = TickStore(store_dir=str(tmp_path))
    writer = BatchedTickWriter(store=real_store, flush_interval_sec=999)
    writer.start()
    writer.enqueue_tick({"source_broker": "angel_one", "token": "T1", "ltp": 100.0,
                          "timestamp_ms": 1_757_000_000_000})
    writer.stop()  # interval is 999s, so only stop()'s own flush can deliver this
    rows = list(real_store.query_ticks("T1", 0, 2_000_000_000_000))
    assert len(rows) == 1


def test_stop_is_safe_to_call_when_never_started():
    writer = BatchedTickWriter(store=_FakeStore(), flush_interval_sec=999)
    writer.stop()  # must not raise


def test_start_is_idempotent():
    writer = BatchedTickWriter(store=_FakeStore(), flush_interval_sec=999)
    writer.start()
    thread1 = writer._thread
    writer.start()
    assert writer._thread is thread1
    writer.stop()
