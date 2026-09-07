"""The order book and open interest — how much of each is real, per row.

Two things arrived on 2026-09-07 that this project had never had: an actual bid/ask from the
exchange, and an actual open-interest value. Both ride the same mode-3 SnapQuote packet, and
the subscription was flipped to it mid-session, so **one session's ticks are mixed**: some rows
carry a real book, the rest still carry the `ltp +/- 0.3%` estimate that every earlier figure in
this repository rests on.

That breaks the assumption `research/provenance.py` was built on. Its registry answers per
FIELD — "bid is ESTIMATED, fabricated on 100% of rows" — and on a mixed session that sentence is
false for a third of the data and true for the rest. A field-level answer can only be wrong
here. This module answers per ROW instead, from the values themselves, and the registry defers
to it for the three fields it covers.

Measured over the recorded sessions:

    2026-09-07   25,263 rows   66.3% estimate   33.7% real book   8,516 rows with OI
    2026-09-04   25,055 rows  100.0% estimate    0.0% real book       0 rows with OI
    2026-09-03   25,124 rows   99.7% estimate    0.3% real book       0 rows with OI
    2026-09-02   22,992 rows  100.0% estimate    0.0% real book       0 rows with OI

Nothing here decides anything. The strategy layer consumed these fields as gates — a spread
filter, and an OI buildup label feeding the score's `oi` component. This module records what
they were and, where useful, what a rule *would* have said, marked as a reconstruction. A gate
that also reports on itself cannot be trusted to report honestly; separating the two is the
whole point.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from research.db import Book

# ── per-row quote origin ────────────────────────────────────────────────────────────────

BOOK = "book"                  # a real best-bid/best-ask from the mode-3 packet
ESTIMATE = "estimate"          # broker.py's fallback; carries no market information
UNRECOGNISED = "unrecognised"  # not the fallback, and nothing corroborates a real book
ABSENT = "absent"              # no usable quote on the row at all

ORIGIN_LABEL = {BOOK: "REAL BOOK", ESTIMATE: "ESTIMATE",
                UNRECOGNISED: "UNRECOGNISED", ABSENT: "ABSENT"}

# Rows are stored rounded to 2 decimals and floats do not compare cleanly at that scale
# (69.89 against 69.90 differs by 0.010000000000005). Slightly over one paisa is the storage
# granularity plus float slack, not a fudge factor.
_ROUNDING_TOLERANCE = 0.011


def _estimated_pair(ltp: float) -> Tuple[float, float]:
    """broker.py's fallback quote, reproduced exactly — including the 5-paisa floor.

    `spread = max(0.05, ltp * 0.003)`, then bid/ask are ltp -/+ half of it, rounded to 2dp.
    The floor matters below ltp 16.67, where a plain 0.3% would be finer than a tick.
    """
    spread = max(0.05, ltp * 0.003)
    return round(ltp - spread / 2, 2), round(ltp + spread / 2, 2)


def quote_origin(ltp: float, bid: Optional[float], ask: Optional[float],
                 has_oi: bool = False, tolerance: float = _ROUNDING_TOLERANCE) -> str:
    """Where this row's quote came from, decided from the numbers plus one corroboration.

    No column records it — `quote_source` is written to the logs and never to the ticks table —
    so the first half is arithmetic: reproduce the fallback and see whether the stored pair
    matches it.

    The second half is why `has_oi` is here. "Not the fallback" is NOT the same as "a real
    book", and treating it that way is the mistake this function was written wrong once
    already. Real quotes and open interest ride the same mode-3 SnapQuote packet, so a real
    book row should carry OI. Measured across the four recorded sessions:

        2026-09-07   8,441 non-fallback rows,  8,433 with OI  (99.9%)  -> real
        2026-09-04       5 non-fallback rows,      0 with OI           -> not real
        2026-09-03       4 non-fallback rows,      0 with OI           -> not real
        2026-09-02       5 non-fallback rows,      0 with OI           -> not real

    Those 4-5 rows per old session are quotes roughly a third as wide as the fallback, on days
    when the best-5 parser did not exist yet, so a real book was not physically available.
    Whatever produced them, this module will not call it a market quote. They are
    UNRECOGNISED, and they are counted, because an anomaly nobody counts becomes a rounding
    error in someone's conclusion.
    """
    if not ltp or ltp <= 0 or bid is None or ask is None:
        return ABSENT
    if bid <= 0 or ask <= 0 or ask < bid:
        return ABSENT
    exp_bid, exp_ask = _estimated_pair(ltp)
    if abs(bid - exp_bid) <= tolerance and abs(ask - exp_ask) <= tolerance:
        return ESTIMATE
    return BOOK if has_oi else UNRECOGNISED


def has_open_interest(oi) -> bool:
    """OI is absent as NULL before the fix and as 0 where the mode-2 path still runs."""
    try:
        return oi is not None and float(oi) > 0
    except (TypeError, ValueError):
        return False


# ── session-level coverage ──────────────────────────────────────────────────────────────

@dataclass
class Coverage:
    """How much of a session's data is real, by row."""

    day: str
    rows: int = 0
    book: int = 0
    estimate: int = 0
    unrecognised: int = 0
    absent: int = 0
    with_oi: int = 0
    first_book_at: Optional[_dt.datetime] = None
    first_oi_at: Optional[_dt.datetime] = None

    @property
    def book_pct(self) -> float:
        return 100.0 * self.book / self.rows if self.rows else 0.0

    @property
    def oi_pct(self) -> float:
        return 100.0 * self.with_oi / self.rows if self.rows else 0.0

    @property
    def mixed(self) -> bool:
        """True when a single field-level provenance statement cannot describe this session."""
        return self.book > 0 and self.estimate > 0

    def summary(self) -> str:
        if not self.rows:
            return f"{self.day}: no ticks"
        kind = "MIXED" if self.mixed else ("real book" if self.book else "estimate only")
        extra = f" | unrecognised {self.unrecognised}" if self.unrecognised else ""
        return (f"{self.day}: {self.rows:,} rows | book {self.book_pct:.1f}% "
                f"| oi {self.oi_pct:.1f}% | {kind}{extra}")


def coverage(book: Book, day: str, symbol: Optional[str] = None) -> Coverage:
    """Row-by-row provenance for one session, across every option symbol unless one is named."""
    out = Coverage(day=day)
    symbols = [symbol] if symbol else [s for s, _ in book.option_symbols(day)]
    for sym in symbols:
        for row in book.option_quotes(sym, day):
            out.rows += 1
            oi_present = has_open_interest(row.get("oi"))
            origin = quote_origin(row.get("ltp"), row.get("bid"), row.get("ask"), oi_present)
            if origin == BOOK:
                out.book += 1
                if out.first_book_at is None or row["t"] < out.first_book_at:
                    out.first_book_at = row["t"]
            elif origin == ESTIMATE:
                out.estimate += 1
            elif origin == UNRECOGNISED:
                out.unrecognised += 1
            else:
                out.absent += 1
            if oi_present:
                out.with_oi += 1
                if out.first_oi_at is None or row["t"] < out.first_oi_at:
                    out.first_oi_at = row["t"]
    return out


# ── spread, kept separate by origin ─────────────────────────────────────────────────────

@dataclass
class SpreadProfile:
    """Spread statistics, never mixing a measured spread with a fabricated one."""

    day: str
    real: List[float] = field(default_factory=list)
    estimated: List[float] = field(default_factory=list)

    @staticmethod
    def _stats(values: Sequence[float]) -> Dict[str, float]:
        if not values:
            return {}
        ordered = sorted(values)
        return {
            "n": len(ordered),
            "min": ordered[0],
            "p50": _st.median(ordered),
            "p90": ordered[int(0.9 * (len(ordered) - 1))],
            "max": ordered[-1],
            "mean": _st.fmean(ordered),
        }

    def real_stats(self) -> Dict[str, float]:
        return self._stats(self.real)

    def estimated_stats(self) -> Dict[str, float]:
        return self._stats(self.estimated)

    def crossing_cost_points(self) -> Optional[float]:
        """Half the median real spread — what crossing it once costs, in option points.

        None when the session recorded no real book, because the alternative is to answer with
        the fabricated number, and a fabricated spread priced as an execution cost is exactly
        the mistake this module exists to stop. `research.costs` handles brokerage and taxes;
        this is the separate, market-side half.
        """
        if not self.real:
            return None
        return round(_st.median(self.real) / 2.0, 4)


def spread_profile(book: Book, day: str, symbol: Optional[str] = None) -> SpreadProfile:
    """Spreads for one session, split by whether the quote was real."""
    out = SpreadProfile(day=day)
    symbols = [symbol] if symbol else [s for s, _ in book.option_symbols(day)]
    for sym in symbols:
        for row in book.option_quotes(sym, day):
            origin = quote_origin(row.get("ltp"), row.get("bid"), row.get("ask"),
                                  has_open_interest(row.get("oi")))
            spread = round(float(row["ask"]) - float(row["bid"]), 4)
            if origin == BOOK:
                out.real.append(spread)
            elif origin == ESTIMATE:
                out.estimated.append(spread)
            # UNRECOGNISED and ABSENT rows are counted in Coverage and deliberately excluded
            # from both distributions: a spread of unknown origin belongs in neither.
    return out


# ── open interest, observed rather than acted on ────────────────────────────────────────

LONG_BUILDUP = "LONG_BUILDUP"
SHORT_BUILDUP = "SHORT_BUILDUP"
SHORT_COVERING = "SHORT_COVERING"
LONG_UNWINDING = "LONG_UNWINDING"
NEUTRAL = "NEUTRAL"

# The live rule's threshold, mirrored so the observation matches what the strategy saw.
_OI_CHANGE_THRESHOLD_PCT = 1.0


def classify_buildup(oi_change_pct: float, price_up: bool) -> str:
    """The label the live rule produces, as a pure function of its two inputs.

    Mirrors `SmartScalpV3.update_oi_data()` exactly, including the +/-1% band. Reproduced here
    rather than imported because the live version carries per-instance state and a monotonic
    clock; this one is a function of the numbers, so a replay gets the same answer twice.
    """
    if oi_change_pct > _OI_CHANGE_THRESHOLD_PCT:
        return LONG_BUILDUP if price_up else SHORT_BUILDUP
    if oi_change_pct < -_OI_CHANGE_THRESHOLD_PCT:
        return SHORT_COVERING if price_up else LONG_UNWINDING
    return NEUTRAL


@dataclass
class OIProfile:
    """What open interest did, and what the buildup rule would have said about it.

    `labels` is a RECONSTRUCTION, not a record: the live rule windows on a monotonic clock and
    only sees ticks the process received, while this walks the persisted rows on their stored
    timestamps. It answers "could this rule have discriminated at all", not "this is what the
    bot decided".
    """

    day: str
    window_sec: float
    rows_with_oi: int = 0
    distinct_values: int = 0
    steps: int = 0                      # how many times OI actually changed
    labels: Dict[str, int] = field(default_factory=dict)

    @property
    def discriminates(self) -> bool:
        """A label that is constant carries no information, whatever its weight."""
        return len([k for k, v in self.labels.items() if v]) > 1


def oi_profile(book: Book, day: str, symbol: Optional[str] = None,
               window_sec: float = 0.0) -> OIProfile:
    """Observe open interest for one session. Never returns a gate, only a description."""
    out = OIProfile(day=day, window_sec=window_sec)
    symbols = [symbol] if symbol else [s for s, _ in book.option_symbols(day)]

    series: List[Tuple[_dt.datetime, float, float]] = []
    for sym in symbols:
        for row in book.option_quotes(sym, day):
            if has_open_interest(row.get("oi")):
                series.append((row["t"], float(row["oi"]), float(row.get("ltp") or 0)))
    series.sort(key=lambda r: r[0])

    out.rows_with_oi = len(series)
    out.distinct_values = len({v for _, v, _ in series})
    out.steps = sum(1 for a, b in zip(series, series[1:]) if a[1] != b[1])

    for i, (t, oi, ltp) in enumerate(series):
        if i == 0:
            continue
        base_t, base_oi, base_price = series[i - 1]
        if window_sec > 0:
            cutoff = t - _dt.timedelta(seconds=window_sec)
            older = [s for s in series[:i] if s[0] <= cutoff]
            base_t, base_oi, base_price = older[-1] if older else series[0]
        if base_oi <= 0:
            continue
        change_pct = (oi - base_oi) / base_oi * 100.0
        label = classify_buildup(change_pct, ltp > base_price)
        out.labels[label] = out.labels.get(label, 0) + 1

    return out


# ── the one call a report makes ─────────────────────────────────────────────────────────

def _provenance_note(cov: "Coverage") -> str:
    """What can honestly be said about this session's quotes — including "nothing".

    A session with no option ticks is not a session of fabricated quotes; it is a session with
    no observations. Answering the first with the second is the fabrication this module exists
    to stop, and the first draft of this function did exactly that for the 20 sessions that
    carry trades but no tick rows.
    """
    if not cov.rows:
        return "no option ticks recorded — nothing to say about quote origin"
    if cov.mixed:
        return "MIXED session — no single field-level provenance statement is true here"
    if cov.book:
        return "real book throughout"
    if cov.estimate:
        return "estimated quotes throughout"
    return f"{cov.rows:,} rows, none carrying a usable quote"


def session_report(book: Book, day: str, window_sec: float = 0.0) -> Dict[str, object]:
    """Everything this instrument knows about one session, as plain data."""
    cov = coverage(book, day)
    spread = spread_profile(book, day)
    oi = oi_profile(book, day, window_sec=window_sec)
    return {
        "day": day,
        "coverage": cov,
        "spread": spread,
        "oi": oi,
        "crossing_cost_points": spread.crossing_cost_points(),
        "provenance_note": _provenance_note(cov),
    }


def render_text(report: Dict[str, object]) -> str:
    """A short, honest paragraph. No chart draws a conclusion this text will not state."""
    cov: Coverage = report["coverage"]            # type: ignore[assignment]
    spread: SpreadProfile = report["spread"]      # type: ignore[assignment]
    oi: OIProfile = report["oi"]                  # type: ignore[assignment]

    lines = [cov.summary(), f"  provenance: {report['provenance_note']}"]
    if not cov.rows:
        # Nothing observed. Every line below would be a statement about data that is not here.
        return "\n".join(lines)
    if cov.first_book_at:
        lines.append(f"  first real book at {cov.first_book_at:%H:%M:%S}")
    if cov.first_oi_at:
        lines.append(f"  first open interest at {cov.first_oi_at:%H:%M:%S}")

    real, est = spread.real_stats(), spread.estimated_stats()
    if real:
        lines.append(f"  real spread     p50 {real['p50']:.2f} pts  p90 {real['p90']:.2f}  "
                     f"max {real['max']:.2f}  (n={real['n']:,})")
    if est:
        lines.append(f"  estimated       p50 {est['p50']:.2f} pts  (n={est['n']:,}) "
                     f"— fabricated, carries no market information")
    cost = report["crossing_cost_points"]
    lines.append(f"  crossing cost   {cost} pts per side" if cost is not None
                 else "  crossing cost   unknown — no real book this session")

    if oi.rows_with_oi:
        lines.append(f"  open interest   {oi.rows_with_oi:,} rows, {oi.distinct_values} distinct "
                     f"values, {oi.steps} changes")
        lines.append(f"  buildup labels  {oi.labels or 'none'} "
                     f"({'discriminates' if oi.discriminates else 'CONSTANT — no information'}; "
                     f"reconstruction, window={oi.window_sec}s)")
    else:
        lines.append("  open interest   absent on every row")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m research.depth [YYYY-MM-DD ...] [--window SEC]`; no day means every session."""
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("days", nargs="*", help="sessions to report; default every session with ticks")
    ap.add_argument("--window", type=float, default=0.0,
                    help="OI comparison window in seconds (0 = tick-to-tick, the live default)")
    args = ap.parse_args(argv)

    book = Book()
    days = args.days or [s["day"] for s in book.sessions()]
    if not days:
        print("no sessions with tick data")
        return 1
    for day in days:
        print(render_text(session_report(book, day, window_sec=args.window)))
        print()
    return 0


if __name__ == "__main__":                                    # pragma: no cover - CLI
    raise SystemExit(main())
