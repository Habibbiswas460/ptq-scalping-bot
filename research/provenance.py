"""Provenance states and the field registry every chart reads.

The rule this exists to enforce: no visual may present an estimated or reconstructed value
with the same weight as a measured one. Charts ask this module what a field is; they never
hard-code the answer, so when a field's status changes every chart updates at once.

**A field-level answer stopped being sufficient on 2026-09-07.** The mode-3 SnapQuote
subscription was switched on at 13:28:53, mid-session, so that day's ticks carry a real book
and real open interest from that moment and the fabricated estimate before it. For `bid`,
`ask`, `spread` and `oi` the honest answer is now per ROW, not per field, and it is
`research.depth.quote_origin()` that gives it. The registry entries below say so rather than
asserting one state over data that holds two.
"""
from __future__ import annotations

REAL = "real"
RECONSTRUCTED = "reconstructed"
ESTIMATED = "estimated"
MISSING = "missing"
LIVE_ONLY = "live-only"
# One field, two truths in the same table: some rows measured, others fabricated. A chart must
# split on research.depth.quote_origin() rather than paint the whole series one colour.
MIXED = "mixed"

LABEL = {
    REAL: "REAL",
    RECONSTRUCTED: "RECONSTRUCTED",
    ESTIMATED: "ESTIMATED",
    MISSING: "MISSING",
    LIVE_ONLY: "LIVE-ONLY",
    MIXED: "MIXED (per row)",
}

# field -> (state, one-line reason shown next to any chart that uses it)
REGISTRY = {
    "spot":        (REAL, "WebSocket spot ticks; unchanged tick-to-tick only 3.5-3.7%"),
    "option_ltp":  (REAL, "WebSocket option ticks, one row per price change"),
    "volume":      (REAL, "cumulative from the feed; differenced for per-interval use"),
    # MIXED as of 2026-09-07 — ask research.depth.quote_origin() per row, never assume.
    "bid":         (MIXED, "real book on 33.4% of 2026-09-07 rows (from 13:28:53), fabricated before that and on every earlier session"),
    "ask":         (MIXED, "same packet as bid; see research.depth.quote_origin()"),
    "spread":      (MIXED, "real p50 0.25 pts where the book is real; the fabricated rows carry no market information and must not be pooled with them"),
    "quote_source": (MISSING, "counted in logs, never written to the ticks table — research.depth derives the origin from the values instead"),
    "oi":          (MIXED, "8,516 of 25,263 rows on 2026-09-07, the first ever; NULL or 0 on every earlier session"),
    # Still MISSING, and deliberately so: this entry describes the COLUMN the strategy
    # persisted, which is constant on every session downstream of the absent oi. That
    # research.depth.oi_profile() can now recompute the label from 2026-09-07's real OI is a
    # separate, reconstructed series — conflating the two would let a chart draw a constant
    # column as though it carried information.
    "oi_direction": (MISSING, "constant on every persisted session, downstream of the missing oi; research.depth.oi_profile() reconstructs it separately where real OI exists"),
    "delta":       (RECONSTRUCTED, "Black-Scholes solved from LTP in indicators_snapshot, not broker-quoted"),
    "greeks":      (RECONSTRUCTED, "same solver; present per-trade, absent per-tick"),
    "atr":         (MISSING, "never populated on any tick; the early-cut branch always took its low path"),
    "rsi_entry":   (REAL, "RSI(14) on spot candles, thousands of distinct values per session"),
    "rsi_exit":    (RECONSTRUCTED, "RSI(14) over 15 option ticks; replay is smoother than live (25,055 of 42,965 ticks persisted)"),
    "vwap":        (REAL, "from the strategy's spot candle series"),
    "ema9":        (REAL, "from the strategy's spot candle series"),
    "ema21":       (REAL, "from the strategy's spot candle series"),
    "macd_hist":   (REAL, "from the strategy's spot candle series"),
    "regime":      (MISSING, "constant on all six sessions; no discriminative power"),
    "score":       (REAL, "recorded faithfully - of a stack whose inputs were largely constant"),
    "confidence":  (REAL, "recorded faithfully; two distinct pairs per session"),
    "mfe_stored":  (REAL, "real but EXIT-CENSORED - never use as 'movement available'"),
    "timestamps":  (ESTIMATED, "second resolution; 18.6-21.4% same-second collisions"),
    "costs":       (MISSING, "no brokerage/STT/slippage field exists; all P&L is gross"),
}


def state(field: str) -> str:
    return REGISTRY.get(field, (MISSING, ""))[0]


def reason(field: str) -> str:
    return REGISTRY.get(field, (MISSING, "field not in the provenance registry"))[1]


def chip(field: str) -> tuple:
    """(label, state) for rendering."""
    s = state(field)
    return LABEL[s], s
