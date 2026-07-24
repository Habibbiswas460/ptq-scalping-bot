from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config.constants import ENABLE_WEBSOCKET, PAPER_TRADING, USE_LIVE_DATA
from core.engines.adaptive_confidence_engine import AdaptiveConfidenceEngine
from core.engines.market_quality_engine import MarketQualityEngine
from core.engines.position_size_engine import PositionSizeEngine
from core.engines.weighted_score_engine import WeightedScoreEngine
from core.risk.kill_switch import is_high_latency_paused, is_stale_data_kill_active
from core.trading.broker import BrokerInterface
from strategies.smart_scalp_v3 import get_strategy
from core.runtime import RuntimeState


CHECKER_VERSION = "v2.0.0"


def _is_paper_simulation_mode() -> bool:
    return bool(PAPER_TRADING and not USE_LIVE_DATA)


def _as_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _derive_outcome(overall_ready: bool, paper_live_preopen_mode: bool, strict_preopen_gate: bool) -> Tuple[str, bool]:
    """Return (overall_status, launch_allowed) from technical readiness and policy flags."""
    if paper_live_preopen_mode and overall_ready:
        overall_status = "DEFERRED"
    else:
        overall_status = "READY" if overall_ready else "NOT_READY"

    if overall_status == "READY":
        launch_allowed = True
    elif overall_status == "DEFERRED":
        launch_allowed = not strict_preopen_gate
    else:
        launch_allowed = False

    return overall_status, launch_allowed


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


def _status_icon(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _status_emoji(passed: bool) -> str:
    return "[OK]" if passed else "[X]"


def _tick_age_ms(tick: Dict[str, Any]) -> Optional[float]:
    ts = tick.get("original_timestamp") or tick.get("timestamp")
    if ts is None:
        return None

    try:
        ts_num = float(ts)
    except (TypeError, ValueError):
        return None

    # Heuristic: epoch ms if value is large.
    tick_ms = ts_num if ts_num > 1e10 else ts_num * 1000.0
    now_ms = time.time() * 1000.0
    return max(0.0, now_ms - tick_ms)


def _print_report(
    results: List[CheckResult],
    overall_ready: bool,
    overall_status: str,
    launch_allowed: bool,
    strict_preopen_gate: bool,
    started_at: datetime,
    summary: Dict[str, Any],
) -> None:
    print("=" * 30)
    print("PTQ Market Readiness Pro")
    print("=" * 30)
    print(f"Version: {CHECKER_VERSION}")
    print(f"Generated: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("")

    max_name = max(len(r.name) for r in results) if results else 10
    for item in results:
        name = item.name.ljust(max_name)
        gate = "BLOCK" if item.blocking else "INFO "
        print(f"{name}  {_status_emoji(item.passed)} {_status_icon(item.passed)}  [{gate}]  {item.detail}")

    print("\nOverall Status")
    print("")
    if overall_status == "DEFERRED":
        print("DEFERRED (PRE-OPEN)")
    elif overall_ready:
        print("READY FOR PAPER TRADING")
    else:
        print("NOT READY")
        failed = [r for r in results if (not r.passed) and r.blocking]
        if failed:
            print("")
            print("Reason:")
            for item in failed:
                print(f"- {item.name}: {item.detail}")

    print("")
    print(f"Technical Ready: {'YES' if overall_ready else 'NO'}")
    print(f"Launch Allowed: {'YES' if launch_allowed else 'NO'}")
    if overall_status == "DEFERRED":
        gate_mode = "STRICT_PREOPEN_GATE=true" if strict_preopen_gate else "STRICT_PREOPEN_GATE=false"
        print(f"Launch Policy: pre-open deferred ({gate_mode})")

    if summary:
        print("\nTelemetry")
        for key, value in summary.items():
            print(f"- {key}: {value}")


def _write_markdown_report(
    out_path: Path,
    results: List[CheckResult],
    overall_ready: bool,
    overall_status: str,
    launch_allowed: bool,
    strict_preopen_gate: bool,
    started_at: datetime,
    summary: Dict[str, Any],
) -> None:
    lines: List[str] = []
    lines.append("# PTQ Market Readiness Pro")
    lines.append("")
    lines.append(f"- Version: {CHECKER_VERSION}")
    lines.append(f"- Generated: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| Check | Status | Gate | Detail |")
    lines.append("|---|---|---|---|")
    for item in results:
        gate = "BLOCK" if item.blocking else "INFO"
        status = "PASS" if item.passed else "FAIL"
        lines.append(f"| {item.name} | {status} | {gate} | {item.detail} |")

    lines.append("")
    lines.append("## Overall")
    lines.append("")
    if overall_status == "DEFERRED":
        lines.append("DEFERRED (PRE-OPEN)")
    else:
        lines.append("READY FOR PAPER TRADING" if overall_ready else "NOT READY")

    lines.append("")
    lines.append(f"Technical Ready: {'YES' if overall_ready else 'NO'}")
    lines.append(f"Launch Allowed: {'YES' if launch_allowed else 'NO'}")
    if overall_status == "DEFERRED":
        gate_mode = "STRICT_PREOPEN_GATE=true" if strict_preopen_gate else "STRICT_PREOPEN_GATE=false"
        lines.append(f"Launch Policy: pre-open deferred ({gate_mode})")

    if summary:
        lines.append("")
        lines.append("## Telemetry")
        lines.append("")
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_profile(profile: str) -> Tuple[int, float, int, bool]:
    profile = (profile or "standard").lower()
    if profile == "quick":
        return 15, 0.5, 30, False
    if profile == "strict":
        return 45, 0.5, 60, True
    return 35, 0.5, 60, False


def _source_mix_stats(sampled_ticks: List[Dict[str, Any]]) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for tick in sampled_ticks:
        src = str(tick.get("data_source") or "UNKNOWN")
        stats[src] = stats.get(src, 0) + 1
    return stats


def _is_market_open_now() -> bool:
    now = datetime.now()
    # Monday=0 ... Sunday=6
    if now.weekday() >= 5:
        return False
    current_mins = now.hour * 60 + now.minute
    return 555 <= current_mins < 930  # 09:15 to 15:30


def run_readiness_check(
    sample_seconds: int,
    tick_interval: float,
    min_ticks: int,
    strict_engines: bool = False,
    broker_instance: Optional[BrokerInterface] = None,
    assume_connected: bool = False,
    close_broker_on_finish: bool = True,
    shared_state: Optional[RuntimeState] = None,
) -> Dict[str, Any]:
    started_at = datetime.now()
    checks: List[CheckResult] = []
    sampled_ticks: List[Dict[str, Any]] = []
    latency_samples: List[float] = []

    broker = broker_instance or BrokerInterface()
    owns_broker = broker_instance is None
    should_close_broker = close_broker_on_finish and owns_broker
    connected = False
    paper_sim_mode = _is_paper_simulation_mode()
    market_open_now = _is_market_open_now()
    paper_live_preopen_mode = bool(PAPER_TRADING and USE_LIVE_DATA and not market_open_now)
    strict_preopen_gate = _as_bool_env("STRICT_PREOPEN_GATE", default=False)

    try:
        if assume_connected:
            connected = True
        else:
            connected = broker.connect()
        checks.append(CheckResult("Broker Login", connected, "connect() success" if connected else "connect() failed"))

        has_real_client = connected and broker.broker_client is not None
        checks.append(
            CheckResult(
                "Angel Session",
                has_real_client,
                "authenticated SmartAPI client" if has_real_client else "fallback/simulation client",
            )
        )

        ws_ok = False
        ws_detail = "WebSocket disabled by config"
        if ENABLE_WEBSOCKET and USE_LIVE_DATA and connected:
            deadline = time.time() + 8
            while time.time() < deadline:
                status = broker.get_ws_status()
                if status.get("connected"):
                    ws_ok = True
                    break
                time.sleep(0.5)
            ws_detail = "connected" if ws_ok else "not connected"
        elif connected:
            ws_ok = True
        ws_check_index = len(checks)
        checks.append(CheckResult("WebSocket", ws_ok, ws_detail, blocking=True))

        rest_ok = False
        rest_detail = "REST check skipped"
        if has_real_client:
            try:
                ltp = broker.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                rest_ok = bool(ltp and ltp > 0)
                rest_detail = f"NIFTY LTP={ltp}" if ltp else "NIFTY LTP unavailable"
            except Exception as e:
                rest_ok = False
                rest_detail = f"REST probe error: {type(e).__name__}"
        checks.append(CheckResult("REST API", rest_ok, rest_detail, blocking=True))

        # Sample live ticks for feed, warm-up and indicator readiness.
        if connected:
            end_time = time.time() + sample_seconds
            while time.time() < end_time:
                tick = broker.get_tick()
                if tick:
                    sampled_ticks.append(tick)
                    if shared_state is not None:
                        shared_state.add_tick(tick)
                    age = _tick_age_ms(tick)
                    if age is not None:
                        latency_samples.append(age)
                time.sleep(tick_interval)

        if shared_state is not None:
            shared_state.rebuild_candles()

        live_sources = {"WEBSOCKET", "WEBSOCKET_SMOOTHED_VWAP", "REST", "REST_REFRESH"}
        if paper_live_preopen_mode:
            spot_live = True
            spot_detail = "pre-open: live spot deferred, waiting for market open"
        elif paper_sim_mode:
            spot_live = any(float(t.get("spot_price", 0) or 0) > 10000 for t in sampled_ticks)
            spot_detail = f"paper ticks={sum(1 for t in sampled_ticks if float(t.get('spot_price', 0) or 0) > 10000)}"
        else:
            spot_live = any(
                (t.get("data_source") in live_sources) and float(t.get("spot_price", 0) or 0) > 10000
                for t in sampled_ticks
            )
            spot_detail = f"live spot ticks={sum(1 for t in sampled_ticks if float(t.get('spot_price', 0) or 0) > 10000)}"
        checks.append(
            CheckResult(
                "Spot Feed",
                spot_live,
                spot_detail,
                blocking=not paper_live_preopen_mode,
            )
        )

        ce_ok = False
        pe_ok = False
        ce_detail = "unavailable"
        pe_detail = "unavailable"
        if paper_live_preopen_mode:
            ce_ok = True
            pe_ok = True
            ce_detail = "pre-open: CE validation deferred"
            pe_detail = "pre-open: PE validation deferred"
        elif has_real_client:
            strike = int(broker.current_strike or 0)
            if strike <= 0 and sampled_ticks:
                spot = float(sampled_ticks[-1].get("spot_price", 0) or 0)
                if spot > 0:
                    strike = int(round(spot / 50.0) * 50)

            if strike > 0:
                ce_symbol = broker._build_option_symbol(strike, "CE")
                pe_symbol = broker._build_option_symbol(strike, "PE")
                ce_token = broker._get_token(ce_symbol, "NFO")
                pe_token = broker._get_token(pe_symbol, "NFO")
                try:
                    ce_ltp = broker.broker_client.get_ltp("NFO", ce_symbol, ce_token) if ce_token else None
                    pe_ltp = broker.broker_client.get_ltp("NFO", pe_symbol, pe_token) if pe_token else None
                except Exception:
                    ce_ltp = None
                    pe_ltp = None
                ce_ok = bool(ce_ltp and ce_ltp > 0)
                pe_ok = bool(pe_ltp and pe_ltp > 0)
                ce_detail = f"{ce_symbol} LTP={ce_ltp}" if ce_ltp else f"{ce_symbol} missing"
                pe_detail = f"{pe_symbol} LTP={pe_ltp}" if pe_ltp else f"{pe_symbol} missing"
            else:
                ce_detail = "strike unavailable"
                pe_detail = "strike unavailable"

        checks.append(CheckResult("CE Feed", ce_ok, ce_detail, blocking=not paper_live_preopen_mode))
        checks.append(CheckResult("PE Feed", pe_ok, pe_detail, blocking=not paper_live_preopen_mode))

        source_stats = _source_mix_stats(sampled_ticks)
        ws_observed_ticks = source_stats.get("WEBSOCKET", 0) + source_stats.get("WEBSOCKET_SMOOTHED_VWAP", 0)
        if ws_observed_ticks > 0 and not checks[ws_check_index].passed:
            checks[ws_check_index].passed = True
            checks[ws_check_index].detail = f"observed websocket ticks during sample: {ws_observed_ticks}"
        simulation_ticks = source_stats.get("SIMULATION", 0)
        if paper_live_preopen_mode:
            source_quality_ok = True
            source_detail = f"pre-open: source gate deferred, sources={source_stats}"
        else:
            source_quality_ok = simulation_ticks == 0 if USE_LIVE_DATA else True
            source_detail = f"sources={source_stats}"
        checks.append(
            CheckResult(
                "Data Source Quality",
                source_quality_ok,
                source_detail,
                blocking=not paper_live_preopen_mode,
            )
        )

        latency_ok = False
        latency_detail = "no latency samples"
        if latency_samples:
            med = median(latency_samples)
            p95_idx = max(0, int(len(latency_samples) * 0.95) - 1)
            sorted_lats = sorted(latency_samples)
            p95 = sorted_lats[p95_idx]
            latency_ok = med <= 5000
            latency_detail = f"median={med:.0f}ms p95={p95:.0f}ms"
        checks.append(CheckResult("Tick Latency", latency_ok, latency_detail, blocking=True))

        warmup_ok = len(sampled_ticks) >= min_ticks
        checks.append(
            CheckResult(
                "Warm-up",
                warmup_ok,
                f"ticks={len(sampled_ticks)} need>={min_ticks}",
                blocking=not paper_live_preopen_mode,
            )
        )

        indicators_ok = False
        indicators: Dict[str, Any] = {}
        indicators_detail = "not calculated"
        if sampled_ticks:
            strategy = get_strategy()
            indicators = strategy.calculate_indicators(sampled_ticks)
            required = {"EMA_9", "EMA_21", "RSI", "ATR", "VWAP"}
            indicators_ok = bool(indicators) and required.issubset(set(indicators.keys()))
            indicators_detail = (
                "keys ready" if indicators_ok else f"missing={sorted(required - set(indicators.keys()))}"
            )
        checks.append(CheckResult("Indicators", indicators_ok, indicators_detail, blocking=not paper_live_preopen_mode))
        if indicators and shared_state is not None:
            shared_state.set_indicators(indicators)

        strategy_ready_ok = False
        strategy_ready_detail = "not evaluated"
        if sampled_ticks:
            strategy = get_strategy()
            sig, direction, confidence, details = strategy.generate_signal(sampled_ticks)
            reason = str((details or {}).get("reason", ""))
            # Strategy may return no-trade due to filters/time, but should not be in warm-up state.
            strategy_ready_ok = indicators_ok and ("warming" not in reason.lower())
            strategy_ready_detail = (
                f"signal={sig}, dir={direction or '-'}, conf={confidence}, reason={reason or 'n/a'}"
            )
        checks.append(CheckResult("Strategy Ready", strategy_ready_ok, strategy_ready_detail, blocking=not paper_live_preopen_mode))

        latest_tick = sampled_ticks[-1] if sampled_ticks else {}
        score_ok = False
        score_detail = "not evaluated"
        confidence_ok = False
        confidence_detail = "not evaluated"
        mq_ok = False
        mq_detail = "not evaluated"
        mq_gate_ok = False
        mq_gate_detail = "not evaluated"
        ps_ok = False
        ps_detail = "not evaluated"

        if indicators_ok and latest_tick:
            # AdaptiveConfidenceEngine expects second-based epoch timestamps.
            conf_tick = dict(latest_tick)
            ts = conf_tick.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 1e10:
                conf_tick["timestamp"] = ts / 1000.0

            score_engine = WeightedScoreEngine()
            score_pct, _ = score_engine.score(indicators, latest_tick, "CE", "NEUTRAL")
            score_ok = 0 <= score_pct <= 100
            score_detail = f"score={score_pct}%"

            conf_engine = AdaptiveConfidenceEngine()
            conf_pct, _ = conf_engine.score(indicators, conf_tick, score_pct, "CE", "NEUTRAL")
            confidence_ok = 0 <= conf_pct <= 100
            confidence_detail = f"confidence={conf_pct}%"

            mq_engine = MarketQualityEngine()
            mq_result = mq_engine.evaluate(
                latest_tick,
                indicators,
                greeks={"delta": float(latest_tick.get("delta", 0) or 0.5)},
                broker_status={
                    "market_open": True,
                    "kill_switch_active": is_stale_data_kill_active() or is_high_latency_paused(),
                    "ws_connected": broker.get_ws_status().get("connected", False) if ENABLE_WEBSOCKET else True,
                    "api_healthy": rest_ok,
                    "exchange_healthy": True,
                    "circuit_breaker_open": broker.get_ws_status().get("circuit_breaker_open", False),
                },
                validator_result={"is_valid": True},
            )
            mq_ok = isinstance(mq_result, dict) and "quality_score" in mq_result
            mq_detail = (
                f"quality={mq_result.get('quality_score')} grade={mq_result.get('grade')}"
                if mq_ok
                else "evaluation failed"
            )
            mq_gate_ok = bool(mq_result.get("passed", False)) if mq_ok else False
            mq_gate_detail = (
                f"passed={mq_result.get('passed')} action={mq_result.get('action')} reason={mq_result.get('reason')}"
                if mq_ok
                else "gate not available"
            )

            ps_engine = PositionSizeEngine()
            ps_result = ps_engine.calculate(
                capital=30000,
                risk_budget={"remaining_risk_pct": 0.01, "capital": 30000},
                weighted_score=score_pct,
                confidence=conf_pct,
                market_quality=mq_result.get("quality_score", 0) if mq_ok else 0,
                regime=str(indicators.get("regime") or "UNKNOWN"),
                volatility={"vix": 16, "atr": float(indicators.get("ATR", 0) or 0)},
                recovery_mode={"active": False},
                daily_loss_state={"loss_utilization": 0.0},
                sl_points=6,
                lot_size=25,
            )
            ps_ok = isinstance(ps_result, dict) and "position_size" in ps_result
            ps_detail = (
                f"qty={ps_result.get('position_size')} grade={ps_result.get('allocation_grade')}"
                if ps_ok
                else "allocation failed"
            )

        checks.append(CheckResult("Score Engine", score_ok, score_detail, blocking=not paper_live_preopen_mode))
        checks.append(CheckResult("Confidence Engine", confidence_ok, confidence_detail, blocking=not paper_live_preopen_mode))
        checks.append(CheckResult("Market Quality Engine", mq_ok, mq_detail, blocking=not paper_live_preopen_mode))
        checks.append(CheckResult("Market Quality Gate", mq_gate_ok, mq_gate_detail, blocking=strict_engines))
        checks.append(CheckResult("Position Size", ps_ok, ps_detail, blocking=not paper_live_preopen_mode))

        kill_ok = not is_stale_data_kill_active() and not is_high_latency_paused()
        kill_detail = "inactive" if kill_ok else "active"
        checks.append(CheckResult("Kill Switch", kill_ok, kill_detail, blocking=True))

        ws_status = broker.get_ws_status() if connected else {}
        circuit_ok = not bool(ws_status.get("circuit_breaker_open", False))
        checks.append(
            CheckResult(
                "Circuit Breaker",
                circuit_ok,
                f"open={ws_status.get('circuit_breaker_open', False)} reconnect_attempts={ws_status.get('reconnect_attempts', 'n/a')}",
                blocking=True,
            )
        )

        paper_mode_ok = bool(PAPER_TRADING)
        if PAPER_TRADING:
            mode_text = "paper+live" if USE_LIVE_DATA else "paper+simulated"
            paper_mode_detail = f"PAPER_TRADING={PAPER_TRADING}, USE_LIVE_DATA={USE_LIVE_DATA} ({mode_text})"
        else:
            paper_mode_detail = f"PAPER_TRADING={PAPER_TRADING}, USE_LIVE_DATA={USE_LIVE_DATA}"
        checks.append(CheckResult("Paper Mode", paper_mode_ok, paper_mode_detail, blocking=True))

        no_live_order_calls_ok = PAPER_TRADING
        checks.append(
            CheckResult(
                "No Live Order Calls",
                no_live_order_calls_ok,
                "checker does not place orders",
                blocking=True,
            )
        )

    finally:
        if should_close_broker:
            try:
                broker.logout()
            except Exception:
                pass

    overall_ready = all(item.passed for item in checks if item.blocking)
    overall_status, launch_allowed = _derive_outcome(
        overall_ready=overall_ready,
        paper_live_preopen_mode=paper_live_preopen_mode,
        strict_preopen_gate=strict_preopen_gate,
    )

    summary = {
        "checker_version": CHECKER_VERSION,
        "sampled_ticks": len(sampled_ticks),
        "sample_seconds": sample_seconds,
        "tick_interval_sec": tick_interval,
        "strict_engines": strict_engines,
        "strict_preopen_gate": strict_preopen_gate,
        "mode": f"PAPER_TRADING={PAPER_TRADING}, USE_LIVE_DATA={USE_LIVE_DATA}, ENABLE_WEBSOCKET={ENABLE_WEBSOCKET}",
    }

    if shared_state is not None:
        shared_state.update_market_snapshot(
            {
                "source_stats": _source_mix_stats(sampled_ticks),
                "sampled_ticks": len(sampled_ticks),
                "latency_samples": len(latency_samples),
                "rest_ok": rest_ok,
                "ws_ok": checks[2].passed if len(checks) > 2 else False,
                "paper_live_preopen_mode": paper_live_preopen_mode,
            }
        )
        shared_state.update_session_info(
            {
                "readiness_status": overall_status,
                "launch_allowed": launch_allowed,
                "technical_ready": overall_ready,
                "strict_preopen_gate": strict_preopen_gate,
            }
        )
        shared_state.increment_counter("readiness_runs", 1)

    _print_report(
        checks,
        overall_ready,
        overall_status,
        launch_allowed,
        strict_preopen_gate,
        started_at,
        summary,
    )

    return {
        "generated_at": started_at.isoformat(),
        "overall_ready": overall_ready,
        "technical_ready": overall_ready,
        "overall_status": overall_status,
        "launch_allowed": launch_allowed,
        "strict_preopen_gate": strict_preopen_gate,
        "checks": [item.__dict__ for item in checks],
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PTQ pre-open market readiness checker")
    parser.add_argument("--profile", choices=["quick", "standard", "strict"], default="standard", help="Readiness profile")
    parser.add_argument("--sample-seconds", type=int, default=None, help="How long to sample live ticks")
    parser.add_argument("--tick-interval", type=float, default=None, help="Tick poll interval in seconds")
    parser.add_argument("--min-ticks", type=int, default=None, help="Minimum ticks required for warm-up")
    parser.add_argument("--json-out", default="", help="Optional JSON output path")
    parser.add_argument("--md-out", default="", help="Optional markdown output path")
    args = parser.parse_args()

    p_sample, p_interval, p_min_ticks, p_strict = _resolve_profile(args.profile)

    result = run_readiness_check(
        sample_seconds=max(5, args.sample_seconds if args.sample_seconds is not None else p_sample),
        tick_interval=max(0.1, args.tick_interval if args.tick_interval is not None else p_interval),
        min_ticks=max(10, args.min_ticks if args.min_ticks is not None else p_min_ticks),
        strict_engines=p_strict,
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved JSON report: {out.as_posix()}")

    if args.md_out:
        md_path = Path(args.md_out)
        _write_markdown_report(
            md_path,
            [CheckResult(**item) for item in result["checks"]],
            bool(result["overall_ready"]),
            str(result.get("overall_status", "READY" if result.get("overall_ready") else "NOT_READY")),
            bool(result.get("launch_allowed", bool(result.get("overall_ready", False)))),
            bool(result.get("strict_preopen_gate", False)),
            datetime.fromisoformat(result["generated_at"]),
            result.get("summary", {}),
        )
        print(f"Saved markdown report: {md_path.as_posix()}")


if __name__ == "__main__":
    main()
