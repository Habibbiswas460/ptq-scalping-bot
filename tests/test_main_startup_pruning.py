"""
Regression test: core/main.py's main() prunes old signal/dvf_signal/tick
rows at startup, not just app.py.

prune_old_signal_rows() was previously only ever called from app.py, ahead
of run_with_auto_reconnect() -- true today (run.sh launches app.py, which
does call it), but core/main.py's own main() is the function actually
invoked on every reconnect and is also directly callable on its own (as
this test file and test_p0_historical_warmup.py both do), so wiring it in
here too is defense-in-depth rather than relying on a single call site.
See fixed.md's tick-persistence entry for the write path this pruning now
also covers.
"""
from unittest.mock import MagicMock, patch

import core.main as core_main


def test_main_prunes_old_signal_rows_at_startup():
    mock_broker = MagicMock()
    mock_broker.connect.return_value = True

    old_broker = core_main.broker
    old_rc = core_main.run_readiness_check
    core_main.broker = mock_broker
    core_main.run_readiness_check = MagicMock(side_effect=RuntimeError("STOP"))

    try:
        with patch('core.services.database.prune_old_signal_rows') as mock_prune:
            try:
                core_main.main()
            except RuntimeError as e:
                assert str(e) == "STOP"
    finally:
        core_main.broker = old_broker
        core_main.run_readiness_check = old_rc

    mock_prune.assert_called_once_with(retention_days=7)


def test_main_does_not_crash_if_pruning_fails():
    """Pruning must never block startup -- a DB error here should be
    swallowed, same as app.py's own try/except around this call."""
    mock_broker = MagicMock()
    mock_broker.connect.return_value = True

    old_broker = core_main.broker
    old_rc = core_main.run_readiness_check
    core_main.broker = mock_broker
    core_main.run_readiness_check = MagicMock(side_effect=RuntimeError("STOP"))

    try:
        with patch('core.services.database.prune_old_signal_rows', side_effect=Exception("disk full")):
            with_raised = False
            try:
                core_main.main()
            except RuntimeError as e:
                with_raised = str(e) == "STOP"
            assert with_raised, "main() should still reach run_readiness_check despite the pruning failure"
    finally:
        core_main.broker = old_broker
        core_main.run_readiness_check = old_rc
