import pytest

from core.engines.position_size_engine import PositionSizeEngine


def test_position_size_engine_output_contract_keys():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=30000,
        risk_budget={"daily_risk_budget_pct": 0.01, "remaining_risk_amount": 1200},
        weighted_score=86,
        confidence=84,
        market_quality=82,
        regime="BULLISH",
        volatility={"vix": 16},
        recovery_mode=False,
        daily_loss_state={"loss_utilization": 0.20},
        sl_points=6,
        lot_size=75,
    )

    expected_keys = {
        "risk_budget_used",
        "risk_amount",
        "position_size",
        "lots",
        "allocation_grade",
        "capped",
        "cap_reason",
        "breakdown",
    }
    assert expected_keys.issubset(set(result.keys()))

    breakdown_keys = {
        "score_multiplier",
        "confidence_multiplier",
        "market_quality_multiplier",
        "regime_multiplier",
        "volatility_multiplier",
        "recovery_multiplier",
        "daily_loss_multiplier",
        "soft_allocation_multiplier",
    }
    assert breakdown_keys.issubset(set(result["breakdown"].keys()))


def test_soft_adjustment_clamp_prevents_collapse():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=30000,
        risk_budget=0.01,
        weighted_score=5,
        confidence=10,
        market_quality=15,
        regime="UNKNOWN",
        volatility={"vix": 40},
        recovery_mode={"active": True, "severity": 1.0},
        daily_loss_state=0.9,
        sl_points=6,
        lot_size=75,
    )

    # Even for weak conditions, soft allocation remains clamped to configured minimum.
    assert result["breakdown"]["soft_allocation_multiplier"] >= 0.40


def test_remaining_risk_cap_is_enforced():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=30000,
        risk_budget={"daily_risk_budget_pct": 0.02, "remaining_risk_amount": 180},
        weighted_score=95,
        confidence=95,
        market_quality=95,
        regime="BULLISH",
        volatility={"vix": 12},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=6,
        lot_size=75,
    )

    assert result["risk_amount"] <= 180
    assert result["capped"] is True
    assert "remaining_risk_amount" in (result["cap_reason"] or "")


def test_lot_rounding_and_max_lots_cap():
    engine = PositionSizeEngine(config={"safety_caps": {"max_lots": 2}})

    result = engine.calculate(
        capital=100000,
        risk_budget=0.02,
        weighted_score=95,
        confidence=95,
        market_quality=95,
        regime="BULLISH",
        volatility={"vix": 10},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=3,
        lot_size=75,
    )

    assert result["lots"] <= 2
    assert result["position_size"] == result["lots"] * 75


def test_symbol_cap_uses_daily_budget_not_per_trade_budget():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=100000,
        risk_budget={
            "daily_risk_budget_amount": 5000,
            "per_trade_risk_amount": 1000,
            "remaining_risk_amount": 3000,
        },
        weighted_score=95,
        confidence=95,
        market_quality=95,
        regime="BULLISH",
        volatility={"vix": 12},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=10,
        lot_size=100,
    )

    # 40% of daily budget = 2000, so executed risk should not collapse to 400.
    assert result["risk_amount"] == 2000
    assert result["lots"] == 2
    assert "max_symbol_daily_risk_pct" in (result["cap_reason"] or "")


def test_persisted_risk_amount_uses_executed_lot_rounded_risk():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=30000,
        risk_budget={"remaining_risk_amount": 899},
        weighted_score=95,
        confidence=95,
        market_quality=95,
        regime="BULLISH",
        volatility={"vix": 12},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=6,
        lot_size=75,
    )

    assert result["lots"] == 1
    assert result["risk_amount"] == 450
    assert result["breakdown"]["requested_risk_amount"] > result["risk_amount"]
    assert result["breakdown"]["actual_risk_amount"] == 450
    assert result["risk_budget_used"] == pytest.approx(round(450 / 899, 4))


def test_legacy_size_multiplier_reduces_allocator_output():
    engine = PositionSizeEngine()

    without_legacy = engine.calculate(
        capital=30000,
        risk_budget={"remaining_risk_amount": 900},
        weighted_score=85,
        confidence=85,
        market_quality=85,
        regime="BULLISH",
        volatility={"vix": 15},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=6,
        lot_size=75,
    )
    with_legacy = engine.calculate(
        capital=30000,
        risk_budget={"remaining_risk_amount": 900, "legacy_size_multiplier": 0.5},
        weighted_score=85,
        confidence=85,
        market_quality=85,
        regime="BULLISH",
        volatility={"vix": 15},
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=6,
        lot_size=75,
    )

    assert with_legacy["breakdown"]["legacy_size_multiplier"] == 0.5
    assert with_legacy["risk_amount"] < without_legacy["risk_amount"]


def test_invalid_inputs_return_safe_zero_output():
    engine = PositionSizeEngine()

    result = engine.calculate(
        capital=0,
        risk_budget=0.01,
        weighted_score=80,
        confidence=80,
        market_quality=80,
        regime="BULLISH",
        volatility=15,
        recovery_mode=False,
        daily_loss_state=0.0,
        sl_points=6,
        lot_size=75,
    )

    assert result["position_size"] == 0
    assert result["allocation_grade"] == "REJECT"
    assert result["capped"] is True
