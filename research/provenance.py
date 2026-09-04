"""Provenance states and the field registry every chart reads.

The rule this exists to enforce: no visual may present an estimated or reconstructed value
with the same weight as a measured one. Charts ask this module what a field is; they never
hard-code the answer, so when a field's status changes (OI arriving live, a real spread from
the collector) every chart updates at once.
"""
from __future__ import annotations

REAL = "real"
RECONSTRUCTED = "reconstructed"
ESTIMATED = "estimated"
MISSING = "missing"
LIVE_ONLY = "live-only"

LABEL = {
    REAL: "REAL",
    RECONSTRUCTED: "RECONSTRUCTED",
    ESTIMATED: "ESTIMATED",
    MISSING: "MISSING",
    LIVE_ONLY: "LIVE-ONLY",
}

# field -> (state, one-line reason shown next to any chart that uses it)
REGISTRY = {
    "spot":        (REAL, "WebSocket spot ticks; unchanged tick-to-tick only 3.5-3.7%"),
    "option_ltp":  (REAL, "WebSocket option ticks, one row per price change"),
    "volume":      (REAL, "cumulative from the feed; differenced for per-interval use"),
    "bid":         (ESTIMATED, "fabricated as ltp-0.3%/2 on 100% of rows"),
    "ask":         (ESTIMATED, "fabricated as ltp+0.3%/2 on 100% of rows"),
    "spread":      (ESTIMATED, "derived from the fabricated quotes; carries no market information"),
    "quote_source": (MISSING, "counted in logs, never written to the ticks table"),
    "oi":          (MISSING, "parsed by the WS client, dropped before persistence; NULL on every row"),
    "oi_direction": (MISSING, "constant on all six sessions, downstream of the missing oi"),
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
