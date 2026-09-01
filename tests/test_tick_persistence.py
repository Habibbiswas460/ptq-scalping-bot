"""
Regression tests for the tick-persistence write path — see fixed.md's
tick-persistence entry.

The `ticks` table existed in schema with no writer at all, so every
post-exit / counterfactual strategy-layer analysis had to fall back to
sparse ~30-90s log-line snapshots (or the underlying spot series) instead
of the real tick stream. `DatabaseManager.log_tick()` / the module-level
`log_tick()` wrapper write to that table; `BrokerInterface._persist_tick()`
(called from `get_tick()`) is what actually feeds it in production, deduped
so the ~2Hz main-loop cadence re-serving an unchanged cached tick doesn't
flood the table, and skipping simulated ticks entirely since they aren't
real market data.
"""
import importlib
from unittest.mock import MagicMock, patch

import pytest


def _reload_database_to_tmp(monkeypatch, tmp_path):
    import core.services.database as database_module

    db_file = tmp_path / "tick_persistence_test.db"
    monkeypatch.setattr(database_module, "DB_PATH", str(db_file), raising=False)
    database_module.DatabaseManager._instance = None
    return importlib.reload(database_module)


class TestLogTickWritesToDB:
    def test_log_tick_inserts_a_row(self, monkeypatch, tmp_path):
        database_module = _reload_database_to_tmp(monkeypatch, tmp_path)

        row_id = database_module.log_tick({
            'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06, 'bid': 104.8,
            'ask': 105.3, 'volume': 1200, 'spot_price': 24050.0, 'oi': 800,
            'timestamp': 1788237912000,
        })

        assert row_id is not None
        conn = database_module.db._get_connection().__enter__()
        cur = conn.cursor()
        cur.execute('SELECT symbol, ltp, bid, ask, spot_price FROM ticks WHERE id = ?', (row_id,))
        row = cur.fetchone()
        assert row['symbol'] == 'NIFTY01SEP2624000CE'
        assert row['ltp'] == 105.06
        assert row['bid'] == 104.8
        assert row['spot_price'] == 24050.0

    def test_log_tick_without_symbol_or_ltp_is_a_no_op(self, monkeypatch, tmp_path):
        database_module = _reload_database_to_tmp(monkeypatch, tmp_path)

        assert database_module.log_tick({'ltp': 105.06}) is None  # no symbol
        assert database_module.log_tick({'symbol': 'X'}) is None  # no ltp


class TestBrokerPersistTick:
    def _make_broker(self):
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        broker.logger = MagicMock()
        return broker

    def test_persist_tick_calls_log_tick(self):
        broker = self._make_broker()
        tick = {'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06, 'bid': 104.8, 'ask': 105.3}

        with patch('core.services.database.log_tick') as mock_log_tick:
            broker._persist_tick(tick)

        mock_log_tick.assert_called_once_with(tick)

    def test_persist_tick_dedupes_identical_consecutive_ticks(self):
        """The ~2Hz main loop re-serving the same cached WS tick (with only
        its timestamp refreshed) must not write a duplicate row each call."""
        broker = self._make_broker()
        tick = {'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06, 'bid': 104.8, 'ask': 105.3}

        with patch('core.services.database.log_tick') as mock_log_tick:
            broker._persist_tick(dict(tick))
            broker._persist_tick(dict(tick))
            broker._persist_tick(dict(tick))

        mock_log_tick.assert_called_once()

    def test_persist_tick_logs_again_when_price_changes(self):
        broker = self._make_broker()

        with patch('core.services.database.log_tick') as mock_log_tick:
            broker._persist_tick({'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06, 'bid': 104.8, 'ask': 105.3})
            broker._persist_tick({'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.20, 'bid': 104.9, 'ask': 105.5})

        assert mock_log_tick.call_count == 2

    def test_persist_tick_no_op_without_symbol(self):
        broker = self._make_broker()
        with patch('core.services.database.log_tick') as mock_log_tick:
            broker._persist_tick({'ltp': 105.06})
        mock_log_tick.assert_not_called()

    def test_persist_tick_never_raises_on_db_failure(self):
        """Persistence is analytics-only — a DB error must never propagate
        into the live tick-serving path."""
        broker = self._make_broker()
        with patch('core.services.database.log_tick', side_effect=Exception("disk full")):
            broker._persist_tick({'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06})  # must not raise


class TestGetTickPersistsOnlyRealTicks:
    def _make_broker(self):
        from core.trading.broker import BrokerInterface
        broker = BrokerInterface()
        broker.logger = MagicMock()
        return broker

    def test_simulated_tick_is_not_persisted(self, monkeypatch):
        broker = self._make_broker()
        broker._get_tick_uncached = MagicMock(
            return_value={'symbol': 'SIM', 'ltp': 100.0, 'data_source': 'SIMULATION'}
        )
        broker._persist_tick = MagicMock()

        broker.get_tick()

        broker._persist_tick.assert_not_called()

    def test_real_tick_is_persisted(self):
        broker = self._make_broker()
        broker._get_tick_uncached = MagicMock(
            return_value={'symbol': 'NIFTY01SEP2624000CE', 'ltp': 105.06, 'data_source': 'WEBSOCKET'}
        )
        broker._persist_tick = MagicMock()

        broker.get_tick()

        broker._persist_tick.assert_called_once()
