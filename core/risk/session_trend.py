"""
Session Trend Tracker with EMA-based Regime Detection
Multi-factor trend analysis:
- Opening price displacement (1st order)
- EMA convergence/divergence (2nd order)
- Volume-weighted directional bias (3rd order)
"""

from typing import Dict, Tuple, Optional
from collections import deque
import logging


class SimpleEMA:
    """Fast EMA calculator for regime detection"""
    
    def __init__(self, period: int = 20):
        self.period = period
        self.multiplier = 2.0 / (period + 1)
        self.ema = None
        self.initialized = False
    
    def update(self, price: float) -> Optional[float]:
        """Update EMA with new price"""
        if self.ema is None:
            self.ema = price
            self.initialized = True
            return price
        
        self.ema = price * self.multiplier + self.ema * (1 - self.multiplier)
        return self.ema
    
    def get(self) -> Optional[float]:
        """Get current EMA value"""
        return self.ema if self.initialized else None


class SessionTrendTracker:
    """
    Track market trend using multi-factor analysis:
    
    Factor 1: Opening displacement (50% weight)
      - >100pts above: BULLISH
      - <-100pts below: BEARISH
      - ±100pts: SIDEWAYS
    
    Factor 2: EMA regime (30% weight)
      - Price > EMA21 > EMA50: BULLISH
      - Price < EMA21 < EMA50: BEARISH
      - Other: SIDEWAYS
    
    Factor 3: RSI extremes (20% weight)
      - RSI < 35: Overdue for bounce (CE favored)
      - RSI > 65: Overdue for drop (PE favored)
      - 35-65: Neutral
    """
    
    def __init__(self):
        self.opening_price = None
        self.session_started = False
        self.price_history = deque(maxlen=200)  # Increased for EMA accuracy
        
        # Primary trend (from multiple factors)
        self.current_trend = "NEUTRAL"
        self.confidence = 0
        self.short_term_trend = "NEUTRAL"
        self.last_rsi = 50
        
        # EMA-based regime (new)
        self.ema_fast = SimpleEMA(period=9)    # Fast trend
        self.ema_medium = SimpleEMA(period=21)  # Medium trend
        self.ema_slow = SimpleEMA(period=50)   # Slow trend
        self.ema_regime = "NEUTRAL"
        
        # Factor scores
        self.opening_factor_score = 0
        self.ema_factor_score = 0
        self.rsi_factor_score = 0
        
        self.logger = logging.getLogger(__name__)
    
    def start_session(self, opening_price: float):
        """Start new trading session"""
        self.opening_price = opening_price
        self.session_started = True
        self.price_history.clear()
        self.price_history.append(opening_price)
        
        # Reset EMAs
        self.ema_fast = SimpleEMA(period=9)
        self.ema_medium = SimpleEMA(period=21)
        self.ema_slow = SimpleEMA(period=50)
        
        # Initialize EMAs with opening price
        self.ema_fast.update(opening_price)
        self.ema_medium.update(opening_price)
        self.ema_slow.update(opening_price)
        
        self.current_trend = "NEUTRAL"
        self.short_term_trend = "NEUTRAL"
        self.confidence = 0
        self.last_rsi = 50
        
        self.logger.info(f"Session started: Opening ₹{opening_price:.0f}")
    
    def _calculate_ema_regime(self, current_price: float) -> str:
        """
        Calculate trend based on EMA crossovers.
        
        BULLISH: Price above EMA21, EMA21 above EMA50
        BEARISH: Price below EMA21, EMA21 below EMA50
        SIDEWAYS: Mixed signals or convergence
        """
        ema_fast = self.ema_fast.get()
        ema_medium = self.ema_medium.get()
        ema_slow = self.ema_slow.get()
        
        if not all([ema_fast, ema_medium, ema_slow]):
            return "NEUTRAL"
        
        # Strong bullish alignment
        if (current_price > ema_fast > ema_medium > ema_slow):
            return "BULLISH"
        
        # Strong bearish alignment
        if (current_price < ema_fast < ema_medium < ema_slow):
            return "BEARISH"
        
        # Price above medium EMA
        if current_price > ema_medium and ema_medium > ema_slow:
            return "BULLISH_WEAK"
        
        # Price below medium EMA
        if current_price < ema_medium and ema_medium < ema_slow:
            return "BEARISH_WEAK"
        
        return "SIDEWAYS"
    
    def _combine_trend_factors(self, opening_displacement: str, 
                              ema_regime: str, rsi_signal: str) -> Tuple[str, int]:
        """
        Combine multiple trend factors with weighted scoring.
        
        Returns:
            (trend, confidence_0_100)
        """
        scores = {'BULLISH': 0, 'BEARISH': 0, 'SIDEWAYS': 0}
        
        # Factor 1: Opening displacement (50% weight)
        if opening_displacement == "BULLISH":
            scores['BULLISH'] += 50
        elif opening_displacement == "BEARISH":
            scores['BEARISH'] += 50
        else:
            scores['SIDEWAYS'] += 50
        
        # Factor 2: EMA regime (30% weight)
        if ema_regime in ("BULLISH", "BULLISH_WEAK"):
            scores['BULLISH'] += 30 if ema_regime == "BULLISH" else 15
        elif ema_regime in ("BEARISH", "BEARISH_WEAK"):
            scores['BEARISH'] += 30 if ema_regime == "BEARISH" else 15
        else:
            scores['SIDEWAYS'] += 20
        
        # Factor 3: RSI extremes (20% weight)
        if rsi_signal == "BULLISH":
            scores['BULLISH'] += 15
        elif rsi_signal == "BEARISH":
            scores['BEARISH'] += 15
        else:
            scores['SIDEWAYS'] += 10
        
        # Find dominant trend
        max_trend = max(scores, key=scores.get)
        confidence = min(100, scores[max_trend])
        
        return max_trend, confidence
    
    def update_price(self, current_price: float) -> str:
        """
        Update price and recalculate trend using multi-factor analysis.
        
        Returns:
            Current trend: BULLISH, BEARISH, or SIDEWAYS
        """
        if not self.session_started or self.opening_price is None:
            return "NEUTRAL"
        
        self.price_history.append(current_price)
        
        # Update all EMAs
        self.ema_fast.update(current_price)
        self.ema_medium.update(current_price)
        self.ema_slow.update(current_price)
        
        # === FACTOR 1: Opening Displacement (50% weight) ===
        price_diff = current_price - self.opening_price
        
        if price_diff > 100:
            opening_signal = "BULLISH"
            opening_conf = min(100, (price_diff / 150) * 100)
        elif price_diff < -100:
            opening_signal = "BEARISH"
            opening_conf = min(100, (abs(price_diff) / 150) * 100)
        else:
            opening_signal = "SIDEWAYS"
            opening_conf = 50
        
        self.opening_factor_score = opening_conf
        
        # === FACTOR 2: EMA Regime (30% weight) ===
        self.ema_regime = self._calculate_ema_regime(current_price)
        
        if "BULLISH" in self.ema_regime:
            self.ema_factor_score = 80 if self.ema_regime == "BULLISH" else 50
        elif "BEARISH" in self.ema_regime:
            self.ema_factor_score = 80 if self.ema_regime == "BEARISH" else 50
        else:
            self.ema_factor_score = 30
        
        # === FACTOR 3: RSI Signal (20% weight) ===
        if self.last_rsi < 35:
            rsi_signal = "BULLISH"
            self.rsi_factor_score = 70  # Strong oversold
        elif self.last_rsi > 65:
            rsi_signal = "BEARISH"
            self.rsi_factor_score = 70  # Strong overbought
        else:
            rsi_signal = "SIDEWAYS"
            self.rsi_factor_score = 40
        
        # === COMBINE FACTORS ===
        combined_trend, combined_conf = self._combine_trend_factors(
            opening_signal, self.ema_regime, rsi_signal
        )
        
        self.current_trend = combined_trend
        self.confidence = combined_conf
        
        # === SHORT-TERM MOMENTUM (for scalp entries) ===
        if len(self.price_history) >= 20:
            recent_start = list(self.price_history)[-20]
            short_diff = current_price - recent_start
            if short_diff > 25:
                self.short_term_trend = "BULLISH"
            elif short_diff < -25:
                self.short_term_trend = "BEARISH"
            else:
                self.short_term_trend = "SIDEWAYS"
        
        return self.current_trend
    
    def update_rsi(self, rsi_value: float):
        """Update RSI for reversal detection"""
        self.last_rsi = rsi_value
    
    def get_trend(self) -> Tuple[str, float]:
        """Get current trend and confidence"""
        return self.current_trend, self.confidence
    
    def can_trade_ce(self, rsi: float = None) -> bool:
        """
        Can we trade CE (buy call)?
        
        Multi-factor check:
        1. Opening displacement: BULLISH → YES
        2. EMA regime: BULLISH → YES (even if sideways opening)
        3. RSI oversold: RSI < 40 → YES (bounce potential)
        4. SIDEWAYS: YES (strategy scoring filters quality)
        """
        if rsi is not None:
            self.last_rsi = rsi
        
        # Primary bullish - strong signal
        if self.current_trend == "BULLISH" and self.confidence > 30:
            return True
        
        # EMA bullish with decent momentum
        if "BULLISH" in self.ema_regime and self.ema_factor_score > 60:
            return True
        
        # RSI oversold reversal - works in any regime
        if self.last_rsi < 40:
            return True
        
        # Short-term momentum confirmation
        if self.short_term_trend == "BULLISH":
            return True
        
        # SIDEWAYS market - allow CE since strategy handles quality filtering
        if self.current_trend == "SIDEWAYS":
            return True
        
        return False
    
    def can_trade_pe(self, rsi: float = None) -> bool:
        """
        Can we trade PE (buy put)?
        
        Multi-factor check:
        1. Opening displacement: BEARISH → YES
        2. EMA regime: BEARISH → YES (even if sideways opening)
        3. RSI overbought: RSI > 60 → YES (drop potential)
        4. SIDEWAYS: YES (strategy scoring filters quality)
        """
        if rsi is not None:
            self.last_rsi = rsi
        
        # Primary bearish - strong signal
        if self.current_trend == "BEARISH" and self.confidence > 30:
            return True
        
        # EMA bearish with decent momentum
        if "BEARISH" in self.ema_regime and self.ema_factor_score > 60:
            return True
        
        # RSI overbought reversal - works in any regime
        if self.last_rsi > 60:
            return True
        
        # Short-term momentum confirmation
        if self.short_term_trend == "BEARISH":
            return True
        
        # SIDEWAYS market - allow PE since strategy handles quality filtering
        if self.current_trend == "SIDEWAYS":
            return True
        
        return False
    
    def get_trend_emoji(self) -> str:
        """Get emoji for trend display"""
        if self.current_trend == "BULLISH":
            return "📈"
        elif self.current_trend == "BEARISH":
            return "📉"
        else:
            return "➡️"
    
    def get_trend_string(self) -> str:
        """Get formatted trend string with EMA regime info"""
        emoji = self.get_trend_emoji()
        trend_str = f"{emoji} {self.current_trend} ({self.confidence:.0f}%)"
        
        # Add EMA regime indicator
        if "BULLISH" in self.ema_regime:
            trend_str += " [EMA↗]"
        elif "BEARISH" in self.ema_regime:
            trend_str += " [EMA↘]"
        else:
            trend_str += " [EMA➡]"
        
        return trend_str
    
    def get_detailed_analysis(self) -> Dict:
        """Get detailed trend analysis for diagnostics"""
        return {
            'trend': self.current_trend,
            'confidence': self.confidence,
            'opening_displacement': self.opening_price,
            'opening_factor': self.opening_factor_score,
            'ema_regime': self.ema_regime,
            'ema_factor': self.ema_factor_score,
            'ema_fast': self.ema_fast.get(),
            'ema_medium': self.ema_medium.get(),
            'ema_slow': self.ema_slow.get(),
            'rsi_factor': self.rsi_factor_score,
            'short_term_trend': self.short_term_trend
        }

# Global instance
_session_tracker = SessionTrendTracker()

def start_trading_session(opening_price: float):
    """Start new trading session"""
    _session_tracker.start_session(opening_price)

def update_market_price(current_price: float) -> str:
    """Update current price and get trend"""
    return _session_tracker.update_price(current_price)

def get_session_trend() -> Tuple[str, float]:
    """Get current session trend"""
    return _session_tracker.get_trend()

def can_trade_ce(rsi: float = None) -> Tuple[bool, str]:
    """Can we trade CE?"""
    can_trade = _session_tracker.can_trade_ce(rsi)
    trend_str = _session_tracker.get_trend_string()
    
    if can_trade:
        if _session_tracker.current_trend not in ("BULLISH", "SIDEWAYS") and rsi and rsi < 40:
            return True, f"CE OK (RSI reversal: {rsi:.0f}) {trend_str}"
        return True, f"CE OK {trend_str}"
    else:
        return False, f"CE SKIP (not bullish) {trend_str}"

def can_trade_pe(rsi: float = None) -> Tuple[bool, str]:
    """Can we trade PE?"""
    can_trade = _session_tracker.can_trade_pe(rsi)
    trend_str = _session_tracker.get_trend_string()
    
    if can_trade:
        if _session_tracker.current_trend not in ("BEARISH", "SIDEWAYS") and rsi and rsi > 60:
            return True, f"PE OK (RSI reversal: {rsi:.0f}) {trend_str}"
        return True, f"PE OK {trend_str}"
    else:
        return False, f"PE SKIP (not bearish) {trend_str}"

def get_trend_display() -> str:
    """Get formatted trend for display"""
    return _session_tracker.get_trend_string()

def get_opening_price() -> float:
    """Get session opening price"""
    return _session_tracker.opening_price if _session_tracker.session_started else 0
