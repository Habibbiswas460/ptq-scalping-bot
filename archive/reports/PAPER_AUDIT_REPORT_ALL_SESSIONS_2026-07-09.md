# Paper Trading Audit Report (Read-Only Evidence)

Generated: 2026-07-09 20:04:56
Audit mode: EVIDENCE ONLY. No code changes were made.

## Scope Reviewed
Reviewed files (where present): summary.json, mq_validation.json, trades.csv, trades.json, events.json, ticks.json, bot.log, errors.log, states.log

Paper session directories reviewed: 13
- logs/2026-07-01
- logs/2026-07-02
- logs/2026-07-03
- logs/2026-07-07
- logs/2026-07-08
- logs/2026-07-09
- logs/backup_logs/2026-03-16
- logs/backup_logs/2026-03-25
- logs/backup_logs/2026-03-27
- logs/backup_logs/2026-04-29
- logs/backup_logs/2026-05-18
- logs/backup_logs/2026-05-19
- logs/backup_logs/2026-06-04

## P1 - Kill Switch Investigation

- Kill switch triggers found (`KILL_SWITCH ACTIVATED`): 18

| Timestamp | Reason | Active position? | Unrealized PnL | WebSocket status | Tick freshness | Market quality | Confidence | Score | Session | Volatility | Exit reason | Evidence |
|---|---|---|---:|---|---|---|---:|---:|---|---|---|---|
| 2026-03-27 11:33:09 | Max daily trades hit | True | -1040.00 | Not logged | Not logged | Not logged at kill timestamp | 80 | 8 | Midday | Not logged at kill timestamp | 🛑 HARD SL HIT | PE | -8pts @ ₹239.00 | Loss: ₹1040 | `[11:33:09] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Max daily trades hit | Details: {"trades": 15}` |
| 2026-04-29 13:37:17 | Max daily trades hit | False | NA | Not logged | Not logged | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[13:37:17] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Max daily trades hit | Details: {"trades": 15}` |
| 2026-05-19 14:36:00 | Stale data KILL | True | -6276.40 | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp | 84 | 7 | Closing | Not logged at kill timestamp | Kill switch: Stale data KILL | `[14:36:00] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-01 09:15:20 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Opening | Not logged at kill timestamp |  | `[09:15:20] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-01 09:16:21 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Opening | Not logged at kill timestamp |  | `[09:16:21] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-01 09:17:22 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Opening | Not logged at kill timestamp |  | `[09:17:22] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-01 09:18:23 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Opening | Not logged at kill timestamp |  | `[09:18:23] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-01 10:04:43 | Stale data KILL | True | -47.45 | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp | 81 | 9 | Morning | Not logged at kill timestamp | Kill switch: Stale data KILL | `[10:04:43] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-02 11:56:36 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Midday | Not logged at kill timestamp |  | `[11:56:36] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-03 10:21:28 | Kill switch daily loss | True | -390.00 | Not logged | Not logged | Not logged at kill timestamp | 81 | 9 | Morning | Not logged at kill timestamp | 🛑 HARD SL HIT | PE | -6pts @ ₹105.10 | Loss: ₹390 | `[10:21:28] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Kill switch daily loss | Details: {"daily_pnl_inr": -794.3}` |
| 2026-07-07 14:10:32 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[14:10:32] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-08 12:58:07 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Midday | Not logged at kill timestamp |  | `[12:58:07] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-08 13:17:55 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[13:17:55] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-08 13:38:29 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[13:38:29] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-09 10:47:08 | Stale data KILL | True | -350.35 | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp | 78 | 63 | Morning | Not logged at kill timestamp | Kill switch: Stale data KILL | `[10:47:08] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-09 14:04:43 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[14:04:43] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-09 14:06:04 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[14:06:04] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |
| 2026-07-09 14:28:32 | Stale data KILL | False | NA | Not logged | stale/rejected ticks=100 | Not logged at kill timestamp |  |  | Afternoon | Not logged at kill timestamp |  | `[14:28:32] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}` |

### Frequency table (grouped by reason)
| Reason | Count |
|---|---:|
| Stale data KILL | 15 |
| Max daily trades hit | 2 |
| Kill switch daily loss | 1 |

Was every kill switch justified?
- Stale-data triggers: 15. Justified by explicit trigger evidence (`consecutive_rejected` in details where present).
- Non-stale triggers: 3. Insufficient statistical evidence for strict justification because pre-trigger MQ/confidence/ws snapshots are not logged at trigger rows.
Could any have been avoided?
- Insufficient statistical evidence.
- Required pre-trigger state snapshots (MQ, confidence, ws health, unrealized PnL stream) are not consistently present at trigger timestamps.

## P2 - Tick Quality Investigation
- Received ticks: 834530
- Valid ticks: 275364
- Filtered ticks: 559166
- Invalid ticks: 558834
- Stale ticks: 106491
- Duplicate ticks: 0
- Missing ticks: 0
- Late ticks: 0

| Metric | % of Received |
|---|---:|
| Valid | 33.00% |
| Filtered | 67.00% |
| Invalid | 66.96% |
| Stale | 12.76% |
| Duplicate | 0.00% |
| Missing | 0.00% |
| Late | 0.00% |

### TOP 10 rejection reasons
| Reason | Count | % |
|---|---:|---:|
| Low volume | 158925 | 57.40% |
| Bid >= Ask (inverted market) | 11464 | 4.14% |
| Stale tick (5286ms old) | 199 | 0.07% |
| Stale tick (5184ms old) | 199 | 0.07% |
| Stale tick (5082ms old) | 197 | 0.07% |
| Stale tick (5489ms old) | 194 | 0.07% |
| Stale tick (5083ms old) | 184 | 0.07% |
| Stale tick (5183ms old) | 183 | 0.07% |
| Stale tick (5387ms old) | 181 | 0.07% |
| Stale tick (5386ms old) | 176 | 0.06% |

Which validator rejects most ticks?
- Proxy from reject-text categories: Volume/Quantity filter (158925, 57.40% of mapped rejects).
Which validator is too aggressive?
- Insufficient statistical evidence.
Which validator never rejects?
- Insufficient statistical evidence. Reject reasons are text-level and do not consistently encode canonical validator IDs across all sessions.

## P3 - Biggest Loss Investigation
| Rank | Entry | Exit | Holding time | MQ | Confidence | Score | Session | Trend | RSI | VWAP relation | ATR | Delta | Gamma | IV | PCR | OI | Volume | Exit reason | Could this trade be avoided? | If yes which validator? |
|---:|---|---|---:|---|---:|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 (PAPER_1779164145_0) | 2026-05-19 09:45:45 | 2026-05-19 14:36:00 | 17414.74 | Not logged | 84 | 7 | Opening | BEARISH (100%) | 27 | Below_VWAP | Not logged | 0.7552217971367983 | 0.0021878171939954806 | Not logged | Not logged | Not logged | Not logged | Kill switch: Stale data KILL | Not proven (post-entry kill event) | Insufficient statistical evidence. |
| 2 (PAPER_1774412236_0) | 2026-03-25 09:47:16 | 2026-03-25 09:47:46 | 30.12 | Not logged | 90 | 9 | Opening | BEARISH (100%) |  |  | Not logged | 0.534214750601163 | 0.001300994169721481 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹125.47 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 3 (PAPER_1774585876_0) | 2026-03-27 10:01:16 | 2026-03-27 10:01:59 | 42.23 | Not logged | 80 | 8 | Morning | BEARISH (100%) |  |  | Not logged | 0.5159463748258255 | 0.0006557211160663399 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹248.00 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 4 (PAPER_1774586624_2) | 2026-03-27 10:13:44 | 2026-03-27 10:21:04 | 439.94 | Not logged | 80 | 8 | Morning | BEARISH (100%) |  |  | Not logged | 0.5072207566817047 | 0.0006298346538656856 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹244.05 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 5 (PAPER_1774588020_5) | 2026-03-27 10:37:00 | 2026-03-27 10:38:56 | 115.79 | Not logged | 80 | 8 | Morning | BEARISH (100%) |  |  | Not logged | 0.5188372892084784 | 0.0007054807407045316 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹224.85 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 6 (PAPER_1774589350_9) | 2026-03-27 10:59:10 | 2026-03-27 11:00:49 | 99.35 | Not logged | 80 | 8 | Morning | BEARISH (100%) |  |  | Not logged | 0.499969716677768 | 0.0006234909802857125 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹240.60 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 7 (PAPER_1774591330_3) | 2026-03-27 11:32:10 | 2026-03-27 11:33:09 | 58.55 | Not logged | 80 | 8 | Midday | BEARISH (100%) |  |  | Not logged | 0.5054086513508338 | 0.0006433924501783012 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -8pts @ ₹239.00 | Loss: ₹1040 | No (not proven) | Insufficient statistical evidence. |
| 8 (PAPER_1777439808_3) | 2026-04-29 10:46:48 | 2026-04-29 10:53:22 | 394.05 | Not logged | 72 | 6 | Morning | BEARISH (100%) | 10 |  | Not logged | 0.515774526910234 | 0.0009590050378213267 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -6pts @ ₹162.50 | Loss: ₹780 | No (not proven) | Insufficient statistical evidence. |
| 9 (PAPER_1777440949_1) | 2026-04-29 11:05:49 | 2026-04-29 11:08:22 | 153.32 | Not logged | 72 | 6 | Morning | BEARISH (100%) | 0 |  | Not logged | 0.5314833343678964 | 0.0010293556109338012 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -6pts @ ₹159.50 | Loss: ₹780 | No (not proven) | Insufficient statistical evidence. |
| 10 (PAPER_1779096574_2) | 2026-05-18 14:59:34 | 2026-05-18 15:00:12 | 38.62 | Not logged | 84 | 7 | Closing | BEARISH (100%) |  |  | Not logged | 0.5037314056792758 | 0.0012395153085626885 | Not logged | Not logged | Not logged | Not logged | 🛑 HARD SL HIT | PE | -6pts @ ₹114.65 | Loss: ₹780 | No (not proven) | Insufficient statistical evidence. |

Avoidability determination: Insufficient statistical evidence.
Reason: per-trade MQ/ATR/IV/PCR/OI/Volume and canonical validator-fail traces at entry are not consistently logged.

## P4 - Confidence Calibration Investigation
- Trades with confidence available: 66
| Band | Trades | Wins | Losses | Win Rate | Average PnL | Median PnL | Max Win | Max Loss | Expected Win Rate | Actual Win Rate | Calibration Error |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50-59 | 0 | 0 | 0 | % |  |  |  |  | % | % |  |
| 60-69 | 0 | 0 | 0 | % |  |  |  |  | % | % |  |
| 70-79 | 32 | 19 | 13 | 59.38% | -34.57 | 9.75 | 877.50 | -780.00 | 71.97% | 59.38% | -12.59 |
| 80-89 | 29 | 17 | 12 | 58.62% | -228.08 | 7.80 | 1534.00 | -6276.40 | 80.69% | 58.62% | -22.07 |
| 90+ | 5 | 4 | 1 | 80.00% | 35.62 | 76.70 | 1032.20 | -1040.00 | 94.80% | 80.00% | -14.80 |
Is confidence overestimating? Yes
Is confidence underestimating? No/Not observed
Which band is best? 90+ (Actual Win Rate 80.00%).

## P5 - Session Performance Investigation
| Session | Trades | Wins | Losses | Win Rate | Average Hold Time | Average PnL | Profit Factor | Largest Win | Largest Loss | Average MQ | Average Confidence | Average Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Opening | 7 | 3 | 4 | 42.86% | 2529.54 | -937.58 | 0.13 | 928.20 | -6276.40 |  | 81.29 | 8.43 |
| Morning | 33 | 19 | 14 | 57.58% | 71.76 | -28.88 | 0.87 | 1534.00 | -1040.00 |  | 78.97 | 9.61 |
| Midday | 8 | 6 | 2 | 75.00% | 89.21 | -52.81 | 0.60 | 193.70 | -1040.00 |  | 74.12 | 6.88 |
| Afternoon | 13 | 9 | 4 | 69.23% | 24.56 | 62.85 | 1.83 | 877.50 | -289.90 |  | 71.46 | 47.15 |
| Closing | 5 | 3 | 2 | 60.00% | 40.48 | -84.24 | 0.73 | 1032.20 | -780.00 |  | 84.00 | 7.00 |
| Outside | 0 | 0 | 0 | % |  |  |  |  |  |  |  |  |
Best session: Midday (Win Rate 75.00%, Avg PnL -52.81).
Worst session: Opening (Win Rate 42.86%, Avg PnL -937.58).
Should any session be disabled? Insufficient statistical evidence.

## FINAL REPORT
### 1. Top 10 improvements (ranked by expected impact)
1. Add structured pre-kill forensic snapshot fields at trigger time.
2. Persist confidence/score/MQ/trend/RSI/VWAP in trade records.
3. Persist ATR/IV/PCR/OI/Volume at trade entry.
4. Standardize events.json schema across all sessions.
5. Standardize ticks.json availability and schema across all sessions.
6. Normalize reject reasons to canonical validator IDs.
7. Add explicit duplicate/missing/late/stale counters in summary.json.
8. Log websocket health snapshots periodically and at kill time.
9. Store unrealized PnL at kill trigger timestamp.
10. Store session label directly in each trade record.
### 2. What should remain unchanged
- Kill switch enabled behavior.
- Detailed exit_reason logging.
- Daily summary.json generation.
### 3. Issue severity
- Critical: Missing structured pre-kill forensic fields.
- High: Missing per-trade feature set required for causal audit.
- Medium: Schema inconsistency across historical sessions.
- Low: Session metadata not embedded directly in trade rows.
### 4. Evidence-only compliance
- No implementation, no fixes, no code modification in this request.
- Unsupported fields are marked with "Not logged" or "Insufficient statistical evidence."
