"""
Tests for core trading functions
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigLoader:
    """Test configuration loading"""
    
    def test_load_config_success(self):
        """Test that config loads successfully"""
        from config.config_loader import load_config
        config = load_config()
        assert config is not None
        assert 'broker' in config
        assert 'capital' in config
        assert 'trading' in config
        assert 'risk_management' in config
    
    def test_config_has_required_keys(self):
        """Test that config has all required keys"""
        from config.config_loader import load_config
        config = load_config()
        
        # Check capital settings
        assert 'total_capital' in config['capital']
        assert config['capital']['total_capital'] > 0
        
        # Check trading settings
        assert 'symbol' in config['trading']
        assert 'lot_size' in config['trading']
        
        # Check risk settings
        assert 'stop_loss_amount' in config['risk_management']
        assert 'max_trades_per_day' in config['risk_management']


class TestStatePersistence:
    """Test state persistence functions"""
    
    def test_load_daily_state_no_file(self, tmp_path):
        """Test loading state when no file exists"""
        from state.state_persistence import load_daily_state
        # Should return empty dict when file doesn't exist
        state = load_daily_state()
        assert isinstance(state, dict)


class TestUtilityFunctions:
    """Test utility functions"""
    
    def test_current_time_ms(self):
        """Test current_time_ms returns valid timestamp"""
        from utils.utility import current_time_ms
        ts = current_time_ms()
        assert ts > 0
        assert isinstance(ts, int)
    
    def test_now_returns_datetime(self):
        """Test now() returns datetime object"""
        from utils.utility import now
        from datetime import datetime
        result = now()
        assert isinstance(result, datetime)
    
    def test_is_expiry_date(self):
        """Test expiry date detection"""
        from utils.utility import is_expiry_date
        result = is_expiry_date()
        assert isinstance(result, bool)
    
    def test_market_open_test_mode(self):
        """Test market_open in test mode"""
        from utils.utility import market_open
        # In test mode, should always return True
        result = market_open(TEST_MODE=True)
        assert result == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
