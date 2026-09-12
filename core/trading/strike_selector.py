"""Strike rotation, premium-based strike search, expiry resolution and option-symbol
building — PTQ's own trading decisions about which contract to be in, not broker
plumbing. (resolve_strike_for_direction() stays on BrokerInterface itself in broker.py:
tests/test_snapquote_depth.py patches CROSS_DIRECTION_STRIKE_ENABLED/TTL_SEC as module
globals on core.trading.broker, which only reaches a function whose __globals__ is that
module — moving it here would silently stop honoring that patch.)

Mixed into BrokerInterface — uses self.spot_price/current_strike/current_symbol/
_option_token/_current_expiry, self.broker_client, self._get_token()
(defined on BrokerInterface itself), self.token_map, and the WS re-subscribe helpers
from reconnect_manager.py.
"""

import sys
import io
import time
from datetime import datetime, timedelta

from config.constants import (
    OPTION_TYPE, EXCHANGE, WS_OPTION_SUB_MODE,
    STRIKE_PREMIUM_MIN, STRIKE_PREMIUM_MAX,
)


class StrikeSelectorMixin:

    def check_and_rotate_strike(self, direction: str = None) -> bool:
        """
        Check if strike needs rotation based on PREMIUM (not just spot movement).
        Select ATM/OTM/ITM based on which has premium in ₹90-150 range.

        Guardrails:
        - Do not rotate again immediately after a recent rotation.
        - Do not churn WebSocket during reconnect / transport stress.

        Args:
            direction: 'CE' or 'PE' - if provided, rotates to this direction

        Returns:
            True if strike was rotated, False otherwise
        """
        if not self.spot_price or self.spot_price < 10000:
            return False

        if self._ws_circuit_open:
            if self.logger:
                self.logger.debug("⏳ Strike rotation skipped: WS circuit breaker is open")
            return False

        now_ts = time.time()
        if self._last_strike_rotation_time and (now_ts - self._last_strike_rotation_time) < self._strike_rotation_cooldown_sec:
            if self.logger:
                self.logger.debug(
                    "⏳ Strike rotation skipped: cooldown active for "
                    f"{self._strike_rotation_cooldown_sec}s"
                )
            return False

        if self._last_ws_ack_timeout_time and (now_ts - self._last_ws_ack_timeout_time) < self._ws_ack_timeout_cooldown_sec:
            if self.logger:
                self.logger.debug(
                    "⏳ Strike rotation skipped: recent ACK timeout stress detected "
                    f"({int(now_ts - self._last_ws_ack_timeout_time)}s ago)"
                )
            return False

        if self._last_ws_reconnect_time and (now_ts - self._last_ws_reconnect_time) < self._ws_reconnect_stress_cooldown_sec:
            if self.logger:
                self.logger.debug(
                    "⏳ Strike rotation skipped: recent reconnect churn detected "
                    f"({int(now_ts - self._last_ws_reconnect_time)}s ago)"
                )
            return False

        if self._last_ws_ack_timeout_time and (now_ts - self._last_ws_ack_timeout_time) < self._ws_ack_timeout_cooldown_sec:
            if self.logger:
                self.logger.debug(
                    "⏳ Strike rotation skipped: recent ACK timeout stress detected "
                    f"({int(now_ts - self._last_ws_ack_timeout_time)}s ago)"
                )
            return False

        opt_type = direction if direction else OPTION_TYPE

        # Get current option premium
        current_premium = 0
        with self._tick_lock:
            if self.last_tick:
                current_premium = self.last_tick.get('ltp', 0)

        # Check if premium is out of range
        need_rotation = False
        if current_premium > 0:
            if current_premium < STRIKE_PREMIUM_MIN or current_premium > STRIKE_PREMIUM_MAX:
                need_rotation = True
                self.logger.info(f"💰 Premium ₹{current_premium:.0f} out of range (₹{STRIKE_PREMIUM_MIN:.0f}-₹{STRIKE_PREMIUM_MAX:.0f}) - searching better strike...")

        # Also check spot movement (original logic)
        atm_strike = round(self.spot_price / 50) * 50
        strike_gap = abs(self.spot_price - self.current_strike)
        if strike_gap >= 50:
            need_rotation = True

        if not need_rotation:
            return False

        # Find best strike by premium
        best_strike, best_premium = self._find_strike_by_premium(opt_type)

        if best_strike and best_strike != self.current_strike:
            old_strike = self.current_strike
            old_symbol = self.current_symbol
            old_token = self._option_token

            # Update strike
            self.current_strike = best_strike
            self.current_symbol = self._build_option_symbol(self.current_strike, opt_type)
            self._option_token = self._get_token(self.current_symbol, EXCHANGE)

            strike_type = "ATM" if best_strike == atm_strike else ("OTM" if (opt_type == 'CE' and best_strike > atm_strike) or (opt_type == 'PE' and best_strike < atm_strike) else "ITM")
            self.logger.info(f"🔄 STRIKE ROTATION: {old_strike} → {self.current_strike} ({strike_type}) | Premium: ₹{best_premium:.0f}")
            self.logger.info(f"   Symbol: {old_symbol} → {self.current_symbol}")
            self._last_strike_rotation_time = time.time()

            # Re-subscribe WebSocket to new token using MAKE-BEFORE-BREAK (Overlapping)
            if self._ws_connected and self.broker_client and self._option_token:
                try:
                    # 1. Subscribe to new token FIRST (so data flow doesn't break)
                    if not self._subscribe_with_retry([(EXCHANGE, self._option_token, WS_OPTION_SUB_MODE)]):
                        self.logger.warning(f"⚠ WebSocket re-subscribe failed for {self._option_token}")
                    else:
                        self.logger.info(f"🔌 WebSocket re-subscribed to {self.current_symbol}")

                    # 2. Unsubscribe old token SECOND
                    if old_token and old_token != self._option_token:
                        if not self._unsubscribe_with_verify([(EXCHANGE, old_token, WS_OPTION_SUB_MODE)]):
                            self.logger.warning(f"⚠ Old token unsubscribe failed: {old_token}")

                except Exception as e:
                    self.logger.warning(f"⚠ WebSocket re-subscribe/unsubscribe failed: {e}")

            self._cached_option_tick = None
            with self._tick_lock:
                self.last_tick = None

            return True

        return False

    def _find_strike_by_premium(self, option_type: str = "CE") -> tuple:
        """
        Find the best strike where premium is in ₹90-150 range.
        Searches ATM first, then OTM/ITM based on premium.

        Args:
            option_type: 'CE' or 'PE'

        Returns:
            (best_strike, premium) or (None, 0) if not found
        """
        if not self.spot_price or self.spot_price < 10000:
            return None, 0

        atm_strike = round(self.spot_price / 50) * 50

        # Build list of strikes to check: ATM, then 2 OTM, then 2 ITM
        strikes_to_check = [atm_strike]

        # For CE: OTM = higher strikes, ITM = lower strikes
        # For PE: OTM = lower strikes, ITM = higher strikes
        if option_type == 'CE':
            otm_strikes = [atm_strike + 50, atm_strike + 100]  # Higher = OTM for CE
            itm_strikes = [atm_strike - 50, atm_strike - 100]  # Lower = ITM for CE
        else:  # PE
            otm_strikes = [atm_strike - 50, atm_strike - 100]  # Lower = OTM for PE
            itm_strikes = [atm_strike + 50, atm_strike + 100]  # Higher = ITM for PE

        strikes_to_check.extend(otm_strikes)
        strikes_to_check.extend(itm_strikes)

        # Get LTP for each strike
        best_strike = None
        best_premium = 0
        best_distance_from_mid = float('inf')  # Prefer premium closer to middle of range

        mid_premium = (STRIKE_PREMIUM_MIN + STRIKE_PREMIUM_MAX) / 2  # ₹210 (post-§2.6 widening)

        for strike in strikes_to_check:
            if strike <= 0:
                continue

            symbol = self._build_option_symbol(strike, option_type)
            token = self._get_token(symbol, EXCHANGE)

            if not token:
                continue

            try:
                ltp = self.broker_client.get_ltp(EXCHANGE, symbol, token)
                if ltp and ltp > 0:
                    # Check if premium is in range
                    if STRIKE_PREMIUM_MIN <= ltp <= STRIKE_PREMIUM_MAX:
                        distance = abs(ltp - mid_premium)
                        if distance < best_distance_from_mid:
                            best_strike = strike
                            best_premium = ltp
                            best_distance_from_mid = distance
                            self.logger.debug(f"   Found: {symbol} @ ₹{ltp:.0f} (in range)")
                    else:
                        self.logger.debug(f"   Skip: {symbol} @ ₹{ltp:.0f} (out of range)")
            except Exception as e:
                self.logger.debug(f"   Error fetching {symbol}: {e}")

        # If no strike found in range, use ATM as fallback
        if not best_strike:
            self.logger.warning(f"⚠ No strike found with premium ₹{STRIKE_PREMIUM_MIN:.0f}-₹{STRIKE_PREMIUM_MAX:.0f}, using ATM {atm_strike}")
            best_strike = atm_strike
            # Get ATM premium for logging
            try:
                symbol = self._build_option_symbol(atm_strike, option_type)
                token = self._get_token(symbol, EXCHANGE)
                if token:
                    best_premium = self.broker_client.get_ltp(EXCHANGE, symbol, token) or 0
            except:
                pass

        return best_strike, best_premium

    # =========================================================================
    # EXPIRY & SYMBOL HELPERS
    # =========================================================================

    def _find_nearest_expiry(self) -> str:
        """
        Find nearest NIFTY expiry — uses ScripMaster data first, API fallback.
        """
        # Method 1: Search ScripMaster for contracts
        if self.token_map:
            today = datetime.now()
            for days_ahead in range(0, 15):
                check_date = today + timedelta(days=days_ahead)
                expiry_str = check_date.strftime("%d%b%y").upper()
                # See if any symbols match this expiry
                prefix = f"NIFTY{expiry_str}"
                matches = [sym for sym in self.token_map if sym.startswith(prefix)]
                if len(matches) > 10:  # Enough contracts = valid expiry
                    self.logger.info(f"✓ Expiry from ScripMaster: {expiry_str} ({len(matches)} contracts)")
                    return expiry_str

        # Method 2: Search via Angel One API (original logic)
        if self.broker_client:
            today = datetime.now()

            for days_ahead in range(1, 15):
                check_date = today + timedelta(days=days_ahead)
                expiry_str = check_date.strftime("%d%b%y").upper()
                try:
                    search_term = f"NIFTY{expiry_str}"
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()
                    try:
                        results = self.broker_client.search_symbol(search_term, "NFO")
                    finally:
                        sys.stdout = old_stdout

                    if results and len(results) > 10:
                        self.logger.info(f"✓ Expiry from API: {expiry_str} ({len(results)} contracts)")
                        return expiry_str
                    time.sleep(0.3)
                except Exception as e:
                    self.logger.warning(f"Expiry search error: {e}")
                    time.sleep(1)

        # Method 3: the instrument-master cache on disk, even if token_map never loaded.
        # What stood here was "next Thursday", and NIFTY weeklies expire on Tuesday, so
        # the fallback built symbols for contracts that do not exist.
        from utils.instruments import describe, nearest_expiry

        upcoming = nearest_expiry()
        if upcoming:
            self.logger.info(f"✓ Expiry from instrument master cache: {upcoming.isoformat()}")
            return upcoming.strftime("%d%b%y").upper()

        # Nothing left to read. Reaching here means neither the ScripMaster nor the search
        # API answered, so no symbol could be resolved to a token either - the session is
        # not tradable. Say so instead of returning a date nothing expires on.
        self.logger.error(f"✗ Cannot determine expiry: {describe()}")
        return ""

    def _build_option_symbol(self, strike: int, option_type: str = "CE") -> str:
        """Build NIFTY option symbol: NIFTY{DDMMMYY}{STRIKE}{CE/PE}

        Returns "" when the expiry is unknown, so the caller's token lookup fails on a
        symbol that was never built rather than on one assembled around a guessed date.
        """
        if not self._current_expiry:
            self._current_expiry = self._find_nearest_expiry()
        if not self._current_expiry:
            return ""
        return f"NIFTY{self._current_expiry}{strike}{option_type}"
