"""Backtest data interface — the future real-data path, made explicit now.

This module does NOT touch core/backtest.py and does NOT run a backtest.
It defines the contract a real-data backtest run will use once real
historical data exists and passes the gate:

  - mode is a REQUIRED, explicit choice ("real" or "synthetic") — there is
    no default, so a caller cannot accidentally end up in synthetic mode.
  - In mode="real", a missing value RAISES (RealDataMissingError) instead
    of silently substituting a synthetic one. This is the specific
    protection the plan called for: synthetic data must never be an
    automatic fallback during a real-data run.
  - In mode="synthetic", the caller must supply its own synthetic_resolver
    callable (e.g. eventually core.backtest.py's existing
    _resolve_option_price linear-proxy logic) — this module does not
    reimplement or duplicate that logic, it only enforces that synthetic
    mode is never reached by accident.
  - Every result is stamped with an explicit data_mode field, so a report
    generated from this interface can never be read later without knowing
    whether it came from real or synthetic data.

Wiring this into core/backtest.py itself is a future step (see the
readiness plan, Section 3/7) — deliberately not done in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from core.historical.gate import GateResult, check_backtest_ready
from core.historical.storage import HistoricalStore

VALID_MODES = ("real", "synthetic")


class RealDataMissingError(Exception):
    """Raised in mode='real' when a requested (timestamp, symbol) has no
    canonical row in storage. This is intentional — the whole point of
    real-data mode is that it never silently substitutes anything."""


class InvalidDataModeError(Exception):
    """Raised when mode is anything other than 'real' or 'synthetic', or
    when synthetic mode is requested without a synthetic_resolver."""


@dataclass
class ProvenancedTick:
    """A single resolved tick, always stamped with where it came from."""

    timestamp: str
    symbol: str
    ltp: float
    bid: Optional[float]
    ask: Optional[float]
    data_mode: str  # "real" or "synthetic" — never absent, never inferred

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "ltp": self.ltp,
            "bid": self.bid,
            "ask": self.ask,
            "data_mode": self.data_mode,
        }


class BacktestDataSource:
    """The single entry point a future real-data backtest run should use to
    resolve option prices, instead of reading canonical storage directly.
    Centralizing it here means the mode/provenance guarantees below are
    enforced in exactly one place."""

    def __init__(
        self,
        store: HistoricalStore,
        mode: str,
        synthetic_resolver: Optional[Callable[[str, str], Dict]] = None,
    ):
        if mode not in VALID_MODES:
            raise InvalidDataModeError(
                f"mode must be one of {VALID_MODES}, got {mode!r} — "
                "there is no default; callers must choose explicitly."
            )
        if mode == "synthetic" and synthetic_resolver is None:
            raise InvalidDataModeError(
                "mode='synthetic' requires an explicit synthetic_resolver "
                "callable — synthetic mode has no built-in fallback logic "
                "here by design."
            )
        self.store = store
        self.mode = mode
        self._synthetic_resolver = synthetic_resolver
        self._row_cache: Dict[tuple, Optional[Dict]] = {}

    def is_ready(self, start_date: str, end_date: str) -> GateResult:
        """Delegates to the hard gate. Callers should check .ready before
        running anything against this data source in mode='real'."""
        return check_backtest_ready(self.store, start_date, end_date)

    def resolve_tick(self, timestamp: str, symbol: str) -> ProvenancedTick:
        """Resolve a single (timestamp, symbol) tick.

        mode='real': looks up canonical storage for the exact date; raises
        RealDataMissingError if the symbol has no row on that date rather
        than approximating or falling back.

        mode='synthetic': always calls the injected synthetic_resolver and
        stamps the result data_mode='synthetic' — this path is never taken
        implicitly, only when the caller constructed this instance with
        mode='synthetic' in the first place.
        """
        if self.mode == "real":
            row = self._lookup_real(timestamp, symbol)
            if row is None:
                raise RealDataMissingError(
                    f"No real canonical data for symbol={symbol!r} at "
                    f"timestamp={timestamp!r} — refusing to substitute a "
                    f"synthetic value in mode='real'."
                )
            return ProvenancedTick(
                timestamp=row["timestamp"],
                symbol=row["symbol"],
                ltp=row["ltp"],
                bid=row.get("bid"),
                ask=row.get("ask"),
                data_mode="real",
            )

        # mode == "synthetic"
        synthetic = self._synthetic_resolver(timestamp, symbol)
        return ProvenancedTick(
            timestamp=timestamp,
            symbol=symbol,
            ltp=synthetic["ltp"],
            bid=synthetic.get("bid"),
            ask=synthetic.get("ask"),
            data_mode="synthetic",
        )

    def _lookup_real(self, timestamp: str, symbol: str) -> Optional[Dict]:
        date = timestamp[:10]
        cache_key = (date, symbol)
        if cache_key not in self._row_cache:
            # Cache the whole day's rows for this symbol on first lookup —
            # avoids a fresh DB query per tick during a sequential replay.
            rows = list(self.store.query_range(date, date, symbols=[symbol]))
            by_ts = {r["timestamp"]: r for r in rows}
            self._row_cache[cache_key] = by_ts  # type: ignore[assignment]
        day_rows = self._row_cache[cache_key]
        return day_rows.get(timestamp) if isinstance(day_rows, dict) else None
