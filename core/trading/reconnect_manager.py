"""WebSocket session lifecycle for the trading bot: subscribe/unsubscribe with retry
and first-tick verification, starting the stream, and the 4-layer reconnect protection
(heartbeat monitor, exponential-backoff auto-reconnect, circuit breaker, pre-market
reconnect). This is PTQ's own orchestration of *when* and *how* to re-establish its
session and re-subscribe its specific instruments — the low-level socket
connect/ping-pong/ACK mechanics this drives live in brokers/angel_one/websocket_client.py.

Mixed into BrokerInterface — uses self.broker_client, self._option_token,
self._tick_lock/last_tick/_tick_buffer, self._ws_connected and the reconnect/circuit-
breaker/heartbeat state set up in BrokerInterface.__init__, self.tick_writer
(core/market_data/tick_writer.py), self._tick_sequence_tracker
(core/market_data/tick_validator.py).
"""

import random
import threading
import time
from datetime import datetime, timedelta
from typing import List

from core.market_data.tick_writer import BatchedTickWriter

from config.constants import (
    USE_LIVE_DATA, ENABLE_WEBSOCKET,
    EXCHANGE, WS_OPTION_SUB_MODE, NIFTY_SPOT_TOKEN,
)


class ReconnectManagerMixin:

    def _clear_rest_cache(self):
        """Invalidate REST fallback cache after WebSocket recovery."""
        self._cached_option_tick = None
        self._last_option_fetch = 0
        self._last_rest_refresh = 0
        with self._tick_lock:
            self.last_tick = None
            self._tick_buffer.clear()
        self.logger.debug("REST cache and tick buffer cleared")

    def _verify_subscriptions(self, tokens: List[tuple]) -> bool:
        """Verify local subscription state for expected tokens."""
        if not self.broker_client:
            return False

        success = True
        for _, token, _ in tokens:
            if token and token not in self.broker_client.subscriptions:
                self.logger.warning(f"⚠ Subscription cache missing token {token}")
                success = False
        return success

    def _wait_for_first_ws_tick(self, expected_token: str, timeout_sec: int = 10) -> bool:
        """Wait for the first valid WebSocket tick for the subscribed token."""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            with self._tick_lock:
                if self.last_tick:
                    tick_token = str(self.last_tick.get('token', ''))
                    ltp = self.last_tick.get('ltp', 0)
                    if tick_token == expected_token and ltp and ltp > 0:
                        return True
            if not self._ws_connected:
                break
            time.sleep(0.2)
        return False

    def _wait_for_symbol_tick(self, expected_symbol: str, expected_token: str, timeout_sec: float = 3.0) -> bool:
        """Wait for a fresh option tick that matches both symbol and token."""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            with self._tick_lock:
                tick = self.last_tick.copy() if self.last_tick else None
            if tick:
                tick_symbol = tick.get('symbol')
                tick_token = str(tick.get('token', ''))
                tick_ltp = tick.get('ltp', 0)
                if tick_symbol == expected_symbol and tick_token == str(expected_token) and tick_ltp and tick_ltp > 0:
                    return True
            if not self._ws_connected:
                break
            time.sleep(0.2)
        return False

    def _ensure_symbol_sync_before_order(self, option_symbol: str, option_token) -> bool:
        """Ensure order symbol/token stream is active before pricing and order placement."""
        if not (USE_LIVE_DATA and ENABLE_WEBSOCKET and self._ws_connected and self.broker_client and option_token):
            return True

        if self._wait_for_symbol_tick(option_symbol, option_token, timeout_sec=3.0):
            return True

        self.logger.warning(
            f"⚠ No fresh tick for {option_symbol} ({option_token}) before order - forcing re-subscribe"
        )

        try:
            if not self._subscribe_with_retry([(EXCHANGE, option_token, WS_OPTION_SUB_MODE)], retries=1, timeout_sec=5):
                return False
        except Exception as e:
            self.logger.warning(f"⚠ Forced re-subscribe failed before order: {e}")
            return False

        return self._wait_for_symbol_tick(option_symbol, option_token, timeout_sec=3.0)

    def _unsubscribe_with_verify(self, tokens: List[tuple], retries: int = 2) -> bool:
        """Unsubscribe from WebSocket tokens with verification."""
        if not self.broker_client:
            return False

        for attempt in range(1, retries + 1):
            self.logger.info(f"🔌 Unsubscribe attempt {attempt}/{retries} for tokens {[t[1] for t in tokens]}")
            unsubscribed = self.broker_client.unsubscribe(tokens)
            if not unsubscribed:
                self.logger.warning("⚠ Unsubscribe send failed")
                time.sleep(0.5)
                continue

            still_present = [token for _, token, _ in tokens if token in self.broker_client.subscriptions]
            if still_present:
                self.logger.warning(f"⚠ Unsubscribe cache still has tokens: {still_present}")
                time.sleep(0.5)
                continue

            return True

        self.logger.error(f"❌ Failed to unsubscribe tokens after {retries} attempts")
        return False

    def _subscribe_with_retry(self, tokens: List[tuple], retries: int = 3, timeout_sec: int = 10) -> bool:
        """Subscribe to WebSocket tokens with retry and first-tick validation."""
        if not self.broker_client:
            return False

        expected_option_token = next((token for _, token, _ in tokens if token == self._option_token), None)

        for attempt in range(1, retries + 1):
            self.logger.info(f"🔌 Subscribe attempt {attempt}/{retries} for tokens {[t[1] for t in tokens]}")
            subscribed = self.broker_client.subscribe(tokens)
            if not subscribed:
                self.logger.warning("⚠ Subscribe send failed")
                time.sleep(1)
                continue

            if not self._verify_subscriptions(tokens):
                self.logger.warning("⚠ Subscription local cache verification failed")
                time.sleep(1)
                continue

            if expected_option_token and not self._wait_for_first_ws_tick(expected_option_token, timeout_sec):
                self.logger.warning("⚠ No first tick after subscribe, retrying...")
                self._unsubscribe_with_verify(tokens)
                time.sleep(1)
                continue

            self._clear_rest_cache()
            return True

        self.logger.error(f"❌ Failed to subscribe to tokens after {retries} attempts")
        return False

    # =========================================================================
    # WEBSOCKET — real-time ticks (eliminates 180s polling delay)
    # =========================================================================

    def _start_websocket(self):
        """Start WebSocket and subscribe to NIFTY spot + option"""
        if not self.broker_client:
            return
        if self._ws_shutdown_requested:
            if self.logger:
                self.logger.info("WebSocket start skipped: shutdown requested")
            return

        # Created once, reused across reconnects (this method can run again on
        # reconnect) — a fresh writer each time would orphan the previous one's
        # background thread instead of stopping it.
        if self.tick_writer is None:
            self.tick_writer = BatchedTickWriter(logger=self.logger)
            self.tick_writer.start()

        try:
            self.broker_client.start_websocket(
                on_tick=self._on_ws_tick,
            )
            # Register disconnect callback so BrokerInterface knows when WS dies
            self.broker_client._broker_ws_disconnect_cb = self._on_ws_disconnect

            # Register explicit ACK timeout callback so we can record transport stress without severing the socket
            self.broker_client._broker_ws_ack_timeout_cb = lambda: setattr(self, '_last_ws_ack_timeout_time', time.time())

            # Wait until WebSocket reports connected or timeout
            start_time = time.time()
            timeout_sec = 10
            while time.time() - start_time < timeout_sec:
                if self.broker_client.ws_connected:
                    break
                time.sleep(0.2)

            if not self.broker_client.ws_connected:
                self.logger.warning("⚠ WebSocket connection failed or timed out, will use REST polling")
                return

            # Subscribe spot first (LTP mode), then option (Quote or SnapQuote,
            # per WS_SNAP_QUOTE_ENABLED — SnapQuote is what carries OI and the book)
            spot_tokens = [
                ("NSE", NIFTY_SPOT_TOKEN, 1),  # NIFTY spot — LTP mode
            ]
            option_tokens = []
            if self._option_token:
                option_tokens.append((EXCHANGE, self._option_token, WS_OPTION_SUB_MODE))  # Option

            spot_ok = self._subscribe_with_retry(spot_tokens)
            option_ok = True
            if spot_ok and option_tokens:
                option_ok = self._subscribe_with_retry(option_tokens)

            if spot_ok and option_ok:
                self._ws_connected = True
                now_ts = time.time()
                self._ws_last_tick_time = now_ts  # Initialize heartbeat
                # Initialize option heartbeat too; avoids false 999s timeout before first option tick.
                self._ws_last_option_tick_time = now_ts
                self._ws_reconnect_attempts = 0  # Reset on successful connect
                self.logger.info(f"🔌 WebSocket subscribed to {len(spot_tokens) + len(option_tokens)} tokens")
            else:
                self.logger.error("❌ WebSocket subscription failed after retries")
                self._ws_connected = False
                return

            # Layer 1: Start heartbeat monitor (if not already running)
            if not self._ws_heartbeat_thread or not self._ws_heartbeat_thread.is_alive():
                self._ws_heartbeat_stop_event.clear()
                self._start_ws_heartbeat_monitor()

        except Exception as e:
            self.logger.warning(f"⚠ WebSocket start failed: {e}")
            self._ws_connected = False
            # Trigger reconnect on failure
            if self._ws_reconnect_attempts < self._ws_max_reconnect_attempts:
                threading.Thread(target=self._trigger_ws_reconnect, daemon=True).start()

    def _on_ws_disconnect(self, reason: str = "unknown"):
        """Called when WebSocket disconnects — triggers Layer 2 auto-reconnect"""
        if self._ws_shutdown_requested:
            if self.logger:
                self.logger.info(f"WebSocket disconnect ignored during shutdown: {reason}")
            return

        reason_text = str(reason or "").lower()

        if "ack timeout" in reason_text:
            self._last_ws_ack_timeout_time = time.time()

        # Broker-side connection limit (HTTP 429) should not trigger reconnect storms.
        is_conn_limit = (
            "429" in reason_text
            or "connection limit exceeded" in reason_text
            or "too many requests" in reason_text
        )
        if is_conn_limit:
            self._ws_connected = False
            self._ws_circuit_open = True
            self._ws_circuit_cooldown_until = datetime.now() + timedelta(
                seconds=self._ws_connection_limit_cooldown_sec
            )
            self.logger.warning(
                "⚠ WebSocket connection limit hit (HTTP 429). "
                f"Pausing reconnects for {self._ws_connection_limit_cooldown_sec}s "
                f"until {self._ws_circuit_cooldown_until.strftime('%H:%M:%S')} and using REST fallback."
            )
            return

        was_connected = self._ws_connected
        self._ws_connected = False
        # A fresh connection restarts the broker's own sequence numbering, so the old
        # high-water mark must not reject every tick on the next connection as
        # out-of-order.
        self._tick_sequence_tracker.reset()

        if was_connected and self.logger:
            self.logger.warning(f"⚠ WebSocket DISCONNECTED: {reason}")

            # Layer 2: Trigger auto-reconnect (don't fall back to REST)
            self._trigger_ws_reconnect()

    def _trigger_ws_reconnect(self):
        """Layer 2: Auto-reconnect worker thread with exponential backoff."""
        if self._ws_shutdown_requested:
            if self.logger:
                self.logger.info("Reconnect skipped: shutdown requested")
            return
        with self._ws_reconnect_lock:
            if self._ws_reconnect_running:
                self.logger.debug("🔄 Reconnect already running, skipping duplicate trigger")
                return
            self._ws_reconnect_running = True

        def reconnect_worker():
            try:
                while True:
                    if self._ws_shutdown_requested:
                        self.logger.info("Reconnect worker stopping: shutdown requested")
                        break
                    # If already reconnected, stop the worker
                    if self._ws_connected:
                        self.logger.info("✅ WebSocket already connected, stopping reconnect worker")
                        break

                    # Circuit breaker logic
                    if self._ws_circuit_open:
                        if self._ws_circuit_cooldown_until and datetime.now() < self._ws_circuit_cooldown_until:
                            self.logger.info(
                                f"🔌 Circuit breaker active until {self._ws_circuit_cooldown_until.strftime('%H:%M:%S')}, delaying reconnect"
                            )
                            time.sleep(10)
                            continue
                        self._ws_circuit_open = False
                        self._ws_reconnect_attempts = 0
                        self._ws_reconnect_delay = 1.0
                        self.logger.info("🔄 Circuit breaker reset - attempting reconnection...")

                    self._ws_reconnect_attempts += 1
                    if self._ws_reconnect_attempts > self._ws_max_reconnect_attempts:
                        self._ws_circuit_open = True
                        self._ws_circuit_cooldown_until = datetime.now() + timedelta(seconds=self._ws_circuit_cooldown_sec)
                        self.logger.warning(
                            f"🔌 CIRCUIT BREAKER OPEN | {self._ws_reconnect_attempts} failed attempts | "
                            f"Cooldown until {self._ws_circuit_cooldown_until.strftime('%H:%M:%S')}"
                        )
                        break

                    raw_delay = min(self._ws_reconnect_delay * (2 ** (self._ws_reconnect_attempts - 1)), self._ws_max_reconnect_delay)
                    jitter = random.uniform(-min(3.0, raw_delay * 0.1), min(3.0, raw_delay * 0.1))
                    current_delay = max(1.0, min(self._ws_max_reconnect_delay, raw_delay + jitter))

                    self.logger.info(
                        f"🔄 WebSocket reconnect attempt {self._ws_reconnect_attempts}/{self._ws_max_reconnect_attempts} "
                        f"(delay: {current_delay:.1f}s, jitter: {jitter:+.2f}s)"
                    )

                    time.sleep(current_delay)

                    self._last_ws_reconnect_time = time.time()

                    if self.broker_client:
                        try:
                            self.broker_client.stop_websocket()
                        except Exception:
                            pass

                    try:
                        self._start_websocket()
                        if self._ws_connected:
                            self._ws_reconnect_attempts = 0
                            self.logger.info("✅ WebSocket reconnected successfully!")
                            break
                        self.logger.warning("⚠ WebSocket reconnect attempt completed without connection")
                    except Exception as e:
                        self.logger.warning(f"⚠ Reconnect attempt error: {e}")

                    # Continue looping until circuit breaker opens or reconnect succeeds

            finally:
                with self._ws_reconnect_lock:
                    self._ws_reconnect_running = False

        threading.Thread(target=reconnect_worker, daemon=True, name="WS-Reconnect").start()

    def _start_ws_heartbeat_monitor(self):
        """Layer 1: Heartbeat monitor - checks if ticks are flowing (algo-trading optimized)

        Note: Angel One WebSocket only sends ticks on PRICE CHANGES.
        If market is quiet, no ticks come even on a healthy connection.
        We use a longer timeout and check if we have usable cached data.
        """
        def heartbeat_monitor():
            while True:
                try:
                    if self._ws_shutdown_requested or self._ws_heartbeat_stop_event.is_set():
                        break
                    # If circuit breaker is open, just sleep
                    if self._ws_circuit_open:
                        time.sleep(60)  # Check circuit breaker every minute
                        continue

                    # Layer 4: Check for pre-market reconnect (2 min before market open)
                    self._check_premarket_reconnect()

                    # Check if we're getting useful ticks for the active option token.
                    if self._option_token:
                        last_stream_tick_time = self._ws_last_option_tick_time
                    else:
                        last_stream_tick_time = self._ws_last_tick_time

                    if last_stream_tick_time > 0:
                        time_since_last_tick = time.time() - last_stream_tick_time
                    else:
                        time_since_last_tick = 999

                    # Only reconnect if:
                    # 1. Connected but no tick received for 2+ minutes, AND
                    # 2. We have no usable cached data (or it's very stale)
                    has_usable_cache = self.last_tick is not None and self._ws_original_tick_time is not None
                    original_tick_age = time.time() - self._ws_original_tick_time if self._ws_original_tick_time else 999

                    if self._ws_connected and time_since_last_tick > self._ws_heartbeat_timeout:
                        now_dt = datetime.now()
                        is_premarket = now_dt.hour < 9 or (now_dt.hour == 9 and now_dt.minute < 15)
                        is_weekend = now_dt.weekday() >= 5

                        # If original tick data is still fresh enough, avoid reconnect churn.
                        # Also do not force disconnects during pre-market or weekends as ticks won't arrive.
                        if (has_usable_cache and original_tick_age < 120) or is_premarket or is_weekend:
                            # Log once per minute that we're using REST refresh
                            if int(time_since_last_tick) % 60 == 0:
                                self.logger.info(f"ℹ WebSocket quiet ({time_since_last_tick:.0f}s), REST keeping data fresh ({original_tick_age:.0f}s old)")
                        else:
                            self.logger.warning(f"💔 Heartbeat FAILED: No tick for {time_since_last_tick:.0f}s - reconnecting...")
                            self._on_ws_disconnect("Heartbeat timeout")

                    time.sleep(15)  # Check every 15 seconds

                except Exception as e:
                    self.logger.debug(f"Heartbeat monitor error: {e}")
                    time.sleep(5)

        self._ws_heartbeat_thread = threading.Thread(target=heartbeat_monitor, daemon=True, name="WS-Heartbeat")
        self._ws_heartbeat_thread.start()

    def _check_premarket_reconnect(self):
        """Layer 4: Reconnect WebSocket 2 minutes before market open to ensure fresh connection"""
        if self._ws_premarket_reconnect_done:
            return  # Already done for today

        now = datetime.now()
        market_open_hour, market_open_min = map(int, self._market_open_time.split(":"))
        market_open = now.replace(hour=market_open_hour, minute=market_open_min, second=0, microsecond=0)

        # Check if we're in the pre-market reconnect window
        premarket_reconnect_time = market_open - timedelta(seconds=self._premarket_reconnect_margin_sec)

        if premarket_reconnect_time <= now < market_open:
            self._ws_premarket_reconnect_done = True
            self.logger.info("🔄 PRE-MARKET RECONNECT: Refreshing WebSocket before market open...")

            # Force reconnect for fresh connection
            if self.broker_client:
                try:
                    self.broker_client.stop_websocket()
                    time.sleep(1)
                    self._start_websocket()
                    self.logger.info("✅ Pre-market WebSocket refresh complete!")
                except Exception as e:
                    self.logger.warning(f"⚠ Pre-market reconnect failed: {e}")

    def reset_premarket_reconnect(self):
        """Reset pre-market reconnect flag for new trading day (call at midnight)"""
        self._ws_premarket_reconnect_done = False
