# Changelog

## v3.5.0 - RC2 Freeze Candidate

### Added
- Runtime shared state module: core/runtime/state.py
- Weighted score engine: core/engines/weighted_score_engine.py
- Adaptive confidence engine: core/engines/adaptive_confidence_engine.py
- Market quality engine: core/engines/market_quality_engine.py
- Position size engine: core/engines/position_size_engine.py
- DVF validation stack modules under core/validation/
- Configuration helper module: config/configuration.py
- Strategy scoring configuration file: config/strategy.json
- Operational readiness and validation utilities

### Improved
- Runtime orchestration with shared RuntimeState flow across engines
- Paper-trading decision pipeline observability via DVF signal capture
- Launcher readiness flow and environment-aware execution paths
- Position sizing integration from risk-budget context to executable quantity
- Market-quality gating integration before execution path

### Fixed
- WebSocket reliability handling across subscribe/unsubscribe and reconnect paths
- ACK timeout fallback handling in broker data flow
- Runtime import and initialization stability in key modules
- Data validation freshness threshold handling and rejection accounting
- Documentation alignment for current RC2 architecture and freeze scope

### Security
- Secret redaction controls applied in operational reporting workflow
- India VIX contract corrected to canonical NSE/INDIAVIX/99926017
- Logging and evidence-handling improvements for safer operational audits

### Testing
- RC2 Freeze verification snapshot
- 151 Passed
- 1 Skipped
