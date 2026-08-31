# Pre-Compare Snapshot

Date: 2026-08-09  
Branches: master vs feature/ptq-scalping-20260808

## 1) Current State

Checked out branch: feature/ptq-scalping-20260808

Local working-tree (not committed):
- M .env.example
- M core/engines/exit_engine.py
- M tests/test_exit_engine_sequence_regression.py
- ?? run.sh
- ?? tests/test_exit_engine_tsl_steps.py

Warning:
- Local uncommitted files can distort compare conclusions. Freeze/clean before final gate.

## 2) Branch Delta Summary

Diff (master...feature):
- 15 files changed
- 1249 insertions
- 1868 deletions

Changed files:
- M .gitignore
- M PROJECT_STRUCTURE.md
- M config/constants.py
- M config/strategy.json
- M core/backtest.py
- M core/engines/adaptive_confidence_engine.py
- M core/engines/entry_engine.py
- M core/engines/exit_engine.py
- M core/engines/market_quality_engine.py
- M core/engines/state_machine.py
- A core/validation/execution_guard_report.py
- A core/validation/walk_forward_backtest.py
- D run.sh
- M strategies/smart_scalp_v3.py
- A tests/test_backtest_execution_guard_regression.py

Commits in feature not in master:
- 69bd43c Ignore local audit and historical data artifacts
- 66e5503 Update project structure and trading engine improvements

## 3) Immediate Blockers Before Final Compare

1. Launcher path consistency blocker
- Branch says run.sh deleted, local has untracked new run.sh.
- Action required: normalize launcher file state before formal pass/fail gate.

2. Operational command reliability blocker
- Terminal evidence shows wrong launcher invocation (`./rin.sh`) fails with 127.
- Action required: enforce canonical command path in runbook + shell shortcuts if needed.

## 4) High-Risk Focus Areas for Tomorrow

1. Exit behavior changes
- Files: core/engines/exit_engine.py + related tests
- Verify trailing SL semantics and loss-cap consistency.

2. Execution guard and state transitions
- Files: core/engines/state_machine.py, core/engines/entry_engine.py
- Verify stale/future timestamp handling and anti-chase logic.

3. Backtest/report interpretation stability
- Files: core/backtest.py, core/validation/execution_guard_report.py, core/validation/walk_forward_backtest.py
- Verify metrics remain comparable with historical baseline.

4. Strategy/config drift
- Files: strategies/smart_scalp_v3.py, config/constants.py, config/strategy.json
- Verify threshold and runtime defaults do not silently shift risk profile.

## 5) Suggested Next Commands (Tomorrow)

1. `git stash -u` (or commit local work-in-progress)
2. `git checkout master && git pull`
3. `git checkout feature/ptq-scalping-20260808 && git pull`
4. `git diff --name-status master...feature/ptq-scalping-20260808`
5. `git diff --stat master...feature/ptq-scalping-20260808`
6. Execute compare checklist from handover template and issue GO/NO-GO.

## 6) Additional Evidence Pack (PRC/TCP)

- [archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md](archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md)
