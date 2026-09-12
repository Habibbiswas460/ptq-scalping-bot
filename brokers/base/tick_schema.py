"""Canonical tick shape, broker-agnostic.

core/market_data/ (validator, router, cache, enricher, aggregator, store) is meant to work
off this shape regardless of which broker produced the tick. brokers/angel_one/normalizer.py
is the first producer of it. This is descriptive documentation of the field contract, not a
runtime-enforced schema — keep it in sync with whatever normalizer.py actually emits.
"""

# name -> type. `symbol` and `exchange` are filled in by whoever owns the subscription
# (the wire tick itself only carries the token), not by the parser/normalizer.
CANONICAL_TICK_FIELDS = {
    "source_broker": str,      # e.g. "angel_one"
    "token": str,
    "exchange": str,
    "symbol": str,
    "mode": int,               # 1=LTP, 2=Quote, 3=SnapQuote
    "sequence": int,
    "timestamp_ms": int,
    "ltp": float,
    "volume": int,
    "open": float,
    "high": float,
    "low": float,
    "close": float,
    "oi": int,
    "best_bid_price": float,
    "best_ask_price": float,
    "best_bid_qty": int,
    "best_ask_qty": int,
}
