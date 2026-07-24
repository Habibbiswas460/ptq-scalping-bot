import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python <3.9 fallback
    ZoneInfo = None


class MarketQualityEngine:
    """
    Market quality gate for trade entry.
    """

    WEIGHTS = {
        'spread': 25,
        'liquidity': 20,
        'freshness': 15,
        'volatility': 15,
        'execution': 10,
        'greeks': 10,
        'session': 5,
    }

    _timestamp_warning_emitted = False
    _naive_timestamp_tz = ZoneInfo("Asia/Kolkata") if ZoneInfo is not None else timezone.utc

    def __init__(self, minimum_pct: int = 60, max_spread_pct: float = 0.60, max_stale_ms: int = 500):
        self.minimum_pct = minimum_pct
        self.max_spread_pct = max_spread_pct
        self.max_stale_ms = max_stale_ms

    def evaluate(
        self,
        tick: Dict,
        indicators: Dict,
        greeks: Optional[Dict] = None,
        broker_status: Optional[Dict] = None,
        validator_result: Optional[Dict] = None,
    ) -> Dict:
        """
        Evaluate execution-grade market quality.

        Returns a structured decision payload with hard reject and component breakdown.
        """
        greeks = greeks or {}
        broker_status = broker_status or {}
        validator_result = validator_result or {'is_valid': True}

        max_stale = broker_status.get('max_stale_ms', self.max_stale_ms)
        age_ms = self._tick_age_ms(tick)
        freshness_state = self._freshness_state(age_ms, max_stale)

        if freshness_state == 'HARD_REJECT':
            return {
                'passed': False,
                'quality_score': 0,
                'grade': 'REJECT',
                'hard_reject': True,
                'hard_reject_reason': f'Tick Stale ({int(age_ms)}ms > {int(max_stale + 700)}ms)',
                'components': {
                    'spread': 0,
                    'liquidity': 0,
                    'freshness': 0,
                    'volatility': 0,
                    'session': 0,
                    'greeks': 0,
                    'execution': 0,
                },
                'reason': f'Tick Stale ({int(age_ms)}ms > {int(max_stale + 700)}ms)',
                'action': 'REJECT',
            }

        if freshness_state == 'REJECT':
            return {
                'passed': False,
                'quality_score': 0,
                'grade': 'REJECT',
                'hard_reject': False,
                'hard_reject_reason': None,
                'components': {
                    'spread': 0,
                    'liquidity': 0,
                    'freshness': 0,
                    'volatility': 0,
                    'session': 0,
                    'greeks': 0,
                    'execution': 0,
                },
                'reason': f'Tick Stale ({int(age_ms)}ms > {int(max_stale + 300)}ms)',
                'action': 'REJECT',
            }

        hard_reject_reason = self._check_hard_reject(tick, broker_status, validator_result)
        if hard_reject_reason:
            return {
                'passed': False,
                'quality_score': 0,
                'grade': 'REJECT',
                'hard_reject': True,
                'hard_reject_reason': hard_reject_reason,
                'components': {
                    'spread': 0,
                    'liquidity': 0,
                    'freshness': 0,
                    'volatility': 0,
                    'session': 0,
                    'greeks': 0,
                    'execution': 0,
                },
                'reason': hard_reject_reason,
                'action': 'REJECT',
            }

        spread_points = self._spread_points(self._spread_pct(tick))
        liquidity_points = self._liquidity_points(indicators, tick)
        freshness_points = self._freshness_points(tick)
        volatility_points = self._volatility_points(indicators)
        session_points = self._session_points(datetime.now())
        greeks_points = self._greeks_points(greeks, indicators, tick)
        execution_points = self._execution_points(broker_status)

        components = {
            'spread': spread_points,
            'liquidity': liquidity_points,
            'freshness': freshness_points,
            'volatility': volatility_points,
            'session': session_points,
            'greeks': greeks_points,
            'execution': execution_points,
        }
        quality_score = int(sum(components.values()))
        grade = self._grade(quality_score)
        action = self._action(quality_score)

        return {
            'passed': quality_score >= self.minimum_pct,
            'quality_score': quality_score,
            'grade': grade,
            'hard_reject': False,
            'hard_reject_reason': None,
            'components': components,
            'reason': None if quality_score >= self.minimum_pct else f'Quality below threshold: {quality_score} < {self.minimum_pct}',
            'action': action,
        }

    def score(self, indicators: Dict, latest_tick: Dict) -> Tuple[bool, Dict[str, int]]:
        """Backward-compatible wrapper used by existing strategy call sites."""
        result = self.evaluate(latest_tick, indicators, {}, {}, {'is_valid': True})
        details = {
            'market_quality_pct': result['quality_score'],
            'market_quality_threshold': self.minimum_pct,
            'market_quality_pass': result['passed'],
            'market_quality_grade': result['grade'],
            'hard_reject': result['hard_reject'],
            'hard_reject_reason': result['hard_reject_reason'],
            'market_quality_components': result['components'],
            'market_quality_action': result['action'],
        }
        return result['passed'], details

    def _check_hard_reject(self, tick: Dict, broker_status: Dict, validator_result: Dict) -> Optional[str]:
        spread_pct = self._spread_pct(tick)
        max_spread = broker_status.get('max_spread_pct', self.max_spread_pct)
        min_liquidity = broker_status.get('min_liquidity', 1)
        volume = tick.get('volume') or tick.get('last_traded_qty') or 0

        if not validator_result.get('is_valid', True):
            return validator_result.get('reason', 'Invalid Tick')
        if not broker_status.get('market_open', True):
            return 'Market Closed'
        if broker_status.get('kill_switch_active', False):
            return 'Kill Switch Active'
        if not broker_status.get('ws_connected', True):
            return 'WebSocket Disconnected'
        if not broker_status.get('api_healthy', True) or not broker_status.get('exchange_healthy', True):
            return 'Exchange/API Unhealthy'
        if broker_status.get('circuit_breaker_open', False):
            return 'Circuit Breaker Open'
        if spread_pct > max_spread:
            return f'Spread Too High ({spread_pct:.2f}% > {max_spread:.2f}%)'
        if volume < min_liquidity:
            return f'Liquidity Below Minimum ({volume} < {min_liquidity})'
        return None

    def _freshness_state(self, age_ms: float, max_stale_ms: int) -> str:
        """Freshness policy with warning and staged reject levels.

        Default thresholds (max_stale_ms=500):
        - <=500ms: NORMAL
        - 500-800ms: WARN
        - 800-1200ms: REJECT
        - >1200ms: HARD_REJECT
        """
        warning_upper = max_stale_ms + 300
        reject_upper = max_stale_ms + 700

        if age_ms <= max_stale_ms:
            return 'NORMAL'
        if age_ms <= warning_upper:
            return 'WARN'
        if age_ms <= reject_upper:
            return 'REJECT'
        return 'HARD_REJECT'

    def _spread_pct(self, tick: Dict) -> float:
        spread_pct = tick.get('spread_pct')
        if spread_pct is not None:
            return float(spread_pct)
        bid = tick.get('bid', 0)
        ask = tick.get('ask', 0)
        if bid and ask and ask > bid:
            return ((ask - bid) / bid) * 100.0
        return 99.0

    def _tick_age_ms(self, tick: Dict) -> float:
        timestamp = tick.get('original_timestamp') or tick.get('timestamp')
        if not timestamp:
            return 999999.0
        now_ms = int(datetime.now().timestamp() * 1000)

        ts_ms = self._normalize_timestamp_ms(timestamp)
        if ts_ms is None:
            self._warn_unsupported_timestamp(timestamp)
            return 999999.0

        return float(max(0, now_ms - ts_ms))

    def _normalize_timestamp_ms(self, timestamp) -> Optional[int]:
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=self._naive_timestamp_tz)
            return int(timestamp.timestamp() * 1000)

        if isinstance(timestamp, (int, float)):
            ts_num = float(timestamp)
            return int(ts_num if ts_num > 1e10 else ts_num * 1000)

        if isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=self._naive_timestamp_tz)
                return int(parsed.timestamp() * 1000)
            except ValueError:
                return None

        # pandas.Timestamp compatibility without importing pandas.
        if hasattr(timestamp, 'timestamp') and callable(getattr(timestamp, 'timestamp')):
            try:
                ts_num = float(timestamp.timestamp())
                return int(ts_num if ts_num > 1e10 else ts_num * 1000)
            except Exception:
                return None

        return None

    def _warn_unsupported_timestamp(self, timestamp) -> None:
        if MarketQualityEngine._timestamp_warning_emitted:
            return
        logging.warning(
            "MarketQualityEngine received unsupported timestamp type %s; using stale fallback",
            type(timestamp).__name__,
        )
        MarketQualityEngine._timestamp_warning_emitted = True

    def _spread_points(self, spread_pct: float) -> int:
        if spread_pct <= 0.20:
            return self.WEIGHTS['spread']
        if spread_pct <= 0.40:
            return 18
        if spread_pct <= 0.60:
            return 10
        return 0

    def _liquidity_points(self, indicators: Dict, tick: Dict) -> int:
        vol_ratio = float(indicators.get('Vol_Ratio', 1.0) or 1.0)
        volume = float(tick.get('volume') or 0)
        if vol_ratio >= 1.8 or volume >= 100000:
            return self.WEIGHTS['liquidity']
        if vol_ratio >= 1.3 or volume >= 50000:
            return 16
        if vol_ratio >= 1.0 or volume >= 15000:
            return 10
        if vol_ratio >= 0.7 or volume >= 5000:
            return 4
        return 0

    def _freshness_points(self, tick: Dict) -> int:
        age_ms = self._tick_age_ms(tick)
        freshness_state = self._freshness_state(age_ms, self.max_stale_ms)

        if freshness_state == 'WARN':
            return 4
        if freshness_state in {'REJECT', 'HARD_REJECT'}:
            return 0

        if age_ms < 150:
            return self.WEIGHTS['freshness']
        if age_ms <= 300:
            return 12
        if age_ms <= 500:
            return 7
        return 0

    def _volatility_points(self, indicators: Dict) -> int:
        atr = float(indicators.get('ATR', 0) or 0)
        vix = float(indicators.get('VIX', 0) or 0)
        if (4 <= atr <= 18) or (12 <= vix <= 22):
            return self.WEIGHTS['volatility']
        if (2 <= atr < 4) or (10 <= vix < 12):
            return 10
        if (18 < atr <= 25) or (22 < vix <= 28):
            return 8
        return 0

    def _session_points(self, now: datetime) -> int:
        hhmm = now.hour * 100 + now.minute
        if 920 <= hhmm < 1030:
            return self.WEIGHTS['session']
        if 1030 <= hhmm < 1300:
            return 4
        if 1300 <= hhmm < 1430:
            return 3
        if 1430 <= hhmm < 1515:
            return 4
        return 1

    def _greeks_points(self, greeks: Dict, indicators: Dict, tick: Dict) -> int:
        delta = float(greeks.get('delta') or indicators.get('Delta') or tick.get('delta') or 0)
        gamma = float(greeks.get('gamma') or 0)
        theta = float(greeks.get('theta') or 0)
        stable_delta = 0.35 <= abs(delta) <= 0.65
        stable_gamma = gamma <= 0.08 if gamma else True
        theta_ok = abs(theta) <= 1.5 if theta else True
        score = 0
        if stable_delta:
            score += 5
        if stable_gamma:
            score += 3
        if theta_ok:
            score += 2
        return min(self.WEIGHTS['greeks'], score)

    def _execution_points(self, broker_status: Dict) -> int:
        ws_ok = broker_status.get('ws_connected', True)
        api_ok = broker_status.get('api_healthy', True)
        reconnects = int(broker_status.get('recent_reconnects', 0) or 0)
        latency_ms = float(broker_status.get('latency_ms', 0) or 0)
        queue_depth = int(broker_status.get('queue_depth', 0) or 0)

        if ws_ok and api_ok and reconnects == 0 and latency_ms <= 80 and queue_depth <= 5:
            return self.WEIGHTS['execution']
        if ws_ok and api_ok and reconnects <= 1 and latency_ms <= 150 and queue_depth <= 10:
            return 8
        if ws_ok and api_ok and latency_ms <= 250:
            return 5
        if ws_ok:
            return 3
        return 0

    def _grade(self, quality_score: int) -> str:
        if quality_score >= 90:
            return 'A+'
        if quality_score >= 80:
            return 'A'
        if quality_score >= 70:
            return 'B'
        if quality_score >= 60:
            return 'C'
        return 'REJECT'

    def _action(self, quality_score: int) -> str:
        if quality_score >= 85:
            return 'ALLOW'
        if quality_score >= 70:
            return 'ALLOW'
        if quality_score >= 60:
            return 'SMALL_SIZE'
        return 'REJECT'
