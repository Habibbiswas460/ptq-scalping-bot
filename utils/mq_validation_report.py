"""Market quality validation report utility.

Generates three institutional validation blocks:
1) Market quality grade histogram
2) Hard reject reason statistics
3) Quality-band win-rate analysis
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.services.database import (
    get_confidence_calibration,
    get_confidence_win_rate_bands,
    get_market_quality_distribution,
    get_market_quality_grade_avg_pnl,
    get_hard_reject_stats,
    get_market_quality_grade_win_rate,
    get_market_quality_win_rate_bands,
)


def _histogram(rows: List[Dict], label_key: str, value_key: str, width: int = 32) -> List[str]:
    if not rows:
        return ["(no data)"]

    max_value = max(int(r.get(value_key, 0) or 0) for r in rows)
    max_value = max(max_value, 1)

    lines = []
    for row in rows:
        label = str(row.get(label_key, "UNKNOWN"))
        count = int(row.get(value_key, 0) or 0)
        bar_len = int((count / max_value) * width)
        bar = "#" * bar_len
        lines.append(f"{label:>8} | {bar:<{width}} {count}")
    return lines


def generate_report(days: int = 30) -> Dict:
    distribution = get_market_quality_distribution(days=days)
    hard_rejects = get_hard_reject_stats(days=days)
    win_rate_bands = get_market_quality_win_rate_bands(days=days)
    grade_win_rate = get_market_quality_grade_win_rate(days=days)
    confidence_win_rate = get_confidence_win_rate_bands(days=days)
    confidence_calibration = get_confidence_calibration(days=days)
    grade_avg_pnl = get_market_quality_grade_avg_pnl(days=days)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "market_quality_distribution": distribution,
        "hard_reject_stats": hard_rejects,
        "quality_vs_win_rate": win_rate_bands,
        "quality_grade_vs_win_rate": grade_win_rate,
        "confidence_vs_win_rate": confidence_win_rate,
        "confidence_calibration": confidence_calibration,
        "quality_grade_avg_pnl": grade_avg_pnl,
    }


def render_report_text(report: Dict) -> str:
    lines: List[str] = []

    lines.append("=" * 72)
    lines.append("P0-3 VALIDATION EVIDENCE - MARKET QUALITY")
    lines.append("=" * 72)
    lines.append(f"Window: last {report['days']} days")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    lines.append("[1] Market Quality Distribution (Histogram)")
    grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3, "REJECT": 4, "UNKNOWN": 5}
    distribution = sorted(
        report["market_quality_distribution"],
        key=lambda x: grade_order.get(str(x.get("grade", "UNKNOWN")), 99),
    )
    for line in _histogram(distribution, "grade", "count"):
        lines.append(line)
    lines.append("")

    lines.append("[2] Hard Reject Statistics")
    reject_rows = report["hard_reject_stats"]
    if not reject_rows:
        lines.append("(no data)")
    else:
        for row in reject_rows:
            reason = str(row.get("reason", "UNKNOWN"))
            count = int(row.get("count", 0) or 0)
            lines.append(f"{count:>6}  {reason}")
    lines.append("")

    lines.append("[3] Quality vs Win Rate (Score Bands)")
    band_rows = report["quality_vs_win_rate"]
    if not band_rows:
        lines.append("(no data)")
    else:
        lines.append(f"{'Band':>8}  {'Trades':>6}  {'Wins':>6}  {'WinRate%':>8}")
        for row in band_rows:
            band = str(row.get("quality_band", "N/A"))
            trades = int(row.get("trades", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            wr = float(row.get("win_rate_pct", 0) or 0)
            lines.append(f"{band:>8}  {trades:>6}  {wins:>6}  {wr:>8.2f}")
    lines.append("")

    lines.append("[4] Threshold Monitoring (Grade vs Win Rate)")
    grade_rows = report.get("quality_grade_vs_win_rate", [])
    if not grade_rows:
        lines.append("(no data)")
    else:
        lines.append(f"{'Grade':>8}  {'Trades':>6}  {'Wins':>6}  {'WinRate%':>8}")
        for row in grade_rows:
            grade = str(row.get("grade", "N/A"))
            trades = int(row.get("trades", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            wr = float(row.get("win_rate_pct", 0) or 0)
            lines.append(f"{grade:>8}  {trades:>6}  {wins:>6}  {wr:>8.2f}")
    lines.append("")

    lines.append("[5] Confidence vs Win Rate")
    conf_rows = report.get("confidence_vs_win_rate", [])
    if not conf_rows:
        lines.append("(no data)")
    else:
        lines.append(f"{'Conf':>8}  {'Trades':>6}  {'Wins':>6}  {'WinRate%':>8}")
        for row in conf_rows:
            band = str(row.get("confidence_band", "N/A"))
            trades = int(row.get("trades", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            wr = float(row.get("win_rate_pct", 0) or 0)
            lines.append(f"{band:>8}  {trades:>6}  {wins:>6}  {wr:>8.2f}")

    lines.append("")
    lines.append("[6] Confidence Calibration")
    calibration_rows = report.get("confidence_calibration", [])
    if not calibration_rows:
        lines.append("(no data)")
    else:
        lines.append(
            f"{'Conf':>8}  {'Trades':>6}  {'AvgConf%':>8}  {'WinRate%':>8}  {'CalErr%':>8}"
        )
        for row in calibration_rows:
            band = str(row.get("confidence_band", "N/A"))
            trades = int(row.get("trades", 0) or 0)
            avg_conf = float(row.get("avg_confidence_pct", 0) or 0)
            wr = float(row.get("realized_win_rate_pct", 0) or 0)
            cal_err = float(row.get("calibration_error_pct", 0) or 0)
            lines.append(f"{band:>8}  {trades:>6}  {avg_conf:>8.2f}  {wr:>8.2f}  {cal_err:>8.2f}")

    lines.append("")
    lines.append("[7] Average PnL by Grade")
    avg_pnl_rows = report.get("quality_grade_avg_pnl", [])
    if not avg_pnl_rows:
        lines.append("(no data)")
    else:
        lines.append(f"{'Grade':>8}  {'Trades':>6}  {'AvgPnL':>10}  {'TotalPnL':>10}")
        for row in avg_pnl_rows:
            grade = str(row.get("grade", "N/A"))
            trades = int(row.get("trades", 0) or 0)
            avg_pnl = float(row.get("avg_pnl", 0) or 0)
            total_pnl = float(row.get("total_pnl", 0) or 0)
            lines.append(f"{grade:>8}  {trades:>6}  {avg_pnl:>10.2f}  {total_pnl:>10.2f}")

    return "\n".join(lines)


def print_report(report: Dict) -> None:
    print(render_report_text(report))


def save_report(report: Dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def save_text_report(report_text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate market quality validation evidence report")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional JSON output path (example: logs/2026-07-02/mq_validation.json)",
    )
    args = parser.parse_args()

    report = generate_report(days=args.days)
    print_report(report)

    if args.out:
        save_report(report, Path(args.out))
        print()
        print(f"Saved JSON report to: {args.out}")


if __name__ == "__main__":
    main()
