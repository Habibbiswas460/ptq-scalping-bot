import importlib
import time
from unittest.mock import MagicMock

broker_module = importlib.import_module('core.trading.broker')
from core.trading.broker import BrokerInterface
from core.risk.validators import is_data_valid


def _mock_broker_logger(broker: BrokerInterface):
    broker.logger = MagicMock()
    return broker


def test_websocket_tick_freshness_allows_old_ws_ticks(monkeypatch):
    monkeypatch.setattr(broker_module, 'USE_LIVE_DATA', True)
    broker = _mock_broker_logger(BrokerInterface())
    broker._ws_connected = True
    broker.current_symbol = 'NIFTY25000CE'
    broker.last_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000) - 8000,
        'original_timestamp': int(time.time() * 1000) - 8000,
        'data_source': 'WEBSOCKET',
    }
    broker._ws_original_tick_time = time.time() - 8
    tick = broker.get_tick()
    assert tick is not None
    assert tick['data_source'] == 'WEBSOCKET'


def test_websocket_stale_tick_triggers_rest_refresh(monkeypatch):
    monkeypatch.setattr(broker_module, 'USE_LIVE_DATA', True)
    broker = _mock_broker_logger(BrokerInterface())
    broker._ws_connected = True
    broker.current_symbol = 'NIFTY25000CE'
    broker.last_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000) - 70000,
        'original_timestamp': int(time.time() * 1000) - 70000,
        'data_source': 'WEBSOCKET',
    }
    broker._ws_original_tick_time = time.time() - 70

    refreshed_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 102.0,
        'bid': 101.5,
        'ask': 102.5,
        'timestamp': int(time.time() * 1000),
        'original_timestamp': int(time.time() * 1000),
        'data_source': 'REST_REFRESH',
    }
    monkeypatch.setattr(broker, '_fetch_option_tick_rest', lambda: refreshed_tick)

    tick = broker.get_tick()
    assert tick is not None
    assert tick['data_source'] == 'REST_REFRESH'
    assert tick['symbol'] == broker.current_symbol
    assert tick['ltp'] == 102.0


def test_websocket_stale_tick_without_rest_refresh_returns_none(monkeypatch):
    monkeypatch.setattr(broker_module, 'USE_LIVE_DATA', True)
    broker = _mock_broker_logger(BrokerInterface())
    broker._ws_connected = True
    broker.current_symbol = 'NIFTY25000CE'
    broker.last_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000) - 70000,
        'original_timestamp': int(time.time() * 1000) - 70000,
        'data_source': 'WEBSOCKET',
    }
    broker._ws_original_tick_time = time.time() - 70

    monkeypatch.setattr(broker, '_fetch_option_tick_rest', lambda: None)

    tick = broker.get_tick()
    assert tick is None


def test_websocket_tick_symbol_mismatch_refreshes_to_current_symbol(monkeypatch):
    monkeypatch.setattr(broker_module, 'USE_LIVE_DATA', True)
    broker = _mock_broker_logger(BrokerInterface())
    broker._ws_connected = True
    broker.current_symbol = 'NIFTY25000PE'
    broker.last_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000),
        'original_timestamp': int(time.time() * 1000),
        'data_source': 'WEBSOCKET',
    }
    broker._ws_original_tick_time = time.time()

    refreshed_tick = {
        'symbol': 'NIFTY25000PE',
        'ltp': 98.0,
        'bid': 97.5,
        'ask': 98.5,
        'timestamp': int(time.time() * 1000),
        'original_timestamp': int(time.time() * 1000),
        'data_source': 'REST_REFRESH',
    }
    monkeypatch.setattr(broker, '_fetch_option_tick_rest', lambda: refreshed_tick)

    tick = broker.get_tick()
    assert tick is not None
    assert tick['data_source'] == 'REST_REFRESH'
    assert tick['symbol'] == 'NIFTY25000PE'
    assert tick['ltp'] == 98.0


def test_rest_tick_freshness_rejects_old_rest_ticks():
    rest_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000) - 6000,
        'original_timestamp': int(time.time() * 1000) - 6000,
        'data_source': 'REST',
    }
    valid, reason = is_data_valid(rest_tick)
    assert valid is False
    assert 'Stale tick' in reason


def test_rest_tick_freshness_allows_recent_rest_ticks():
    rest_tick = {
        'symbol': 'NIFTY25000CE',
        'ltp': 100.0,
        'bid': 99.5,
        'ask': 100.5,
        'timestamp': int(time.time() * 1000) - 4000,
        'original_timestamp': int(time.time() * 1000) - 4000,
        'data_source': 'REST',
    }
    valid, reason = is_data_valid(rest_tick)
    assert valid is True
    assert reason == 'OK'
