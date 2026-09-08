"""
SMART SCALP v3.4 - Institutional Grade Multi-Factor Scoring Strategy
=====================================================================
v3.4 IMPROVEMENTS:
- VWAP trend filter
- Delta range filter (0.35-0.65 ATM zone)
- OI change direction analysis
- Volume spike detection (1.5x avg)
- Premium band filter (from config.constants)
- Risk-based position sizing
- Improved chop detection

Backtest Results (6 months):
- Win Rate: 58.5% (CE: 62%, PE: 54%)
- Profit Factor: 2.06x
- Monthly Return: +42.2%
- Max Drawdown: -15.4%

4-Lot Configuration:
- CE: 260 qty (100%)
- PE: 156 qty (60%)
- Monthly P&L: ₹50,608
"""

import json
import logging
import time as _time
from pathlib import Path
from typing import Dict, Tuple, List, Optional
from datetime import datetime
import os
from collections import deque
from statistics import median

from strategies.scoring import WeightedScoreEngine
from strategies import market_context, market_gate, selector
from strategies import pullback_strategy as _pullback_strategy_module
from config.constants import TRADING_NO_TRADE_BEFORE

def _parse_no_trade_before() -> tuple:
    """(hour, minute) before which the strategy will not signal. Falls back to the historical
    09:45 if the setting is malformed, so a typo cannot silently open the whole session."""
    try:
        h, m = TRADING_NO_TRADE_BEFORE.split(':')
        return int(h), int(m)
    except (ValueError, AttributeError):
        return 9, 45


from strategies.scoring import AdaptiveConfidenceEngine
from core.engines.market_quality_engine import MarketQualityEngine
from config.constants import (
    SL_POINTS_FIXED, TP_POINTS_FIXED,
    CE_QUANTITY, PE_QUANTITY,
    MIN_SCORE_TO_TRADE, MIN_CONFIDENCE,
    MAX_CONFIDENCE_SCORE,
    MIN_ENTRY_PREMIUM, MAX_ENTRY_PREMIUM,
    TP_MULTIPLIER,
    ATR_SL_HIGH_THRESHOLD, ATR_SL_LOW_THRESHOLD,
    ATR_HIGH_SL_ADJUSTMENT, ATR_HIGH_TP_ADJUSTMENT,
    ATR_LOW_SL_ADJUSTMENT, ATR_LOW_TP_ADJUSTMENT,
    ATR_SL_MIN_POINTS, ATR_TP_MIN_POINTS,
    DIRECTIONAL_EXHAUSTION_ENABLED, PE_EXHAUSTION_RSI, CE_EXHAUSTION_RSI,
    OI_CHANGE_WINDOW_SEC,
)

try:
    from core.runtime import runtime_state
except Exception:
    runtime_state = None

# v3.1 Filter Constants
VWAP_ENABLED = True
DELTA_FILTER_ENABLED = True
DELTA_MIN = 0.35  # Avoid deep OTM
DELTA_MAX = 0.65  # Avoid deep ITM  
OI_CHANGE_ENABLED = True
VOLUME_SPIKE_MULTIPLIER = 1.5  # Volume > 1.5x avg = spike
# Single source of truth for premium band comes from config.constants.
PREMIUM_MIN = MIN_ENTRY_PREMIUM
PREMIUM_MAX = MAX_ENTRY_PREMIUM


class SmartScalpV3:
    """
    Multi-factor scoring system with institutional-grade confluence.
    v3.4: Added VWAP, Delta, OI, Volume filters.
    Requires 4+ points and 70%+ confidence for entry.
    """

    SCORE_CATEGORIES = [
        (50, 'NO TRADE'),
        (65, 'WEAK'),
        (75, 'NORMAL'),
        (85, 'STRONG'),
        (100, 'INSTITUTIONAL'),
    ]
    
    # Lazy import cache for circular import safety
    _trading_state = None
    _greeks_calculator = None
    _project_root = Path(__file__).resolve().parent.parent
    
    def __init__(self, config_path: str = "config/bot_config.json"):
        """Initialize with config"""
        self.config = self._load_config(config_path)
        self.strategy_config = self._load_strategy_config()
        self.indicators_config = self.strategy_config.get('indicators', {})
        self.scoring_config = self.strategy_config.get('scoring_system', {})
        
        # Indicator periods
        self.ema_fast = self.indicators_config.get('ema_fast', 5)
        self.ema_signal = self.indicators_config.get('ema_signal', 9)
        self.ema_medium = self.indicators_config.get('ema_medium', 21)
        self.ema_slow = self.indicators_config.get('ema_slow', 50)
        self.rsi_period = self.indicators_config.get('rsi_period', 14)
        self.macd_fast = self.indicators_config.get('macd_fast', 12)
        self.macd_slow = self.indicators_config.get('macd_slow', 26)
        self.macd_signal_period = self.indicators_config.get('macd_signal', 9)
        self.bb_period = self.indicators_config.get('bb_period', 20)
        self.bb_std = self.indicators_config.get('bb_std', 2.0)
        self.kc_period = self.indicators_config.get('kc_period', 20)
        self.kc_atr_mult = self.indicators_config.get('kc_atr_mult', 1.5)
        self.vol_sma = self.indicators_config.get('volume_sma', 20)
        self.atr_period = self.indicators_config.get('atr_period', 14)
        
        # Scoring requirements
        self.min_score = self.scoring_config.get('min_score_to_trade', MIN_SCORE_TO_TRADE)
        self.min_confidence = self.scoring_config.get('min_confidence_pct', MIN_CONFIDENCE)
        self.max_confidence_score = self.scoring_config.get('max_confidence_score', MAX_CONFIDENCE_SCORE)
        self.min_weighted_score_pct = self.scoring_config.get(
            'min_weighted_score_pct',
            int((self.min_score / max(1, self.max_confidence_score)) * 100)
        )
        self.confidence_mq_adjustments = self.scoring_config.get(
            'confidence_mq_adjustments',
            {
                'A+': -2,
                'A': -2,
                'B': -1,
                'C': 2,
                'REJECT': 5,
            }
        )
        
        # Entry configs
        self.ce_config = self.strategy_config.get('ce_entry', {})
        self.pe_config = self.strategy_config.get('pe_entry', {})

        self.weighted_score_engine = WeightedScoreEngine(
            self.scoring_config.get('score_weights')
        )
        self.confidence_engine = AdaptiveConfidenceEngine(
            self.scoring_config.get('confidence_weights')
        )
        self.market_quality_engine = MarketQualityEngine(
            self.scoring_config.get('market_quality', {}).get('minimum_pct', 65)
        )
        
        self._last_calc_time = None
        
        # v3.1: Greeks and OI cache
        self._last_delta = None
        self._last_oi = None
        self._prev_oi = None
        self._oi_change_pct = 0.0
        # (monotonic seconds, oi, price) samples, only used when OI_CHANGE_WINDOW_SEC > 0
        self._oi_history = deque(maxlen=4000)
        self._last_price = None
        self._recent_valid_premiums = deque(maxlen=30)
    
    def _get_greeks_calculator(self):
        """Lazy load Greeks calculator to avoid circular imports"""
        if SmartScalpV3._greeks_calculator is None:
            try:
                from utils.greeks import GreeksCalculator
                SmartScalpV3._greeks_calculator = GreeksCalculator()
            except ImportError:
                pass
        return SmartScalpV3._greeks_calculator

    def calculate_weighted_score(self, indicators: Dict, latest_tick: Dict, direction: str, oi_direction: str) -> Tuple[int, Dict[str, int]]:
        """Calculate weighted score using the modular weighted score engine."""
        if 'regime' not in indicators or indicators.get('regime') == 'UNKNOWN':
            indicators['regime'] = self.get_market_regime(indicators)
        return self.weighted_score_engine.score(indicators, latest_tick, direction, oi_direction)

    def calculate_adaptive_confidence(self, indicators: Dict, latest_tick: Dict, score_pct: int, direction: str, oi_direction: str) -> Tuple[int, Dict[str, float]]:
        """Calculate adaptive confidence using the modular confidence engine."""
        if 'regime' not in indicators or indicators.get('regime') == 'UNKNOWN':
            indicators['regime'] = self.get_market_regime(indicators)
        return self.confidence_engine.score(indicators, latest_tick, score_pct, direction, oi_direction)

    def _score_to_confidence(self, score: int) -> int:
        """Convert raw score into a normalized confidence percent."""
        if self.max_confidence_score <= 0:
            return 0
        confidence = int((score / self.max_confidence_score) * 100)
        return min(100, max(0, confidence))

    def _load_strategy_config(self) -> Dict:
        """Load strategy defaults from config/strategy.json and merge with bot config."""
        strategy_defaults = self._load_config('config/strategy.json').get('strategy', {})
        bot_strategy = self.config.get('strategy', {})

        merged = strategy_defaults.copy()
        for key, value in bot_strategy.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged
    
    def get_option_delta(self, tick: Dict) -> Optional[float]:
        """
        Get delta for the current option.
        Delta filter: 0.35 < delta < 0.65 (ATM zone)
        
        Returns:
            delta value or None if calculation failed
        """
        calculator = self._get_greeks_calculator()
        if not calculator:
            return None
        
        try:
            ltp = tick.get('ltp', 0)
            spot_price = tick.get('spot_price', 0)
            
            # Estimate spot from option price if not available
            if spot_price < 10000:
                spot_price = 23500  # Default NIFTY spot
            
            # Get strike (ATM)
            strike = round(spot_price / 50) * 50
            
            # Determine option type from tick or default
            option_type = tick.get('option_type', 'CE')
            
            # Calculate greeks using correct parameter names
            greeks = calculator.calculate(
                spot_price=spot_price,
                strike_price=strike,
                time_to_expiry=6 / (365 * 24),  # ~6 hours to expiry in years
                volatility=0.20,  # Default 20% IV
                risk_free_rate=0.07,  # 7% RBI rate
                option_type=option_type
            )
            
            if greeks and 'delta' in greeks:
                self._last_delta = abs(greeks['delta'])
                return self._last_delta
        except Exception:
            pass
        
        return self._last_delta
    
    def update_oi_data(self, tick: Dict) -> Tuple[float, str]:
        """
        Track OI changes and determine market direction.
        
        OI Direction Logic:
        - Price ↑ + OI ↑ = Long buildup (BULLISH)
        - Price ↑ + OI ↓ = Short covering (WEAK BULLISH)
        - Price ↓ + OI ↑ = Short buildup (BEARISH)
        - Price ↓ + OI ↓ = Long unwinding (WEAK BEARISH)
        
        Returns:
            (oi_change_pct, direction_signal)
        """
        current_oi = tick.get('oi', tick.get('open_interest', 0))
        current_price = tick.get('ltp', 0)
        
        if current_oi <= 0:
            return 0.0, "NEUTRAL"
        
        # Initialize OI tracking on first tick
        if self._last_oi is None:
            self._last_oi = current_oi
            self._prev_oi = current_oi
            self._last_price = current_price
            return 0.0, "NEUTRAL"
        
        # Use a stable previous price if available
        prev_price = self._last_price if self._last_price is not None else current_price
        base_oi = self._last_oi

        if OI_CHANGE_WINDOW_SEC > 0:
            # Compare against where OI and price were OI_CHANGE_WINDOW_SEC ago rather than
            # against the previous tick. The broker republishes OI in steps, so tick-to-tick
            # it is almost always unchanged and the +/-1% test below can essentially never
            # fire; over a real interval the same series moves by percent.
            nowt = _time.monotonic()
            self._oi_history.append((nowt, current_oi, current_price))
            cutoff = nowt - OI_CHANGE_WINDOW_SEC
            older = [h for h in self._oi_history if h[0] <= cutoff]
            if older:
                base_oi = older[-1][1]
                prev_price = older[-1][2]
            else:
                base_oi = self._oi_history[0][1]
                prev_price = self._oi_history[0][2]

        oi_change = current_oi - base_oi
        oi_change_pct = (oi_change / base_oi * 100) if base_oi > 0 else 0
        self._oi_change_pct = oi_change_pct
        
        price_up = current_price > prev_price
        
        if oi_change_pct > 1:  # OI increasing
            direction = "LONG_BUILDUP" if price_up else "SHORT_BUILDUP"
        elif oi_change_pct < -1:  # OI decreasing
            direction = "SHORT_COVERING" if price_up else "LONG_UNWINDING"
        else:
            direction = "NEUTRAL"
        
        # Update tracking for the next tick
        self._prev_oi = self._last_oi
        self._last_oi = current_oi
        self._last_price = current_price
        
        return oi_change_pct, direction
    
    def check_premium_filter(self, tick: Dict) -> Tuple[bool, str]:
        """
        Premium filter: Avoid too cheap or expensive options.
        Range from config.constants MIN_ENTRY_PREMIUM / MAX_ENTRY_PREMIUM.
        
        Returns:
            (pass_filter, reason)
        """
        premium = float(tick.get('ltp', 0) or 0)
        bid = float(tick.get('bid', 0) or 0)
        ask = float(tick.get('ask', 0) or 0)

        # Guard against quote glitches before evaluating premium range.
        if bid and ask and ask < bid:
            return False, f"Invalid quote: ask {ask:.2f} < bid {bid:.2f}"

        # If LTP is unusable but bid/ask are present, use midpoint as fallback premium.
        if premium <= 0 and bid > 0 and ask > 0:
            premium = round((bid + ask) / 2.0, 2)

        if premium <= 0:
            return False, "Invalid premium feed: non-positive LTP"

        # Detect abrupt collapses versus recent valid premium context.
        if premium >= MIN_ENTRY_PREMIUM:
            self._recent_valid_premiums.append(premium)
        if len(self._recent_valid_premiums) >= 10:
            ref_premium = median(self._recent_valid_premiums)
            if ref_premium >= MIN_ENTRY_PREMIUM and premium < (0.35 * ref_premium):
                return False, (
                    f"Premium feed anomaly ₹{premium:.0f} << ref ₹{ref_premium:.0f}"
                )
        
        if premium < MIN_ENTRY_PREMIUM:
            return False, f"Premium too low ₹{premium:.0f} < ₹{MIN_ENTRY_PREMIUM:.0f}"
        
        if premium > MAX_ENTRY_PREMIUM:
            return False, f"Premium too high ₹{premium:.0f} > ₹{MAX_ENTRY_PREMIUM:.0f}"
        
        return True, f"Premium OK ₹{premium:.0f}"

    def _resolve_tick_time(self, tick: Dict) -> datetime:
        """Resolve tick timestamp for deterministic replay/backtest time filters."""
        timestamp = tick.get('original_timestamp') or tick.get('timestamp')
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, (int, float)):
            ts_num = float(timestamp)
            if ts_num > 1e10:
                ts_num = ts_num / 1000.0
            return datetime.fromtimestamp(ts_num)
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                pass
        return datetime.now()

    def _required_confidence(self, market_quality_grade: Optional[str]) -> int:
        """Adjust minimum confidence by market-quality grade to keep good setups and filter weak ones."""
        grade = (market_quality_grade or '').upper()
        base = int(self.min_confidence)
        adjustments = getattr(self, 'confidence_mq_adjustments', {
            'A+': -2,
            'A': -2,
            'B': -1,
            'C': 2,
            'REJECT': 5,
        })
        delta = int(adjustments.get(grade, 0))
        return max(0, min(100, base + delta))
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration file"""
        try:
            path = Path(config_path)
            if not path.is_absolute():
                path = self._project_root / path

            if not path.exists():
                # Optional config override file; defaults from constants/strategy are used.
                return {}

            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            import logging
            logging.warning(f"⚠️ Config load error: {e}")
            return {}
    
    # NO Yahoo Finance - pure tick-based indicators
    
    def calculate_indicators(self, ticks: List[Dict]) -> Dict:
        """
        Calculate all technical indicators from tick data.
        Converts ticks to OHLCV and calculates indicators.

        Uses simulated/broker tick data for indicators.

        Phase C: delegates to strategies.market_context.compute_indicators() —
        the Market Context module — passing this instance's configured periods
        explicitly. No formula, threshold, or period value changed; this is a
        pure code-motion (see claude_code/report/strategy_rebuild_phaseC_*.md).
        The Supertrend computation that previously lived here was deleted —
        zero consumers repo-wide, re-verified immediately before deletion.
        """
        indicators = market_context.compute_indicators(
            ticks,
            {
                'ema_fast': self.ema_fast,
                'ema_signal': self.ema_signal,
                'ema_medium': self.ema_medium,
                'ema_slow': self.ema_slow,
                'rsi_period': self.rsi_period,
                'macd_fast': self.macd_fast,
                'macd_slow': self.macd_slow,
                'macd_signal_period': self.macd_signal_period,
                'bb_period': self.bb_period,
                'bb_std': self.bb_std,
                'atr_period': self.atr_period,
                'kc_period': self.kc_period,
                'kc_atr_mult': self.kc_atr_mult,
                'vol_sma': self.vol_sma,
            },
            runtime_state=runtime_state,
            volume_spike_multiplier=VOLUME_SPIKE_MULTIPLIER,
        )
        self._last_calc_time = datetime.now()
        return indicators
    
    # Phase C: calculate_bullish_score() and calculate_bearish_score() — a
    # second, unreferenced implementation of the CE/PE setup score — were
    # deleted here. Re-verified zero consumers repo-wide immediately before
    # deletion (see claude_code/report/strategy_rebuild_phaseC_*.md). The live
    # setup score has always been evaluate_pullback_strategy() -> now
    # strategies/pullback_strategy.py.

    def get_market_regime(self, indicators: Dict) -> str:
        """Determine market regime: BULLISH, BEARISH, or SIDEWAYS"""
        ema21 = indicators.get('EMA_21', 0)
        ema50 = indicators.get('EMA_50', 0)

        if ema50 == 0:
            return "UNKNOWN"

        diff_pct = abs(ema21 - ema50) / ema50

        if diff_pct < 0.002:  # 0.2% difference
            return "SIDEWAYS"
        elif ema21 > ema50:
            return "BULLISH"
        else:
            return "BEARISH"

    def evaluate_pullback_strategy(self, indicators: Dict, oi_direction: str) -> Dict:
        """
        PULLBACK strategy — the explicit Strategy boundary.

        Phase C: delegates to strategies.pullback_strategy.evaluate_pullback_strategy(),
        passing this instance's threshold/toggle configuration explicitly. No
        condition, threshold, or evaluation order changed — pure code-motion
        (claude_code/report/strategy_rebuild_phaseC_*.md). Kept as a method (not
        removed) so the existing public call shape — strategy.evaluate_pullback_strategy(...)
        — used by generate_signal() and by tests continues to work unchanged.
        """
        return _pullback_strategy_module.evaluate_pullback_strategy(
            indicators, oi_direction,
            min_score=self.min_score,
            vwap_enabled=VWAP_ENABLED,
            oi_change_enabled=OI_CHANGE_ENABLED,
        )

    def generate_signal(self, ticks: List[Dict]) -> Tuple[int, str, int, Dict]:
        """
        Generate trading signal based on PULLBACK logic (not blind EMA crosses).
        
        PULLBACK & PROTECT Strategy:
        - CE: Uptrend (EMA9 > EMA21) + Price dips to EMA9 support + Green candle rejection + RSI > 55
        - PE: Downtrend (EMA9 < EMA21) + Price rises to EMA9 resistance + Red candle rejection + RSI < 45
        - Chop Filter: No trade if EMAs are in squeeze (too close together)
        - Time Filter: No trade before 09:45 AM
        
        Returns:
            (signal, direction, confidence, details)
            signal: 1 for entry, 0 for no trade
            direction: "CE" or "PE"
            confidence: 0-100
            details: dict with scoring details
        """
        # ====== TIME FILTER: no trades before TRADING_NO_TRADE_BEFORE ======
        latest_tick = ticks[-1] if ticks else {}
        current_time = self._resolve_tick_time(latest_tick)
        block_h, block_m = _parse_no_trade_before()
        if (current_time.hour, current_time.minute) < (block_h, block_m):
            return 0, "", 0, {"reason": f"Time filter: Wait until {TRADING_NO_TRADE_BEFORE} "
                                        f"(now {current_time.strftime('%H:%M')})"}
        
        # We use Yahoo historical data, so don't need many ticks
        if len(ticks) < 5:
            return 0, "", 0, {"reason": "Warming up"}
        
        # latest_tick is already resolved before time filtering.
        
        # ═══════════════════════════════════════════════════════════════
        # v3.1: PREMIUM FILTER (₹80-300 range)
        # ═══════════════════════════════════════════════════════════════
        premium_ok, premium_msg = self.check_premium_filter(latest_tick)
        if not premium_ok:
            return 0, "", 0, {"reason": premium_msg}
        
        # ═══════════════════════════════════════════════════════════════
        # v3.1: DELTA FILTER (0.35-0.65 ATM zone)
        # ═══════════════════════════════════════════════════════════════
        if DELTA_FILTER_ENABLED:
            delta = self.get_option_delta(latest_tick)
            if delta is not None:
                if delta < DELTA_MIN:
                    return 0, "", 0, {"reason": f"Delta too low {delta:.2f} < {DELTA_MIN} (deep OTM)"}
                if delta > DELTA_MAX:
                    return 0, "", 0, {"reason": f"Delta too high {delta:.2f} > {DELTA_MAX} (deep ITM)"}
        
        # ═══════════════════════════════════════════════════════════════
        # v3.1: OI CHANGE ANALYSIS
        # ═══════════════════════════════════════════════════════════════
        oi_direction = "NEUTRAL"
        if OI_CHANGE_ENABLED:
            oi_change_pct, oi_direction = self.update_oi_data(latest_tick)
        
        # Calculate indicators (uses Yahoo data internally)
        indicators = self.calculate_indicators(ticks)
        if not indicators:
            return 0, "", 0, {"reason": "Failed to calculate indicators"}
        
        # Get key indicators
        close = indicators.get('Close', 0)
        prev_close = indicators.get('Prev_Close', 0)
        high = indicators.get('High', 0)
        low = indicators.get('Low', 0)
        ema9 = indicators.get('EMA_9', 0)
        ema21 = indicators.get('EMA_21', 0)
        rsi = indicators.get('RSI', 50)
        
        # Get market regime
        regime = self.get_market_regime(indicators)
        
        details = {
            "close": close,
            "ema9": ema9,
            "ema21": ema21,
            "rsi": rsi,
            "regime": regime,
            "squeeze": indicators.get('Squeeze', False),
            "macd_hist": indicators.get('MACD_Hist', 0),
            # v3.1 additions
            "vwap": indicators.get('VWAP', 0),
            "above_vwap": indicators.get('Above_VWAP', False),
            "volume_spike": indicators.get('Volume_Spike', False),
            "delta": self._last_delta,
            "oi_direction": oi_direction,
            "oi_change_pct": self._oi_change_pct
        }

        market_quality = self.market_quality_engine.evaluate(
            tick=latest_tick,
            indicators=indicators,
            greeks={'delta': self._last_delta} if self._last_delta is not None else {},
            broker_status={
                'ws_connected': not latest_tick.get('ws_disconnected', False),
                'api_healthy': latest_tick.get('api_healthy', True),
                'exchange_healthy': latest_tick.get('exchange_healthy', True),
                'kill_switch_active': latest_tick.get('kill_switch_active', False),
                'market_open': latest_tick.get('market_open', True),
                'circuit_breaker_open': latest_tick.get('circuit_breaker_open', False),
                'latency_ms': latest_tick.get('latency_ms', 0),
                'recent_reconnects': latest_tick.get('recent_reconnects', 0),
                'queue_depth': latest_tick.get('queue_depth', 0),
                'evaluation_time': current_time,
            },
            validator_result={
                'is_valid': latest_tick.get('is_valid', True),
                'reason': latest_tick.get('invalid_reason')
            }
        )
        # Phase C: MQ-result unpacking and chop detection delegate to
        # strategies.market_gate — the Market Gate module ("is the market
        # tradable?"). Same keys, same fallback values, same thresholds; pure
        # code-motion (claude_code/report/strategy_rebuild_phaseC_*.md).
        details.update(market_gate.build_market_quality_details(market_quality))

        if not market_quality.get('passed', False):
            details["reason"] = market_gate.market_quality_rejection_reason(market_quality)
            return 0, "", 0, details

        is_choppy, chop_reason = market_gate.evaluate_chop(indicators, ema9, ema21)
        if is_choppy:
            details["reason"] = f"Chop filter: {', '.join(chop_reason)}"
            details["is_choppy"] = True
            return 0, "", 0, details
        
        # ====== STRATEGY: PULLBACK (Phase 3 — extracted to an explicit boundary) ======
        # See evaluate_pullback_strategy() above. This call preserves the exact
        # inputs, conditions, thresholds, and evaluation order that previously
        # ran inline at this point in generate_signal() — nothing before it
        # (premium, delta, market quality, chop, all above) or after it
        # (weighted score, exhaustion, adaptive confidence, all below) moved.
        pullback_result = self.evaluate_pullback_strategy(indicators, oi_direction)
        ce_signal = pullback_result["ce_signal"]
        ce_score = pullback_result["ce_score"]
        ce_factors = pullback_result["ce_factors"]
        pe_signal = pullback_result["pe_signal"]
        pe_score = pullback_result["pe_score"]
        pe_factors = pullback_result["pe_factors"]

        # ====== GENERATE SIGNAL ======
        details["ce_score"] = ce_score
        details["pe_score"] = pe_score
        details["ce_factors"] = ce_factors
        details["pe_factors"] = pe_factors
        details["pullback_strategy"] = pullback_result["observability"]
        # Phase C: Strategy Selector — additive only. Documents which direction's
        # candidate the (only) Strategy produced; does not change ce_signal/
        # pe_signal or the CE-checked-first control flow below, which is
        # unchanged and remains the actual source of truth. See
        # strategies/selector.py for why no priority logic was invented.
        details["selected_direction"] = selector.select_direction(pullback_result)

        # Phase 4 (Scoring Simplification): a single, ordered rejection-attribution
        # record per direction — trigger/confirmation, then weighted-score threshold,
        # then exhaustion, then confidence threshold — so "why did this fail" has one
        # place to look instead of three differently-shaped signals (ce_score_threshold_fail,
        # exhaustion, and a reason string that gets overwritten up to three times).
        #
        # This is additive only. It does not change ce_signal/pe_signal, does not
        # change ce_weighted_pct/pe_weighted_pct, does not change confidence, and does
        # not change any threshold. Weighted Score and Adaptive Confidence's raw
        # percentages are live inputs to PositionSizeEngine's score/confidence
        # multipliers (state_machine.py -> position_size_engine.py) and to
        # entry_engine.py's own separate confidence re-check, so collapsing either
        # into a boolean here would silently change position sizing and the
        # external confidence gate — out of Phase 4's bounds (PositionSizeEngine and
        # execution behaviour are explicitly not to be changed). See
        # claude_code/report/strategy_architecture_phase4_*.md Step 11 for the full
        # evidence trail behind this decision.
        strategy_decision = {
            "CE": {"trigger_confirmation": pullback_result["observability"]["CE"]["final"]},
            "PE": {"trigger_confirmation": pullback_result["observability"]["PE"]["final"]},
        }
        details["strategy_decision"] = strategy_decision

        def _finalize_strategy_decision():
            # generate_signal() can return from several points once one direction
            # resolves (e.g. CE passes and returns before PE's own checks run).
            # Called right before every return past this point so BOTH directions'
            # strategy_decision always end with a 'final'/'failed_at', regardless of
            # which direction the function actually returned on. Backfill only —
            # never overwrites a 'final' a direction already reached on its own.
            for _dir, _score in (("CE", ce_score), ("PE", pe_score)):
                if "final" not in strategy_decision[_dir]:
                    strategy_decision[_dir]["final"] = "FAIL"
                    if strategy_decision[_dir]["trigger_confirmation"] == "FAIL":
                        strategy_decision[_dir]["failed_at"] = "trigger_confirmation"
                    elif "weighted_score" in strategy_decision[_dir]:
                        strategy_decision[_dir]["failed_at"] = "weighted_score"
                    else:
                        strategy_decision[_dir]["failed_at"] = "trigger_confirmation"
        
        # ═══════════════════════════════════════════════════════════════
        # PHASE 1: TREND EXHAUSTION DETECTION (v3.2)
        # ═══════════════════════════════════════════════════════════════
        macd_hist = indicators.get('MACD_Hist', 0)
        macd_hist_prev = indicators.get('MACD_Hist_Prev', 0)
        
        # Weighted score engine and trend exhaustion checks.
        ce_weighted_pct = 0
        pe_weighted_pct = 0

        if ce_signal:
            ce_weighted_pct, ce_components = self.calculate_weighted_score(
                indicators, latest_tick, 'CE', oi_direction
            )
            ce_score_breakdown = {
                'ema': ce_components.get('ema_trend', 0),
                'vwap': ce_components.get('vwap', 0),
                'delta': ce_components.get('delta', 0),
                'volume': ce_components.get('volume', 0),
                'oi': ce_components.get('oi', 0),
                'rsi': ce_components.get('rsi', 0),
                'macd': ce_components.get('macd', 0),
                'atr': ce_components.get('atr_volatility', 0),
                'premium': ce_components.get('premium_quality', 0),
                'greeks': ce_components.get('greeks', 0),
                'regime': ce_components.get('market_regime', 0),
                'spread': ce_components.get('spread_quality', 0),
                'raw_score': ce_components.get('_raw_score', 0),
                'total_weight': ce_components.get('_total_weight', 0),
                'normalized_score_pct': ce_components.get('_normalized_score_pct', ce_weighted_pct)
            }
            details["ce_weighted_score_pct"] = ce_weighted_pct
            details["ce_score_components"] = ce_components
            details["ce_score_breakdown"] = ce_score_breakdown
            details["ce_score_trace"] = (
                f"Raw Score {ce_score_breakdown['raw_score']}/{ce_score_breakdown['total_weight']}"
                f" -> Normalized Score {ce_score_breakdown['normalized_score_pct']}%"
            )
            ce_weighted_pass = ce_weighted_pct >= self.min_weighted_score_pct
            strategy_decision["CE"]["weighted_score"] = {
                "value": ce_weighted_pct, "threshold": self.min_weighted_score_pct,
                "pass": ce_weighted_pass,
            }
            if not ce_weighted_pass:
                ce_signal = False
                details["ce_score_threshold_fail"] = (
                    f"CE weighted score {ce_weighted_pct}% < {self.min_weighted_score_pct}%"
                )

        if pe_signal:
            pe_weighted_pct, pe_components = self.calculate_weighted_score(
                indicators, latest_tick, 'PE', oi_direction
            )
            pe_score_breakdown = {
                'ema': pe_components.get('ema_trend', 0),
                'vwap': pe_components.get('vwap', 0),
                'delta': pe_components.get('delta', 0),
                'volume': pe_components.get('volume', 0),
                'oi': pe_components.get('oi', 0),
                'rsi': pe_components.get('rsi', 0),
                'macd': pe_components.get('macd', 0),
                'atr': pe_components.get('atr_volatility', 0),
                'premium': pe_components.get('premium_quality', 0),
                'greeks': pe_components.get('greeks', 0),
                'regime': pe_components.get('market_regime', 0),
                'spread': pe_components.get('spread_quality', 0),
                'raw_score': pe_components.get('_raw_score', 0),
                'total_weight': pe_components.get('_total_weight', 0),
                'normalized_score_pct': pe_components.get('_normalized_score_pct', pe_weighted_pct)
            }
            details["pe_weighted_score_pct"] = pe_weighted_pct
            details["pe_score_components"] = pe_components
            details["pe_score_breakdown"] = pe_score_breakdown
            details["pe_score_trace"] = (
                f"Raw Score {pe_score_breakdown['raw_score']}/{pe_score_breakdown['total_weight']}"
                f" -> Normalized Score {pe_score_breakdown['normalized_score_pct']}%"
            )
            pe_weighted_pass = pe_weighted_pct >= self.min_weighted_score_pct
            strategy_decision["PE"]["weighted_score"] = {
                "value": pe_weighted_pct, "threshold": self.min_weighted_score_pct,
                "pass": pe_weighted_pass,
            }
            if not pe_weighted_pass:
                pe_signal = False
                details["pe_score_threshold_fail"] = (
                    f"PE weighted score {pe_weighted_pct}% < {self.min_weighted_score_pct}%"
                )

        # Get per-direction loss count from state machine
        try:
            # Lazy import with caching (avoids circular import issues)
            if SmartScalpV3._trading_state is None:
                from core.engines.state_machine import trading_state
                SmartScalpV3._trading_state = trading_state
            
            # Use is_direction_blocked which handles cooldown logic
            ce_blocked, ce_block_reason = SmartScalpV3._trading_state.is_direction_blocked('CE')
            pe_blocked, pe_block_reason = SmartScalpV3._trading_state.is_direction_blocked('PE')
        except:
            ce_blocked, ce_block_reason = False, ""
            pe_blocked, pe_block_reason = False, ""
        
        # CE Trend Exhaustion Check
        ce_exhausted = False
        if ce_signal:
            # 1. RSI overbought + MACD declining = momentum waning.
            #    Threshold is settable (default 70 = the value that was hardcoded here);
            #    CE_EXHAUSTION_RSI above 100, or ENABLED=false, disables this half.
            if (DIRECTIONAL_EXHAUSTION_ENABLED
                    and rsi > CE_EXHAUSTION_RSI and macd_hist < macd_hist_prev):
                ce_exhausted = True
                details["exhaustion"] = "CE overbought + MACD declining"
            # 2. Check direction block (with cooldown support). This is the SL-streak
            #    block, a different mechanism with its own evidence — the settings above
            #    deliberately do not touch it.
            if ce_blocked:
                ce_exhausted = True
                details["exhaustion"] = ce_block_reason
            strategy_decision["CE"]["exhaustion"] = {
                "pass": not ce_exhausted,
                "reason": details.get("exhaustion") if ce_exhausted else None,
            }

        # PE Trend Exhaustion Check
        pe_exhausted = False
        if pe_signal:
            # 1. RSI oversold + MACD rising = bounce coming.
            #    Threshold is settable (default 30 = the value that was hardcoded here);
            #    PE_EXHAUSTION_RSI=0 disables this half, since rsi < 0 is never true.
            if (DIRECTIONAL_EXHAUSTION_ENABLED
                    and rsi < PE_EXHAUSTION_RSI and macd_hist > macd_hist_prev):
                pe_exhausted = True
                details["exhaustion"] = "PE oversold + MACD rising"
            # 2. Check direction block (with cooldown support). SL-streak, untouched.
            if pe_blocked:
                pe_exhausted = True
                details["exhaustion"] = pe_block_reason
            strategy_decision["PE"]["exhaustion"] = {
                "pass": not pe_exhausted,
                "reason": details.get("exhaustion") if pe_exhausted else None,
            }

        # CE Signal: Weighted score and adaptive confidence
        if ce_signal and not ce_exhausted:
            confidence, confidence_components = self.calculate_adaptive_confidence(
                indicators, latest_tick, ce_weighted_pct, 'CE', oi_direction
            )
            required_conf = self._required_confidence(details.get('market_quality_grade'))
            details["ce_confidence_components"] = confidence_components
            details["score_breakdown"] = details.get("ce_score_breakdown", {})
            details["confidence_breakdown"] = confidence_components
            details["weighted_score"] = ce_weighted_pct
            details["bull_score"] = ce_weighted_pct
            details["bull_factors"] = ce_factors
            # Phase 6 (Sizing-Input Separation): the same weighted_score/confidence
            # values already assigned above (unchanged), packaged as an explicit,
            # dedicated contract for PositionSizeEngine's two consumers
            # (state_machine.py's live path, core/backtest.py's offline path) to
            # read instead of inferring them from the generic 'score'/'confidence'
            # keys that also happen to gate this signal. Additive only — 'score'
            # and 'confidence' below are untouched, and this does not change
            # ce_signal or any threshold.
            details["sizing_inputs"] = {"weighted_score": ce_weighted_pct, "confidence": confidence}
            details["reason"] = (
                f"📈 CE PULLBACK: Score {ce_weighted_pct}% | Conf {confidence}%"
            )
            ce_conf_pass = confidence >= required_conf
            strategy_decision["CE"]["confidence"] = {
                "value": confidence, "threshold": required_conf, "pass": ce_conf_pass,
            }
            strategy_decision["CE"]["final"] = "PASS" if ce_conf_pass else "FAIL"
            strategy_decision["CE"]["failed_at"] = None if ce_conf_pass else "confidence"
            if not ce_conf_pass:
                details["reason"] = (
                    f"Low confidence {confidence}% < {required_conf}%"
                    f" (MQ {details.get('market_quality_grade', 'NA')})"
                )
                # Keep the real confidence value for DVF/analytics even though the signal is rejected.
                _finalize_strategy_decision()
                return 0, "", confidence, details
            _finalize_strategy_decision()
            return 1, "CE", confidence, details
        elif ce_signal and ce_exhausted:
            strategy_decision["CE"]["final"] = "FAIL"
            strategy_decision["CE"]["failed_at"] = "exhaustion"
            details["reason"] = f"CE signal blocked: {details.get('exhaustion', 'Trend exhausted')}"
            _finalize_strategy_decision()
            return 0, "", 0, details
        
        # PE Signal: Weighted score and adaptive confidence
        if pe_signal and not pe_exhausted:
            confidence, confidence_components = self.calculate_adaptive_confidence(
                indicators, latest_tick, pe_weighted_pct, 'PE', oi_direction
            )
            required_conf = self._required_confidence(details.get('market_quality_grade'))
            details["pe_confidence_components"] = confidence_components
            details["score_breakdown"] = details.get("pe_score_breakdown", {})
            details["confidence_breakdown"] = confidence_components
            details["weighted_score"] = pe_weighted_pct
            details["bear_score"] = pe_weighted_pct
            details["bear_factors"] = pe_factors
            # Phase 6 (Sizing-Input Separation): see the CE block above for the
            # full rationale. Same additive, non-gating packaging for PE.
            details["sizing_inputs"] = {"weighted_score": pe_weighted_pct, "confidence": confidence}
            details["reason"] = (
                f"📉 PE PULLBACK: Score {pe_weighted_pct}% | Conf {confidence}%"
            )
            pe_conf_pass = confidence >= required_conf
            strategy_decision["PE"]["confidence"] = {
                "value": confidence, "threshold": required_conf, "pass": pe_conf_pass,
            }
            strategy_decision["PE"]["final"] = "PASS" if pe_conf_pass else "FAIL"
            strategy_decision["PE"]["failed_at"] = None if pe_conf_pass else "confidence"
            if not pe_conf_pass:
                details["reason"] = (
                    f"Low confidence {confidence}% < {required_conf}%"
                    f" (MQ {details.get('market_quality_grade', 'NA')})"
                )
                # Keep the real confidence value for DVF/analytics even though the signal is rejected.
                _finalize_strategy_decision()
                return 0, "", confidence, details
            _finalize_strategy_decision()
            return 1, "PE", confidence, details
        elif pe_signal and pe_exhausted:
            strategy_decision["PE"]["final"] = "FAIL"
            strategy_decision["PE"]["failed_at"] = "exhaustion"
            details["reason"] = f"PE signal blocked: {details.get('exhaustion', 'Trend exhausted')}"
            _finalize_strategy_decision()
            return 0, "", 0, details
        
        # No valid pullback signal.
        _finalize_strategy_decision()

        if ce_score > pe_score:
            details["reason"] = f"No CE pullback: Score {ce_score}/{self.max_confidence_score}, factors: {ce_factors}"
        elif pe_score > ce_score:
            details["reason"] = f"No PE pullback: Score {pe_score}/{self.max_confidence_score}, factors: {pe_factors}"
        else:
            details["reason"] = f"No pullback: CE={ce_score}, PE={pe_score}"

        return 0, "", 0, details
    
    def get_entry_params(self, direction: str, confidence: int, indicators: Dict) -> Dict:
        """
        Get entry parameters based on direction and confidence.
        
        Returns:
            Dict with sl_points, tp_points, quantity, use_runner, etc.
        """
        config = self.ce_config if direction == "CE" else self.pe_config
        
        sl_points = SL_POINTS_FIXED
        tp_points = TP_POINTS_FIXED
        
        # Dynamic adjustment based on local volatility and regime
        atr = indicators.get('ATR', 0)
        if atr:
            if atr > ATR_SL_HIGH_THRESHOLD:
                sl_points += ATR_HIGH_SL_ADJUSTMENT
                tp_points += ATR_HIGH_TP_ADJUSTMENT
            elif atr < ATR_SL_LOW_THRESHOLD:
                sl_points = max(ATR_SL_MIN_POINTS, sl_points - ATR_LOW_SL_ADJUSTMENT)
                tp_points = max(ATR_TP_MIN_POINTS, tp_points - ATR_LOW_TP_ADJUSTMENT)
        
        # Ensure TP maintains a minimum R:R relative to SL
        if TP_MULTIPLIER and sl_points > 0:
            tp_points = max(tp_points, int(round(sl_points * TP_MULTIPLIER)))
        
        # Slightly wider targets for sideways regime to avoid chop exits
        if self.get_market_regime(indicators) == "SIDEWAYS":
            tp_points = max(tp_points, int(round(sl_points * 1.8)))
        
        quantity = CE_QUANTITY if direction == "CE" else PE_QUANTITY
        
        return {
            "sl_points": sl_points,
            "tp_points": tp_points,
            "quantity": quantity,
            "use_runner": False,
            "use_trailing": False,  # DISABLED
            "trail_at_1x_sl": False,  # DISABLED
            "partial_tp_at_70pct": False,  # DISABLED
            "confidence": confidence,
            "regime": self.get_market_regime(indicators)
        }


# Singleton instance
_strategy_instance = None

def get_strategy() -> SmartScalpV3:
    """Get or create strategy singleton"""
    global _strategy_instance
    if _strategy_instance is None:
        _strategy_instance = SmartScalpV3()
    return _strategy_instance


def smart_scalp_signal(ticks: List[Dict]) -> Tuple[bool, str, Dict]:
    """
    Main entry point for SMART SCALP v3.4 signal.
    Used by entry_engine.py
    
    Returns:
        (should_enter, message, params)
    """
    strategy = get_strategy()
    signal, direction, confidence, details = strategy.generate_signal(ticks)
    
    if signal == 0:
        if runtime_state is not None:
            runtime_state.update_market_snapshot(
                {
                    "delta": details.get("delta"),
                    "oi_direction": details.get("oi_direction"),
                    "oi_change_pct": details.get("oi_change_pct"),
                    "market_quality": details.get("market_quality"),
                    "market_quality_grade": details.get("market_quality_grade"),
                    "spread": (ticks[-1] or {}).get("spread") if ticks else None,
                }
            )
            runtime_state.set_strategy_decision(
                signal=False,
                direction=direction or "",
                score=details.get("weighted_score"),
                confidence=confidence,
                reject_reason=details.get("reason", "No signal"),
                mq_grade=(details.get("market_quality") or {}).get("grade") if isinstance(details.get("market_quality"), dict) else details.get("market_quality_grade"),
            )
        return False, details.get("reason", "No signal"), {
            "direction": direction or "",
            "confidence": confidence,
            "details": details,
            "factors": []
        }
    
    # Get entry parameters
    indicators = runtime_state.get_indicators() if runtime_state is not None else {}
    if not indicators:
        indicators = strategy.calculate_indicators(ticks)
    entry_params = strategy.get_entry_params(direction, confidence, indicators)
    
    # Build message
    factors = details.get("bull_factors" if direction == "CE" else "bear_factors", [])
    factors_str = " | ".join(factors[:4])  # Top 4 factors
    
    message = (
        f"SMART SCALP v3.4 | {direction} | Conf: {confidence}% | "
        f"Score: {details.get('bull_score' if direction == 'CE' else 'bear_score')} | "
        f"{factors_str}"
    )

    if runtime_state is not None:
        runtime_state.update_market_snapshot(
            {
                "delta": details.get("delta"),
                "oi_direction": details.get("oi_direction"),
                "oi_change_pct": details.get("oi_change_pct"),
                "market_quality": details.get("market_quality"),
                "market_quality_grade": details.get("market_quality_grade"),
                "spread": (ticks[-1] or {}).get("spread") if ticks else None,
                "strategy_regime": details.get("regime"),
            }
        )
        runtime_state.set_strategy_decision(
            signal=True,
            direction=direction,
            score=details.get("weighted_score"),
            confidence=confidence,
            reject_reason="",
            mq_grade=(details.get("market_quality") or {}).get("grade") if isinstance(details.get("market_quality"), dict) else details.get("market_quality_grade"),
        )
    
    return True, message, {
        "direction": direction,
        "score": details.get('weighted_score'),
        "confidence": confidence,
        # Phase 6: the explicit sizing contract, alongside (not replacing) 'score'/
        # 'confidence' above — same values, dedicated key so a consumer does not
        # need to know 'score' happens to also be a gating field.
        "sizing_inputs": details.get('sizing_inputs'),
        "sl_points": entry_params["sl_points"],
        "tp_points": entry_params["tp_points"],
        "regime": entry_params["regime"],
        "factors": factors,
        "details": details
    }
