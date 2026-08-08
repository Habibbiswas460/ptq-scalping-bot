"""Execution guard metrics report generator.

Reads daily JSONL events produced by state_machine execution guard and prints/writes summary.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from statistics import mean


def _load_events(path: str):
    events = []
    if not os.path.exists(path):
        return events
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def _build_summary(events):
    total = len(events)
    status_counts = Counter((e.get("status") or "unknown") for e in events)
    reason_counts = Counter((e.get("reason") or "unknown") for e in events)

    blocked = [e for e in events if e.get("status") == "blocked"]
    drift_vals = []
    stale_vals = []
    for e in blocked:
        details = e.get("details") or {}
        if details.get("check") == "drift" and details.get("drift_pct") is not None:
            drift_vals.append(float(details.get("drift_pct")))
        if details.get("check") == "stale" and details.get("age_ms") is not None:
            stale_vals.append(float(details.get("age_ms")))

    return {
        "total_events": total,
        "status_counts": dict(status_counts),
        "reason_counts": dict(reason_counts),
        "blocked_rate_pct": round((status_counts.get("blocked", 0) / total) * 100.0, 2) if total else 0.0,
        "avg_blocked_drift_pct": round(mean(drift_vals), 4) if drift_vals else None,
        "avg_blocked_age_ms": round(mean(stale_vals), 2) if stale_vals else None,
        "drift_blocks": len(drift_vals),
        "stale_blocks": len(stale_vals),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate execution guard metrics report")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Date folder in logs/readiness/YYYY-MM-DD")
    parser.add_argument("--output", default=None, help="Optional output JSON path")
    args = parser.parse_args()

    metrics_path = os.path.join("logs", "readiness", args.date, "execution_guard_metrics.jsonl")
    events = _load_events(metrics_path)
    summary = _build_summary(events)

    payload = {
        "date": args.date,
        "metrics_file": metrics_path,
        "summary": summary,
    }

    if args.output:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"Saved: {args.output}")

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
