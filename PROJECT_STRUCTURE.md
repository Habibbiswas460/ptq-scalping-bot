# PTQ Scalping Bot Project Structure (RC2 Current)

## Top-Level

```text
PTQ-scalping bot/
├── app.py
├── run.sh
├── README.md
├── DOCUMENTATION.md
├── PROJECT_STRUCTURE.md
├── requirements.txt
├── config/
├── core/
├── strategies/
├── brokers/
├── utils/
├── tests/
├── logs/
├── data/
└── archive/
```

## Config
- [config/configuration.py](config/configuration.py): env helper and root resolution
- [config/constants.py](config/constants.py): runtime constants from env
- [config/validator.py](config/validator.py): startup validation
- [config/strategy.json](config/strategy.json): scoring and position-size config

## Core Runtime
- [core/main.py](core/main.py): main loop
- [core/runtime/state.py](core/runtime/state.py): shared RuntimeState
- [core/trading/broker.py](core/trading/broker.py): broker interface and execution
- [core/services/database.py](core/services/database.py): sqlite persistence

## Engines
- [core/engines/entry_engine.py](core/engines/entry_engine.py)
- [core/engines/exit_engine.py](core/engines/exit_engine.py)
- [core/engines/state_machine.py](core/engines/state_machine.py)
- [core/engines/market_quality_engine.py](core/engines/market_quality_engine.py)
- [core/engines/position_size_engine.py](core/engines/position_size_engine.py)
- [core/engines/weighted_score_engine.py](core/engines/weighted_score_engine.py)
- [core/engines/adaptive_confidence_engine.py](core/engines/adaptive_confidence_engine.py)

## Risk and Mode
- [core/risk/risk_manager.py](core/risk/risk_manager.py)
- [core/risk/validators.py](core/risk/validators.py)
- [core/risk/kill_switch.py](core/risk/kill_switch.py)
- [core/services/mode_switch.py](core/services/mode_switch.py)

## Strategy
- [strategies/smart_scalp_v3.py](strategies/smart_scalp_v3.py)

## Broker Integration
- [brokers/angel_one/client.py](brokers/angel_one/client.py)
- [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md)

India VIX canonical contract used by runtime:
- NSE / INDIAVIX / 99926017

## Validation (DVF)
- [core/validation/signal_logger.py](core/validation/signal_logger.py)
- [core/validation/paper_executor.py](core/validation/paper_executor.py)
- [core/validation/decision_replay.py](core/validation/decision_replay.py)
- [core/validation/calibration_engine.py](core/validation/calibration_engine.py)
- [core/validation/analytics.py](core/validation/analytics.py)
- [core/validation/validation_report.py](core/validation/validation_report.py)
- [core/validation/exporter.py](core/validation/exporter.py)

## Utilities
- [utils/helpers.py](utils/helpers.py)
- [utils/market_readiness_checker.py](utils/market_readiness_checker.py)
- [utils/mq_validation_report.py](utils/mq_validation_report.py)
- plus analytics, logger, monitoring helpers

## Tests
The suite includes legacy and RC2 coverage groups.

RC2-focused examples:
- [tests/test_smart_scalp_confidence.py](tests/test_smart_scalp_confidence.py)
- [tests/test_websocket.py](tests/test_websocket.py)
- [tests/test_dvf_pipeline.py](tests/test_dvf_pipeline.py)
- [tests/test_dvf_signal_logger.py](tests/test_dvf_signal_logger.py)
- [tests/test_position_size_engine.py](tests/test_position_size_engine.py)
- [tests/test_position_size_integration.py](tests/test_position_size_integration.py)
- [tests/test_readiness_policy.py](tests/test_readiness_policy.py)
- [tests/test_validator_config.py](tests/test_validator_config.py)

RC2 Freeze verification snapshot:
- 151 passed
- 1 skipped

## Archive
Historical reports and freeze records:
- [archive/reports](archive/reports)
- [archive/audits](archive/audits)
- [archive/freeze](archive/freeze)
- [archive/root_cause](archive/root_cause)

## Freeze Status
- RC1 technical verification completed.
- RC2 operational verification completed (pre-release).
- Freeze Candidate documentation aligned for RC2 commit preparation.
