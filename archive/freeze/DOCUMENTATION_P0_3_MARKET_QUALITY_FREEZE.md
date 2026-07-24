# P0-3 Market Quality Gate v1.0 - Design Freeze

## Objective
Market Quality Gate does not create a signal. It validates execution quality.

If market quality is poor, output must be NO_TRADE even when weighted score and confidence are high.

## Pipeline Position
Indicators -> Weighted Score -> Adaptive Confidence -> Market Quality Gate -> Dynamic Position Size -> Entry

## Engine Contract
Implemented contract in [core/engines/market_quality_engine.py](core/engines/market_quality_engine.py):

- evaluate(tick, indicators, greeks, broker_status, validator_result)
- output keys:
  - passed
  - quality_score
  - grade
  - hard_reject
  - hard_reject_reason
  - components
  - reason
  - action

Backward-compatible wrapper `score(indicators, latest_tick)` is retained for legacy call sites.

## Hard Reject Layer
Immediate reject if any condition is true:

- invalid tick
- market closed
- kill switch active
- websocket disconnected
- exchange/api unhealthy
- circuit breaker open
- spread too high
- stale tick
- liquidity below minimum

Hard reject bypasses soft score.

## Soft Quality Score Weights (Total 100)
Final freeze weights:

- spread: 25
- liquidity: 20
- freshness: 15
- volatility: 15
- execution: 10
- greeks: 10
- session: 5

## Decision and Grade
- A+: score >= 90
- A: score >= 80
- B: score >= 70
- C: score >= 60
- REJECT: score < 60

Entry gate threshold is score >= 60.

Action bands:
- ALLOW: >= 70 (and >= 85 as excellent)
- SMALL_SIZE: 60-69
- REJECT: < 60

## Strategy Integration
Integrated in [strategies/smart_scalp_v3.py](strategies/smart_scalp_v3.py):

- strategy calls market_quality_engine.evaluate(...)
- on `passed == False`, strategy returns NO_TRADE
- details carry:
  - market_quality_score
  - market_quality_grade
  - market_quality_components
  - hard_reject_reason

## Database Persistence
Signals table and logger updated in [core/services/database.py](core/services/database.py):

- market_quality_score
- market_quality_grade
- market_quality_components
- hard_reject_reason

Legacy fields remain for compatibility:
- market_quality_pass
- market_quality_pct

## Validation Criteria
Freeze accepted when all are true:

- hard reject rules execute first
- quality score normalized to 0-100
- component breakdown available
- DB persistence for score/grade/components/reason
- entry gate uses `if not market_quality["passed"]: NO_TRADE`
