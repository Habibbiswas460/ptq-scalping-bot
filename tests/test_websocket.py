"""
Unit Tests for WebSocket Improvements
Tests algo trading optimizations and connection management
"""

import pytest
import time
from unittest.mock import patch, MagicMock, PropertyMock

from brokers.angel_one.client import AngelOneClient


class TestWebSocketConfig:
    """Test WebSocket configuration values"""
    
    def test_heartbeat_timeout_value(self):
        """Test heartbeat timeout is set for algo trading (30s)"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._ws_heartbeat_timeout == 30
    
    def test_max_reconnect_attempts(self):
        """Test max reconnect attempts is reasonable"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._ws_max_reconnect_attempts >= 10
    
    def test_circuit_breaker_cooldown(self):
        """Test circuit breaker cooldown is 3 minutes"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._ws_circuit_cooldown_sec == 180  # 3 minutes
    
    def test_tick_buffer_enabled(self):
        """Test tick buffer is enabled for algo trading"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._use_tick_buffer == True
        assert broker._tick_buffer_max_size == 10


class TestWebSocketStatus:
    """Test WebSocket status methods"""
    
    def test_get_ws_status_exists(self):
        """Test get_ws_status method exists"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, 'get_ws_status')
        assert callable(broker.get_ws_status)
    
    def test_get_ws_status_returns_dict(self):
        """Test get_ws_status returns proper dictionary"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        status = broker.get_ws_status()
        
        assert isinstance(status, dict)
        assert 'connected' in status
        assert 'reconnect_attempts' in status
        assert 'circuit_breaker_open' in status
        assert 'tick_buffer_size' in status
    
    def test_get_smoothed_tick_exists(self):
        """Test get_smoothed_tick method exists"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, 'get_smoothed_tick')
        assert callable(broker.get_smoothed_tick)
    
    def test_clear_tick_buffer_exists(self):
        """Test clear_tick_buffer method exists"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, 'clear_tick_buffer')
        assert callable(broker.clear_tick_buffer)


class TestPreMarketReconnect:
    """Test pre-market reconnect feature"""
    
    def test_premarket_reconnect_flag_exists(self):
        """Test pre-market reconnect done flag exists"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, '_ws_premarket_reconnect_done')
        assert broker._ws_premarket_reconnect_done == False
    
    def test_premarket_reconnect_margin(self):
        """Test pre-market reconnect margin is 2 minutes"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._premarket_reconnect_margin_sec == 120  # 2 minutes
    
    def test_reset_premarket_reconnect_exists(self):
        """Test reset_premarket_reconnect method exists"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, 'reset_premarket_reconnect')
        assert callable(broker.reset_premarket_reconnect)


class TestExponentialBackoff:
    """Test exponential backoff for reconnection"""
    
    def test_reconnect_delay_exists(self):
        """Test reconnect delay variables exist"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert hasattr(broker, '_ws_reconnect_delay')
        assert hasattr(broker, '_ws_max_reconnect_delay')
    
    def test_reconnect_delay_values(self):
        """Test reconnect delay starts at 1s, max 30s"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._ws_reconnect_delay == 1.0
        assert broker._ws_max_reconnect_delay == 30.0


class TestWebSocketReconnectGuards:
    """Regression tests for websocket None/sock None reconnect guards."""

    def test_subscribe_with_missing_socket_requests_reconnect_without_crash(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        client.ws_connected = True
        client.ws = MagicMock()
        client.ws.sock = None
        client._broker_ws_disconnect_cb = MagicMock()

        ok = client.subscribe([("NFO", "12345", 1)])

        assert ok is False
        client._broker_ws_disconnect_cb.assert_called()

    def test_unsubscribe_with_none_websocket_requests_reconnect_without_crash(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        client.ws_connected = True
        client.ws = None
        client._broker_ws_disconnect_cb = MagicMock()

        ok = client.unsubscribe([("NFO", "12345", 1)])

        assert ok is False
        client._broker_ws_disconnect_cb.assert_called()


class TestBrokerSplitSubscriptions:
    """Regression tests for startup WebSocket split-by-mode subscriptions."""

    def test_start_websocket_subscribes_spot_then_option(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._option_token = "44649"
        broker.broker_client = MagicMock()
        broker.broker_client.ws_connected = True
        broker._start_ws_heartbeat_monitor = MagicMock()
        broker._subscribe_with_retry = MagicMock(side_effect=[True, True])

        broker._start_websocket()

        assert broker._subscribe_with_retry.call_count == 2
        assert broker._subscribe_with_retry.call_args_list[0].args[0] == [("NSE", "99926000", 1)]
        assert broker._subscribe_with_retry.call_args_list[1].args[0] == [("NFO", "44649", 2)]
        assert broker._ws_connected is True

    def test_start_websocket_only_spot_when_option_missing(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._option_token = None
        broker.broker_client = MagicMock()
        broker.broker_client.ws_connected = True
        broker._start_ws_heartbeat_monitor = MagicMock()
        broker._subscribe_with_retry = MagicMock(return_value=True)

        broker._start_websocket()

        broker._subscribe_with_retry.assert_called_once_with([("NSE", "99926000", 1)])
        assert broker._ws_connected is True

    def test_start_websocket_marks_disconnected_if_option_subscribe_fails(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._option_token = "44649"
        broker.broker_client = MagicMock()
        broker.broker_client.ws_connected = True
        broker._start_ws_heartbeat_monitor = MagicMock()
        broker._subscribe_with_retry = MagicMock(side_effect=[True, False])

        broker._start_websocket()

        assert broker._subscribe_with_retry.call_count == 2
        assert broker._ws_connected is False


class TestClientReliabilityHardening:
    """Regression tests for client-side websocket reliability infrastructure."""

    def test_ack_waiter_handles_early_ack_signal(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)

        client._register_ack_waiter("sub_test")
        assert client._set_ack_result("sub_test", True) is True
        assert client._wait_for_ack("sub_test", timeout=0.01) is True

    def test_subscribe_ack_timeout_falls_back_to_local_cache(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        client.ws_connected = True
        client.ws = MagicMock()
        client.ws.sock = object()
        client._wait_for_ack = MagicMock(return_value=False)

        ok = client.subscribe([("NFO", "12345", 2)])

        assert ok is True
        assert client.subscriptions.get("12345") == 2
        assert "NFO:12345:2" in client.ws_subscriptions

    def test_duplicate_subscribe_is_skipped(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        client.ws_connected = True
        client.ws = MagicMock()
        client.ws.sock = object()
        client.subscriptions["12345"] = 2

        ok = client.subscribe([("NFO", "12345", 2)])

        assert ok is True
        client.ws.send.assert_not_called()

    def test_stop_websocket_clears_runtime_state(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        ws = MagicMock()
        client.ws = ws
        client.ws_connected = True
        client.ws_connections = [ws]
        client.subscriptions["12345"] = 2
        client.ws_subscriptions["NFO:12345:2"] = {"token": "12345", "mode": 2}
        client._pending_ack_events["sub_1"] = MagicMock()
        client._pending_ack_results["sub_1"] = False

        client.stop_websocket()

        assert client.ws_connected is False
        assert client.ws is None
        assert client.subscriptions == {}
        assert client.ws_subscriptions == {}
        assert client._pending_ack_events == {}
        assert client._pending_ack_results == {}

    def test_manual_close_does_not_trigger_reconnect_callback(self):
        logger = MagicMock()
        client = AngelOneClient("k", "c", "p", "t", logger=logger)
        ws = MagicMock()
        client.ws = ws
        client.ws_connections = [ws]
        client.ws_connected = True
        client._manual_ws_stop = True
        client._broker_ws_disconnect_cb = MagicMock()

        client._on_ws_close(ws, None, None)

        client._broker_ws_disconnect_cb.assert_not_called()


class TestBrokerReliabilityHardening:
    """Regression tests for broker reconnect and shutdown infrastructure."""

    def test_reconnect_worker_not_started_when_already_running(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._ws_reconnect_running = True

        with patch("core.trading.broker.threading.Thread") as thread_cls:
            broker._trigger_ws_reconnect()
            thread_cls.assert_not_called()

    def test_reconnect_skipped_when_shutdown_requested(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._ws_shutdown_requested = True

        with patch("core.trading.broker.threading.Thread") as thread_cls:
            broker._trigger_ws_reconnect()
            thread_cls.assert_not_called()

    def test_disconnect_ignored_during_shutdown(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.logger = MagicMock()
        broker._ws_shutdown_requested = True
        broker._trigger_ws_reconnect = MagicMock()

        broker._on_ws_disconnect("manual shutdown")

        broker._trigger_ws_reconnect.assert_not_called()

    def test_logout_stops_websocket_and_heartbeat(self):
        from core.trading.broker import BrokerInterface

        broker = BrokerInterface()
        broker.broker_client = MagicMock()
        broker._ws_connected = True
        broker._ws_heartbeat_thread = MagicMock()
        broker._ws_heartbeat_thread.is_alive.return_value = True

        broker.logout()

        assert broker._ws_shutdown_requested is True
        assert broker._ws_connected is False
        broker.broker_client.stop_websocket.assert_called_once()
        broker._ws_heartbeat_thread.join.assert_called_once_with(timeout=1.0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
