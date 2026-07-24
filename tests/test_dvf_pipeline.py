import importlib
from datetime import datetime, timedelta

import pytest


def _reload_database_to_tmp(monkeypatch, tmp_path):
    import core.services.database as database_module

    db_file = tmp_path / "dvf_test.db"
    monkeypatch.setattr(database_module, "DB_PATH", str(db_file), raising=False)
    database_module.DatabaseManager._instance = None
    return importlib.reload(database_module)


def _sample_decision(decision_id: str = "dec-1"):
    from core.validation.signal_logger import build_decision_event

    return build_decision_event(
        {
            "decision_id": decision_id,
            "direction": "CE",
            "score": 88,
            "confidence": 84,
            "regime": "BULLISH",
            "position_size_recommendation": 150,
            "allocation_grade": "A",
            "details": {
                "weighted_score": 88,
                "market_quality_score": 82,
                "market_quality_grade": "A",
                "market_quality_components": {"spread": 20},
                "score_breakdown": {"ema": 20},
                "confidence_breakdown": {"raw_confidence": 84},
                "rsi": 57,
                "macd_hist": 1.2,
                "delta": 0.52,
                "close": 25050,
                "ema9": 25020,
                "ema21": 24980,
            },
        },
        was_taken=True,
        result_message="Accepted CE",
    )


def test_paper_executor_virtual_trade_lifecycle(monkeypatch, tmp_path):
    db_module = _reload_database_to_tmp(monkeypatch, tmp_path)
    import core.validation.signal_logger as signal_logger
    import core.validation.paper_executor as paper_executor

    signal_logger = importlib.reload(signal_logger)
    paper_executor = importlib.reload(paper_executor)

    decision = _sample_decision()
    first_id = db_module.log_dvf_signal(decision)
    second_id = db_module.log_dvf_signal(decision)
    assert first_id == second_id

    trade = paper_executor.simulate_entry_by_decision_id(decision["decision_id"], {
        "entry_price": 100.0,
        "risk_amount": 450,
        "entry_time": datetime.now(),
        "slippage_model": "fixed",
    })

    assert trade is not None
    assert trade["status"] == "OPEN"

    closed = paper_executor.simulate_exit_by_decision_id(decision["decision_id"], {
        "exit_price": 104.0,
        "exit_time": datetime.now() + timedelta(minutes=5),
        "exit_reason": "Target Hit",
        "mfe": 700,
        "mae": -120,
    })

    assert closed is not None
    assert closed["status"] == "CLOSED"
    assert closed["pnl"] > 0
    stored = db_module.get_dvf_trade_by_decision_id(decision["decision_id"])
    assert stored is not None
    assert stored["status"] == "CLOSED"


def test_decision_replay_reconstructs_timeline(monkeypatch, tmp_path):
    db_module = _reload_database_to_tmp(monkeypatch, tmp_path)
    import core.validation.signal_logger as signal_logger
    import core.validation.paper_executor as paper_executor
    import core.validation.decision_replay as decision_replay

    signal_logger = importlib.reload(signal_logger)
    paper_executor = importlib.reload(paper_executor)
    decision_replay = importlib.reload(decision_replay)

    decision = _sample_decision("dec-2")
    db_module.log_dvf_signal(decision)
    trade = paper_executor.simulate_entry_by_decision_id(decision["decision_id"], {"entry_price": 100.0, "risk_amount": 450})
    paper_executor.simulate_exit(trade, {"exit_price": 103.0, "exit_time": datetime.now() + timedelta(minutes=1), "exit_reason": "Exit"})

    replay = decision_replay.replay_decision(decision["decision_id"])
    assert replay is not None
    assert replay["signal"]["decision_id"] == decision["decision_id"]
    stages = [item["stage"] for item in replay["timeline"]]
    assert "signal_generated" in stages
    assert "decision_gate" in stages
    assert "virtual_entry" in stages
    assert "virtual_exit" in stages


def test_calibration_and_report_and_export(monkeypatch, tmp_path):
    db_module = _reload_database_to_tmp(monkeypatch, tmp_path)
    import core.validation.signal_logger as signal_logger
    import core.validation.paper_executor as paper_executor
    import core.validation.calibration_engine as calibration_engine
    import core.validation.validation_report as validation_report
    import core.validation.exporter as exporter

    signal_logger = importlib.reload(signal_logger)
    paper_executor = importlib.reload(paper_executor)
    calibration_engine = importlib.reload(calibration_engine)
    validation_report = importlib.reload(validation_report)
    exporter = importlib.reload(exporter)

    for idx, exit_price in enumerate([105.0, 95.0, 108.0], start=1):
        decision = _sample_decision(f"cal-{idx}")
        decision["confidence"] = 70 + idx * 10
        decision["weighted_score"] = 70 + idx * 10
        db_module.log_dvf_signal(decision)
        trade = paper_executor.simulate_entry_by_decision_id(decision["decision_id"], {"entry_price": 100.0, "risk_amount": 450})
        paper_executor.simulate_exit(trade, {"exit_price": exit_price, "exit_time": datetime.now() + timedelta(minutes=idx), "exit_reason": "Test Exit"})

    assert calibration_engine.score_calibration(30)
    assert calibration_engine.confidence_calibration(30)
    assert calibration_engine.market_quality_calibration(30)
    assert calibration_engine.position_size_calibration(30)

    report = validation_report.generate_daily_validation_report()
    rendered = validation_report.render_daily_validation_report(report)
    assert "DVF DAILY REPORT" in rendered
    assert report["signal_summary"]["total_signals"] >= 3

    historical_report = validation_report.generate_daily_validation_report("2000-01-01")
    assert historical_report["signal_summary"]["total_signals"] == 0

    same_day_1 = validation_report.generate_daily_validation_report("2026-07-05")
    same_day_2 = validation_report.generate_daily_validation_report("2026-07-05")
    assert same_day_1["report_date"] == same_day_2["report_date"]
    assert len(db_module.get_dvf_reports()) >= 1

    monkeypatch.setattr(exporter, "EXPORT_DIR", tmp_path / "exports", raising=False)
    csv_path = exporter.export_csv()
    json_path = exporter.export_json()
    db_path = exporter.export_sqlite_snapshot()
    html_path = exporter.export_html()

    for path in [csv_path, json_path, db_path, html_path]:
        assert path
        assert (tmp_path / "exports" / path.split("/")[-1]).exists()
