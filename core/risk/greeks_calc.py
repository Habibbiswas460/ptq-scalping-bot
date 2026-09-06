"""
PTQ Scalping Bot - Greeks from Angel One API
Fetches real-time Greeks from Angel One SmartAPI
Falls back to BSM calculation if API fails
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
import time

from config.constants import CONFIG

# Fallback calculator
from utils.greeks import GreeksCalculator


# Disable API Greeks - Angel One API is unreliable, BSM works better
USE_API_GREEKS = False

_expiry_warned = False


def _resolve_expiry_time() -> datetime:
    """When the front contract expires, at the 15:30 close.

    Read from the broker's instrument master (utils/expiry.py). The three places that
    used to compute this each rolled forward to the next Thursday; NIFTY weeklies expire
    on Tuesday, so every time-to-expiry derived here - and with it theta, gamma and
    detect_day_type()'s reading of the session - was two days long.

    With no instrument master there is no honest answer. Rather than invent a weekday,
    fall back to today's close, which reads as maximally near expiry: theta and gamma
    come out large and the day is classified EXPIRY, tightening the risk rules. That is
    the safe direction to be wrong in, and it only happens when the bot has never
    reached the broker, in which case it is not trading anyway.
    """
    global _expiry_warned
    from utils.expiry import describe, expiry_datetime

    when = expiry_datetime()
    if when:
        return when

    if not _expiry_warned:
        _expiry_warned = True
        print(f"[greeks] no expiry from the instrument master ({describe()}); "
              f"treating the current session as expiry day")
    return datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)


class GreeksFetcher:
    """Fetch Greeks from Angel One API"""
    
    def __init__(self, broker_client=None):
        self.broker_client = broker_client
        self.cached_greeks: Dict[str, Dict] = {}
        self.cache_expiry: Dict[str, float] = {}
        self.cache_duration = 60  # Cache for 60 seconds (reduced API calls)
        self.last_api_call = 0
        self.rate_limit_interval = 5  # 5 seconds between API calls (avoid rate limit)
        
    def set_broker(self, broker_client):
        """Set broker client"""
        self.broker_client = broker_client
        
    def get_expiry_date_str(self) -> str:
        """Expiry in API format (e.g. '08SEP2026'), from the instrument master.

        Always the expiry strictly after today: Angel One serves no Greeks for a contract
        expiring the same day, which is what the old "skip to next week on expiry day"
        branch was for. It computed Thursdays, and NIFTY weeklies expire on Tuesday, so
        the date it asked for belonged to no listed contract.

        Returns "" when the master is unavailable; fetch_from_api() treats that as "no
        Greeks this cycle" rather than requesting a date nobody can honour.
        """
        from utils.expiry import next_expiry_after

        nxt = next_expiry_after()
        return nxt.strftime("%d%b%Y").upper() if nxt else ""
    
    def fetch_from_api(self, underlying: str = "NIFTY", strike_price: int = None) -> Optional[Dict]:
        """
        Fetch Greeks from Angel One API
        
        Args:
            underlying: "NIFTY" or "BANKNIFTY"
            strike_price: Specific strike to get (optional)
            
        Returns:
            Dict with delta, gamma, theta, vega, iv or None
        """
        # Skip API if disabled
        if not USE_API_GREEKS:
            return None
            
        if not self.broker_client:
            return None
            
        # Rate limiting
        now = time.time()
        if now - self.last_api_call < self.rate_limit_interval:
            # Check cache first
            cache_key = f"{underlying}_{strike_price}"
            if cache_key in self.cached_greeks:
                if now < self.cache_expiry.get(cache_key, 0):
                    return self.cached_greeks[cache_key]
            return None
            
        try:
            self.last_api_call = now
            expiry_date = self.get_expiry_date_str()
            if not expiry_date:
                # No instrument master, so no expiry to ask about. Skip rather than guess.
                return None

            # Call Angel One API
            greeks_data = self.broker_client.get_option_greeks(underlying, expiry_date)
            
            if not greeks_data:
                return None
                
            # Find matching strike
            option_type = CONFIG['trading']['option_type']  # CE or PE
            
            for item in greeks_data:
                item_strike = float(item.get('strikePrice', 0))
                item_type = item.get('optionType', '')
                
                # Match strike and option type
                if strike_price and abs(item_strike - strike_price) < 1:
                    if item_type == option_type:
                        greeks = self._parse_api_greeks(item)
                        
                        # Cache it
                        cache_key = f"{underlying}_{strike_price}"
                        self.cached_greeks[cache_key] = greeks
                        self.cache_expiry[cache_key] = now + self.cache_duration
                        
                        return greeks
            
            return None
            
        except Exception as e:
            import logging
            logging.debug(f"Greeks API error: {e}")
            return None
    
    def _parse_api_greeks(self, api_data: Dict) -> Dict[str, float]:
        """Parse API response into standard format"""
        try:
            delta = float(api_data.get('delta', 0.5))
            gamma = float(api_data.get('gamma', 0.001))
            theta = float(api_data.get('theta', -50))  # Daily theta
            vega = float(api_data.get('vega', 5))
            iv = float(api_data.get('impliedVolatility', 15))
            
            # Calculate theta per second (for scalping)
            theta_per_sec = abs(theta) / (24 * 60 * 60)
            
            return {
                'delta': delta,
                'gamma': gamma,
                'theta': theta,
                'vega': vega,
                'theta_sec': theta_per_sec,
                'iv': iv,
                'source': 'API'
            }
        except Exception:
            return None


# Global instance
_greeks_fetcher: Optional[GreeksFetcher] = None


def init_greeks_fetcher(broker_client=None):
    """Initialize Greeks fetcher with broker client"""
    global _greeks_fetcher
    _greeks_fetcher = GreeksFetcher(broker_client)


def calculate_greeks(tick: Dict, spot_price: float, current_strike: int,
                     expiry_time: datetime = None) -> Dict[str, float]:
    """
    Get option Greeks - first try API, fallback to BSM calculation
    
    Args:
        tick: Current tick data
        spot_price: NIFTY spot price
        current_strike: Strike price
        expiry_time: Option expiry time
        
    Returns:
        Dict with delta, gamma, theta, vega, theta_sec
    """
    global _greeks_fetcher
    
    # Try API first
    if _greeks_fetcher and _greeks_fetcher.broker_client:
        underlying = CONFIG['trading']['symbol']
        api_greeks = _greeks_fetcher.fetch_from_api(underlying, current_strike)
        
        if api_greeks:
            # Add time to expiry
            if not expiry_time:
                expiry_time = _resolve_expiry_time()
            
            tte_sec = GreeksCalculator.time_to_expiry_seconds(expiry_time)
            api_greeks['tte'] = max(tte_sec, 3600)
            
            return api_greeks
    
    # Fallback to BSM calculation
    return _calculate_greeks_bsm(tick, spot_price, current_strike, expiry_time)


def _calculate_greeks_bsm(tick: Dict, spot_price: float, current_strike: int,
                          expiry_time: datetime = None) -> Dict[str, float]:
    """
    Fallback: Calculate option Greeks using BSM model
    """
    # Ensure valid values
    if not spot_price or spot_price <= 0:
        spot_price = tick.get('spot_price', tick['ltp'] * 100)
    
    if not current_strike or current_strike <= 0:
        current_strike = round(spot_price / 100) * 100
    
    if not expiry_time:
        expiry_time = _resolve_expiry_time()
    
    # Calculate time to expiry
    tte_sec = GreeksCalculator.time_to_expiry_seconds(expiry_time)
    
    if tte_sec <= 0:
        tte_sec = 3600
    
    try:
        greeks = GreeksCalculator.calculate_from_ltp(
            ltp=tick['ltp'],
            spot_price=spot_price,
            strike_price=current_strike,
            time_to_expiry_sec=tte_sec,
            option_type=CONFIG['trading']['option_type']
        )
        greeks['source'] = 'BSM'
        return greeks
    except Exception:
        return {
            'delta': 0.5,
            'gamma': 0.001,
            'theta': -50.0,
            'vega': 5.0,
            'theta_sec': 0.0005,
            'tte': tte_sec,
            'source': 'DEFAULT'
        }
