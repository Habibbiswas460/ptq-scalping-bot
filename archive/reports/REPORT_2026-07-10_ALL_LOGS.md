# 10-07-2026 Full Log Report

- Generated at: 2026-07-10 19:36:42
- Scope directory: logs/2026-07-10
- Total files reviewed: 11

## File Inventory (No file skipped)

| File | Size (bytes) | Lines |
|---|---:|---:|
| app.log | 277552 | 132 |
| bot.log | 144830 | 1340 |
| errors.log | 951 | 9 |
| mq_validation.json | 40704 | 2106 |
| mq_validation.txt | 19753 | 540 |
| states.log | 37 | 1 |
| summary.json | 304 | 15 |
| ticks.json | 24145 | 98 |
| ticks.log | 9543 | 99 |
| trades.csv | 165 | 1 |
| trades.log | 37 | 1 |

## Summary Snapshot (summary.json)

- total_trades: 0
- winning_trades: 0
- losing_trades: 0
- total_pnl: 0.0
- max_drawdown: 0
- kill_switch_count: 0
- ticks_received: 41763
- ticks_valid: 41665
- ticks_invalid: 98
- ticks_processed: 98
- entries: 0
- exits: 0
- session_duration_sec: 22801.447352

## Trades (trades.csv + trades.log)

- Trade rows (excluding header): 0
- No trade entry/exit records for 10-07-2026.
- trades.log start marker: # Log started at 2026-07-10 08:09:09

## Tick Quality (ticks.json + ticks.log)

- Logged tick snapshots in ticks.json: 98
- accepted=true: 0
- accepted=false: 98
- LTP range in snapshots: 109.45 to 225.70
- Top reject reasons from ticks.json:
  - Stale tick (5257ms old): 1
  - Stale tick (5359ms old): 1
  - Stale tick (5460ms old): 1
  - Stale tick (5561ms old): 1
  - Stale tick (5663ms old): 1
  - Stale tick (5764ms old): 1
  - Stale tick (5866ms old): 1
  - Stale tick (5968ms old): 1
  - Stale tick (6069ms old): 1
  - Stale tick (6171ms old): 1
- ticks.log lines: 99
- ticks.log first event: [2026-07-10 09:16:46.874] [REJECT] TICK_REJECTED | Reason: Stale tick (5257ms old) | LTP: 222.65
- ticks.log last event: [2026-07-10 09:34:38.533] [REJECT] TICK_REJECTED | Reason: Stale tick (5342ms old) | LTP: 109.45

## Bot Runtime Analysis (bot.log)

- bot.log lines: 1340
- SIGNAL lines: 0
- No signal lines: 131
- Low confidence lines: 0
- INVALID_TICK warnings: 98
- Kill switch lines: 0
- ENTRY lines: 0
- EXIT lines: 0

Top No-Signal reasons:
- Chop filter: EMA squeeze (0.2pts), Low ATR (0), MACD flat: 21
- Chop filter: EMA squeeze (0.1pts), Low ATR (0), MACD flat: 17
- Chop filter: EMA squeeze (0.4pts), Low ATR (0), MACD flat: 16
- Chop filter: EMA squeeze (0.3pts), Low ATR (0), MACD flat: 11
- Chop filter: EMA squeeze (0.0pts), Low ATR (0), MACD flat: 10
- Chop filter: EMA squeeze (0.5pts), Low ATR (0), MACD flat: 8
- Chop filter: EMA squeeze (0.6pts), Low ATR (0), MACD flat: 5
- Chop filter: EMA squeeze (0.7pts), Low ATR (0), MACD flat: 3
- Chop filter: EMA squeeze (0.1pts), Low ATR (1), MACD flat: 2
- Tick Stale (860ms > 800ms): 2
- Tick Stale (909ms > 800ms): 2
- Time filter: Wait until 09:45 (now 09:22): 1

- First key line: [08:09:12] [INFO] ✅ NIFTY Spot: ₹23,962.80 → ATM Strike: 23950
- Last key line: [2026-07-10 15:14:20.257] [DEBUG] No signal: Chop filter: EMA squeeze (0.2pts), Low ATR (0), MACD flat

## App Connectivity Errors (app.log)

- app.log lines: 132
- NameResolutionError occurrences: 132
- timeout-related occurrences: 0
- connection reset occurrences: 0
- First error sample (sanitized): [E 260710 09:15:00 smartConnect:221] Error occurred while making a POST request to https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData.
- Last error sample (sanitized): [E 260710 09:16:41 smartConnect:221] Error occurred while making a POST request to https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData.

## Error Log (errors.log)

- errors.log lines: 9
- Captured errors:
  - # Log started at 2026-07-10 08:09:09
  - [09:15:00] [ERROR] LTP error for NIFTY: HTTPSConnectionPool(host='apiconnect.angelone.in', port=443): Max retries exceeded with url: /rest/secure/angelbroking/order/v1/getLtpData (Caused by NameResolutionError("HTTPSConnection(host='apiconnect.angelone.in', port=443): Failed to resolve 'apiconnect.angelone.in' ([Errno -3] Temporary failure in name resolution)"))
  - [09:15:07] [ERROR] WebSocket error: ping/pong timed out
  - [09:15:09] [ERROR] WebSocket error: [Errno -3] Temporary failure in name resolution
  - [09:15:21] [ERROR] WebSocket error: [Errno -3] Temporary failure in name resolution
  - [09:15:35] [ERROR] WebSocket error: [Errno -3] Temporary failure in name resolution
  - [09:15:53] [ERROR] WebSocket error: [Errno -3] Temporary failure in name resolution
  - [09:16:20] [ERROR] WebSocket error: [Errno -3] Temporary failure in name resolution
  - [09:34:32] [ERROR] WebSocket error: [Errno 104] Connection reset by peer

## State Machine Log (states.log)

- states.log lines: 1
  - # Log started at 2026-07-10 08:09:09

## Market Quality Validation (mq_validation.json + mq_validation.txt)

- mq_validation.json lines: 2106
- JSON top-level keys: generated_at, days, market_quality_distribution, hard_reject_stats, quality_vs_win_rate, quality_grade_vs_win_rate, confidence_vs_win_rate, confidence_calibration, quality_grade_avg_pnl
- market_quality_distribution:
  - A: 159
  - A+: 1
  - B: 39728
  - C: 34842
  - REJECT: 10051
- top hard_reject_stats (first 8):
  - Tick Stale (1282ms > 1200ms): 5
  - Tick Stale (1263ms > 1200ms): 5
  - Tick Stale (1243ms > 1200ms): 5
  - Tick Stale (1237ms > 1200ms): 5
  - Tick Stale (1234ms > 1200ms): 5
  - Tick Stale (1226ms > 1200ms): 5
  - Tick Stale (1278ms > 1200ms): 4
  - Tick Stale (1230ms > 1200ms): 4
- confidence_calibration:
  - 70-79: trades=10, realized_win_rate_pct=60.0, calibration_error_pct=11.3
- mq_validation.txt lines: 540
- mq_validation.txt first line: ========================================================================
- mq_validation.txt last line:        C       5       32.24      161.20

## Final Day Assessment (10-07-2026)

- Trading outcome: total_trades=0, total_pnl=0.0
- Kill switch count: 0
- Tick quality: received=41763, valid=41665, invalid=98
- Valid ratio: 99.77% | Invalid ratio: 0.23%
- No trades executed today (trades.csv only header, trades.log only start marker).

## Coverage Confirmation

- Reviewed: app.log
- Reviewed: bot.log
- Reviewed: errors.log
- Reviewed: mq_validation.json
- Reviewed: mq_validation.txt
- Reviewed: states.log
- Reviewed: summary.json
- Reviewed: ticks.json
- Reviewed: ticks.log
- Reviewed: trades.csv
- Reviewed: trades.log
