"""Expiry dates, read from the broker's own instrument master.

Every NIFTY option contract Angel One lists carries its expiry in the symbol, and
brokers/… caches that dump at SCRIP_MASTER_CACHE_FILE. This module parses it, so the
answer to "when does the weekly expire" comes from the exchange rather than from a rule
written into the code.

That distinction is not academic. The codebase assumed Thursday in five places
(utils.helpers.is_expiry_date, three computations in core/risk/greeks_calc.py and the
fallback in core/trading/broker.py). Every NIFTY weekly in the cached dump is a Tuesday,
so is_expiry_date() was true only on days that are never expiry and false on every day
that is - and the time-to-expiry those functions derived, which feeds theta, gamma and
detect_day_type(), was two days out.

Nothing here guesses. When the dump is missing, unreadable, or holds no expiry at or
after the date asked about, every function says so - None, False or an empty list - and
the caller decides what to do with not knowing.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, time as _time
from typing import List, Optional

from config.constants import SCRIP_MASTER_CACHE_FILE

# NIFTY24MAR2523500CE -> expiry "24MAR25". Weeklies and monthlies share the shape.
_SYMBOL = re.compile(r"^NIFTY(\d{2}[A-Z]{3}\d{2})\d+(?:CE|PE)$")

# NSE closes the option at 15:30 IST; expiry-day time-to-expiry is measured to that.
CLOSE_TIME = _time(15, 30)

def _path(path: Optional[str]) -> str:
    """The instrument master to read. Resolved per call so the configured location is
    honoured even if it is changed after import - a default argument would bind once."""
    return path if path is not None else SCRIP_MASTER_CACHE_FILE


_cache: Optional[List[date]] = None
_cache_key: Optional[tuple] = None


def _read_symbols(path: str) -> List[str]:
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    if isinstance(blob, dict):
        token_map = blob.get("token_map") or {}
        if isinstance(token_map, dict):
            return [str(k) for k in token_map]
        return []
    if isinstance(blob, list):
        return [str(item.get("symbol", "")) for item in blob if isinstance(item, dict)]
    return []


def expiry_dates(path: Optional[str] = None) -> List[date]:
    """Every distinct NIFTY expiry in the instrument master, ascending.

    Empty when the file is absent or unreadable - that is a real answer, not an error:
    the bot has simply never spoken to the broker. Re-parsed when the file changes,
    since broker startup rewrites it.
    """
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

    found = set()
    try:
        for symbol in _read_symbols(path):
            match = _SYMBOL.match(symbol)
            if not match:
                continue
            try:
                found.add(datetime.strptime(match.group(1), "%d%b%y").date())
            except ValueError:
                continue
    except (OSError, ValueError, json.JSONDecodeError):
        _cache, _cache_key = [], None
        return []

    _cache, _cache_key = sorted(found), key
    return list(_cache)


def is_expiry_date(day: Optional[date] = None, path: Optional[str] = None) -> bool:
    """True only when the instrument master lists a contract expiring on `day`.

    False when the master is unavailable: an unknown expiry must not be reported as one.
    """
    path = _path(path)
    day = day or datetime.now().date()
    return day in set(expiry_dates(path))


def nearest_expiry(on_or_after: Optional[date] = None,
                   path: Optional[str] = None) -> Optional[date]:
    """First expiry on or after the date given (today by default), or None."""
    path = _path(path)
    day = on_or_after or datetime.now().date()
    for d in expiry_dates(path):
        if d >= day:
            return d
    return None


def next_expiry_after(day: Optional[date] = None,
                      path: Optional[str] = None) -> Optional[date]:
    """First expiry strictly after the date given, or None.

    Used where same-day expiry is not usable - Angel One serves no Greeks for a contract
    expiring today, so the Greeks path asks for the one after it.
    """
    path = _path(path)
    day = day or datetime.now().date()
    for d in expiry_dates(path):
        if d > day:
            return d
    return None


def expiry_datetime(day: Optional[date] = None,
                    path: Optional[str] = None) -> Optional[datetime]:
    """The nearest expiry as a datetime at the 15:30 close, or None."""
    path = _path(path)
    d = nearest_expiry(day, path)
    return datetime.combine(d, CLOSE_TIME) if d else None


def expiry_weekday(path: Optional[str] = None) -> Optional[int]:
    """The weekday NSE is actually expiring NIFTY weeklies on, as Monday=0.

    Learned from the dump rather than declared, so a change of expiry day needs no code
    change here. None when the master carries no expiries.
    """
    path = _path(path)
    dates = expiry_dates(path)
    if not dates:
        return None
    counts = {}
    for d in dates:
        counts[d.weekday()] = counts.get(d.weekday(), 0) + 1
    return max(counts, key=counts.get)


def describe(path: Optional[str] = None) -> str:
    """One line for logs and diagnostics: where the answer came from, and how fresh."""
    path = _path(path)
    dates = expiry_dates(path)
    if not dates:
        return f"no expiry data ({path} missing or unreadable)"
    try:
        age_h = (datetime.now().timestamp() - os.stat(path).st_mtime) / 3600.0
        age = f", cache age {age_h:.1f}h"
    except OSError:
        age = ""
    wd = expiry_weekday(path)
    name = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[wd]
    upcoming = nearest_expiry(path=path)
    return (f"{len(dates)} expiries from {path} (mostly {name}{age}); "
            f"next {upcoming.isoformat() if upcoming else 'none in the future'}")
