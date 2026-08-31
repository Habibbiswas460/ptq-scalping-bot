# Compare Gate Run #2 Results

Date: 2026-08-09  
Compare pair: master vs feature/ptq-scalping-20260808  
Execution mode: blocker-closure + conditional-waiver governance

## Gate Results

1. G1 Launcher integrity and reproducibility: PASS
- Evidence:
  - master tree contains run.sh
  - feature branch now has durable launcher commit (53456ac)
  - local untracked launcher ambiguity removed
- Risk: low; continue runbook discipline.

2. G2 Operational command consistency: PASS
- Evidence:
  - canonical command documented in README and DOCUMENTATION
  - ./run.sh --version executed successfully
- Risk: low, monitor runbook compliance.

3. G3 Runtime transport resiliency: PASS with monitor
- Evidence source:
  - PRC ACK investigation: timeout fallback markers and 98.18% reconnect success.
- Risk: timeout pressure remains monitoring item.

4. G4 Operational evidence completeness: WAIVED (conditional)
- Evidence:
  - PRC audited missing artifacts remain 14/14 after re-check.
  - Formal waiver memo created.
- Control:
  - Requires Validation + Release signoff before final promotion decision.

5. G5 Strategy payoff readiness: WAIVED (conditional pilot)
- Evidence:
  - baseline remains NOT READY (negative expectancy, PF<1, payoff asymmetry).
  - B4 refresh sheet finalized with conditional pilot waiver controls.
- Control:
  - No unrestricted promotion; pilot-only under strict risk controls.

6. G6 Entry-state-exit regression: PASS
- Evidence:
  - targeted tests run for guard/exit regressions
  - pytest exit code: 0
- Risk: low for reviewed scope.

7. G7 Config/strategy drift control: CAUTION
- Evidence:
  - tightened entry/quality thresholds with stricter filter behavior in TCP evidence.
- Risk: acceptance profile shift; needs continued monitoring.

8. G8 Architecture suitability: PASS with conditions
- Evidence source:
  - PRC architecture certification approved with conditions.
- Risk: managed technical debt remains.

## Run #2 Decision

Result: CONDITIONAL GO (Pilot Only)

Interpretation:
- Compare gate can proceed under signed waivers and strict controls.
- Unrestricted promotion remains NO-GO until B1 commit durability and strategy readiness improve.

## Mandatory Controls

1. Complete feature-side commit to make launcher normalization durable. (Completed: 53456ac)
2. Signed B3 waiver (Validation + Release owners).
3. Signed B4 waiver (Strategy + Risk + Release owners).
4. Paper-first mode with position cap and strict kill-switch enforcement.
5. Mandatory review checkpoint date: 2026-08-16.
