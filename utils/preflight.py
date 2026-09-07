"""Offline pre-open check: everything that can be known before the market opens.

`utils/market_readiness_checker.py` answers "is the feed alive and is the strategy
warm?" — it needs a live session and cannot be run the night before. This answers
the complementary question, and it is the one that has actually bitten:

    on the morning of 2026-09-08 the bot was fully healthy, fully connected, and
    could not have placed a single trade, because a persisted risk gate had latched
    shut Rs28 short of its limit and nothing reported that until a signal arrived.

Every check here is a fact that is already decided before the open — persisted risk
state, config arithmetic, the calendar, the contract master, whether the account can
fund the smallest tradeable position at all. Run it the night before or at 09:00:

    ./venv/bin/python -m utils.preflight

Exit code is 0 when nothing blocking failed, 1 otherwise, so it can gate a launch.
No credential is read, printed or needed; nothing here touches the network.
"""
from __future__ import annotations

import datetime
import sys
from typing import List, Tuple

# (name, passed, blocking, detail)
Check = Tuple[str, bool, bool, str]


def _risk_state_checks(cfg) -> List[Check]:
    from core.risk.risk_manager import RiskManager

    out: List[Check] = []
    rm = RiskManager(cfg, logger=None)

    can, details = rm.can_trade(spot_price=None)
    reasons = "; ".join(details.get("reasons", [])) or "no gate blocking"
    out.append(("Risk gates open", can, True, reasons))

    ok, reason = rm.check_drawdown()
    peak = rm.effective_peak_equity()
    out.append(("Drawdown gate", ok, True,
                reason or f"equity Rs{rm.current_equity:,.0f} vs peak Rs{peak:,.0f}"))

    cap = cfg["capital"]
    dd, daily = cap.get("max_drawdown_amount"), cap.get("max_daily_loss_amount")
    out.append(("Lifetime ceiling > daily ceiling", bool(dd and daily and dd > daily), True,
                f"lifetime Rs{dd} vs daily Rs{daily}"
                + ("" if (dd and daily and dd > daily)
                   else " — one full permitted losing day also trips the lifetime halt")))

    # A halt that cannot be escaped is not a limit, it is an outage. Report the
    # distance back, which is what tells the two apart.
    if not ok:
        need = (peak - rm.current_equity) - float(cap.get("max_drawdown_amount", 0))
        out.append(("Drawdown gate is escapable", False, True,
                    f"needs +Rs{need:.2f}, which requires the trading this gate blocks"))

    out.append(("Today's loss budget is fresh", rm.daily_pnl == 0.0, False,
                f"daily_pnl Rs{rm.daily_pnl:+.2f}"))
    out.append(("Recovery mode", True, False,
                "ACTIVE — sizing reduced" if rm.recovery_mode else "inactive"))
    return out


def _sizing_checks(cfg) -> List[Check]:
    """Can the account actually fund one lot? A soft multiplier that rounds a
    position to zero stops trading without ever calling it a stop — that is what
    produced 87 accepted signals and no orders on 2026-09-07."""
    from core.risk.risk_manager import RiskManager
    from core.engines.position_size_engine import PositionSizeEngine

    rm = RiskManager(cfg, logger=None)
    _, details = rm.can_trade(spot_price=None)
    rb = details.get("risk_budget", {})
    lot = int(cfg["trading"].get("lot_size", 1))
    eng = PositionSizeEngine()

    worst = None
    for sl in (5.0, 7.0, 8.0, 10.0, 12.0):
        a = eng.calculate(
            capital=rb.get("capital", cfg["capital"]["total_capital"]), risk_budget=rb,
            weighted_score=cfg.get("_min_score", 4), confidence=cfg.get("_min_conf", 70),
            market_quality=50, regime="TREND", volatility={"vix": 14.0},
            recovery_mode=rb.get("recovery_mode", {"active": False}),
            daily_loss_state=rb.get("daily_loss_state", {"loss_utilization": 0.0}),
            sl_points=sl, lot_size=lot)
        qty = int(a.get("position_size", 0) or 0)
        if worst is None or qty < worst[1]:
            worst = (sl, qty, a.get("cap_reason"))

    sl, qty, reason = worst
    return [("Sizing funds at least one lot", qty > 0, True,
             f"worst case sl={sl} -> qty={qty}" + (f" ({reason})" if reason else ""))]


def _calendar_checks(when: datetime.date) -> List[Check]:
    out: List[Check] = []
    try:
        from utils.trading_calendar import is_trading_day, holiday_reason
        trading = is_trading_day(when)
        out.append((f"{when} is a trading day", trading, True,
                    holiday_reason(when) or when.strftime("%A")))
    except Exception as e:
        out.append(("Trading calendar", False, False, f"{type(e).__name__}: {e}")) 

    try:
        from utils import instruments as I
        exp = I.nearest_expiry(when)
        dte = (exp - when).days if exp else None
        out.append(("Contract master", bool(exp), True,
                    f"nearest expiry {exp} ({dte} days), lot {I.lot_size()}, "
                    f"tick {I.tick_size()}, strike step {I.strike_step()}"))
        if exp == when:
            out.append(("Expiry day", True, False, "today is expiry — gamma/theta regime differs"))
    except Exception as e:
        out.append(("Contract master", False, True, f"{type(e).__name__}: {e}"))
    return out


def _cost_checks(cfg) -> List[Check]:
    """Costs off means every number the session reports is gross — which is the
    state the whole project was in until 2026-09-08."""
    costs = cfg.get("costs", {})
    on = bool(costs.get("enabled"))
    detail = f"brokerage Rs{costs.get('brokerage_per_order')}/order"
    if on:
        try:
            from research.costs import CostModel
            rt = CostModel(brokerage_per_order=float(costs.get("brokerage_per_order", 20.0))
                           ).round_trip(150.0, 150.0, int(cfg["trading"].get("lot_size", 65)))
            detail += f", round trip on one lot at Rs150 = Rs{rt:.2f}"
        except Exception:
            pass
    return [("Cost accounting on", on, False,
             detail if on else "P&L WILL BE REPORTED GROSS")]


def run(when: datetime.date | None = None) -> Tuple[List[Check], bool]:
    from config.constants import CONFIG, MIN_SCORE_TO_TRADE, MIN_CONFIDENCE

    cfg = dict(CONFIG)
    cfg["_min_score"], cfg["_min_conf"] = MIN_SCORE_TO_TRADE, MIN_CONFIDENCE
    when = when or (datetime.date.today() + datetime.timedelta(days=1))

    checks: List[Check] = []
    checks += _calendar_checks(when)
    checks += _risk_state_checks(cfg)
    checks += _sizing_checks(cfg)
    checks += _cost_checks(cfg)

    blocking_failed = any(not ok and blocking for _, ok, blocking, _ in checks)
    return checks, not blocking_failed


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    when = None
    if argv:
        try:
            when = datetime.date.fromisoformat(argv[0])
        except ValueError:
            print(f"usage: python -m utils.preflight [YYYY-MM-DD]   (got {argv[0]!r})")
            return 2

    checks, ok = run(when)
    target = when or (datetime.date.today() + datetime.timedelta(days=1))
    print(f"\nPRE-OPEN CHECK for {target}\n" + "=" * 72)
    for name, passed, blocking, detail in checks:
        mark = "PASS" if passed else ("FAIL" if blocking else "warn")
        print(f"  [{mark}] {name:<34} {detail}")
    print("=" * 72)
    print("READY — nothing blocking\n" if ok else
          "NOT READY — a blocking check failed; the session would place no trades\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
