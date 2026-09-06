"""MARKET_OPEN / MARKET_CLOSE must actually decide something.

Both were documented in .env, parsed into config.constants, and read by nothing except a
print(). Every function that decided whether the market was open wrote 09:15 and 15:30
into the code, so changing the setting changed nothing at all.
"""
from datetime import datetime

import pytest

from config import constants as C


@pytest.mark.parametrize("text_open, text_close, expected", [
    ("09:15", "15:30", ((9, 15), (15, 30))),
    ("10:00", "14:00", ((10, 0), (14, 0))),
    ("9:5",   "15:30", ((9, 5), (15, 30))),
])
def test_market_hours_parses_the_setting(monkeypatch, text_open, text_close, expected):
    monkeypatch.setattr(C, "MARKET_OPEN_TIME", text_open)
    monkeypatch.setattr(C, "MARKET_CLOSE_TIME", text_close)
    assert C.market_hours() == expected


@pytest.mark.parametrize("bad", ["", "nonsense", "25:00", "09:99", None, "0915"])
def test_a_malformed_setting_falls_back_to_nse_hours(monkeypatch, bad):
    # A typo in .env must not stop the bot, and must not invent a session either.
    monkeypatch.setattr(C, "MARKET_OPEN_TIME", bad)
    monkeypatch.setattr(C, "MARKET_CLOSE_TIME", bad)
    assert C.market_hours() == ((9, 15), (15, 30))


def _at(hh, mm):
    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 8, hh, mm)
    return _Now


def test_market_open_follows_the_setting(monkeypatch):
    import utils.helpers as helpers

    monkeypatch.setattr(helpers, "TEST_MODE", False)
    monkeypatch.setattr(helpers, "market_hours", lambda: ((10, 0), (14, 0)))

    monkeypatch.setattr(helpers, "datetime", _at(9, 30))
    assert helpers.market_open() is False        # inside NSE hours, outside the setting
    monkeypatch.setattr(helpers, "datetime", _at(10, 30))
    assert helpers.market_open() is True
    monkeypatch.setattr(helpers, "datetime", _at(14, 30))
    assert helpers.market_open() is False


def test_the_readiness_gate_follows_the_setting(monkeypatch):
    import utils.market_readiness_checker as checker

    monkeypatch.setattr(C, "MARKET_OPEN_TIME", "10:00")
    monkeypatch.setattr(C, "MARKET_CLOSE_TIME", "14:00")
    monkeypatch.setattr(checker, "datetime", _at(9, 30))
    assert checker._is_market_open_now() is False
    monkeypatch.setattr(checker, "datetime", _at(10, 30))
    assert checker._is_market_open_now() is True


def test_default_hours_are_unchanged_by_all_of_this():
    # The wiring must not have moved the live behaviour: .env ships NSE's own hours.
    assert C.market_hours() == ((9, 15), (15, 30))


def test_the_spot_token_is_named_once_and_is_the_nse_index(monkeypatch):
    # Verified against the published instrument master: 99926000 is NSE "Nifty 50".
    # It had been spelled out at seven call sites; these are the ones that consume it.
    import importlib

    # core.trading exports a BrokerInterface instance under the name "broker", so the
    # module has to be fetched explicitly rather than by attribute.
    broker = importlib.import_module("core.trading.broker")
    collector = importlib.import_module("utils.run_historical_collector")

    assert C.NIFTY_SPOT_TOKEN == "99926000"
    assert broker.NIFTY_SPOT_TOKEN == C.NIFTY_SPOT_TOKEN
    assert collector.NIFTY_SPOT_TOKEN == C.NIFTY_SPOT_TOKEN


def test_no_production_module_still_spells_the_token_out():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in list((root / "core").rglob("*.py")) + list((root / "utils").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The definition in config/ is the one place it may appear.
        if re.search(r'["\']99926000["\']', text):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"spot token written out again in: {offenders}"


def _on(dt_value):
    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return dt_value
    return _Now


@pytest.mark.parametrize("when, expected, note", [
    (datetime(2026, 9, 5, 11, 0), False, "Saturday"),
    (datetime(2026, 9, 6, 11, 0), False, "Sunday"),
    (datetime(2026, 9, 7, 11, 0), True, "Monday"),
    (datetime(2026, 9, 8, 11, 0), True, "Tuesday"),
    (datetime(2026, 9, 11, 11, 0), True, "Friday"),
])
def test_market_open_is_false_at_the_weekend(monkeypatch, when, expected, note):
    """market_open() gates core/main.py's trading loop.

    It used to check the clock and nothing else, so at 11:00 on a Saturday or Sunday it
    said the market was open and the bot went straight into the loop.
    market_readiness_checker had always refused weekends, so the two disagreed.
    """
    import utils.helpers as helpers

    monkeypatch.setattr(helpers, "TEST_MODE", False)
    monkeypatch.setattr(helpers, "datetime", _on(when))
    assert helpers.market_open() is expected, note


def test_the_weekday_check_does_not_replace_the_time_check(monkeypatch):
    import utils.helpers as helpers

    monkeypatch.setattr(helpers, "TEST_MODE", False)
    monkeypatch.setattr(helpers, "datetime", _on(datetime(2026, 9, 8, 8, 0)))
    assert helpers.market_open() is False        # a weekday, but before the open
    monkeypatch.setattr(helpers, "datetime", _on(datetime(2026, 9, 8, 16, 0)))
    assert helpers.market_open() is False        # a weekday, but after the close


def test_readiness_and_helpers_agree_about_the_weekend(monkeypatch):
    """The disagreement is the thing being fixed, so pin that they now match."""
    import utils.helpers as helpers
    import utils.market_readiness_checker as checker

    monkeypatch.setattr(helpers, "TEST_MODE", False)
    for when in (datetime(2026, 9, 5, 11, 0), datetime(2026, 9, 6, 11, 0),
                 datetime(2026, 9, 8, 11, 0)):
        monkeypatch.setattr(helpers, "datetime", _on(when))
        monkeypatch.setattr(checker, "datetime", _on(when))
        assert helpers.market_open() is checker._is_market_open_now(), when
