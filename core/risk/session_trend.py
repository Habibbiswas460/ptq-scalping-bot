"""
Session Trend Tracker
Simple opening-based trend detection
"""

from typing import Dict, Tuple
from collections import deque

class SessionTrendTracker:
    """
    Track market trend based on opening price
    - If price > opening: BULLISH
    - If price < opening: BEARISH
    - If near opening: SIDEWAYS
    """
    
    def __init__(self):
        self.opening_price = None
        self.session_started = False
        self.price_history = deque(maxlen=100)
        self.current_trend = "NEUTRAL"
        self.confidence = 0
    
    def start_session(self, opening_price: float):
        """Start new trading session"""
        self.opening_price = opening_price
        self.session_started = True
        self.price_history.clear()
        self.price_history.append(opening_price)
        self.current_trend = "NEUTRAL"
        self.confidence = 0
    
    def update_price(self, current_price: float) -> str:
        """Update price and return current trend"""
        
        if not self.session_started or self.opening_price is None:
            return "NEUTRAL"
        
        self.price_history.append(current_price)
        
        # Calculate difference from opening
        price_diff = current_price - self.opening_price
        diff_pct = (price_diff / self.opening_price) * 100
        
        # Determine trend
        if price_diff > 50:  # More than 50 points above opening
            self.current_trend = "BULLISH"
            self.confidence = min(100, (price_diff / 100) * 100)  # Stronger as it goes higher
        elif price_diff < -50:  # More than 50 points below opening
            self.current_trend = "BEARISH"
            self.confidence = min(100, (abs(price_diff) / 100) * 100)
        else:  # Within 50 points of opening
            self.current_trend = "SIDEWAYS"
            self.confidence = 50
        
        return self.current_trend
    
    def get_trend(self) -> Tuple[str, float]:
        """Get current trend and confidence"""
        return self.current_trend, self.confidence
    
    def can_trade_ce(self) -> bool:
        """Can we trade CE (buy call)?"""
        # Only trade CE in BULLISH trend
        return self.current_trend == "BULLISH" and self.confidence > 40
    
    def can_trade_pe(self) -> bool:
        """Can we trade PE (buy put)?"""
        # Only trade PE in BEARISH trend
        return self.current_trend == "BEARISH" and self.confidence > 40
    
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

def can_trade_ce() -> Tuple[bool, str]:
    """Can we trade CE?"""
    can_trade = _session_tracker.can_trade_ce()
    trend_str = _session_tracker.get_trend_string()
    
    if can_trade:
        return True, f"CE OK {trend_str}"
    else:
        return False, f"CE SKIP (not bullish) {trend_str}"

def can_trade_pe() -> Tuple[bool, str]:
    """Can we trade PE?"""
    can_trade = _session_tracker.can_trade_pe()
    trend_str = _session_tracker.get_trend_string()
    
    if can_trade:
        return True, f"PE OK {trend_str}"
    else:
        return False, f"PE SKIP (not bearish) {trend_str}"

def get_trend_display() -> str:
    """Get formatted trend for display"""
    return _session_tracker.get_trend_string()

def get_opening_price() -> float:
    """Get session opening price"""
    return _session_tracker.opening_price if _session_tracker.session_started else 0
