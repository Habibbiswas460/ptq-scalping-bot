"""
Regression tests for BrokerInterface.get_tick_for_direction() — the fix for
the entry-engine cross-direction bug documented in fixed.md's entry-engine
audit: every entry-decision tick-based check (premium filter, spread) used
to read get_tick(), which reflects whichever option contract happens to be
currently subscribed. Pattern detection is spot-price-based and
direction-agnostic, so a signal's direction routinely differs from the
subscribed contract — confirmed live on 2026-09-01, where two PE signals
were validated against a CE contract's ~₹98 premium and then filled on a
PE contract at ₹6-11, well below the configured ₹70 floor.

get_tick_for_direction() closes that gap by fetching a real tick for the
contract that will actually be traded when the direction differs from the
subscription, instead of silently reusing the subscribed contract's tick.
"""
from unittest.mock import MagicMock

from core.trading.broker import BrokerInterface


def _make_broker():
    broker = BrokerInterface()
    broker.logger = MagicMock()
    return broker


def test_same_direction_reuses_get_tick_no_extra_fetch():
    """When the requested direction matches the subscribed contract, no
    cross-direction fetch is needed — just defer to the normal get_tick()."""
    broker = _make_broker()
    broker.current_symbol = 'NIFTY01SEP2624000CE'
    broker._build_option_symbol = lambda strike, option_type: f'NIFTY01SEP2624000{option_type}'
    broker.get_tick = MagicMock(return_value={'ltp': 100.0, 'symbol': 'NIFTY01SEP2624000CE'})
    broker.broker_client = MagicMock()

    tick = broker.get_tick_for_direction('CE')

    assert tick == {'ltp': 100.0, 'symbol': 'NIFTY01SEP2624000CE'}
    broker.get_tick.assert_called_once()
    broker.broker_client.get_market_tick.assert_not_called()


def test_cross_direction_fetches_the_target_contract_not_the_subscribed_one():
    """Subscribed to a CE, but asked for the PE at the same strike — must
    fetch the PE's own tick via the broker client, not reuse the CE tick."""
    broker = _make_broker()
    broker.current_symbol = 'NIFTY01SEP2624000CE'
    broker.current_strike = 24000
    broker.spot_price = 24050.0
    broker._build_option_symbol = lambda strike, option_type: f'NIFTY01SEP2624000{option_type}'
    broker.get_tick = MagicMock(return_value={'ltp': 98.0, 'symbol': 'NIFTY01SEP2624000CE'})
    broker.broker_client = MagicMock()
    broker.broker_client.get_market_tick.return_value = {
        'ltp': 6.12, 'bid': 6.05, 'ask': 6.20, 'symbol': 'NIFTY01SEP2624000PE',
    }

    tick = broker.get_tick_for_direction('PE')

    broker.broker_client.get_market_tick.assert_called_once_with(
        symbol='NIFTY01SEP2624000PE', exchange='NFO'
    )
    assert tick['ltp'] == 6.12
    assert tick['symbol'] == 'NIFTY01SEP2624000PE'
    assert tick['direction'] == 'PE'
    assert tick['strike'] == 24000
    assert tick['spot_price'] == 24050.0
    broker.get_tick.assert_not_called()


def test_cross_direction_returns_none_without_broker_client():
    broker = _make_broker()
    broker.current_symbol = 'NIFTY01SEP2624000CE'
    broker._build_option_symbol = lambda strike, option_type: f'NIFTY01SEP2624000{option_type}'
    broker.broker_client = None

    assert broker.get_tick_for_direction('PE') is None


def test_cross_direction_returns_none_on_fetch_exception():
    broker = _make_broker()
    broker.current_symbol = 'NIFTY01SEP2624000CE'
    broker._build_option_symbol = lambda strike, option_type: f'NIFTY01SEP2624000{option_type}'
    broker.broker_client = MagicMock()
    broker.broker_client.get_market_tick.side_effect = ConnectionError("network down")

    assert broker.get_tick_for_direction('PE') is None
