"""
Session Trend Tracker
Smart trend detection with pullback support
"""

from typing import Dict, Tuple
from collections import deque

class SessionTrendTracker:
    """
    Track market trend based on opening price + short-term momentum
    - Primary trend from opening price
    - Allows counter-trend trades on strong pullbacks/bounces
    """
    
    def __init__(self):
        self.opening_price = None
        self.session_started = False
        self.price_history = deque(maxlen=100)
        self.current_trend = "NEUTRAL"
        self.confidence = 0
        self.short_term_trend = "NEUTRAL"  # 5-minute trend
        self.last_rsi = 50
    
    def start_session(self, opening_price: float):
        """Start new trading session"""
        self.opening_price = opening_price
        self.session_started = True
        self.price_history.clear()
        self.price_history.append(opening_price)
        self.current_trend = "NEUTRAL"
        self.short_term_trend = "NEUTRAL"
        self.confidence = 0
        self.last_rsi = 50
    
    def update_price(self, current_price: float) -> str:
        """Update price and return current trend"""
        
        if not self.session_started or self.opening_price is None:
            return "NEUTRAL"
        
        self.price_history.append(current_price)
        
        # Calculate difference from opening
        price_diff = current_price - self.opening_price
        diff_pct = (price_diff / self.opening_price) * 100
        
        # BUG FIX #10: Increased threshold from 50 to 100 points
        # NIFTY typically moves 100-300 points/day, 50 was too sensitive
        # Primary trend (from opening)
        if price_diff > 100:  # More than 100 points above opening
            self.current_trend = "BULLISH"
            self.confidence = min(100, (price_diff / 150) * 100)
        elif price_diff < -100:  # More than 100 points below opening
            self.current_trend = "BEARISH"
            self.confidence = min(100, (abs(price_diff) / 150) * 100)
        else:  # Within 100 points of opening
            self.current_trend = "SIDEWAYS"
            self.confidence = 50
        
        # Short-term trend (last 20 prices ~ 10 seconds)
        # Also increased threshold from 15 to 25 points
        if len(self.price_history) >= 20:
            recent_start = list(self.price_history)[-20]
            short_diff = current_price - recent_start
            if short_diff > 25:  # 25 points up in short term
                self.short_term_trend = "BULLISH"
            elif short_diff < -25:  # 25 points down
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
        
        v3.3: Relaxed to enable dual-direction trading (was PE-only bias)
        
        YES if:
        1. Primary trend is BULLISH, OR
        2. (SIDEWAYS or BEARISH) + RSI < 40 (oversold reversal - relaxed from 35), OR
        3. Short-term trend is BULLISH with momentum, OR
        4. SIDEWAYS market (allow CE since strategy scoring handles quality)
        """
        if rsi is not None:
            self.last_rsi = rsi
        
        # 1. Primary bullish - always OK
        if self.current_trend == "BULLISH" and self.confidence > 30:
            return True
        
        # 2. Reversal trade: RSI oversold in bearish/sideways market (relaxed from 35 to 40)
        if self.last_rsi < 40:
            return True  # Allow CE on oversold bounce
        
        # 3. Short-term bullish momentum
        if self.short_term_trend == "BULLISH":
            return True
        
        # 4. SIDEWAYS market: allow CE trades (v3.3 - dual direction)
        # Strategy scoring already ensures quality; trend filter shouldn't block
        if self.current_trend == "SIDEWAYS":
            return True
        
        return False
    
    def can_trade_pe(self, rsi: float = None) -> bool:
        """
        Can we trade PE (buy put)?
        
        v3.3: Relaxed for dual-direction trading
        
        YES if:
        1. Primary trend is BEARISH, OR
        2. (SIDEWAYS or BULLISH) + RSI > 60 (overbought reversal - relaxed from 65), OR
        3. Short-term trend is BEARISH with momentum, OR
        4. SIDEWAYS market (allow PE since strategy scoring handles quality)
        """
        if rsi is not None:
            self.last_rsi = rsi
        
        # 1. Primary bearish - always OK
        if self.current_trend == "BEARISH" and self.confidence > 30:
            return True
        
        # 2. Reversal trade: RSI overbought in bullish/sideways market (relaxed from 65 to 60)
        if self.last_rsi > 60:
            return True  # Allow PE on overbought drop
        
        # 3. Short-term bearish momentum
        if self.short_term_trend == "BEARISH":
            return True
        
        # 4. SIDEWAYS market: allow PE trades (v3.3 - dual direction)
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
        """Get formatted trend string"""
        emoji = self.get_trend_emoji()
        return f"{emoji} {self.current_trend} ({self.confidence:.0f}%)"

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
