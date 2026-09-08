"""Upstox expired-instruments loader. No network: every test feeds a canned payload.

Two of these tests are the ones that matter, and they matter because two reports in
this repo disagreed:

  * `test_classify_probe_says_gated_by_auth_not_no_route` freezes the shape of the
    2026-09-08 measurement — 401 on the v2 expired family, 400/UDAPI1021 on the free
    v3 route, 200 on a listed contract. That shape is what distinguishes "the archive
    does not exist" (backtest_data_20260908.md §2) from "the vendor is refusing this
    caller" (what was actually observed).
  * `test_credential_status_never_returns_a_value` is the leak guard. A token has
    leaked twice in this project's history.

The rest cover the parsing, the chunker, the no-fabrication policy on a failed chunk,
and the two verification functions, which are the only reason any of this would ever
be trusted.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import urllib.error

import pytest

from research.backtest import upstox_expired as ux

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


# ── fake transport ───────────────────────────────────────────────────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _ok(payload):
    """An opener that always answers 200 with `payload`, and records the URLs."""
    seen = []

    def opener(req, timeout=None):
        seen.append(req.full_url)
        return _Resp(json.dumps(payload).encode())

    opener.seen = seen
    return opener


def _fail(status, error_code, message="no"):
    """An opener that always raises the Upstox error envelope for `error_code`."""
    body = json.dumps({"status": "error", "errors": [
        {"errorCode": error_code, "message": message,
         "error_code": error_code}]}).encode()

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, status, message, {},
                                     io.BytesIO(body))
    return opener


def _sequence(*openers):
    """Answer each successive call with the next opener. Used by the probe test."""
    calls = {"n": 0}

    def opener(req, timeout=None):
        o = openers[min(calls["n"], len(openers) - 1)]
        calls["n"] += 1
        return o(req, timeout)
    return opener


def _candle_payload(rows):
    return {"status": "success", "data": {"candles": rows}}


def _bars(day="2026-08-04", n=5, base=100.0):
    """Newest-first, as Upstox returns them: [ts, o, h, l, c, volume, oi]."""
    out = []
    for i in range(n):
        t = f"{day}T09:{15 + i:02d}:00+05:30"
        c = base + i
        out.append([t, c, c + 0.5, c - 0.5, c, 1000 + i, 50000 + i])
    return list(reversed(out))


# ── the leak guard ───────────────────────────────────────────────────────────

def test_credential_status_never_returns_a_value(monkeypatch):
    monkeypatch.setenv(ux.ENV_TOKEN, "super-secret-token-value")
    status = ux.credential_status()
    assert status == {ux.ENV_TOKEN: True}
    assert "super-secret-token-value" not in json.dumps(status)


def test_credential_status_reports_absence_without_raising(monkeypatch):
    monkeypatch.delenv(ux.ENV_TOKEN, raising=False)
    assert ux.credential_status() == {ux.ENV_TOKEN: False}


def test_missing_token_is_its_own_error_not_a_vendor_refusal(monkeypatch):
    """"You have no token" and "the vendor rejected your token" are different
    diagnoses and must not collapse into one failed fetch."""
    monkeypatch.delenv(ux.ENV_TOKEN, raising=False)
    with pytest.raises(ux.MissingToken):
        ux.access_token()
    assert issubclass(ux.MissingToken, ux.ExpiredSourceError)


def test_blank_token_counts_as_missing(monkeypatch):
    monkeypatch.setenv(ux.ENV_TOKEN, "   ")
    assert ux.credential_status() == {ux.ENV_TOKEN: False}
    with pytest.raises(ux.MissingToken):
        ux.access_token()


# ── the finding this module exists to settle ─────────────────────────────────

def test_classify_probe_says_gated_by_auth_not_no_route():
    """The 2026-09-08 measurement, frozen.

    401 on the v2 expired family (route exists, caller refused) is a different
    world from 404 (route does not exist). backtest_data_20260908.md §2 inferred
    the second from evidence that only ever showed the first.
    """
    rows = [
        {"check": "v3 free, LISTED contract", "http": 200, "error_code": None, "rows": 1155},
        {"check": "v3 free, EXPIRED-style key", "http": 400,
         "error_code": ux.ERR_BAD_KEY_FORMAT, "rows": 0},
        {"check": "v2 expired-instruments/expiries", "http": 401,
         "error_code": ux.ERR_BAD_TOKEN, "rows": 0},
        {"check": "v2 expired-instruments/historical-candle", "http": 401,
         "error_code": ux.ERR_BAD_TOKEN, "rows": 0},
    ]
    verdict = ux.classify_probe(rows)
    assert verdict.startswith("GATED BY AUTH")
    assert "UDAPI1021" in verdict          # free v3 cannot even parse an expired key
    assert "not a network fault" in verdict


def test_classify_probe_would_have_said_no_route_on_a_404():
    """If the endpoints really were absent, this is what it would look like. The
    branch exists so the other verdict is not the only thing the code can say."""
    rows = [
        {"check": "v3 free, LISTED contract", "http": 200, "error_code": None, "rows": 1},
        {"check": "v2 expired-instruments/expiries", "http": 404,
         "error_code": ux.ERR_NOT_FOUND, "rows": 0},
    ]
    assert ux.classify_probe(rows).startswith("NO ROUTE")


def test_classify_probe_separates_plan_gate_from_auth_gate():
    """UDAPI1149 means the token was fine and the PLAN was not. That is the one
    outcome this host cannot produce, so it is asserted rather than measured."""
    rows = [
        {"check": "v2 expired-instruments/expiries", "http": 403,
         "error_code": ux.ERR_PLUS_REQUIRED, "rows": 0},
    ]
    assert ux.classify_probe(rows).startswith("GATED BY PLAN")


def test_probe_sends_no_authorization_header():
    """The probe's whole claim is that it is unauthenticated. If it ever grew an
    Authorization header the 401s would stop meaning anything."""
    headers_seen = []

    def opener(req, timeout=None):
        headers_seen.append({k.lower() for k in req.headers})
        return _Resp(json.dumps(_candle_payload([])).encode())

    ux.probe(opener=opener, sleep=lambda s: None, pacing=0)
    assert headers_seen
    assert all("authorization" not in h for h in headers_seen)


def test_probe_records_a_refusal_instead_of_raising():
    rows = ux.probe(opener=_fail(401, ux.ERR_BAD_TOKEN), sleep=lambda s: None, pacing=0)
    assert len(rows) == 4
    assert all(r["http"] == 401 and r["error_code"] == ux.ERR_BAD_TOKEN for r in rows)


# ── error mapping ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,code,needs_token,needs_plus", [
    (401, ux.ERR_BAD_TOKEN, True, False),
    (403, ux.ERR_PLUS_REQUIRED, False, True),
    (400, ux.ERR_UNKNOWN_KEY, False, False),
])
def test_vendor_error_code_survives_to_the_caller(status, code, needs_token, needs_plus):
    with pytest.raises(ux.ExpiredSourceError) as e:
        ux.expiries(token="t", opener=_fail(status, code))
    assert e.value.error_code == code
    assert e.value.http_status == status
    assert e.value.needs_token is needs_token
    assert e.value.needs_plus is needs_plus


def test_a_non_json_body_does_not_crash_the_parser():
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {},
                                     io.BytesIO(b"<html>nginx</html>"))
    with pytest.raises(ux.ExpiredSourceError) as e:
        ux.expiries(token="t", opener=opener)
    assert e.value.http_status == 502


def test_success_envelope_is_checked_not_assumed():
    """HTTP 200 with status="error" is a thing Upstox does. Trusting the status
    line alone would import an error envelope as zero candles."""
    def opener(req, timeout=None):
        return _Resp(json.dumps({"status": "error", "errors": [
            {"errorCode": ux.ERR_BAD_DATE, "message": "bad date"}]}).encode())
    with pytest.raises(ux.ExpiredSourceError) as e:
        ux.expiries(token="t", opener=opener)
    assert e.value.error_code == ux.ERR_BAD_DATE


# ── keys and URLs ────────────────────────────────────────────────────────────

def test_expired_key_uses_dd_mm_yyyy_not_iso():
    """The expired route wants DD-MM-YYYY inside the key while every date PARAM is
    ISO. Getting this backwards is a UDAPI1021, which is exactly what the free v3
    route returned on 2026-09-08."""
    assert ux.expired_key_for("47983", _dt.date(2025, 4, 17)) == "NSE_FO|47983|17-04-2025"


def test_candle_url_percent_encodes_the_pipe_and_keeps_iso_dates():
    o = _ok(_candle_payload([]))
    ux.expired_candles("NSE_FO|47983|17-04-2025", _dt.date(2025, 4, 1),
                       _dt.date(2025, 4, 17), token="t", opener=o)
    url = o.seen[0]
    assert "NSE_FO%7C47983%7C17-04-2025" in url
    assert url.endswith("/1minute/2025-04-17/2025-04-01")
    assert "|" not in url


def test_underlying_key_space_is_encoded():
    o = _ok({"status": "success", "data": []})
    ux.expiries(token="t", opener=o)
    assert "Nifty%2050" in o.seen[0]
    assert " " not in o.seen[0]


def test_interval_vocabulary_is_the_v2_one_not_the_v3_one():
    """v3 says minutes/1; v2 expired says 1minute. Passing v3 syntax earns
    UDAPI1020, so the module refuses it locally rather than spending a request."""
    assert "1minute" in ux.INTERVALS
    assert "1" not in ux.INTERVALS
    with pytest.raises(ValueError):
        ux.expired_candles("k", _dt.date(2025, 4, 1), _dt.date(2025, 4, 2),
                           interval="minutes/1", token="t", opener=_ok({}))


def test_backwards_window_is_rejected_before_a_request_is_spent():
    o = _ok(_candle_payload([]))
    with pytest.raises(ValueError):
        ux.expired_candles("k", _dt.date(2025, 4, 17), _dt.date(2025, 4, 1),
                           token="t", opener=o)
    assert o.seen == []


def test_oversized_minute_window_is_rejected_before_a_request_is_spent():
    o = _ok(_candle_payload([]))
    with pytest.raises(ValueError):
        ux.expired_candles("k", _dt.date(2025, 1, 1), _dt.date(2025, 3, 1),
                           token="t", opener=o)
    assert o.seen == []


# ── parsing ──────────────────────────────────────────────────────────────────

def test_candles_come_back_oldest_first_with_oi():
    """Upstox answers newest-first. Every other consumer in research/backtest sees
    time moving forward; a silent reversal here would corrupt every replay."""
    bars, _ = ux.expired_candles("k", _dt.date(2026, 8, 4), _dt.date(2026, 8, 4),
                                 token="t", opener=_ok(_candle_payload(_bars())))
    assert len(bars) == 5
    assert [b["epoch"] for b in bars] == sorted(b["epoch"] for b in bars)
    assert bars[0]["ts"].astimezone(IST).strftime("%H:%M") == "09:15"
    assert bars[0]["oi"] == 50000


def test_oi_is_carried_because_angel_has_none():
    """store.PROVENANCE marks oi missing. That is a statement about the Angel feed.
    This route carries field 7, and the loader must not drop it."""
    bars, _ = ux.expired_candles("k", _dt.date(2026, 8, 4), _dt.date(2026, 8, 4),
                                 token="t", opener=_ok(_candle_payload(_bars())))
    assert all(b["oi"] > 0 for b in bars)
    assert ux.provenance()["oi"][0] == "unverified"


def test_a_short_candle_row_without_oi_is_tolerated():
    rows = [["2026-08-04T09:15:00+05:30", 100.0, 101.0, 99.0, 100.5, 10]]
    bars, _ = ux.expired_candles("k", _dt.date(2026, 8, 4), _dt.date(2026, 8, 4),
                                 token="t", opener=_ok(_candle_payload(rows)))
    assert bars[0]["oi"] == 0


def test_expiries_are_sorted_ascending_and_deduped():
    payload = {"status": "success",
               "data": ["2026-08-05", "2026-07-29", "2026-08-05", "2026-08-12"]}
    got, _ = ux.expiries(token="t", opener=_ok(payload))
    assert got == [_dt.date(2026, 7, 29), _dt.date(2026, 8, 5), _dt.date(2026, 8, 12)]


def test_contract_rows_normalise_both_naming_styles():
    payload = {"status": "success", "data": [
        {"instrument_key": "NSE_FO|1|05-08-2026", "instrument_type": "CE",
         "strike_price": 24500, "trading_symbol": "NIFTY 24500 CE",
         "lot_size": 75, "tick_size": 0.05, "exchange_token": "1", "weekly": True},
        {"instrumentKey": "NSE_FO|2|05-08-2026", "instrumentType": "PE",
         "strikePrice": 24400, "tradingSymbol": "NIFTY 24400 PE",
         "lotSize": 75, "tickSize": 0.05, "exchangeToken": "2"},
    ]}
    got, _ = ux.option_contracts(_dt.date(2026, 8, 5), token="t", opener=_ok(payload))
    assert [c["strike"] for c in got] == [24400.0, 24500.0]   # sorted by strike
    assert got[0]["instrument_type"] == "PE"
    assert got[1]["lot_size"] == 75
    assert all(c["expiry"] == _dt.date(2026, 8, 5) for c in got)


def test_a_row_that_is_not_an_option_is_dropped_not_guessed():
    payload = {"status": "success", "data": [
        {"instrument_key": "NSE_FO|9|05-08-2026", "instrument_type": "FUT",
         "strike_price": 0},
        {"instrument_key": "NSE_FO|8|05-08-2026", "instrument_type": "CE"},  # no strike
    ]}
    got, _ = ux.option_contracts(_dt.date(2026, 8, 5), token="t", opener=_ok(payload))
    assert got == []


def test_atm_band_filters_only_on_what_the_caller_observed():
    chain = [{"strike": s, "instrument_type": t, "expired_instrument_key": f"k{s}{t}"}
             for s in (24300.0, 24400.0, 24500.0, 24600.0) for t in ("CE", "PE")]
    band = ux.atm_band(chain, 24400, 24500)
    assert {c["strike"] for c in band} == {24400.0, 24500.0}
    assert {c["instrument_type"] for c in ux.atm_band(chain, 0, 1e9, ("CE",))} == {"CE"}


def test_interval_tag_translates_to_the_store_vocabulary():
    assert ux._interval_tag("1minute") == "1m"
    assert ux._interval_tag("15minute") == "15m"
    assert ux._interval_tag("day") == "1d"


# ── chunking and the no-fabrication policy ───────────────────────────────────

def test_chunks_cover_the_range_without_overlap_or_holes():
    frm, to = _dt.date(2026, 1, 1), _dt.date(2026, 3, 31)
    chunks = list(ux._day_chunks(frm, to, ux.MAX_WINDOW_DAYS))
    assert chunks[0][0] == frm and chunks[-1][1] == to
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert next_start == prev_end + _dt.timedelta(days=1)
    assert all((b - a).days + 1 <= ux.MAX_WINDOW_DAYS for a, b in chunks)


def test_a_failed_chunk_leaves_a_hole_and_a_receipt_never_a_fill():
    """The rule the whole research layer rests on: a minute the vendor did not
    return is a gap. It is never back-filled, never retried into a neighbouring
    window, and never quietly dropped from the record."""
    good = _ok(_candle_payload(_bars(day="2026-08-04")))
    bad = _fail(500, None, "upstream")
    bars, receipts = ux.expired_range(
        "k", _dt.date(2026, 7, 1), _dt.date(2026, 9, 15),
        token="t", opener=_sequence(good, bad, good), sleep=lambda s: None, pacing=0)
    assert len(receipts) == 3
    assert receipts[1]["rows_returned"] == 0
    assert receipts[1]["error"] and "500" in receipts[1]["error"]
    assert receipts[0]["error"] is None
    # the successful chunks are kept; nothing stands in for the failed one
    assert len(bars) == 5          # both good chunks returned the SAME 5 minutes
    assert receipts[1]["returned_from"] is None


def test_every_request_leaves_a_receipt_with_source_and_url():
    o = _ok(_candle_payload(_bars()))
    _, receipts = ux.expired_range("NSE_FO|1|05-08-2026", _dt.date(2026, 8, 1),
                                   _dt.date(2026, 8, 5), token="t", opener=o,
                                   sleep=lambda s: None, pacing=0)
    r = receipts[0]
    assert r["source"] == ux.SOURCE == "upstox_expired"
    assert r["source"] != "upstox"      # must never overwrite the v3 rows
    assert r["endpoint_url"].startswith("https://api.upstox.com/v2/expired-instruments/")
    assert r["interval"] == "1m"
    assert r["requested_from"] == "2026-08-01" and r["requested_to"] == "2026-08-05"
    assert r["rows_returned"] == 5
    assert r["fetched_at_utc"]


def test_duplicate_minutes_across_chunks_are_deduped_not_double_counted():
    o = _ok(_candle_payload(_bars()))
    bars, receipts = ux.expired_range("k", _dt.date(2026, 7, 1), _dt.date(2026, 9, 15),
                                      token="t", opener=o, sleep=lambda s: None, pacing=0)
    assert len(receipts) == 3
    assert len(bars) == 5
    assert len({b["epoch"] for b in bars}) == 5


def test_pacing_is_applied_between_chunks_only():
    slept = []
    ux.expired_range("k", _dt.date(2026, 7, 1), _dt.date(2026, 9, 15), token="t",
                     opener=_ok(_candle_payload([])), sleep=slept.append, pacing=1.5)
    assert slept == [1.5, 1.5]      # 3 chunks, 2 gaps


# ── provenance ───────────────────────────────────────────────────────────────

def test_nothing_is_graded_real_before_it_has_been_fetched_and_reconciled():
    """The synthetic bid/ask correction in this project happened because fabricated
    fields were graded as measured. Nothing here may be graded 'real' while the
    reconciliation has never run."""
    prov = ux.provenance()
    assert prov["option_ohlc"][0] == "unverified"
    assert prov["bid"][0] == "missing" and prov["ask"][0] == "missing"
    assert prov["spread"][0] == "missing"
    assert all(grade in ("unverified", "missing") for grade, _ in prov.values())
    assert "real" not in {g for g, _ in prov.values()}


def test_every_provenance_field_explains_itself():
    """No bare grade without a reason. The two load-bearing ones spell it out; the
    rest may point at the field above them, but none may be empty."""
    prov = ux.provenance()
    assert all(why.strip() for _, why in prov.values())
    assert "verify_against_broker" in prov["option_ohlc"][1]
    assert "MODELLED" in prov["spread"][1]


# ── the falsification test ───────────────────────────────────────────────────

def test_reconciliation_passes_only_on_an_exact_match():
    broker = [{"epoch": 1, "close": 100.0}, {"epoch": 2, "close": 101.0}]
    same = [{"epoch": 1, "close": 100.0}, {"epoch": 2, "close": 101.0}]
    v = ux.verify_against_broker(broker, same)
    assert v["verdict"] == "RECONCILED"
    assert v["identical_pct"] == 100.0 and v["max_abs_diff"] == 0.0
    assert v["shared_minutes"] == 2


def test_reconciliation_reports_disagreement_as_a_result_not_an_exception():
    broker = [{"epoch": i, "close": 100.0} for i in range(100)]
    other = [{"epoch": i, "close": 100.0 + (5.0 if i < 50 else 0.0)} for i in range(100)]
    v = ux.verify_against_broker(broker, other)          # must not raise
    assert v["verdict"] == "DISAGREES"
    assert v["identical_pct"] == 50.0
    assert v["max_abs_diff"] == 5.0


def test_no_overlap_is_reported_as_no_overlap_not_as_agreement():
    """A reconciliation over zero shared minutes proves nothing, and must never
    come back looking like a pass."""
    v = ux.verify_against_broker([{"epoch": 1, "close": 100.0}],
                                 [{"epoch": 9, "close": 100.0}])
    assert v["verdict"] == "NO OVERLAP"
    assert v["shared_minutes"] == 0
    assert v["identical_pct"] is None


def test_reconciliation_counts_minutes_present_on_only_one_side():
    v = ux.verify_against_broker([{"epoch": 1, "close": 1.0}, {"epoch": 2, "close": 2.0}],
                                 [{"epoch": 2, "close": 2.0}, {"epoch": 3, "close": 3.0}])
    assert v["only_in_broker"] == 1 and v["only_in_expired"] == 1


# ── premium sanity ───────────────────────────────────────────────────────────

def test_a_plausible_premium_series_passes():
    bars, _ = ux.expired_candles("k", _dt.date(2026, 8, 4), _dt.date(2026, 8, 4),
                                 token="t", opener=_ok(_candle_payload(_bars())))
    s = ux.sanity_check_premiums(bars)
    assert s["passed"] and s["bars"] == 5
    assert s["ohlc_violations"] == 0 and s["nonpositive_close"] == 0
    assert s["has_oi"] is True


def test_a_flat_series_fails_because_a_premium_that_never_moves_is_not_data():
    flat = [{"ts": _dt.datetime(2026, 8, 4, 9, 15 + i, tzinfo=IST), "epoch": i,
             "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0,
             "volume": 1, "oi": 1} for i in range(10)]
    assert ux.sanity_check_premiums(flat)["passed"] is False


def test_a_negative_premium_fails():
    bad = [{"ts": _dt.datetime(2026, 8, 4, 9, 15, tzinfo=IST), "epoch": 1,
            "open": -1.0, "high": 1.0, "low": -2.0, "close": -1.0, "volume": 1, "oi": 1},
           {"ts": _dt.datetime(2026, 8, 4, 9, 16, tzinfo=IST), "epoch": 2,
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1, "oi": 1}]
    s = ux.sanity_check_premiums(bad)
    assert s["nonpositive_close"] == 1 and s["passed"] is False


def test_ohlc_that_does_not_bracket_is_caught():
    bad = [{"ts": _dt.datetime(2026, 8, 4, 9, 15, tzinfo=IST), "epoch": 1,
            "open": 10.0, "high": 9.0, "low": 11.0, "close": 10.5, "volume": 1, "oi": 0},
           {"ts": _dt.datetime(2026, 8, 4, 9, 16, tzinfo=IST), "epoch": 2,
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1, "oi": 0}]
    s = ux.sanity_check_premiums(bad)
    assert s["ohlc_violations"] == 1 and s["passed"] is False


def test_bars_outside_the_nse_session_are_counted():
    off = [{"ts": _dt.datetime(2026, 8, 4, 3, 0, tzinfo=IST), "epoch": 1,
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1, "oi": 0},
           {"ts": _dt.datetime(2026, 8, 4, 9, 16, tzinfo=IST), "epoch": 2,
            "open": 1.0, "high": 2.0, "low": 1.0, "close": 2.0, "volume": 1, "oi": 0}]
    assert ux.sanity_check_premiums(off)["outside_session"] == 1


def test_empty_input_is_not_a_pass():
    s = ux.sanity_check_premiums([])
    assert s["bars"] == 0 and s["passed"] is False


# ── constants frozen deliberately ────────────────────────────────────────────

def test_the_documented_error_codes_are_the_ones_that_were_observed():
    """Changing any of these should be a deliberate act with a fresh probe behind
    it, not a drive-by edit."""
    assert ux.ERR_BAD_TOKEN == "UDAPI100050"      # observed 2026-09-08, all 4 endpoints
    assert ux.ERR_BAD_KEY_FORMAT == "UDAPI1021"   # observed, free v3 + expired-style key
    assert ux.ERR_NOT_FOUND == "UDAPI100060"      # observed, v3 expired route
    assert ux.ERR_PLUS_REQUIRED == "UDAPI1149"    # documented only; never reached here


def test_base_url_is_v2_because_v3_has_no_expired_route():
    assert ux.BASE == "https://api.upstox.com/v2"
    assert ux.CANDLE_URL.startswith(ux.BASE + "/expired-instruments/")
