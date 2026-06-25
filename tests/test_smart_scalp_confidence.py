import pytest

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
        self._indicators_cache = {}
        self._last_delta = None
        self._last_oi = None
        self._prev_oi = None
        self._oi_change_pct = 0.0

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

    # Force a score that is above min score but below min confidence threshold.
    strategy.min_score = 4
    strategy.min_confidence = 70
    strategy.max_confidence_score = 11

    # Patch calculate_indicators to create a score of exactly 4.
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
        }

    strategy.calculate_indicators = calculate_indicators_low_score

    signal, direction, confidence, details = strategy.generate_signal([{}] * 10)

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
        }

    strategy.calculate_indicators = calculate_indicators_high_score

    signal, direction, confidence, details = strategy.generate_signal([{}] * 10)

    assert signal == 1
    assert direction == "CE"
    assert confidence >= 70
    assert details["bull_score"] >= 8
