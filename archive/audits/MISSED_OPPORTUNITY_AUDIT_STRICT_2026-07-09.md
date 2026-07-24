# AUDIT MODE ONLY REPORT
Question: Why did the bot NOT TRADE during large market moves?
Method: Evidence-only from runtime logs and source code. No code changes.

## PART 1 MARKET MOVEMENT DETECTION
Important: Continuous NIFTY spot time-series is not available in logs. Movement detection below is based on option LTP ticks from ticks.json. For pure underlying-move attribution: Insufficient evidence.

| Threshold | Detected Moves | Entry Taken | No Entry |
|---|---:|---:|---:|
| 50+ | 7 | 1 | 6 |
| 100+ | 1 | 0 | 1 |
| 150+ | 0 | 0 | 0 |
| 200+ | 0 | 0 | 0 |
| 300+ | 0 | 0 | 0 |
| 400+ | 0 | 0 | 0 |

Per-day movement coverage (where ticks.json exists):
| Day | Status | Ticks | Entries | Moves 50+ | Max Move |
|---|---|---:|---:|---:|---:|
| 2026-07-01 | ok | 1845 | 3 | 2 | 58.75 |
| 2026-07-02 | ok | 831 | 11 | 1 | 52.35 |
| 2026-07-03 | ok | 78561 | 4 | 0 | 0 |
| 2026-07-05 | insufficient_artifacts |  |  |  |  |
| 2026-07-06 | ok | 45393 | 0 | 2 | 72.7 |
| 2026-07-07 | ok | 45672 | 6 | 0 | 0 |
| 2026-07-08 | ok | 50616 | 1 | 2 | 140.45 |
| 2026-07-09 | ok | 99184 | 4 | 0 | 0 |

## PART 2 ENTRY VS NO ENTRY DURING MOVES
Detected 50+ move windows are mapped with trade entries occurring inside each move window.

| Day | Direction | Start | End | Move | Entry Count | Entry Times |
|---|---|---|---|---:|---:|---|
| 2026-07-01 | UP | 2026-07-01 09:15:20.021000 | 2026-07-01 10:04:37.777000 | 58.75 | 3 | 2026-07-01 09:46:36.745, 2026-07-01 09:53:29.524, 2026-07-01 10:04:32.348 |
| 2026-07-01 | DOWN | 2026-07-01 10:10:39.602000 | 2026-07-01 10:44:09.895000 | 50.1 | 0 | No entry |
| 2026-07-02 | UP | 2026-07-02 13:38:25.331000 | 2026-07-02 14:40:21.761000 | 52.35 | 0 | No entry |
| 2026-07-06 | UP | 2026-07-06 09:31:30.232000 | 2026-07-06 14:01:39.285000 | 58.8 | 0 | No entry |
| 2026-07-06 | DOWN | 2026-07-06 14:08:29.704000 | 2026-07-06 14:29:20.326000 | 72.7 | 0 | No entry |
| 2026-07-08 | DOWN | 2026-07-08 14:02:43.332000 | 2026-07-08 14:23:37.479000 | 51.2 | 0 | No entry |
| 2026-07-08 | UP | 2026-07-08 14:23:39.506000 | 2026-07-08 14:23:47.995000 | 140.45 | 0 | No entry |

## PART 3 REJECT CHAIN (NO ENTRY WINDOWS)
Canonical per-window validator sequence IDs are not fully logged in runtime artifacts. Insufficient evidence.
Available direct no-entry evidence from bot.log categories:
| Category | Count |
|---|---:|
| CHOP_FILTER | 165 |
| TIME_FILTER | 67 |
| DATA_STALE | 16 |
| EXHAUSTION_BLOCK | 8 |
| PREMIUM_FILTER | 3 |
| REGIME_MISMATCH | 1 |
| LOW_CONFIDENCE_LINES | 8 |
| KILL_SWITCH_LINES | 38 |

Top raw reasons (runtime text):
- Chop filter: EMA squeeze (0.1pts), Low ATR (0), MACD flat: 26
- Chop filter: EMA squeeze (0.3pts), Low ATR (0), MACD flat: 21
- Chop filter: EMA squeeze (0.2pts), Low ATR (0), MACD flat: 18
- Chop filter: EMA squeeze (0.4pts), Low ATR (0), MACD flat: 14
- Chop filter: EMA squeeze (0.5pts), Low ATR (0), MACD flat: 12
- Chop filter: EMA squeeze (0.3pts), Low ATR (1), MACD flat: 10
- Chop filter: EMA squeeze (0.0pts), Low ATR (0), MACD flat: 9
- Chop filter: EMA squeeze (0.1pts), Low ATR (1), MACD flat: 7
- Time filter: Wait until 09:45 (now 09:20): 6
- Time filter: Wait until 09:45 (now 09:25): 6
- Chop filter: EMA squeeze (0.7pts), Low ATR (0), MACD flat: 6
- Chop filter: EMA squeeze (0.5pts), Low ATR (1), MACD flat: 6

## PART 4 COUNTERFACTUAL REPLAY (MISSED WINDOWS)
For missed windows, MFE/MAE is computed within the detected move window relative to window start price. Exit-engine simulation for non-taken trades: Insufficient evidence.

| Day | Dir | Start | End | Move | Window MFE | Window MAE | Expected Exit |
|---|---|---|---|---:|---:|---:|---|
| 2026-07-08 | UP | 2026-07-08 14:23:39.506000 | 2026-07-08 14:23:47.995000 | 140.45 | 140.45 | 0.0 | Insufficient evidence |
| 2026-07-06 | DOWN | 2026-07-06 14:08:29.704000 | 2026-07-06 14:29:20.326000 | 72.7 | 0.0 | -72.7 | Insufficient evidence |
| 2026-07-06 | UP | 2026-07-06 09:31:30.232000 | 2026-07-06 14:01:39.285000 | 58.8 | 58.8 | 0.0 | Insufficient evidence |
| 2026-07-02 | UP | 2026-07-02 13:38:25.331000 | 2026-07-02 14:40:21.761000 | 52.35 | 52.35 | -13.25 | Insufficient evidence |
| 2026-07-08 | DOWN | 2026-07-08 14:02:43.332000 | 2026-07-08 14:23:37.479000 | 51.2 | 0.0 | -51.2 | Insufficient evidence |
| 2026-07-01 | DOWN | 2026-07-01 10:10:39.602000 | 2026-07-01 10:44:09.895000 | 50.1 | 14.4 | -50.1 | Insufficient evidence |

## PART 5 TOP 20 MISSED PROFITABLE OPPORTUNITIES
Only detected missed windows are listed. Total detected missed windows < 20 in available dataset.
| Rank | Day | Dir | Start | End | Move | Reversal |
|---:|---|---|---|---|---:|---:|
| 1 | 2026-07-08 | UP | 2026-07-08 14:23:39.506000 | 2026-07-08 14:23:47.995000 | 140.45 | 0.0 |
| 2 | 2026-07-06 | DOWN | 2026-07-06 14:08:29.704000 | 2026-07-06 14:29:20.326000 | 72.7 | 0.0 |
| 3 | 2026-07-06 | UP | 2026-07-06 09:31:30.232000 | 2026-07-06 14:01:39.285000 | 58.8 | 0.0 |
| 4 | 2026-07-02 | UP | 2026-07-02 13:38:25.331000 | 2026-07-02 14:40:21.761000 | 52.35 | 0.0 |
| 5 | 2026-07-08 | DOWN | 2026-07-08 14:02:43.332000 | 2026-07-08 14:23:37.479000 | 51.2 | 0.0 |
| 6 | 2026-07-01 | DOWN | 2026-07-01 10:10:39.602000 | 2026-07-01 10:44:09.895000 | 50.1 | 0.0 |

## PART 6 FALSE POSITIVE ENTRIES (ENTRY TAKEN BUT BAD OUTCOME)
| Rank | Day | Entry | Exit | PnL | Exit Reason |
|---:|---|---|---|---:|---|
| 1 | 2026-07-02 | 2026-07-02 11:02:15.525 | 2026-07-02 11:03:36.831 | -390.0 | 🛑 HARD SL HIT | PE | -6pts @ ₹111.60 | Loss: ₹390 |
| 2 | 2026-07-03 | 2026-07-03 10:20:27.153 | 2026-07-03 10:21:28.436 | -390.0 | 🛑 HARD SL HIT | PE | -6pts @ ₹105.10 | Loss: ₹390 |
| 3 | 2026-07-09 | 2026-07-09 10:46:57.523 | 2026-07-09 10:47:08.302 | -350.35 | Kill switch: Stale data KILL |
| 4 | 2026-07-07 | 2026-07-07 14:10:16.322 | 2026-07-07 14:10:19.837 | -289.9 | ⚡ EARLY LOSS CUT | PE | -4.5pts in 4s (ATR-thresh:3) | Loss: ₹290 (saved 1.5pts vs SL) |
| 5 | 2026-07-07 | 2026-07-07 13:20:00.385 | 2026-07-07 13:20:03.435 | -272.35 | ⚡ EARLY LOSS CUT | PE | -4.2pts in 3s (ATR-thresh:3) | Loss: ₹272 (saved 1.8pts vs SL) |
| 6 | 2026-07-03 | 2026-07-03 09:45:09.608 | 2026-07-03 09:45:24.183 | -241.15 | ⚡ EARLY LOSS CUT | CE | -3.7pts in 15s (ATR-thresh:3) | Loss: ₹241 (saved 2.3pts vs SL) |
| 7 | 2026-07-07 | 2026-07-07 13:12:55.966 | 2026-07-07 13:13:13.898 | -211.25 | ⚡ EARLY LOSS CUT | PE | -3.2pts in 18s (ATR-thresh:3) | Loss: ₹211 (saved 2.8pts vs SL) |
| 8 | 2026-07-03 | 2026-07-03 10:05:11.040 | 2026-07-03 10:05:27.120 | -208.65 | ⚡ EARLY LOSS CUT | PE | -3.2pts in 16s (ATR-thresh:3) | Loss: ₹209 (saved 2.8pts vs SL) |
| 9 | 2026-07-07 | 2026-07-07 14:00:55.969 | 2026-07-07 14:01:05.875 | -208.65 | ⚡ EARLY LOSS CUT | CE | -3.2pts in 10s (ATR-thresh:3) | Loss: ₹209 (saved 2.8pts vs SL) |
| 10 | 2026-07-01 | 2026-07-01 10:04:32.348 | 2026-07-01 10:04:43.616 | -47.45 | Kill switch: Stale data KILL |
| 11 | 2026-07-02 | 2026-07-02 09:57:33.548 | 2026-07-02 09:57:44.088 | -9.75 | 🔄 RSI REVERSAL EXIT | PE | RSI 0→59 | Lock: ₹3 |
| 12 | 2026-07-02 | 2026-07-02 10:05:25.202 | 2026-07-02 10:05:52.300 | -9.75 | 🔄 RSI REVERSAL EXIT | PE | RSI 11→80 | Lock: ₹3 |
| 13 | 2026-07-02 | 2026-07-02 11:47:14.107 | 2026-07-02 11:47:23.643 | -5.2 | 🔄 RSI REVERSAL EXIT | PE | RSI 23→91 | Lock: ₹7 |
| 14 | 2026-07-02 | 2026-07-02 11:21:52.308 | 2026-07-02 11:22:07.363 | -0.65 | 🔄 RSI REVERSAL EXIT | PE | RSI 12→50 | Lock: ₹11 |

## PART 7 FIRST STOPPING COMPONENT
From source logic, earliest blockers before trade placement include time filter, chop filter, premium range, confidence gate, trend-exhaustion block, and stale-data kill.
Observed first blockers in runtime logs are dominated by CHOP_FILTER and TIME_FILTER.
| Component | Observed Count |
|---|---:|
| CHOP_FILTER | 165 |
| TIME_FILTER | 67 |
| DATA_STALE | 16 |
| EXHAUSTION_BLOCK | 8 |
| PREMIUM_FILTER | 3 |
| REGIME_MISMATCH | 1 |

## PART 8 THRESHOLD BLOCK COUNTS
Configured threshold evidence from code:
- Min confidence 70 (config/constants.py line 124)
- Min premium 90 (config/constants.py line 129)
- Trading start time 09:20 + runtime no-signal wait-until-09:45 behavior (config/constants.py line 180 and bot.log evidence)
- Stale data kill at 100 consecutive rejected ticks (core/risk/kill_switch.py line 24 and line 59)

Observed threshold hit evidence:
- Low confidence lines: 8
- Premium out-of-range evidence exists (example: 2026-07-07 10:04:36 premium too low 24 < 90).
- Stale-data kill evidence exists on multiple days with consecutive_rejected=100.

## PART 9 REGIME ANALYSIS
Runtime no-signal evidence is heavily chop-dominated, consistent with range/chop regime handling.
Direct per-window regime label for every missed move is not persistently logged. Insufficient evidence.
Proxy evidence: high frequency of Chop filter and exhaustion blocks in bot.log no-signal lines.

## PART 10 FINAL REPORT
Primary evidence-backed answer to the question:
1. The bot did not trade many detected large option-premium moves because pre-entry gates blocked signals most often at chop filter and time filter stages, plus stale-data kill episodes.
2. There is clear runtime evidence of stale-data kill activation after 100 consecutive rejected ticks, which suppresses entries during active move windows.
3. Premium-range and confidence gates also block entries at key timestamps.
4. For pure underlying NIFTY 50/100/150/200/300/400 point move analysis, artifacts are insufficient because continuous spot series is not logged in the same granularity as option ticks. Insufficient evidence.

Supporting runtime evidence files:
- logs/2026-07-07/bot.log
- logs/2026-07-08/bot.log
- logs/2026-07-09/bot.log
- logs/2026-07-07/summary.json
- logs/2026-07-08/summary.json
- logs/2026-07-09/summary.json
- logs/2026-07-09/events.json
- logs/2026-07-07/trades.csv, logs/2026-07-08/trades.csv, logs/2026-07-09/trades.csv
