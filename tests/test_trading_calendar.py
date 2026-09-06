"""The exchange is shut at weekends and on holidays, and the code must know both.

Weekends were arithmetic and already handled. Holidays were not handled at all: no source
the bot can reach publishes them, so a holiday read as an ordinary trading day. These pin
what the calendar may and may not conclude - above all that it never invents a date.
"""
import datetime as dt
import json

import pytest

from utils import trading_calendar as cal


def _write(tmp_path, entries, name="holidays.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"holidays": entries}), encoding="utf-8")
    return str(p)


# ── the declared file ────────────────────────────────────────────────
def test_declared_dates_are_holidays(tmp_path):
    path = _write(tmp_path, [{"date": "2026-10-02", "name": "Gandhi Jayanti"}])
    assert cal.is_holiday(dt.date(2026, 10, 2), path) is True
    assert cal.holiday_reason(dt.date(2026, 10, 2), path) == "declared: Gandhi Jayanti"
    assert cal.is_trading_day(dt.date(2026, 10, 2), path) is False


def test_a_bare_list_of_dates_is_accepted(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps(["2026-10-02"]), encoding="utf-8")
    assert cal.is_holiday(dt.date(2026, 10, 2), str(p)) is True


def test_a_missing_file_is_empty_not_an_error(tmp_path):
    path = str(tmp_path / "nope.json")
    assert cal.declared_holidays(path) == {}
    assert cal.unknown_calendar(path) is True
    # The inference still supplies expiry-day holidays; what matters is that the report
    # says nothing is declared, because that is the part of the gap a user can close.
    assert "nothing declared" in cal.describe(path)


def test_a_malformed_file_is_empty_not_an_exception(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert cal.declared_holidays(str(p)) == {}


def test_unparseable_entries_are_skipped_not_guessed(tmp_path):
    path = _write(tmp_path, [{"date": "not-a-date"}, {"date": "2026-10-02"}, {}])
    assert set(cal.declared_holidays(path)) == {dt.date(2026, 10, 2)}


# ── inference from expiry shifts ─────────────────────────────────────
def test_an_expiry_that_moved_earlier_implies_a_holiday(monkeypatch):
    # Weeklies expire on Tuesday; one sits on the Monday, so that Tuesday was shut.
    monkeypatch.setattr(cal, "inferred_holidays", cal.inferred_holidays)
    from utils import instruments

    monkeypatch.setattr(instruments, "expiry_dates",
                        lambda path=None: [dt.date(2026, 11, 10), dt.date(2026, 11, 17),
                                           dt.date(2026, 11, 23), dt.date(2026, 12, 1)])
    inferred = cal.inferred_holidays()
    assert dt.date(2026, 11, 24) in inferred


def test_inference_needs_enough_expiries_to_know_the_usual_day(monkeypatch):
    from utils import instruments

    monkeypatch.setattr(instruments, "expiry_dates", lambda path=None: [dt.date(2026, 11, 23)])
    assert cal.inferred_holidays() == {}


def test_the_declared_file_outranks_the_inference(tmp_path, monkeypatch):
    from utils import instruments

    monkeypatch.setattr(instruments, "expiry_dates",
                        lambda path=None: [dt.date(2026, 11, 10), dt.date(2026, 11, 17),
                                           dt.date(2026, 11, 23), dt.date(2026, 12, 1)])
    path = _write(tmp_path, [{"date": "2026-11-24", "name": "Guru Nanak Jayanti"}])
    source, reason = cal.holidays(path)[dt.date(2026, 11, 24)]
    assert source == cal.DECLARED and reason == "Guru Nanak Jayanti"


# ── what it refuses to conclude ──────────────────────────────────────
def test_a_date_with_no_evidence_is_not_called_a_holiday(tmp_path):
    path = _write(tmp_path, [])
    # A Wednesday nobody has said anything about stays a trading day.
    assert cal.is_holiday(dt.date(2026, 10, 7), path) is False
    assert cal.is_trading_day(dt.date(2026, 10, 7), path) is True


def test_observed_sessions_are_never_read_as_evidence_of_a_holiday():
    """The trade store proves days were open; its gaps prove nothing.

    Collection in this project is intermittent, so inverting it would invent holidays on
    every day nobody happened to record.
    """
    observed = cal.observed_trading_days()
    if not observed:
        pytest.skip("no sessions in the trade store")
    gap = observed[0] + dt.timedelta(days=1)
    while gap in observed or gap.weekday() >= 5:
        gap += dt.timedelta(days=1)
    assert gap < observed[-1]
    assert cal.is_holiday(gap) is False


# ── weekends and stepping forward ────────────────────────────────────
@pytest.mark.parametrize("day, expected", [
    (dt.date(2026, 9, 5), False),   # Saturday
    (dt.date(2026, 9, 6), False),   # Sunday
    (dt.date(2026, 9, 8), True),    # Tuesday
])
def test_weekends_are_not_trading_days(tmp_path, day, expected):
    assert cal.is_trading_day(day, _write(tmp_path, [])) is expected


def test_next_trading_day_steps_over_a_holiday_and_a_weekend(tmp_path):
    # Friday 2026-10-02 declared shut -> the next open day is the following Monday.
    path = _write(tmp_path, [{"date": "2026-10-02", "name": "Gandhi Jayanti"}])
    assert cal.next_trading_day(dt.date(2026, 10, 1), path) == dt.date(2026, 10, 5)


def test_next_trading_day_walks_past_a_run_of_closures(tmp_path):
    path = _write(tmp_path, [{"date": d, "name": "x"} for d in
                             ("2026-10-05", "2026-10-06", "2026-10-07")])
    assert cal.next_trading_day(dt.date(2026, 10, 2), path) == dt.date(2026, 10, 8)


# ── the callers ──────────────────────────────────────────────────────
def _at(when):
    class _Now(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    return _Now


def test_market_open_is_false_on_a_declared_holiday(tmp_path, monkeypatch):
    import utils.helpers as helpers

    monkeypatch.setattr(cal, "NSE_HOLIDAY_FILE",
                        _write(tmp_path, [{"date": "2026-10-02", "name": "Gandhi Jayanti"}]))
    monkeypatch.setattr(helpers, "TEST_MODE", False)
    monkeypatch.setattr(helpers, "datetime", _at(dt.datetime(2026, 10, 2, 11, 0)))
    assert helpers.market_open() is False           # a Friday, inside market hours
    monkeypatch.setattr(helpers, "datetime", _at(dt.datetime(2026, 10, 1, 11, 0)))
    assert helpers.market_open() is True


def test_the_readiness_gate_agrees_about_a_holiday(tmp_path, monkeypatch):
    import utils.market_readiness_checker as checker

    monkeypatch.setattr(cal, "NSE_HOLIDAY_FILE",
                        _write(tmp_path, [{"date": "2026-10-02", "name": "Gandhi Jayanti"}]))
    monkeypatch.setattr(checker, "datetime", _at(dt.datetime(2026, 10, 2, 11, 0)))
    assert checker._is_market_open_now() is False


# ── writing the file back ────────────────────────────────────────────
def test_written_dates_are_read_back(tmp_path):
    path = str(tmp_path / "out.json")
    cal.write_declared([dt.date(2026, 10, 2), dt.date(2026, 10, 21)], "test", path)
    assert set(cal.declared_holidays(path)) == {dt.date(2026, 10, 2), dt.date(2026, 10, 21)}
    blob = json.loads(open(path, encoding="utf-8").read())
    assert blob["source"] == "test" and blob["updated"]


def test_writing_does_not_drop_what_was_already_declared(tmp_path):
    path = _write(tmp_path, [{"date": "2026-01-26", "name": "Republic Day"}])
    cal.write_declared([dt.date(2026, 10, 2)], "test", path)
    declared = cal.declared_holidays(path)
    assert declared[dt.date(2026, 1, 26)] == "Republic Day"
    assert dt.date(2026, 10, 2) in declared


def test_the_shipped_calendar_is_empty_and_says_so():
    """It ships empty on purpose: dates nobody verified are worse than a known gap."""
    from config.constants import NSE_HOLIDAY_FILE

    blob = json.loads(open(NSE_HOLIDAY_FILE, encoding="utf-8").read())
    assert blob["holidays"] == []
    assert "unknown" in blob["note"]
