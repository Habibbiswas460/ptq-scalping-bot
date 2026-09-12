"""The live tick feed: the WebSocket callback, REST fallback/polling, the paper-trading
simulator, tick persistence, and the buffer-smoothing/observability helpers built on
top of them. get_tick()/_get_tick_uncached() (the unified WebSocket -> REST ->
simulation entry point) stay on BrokerInterface itself in broker.py:
tests/test_tick_freshness.py patches USE_LIVE_DATA as a module global on
core.trading.broker, which only reaches a function whose __globals__ is that module.

Mixed into BrokerInterface — uses self._tick_lock/last_tick/_tick_buffer,
self.spot_price/current_symbol/current_strike/_option_token, self.broker_client,
self.market_tick_cache/market_ohlcv/tick_writer (core/market_data/), and the
subscribe/unsubscribe helpers from reconnect_manager.py.
"""

import math
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from brokers.angel_one.normalizer import normalize_tick
from core.market_data.tick_enricher import enrich_tick
from core.market_data.tick_validator import validate_tick

from utils.helpers import current_time_ms

from config.constants import (
    OPTION_TYPE, EXCHANGE, TICK_OI_ENABLED, WS_OPTION_SUB_MODE,
    NIFTY_SPOT_TOKEN, STALE_THRESHOLD_MS_REST,
)


class TickFeedMixin:

    def _on_market_candle_closed(self, candle: Dict) -> None:
        """core/market_data/ohlcv_aggregator.py callback for a completed 5-min bucket —
        hands it to the batched writer, never blocks the aggregator that called this."""
        if self.tick_writer:
            self.tick_writer.enqueue_candle(candle)

    def _on_ws_tick(self, tick_data: Dict):
        """Handle incoming WebSocket tick — thread-safe"""
        with self._tick_lock:
            token = str(tick_data.get('token', ''))

            # Layer 1: Update heartbeat timestamp (tick received = connection alive)
            self._ws_last_tick_time = time.time()

            # Reset reconnect counter and delay on successful tick
            if self._ws_reconnect_attempts > 0:
                self._ws_reconnect_attempts = 0
                self._ws_reconnect_delay = 1.0  # Reset exponential backoff

            if token == NIFTY_SPOT_TOKEN:
                # NIFTY spot update
                ltp = tick_data.get('ltp', 0)
                if ltp and ltp > 10000:
                    self.spot_price = ltp
                    # In-memory only — see the comment on self.market_ohlcv in __init__.
                    self.market_ohlcv.add_tick(tick_data)
                    if self.tick_writer:
                        self.tick_writer.enqueue_tick(normalize_tick(tick_data, symbol="NIFTY"))
            else:
                # Option tick update
                ltp = tick_data.get('ltp', 0)
                if not ltp or ltp <= 0:
                    return

                # Build tick dict with bid/ask from the best-5 book. Present only on a
                # SnapQuote subscription (WS_SNAP_QUOTE_ENABLED); in Quote mode these keys
                # are absent and the estimate below is what every historical row holds.
                bid = tick_data.get('best_bid_price', 0) or ltp
                ask = tick_data.get('best_ask_price', 0) or ltp
                volume = tick_data.get('volume', 0) or 0

                # FIX: If bid/ask equal OR not available, estimate spread
                # This prevents inverted market (bid >= ask) rejection
                #
                # OBSERVABILITY ONLY (no behaviour change): tag whether the
                # quote is a real book quote or this estimate, and count both.
                # Nothing reads `quote_source` for any trading decision — it
                # exists to quantify how often the spread-based filters are
                # operating on an estimate rather than a real spread. See the
                # synthetic-bid/ask correction record; measurement must come
                # before any threshold decision.
                quote_source = 'real'
                if bid <= 0 or ask <= 0 or bid >= ask:
                    spread = max(0.05, ltp * 0.003)  # 0.3% spread estimate
                    bid = round(ltp - spread / 2, 2)
                    ask = round(ltp + spread / 2, 2)
                    quote_source = 'estimated'
                self._quote_source_counts[quote_source] = (
                    self._quote_source_counts.get(quote_source, 0) + 1
                )
                self._maybe_log_quote_source_summary()

                # ═══════════════════════════════════════════════════════════════
                # CRITICAL FIX: Only accept ticks from CURRENT subscribed token
                # After symbol switch, old token's ticks may still arrive briefly.
                # This is also what makes the unsubscribe-side verification gap
                # noted in findings.md/fixed.md §2.10 low-risk in practice — even
                # if a real unsubscribe silently fails at the SmartAPI layer, a
                # stale old-token tick can never reach strategy/exit logic; it's
                # discarded right here. Logged (not silent) so a real occurrence
                # is now observable instead of invisible.
                # ═══════════════════════════════════════════════════════════════
                if self._option_token and token != self._option_token:
                    self._stale_token_tick_count = getattr(self, '_stale_token_tick_count', 0) + 1
                    if self.logger and self._stale_token_tick_count % 20 == 1:
                        self.logger.debug(
                            f"⏳ Discarded stale tick for old token={token} "
                            f"(current={self._option_token}, count={self._stale_token_tick_count})"
                        )
                    return

                tick_ts = current_time_ms()
                new_tick = {
                    'timestamp': tick_ts,
                    'original_timestamp': tick_ts,
                    'ltp': round(ltp, 2),
                    'bid': round(bid, 2),
                    'ask': round(ask, 2),
                    'volume': volume,
                    'spot_price': self.spot_price,
                    'symbol': self.current_symbol,
                    'strike': self.current_strike,
                    'direction': OPTION_TYPE,
                    'token': token,  # Include token for debugging
                    'quote_source': quote_source,  # observability only, never read for decisions
                }

                # The websocket parser already decodes open interest, but it was
                # dropped here, so `update_oi_data()` saw current_oi <= 0 and
                # returned NEUTRAL forever — pinning the score's oi component to
                # 0 and the confidence oi_score to 50. The persistence layer
                # already writes tick['oi'], so this also fills the ticks.oi
                # column that was NULL on every historical row.
                # REST-path ticks carry no OI (the LTP endpoint does not return
                # it), so this only populates on the websocket path.
                if TICK_OI_ENABLED:
                    new_tick['oi'] = tick_data.get('open_interest', 0) or 0

                # core/market_data/ pipeline (additive): null/sequence/book-sanity
                # observability, mid_price/spread_bps/change_pct enrichment as new keys
                # only, and a token-keyed cache mirror. None of this alters new_tick's
                # existing keys or gates it from becoming self.last_tick below.
                validation = validate_tick(new_tick, self._tick_sequence_tracker)
                if not validation.ok and self.logger:
                    self.logger.debug(f"⚠ tick_validator flagged: {', '.join(validation.reasons)}")
                enriched = enrich_tick(new_tick)
                new_tick['mid_price'] = enriched.get('mid_price')
                new_tick['spread_bps'] = enriched.get('spread_bps')
                new_tick['change_pct'] = enriched.get('change_pct')
                self.market_tick_cache.update(new_tick)
                self.market_ohlcv.add_tick(new_tick)
                if self.tick_writer:
                    # Normalized from tick_data (the raw wire tick), not new_tick — it
                    # carries the exchange's own timestamp/sequence/exchange_type that
                    # new_tick doesn't restate.
                    self.tick_writer.enqueue_tick(normalize_tick(tick_data, symbol=self.current_symbol))

                # Add to tick buffer for smoother data flow
                if self._use_tick_buffer:
                    self._tick_buffer.append(new_tick)
                    if len(self._tick_buffer) > self._tick_buffer_max_size:
                        self._tick_buffer.pop(0)

                self.last_tick = new_tick
                self.last_valid_tick_time = datetime.now()
                self._ws_original_tick_time = time.time()  # Track when real data arrived
                self._ws_last_option_tick_time = time.time()

    # =========================================================================
    # REST FALLBACK — when WebSocket is disabled or fails
    # =========================================================================

    def _fetch_option_tick_rest(self) -> Optional[Dict]:
        """Fetch option tick via REST API (used as fallback or initial)

        Circuit Breaker Pattern:
        - If 10+ consecutive errors, enter cooldown mode
        - Cooldown: 300 seconds (5 min) before retrying
        - Prevents log spam during network outages
        """
        if not self.broker_client or not self.current_symbol:
            return None

        # Initialize circuit breaker state
        if not hasattr(self, '_network_error_count'):
            self._network_error_count = 0
            self._network_cooldown_until = None

        # Check if in cooldown mode (circuit breaker open)
        if self._network_cooldown_until:
            if datetime.now() < self._network_cooldown_until:
                # Still in cooldown - return cached tick silently
                if self._cached_option_tick:
                    cached = self._cached_option_tick.copy()
                    cached['timestamp'] = current_time_ms()
                    return cached
                return None
            else:
                # Cooldown expired - reset and try again
                self._network_cooldown_until = None
                self._network_error_count = 0
                self.logger.info("🔄 Network cooldown ended - retrying connection...")

        try:
            tick = self.broker_client.get_market_tick(
                symbol=self.current_symbol,
                exchange=EXCHANGE
            )
            if tick:
                tick_ts = current_time_ms()
                tick['spot_price'] = self.spot_price
                tick['strike'] = self.current_strike
                tick['direction'] = OPTION_TYPE
                tick['symbol'] = self.current_symbol  # CRITICAL: Set symbol for verification
                tick['timestamp'] = tick_ts
                tick['original_timestamp'] = tick_ts
                self._cached_option_tick = tick
                self._last_option_fetch = time.time()
                self.last_valid_tick_time = datetime.now()
                # Reset error count on success
                self._network_error_count = 0
                return tick
        except (ConnectionError, OSError, requests.exceptions.RequestException) as e:
            self._network_error_count += 1
            error_str = str(e).lower()

            # Check if this is a network-related error
            is_network_error = any(x in error_str for x in [
                'name resolution', 'connection', 'network', 'timeout',
                'unreachable', 'reset', 'refused', 'dns'
            ])

            if is_network_error and self._network_error_count >= 10:
                # Circuit breaker OPEN - enter cooldown
                self._network_cooldown_until = datetime.now() + timedelta(seconds=300)
                self.logger.warning(
                    f"🔌 Network Down - Circuit breaker activated | "
                    f"Errors: {self._network_error_count} | "
                    f"Cooldown: 5 minutes (until {self._network_cooldown_until.strftime('%H:%M:%S')})"
                )
            elif self._network_error_count == 1 or self._network_error_count % 50 == 0:
                # Log only first error and every 50th to prevent spam
                self.logger.warning(f"⚠ REST tick fetch failed ({self._network_error_count}x): {e}")
        except Exception as e:
            # Non-network errors - log normally but less frequently
            if not hasattr(self, '_last_rest_error') or time.time() - self._last_rest_error > 300:
                self.logger.warning(f"⚠ REST tick fetch failed: {e}")
                self._last_rest_error = time.time()

        return None

    def _get_rest_tick(self) -> Optional[Dict]:
        """
        Get tick via REST polling with 10-second interval.
        (Was 180s — reduced since WebSocket is primary now)
        """
        if not self.broker_client:
            return None

        # Keep REST fallback cadence below stale threshold to reduce stale rejects.
        rest_stale_sec = max(1.0, STALE_THRESHOLD_MS_REST / 1000.0)
        poll_interval = max(1.0, min(10.0, rest_stale_sec - 1.0))

        # Fetch NIFTY spot every 30s via REST
        if time.time() - self._last_spot_fetch > 30:
            try:
                real_spot = self.broker_client.get_ltp("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
                if real_spot and real_spot > 10000:
                    self.spot_price = real_spot
                    self._last_spot_fetch = time.time()

                    # Check if strike needs adjustment
                    base_strike = round(self.spot_price / 50) * 50
                    if abs(self.spot_price - self.current_strike) >= 50:  # Reduced from 150 to 50
                        old_symbol = self.current_symbol
                        old_token = self._option_token
                        self.current_strike = base_strike
                        self.current_symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)
                        self._option_token = self._get_token(self.current_symbol, EXCHANGE)
                        self.logger.info(f"🔧 Strike adjusted: {self.current_strike} | {self.current_symbol}")

                        # Strike changed via REST path, so WS token must be updated too.
                        if (
                            self._ws_connected
                            and self.broker_client
                            and self._option_token
                            and self._option_token != old_token
                        ):
                            try:
                                with self._tick_lock:
                                    self.last_tick = None
                                    self._tick_buffer.clear()

                                if old_token:
                                    if not self._unsubscribe_with_verify([(EXCHANGE, old_token, WS_OPTION_SUB_MODE)]):
                                        self.logger.warning(f"⚠ Old token unsubscribe failed: {old_token}")

                                if not self._subscribe_with_retry([(EXCHANGE, self._option_token, WS_OPTION_SUB_MODE)]):
                                    self.logger.warning(f"⚠ WebSocket re-subscribe failed for {self._option_token}")
                                else:
                                    self.logger.info(f"🔌 WebSocket re-subscribed after strike adjust: {old_symbol} → {self.current_symbol}")
                            except Exception as e:
                                self.logger.warning(f"⚠ WebSocket re-subscribe failed after strike adjust: {e}")
            except Exception:
                pass

        # Fetch option tick
        if time.time() - self._last_option_fetch > poll_interval:
            tick = self._fetch_option_tick_rest()
            if tick:
                return tick

        # Return cached tick (no noise for accurate paper trading)
        # BUG FIX #14: Removed random noise that was distorting prices
        if self._cached_option_tick:
            cached = self._cached_option_tick.copy()
            cached['spot_price'] = self.spot_price
            # REST snapshots are pull-based; treat each delivered cache read as a fresh
            # snapshot timestamp for validator freshness checks.
            now_ms = current_time_ms()
            cached['timestamp'] = now_ms
            cached['original_timestamp'] = now_ms
            self.last_valid_tick_time = datetime.now()
            return cached

        return None

    # =========================================================================
    # GET TICK — cross-direction lookup + observability
    # =========================================================================

    def get_tick_for_direction(self, direction: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a real tick for the option contract matching `direction`
        (CE/PE) at that direction's own strike — even when a different
        contract is currently subscribed.

        Every entry-decision check that reads a tick (premium filter,
        delta filter, market-quality's spread/liquidity gate) normally
        reads get_tick(), which reflects whichever contract is currently
        subscribed. Pattern detection itself is spot-price-based and
        direction-agnostic, so smart_scalp_v3.generate_signal() can — and
        routinely does — return a signal whose direction differs from the
        subscribed contract (e.g. subscribed to a CE, but the pattern
        match is PE). place_order() switches the subscription to match at
        order time, but every check before that point had already run
        against the wrong contract's price, spread and premium. Callers
        use this to re-validate against the contract that will actually
        be traded before committing to the entry.
        """
        target_strike = self.resolve_strike_for_direction(direction)
        target_symbol = self._build_option_symbol(target_strike, direction)
        if target_symbol == self.current_symbol:
            return self.get_tick()

        if not self.broker_client:
            return None

        try:
            tick = self.broker_client.get_market_tick(symbol=target_symbol, exchange=EXCHANGE)
        except Exception as e:
            self.logger.warning(f"⚠ Cross-direction tick fetch failed for {target_symbol}: {e}")
            return None

        if not tick:
            return None

        tick_ts = current_time_ms()
        tick['spot_price'] = self.spot_price
        tick['strike'] = target_strike
        tick['direction'] = direction
        tick['symbol'] = target_symbol
        tick['timestamp'] = tick_ts
        tick['original_timestamp'] = tick_ts
        return tick

    def get_quote_source_stats(self) -> Dict[str, Any]:
        """Real-vs-estimated quote counts for this session (observability only).

        Reported, never acted on: the spread-based filters currently receive
        an estimated ~0.3% spread whenever the book is unavailable, which
        makes them non-discriminating. Quantifying that is the prerequisite
        for deciding anything about the thresholds.
        """
        counts = dict(self._quote_source_counts)
        total = sum(counts.values())
        estimated = counts.get('estimated', 0)
        return {
            'real': counts.get('real', 0),
            'estimated': estimated,
            'total': total,
            'estimated_pct': round(100.0 * estimated / total, 2) if total else None,
        }

    def _maybe_log_quote_source_summary(self) -> None:
        """Periodically log the real/estimated quote split. Never raises."""
        try:
            now = time.time()
            if now - self._quote_source_last_log < self._quote_source_log_interval_sec:
                return
            self._quote_source_last_log = now
            stats = self.get_quote_source_stats()
            if self.logger and stats['total']:
                self.logger.info(
                    f"📊 Quote source: real={stats['real']} estimated={stats['estimated']} "
                    f"({stats['estimated_pct']}% estimated)"
                )
        except Exception:
            pass  # observability must never affect the feed path

    def _persist_tick(self, tick: Dict[str, Any]) -> None:
        """Write a real tick to the ticks table, deduped on
        (symbol, ltp, bid, ask) so the ~2Hz main-loop cadence re-serving an
        unchanged cached WS tick (see the 'Refresh timestamp to NOW' path
        below) doesn't flood the table with identical rows — every row
        persisted here represents an actual price change.
        """
        symbol = tick.get('symbol')
        if not symbol:
            return
        key = (symbol, tick.get('ltp'), tick.get('bid'), tick.get('ask'))
        if key == getattr(self, '_last_logged_tick', None):
            return
        self._last_logged_tick = key
        try:
            from core.services.database import log_tick
            log_tick(tick)
        except Exception:
            pass  # Persistence is analytics-only and must never block trading.

    def get_ws_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status for monitoring"""
        return {
            'connected': self._ws_connected,
            'last_tick_time': self._ws_last_tick_time,
            'time_since_last_tick': time.time() - self._ws_last_tick_time if self._ws_last_tick_time else None,
            'reconnect_attempts': self._ws_reconnect_attempts,
            'circuit_breaker_open': self._ws_circuit_open,
            'circuit_cooldown_until': self._ws_circuit_cooldown_until.strftime('%H:%M:%S') if self._ws_circuit_cooldown_until else None,
            'premarket_reconnect_done': self._ws_premarket_reconnect_done,
            'tick_buffer_size': len(self._tick_buffer),
        }

    def get_smoothed_tick(self) -> Optional[Dict[str, Any]]:
        """Get smoothed tick from buffer for more robust algo trading."""
        if not self._tick_buffer or len(self._tick_buffer) < 2:
            return self.get_tick()

        with self._tick_lock:
            weights = [(t.get('volume') or 1) for t in self._tick_buffer]
            total_weight = sum(weights)
            if total_weight <= 0:
                total_weight = len(self._tick_buffer)
                weights = [1] * len(self._tick_buffer)

            vwap_ltp = sum((t.get('ltp', 0) * w) for t, w in zip(self._tick_buffer, weights)) / total_weight
            vwap_bid = sum((t.get('bid', 0) * w) for t, w in zip(self._tick_buffer, weights)) / total_weight
            vwap_ask = sum((t.get('ask', 0) * w) for t, w in zip(self._tick_buffer, weights)) / total_weight
            smoothed_volume = self._tick_buffer[-1].get('volume', 0) or 1

            smoothed = self._tick_buffer[-1].copy()
            smoothed['ltp'] = round(vwap_ltp, 2)
            smoothed['bid'] = round(vwap_bid, 2)
            smoothed['ask'] = round(vwap_ask, 2)
            smoothed['volume'] = smoothed_volume
            smoothed['data_source'] = 'WEBSOCKET_SMOOTHED_VWAP'
            smoothed['buffer_size'] = len(self._tick_buffer)

            return smoothed

    def clear_tick_buffer(self):
        """Clear tick buffer (call on position change to reset smoothing)"""
        with self._tick_lock:
            self._tick_buffer.clear()

    # =========================================================================
    # SIMULATION
    # =========================================================================

    def _get_simulated_tick(self) -> Dict:
        """Generate realistic simulated tick for paper trading"""
        if self._simulated_premium is None:
            self._simulated_premium = 125.0
        if not hasattr(self, '_wave_position'):
            self._wave_position = 0.0
            self._wave_speed = random.uniform(0.005, 0.02)
            self._wave_amplitude = random.uniform(15, 40)
            self._base_price = self._simulated_spot

        # Try real spot from broker (every 5 min)
        if self.broker_client and (time.time() - self._last_spot_fetch > 300):
            try:
                real_spot = self.broker_client.get_ltp("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
                if real_spot and real_spot > 10000:
                    self._simulated_spot = real_spot
                    self._base_price = real_spot
                    self._last_spot_fetch = time.time()
            except Exception:
                pass

        # Sinusoidal + Trend + Noise spot movement
        self._wave_position += self._wave_speed
        wave = math.sin(self._wave_position) * self._wave_amplitude
        trend = math.sin(self._wave_position * 0.1) * 30
        if not hasattr(self, '_random_walk'):
            self._random_walk = 0
        self._random_walk += random.gauss(0, 2)
        self._random_walk = max(-50, min(50, self._random_walk))
        self.spot_price = round(self._base_price + wave + trend + self._random_walk + random.gauss(0, 1), 2)

        # Auto-adjust strike
        base_strike = round(self.spot_price / 50) * 50
        if not hasattr(self, '_last_strike') or abs(self.spot_price - self.current_strike) >= 150:
            self.current_strike = base_strike
        self._last_strike = self.current_strike

        # Option premium correlated with spot
        spot_change = self.spot_price - (self._base_price + wave + trend)
        delta_effect = spot_change * 0.5
        self._trend_ticks += 1
        if random.random() < 0.02:
            self._premium_trend *= -1
        noise = random.gauss(0, 0.5)
        target_premium = 125 + delta_effect + self._premium_trend * 10 + noise
        target_premium = max(40, min(300, target_premium))

        # Max 2pt move per tick
        max_change = 2.0
        diff = target_premium - self._simulated_premium
        if abs(diff) > max_change:
            self._simulated_premium += max_change if diff > 0 else -max_change
        else:
            self._simulated_premium = target_premium
        self._simulated_premium = max(40, min(300, self._simulated_premium))

        ltp = round(self._simulated_premium, 2)
        spread = 0.50
        base_volume = 400000
        volume_spike = abs(wave) / self._wave_amplitude * 200000
        volume = int(base_volume + volume_spike + random.uniform(-50000, 50000))
        self.last_valid_tick_time = datetime.now()

        return {
            'timestamp': current_time_ms(),
            'bid': round(ltp - spread / 2, 2),
            'ask': round(ltp + spread / 2, 2),
            'ltp': ltp,
            'volume': volume,
            'spot_price': self.spot_price,
            'symbol': self.current_symbol,
            'strike': self.current_strike,
            'direction': OPTION_TYPE,
            'data_source': 'SIMULATION',
        }
