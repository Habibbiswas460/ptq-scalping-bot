from typing import Dict, Tuple


class WeightedScoreEngine:
    """
    Institutional weighted scoring engine.

    This engine accepts normalized indicators and context data,
    returns a weighted score percentage plus per-factor breakdown.
    """

    DEFAULT_WEIGHTS = {
        'ema_trend': 20,
        'vwap': 15,
        'volume': 10,
        'delta': 10,
        'oi': 10,
        'rsi': 8,
        'macd': 8,
        'atr_volatility': 5,
        'premium_quality': 5,
        'greeks': 5,
        'market_regime': 4,
        'spread_quality': 5,
    }

    def __init__(self, weights: Dict[str, int] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.total_weight = sum(self.weights.values())

    def score(self, indicators: Dict, latest_tick: Dict, direction: str, oi_direction: str) -> Tuple[int, Dict[str, int]]:
        contributions = {name: 0 for name in self.weights}

        price = indicators.get('Close', 0)
        vwap = indicators.get('VWAP', 0)
        vol_ratio = indicators.get('Vol_Ratio', 1)
        rsi = indicators.get('RSI', 50)
        macd_hist = indicators.get('MACD_Hist', 0)
        macd_hist_prev = indicators.get('MACD_Hist_Prev', 0)
        atr = indicators.get('ATR', 0)
        regime = indicators.get('regime') or indicators.get('Regime') or 'UNKNOWN'
        delta = indicators.get('Delta', 0) or latest_tick.get('delta', 0)
        premium = latest_tick.get('ltp', price)
        spread_pct = latest_tick.get('spread_pct')

        if spread_pct is None:
            bid = latest_tick.get('bid', 0)
            ask = latest_tick.get('ask', 0)
            if bid > 0 and ask > bid:
                spread_pct = (ask - bid) / bid * 100
            else:
                spread_pct = 2.0

        if direction == 'CE' and indicators.get('EMA_9', 0) > indicators.get('EMA_21', 0):
            contributions['ema_trend'] = self.weights['ema_trend']
        elif direction == 'PE' and indicators.get('EMA_9', 0) < indicators.get('EMA_21', 0):
            contributions['ema_trend'] = self.weights['ema_trend']

        if direction == 'CE' and price > vwap:
            contributions['vwap'] = self.weights['vwap']
        elif direction == 'PE' and price < vwap:
            contributions['vwap'] = self.weights['vwap']

        if vol_ratio >= 1.3:
            contributions['volume'] = self.weights['volume']
        elif vol_ratio >= 1.0:
            contributions['volume'] = int(self.weights['volume'] * 0.5)

        if 0.35 <= delta <= 0.65:
            contributions['delta'] = self.weights['delta']
            contributions['greeks'] = self.weights['greeks']
        elif 0.30 <= delta <= 0.70:
            contributions['delta'] = int(self.weights['delta'] * 0.5)
            contributions['greeks'] = int(self.weights['greeks'] * 0.5)

        if direction == 'CE' and oi_direction in ['LONG_BUILDUP', 'SHORT_COVERING']:
            contributions['oi'] = self.weights['oi']
        elif direction == 'PE' and oi_direction in ['SHORT_BUILDUP', 'LONG_UNWINDING']:
            contributions['oi'] = self.weights['oi']

        if direction == 'CE':
            if 50 < rsi < 70:
                contributions['rsi'] = self.weights['rsi']
            elif rsi >= 45:
                contributions['rsi'] = int(self.weights['rsi'] * 0.5)
        else:
            if 30 < rsi < 50:
                contributions['rsi'] = self.weights['rsi']
            elif rsi <= 55:
                contributions['rsi'] = int(self.weights['rsi'] * 0.5)

        if direction == 'CE' and macd_hist > 0 and macd_hist > macd_hist_prev:
            contributions['macd'] = self.weights['macd']
        elif direction == 'PE' and macd_hist < 0 and macd_hist < macd_hist_prev:
            contributions['macd'] = self.weights['macd']

        if 4 <= atr <= 18:
            contributions['atr_volatility'] = self.weights['atr_volatility']
        elif atr > 0:
            contributions['atr_volatility'] = int(self.weights['atr_volatility'] * 0.5)

        if premium and premium > 0:
            if premium <= 300:
                contributions['premium_quality'] = self.weights['premium_quality']
            else:
                contributions['premium_quality'] = int(self.weights['premium_quality'] * 0.6)

        if (direction == 'CE' and regime == 'BULLISH') or (direction == 'PE' and regime == 'BEARISH'):
            contributions['market_regime'] = self.weights['market_regime']
        elif regime == 'SIDEWAYS':
            contributions['market_regime'] = int(self.weights['market_regime'] * 0.5)

        if spread_pct <= 1.0:
            contributions['spread_quality'] = self.weights['spread_quality']
        elif spread_pct <= 2.0:
            contributions['spread_quality'] = int(self.weights['spread_quality'] * 0.6)

        raw_score = sum(contributions.values())
        score_pct = int((raw_score / self.total_weight) * 100) if self.total_weight else 0

        # Add normalization trace for explainability logs.
        contributions['_raw_score'] = int(raw_score)
        contributions['_total_weight'] = int(self.total_weight)
        contributions['_normalized_score_pct'] = int(min(100, score_pct))
        return min(100, score_pct), contributions
