# Handover Addendum: PRC + TCP Evidence (Up To Friday 2026-08-07)

Date prepared: 2026-08-09  
Evidence scope: PRC and TCP folders only  
Cutoff used: Last Friday = 2026-08-07

## 1) High-Confidence Friday-Relevant Evidence

1. ACK/WebSocket behavior remained recoverable, not proven as direct trade-stop cause
- Source: [prc/PRC_ACK_WEBSOCKET_INVESTIGATION.md](prc/PRC_ACK_WEBSOCKET_INVESTIGATION.md)
- Window in report: 2026-07-27 to 2026-08-07
- Key proof points:
  - 938 ACK timeout lines in 10 days
  - subscribe/unsubscribe timeout recovery markers: 100%
  - reconnect success: 54/55 (98.18%)
  - only non-recovered reconnect on 2026-08-07 was post-market context
- Classification from report: Operational Warning

2. Master operational evidence set is still incomplete
- Source: [prc/PRC_MASTER_OPERATIONAL_AUDIT.md](prc/PRC_MASTER_OPERATIONAL_AUDIT.md)
- Key proof points:
  - required checks: 120
  - required present: 106
  - missing: 14
  - 2026-08-07 missing artifacts include trades.json and events.json
  - latest readiness snapshot at 2026-08-07 pre-open shows NOT_READY, launch_allowed=false
- Final verdict in report: Evidence Incomplete

3. Trade funnel is ultra-selective and major reject source is chop filter
- Source: [prc/PRC_TRADE_ENGINE_INVESTIGATION.md](prc/PRC_TRADE_ENGINE_INVESTIGATION.md)
- Key proof points:
  - signals: 381241
  - accepted: 5 (0.001312%)
  - rejected: 381236
  - chop family rejects: 291609 (76.49%)
  - MQ rejects: 42737 (11.21%)
- Final verdict in report: Requires Further Investigation

4. Strike rotation gives premium alignment benefit but transport-load side effect
- Source: [prc/PRC_STRIKE_ROTATION_INVESTIGATION.md](prc/PRC_STRIKE_ROTATION_INVESTIGATION.md)
- Key proof points:
  - premium moved closer-to-target in 91.87% known cases
  - premium-after inside target band in 89.05% rotations
  - rotation count and ACK timeout correlation: 0.9982
  - no proven active-session execution collapse from rotation in this window
- Final verdict in report: Neutral

5. Release readiness is approved but with explicit conditions
- Source: [prc/PRC_RELEASE_READINESS_CERTIFICATION.md](prc/PRC_RELEASE_READINESS_CERTIFICATION.md)
- Key proof points:
  - PRC status: APPROVED WITH CONDITIONS
  - real trading decision noted as CONDITIONAL
  - deferred risks include evidence completeness and DVF linkage gaps
- Final engineering decision: APPROVED WITH CONDITIONS

## 2) TCP (TPC) Friday-Cutoff Evidence

1. Strategy effectiveness is not yet capital-ready
- Source: [tcp/TPC_STRATEGY_EFFECTIVENESS_AUDIT.md](tcp/TPC_STRATEGY_EFFECTIVENESS_AUDIT.md)
- Window: 2026-07-27 to 2026-08-07
- Key proof points:
  - total PnL: -149.50
  - expectancy: negative
  - profit factor: 0.7551
  - accepted->completed is consistent but volume too low
- Final verdict: NOT READY

2. Trade replay shows payoff asymmetry and MQ-grade split impact
- Source: [tcp/TPC_TRADE_REPLAY_AND_LOSS_ANALYSIS.md](tcp/TPC_TRADE_REPLAY_AND_LOSS_ANALYSIS.md)
- Key proof points:
  - winners: MQ B
  - losers: MQ C
  - avg winner 153.62 vs avg loser -305.17
  - one hard-SL event drove largest downside
- Bottleneck theme: loss magnitude dominates winner magnitude

3. Entry decision process is rule-consistent but many accepts are borderline
- Source: [tcp/TPC_ENTRY_DECISION_CERTIFICATION.md](tcp/TPC_ENTRY_DECISION_CERTIFICATION.md)
- Key proof points:
  - Correct: 2, Borderline: 3, Wrong: 0
  - accepted band clustered in score/confidence 59-63 / 70-78
- Final verdict: ENTRY DECISION ACCEPTABLE

4. 2026-08-07 tuning evidence: entry gate is materially stricter
- Source: [tcp/TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md](tcp/TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md)
- Key proof points:
  - old pass: 23, new pass: 7
  - historically accepted 5 trades -> new gate keeps only 2
  - acceptance delta on historical accepted set: -60%
- Interpretation from report: stricter filtering removes context-thin setups

5. 2026-08-07 tuning evidence: chop-filter false-pressure reduced, but acceptance unchanged in replay sample
- Source: [tcp/TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md](tcp/TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md)
- Key proof points:
  - chop blocks 34 -> 25 (26.47% reduction)
  - accepted signals unchanged in replay sample
- Interpretation from report: non-chop gates still dominant

## 3) Cross-Document Synthesis (PRC + TCP)

Confirmed strengths:
- Runtime continuity and transport recovery are operationally decent.
- Accepted trades complete cleanly (entry->exit->closed path consistency).
- Risk control mechanisms are active and observable.

Confirmed risks:
- Evidence completeness gaps remain a formal audit blocker.
- Strategy-level payoff quality is weak (negative expectancy / PF<1 in audited window).
- Tight filtering plus narrow accepted context reduces trade breadth and confidence in robustness.

Net handover stance from PRC+TCP evidence up to Friday:
- System is operationally controllable but performance-confidence is conditional.
- Release/handover may proceed only with condition-based governance, not unconditional promotion.

## 4) What To Use Tomorrow In Compare Gate

Priority documents for opening discussion:
1. [prc/PRC_RELEASE_READINESS_CERTIFICATION.md](prc/PRC_RELEASE_READINESS_CERTIFICATION.md)
2. [prc/PRC_MASTER_OPERATIONAL_AUDIT.md](prc/PRC_MASTER_OPERATIONAL_AUDIT.md)
3. [prc/PRC_ACK_WEBSOCKET_INVESTIGATION.md](prc/PRC_ACK_WEBSOCKET_INVESTIGATION.md)
4. [tcp/TPC_STRATEGY_EFFECTIVENESS_AUDIT.md](tcp/TPC_STRATEGY_EFFECTIVENESS_AUDIT.md)
5. [tcp/TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md](tcp/TPC_ENTRY_GATE_DELTA_AFTER_TUNING_2026-08-07.md)
6. [tcp/TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md](tcp/TPC_CHOP_FILTER_REPLAY_IMPACT_2026-08-07.md)

## 5) Ready-To-Quote Evidence Lines

- PRC status: APPROVED WITH CONDITIONS
- Operational master verdict: Evidence Incomplete
- ACK investigation verdict: Operational Warning
- Strike rotation verdict: Neutral
- TPC strategy verdict: NOT READY
- Entry decision verdict: ENTRY DECISION ACCEPTABLE
