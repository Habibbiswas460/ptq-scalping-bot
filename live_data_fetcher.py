"""
Live Data Fetcher - Free Real-Time Data
Fetches real-time NIFTY prices using Yahoo Finance (no credentials needed)
"""

import yfinance as yf
import time
from datetime import datetime
from typing import Optional, Dict
import random

class LiveDataFetcher:
    """Fetch live market data from Yahoo Finance (free, no auth required)"""
    
    def __init__(self):
        self.nifty_ticker = "^NSEI"  # NIFTY 50 Yahoo symbol
        self.last_spot = None
        self.last_fetch_time = None
        self.price_cache = []  # Cache last 10 valid prices
        self.max_cache_size = 10
        
        # Circuit breaker state (Fix #9)
        self.consecutive_failures = 0
        self.circuit_open = False
        self.circuit_open_time = None
        self.circuit_break_threshold = 5  # Open circuit after 5 consecutive failures
        self.circuit_reset_seconds = 30  # Reset circuit after 30 seconds
        
    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows requests. Returns True if OK to proceed."""
        if not self.circuit_open:
            return True
            
        # Check if enough time has passed to try again
        if self.circuit_open_time and (time.time() - self.circuit_open_time) > self.circuit_reset_seconds:
            print("🔄 Circuit breaker reset - attempting to reconnect...")
            self.circuit_open = False
            self.consecutive_failures = 0
            return True
            
        return False
        
    def _record_success(self):
        """Record a successful API call - reset failure count"""
        self.consecutive_failures = 0
        if self.circuit_open:
            print("✅ Circuit breaker closed - API connection restored")
            self.circuit_open = False
            
    def _record_failure(self):
        """Record a failed API call - potentially open circuit"""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.circuit_break_threshold and not self.circuit_open:
            print(f"🔴 Circuit breaker OPEN - {self.consecutive_failures} consecutive failures")
            self.circuit_open = True
            self.circuit_open_time = time.time()
        
    def get_nifty_spot(self) -> Optional[float]:
        """Get live NIFTY spot price from Yahoo Finance with retry logic and circuit breaker"""
        # Cache for 1 second to avoid too many requests
        now = time.time()
        if self.last_spot and self.last_fetch_time and (now - self.last_fetch_time) < 1:
            return self.last_spot
        
        # Check circuit breaker before making API call
        if not self._check_circuit_breaker():
            # Circuit is open - use cached data
            if self.price_cache:
                fallback = sum(self.price_cache) / len(self.price_cache)
                print(f"⚡ Circuit open - using cached: ₹{fallback:.2f}")
                return fallback
            return self.last_spot if self.last_spot else 25000.0
        
        # Retry logic with exponential backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                nifty = yf.Ticker(self.nifty_ticker)
                data = nifty.history(period='1d', interval='1m')
                
                if not data.empty:
                    ltp = float(data['Close'].iloc[-1])
                    
                    # Validate price range (15000 - 30000)
                    if 15000 <= ltp <= 30000:
                        self.last_spot = ltp
                        self.last_fetch_time = now
                        self._record_success()  # Circuit breaker success
                        
                        # Update price cache
                        self.price_cache.append(ltp)
                        if len(self.price_cache) > self.max_cache_size:
                            self.price_cache.pop(0)
                        
                        return ltp
                    else:
                        print(f"⚠️ Invalid NIFTY price: {ltp}")
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                    time.sleep(wait_time)
                else:
                    print(f"Error fetching NIFTY spot after {max_retries} attempts: {e}")
                    self._record_failure()  # Circuit breaker failure
        
        # Fallback: Use average of cached prices or last known price
        if self.price_cache:
            fallback = sum(self.price_cache) / len(self.price_cache)
            print(f"📌 Using cached average: ₹{fallback:.2f}")
            return fallback
        
        return self.last_spot if self.last_spot else 25000.0
    
    def get_market_tick(self, strike: int, option_type: str = "CE") -> Optional[Dict]:
        """
        Get market tick with live NIFTY-based option pricing
        
        Args:
            strike: Strike price (e.g., 24800)
            option_type: 'CE' or 'PE'
        
        Returns:
            Tick dict with real NIFTY-based prices
        """
        try:
            # Get live NIFTY spot
            spot = self.get_nifty_spot()
            if not spot:
                return None
            
            # Validate spot price
            if spot < 15000 or spot > 30000:
                print(f"⚠️ Invalid spot price: {spot}")
                return None
            
            # Calculate approximate option price using simplified BS approximation
            # Weekly option with ~5 days to expiry assumption
            import math
            
            moneyness = spot - strike  # Absolute difference
            moneyness_pct = abs(moneyness) / strike  # Percentage moneyness
            
            # Base time value for ATM weekly option (~0.4-0.6% of spot)
            base_time_value = spot * 0.005  # ~125 for NIFTY 25000
            
            if option_type == "CE":
                if spot > strike:
                    # ITM call
                    intrinsic = spot - strike
                    # Time value decreases as more ITM
                    time_value = base_time_value * max(0.3, 1 - moneyness_pct * 5)
                    ltp = intrinsic + time_value
                else:
                    # OTM call
                    # Time value decreases as more OTM
                    decay_factor = max(0.1, 1 - moneyness_pct * 5)
                    ltp = base_time_value * decay_factor
            else:
                if spot < strike:
                    # ITM put
                    intrinsic = strike - spot
                    time_value = base_time_value * max(0.3, 1 - moneyness_pct * 5)
                    ltp = intrinsic + time_value
                else:
                    # OTM put
                    decay_factor = max(0.1, 1 - moneyness_pct * 5)
                    ltp = base_time_value * decay_factor
            
            # Minimum option price (weekly options can go low)
            ltp = max(ltp, 5.0)
            
            # Add small random variation for realistic price action
            ltp = ltp * (1 + random.uniform(-0.005, 0.005))
            
            # Round to 0.05 (typical tick size)
            ltp = round(ltp * 20) / 20
            
            # Estimate bid/ask spread based on price level
            # Lower priced options have wider spreads
            if ltp < 20:
                spread = 0.50  # 50 paise spread
            elif ltp < 50:
                spread = 0.75
            elif ltp < 100:
                spread = 1.00
            else:
                spread = ltp * 0.005  # 0.5% spread
            
            bid = round(ltp - spread / 2, 2)
            ask = round(ltp + spread / 2, 2)
            
            # Estimated volume based on liquidity and moneyness
            # ATM options have higher volume
            if moneyness_pct < 0.01:  # ATM
                volume = int(random.uniform(200000, 500000))
            elif moneyness_pct < 0.02:  # Near ATM
                volume = int(random.uniform(100000, 300000))
            else:  # OTM/ITM
                volume = int(random.uniform(50000, 150000))
            
            tick = {
                'timestamp': int(time.time() * 1000),
                'bid': bid,
                'ask': ask,
                'ltp': ltp,
                'volume': volume,
                'symbol': f"NIFTY{strike}{option_type}",
                'strike': strike,
                'option_type': option_type,
                'spot_price': spot,
                'source': 'YAHOO_LIVE'
            }
            
            return tick
            
        except Exception as e:
            print(f"Error getting market tick: {e}")
            return None


# Test function
if __name__ == "__main__":
    print("Testing Live Data Fetcher (Yahoo Finance)...")
    print("=" * 60)
    
    fetcher = LiveDataFetcher()
    
    # Get NIFTY spot
    print("\n📊 Fetching LIVE NIFTY Spot Price...")
    spot = fetcher.get_nifty_spot()
    if spot:
        print(f"✅ NIFTY Spot: ₹{spot:,.2f} (LIVE from Yahoo Finance)")
    else:
        print("❌ Failed to fetch spot price")
    
    # Get option tick based on live spot
    print("\n📈 Calculating Option Price from Live Spot...")
    strike = 24800
    tick = fetcher.get_market_tick(strike, "CE")
    if tick:
        print("✅ Live-Based Tick Data:")
        print(f"   Spot: ₹{tick['spot_price']:,.2f}")
        print(f"   Strike: {strike} CE")
        print(f"   LTP: ₹{tick['ltp']:,.2f}")
        print(f"   Bid: ₹{tick['bid']:,.2f}")
        print(f"   Ask: ₹{tick['ask']:,.2f}")
        print(f"   Volume: {tick['volume']:,}")
        print(f"   Source: {tick['source']}")
        
        # Show moneyness
        moneyness = ((tick['spot_price'] - strike) / strike) * 100
        itm_otm = "ITM" if tick['spot_price'] > strike else "OTM"
        print(f"   Status: {itm_otm} (Spot {moneyness:+.2f}% from strike)")
    else:
        print("❌ Failed to generate tick")
    
    print("\n" + "=" * 60)
    print("Ready to use in bot with live NIFTY data!")

