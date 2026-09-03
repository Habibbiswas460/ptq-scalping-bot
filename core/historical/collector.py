"""Isolated historical data collector.

Purpose: accumulate spec-compliant historical option data (real bid/ask, real
OI, millisecond timestamps, ATM+/-200 CE/PE chain plus spot) going forward
from the live feed, because no vendor sells this at retail (see the Phase-2
acquisition research).

ISOLATION CONTRACT — this module deliberately imports NOTHING from the
trading path (no state_machine, entry_engine, exit_engine, risk, strategies).
It runs on its own WebSocket connection (Angel One permits 3 concurrent
connections per account; the trading bot uses one) and writes only to the
canonical historical store. It cannot influence live entries, exits, filters,
risk controls, or strategy behaviour, by construction.

WHY ITS OWN BINARY PARSER: brokers/angel_one/client.py's `_parse_ws_binary`
skips the best-5 depth block entirely (it jumps from open_interest at byte
139 straight to upper_circuit at 347), which is the root cause of
`best_bid_price` never being populated and the trading path silently
substituting a synthetic `ltp +/- (ltp*0.003)/2` spread on every tick.
Fixing that shared parser would change what the live spread filters see,
i.e. change trading behaviour — explicitly out of scope. So this module
parses independently and leaves the trading path untouched.

FAIL-CLOSED PRINCIPLE: every field here is either genuinely present in the
exchange payload or recorded as NULL. Nothing is estimated, defaulted, or
back-filled. A NULL that fails the quality gate is the correct outcome; a
fabricated value that passes it is not.
"""

from __future__ import annotations

import json
import struct
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from core.historical.schema import build_option_symbol
from core.historical.storage import HistoricalStore

# Angel One WebSocket 2.0 binary layout (verified against the official
# angel-one/smartapi-python SmartApi/smartWebSocketV2.py implementation).
WS_MODE_LTP = 1
WS_MODE_QUOTE = 2
WS_MODE_SNAP_QUOTE = 3

_BEST5_START = 147
_BEST5_END = 347
_BEST5_PACKET_LEN = 20
_SNAP_QUOTE_MIN_LEN = 379

IST = timezone(timedelta(hours=5, minutes=30))

# Chain geometry
STRIKE_STEP = 50
COVERAGE_BAND_POINTS = 200

# A spot reference older than this is treated as unusable rather than stale-stamped.
SPOT_REF_MAX_AGE_SEC = 1.0


# ---------------------------------------------------------------------------
# Pure parsing helpers (no I/O, no broker, no trading state — unit-testable
# offline, which matters because these can only be exercised against a live
# feed during market hours).
# ---------------------------------------------------------------------------

def epoch_ms_to_ist_string(epoch_ms: int) -> str:
    """Exchange timestamp (epoch milliseconds, UTC-based) -> IST string with
    millisecond precision preserved.

    Millisecond precision comes from the exchange payload itself; it is not
    invented. If the feed ever supplies second-granularity values the
    sub-second component will simply be .000, which is honest.
    """
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone(IST)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def parse_best_5(block: bytes) -> List[Dict]:
    """Split the best-5 depth block into its 20-byte packets.

    Packet layout (little-endian): flag uint16 | quantity int64 |
    price int64 (paise) | orders uint16.
    """
    packets = []
    for offset in range(0, min(len(block), _BEST5_END - _BEST5_START), _BEST5_PACKET_LEN):
        chunk = block[offset:offset + _BEST5_PACKET_LEN]
        if len(chunk) < _BEST5_PACKET_LEN:
            break
        flag = struct.unpack("<H", chunk[0:2])[0]
        quantity = struct.unpack("<q", chunk[2:10])[0]
        price = struct.unpack("<q", chunk[10:18])[0] / 100.0
        orders = struct.unpack("<H", chunk[18:20])[0]
        packets.append({"flag": flag, "quantity": quantity, "price": price, "orders": orders})
    return packets


def derive_bid_ask(packets: Sequence[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """Derive best bid / best ask from the best-5 packets.

    Deliberately does NOT trust the buy/sell flag semantics: the official
    Angel One python client itself swaps the two labels when exposing them
    (`best_5_buy_data` is assigned from `best_5_sell_data`), so the flag's
    meaning is ambiguous in practice. Instead the two flag-groups are
    partitioned by price ordering, which is self-validating: in any sane
    order book every bid is strictly below every ask.

    Returns (None, None) — never a guess — when the book is empty, one-sided,
    or crossed/overlapping, so the caller records NULL rather than fabricating.
    """
    live = [p for p in packets if p["price"] > 0 and p["quantity"] > 0]
    if not live:
        return None, None

    group_a = [p["price"] for p in live if p["flag"] == 0]
    group_b = [p["price"] for p in live if p["flag"] != 0]
    if not group_a or not group_b:
        return None, None  # one-sided book: cannot establish a spread

    if max(group_a) < min(group_b):
        return round(max(group_a), 2), round(min(group_b), 2)
    if max(group_b) < min(group_a):
        return round(max(group_b), 2), round(min(group_a), 2)

    # Crossed or overlapping book — ambiguous. Fail closed.
    return None, None


def parse_snapquote(data: bytes) -> Optional[Dict]:
    """Parse an Angel One WebSocket 2.0 binary tick.

    Returns None for malformed/short payloads. Fields absent from the
    subscribed mode are left absent (never defaulted to 0), so callers can
    distinguish 'not provided by the feed' from 'genuinely zero'.
    """
    if len(data) < 51:
        return None
    try:
        mode = data[0]
        token = data[2:27].decode("utf-8", errors="ignore").rstrip("\x00")
        out: Dict = {
            "mode": mode,
            "token": token,
            "exchange_timestamp": struct.unpack("<q", data[35:43])[0],
            "ltp": struct.unpack("<q", data[43:51])[0] / 100.0,
        }

        if mode >= WS_MODE_QUOTE and len(data) >= 123:
            out["volume"] = struct.unpack("<q", data[67:75])[0]

        if mode >= WS_MODE_SNAP_QUOTE and len(data) >= _SNAP_QUOTE_MIN_LEN:
            # Open interest is only present in SnapQuote. Recorded exactly as
            # the exchange sent it; never defaulted when the mode lacks it.
            out["oi"] = struct.unpack("<q", data[131:139])[0]
            bid, ask = derive_bid_ask(parse_best_5(data[_BEST5_START:_BEST5_END]))
            out["bid"] = bid
            out["ask"] = ask

        return out
    except Exception:
        return None


def build_chain(spot_price: float, expiry_iso: str,
                band_points: int = COVERAGE_BAND_POINTS,
                strike_step: int = STRIKE_STEP) -> List[Dict]:
    """The ATM+/-band CE/PE chain to collect, as canonical descriptors.

    ATM is rounded to the nearest strike step, matching the convention in
    core/trading/broker.py's `_find_strike_by_premium`.
    """
    atm = round(spot_price / strike_step) * strike_step
    chain = []
    for strike in range(atm - band_points, atm + band_points + 1, strike_step):
        for itype in ("CE", "PE"):
            symbol = build_option_symbol(expiry_iso, strike, itype)
            if symbol is None:
                continue
            chain.append({"symbol": symbol, "strike": strike,
                          "instrument_type": itype, "expiry": expiry_iso})
    return chain


def to_canonical_row(parsed: Dict, symbol: str, instrument_type: str,
                     expiry: Optional[str], strike: Optional[int],
                     spot_ref: Optional[float]) -> Dict:
    """Map a parsed tick into a canonical historical row.

    Absent feed fields stay None. Greeks/IV are not published on this feed and
    are therefore always None here rather than computed — a computed Greek is
    a model output, not observed market data, and must not masquerade as one
    in a dataset used to validate strategy behaviour.
    """
    return {
        "timestamp": epoch_ms_to_ist_string(parsed["exchange_timestamp"]),
        "instrument_type": instrument_type,
        "symbol": symbol,
        "expiry": expiry,
        "strike": strike,
        "ltp": round(parsed["ltp"], 2),
        "bid": parsed.get("bid"),
        "ask": parsed.get("ask"),
        "volume": parsed.get("volume"),
        "oi": parsed.get("oi"),
        "delta": None, "gamma": None, "theta": None, "vega": None, "iv": None,
        "spot_ref": spot_ref,
    }


def validate_oi_populated(rows: Sequence[Dict], min_fraction: float = 0.99) -> Dict:
    """Prove OI is genuinely populated rather than silently defaulted.

    Distinguishes three cases explicitly: missing (None), all-zero (the
    signature of a default rather than a real value), and real. A chain of
    liquid options cannot legitimately have zero open interest across the
    board, so an all-zero result is reported as suspect, not as success.
    """
    option_rows = [r for r in rows if r.get("instrument_type") in ("CE", "PE")]
    if not option_rows:
        return {"ok": False, "reason": "no option rows", "checked": 0}

    present = [r for r in option_rows if r.get("oi") is not None]
    nonzero = [r for r in present if r["oi"] > 0]
    fraction_present = len(present) / len(option_rows)
    fraction_nonzero = (len(nonzero) / len(present)) if present else 0.0

    ok = fraction_present >= min_fraction and fraction_nonzero > 0.0
    reason = "ok"
    if fraction_present < min_fraction:
        reason = f"only {fraction_present * 100:.1f}% of option rows carry OI"
    elif fraction_nonzero == 0.0:
        reason = "every OI value is exactly 0 — indicates a default, not real data"

    return {
        "ok": ok, "reason": reason, "checked": len(option_rows),
        "present": len(present), "nonzero": len(nonzero),
        "fraction_present": round(fraction_present, 4),
        "fraction_nonzero": round(fraction_nonzero, 4),
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class HistoricalCollector:
    """Runs an isolated WebSocket collection session.

    The trading connection is untouched: this opens its own socket using the
    same account's auth material and subscribes its own token set in
    SNAP_QUOTE mode.
    """

    def __init__(self, store: HistoricalStore, auth: Dict,
                 flush_interval_sec: float = 5.0, max_buffer: int = 2000,
                 websocket_url: str = "wss://smartapisocket.angelone.in/smart-stream"):
        self.store = store
        self.auth = auth  # {auth_token, api_key, client_id, feed_token}
        self.flush_interval_sec = flush_interval_sec
        self.max_buffer = max_buffer
        self.websocket_url = websocket_url

        self._token_map: Dict[str, Dict] = {}   # token -> descriptor
        self._spot_token: Optional[str] = None
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()
        self._ws = None
        self._running = False
        self._last_flush = time.time()

        self._last_spot_price: Optional[float] = None
        self._last_spot_epoch_ms: Optional[int] = None

        self.stats = {"ticks": 0, "rows": 0, "flushes": 0,
                      "bid_ask_null": 0, "oi_null": 0, "parse_failures": 0}

    # -- subscription set ---------------------------------------------------

    def configure(self, chain: Sequence[Dict], token_lookup, spot_token: str,
                  spot_symbol: str = "NIFTY") -> int:
        """Register the chain + spot token. `token_lookup(symbol)` resolves a
        tradable symbol to its exchange token."""
        self._token_map.clear()
        for entry in chain:
            token = token_lookup(entry["symbol"])
            if not token:
                continue
            self._token_map[str(token)] = dict(entry)
        self._spot_token = str(spot_token)
        self._token_map[self._spot_token] = {
            "symbol": spot_symbol, "instrument_type": "SPOT",
            "expiry": None, "strike": None,
        }
        return len(self._token_map)

    def subscribe_message(self, exchange_type_option: int = 2,
                          exchange_type_spot: int = 1) -> Dict:
        """Build the SNAP_QUOTE subscribe payload for the registered tokens."""
        option_tokens = [t for t, d in self._token_map.items()
                         if d["instrument_type"] in ("CE", "PE")]
        spot_tokens = [t for t, d in self._token_map.items()
                       if d["instrument_type"] == "SPOT"]
        token_list = []
        if option_tokens:
            token_list.append({"exchangeType": exchange_type_option, "tokens": option_tokens})
        if spot_tokens:
            token_list.append({"exchangeType": exchange_type_spot, "tokens": spot_tokens})
        return {
            "correlationID": f"histcollect_{int(time.time() * 1000)}",
            "action": 1,
            "params": {"mode": WS_MODE_SNAP_QUOTE, "tokenList": token_list},
        }

    # -- tick handling ------------------------------------------------------

    def handle_binary(self, data: bytes) -> Optional[Dict]:
        """Parse one binary frame into a canonical row and buffer it.

        Returns the row (for testing/inspection) or None if the frame was
        unusable or for an untracked token.
        """
        parsed = parse_snapquote(data)
        if parsed is None:
            self.stats["parse_failures"] += 1
            return None

        descriptor = self._token_map.get(parsed["token"])
        if descriptor is None:
            return None

        self.stats["ticks"] += 1

        if descriptor["instrument_type"] == "SPOT":
            # Spot is persisted as its OWN canonical row (instrument_type
            # SPOT), not merely denormalised onto option rows — otherwise the
            # gate's spot/option alignment check has nothing real to verify
            # against and passes vacuously.
            self._last_spot_price = round(parsed["ltp"], 2)
            self._last_spot_epoch_ms = parsed["exchange_timestamp"]
            row = to_canonical_row(parsed, descriptor["symbol"], "SPOT",
                                   None, None, spot_ref=round(parsed["ltp"], 2))
        else:
            spot_ref = self._current_spot_ref(parsed["exchange_timestamp"])
            row = to_canonical_row(parsed, descriptor["symbol"],
                                   descriptor["instrument_type"],
                                   descriptor["expiry"], descriptor["strike"],
                                   spot_ref=spot_ref)
            if row["bid"] is None or row["ask"] is None:
                self.stats["bid_ask_null"] += 1
            if row["oi"] is None:
                self.stats["oi_null"] += 1

        with self._lock:
            self._buffer.append(row)
            self.stats["rows"] += 1
            should_flush = (len(self._buffer) >= self.max_buffer or
                            time.time() - self._last_flush >= self.flush_interval_sec)
        if should_flush:
            self.flush()
        return row

    def _current_spot_ref(self, option_epoch_ms: int) -> Optional[float]:
        """Latest spot price, but only if fresh enough to be a truthful
        reference for this option tick. A stale spot is recorded as NULL
        rather than stamped forward."""
        if self._last_spot_price is None or self._last_spot_epoch_ms is None:
            return None
        age_sec = abs(option_epoch_ms - self._last_spot_epoch_ms) / 1000.0
        if age_sec > SPOT_REF_MAX_AGE_SEC:
            return None
        return self._last_spot_price

    def flush(self) -> int:
        with self._lock:
            pending, self._buffer = self._buffer, []
            self._last_flush = time.time()
        if not pending:
            return 0
        try:
            self.store.write_rows(pending)
            self.stats["flushes"] += 1
            return len(pending)
        except Exception:
            # Never raise into the feed thread. Collection is analytics-only.
            return 0

    # -- connection ---------------------------------------------------------

    def start(self) -> None:
        """Open the isolated WebSocket connection and begin collecting."""
        import websocket  # imported lazily so unit tests need no network stack

        headers = {
            "Authorization": f"Bearer {self.auth['auth_token']}",
            "x-api-key": self.auth["api_key"],
            "x-client-code": self.auth["client_id"],
            "x-feed-token": self.auth["feed_token"],
        }

        def on_open(ws):
            ws.send(json.dumps(self.subscribe_message()))

        def on_message(ws, message):
            if isinstance(message, bytes):
                self.handle_binary(message)

        def on_error(ws, error):  # pragma: no cover - network path
            pass

        def on_close(ws, *_):  # pragma: no cover - network path
            self.flush()

        self._ws = websocket.WebSocketApp(
            self.websocket_url, header=headers, on_open=on_open,
            on_message=on_message, on_error=on_error, on_close=on_close,
        )
        self._running = True
        threading.Thread(
            target=lambda: self._ws.run_forever(ping_interval=25, ping_timeout=10),
            daemon=True, name="historical-collector",
        ).start()

    def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self.flush()
