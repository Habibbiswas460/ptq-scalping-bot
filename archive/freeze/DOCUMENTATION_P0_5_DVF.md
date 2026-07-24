# P0-5 Decision Validation Framework (DVF)

## Status
Design Freeze Draft

P0-5 is the final validation phase for the P0 trading brain.

Completed upstream modules:
- P0-1 Weighted Score Engine
- P0-2 Adaptive Confidence Engine
- P0-3 Market Quality Gate
- P0-4 Position Size Engine

DVF validates the full decision chain before production readiness.

## Objective
Validate the full decision pipeline with replayable evidence, calibration metrics, paper execution outcomes, and daily institutional reports.

DVF is not a strategy engine.
DVF is not a broker.
DVF is not a replacement for runtime logging.

DVF is the post-decision validation layer.

## Golden Rule
DVF must never influence trading decisions.

DVF is read-only.
It observes.
It records.
It validates.
It never trades.

## Naming
Official module name:
- Decision Validation Framework (DVF)

Submodule naming:
- paper_executor is only one component inside DVF
- do not use "paper trade framework" as the primary architecture name

## Validation Scope
DVF must validate:
- signal generation
- accept/reject gate behavior
- score calibration
- confidence calibration
- market quality calibration
- position size behavior
- replay consistency
- paper execution outcomes
- daily decision quality

## End-to-End Pipeline
Indicators
-> Weighted Score
-> Adaptive Confidence
-> Market Quality
-> Position Size
-> Decision Validation Framework
-> Analytics
-> Calibration
-> Reports

## Module Structure
Recommended module layout:

```text
core/
  validation/
    __init__.py
    signal_logger.py
    paper_executor.py
    decision_replay.py
    calibration_engine.py
    validation_report.py
    analytics.py
    exporter.py
```

## Responsibilities
### signal_logger.py
Responsibilities:
- capture every evaluated signal
- capture both accepted and rejected decisions
- normalize payload shape for downstream replay and analytics
- attach runtime identifiers and timestamps

Non-responsibilities:
- trade execution
- report generation
- broker integration logic

### paper_executor.py
Responsibilities:
- simulate virtual entry and exit
- record pnl, hold time, mfe, mae, slippage model output
- operate without live broker dependency

Non-responsibilities:
- real order placement
- score/confidence computation

### decision_replay.py
Responsibilities:
- reconstruct the decision path for any signal or trade
- replay timeline of indicator -> score -> confidence -> mq -> position size -> entry/exit
- support both accepted and rejected paths

Non-responsibilities:
- strategy mutation
- broker execution

### calibration_engine.py
Responsibilities:
- compute calibration tables for score, confidence, market quality, and position size
- produce calibration error metrics
- provide bucketed accuracy summaries

### validation_report.py
Responsibilities:
- generate daily text and json institutional validation reports
- aggregate results from analytics and calibration modules

### analytics.py
Responsibilities:
- performance breakdowns by regime, session, score band, quality grade, allocation grade
- reject reason analysis
- risk utilization efficiency

### exporter.py
Responsibilities:
- export csv/json/sqlite snapshots/html reports
- no business logic

## Data Capture Contract
Every evaluated decision should be representable as a DVF event record.

### Signal Capture Fields
Required fields:
- decision_id
- parent_decision_id
- timestamp
- direction
- session_type
- underlying
- strike
- expiry
- spot_price
- premium
- weighted_score
- confidence
- market_quality_score
- market_quality_grade
- position_size
- allocation_grade
- regime
- regime_snapshot
- session
- spread
- volume
- greeks
- indicators_snapshot
- score_breakdown
- confidence_breakdown
- market_quality_components
- position_size_breakdown
- accepted
- rejected
- reject_reason
- hard_reject
- hard_reject_reason
- strategy_version
- engine_version
- config_hash

### Paper Execution Fields
Required fields:
- virtual_entry_time
- virtual_entry_price
- virtual_exit_time
- virtual_exit_price
- pnl
- pnl_pct
- hold_time_sec
- mfe
- mae
- slippage_model
- exit_reason

## Storage Strategy
DVF should persist to SQLite first.

Recommended tables:
- dvf_signals
- dvf_trades
- dvf_reports
- dvf_calibration

Principles:
- append-friendly
- replay-safe
- normalized enough for analytics
- json columns allowed for breakdown payloads

## Public API Freeze
### Signal Logger API
```python
log_decision(event: dict) -> int
```

### Paper Executor API
```python
simulate_entry(decision: dict, market_context: dict) -> dict
simulate_exit(position: dict, market_context: dict) -> dict
```

### Replay API
```python
replay_decision(decision_id: int) -> dict
replay_trade(trade_id: int) -> dict
```

### Calibration API
```python
score_calibration(days: int = 30) -> list[dict]
confidence_calibration(days: int = 30) -> list[dict]
market_quality_calibration(days: int = 30) -> list[dict]
position_size_calibration(days: int = 30) -> list[dict]
```

### Report API
```python
generate_daily_validation_report(date: str | None = None) -> dict
render_daily_validation_report(report: dict) -> str
```

### Export API
```python
export_csv(date: str | None = None) -> str
export_json(date: str | None = None) -> str
export_sqlite_snapshot(date: str | None = None) -> str
export_html(date: str | None = None) -> str
```

## Phase Breakdown
### Phase 1: Signal Capture
Deliverables:
- signal logger contract
- accepted + rejected capture
- db schema for dvf_signals

Success criteria:
- every evaluated signal is saved
- hard reject and soft reject are distinguishable

### Phase 2: Paper Execution
Deliverables:
- virtual trade lifecycle
- mfe/mae tracking
- slippage simulation hooks

Success criteria:
- paper trades can run independently of broker
- entry/exit outcomes can be analyzed per signal

### Phase 3: Replay Engine
Deliverables:
- replay payload builder
- timeline reconstruction

Success criteria:
- any accepted or rejected signal can be replayed from stored inputs

### Phase 4: Calibration Engine
Deliverables:
- score calibration
- confidence calibration
- market quality calibration
- position size calibration

Success criteria:
- calibration error is measurable from stored outcomes

### Phase 5: Validation Reports
Deliverables:
- daily validation report
- json and text outputs
- top patterns and reject summaries

Success criteria:
- one command can produce an institutional validation report

### Phase 6: Export Layer
Deliverables:
- csv export
- json export
- sqlite snapshot export
- html export

Success criteria:
- validation artifacts can be archived and shared without code changes

## Calibration Metrics
### Score Calibration
Examples:
- 90+ vs realized win rate
- 80-89 vs realized win rate
- 70-79 vs realized win rate

### Confidence Calibration
Examples:
- avg predicted confidence vs realized win rate
- calibration error per confidence band

### Market Quality Calibration
Examples:
- A+ grade vs win rate
- A grade vs avg pnl
- B grade vs reject-adjusted expectancy

### Position Size Calibration
Examples:
- allocation grade vs win rate
- allocation grade vs avg pnl
- risk budget used vs avg return
- risk efficiency = pnl / actual executed risk

## Analytics KPIs
### Trading KPIs
- win rate
- profit factor
- expectancy
- drawdown
- average pnl

### Intelligence KPIs
- score accuracy
- confidence accuracy
- market quality accuracy
- position size accuracy

### Execution KPIs
- signal acceptance rate
- hard reject rate
- soft reject rate
- paper slippage estimate
- latency buckets if available

## Daily Validation Report Sections
Required sections:
- signals total
- accepted total
- rejected total
- top reject reasons
- score calibration
- confidence calibration
- market quality calibration
- position size summary
- best regime
- worst regime
- best session
- worst session
- top winning pattern
- top losing pattern

## Test Plan
### Unit Tests
- signal event schema normalization
- calibration bucket math
- paper trade pnl math
- replay payload reconstruction
- exporter output paths

### Integration Tests
- signal -> dvf_signals persistence
- accepted + rejected capture flow
- paper execution lifecycle
- replay from stored row
- report generation from recorded data

### Regression Tests
- no mutation of strategy outputs
- no broker dependency in paper executor
- no missing fields in accepted/rejected events
- calibration math stable across refactors

## Success Criteria
P0-5 is complete when all are true:
- every signal is captured
- accepted and rejected decisions are stored
- replay works end to end
- paper execution is analyzable
- calibration metrics are available
- daily validation report is generated
- export layer works for csv/json/sqlite/html

## Out of Scope for P0-5
- live broker execution redesign
- strategy feature changes
- multi-broker validation
- shadow live trading
- portfolio correlation control
- pdf export

These belong to P1 or later.

## Implementation Order Recommendation
1. signal_logger.py
2. paper_executor.py
3. decision_replay.py
4. calibration_engine.py
5. validation_report.py
6. analytics.py
7. exporter.py

## Freeze Decision
Before implementation begins, freeze:
- module structure
- public APIs
- event payload shape
- report sections
- test plan

No strategy logic changes should be bundled into DVF work.
