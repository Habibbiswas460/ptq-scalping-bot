# PTQ Scalping Bot Project Structure

This document shows the project tree and the purpose of the main folders and files in the repository.

## Root-level structure

```text
PTQ-scalping bot/
├── .env
├── .env.example
├── .gitignore
├── ACK_WARNING_VERIFICATION_2026-07-27_TO_2026-07-31.md
├── CHANGELOG.md
├── DOCUMENTATION.md
├── LICENSE
├── PROJECT_STRUCTURE.md
├── README.md
├── RC2_STABILIZATION_AUDIT_2026-07-27_TO_2026-07-31.md
├── SESSION_COMPLETION.md
├── app.py
├── cleanup.sh
├── pyproject.toml
├── requirements.txt
├── archive/
├── audit_tmp/
├── brokers/
├── config/
├── core/
├── data/
├── logs/
├── prc/
├── strategies/
├── tcp/
├── tests/
├── utils/
├── venv/
└── .venv/
```

## Top-level files and their purpose

- [app.py](app.py): main application entry point that validates configuration and starts the bot.
- [README.md](README.md): high-level overview and usage instructions.
- [DOCUMENTATION.md](DOCUMENTATION.md): detailed documentation for the project.
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md): repository structure and module overview.
- [CHANGELOG.md](CHANGELOG.md): change history and release notes.
- [LICENSE](LICENSE): license information.
- [pyproject.toml](pyproject.toml): Python project metadata and tooling configuration.
- [requirements.txt](requirements.txt): Python package dependencies.
- [cleanup.sh](cleanup.sh): maintenance script for cleanup tasks.
- [SESSION_COMPLETION.md](SESSION_COMPLETION.md): session summary and completion notes.
- [ACK_WARNING_VERIFICATION_2026-07-27_TO_2026-07-31.md](ACK_WARNING_VERIFICATION_2026-07-27_TO_2026-07-31.md): audit/verification notes.
- [RC2_STABILIZATION_AUDIT_2026-07-27_TO_2026-07-31.md](RC2_STABILIZATION_AUDIT_2026-07-27_TO_2026-07-31.md): RC2 stabilization audit notes.

## Configuration

```text
config/
├── configuration.py
├── constants.py
├── strategy.json
└── validator.py
```

- [config/configuration.py](config/configuration.py): loads environment variables and resolves the repo root.
- [config/constants.py](config/constants.py): central trading constants and thresholds.
- [config/strategy.json](config/strategy.json): strategy scoring, entry, and sizing configuration.
- [config/validator.py](config/validator.py): validates configuration at startup.

## Core application runtime

```text
core/
├── __init__.py
├── backtest.py
├── main.py
├── data/
├── engines/
├── risk/
├── runtime/
├── services/
├── trading/
└── validation/
```

- [core/main.py](core/main.py): main live trading loop with reconnect, market waiting, and trade orchestration.
- [core/backtest.py](core/backtest.py): backtesting support for strategy evaluation.
- [core/__init__.py](core/__init__.py): package marker.

### Core subfolders

- [core/data](core/data): market and historical data handling modules.
- [core/engines](core/engines): decision engines for entry, exit, scoring, confidence, and sizing.
- [core/risk](core/risk): risk controls, kill-switch logic, and validation helpers.
- [core/runtime](core/runtime): runtime state container.
- [core/services](core/services): database, telegram, mode switching, and session helpers.
- [core/trading](core/trading): broker and trade execution management.
- [core/validation](core/validation): validation, replay, analytics, and reporting utilities.

## Trading engines

```text
core/engines/
├── adaptive_confidence_engine.py
├── entry_engine.py
├── exit_engine.py
├── market_quality_engine.py
├── position_size_engine.py
├── state_machine.py
└── weighted_score_engine.py
```

- [core/engines/entry_engine.py](core/engines/entry_engine.py): creates entry signals.
- [core/engines/exit_engine.py](core/engines/exit_engine.py): evaluates exit conditions.
- [core/engines/state_machine.py](core/engines/state_machine.py): tracks the current trading state.
- [core/engines/market_quality_engine.py](core/engines/market_quality_engine.py): filters based on market quality.
- [core/engines/position_size_engine.py](core/engines/position_size_engine.py): calculates risk-based position size.
- [core/engines/weighted_score_engine.py](core/engines/weighted_score_engine.py): scores signals using weighted factors.
- [core/engines/adaptive_confidence_engine.py](core/engines/adaptive_confidence_engine.py): adjusts confidence dynamically.

## Risk and runtime helpers

```text
core/risk/
├── greeks_calc.py
├── greeks_validator.py
├── kill_switch.py
├── risk_manager.py
├── session_trend.py
└── validators.py
```

- [core/risk/risk_manager.py](core/risk/risk_manager.py): central risk management controller.
- [core/risk/validators.py](core/risk/validators.py): data and signal validation rules.
- [core/risk/kill_switch.py](core/risk/kill_switch.py): emergency stop and kill-switch logic.
- [core/risk/greeks_calc.py](core/risk/greeks_calc.py): Greek calculation helpers.
- [core/risk/greeks_validator.py](core/risk/greeks_validator.py): validation of Greek inputs.
- [core/risk/session_trend.py](core/risk/session_trend.py): session trend tracking.

```text
core/services/
├── database.py
├── mode_switch.py
├── paper_trade_validator.py
├── session_manager.py
└── telegram_bot.py
```

- [core/services/database.py](core/services/database.py): stores trade and state data.
- [core/services/mode_switch.py](core/services/mode_switch.py): controls trading mode transitions.
- [core/services/paper_trade_validator.py](core/services/paper_trade_validator.py): validates paper-trading behavior.
- [core/services/session_manager.py](core/services/session_manager.py): handles session lifecycle activities.
- [core/services/telegram_bot.py](core/services/telegram_bot.py): Telegram notifications and dashboard integration.

```text
core/trading/
├── broker.py
└── trade_manager.py
```

- [core/trading/broker.py](core/trading/broker.py): broker interface and order execution logic.
- [core/trading/trade_manager.py](core/trading/trade_manager.py): manages trade lifecycle operations.

```text
core/runtime/
├── __init__.py
└── state.py
```

- [core/runtime/state.py](core/runtime/state.py): shared runtime state for the trading bot.

```text
core/validation/
├── analytics.py
├── calibration_engine.py
├── decision_replay.py
├── execution_guard_report.py
├── exporter.py
├── paper_executor.py
├── signal_logger.py
├── validation_report.py
└── walk_forward_backtest.py
```

- [core/validation/signal_logger.py](core/validation/signal_logger.py): logs validation signals and decisions.
- [core/validation/paper_executor.py](core/validation/paper_executor.py): replay and paper execution support.
- [core/validation/decision_replay.py](core/validation/decision_replay.py): replays decisions for analysis.
- [core/validation/calibration_engine.py](core/validation/calibration_engine.py): calibration utilities.
- [core/validation/analytics.py](core/validation/analytics.py): analytics and report generation helpers.
- [core/validation/validation_report.py](core/validation/validation_report.py): validation summary reporting.
- [core/validation/exporter.py](core/validation/exporter.py): exports validation results.
- [core/validation/execution_guard_report.py](core/validation/execution_guard_report.py): execution guard reporting.
- [core/validation/walk_forward_backtest.py](core/validation/walk_forward_backtest.py): walk-forward backtest support.

## Broker integration

```text
brokers/
└── angel_one/
    ├── DOCUMENTATION.md
    ├── __init__.py
    ├── client.py
    └── exceptions.py
```

- [brokers/angel_one/client.py](brokers/angel_one/client.py): SmartAPI/Angel One client wrapper.
- [brokers/angel_one/exceptions.py](brokers/angel_one/exceptions.py): broker-specific exception definitions.
- [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md): broker integration documentation.

## Strategy layer

```text
strategies/
├── __init__.py
└── smart_scalp_v3.py
```

- [strategies/smart_scalp_v3.py](strategies/smart_scalp_v3.py): main trading strategy implementation with multi-factor scoring.

## Utilities

```text
utils/
├── __init__.py
├── analytics.py
├── greeks.py
├── helpers.py
├── logger.py
├── market_readiness_checker.py
├── monitoring.py
├── mq_validation_report.py
```

- [utils/helpers.py](utils/helpers.py): shared helper utilities.
- [utils/greeks.py](utils/greeks.py): Greek calculation helpers.
- [utils/logger.py](utils/logger.py): bot logging setup.
- [utils/market_readiness_checker.py](utils/market_readiness_checker.py): readiness checks for trading sessions.
- [utils/monitoring.py](utils/monitoring.py): monitoring functions.
- [utils/mq_validation_report.py](utils/mq_validation_report.py): market-quality validation reporting.
- [utils/analytics.py](utils/analytics.py): analytics utilities.

## Data and logs

```text
data/
├── historical/
└── trades.log
```

- [data/historical](data/historical): historical market data input directory.
- [data/trades.log](data/trades.log): trade log storage.

```text
logs/
├── 2026-07-27/
├── 2026-07-28/
├── 2026-07-29/
├── 2026-07-30/
├── 2026-07-31/
├── 2026-08-03/
├── 2026-08-04/
├── 2026-08-05/
├── 2026-08-06/
├── 2026-08-07/
├── 2026-08-08/
├── backtest/
├── backup_logs/
└── readiness/
```

- [logs](logs): runtime and diagnostic logs for live trading, backtests, and readiness checks.

## Archive and audit folders

```text
archive/
├── audits/
├── freeze/
├── reports/
└── root_cause/
```

- [archive](archive): historical reports and archived audit material.

```text
audit_tmp/
├── ack_occurrences_2026-07-27.tsv
├── ack_occurrences_2026-07-28.tsv
├── ack_occurrences_2026-07-29.tsv
├── ack_occurrences_2026-07-30.tsv
└── ack_occurrences_2026-07-31.tsv
```

- [audit_tmp](audit_tmp): temporary audit and verification output files.

## Process and technical notes

```text
prc/
├── PRC_ACK_WEBSOCKET_INVESTIGATION.md
├── PRC_ARCHITECTURE_CERTIFICATION.md
├── PRC_GITHUB_REVIEW_VERIFICATION.md
├── PRC_MASTER_OPERATIONAL_ANALYSIS.md
├── PRC_MASTER_OPERATIONAL_AUDIT.md
├── PRC_RELEASE_READINESS_CERTIFICATION.md
├── PRC_STRIKE_ROTATION_INVESTIGATION.md
└── PRC_TRADE_ENGINE_INVESTIGATION.md
```

- [prc](prc): process review and operational certification notes.

```text
tcp/
├── TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md
├── TPC_ENTRY_DECISION_CERTIFICATION.md
├── TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md
├── TPC_STRATEGY_EFFECTIVENESS_AUDIT.md
├── TPC_TRADE_FORENSICS.md
├── TPC_TRADE_REPLAY_AND_LOSS_ANALYSIS.md
```

- [tcp](tcp): strategy and trade replay analysis documents.

## Tests

```text
tests/
├── __init__.py
├── test_analytics.py
├── test_backtest_execution_guard_regression.py
├── test_batch_market_data.py
├── test_config_validator.py
├── test_dvf_phase1_integration.py
├── test_dvf_pipeline.py
├── test_dvf_signal_logger.py
├── test_exit_engine_regression.py
├── test_exit_engine_sequence_regression.py
├── test_greeks.py
├── test_greeks_caching.py
├── test_kill_switch.py
├── test_phases_3_4_5.py
├── test_position_size_engine.py
├── test_position_size_integration.py
├── test_readiness_policy.py
├── test_smart_scalp_confidence.py
├── test_tick_freshness.py
├── test_validator_config.py
├── test_validators.py
└── test_websocket.py
```

- [tests](tests): regression, integration, and validation tests for the trading pipeline.

## Summary

This repository is organized around a live trading entry point, modular core engines, risk controls, broker integration, validation utilities, and test coverage.
