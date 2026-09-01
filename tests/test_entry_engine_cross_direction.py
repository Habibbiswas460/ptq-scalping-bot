"""
Regression tests for entry_engine.entry_signal()'s cross-direction
instrument check — the fix for the bug documented in fixed.md's
entry-engine audit.

Pattern detection (smart_scalp_v3.generate_signal()) runs on spot price
and is direction-agnostic, so its signal direction can differ from
whichever option contract happens to be currently subscribed. Before this
fix, the premium filter, spread check, drift-guard reference price, and
live-mode Greeks gate all read the subscribed contract's tick regardless
of the signal's actual direction — confirmed live on 2026-09-01, where
two PE signals were validated against a CE contract's ~₹98 premium and
then filled on a PE contract at ₹6-11, well below the configured ₹70
floor, because nothing re-checked the PE's own price before entering.

These tests exercise entry_signal() with smart_scalp_signal() and the
session-trend gates mocked out, so only the cross-direction tick logic
itself is under test.
"""
from unittest.mock import MagicMock, patch

import core.engines.entry_engine as entry_engine_module
from core.engines.entry_engine import entry_signal


def _base_params(direction='PE', confidence=82):
    return {
        'direction': direction,
        'confidence': confidence,
        'details': {'rsi': 40},
    }


def _patched(monkeypatch, *, current_symbol, signal_params, cross_tick=None,
             subscribed_tick_ltp=98.0):
    dummy_recent_ticks = [{'ltp': subscribed_tick_ltp, 'spot_price': 24050.0}] * 10
    monkeypatch.setattr(
        entry_engine_module.runtime_state, 'get_recent_ticks',
        lambda max_items=None: dummy_recent_ticks
    )
    monkeypatch.setattr(
        entry_engine_module, 'smart_scalp_signal',
        lambda ticks: (True, 'CE PULLBACK: Score 66% | Conf 82%', signal_params)
    )
    monkeypatch.setattr(entry_engine_module, 'can_trade_ce', lambda rsi: (True, 'CE OK'))
    monkeypatch.setattr(entry_engine_module, 'can_trade_pe', lambda rsi: (True, 'PE OK'))
    monkeypatch.setattr(entry_engine_module, '_log_signal_snapshot', MagicMock())

    mock_broker = MagicMock()
    mock_broker.current_symbol = current_symbol
    mock_broker.get_tick_for_direction = MagicMock(return_value=cross_tick)

    subscribed_tick = {
        'ltp': subscribed_tick_ltp, 'bid': subscribed_tick_ltp - 0.2,
        'ask': subscribed_tick_ltp + 0.2, 'spot_price': 24050.0,
        'symbol': current_symbol,
    }
    return mock_broker, subscribed_tick


class TestCrossDirectionInstrumentCheck:
    def test_same_direction_does_not_fetch_cross_direction_tick(self, monkeypatch):
        """Subscribed to a CE, signal is CE — no mismatch, no extra fetch,
        the subscribed tick's premium is used directly."""
        mock_broker, subscribed_tick = _patched(
            monkeypatch,
            current_symbol='NIFTY01SEP2624000CE',
            signal_params=_base_params(direction='CE'),
            subscribed_tick_ltp=98.0,
        )

        with patch('core.trading.broker.broker', mock_broker):
            ok, message = entry_signal(subscribed_tick, day_type='NORMAL')

        assert ok is True
        mock_broker.get_tick_for_direction.assert_not_called()

    def test_cross_direction_rejects_on_target_contracts_own_premium(self, monkeypatch):
        """Subscribed to a CE (premium ₹98, would pass the filter), signal
        is PE — the PE's own premium (₹6.12) must be what's checked, and
        it must be rejected as too low. This is the exact 2026-09-01 bug:
        without the fix, this entry would have passed on the CE's ₹98."""
        cross_tick = {
            'ltp': 6.12, 'bid': 6.05, 'ask': 6.20, 'spot_price': 24050.0,
            'symbol': 'NIFTY01SEP2624000PE', 'direction': 'PE',
        }
        mock_broker, subscribed_tick = _patched(
            monkeypatch,
            current_symbol='NIFTY01SEP2624000CE',
            signal_params=_base_params(direction='PE'),
            cross_tick=cross_tick,
            subscribed_tick_ltp=98.0,
        )

        with patch('core.trading.broker.broker', mock_broker):
            ok, message = entry_signal(subscribed_tick, day_type='NORMAL')

        mock_broker.get_tick_for_direction.assert_called_once_with('PE')
        assert ok is False
        assert 'Premium too low' in message
        assert '₹6' in message

    def test_cross_direction_allows_entry_when_target_premium_is_fine(self, monkeypatch):
        """Same mismatch, but the PE's own premium is within range — entry
        should proceed, proving this isn't just a blanket cross-direction
        rejection."""
        cross_tick = {
            'ltp': 95.0, 'bid': 94.8, 'ask': 95.2, 'spot_price': 24050.0,
            'symbol': 'NIFTY01SEP2624000PE', 'direction': 'PE',
        }
        mock_broker, subscribed_tick = _patched(
            monkeypatch,
            current_symbol='NIFTY01SEP2624000CE',
            signal_params=_base_params(direction='PE'),
            cross_tick=cross_tick,
            subscribed_tick_ltp=98.0,
        )

        with patch('core.trading.broker.broker', mock_broker):
            ok, message = entry_signal(subscribed_tick, day_type='NORMAL')

        assert ok is True

    def test_cross_direction_tick_unavailable_rejects_entry(self, monkeypatch):
        """If the target contract's tick can't be fetched at all, refuse
        the entry rather than silently falling back to the wrong tick."""
        mock_broker, subscribed_tick = _patched(
            monkeypatch,
            current_symbol='NIFTY01SEP2624000CE',
            signal_params=_base_params(direction='PE'),
            cross_tick=None,
            subscribed_tick_ltp=98.0,
        )

        with patch('core.trading.broker.broker', mock_broker):
            ok, message = entry_signal(subscribed_tick, day_type='NORMAL')

        assert ok is False
        assert 'Cross-direction tick unavailable' in message

    def test_cross_direction_rejects_on_wide_spread(self, monkeypatch):
        """The target contract's own spread must be checked too — a
        premium that passes but a spread that doesn't should still block."""
        cross_tick = {
            'ltp': 95.0, 'bid': 90.0, 'ask': 95.0, 'spot_price': 24050.0,
            'symbol': 'NIFTY01SEP2624000PE', 'direction': 'PE',
        }
        mock_broker, subscribed_tick = _patched(
            monkeypatch,
            current_symbol='NIFTY01SEP2624000CE',
            signal_params=_base_params(direction='PE'),
            cross_tick=cross_tick,
            subscribed_tick_ltp=98.0,
        )

        with patch('core.trading.broker.broker', mock_broker):
            ok, message = entry_signal(subscribed_tick, day_type='NORMAL')

        assert ok is False
        assert 'Spread too wide' in message
