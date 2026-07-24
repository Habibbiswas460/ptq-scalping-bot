# P0-4 Position Size Engine Documentation (RC2 Current)

## Status
- Original scaffold phase: complete
- Runtime integration: complete in RC2
- RC1 technical verification completed.
- RC2 operational verification completed (pre-release).

## Engine Implementation
- [core/engines/position_size_engine.py](core/engines/position_size_engine.py)

## Runtime Integration
Integrated through:
- [core/engines/state_machine.py](core/engines/state_machine.py)
- [core/risk/risk_manager.py](core/risk/risk_manager.py) for risk budget payload

The runtime uses PositionSizeEngine output to derive final order quantity before broker placement.

## Public API
Class:
- PositionSizeEngine

Method:
- calculate(capital, risk_budget, weighted_score, confidence, market_quality, regime, volatility, recovery_mode, daily_loss_state, sl_points, lot_size)

## Output Contract
Returned fields:
- risk_budget_used
- risk_amount
- position_size
- lots
- allocation_grade
- capped
- cap_reason
- breakdown

Breakdown includes per-factor multipliers and final soft-allocation multiplier.

## Configuration Source
Configured from:
- [config/strategy.json](config/strategy.json)

Path:
- strategy.scoring_system.position_size_engine

Sections:
- base
- soft_adjustment
- ranges
- safety_caps
- allocation_grades

## Operational Model
Position size is determined by:
1. base risk budget resolution
2. weighted contextual multipliers (score, confidence, market quality, regime, volatility, recovery, daily loss)
3. clamp and cap enforcement
4. lot rounding and executable quantity checks

## Validation and Tests
Primary tests:
- [tests/test_position_size_engine.py](tests/test_position_size_engine.py)
- [tests/test_position_size_integration.py](tests/test_position_size_integration.py)

RC2 Freeze verification snapshot:
- 151 passed
- 1 skipped

## Freeze Note
This document now reflects current RC2 integrated behavior, not scaffold-only planning.
