# B4 Strategy Readiness Refresh Sheet

Date: 2026-08-09  
Related gate: G5 Strategy payoff readiness (B4)

## 1) Baseline (Current Known Verdict)

Source baseline:
- tcp/TPC_STRATEGY_EFFECTIVENESS_AUDIT.md
- tcp/TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md
- tcp/TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md

Current baseline verdict: NOT READY

Baseline metrics:
- Closed trades: 5
- Win rate: 60.00%
- Total PnL: -149.50
- Expectancy per trade: -29.90
- Profit factor: 0.7551
- Average winner: +153.62
- Average loser: -305.17
- Avg win/loss ratio: 0.5034

## 2) Acceptance Criteria For READY

Mark READY only if all are true in refreshed window:
1. Expectancy > 0
2. Profit factor >= 1.10
3. Avg winner >= avg loser magnitude * 0.90
4. Sample depth is adequate for promotion decision (owner signoff on sample sufficiency)
5. No evidence of one-sided fragile directional dependency without risk controls

If any criterion fails:
- B4 remains OPEN, or
- B4 becomes WAIVED with strict deployment limits and signed risk memo

## 3) Refresh Input Table (To Fill)

| Metric | Baseline | Refreshed value | Pass/Fail |
|---|---:|---:|---|
| Closed trades | 5 | 5 | CAUTION (low sample) |
| Win rate | 60.00% | 60.00% | PASS (rate only) |
| Total PnL | -149.50 | -149.50 | FAIL |
| Expectancy | -29.90 | -29.90 | FAIL |
| Profit factor | 0.7551 | 0.7551 | FAIL |
| Avg winner | +153.62 | +153.62 | FAIL (vs loss magnitude) |
| Avg loser | -305.17 | -305.17 | FAIL |
| Avg win/loss ratio | 0.5034 | 0.5034 | FAIL |

## 4) Decision Block

B4 final status:
- WAIVED (Conditional Pilot)

Rationale:
- Refreshed window does not improve baseline payoff quality (negative expectancy, PF<1).
- To unblock Run #2 governance flow, B4 is waived only for controlled pilot path, not unrestricted promotion.

If WAIVED, controls required:
1. Paper-first continuation only
2. Position cap enforced
3. Daily readiness PASS/DEFERRED gate mandatory
4. Kill-switch strict enforcement
5. Mandatory review date: 2026-08-16

## 5) Signoff

- Strategy Owner: ____________________  Date: __________
- Risk Owner: ________________________  Date: __________
- Release Owner: _____________________  Date: __________
