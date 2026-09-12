"""REST market data: LTP, quotes, batch quotes, option Greeks, historical candles,
symbol search/token resolution (with a 24h symbol cache) and the shared rate-limit /
circuit-breaker / login-guard helpers every REST call in this package goes through.

Mixed into AngelOneClient — methods here use self.smart_api, self.logger,
self.symbol_cache/symbol_cache_ttl/symbol_cache_ttl_sec, self._api_cooldown_until/
_api_error_count/_api_error_threshold/_api_cooldown_duration, self.latest_ticks,
self.last_call_time, self.is_logged_in.
"""

import io
import sys
import time
from typing import Dict, List, Optional

from .exceptions import AngelOneApiError

RATE_LIMITS = {
    'login': 1,
    'generateTokens': 1,
    'getProfile': 3,
    'getRMS': 2,
    'placeOrder': 9,
    'modifyOrder': 9,
    'cancelOrder': 9,
    'getOrderBook': 1,
    'getLtpData': 10,
    'getPosition': 1,
    'getTradeBook': 1,
    'quote': 10,
    'optionGreek': 1,
    'getCandleData': 3
}


class MarketDataRestMixin:

    # =========================================================================
    # SHARED HELPERS (login guard + rate limiting)
    # =========================================================================

    def _ensure_logged_in(self):
        """Ensure client is logged in"""
        if not self.is_logged_in:
            raise AngelOneApiError("Not logged in. Call login() first.")

    def _rate_limit(self, endpoint: str):
        """Apply rate limiting"""
        if endpoint in RATE_LIMITS:
            last_time = self.last_call_time.get(endpoint, 0)
            min_interval = 1.0 / RATE_LIMITS[endpoint]
            elapsed = time.time() - last_time

            if elapsed < min_interval:
                sleep_time = min_interval - elapsed
                time.sleep(sleep_time)

        self.last_call_time[endpoint] = time.time()

    # =========================================================================
    # MARKET DATA
    # =========================================================================

    def get_ltp(self, exchange: str, symbol: str, symbol_token: str, max_retries: int = 3) -> Optional[float]:
        """
        Get Last Traded Price with retry logic and circuit breaker

        Args:
            exchange: Exchange code
            symbol: Trading symbol
            symbol_token: Symbol token
            max_retries: Max retries on rate limit (default 3)

        Returns:
            LTP as float or None
        """
        # Circuit breaker check - skip API call during cooldown
        current_time = time.time()
        if current_time < self._api_cooldown_until:
            return None  # Silently return during cooldown

        for attempt in range(max_retries):
            self._rate_limit('getLtpData')
            self._ensure_logged_in()

            try:
                response = self.smart_api.ltpData(exchange, symbol, symbol_token)
                # DEBUG: Log raw response to diagnose stale data
                self.logger.debug(f"[LTP RAW] {symbol}: {response}")
                if response and response.get('status') and response.get('data'):
                    ltp = float(response['data'].get('ltp', 0))
                    # Log if LTP seems stale (same as previous)
                    prev_ltp = getattr(self, '_prev_ltp', {}).get(symbol)
                    if prev_ltp and abs(ltp - prev_ltp) < 0.01:
                        self.logger.debug(f"[LTP UNCHANGED] {symbol}: ₹{ltp:.2f}")
                    if not hasattr(self, '_prev_ltp'):
                        self._prev_ltp = {}
                    self._prev_ltp[symbol] = ltp
                    # Reset circuit breaker on success
                    self._api_error_count = 0
                    return ltp

                # Check for rate limit error in response
                if response and 'Access denied' in str(response.get('message', '')):
                    wait_time = (2 ** attempt) * 2  # Exponential backoff: 2, 4, 8 seconds
                    self.logger.warning(f"⏳ Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue

                return None
            except Exception as e:
                error_msg = str(e)
                if 'Access denied' in error_msg or 'rate' in error_msg.lower():
                    wait_time = (2 ** attempt) * 2
                    self.logger.warning(f"⏳ Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue

                # Network error - apply circuit breaker
                self._api_error_count += 1
                if self._api_error_count == 1:
                    # Log first error
                    self.logger.error(f"LTP error for {symbol}: {e}")
                elif self._api_error_count == self._api_error_threshold:
                    # Enter cooldown mode
                    self._api_cooldown_until = time.time() + self._api_cooldown_duration
                    self.logger.warning(f"🔌 Circuit breaker triggered: {self._api_error_count} consecutive errors. Cooldown for {self._api_cooldown_duration}s")
                # Skip logging intermediate errors to reduce spam
                return None

        self.logger.error(f"LTP failed after {max_retries} retries for {symbol}")
        return None

    def get_quote(
        self,
        exchange_tokens: Dict[str, List[str]],
        mode: str = "LTP"
    ) -> Dict:
        """
        Get market quote data

        Args:
            exchange_tokens: Dict of exchange -> list of tokens
                Example: {"NFO": ["12345", "12346"], "NSE": ["3045"]}
            mode: LTP, OHLC, or FULL

        Returns:
            Quote data
        """
        self._rate_limit('quote')
        self._ensure_logged_in()

        try:
            # SmartAPI expects mode and exchangeTokens as separate args
            response = self.smart_api.getMarketData(mode, exchange_tokens)
            if response and response.get('status'):
                return response.get('data', {})
            return {}
        except Exception as e:
            self.logger.error(f"Quote error: {e}")
            return {}

    def get_ltp_batch(
        self,
        symbols_data: List[Dict],
        exchange: str = "NFO",
        mode: str = "OHLC",
        max_retries: int = 3
    ) -> Dict[str, Optional[float]]:
        """
        Get LTP for multiple symbols in ONE API call using batch Market Data API

        PHASE 2 OPTIMIZATION: 99% API reduction (50 symbols → 1 request)

        Args:
            symbols_data: List of dicts with 'symbol' and 'token' keys
                Example: [{'symbol': 'NIFTY03FEB2625400CE', 'token': '49801'}, ...]
            exchange: Exchange code (NFO, NSE, etc.)
            mode: OHLC or FULL (LTP already handled by get_ltp)
            max_retries: Max retries on rate limit

        Returns:
            Dict of symbol -> ltp: {'NIFTY03FEB2625400CE': 125.50, ...}
        """
        if not symbols_data:
            return {}

        # Batch into groups of 50 (SmartAPI limit)
        batch_size = 50
        all_ltps = {}

        for batch_idx in range(0, len(symbols_data), batch_size):
            batch = symbols_data[batch_idx:batch_idx + batch_size]
            tokens = [item['token'] for item in batch if 'token' in item]

            if not tokens:
                continue

            for attempt in range(max_retries):
                self._rate_limit('quote')  # Use quote rate limit (10 req/sec)
                self._ensure_logged_in()

                try:
                    # Build exchange_tokens dict for batch
                    exchange_tokens = {exchange: tokens}

                    # Call market data API with batch
                    response = self.smart_api.getMarketData(mode, exchange_tokens)

                    if response and response.get('status'):
                        data = response.get('data', {})

                        # Extract LTP from response
                        # Response format: {exchange: {token: {ltp, ohlc, ...}}}
                        exchange_data = data.get(exchange, {})

                        for item in batch:
                            token = item.get('token')
                            symbol = item.get('symbol')

                            if token and symbol:
                                token_data = exchange_data.get(token, {})
                                ltp = None

                                if mode == "LTP":
                                    ltp = token_data.get('ltp')
                                elif mode == "OHLC":
                                    # Get close from OHLC or fallback to LTP
                                    ohlc = token_data.get('ohlc', {})
                                    ltp = ohlc.get('close') or token_data.get('ltp')
                                else:  # FULL mode
                                    ltp = token_data.get('ltp')

                                if ltp:
                                    all_ltps[symbol] = float(ltp)
                                else:
                                    all_ltps[symbol] = None

                        break  # Success, move to next batch

                    # Check for rate limit in response
                    if response and 'Access denied' in str(response.get('message', '')):
                        wait_time = (2 ** attempt) * 2
                        self.logger.warning(f"⏳ Batch rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue

                except Exception as e:
                    error_msg = str(e)
                    if 'Access denied' in error_msg or 'rate' in error_msg.lower():
                        wait_time = (2 ** attempt) * 2
                        self.logger.warning(f"⏳ Batch rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue

                    self.logger.error(f"Batch LTP error: {e}")
                    break

            # Log optimization savings
            if batch:
                self.logger.debug(f"📦 Batch {batch_idx // batch_size + 1}: {len(tokens)} symbols in 1 request (saved {len(tokens) - 1} API calls)")

        return all_ltps

    def get_market_tick(self, symbol: str, exchange: str = "NFO") -> Optional[Dict]:
        """
        Get real-time tick data for a symbol

        Args:
            symbol: Trading symbol
            exchange: Exchange code

        Returns:
            Tick dict with ltp, bid, ask, volume
        """
        symbol_token = self.get_symbol_token(symbol, exchange)
        if not symbol_token:
            return None

        ltp = self.get_ltp(exchange, symbol, symbol_token)
        if ltp is None:
            return None

        # Estimate spread (0.1% of LTP)
        spread = ltp * 0.001

        tick = {
            'timestamp': int(time.time() * 1000),
            'ltp': ltp,
            'bid': round(ltp - spread/2, 2),
            'ask': round(ltp + spread/2, 2),
            'volume': 0,  # Not available from LTP endpoint
            'symbol': symbol,
            'exchange': exchange,
            'symbol_token': symbol_token
        }

        self.latest_ticks[symbol] = tick
        return tick

    # =========================================================================
    # OPTION GREEKS
    # =========================================================================

    def get_option_greeks(
        self,
        underlying: str,
        expiry_date: str,
        max_retries: int = 3
    ) -> List[Dict]:
        """
        Get option Greeks for all strikes of an underlying

        Args:
            underlying: Underlying name (e.g., "NIFTY", "BANKNIFTY")
            expiry_date: Expiry date in format "25JAN2024"
            max_retries: Max retries on rate limit (default 3)

        Returns:
            List of Greeks data for each strike
        """
        for attempt in range(max_retries):
            self._rate_limit('optionGreek')
            self._ensure_logged_in()

            try:
                params = {
                    "name": underlying,
                    "expirydate": expiry_date
                }

                response = self.smart_api.optionGreek(params)
                if response and response.get('status'):
                    return response.get('data', []) or []

                # Check for rate limit error
                if response and 'Access denied' in str(response.get('message', '')):
                    wait_time = (2 ** attempt) * 2
                    self.logger.warning(f"⏳ Greeks rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue

                return []
            except Exception as e:
                error_msg = str(e)
                if 'Access denied' in error_msg or 'rate' in error_msg.lower():
                    wait_time = (2 ** attempt) * 2
                    self.logger.warning(f"⏳ Greeks rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                self.logger.error(f"Option Greeks error: {e}")
                return []

        self.logger.warning(f"Greeks failed after {max_retries} retries")
        return []

    # =========================================================================
    # HISTORICAL DATA
    # =========================================================================

    def get_candle_data(
        self,
        symbol_token: str,
        exchange: str,
        interval: str,
        from_date: str,
        to_date: str
    ) -> List[Dict]:
        """
        Get historical candle data

        Args:
            symbol_token: Symbol token
            exchange: Exchange code
            interval: ONE_MINUTE, FIVE_MINUTE, TEN_MINUTE, FIFTEEN_MINUTE,
                     THIRTY_MINUTE, ONE_HOUR, ONE_DAY
            from_date: Start date "YYYY-MM-DD HH:MM"
            to_date: End date "YYYY-MM-DD HH:MM"

        Returns:
            List of candle data
        """
        self._rate_limit('getCandleData')
        self._ensure_logged_in()

        try:
            params = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "interval": interval,
                "fromdate": from_date,
                "todate": to_date
            }

            response = self.smart_api.getCandleData(params)
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Candle data error: {e}")
            return []

    # =========================================================================
    # SYMBOL UTILITIES
    # =========================================================================

    def _is_symbol_cache_valid(self, cache_key: str) -> bool:
        """Check if symbol cache entry is still valid (Phase 3 TTL check)"""
        if cache_key not in self.symbol_cache_ttl:
            return False
        return time.time() < self.symbol_cache_ttl[cache_key]

    def _get_cached_symbol_token(self, cache_key: str) -> Optional[str]:
        """
        Get symbol token from cache if valid (Phase 3 optimization)

        Args:
            cache_key: Formatted as "EXCHANGE:SYMBOL"

        Returns:
            Symbol token or None if expired/not found
        """
        if self._is_symbol_cache_valid(cache_key):
            return self.symbol_cache[cache_key]

        # Cache expired, remove it
        if cache_key in self.symbol_cache:
            del self.symbol_cache[cache_key]
            del self.symbol_cache_ttl[cache_key]

        return None

    def _cache_symbol_token(self, cache_key: str, token: str) -> None:
        """
        Cache symbol token with 24-hour TTL (Phase 3)

        Args:
            cache_key: Formatted as "EXCHANGE:SYMBOL"
            token: Symbol token to cache
        """
        self.symbol_cache[cache_key] = token
        self.symbol_cache_ttl[cache_key] = time.time() + self.symbol_cache_ttl_sec

    def clear_symbol_cache(self) -> None:
        """Clear all symbol cache entries"""
        self.symbol_cache.clear()
        self.symbol_cache_ttl.clear()
        self.logger.debug("Symbol cache cleared")

    def get_symbol_token(self, symbol: str, exchange: str = "NFO") -> Optional[str]:
        """
        Get symbol token (required for most API calls)
        PHASE 3: Uses 24-hour symbol cache to reduce searchScrip calls by 96%

        Args:
            symbol: Trading symbol
            exchange: Exchange code

        Returns:
            Symbol token string or None
        """
        cache_key = f"{exchange}:{symbol}"

        # Check Phase 3 cache first (24-hour TTL)
        cached_token = self._get_cached_symbol_token(cache_key)
        if cached_token:
            self.logger.debug(f"📦 Symbol cache HIT: {symbol} → {cached_token}")
            return cached_token

        # Circuit breaker check - skip API call during cooldown
        if time.time() < self._api_cooldown_until:
            return None  # Silently return during cooldown

        try:
            # Suppress SmartAPI SDK's verbose print statements
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()  # Capture stdout

            try:
                result = self.smart_api.searchScrip(exchange=exchange, searchscrip=symbol)
            finally:
                sys.stdout = old_stdout  # Restore stdout

            if result and result.get('status') and result.get('data'):
                for item in result['data']:
                    if item.get('tradingsymbol') == symbol or item.get('symbol') == symbol:
                        token = item.get('symboltoken') or item.get('token')
                        if token:
                            # Cache with 24-hour TTL (Phase 3)
                            self._cache_symbol_token(cache_key, token)
                            self.logger.debug(f"📦 Symbol cache SET: {symbol} → {token} (24h TTL)")
                            # Reset circuit breaker on success
                            self._api_error_count = 0
                            return token
            return None
        except Exception as e:
            # Network error - apply circuit breaker
            self._api_error_count += 1
            if self._api_error_count == 1:
                # Log first error
                self.logger.error(f"Symbol token search error for {symbol}: {e}")
            elif self._api_error_count == self._api_error_threshold:
                # Enter cooldown mode
                self._api_cooldown_until = time.time() + self._api_cooldown_duration
                self.logger.warning(f"🔌 Circuit breaker triggered: {self._api_error_count} consecutive errors. Cooldown for {self._api_cooldown_duration}s")
            # Skip logging intermediate errors to reduce spam
            return None

    def search_symbol(self, search_term: str, exchange: str = "NFO") -> List[Dict]:
        """
        Search for symbols (with suppressed verbose SDK output)

        Args:
            search_term: Search string
            exchange: Exchange code

        Returns:
            List of matching symbols
        """
        try:
            # Suppress SmartAPI SDK's verbose print statements
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()  # Capture stdout

            try:
                result = self.smart_api.searchScrip(exchange=exchange, searchscrip=search_term)
            finally:
                sys.stdout = old_stdout  # Restore stdout

            if result and result.get('status'):
                return result.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Symbol search error: {e}")
            return []

    def get_instrument_list(self) -> List[Dict]:
        """
        Fetch the full list of tradable instruments.

        Returns:
            A list of instrument dictionaries.
        """
        self._ensure_logged_in()
        try:
            # The smartapi-python library downloads this from a static URL
            # so it doesn't have a rate limit in the same way as other API calls.
            instrument_list = self.smart_api.getInstruments()
            if isinstance(instrument_list, list) and len(instrument_list) > 0:
                self.logger.info(f"Fetched {len(instrument_list)} instruments.")
                return instrument_list
            else:
                self.logger.error("Failed to fetch instrument list or list is empty.")
                return []
        except Exception as e:
            self.logger.error(f"Error fetching instrument list: {e}", exc_info=True)
            return []
