from core.engines import entry_engine
from core.runtime import runtime_state


def _valid_tick(timestamp_ms: int = 1_700_000_000_000):
    return {
        "ltp": 100.0,
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "volume": 1000,
        "timestamp": timestamp_ms,
        "original_timestamp": timestamp_ms,
    }


def test_entry_engine_logs_warmup_to_dvf(monkeypatch):
    captured = []
    monkeypatch.setattr(entry_engine, "HAS_DVF", True)
    monkeypatch.setattr(entry_engine, "log_decision_event", lambda params, was_taken, result_message: captured.append((params, was_taken, result_message)) or 1)
    monkeypatch.setattr(entry_engine, "HAS_DB", False)

    runtime_state.clear_ticks()
    runtime_state.extend_ticks([_valid_tick()] * 5, max_ticks=240)
    should_enter, message = entry_engine.entry_signal(_valid_tick(), day_type="NORMAL")

    assert should_enter is False
    assert message == "Warming up..."
    assert captured[-1][1] is False
    assert captured[-1][2] == "Warming up..."


def test_entry_engine_logs_rejected_smart_scalp_decision_to_dvf(monkeypatch):
    captured = []
    monkeypatch.setattr(entry_engine, "HAS_DVF", True)
    monkeypatch.setattr(entry_engine, "log_decision_event", lambda params, was_taken, result_message: captured.append((params, was_taken, result_message)) or 1)
    monkeypatch.setattr(entry_engine, "HAS_DB", False)
    monkeypatch.setattr(entry_engine, "HAS_SMART_SCALP", True)
    monkeypatch.setattr(entry_engine, "smart_scalp_signal", lambda ticks: (False, "Rejected: spread high", {"direction": "CE", "confidence": 0, "details": {"market_quality_grade": "REJECT"}}))

    runtime_state.clear_ticks()
    runtime_state.extend_ticks([_valid_tick()] * 15, max_ticks=240)
    should_enter, message = entry_engine.entry_signal(_valid_tick(), day_type="NORMAL")

    assert should_enter is False
    assert message == "Rejected: spread high"
    assert captured[-1][1] is False
    assert captured[-1][2] == "Rejected: spread high"


def test_entry_engine_logs_accepted_smart_scalp_decision_to_dvf(monkeypatch):
    captured = []
    monkeypatch.setattr(entry_engine, "HAS_DVF", True)
    monkeypatch.setattr(entry_engine, "log_decision_event", lambda params, was_taken, result_message: captured.append((params, was_taken, result_message)) or 1)
    monkeypatch.setattr(entry_engine, "HAS_DB", False)
    monkeypatch.setattr(entry_engine, "HAS_SMART_SCALP", True)
    monkeypatch.setattr(entry_engine, "PAPER_TRADING", True)
    monkeypatch.setattr(entry_engine, "can_trade_ce", lambda rsi: (True, "OK"))
    monkeypatch.setattr(entry_engine, "smart_scalp_signal", lambda ticks: (
        True,
        "Accepted CE",
        {
            "direction": "CE",
            "confidence": 82,
            "regime": "BULLISH",
            "details": {
                "rsi": 56,
                "market_quality_score": 81,
                "market_quality_grade": "A",
            },
        },
    ))

    runtime_state.clear_ticks()
    runtime_state.extend_ticks([_valid_tick()] * 15, max_ticks=240)
    should_enter, message = entry_engine.entry_signal(_valid_tick(), day_type="NORMAL")

    assert should_enter is True
    assert message.startswith("Accepted CE")
    assert captured[-1][1] is True
    assert captured[-1][2].startswith("Accepted CE")
