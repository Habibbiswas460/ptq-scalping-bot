"""Maps a parsed Angel One tick (message_parser.py's output) onto the broker-agnostic
canonical shape in brokers/base/tick_schema.py, so a future core/market_data/ consumer
can work off one shape regardless of which broker produced the tick.

Not wired into the live tick path yet — the exchange_type -> exchange string reverse
mapping and the rupee conversion both already happen upstream (message_parser.py divides
paise by 100 during parsing; _get_ws_exchange_type is the forward direction of the map
below). This is available for core/market_data/ to consume once that layer exists;
today's strategies keep reading the raw parsed-tick dict exactly as before.
"""

from typing import Dict, Optional

_EXCHANGE_TYPE_TO_NAME = {
    1: "NSE",
    2: "NFO",
    3: "BSE",
    4: "BFO",
    5: "MCX",
    13: "CDS",
}


def normalize_tick(raw: Dict, symbol: Optional[str] = None, source_broker: str = "angel_one") -> Dict:
    """raw is a message_parser._parse_ws_binary() result. `symbol` is filled in by the
    caller — the wire tick only carries the token, the subscriber knows which symbol it
    subscribed that token under."""
    return {
        "source_broker": source_broker,
        "token": raw.get("token"),
        "exchange": _EXCHANGE_TYPE_TO_NAME.get(raw.get("exchange_type"), None),
        "symbol": symbol,
        "mode": raw.get("mode"),
        "sequence": raw.get("sequence"),
        "timestamp_ms": raw.get("timestamp"),
        "ltp": raw.get("ltp"),
        "volume": raw.get("volume"),
        "open": raw.get("open"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "close": raw.get("close"),
        "oi": raw.get("open_interest"),
        "best_bid_price": raw.get("best_bid_price"),
        "best_ask_price": raw.get("best_ask_price"),
        "best_bid_qty": raw.get("best_bid_qty"),
        "best_ask_qty": raw.get("best_ask_qty"),
    }
