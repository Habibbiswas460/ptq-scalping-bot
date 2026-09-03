"""The hard BACKTEST READY / NOT READY gate.

Per the approved plan (Section 6): a real-data backtest run must call this
gate first and must be refused outright — not degraded, not partially run —
if the requested date range fails any check or has incomplete coverage.

Runs quality_checks against the canonical HistoricalStore one month at a
time (never materializing the full requested range in memory at once) and
merges the per-month CheckResults into one GateResult.

Known limitation, stated explicitly rather than silently assumed away:
"required trading dates" here is approximated as weekdays (Mon-Fri) in the
requested range. This repository has no exchange holiday calendar, so a
genuine market holiday will show up as a "missing date" false positive.
Anyone acting on a NOT READY result should cross-check flagged missing
dates against the actual NSE holiday calendar before treating them as a
real data gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List

from core.historical.quality_checks import CheckResult, run_all_checks
from core.historical.storage import HistoricalStore


@dataclass
class GateResult:
    ready: bool
    requested_range: tuple
    row_count: int
    missing_dates: List[str] = field(default_factory=list)
    failing_checks: List[CheckResult] = field(default_factory=list)
    checks: List[CheckResult] = field(default_factory=list)
    holiday_calendar_caveat: str = (
        "missing_dates is computed against weekdays only; this repo has no "
        "exchange holiday calendar, so genuine market holidays will appear "
        "here as false-positive gaps — cross-check against the real NSE "
        "calendar before treating a flagged date as an actual data problem."
    )

    def to_dict(self) -> Dict:
        return {
            "ready": self.ready,
            "requested_range": list(self.requested_range),
            "row_count": self.row_count,
            "missing_dates": self.missing_dates,
            "failing_checks": [c.to_dict() for c in self.failing_checks],
            "checks": [c.to_dict() for c in self.checks],
            "holiday_calendar_caveat": self.holiday_calendar_caveat,
        }


def _required_weekdays(start_date: str, end_date: str) -> List[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def _merge_check_results(results_by_name: Dict[str, List[CheckResult]]) -> List[CheckResult]:
    merged = []
    for name, results in results_by_name.items():
        checked = sum(r.checked for r in results)
        failed = sum(r.failed for r in results)
        details = []
        failing_dates = []
        for r in results:
            details.extend(r.details)
            failing_dates.extend(r.failing_dates)
        merged.append(
            CheckResult(
                name=name,
                passed=(failed == 0),
                checked=checked,
                failed=failed,
                details=details[:20],
                failing_dates=sorted(set(failing_dates)),
            )
        )
    return merged


def check_backtest_ready(
    store: HistoricalStore,
    start_date: str,
    end_date: str,
) -> GateResult:
    """The hard gate. Streams the store month-by-month, runs every
    quality check per chunk, merges results, and additionally checks
    that every required weekday in range has at least one row.

    ready=True only if: zero missing required dates AND every check passes
    with zero failures across the whole range.
    """
    required_dates = set(_required_weekdays(start_date, end_date))
    present_dates = set()
    results_by_name: Dict[str, List[CheckResult]] = {}
    total_rows = 0

    # Chunk by month to bound memory: query_range already streams row-by-row
    # from disk per month, but run_all_checks needs a list to do its
    # per-symbol grouping, so we materialize one month at a time rather
    # than the whole requested range.
    months = sorted({d[:7] for d in required_dates}) or [start_date[:7]]
    for month_key in months:
        month_start = f"{month_key}-01"
        # crude month-end: next month's day 1 minus a day, good enough since
        # query_range's BETWEEN is on date(timestamp) and end_date here only
        # needs to be >= the last real day of the month.
        year, mon = int(month_key[:4]), int(month_key[5:7])
        if mon == 12:
            next_month_start = f"{year + 1}-01-01"
        else:
            next_month_start = f"{year}-{mon + 1:02d}-01"
        month_rows = list(
            store.query_range(
                max(month_start, start_date),
                min((datetime.strptime(next_month_start, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"), end_date),
            )
        )
        total_rows += len(month_rows)
        present_dates.update({r["timestamp"][:10] for r in month_rows if r.get("timestamp")})

        if month_rows:
            report = run_all_checks(month_rows)
            for check in report.checks:
                results_by_name.setdefault(check.name, []).append(check)

    missing_dates = sorted(required_dates - present_dates)
    checks = _merge_check_results(results_by_name)
    failing_checks = [c for c in checks if not c.passed]

    ready = (len(missing_dates) == 0) and (len(failing_checks) == 0) and total_rows > 0

    return GateResult(
        ready=ready,
        requested_range=(start_date, end_date),
        row_count=total_rows,
        missing_dates=missing_dates,
        failing_checks=failing_checks,
        checks=checks,
    )
