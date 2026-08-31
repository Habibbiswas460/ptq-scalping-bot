# Handover Checklist + Risk Register + Compare Template

Date: 2026-08-09  
Use case: Tomorrow branch compare and handover acceptance  
Compare pair: master vs feature/ptq-scalping-20260808

## A) Pre-Compare Checklist (Mandatory)

1. Confirm clean reproducible workspace
- [ ] `git fetch --all --prune` completed
- [ ] `git checkout master` and pull completed
- [ ] `git checkout feature/ptq-scalping-20260808` completed
- [ ] No hidden untracked operational file mismatch for launcher

2. Confirm compare baseline integrity
- [ ] Diff list captured: `git diff --name-status master...feature/ptq-scalping-20260808`
- [ ] Commit list captured: `git log --oneline master..feature/ptq-scalping-20260808`
- [ ] High-impact files tagged (launcher, engines, config, tests)

3. Confirm test and runbook context
- [ ] Read [README.md](README.md) startup instructions
- [ ] Read [DOCUMENTATION.md](DOCUMENTATION.md) architecture index
- [ ] Verify readiness workflow ownership and expected command path

## B) Risk Register (Current)

| ID | Severity | Risk | Evidence | Impact | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R1 | Critical | Launcher tracked/untracked mismatch | branch diff + local status | non-reproducible startup | unify tracked launcher path | Ops |
| R2 | Critical | Operational command drift (`rin.sh` typo risk) | terminal execution failure (127) | startup failure during demo/handover | runbook command hardening + alias warning | Ops |
| R3 | High | Duplicate launcher menu item | [run.sh](run.sh#L1532), [run.sh](run.sh#L1533) | operator confusion | remove duplicate and renumber verify | Ops |
| R4 | High | Stale-data kill-switch dominance | [archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md](archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md) | trade continuity disruption | data-quality guard tuning + visibility | Core |
| R5 | High | Confidence overestimation | same audit report | wrong risk appetite perception | weekly calibration governance | Validation |
| R6 | Medium | Forensic field gaps at incident time | historical audit notes | weak RCA quality | pre-kill structured snapshot logging | Validation/Core |
| R7 | Medium | Large combined surface changes | diff stat concentration | regression coupling risk | strict gate-based compare execution | All |

## C) Tomorrow Compare Template

## 1) Diff Inventory

- Files changed count: ______
- Insertions/Deletions: ______
- New files: ______
- Deleted files: ______
- Operational files impacted: ______
- Core trading logic files impacted: ______
- Test files impacted: ______

## 2) Functional Review Blocks

1. Launcher and operation flow
- Inputs: [run.sh](run.sh), [README.md](README.md)
- Checkpoints:
  - command consistency
  - menu integrity
  - readiness invocation integrity
- Result: PASS / FAIL
- Notes: ______

2. Entry-State-Exit behavior
- Inputs: [core/engines/entry_engine.py](core/engines/entry_engine.py), [core/engines/state_machine.py](core/engines/state_machine.py), [core/engines/exit_engine.py](core/engines/exit_engine.py)
- Checkpoints:
  - signal guard consistency
  - stale/future signal behavior
  - trailing and loss-cap behavior
- Result: PASS / FAIL
- Notes: ______

3. Broker and data reliability
- Inputs: [core/trading/broker.py](core/trading/broker.py), [brokers/angel_one/client.py](brokers/angel_one/client.py)
- Checkpoints:
  - reconnect logic consistency
  - ack/fallback handling continuity
  - stale handling compatibility
- Result: PASS / FAIL
- Notes: ______

4. Backtest and validation consistency
- Inputs: [core/backtest.py](core/backtest.py), [core/validation/execution_guard_report.py](core/validation/execution_guard_report.py), [core/validation/walk_forward_backtest.py](core/validation/walk_forward_backtest.py)
- Checkpoints:
  - report semantics
  - end-of-data exit behavior
  - guard metrics pipeline
- Result: PASS / FAIL
- Notes: ______

5. Test surface adequacy
- Inputs: [tests/test_backtest_execution_guard_regression.py](tests/test_backtest_execution_guard_regression.py), [tests/test_exit_engine_sequence_regression.py](tests/test_exit_engine_sequence_regression.py), [tests/test_exit_engine_tsl_steps.py](tests/test_exit_engine_tsl_steps.py)
- Checkpoints:
  - modified behaviors covered
  - no deleted critical regression tests
  - pass/fail relevance
- Result: PASS / FAIL
- Notes: ______

## 3) Decision Gate

Gate scoring:
- Critical issue present = automatic NO-GO
- High issues > 2 unresolved = NO-GO
- Medium issues can proceed only with mitigation owner/date

Final decision:
- GO / CONDITIONAL GO / NO-GO
- Signed by: ______
- Date/Time: ______

## D) Suggested Patch Queue (No Apply)

Priority 0 (before merge)
1. Launcher tracked-state normalization
2. Duplicate menu line fix
3. Official command path clarification in docs

Priority 1 (after compare pass)
1. Incident forensic snapshot enrichment at kill trigger
2. Canonical validator reason IDs
3. Confidence drift governance report automation

## E) Handover Acceptance Checklist

- [ ] System architecture explained with module ownership
- [ ] Known risks acknowledged with mitigation owners
- [ ] Compare outcome documented and signed
- [ ] Operational runbook commands validated by dry-run
- [ ] Post-handover first-week monitoring plan assigned
