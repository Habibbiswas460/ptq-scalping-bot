from datetime import datetime

from core.validation.signal_logger import build_decision_event


def test_build_decision_event_for_rejected_signal_contains_versions_and_hash():
    event = build_decision_event(
        params={
            "direction": "CE",
            "score": 84,
            "confidence": 82,
            "regime": "BULLISH",
            "details": {
                "weighted_score": 84,
                "market_quality_score": 81,
                "market_quality_grade": "A",
                "market_quality_components": {"spread": 20},
                "score_breakdown": {"ema": 20},
                "confidence_breakdown": {"raw_confidence": 82},
                "rsi": 58,
                "macd_hist": 1.2,
                "delta": 0.5,
                "vwap": 25100,
            },
        },
        was_taken=False,
        result_message="Rejected: spread high",
    )

    assert event["strategy_name"] == "SMART_SCALP"
    assert event["strategy_version"] == "v3.5.0"
    assert event["engine_version"] == "allocator_v1"
    assert len(event["config_hash"]) == 6
    assert event["decision_id"]
    assert event["parent_decision_id"] is None
    assert event["session_type"] in {"OPEN", "MID", "CLOSE"}
    assert event["accepted"] is False
    assert event["rejected"] is True
    assert event["reject_reason"] == "Rejected: spread high"
    assert event["regime_snapshot"]["trend"] == "bullish"


def test_build_decision_event_for_accepted_signal_marks_acceptance():
    event = build_decision_event(
        params={
            "timestamp": datetime.now(),
            "parent_decision_id": "parent-123",
            "direction": "PE",
            "score": 79,
            "confidence": 76,
            "position_size_recommendation": 150,
            "allocation_grade": "A",
            "details": {
                "weighted_score": 79,
                "market_quality_score": 75,
                "market_quality_grade": "B",
                "market_quality_components": {"spread": 18},
                "hard_reject_reason": None,
            },
        },
        was_taken=True,
        result_message="Accepted",
    )

    assert event["accepted"] is True
    assert event["rejected"] is False
    assert event["reject_reason"] is None
    assert event["position_size_recommendation"] == 150
    assert event["allocation_grade"] == "A"
    assert event["parent_decision_id"] == "parent-123"
