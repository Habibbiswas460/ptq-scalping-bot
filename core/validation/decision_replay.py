from __future__ import annotations

import json
from typing import Dict, Optional

from core.services.database import get_dvf_signal_by_decision_id, get_dvf_trade, get_dvf_trade_by_decision_id


_JSON_FIELDS_SIGNAL = {
    "greeks",
    "indicators_snapshot",
    "score_breakdown",
    "confidence_breakdown",
    "market_quality_components",
    "position_size_breakdown",
    "regime_snapshot",
}


_JSON_FIELDS_TRADE = set()


def _decode_row(row: Optional[Dict], json_fields: set[str]) -> Optional[Dict]:
    if not row:
        return None
    decoded = dict(row)
    for field in json_fields:
        value = decoded.get(field)
        if isinstance(value, str) and value:
            try:
                decoded[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return decoded


def replay_decision(decision_id: str) -> Optional[Dict]:
    signal = _decode_row(get_dvf_signal_by_decision_id(decision_id), _JSON_FIELDS_SIGNAL)
    if not signal:
        return None

    timeline = [
        {"stage": "signal_generated", "timestamp": signal.get("timestamp")},
        {
            "stage": "decision_gate",
            "accepted": bool(signal.get("accepted")),
            "rejected": bool(signal.get("rejected")),
            "reason": signal.get("result"),
        },
    ]

    trade = _decode_row(get_dvf_trade_by_decision_id(decision_id), _JSON_FIELDS_TRADE)
    if trade:
        timeline.append({
            "stage": "virtual_entry",
            "timestamp": trade.get("virtual_entry_time"),
            "price": trade.get("virtual_entry_price"),
            "position_size": trade.get("position_size"),
        })
        if trade.get("status") == "CLOSED":
            timeline.append({
                "stage": "virtual_exit",
                "timestamp": trade.get("virtual_exit_time"),
                "price": trade.get("virtual_exit_price"),
                "pnl": trade.get("pnl"),
                "exit_reason": trade.get("exit_reason"),
            })

    return {
        "decision_id": decision_id,
        "signal": signal,
        "trade": trade,
        "timeline": timeline,
    }


def replay_trade(trade_id: int) -> Optional[Dict]:
    trade = _decode_row(get_dvf_trade(trade_id), _JSON_FIELDS_TRADE)
    if not trade:
        return None
    decision_id = trade.get("decision_id")
    return replay_decision(decision_id) if decision_id else {"trade": trade, "timeline": []}
