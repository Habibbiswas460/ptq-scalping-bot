# Compare Gate Run #1 Results

Date: 2026-08-09  
Compare pair: master vs feature/ptq-scalping-20260808  
Execution mode: evidence + targeted test validation

## Gate Results

1. G1 Launcher integrity and reproducibility: FAIL
- Evidence:
  - master tree contains run.sh
  - feature tree does not contain run.sh
  - local workspace has untracked run.sh
- Risk: compare result depends on local state, not clean branch state.

2. G2 Operational command consistency: FAIL
- Evidence:
  - terminal record shows ./rin.sh fails with exit 127.
- Risk: handover operator can fail startup due command drift/typo path.

3. G3 Runtime transport resiliency: PASS with monitor
- Evidence source:
  - PRC ACK investigation reports full timeout fallback markers and 98.18% reconnect success in audited window.
- Risk: persistent timeout pressure still requires monitoring.

4. G4 Operational evidence completeness: FAIL
- Evidence source:
  - PRC master operational audit final verdict is Evidence Incomplete.
- Risk: governance confidence reduced for causal incident closure.

5. G5 Strategy payoff quality: FAIL
- Evidence source:
  - TCP strategy effectiveness audit final verdict NOT READY in audited window.
- Risk: negative expectancy / low confidence for unrestricted promotion.

6. G6 Entry-state-exit logic regression: PASS with caution
- Evidence:
  - branch introduces entry timestamp enrichment and execution-guard additions.
  - targeted regression tests pass:
    - tests/test_backtest_execution_guard_regression.py (5 pass)
    - tests/test_exit_engine_sequence_regression.py (1 pass)
    - tests/test_exit_engine_tsl_steps.py (3 pass)
- Caution: local-only files/tests still need clean-branch confirmation.

7. G7 Config/strategy drift control: CAUTION
- Evidence:
  - thresholds tightened in config/strategy.json (confidence and weighted score minimums, MQ minimum increase).
  - min entry premium lowered in config/constants.py (90 -> 80) while gating tightened elsewhere.
- Risk: acceptance profile shifts; requires updated performance window confirmation.

8. G8 Architecture suitability: PASS with conditions
- Evidence source:
  - PRC architecture certification approved with conditions.
- Risk: coupling/singleton concentration remains managed debt.

## Run #1 Decision

Result: CONDITIONAL NO-GO

Reason:
- Blocking gates failed: G1, G2, G4, G5
- Functional regression checks are currently passing, but governance and reproducibility blockers remain.

## Minimum Actions Before Re-run

1. Normalize launcher path as tracked branch artifact.
2. Enforce canonical startup command in docs/runbook.
3. Resolve evidence completeness gap or issue formal risk acceptance memo.
4. Re-run performance effectiveness audit after current threshold tuning window.

## Re-run Trigger

Run Compare Gate #2 only after blockers 1-4 are closed or formally waived with signoff.
