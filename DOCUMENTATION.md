# PTQ Scalping Bot Documentation Index (RC2)

## Release State
- RC1 technical verification completed.
- RC2 operational verification completed (pre-release).
- Freeze Candidate: pre-commit stage.

## Core Documents
- [README.md](README.md): current runtime and operational overview
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md): current folder and module map
- [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md): SmartAPI integration and contract references

## Configuration Documentation
Current model:
- [config/configuration.py](config/configuration.py): env helper functions and project root
- [config/constants.py](config/constants.py): runtime constants and env keys
- [config/strategy.json](config/strategy.json): scoring, market quality, and position sizing config

Configuration precedence summary:
1. defaults in strategy.json and code
2. env values loaded through constants helpers
3. runtime merge in strategy and engine layers

## Runtime Architecture Docs
- RuntimeState: [core/runtime/state.py](core/runtime/state.py)
- Main loop: [core/main.py](core/main.py)
- Entry and state orchestration: [core/engines/entry_engine.py](core/engines/entry_engine.py), [core/engines/state_machine.py](core/engines/state_machine.py)
- Strategy: [strategies/smart_scalp_v3.py](strategies/smart_scalp_v3.py)
- Broker path: [core/trading/broker.py](core/trading/broker.py), [brokers/angel_one/client.py](brokers/angel_one/client.py)

## Feature-Specific Freeze Docs
- Market Quality Gate: [archive/freeze/DOCUMENTATION_P0_3_MARKET_QUALITY_FREEZE.md](archive/freeze/DOCUMENTATION_P0_3_MARKET_QUALITY_FREEZE.md)
- Position Size Engine: [archive/freeze/DOCUMENTATION_P0_4_POSITION_SIZE_SCAFFOLD.md](archive/freeze/DOCUMENTATION_P0_4_POSITION_SIZE_SCAFFOLD.md)
- DVF: [archive/freeze/DOCUMENTATION_P0_5_DVF.md](archive/freeze/DOCUMENTATION_P0_5_DVF.md)
- Final freeze summary: [archive/freeze/DOCUMENTATION_P0_FINAL_FREEZE.md](archive/freeze/DOCUMENTATION_P0_FINAL_FREEZE.md)
- DVF runtime status: [archive/freeze/DVF_STATUS.md](archive/freeze/DVF_STATUS.md)

## India VIX Contract (Canonical)
Current contract used by runtime:
- exchange: NSE
- symbol: INDIAVIX
- token: 99926017

References:
- [config/constants.py](config/constants.py)
- [utils/helpers.py](utils/helpers.py)
- [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md)

## Paper Trading and Operations
Operational workflow is implemented through:
- readiness path in [run.sh](run.sh) and [utils/market_readiness_checker.py](utils/market_readiness_checker.py)
- runtime decision pipeline in [core/main.py](core/main.py)
- evidence and reports under [archive/reports](archive/reports) and [archive/audits](archive/audits)

## Historical and Audit Records
All historical reports, audits, and root-cause plans are archived under [archive](archive):
- [archive/reports](archive/reports)
- [archive/audits](archive/audits)
- [archive/freeze](archive/freeze)
- [archive/root_cause](archive/root_cause)

## Test Baseline
RC2 Freeze verification snapshot:
- 151 passed
- 1 skipped
- 0 failed

Key RC2 test groups include:
- websocket and confidence behavior
- DVF pipeline and signal logger
- position size engine and integration
- readiness and validator config coverage

## Code Freeze Note
This documentation set is frozen to current RC2 behavior and should be updated only via explicit freeze-maintenance steps.
