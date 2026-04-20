"""
Unit Tests for Kill Switch Module
Tests latency, stale data, and spread kill switch functionality
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestLatencyKillSwitch:
    """Test latency-based kill switch (500ms threshold, recoverable)"""
    
    def test_high_latency_threshold(self):
        """Test HIGH_LATENCY_THRESHOLD_MS is set to 500ms"""
        from core.risk.kill_switch import HIGH_LATENCY_THRESHOLD_MS
        assert HIGH_LATENCY_THRESHOLD_MS == 500
    
    def test_latency_status_initial(self):
        """Test initial latency status"""
        from core.risk.kill_switch import get_latency_status
        status = get_latency_status()
        assert 'paused' in status
        assert 'high_count' in status
        assert 'threshold_ms' in status
        assert status['threshold_ms'] == 500
    
    def test_latency_not_paused_initially(self):
        """Test latency pause is not active initially"""
        from core.risk.kill_switch import is_high_latency_paused
        assert is_high_latency_paused() == False


class TestStaleDataKillSwitch:
    """Test stale data kill switch functionality"""
    
    def test_stale_data_function_exists(self):
        """Test is_stale_data_kill_active function exists"""
        from core.risk.kill_switch import is_stale_data_kill_active
        assert callable(is_stale_data_kill_active)
    
    def test_stale_data_not_active_initially(self):
        """Test stale data kill is not active initially"""
        from core.risk.kill_switch import is_stale_data_kill_active
        assert is_stale_data_kill_active() == False
    
    def test_rejected_tick_counter_functions_exist(self):
        """Test rejected tick tracking functions exist"""
        from core.risk.kill_switch import track_rejected_tick, reset_rejected_tick_counter
        assert callable(track_rejected_tick)
        assert callable(reset_rejected_tick_counter)


class TestEmergencyCheck:
    """Test emergency_check function"""
    
    def test_emergency_check_function_exists(self):
        """Test emergency_check function exists"""
        from core.risk.kill_switch import emergency_check
        assert callable(emergency_check)
    
    def test_emergency_check_returns_tuple(self):
        """Test emergency_check returns proper tuple structure"""
        from core.risk.kill_switch import emergency_check
        
        # Create mock tick with current timestamp
        mock_tick = {
            'timestamp': int(time.time() * 1000),
            'ltp': 100.0,
            'bid': 99.5,
            'ask': 100.5,
        }
        
        # Call with current function signature
        result = emergency_check(
            tick=mock_tick,
            daily_pnl_inr=-500,
            total_trades_today=5,
            last_valid_tick_time=datetime.now()
        )
        
        # Should return tuple (kill_triggered: bool, reason: str, details: dict)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)
        assert isinstance(result[2], dict)


class TestKillSwitchImports:
    """Test all kill switch exports are available"""
    
    def test_all_exports_available(self):
        """Test all expected functions are exported"""
        from core.risk.kill_switch import (
            emergency_check,
            track_rejected_tick,
            reset_rejected_tick_counter,
            is_stale_data_kill_active,
            is_high_latency_paused,
            get_latency_status,
            HIGH_LATENCY_THRESHOLD_MS,
        )
        # If we get here without ImportError, test passes
        assert True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
