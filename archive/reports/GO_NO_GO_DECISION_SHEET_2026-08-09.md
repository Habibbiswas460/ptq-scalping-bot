# PTQ Branch Promotion Decision Sheet

Date: 2026-08-09  
Decision type: Live compare execution run #1 (master vs feature/ptq-scalping-20260808)  
Evidence baseline: Handover master report + PRC/TCP addendum + git delta snapshot

## 1) Decision Outcome (Current)

Current status: CONDITIONAL NO-GO

Reason:
- Evidence package is strong enough for governance review.
- Promotion gate is not yet pass because blocker items remain unresolved.
- Tomorrow compare run is still required for final GO/NO-GO signoff.

## 2) Gate Status Matrix

| Gate | Scope | Current Status | Evidence | Promotion Impact |
|---|---|---|---|---|
| G1 | Launcher integrity and reproducibility | FAIL | run.sh branch/local mismatch in pre-compare snapshot | Blocker |
| G2 | Operational command consistency | FAIL | terminal showed ./rin.sh failure (127) | Blocker |
| G3 | Runtime transport resiliency | PASS with monitor | PRC ACK investigation: high fallback recovery, 98.18% reconnect success | Monitor |
| G4 | Operational evidence completeness | FAIL | PRC master operational audit verdict: Evidence Incomplete | Blocker |
| G5 | Strategy payoff quality | FAIL | TCP strategy effectiveness verdict: NOT READY in audited window | Blocker |
| G6 | Entry decision consistency | PASS with caution | TCP entry decision certification: acceptable but borderline entries exist | Caution |
| G7 | Tuning effect traceability | PASS with caution | 2026-08-07 gate/chop tuning docs show stricter filter and reduced chop blocks | Caution |
| G8 | Architecture baseline suitability | PASS with conditions | PRC architecture certification: approved with conditions | Monitor |

## 2A) Live Execution Evidence Captured Today

Branch-delta evidence (run today):
- 15 files changed, 1249 insertions, 1868 deletions
- run.sh exists in master tree, absent in feature tree, while local workspace has untracked run.sh

Targeted regression checks run today:
- tests/test_backtest_execution_guard_regression.py: PASS (5 tests)
- tests/test_exit_engine_sequence_regression.py + tests/test_exit_engine_tsl_steps.py: PASS (4 tests)
- Diagnostics check on changed core files: no editor errors detected

Interpretation:
- Core behavior changes under review are testable and currently passing in workspace execution.
- Promotion remains blocked by release-governance blockers (launcher reproducibility, evidence completeness, payoff readiness), not by immediate syntax/regression break.

## 3) Blockers To Clear Before Final GO

1. Normalize launcher file lifecycle
- Owner: Ops/Release
- Required: one authoritative tracked launcher path, no delete-vs-untracked ambiguity
- Completion proof: clean git status and deterministic launcher command in docs

2. Complete mandatory evidence artifacts
- Owner: Audit/Validation
- Required: close missing day-artifact gaps identified in PRC master operational audit, or issue formal accepted exception memo
- Completion proof: updated completeness check and revised audit verdict

3. Resolve strategy readiness gap for capital promotion
- Owner: Strategy/Risk
- Required: show improved expectancy/profit-factor in latest accepted validation window or issue strict risk-limited deployment condition
- Completion proof: updated TCP-style performance audit with pass criteria

## 4) Conditional Path If Promotion Is Urgent

Allowed only as controlled pilot if all conditions below are accepted in writing:
- Paper-first continuation only, no immediate unrestricted real-capital scale-up.
- Daily readiness gate must be PASS/DEFERRED policy-compliant before launch.
- Kill-switch and transport monitoring must remain active with post-session review.
- Explicit risk acceptance signoff from release owner and strategy owner.

## 5) Tomorrow Final Decision Checklist

1. Run branch compare checklist from:
- [archive/reports/HANDOVER_CHECKLIST_RISK_REGISTER_COMPARE_TEMPLATE_2026-08-09.md](archive/reports/HANDOVER_CHECKLIST_RISK_REGISTER_COMPARE_TEMPLATE_2026-08-09.md)

2. Complete blocker closure checklist before re-run:
- [archive/reports/COMPARE_GATE_RUN2_BLOCKER_CLOSURE_CHECKLIST_2026-08-09.md](archive/reports/COMPARE_GATE_RUN2_BLOCKER_CLOSURE_CHECKLIST_2026-08-09.md)

3. Execute Run #2 command pack:
- [archive/reports/COMPARE_GATE_RUN2_EXECUTION_PACK_2026-08-09.md](archive/reports/COMPARE_GATE_RUN2_EXECUTION_PACK_2026-08-09.md)

4. Re-verify PRC/TCP evidence pack:
- [archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md](archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md)

5. Update final signoff fields:
- Final decision: GO / CONDITIONAL GO / NO-GO
- Blockers cleared: Yes/No
- Signed by: Release owner, Strategy owner, Validation owner

## 6) Recommended Signoff Statement

Recommended statement for current date:
- Based on available technical and operational evidence, branch promotion is currently CONDITIONAL NO-GO.
- Handover process can proceed, but production-grade promotion decision must wait for blocker closure and tomorrow compare gate completion.

## 7) Post Run #1 Delta (Executed Next)

1. Run #2 preparation pack created:
- [archive/reports/COMPARE_GATE_RUN2_BLOCKER_CLOSURE_CHECKLIST_2026-08-09.md](archive/reports/COMPARE_GATE_RUN2_BLOCKER_CLOSURE_CHECKLIST_2026-08-09.md)
- [archive/reports/COMPARE_GATE_RUN2_EXECUTION_PACK_2026-08-09.md](archive/reports/COMPARE_GATE_RUN2_EXECUTION_PACK_2026-08-09.md)

2. G2 blocker (command consistency) moved to closed-precondition state:
- Canonical command standard documented as ./run.sh
- Invalid variant explicitly marked: ./rin.sh
- Canonical command proof executed: ./run.sh --version

3. Remaining hard blockers for final GO decision:
- G1 launcher reproducibility
- G4 operational evidence completeness
- G5 strategy payoff readiness

## 8) B1 Fix Update (Feature-Only, Master Untouched)

1. Launcher reproducibility action completed in feature working context:
- run.sh is now durable in feature via commit 53456ac
- local untracked launcher ambiguity removed

2. Master branch protection respected:
- no changes applied to master

3. Remaining blockers after B1 action:
- G5 strategy payoff readiness

## 9) B3 Update (Operational Evidence Completeness)

1. B3 cannot be closed by artifact recovery in current window:
- PRC-audited missing artifacts remain missing after re-check (14/14)

2. Governance action taken:
- B3 marked WAIVED (conditional) via formal memo:
- [archive/reports/B3_EVIDENCE_COMPLETENESS_WAIVER_MEMO_2026-08-09.md](archive/reports/B3_EVIDENCE_COMPLETENESS_WAIVER_MEMO_2026-08-09.md)

3. Run #2 implication:
- G4 can proceed only under signed waiver (Validation owner + Release owner)
- Primary remaining technical-performance blocker is G5 (B4)

## 10) B4 Handoff Update

1. B4 refresh package prepared from TCP baseline:
- [archive/reports/B4_STRATEGY_READINESS_REFRESH_SHEET_2026-08-09.md](archive/reports/B4_STRATEGY_READINESS_REFRESH_SHEET_2026-08-09.md)

2. Current B4 baseline remains NOT READY (latest certified window):
- negative expectancy
- profit factor below 1
- payoff asymmetry (avg loser magnitude > avg winner)

3. Next required action for Run #2:
- fill refreshed metrics and declare READY / NOT READY / WAIVED with Strategy and Risk signoff

## 11) Run #2 Final Sync

1. Run #2 result file created:
- [archive/reports/COMPARE_GATE_RUN2_RESULTS_2026-08-09.md](archive/reports/COMPARE_GATE_RUN2_RESULTS_2026-08-09.md)

2. Gate outcome alignment:
- B1: operationally normalized and durable in feature (commit 53456ac)
- B2: PASS
- B3: WAIVED (conditional)
- B4: WAIVED (conditional pilot)

3. Promotion decision update:
- Current decision: CONDITIONAL GO (Pilot Only)
- Unrestricted promotion decision: NO-GO until strategy readiness improvement
