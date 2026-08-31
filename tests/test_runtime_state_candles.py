import pytest
from core.runtime.state import RuntimeState
import time

def test_add_historical_candles_and_merge():
    state = RuntimeState()
    
    # 1. Provide historical
    state.set_historical_candles([
        {"timestamp": "2026-08-15T09:15:00+05:30", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
        {"timestamp": "2026-08-15T09:20:00+05:30", "open": 105, "high": 115, "low": 100, "close": 112, "volume": 1200}
    ])
    
    # 2. Add some live ticks falling into the next 5-min bucket (09:25)
    import datetime
    dt_base = datetime.datetime.strptime("2026-08-15 09:26:00", "%Y-%m-%d %H:%M:%S")
    
    state.add_tick({"original_timestamp": dt_base.timestamp() * 1000, "spot_price": 110, "volume": 100})
    state.add_tick({"original_timestamp": (dt_base.timestamp() + 60) * 1000, "spot_price": 116, "volume": 200})
    state.add_tick({"original_timestamp": (dt_base.timestamp() + 120) * 1000, "spot_price": 108, "volume": 50})
    state.add_tick({"original_timestamp": (dt_base.timestamp() + 180) * 1000, "spot_price": 114, "volume": 150})
    
    candles = state.get_canonical_candles(interval_min=5)
    
    assert len(candles) == 3
    assert candles[0]["timestamp"] == "2026-08-15T09:15:00+05:30"
    assert candles[1]["timestamp"] == "2026-08-15T09:20:00+05:30"
    
    # Verify the live bucket
    assert candles[2]["timestamp"] == "2026-08-15T09:25:00+05:30"
    assert candles[2]["open"] == 110
    assert candles[2]["high"] == 116
    assert candles[2]["low"] == 108
    assert candles[2]["close"] == 114
    assert candles[2]["volume"] == 500
    assert candles[2]["is_live"] is True

