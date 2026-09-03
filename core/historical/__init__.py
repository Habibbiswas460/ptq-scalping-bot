"""Historical option-data acquisition & backtest-readiness infrastructure.

Phase 1 scope only: ingestion, canonical storage, quality gate, and a
data-interface that a future real-data backtest run will consume. Nothing
in this package runs or modifies the live strategy, and nothing here
performs a strategy backtest — see core/backtest.py for that, which this
package does not touch.
"""
