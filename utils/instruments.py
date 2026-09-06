"""Contract facts, read from the broker's own instrument master.

Angel One publishes every tradable contract with its expiry, strike, lot size, tick size
and freeze quantity; core/trading/broker.py downloads that file and caches it. This module
is the one place that reads it, so the answers to "when is expiry", "what is a lot", "what
price increments does this trade in" come from the exchange rather than from numbers
written into the code.

The loader used to keep only symbol -> token and discard the rest, and each discarded
field had been replaced by an assumption somewhere:

    expiry      assumed Thursday. Every NIFTY weekly listed is a Tuesday - and two of the
                eighteen are a Monday, because expiry shifts when a holiday lands on it.
                No weekday rule can be right; only the master is.
    tick_size   assumed 0.01, via round(limit_price, 2). Options trade in 0.05 steps, so
                limit prices landed between ticks and the exchange rejects those.
    strike      entry and exit round the spot to 50, greeks_calc rounded to 100, so the
                Greeks could describe a strike 50 points from the one being traded.
    lotsize     hardcoded 65. It agrees today; nothing would notice if it changed.
    freeze_qty  the largest quantity one order may carry. Nothing knew about it.

Nothing here guesses. With no master readable every accessor returns None or an empty
list, and each caller decides what to do about not knowing.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import date, datetime, time as _time
from typing import Dict, List, Optional

from config.constants import SCRIP_MASTER_CACHE_FILE

# NIFTY24MAR2523500CE -> "24MAR25". Only needed for caches written before the loader
# began keeping the expiry field itself.
_SYMBOL = re.compile(r"^NIFTY(\d{2}[A-Z]{3}\d{2})\d+(?:CE|PE)$")

# Strike and tick arrive in paise in the master; both scale by the same 100.
_PAISE = 100.0

# NSE closes the option at 15:30 IST; expiry-day time-to-expiry is measured to that.
CLOSE_TIME = _time(15, 30)

_cache: Optional[List[Dict]] = None
_cache_key: Optional[tuple] = None


def _path(path: Optional[str]) -> str:
    """Resolved per call, so the configured location is honoured even when it changes
    after import - a default argument would bind once."""
    return path if path is not None else SCRIP_MASTER_CACHE_FILE


def _num(value, scale: float = 1.0) -> Optional[float]:
    try:
        return float(value) / scale
    except (TypeError, ValueError):
        return None


def _record(symbol: str, raw: Dict) -> Optional[Dict]:
    """One normalised contract, or None when it carries no usable expiry."""
    expiry = None
    text = raw.get("expiry")
    if text:
        for fmt in ("%d%b%Y", "%d%b%y"):
            try:
                expiry = datetime.strptime(str(text), fmt).date()
                break
            except ValueError:
                continue
    if expiry is None:
        match = _SYMBOL.match(symbol)
        if match:
            try:
                expiry = datetime.strptime(match.group(1), "%d%b%y").date()
            except ValueError:
                expiry = None
    if expiry is None:
        return None
    return {
        "symbol": symbol,
        "token": str(raw.get("token") or ""),
        "expiry": expiry,
        "strike": _num(raw.get("strike"), _PAISE),
        "lot_size": int(_num(raw.get("lotsize")) or 0) or None,
        "tick_size": _num(raw.get("tick_size"), _PAISE),
        "freeze_qty": int(_num(raw.get("freeze_qty")) or 0) or None,
        "kind": str(raw.get("instrumenttype") or ""),
    }


def _load(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)

    if isinstance(blob, list):                      # the raw published dump
        return [r for r in (_record(str(i.get("symbol", "")), i)
                            for i in blob if isinstance(i, dict)) if r]

    if isinstance(blob, dict):
        contracts = blob.get("contracts")
        if isinstance(contracts, dict) and contracts:
            return [r for r in (_record(sym, raw) for sym, raw in contracts.items()
                                if isinstance(raw, dict)) if r]
        # A cache written before contract fields were kept: expiry is still recoverable
        # from the symbol, but lot size, tick size and the rest are simply not there.
        token_map = blob.get("token_map") or {}
        if isinstance(token_map, dict):
            return [r for r in (_record(str(sym), {"token": tok})
                                for sym, tok in token_map.items()) if r]
    return []


def contracts(path: Optional[str] = None) -> List[Dict]:
    """Every NIFTY contract in the master. Empty when it cannot be read - a real answer:
    the bot has not spoken to the broker. Re-read whenever the file changes, because
    broker startup rewrites it."""
    global _cache, _cache_key
    path = _path(path)
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        _cache, _cache_key = [], None
        return []

    if _cache is not None and _cache_key == key:
        return list(_cache)

    try:
        rows = _load(path)
    except (OSError, ValueError, json.JSONDecodeError):
        rows = []
    _cache, _cache_key = rows, key
    return list(rows)


def _options(path: Optional[str] = None) -> List[Dict]:
    """Options only. The master lists a few index futures under the same name, and they
    carry a different tick size, so they must not be averaged in."""
    rows = contracts(path)
    typed = [r for r in rows if r["kind"].startswith("OPT")]
    # Caches without instrumenttype fall back to the symbol shape.
    return typed or [r for r in rows if r["symbol"].endswith(("CE", "PE"))]


# ── expiry ───────────────────────────────────────────────────────────
def expiry_dates(path: Optional[str] = None) -> List[date]:
    """Every distinct expiry, ascending."""
    return sorted({r["expiry"] for r in contracts(path)})


def is_expiry_date(day: Optional[date] = None, path: Optional[str] = None) -> bool:
    """True only when a contract actually expires on `day`. False when the master is
    unavailable: an unknown expiry must not be reported as one."""
    day = day or datetime.now().date()
    return day in set(expiry_dates(path))


def nearest_expiry(on_or_after: Optional[date] = None,
                   path: Optional[str] = None) -> Optional[date]:
    """First expiry on or after the date given (today by default), or None."""
    day = on_or_after or datetime.now().date()
    return next((d for d in expiry_dates(path) if d >= day), None)


def next_expiry_after(day: Optional[date] = None,
                      path: Optional[str] = None) -> Optional[date]:
    """First expiry strictly after the date given, or None. Angel One serves no Greeks
    for a contract expiring today, so the Greeks path asks for the one after it."""
    day = day or datetime.now().date()
    return next((d for d in expiry_dates(path) if d > day), None)


def expiry_datetime(day: Optional[date] = None,
                    path: Optional[str] = None) -> Optional[datetime]:
    """The nearest expiry as a datetime at the 15:30 close, or None."""
    d = nearest_expiry(day, path)
    return datetime.combine(d, CLOSE_TIME) if d else None


def expiry_weekday(path: Optional[str] = None) -> Optional[int]:
    """The weekday NIFTY weeklies mostly expire on, Monday=0 - counted, not declared.
    Reported for diagnostics only; never use it to predict a date, because holidays move
    individual expiries off it."""
    dates = expiry_dates(path)
    if not dates:
        return None
    counts = Counter(d.weekday() for d in dates)
    return counts.most_common(1)[0][0]


# ── contract mechanics ───────────────────────────────────────────────
def _modal(values) -> Optional[float]:
    vals = [v for v in values if v]
    return Counter(vals).most_common(1)[0][0] if vals else None


def lot_size(path: Optional[str] = None) -> Optional[int]:
    """Contract lot size as the exchange lists it, or None."""
    value = _modal(r["lot_size"] for r in _options(path))
    return int(value) if value else None


def tick_size(path: Optional[str] = None) -> Optional[float]:
    """Minimum price increment in rupees (0.05 for NIFTY options), or None."""
    return _modal(r["tick_size"] for r in _options(path))


def freeze_quantity(path: Optional[str] = None) -> Optional[int]:
    """Largest quantity a single order may carry before the exchange refuses it."""
    value = _modal(r["freeze_qty"] for r in _options(path))
    return int(value) if value else None


def strike_step(path: Optional[str] = None) -> Optional[int]:
    """Spacing of listed strikes on the front expiry, or None.

    Measured on one expiry: far-dated series are listed sparsely, so mixing them in would
    report a step no near-dated contract uses.
    """
    front = nearest_expiry(path=path)
    if not front:
        return None
    strikes = sorted({r["strike"] for r in _options(path)
                      if r["expiry"] == front and r["strike"]})
    gaps = [round(b - a) for a, b in zip(strikes, strikes[1:]) if b > a]
    return int(Counter(gaps).most_common(1)[0][0]) if gaps else None


def round_to_tick(price: float, side: str = "BUY",
                  path: Optional[str] = None, tick: Optional[float] = None) -> float:
    """Snap a price onto the exchange's tick grid, never against the trader.

    A buy limit rounds down and a sell limit rounds up, so the rounding can only improve
    the price paid, never worsen it. With no tick known the price is returned to two
    decimals, which is what the code did everywhere before.
    """
    step = tick if tick else tick_size(path)
    if not step or step <= 0:
        return round(price, 2)
    units = price / step
    # Tolerate binary float error before deciding which way to move.
    if abs(units - round(units)) < 1e-9:
        return round(round(units) * step, 2)
    import math
    snapped = math.floor(units) if str(side).upper() == "BUY" else math.ceil(units)
    return round(snapped * step, 2)


def describe(path: Optional[str] = None) -> str:
    """One line for logs and diagnostics: what was read, and how fresh it is."""
    path = _path(path)
    rows = contracts(path)
    if not rows:
        return f"no instrument master ({path} missing or unreadable)"
    try:
        age = f", cache age {(datetime.now().timestamp() - os.stat(path).st_mtime)/3600:.1f}h"
    except OSError:
        age = ""
    upcoming = nearest_expiry(path=path)
    return (f"{len(rows):,} contracts, {len(expiry_dates(path))} expiries from {path}"
            f"{age}; next {upcoming.isoformat() if upcoming else 'none ahead'}, "
            f"lot {lot_size(path)}, tick {tick_size(path)}, strike step {strike_step(path)}")
