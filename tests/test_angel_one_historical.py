import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from brokers.angel_one.client import AngelOneClient

class TestAngelOneHistorical:
    def test_get_candle_data_wrapper(self):
        client = AngelOneClient("key", "id", "pass", "totp", logger=MagicMock())
        client.smart_api = MagicMock()
        client.is_logged_in = True
        client.login_time = datetime.now()
        
        mock_response = {
            "status": True,
            "data": [
                ["2026-08-14T09:15:00+05:30", 24350.0, 24370.0, 24345.0, 24365.0, 450000]
            ]
        }
        client.smart_api.getCandleData.return_value = mock_response
        
        candles = client.get_candle_data("99926000", "NSE", "FIVE_MINUTE", "2026-08-14 09:15", "2026-08-14 09:20")
        
        assert len(candles) == 1
        assert candles[0][0] == "2026-08-14T09:15:00+05:30"
        
        # Verify the smart API call
        params = client.smart_api.getCandleData.call_args[0][0]
        assert params["interval"] == "FIVE_MINUTE"
        assert params["symboltoken"] == "99926000"
