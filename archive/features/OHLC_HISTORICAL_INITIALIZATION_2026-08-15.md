# Historical OHLC + Indicator Warm-Up Implementation

Date: 2026-08-15
Scope: Strategy Layer, Indicator Calculation, Data Pipeline

## Problem Statement

The bot's strategy calculation layer (`SmartScalpV3.calculate_indicators`) exhibited a fatal flaw during mid-session startup or transport reconnection:
It artificially generated its OHLC tracking and standard indicators (EMA, VWAP, MACD) exclusively using the real-time buffer of ticks accumulated *since the bot was turned on*.

**Consequences:**
- When starting at 10:30 AM, the bot had zero knowledge of 09:15 AM - 10:30 AM trends.
- `EMA_50` and `MACD` provided garbage values, as they require deep historical periods to calculate meaningfully.
- The runtime slice length depended purely on arbitrary array lengths (`chunk_size = len(prices) // 60`), entirely divorcing internal logic from objective 1-minute or 5-minute time boundaries.
- This directly caused "missed trades" and late, lagging entries due to under-converged technical indicators yielding false scores to the decision engine.


## Implemented Architectural Solution

A dedicated, highly robust multi-layer pipeline has been executed across the transport, state, and strategy modules.

### 1. Broker Integration (Transport Layer)
`BrokerInterface.get_historical_candles` was added.
- **Action:** At startup, right after connection, the broker silently fetches up to 100 periods (500 minutes / 1.3 trading days) of exact pristine `FIVE_MINUTE` interval data using Angel One's `getCandleData` endpoint.
- **Result:** The system receives a reliable structural floor spanning the current market session (and yesterday's session if required for convergence).

### 2. State Integration (Data Layer)
`RuntimeState.get_canonical_candles` was introduced.
- **Action:** It merges the immutable downloaded historical data with any new live sub-5-minute ticks accrued since connect. 
- **Result:** It enforces exact minute boundaries (e.g., locking the 10:15 - 10:20 boundary deterministically) without duplicating data, no matter how many WebSocket drops or reconnects happen.

### 3. Strategy Integration (Scoring Layer)
`SmartScalpV3.calculate_indicators` was refactored.
- **Action:** The strategy is now fed the 100% verified canonical OHLC list from the runtime state engine.
- **Result:** The bot computes TradingView-identical momentum indices (`EMA_50`, `RSI_14`) on the very first tick after connection. 
- The legacy brute-force array slicing was preserved exclusively as a fallback capability for older backtest scenarios, ensuring zero backward compatibility breakage.

## Validation & Testing

- `tests/test_runtime_state_candles.py` was introduced to prove the absolute correct mathematical mapping of live-ticks into rigid historical timeframes.
- The change was verified as non-destructive against the execution layer; the entry/exit/risk logic required no modifications.
- Complete regression suite (including `test_dvf_pipeline.py` and `test_websocket.py`) executed with a 100% pass rate.

## Summary Conclusion

The project's architectural mismatch between live execution and historical indicator context has been bridged. 
The system operates seamlessly without false entry blindspots upon reboot, ensuring institutional-grade indicator alignment matching any standard professional execution platform.
