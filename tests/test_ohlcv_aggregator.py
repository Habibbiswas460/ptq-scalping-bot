"""core/market_data/ohlcv_aggregator.py: rolling 5-min OHLCV built from ticks."""

from core.market_data.ohlcv_aggregator import OHLCVAggregator, bucket_start_ms

FIVE_MIN_MS = 5 * 60 * 1000


def _tick(token, ts, ltp, volume=None):
    return {"token": token, "timestamp_ms": ts, "ltp": ltp, "volume": volume}


def test_bucket_start_rounds_down_to_the_five_minute_boundary():
    assert bucket_start_ms(7 * 60_000) == 5 * 60_000
    assert bucket_start_ms(4 * 60_000) == 0
    assert bucket_start_ms(9 * 60_000 + 59_000) == 5 * 60_000


def test_first_tick_in_a_bucket_sets_open_high_low_close_equal():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0))
    candle = agg.current_candle("T1")
    assert candle["open"] == candle["high"] == candle["low"] == candle["close"] == 100.0
    assert candle["tick_count"] == 1


def test_subsequent_ticks_in_the_same_bucket_update_high_low_close_not_open():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0))
    agg.add_tick(_tick("T1", 60_000, 105.0))
    agg.add_tick(_tick("T1", 120_000, 98.0))
    agg.add_tick(_tick("T1", 180_000, 102.0))
    candle = agg.current_candle("T1")
    assert candle["open"] == 100.0
    assert candle["high"] == 105.0
    assert candle["low"] == 98.0
    assert candle["close"] == 102.0
    assert candle["tick_count"] == 4


def test_a_tick_in_the_next_bucket_closes_the_previous_one():
    closed = []
    agg = OHLCVAggregator(on_candle_close=lambda c: closed.append(c))
    agg.add_tick(_tick("T1", 0, 100.0))
    agg.add_tick(_tick("T1", 4 * 60_000, 110.0))
    assert closed == []  # still in bucket 0
    agg.add_tick(_tick("T1", FIVE_MIN_MS, 120.0))  # bucket 1 starts
    assert len(closed) == 1
    assert closed[0]["open"] == 100.0
    assert closed[0]["close"] == 110.0
    assert closed[0]["bucket_start_ms"] == 0
    # the new bucket's candle is now in-progress, seeded by the tick that opened it
    current = agg.current_candle("T1")
    assert current["bucket_start_ms"] == FIVE_MIN_MS
    assert current["open"] == 120.0


def test_tokens_are_aggregated_independently():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("SPOT", 0, 25000.0))
    agg.add_tick(_tick("OPT", 0, 125.0))
    assert agg.current_candle("SPOT")["open"] == 25000.0
    assert agg.current_candle("OPT")["open"] == 125.0


def test_volume_is_the_delta_between_first_and_last_cumulative_reading():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0, volume=1000))
    agg.add_tick(_tick("T1", 60_000, 101.0, volume=1500))
    agg.add_tick(_tick("T1", 120_000, 102.0, volume=1800))
    assert agg.current_candle("T1")["volume"] == 800


def test_volume_delta_is_floored_at_zero_on_a_session_boundary_reset():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0, volume=5000))
    agg.add_tick(_tick("T1", 60_000, 101.0, volume=50))  # cumulative counter reset
    assert agg.current_candle("T1")["volume"] == 0


def test_missing_volume_yields_zero_not_a_crash():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0))
    assert agg.current_candle("T1")["volume"] == 0


def test_a_tick_missing_token_or_ltp_or_timestamp_is_ignored():
    agg = OHLCVAggregator()
    agg.add_tick({"ltp": 100.0, "timestamp_ms": 0})       # no token
    agg.add_tick({"token": "T1", "timestamp_ms": 0})       # no ltp
    agg.add_tick({"token": "T1", "ltp": 100.0})            # no timestamp
    assert agg.current_candle("T1") is None


def test_raw_broker_tick_shape_with_timestamp_key_also_works():
    agg = OHLCVAggregator()
    agg.add_tick({"token": "T1", "timestamp": 0, "ltp": 100.0})
    assert agg.current_candle("T1")["open"] == 100.0


def test_flush_closes_the_in_progress_candle():
    closed = []
    agg = OHLCVAggregator(on_candle_close=lambda c: closed.append(c))
    agg.add_tick(_tick("T1", 0, 100.0))
    agg.flush("T1")
    assert len(closed) == 1
    assert agg.current_candle("T1") is None


def test_flush_with_no_token_closes_every_open_candle():
    agg = OHLCVAggregator()
    agg.add_tick(_tick("T1", 0, 100.0))
    agg.add_tick(_tick("T2", 0, 200.0))
    agg.flush()
    assert agg.current_candle("T1") is None
    assert agg.current_candle("T2") is None
    assert len(agg.completed["T1"]) == 1
    assert len(agg.completed["T2"]) == 1
