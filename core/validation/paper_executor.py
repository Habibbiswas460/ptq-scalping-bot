from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from core.services.database import (
    get_dvf_signal_by_decision_id,
    get_dvf_trade,
    get_dvf_trade_by_decision_id,
    get_open_dvf_trades,
    log_dvf_trade_entry,
    log_dvf_trade_exit,
)


def _to_datetime(value) -> datetime:
    """Normalize to a naive local-time datetime, matching the convention used
    everywhere else in this codebase (dvf_signals.timestamp, trades.entry_time,
    state_machine.py's now(), etc.). Tz-aware inputs — including rows written
    before this normalization, when this module used datetime.now(timezone.utc)
    — are converted to local time first so hold-time math stays correct."""
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str) and value:
        normalized = value.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            return datetime.now()
    return datetime.now()


def simulate_entry(decision: Dict, market_context: Dict) -> Dict:
    """Create a broker-independent virtual entry record for a DVF decision."""
    entry_price = float(market_context.get("entry_price", decision.get("premium") or 0) or 0)
    slippage_pct = float(market_context.get("entry_slippage_pct", 0) or 0)
    fill_price = round(entry_price * (1 + slippage_pct / 100.0), 2) if entry_price > 0 else 0.0

    trade = {
        "decision_id": decision.get("decision_id"),
        "status": "OPEN",
        "direction": decision.get("direction"),
        "session_type": decision.get("session_type"),
        "strategy_version": decision.get("strategy_version"),
        "engine_version": decision.get("engine_version"),
        "config_hash": decision.get("config_hash"),
        "position_size": decision.get("position_size_recommendation") or 0,
        "allocation_grade": decision.get("allocation_grade"),
        "market_quality_grade": decision.get("market_quality_grade"),
        "risk_amount": market_context.get("risk_amount", 0),
        "virtual_entry_time": market_context.get("entry_time", datetime.now()),
        "virtual_entry_price": fill_price,
        "slippage_model": market_context.get("slippage_model", "none"),
        "notes": market_context.get("notes"),
    }
    trade_id = log_dvf_trade_entry(trade)
    trade["id"] = trade_id
    return trade


def simulate_exit(position: Dict, market_context: Dict) -> Dict:
    """Close a virtual position and persist realized paper-trade metrics."""
    entry_price = float(position.get("virtual_entry_price", 0) or 0)
    exit_price = float(market_context.get("exit_price", entry_price) or 0)
    exit_slippage_pct = float(market_context.get("exit_slippage_pct", 0) or 0)
    filled_exit_price = round(exit_price * (1 - exit_slippage_pct / 100.0), 2) if exit_price > 0 else 0.0
    qty = int(position.get("position_size") or 0)

    if str(position.get("direction", "CE")).upper() == "PE":
        pnl = round((entry_price - filled_exit_price) * qty, 2)
    else:
        pnl = round((filled_exit_price - entry_price) * qty, 2)

    risk_amount = float(position.get("risk_amount", 0) or 0)
    pnl_pct = round((pnl / risk_amount) * 100, 2) if risk_amount > 0 else 0.0
    entry_time = _to_datetime(position.get("virtual_entry_time"))
    exit_time = _to_datetime(market_context.get("exit_time", datetime.now()))
    hold_time_sec = max(0, int((exit_time - entry_time).total_seconds()))
    mfe = float(market_context.get("mfe", max(0.0, pnl)) or 0)
    mae = float(market_context.get("mae", min(0.0, pnl)) or 0)

    payload = {
        "status": "CLOSED",
        "virtual_exit_time": exit_time,
        "virtual_exit_price": filled_exit_price,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "hold_time_sec": hold_time_sec,
        "mfe": mfe,
        "mae": mae,
        "exit_reason": market_context.get("exit_reason"),
        "notes": market_context.get("notes"),
    }
    log_dvf_trade_exit(int(position["id"]), payload)
    return {**position, **payload}


def simulate_entry_by_decision_id(decision_id: str, market_context: Dict) -> Optional[Dict]:
    decision = get_dvf_signal_by_decision_id(decision_id)
    if not decision:
        return None
    return simulate_entry(decision, market_context)


def simulate_exit_by_decision_id(decision_id: str, market_context: Dict) -> Optional[Dict]:
    trade = get_dvf_trade_by_decision_id(decision_id)
    if not trade:
        return None
    return simulate_exit(trade, market_context)


def get_virtual_trade(trade_id: int) -> Optional[Dict]:
    return get_dvf_trade(trade_id)


# ═══════════════════════════════════════════════════════════════════════
# LIVE-LOOP OBSERVER: auto-tracks accepted decisions as virtual positions.
# Read-only per the DVF golden rule — never raises into the caller and
# never feeds anything back into real trading decisions.
# ═══════════════════════════════════════════════════════════════════════
_OPEN_VIRTUAL_POSITIONS: Dict[str, Dict] = {}
_MAX_OPEN_VIRTUAL_POSITIONS = 200
_MAX_VIRTUAL_HOLD_SEC = 1800  # safety expiry if a matching-symbol tick never returns


def record_decision(decision: Dict, was_taken: bool, tick: Dict) -> None:
    """Open a virtual DVF position for an accepted decision so it can be tracked to a paper exit."""
    try:
        if not was_taken or not isinstance(decision, dict) or not isinstance(tick, dict):
            return
        decision_id = decision.get("decision_id")
        direction = decision.get("direction")
        symbol = tick.get("symbol")
        entry_price = float(tick.get("ltp", 0) or 0)
        if not decision_id or direction not in ("CE", "PE") or not symbol or entry_price <= 0:
            return
        if decision_id in _OPEN_VIRTUAL_POSITIONS or len(_OPEN_VIRTUAL_POSITIONS) >= _MAX_OPEN_VIRTUAL_POSITIONS:
            return

        from config.constants import SL_POINTS_FIXED, TP_POINTS_FIXED, LOT_SIZE

        details = decision.get("details", {}) if isinstance(decision.get("details"), dict) else {}
        sl_points = float(decision.get("sl_points") or details.get("sl_points") or SL_POINTS_FIXED)
        tp_points = float(decision.get("tp_points") or details.get("tp_points") or TP_POINTS_FIXED)
        # entry_engine's decision payload never sets position_size_recommendation, so
        # fall back to one lot instead of 0 — otherwise virtual pnl = price_diff * 0
        # always computes to 0, which silently breaks DVF's win/loss tracking.
        position_size = decision.get("position_size_recommendation") or LOT_SIZE

        trade = simulate_entry(
            {
                "decision_id": decision_id,
                "direction": direction,
                "session_type": decision.get("session_type"),
                "strategy_version": decision.get("strategy_version"),
                "engine_version": decision.get("engine_version"),
                "config_hash": decision.get("config_hash"),
                "position_size_recommendation": position_size,
                "allocation_grade": decision.get("allocation_grade"),
                "market_quality_grade": details.get("market_quality_grade"),
            },
            {
                "entry_price": entry_price,
                "entry_time": datetime.now(),
                "risk_amount": decision.get("risk_amount") or 0,
            },
        )
        trade["symbol"] = symbol
        trade["direction"] = direction
        trade["sl_price"] = entry_price - sl_points if direction == "CE" else entry_price + sl_points
        trade["tp_price"] = entry_price + tp_points if direction == "CE" else entry_price - tp_points
        trade["opened_at"] = datetime.now()
        _OPEN_VIRTUAL_POSITIONS[decision_id] = trade
    except Exception:
        pass


def update_open_positions(tick: Dict) -> None:
    """Close tracked virtual positions on a virtual SL/TP hit or a max-hold safety expiry."""
    try:
        if not _OPEN_VIRTUAL_POSITIONS or not isinstance(tick, dict):
            return
        tick_symbol = tick.get("symbol")
        ltp = float(tick.get("ltp", 0) or 0)
        now_ts = datetime.now()

        for decision_id in list(_OPEN_VIRTUAL_POSITIONS.keys()):
            position = _OPEN_VIRTUAL_POSITIONS[decision_id]
            hold_sec = (now_ts - position["opened_at"]).total_seconds()
            exit_reason = None
            exit_price = None

            if tick_symbol and tick_symbol == position.get("symbol") and ltp > 0:
                direction = position.get("direction")
                if direction == "CE":
                    if ltp <= position["sl_price"]:
                        exit_reason = "SL (virtual)"
                    elif ltp >= position["tp_price"]:
                        exit_reason = "TP (virtual)"
                else:
                    if ltp >= position["sl_price"]:
                        exit_reason = "SL (virtual)"
                    elif ltp <= position["tp_price"]:
                        exit_reason = "TP (virtual)"
                if exit_reason:
                    exit_price = ltp

            if exit_reason is None and hold_sec >= _MAX_VIRTUAL_HOLD_SEC:
                exit_reason = "Virtual max hold"
                exit_price = ltp if (tick_symbol == position.get("symbol") and ltp > 0) else position.get("virtual_entry_price", 0)

            if exit_reason:
                simulate_exit(position, {"exit_price": exit_price, "exit_time": now_ts, "exit_reason": exit_reason})
                del _OPEN_VIRTUAL_POSITIONS[decision_id]
    except Exception:
        pass


def reconcile_stale_open_positions(max_age_sec: int = _MAX_VIRTUAL_HOLD_SEC) -> int:
    """Force-close DVF trades left OPEN by a previous, now-dead process.

    _OPEN_VIRTUAL_POSITIONS lives only in this process's memory, so if the bot
    restarts before a tracked position's in-loop safety expiry fires, the
    dvf_trades row is already INSERTed as OPEN and nothing will ever call
    simulate_exit on it again — it's orphaned OPEN forever. Call this once at
    startup to sweep those up (flat exit at entry price, since we have no
    tick history to know what actually happened to it).
    """
    closed = 0
    try:
        now_ts = datetime.now()
        for row in get_open_dvf_trades():
            entry_time = _to_datetime(row.get("virtual_entry_time"))
            if (now_ts - entry_time).total_seconds() < max_age_sec:
                continue
            simulate_exit(row, {
                "exit_price": row.get("virtual_entry_price"),
                "exit_time": now_ts,
                "exit_reason": "Virtual max hold (reconciled on restart)",
            })
            closed += 1
    except Exception:
        pass
    return closed
