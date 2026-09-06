#!/usr/bin/env python3
"""Standalone runner for the isolated historical data collector.

RUN AS ITS OWN PROCESS — never inside the trading process:

    python utils/run_historical_collector.py --duration-min 60

OPERATIONAL ISOLATION CONTRACT
------------------------------
* Its own authenticated broker session (Angel One permits multiple concurrent
  sessions for the same client code) and its own WebSocket connection.
* It NEVER calls logout()/terminateSession(). Angel One's session teardown is
  account-scoped, so a logout here could invalidate the *trading* session.
  This process therefore only ever logs IN, and lets the session lapse at
  midnight on its own.
* Imports nothing from core.trading / core.engines / core.risk / strategies.
  Token resolution reads the ScripMaster JSON cache directly rather than
  importing the trading broker.
* Any failure terminates only this process. The trading bot is unaffected.

SAFETY NOTE FOR THE FIRST REAL RUN
----------------------------------
Whether a second concurrent login can disturb the trading session is
documented as permitted but has not been verified on this account. The first
real-market validation should therefore be run while the trading bot is NOT
running, and only after that proves clean should the two be run concurrently.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.historical.collector import (  # noqa: E402
    COVERAGE_BAND_POINTS,
    HistoricalCollector,
    build_chain,
    validate_oi_populated,
)
from core.historical.storage import HistoricalStore  # noqa: E402

SCRIPMASTER_CACHE = Path("core/data/scripmaster_nifty_nfo.json")
from config.constants import NIFTY_SPOT_TOKEN  # NSE index token for "Nifty 50"
EXPIRY_RE = re.compile(r"^NIFTY(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)$")


def load_token_map() -> dict:
    if not SCRIPMASTER_CACHE.exists():
        raise SystemExit(f"ScripMaster cache not found at {SCRIPMASTER_CACHE}. "
                         f"Start the trading bot once to populate it, or supply it manually.")
    with open(SCRIPMASTER_CACHE) as f:
        return {str(k): str(v) for k, v in json.load(f).get("token_map", {}).items()}


def nearest_weekly_expiry(token_map: dict, today: datetime) -> str:
    """Nearest non-expired expiry present in the ScripMaster, as 'DDMMMYY'."""
    expiries = set()
    for symbol in token_map:
        m = EXPIRY_RE.match(symbol)
        if m:
            expiries.add(m.group(1))

    dated = []
    for token in expiries:
        try:
            dt = datetime.strptime(token, "%d%b%y")
        except ValueError:
            continue
        if dt.date() >= today.date():
            dated.append((dt, token))
    if not dated:
        raise SystemExit("No non-expired NIFTY expiries found in ScripMaster cache.")
    dated.sort()
    return dated[0][1]


def expiry_token_to_iso(expiry_token: str) -> str:
    return datetime.strptime(expiry_token, "%d%b%y").strftime("%Y-%m-%d")


def login() -> dict:
    """Independent authenticated session. Returns the auth material the
    collector's WebSocket needs. Never logs out."""
    from dotenv import load_dotenv
    load_dotenv()

    import pyotp
    from SmartApi import SmartConnect

    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")
    if not all([api_key, client_id, password, totp_secret]):
        raise SystemExit("Missing ANGEL_* credentials in environment/.env")

    smart = SmartConnect(api_key=api_key)
    data = smart.generateSession(client_id, password, pyotp.TOTP(totp_secret).now())
    if not (data and data.get("status")):
        raise SystemExit(f"Login failed: {data.get('message') if data else 'no response'}")

    return {
        "auth_token": data["data"]["jwtToken"],
        "api_key": api_key,
        "client_id": client_id,
        "feed_token": smart.getfeedToken(),
        "_smart": smart,
    }


def resolve_spot(auth: dict) -> float:
    """Current NIFTY spot, used only to centre the strike band."""
    smart = auth["_smart"]
    resp = smart.ltpData("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
    if resp and resp.get("status") and resp.get("data"):
        return float(resp["data"]["ltp"])
    raise SystemExit("Could not resolve NIFTY spot price for chain centring.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration-min", type=float, default=0,
                        help="Stop after N minutes (0 = run until interrupted)")
    parser.add_argument("--store-dir", default=None, help="Override canonical store directory")
    parser.add_argument("--band-points", type=int, default=COVERAGE_BAND_POINTS)
    parser.add_argument("--status-every-sec", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve chain/tokens and print the plan, without connecting")
    args = parser.parse_args()

    token_map = load_token_map()
    expiry_token = nearest_weekly_expiry(token_map, datetime.now())
    expiry_iso = expiry_token_to_iso(expiry_token)
    print(f"ScripMaster tokens : {len(token_map)}")
    print(f"Nearest expiry     : {expiry_token} ({expiry_iso})")

    if args.dry_run:
        # Chain centred on a nominal spot so the plan can be inspected offline.
        chain = build_chain(24000.0, expiry_iso, band_points=args.band_points)
        resolved = sum(1 for c in chain if token_map.get(c["symbol"]))
        print(f"Chain (nominal ATM): {len(chain)} contracts, {resolved} resolvable in ScripMaster")
        for c in chain:
            print(f"   {c['symbol']:28s} token={token_map.get(c['symbol'], 'MISSING')}")
        print("\nDRY RUN — no login, no connection made.")
        return 0

    auth = login()
    print("Login              : OK (independent session; will NOT log out)")

    spot = resolve_spot(auth)
    print(f"NIFTY spot         : {spot}")

    chain = build_chain(spot, expiry_iso, band_points=args.band_points)
    store = HistoricalStore(store_dir=args.store_dir) if args.store_dir else HistoricalStore()
    collector = HistoricalCollector(store=store, auth=auth)
    subscribed = collector.configure(chain, lambda s: token_map.get(s), spot_token=NIFTY_SPOT_TOKEN)

    missing = [c["symbol"] for c in chain if not token_map.get(c["symbol"])]
    print(f"Subscribing        : {subscribed} tokens (band ATM+/-{args.band_points})")
    if missing:
        print(f"  WARNING unresolved: {missing}")

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        print(f"\nSignal {signum} received — flushing and stopping.")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    collector.start()
    started = time.time()
    last_status = 0.0
    deadline = started + args.duration_min * 60 if args.duration_min else None

    try:
        while not stop["flag"]:
            time.sleep(1.0)
            now = time.time()
            if now - last_status >= args.status_every_sec:
                last_status = now
                s = collector.stats
                print(f"[{datetime.now():%H:%M:%S}] ticks={s['ticks']} rows={s['rows']} "
                      f"flushes={s['flushes']} bid_ask_null={s['bid_ask_null']} "
                      f"oi_null={s['oi_null']} parse_failures={s['parse_failures']}")
            if deadline and now >= deadline:
                print("Duration reached — stopping.")
                break
    finally:
        collector.stop()

    print("\n=== SESSION SUMMARY ===")
    print(f"stats: {collector.stats}")
    today = datetime.now().strftime("%Y-%m-%d")
    rows = list(store.query_range(today, today))
    print(f"rows persisted today: {len(rows)}")
    if rows:
        print(f"OI validation      : {validate_oi_populated(rows)}")
        print("\nRun the gate with:")
        print(f"  python utils/phase1_data_audit.py --store --start {today} --end {today}")
    print("\nNOTE: this process never logged out; the broker session lapses at midnight.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
