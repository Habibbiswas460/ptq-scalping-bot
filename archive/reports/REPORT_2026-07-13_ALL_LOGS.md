# Daily Report - 2026-07-13 (All Logs)

- Generated at: 2026-07-13 18:50:06
- Log directory: logs/2026-07-13
- Files reviewed: 13

## File Inventory

| File | Size (bytes) | Lines |
|---|---:|---:|
| app.log | 807 | 1 |
| bot.log | 28195345 | 200101 |
| errors.log | 303 | 3 |
| events.json | 1036 | 6 |
| mq_validation.json | 40940 | 2118 |
| mq_validation.txt | 19864 | 543 |
| states.log | 452 | 5 |
| summary.json | 346 | 15 |
| ticks.json | 45978786 | 191641 |
| ticks.log | 17213138 | 191642 |
| trades.csv | 570 | 3 |
| trades.json | 746 | 2 |
| trades.log | 406 | 3 |

## Session Summary

- total_trades: 1
- winning_trades: 0
- losing_trades: 1
- total_pnl: -238.55000000000013
- max_drawdown: -238.55000000000013
- kill_switch_count: 2
- ticks_received: 196342
- ticks_valid: 4697
- ticks_invalid: 191641
- ticks_processed: 191641
- entries: 1
- exits: 1
- session_duration_sec: 22801.092317
- tick_valid_pct: 2.39%
- tick_invalid_pct: 97.61%

## Trades Evidence

- trades.csv records (excluding header): 2
- exits in trades.csv: 1
- aggregated realized pnl from trades.csv: -238.55
- last trades.csv rows:
  - 2026-07-13 10:29:45.390 | ENTRY | NIFTY14JUL2624100CE | qty=65 | entry=111.87 | exit=- | pnl=-
  - 2026-07-13 10:29:47.399 | EXIT | - | qty=- | entry=- | exit=108.04 | pnl=-238.55000000000013
- trades.json events: 2
- first trades.json event: ENTRY at 2026-07-13 10:29:45.390
- last trades.json event: EXIT at 2026-07-13 10:29:47.399
- trades.log lines: 3
  - [10:29:45] [ENTRY] ENTRY #1 | OrderID: PAPER_1783918785_0 | Symbol: NIFTY14JUL2624100CE | Side: BUY | Qty: 65 | Price: ₹111.87 | Reason: Entry signal
  - [10:29:47] [EXIT] EXIT ❌ | OrderID: PAPER_1783918785_0 | Price: ₹108.04 | PnL: ₹-238.55 (-0.80%) | Hold: 2.0s | Reason: ⚡ EARLY LOSS CUT | CE | -3.7pts in 2s (ATR-thresh:3) | Loss: ₹239 (saved 2.3pts vs SL)

## State and Event Timeline

- states.log lines: 5
  - [10:29:44] [STATE] STATE: IDLE → ENTRY_READY | Reason: SMART SCALP v3.4 | CE | Conf: 75% | Score: 60 | EMA9>21 | EMA9_Pullback | Green_Candle | Close>EMA9 | 📉 BEARISH (50%) [EMA↗]
  - [10:29:45] [STATE] STATE: ENTRY_READY → IN_TRADE | Reason: Order: PAPER_1783918785_0
  - [10:29:48] [STATE] STATE: IN_TRADE → COOLDOWN | Reason: Cooldown 300s
  - [10:34:48] [STATE] STATE: COOLDOWN → IDLE | Reason: Cooldown ended
- events.json records: 6
- events by type:
  - kill_switch: 2
  - state_change: 4
  - kill_switch at 2026-07-13T09:45:11.402696 | trigger=Stale data KILL | details={'consecutive_rejected': 100, 'cooldown_sec': 30}
  - kill_switch at 2026-07-13T10:56:19.473469 | trigger=Stale data KILL | details={'consecutive_rejected': 100, 'cooldown_sec': 30}

## Error Surface

- errors.log lines: 3
  - [09:45:11] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}
  - [10:56:19] [KILL] 🛑 KILL_SWITCH ACTIVATED | Trigger: Stale data KILL | Details: {"consecutive_rejected": 100, "cooldown_sec": 30}
- app.log lines: 1
- app.log sample (sanitized): [E 260713 10:29:45 smartConnect:246] Error occurred while making a POST request to https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData. Error: Symbol token not found in scrip master cache for the given exchange. URL: https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData,

## Bot Runtime Diagnostics (bot.log)

- bot.log lines: 200101
- entry_lines: 0
- exit_lines: 0
- kill_lines: 4
- invalid_tick_lines: 191641
- no_signal_lines: 12
- top no-signal reasons:
  - Chop filter: EMA squeeze (0.5pts), Low ATR (0), MACD flat: 2
  - Time filter: Wait until 09:45 (now 09:30): 1
  - Time filter: Wait until 09:45 (now 09:32): 1
  - Time filter: Wait until 09:45 (now 09:39): 1
  - Time filter: Wait until 09:45 (now 09:41): 1
  - Chop filter: EMA squeeze (0.6pts), Low ATR (1), MACD flat: 1
  - Chop filter: EMA squeeze (0.2pts), Low ATR (0), MACD flat: 1
  - Chop filter: EMA squeeze (0.4pts), Low ATR (1), MACD flat: 1
  - Tick Stale (920ms > 800ms): 1
  - Chop filter: EMA squeeze (0.3pts), Low ATR (0), MACD flat: 1
  - Premium too low ₹89 < ₹90: 1

## Tick Diagnostics (ticks.json + ticks.log)

- ticks.json records: 191641
- accepted=true: 0
- accepted=false: 191641
- top reject reasons:
  - Low volume: 92654
  - Stale tick (5589ms old): 249
  - Stale tick (5792ms old): 246
  - Stale tick (5894ms old): 246
  - Stale tick (5081ms old): 238
  - Stale tick (5182ms old): 234
  - Stale tick (6097ms old): 232
  - Stale tick (5386ms old): 230
  - Stale tick (5995ms old): 228
  - Stale tick (5487ms old): 227
  - Stale tick (5284ms old): 226
  - Stale tick (5080ms old): 224
- first ticks.json ts: 2026-07-13 09:15:05.434
- last ticks.json ts: 2026-07-13 15:30:00.991
- ticks.log lines: 191642
- ticks.log first event: [2026-07-13 09:15:05.435] [REJECT] TICK_REJECTED | Reason: Stale tick (5007ms old) | LTP: 86.35
- ticks.log last event: [2026-07-13 15:30:00.992] [REJECT] TICK_REJECTED | Reason: Low volume | LTP: 93.55

## Market Quality Validation

- mq_validation.json lines: 2118
- top-level keys: generated_at, days, market_quality_distribution, hard_reject_stats, quality_vs_win_rate, quality_grade_vs_win_rate, confidence_vs_win_rate, confidence_calibration, quality_grade_avg_pnl
- market_quality_distribution:
  - A: 159
  - A+: 1
  - B: 40683
  - C: 35901
  - REJECT: 10318
- top hard rejects (first 10):
  - Tick Stale (1282ms > 1200ms): 5
  - Tick Stale (1263ms > 1200ms): 5
  - Tick Stale (1243ms > 1200ms): 5
  - Tick Stale (1237ms > 1200ms): 5
  - Tick Stale (1234ms > 1200ms): 5
  - Tick Stale (1226ms > 1200ms): 5
  - Tick Stale (1222ms > 1200ms): 5
  - Tick Stale (1278ms > 1200ms): 4
  - Tick Stale (1230ms > 1200ms): 4
  - Tick Stale (1220ms > 1200ms): 4
- mq_validation.txt lines: 543
- mq_validation.txt first line: ========================================================================
- mq_validation.txt last line:        C       5       32.24      161.20

## Final Outcome

- Net result: trades=1 | pnl=-238.55000000000013
- Kill switches: 2
- Tick health: valid=4697 / received=196342
- Full coverage confirmation:
- reviewed: app.log
- reviewed: bot.log
- reviewed: errors.log
- reviewed: events.json
- reviewed: mq_validation.json
- reviewed: mq_validation.txt
- reviewed: states.log
- reviewed: summary.json
- reviewed: ticks.json
- reviewed: ticks.log
- reviewed: trades.csv
- reviewed: trades.json
- reviewed: trades.log
