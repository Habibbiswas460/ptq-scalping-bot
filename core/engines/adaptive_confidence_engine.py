from typing import Dict, Tuple
from datetime import datetime


class AdaptiveConfidenceEngine:
    """
    Adaptive confidence engine that combines score with market quality signals.
    """

    DEFAULT_WEIGHTS = {
        'score': 30,
        'market_regime': 15,
        'market_quality': 10,
        'spread': 8,
        'volume': 8,
        'greeks': 8,
        'oi': 6,
        'vwap': 5,
        'session': 5,
        'freshness': 5,
    }

    def __init__(self, weights: Dict[str, int] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.total_weight = sum(self.weights.values())

    def score(self, indicators: Dict, latest_tick: Dict, score_pct: int, direction: str, oi_direction: str) -> Tuple[int, Dict[str, float]]:
        components: Dict[str, float] = {}

        regime = indicators.get('regime') or indicators.get('Regime') or 'UNKNOWN'
        vol_ratio = indicators.get('Vol_Ratio', 1)
        squeeze = indicators.get('Squeeze', False)
        price = indicators.get('Close', 0)
        vwap = indicators.get('VWAP', 0)
        delta = indicators.get('Delta', 0) or latest_tick.get('delta', 0)
        spread_pct = latest_tick.get('spread_pct')

        if spread_pct is None:
            bid = latest_tick.get('bid', 0)
            ask = latest_tick.get('ask', 0)
            if bid > 0 and ask > bid:
                spread_pct = (ask - bid) / bid * 100
            else:
                spread_pct = 2.0

        components['score_input_pct'] = float(score_pct)

        if direction == 'CE':
            regime_score = 100 if regime == 'BULLISH' else 50 if regime == 'SIDEWAYS' else 20
            vwap_score = 100 if price > vwap else 30
        else:
            regime_score = 100 if regime == 'BEARISH' else 50 if regime == 'SIDEWAYS' else 20
            vwap_score = 100 if price < vwap else 30

        market_quality_score = 100 if not squeeze and vol_ratio >= 1.1 else 60 if vol_ratio >= 0.9 else 30
        spread_score = 100 if spread_pct <= 1.0 else 60 if spread_pct <= 2.0 else 20
        volume_score = 100 if vol_ratio >= 1.3 else 70 if vol_ratio >= 1.0 else 35
        greeks_score = 100 if 0.35 <= delta <= 0.65 else 50 if 0.30 <= delta <= 0.70 else 10

        if direction == 'CE':
            oi_score = 100 if oi_direction in ['LONG_BUILDUP', 'SHORT_COVERING'] else 50 if oi_direction == 'NEUTRAL' else 20
        else:
            oi_score = 100 if oi_direction in ['SHORT_BUILDUP', 'LONG_UNWINDING'] else 50 if oi_direction == 'NEUTRAL' else 20

        session_score = 100 if self._is_session_primary(latest_tick) else 65
        freshness_score = self._freshness_score(latest_tick)

        # Core adaptive chain requested by strategy review:
        # Score × Regime × Market Quality × Session × ExecutionQuality.
        regime_multiplier = self._to_multiplier(regime_score)
        market_quality_multiplier = self._to_multiplier(market_quality_score)
        session_multiplier = self._to_multiplier(session_score)

        execution_quality_score = (
            spread_score * 0.25 +
            volume_score * 0.20 +
            greeks_score * 0.20 +
            oi_score * 0.15 +
            vwap_score * 0.10 +
            freshness_score * 0.10
        )
        execution_multiplier = self._to_multiplier(execution_quality_score)

        raw_confidence = (
            float(score_pct) *
            regime_multiplier *
            market_quality_multiplier *
            session_multiplier *
            execution_multiplier
        )

        confidence = min(100, max(0, int(raw_confidence)))

        components['regime_score'] = float(regime_score)
        components['market_quality_score'] = float(market_quality_score)
        components['session_score'] = float(session_score)
        components['execution_quality_score'] = float(round(execution_quality_score, 2))
        components['vwap_score'] = float(vwap_score)
        components['spread_score'] = float(spread_score)
        components['volume_score'] = float(volume_score)
        components['greeks_score'] = float(greeks_score)
        components['oi_score'] = float(oi_score)
        components['freshness_score'] = float(freshness_score)
        components['regime_multiplier'] = float(round(regime_multiplier, 4))
        components['market_quality_multiplier'] = float(round(market_quality_multiplier, 4))
        components['session_multiplier'] = float(round(session_multiplier, 4))
        components['execution_multiplier'] = float(round(execution_multiplier, 4))
        components['raw_confidence'] = float(round(raw_confidence, 2))
        components['final_confidence'] = float(confidence)
        components['formula'] = 'Score x Regime x MarketQuality x Session x ExecutionQuality'
        return confidence, components

    def _to_multiplier(self, score: float, minimum: float = 0.5, maximum: float = 1.2) -> float:
        """Convert a 0-100 score into a bounded multiplier."""
        bounded = min(100.0, max(0.0, score))
        return minimum + ((bounded / 100.0) * (maximum - minimum))

    def _is_session_primary(self, latest_tick: Dict = None) -> bool:
        timestamp = (latest_tick or {}).get('timestamp') or (latest_tick or {}).get('original_timestamp')
        tick_dt = self._normalize_timestamp(timestamp) if timestamp is not None else None
        now = tick_dt or datetime.now()
        return now.hour == 9 and now.minute >= 45 or 10 <= now.hour < 15 or (now.hour == 15 and now.minute <= 25)

    def _normalize_timestamp(self, timestamp):
        """Normalize supported timestamp formats to datetime.

        Supports datetime objects and unix timestamps in seconds, milliseconds,
        microseconds, and nanoseconds. Returns None when parsing fails.
        """
        if isinstance(timestamp, datetime):
            return timestamp

        if not isinstance(timestamp, (int, float)):
            return None

        try:
            ts = float(timestamp)
            if ts <= 0:
                return None

            # ns -> s
            if ts > 1e17:
                ts /= 1e9
            # us -> s
            elif ts > 1e14:
                ts /= 1e6
            # ms -> s
            elif ts > 1e11:
                ts /= 1e3
            # else seconds

            return datetime.fromtimestamp(ts)
        except Exception:
            return None

    def _freshness_score(self, latest_tick: Dict) -> int:
        timestamp = latest_tick.get('timestamp') or latest_tick.get('original_timestamp')
        if not timestamp:
            return 50

        tick_dt = self._normalize_timestamp(timestamp)
        if tick_dt is None:
            return 50

        # Keep datetime arithmetic timezone-consistent for aware/naive timestamps.
        now = datetime.now(tick_dt.tzinfo) if tick_dt.tzinfo else datetime.now()
        age_sec = max(0.0, (now - tick_dt).total_seconds())

        if age_sec <= 5:
            return 100
        if age_sec <= 15:
            return 80
        if age_sec <= 30:
            return 50
        return 20
