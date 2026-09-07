"""
Regression tests: kill-switch/emergency exits finalize the same accounting
as a normal SL/TP/RSI exit.

Guards against reintroducing the gap fixed in fixed.md §17 —
core/main.py's close_current_trade() (the exit path used by every
kill-switch, stale-data, high-latency, and manual/shutdown exit) used to
call state.update_pnl() and stop, skipping RiskManager.record_trade(),
log_trade_exit(), and close_position() entirely. Those three only ever ran
on the "normal" exit path inside state_machine.state_in_trade(). Confirmed
live on 2026-09-01: two kill-switch-exited trades were left with
active_positions rows stuck 'ACTIVE' and trades rows stuck 'OPEN' forever,
and their losses never reached RiskManager's daily PnL/streak counters —
which are what real-time position sizing and the §14.7 consecutive-loss
pause actually gate on.

The fix factored the three calls into a single shared helper,
state_machine.finalize_trade_exit_accounting(), called from both exit
paths. These tests protect that both paths actually call it.
"""
from unittest.mock import MagicMock, patch

import core.main as main_module
from core.engines.state_machine import TradingState


def _make_state():
    state = TradingState()
    state.current_trade = {
        'order_id': 'TEST_ORDER_1',
        'direction': 'CE',
        'symbol': 'NIFTY01SEP2624000CE',
        'mfe_inr': 50.0,
        'mae_inr': -20.0,
    }
    return state


class TestCloseCurrentTradeFinalizesFullAccounting:
    def test_close_current_trade_calls_shared_finalizer(self):
        """close_current_trade() must call finalize_trade_exit_accounting()
        — not just state.update_pnl() — so RiskManager/log_trade_exit/
        close_position all run on kill-switch/emergency exits too."""
        state = _make_state()
        logger = MagicMock()
        exit_result = {
            'pnl_inr': -100.0,
            'pnl_pct': -1.5,
            'hold_time': 30,
            'exit_confirmed': True,
            'exit_price': 95.0,
            'exit_reason': 'Kill switch: Wide spread KILL',
        }

        with patch.object(main_module.broker, 'exit_position', return_value=exit_result), \
             patch.object(main_module, 'finalize_trade_exit_accounting') as mock_finalize:
            ok = main_module.close_current_trade(state, 'Kill switch: Wide spread KILL', logger)

        assert ok is True
        mock_finalize.assert_called_once()
        call_args = mock_finalize.call_args.args
        assert call_args[0] == 'TEST_ORDER_1'  # order_id
        assert call_args[1] == 'CE'  # trade_direction
        assert call_args[2] == exit_result  # result

    def test_kill_switch_exit_closes_the_db_position_row(self):
        """End-to-end: a kill-switch exit through close_current_trade() must
        reach database.close_position() for the exited order_id — the exact
        gap that left two rows stuck ACTIVE forever on 2026-09-01."""
        state = _make_state()
        logger = MagicMock()
        exit_result = {
            'pnl_inr': -50.0,
            'pnl_pct': -0.8,
            'hold_time': 10,
            'exit_confirmed': True,
            'exit_price': 5.97,
            'exit_reason': 'Kill switch: Wide spread KILL',
        }

        with patch.object(main_module.broker, 'exit_position', return_value=exit_result), \
             patch('core.services.database.close_position') as mock_close_position, \
             patch('core.services.database.log_trade_exit'), \
             patch('core.risk.risk_manager.get_risk_manager', return_value=None):
            ok = main_module.close_current_trade(state, 'Kill switch: Wide spread KILL', logger)

        assert ok is True
        mock_close_position.assert_called_once_with('TEST_ORDER_1')

    def test_kill_switch_exit_records_pnl_with_risk_manager(self):
        """A kill-switch exit's loss must reach RiskManager.record_trade()
        — RiskManager.daily_pnl feeds real position-sizing decisions and its
        own consecutive_losses is what §14.7's pause gates on."""
        state = _make_state()
        logger = MagicMock()
        exit_result = {
            'pnl_inr': -50.0,
            'pnl_pct': -0.8,
            'hold_time': 10,
            'exit_confirmed': True,
            'exit_price': 5.97,
            'exit_reason': 'Kill switch: Wide spread KILL',
        }
        mock_rm = MagicMock()

        with patch.object(main_module.broker, 'exit_position', return_value=exit_result), \
             patch('core.services.database.close_position'), \
             patch('core.services.database.log_trade_exit'), \
             patch('core.risk.risk_manager.get_risk_manager', return_value=mock_rm):
            ok = main_module.close_current_trade(state, 'Kill switch: Wide spread KILL', logger)

        assert ok is True
        # The payload also carries entry/exit/qty since 2026-09-08: RiskManager
        # charges the round-trip transaction cost there, and without prices it
        # cannot, so the trade would be recorded gross the way every trade before
        # that date was. This fixture's trade has no entry_price/qty, so those
        # come through as None — which is the honest answer, and record_trade()
        # then charges nothing rather than inventing a cost.
        mock_rm.record_trade.assert_called_once_with({
            'pnl': -50.0,
            'direction': 'CE',
            'entry_price': None,
            'exit_price': 5.97,
            'qty': None,
        })

    def test_a_priced_exit_forwards_what_the_cost_model_needs(self):
        """With prices present the cost of the round trip is computable, which is
        the whole point of forwarding them."""
        state = _make_state()
        state.current_trade['entry_price'] = 150.0
        state.current_trade['qty'] = 65
        logger = MagicMock()
        exit_result = {
            'pnl_inr': -455.0, 'pnl_pct': -1.5, 'hold_time': 30,
            'exit_confirmed': True, 'exit_price': 143.0, 'exit_reason': 'SL',
        }
        mock_rm = MagicMock()

        with patch.object(main_module.broker, 'exit_position', return_value=exit_result), \
             patch('core.services.database.close_position'), \
             patch('core.services.database.log_trade_exit'), \
             patch('core.risk.risk_manager.get_risk_manager', return_value=mock_rm):
            main_module.close_current_trade(state, 'SL', logger)

        payload = mock_rm.record_trade.call_args[0][0]
        assert payload['entry_price'] == 150.0
        assert payload['exit_price'] == 143.0
        assert payload['qty'] == 65
