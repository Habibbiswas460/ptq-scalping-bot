"""Derives mid_price/spread/spread_bps/change_pct from a tick. Pure, stateless,
broker-agnostic — adds new keys, never touches the ones already on the tick.

`change_pct` needs a reference price; the caller supplies `prev_close` (whatever "the
previous close" means for that instrument/broker isn't this module's job to know), and
this falls back to the tick's own `close` field when the caller doesn't have one.
"""

from typing import Dict, Optional


def enrich_tick(tick: Dict, prev_close: Optional[float] = None) -> Dict:
    """Returns a NEW dict: `tick` plus whatever of mid_price/spread/spread_bps/change_pct
    can be computed from what it carries. The input dict is left untouched."""
    enriched = dict(tick)

    bid = tick.get("best_bid_price")
    ask = tick.get("best_ask_price")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        enriched["mid_price"] = round(mid, 2)
        enriched["spread"] = round(ask - bid, 2)
        enriched["spread_bps"] = round(((ask - bid) / mid) * 10000, 2) if mid else None

    ltp = tick.get("ltp")
    reference = prev_close if prev_close is not None else tick.get("close")
    if ltp is not None and reference:
        enriched["change_pct"] = round(((ltp - reference) / reference) * 100.0, 4)

    return enriched
