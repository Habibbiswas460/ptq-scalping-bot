from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from config.constants import CONFIG
from core.services.database import log_dvf_signal


STRATEGY_NAME = "SMART_SCALP"
STRATEGY_VERSION = "v3.5.0"
ENGINE_VERSION = "allocator_v1"


def _config_hash() -> str:
    payload = json.dumps(CONFIG, sort_keys=True, default=str)
    strategy_path = Path(__file__).resolve().parents[2] / "config" / "strategy.json"
    if strategy_path.exists():
        payload += strategy_path.read_text(encoding="utf-8")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:6].upper()


def _session_type(timestamp: datetime) -> str:
    hhmm = timestamp.hour * 100 + timestamp.minute
    if 915 <= hhmm < 1030:
        return "OPEN"
    if 1030 <= hhmm < 1430:
        return "MID"
    return "CLOSE"


def build_decision_event(
    params: Dict,
    was_taken: bool,
    result_message: str,
    strategy_name: str = STRATEGY_NAME,
    strategy_version: str = STRATEGY_VERSION,
    engine_version: str = ENGINE_VERSION,
) -> Dict:
    """Build a normalized DVF Phase-1 decision record.

    Read-only contract: this function prepares an event payload only.
    """
    details = params.get("details", {}) if isinstance(params, dict) else {}
    market_quality_score = details.get("market_quality_score")
    hard_reject_reason = details.get("hard_reject_reason")
    rejected = not bool(was_taken)
    timestamp = params.get("timestamp", datetime.now())
    if not isinstance(timestamp, datetime):
        timestamp = datetime.now()
    regime_name = params.get("regime", details.get("regime"))
    regime_snapshot = {
        "trend": regime_name.lower() if isinstance(regime_name, str) else regime_name,
        "volatility": details.get("volatility_regime"),
        "vix": params.get("vix", details.get("vix")),
    }

    indicators_snapshot = {
        "rsi": details.get("rsi"),
        "macd_hist": details.get("macd_hist"),
        "regime": details.get("regime"),
        "vwap": details.get("vwap"),
        "delta": details.get("delta"),
        "oi_direction": details.get("oi_direction"),
        "oi_change_pct": details.get("oi_change_pct"),
        "volume_spike": details.get("volume_spike"),
        "close": details.get("close"),
        "ema9": details.get("ema9"),
        "ema21": details.get("ema21"),
    }

    return {
        "decision_id": params.get("decision_id") or str(uuid4()),
        "parent_decision_id": params.get("parent_decision_id"),
        "timestamp": timestamp,
        "direction": params.get("direction"),
        "session_type": params.get("session_type") or _session_type(timestamp),
        "strategy_name": strategy_name,
        "strategy_version": strategy_version,
        "engine_version": engine_version,
        "config_hash": _config_hash(),
        "weighted_score": params.get("score", details.get("weighted_score")),
        "confidence": params.get("confidence", 0),
        "market_quality_score": market_quality_score,
        "market_quality_grade": details.get("market_quality_grade"),
        "position_size_recommendation": params.get("position_size_recommendation"),
        "allocation_grade": params.get("allocation_grade"),
        "regime": regime_name,
        "regime_snapshot": regime_snapshot,
        "spread": details.get("spread") or details.get("spread_pct"),
        "volume": params.get("volume", details.get("volume")),
        "greeks": {
            "delta": details.get("delta"),
        },
        "indicators_snapshot": indicators_snapshot,
        "score_breakdown": details.get("score_breakdown", {}),
        "confidence_breakdown": details.get("confidence_breakdown", {}),
        "market_quality_components": details.get("market_quality_components", {}),
        "position_size_breakdown": params.get("position_size_breakdown", {}),
        "accepted": bool(was_taken),
        "rejected": rejected,
        "reject_reason": None if was_taken else result_message,
        "hard_reject": bool(hard_reject_reason),
        "hard_reject_reason": hard_reject_reason,
        "result": result_message,
    }


def log_decision_event(params: Dict, was_taken: bool, result_message: str) -> Optional[int]:
    """Persist a DVF decision event without affecting trading flow."""
    try:
        event = build_decision_event(params, was_taken, result_message)
        return log_dvf_signal(event)
    except Exception:
        return None
