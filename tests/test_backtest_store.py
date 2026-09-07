"""The import layer: provenance, gap recording, and the no-fabrication rule.

No network. Every test builds its own in-file SQLite under tmp_path.
"""
from __future__ import annotations

import datetime as _dt
import json

import pytest

from research.backtest import store

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _bar(day: str, hh: int, mm: int, close: float = 100.0, volume: int = 10):
    ts = _dt.datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+05:30")
    return {"ts": ts, "epoch": int(ts.timestamp()), "open": close, "high": close + 1,
            "low": close - 1, "close": close, "volume": volume, "oi": None}


def _session(day: str, n: int = store.BARS_PER_SESSION, start_min: int = 0):
    base = _dt.datetime.fromisoformat(f"{day}T09:15:00+05:30")
    out = []
    for i in range(start_min, start_min + n):
        ts = base + _dt.timedelta(minutes=i)
        out.append({"ts": ts, "epoch": int(ts.timestamp()), "open": 100.0 + i * 0.1,
                    "high": 100.5 + i * 0.1, "low": 99.5 + i * 0.1,
                    "close": 100.0 + i * 0.1, "volume": 5, "oi": None})
    return out


@pytest.fixture()
def con(tmp_path):
    return store.connect(str(tmp_path / "candles.db"))


def test_schema_and_provenance_recorded(con):
    v = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert int(v) == store.SCHEMA_VERSION
    prov = json.loads(con.execute("SELECT value FROM meta WHERE key='provenance'").fetchone()[0])
    # oi, bid, ask and spread must be declared MISSING. If a future change starts
    # populating one of them, this test is the thing that forces the declaration
    # to be updated with it rather than silently going stale.
    for field in ("oi", "bid", "ask", "spread"):
        assert prov[field][0] == "missing", f"{field} must be declared missing"
    assert prov["spot_ohlc"][0] == "real"
    assert prov["candles_5m"][0] == "reconstructed"


def test_session_minutes_is_375_from_0915_to_1529():
    m = store.session_minutes()
    assert len(m) == 375
    assert m[0] == "09:15" and m[-1] == "15:29"


def test_write_and_read_round_trip(con):
    bars = _session("2026-09-01", n=10)
    store.write_candles(con, "NSE:99926000", "NIFTY50", "1m", bars, "test_src")
    got = store.load_candles(con, "NSE:99926000", "test_src", "1m", session_date="2026-09-01")
    assert len(got) == 10
    assert got[0]["ts_ist"].startswith("2026-09-01T09:15")
    assert [g["epoch"] for g in got] == sorted(g["epoch"] for g in got)


def test_two_sources_coexist_rather_than_overwrite(con):
    """`source` is in the primary key so vendors can be compared, not merged."""
    bars = _session("2026-09-01", n=5)
    other = [dict(b, close=b["close"] + 7.0) for b in bars]
    store.write_candles(con, "K", "S", "1m", bars, "angelone_smartapi")
    store.write_candles(con, "K", "S", "1m", other, "upstox")
    a = store.load_candles(con, "K", "angelone_smartapi", "1m")
    b = store.load_candles(con, "K", "upstox", "1m")
    assert len(a) == len(b) == 5
    assert a[0]["close"] != b[0]["close"]


def test_missing_minutes_become_gap_rows_and_are_never_filled(con):
    # 300 of 375 minutes present: the last 75 of the session are absent.
    store.write_candles(con, "K", "S", "1m", _session("2026-09-01", n=300), "src")
    gaps = store.detect_gaps(con, "K", "1m", "src")
    assert len(gaps) == 1
    assert gaps[0]["session_date"] == "2026-09-01"
    assert gaps[0]["missing"] == 75
    # The candles table still holds exactly what the source returned.
    assert len(store.load_candles(con, "K", "src", "1m")) == 300
    row = con.execute("SELECT missing_minutes FROM gaps").fetchone()[0]
    assert json.loads(row)["count"] == 75


def test_complete_session_records_no_gap(con):
    store.write_candles(con, "K", "S", "1m", _session("2026-09-01"), "src")
    assert store.detect_gaps(con, "K", "1m", "src") == []


def test_repaired_day_clears_its_stale_gap_row(con):
    """The SmartAPI row cap truncates a day; refetching it whole must un-gap it."""
    store.write_candles(con, "K", "S", "1m", _session("2026-09-01", n=125), "src")
    assert len(store.detect_gaps(con, "K", "1m", "src")) == 1
    store.write_candles(con, "K", "S", "1m", _session("2026-09-01"), "src")
    assert store.detect_gaps(con, "K", "1m", "src") == []
    assert con.execute("SELECT count(*) FROM gaps").fetchone()[0] == 0


def test_receipt_records_what_was_asked_and_what_came_back(con):
    rid = store.record_run(con, {
        "source": "angelone_smartapi", "endpoint_url": "getCandleData",
        "instrument_key": "NSE:99926000", "interval": "1m",
        "requested_from": "2026-06-07", "requested_to": "2026-09-05",
        "returned_from": "2026-08-06", "returned_to": "2026-09-04",
        "rows_returned": 8000, "clamped": True, "error": None,
        "fetched_at_utc": "2026-09-08T00:00:00+00:00",
    }, "NIFTY50")
    r = con.execute("SELECT * FROM fetch_runs WHERE run_id=?", (rid,)).fetchone()
    assert r["clamped"] == 1
    assert r["requested_from"] == "2026-06-07" and r["returned_from"] == "2026-08-06"


def test_aggregate_builds_5m_from_1m_without_padding():
    bars = []
    for i in range(12):
        ts = _dt.datetime.fromisoformat("2026-09-01T09:15:00+05:30") + _dt.timedelta(minutes=i)
        bars.append({"ts_ist": ts.isoformat(), "open": 100 + i, "high": 101 + i,
                     "low": 99 + i, "close": 100.5 + i, "volume": 2})
    out = store.aggregate(bars, 5)
    # 09:15-09:19, 09:20-09:24, 09:25-09:26 -> three buckets, the last one short.
    assert [c["bars"] for c in out] == [5, 5, 2]
    assert out[0]["timestamp"] == "2026-09-01T09:15:00+05:30"
    assert out[0]["open"] == 100 and out[0]["close"] == 104.5
    assert out[0]["high"] == max(101 + i for i in range(5))
    assert out[0]["low"] == 99
    # A short bucket stays short. Nothing is invented to round it out.
    assert out[-1]["bars"] == 2


def test_aggregate_aligns_to_the_wall_clock_not_the_first_bar():
    """A session that starts late must still land on the 09:15/09:20 grid."""
    bars = []
    for i in range(6):
        ts = _dt.datetime.fromisoformat("2026-09-01T09:17:00+05:30") + _dt.timedelta(minutes=i)
        bars.append({"ts_ist": ts.isoformat(), "open": 100.0, "high": 100.0,
                     "low": 100.0, "close": 100.0, "volume": 0})
    out = store.aggregate(bars, 5)
    assert out[0]["timestamp"].endswith("09:15:00+05:30")
    assert out[0]["bars"] == 3          # 09:17, 09:18, 09:19
    assert out[1]["timestamp"].endswith("09:20:00+05:30")
