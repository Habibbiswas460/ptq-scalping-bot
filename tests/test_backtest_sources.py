"""Source-layer parsing and windowing. No network: every test feeds a canned payload.

These cover the two vendor quirks that silently corrupt a dataset if missed —
Yahoo's trailing quote bar and the SmartAPI row cap — plus the chunker that keeps
requests under the cap.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from research.backtest import broker_source, sources

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


# ── chunking ─────────────────────────────────────────────────────────────────

def test_chunks_cover_the_range_without_overlap_or_holes():
    frm, to = _dt.date(2026, 1, 1), _dt.date(2026, 3, 31)
    chunks = list(broker_source._day_chunks(frm, to, broker_source.MAX_WINDOW_DAYS))
    assert chunks[0][0] == frm and chunks[-1][1] == to
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert next_start == prev_end + _dt.timedelta(days=1)


def test_every_chunk_stays_under_the_row_cap():
    """20 calendar days holds at most 15 trading days = 5625 bars, under 8000.

    The SmartAPI cap is a ROW COUNT (~8000), not the documented 30 days. A
    30-day chunk containing 22 trading days silently loses two thirds of its
    oldest session, and the response gives no sign of it.
    """
    assert broker_source.MAX_WINDOW_DAYS <= 20
    worst_case_trading_days = broker_source.MAX_WINDOW_DAYS
    assert worst_case_trading_days * 375 < broker_source.ROW_CAP


def test_single_day_window_is_one_chunk():
    d = _dt.date(2026, 9, 4)
    assert list(broker_source._day_chunks(d, d, 20)) == [(d, d)]


# ── SmartAPI row parsing ─────────────────────────────────────────────────────

def test_parse_rows_marks_open_interest_absent_not_zero():
    """getCandleData carries no OI. A 0 would be read downstream as a reading."""
    rows = [["2026-09-04T09:15:00+05:30", 100.0, 101.0, 99.0, 100.5, 1234]]
    out = broker_source._parse_rows(rows)
    assert len(out) == 1
    assert out[0]["oi"] is None
    assert out[0]["volume"] == 1234
    assert out[0]["ts"].tzinfo is not None


def test_parse_rows_handles_an_empty_response():
    assert broker_source._parse_rows([]) == []
    assert broker_source._parse_rows(None) == []


# ── credential handling ──────────────────────────────────────────────────────

def test_credential_status_returns_only_booleans():
    """A token has been leaked on this project twice by printing a config object.
    This helper must never be able to carry a secret to a caller."""
    st = broker_source.credential_status()
    assert set(st) >= {"ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD",
                       "ANGEL_TOTP_SECRET"}
    for k, v in st.items():
        assert isinstance(v, bool), f"{k} leaked a non-boolean"


# ── ScripMaster normalisation ────────────────────────────────────────────────

def test_scripmaster_strikes_and_ticks_are_converted_from_paise():
    scrip = {"contracts": {
        "NIFTY08SEP2623900CE": {"token": "42635", "expiry": "08SEP2026",
                                "strike": "2390000.000000", "lotsize": "65",
                                "tick_size": "5.000000", "instrumenttype": "OPTIDX"},
    }}
    got = broker_source.nifty_option_contracts(scrip)
    assert len(got) == 1
    c = got[0]
    assert c["strike"] == 23900.0          # not 2390000
    assert c["tick_size"] == pytest.approx(0.05)   # not 5.0
    assert c["lot_size"] == 65
    assert c["expiry"] == _dt.date(2026, 9, 8)
    assert c["instrument_type"] == "CE"


def test_scripmaster_ignores_non_option_rows():
    scrip = {"contracts": {
        "NIFTY26SEPFUT": {"token": "1", "expiry": "29SEP2026", "strike": "0",
                          "lotsize": "65", "tick_size": "5", "instrumenttype": "FUTIDX"},
    }}
    assert broker_source.nifty_option_contracts(scrip) == []


def test_atm_band_selects_only_the_requested_expiry_and_strike_window():
    def c(strike, kind, expiry):
        return {"token": "1", "symbol": f"X{strike}{kind}", "instrument_type": kind,
                "strike": float(strike), "expiry": expiry, "lot_size": 65,
                "tick_size": 0.05}
    e1, e2 = _dt.date(2026, 9, 8), _dt.date(2026, 9, 15)
    contracts = [c(23900, "CE", e1), c(23900, "PE", e1), c(24500, "CE", e1),
                 c(23900, "CE", e2)]
    got = broker_source.atm_band(contracts, e1, 23850, 23950)
    assert {g["symbol"] for g in got} == {"X23900CE", "X23900PE"}


# ── Yahoo's trailing quote bar ───────────────────────────────────────────────

def _ybar(hh, mm):
    ts = _dt.datetime(2026, 9, 4, hh, mm, tzinfo=IST)
    return {"ts": ts, "epoch": int(ts.timestamp()), "open": 1.0, "high": 1.0,
            "low": 1.0, "close": 1.0, "volume": 0, "oi": 0}


def test_yahoo_trailing_1530_quote_bar_is_dropped():
    """Yahoo appends one row stamped at the last regular-market time. It is not a
    376th traded minute, and keeping it puts a duplicate close into the series."""
    bars = [_ybar(9, 15), _ybar(15, 28), _ybar(15, 29), _ybar(15, 30)]
    out = sources._strip_yahoo_artifact(bars)
    assert len(out) == 3
    assert all(b["ts"].time() < _dt.time(15, 30) for b in out)


def test_yahoo_stripper_keeps_a_full_normal_session():
    bars = [_ybar(9, 15 + i) if 15 + i < 60 else _ybar(10, (15 + i) % 60)
            for i in range(30)]
    assert len(sources._strip_yahoo_artifact(bars)) == 30


def test_measured_source_limits_are_recorded_as_constants():
    """These were probed, not read off a doc page; freeze them so a later edit
    that loosens one has to be deliberate."""
    assert sources.YAHOO_MAX_WINDOW_DAYS == 8
    assert sources.UPSTOX_MAX_WINDOW_DAYS == 30
    assert sources.UPSTOX_1M_EPOCH.year == 2022
    assert sources.BARS_PER_SESSION == 375
