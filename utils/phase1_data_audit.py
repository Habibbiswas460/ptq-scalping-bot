#!/usr/bin/env python3
"""Rebuild of the historical-data Phase-1 quality gate referenced by
data/historical/v3_5_0/EXTERNAL_DATA_INSTRUCTIONS.md and demonstrated by
archive/audits/DATA_AUDIT_REPORT.md (2026-07-05, which returned NO-GO — the
original script was never committed to git and is gone, per
archive/audits/ORIGINAL_CEPE_GENERATOR_AUDIT.md).

Runs every check defined in core/historical/quality_checks.py (the same
checks the hard BACKTEST READY gate in core/historical/gate.py uses)
against a canonical CSV or a date range already loaded into the
HistoricalStore, and prints an explicit PASS/FAIL report with affected
row/date counts. Never repairs or interpolates.

Usage:
    # Against a canonical CSV (e.g. straight out of ingest_cepe_and_audit.py):
    python utils/phase1_data_audit.py --source path/to/canonical.csv

    # Against whatever is already loaded into the HistoricalStore:
    python utils/phase1_data_audit.py --store --start 2026-03-01 --end 2026-09-01
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from typing import Dict, List

from core.historical.quality_checks import run_all_checks
from core.historical.schema import CANONICAL_COLUMNS


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


def load_csv_rows(path: str) -> List[Dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = {c: r.get(c) for c in CANONICAL_COLUMNS}
            for col in ("strike", "volume", "oi"):
                row[col] = _to_int(row[col])
            for col in ("ltp", "bid", "ask", "delta", "gamma", "theta", "vega", "iv", "spot_ref"):
                row[col] = _to_float(row[col])
            rows.append(row)
    return rows


def render_report(report_dict: Dict) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("PHASE-1 HISTORICAL DATA AUDIT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    lines.append(f"Row count:  {report_dict['row_count']}")
    lines.append(f"Date range: {report_dict['date_range']}")
    lines.append("")
    lines.append(f"{'Check':30s} {'Status':6s} {'Checked':>10s} {'Failed':>10s}")
    lines.append("-" * 60)
    for c in report_dict["checks"]:
        status = "PASS" if c["passed"] else "FAIL"
        lines.append(f"{c['name']:30s} {status:6s} {c['checked']:10d} {c['failed']:10d}")
        if not c["passed"] and c["details"]:
            for d in c["details"][:5]:
                lines.append(f"    - {d}")
            if c["failing_dates"]:
                lines.append(f"    affected dates: {c['failing_dates'][:10]}{'...' if len(c['failing_dates']) > 10 else ''}")
    lines.append("")
    lines.append(f"Overall Phase-1 status: {'PASS' if report_dict['all_passed'] else 'FAIL'}")
    lines.append(f"Backtest gate: {'GO' if report_dict['all_passed'] else 'NO-GO'}")
    if not report_dict["all_passed"]:
        lines.append("Do not proceed to backtest until all checks pass.")
    lines.append("=" * 70)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="Canonical CSV to audit")
    parser.add_argument("--store", action="store_true", help="Audit a range from the HistoricalStore instead of a CSV")
    parser.add_argument("--store-dir", default=None)
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD), required with --store")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD), required with --store")
    parser.add_argument("--json-out", default=None, help="Optional path to also write the report as JSON")
    args = parser.parse_args(argv)

    if not args.source and not args.store:
        parser.error("one of --source or --store is required")

    if args.source:
        rows = load_csv_rows(args.source)
    else:
        if not (args.start and args.end):
            parser.error("--start and --end are required with --store")
        from core.historical.storage import HistoricalStore, DEFAULT_STORE_DIR

        store = HistoricalStore(args.store_dir or DEFAULT_STORE_DIR)
        rows = list(store.query_range(args.start, args.end))

    report = run_all_checks(rows)
    report_dict = report.to_dict()

    print(render_report(report_dict))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, default=str)
        print(f"\nJSON report written: {args.json_out}")

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
