# Compare Gate Run #2 Execution Pack

Date: 2026-08-09  
Objective: execute a clean, reproducible Run #2 compare and produce final signoff inputs

## A) Pre-Run Control Checks

1. Branch and workspace integrity
- Verify active branch and compare target branches.
- Ensure no unintended local state distorts compare verdict.

2. Launcher and command controls
- Confirm canonical launcher path and canonical startup command.
- Confirm invalid command variants are not used.

3. Evidence controls
- Ensure PRC completeness note is updated.
- Ensure TCP readiness evidence is refreshed.

## B) Suggested Command Sequence

1. Compare metadata
- git branch --show-current
- git diff --name-status master...feature/ptq-scalping-20260808
- git diff --stat master...feature/ptq-scalping-20260808

2. Launcher state verification
- git ls-tree -r --name-only master | grep '^run.sh$'
- git ls-tree -r --name-only feature/ptq-scalping-20260808 | grep '^run.sh$'
- git status --short

3. Regression sanity checks (targeted)
- "/home/lora/projects/PTQ-scalping bot/venv/bin/python" -m pytest -q tests/test_backtest_execution_guard_regression.py
- "/home/lora/projects/PTQ-scalping bot/venv/bin/python" -m pytest -q tests/test_exit_engine_sequence_regression.py tests/test_exit_engine_tsl_steps.py

4. Optional guard checks
- "/home/lora/projects/PTQ-scalping bot/venv/bin/python" -m pytest -q tests/test_readiness_policy.py

## C) Gate Recording Template

| Gate | Status (PASS/FAIL/CAUTION) | Evidence summary | Blocker? |
|---|---|---|---|
| G1 Launcher integrity | | | |
| G2 Command consistency | | | |
| G3 Transport resiliency | | | |
| G4 Evidence completeness | | | |
| G5 Strategy payoff readiness | | | |
| G6 Entry/exit regression | | | |
| G7 Config drift control | | | |
| G8 Architecture suitability | | | |

## D) Decision Rule

- GO: no blocking FAIL gates
- CONDITIONAL GO: no blocking FAIL gates but one or more CAUTION gates with written controls
- NO-GO: any blocking FAIL gate remains

## E) Output Files To Update After Run

1. Update decision sheet:
- archive/reports/GO_NO_GO_DECISION_SHEET_2026-08-09.md

2. Create run report:
- archive/reports/COMPARE_GATE_RUN2_RESULTS_2026-08-09.md

3. Reference closure status:
- archive/reports/COMPARE_GATE_RUN2_BLOCKER_CLOSURE_CHECKLIST_2026-08-09.md
