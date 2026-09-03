"""Canonical long-format schema for historical spot/option data.

One row per (timestamp, instrument) — matches the live core/services/database.py
`ticks` table shape (timestamp, symbol, ltp, bid, ask, volume, spot_price, oi)
plus the additional fields the historical-data readiness plan requires
(instrument_type, expiry, strike, Greeks/IV) so the same downstream query
patterns already proven against the live ticks table carry over unchanged.

This is deliberately the single source of truth for column names/order —
utils/ingest_cepe_and_audit.py, utils/phase1_data_audit.py, and
core/historical/storage.py all import from here instead of each hardcoding
their own header, so the three can't silently drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Optional

INSTRUMENT_TYPES = ("SPOT", "CE", "PE")

# Canonical column order — this is also the CSV header order written by the
# ingestion utility and read by the audit/storage layers.
CANONICAL_COLUMNS = (
    "timestamp",
    "instrument_type",
    "symbol",
    "expiry",
    "strike",
    "ltp",
    "bid",
    "ask",
    "volume",
    "oi",
    "delta",
    "gamma",
    "theta",
    "vega",
    "iv",
    "spot_ref",
)

# Fields that are required (non-null) for every row regardless of instrument_type.
REQUIRED_ALWAYS = ("timestamp", "instrument_type", "symbol", "ltp")

# Fields required specifically for CE/PE rows (spot rows leave these null).
REQUIRED_FOR_OPTIONS = ("expiry", "strike", "bid", "ask")


@dataclass
class CanonicalRow:
    """One canonical historical-data row. Mirrors CANONICAL_COLUMNS exactly."""

    timestamp: str
    instrument_type: str
    symbol: str
    ltp: float
    expiry: Optional[str] = None
    strike: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    spot_ref: Optional[float] = None

    def as_tuple(self):
        return tuple(getattr(self, col) for col in CANONICAL_COLUMNS)

    def as_dict(self):
        return {col: getattr(self, col) for col in CANONICAL_COLUMNS}


def expiry_to_symbol_token(expiry_iso: str) -> Optional[str]:
    """Canonical ISO expiry ('2026-08-14') -> the exchange-format token
    ('14AUG26') NIFTY option symbols embed — matches
    core/trading/broker.py's _build_option_symbol()/_find_nearest_expiry()
    convention exactly (expiry_str = check_date.strftime("%d%b%y").upper()).
    Returns None if expiry_iso isn't a parseable 'YYYY-MM-DD' date.

    This is the single conversion point ingestion and validation both use,
    so a canonical 'expiry' column is always stored as ISO — sortable,
    unambiguous — while symbols still match the live system's exact format."""
    try:
        return datetime.strptime(str(expiry_iso), "%Y-%m-%d").strftime("%d%b%y").upper()
    except (ValueError, TypeError):
        return None


def build_option_symbol(expiry_iso: str, strike, option_type: str) -> Optional[str]:
    """ISO expiry + strike + CE/PE -> canonical symbol string, using the
    exact same convention as core/trading/broker.py's _build_option_symbol().
    Returns None if expiry_iso doesn't parse."""
    token = expiry_to_symbol_token(expiry_iso)
    if token is None or strike is None:
        return None
    return f"NIFTY{token}{int(strike)}{option_type}"


def field_names() -> tuple:
    """CanonicalRow's dataclass field names, for validation against CANONICAL_COLUMNS."""
    return tuple(f.name for f in fields(CanonicalRow))


# Sanity check at import time: CanonicalRow must declare every canonical column
# (order may legitimately differ due to the dataclass's required/default-arg
# ordering constraint) and nothing extra.
_missing = set(CANONICAL_COLUMNS) - set(field_names())
_extra = set(field_names()) - set(CANONICAL_COLUMNS)
if _missing or _extra:
    raise RuntimeError(
        f"core.historical.schema: CanonicalRow fields out of sync with "
        f"CANONICAL_COLUMNS (missing={_missing}, extra={_extra})"
    )
