"""Upstox `expired-instruments` — the only route to an EXPIRED NIFTY weekly, measured.

WHY THIS FILE EXISTS
--------------------
`sources.py` records, correctly, that the free keyless Upstox v3 endpoint cannot
reach a contract that has already expired. Two reports then disagreed about what
that means:

  claude_code/report/backtest_data_20260908.md  §2  concluded it was an
      "exchange-side archive boundary" and that there is "no route, free or
      credentialed, to a NIFTY weekly option that has already expired".
  claude_code/report/strategy_sources_20260908.md §1.1 said that is wrong, and
      that Upstox serves expired chains through a separate v2 endpoint family.

Probed here on 2026-09-08 with curl, unauthenticated, from this host. The second
report is right about the endpoints existing; the first report's MEASUREMENTS were
also right, and its INFERENCE was wrong. Both facts are reproducible:

    GET https://api.upstox.com/v3/historical-candle/NSE_FO%7C42615/minutes/1/2026-09-04/2026-09-02
        -> HTTP 200, real 1-minute bars WITH open interest, no key, no account.
           (42615 = NIFTY08SEP2623550CE, listed on the day of the probe.)

    GET https://api.upstox.com/v3/historical-candle/NSE_FO%7C42615%7C08-09-2026/...
        -> HTTP 400 UDAPI1021 "Instrument key is of invalid format"
           The free v3 route does not merely lack expired DATA; it cannot parse an
           expired instrument KEY. No amount of probing v3 will ever reach one.

    GET https://api.upstox.com/v2/expired-instruments/expiries?instrument_key=NSE_INDEX%7CNifty%2050
    GET https://api.upstox.com/v2/expired-instruments/option/contract?...
    GET https://api.upstox.com/v2/expired-instruments/future/contract?...
    GET https://api.upstox.com/v2/expired-instruments/historical-candle/...
        -> HTTP 401 UDAPI100050 "Invalid token used to access API"   (all four)

    GET https://api.upstox.com/v3/expired-instruments/expiries?...
        -> HTTP 404 UDAPI100060 "Resource not Found."

The 404 on v3 next to the 401 on v2 is the load-bearing detail: the server
distinguishes a route that does not exist from a route that exists and is refusing
this caller. The v2 expired family EXISTS. It is gated by OAuth, not by the
exchange.

WHAT IT COSTS (read from Upstox's own pages on 2026-09-08, not tested — see below)
----------------------------------------------------------------------------------
  * The endpoints are documented as Upstox **Plus**-only; the documented refusal is
    UDAPI1149 "This API is available exclusively with an Upstox Plus plan
    subscription". https://upstox.com/plus/ lists "OHLC for expired contracts" as
    Plus, "-" on Basic.
  * Upstox's own T&C page says: "The Plus Plan can be activated for free initially.
    If the plan becomes chargeable in the future, we will notify you in advance of
    the applicable date." So the SUBSCRIPTION price today is zero.
  * Plus does change brokerage from Rs20 to Rs30 per order. That is free to this
    project only for as long as no order is routed through Upstox: this repo trades
    on Angel One and would use Upstox purely as a data vendor.
  * Prerequisite that is NOT free of effort: an Upstox trading account (this repo
    has none — .env carries ANGEL_* and TELEGRAM_* only), Plus activated on it, a
    developer app, and an OAuth login to mint an access token.

  NOTHING HERE SIGNS UP FOR, ACTIVATES OR PAYS FOR ANYTHING. That is the account
  owner's decision. This module only knows how to use a token if one is handed to it.

DEPTH (documented; unverifiable from here without a token)
----------------------------------------------------------
  * get-expiries doc: "covering up to six months of historical expiries".
  * Upstox staff, community thread 9245: "OHLC data for expired contracts is
    available from the date the first trade occurred for that contract up to its
    expiry date"; "we provide historical expiry data for the last six months";
    "we plan to retain and make available up to 2 years of data ... in the future".
  * Six months of NIFTY weeklies is ~26 expiries. Against the 13 sessions and ONE
    chain every current result rests on, that is the whole point of this file.

HONEST STATUS OF THIS MODULE
----------------------------
  TESTED     the four endpoint URLs exist and answer; the free route provably
             cannot address an expired key; the auth class is OAuth bearer.
  NOT TESTED anything behind the token: real depth, real row counts, whether the
             premiums reconcile with Angel. `verify_against_broker()` is the
             falsification test, written and unrun. Until it is run and passes,
             NO candle fetched here should be trusted as a second opinion, and
             `provenance()` says so.

Conventions inherited from store.py and research/provenance.py, unchanged:
  1. No fabrication. A minute the vendor did not return is a gap, never a fill.
  2. Every row carries its source; `source="upstox_expired"` is distinct from
     `"upstox"` so the two views never silently overwrite each other.
  3. Every request leaves a receipt, including the ones that failed.
  4. Secrets are never printed. `credential_status()` returns names and booleans.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

SOURCE = "upstox_expired"
BASE = "https://api.upstox.com/v2"

EXPIRIES_URL = BASE + "/expired-instruments/expiries?instrument_key={key}"
OPTION_CONTRACT_URL = BASE + "/expired-instruments/option/contract?instrument_key={key}&expiry_date={expiry}"
FUTURE_CONTRACT_URL = BASE + "/expired-instruments/future/contract?instrument_key={key}&expiry_date={expiry}"
CANDLE_URL = BASE + "/expired-instruments/historical-candle/{key}/{iv}/{to}/{frm}"

# The free keyless endpoint, kept here only so probe() can demonstrate the
# contrast in one run. sources.py owns the real use of it.
V3_CANDLE_URL = "https://api.upstox.com/v3/historical-candle/{key}/minutes/{iv}/{to}/{frm}"

NIFTY_UNDERLYING_KEY = "NSE_INDEX|Nifty 50"

# Documented interval vocabulary of the EXPIRED endpoint. Note it is NOT the v3
# "minutes/1" path shape; passing v3 syntax here earns UDAPI1020.
INTERVALS = ("1minute", "3minute", "5minute", "15minute", "30minute", "day")

# Upstox staff, thread 9245: no hard cap, but "for minute-level intervals, we
# recommend keeping the from_date and to_date range within one month". The
# reference client (rajmaurya0904/bhav) chunks at 30 days. Same number as the
# hard v3 cap, arrived at independently.
MAX_WINDOW_DAYS = 30

# sources.py measured ~10 rapid keyless requests -> HTTP 403 for minutes. The
# documented authenticated limit is far higher (50/s, 500/min, 2000/30min), but
# a live paper session shares this network, so the default here stays polite.
PACING_SEC = 1.0

ENV_TOKEN = "UPSTOX_ACCESS_TOKEN"

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")

# Error codes seen or documented. Mapped, not guessed at call time.
ERR_BAD_TOKEN = "UDAPI100050"     # observed: no/!valid bearer
ERR_PLUS_REQUIRED = "UDAPI1149"   # documented: Basic plan, endpoint is Plus-only
ERR_BAD_KEY_FORMAT = "UDAPI1021"  # observed on v3 when given an expired-style key
ERR_UNKNOWN_KEY = "UDAPI100011"   # documented: expired key not recognised
ERR_BAD_INTERVAL = "UDAPI1020"
ERR_BAD_DATE = "UDAPI1088"
ERR_NOT_FOUND = "UDAPI100060"     # observed on the non-existent v3 expired route


class ExpiredSourceError(RuntimeError):
    """The expired route refused. Carries the vendor's own code so the caller can
    tell 'you have no token' from 'your plan does not include this' from 'that
    contract does not exist' — three very different answers that all look like a
    failed fetch if you only keep the HTTP status."""

    def __init__(self, message: str, *, http_status: Optional[int] = None,
                 error_code: Optional[str] = None, url: str = ""):
        super().__init__(message)
        self.http_status = http_status
        self.error_code = error_code
        self.url = url

    @property
    def needs_token(self) -> bool:
        return self.error_code == ERR_BAD_TOKEN or self.http_status == 401

    @property
    def needs_plus(self) -> bool:
        return self.error_code == ERR_PLUS_REQUIRED


class MissingToken(ExpiredSourceError):
    """No token configured at all. Distinct from a token the vendor rejected."""


# ── credentials ──────────────────────────────────────────────────────────────

def credential_status() -> Dict[str, bool]:
    """Names and presence ONLY. This function must never return a token value.

    A token has leaked twice in this project's history; the rule that came out of
    that is binding and applies here.
    """
    return {ENV_TOKEN: bool(os.environ.get(ENV_TOKEN, "").strip())}


def access_token() -> str:
    tok = os.environ.get(ENV_TOKEN, "").strip()
    if not tok:
        raise MissingToken(
            f"{ENV_TOKEN} is not set. The expired-instruments family is OAuth-gated; "
            "see this module's docstring for what obtaining one requires.")
    return tok


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": _UA}


# ── transport ────────────────────────────────────────────────────────────────

def _parse_error(body: str) -> Tuple[Optional[str], str]:
    """Pull (errorCode, message) out of an Upstox error envelope, tolerantly."""
    try:
        payload = json.loads(body)
    except Exception:  # noqa: BLE001 - a non-JSON body is itself the message
        return None, body[:200]
    errs = payload.get("errors") or []
    if errs and isinstance(errs, list) and isinstance(errs[0], dict):
        e = errs[0]
        return e.get("errorCode") or e.get("error_code"), str(e.get("message", ""))
    return None, str(payload)[:200]


def _get_json(url: str, headers: Dict[str, str], timeout: int = 60,
              opener: Optional[Callable] = None) -> Dict:
    """One GET. Any refusal becomes an ExpiredSourceError carrying the vendor code.

    `opener` exists so tests can drive every branch without a socket.
    """
    req = urllib.request.Request(url, headers=headers)
    do = opener or (lambda r, timeout: urllib.request.urlopen(r, timeout=timeout))
    try:
        with do(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        code, msg = _parse_error(body)
        raise ExpiredSourceError(f"HTTP {e.code} {code or ''} {msg}".strip(),
                                 http_status=e.code, error_code=code, url=url) from e
    except ExpiredSourceError:
        raise
    except Exception as e:  # noqa: BLE001 - network shapes vary; the caller records it
        raise ExpiredSourceError(f"{type(e).__name__}: {e}", url=url) from e


def _check_success(payload: Dict, url: str) -> Dict:
    if payload.get("status") != "success":
        code, msg = None, ""
        errs = payload.get("errors") or []
        if errs and isinstance(errs[0], dict):
            code = errs[0].get("errorCode") or errs[0].get("error_code")
            msg = str(errs[0].get("message", ""))
        raise ExpiredSourceError(f"status={payload.get('status')!r} {code or ''} {msg}".strip(),
                                 error_code=code, url=url)
    return payload


# ── endpoint 1: which expiries does the vendor still hold ────────────────────

def expiries(underlying_key: str = NIFTY_UNDERLYING_KEY, *, token: Optional[str] = None,
             opener: Optional[Callable] = None) -> Tuple[List[_dt.date], str]:
    """Past expiry dates the vendor will serve. Returns (dates ascending, url).

    Documented as "up to six months of historical expiries". That claim is the
    vendor's; this function reports whatever actually comes back, which is the
    only number worth quoting.
    """
    url = EXPIRIES_URL.format(key=urllib.parse.quote(underlying_key, safe=""))
    payload = _check_success(_get_json(url, _auth_headers(token or access_token()),
                                       opener=opener), url)
    raw = payload.get("data") or []
    out = sorted({_dt.date.fromisoformat(x) for x in raw if x})
    return out, url


# ── endpoint 2/3: the contract directory for one expired expiry ──────────────

def _normalise_contract(c: Dict, expiry: _dt.date) -> Optional[Dict]:
    ikey = c.get("instrument_key") or c.get("instrumentKey")
    itype = c.get("instrument_type") or c.get("instrumentType")
    strike = c.get("strike_price", c.get("strikePrice"))
    if not ikey or itype not in ("CE", "PE") or strike is None:
        return None
    return {
        "expired_instrument_key": ikey,
        "trading_symbol": c.get("trading_symbol") or c.get("tradingSymbol") or "",
        "instrument_type": itype,
        "strike": float(strike),
        "expiry": expiry,
        "lot_size": int(c.get("lot_size") or c.get("lotSize") or 0),
        "tick_size": float(c.get("tick_size") or c.get("tickSize") or 0.0),
        "exchange_token": str(c.get("exchange_token") or c.get("exchangeToken") or ""),
        "weekly": bool(c.get("weekly")),
    }


def option_contracts(expiry: _dt.date, underlying_key: str = NIFTY_UNDERLYING_KEY, *,
                     token: Optional[str] = None,
                     opener: Optional[Callable] = None) -> Tuple[List[Dict], str]:
    """The full expired chain for one expiry.

    This endpoint is not merely a convenience: it is the ONLY directory of expired
    tokens available to this project. The Angel ScripMaster cache and the Upstox
    public master both hold unexpired contracts only (verified 2026-09-08:
    core/data/scripmaster_nifty_nfo.json, saved 2026-09-07, earliest expiry
    08SEP2026 — nothing already expired). Without this call an expired contract
    cannot even be NAMED, let alone fetched.
    """
    url = OPTION_CONTRACT_URL.format(key=urllib.parse.quote(underlying_key, safe=""),
                                     expiry=expiry.isoformat())
    payload = _check_success(_get_json(url, _auth_headers(token or access_token()),
                                       opener=opener), url)
    out = []
    for c in payload.get("data") or []:
        n = _normalise_contract(c, expiry)
        if n:
            out.append(n)
    out.sort(key=lambda c: (c["strike"], c["instrument_type"]))
    return out, url


def atm_band(contracts: Sequence[Dict], lo: float, hi: float,
             types: Sequence[str] = ("CE", "PE")) -> List[Dict]:
    """Strikes inside [lo, hi]. No centre is guessed: the caller supplies the range
    it actually observed in the index, exactly as fetch.py does for Angel."""
    return [c for c in contracts
            if lo <= c["strike"] <= hi and c["instrument_type"] in types]


# ── endpoint 4: the candles ──────────────────────────────────────────────────

def _bar(row: Sequence) -> Dict:
    ts = _dt.datetime.fromisoformat(row[0])
    return {
        "ts": ts,
        "epoch": int(ts.timestamp()),
        "open": float(row[1]), "high": float(row[2]),
        "low": float(row[3]), "close": float(row[4]),
        "volume": int(row[5] or 0),
        "oi": int(row[6] or 0) if len(row) > 6 else 0,
    }


def expired_candles(expired_key: str, frm: _dt.date, to: _dt.date,
                    interval: str = "1minute", *, token: Optional[str] = None,
                    opener: Optional[Callable] = None) -> Tuple[List[Dict], str]:
    """One request. Returns (bars oldest-first, url).

    Upstox answers newest-first as [ts, o, h, l, c, volume, oi]; reversed here so
    every consumer in this package sees time moving forward, matching
    sources.upstox_candles().

    Unlike the v3 endpoint this one DOES carry open interest for options. That is a
    real difference from the Angel feed, whose getCandleData has no OI field at any
    interval — see store.PROVENANCE["oi"], which is a statement about Angel and
    should not be read as a statement about this route.
    """
    if interval not in INTERVALS:
        raise ValueError(f"interval {interval!r} is not one of {INTERVALS}")
    if to < frm:
        raise ValueError(f"window {frm}..{to} runs backwards")
    if interval.endswith("minute") and (to - frm).days + 1 > MAX_WINDOW_DAYS:
        raise ValueError(
            f"window {frm}..{to} exceeds the {MAX_WINDOW_DAYS}-day chunk this module "
            "walks minute data in; use expired_range()")
    url = CANDLE_URL.format(key=urllib.parse.quote(expired_key, safe=""),
                            iv=interval, to=to.isoformat(), frm=frm.isoformat())
    payload = _check_success(_get_json(url, _auth_headers(token or access_token()),
                                       opener=opener), url)
    raw = (payload.get("data") or {}).get("candles") or []
    return [_bar(r) for r in reversed(raw)], url


def _day_chunks(frm: _dt.date, to: _dt.date, span: int) -> Iterable[Tuple[_dt.date, _dt.date]]:
    cur, step, one = frm, _dt.timedelta(days=span - 1), _dt.timedelta(days=1)
    while cur <= to:
        end = min(cur + step, to)
        yield cur, end
        cur = end + one


def expired_range(expired_key: str, frm: _dt.date, to: _dt.date, interval: str = "1minute", *,
                  token: Optional[str] = None, pacing: float = PACING_SEC,
                  on_chunk: Optional[Callable] = None,
                  opener: Optional[Callable] = None,
                  sleep: Callable[[float], None] = time.sleep) -> Tuple[List[Dict], List[Dict]]:
    """Walk a span in 30-day chunks. Returns (bars, one receipt per request).

    A chunk that fails is recorded in its receipt with the vendor's error code and
    SKIPPED. It is never retried into a different date range and never back-filled
    from another source: the hole stays a hole and store.detect_gaps() writes it.
    Identical policy to sources.upstox_range(), deliberately.
    """
    bars: List[Dict] = []
    receipts: List[Dict] = []
    chunks = list(_day_chunks(frm, to, MAX_WINDOW_DAYS if interval.endswith("minute") else 10_000))
    tok = token or access_token()
    for i, (a, b) in enumerate(chunks):
        fetched_at = _dt.datetime.now(_dt.timezone.utc)
        url = CANDLE_URL.format(key=urllib.parse.quote(expired_key, safe=""),
                                iv=interval, to=b.isoformat(), frm=a.isoformat())
        try:
            got, url = expired_candles(expired_key, a, b, interval, token=tok, opener=opener)
            err = None
        except (ExpiredSourceError, ValueError) as e:
            got, err = [], str(e)
        bars.extend(got)
        receipts.append({
            "source": SOURCE, "endpoint_url": url, "instrument_key": expired_key,
            "interval": _interval_tag(interval),
            "requested_from": a.isoformat(), "requested_to": b.isoformat(),
            "returned_from": got[0]["ts"].astimezone(IST).date().isoformat() if got else None,
            "returned_to": got[-1]["ts"].astimezone(IST).date().isoformat() if got else None,
            "rows_returned": len(got),
            "fetched_at_utc": fetched_at.isoformat(),
            "error": err, "clamped": False,
        })
        if on_chunk:
            on_chunk(i + 1, len(chunks), a, b, len(got), err)
        if pacing and i + 1 < len(chunks):
            sleep(pacing)
    seen, dedup = set(), []
    for bar in sorted(bars, key=lambda r: r["epoch"]):
        if bar["epoch"] in seen:
            continue
        seen.add(bar["epoch"])
        dedup.append(bar)
    return dedup, receipts


def _interval_tag(interval: str) -> str:
    """store.candles.interval uses '1m'; the vendor says '1minute'. One translation
    point rather than string surgery scattered through the callers."""
    if interval == "day":
        return "1d"
    return interval.replace("minute", "m")


def expired_key_for(exchange_token: str, expiry: _dt.date, segment: str = "NSE_FO") -> str:
    """`NSE_FO|47983|17-04-2025` — instrument key plus expiry, DD-MM-YYYY.

    Built here only so a caller can reconstruct a key it already saw. Guessing one
    is pointless: the free v3 route rejects this format outright (UDAPI1021,
    observed), and the expired route answers UDAPI100011 for a key it does not know.
    """
    return f"{segment}|{exchange_token}|{expiry.strftime('%d-%m-%Y')}"


# ── provenance ───────────────────────────────────────────────────────────────

def provenance() -> Dict[str, Tuple[str, str]]:
    """Field-level provenance for what THIS route would import, in the vocabulary
    of research/provenance.py.

    `option_ohlc` is deliberately NOT "real" yet. The reconciliation against the
    Angel bars already in candles.db has been written (verify_against_broker) and
    has never been run, because no token exists on this host. Calling vendor data
    "real" before it has been checked against a second vendor is exactly the
    mistake the synthetic bid/ask correction was written about.
    """
    return {
        "option_ohlc": ("unverified",
                        "exchange 1-minute OHLC for an EXPIRED contract via Upstox "
                        "v2 expired-instruments; endpoint existence probed 2026-09-08, "
                        "content never fetched (OAuth + Upstox Plus required). Promote "
                        "to 'real' only after verify_against_broker() reconciles it "
                        "against the Angel bars for an overlapping window."),
        "option_volume": ("unverified", "same caveat; field is present in the payload"),
        "oi": ("unverified",
               "this route DOES carry open interest (field 7 of each candle row), "
               "unlike Angel getCandleData. Unverified for the same reason."),
        "bid": ("missing", "no historical book on this endpoint either"),
        "ask": ("missing", "same"),
        "spread": ("missing",
                   "still unmeasurable historically; a backtest over this data must "
                   "keep charging a MODELLED slippage and labelling it an assumption"),
    }


# ── the falsification test ───────────────────────────────────────────────────

def verify_against_broker(broker_bars: Sequence[Dict], expired_bars: Sequence[Dict],
                          tolerance: float = 0.0) -> Dict:
    """Do the expired-route bars agree with the Angel bars already imported?

    The project's index cross-check reconciled Angel against Upstox at 100.0%
    identical closes, max |diff| 0.00. That is the bar this must clear. If option
    closes do not reconcile to the paisa over an overlapping window, the expired
    route is not the same book and nothing fetched through it should be used.

    Returns a verdict dict; it never raises on disagreement, because a
    disagreement is a RESULT, not an error.
    """
    a = {b["epoch"]: float(b["close"]) for b in broker_bars}
    c = {b["epoch"]: float(b["close"]) for b in expired_bars}
    shared = sorted(set(a) & set(c))
    if not shared:
        return {"shared_minutes": 0, "verdict": "NO OVERLAP",
                "broker_bars": len(a), "expired_bars": len(c),
                "identical_pct": None, "max_abs_diff": None, "mean_abs_diff": None,
                "only_in_broker": len(set(a) - set(c)), "only_in_expired": len(set(c) - set(a))}
    diffs = [abs(a[e] - c[e]) for e in shared]
    identical = sum(1 for d in diffs if d <= tolerance + 1e-9)
    pct = 100.0 * identical / len(shared)
    return {
        "shared_minutes": len(shared),
        "broker_bars": len(a), "expired_bars": len(c),
        "identical_pct": pct,
        "max_abs_diff": max(diffs),
        "mean_abs_diff": sum(diffs) / len(diffs),
        "only_in_broker": len(set(a) - set(c)),
        "only_in_expired": len(set(c) - set(a)),
        "verdict": "RECONCILED" if pct == 100.0 else
                   ("CLOSE" if pct >= 99.0 else "DISAGREES"),
    }


def sanity_check_premiums(bars: Sequence[Dict]) -> Dict:
    """Cheap structural checks that a premium series behaves like a premium series.

    None of these prove the data is genuine. They catch the failures that would
    make it obviously synthetic: negative or zero prices, OHLC that does not
    bracket, a series that never moves, bars outside the NSE session grid. A pass
    here is necessary and nowhere near sufficient — verify_against_broker() is the
    test that actually decides.
    """
    n = len(bars)
    out = {
        "bars": n, "nonpositive_close": 0, "ohlc_violations": 0,
        "outside_session": 0, "zero_volume": 0, "distinct_closes": 0,
        "min_close": None, "max_close": None, "has_oi": False, "passed": False,
    }
    if not n:
        return out
    closes = []
    for b in bars:
        o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        closes.append(c)
        if c <= 0:
            out["nonpositive_close"] += 1
        if not (l <= min(o, c) and max(o, c) <= h and l <= h):
            out["ohlc_violations"] += 1
        t = b["ts"].astimezone(IST).time()
        if not (_dt.time(9, 15) <= t <= _dt.time(15, 30)):
            out["outside_session"] += 1
        if not b.get("volume"):
            out["zero_volume"] += 1
        if b.get("oi"):
            out["has_oi"] = True
    out["distinct_closes"] = len(set(closes))
    out["min_close"], out["max_close"] = min(closes), max(closes)
    out["passed"] = (out["nonpositive_close"] == 0 and out["ohlc_violations"] == 0
                     and out["distinct_closes"] > 1)
    return out


# ── the reachability probe (this is the empirical part) ──────────────────────

def probe(listed_key: str = "NSE_FO|42615", frm: str = "2026-09-02", to: str = "2026-09-04",
          *, opener: Optional[Callable] = None,
          sleep: Callable[[float], None] = time.sleep,
          pacing: float = 6.0) -> List[Dict]:
    """Re-run, from code, exactly the probe this module's docstring reports.

    Four unauthenticated requests. Each returns a row saying what happened, so the
    finding can be re-established later instead of trusted from a report. Uses the
    keyless pacing from sources.py because these calls carry no token.
    """
    fk = urllib.parse.quote(listed_key, safe="")
    expired_style = urllib.parse.quote(f"{listed_key}|08-09-2026", safe="")
    checks = [
        ("v3 free, LISTED contract",
         V3_CANDLE_URL.format(key=fk, iv=1, to=to, frm=frm)),
        ("v3 free, EXPIRED-style key",
         V3_CANDLE_URL.format(key=expired_style, iv=1, to=to, frm=frm)),
        ("v2 expired-instruments/expiries",
         EXPIRIES_URL.format(key=urllib.parse.quote(NIFTY_UNDERLYING_KEY, safe=""))),
        ("v2 expired-instruments/historical-candle",
         CANDLE_URL.format(key=expired_style, iv="1minute", to=to, frm=frm)),
    ]
    rows: List[Dict] = []
    headers = {"Accept": "application/json", "User-Agent": _UA}  # no Authorization: the point
    for i, (label, url) in enumerate(checks):
        try:
            payload = _get_json(url, headers, opener=opener)
            rows.append({"check": label, "url": url, "http": 200,
                         "error_code": None, "status": payload.get("status"),
                         "rows": len((payload.get("data") or {}).get("candles") or [])
                                 if isinstance(payload.get("data"), dict)
                                 else len(payload.get("data") or [])})
        except ExpiredSourceError as e:
            rows.append({"check": label, "url": url, "http": e.http_status,
                         "error_code": e.error_code, "status": "error", "rows": 0,
                         "message": str(e)})
        if pacing and i + 1 < len(checks):
            sleep(pacing)
    return rows


def classify_probe(rows: Sequence[Dict]) -> str:
    """Turn probe() output into the one sentence the reports disagreed about."""
    by = {r["check"]: r for r in rows}
    free_listed = by.get("v3 free, LISTED contract", {})
    free_expired = by.get("v3 free, EXPIRED-style key", {})
    gated = [r for r in rows if r["check"].startswith("v2 ")]
    if any(r.get("http") == 404 for r in gated):
        return ("NO ROUTE: the v2 expired-instruments family does not answer at all. "
                "backtest_data_20260908.md would be right.")
    if all(r.get("error_code") == ERR_BAD_TOKEN or r.get("http") == 401 for r in gated) and gated:
        base = ("GATED BY AUTH: the expired-instruments endpoints exist and refuse this "
                "caller for want of an OAuth token, not because the archive is absent.")
        if free_expired.get("error_code") == ERR_BAD_KEY_FORMAT:
            base += (" The free v3 route cannot even parse an expired key (UDAPI1021), "
                     "so no probing of it will ever reach one.")
        if free_listed.get("http") == 200:
            base += " The same free route serves a LISTED contract fine, so this is not a network fault."
        return base
    if any(r.get("error_code") == ERR_PLUS_REQUIRED for r in gated):
        return ("GATED BY PLAN: a valid token was presented and Upstox refused for want of "
                "an Upstox Plus subscription (UDAPI1149).")
    return "INCONCLUSIVE: " + json.dumps(rows)[:400]


# ── CLI ──────────────────────────────────────────────────────────────────────

_USAGE = """\
research.backtest.upstox_expired — is an expired NIFTY weekly reachable?

  probe                          4 unauthenticated requests; prints the verdict
  status                         token presence (name + True/False, never a value)
  expiries                       past expiries the vendor holds        [needs token]
  chain    --expiry YYYY-MM-DD   the expired chain for one expiry      [needs token]
  candles  --key K --from D --to D [--interval 1minute] [--store]      [needs token]
  verify   --key K --symbol S --from D --to D                          [needs token]
           reconcile the expired route against the Angel bars in candles.db

Nothing here places an order, writes to the trading database, or subscribes to
anything. `--store` writes candles and gap rows into data/historical/candles.db
under source='upstox_expired', alongside the Angel rows rather than over them.
"""


def _cmd_probe(args) -> int:
    print("probing, unauthenticated, 4 requests paced 6s apart\n")
    rows = probe()
    for r in rows:
        print(f"  {r['check']:<42} HTTP {str(r['http']):<4} "
              f"{r.get('error_code') or '':<14} rows={r['rows']}")
    print("\n" + classify_probe(rows))
    return 0


def _cmd_status(args) -> int:
    print("credentials (names and presence only):")
    for k, ok in credential_status().items():
        print(f"   {k}: {ok}")
    print("\nprovenance this route would declare:")
    for k, (grade, why) in provenance().items():
        print(f"   {k:<14} {grade:<12} {why}")
    return 0


def _cmd_expiries(args) -> int:
    got, url = expiries()
    print(f"{len(got)} expiries returned")
    for d in got:
        print(f"   {d}")
    if got:
        print(f"\noldest {got[0]}  newest {got[-1]}  span "
              f"{(got[-1] - got[0]).days} days")
    return 0


def _cmd_chain(args) -> int:
    expiry = _dt.date.fromisoformat(args.expiry)
    got, url = option_contracts(expiry)
    print(f"{len(got)} contracts for {expiry}")
    for c in got[:20]:
        print(f"   {c['trading_symbol']:<28} {c['expired_instrument_key']}")
    if len(got) > 20:
        print(f"   ... {len(got) - 20} more")
    return 0


def _cmd_candles(args) -> int:
    frm, to = _dt.date.fromisoformat(args.frm), _dt.date.fromisoformat(args.to)
    bars, receipts = expired_range(args.key, frm, to, args.interval,
                                   on_chunk=lambda i, n, a, b, r, e: print(
                                       f"  [{i}/{n}] {a}..{b} rows={r}" + (f" ERROR {e}" if e else "")))
    print(f"\n{len(bars)} bars, {len(receipts)} requests")
    if not bars:
        return 1
    s = sanity_check_premiums(bars)
    print(f"sanity: {s}")
    if args.store:
        from research.backtest import store
        con = store.connect()
        run_ids = [store.record_run(con, r, args.symbol or "") for r in receipts]
        n = store.write_candles(con, args.key, args.symbol or args.key,
                                _interval_tag(args.interval), bars, SOURCE,
                                run_ids[-1] if run_ids else None)
        store.detect_gaps(con, args.key, _interval_tag(args.interval), SOURCE)
        print(f"stored {n} bars under source={SOURCE!r} (gaps recorded, never filled)")
    return 0


def _cmd_verify(args) -> int:
    from research.backtest import store
    con = store.connect()
    frm, to = _dt.date.fromisoformat(args.frm), _dt.date.fromisoformat(args.to)
    broker = store.load_candles(con, args.broker_key, "angelone_smartapi", "1m",
                                frm=args.frm, to=args.to)
    if not broker:
        print(f"no Angel bars for {args.broker_key} in {args.frm}..{args.to}; "
              "nothing to reconcile against")
        return 1
    bars, _ = expired_range(args.key, frm, to, "1minute")
    verdict = verify_against_broker(broker, bars)
    for k, v in verdict.items():
        print(f"   {k}: {v}")
    return 0 if verdict["verdict"] == "RECONCILED" else 1


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="research.backtest.upstox_expired",
                                description=_USAGE,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe").set_defaults(fn=_cmd_probe)
    sub.add_parser("status").set_defaults(fn=_cmd_status)
    sub.add_parser("expiries").set_defaults(fn=_cmd_expiries)

    pc = sub.add_parser("chain")
    pc.add_argument("--expiry", required=True)
    pc.set_defaults(fn=_cmd_chain)

    pd_ = sub.add_parser("candles")
    pd_.add_argument("--key", required=True, help="expired_instrument_key, e.g. NSE_FO|47983|17-04-2025")
    pd_.add_argument("--from", dest="frm", required=True)
    pd_.add_argument("--to", dest="to", required=True)
    pd_.add_argument("--interval", default="1minute", choices=list(INTERVALS))
    pd_.add_argument("--symbol", default="")
    pd_.add_argument("--store", action="store_true")
    pd_.set_defaults(fn=_cmd_candles)

    pv = sub.add_parser("verify")
    pv.add_argument("--key", required=True)
    pv.add_argument("--broker-key", required=True, help="e.g. NFO:42615, as stored by Angel")
    pv.add_argument("--from", dest="frm", required=True)
    pv.add_argument("--to", dest="to", required=True)
    pv.set_defaults(fn=_cmd_verify)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except MissingToken as e:
        print(f"no token: {e}")
        return 2
    except ExpiredSourceError as e:
        extra = " (needs an Upstox Plus plan)" if e.needs_plus else ""
        print(f"expired route refused: {e}{extra}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
