import core.risk.validators as validators


def test_ws_tick_with_configured_threshold_is_not_rejected(monkeypatch):
    validators.reset_validation_stats()

    validators.CONFIG["data_hygiene"]["stale_threshold_ms_websocket"] = 10000
    validators.CONFIG["data_hygiene"]["stale_threshold_ms_rest"] = 5000
    validators.CONFIG["data_hygiene"]["stale_threshold_ms_unknown"] = 2000

    base_time = 10_000_000
    monkeypatch.setattr(validators, "current_time_ms", lambda: base_time)

    tick = {
        "bid": 100.0,
        "ask": 101.0,
        "ltp": 100.5,
        "spot_price": 20000,
        "timestamp": base_time - 9000,
        "original_timestamp": base_time - 9000,
        "data_source": "WS",
        "symbol": "NIFTY25000CE",
        "volume": 100,
    }

    is_valid, reason = validators.is_data_valid(tick)

    assert is_valid is True, reason
    assert "Stale" not in reason
