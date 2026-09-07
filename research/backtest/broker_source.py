"""Angel One SmartAPI historical candles — the primary feed, and its measured limits.

This is a READ-ONLY client. It logs in, calls `getCandleData`, and logs out of
nothing (see the isolation note below). It never places, modifies or queries an
order, and it never writes a credential anywhere: the four secrets are read from
`config.constants`, held in local variables, and only `bool(present)` is ever
printed or persisted.

WHAT WAS MEASURED (2026-09-08, this account, NIFTY)
--------------------------------------------------
Index (exchange NSE, token = config.constants.NIFTY_SPOT_TOKEN), ONE_MINUTE:
    * 2015-01 returns a full month. 2012-01 returns zero rows. So the 1-minute
      archive begins somewhere in 2012-2015 — deeper than any free source found.
    * 375 bars per session, 09:15..15:29 IST.

Options (exchange NFO, token from the ScripMaster), ONE_MINUTE:
    * Real 1-minute option premium, which free sources essentially never give.
    * BUT bounded by the contract's listing date, not by the archive. The
      2026-09-08 weekly ATM CE (token 42635) returns 2026-08-19..2026-09-04 and
      exactly zero rows for any window before 2026-08-19.
    * EXPIRED CONTRACTS ARE UNREACHABLE. The ScripMaster holds only unexpired
      contracts, so an expired weekly's token cannot be looked up; blind token
      probes (30000, 33000, 35000, 36000, 38000, 40000, 41000) over a July 2026
      window all returned zero rows. Upstox's free endpoint has exactly the same
      boundary and the same listing date, which is corroboration rather than
      coincidence: this is an exchange-side archive boundary, not a broker quirk.
      => There is no route, free or credentialed, to a NIFTY weekly option that
         has already expired. Option backtesting is capped at the currently
         listed chains.

THE SILENT CLAMP — the trap in this API, and it is NOT the documented one
-------------------------------------------------------------------------
A ONE_MINUTE request that is too wide does NOT error. It returns the most recent
part of the requested range and drops the oldest, silently:

    request 2026-06-07..2026-09-05  ->  7950 rows starting 2026-08-06
    request 2026-07-22..2026-09-05  ->  7950 rows starting 2026-08-06
    request 2026-08-06..2026-09-05  ->  7950 rows starting 2026-08-06

All three are the same answer to different questions. That much matches the
documented "~30 days per call". The documentation is wrong about the unit, and
the difference matters:

    THE CAP IS A ROW COUNT, ABOUT 8000 CANDLES — NOT A NUMBER OF DAYS.

Measured on a first pass that chunked at 30 calendar days: four chunks came back
holding exactly 8000 rows, and in each of them the OLDEST session was truncated
to 125 bars (8000 = 21 full sessions x 375 + 125). Refetched on its own,
2025-01-01 returns its full 375 bars and 2025-06-30 returns its full 375. So a
30-day chunk that happens to contain 22 trading days silently loses two-thirds of
its first day, and nothing in the response says so — the day is simply short, and
looks exactly like a half-session.

MAX_WINDOW_DAYS is therefore 20 calendar days (<=15 trading days, <=5625 rows),
which leaves a wide margin under the cap. Do not raise it back to 30 because the
documentation says 30.

A genuinely short session does exist and must not be "repaired": 2025-10-21
returns 72 bars from 11:17 to 14:46 whether fetched alone or in a chunk. That is
the Diwali Muhurat session, and it is real.

RATE LIMIT
----------
SmartAPI publishes ~3 requests/second for getCandleData. `PACING_SEC` is 0.45s
(~2.2 rps), under the limit with margin. The bundled client applies its own
`_rate_limit('getCandleData')` too; this module talks to SmartConnect directly so
that a research pull cannot perturb the trading client's state, and so re-applies
the pacing itself.

SESSION ISOLATION (inherited from utils/run_historical_collector.py)
--------------------------------------------------------------------
This module NEVER calls logout()/terminateSession(). Angel One's teardown is
account-scoped, so logging out here could invalidate a live trading session. It
only ever logs in and lets the session lapse.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from typing import Dict, Iterable, List, Optional, Tuple

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

# Measured above: the cap is ~8000 rows, so this is sized in rows, not days.
# 20 calendar days holds at most 15 trading days = 5625 one-minute bars.
MAX_WINDOW_DAYS = 20
ROW_CAP = 8000             # observed truncation point for ONE_MINUTE
# 0.45s (~2.2 rps) is inside the published ~3 rps ceiling but still earned
# "Access denied because of exceeding access rate" on a burst of small requests,
# so there is a second, longer-window limit that is not published. 1.0s plus the
# backoff in _call() survived a full multi-hundred-request import.
PACING_SEC = 1.0
RATE_LIMIT_BACKOFF = (5.0, 20.0, 60.0)
INDEX_EXCHANGE = "NSE"
OPTION_EXCHANGE = "NFO"
ONE_MINUTE = "ONE_MINUTE"

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPMASTER = os.path.join(_ROOT, "core", "data", "scripmaster_nifty_nfo.json")


class BrokerSourceError(RuntimeError):
    pass


# ── credentials ──────────────────────────────────────────────────────────────

def credential_status() -> Dict[str, bool]:
    """Which credential NAMES are populated. Values are never returned or logged.

    A leak has happened twice on this project, both times by printing a whole
    config object. This function exists so that no caller ever needs the values
    in order to report readiness.
    """
    from config import constants as c
    return {
        "ANGEL_API_KEY": bool(getattr(c, "ANGEL_API_KEY", "")),
        "ANGEL_CLIENT_ID": bool(getattr(c, "ANGEL_CLIENT_ID", "")),
        "ANGEL_PASSWORD": bool(getattr(c, "ANGEL_PASSWORD", "")),
        "ANGEL_TOTP_SECRET": bool(getattr(c, "ANGEL_TOTP_SECRET", "")),
        "NIFTY_SPOT_TOKEN": bool(getattr(c, "NIFTY_SPOT_TOKEN", "")),
    }


def _connect():
    """Own SmartConnect session. Read-only use; never logs out."""
    from SmartApi import SmartConnect
    import pyotp
    from config import constants as c

    missing = [k for k, ok in credential_status().items() if not ok]
    if missing:
        raise BrokerSourceError(f"missing credentials: {', '.join(missing)} (names only)")

    sm = SmartConnect(api_key=c.ANGEL_API_KEY)
    data = sm.generateSession(c.ANGEL_CLIENT_ID, c.ANGEL_PASSWORD,
                              pyotp.TOTP(c.ANGEL_TOTP_SECRET).now())
    if not (data and data.get("status")):
        # data['message'] is a status string, not a secret.
        raise BrokerSourceError(f"login failed: {(data or {}).get('message', 'no response')}")
    return sm


# ── candles ──────────────────────────────────────────────────────────────────

def _parse_rows(rows: Iterable) -> List[Dict]:
    out = []
    for r in rows or []:
        ts = _dt.datetime.fromisoformat(r[0])
        out.append({
            "ts": ts, "epoch": int(ts.timestamp()),
            "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]),
            "volume": int(r[5] or 0),
            # getCandleData carries no open interest. Recorded as absent, never as 0
            # pretending to be a reading — see research/provenance.py on `oi`.
            "oi": None,
        })
    return out


def _day_chunks(frm: _dt.date, to: _dt.date, span: int):
    cur, step, one = frm, _dt.timedelta(days=span - 1), _dt.timedelta(days=1)
    while cur <= to:
        end = min(cur + step, to)
        yield cur, end
        cur = end + one


class AngelHistorical:
    """One login, many candle requests, paced. Read-only."""

    def __init__(self, smart=None):
        self.sm = smart or _connect()

    def candles(self, token: str, exchange: str, frm: _dt.date, to: _dt.date,
                interval: str = ONE_MINUTE) -> Tuple[List[Dict], Dict]:
        """One request. Returns (bars oldest-first, receipt).

        The receipt records BOTH the requested range and the range actually
        returned, because this API clamps long ONE_MINUTE windows silently.
        """
        frm_s = f"{frm.isoformat()} 09:15"
        to_s = f"{to.isoformat()} 15:30"
        fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        err = None
        rows: List[Dict] = []
        params = {"exchange": exchange, "symboltoken": str(token),
                  "interval": interval, "fromdate": frm_s, "todate": to_s}
        for attempt, wait in enumerate((0.0,) + RATE_LIMIT_BACKOFF):
            if wait:
                time.sleep(wait)
            err = None
            try:
                resp = self.sm.getCandleData(params)
                if resp and resp.get("status"):
                    rows = _parse_rows(resp.get("data") or [])
                    break
                err = f"status=false message={(resp or {}).get('message')!r}"
            except Exception as e:  # noqa: BLE001 - network/SDK shapes vary
                err = f"{type(e).__name__}: {e}"
            # Only a rate-limit refusal is worth retrying. Anything else (a bad
            # token, an unlisted contract) will fail identically forever, and
            # retrying it would just spend the rate budget.
            if "exceeding access rate" not in str(err):
                break

        got_from = rows[0]["ts"].date().isoformat() if rows else None
        got_to = rows[-1]["ts"].date().isoformat() if rows else None
        receipt = {
            "source": "angelone_smartapi",
            "endpoint_url": f"SmartConnect.getCandleData exchange={exchange} interval={interval}",
            "instrument_key": f"{exchange}:{token}",
            "interval": "1m" if interval == ONE_MINUTE else interval,
            "requested_from": frm.isoformat(), "requested_to": to.isoformat(),
            "returned_from": got_from, "returned_to": got_to,
            "rows_returned": len(rows), "fetched_at_utc": fetched_at, "error": err,
            # The clamp is a property of the REQUEST WIDTH, not of the answer.
            # A window that opens on a weekend or a holiday also returns a later
            # first bar, and calling that "clamped" would cry wolf on almost every
            # chunk. Only a request wider than the documented ceiling can have been
            # truncated; `returned_from` above lets a reader check the rest.
            # Truncation is a row-count effect, so the honest test is the row
            # count, not the calendar width. At the cap, assume the oldest day
            # was cut and say so; below it, the response is whole.
            "clamped": len(rows) >= ROW_CAP,
        }
        return rows, receipt

    def range(self, token: str, exchange: str, frm: _dt.date, to: _dt.date,
              interval: str = ONE_MINUTE, pacing: float = PACING_SEC,
              on_chunk=None) -> Tuple[List[Dict], List[Dict]]:
        """Walk a long span in <=30-day chunks so the clamp never engages.

        A failed chunk is recorded and skipped. It is never retried into a shifted
        date range and never substituted from another vendor: the hole stays a
        hole, and store.py writes it as an explicit gap row.
        """
        bars: List[Dict] = []
        receipts: List[Dict] = []
        chunks = list(_day_chunks(frm, to, MAX_WINDOW_DAYS))
        for i, (a, b) in enumerate(chunks):
            got, receipt = self.candles(token, exchange, a, b, interval)
            bars.extend(got)
            receipts.append(receipt)
            if on_chunk:
                on_chunk(i + 1, len(chunks), a, b, len(got), receipt["error"])
            if pacing and i + 1 < len(chunks):
                time.sleep(pacing)
        seen, dedup = set(), []
        for bar in sorted(bars, key=lambda r: r["epoch"]):
            if bar["epoch"] in seen:
                continue
            seen.add(bar["epoch"])
            dedup.append(bar)
        return dedup, receipts


# ── instruments ──────────────────────────────────────────────────────────────

def load_scripmaster(path: str = SCRIPMASTER) -> Dict:
    if not os.path.exists(path):
        raise BrokerSourceError(
            f"ScripMaster cache not found at {path}; the trading bot writes it at warm-up")
    with open(path) as f:
        return json.load(f)


def nifty_option_contracts(scrip: Optional[Dict] = None) -> List[Dict]:
    """NIFTY CE/PE contracts from the cached ScripMaster, normalised.

    Only unexpired contracts are present — that is the archive boundary described
    in the module docstring, not an omission that can be patched here.
    """
    scrip = scrip or load_scripmaster()
    out = []
    for symbol, meta in (scrip.get("contracts") or {}).items():
        if meta.get("instrumenttype") != "OPTIDX" or not symbol.startswith("NIFTY"):
            continue
        opt_type = symbol[-2:]
        if opt_type not in ("CE", "PE"):
            continue
        try:
            expiry = _dt.datetime.strptime(meta["expiry"], "%d%b%Y").date()
        except (KeyError, ValueError):
            continue
        # ScripMaster strikes are in paise: "2300000.000000" is strike 23000.
        try:
            strike = float(meta["strike"]) / 100.0
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            "token": str(meta["token"]), "symbol": symbol, "instrument_type": opt_type,
            "strike": strike, "expiry": expiry,
            "lot_size": int(float(meta.get("lotsize") or 0)),
            # ScripMaster tick_size is also in paise: 5.0 -> Rs0.05.
            "tick_size": float(meta.get("tick_size") or 0) / 100.0,
        })
    return out


def atm_band(contracts: List[Dict], expiry: _dt.date, low: float, high: float,
             step: float = 50.0, types=("CE", "PE")) -> List[Dict]:
    """Contracts of one expiry whose strike falls in [low, high].

    `step` is the NIFTY strike interval and is NOT assumed to be 100: the
    instrument master is the authority, and NIFTY weeklies step by 50.
    """
    lo = step * round(low / step)
    hi = step * round(high / step)
    return sorted(
        (c for c in contracts
         if c["expiry"] == expiry and lo <= c["strike"] <= hi and c["instrument_type"] in types),
        key=lambda c: (c["strike"], c["instrument_type"]))
