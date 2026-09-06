"""Expiry must come from the broker's contract list, never from a weekday rule.

The bug these guard: utils.helpers.is_expiry_date() returned `weekday() == 3`, and every
NIFTY weekly Angel One lists is a Tuesday - so it was true only on days that are never
expiry, and false on every day that is. core/risk/greeks_calc.py derived time-to-expiry
the same way, putting theta, gamma and detect_day_type()'s classification two days out.
"""
import json
from datetime import date, datetime

import pytest

from utils import expiry


# Real shape of core/data/scripmaster_nifty_nfo.json: the broker's symbol -> token map.
TUESDAYS = ["08SEP26", "15SEP26", "22SEP26", "29SEP26"]


def _write_master(tmp_path, expiries=TUESDAYS, extra=()):
    symbols = {}
    for e in expiries:
        for strike in (24500, 24600, 24700):
            for side in ("CE", "PE"):
                symbols[f"NIFTY{e}{strike}{side}"] = str(len(symbols) + 1)
    for sym in extra:
        symbols[sym] = "0"
    p = tmp_path / "scripmaster.json"
    p.write_text(json.dumps({"saved_at": "x", "token_map": symbols}), encoding="utf-8")
    return str(p)


def test_expiries_are_read_from_the_contract_list(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.expiry_dates(path) == [
        date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]


def test_the_expiry_weekday_is_learned_not_declared(tmp_path):
    # Tuesday is weekday 1. Nothing in the code says so; it is counted from the dump,
    # so an exchange moving expiry again needs no code change.
    assert expiry.expiry_weekday(_write_master(tmp_path)) == 1


def test_a_listed_date_is_expiry_and_a_thursday_is_not(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.is_expiry_date(date(2026, 9, 8), path) is True      # Tuesday, listed
    assert expiry.is_expiry_date(date(2026, 9, 10), path) is False    # Thursday, not listed
    assert date(2026, 9, 10).weekday() == 3                           # the old rule's answer


def test_nearest_and_next_differ_on_expiry_day(tmp_path):
    path = _write_master(tmp_path)
    on_expiry = date(2026, 9, 8)
    assert expiry.nearest_expiry(on_expiry, path) == on_expiry
    # Angel One serves no Greeks for a contract expiring today, so the Greeks path needs
    # the one after it.
    assert expiry.next_expiry_after(on_expiry, path) == date(2026, 9, 15)


def test_expiry_datetime_lands_on_the_close(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.expiry_datetime(date(2026, 9, 8), path) == datetime(2026, 9, 8, 15, 30)


def test_dates_after_the_last_listed_contract_are_unknown(tmp_path):
    path = _write_master(tmp_path)
    assert expiry.nearest_expiry(date(2026, 12, 1), path) is None
    assert expiry.expiry_datetime(date(2026, 12, 1), path) is None


def test_a_missing_master_is_reported_as_unknown_not_guessed(tmp_path):
    absent = str(tmp_path / "does_not_exist.json")
    assert expiry.expiry_dates(absent) == []
    assert expiry.is_expiry_date(date(2026, 9, 10), absent) is False
    assert expiry.nearest_expiry(date(2026, 9, 8), absent) is None
    assert expiry.expiry_weekday(absent) is None
    assert "no expiry data" in expiry.describe(absent)


def test_unreadable_master_is_unknown_rather_than_an_exception(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert expiry.expiry_dates(str(p)) == []


def test_symbols_that_are_not_nifty_options_are_ignored(tmp_path):
    path = _write_master(tmp_path, extra=("BANKNIFTY08SEP2650000CE", "NIFTY", "NIFTYNOTADATE1CE"))
    assert expiry.expiry_dates(path) == [
        date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]


def test_a_rewritten_master_is_re_read(tmp_path):
    # broker startup rewrites this file; a cached parse must not outlive it.
    path = _write_master(tmp_path, ["08SEP26"])
    assert expiry.expiry_dates(path) == [date(2026, 9, 8)]
    _write_master(tmp_path, ["15SEP26"])
    assert expiry.expiry_dates(path) == [date(2026, 9, 15)]


def test_helpers_delegates_to_the_master(tmp_path, monkeypatch):
    from utils import helpers

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))

    class _On(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 9, 8, 10, 0)      # a listed Tuesday

    class _Off(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 9, 10, 10, 0)     # the Thursday the old rule liked

    monkeypatch.setattr(expiry, "datetime", _On)
    assert helpers.is_expiry_date() is True
    monkeypatch.setattr(expiry, "datetime", _Off)
    assert helpers.is_expiry_date() is False


def test_greeks_asks_for_a_date_that_exists(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))
    got = greeks_calc.GreeksFetcher().get_expiry_date_str()
    # Whatever it returns must be a real listed expiry, formatted for the API.
    assert got == "" or datetime.strptime(got, "%d%b%Y").date() in expiry.expiry_dates(
        expiry.SCRIP_MASTER_CACHE_FILE)


def test_greeks_skips_the_api_when_expiry_is_unknown(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", str(tmp_path / "absent.json"))
    fetcher = greeks_calc.GreeksFetcher(broker_client=object())
    assert fetcher.get_expiry_date_str() == ""


def test_resolve_expiry_time_never_lands_on_a_weekday_rule(tmp_path, monkeypatch):
    from core.risk import greeks_calc

    monkeypatch.setattr(expiry, "SCRIP_MASTER_CACHE_FILE", _write_master(tmp_path))
    when = greeks_calc._resolve_expiry_time()
    assert when.date() in expiry.expiry_dates(expiry.SCRIP_MASTER_CACHE_FILE)
    assert (when.hour, when.minute) == (15, 30)
