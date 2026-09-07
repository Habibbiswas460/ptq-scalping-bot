"""Which days the exchange is actually open.

Weekends are arithmetic. Holidays are not: no source the bot can reach publishes them -
not the Angel One client, not the SmartAPI SDK, not the instrument master - so they have
to come from data. This module has three inputs and keeps them apart, because they carry
different weight:

  declared    config/nse_holidays.json, the NSE circular transcribed. Authoritative.
              Ships empty; nothing here writes dates it cannot support.
  inferred    NIFTY weeklies expire on one weekday, and an expiry that falls earlier means
              the usual day was shut. The instrument master lists 2026-11-23 (Monday) and
              2029-12-24 (Monday), implying 2026-11-24 and 2029-12-25 were holidays - and
              the second is Christmas, which is how you can tell the inference works.
              It only ever finds holidays that land on an expiry day.
  observed    dates the trade store holds market data for. These prove a day was OPEN.
              They are never read the other way round: this project's collection has gaps,
              so a date with no data means nothing was recorded, not that nothing traded.

Anything with no evidence is unknown, and unknown is reported as unknown. is_trading_day()
answers False only when it can show why; callers that must decide treat unknown as open,
which is the behaviour that was there before, but they can now say so.

Populate the declared file from the broker with:

    ./venv/bin/python -m utils.trading_calendar fetch 2026-01-01 2026-12-31

which asks for NIFTY spot candles across the range and records the weekdays that returned
none. That needs credentials, and is the only thing here that talks to a broker.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections import Counter
from typing import Dict, List, Optional, Tuple

from config.constants import NSE_HOLIDAY_FILE

DECLARED = "declared"
INFERRED = "inferred"

# The note the declared file carries. It lives here, not only in the shipped JSON, because
# write_declared() rewrites the whole file: when the text was duplicated, the first fetch
# silently replaced the shipped note - including the only place that says how to refill it.
NOTE = (
    "NSE trading holidays. Dates here are treated as authoritative: market_open() returns "
    "False on them and next_trading_day() skips them. Anything not listed is 'unknown', "
    "not 'trading' - utils/trading_calendar.py never invents a date. Populate it from the "
    "broker with: ./venv/bin/python -m utils.trading_calendar fetch 2026-01-01 2026-12-31 "
    "(asks for NIFTY spot candles and records the weekdays that produced none), or add "
    "entries by hand from the NSE circular."
)

_cache: Optional[Dict[_dt.date, str]] = None
_cache_key: Optional[tuple] = None


def _path(path: Optional[str]) -> str:
    return path if path is not None else NSE_HOLIDAY_FILE


def _parse(text) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        return None


def declared_holidays(path: Optional[str] = None) -> Dict[_dt.date, str]:
    """The transcribed calendar. Empty, not an error, when the file is absent."""
    path = _path(path)
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, ValueError):
        return {}
    entries = blob.get("holidays") if isinstance(blob, dict) else blob
    if not isinstance(entries, list):
        return {}
    out: Dict[_dt.date, str] = {}
    for item in entries:
        if isinstance(item, dict):
            day, name = _parse(item.get("date")), str(item.get("name") or "holiday")
        else:
            day, name = _parse(item), "holiday"
        if day:
            out[day] = name
    return out


def inferred_holidays() -> Dict[_dt.date, str]:
    """Holidays implied by an expiry that moved off its usual weekday.

    Only finds the ones that land on expiry day, so it is a supplement to the declared
    file and never a replacement for it.
    """
    from utils.instruments import expiry_dates

    dates = expiry_dates()
    if len(dates) < 3:
        return {}
    usual = Counter(d.weekday() for d in dates).most_common(1)[0][0]
    out: Dict[_dt.date, str] = {}
    for d in dates:
        if d.weekday() == usual:
            continue
        shift = (usual - d.weekday()) % 7
        if 0 < shift <= 3:          # expiry is pulled earlier, not pushed a week out
            out[d + _dt.timedelta(days=shift)] = f"expiry moved to {d.isoformat()}"
    return out


def holidays(path: Optional[str] = None) -> Dict[_dt.date, Tuple[str, str]]:
    """Every holiday known, as {date: (source, reason)}. Declared beats inferred."""
    global _cache, _cache_key
    path = _path(path)
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (path, None, None)

    out: Dict[_dt.date, Tuple[str, str]] = {
        d: (INFERRED, why) for d, why in inferred_holidays().items()}
    out.update({d: (DECLARED, name) for d, name in declared_holidays(path).items()})
    _cache_key = key
    return out


def is_holiday(day: Optional[_dt.date] = None, path: Optional[str] = None) -> bool:
    """True only when the day is a holiday this module can point at evidence for."""
    day = day or _dt.date.today()
    return day in holidays(path)


def holiday_reason(day: _dt.date, path: Optional[str] = None) -> Optional[str]:
    hit = holidays(path).get(day)
    return f"{hit[0]}: {hit[1]}" if hit else None


def is_trading_day(day: Optional[_dt.date] = None, path: Optional[str] = None) -> bool:
    """False at the weekend and on a known holiday; True otherwise.

    True therefore means "no reason to think otherwise", not "confirmed open". Use
    unknown_calendar() when that difference matters.
    """
    day = day or _dt.date.today()
    if day.weekday() >= 5:
        return False
    return not is_holiday(day, path)


def unknown_calendar(path: Optional[str] = None) -> bool:
    """True when no holiday is declared at all, so a holiday would read as a trading day."""
    return not declared_holidays(path)


def next_trading_day(after: Optional[_dt.date] = None,
                     path: Optional[str] = None) -> _dt.date:
    """The next day the exchange should be open. Skips weekends and known holidays.

    The loops this replaces skipped weekends only, so they would have aimed the bot at a
    holiday and waited overnight for a session that never opened.
    """
    day = (after or _dt.date.today()) + _dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(day, path):
            return day
        day += _dt.timedelta(days=1)
    return day


def observed_trading_days() -> List[_dt.date]:
    """Dates the trade store holds market data for - proof those days were open.

    Never inverted into "no data means holiday": collection here has gaps, and absence of
    a recording is not absence of a session.
    """
    try:
        from research.db import Book
    except Exception:
        return []
    try:
        rows = Book().sessions()
    except Exception:
        return []
    out = []
    for s in rows:
        if s.get("n_ticks") or s.get("n_signals") or s.get("n_trades"):
            day = _parse(s.get("day"))
            if day:
                out.append(day)
    return sorted(out)


def describe(path: Optional[str] = None) -> str:
    path = _path(path)
    known = holidays(path)
    declared = declared_holidays(path)
    # Say plainly when nothing is declared. The inference only ever catches holidays that
    # land on an expiry day, so an empty declared file means most holidays still read as
    # trading days - that is the gap worth reporting, not the total.
    gap = ("" if declared else
           f" — nothing declared in {path}, so holidays away from an expiry still read "
           f"as trading days")
    if not known:
        return f"no holiday calendar ({path} empty or missing); holidays read as trading days"
    upcoming = sorted(d for d in known if d >= _dt.date.today())
    nxt = upcoming[0] if upcoming else None
    return (f"{len(known)} holidays known ({len(declared)} declared in {path}, "
            f"{len(known) - len(declared)} inferred from expiry shifts)"
            + (f"; next {nxt.isoformat()} — {holiday_reason(nxt, path)}" if nxt else "")
            + gap)


# ── populating the declared file from the broker ──────────────────────────────
def fetch_from_broker(start: _dt.date, end: _dt.date) -> List[_dt.date]:
    """Weekdays in the range for which the broker returned no NIFTY spot candle.

    A weekday the exchange did not trade produces no candle, so this is the exchange's own
    answer rather than a list typed from memory. Requires credentials; returns [] if the
    broker cannot be reached, and says so rather than inventing dates.
    """
    from config.constants import NIFTY_SPOT_TOKEN
    from core.trading.broker import BrokerInterface

    broker = BrokerInterface()
    if not broker.connect():
        print("could not connect to the broker; nothing fetched")
        return []

    days = (end - start).days + 1
    candles = broker.get_historical_candles(
        exchange="NSE", token=NIFTY_SPOT_TOKEN, interval="ONE_DAY", days_back=days) or []
    traded = set()
    for row in candles:
        stamp = row[0] if isinstance(row, (list, tuple)) else row.get("timestamp")
        day = _parse(str(stamp)[:10])
        if day:
            traded.add(day)
    if not traded:
        print("the broker returned no candles; nothing can be concluded")
        return []

    # Only trust the span the broker actually covered.
    lo, hi = max(start, min(traded)), min(end, max(traded))
    out, day = [], lo
    while day <= hi:
        if day.weekday() < 5 and day not in traded:
            out.append(day)
        day += _dt.timedelta(days=1)
    return out


def write_declared(days: List[_dt.date], source: str,
                   path: Optional[str] = None) -> str:
    path = _path(path)
    existing = declared_holidays(path)
    for day in days:
        existing.setdefault(day, "no NIFTY candle on a weekday")
    blob = {
        "note": NOTE,
        "source": source,
        "updated": _dt.datetime.now().isoformat(timespec="seconds"),
        "holidays": [{"date": d.isoformat(), "name": existing[d]} for d in sorted(existing)],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, indent=2)
        fh.write("\n")
    return path


def main(argv: List[str]) -> int:
    if argv and argv[0] == "fetch":
        if len(argv) != 3:
            print("usage: python -m utils.trading_calendar fetch YYYY-MM-DD YYYY-MM-DD")
            return 2
        start, end = _parse(argv[1]), _parse(argv[2])
        if not start or not end or end < start:
            print("both dates must be YYYY-MM-DD, and the second not before the first")
            return 2
        found = fetch_from_broker(start, end)
        if not found:
            return 1
        path = write_declared(found, f"broker candles {start}..{end}")
        print(f"wrote {len(found)} holiday(s) into {path}:")
        for d in found:
            print(f"  {d} ({d:%A})")
        return 0

    print(describe())
    obs = observed_trading_days()
    if obs:
        print(f"trade store proves {len(obs)} trading days, {obs[0]} .. {obs[-1]}")
    for day, (src, why) in sorted(holidays().items()):
        print(f"  {day} ({day:%a})  {src:<9} {why}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
