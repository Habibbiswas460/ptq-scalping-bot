"""Guards for the session time gates.

The strategy used to hard-code a 09:45 opening block that could not be turned off without
editing code, which meant the most volatile part of the session was permanently unreachable.
It is now configurable. These tests keep the CODE default at the historical 09:45 so a
checkout with no .env still reproduces the frozen baseline, and check the override works.
"""
import importlib
import pytest

import config.constants as C
from config.configuration import env_bool, env_str
from strategies import smart_scalp_v3


@pytest.fixture(autouse=True)
def _restore():
    yield
    importlib.reload(C)
    importlib.reload(smart_scalp_v3)


def test_code_default_preserves_the_historical_block(monkeypatch):
    """No .env entry must mean the old 09:45 behaviour, so the baseline stays reproducible."""
    monkeypatch.delenv('TRADING_NO_TRADE_BEFORE', raising=False)
    assert env_str('TRADING_NO_TRADE_BEFORE', '09:45') == '09:45'
    monkeypatch.delenv('TRADING_START', raising=False)
    monkeypatch.delenv('SESSION_FILTER_ENABLED', raising=False)
    assert env_str('TRADING_START', '09:20') == '09:20'
    assert env_bool('SESSION_FILTER_ENABLED', True) is True


def test_parser_reads_the_configured_time(monkeypatch):
    monkeypatch.setenv('TRADING_NO_TRADE_BEFORE', '09:15')
    importlib.reload(C)
    importlib.reload(smart_scalp_v3)
    assert smart_scalp_v3._parse_no_trade_before() == (9, 15)


def test_parser_falls_back_rather_than_opening_the_session(monkeypatch):
    """A typo must not silently unblock the whole session — fall back to the historical value."""
    for bad in ('', 'not-a-time', '09-45', None):
        monkeypatch.setenv('TRADING_NO_TRADE_BEFORE', bad if bad is not None else '')
        importlib.reload(C)
        importlib.reload(smart_scalp_v3)
        assert smart_scalp_v3._parse_no_trade_before() == (9, 45), f"failed for {bad!r}"


def test_block_comparison_semantics():
    """The gate compares (hour, minute) tuples, so it must work across the hour boundary."""
    block = (9, 15)
    assert (9, 14) < block          # blocked
    assert not (9, 15) < block      # open at exactly the configured time
    assert not (9, 30) < block
    assert not (15, 29) < block


def test_session_filter_can_be_disabled(monkeypatch):
    """ALLOWED_SESSIONS start at 09:20 and end at 15:15, so the filter has to be switchable."""
    monkeypatch.setenv('SESSION_FILTER_ENABLED', 'false')
    importlib.reload(C)
    import core.engines.state_machine as sm
    importlib.reload(sm)
    allowed, reason = sm.is_trading_session_allowed('NORMAL')
    assert allowed is True and 'disabled' in reason.lower()
    importlib.reload(sm)


def test_market_close_exit_still_guards_the_new_late_window():
    """TRADING_END is now 15:30, so the 15:25 close-exit is the only thing standing between an
    open position and the shutdown. It must still be present."""
    src = open(smart_scalp_v3.__file__.replace('strategies/smart_scalp_v3.py',
                                               'core/engines/exit_engine.py')).read()
    assert "now.hour == 15 and now.minute >= 25" in src
    assert "MARKET CLOSE EXIT" in src
