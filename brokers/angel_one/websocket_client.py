"""WebSocket connection lifecycle: connect, protocol-level ping/pong keepalive,
subscribe/unsubscribe (with the fire-and-forget ACK bookkeeping SmartAPI actually uses),
and failover across redundant connections.

Mixed into AngelOneClient — uses the ws state set up in AngelOneClient.__init__
(self._ws_lock, self.ws, self.ws_thread, self._ws_threads, self.ws_connected,
self._manual_ws_stop, self.subscriptions, self._pending_ack_*, self.ws_connections,
self.ws_primary_index, self.ws_max_connections, self.ws_subscriptions,
self.on_tick_callback, self.on_order_update_callback) and self.auth_token/api_key/
client_id/feed_token from auth, self._parse_ws_binary from message_parser.py, self.logger.
"""

import json
import threading
import time
from typing import Callable, Dict, List, Optional

try:
    import websocket
except ImportError:
    websocket = None

WEBSOCKET_URL = "wss://smartapisocket.angelone.in/smart-stream"

WS_EXCHANGE_NSE_CM = 1
WS_EXCHANGE_NSE_FO = 2
WS_EXCHANGE_BSE_CM = 3
WS_EXCHANGE_BSE_FO = 4
WS_EXCHANGE_MCX_FO = 5
WS_EXCHANGE_NCX_FO = 7
WS_EXCHANGE_CDE_FO = 13

WS_MODE_LTP = 1


class WebSocketMixin:

    def _get_primary_websocket(self):
        """Get the primary (active) WebSocket connection (Phase 5)"""
        if self.ws_connections and len(self.ws_connections) > 0:
            return self.ws_connections[self.ws_primary_index % len(self.ws_connections)]
        return self.ws

    def _failover_websocket(self):
        """
        Attempt failover to next WebSocket connection (Phase 5)
        Cycles through 3 available connections for redundancy
        """
        if len(self.ws_connections) > 1:
            old_index = self.ws_primary_index
            self.ws_primary_index = (self.ws_primary_index + 1) % len(self.ws_connections)
            new_ws = self.ws_connections[self.ws_primary_index]
            self.logger.warning(f"🔄 WebSocket failover: connection {old_index} → {self.ws_primary_index}")
            return new_ws
        return None

    def start_websocket(
        self,
        on_tick: Optional[Callable[[Dict], None]] = None,
        on_order_update: Optional[Callable[[Dict], None]] = None,
        num_connections: int = 1
    ):
        """
        Start WebSocket connection(s) for real-time data
        PHASE 5: Supports up to 3 concurrent connections for redundancy

        Args:
            on_tick: Callback function for tick data
            on_order_update: Callback function for order updates
            num_connections: Number of concurrent connections (1-3, default 1)
        """
        if websocket is None:
            self.logger.warning("websocket-client not installed. Run: pip install websocket-client")
            return

        if self.ws_connected:
            self.logger.warning("WebSocket already connected")
            return

        with self._ws_lock:
            self._manual_ws_stop = False
            self._ws_threads = []
            self.ws_connections = []
            self.ws_primary_index = 0

        # Phase 5: Validate num_connections
        num_connections = min(max(1, num_connections), self.ws_max_connections)

        self.on_tick_callback = on_tick
        self.on_order_update_callback = on_order_update

        # Phase 5: Start multiple WebSocket connections for redundancy
        if num_connections > 1:
            self.logger.info(f"🔄 Starting {num_connections} WebSocket connections for redundancy (Phase 5)")
            for i in range(num_connections):
                ws_thread = threading.Thread(
                    target=self._ws_connect,
                    args=(i,),
                    daemon=True,
                    name=f"WebSocket-{i}"
                )
                self._ws_threads.append(ws_thread)
                ws_thread.start()
        else:
            # Original single connection mode
            self.ws_thread = threading.Thread(target=self._ws_connect, args=(0,), daemon=True)
            self._ws_threads.append(self.ws_thread)
            self.ws_thread.start()

    def stop_websocket(self):
        """Stop WebSocket connection (RACE CONDITION FIX v3.1: Thread-safe)"""
        with self._ws_lock:
            self._manual_ws_stop = True
            self.ws_connected = False  # Set first to prevent races
            ws_ref = self.ws  # Capture reference
            ws_connections_ref = list(self.ws_connections)
            ws_thread_ref = self.ws_thread
            ws_threads_ref = list(self._ws_threads)
            self.ws = None  # Clear reference immediately
            self.ws_thread = None
            self._ws_threads = []
            self.ws_connections = []
            self.ws_primary_index = 0
            self.subscriptions.clear()
            self.ws_subscriptions.clear()

        self._clear_pending_ack_state()
        self.logger.info("🧹 Cache Cleared | subscriptions, ws_subscriptions, pending_ack")

        # Close outside lock to avoid deadlock
        if ws_ref:
            try:
                # Check if ws object has close method before calling
                if hasattr(ws_ref, 'close') and callable(ws_ref.close):
                    ws_ref.close()
            except Exception as e:
                self.logger.debug(f"WebSocket close ignored: {e}")

        for ws_conn in ws_connections_ref:
            if ws_conn is ws_ref:
                continue
            try:
                if hasattr(ws_conn, 'close') and callable(ws_conn.close):
                    ws_conn.close()
            except Exception as e:
                self.logger.debug(f"Secondary WebSocket close ignored: {e}")

        if ws_thread_ref and ws_thread_ref.is_alive():
            ws_thread_ref.join(timeout=1.0)
        for thread_ref in ws_threads_ref:
            if thread_ref is ws_thread_ref:
                continue
            if thread_ref and thread_ref.is_alive():
                thread_ref.join(timeout=1.0)

        self.logger.info("WebSocket stopped")

    def _clear_pending_ack_state(self):
        """Clear pending ACK waiters/results to avoid stale wait state."""
        with self._pending_ack_lock:
            self._pending_ack_events.clear()
            self._pending_ack_results.clear()

    def _register_ack_waiter(self, correlation_id: str) -> threading.Event:
        """Register waiter before send to avoid ACK race (ACK arriving too early)."""
        event = threading.Event()
        with self._pending_ack_lock:
            self._pending_ack_events[correlation_id] = event
            self._pending_ack_results[correlation_id] = False
        return event

    def _sanitize_tokens(self, tokens: List[tuple]) -> List[tuple]:
        """Normalize token tuples and remove duplicates while preserving order."""
        unique_tokens: List[tuple] = []
        seen = set()
        for exchange, token, mode in tokens:
            key = (str(exchange), str(token), int(mode))
            if key in seen:
                continue
            seen.add(key)
            unique_tokens.append(key)
        return unique_tokens

    def _sync_subscription_cache(self, tokens: List[tuple], source: str):
        """Keep both local caches in sync after subscribe fallback/success."""
        with self._ws_lock:
            for exchange, token, mode in tokens:
                self.subscriptions[token] = mode
                self.ws_subscriptions[f"{exchange}:{token}:{mode}"] = {
                    "exchange": exchange,
                    "token": token,
                    "mode": mode,
                    "updated_at": int(time.time() * 1000),
                    "source": source,
                }
        self.logger.info(f"🗂 Cache Rebuilt | source={source} | tokens={len(tokens)}")

    def _remove_from_subscription_cache(self, tokens: List[tuple], source: str):
        """Remove token entries from both subscription caches safely."""
        with self._ws_lock:
            for exchange, token, mode in tokens:
                self.subscriptions.pop(token, None)
                self.ws_subscriptions.pop(f"{exchange}:{token}:{mode}", None)
                stale_keys = [
                    key for key in self.ws_subscriptions
                    if key.split(":", 2)[1] == token
                ]
                for stale_key in stale_keys:
                    self.ws_subscriptions.pop(stale_key, None)
        self.logger.info(f"🧹 Cache Cleared | source={source} | tokens={len(tokens)}")

    def _set_ack_result(self, correlation_id: str, success: bool) -> bool:
        with self._pending_ack_lock:
            if correlation_id in self._pending_ack_events:
                self._pending_ack_results[correlation_id] = success
                self._pending_ack_events[correlation_id].set()
                return True
        return False

    def _wait_for_ack(self, correlation_id: str, timeout: float = 5.0) -> bool:
        event = None
        with self._pending_ack_lock:
            event = self._pending_ack_events.get(correlation_id)
            if event is None:
                event = threading.Event()
                self._pending_ack_events[correlation_id] = event
                self._pending_ack_results[correlation_id] = False

        success = event.wait(timeout)

        with self._pending_ack_lock:
            result = self._pending_ack_results.pop(correlation_id, False)
            self._pending_ack_events.pop(correlation_id, None)

        if not success:
            self.logger.warning(
                f"⚠ ACK Timeout | correlation={correlation_id} | "
                f"reason=No matching SmartAPI ACK within {timeout:.1f}s"
            )
            # Notify broker to apply transport stress limits without crashing the socket
            if hasattr(self, '_broker_ws_ack_timeout_cb'):
                try:
                    self._broker_ws_ack_timeout_cb()
                except Exception:
                    pass
            return False
        return result

    def _ws_is_usable(self, ws_ref) -> bool:
        """WebSocket is usable only when object and underlying socket are alive."""
        if ws_ref is None:
            return False
        try:
            return getattr(ws_ref, 'sock', None) is not None
        except Exception:
            return False

    def _request_ws_reconnect(self, reason: str) -> None:
        """Ask broker layer to reconnect WS without raising from client layer."""
        with self._ws_lock:
            self.ws_connected = False
        cb = getattr(self, '_broker_ws_disconnect_cb', None)
        self.logger.warning(f"🔄 Reconnecting | reason={reason}")
        if cb:
            try:
                cb(reason)
            except Exception as e:
                self.logger.debug(f"WS reconnect callback error ignored: {e}")

    def subscribe(self, tokens: List[tuple]) -> bool:
        """
        Subscribe to market data (RACE CONDITION FIX v3.1: Thread-safe)

        Args:
            tokens: List of (exchange, token, mode) tuples
                Example: [("NFO", "12345", WS_MODE_LTP)]

        Returns:
            True if subscribe message was sent, False otherwise.
        """
        tokens = self._sanitize_tokens(tokens)
        if not tokens:
            self.logger.info("Subscribe skipped: empty token list after normalization")
            return True

        with self._ws_lock:
            if not self.ws_connected or not self.ws:
                self.logger.warning("WebSocket not connected or not initialized")
                self._request_ws_reconnect("subscribe requested while websocket is None")
                return False
            ws_ref = self.ws  # Capture reference while locked
            if not self._ws_is_usable(ws_ref):
                self.logger.warning("WebSocket socket unavailable during subscribe")
                self._request_ws_reconnect("subscribe requested while websocket.sock is None")
                return False

            pending_tokens = [
                token_row for token_row in tokens
                if self.subscriptions.get(token_row[1]) != token_row[2]
            ]
            if not pending_tokens:
                self.logger.info("Subscribe skipped: no new token/mode pairs")
                return True

            # Group by exchange
            exchange_tokens = {}
            for exchange, token, mode in pending_tokens:
                ws_exchange = self._get_ws_exchange_type(exchange)
                if ws_exchange not in exchange_tokens:
                    exchange_tokens[ws_exchange] = []
                exchange_tokens[ws_exchange].append(token)

        # Build subscribe message (outside lock - just data manipulation)
        correlation_id = f"sub_{int(time.time() * 1000)}"
        token_list = []
        for exchange_type, token_ids in exchange_tokens.items():
            token_list.append({
                "exchangeType": exchange_type,
                "tokens": token_ids
            })

        subscribe_msg = {
            "correlationID": correlation_id,
            "action": 1,  # Subscribe
            "params": {
                "mode": tokens[0][2] if tokens else WS_MODE_LTP,
                "tokenList": token_list
            }
        }
        # NOTE: SmartAPI WebSocket 2.0 does not send a JSON acknowledgement
        # frame for subscribe/unsubscribe — confirmed against Angel One's own
        # official smartapi-python SDK, which is fire-and-forget for these
        # actions too (see findings.md §2.10). Waiting on one here previously
        # meant every subscribe blocked for the full timeout, ~95-100% of the
        # time, every session. Real confirmation is the arrival of binary
        # tick data for the subscribed token, verified independently by
        # broker.py's _wait_for_first_ws_tick() after this call returns.
        #
        # Send outside lock to avoid holding lock during I/O
        try:
            if self._ws_is_usable(ws_ref) and hasattr(ws_ref, 'send') and callable(ws_ref.send):
                ws_ref.send(json.dumps(subscribe_msg))
                self._sync_subscription_cache(pending_tokens, source="sent")
                self.logger.info(f"✅ Subscribe Sent | tokens={len(pending_tokens)} | correlation={correlation_id}")
                return True
            else:
                self.logger.warning("WebSocket not ready for subscribe")
                self._request_ws_reconnect("subscribe send blocked: websocket.sock is None")
                return False
        except Exception as e:
            self.logger.warning(f"Subscribe failed: {e}")
            self._request_ws_reconnect(f"subscribe exception: {e}")
            return False

    def unsubscribe(self, tokens: List[tuple]) -> bool:
        """
        Unsubscribe from market data (RACE CONDITION FIX v3.1: Thread-safe)

        Args:
            tokens: List of (exchange, token, mode) tuples

        Returns:
            True if unsubscribe message was sent, False otherwise.
        """
        tokens = self._sanitize_tokens(tokens)
        if not tokens:
            self.logger.info("Unsubscribe skipped: empty token list after normalization")
            return True

        with self._ws_lock:
            if not self.ws_connected or not self.ws:
                self._request_ws_reconnect("unsubscribe requested while websocket is None")
                return False
            ws_ref = self.ws  # Capture reference while locked
            if not self._ws_is_usable(ws_ref):
                self._request_ws_reconnect("unsubscribe requested while websocket.sock is None")
                return False

            pending_tokens = [token_row for token_row in tokens if token_row[1] in self.subscriptions]
            if not pending_tokens:
                self.logger.info("Unsubscribe skipped: tokens not present in cache")
                return True

            # Build unsubscribe message
            exchange_tokens = {}
            for exchange, token, mode in pending_tokens:
                ws_exchange = self._get_ws_exchange_type(exchange)
                if ws_exchange not in exchange_tokens:
                    exchange_tokens[ws_exchange] = []
                exchange_tokens[ws_exchange].append(token)

        correlation_id = f"unsub_{int(time.time() * 1000)}"
        token_list = []
        for exchange_type, token_ids in exchange_tokens.items():
            token_list.append({
                "exchangeType": exchange_type,
                "tokens": token_ids
            })

        unsubscribe_msg = {
            "correlationID": correlation_id,
            "action": 0,  # Unsubscribe
            "params": {
                "mode": tokens[0][2] if tokens else WS_MODE_LTP,
                "tokenList": token_list
            }
        }
        # See the matching NOTE in subscribe() — same fire-and-forget rationale.
        try:
            if self._ws_is_usable(ws_ref) and hasattr(ws_ref, 'send') and callable(ws_ref.send):
                ws_ref.send(json.dumps(unsubscribe_msg))
                self._remove_from_subscription_cache(pending_tokens, source="sent")
                self.logger.info(f"✅ Unsubscribe Sent | tokens={len(pending_tokens)} | correlation={correlation_id}")
                return True
            self._request_ws_reconnect("unsubscribe send blocked: websocket.sock is None")
            return False
        except Exception as e:
            self.logger.debug(f"Unsubscribe failed: {e}")
            self._request_ws_reconnect(f"unsubscribe exception: {e}")
            return False

    def _ws_connect(self, connection_id: int = 0):
        """Internal: Connect to WebSocket"""
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "x-api-key": self.api_key,
            "x-client-code": self.client_id,
            "x-feed-token": self.feed_token
        }

        ws_app = websocket.WebSocketApp(
            WEBSOCKET_URL,
            header=headers,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_ping=lambda ws, msg: None,  # Handle ping from server
            on_pong=self._on_ws_pong  # Track pong responses
        )

        with self._ws_lock:
            if connection_id == 0:
                self.ws = ws_app
            if ws_app not in self.ws_connections:
                self.ws_connections.append(ws_app)

        # Use protocol-level pings every 25s to prevent idle timeout
        # Angel One closes connections after ~60s of inactivity
        ws_app.run_forever(ping_interval=25, ping_timeout=10)

    def _on_ws_open(self, ws):
        """WebSocket opened"""
        with self._ws_lock:
            self.ws_connected = True
            self._manual_ws_stop = False
        self.logger.info("✅ Connected | websocket opened")

        # Start heartbeat thread
        self._start_heartbeat()

    def _on_ws_message(self, ws, message):
        """WebSocket message received"""
        try:
            # Check if it's a text message (pong or error)
            if isinstance(message, str):
                if message == "pong":
                    return
                # Try to parse as JSON (error message or ack)
                try:
                    data = json.loads(message)
                    correlation_id = data.get('correlationID') or data.get('correlationId') or data.get('correlation_id')
                    if correlation_id:
                        status = True
                        if 'errorCode' in data and data.get('errorCode') not in (None, 0, '0', '00'):
                            status = False
                        if 'status' in data and data.get('status') is False:
                            status = False
                        matched = self._set_ack_result(correlation_id, status)
                        if matched:
                            self.logger.info(f"✅ ACK Received | correlation={correlation_id} | status={status}")
                        else:
                            self.logger.debug(f"ACK received without pending waiter | correlation={correlation_id} | payload={data}")
                        if not status:
                            self.logger.warning(f"WebSocket NACK for correlation {correlation_id}: {data}")
                        return
                    if 'errorCode' in data:
                        self.logger.error(f"WebSocket error: {data.get('errorMessage')}")
                    return
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    self.logger.debug(f"WebSocket JSON parse warning: {e}")

            # Binary message - parse tick data
            if isinstance(message, bytes):
                tick = self._parse_ws_binary(message)
                if tick and self.on_tick_callback:
                    self.on_tick_callback(tick)

        except Exception as e:
            self.logger.error(f"WebSocket message error: {e}")

    def _on_ws_error(self, ws, error):
        """WebSocket error"""
        error_text = str(error)
        lowered = error_text.lower()
        is_conn_limit = (
            "429" in lowered
            or "connection limit exceeded" in lowered
            or "too many requests" in lowered
        )

        if is_conn_limit:
            now_ts = time.time()
            last_ts = getattr(self, '_last_ws_429_log_ts', 0.0)
            if now_ts - last_ts >= 30:
                self.logger.warning("⚠ WebSocket rejected by broker (HTTP 429 connection limit exceeded)")
                self._last_ws_429_log_ts = now_ts
        else:
            self.logger.error(f"WebSocket error: {error}")

        # Notify BrokerInterface that WebSocket is no longer reliable
        if hasattr(self, '_broker_ws_disconnect_cb') and self._broker_ws_disconnect_cb:
            self._broker_ws_disconnect_cb(f"WS error: {error_text}")

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """WebSocket closed"""
        with self._ws_lock:
            is_manual = self._manual_ws_stop
            is_active_ws = ws is self.ws
            if is_active_ws:
                self.ws_connected = False
            if ws in self.ws_connections:
                try:
                    self.ws_connections.remove(ws)
                except ValueError:
                    pass

        self.logger.info(f"❌ Disconnected | code={close_status_code} | msg={close_msg}")

        if not is_active_ws:
            self.logger.debug("Ignoring close callback from non-primary websocket")
            return
        if is_manual:
            self.logger.info("Manual websocket stop acknowledged; reconnect not requested")
            return
        # Notify BrokerInterface that WebSocket disconnected
        if hasattr(self, '_broker_ws_disconnect_cb') and self._broker_ws_disconnect_cb:
            self._broker_ws_disconnect_cb(f"WS closed: {close_status_code} - {close_msg}")

    def _on_ws_pong(self, ws, message):
        """Handle pong response from server - connection is alive"""
        # Protocol-level pong received, connection is healthy
        pass

    def _start_heartbeat(self):
        """
        Legacy heartbeat method - now handled by WebSocket protocol pings.
        Kept for backwards compatibility but no longer sends text pings.
        The ws.run_forever(ping_interval=25, ping_timeout=10) handles keepalive.
        """
        pass  # Protocol-level pings handle this now

    def _get_ws_exchange_type(self, exchange: str) -> int:
        """Convert exchange string to WebSocket exchange type"""
        mapping = {
            'NSE': WS_EXCHANGE_NSE_CM,
            'NFO': WS_EXCHANGE_NSE_FO,
            'BSE': WS_EXCHANGE_BSE_CM,
            'BFO': WS_EXCHANGE_BSE_FO,
            'MCX': WS_EXCHANGE_MCX_FO,
            'CDS': WS_EXCHANGE_CDE_FO
        }
        return mapping.get(exchange, WS_EXCHANGE_NSE_CM)
