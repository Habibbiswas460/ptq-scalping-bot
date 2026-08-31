import pytest
from unittest.mock import MagicMock
from core.runtime.state import runtime_state
import core.main as core_main
from strategies.smart_scalp_v3 import SmartScalpV3


def test_strategy_calculate_indicators_works_with_canonical_candles():
    runtime_state.historical_candles = [
        {"timestamp": f"2026-08-15T09:{str(minute).zfill(2)}:00+05:30", "open": 100 + minute, "high": 110 + minute, "low": 90 + minute, "close": 105 + minute, "volume": 1000}
        for minute in range(20)
    ]

    strategy = SmartScalpV3()
    indicators = strategy.calculate_indicators([])

    assert "High" in indicators
    assert "Low" in indicators
    assert indicators["Close"] > 0


def test_startup_warmup_loads_candles():
    mock_broker = MagicMock()
    mock_broker.connect.return_value = True
    mock_broker.get_historical_candles.return_value = [
        {"timestamp": f"2026-08-15 09:15", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
    ] * 50
    
    old_broker = core_main.broker
    core_main.broker = mock_broker
    
    old_rc = core_main.run_readiness_check
    core_main.run_readiness_check = MagicMock(side_effect=RuntimeError("STOP"))
    
    try:
        with pytest.raises(RuntimeError, match="STOP"):
            core_main.main()
    finally:
        core_main.broker = old_broker
        core_main.run_readiness_check = old_rc
        
    assert len(runtime_state.historical_candles) == 50
    assert runtime_state.historical_candles[0]["open"] == 100

