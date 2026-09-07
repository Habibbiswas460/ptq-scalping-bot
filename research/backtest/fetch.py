"""Import 1-minute candles into data/historical/candles.db.

    ./venv/bin/python -m research.backtest.fetch index   --from 2024-01-01 --to 2026-09-04
    ./venv/bin/python -m research.backtest.fetch options --expiry 08SEP26 --band 400
    ./venv/bin/python -m research.backtest.fetch crosscheck --days 5
    ./venv/bin/python -m research.backtest.fetch status

`index` and `options` use Angel One SmartAPI (credentials from config.constants,
never printed). `crosscheck` re-fetches a small overlapping sample from the two
free public sources and reports how far they disagree — the point being that a
single vendor agreeing with itself is not evidence.

Nothing here places an order or writes to the trading database.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from typing import Dict, List, Optional

from research.backtest import store
from research.backtest.broker_source import (
    AngelHistorical, INDEX_EXCHANGE, OPTION_EXCHANGE, BrokerSourceError,
    atm_band, credential_status, nifty_option_contracts,
)

ANGEL = "angelone_smartapi"
INDEX_SYMBOL = "NIFTY50"


def _index_key() -> str:
    from config.constants import NIFTY_SPOT_TOKEN
    return f"{INDEX_EXCHANGE}:{NIFTY_SPOT_TOKEN}"


def _index_token() -> str:
    from config.constants import NIFTY_SPOT_TOKEN
    return str(NIFTY_SPOT_TOKEN)


def _progress(i, n, a, b, rows, err):
    tail = f" ERROR {err}" if err else ""
    print(f"  [{i}/{n}] {a}..{b}  rows={rows}{tail}", flush=True)


def cmd_index(args) -> int:
    frm = _dt.date.fromisoformat(args.frm)
    to = _dt.date.fromisoformat(args.to)
    con = store.connect()
    api = AngelHistorical()
    key, token = _index_key(), _index_token()
    print(f"NIFTY 50 index 1-minute  {frm}..{to}  via {ANGEL}")
    bars, receipts = api.range(token, INDEX_EXCHANGE, frm, to, on_chunk=_progress)
    run_ids = [store.record_run(con, r, INDEX_SYMBOL) for r in receipts]
    store.write_instruments(con, [{
        "instrument_key": key, "symbol": INDEX_SYMBOL, "kind": "INDEX",
        "strike": None, "expiry": None, "lot_size": None, "tick_size": None,
    }], ANGEL)
    n = store.write_candles(con, key, INDEX_SYMBOL, "1m", bars, ANGEL,
                            run_ids[-1] if run_ids else None)
    days = store.sessions(con, key, ANGEL)
    gaps = store.detect_gaps(con, key, "1m", ANGEL)
    clamped = sum(1 for r in receipts if r.get("clamped"))
    failed = [r for r in receipts if r.get("error")]
    print(f"\nwrote {n} bars over {len(days)} sessions "
          f"({days[0]}..{days[-1]})" if days else "\nwrote nothing")
    print(f"chunks={len(receipts)} clamped={clamped} failed={len(failed)}")
    print(f"sessions with missing minutes: {len(gaps)} (recorded in `gaps`, not filled)")
    for g in gaps[:10]:
        print(f"   {g['session_date']}: {g['actual']}/375 bars, {g['missing']} missing")
    return 0


def _parse_expiry(tag: str) -> _dt.date:
    return _dt.datetime.strptime(tag, "%d%b%y").date()


def cmd_options(args) -> int:
    con = store.connect()
    contracts = nifty_option_contracts()
    if not contracts:
        print("no NIFTY contracts in the ScripMaster cache", file=sys.stderr)
        return 1
    expiries = sorted({c["expiry"] for c in contracts})
    if args.expiry:
        want = [_parse_expiry(args.expiry)]
    else:
        want = expiries[: args.expiries]
    print("expiries in the ScripMaster (unexpired only — expired weeklies are unreachable):")
    print("   " + ", ".join(e.isoformat() for e in expiries))

    api = AngelHistorical()
    key, token = _index_key(), _index_token()
    # Centre the strike band on the index range actually observed over the window,
    # read back from what was already imported. No spot data -> no band, rather
    # than a guessed centre.
    frm = _dt.date.fromisoformat(args.frm) if args.frm else None
    to = _dt.date.fromisoformat(args.to) if args.to else None
    spot = store.load_candles(con, key, ANGEL, "1m",
                              frm=frm.isoformat() if frm else None,
                              to=to.isoformat() if to else None)
    if not spot:
        print("no index candles imported yet — run `fetch index` first", file=sys.stderr)
        return 1
    lo = min(b["low"] for b in spot)
    hi = max(b["high"] for b in spot)
    print(f"index range over the window: {lo:.1f}..{hi:.1f}  -> strike band "
          f"{lo - args.band:.0f}..{hi + args.band:.0f}")

    total = 0
    for expiry in want:
        band = atm_band(contracts, expiry, lo - args.band, hi + args.band)
        print(f"\nexpiry {expiry}: {len(band)} contracts in band")
        for c in band:
            ikey = f"{OPTION_EXCHANGE}:{c['token']}"
            # Contracts are listed a few weeks out; asking wider than that is
            # harmless (it returns what exists) but pointless, so the caller's
            # window is used as-is and the true listing date is whatever comes back.
            a = frm or (expiry - _dt.timedelta(days=45))
            b = to or expiry
            bars, receipts = api.range(c["token"], OPTION_EXCHANGE, a, b)
            run_ids = [store.record_run(con, r, c["symbol"]) for r in receipts]
            if not bars:
                print(f"   {c['symbol']:<26} no data (not listed in this window)")
                continue
            store.write_instruments(con, [{
                "instrument_key": ikey, "symbol": c["symbol"],
                "kind": c["instrument_type"], "strike": c["strike"],
                "expiry": expiry.isoformat(), "lot_size": c["lot_size"],
                "tick_size": c["tick_size"],
            }], ANGEL)
            n = store.write_candles(con, ikey, c["symbol"], "1m", bars, ANGEL,
                                    run_ids[-1] if run_ids else None)
            store.detect_gaps(con, ikey, "1m", ANGEL)
            days = store.sessions(con, ikey, ANGEL)
            total += n
            print(f"   {c['symbol']:<26} {n:>6} bars  {days[0]}..{days[-1]} ({len(days)} sessions)")
    print(f"\ntotal option bars written: {total}")
    return 0


def cmd_crosscheck(args) -> int:
    """Do two independent vendors see the same NIFTY minutes as the broker?

    This is the only thing the free sources are used for. Disagreement here would
    invalidate everything downstream, so it is checked rather than assumed.
    """
    from research.backtest import sources
    con = store.connect()
    key = _index_key()
    days = store.sessions(con, key, ANGEL)
    if not days:
        print("no broker index data to check against", file=sys.stderr)
        return 1
    sample = days[-args.days:]
    frm, to = _dt.date.fromisoformat(sample[0]), _dt.date.fromisoformat(sample[-1])
    print(f"cross-checking {frm}..{to} ({len(sample)} sessions)")

    broker = {b["epoch"]: b["close"] for b in store.load_candles(
        con, key, ANGEL, "1m", frm=sample[0], to=sample[-1])}
    print(f"  broker(angelone): {len(broker)} bars")

    for name, fetch in (
        ("upstox", lambda: sources.upstox_candles(sources.NIFTY_INDEX_KEY, frm, to)),
        ("yahoo", lambda: sources.yahoo_candles(frm, to)),
    ):
        try:
            bars, url = fetch()
        except sources.SourceError as e:
            print(f"  {name}: UNAVAILABLE — {e}")
            continue
        store.record_run(con, {
            "source": name, "endpoint_url": url, "instrument_key": key,
            "interval": "1m", "requested_from": frm.isoformat(),
            "requested_to": to.isoformat(),
            "returned_from": bars[0]["ts"].date().isoformat() if bars else None,
            "returned_to": bars[-1]["ts"].date().isoformat() if bars else None,
            "rows_returned": len(bars),
            "fetched_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "error": None, "clamped": False,
        }, INDEX_SYMBOL)
        store.write_candles(con, key, INDEX_SYMBOL, "1m", bars, name)
        common = [(broker[b["epoch"]], b["close"]) for b in bars if b["epoch"] in broker]
        if not common:
            print(f"  {name}: {len(bars)} bars, NO overlapping minutes with the broker")
            continue
        diffs = [abs(a - c) for a, c in common]
        exact = sum(1 for d in diffs if d < 1e-9)
        print(f"  {name}: {len(bars)} bars, {len(common)} shared minutes | "
              f"identical close {100.0 * exact / len(common):.1f}% | "
              f"max |diff| {max(diffs):.2f} | mean |diff| {sum(diffs) / len(diffs):.4f}")
    return 0


def cmd_status(args) -> int:
    con = store.connect()
    print("credentials (names and presence only):")
    for k, ok in credential_status().items():
        print(f"   {k}: {ok}")
    print("\ninstruments:")
    for r in con.execute("""SELECT kind, count(*) n FROM instruments GROUP BY kind"""):
        print(f"   {r['kind']}: {r['n']}")
    print("\ncandles by source:")
    for r in con.execute(
            """SELECT source, interval, count(*) n, count(DISTINCT instrument_key) k,
                      count(DISTINCT session_date) d, min(session_date) a, max(session_date) b
               FROM candles GROUP BY source, interval ORDER BY n DESC"""):
        print(f"   {r['source']:<20} {r['interval']}  bars={r['n']:>8}  instruments={r['k']:>4}  "
              f"sessions={r['d']:>4}  {r['a']}..{r['b']}")
    print("\nfetch runs:")
    for r in con.execute(
            """SELECT source, count(*) n, sum(clamped) c,
                      sum(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) e
               FROM fetch_runs GROUP BY source"""):
        print(f"   {r['source']:<20} requests={r['n']:>4} clamped={r['c'] or 0} failed={r['e'] or 0}")
    g = con.execute("SELECT count(*) n, sum(expected_bars - actual_bars) m FROM gaps").fetchone()
    print(f"\ngaps: {g['n'] or 0} instrument-sessions with missing minutes, "
          f"{g['m'] or 0} minutes absent (recorded, never filled)")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="research.backtest.fetch", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="NIFTY 50 1-minute spot from Angel One")
    pi.add_argument("--from", dest="frm", required=True)
    pi.add_argument("--to", dest="to", required=True)
    pi.set_defaults(fn=cmd_index)

    po = sub.add_parser("options", help="NIFTY option 1-minute from Angel One")
    po.add_argument("--expiry", help="e.g. 08SEP26; default = the nearest N expiries")
    po.add_argument("--expiries", type=int, default=1)
    po.add_argument("--band", type=float, default=300.0,
                    help="strikes this far beyond the observed index range")
    po.add_argument("--from", dest="frm")
    po.add_argument("--to", dest="to")
    po.set_defaults(fn=cmd_options)

    pc = sub.add_parser("crosscheck", help="independent vendors vs the broker feed")
    pc.add_argument("--days", type=int, default=5)
    pc.set_defaults(fn=cmd_crosscheck)

    ps = sub.add_parser("status", help="what is in the database")
    ps.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except BrokerSourceError as e:
        print(f"broker source error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
