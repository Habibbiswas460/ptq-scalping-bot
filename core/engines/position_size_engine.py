from __future__ import annotations

from dataclasses import dataclass
import json
from math import floor
import os
from typing import Dict, Tuple, Union, Optional


Number = Union[int, float]


@dataclass
class ClampRange:
    minimum: float
    maximum: float

    def apply(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))


class PositionSizeEngine:
    """
    Institutional risk budget allocator scaffold.

    Scope of this class:
    - Convert a daily/remaining risk budget into executable quantity
    - Apply soft adjustments from score/confidence/quality/regime/volatility/recovery/loss state
    - Enforce safety caps and lot rounding

    Non-scope in scaffold phase:
    - No integration with entry/risk/broker call sites
    - No strategy behavior mutation
    """

    DEFAULT_CONFIG: Dict = {
        "base": {
            "default_risk_budget_pct": 0.01,
            "min_risk_budget_pct": 0.002,
            "max_risk_budget_pct": 0.02,
        },
        "soft_adjustment": {
            "weights": {
                "score": 0.18,
                "confidence": 0.18,
                "market_quality": 0.18,
                "regime": 0.12,
                "volatility": 0.14,
                "recovery": 0.10,
                "daily_loss": 0.10,
            },
            "final_allocation_clamp": [0.40, 1.10],
        },
        "ranges": {
            "score": [0.80, 1.10],
            "confidence": [0.80, 1.10],
            "market_quality": [0.75, 1.10],
            "regime": [0.85, 1.05],
            "volatility": [0.70, 1.00],
            "recovery": [0.50, 1.00],
            "daily_loss": [0.40, 1.00],
        },
        "safety_caps": {
            "max_capital_allocation_pct": 0.20,
            "max_symbol_daily_risk_pct": 0.40,
            "max_lots": 8,
            "min_executable_quantity": 1,
            "enforce_lot_rounding": True,
            "daily_risk_cap_pct": 0.03,
            "recovery_mode_cap_pct": 0.50,
        },
        "allocation_grades": {
            "A+": 1.02,
            "A": 0.95,
            "B": 0.85,
            "C": 0.70,
        },
    }

    def __init__(self, config: Optional[Dict] = None):
        strategy_config = self._load_strategy_config()
        self.config = self._merge_config(self.DEFAULT_CONFIG, strategy_config)
        self.config = self._merge_config(self.config, config or {})

    def calculate(
        self,
        capital: Number,
        risk_budget: Union[Number, Dict],
        weighted_score: Number,
        confidence: Number,
        market_quality: Union[Number, Dict],
        regime: str,
        volatility: Union[Number, Dict],
        recovery_mode: Union[bool, Dict],
        daily_loss_state: Union[Number, Dict],
        sl_points: Number,
        lot_size: int,
    ) -> Dict:
        """
        Public API contract for P0-4 scaffold.

        Returns
        - risk_budget_used
        - risk_amount
        - position_size
        - lots
        - allocation_grade
        - capped
        - cap_reason
        - breakdown (per-factor multipliers)
        """
        capital_value = max(0.0, float(capital))
        if capital_value <= 0 or lot_size <= 0 or float(sl_points) <= 0:
            return self._empty_result("Invalid capital/lot_size/sl_points")

        base_risk_amount = self._resolve_base_risk_amount(capital_value, risk_budget)

        score_multiplier = self._score_multiplier(weighted_score)
        confidence_multiplier = self._confidence_multiplier(confidence)
        market_quality_multiplier = self._market_quality_multiplier(market_quality)
        regime_multiplier = self._regime_multiplier(regime)
        volatility_multiplier = self._volatility_multiplier(volatility)
        recovery_multiplier = self._recovery_multiplier(recovery_mode)
        daily_loss_multiplier = self._daily_loss_multiplier(daily_loss_state)
        legacy_size_multiplier = self._legacy_size_multiplier(risk_budget)

        breakdown = {
            "score_multiplier": round(score_multiplier, 4),
            "confidence_multiplier": round(confidence_multiplier, 4),
            "market_quality_multiplier": round(market_quality_multiplier, 4),
            "regime_multiplier": round(regime_multiplier, 4),
            "volatility_multiplier": round(volatility_multiplier, 4),
            "recovery_multiplier": round(recovery_multiplier, 4),
            "daily_loss_multiplier": round(daily_loss_multiplier, 4),
            "legacy_size_multiplier": round(legacy_size_multiplier, 4),
        }

        # Soft-adjustment model: weighted deltas from 1.0 + clamp.
        adjusted_multiplier = self._soft_adjustment_multiplier(breakdown)
        adjusted_multiplier = self._apply_final_clamp(adjusted_multiplier * legacy_size_multiplier)

        preliminary_risk_amount = base_risk_amount * adjusted_multiplier
        capped_risk_amount, capped, cap_reason = self._apply_risk_caps(
            preliminary_risk_amount,
            capital_value,
            risk_budget,
            recovery_mode,
        )

        lot_risk = float(sl_points) * float(lot_size)
        lots = int(floor(capped_risk_amount / lot_risk)) if lot_risk > 0 else 0

        max_lots = int(self.config["safety_caps"]["max_lots"])
        if lots > max_lots:
            lots = max_lots
            capped = True
            cap_reason = self._append_reason(cap_reason, "max_lots")

        position_size = lots * int(lot_size)
        actual_risk_amount = lots * lot_risk

        min_qty = int(self.config["safety_caps"]["min_executable_quantity"])
        if 0 < position_size < min_qty:
            position_size = 0
            lots = 0
            actual_risk_amount = 0.0
            capped = True
            cap_reason = self._append_reason(cap_reason, "below_min_executable_quantity")

        risk_budget_used = (actual_risk_amount / base_risk_amount) if base_risk_amount > 0 else 0.0
        allocation_grade = self._allocation_grade(adjusted_multiplier)

        breakdown["soft_allocation_multiplier"] = round(adjusted_multiplier, 4)
        breakdown["requested_risk_amount"] = round(capped_risk_amount, 2)
        breakdown["actual_risk_amount"] = round(actual_risk_amount, 2)

        return {
            "risk_budget_used": round(risk_budget_used, 4),
            "risk_amount": round(actual_risk_amount, 2),
            "position_size": int(position_size),
            "lots": int(lots),
            "allocation_grade": allocation_grade,
            "capped": bool(capped),
            "cap_reason": cap_reason,
            "breakdown": breakdown,
        }

    def _merge_config(self, base: Dict, override: Dict) -> Dict:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_config(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _load_strategy_config(self) -> Dict:
        config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'strategy.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            return payload.get('strategy', {}).get('scoring_system', {}).get('position_size_engine', {})
        except Exception:
            return {}

    def _range(self, key: str) -> ClampRange:
        minimum, maximum = self.config["ranges"][key]
        return ClampRange(float(minimum), float(maximum))

    def _linear_scale(self, value: float, in_min: float, in_max: float, out_range: ClampRange) -> float:
        if in_max <= in_min:
            return out_range.minimum
        normalized = (value - in_min) / (in_max - in_min)
        raw = out_range.minimum + (out_range.maximum - out_range.minimum) * normalized
        return out_range.apply(raw)

    def _resolve_base_risk_amount(self, capital: float, risk_budget: Union[Number, Dict]) -> float:
        min_pct = float(self.config["base"]["min_risk_budget_pct"])
        max_pct = float(self.config["base"]["max_risk_budget_pct"])
        default_pct = float(self.config["base"]["default_risk_budget_pct"])

        if isinstance(risk_budget, dict):
            if "remaining_risk_amount" in risk_budget:
                amount = float(risk_budget.get("remaining_risk_amount") or 0)
                return max(0.0, amount)
            pct = float(risk_budget.get("remaining_risk_pct", risk_budget.get("daily_risk_budget_pct", default_pct)) or default_pct)
        elif isinstance(risk_budget, (int, float)):
            value = float(risk_budget)
            pct = value if value <= 1.0 else (value / 100.0)
        else:
            pct = default_pct

        pct = max(min_pct, min(max_pct, pct))
        return capital * pct

    def _score_multiplier(self, weighted_score: Number) -> float:
        return self._linear_scale(float(weighted_score), 0.0, 100.0, self._range("score"))

    def _confidence_multiplier(self, confidence: Number) -> float:
        return self._linear_scale(float(confidence), 0.0, 100.0, self._range("confidence"))

    def _market_quality_multiplier(self, market_quality: Union[Number, Dict]) -> float:
        if isinstance(market_quality, dict):
            score = float(market_quality.get("quality_score", market_quality.get("score", 0)) or 0)
        else:
            score = float(market_quality)
        return self._linear_scale(score, 0.0, 100.0, self._range("market_quality"))

    def _regime_multiplier(self, regime: str) -> float:
        regime_map = {
            "BULLISH": 1.03,
            "BEARISH": 1.03,
            "SIDEWAYS": 0.92,
            "UNKNOWN": 0.90,
        }
        return self._range("regime").apply(float(regime_map.get(str(regime).upper(), 0.90)))

    def _volatility_multiplier(self, volatility: Union[Number, Dict]) -> float:
        # Lower multiplier in high-volatility states.
        if isinstance(volatility, dict):
            vix = float(volatility.get("vix", 0) or 0)
            atr = float(volatility.get("atr", 0) or 0)
            indicator = vix if vix > 0 else atr
        else:
            indicator = float(volatility)

        if indicator <= 0:
            return self._range("volatility").apply(0.95)
        return self._linear_scale(indicator, 10.0, 40.0, ClampRange(self._range("volatility").maximum, self._range("volatility").minimum))

    def _recovery_multiplier(self, recovery_mode: Union[bool, Dict]) -> float:
        if isinstance(recovery_mode, dict):
            active = bool(recovery_mode.get("active", False))
            severity = float(recovery_mode.get("severity", 1.0) or 1.0)
            base = 1.0 - min(0.5, max(0.0, severity * 0.5)) if active else 1.0
        else:
            base = 0.75 if bool(recovery_mode) else 1.0
        return self._range("recovery").apply(base)

    def _daily_loss_multiplier(self, daily_loss_state: Union[Number, Dict]) -> float:
        if isinstance(daily_loss_state, dict):
            utilization = float(daily_loss_state.get("loss_utilization", 0.0) or 0.0)
        else:
            value = float(daily_loss_state)
            utilization = value if value <= 1.0 else value / 100.0
        base = 1.0 - min(0.6, max(0.0, utilization * 0.8))
        return self._range("daily_loss").apply(base)

    def _soft_adjustment_multiplier(self, breakdown: Dict[str, float]) -> float:
        weights = self.config["soft_adjustment"]["weights"]
        delta_sum = 0.0
        for key, weight in weights.items():
            metric_key = f"{key}_multiplier"
            multiplier = float(breakdown.get(metric_key, 1.0))
            delta_sum += (multiplier - 1.0) * float(weight)

        raw = 1.0 + delta_sum
        return self._apply_final_clamp(raw)

    def _apply_final_clamp(self, value: float) -> float:
        min_alloc, max_alloc = self.config["soft_adjustment"]["final_allocation_clamp"]
        return ClampRange(float(min_alloc), float(max_alloc)).apply(value)

    def _legacy_size_multiplier(self, risk_budget: Union[Number, Dict]) -> float:
        if isinstance(risk_budget, dict):
            value = float(risk_budget.get("legacy_size_multiplier", 1.0) or 1.0)
            return max(0.1, min(1.0, value))
        return 1.0

    def _apply_risk_caps(
        self,
        risk_amount: float,
        capital: float,
        risk_budget: Union[Number, Dict],
        recovery_mode: Union[bool, Dict],
    ) -> Tuple[float, bool, Optional[str]]:
        capped = False
        reason: Optional[str] = None
        result = max(0.0, risk_amount)

        safety_caps = self.config["safety_caps"]

        capital_cap = capital * float(safety_caps["max_capital_allocation_pct"])
        if result > capital_cap:
            result = capital_cap
            capped = True
            reason = self._append_reason(reason, "max_capital_allocation_pct")

        daily_cap = capital * float(safety_caps["daily_risk_cap_pct"])
        if result > daily_cap:
            result = daily_cap
            capped = True
            reason = self._append_reason(reason, "daily_risk_cap_pct")

        if isinstance(risk_budget, dict) and "remaining_risk_amount" in risk_budget:
            remaining_amount = max(0.0, float(risk_budget.get("remaining_risk_amount") or 0))
            if result > remaining_amount:
                result = remaining_amount
                capped = True
                reason = self._append_reason(reason, "remaining_risk_amount")

        if isinstance(risk_budget, dict) and "daily_risk_budget_amount" in risk_budget:
            symbol_cap_pct = float(safety_caps.get("max_symbol_daily_risk_pct", 1.0))
            symbol_cap = max(0.0, float(risk_budget.get("daily_risk_budget_amount") or 0) * symbol_cap_pct)
            if symbol_cap > 0 and result > symbol_cap:
                result = symbol_cap
                capped = True
                reason = self._append_reason(reason, "max_symbol_daily_risk_pct")

        recovery_active = bool(recovery_mode.get("active", False)) if isinstance(recovery_mode, dict) else bool(recovery_mode)
        if recovery_active:
            recovery_cap = capital * float(safety_caps["recovery_mode_cap_pct"])
            if result > recovery_cap:
                result = recovery_cap
                capped = True
                reason = self._append_reason(reason, "recovery_mode_cap_pct")

        return result, capped, reason

    def _allocation_grade(self, allocation_multiplier: float) -> str:
        grades = self.config["allocation_grades"]
        if allocation_multiplier >= float(grades["A+"]):
            return "A+"
        if allocation_multiplier >= float(grades["A"]):
            return "A"
        if allocation_multiplier >= float(grades["B"]):
            return "B"
        if allocation_multiplier >= float(grades["C"]):
            return "C"
        return "REJECT"

    def _append_reason(self, current: Optional[str], reason: str) -> str:
        if not current:
            return reason
        return f"{current},{reason}"

    def _empty_result(self, reason: str) -> Dict:
        return {
            "risk_budget_used": 0.0,
            "risk_amount": 0.0,
            "position_size": 0,
            "lots": 0,
            "allocation_grade": "REJECT",
            "capped": True,
            "cap_reason": reason,
            "breakdown": {
                "score_multiplier": 0.0,
                "confidence_multiplier": 0.0,
                "market_quality_multiplier": 0.0,
                "regime_multiplier": 0.0,
                "volatility_multiplier": 0.0,
                "recovery_multiplier": 0.0,
                "daily_loss_multiplier": 0.0,
                "soft_allocation_multiplier": 0.0,
            },
        }
