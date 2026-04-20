"""
Unit Tests for WebSocket Improvements
Tests algo trading optimizations and connection management
"""

import pytest
import time
from unittest.mock import patch, MagicMock, PropertyMock


class TestWebSocketConfig:
    """Test WebSocket configuration values"""
    
    def test_heartbeat_timeout_value(self):
        """Test heartbeat timeout is set for algo trading (15s)"""
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        assert broker._ws_heartbeat_timeout == 15
    
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
