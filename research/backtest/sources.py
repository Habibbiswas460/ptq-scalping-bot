"""What the public internet actually returns for NIFTY, measured on 2026-09-08.

ROLE: these are the CROSS-CHECK, not the feed. broker_source.py (Angel One
SmartAPI) is the primary source — it reaches back to 2015 on the index where the
best free source reaches 2022, and it is the only one with the option chain
already wired into this repo. What the free sources are worth is independence:
two unrelated vendors agreeing on a close is evidence that the broker feed is
undistorted; one vendor agreeing with itself is not. compare.py does that check.

Every limit written here was probed, not read off a documentation page. The probe
results, in full:

UPSTOX  https://api.upstox.com/v3/historical-candle/{key}/minutes/1/{to}/{from}
    No API key, no OAuth, no account. Returns real 1-minute OHLCV.
    - NIFTY 50 index (NSE_INDEX|Nifty 50): 1-minute back to 2026-01-05 confirmed,
      and 2022-01-05 confirmed; 2021-01-05 and 2019-01-05 return zero candles.
      So the 1-minute archive begins in January 2022.
    - Window cap: 30 calendar days per request (31+ -> HTTP 400). Longer spans must
      be walked in chunks.
    - Rate limit: bursts of ~10 requests earn HTTP 403 for several minutes. The
      pacing below (6s) survived a 100+ request run.
    - NIFTY weekly/monthly OPTIONS work on the same endpoint with an
      NSE_FO|<token> key. This is the surprise: real 1-minute option premium,
      free. The catch is severe and is enforced in resolve_option_keys():
      only contracts present in the CURRENT instrument master are addressable,
      and an expired contract's token is not in it. A random token returns 400.
      Near weeklies carry ~13 trading days of history (from 2026-08-19).

YAHOO   https://query2.finance.yahoo.com/v8/finance/chart/^NSEI?interval=1m
    - query1.finance.yahoo.com returned HTTP 429 on every attempt from this host;
      query2 worked. Both are otherwise the same API.
    - 8 calendar days per request (9+ -> HTTP 422 naming the limit), and the 1m
      archive itself stops ~30 days back (a window 4 weeks old -> 422).
    - 375 bars per session (09:15..15:29 IST) plus ONE trailing bar stamped at the
      last regular-market time, which is a quote artifact and not a 376th minute.
      _strip_yahoo_artifact() drops it. Missing that is how a duplicate 15:30 bar
      gets into a dataset.
    - Used here only as an INDEPENDENT CHECK on Upstox, which is worth more than
      its 30-day depth: two unrelated vendors agreeing on a close is evidence,
      one vendor is an assumption.

STOOQ   Solved its SHA-256 proof-of-work challenge and still got "Access denied"
    on /q/d/l/. Not usable from here. Recorded so nobody spends the hour again.

DHAN    /v2/charts/intraday -> HTTP 401 DH-901. Needs a client id and access token.
NSE     www.nseindia.com -> HTTP 403 to any non-browser client.
ALPHA VANTAGE / TWELVE DATA  require a key and neither lists NIFTY 50 index
    intraday on the free tier; not pursued once Upstox proved deeper than both.
"""
from __future__ import annotations

import datetime as _dt
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Tuple

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")
_HEADERS = {"Accept": "application/json", "User-Agent": _UA}

UPSTOX_CANDLE = "https://api.upstox.com/v3/historical-candle/{key}/minutes/{iv}/{to}/{frm}"
UPSTOX_MASTER = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
YAHOO_CHART = ("https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI"
               "?interval={iv}&period1={p1}&period2={p2}")

NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"

# Measured, not assumed. See the module docstring.
UPSTOX_MAX_WINDOW_DAYS = 30
UPSTOX_1M_EPOCH = _dt.date(2022, 1, 1)
YAHOO_MAX_WINDOW_DAYS = 8
UPSTOX_PACING_SEC = 6.0

# NSE regular session. 375 one-minute bars, 09:15 through 15:29 inclusive.
SESSION_OPEN = _dt.time(9, 15)
SESSION_LAST_BAR = _dt.time(15, 29)
BARS_PER_SESSION = 375


class SourceError(RuntimeError):
    """A source refused or returned something unusable. Never swallowed silently:
    the caller records the failure rather than substituting a different source."""


def _get_json(url: str, timeout: int = 60) -> Dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} for {url}") from e
    except Exception as e:  # noqa: BLE001 - network shapes vary; the caller logs it
        raise SourceError(f"{type(e).__name__}: {e} for {url}") from e


def _day_chunks(frm: _dt.date, to: _dt.date, span: int) -> Iterable[Tuple[_dt.date, _dt.date]]:
    """Walk [frm, to] in <= span-day windows, oldest first, without overlap."""
    cur = frm
    step = _dt.timedelta(days=span - 1)
    one = _dt.timedelta(days=1)
    while cur <= to:
        end = min(cur + step, to)
        yield cur, end
        cur = end + one


# ── Upstox ───────────────────────────────────────────────────────────────────

def upstox_candles(instrument_key: str, frm: _dt.date, to: _dt.date,
                   interval: int = 1) -> Tuple[List[Dict], str]:
    """One request. Returns (bars oldest-first, the URL that produced them).

    Upstox answers newest-first with rows [ts, o, h, l, c, volume, oi]; they are
    reversed here so every consumer in this package sees time moving forward.
    """
    if (to - frm).days + 1 > UPSTOX_MAX_WINDOW_DAYS:
        raise ValueError(f"window {frm}..{to} exceeds the measured {UPSTOX_MAX_WINDOW_DAYS}-day cap")
    url = UPSTOX_CANDLE.format(key=urllib.parse.quote(instrument_key, safe=""),
                               iv=interval, to=to.isoformat(), frm=frm.isoformat())
    payload = _get_json(url)
    if payload.get("status") != "success":
        raise SourceError(f"upstox status={payload.get('status')!r} for {url}")
    raw = (payload.get("data") or {}).get("candles") or []
    out: List[Dict] = []
    for row in reversed(raw):
        ts = _dt.datetime.fromisoformat(row[0])
        out.append({
            "ts": ts,
            "epoch": int(ts.timestamp()),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": int(row[5] or 0),
            "oi": int(row[6] or 0) if len(row) > 6 else 0,
        })
    return out, url


def upstox_range(instrument_key: str, frm: _dt.date, to: _dt.date, interval: int = 1,
                 pacing: float = UPSTOX_PACING_SEC, on_chunk=None) -> Tuple[List[Dict], List[Dict]]:
    """Walk a long span in 30-day chunks. Returns (bars, one receipt per request).

    A chunk that fails is recorded in its receipt with the error and SKIPPED. It is
    never retried into a different date range and never back-filled from another
    source: the resulting hole stays a hole and store.py writes it as a gap.
    """
    bars: List[Dict] = []
    receipts: List[Dict] = []
    chunks = list(_day_chunks(frm, to, UPSTOX_MAX_WINDOW_DAYS))
    for i, (a, b) in enumerate(chunks):
        fetched_at = _dt.datetime.now(_dt.timezone.utc)
        try:
            got, url = upstox_candles(instrument_key, a, b, interval)
            err = None
        except (SourceError, ValueError) as e:
            got, url, err = [], UPSTOX_CANDLE.format(
                key=urllib.parse.quote(instrument_key, safe=""), iv=interval,
                to=b.isoformat(), frm=a.isoformat()), str(e)
        bars.extend(got)
        receipts.append({
            "source": "upstox", "endpoint_url": url, "instrument_key": instrument_key,
            "interval": f"{interval}m", "requested_from": a.isoformat(),
            "requested_to": b.isoformat(), "rows_returned": len(got),
            "fetched_at_utc": fetched_at.isoformat(), "error": err,
        })
        if on_chunk:
            on_chunk(i + 1, len(chunks), a, b, len(got), err)
        if pacing and i + 1 < len(chunks):
            time.sleep(pacing)
    # Chunks are disjoint by construction, but a vendor may still repeat a boundary
    # minute. Deduplicate on epoch, keeping the first, rather than trusting it.
    seen, dedup = set(), []
    for bar in sorted(bars, key=lambda r: r["epoch"]):
        if bar["epoch"] in seen:
            continue
        seen.add(bar["epoch"])
        dedup.append(bar)
    return dedup, receipts


def upstox_instrument_master(timeout: int = 180) -> Tuple[List[Dict], str]:
    """The public gzipped instrument master. No auth."""
    req = urllib.request.Request(UPSTOX_MASTER, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(gzip.decompress(r.read()).decode("utf-8")), UPSTOX_MASTER
    except Exception as e:  # noqa: BLE001
        raise SourceError(f"instrument master: {type(e).__name__}: {e}") from e


def nifty_option_contracts(master: List[Dict]) -> List[Dict]:
    """NIFTY CE/PE rows from the master, normalised.

    The master holds only contracts that have NOT yet expired. That is the single
    hardest limit on option backtesting from this source and it is not a bug to be
    worked around: an expired weekly's token is simply not addressable, and guessing
    one returns HTTP 400.
    """
    out = []
    for x in master:
        if x.get("segment") != "NSE_FO" or x.get("underlying_symbol") != "NIFTY":
            continue
        if x.get("instrument_type") not in ("CE", "PE"):
            continue
        out.append({
            "instrument_key": x["instrument_key"],
            "trading_symbol": x.get("trading_symbol", ""),
            "instrument_type": x["instrument_type"],
            "strike": float(x.get("strike_price") or 0),
            "expiry": _dt.datetime.fromtimestamp(x["expiry"] / 1000, IST).date(),
            "lot_size": int(x.get("lot_size") or 0),
            "tick_size": float(x.get("tick_size") or 0),
            "weekly": bool(x.get("weekly")),
        })
    return out


def resolve_option_keys(contracts: List[Dict], expiry: _dt.date,
                        strikes: Iterable[float], types=("CE", "PE")) -> List[Dict]:
    want = {float(s) for s in strikes}
    return sorted(
        (c for c in contracts
         if c["expiry"] == expiry and c["strike"] in want and c["instrument_type"] in types),
        key=lambda c: (c["strike"], c["instrument_type"]))


# ── Yahoo (cross-check only) ─────────────────────────────────────────────────

def _strip_yahoo_artifact(bars: List[Dict]) -> List[Dict]:
    """Drop the trailing quote bar Yahoo appends outside the session grid.

    Yahoo returns 375 real minutes (09:15..15:29) and then one more row stamped at
    the last regular-market time — 15:30, which is not a traded minute. It also
    appears, alone, in windows that are entirely in the past. Anything at or after
    15:30 IST is that artifact.
    """
    return [b for b in bars if b["ts"].astimezone(IST).time() < _dt.time(15, 30)]


def yahoo_candles(frm: _dt.date, to: _dt.date, interval: str = "1m") -> Tuple[List[Dict], str]:
    p1 = int(_dt.datetime.combine(frm, _dt.time(0, 0), IST).timestamp())
    p2 = int(_dt.datetime.combine(to + _dt.timedelta(days=1), _dt.time(0, 0), IST).timestamp())
    url = YAHOO_CHART.format(iv=interval, p1=p1, p2=p2)
    payload = _get_json(url)
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise SourceError(f"yahoo {chart['error']} for {url}")
    res = (chart.get("result") or [None])[0]
    if not res:
        raise SourceError(f"yahoo empty result for {url}")
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c = (q.get("open") or []), (q.get("high") or []), (q.get("low") or []), (q.get("close") or [])
    v = q.get("volume") or []
    bars = []
    for i, t in enumerate(ts):
        # A None close is Yahoo saying it has no print for that minute. It is dropped
        # and later shows up as a gap; it is never carried forward from the last bar.
        if i >= len(c) or c[i] is None:
            continue
        bars.append({
            "ts": _dt.datetime.fromtimestamp(t, IST), "epoch": int(t),
            "open": float(o[i]) if i < len(o) and o[i] is not None else float(c[i]),
            "high": float(h[i]) if i < len(h) and h[i] is not None else float(c[i]),
            "low": float(l[i]) if i < len(l) and l[i] is not None else float(c[i]),
            "close": float(c[i]),
            "volume": int(v[i]) if i < len(v) and v[i] is not None else 0,
            "oi": 0,
        })
    return _strip_yahoo_artifact(bars), url
