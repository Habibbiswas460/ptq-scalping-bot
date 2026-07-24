from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from core.services.database import (
    get_dvf_signal_by_decision_id,
    get_dvf_trade,
    get_dvf_trade_by_decision_id,
    log_dvf_trade_entry,
    log_dvf_trade_exit,
)


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        normalized = value.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


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
        "virtual_entry_time": market_context.get("entry_time", datetime.now(timezone.utc)),
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
    exit_time = _to_datetime(market_context.get("exit_time", datetime.now(timezone.utc)))
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
