# Compare Gate Run #2 Blocker Closure Checklist

Date: 2026-08-09  
Scope: master vs feature/ptq-scalping-20260808  
Purpose: clear Run #1 blocking gates before Run #2 final signoff

## Status Key

- OPEN: not resolved
- CLOSED: resolved with evidence
- WAIVED: unresolved but formally accepted risk

## Blocker Matrix

| Blocker | Gate | Owner | Required Closure | Evidence To Attach | Status | Signoff |
|---|---|---|---|---|---|---|
| B1 Launcher reproducibility | G1 | Ops/Release | Ensure one tracked launcher path exists in branch compare context | clean compare snapshot + launcher file tracking proof | CLOSED (durable commit) | Completed |
| B2 Startup command consistency | G2 | Ops/Runbook | Define one canonical startup command and remove typo-prone variants | runbook update + terminal proof command runs | CLOSED | Pending |
| B3 Operational evidence completeness | G4 | Validation/Audit | Close evidence gaps or issue formal accepted-risk memo | updated PRC evidence index + verdict note | WAIVED (conditional) | Pending Validation signoff |
| B4 Strategy readiness for promotion | G5 | Strategy/Risk | Refresh effectiveness evidence after tuning window | updated TCP performance verdict with pass/fail criteria | WAIVED (conditional pilot) | Pending Strategy/Risk signoff |

## Detailed Closure Tasks

### B1 Launcher reproducibility (G1)

1. Confirm launcher file state in both branches.
2. Ensure compare branch state does not depend on local untracked launcher copy.
3. Record clean status output after alignment.

Required proof:
- tree check output for master and feature launcher presence
- workspace status showing no ambiguous untracked launcher artifact for compare run

### B2 Startup command consistency (G2)

1. Publish canonical launch command in runbook/readme.
2. Remove or mark invalid command variants.
3. Execute canonical command in controlled dry-run mode and capture result.

Required proof:
- docs snippet showing canonical command
- terminal result showing command exists and returns expected startup behavior

### B3 Operational evidence completeness (G4)

1. Enumerate missing PRC evidence items from latest audit findings.
2. Attach missing artifacts or formal acceptance memo for missing items.
3. Re-state final evidence verdict.

Required proof:
- evidence checklist table with each gap marked closed or waived
- final one-line verdict for completeness

### B4 Strategy readiness (G5)

1. Re-run payoff effectiveness evaluation after threshold tuning window.
2. Compare expectancy, profit factor, hit quality against acceptance thresholds.
3. Mark final readiness as READY or NOT READY for promotion.

Required proof:
- refreshed performance summary table
- final recommendation line with rationale

## Run #2 Entry Criteria

Run Compare Gate #2 only if all are true:
- B1 and B2 are CLOSED
- B3 is CLOSED or WAIVED with written signoff
- B4 is CLOSED or WAIVED with written signoff

## Latest Verification Update (2026-08-09)

1. B1 moved to CLOSED (durable in feature)
- master contains run.sh (master untouched)
- feature branch includes launcher commit: 53456ac
- untracked launcher ambiguity removed from local compare context

2. B2 moved to CLOSED
- Canonical startup command documented in [README.md](README.md) and [DOCUMENTATION.md](DOCUMENTATION.md)
- Canonical command proof captured: ./run.sh --version executed successfully

3. B3 moved to WAIVED (conditional)
- Missing historical artifacts remain 14/14 after filesystem re-check
- Formal waiver memo created: [archive/reports/B3_EVIDENCE_COMPLETENESS_WAIVER_MEMO_2026-08-09.md](archive/reports/B3_EVIDENCE_COMPLETENESS_WAIVER_MEMO_2026-08-09.md)
- Run #2 can proceed only with Validation owner signoff on waiver

4. B4 moved to WAIVED (conditional pilot)
- Refresh sheet finalized with refreshed metrics and conditional waiver verdict:
- [archive/reports/B4_STRATEGY_READINESS_REFRESH_SHEET_2026-08-09.md](archive/reports/B4_STRATEGY_READINESS_REFRESH_SHEET_2026-08-09.md)

## Final Signoff Block

- Release Owner: ____________________  Date: __________
- Strategy Owner: ___________________  Date: __________
- Validation Owner: _________________  Date: __________
- Final Decision: GO / CONDITIONAL GO / NO-GO
