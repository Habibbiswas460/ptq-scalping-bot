# Root Cause Summary (Quick View)

Date: 2026-08-09
Source: archive/root_cause/ROOT_CAUSE_ANALYSIS_PLAN.md

## Main Objective

- Not now: new features or strategy changes.
- Now: verify actual runtime issues first, using evidence from logs.

## Priority Flow

1. Invalid tick root cause logging (Highest)
- Add detailed reject logging near `is_data_valid(...)`.
- Capture reason, source, ltp, bid/ask, spread, tick age.
- Target: identify real cause behind high invalid tick rate.

2. Validator reject distribution audit (High)
- Track reject counts by rule: stale, spread, bid_ask, price, volume, other.
- Publish daily reject % summary.
- Target: know which rule causes most rejections.

3. Exit engine behavior audit (High)
- Review quick RSI-driven exits.
- Evaluate: delay, minimum hold time, and confirmation logic.
- Target: confirm whether exits are too aggressive or data quality is the trigger.

4. One-day forward paper test (Medium)
- Measure: invalid tick %, REST fallback frequency, WS reconnect frequency, trade quality.
- Target: verify whether audits/logging lead to runtime improvement.

## Config Validator Status

- Do not modify validator rules yet.
- First collect runtime evidence.
- Later cross-checks planned for:
  - TICK_TIMEOUT_SEC vs polling interval
  - SPREAD_LIMIT_PCT
  - MIN_OPTION_PRICE < MAX_OPTION_PRICE
  - MIN_CONFIDENCE
  - LATENCY_LIMIT_MS vs KILL_SWITCH_LATENCY

## Current Checklist Status

- Done:
  - Broker layer audit
  - WebSocket layer hardening
  - Invalid tick root cause logging
  - Validator reject stats
  - Exit engine audit
  - One-day paper forward test checklist prepared
- Pending:
  - Config validator improvements (later)

## Final Recommendation

- Keep focus on runtime evidence first.
- Do not introduce feature/strategy changes until root cause is fully confirmed.
- Decide fixes only after measured validation outcomes.
