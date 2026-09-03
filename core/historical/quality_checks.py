"""Data-quality checks for canonical historical rows.

Implements every check from the approved Historical Data Acquisition &
Backtest Readiness Plan, Section 2:
  - timestamp integrity
  - missing ticks (gaps)
  - duplicate ticks
  - contract identity
  - expiry/strike consistency
  - bid/ask validity
  - trading-session boundaries
  - option-chain coverage (ATM +/- COVERAGE_BAND_POINTS)
  - spot/option timestamp alignment

Each check is a pure function over a list of row dicts (CANONICAL_COLUMNS
shape) and returns a CheckResult. run_all_checks() aggregates them into a
QualityReport with an explicit PASS/FAIL per check and affected
row/date counts — never a silent repair or interpolation of missing data.

Shared by utils/phase1_data_audit.py (CLI, runs against an ingested file)
and core/historical/gate.py (the hard backtest-ready gate, runs against
whatever is in canonical storage for a requested date range).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Dict, Iterable, List, Optional

from core.historical.schema import CANONICAL_COLUMNS, INSTRUMENT_TYPES, build_option_symbol

SESSION_START = dt_time(9, 15, 0)
SESSION_END = dt_time(15, 30, 0)

MAX_GAP_SEC = 5.0
STRIKE_STEP = 50
COVERAGE_BAND_POINTS = 200
SPOT_ALIGN_TOLERANCE_SEC = 1.0
SPOT_ALIGN_PRICE_EPSILON = 0.01
SPREAD_SANITY_MULTIPLE = 10.0  # flag a spread more than 10x the day's median for that symbol

# Resolution gate: the approved spec requires 1-second minimum resolution.
# Real 1-second feeds show occasional 2-5s quiet gaps (measured: the live
# feed's median inter-tick spacing is 1.0s, p95 2.0s), so the threshold is
# set on the MEDIAN spacing with headroom rather than on any single gap.
# A 1-minute dataset (median 60s) or EOD data is decisively rejected.
MAX_MEDIAN_SPACING_SEC = 2.0
MIN_ROWS_FOR_RESOLUTION_CHECK = 10

# Quote-authenticity gate: formula-derived (synthetic) bid/ask puts LTP exactly
# at the midpoint on essentially every row, because it is *constructed* as
# ltp +/- spread/2. Real trades print at or near the bid or the ask, so a real
# feed never shows ~100% midpoint-exact rows. Threshold deliberately high so
# only unambiguous fabrication trips it.
SYNTHETIC_MIDPOINT_FRACTION_LIMIT = 0.95
MIN_ROWS_FOR_AUTHENTICITY_CHECK = 100
MIDPOINT_EPSILON = 0.005


@dataclass
class CheckResult:
    name: str
    passed: bool
    checked: int
    failed: int
    details: List[str] = field(default_factory=list)
    failing_dates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "checked": self.checked,
            "failed": self.failed,
            "details": self.details[:20],  # cap for report readability
            "failing_dates": sorted(set(self.failing_dates)),
        }


@dataclass
class QualityReport:
    checks: List[CheckResult]
    row_count: int
    date_range: Optional[tuple] = None

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> Dict:
        return {
            "row_count": self.row_count,
            "date_range": list(self.date_range) if self.date_range else None,
            "all_passed": self.all_passed,
            "checks": [c.to_dict() for c in self.checks],
        }


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None


def _date_str(ts: str) -> str:
    dt = _parse_ts(ts)
    return dt.strftime("%Y-%m-%d") if dt else "UNPARSEABLE"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_timestamp_integrity(rows: List[Dict]) -> CheckResult:
    """Every timestamp parses, and per-instrument timestamps are strictly monotonic."""
    unparseable = 0
    out_of_order = 0
    details = []
    failing_dates = []
    last_ts_by_symbol: Dict[str, datetime] = {}

    for row in rows:
        dt = _parse_ts(row.get("timestamp"))
        if dt is None:
            unparseable += 1
            details.append(f"unparseable timestamp: {row.get('timestamp')!r} symbol={row.get('symbol')!r}")
            continue
        symbol = row.get("symbol")
        prev = last_ts_by_symbol.get(symbol)
        if prev is not None and dt <= prev:
            out_of_order += 1
            details.append(f"out-of-order: {symbol} {prev} -> {dt}")
            failing_dates.append(_date_str(row.get("timestamp")))
        last_ts_by_symbol[symbol] = dt

    failed = unparseable + out_of_order
    return CheckResult(
        name="timestamp_integrity",
        passed=(failed == 0),
        checked=len(rows),
        failed=failed,
        details=details,
        failing_dates=failing_dates,
    )


def check_duplicate_ticks(rows: List[Dict]) -> CheckResult:
    """No exact (timestamp, symbol) duplicates."""
    seen = set()
    dupes = 0
    details = []
    failing_dates = []
    for row in rows:
        key = (row.get("timestamp"), row.get("symbol"))
        if key in seen:
            dupes += 1
            details.append(f"duplicate: {key}")
            failing_dates.append(_date_str(row.get("timestamp")))
        else:
            seen.add(key)
    return CheckResult(
        name="duplicate_ticks",
        passed=(dupes == 0),
        checked=len(rows),
        failed=dupes,
        details=details,
        failing_dates=failing_dates,
    )


def check_missing_ticks(rows: List[Dict], max_gap_sec: float = MAX_GAP_SEC) -> CheckResult:
    """No gap larger than max_gap_sec between consecutive rows of the same
    instrument during the trading session. Gaps that straddle a session
    boundary (previous day's close to next day's open) are not counted —
    only intraday gaps."""
    by_symbol: Dict[str, List[datetime]] = defaultdict(list)
    for row in rows:
        dt = _parse_ts(row.get("timestamp"))
        if dt is not None:
            by_symbol[row.get("symbol")].append(dt)

    gaps = 0
    details = []
    failing_dates = []
    checked = 0
    for symbol, timestamps in by_symbol.items():
        timestamps.sort()
        for prev, cur in zip(timestamps, timestamps[1:]):
            if prev.date() != cur.date():
                continue  # cross-day boundary, not an intraday gap
            # counted only for pairs actually gap-evaluated, so checked==0
            # genuinely means "nothing intraday was verifiable"
            checked += 1
            gap = (cur - prev).total_seconds()
            if gap > max_gap_sec:
                gaps += 1
                details.append(f"gap {gap:.1f}s in {symbol}: {prev} -> {cur}")
                failing_dates.append(cur.strftime("%Y-%m-%d"))

    # HARDENING: never pass vacuously. checked==0 means no symbol had two
    # consecutive same-day rows to compare — which is exactly what EOD data
    # looks like (one row per contract per day). Previously this returned
    # PASS with checked=0, letting daily data satisfy an intraday-gap check.
    if checked == 0:
        return CheckResult(
            name="missing_ticks",
            passed=False,
            checked=0,
            failed=1,
            details=[
                "no intraday tick pairs to check — every symbol has at most one "
                "row per day. This is EOD/daily data, not the intraday series "
                "this gate exists to validate."
            ],
            failing_dates=sorted({_date_str(r.get("timestamp")) for r in rows if r.get("timestamp")}),
        )

    return CheckResult(
        name="missing_ticks",
        passed=(gaps == 0),
        checked=checked,
        failed=gaps,
        details=details,
        failing_dates=failing_dates,
    )


def check_contract_identity(rows: List[Dict]) -> CheckResult:
    """symbol must equal NIFTY{expiry-as-DDMMMYY}{strike}{CE|PE} for option
    rows — the same convention core/trading/broker.py's
    _build_option_symbol() uses live (see schema.build_option_symbol)."""
    bad = 0
    checked = 0
    details = []
    failing_dates = []
    for row in rows:
        if row.get("instrument_type") not in ("CE", "PE"):
            continue
        checked += 1
        expiry = row.get("expiry")
        strike = row.get("strike")
        itype = row.get("instrument_type")
        symbol = row.get("symbol") or ""
        if expiry is None or strike is None:
            bad += 1
            details.append(f"missing expiry/strike for symbol={symbol}")
            failing_dates.append(_date_str(row.get("timestamp")))
            continue
        expected = build_option_symbol(expiry, strike, itype)
        if expected is None or symbol != expected:
            bad += 1
            details.append(f"symbol/expiry/strike mismatch: symbol={symbol} expected={expected} (expiry={expiry} strike={strike} type={itype})")
            failing_dates.append(_date_str(row.get("timestamp")))
    return CheckResult(
        name="contract_identity",
        passed=(bad == 0),
        checked=checked,
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_expiry_strike_consistency(rows: List[Dict]) -> CheckResult:
    """Structural sanity only: expiry parses as a date, strike is a positive
    multiple of the NIFTY strike step. This does NOT verify the strike/expiry
    combination was an actually-listed exchange contract on that date — doing
    that would require an external reference contract list this repo does not
    have. That limitation is reported explicitly rather than silently assumed
    to be covered."""
    bad = 0
    checked = 0
    details = []
    failing_dates = []
    for row in rows:
        if row.get("instrument_type") not in ("CE", "PE"):
            continue
        checked += 1
        strike = row.get("strike")
        expiry = row.get("expiry")
        ok = True
        if strike is None or not isinstance(strike, (int, float)) or strike <= 0 or int(strike) % STRIKE_STEP != 0:
            ok = False
            details.append(f"invalid strike: {strike} (must be positive multiple of {STRIKE_STEP})")
        if not expiry:
            ok = False
            details.append(f"missing expiry for symbol={row.get('symbol')}")
        else:
            try:
                datetime.strptime(str(expiry), "%Y-%m-%d")
            except ValueError:
                ok = False
                details.append(f"unparseable expiry: {expiry!r}")
        if not ok:
            bad += 1
            failing_dates.append(_date_str(row.get("timestamp")))
    return CheckResult(
        name="expiry_strike_consistency",
        passed=(bad == 0),
        checked=checked,
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_bid_ask_validity(rows: List[Dict]) -> CheckResult:
    """0 < bid <= ltp <= ask for option rows, plus a spread-sanity bound
    against the per-symbol median spread (catches feed garbage, same class
    of issue as the live 'Premium feed anomaly' rejections already observed
    in production)."""
    option_rows = [r for r in rows if r.get("instrument_type") in ("CE", "PE")]
    spreads_by_symbol: Dict[str, List[float]] = defaultdict(list)
    for r in option_rows:
        bid, ask = r.get("bid"), r.get("ask")
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            spreads_by_symbol[r.get("symbol")].append(ask - bid)

    medians = {}
    for symbol, spreads in spreads_by_symbol.items():
        s = sorted(spreads)
        medians[symbol] = s[len(s) // 2] if s else 0.0

    bad = 0
    details = []
    failing_dates = []
    for r in option_rows:
        bid, ask, ltp = r.get("bid"), r.get("ask"), r.get("ltp")
        symbol = r.get("symbol")
        ok = bid is not None and ask is not None and ltp is not None and 0 < bid <= ltp <= ask
        if ok:
            median = medians.get(symbol, 0.0)
            spread = ask - bid
            if median > 0 and spread > median * SPREAD_SANITY_MULTIPLE:
                ok = False
                details.append(f"spread outlier: {symbol} spread={spread:.2f} vs median={median:.2f}")
        else:
            details.append(f"invalid bid/ltp/ask: {symbol} bid={bid} ltp={ltp} ask={ask}")
        if not ok:
            bad += 1
            failing_dates.append(_date_str(r.get("timestamp")))

    return CheckResult(
        name="bid_ask_validity",
        passed=(bad == 0),
        checked=len(option_rows),
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_session_boundaries(rows: List[Dict]) -> CheckResult:
    """Every row's time-of-day falls within 09:15-15:30 IST."""
    bad = 0
    details = []
    failing_dates = []
    for row in rows:
        dt = _parse_ts(row.get("timestamp"))
        if dt is None:
            continue
        t = dt.time()
        if not (SESSION_START <= t <= SESSION_END):
            bad += 1
            details.append(f"outside session: {row.get('symbol')} at {dt}")
            failing_dates.append(dt.strftime("%Y-%m-%d"))
    return CheckResult(
        name="session_boundaries",
        passed=(bad == 0),
        checked=len(rows),
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_option_chain_coverage(rows: List[Dict], band_points: int = COVERAGE_BAND_POINTS) -> CheckResult:
    """For every trading day present, both CE and PE must be present for
    strikes spanning at least ATM +/- band_points (using each day's observed
    spot_ref range as the ATM proxy, since exact intraday ATM moves)."""
    by_date_type: Dict[str, Dict[str, set]] = defaultdict(lambda: {"CE": set(), "PE": set()})
    spot_by_date: Dict[str, List[float]] = defaultdict(list)

    for row in rows:
        d = _date_str(row.get("timestamp"))
        if row.get("instrument_type") == "SPOT" and row.get("ltp"):
            spot_by_date[d].append(row["ltp"])
        elif row.get("instrument_type") in ("CE", "PE") and row.get("strike") is not None:
            by_date_type[d][row["instrument_type"]].add(int(row["strike"]))
        spot_ref = row.get("spot_ref")
        if spot_ref:
            spot_by_date[d].append(spot_ref)

    # HARDENING: never pass vacuously. With no spot rows and no spot_ref on any
    # option row there is no ATM reference, so coverage is unverifiable — which
    # previously returned PASS with checked=0 rather than admitting it could not
    # evaluate anything.
    option_dates = sorted({_date_str(r.get("timestamp")) for r in rows
                           if r.get("instrument_type") in ("CE", "PE") and r.get("timestamp")})
    if not spot_by_date and option_dates:
        return CheckResult(
            name="option_chain_coverage",
            passed=False,
            checked=0,
            failed=len(option_dates),
            details=[
                "cannot evaluate ATM coverage: dataset has no SPOT rows and no "
                "spot_ref on any option row, so there is no ATM reference price."
            ],
            failing_dates=option_dates,
        )

    bad = 0
    details = []
    failing_dates = []
    checked = 0
    for d, spots in spot_by_date.items():
        checked += 1
        if not spots:
            continue
        atm = round((sum(spots) / len(spots)) / STRIKE_STEP) * STRIKE_STEP
        low, high = atm - band_points, atm + band_points
        for itype in ("CE", "PE"):
            strikes = by_date_type[d][itype]
            covered = {s for s in strikes if low <= s <= high}
            required = set(range(low, high + 1, STRIKE_STEP))
            missing = required - covered
            if missing:
                bad += 1
                details.append(f"{d} {itype} missing strikes near ATM {atm}: {sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}")
                failing_dates.append(d)

    return CheckResult(
        name="option_chain_coverage",
        passed=(bad == 0),
        checked=checked,
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_spot_option_alignment(rows: List[Dict], tolerance_sec: float = SPOT_ALIGN_TOLERANCE_SEC) -> CheckResult:
    """Every CE/PE row's spot_ref must correspond to a real SPOT row within
    tolerance_sec of the same timestamp (and match its price closely) —
    guards against a stale/joined spot value being silently carried forward."""
    spot_points: Dict[str, List[tuple]] = defaultdict(list)  # date -> [(dt, ltp), ...]
    for row in rows:
        if row.get("instrument_type") == "SPOT":
            dt = _parse_ts(row.get("timestamp"))
            if dt is not None:
                spot_points[dt.strftime("%Y-%m-%d")].append((dt, row.get("ltp")))
    for d in spot_points:
        spot_points[d].sort()

    bad = 0
    checked = 0
    details = []
    failing_dates = []
    for row in rows:
        if row.get("instrument_type") not in ("CE", "PE"):
            continue
        spot_ref = row.get("spot_ref")
        if spot_ref is None:
            bad += 1
            checked += 1
            details.append(f"no spot_ref: {row.get('symbol')} at {row.get('timestamp')}")
            failing_dates.append(_date_str(row.get("timestamp")))
            continue
        checked += 1
        dt = _parse_ts(row.get("timestamp"))
        if dt is None:
            bad += 1
            continue
        d = dt.strftime("%Y-%m-%d")
        candidates = spot_points.get(d, [])
        nearest = min(candidates, key=lambda p: abs((p[0] - dt).total_seconds()), default=None)
        if nearest is None or abs((nearest[0] - dt).total_seconds()) > tolerance_sec:
            bad += 1
            details.append(f"no SPOT row within {tolerance_sec}s of {row.get('symbol')} at {dt}")
            failing_dates.append(d)
        elif nearest[1] is not None and abs(nearest[1] - spot_ref) > SPOT_ALIGN_PRICE_EPSILON:
            bad += 1
            details.append(f"spot_ref mismatch: {row.get('symbol')} spot_ref={spot_ref} vs nearest SPOT ltp={nearest[1]}")
            failing_dates.append(d)

    return CheckResult(
        name="spot_option_alignment",
        passed=(bad == 0),
        checked=checked,
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_resolution(rows: List[Dict], max_median_spacing_sec: float = MAX_MEDIAN_SPACING_SEC) -> CheckResult:
    """Enforce the approved minimum resolution (1-second) explicitly.

    The gate previously had NO granularity check at all: a 1-minute or EOD
    dataset could satisfy every other check and be declared READY, silently
    violating the spec this whole pipeline exists to enforce. This measures
    the MEDIAN inter-row spacing per (symbol, date) — median rather than max
    so ordinary quiet-minute gaps in a genuine 1-second feed don't fail it,
    and per-symbol so a busy chain doesn't mask a thin contract.
    """
    by_symbol_date: Dict[tuple, List[datetime]] = defaultdict(list)
    for row in rows:
        dt = _parse_ts(row.get("timestamp"))
        if dt is not None:
            by_symbol_date[(row.get("symbol"), dt.strftime("%Y-%m-%d"))].append(dt)

    bad = 0
    checked = 0
    details = []
    failing_dates = []
    for (symbol, date), timestamps in by_symbol_date.items():
        if len(timestamps) < MIN_ROWS_FOR_RESOLUTION_CHECK:
            # Too few rows to characterise spacing — that is itself a failure
            # for an intraday dataset covering a full session.
            bad += 1
            details.append(
                f"{symbol} on {date}: only {len(timestamps)} rows — too sparse to be "
                f"1-second intraday data"
            )
            failing_dates.append(date)
            continue
        checked += 1
        timestamps.sort()
        spacings = sorted((b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:]))
        median = spacings[len(spacings) // 2]
        if median > max_median_spacing_sec:
            bad += 1
            details.append(
                f"{symbol} on {date}: median spacing {median:.1f}s exceeds "
                f"{max_median_spacing_sec}s — this is not 1-second resolution data"
            )
            failing_dates.append(date)

    if checked == 0 and bad == 0:
        return CheckResult(
            name="resolution",
            passed=False,
            checked=0,
            failed=1,
            details=["no rows available to verify resolution"],
            failing_dates=[],
        )

    return CheckResult(
        name="resolution",
        passed=(bad == 0),
        checked=checked,
        failed=bad,
        details=details,
        failing_dates=failing_dates,
    )


def check_quote_authenticity(rows: List[Dict]) -> CheckResult:
    """Detect formula-derived (synthetic) bid/ask.

    Added after discovering that 100% of this project's own persisted ticks
    carry synthetic quotes: the live collector falls back to
    `bid/ask = ltp -/+ (ltp*0.003)/2` whenever the feed's best-bid/ask is
    absent, and that fallback fired on every tick. Such data satisfies
    bid_ask_validity perfectly (0 < bid <= ltp <= ask holds by construction),
    so internal-consistency checking alone cannot catch fabrication.

    Signature: LTP sits EXACTLY at the bid/ask midpoint on essentially every
    row. Real prints occur at or near the bid or the ask.
    """
    quoted = [r for r in rows
              if r.get("instrument_type") in ("CE", "PE")
              and r.get("bid") is not None and r.get("ask") is not None
              and r.get("ltp") is not None]
    if len(quoted) < MIN_ROWS_FOR_AUTHENTICITY_CHECK:
        return CheckResult(
            name="quote_authenticity",
            passed=True,
            checked=len(quoted),
            failed=0,
            details=[f"only {len(quoted)} quoted rows — below the "
                     f"{MIN_ROWS_FOR_AUTHENTICITY_CHECK}-row minimum to judge authenticity"],
        )

    midpoint_exact = sum(
        1 for r in quoted
        if abs((r["bid"] + r["ask"]) / 2.0 - r["ltp"]) < MIDPOINT_EPSILON
    )
    fraction = midpoint_exact / len(quoted)
    if fraction >= SYNTHETIC_MIDPOINT_FRACTION_LIMIT:
        return CheckResult(
            name="quote_authenticity",
            passed=False,
            checked=len(quoted),
            failed=midpoint_exact,
            details=[
                f"{fraction * 100:.1f}% of quoted rows have LTP exactly at the "
                f"bid/ask midpoint — bid/ask appear formula-derived (synthetic), "
                f"not real market quotes."
            ],
            failing_dates=sorted({_date_str(r.get("timestamp")) for r in quoted if r.get("timestamp")}),
        )

    return CheckResult(
        name="quote_authenticity",
        passed=True,
        checked=len(quoted),
        failed=0,
        details=[f"{fraction * 100:.1f}% midpoint-exact — consistent with real quotes"],
    )


ALL_CHECKS = (
    check_timestamp_integrity,
    check_duplicate_ticks,
    check_missing_ticks,
    check_contract_identity,
    check_expiry_strike_consistency,
    check_bid_ask_validity,
    check_session_boundaries,
    check_option_chain_coverage,
    check_spot_option_alignment,
    check_resolution,
    check_quote_authenticity,
)


def run_all_checks(rows: Iterable[Dict]) -> QualityReport:
    """Run every Section-2 check against rows (an iterable of dicts shaped
    like CANONICAL_COLUMNS) and return an aggregate QualityReport.

    Never repairs or interpolates — every check either passes on what is
    actually present, or fails with an explicit count and sample."""
    rows = list(rows)
    checks = [fn(rows) for fn in ALL_CHECKS]

    dates = sorted({_date_str(r.get("timestamp")) for r in rows if r.get("timestamp")})
    date_range = (dates[0], dates[-1]) if dates else None

    return QualityReport(checks=checks, row_count=len(rows), date_range=date_range)
