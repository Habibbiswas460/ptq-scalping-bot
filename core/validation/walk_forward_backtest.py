"""
Walk-forward backtest utility for robustness checks.

Runs rolling windows over a historical CSV and summarizes stability metrics.
"""

import argparse
import json
import os
from datetime import timedelta
from statistics import mean, median
from typing import Dict, List

from core.backtest import Backtester, load_historical_data


def _run_window(candles: List[Dict], args) -> Dict:
    bt = Backtester(
        initial_capital=args.capital,
        sl_points=args.sl,
        tp_points=args.tp,
        use_position_size_engine=args.use_position_size_engine,
        position_size_risk_budget_pct=args.position_size_risk_budget_pct,
        position_size_daily_cap_pct=args.position_size_daily_cap_pct,
    )
    strategy = bt._get_strategy()
    strategy.min_confidence = args.min_confidence
    result = bt.run_backtest(candles)
    return {
        "start_date": result.start_date,
        "end_date": result.end_date,
        "total_pnl": round(result.total_pnl, 2),
        "trades": result.total_trades,
        "win_rate_pct": round(result.win_rate, 2),
        "profit_factor": round(result.profit_factor, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 2),
    }


def _build_windows(data: List[Dict], window_days: int, step_days: int) -> List[List[Dict]]:
    if not data:
        return []

    start = data[0]["timestamp"]
    end = data[-1]["timestamp"]
    windows = []
    cursor = start
    window_delta = timedelta(days=window_days)
    step_delta = timedelta(days=step_days)

    while cursor + window_delta <= end:
        w_end = cursor + window_delta
        candles = [c for c in data if cursor <= c["timestamp"] <= w_end]
        if candles:
            windows.append(candles)
        cursor += step_delta

    return windows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run rolling walk-forward backtests")
    parser.add_argument("--data", required=True, help="Path to historical CSV")
    parser.add_argument("--output", default="logs/backtest/walk_forward", help="Output directory")
    parser.add_argument("--window-days", type=int, default=30, help="Window size in days")
    parser.add_argument("--step-days", type=int, default=10, help="Window step in days")
    parser.add_argument("--capital", type=float, default=30000)
    parser.add_argument("--sl", type=float, default=7)
    parser.add_argument("--tp", type=float, default=18)
    parser.add_argument("--min-confidence", type=int, default=72)
    parser.add_argument("--use-position-size-engine", action="store_true")
    parser.add_argument("--position-size-risk-budget-pct", type=float, default=0.04)
    parser.add_argument("--position-size-daily-cap-pct", type=float, default=0.05)
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    data = load_historical_data(args.data)
    windows = _build_windows(data, args.window_days, args.step_days)

    if not windows:
        raise SystemExit("No windows built. Check data range or window/step values.")

    print(f"Running walk-forward: windows={len(windows)} | window_days={args.window_days} | step_days={args.step_days}")

    rows = []
    for i, candles in enumerate(windows, start=1):
        print(f"  window {i}/{len(windows)} ...")
        rows.append(_run_window(candles, args))

    positive = [r for r in rows if r["total_pnl"] > 0]
    pnl_values = [r["total_pnl"] for r in rows]
    # Ignore sentinel-like PF values that represent "no losses" windows.
    finite_pf_values = [r["profit_factor"] for r in rows if 0 < r["profit_factor"] < 50]
    summary = {
        "windows": len(rows),
        "positive_windows": len(positive),
        "positive_ratio_pct": round((len(positive) / len(rows)) * 100.0, 2),
        "avg_pnl": round(mean(pnl_values), 2),
        "median_pnl": round(median(pnl_values), 2),
        "best_pnl": round(max(pnl_values), 2),
        "worst_pnl": round(min(pnl_values), 2),
        "avg_trades": round(mean(r["trades"] for r in rows), 2),
        "avg_win_rate_pct": round(mean(r["win_rate_pct"] for r in rows), 2),
        "avg_profit_factor": round(mean(finite_pf_values), 2) if finite_pf_values else None,
        "avg_max_drawdown_pct": round(mean(r["max_drawdown_pct"] for r in rows), 2),
        "settings": {
            "sl": args.sl,
            "tp": args.tp,
            "min_confidence": args.min_confidence,
            "use_position_size_engine": args.use_position_size_engine,
            "position_size_risk_budget_pct": args.position_size_risk_budget_pct,
            "position_size_daily_cap_pct": args.position_size_daily_cap_pct,
        },
    }

    payload = {"summary": summary, "windows": rows}
    json_path = os.path.join(args.output, "walk_forward_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("Saved:", json_path)
    print("Summary:", summary)


if __name__ == "__main__":
    main()
