# Root Cause Analysis Plan

## Objective

Do not introduce new features or strategy changes right now. Focus only on verifying the real runtime issues seen in the 2 July logs.

## Priority Order

### 1. Invalid Tick Root Cause Analysis
Priority: Highest

The first goal is to identify why the bot is rejecting so many ticks. The current issue is the invalid tick rate, which appears to be the dominant problem.

#### Action
- Add detailed reject reason logging where the bot calls:
  - `is_data_valid(...)`
- Log the reason, source, LTP, bid, ask, spread, and tick age.

#### Expected output
A log entry like:

```python
if not is_valid:
    logger.warning(
        f"INVALID_TICK | "
        f"reason={validation_msg} | "
        f"source={tick.get('data_source')} | "
        f"ltp={tick.get('ltp')} | "
        f"bid={tick.get('bid')} | "
        f"ask={tick.get('ask')} | "
        f"spread={tick.get('spread')} | "
        f"age={tick.get('original_timestamp')}"
    )
```

#### Goal
Find the actual cause behind the 81% invalid tick rate.

---

### 2. Validator Audit
Priority: High

The validator should track reject counts separately so the cause distribution is visible.

#### Proposed reject stats

```python
reject_stats = {
    "stale": 0,
    "spread": 0,
    "bid_ask": 0,
    "price": 0,
    "volume": 0,
}
```

#### Daily summary format

```text
Rejected:
Stale: 73%
Spread: 12%
Bid/Ask: 8%
Volume: 5%
Other: 2%
```

#### Goal
Know exactly which validation rule is responsible for the majority of rejections.

---

### 3. Exit Engine Audit
Priority: High

The 2 July logs showed that many trades exited very quickly due to RSI exits.

#### Questions to answer
- Is RSI exit delay needed?
- Is a minimum hold time needed?
- Should RSI exit require price confirmation?

#### Goal
Determine whether the exit engine is too aggressive or whether the market data is causing premature exits.

---

### 4. Forward Test for One Day
Priority: Medium

After the logging and validator audit are in place, run one paper trading day.

#### Measure
- Invalid tick percentage
- REST fallback frequency
- WebSocket reconnect frequency
- Trade quality

#### Goal
Confirm whether the changes truly improve runtime behavior.

---

## Config Validator Plan

Do not change config validation yet.

First, fix runtime issues and gather evidence.

After that, add cross-checks for:
- `TICK_TIMEOUT_SEC` vs polling interval
- `SPREAD_LIMIT_PCT`
- `MIN_OPTION_PRICE < MAX_OPTION_PRICE`
- `MIN_CONFIDENCE`
- `LATENCY_LIMIT_MS` vs `KILL_SWITCH_LATENCY`

---

## Current Priority List

- [x] Broker layer audit
- [x] WebSocket layer hardening
- [x] Invalid tick root cause logging
- [x] Validator reject stats
- [x] Exit engine audit
- [x] One-day paper forward test checklist prepared
- [ ] Config validator improvements later

---

## Recommendation

Do not add new features or change strategy at this point.

The immediate focus should be:
1. Add detailed invalid tick logging
2. Measure validator reject reasons
3. Confirm the actual root cause from runtime data
4. Only then decide whether a fix is needed
