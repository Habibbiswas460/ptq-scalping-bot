# P0 TASK — HISTORICAL OHLC + INDICATOR INITIALIZATION AUDIT

## 1. Current Data Flow & Audit Findings
### 1.1 Data Origin and Buffering
- Live ticks originate from `BrokerInterface._on_ws_tick` in `core/trading/broker.py`.
- Ticks are appended during runtime to `RuntimeState.recent_ticks` via `add_tick()` in `core/runtime/state.py`.
- `RuntimeState` caps the raw tick buffer to 240 items.

### 1.2 The Strategy's Indicator Pipeline
- `SmartScalpV3.calculate_indicators(ticks)` receives the raw live tick array.
- Currently, `calculate_indicators` converts this bounded array into "candles" using array division:
  ```python
  chunk_size = max(1, len(prices) // 60)
  ```
- **Flaws:**
  - This synthesizes OHLC values per chunk *disregarding actual timestamps*.
  - At best, 60 raw ticks are treated as 60 "candles". At 240 ticks, it groups 4 ticks into a "candle".
  - This results in arbitrary indicator periods entirely detached from real 1-minute or 5-minute time boundaries.
  - When the bot starts or reconnects, the tick history is empty, leading to cold-start indicator failures.

### 1.3 Historical Data Capabilities
- `brokers/angel_one/client.py` has `get_candle_data(symbol_token, exchange, interval, fromdate, todate)` wrapping Angel One's `getCandleData`.
- Valid intervals include `"ONE_MINUTE"` and `"FIVE_MINUTE"`.
- `BrokerInterface` (`core/trading/broker.py`) does *not* currently expose an OHLC fetching wrapper to the runtime engines.

## 2. Root Cause & Architectural Gap
- **Root Cause:** The strategy computes indicators relying exclusively on the bot's runtime tick array length, inherently lacking actual timeframe context and pre-market history.
- **Architectural Gap:** There is no bridge between the broker's historical API and the runtime engine's indicator computation to establish canonical market context (like the EMA 50) upon startup or reconnection.

## 3. Architecture Proposal
To fulfill the requirement of `Historical 5-min OHLC + Live 5-min ticks -> Canonical 5-min series -> Indicators`:

1. **Broker Level:** Add `get_historical_candles(symbol, token, interval, minutes_back)` to `BrokerInterface`.
2. **State Level:** Implement deterministic 5-minute OHLC merging in `RuntimeState`:
   - Store historical completed candles immutably (keyed by `YYYY-MM-DD HH:MM`).
   - Allow live ticks to update the *current* incomplete 5-minute bucket.
   - When a tick's timestamp moves to the next 5-minute interval, close and freeze the current bucket.
3. **Strategy Level:** `SmartScalpV3.calculate_indicators` will accept canonical `List[Dict]` OHLC candles instead of forcing raw tick chunking.

## 4. Minimum Warm-up Requirement
- **Requirement:** The strategy uses EMA 50, EMA 21, and MACD (26). 
- **Calculation:** To properly seed an EMA 50 without severe initial skew, at least 2 periods (100 periods total) of data are strongly recommended, although 60-70 periods mathematically provide passable convergence.
- **Decision:** Fetch **100 historical 5-minute candles** (500 minutes, max 1.3 trading days of history). This guarantees both EMA 50 and RSI 14 have deeply stabilized values before the first live tick is processed.

## 5. Files to Change (Scope)
- **`core/trading/broker.py`**: Add `get_historical_candles` wrapping the underlying client call.
- **`core/runtime/state.py`**: Add deterministic 5-min OHLC aggregation bucket and tracking.
- **`core/engines/state_machine.py` or `core/main.py`**: Integrate the startup API fetch.
- **`strategies/smart_scalp_v3.py`**: Refactor `calculate_indicators` to iterate over canonical OHLC dicts directly.
- **`tests/test_...`**: Add unit tests for candle merging edge-cases.

## 6. Strict Scope Limitations (Do NOT Change)
- Do **not** alter the weighting algorithms in `WeightedScoreEngine`.
- Do **not** alter the MQ (Market Quality) grade thresholds.
- Do **not** change position sizing, SL/TP variables, or entry gating rules.

## 7. Risks & Testing Considerations
- **Duplicate Ticks:** If REST fallback or duplicate WS ticks occur, the 5-min candle bucket `high/low/volume` must simply absorb them idempotently without creating redundant candles.
- **Timezone/Session Bound:** The SmartAPI API usually returns IST timestamps. Timestamp extraction must strictly match 5-minute boundaries (`minute % 5 == 0`).
- **Reconnects:** The historical dataset should NOT be forcefully re-fetched on brief disconnects to avoid rate limiting. Brief gaps should just bridge or be tolerated unless the downtime exceeds 5 minutes.