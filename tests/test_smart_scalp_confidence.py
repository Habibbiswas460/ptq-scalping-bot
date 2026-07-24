import pytest
import time
from datetime import datetime
import logging

from core.engines.adaptive_confidence_engine import AdaptiveConfidenceEngine
from core.engines.market_quality_engine import MarketQualityEngine
from core.engines.weighted_score_engine import WeightedScoreEngine
from strategies.smart_scalp_v3 import SmartScalpV3


class DummyStrategy(SmartScalpV3):
    def __init__(self):
        # Avoid config file load warnings
        self.config = {}
        self.strategy_config = {}
        self.indicators_config = {}
        self.scoring_config = {}
        self.min_score = 4
        self.min_confidence = 70
        self.max_confidence_score = 11
        self.min_weighted_score_pct = 0
        self._last_delta = None
        self._last_oi = None
        self._prev_oi = None
        self._oi_change_pct = 0.0
        self.weighted_score_engine = WeightedScoreEngine()
        self.confidence_engine = AdaptiveConfidenceEngine()
        self.market_quality_engine = MarketQualityEngine(minimum_pct=0, max_spread_pct=100.0, max_stale_ms=10**9)

    def check_premium_filter(self, tick):
        return True, "Premium OK"

    def get_option_delta(self, tick):
        return 0.5

    def update_oi_data(self, tick):
        return 0.0, "NEUTRAL"

    def calculate_indicators(self, ticks):
        return {
            'Close': 100.0,
            'Prev_Close': 98.0,
            'High': 101.0,
            'Low': 98.5,
            'EMA_9': 100.0,
            'EMA_21': 95.0,
            'EMA_50': 90.0,
            'RSI': 55.0,
            'ATR': 10.0,
            'MACD_Hist': 0.5,
            'MACD_Hist_Prev': 0.2,
            'VWAP': 99.0,
            'Above_VWAP': True,
            'Below_VWAP': False,
            'Volume_Spike': False,
            'Vol_Ratio': 1.0,
            'Squeeze': False,
            'Was_Squeeze': False,
            'Delta': 0.5,
        }


def test_score_to_confidence_normalization():
    strategy = DummyStrategy()
    strategy.max_confidence_score = 11

    assert strategy._score_to_confidence(0) == 0
    assert strategy._score_to_confidence(1) == 9
    assert strategy._score_to_confidence(4) == 36
    assert strategy._score_to_confidence(8) == 72
    assert strategy._score_to_confidence(11) == 100


def test_generate_signal_blocks_low_confidence():
    strategy = DummyStrategy()

    strategy.min_score = 4
    strategy.min_confidence = 70
    strategy.max_confidence_score = 11

    def calculate_indicators_low_score(ticks):
        return {
            'Close': 100.0,
            'Prev_Close': 99.0,
            'High': 100.5,
            'Low': 99.0,
            'EMA_9': 100.0,
            'EMA_21': 99.0,
            'EMA_50': 98.0,
            'RSI': 46.0,
            'ATR': 10.0,
            'MACD_Hist': 0.5,
            'MACD_Hist_Prev': 0.2,
            'VWAP': 101.0,
            'Above_VWAP': False,
            'Below_VWAP': True,
            'Volume_Spike': False,
            'Vol_Ratio': 1.0,
            'Squeeze': False,
            'Was_Squeeze': False,
            'Delta': 0.5,
        }

    strategy.calculate_indicators = calculate_indicators_low_score
    strategy.calculate_adaptive_confidence = lambda indicators, latest_tick, score_pct, direction, oi_direction: (60, {})

    now_ms = int(time.time() * 1000)
    ticks = [{
        'bid': 100.0,
        'ask': 100.2,
        'volume': 1000,
        'timestamp': now_ms,
        'original_timestamp': now_ms,
    } for _ in range(10)]
    signal, direction, confidence, details = strategy.generate_signal(ticks)

    assert signal == 0
    assert direction == ""
    assert confidence == 0
    assert "Low confidence" in details["reason"]


def test_generate_signal_allows_high_confidence():
    strategy = DummyStrategy()
    strategy.min_score = 4
    strategy.min_confidence = 70
    strategy.max_confidence_score = 11

    # Force a stronger bullish signal with score >= 8.
    def calculate_indicators_high_score(ticks):
        return {
            'Close': 105.0,
            'Prev_Close': 100.0,
            'High': 106.0,
            'Low': 100.0,
            'EMA_9': 103.0,
            'EMA_21': 100.0,
            'EMA_50': 99.0,
            'RSI': 60.0,
            'ATR': 10.0,
            'MACD_Hist': 0.5,
            'MACD_Hist_Prev': 0.1,
            'VWAP': 102.0,
            'Above_VWAP': True,
            'Below_VWAP': False,
            'Volume_Spike': True,
            'Vol_Ratio': 2.0,
            'Squeeze': False,
            'Was_Squeeze': False,
            'Delta': 0.5,
        }

    strategy.calculate_indicators = calculate_indicators_high_score
    strategy.calculate_adaptive_confidence = lambda indicators, latest_tick, score_pct, direction, oi_direction: (75, {})

    now_ms = int(time.time() * 1000)
    ticks = [{
        'bid': 100.0,
        'ask': 100.2,
        'volume': 1000,
        'timestamp': now_ms,
        'original_timestamp': now_ms,
    } for _ in range(10)]
    signal, direction, confidence, details = strategy.generate_signal(ticks)

    assert signal == 1
    assert direction == "CE"
    assert confidence >= 70
    assert details["bull_score"] >= 8


def test_freshness_score_handles_seconds_milliseconds_microseconds_nanoseconds():
    engine = AdaptiveConfidenceEngine()
    now = datetime.now()

    ts_seconds = now.timestamp()
    ts_milliseconds = ts_seconds * 1_000
    ts_microseconds = ts_seconds * 1_000_000
    ts_nanoseconds = ts_seconds * 1_000_000_000

    assert engine._freshness_score({'timestamp': ts_seconds}) >= 80
    assert engine._freshness_score({'timestamp': ts_milliseconds}) >= 80
    assert engine._freshness_score({'timestamp': ts_microseconds}) >= 80
    assert engine._freshness_score({'timestamp': ts_nanoseconds}) >= 80


def test_freshness_score_invalid_timestamp_returns_default_mid_score():
    engine = AdaptiveConfidenceEngine()

    assert engine._freshness_score({'timestamp': 'invalid'}) == 50
    assert engine._freshness_score({'timestamp': -999}) == 50


def test_market_quality_freshness_policy_warning_reject_and_hard_reject():
    engine = MarketQualityEngine(minimum_pct=0, max_spread_pct=100.0, max_stale_ms=500)
    now_ms = int(time.time() * 1000)

    base_tick = {
        'timestamp': now_ms,
        'original_timestamp': now_ms,
        'bid': 100.0,
        'ask': 100.1,
        'spread_pct': 0.1,
        'volume': 100,
    }

    warning_tick = dict(base_tick)
    warning_tick['original_timestamp'] = now_ms - 600
    warning_result = engine.evaluate(warning_tick, indicators={})
    assert warning_result['hard_reject'] is False
    assert warning_result['passed'] is True

    reject_tick = dict(base_tick)
    reject_tick['original_timestamp'] = now_ms - 900
    reject_result = engine.evaluate(reject_tick, indicators={})
    assert reject_result['hard_reject'] is False
    assert reject_result['passed'] is False
    assert 'Tick Stale' in (reject_result['reason'] or '')

    hard_reject_tick = dict(base_tick)
    hard_reject_tick['original_timestamp'] = now_ms - 1300
    hard_reject_result = engine.evaluate(hard_reject_tick, indicators={})
    assert hard_reject_result['hard_reject'] is True
    assert hard_reject_result['passed'] is False
    assert 'Tick Stale' in (hard_reject_result['hard_reject_reason'] or '')


def test_market_quality_tick_age_accepts_datetime_timestamp():
    engine = MarketQualityEngine()
    now = datetime.now()

    age_ms = engine._tick_age_ms({'timestamp': now})

    assert isinstance(age_ms, float)
    assert age_ms >= 0
    assert age_ms < 2000


def test_market_quality_tick_age_accepts_epoch_seconds():
    engine = MarketQualityEngine()
    now_seconds = datetime.now().timestamp()

    age_ms = engine._tick_age_ms({'timestamp': now_seconds})

    assert isinstance(age_ms, float)
    assert age_ms >= 0
    assert age_ms < 2000


def test_market_quality_tick_age_accepts_epoch_milliseconds():
    engine = MarketQualityEngine()
    now_milliseconds = datetime.now().timestamp() * 1000

    age_ms = engine._tick_age_ms({'timestamp': now_milliseconds})

    assert isinstance(age_ms, float)
    assert age_ms >= 0
    assert age_ms < 2000


def test_market_quality_tick_age_accepts_iso8601_string():
    engine = MarketQualityEngine()
    now_iso = datetime.now().isoformat()

    age_ms = engine._tick_age_ms({'timestamp': now_iso})

    assert isinstance(age_ms, float)
    assert age_ms >= 0
    assert age_ms < 2000


def test_market_quality_tick_age_accepts_pandas_timestamp_if_available():
    pd = pytest.importorskip('pandas')
    engine = MarketQualityEngine()
    now_ts = pd.Timestamp(datetime.now())

    age_ms = engine._tick_age_ms({'timestamp': now_ts})

    assert isinstance(age_ms, float)
    assert age_ms >= 0
    assert age_ms < 2000


def test_market_quality_tick_age_unsupported_type_warns_once_and_falls_back(caplog):
    class UnsupportedTimestamp:
        pass

    engine = MarketQualityEngine()
    MarketQualityEngine._timestamp_warning_emitted = False

    with caplog.at_level(logging.WARNING):
        age_ms_first = engine._tick_age_ms({'timestamp': UnsupportedTimestamp()})
        age_ms_second = engine._tick_age_ms({'timestamp': UnsupportedTimestamp()})

    warnings = [rec for rec in caplog.records if 'unsupported timestamp type' in rec.getMessage().lower()]

    assert age_ms_first == 999999.0
    assert age_ms_second == 999999.0
    assert len(warnings) == 1
