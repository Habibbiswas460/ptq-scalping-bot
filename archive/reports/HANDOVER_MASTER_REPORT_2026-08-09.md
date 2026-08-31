# PTQ Handover Master Report

Date: 2026-08-09  
Language: Bangla + English (mixed)  
Scope: Full project review + historical paper-trading evidence + current branch risk scan + tomorrow compare readiness.

## 1) Executive Verdict

Project handover করা যাবে, but currently **conditional** readiness:
- Historical architecture and risk controls are mature enough for controlled transfer.
- Paper-trading evidence shows repeatability but also recurring stale-data/telemetry gaps.
- Current feature branch has high-impact operational surface changes that must be gated before merge.

Overall today verdict: **Proceed with handover prep, do not promote branch without compare-gate pass.**

## 2) Evidence Base Used

Primary sources:
- Architecture and runtime overview: [README.md](README.md), [DOCUMENTATION.md](DOCUMENTATION.md), [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- Runtime critical flow: [core/main.py](core/main.py), [core/engines/entry_engine.py](core/engines/entry_engine.py), [core/engines/state_machine.py](core/engines/state_machine.py), [core/engines/exit_engine.py](core/engines/exit_engine.py), [core/trading/broker.py](core/trading/broker.py), [core/services/database.py](core/services/database.py)
- Historical paper evidence: [archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md](archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md), [archive/reports/REPORT_2026-07-07_08_09_PAPER.md](archive/reports/REPORT_2026-07-07_08_09_PAPER.md)
- Reliability evidence: [archive/audits/PRODUCTION_EVIDENCE_REPORT_2026-07-06.md](archive/audits/PRODUCTION_EVIDENCE_REPORT_2026-07-06.md)
- PRC/TCP Friday-cutoff addendum: [archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md](archive/reports/HANDOVER_ADDENDUM_PRC_TCP_EVIDENCE_UPTO_2026-08-07.md)
- Decision sheet: [archive/reports/GO_NO_GO_DECISION_SHEET_2026-08-09.md](archive/reports/GO_NO_GO_DECISION_SHEET_2026-08-09.md)
- Change chronology: [CHANGELOG.md](CHANGELOG.md)
- Current branch state and deltas (git evidence captured today)

## 3) Current Branch Snapshot (Today)

Active branch: feature/ptq-scalping-20260808  
Baseline branch for compare: master

Working tree status (important):
- Modified: .env.example, core/engines/exit_engine.py, tests/test_exit_engine_sequence_regression.py
- Untracked: run.sh, tests/test_exit_engine_tsl_steps.py

Branch diff vs master (feature-only):
- 15 files changed
- 1249 insertions, 1868 deletions
- Notable: `run.sh` appears deleted in branch history while a new untracked run.sh exists locally.

Commits on feature not in master:
- 69bd43c Ignore local audit and historical data artifacts
- 66e5503 Update project structure and trading engine improvements

## 4) Findings (Severity-Ordered)

### Critical Findings

1. Launcher continuity risk (branch/delete vs local/untracked mismatch)
- Evidence: branch diff shows `run.sh` deleted; local workspace has untracked replacement.
- Impact: tomorrow compare may produce inconsistent conclusions depending on whether local untracked file is included.
- Why handover risk: operational startup path may be non-reproducible across machines.

2. Operational command drift risk
- Evidence from today terminal context: `./rin.sh` failed with exit 127.
- Impact: runbook typo or launcher naming confusion can block startup during handover demo.
- Why handover risk: first impression reliability and onboarding friction.

### High Findings

1. Duplicate menu entry bug in launcher UI
- Evidence: duplicated option line in [run.sh](run.sh#L1532) and [run.sh](run.sh#L1533).
- Impact: operator confusion; increases chance of wrong selection in live operations.

2. Historical stale-data kill-switch concentration
- Evidence: [archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md](archive/reports/PAPER_AUDIT_REPORT_ALL_SESSIONS_2026-07-09.md) reports stale-data kill as dominant trigger.
- Impact: strategy execution continuity heavily sensitive to feed quality and validator behavior.

3. Confidence calibration overestimation pattern
- Evidence: same audit report shows confidence bands overstating realized win rate.
- Impact: decision confidence may appear safer than realized outcomes.

### Medium Findings

1. Forensic telemetry gaps in historical logs
- Evidence: repeated “Not logged / Insufficient statistical evidence” in paper audit report for pre-kill context fields.
- Impact: root-cause analysis quality drops when incidents happen.

2. Large operational surface changes concentrated in few modules
- Evidence: core engines + backtest + launcher + new validation scripts changed together.
- Impact: regression probability rises unless compare checklist is strict.

### Low Findings

1. Documentation and operation scripts drift risk
- Evidence: docs still refer to run.sh flow while branch history indicates deletion/replacement complexity.
- Impact: onboarding confusion, not immediate trading logic failure.

## 5) Architecture Review Summary

Strengths:
- Modular pipeline (entry, state, exit, broker, validation) is clear and maintainable.
- RuntimeState and DVF-oriented evidence architecture support post-trade analysis.
- Risk controls (kill switch, cooldown, guardrails) are already integrated in core path.

Weak Points:
- Launcher and operational shell surface is high blast radius, low isolation.
- Data-quality dependency remains dominant in runtime safety outcomes.
- Historical auditability still constrained by missing canonical forensic fields at incident timestamps.

## 6) Suggested Patch List (No Apply Today)

### Patch Set A (Blocker before merge)

1. Normalize launcher lifecycle in git history
- Target: [run.sh](run.sh)
- Action: ensure single tracked launcher file in branch (no delete+untracked ambiguity).
- Acceptance: clean git status for launcher path; compare reproducible on fresh clone.

2. Fix duplicated menu line
- Target: [run.sh](run.sh#L1532)
- Action: remove duplicate option line.
- Acceptance: menu options unique and sequential.

3. Add compare guard note in README
- Target: [README.md](README.md)
- Action: small runbook note for official launch command and readiness mode.
- Acceptance: operator cannot confuse run command names.

### Patch Set B (High-value hardening)

1. Pre-kill forensic snapshot enrichment
- Target: [core/engines/state_machine.py](core/engines/state_machine.py)
- Action: persist MQ/confidence/score/ws health/unrealized pnl at trigger time.
- Acceptance: next incident report has complete causal context.

2. Validator reject reason normalization
- Target: risk validator logging path + report pipeline.
- Action: canonical reason IDs instead of free-text only.
- Acceptance: reject trend analytics become deterministic.

3. Confidence calibration governance
- Target: DVF calibration/report workflow.
- Action: add weekly drift report and threshold alarm.
- Acceptance: overconfidence deviations become visible early.

## 7) New Feature Recommendations

1. Branch Compare Gate Runner
- Auto-check for runtime/config/test/docs delta and emit GO/NO-GO score.

2. Incident Forensics Pack Generator
- One command to export pre/post kill context, guard metrics, and decision trace.

3. Readiness Score History
- Persist daily readiness outcomes for trend-based operations sign-off.

4. Strategy Regime Stability Tracker
- Track performance split by session/regime for adaptive parameter governance.

## 8) Tomorrow Compare Mission (master vs feature/ptq-scalping-20260808)

Must-pass gates:
- Gate 1: Launcher integrity and runbook consistency
- Gate 2: Exit-engine behavioral consistency with tests
- Gate 3: Execution guard and stale-signal safety consistency
- Gate 4: Backtest/report semantic consistency
- Gate 5: Test coverage relevance and pass status

Any Critical fail => **NO-GO for promotion**.

## 9) Handover Notes

Assumptions:
- Baseline branch is `master`.
- Compare target is `feature/ptq-scalping-20260808`.

Out of scope today:
- No code apply, no merge, no release cut.

Recommended owner split:
- Ops/Launcher owner: runbook + launcher stabilization
- Core engine owner: exit/state guard behavior validation
- Validation owner: telemetry and calibration evidence quality

## 10) Final Recommendation

Handover prep can continue immediately, but branch promotion should wait for tomorrow’s checklist pass with explicit GO/NO-GO signoff.
