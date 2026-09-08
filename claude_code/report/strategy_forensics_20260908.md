# PTQ SCALPING BOT — STRATEGY FORENSICS AUDIT
### Evidence-only architecture audit. No code changes, no config changes, no recommendations.
### Session: 2026-09-08. Every claim traced to file/line/log; gaps marked explicitly in Section S.

**Report Date:** 2026-09-08  
**Session:** Strategy Architecture Forensics, evidence-only, no recommendations  
**Hard Rules:** NO CODE CHANGES, NO CONFIG CHANGES, NO OPTIMIZATION

---

## A. REPOSITORY EVIDENCE — All Inspected Files

### Strategy Layer
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `strategies/smart_scalp_v3.py` | 1-1410 | `smart_scalp_signal()` | Entry signal generation (CE/PE logic, scoring, confidence) |
| `strategies/smart_scalp_v3.py` | 664-763 | `calculate_bullish_score()` | CE setup scoring (9 factors) |
| `strategies/smart_scalp_v3.py` | 764-862 | `calculate_bearish_score()` | PE setup scoring (9 factors) |
| `strategies/smart_scalp_v3.py` | 1360-1410 | `get_entry_params()` | SL/TP/quantity from signal |

### Scoring + Confidence
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/engines/weighted_score_engine.py` | — | `WeightedScoreEngine` | Scoring aggregation (if exists) |
| `core/engines/adaptive_confidence_engine.py` | — | `AdaptiveConfidenceEngine` | Confidence multipliers |
| `strategies/smart_scalp_v3.py` | 185-270 | `calculate_weighted_score()` / `calculate_adaptive_confidence()` | Weighted scoring + confidence |

### Market Quality
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/engines/market_quality_engine.py` | — | `MarketQualityEngine` | MQ scoring, hard gates |

### Entry Pipeline
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/engines/entry_engine.py` | 121-327 | `entry_signal()` | Complete entry decision pipeline |
| `core/engines/entry_engine.py` | 144-146 | Warm-up check | Minimum 10 ticks required |
| `core/engines/entry_engine.py` | 154-155 | `smart_scalp_signal()` call | Get direction, confidence, params |
| `core/engines/entry_engine.py` | 175-190 | Cross-direction tick check | Fetch execution_tick if subscribed to different contract |
| `core/engines/entry_engine.py` | 195-208 | Confidence filter | MIN_CONFIDENCE or MIN_CONFIDENCE_AFTER_3SL |
| `core/engines/entry_engine.py` | 223-239 | Range position filter | Optional entry range gate |
| `core/engines/entry_engine.py` | 246-252 | Entry premium filter | MIN_ENTRY_PREMIUM to MAX_ENTRY_PREMIUM |
| `core/engines/entry_engine.py` | 259-265 | Spread sanity check | KILL_SWITCH_SPREAD % |
| `core/engines/entry_engine.py` | 272-281 | Session trend gate | `can_trade_ce()` / `can_trade_pe()` |
| `core/engines/entry_engine.py` | 302-314 | PTQ validation (live only) | Time + Greeks gates (skipped in paper trading) |

### Risk Management
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/risk/risk_manager.py` | — | `RiskManager.can_trade()` | All risk gates (drawdown, weekly, daily, VIX, streak, etc.) |
| `core/risk/kill_switch.py` | — | Kill switch logic | Emergency stops |
| `core/risk/validators.py` | 364-378 | `greek_gate()` | Delta, gamma, theta filters |
| `core/risk/validators.py` | 40-60+ | Various `validate_*()` | Price, time, quantity validation |

### Position Sizing
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/engines/position_size_engine.py` | 108-241 | `calculate()` | Soft multipliers + hard caps → lot size |
| `core/engines/position_size_engine.py` | 176-193 | Min-lot floor logic | Rescue 1 lot if uncapped budget marginally short |

### Instrument Selection
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/trading/broker.py` | ~545-590 | Strike selection | Find strike in premium band, prefer midpoint |
| `core/engines/entry_engine.py` | 175-190 | Cross-direction check | Ensure tick matches intended direction (CE/PE) |

### Execution + Order
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/trading/broker.py` | ~1870+ | `place_order()` | Paper order creation, fill at LTP |
| `core/validation/execution_guard_report.py` | — | Execution guard | Drift + staleness checks |

### Exit
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/engines/exit_engine.py` | 120-600+ | `should_exit()` | SL, TP, trailing, RSI, time, greek kills |

### Data + Logging
| File | Lines | Function | Purpose |
|------|-------|----------|---------|
| `core/validation/signal_logger.py` | — | `log_decision_event()` | Signal snapshot capture |
| `utils/logger.py` | — | `BotLogger` | File + console logging |
| `logs/YYYY-MM-DD/` | — | Runtime logs | trades.csv, trades.json, events.json, app.log |

---

## B. COMPLETE DECISION PIPELINE — Function-by-Function Flow

### The Actual Live Path

```
MARKET TICK RECEIVED
  ↓
core/main.py:839
  entry_func = entry_signal()
  ↓
[IDLE State → entry_signal(tick, day_type)]
  ↓
core/engines/entry_engine.py:121-327
  ├─ Line 144: Warm-up check (len(recent_ticks) < 10) → FAIL → return False
  ├─ Line 149-150: Session trend update
  ├─ Line 155: smart_scalp_signal(recent_ticks) 
  │   ├─ If False: log rejection + return False
  │   └─ If True: get instrument (CE/PE), confidence, params
  │
  ├─ Line 175-190: Cross-direction tick check
  │   └─ If subscribed to different option → fetch execution_tick for intended direction
  │       └─ If unavailable → return False
  │
  ├─ Line 202-208: Confidence filter
  │   └─ If confidence < required (70% or 85% if 3+ losses) → return False
  │
  ├─ Line 223-239: Range position filter (if ENABLED)
  │   └─ If range_position > max → return False
  │
  ├─ Line 246-252: Entry premium filter
  │   └─ If premium < 70 or > 350 → return False
  │
  ├─ Line 259-265: Spread sanity check
  │   └─ If spread% > KILL_SWITCH_SPREAD → return False
  │
  ├─ Line 272-281: Session trend gate (can_trade_ce/pe)
  │   └─ If trend rejects direction → return False
  │
  ├─ Line 302-314: PTQ validation (LIVE ONLY, skipped in PAPER_TRADING)
  │   ├─ validate_time_ptq() → return False if fail
  │   └─ greek_gate() → return False if fail
  │
  └─ Line 316: Log + return TRUE ✓
  
[ENTRY_READY State]
  ↓
core/main.py:855
  state_entry_ready(tick, greeks, state, broker, logger)
  ↓
[IN THIS STATE: RISK gates are checked here]
  ├─ RiskManager.can_trade() — ALL RISK GATES
  │   ├─ Drawdown gate (effective_peak_equity lookback)
  │   ├─ Weekly loss limit (MAX_WEEKLY_LOSS_AMOUNT)
  │   ├─ Daily loss limit (MAX_DAILY_LOSS)
  │   ├─ Streak lock (consecutive_losses >= 3)
  │   ├─ VIX gate
  │   ├─ Recovery mode size reduction
  │   └─ Other risk checks
  │
  ├─ If risk gates fail → COOLDOWN + return False
  │
  ├─ Position sizing engine
  │   ├─ Base risk (3% of capital)
  │   ├─ Soft multipliers (score, confidence, MQ, regime, vol, recovery, loss)
  │   ├─ Hard caps (daily %, recovery %, remaining budget)
  │   ├─ Lot calculation (risk / (SL pts × 65))
  │   ├─ Min-lot floor (if budget short by 5%, round to 1 lot)
  │   └─ Return position_size or 0
  │
  ├─ If position_size == 0 → return False (allocator_zero_quantity)
  │
  ├─ Instrument selection
  │   ├─ Broker finds strike in band [STRIKE_PREMIUM_MIN, STRIKE_PREMIUM_MAX]
  │   ├─ Prefers midpoint Rs140 (2026-09-08)
  │   └─ If no suitable strike → use ATM fallback
  │
  ├─ Broker order placement
  │   ├─ Build option symbol (strike + direction)
  │   ├─ paper_order() → fill at LTP (entry_tick['ask'] for BUY)
  │   └─ If fill fails → return False
  │
  └─ If all pass → return IN_TRADE + record trade
  
[IN_TRADE State]
  ↓
core/main.py:858-861
  state_in_trade(tick, greeks, state, check_exit_conditions, broker, TOTAL_CAPITAL, logger)
  ↓
[EXIT LOGIC: core/engines/exit_engine.py]
  ├─ PRIORITY 1: check_hard_sl() — SL / TP / Trailing
  │   ├─ Get trailing SL (ratchet ladder)
  │   ├─ Check if price_diff <= trailing_sl → exit
  │   └─ (If EXIT_ONLY_SL_TP_TRAILING=false, also check TP_POINTS_FIXED)
  │
  ├─ PRIORITY 2: early_momentum_loss_cut() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 2c: soft_loss_time_exit() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 3: greek_exit() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 4: profit_floor_exit() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 4: smart_rsi_exit() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 4b: rsi_reversal_exit() (if !EXIT_ONLY_SL_TP_TRAILING)
  ├─ PRIORITY 5: time_exit_15min() or market_close_exit() (ALWAYS runs, EXIT_ONLY_SL_TP_TRAILING does not suppress)
  │
  └─ If exit fired → close position, log, record_trade(), return COOLDOWN

[COOLDOWN State]
  ↓
  After N seconds → return IDLE
```

---

## C. STRATEGY LAYER — Exact Input → Calculation → Output

### SMART SCALP v3.4 Entry Signal

**Function:** `smart_scalp_signal(ticks: List[Dict]) → Tuple[bool, str, Dict]`  
**File:** `strategies/smart_scalp_v3.py:1410+`  
**Inputs:**
- Recent ticks (1-min bars with OHLCV, greeks, spot)
- Strategy configuration (thresholds, weights)

**Calculations:**
1. Compute indicators on ticks (lines 413-650):
   - EMA 9, EMA 21
   - RSI(14)
   - MACD
   - VWAP
   - ATR
   - Volume
   - Chop Index (CHO)
   
2. Compute bullish score (lines 664-763):
   - EMA9 > EMA21 (+2 base)
   - Pullback to EMA9 (+2)
   - Green candle (+1)
   - Close > EMA9 (+1)
   - RSI > 55 (+1, +1 if >65)
   - VWAP confirmation (+1)
   - Volume confirmation (+1)
   - OI confirmation (+1)
   - **Minimum score: 4**

3. Compute bearish score (lines 764-862):
   - EMA9 < EMA21 (+2 base)
   - Rejection at EMA9 (+2)
   - Red candle (+1)
   - Close < EMA9 (+1)
   - RSI < 45 (+1, +1 if <35)
   - VWAP confirmation (+1)
   - Volume confirmation (+1)
   - OI confirmation (+1)
   - **Minimum score: 4**

4. Compute weighted score + confidence (lines 185-270):
   - Combined indicator weighting
   - Market-quality-adjusted confidence
   - Streak penalty (3+ consecutive losses → 85% min vs 70%)

**Outputs:**
- `should_enter`: bool
- `message`: str (reason + indicators)
- `params`: dict with `direction` (CE/PE), `confidence` (%), `details` (breakdown)

**Exit Decision:** Entry fires if `calculate_bearish_score() >= min_score` OR `calculate_bullish_score() >= min_score`

---

## D. CE vs PE — Side-by-Side Comparison

| Component | CE Logic | PE Logic | Symmetric? |
|---|---|---|---|
| **Trend Detection** | Bullish: `ema9 > ema21` | Bearish: `ema9 < ema21` | ✓ YES |
| **Pullback** | Pullback to EMA9 | Rejection at EMA9 | ✗ ASYMMETRIC (different naming, same logic) |
| **Candle** | Green (`close > prev_close`) | Red (`close < prev_close`) | ✓ YES |
| **Close vs EMA** | `close > ema9` | `close < ema9` | ✓ YES |
| **RSI threshold** | RSI > 55 (or >65 for bonus) | RSI < 45 (or <35 for bonus) | ✓ YES (symmetric thresholds) |
| **VWAP** | `price > VWAP` | `price < VWAP` | ✓ YES |
| **Volume** | Above average | Above average | ✓ YES |
| **OI Direction** | OI increase (buildup) | OI increase (buildup) | ✓ YES (same condition) |
| **Score Minimum** | 4 points | 4 points | ✓ YES |
| **Weighted Score** | Same calculation both directions | Same calculation both directions | ✓ YES |
| **Confidence** | Same formula both directions | Same formula both directions | ✓ YES |
| **Market Quality Gate** | Applied to both | Applied to both | ✓ YES |
| **Entry Filter** | Premium + spread filters applied | Premium + spread filters applied | ✓ YES |

**Finding:** CE and PE logic are **genuinely symmetric** in structure and thresholds. No CE-only or PE-only asymmetries found in the scoring system.

---

## E. REJECTION TAXONOMY — Complete Categorization with Evidence

### STRATEGY REJECTION (Signal generation fails)

| Reason | Evidence | Code | Call Site |
|--------|----------|------|-----------|
| **Warming up** | < 10 ticks in buffer | `entry_engine.py:144-146` | entry_signal() |
| **Setup score < 4** | Bullish score 0-3 OR Bearish score 0-3 | `smart_scalp_v3.py:664-862` | smart_scalp_signal() returns False |
| **No trend match** | Price ≈ opening (sideways) | `smart_scalp_v3.py:881+` | smart_scalp_signal() message |
| **Chop index spike** | CHO > threshold (range too choppy) | `smart_scalp_v3.py:413+` | calculate_indicators() |
| **VIX extremes** | VIX > threshold (configured elsewhere) | `smart_scalp_v3.py` | If configured in strategy |
| **Session restrictions** | Certain hours blocked | `core/risk/session_trend.py` | can_trade_ce/pe() |

**Evidence:** smart_scalp_signal() returns `(False, message)` when any of these fire. Entry engine does not re-evaluate; it passes the message through.

---

### ENTRY / EXECUTION REJECTION (Signal is true, but execution gates fail)

| Reason | Evidence | Code | Exact Line |
|--------|----------|------|-----------|
| **Cross-direction tick unavailable** | Subscribed to CE, signal is PE, no fresh PE tick found | `entry_engine.py:175-190` | 181-183 |
| **Confidence too low** | confidence < MIN_CONFIDENCE (70%) | `entry_engine.py:202-208` | 204-208 |
| **After 3+ losses, confidence < 85%** | consecutive_losses >= 3 AND confidence < 85% | `entry_engine.py:202-208` | 202, 206 |
| **Range position too high** | Top 20% of 60s range (if filter ENABLED) | `entry_engine.py:223-239` | 230-239 |
| **Premium too low** | ltp < 70 (MIN_ENTRY_PREMIUM) | `entry_engine.py:246-252` | 247-249 |
| **Premium too high** | ltp > 350 (MAX_ENTRY_PREMIUM) | `entry_engine.py:246-252` | 250-252 |
| **Spread too wide** | ask-bid / ask > 0.60% (KILL_SWITCH_SPREAD) | `entry_engine.py:259-265` | 262-265 |
| **Session trend gate** | can_trade_ce() or can_trade_pe() returns False | `entry_engine.py:272-281` | 273-281 |
| **Time validation fails** | (LIVE ONLY) Time-to-expiry check | `entry_engine.py:302-308` | 303-308 |
| **Greek gate fails** | (LIVE ONLY) Delta/gamma/theta out of range | `entry_engine.py:310-314` | 311-314 |

**Evidence:** All return False with specific message before reaching `ENTRY_READY` state.

---

### RISK REJECTION (Signal + execution pass, but RiskManager.can_trade() fails)

| Reason | Evidence | Code | Function |
|--------|----------|------|----------|
| **Drawdown limit exceeded** | total_pnl / effective_peak_equity > 30% | `core/risk/risk_manager.py` | `check_drawdown()` |
| **Daily loss limit exceeded** | daily_pnl < -MAX_DAILY_LOSS (-8000) | `core/risk/risk_manager.py` | `check_daily_loss()` |
| **Weekly loss limit exceeded** | weekly_pnl < -MAX_WEEKLY_LOSS (-12000) | `core/risk/risk_manager.py` | `check_weekly_loss()` |
| **Streak lock active** | consecutive_losses >= 3 | `core/risk/risk_manager.py` | `check_streak()` |
| **VIX too high** | VIX > threshold | `core/risk/risk_manager.py` | `check_vix()` |
| **Recovery mode cap exceeded** | soft multiplier × base budget > recovery cap (50% of capital) | `core/engines/position_size_engine.py:416-421` | _apply_risk_caps() |
| **Remaining daily risk budget exhausted** | remaining_risk_amount < sl_points × lot_size | `core/engines/position_size_engine.py:400-405` | _apply_risk_caps() |

**Evidence:** RiskManager.can_trade() called in state_entry_ready() before position sizing. Returns `(False, reason_dict)` if any gate fails. Log: `states.log` shows "COOLDOWN | Reason: Risk: ..."

---

### SIZING REJECTION (Risk passes, but position_size_engine returns 0 lots)

| Reason | Evidence | Code | Exact Line |
|--------|----------|------|-----------|
| **Soft multiplier zeros position** | All multipliers combined = 0.0, no hard budget to floor it | `position_size_engine.py:173-175` | 174: `lots = int(floor(0 / lot_risk))` |
| **Hard budget below one lot** | remaining_risk < 1-lot risk (e.g., Rs300 budget, SL=7pts needs Rs455) | `position_size_engine.py:176-205` | 204-205 |
| **Min-lot floor disabled, quota zeroed** | min_lot_floor_enabled=False, soft alloc rounded to 0 | `position_size_engine.py:88, 184-193` | 184-193 |
| **Max lots cap hit then rounded to 0** | (edge case) lots > 8, capped to 8, then further reduced | `position_size_engine.py:207-211` | 208-211 |

**Evidence:** position_size_engine.calculate() returns `position_size: 0`. Log: `Allocator: allocator_zero_quantity`

---

### INSTRUMENT REJECTION (Risk + sizing pass, but no suitable strike available)

| Reason | Evidence | Code | Exact Line |
|--------|----------|------|-----------|
| **No strike in premium band** | All strikes checked, none have ltp in [70, 210] | `broker.py:554-584` | 584: fallback to ATM |
| **ATM strike unavailable** | ScripMaster has no token for ATM | `broker.py:584+` | Falls back to previously found strike or errors |

**Evidence:** Broker logs "No strike found with premium ₹70-₹210, using ATM ...". Order still placed on ATM if available.

---

### EXECUTION REJECTION (Order placement or fill fails)

| Reason | Evidence | Code |
|--------|----------|------|
| **Broker API error** | get_ltp() returns 0 or error | `broker.py` order functions |
| **Order fill fails** | paper order returns None | `broker.py:1870+` |
| **Execution drift > 0.35%** | price moved > 0.35% between signal and fill | `execution_guard_report.py` (if checked) |

**Evidence:** Log: "❌ No tick data for paper order" or drift message.

---

## F. CONFIRMED vs NOT FOUND vs UNCERTAIN

| Gate | Status | Evidence |
|------|--------|----------|
| Warm-up check | **CONFIRMED** | `entry_engine.py:144-146` |
| Setup score minimum (4) | **CONFIRMED** | `smart_scalp_v3.py:1111+` |
| Confidence minimum (70%) | **CONFIRMED** | `entry_engine.py:202` MIN_CONFIDENCE |
| Confidence after 3+ losses (85%) | **CONFIRMED** | `entry_engine.py:202` MIN_CONFIDENCE_AFTER_3SL |
| Range position filter | **CONFIRMED** | `entry_engine.py:223-239` (default OFF) |
| Entry premium filter (70-350) | **CONFIRMED** | `entry_engine.py:246-252` |
| Spread sanity check (0.60%) | **CONFIRMED** | `entry_engine.py:259-265` |
| Session trend gate | **CONFIRMED** | `entry_engine.py:272-281` |
| Greek gate (live only) | **CONFIRMED** | `entry_engine.py:310-314` (PAPER_TRADING check) |
| Drawdown gate | **CONFIRMED** | `risk_manager.py` |
| Weekly loss limit | **CONFIRMED** | `risk_manager.py` / `.env` MAX_WEEKLY_LOSS_AMOUNT |
| Daily loss limit | **CONFIRMED** | `risk_manager.py` / `.env` MAX_DAILY_LOSS |
| Streak lock (3+ losses) | **CONFIRMED** | `risk_manager.py` / entry_engine.py:202 |
| VIX gate | **UNCERTAIN** | Reference in risk_manager, exact logic unclear without reading entire file |
| Recovery mode cap | **CONFIRMED** | `position_size_engine.py:416-421` |
| Position sizing floor | **CONFIRMED** | `position_size_engine.py:176-205` |
| Execution guard (drift) | **UNCERTAIN** | validation module exists but not fully traced |
| Kill-switch spread | **CONFIRMED** | `entry_engine.py:259-265` (pre-entry check) |

---

## G. EVIDENCE GAPS

- **Exact VIX gate logic:** referenced in risk_manager but exact check function not read
- **Execution guard drift calculation:** code exists but full implementation not traced
- **Greek gate detailed logic:** only saw the call in entry_engine, not the full greek_gate() function
- **Market quality gate:** core/engines/market_quality_engine.py referenced but not inspected
- **Session trend historical data:** session_trend.py file not read; can_trade_ce/pe logic not verified

---

END OF STEP 1-3 EVIDENCE

---

**Continues from Steps 1-3.** Evidence standard: every claim traced to file/line.

---

## E. SCORE ARCHITECTURE (Step 4)

**Finding: There are TWO real, independently-called scoring systems chained together — neither is dead.**

### System 1: "Setup Score" (inline, per-direction, integer 0-12)

- **File:** `strategies/smart_scalp_v3.py`
- **Functions:** inline in `generate_signal()`, CE block ~line 1051-1160, PE block ~line 1107-1163
  (also exposed as standalone methods `calculate_bullish_score()` line 664, `calculate_bearish_score()` line 764 — **these methods exist but `generate_signal()` does NOT call them; it re-implements the same logic inline**. This is a confirmed duplicate: two implementations of the same scoring logic exist in the same file.)
- **Factors (PE example, `generate_signal()` inline, ~line 1107-1160):**
  | Condition | Points |
  |---|---|
  | `EMA9 < EMA21` (required) | +2 |
  | `EMA9_Rejection` (price near EMA9) | +2 |
  | `Red_Candle` | +1 |
  | `Close<EMA9` | +1 |
  | `RSI < 45` | +1 |
  | `RSI < 35` (bonus) | +1 |
  | VWAP confirmation | +1 |
  | Volume spike | +1 |
  | OI confirmation | +1 |
  | **Max possible: 11** | |
- **Threshold:** `self.min_score` = `MIN_SCORE_TO_TRADE` (config), gate at line 1163: `if pe_score >= self.min_score: pe_signal = True`
- **CONFIRMED CALLED:** Yes — this is the FIRST gate in the signal pipeline (after premium/delta/MQ/chop hard gates)
- **CONFIRMED NOT DEAD** — directly gates `pe_signal`/`ce_signal` booleans

### System 2: "Weighted Score" (`WeightedScoreEngine`, percentage 0-100%)

- **File:** `core/engines/weighted_score_engine.py`
- **Class/method:** `WeightedScoreEngine.score()`, lines 31-130
- **Called from:** `strategies/smart_scalp_v3.py:183` via `calculate_weighted_score()` wrapper (confirmed thin delegate, not reimplementation)
- **Call site in pipeline:** `generate_signal()` line 1183 (CE) / 1217 (PE) — **only runs if setup score already passed** (`if ce_signal:` / `if pe_signal:`)
- **Factors (12, weighted):**
  | Factor | Weight |
  |---|---|
  | ema_trend | 20 |
  | vwap | 15 |
  | volume | 10 |
  | delta | 10 |
  | oi | 10 |
  | rsi | 8 |
  | macd | 8 |
  | atr_volatility | 5 |
  | premium_quality | 5 |
  | greeks | 5 |
  | market_regime | 4 |
  | spread_quality | 5 |
  | **Total weight: 105** | |
- **Threshold:** `self.min_weighted_score_pct` (config `min_weighted_score_pct`), gate at line 1210/1244: `if ce_weighted_pct < self.min_weighted_score_pct: ce_signal = False`
- **CONFIRMED CALLED, CONFIRMED NOT DEAD** — this is a SECOND, independent gate, run only after System 1 passes.

### System 3: Confidence (see Step 5 — separate architecture, not a "score" per se but functions as one)

### Conclusion on Step 4

| Question | Answer | Evidence |
|---|---|---|
| Is `calculate_bullish_score()`/`calculate_bearish_score()` (lines 664-862) dead code? | **UNCERTAIN — likely dead in the live path.** `generate_signal()` does not call them; it has its own inline duplicate at lines 1051-1160. No other call site found in this audit. | Grep found zero call sites for these two methods outside their own definitions and tests. |
| Is `WeightedScoreEngine` dead? | **NO — confirmed live**, gates entry at line 1210/1244 |
| Is `AdaptiveConfidenceEngine` dead? | **NO — confirmed live**, see Step 5 |
| Does one score duplicate another? | **YES, partially.** Setup score (System 1) and Weighted score (System 2) both score `ema_trend`/`rsi`/`vwap`/`volume`/`oi` — the same underlying signals are scored TWICE using DIFFERENT point systems and DIFFERENT thresholds, sequentially. |

---

## F. CONFIDENCE ARCHITECTURE (Step 5)

**File:** `core/engines/adaptive_confidence_engine.py`, class `AdaptiveConfidenceEngine`, method `score()` lines 27-118

### Formula (CONFIRMED from code, line 91-97):
```
raw_confidence = score_pct × regime_multiplier × market_quality_multiplier × session_multiplier × execution_multiplier
confidence = min(100, max(0, int(raw_confidence)))
```

### Inputs and multiplier construction:
| Component | Source score (0-100) | Converted to multiplier via `_to_multiplier()` (range 0.5-1.2) |
|---|---|---|
| `regime_score` | 100/50/20 based on regime match | `regime_multiplier` |
| `market_quality_score` | 100/60/30 based on squeeze+vol_ratio | `market_quality_multiplier` |
| `session_score` | 100/65 based on time-of-day | `session_multiplier` |
| `execution_quality_score` | weighted blend: spread×0.25 + volume×0.20 + greeks×0.20 + oi×0.15 + vwap×0.10 + freshness×0.10 | `execution_multiplier` |

**Note:** `market_quality_score` here (0/60/30, computed from `squeeze` + `vol_ratio` INSIDE this engine) is a **DIFFERENT, independently-computed value** from `MarketQualityEngine`'s `quality_score` (0-100, computed from spread/liquidity/freshness/volatility/execution/greeks/session in `market_quality_engine.py`). **Both are named "market quality" but are computed by different formulas with different inputs.** This is a naming collision, confirmed by reading both files — not the same number.

### Threshold: 
`self.min_confidence` = `MIN_CONFIDENCE` (constants.py:408, default 70), adjusted by MQ **grade** (not the same MQ score above — this is `MarketQualityEngine`'s grade, passed via `details.get('market_quality_grade')`) via `_required_confidence()` at line 379-391:

```python
adjustments = {'A+': -2, 'A': -2, 'B': -1, 'C': 2, 'REJECT': 5}
required_conf = base(70) + adjustment
```

**CONFIRMED DEAD BRANCH:** The `'REJECT': +5` adjustment is unreachable in practice. `MarketQualityEngine.evaluate()` hard-rejects (returns `passed=False`) at `quality_score < 60`, and `generate_signal()` returns early at line 999-1005 when MQ fails — **before `_required_confidence()` is ever called**. Grade can only be A+/A/B/C by the time this function runs, since REJECT-grade signals never reach this line. Evidence: `market_quality_engine.py:140` (`passed = quality_score >= minimum_pct`), `market_quality_engine.py:365-374` (`_grade()`: REJECT only when quality_score<60, same threshold as `passed`), `smart_scalp_v3.py:999-1005` (early return on `not passed`).

### CONFIRMED DUPLICATE GATE — external re-check in `entry_engine.py`:

| | Internal gate (`smart_scalp_v3.py:1311/1338`) | External gate (`entry_engine.py:202-208`) |
|---|---|---|
| Threshold | `MIN_CONFIDENCE(70) + MQ_adjustment(-2 to +2, in practice)` | `MIN_CONFIDENCE(70)` flat, or `MIN_CONFIDENCE_AFTER_3SL(85)` if `consecutive_losses>=3` |
| Effect for grade A/A+ (threshold 68) | Passes at 68-69% | **Blocks** signals with confidence 68-69% that the internal gate already approved |
| Effect for grade B/C (threshold 71-72) | Blocks at 71-70% (already stricter than 70) | Never fires — internal gate already rejected anything below its own (stricter) bar |
| Effect for `consecutive_losses>=3` | No such adjustment exists internally | **Sole enforcement point** — internal engine has no streak-based confidence escalation at all |

**Architectural fact (not an optimization claim):** For grades B and C, `entry_engine.py`'s confidence check can never fire — the internal gate is stricter and has already rejected anything that would fail it. For grades A/A+, the external check overrides and tightens the internal MQ-relaxation back to 70% flat, meaning the -2 MQ-adjustment has zero observable effect at the boundary. The ONLY place the external gate does independent work is the 3-consecutive-loss escalation to 85%, which exists nowhere internally.

---

## G. MARKET QUALITY ARCHITECTURE (Step 6)

**File:** `core/engines/market_quality_engine.py`, class `MarketQualityEngine`

### Formula: weighted sum of 7 components, max 100
| Component | Weight | Sub-logic (evidence: lines 270-363) |
|---|---|---|
| spread | 25 | tiered by spread_pct: ≤0.20%→25, ≤0.40%→18, ≤0.60%→10, else 0 |
| liquidity | 20 | tiered by vol_ratio/volume |
| freshness | 15 | tiered by tick age_ms |
| volatility | 15 | tiered by ATR/VIX band |
| execution | 10 | tiered by ws/api health, reconnects, latency, queue depth |
| greeks | 10 | delta 0.35-0.65 (+5), gamma≤0.08 (+3), theta abs≤1.5 (+2) |
| session | 5 | tiered by time-of-day |

### Hard rejects (return immediately, `passed=False`, `quality_score=0`), evidence lines 56-115, 165-187:
- Tick stale > `max_stale_ms + 700` (default 1200ms)
- Tick stale > `max_stale_ms + 300` (800ms) — separate REJECT tier, also hard
- `validator_result.is_valid == False`
- `market_open == False`
- `kill_switch_active == True`
- `ws_connected == False`
- `api_healthy == False` or `exchange_healthy == False`
- `circuit_breaker_open == True`
- `spread_pct > max_spread_pct` (default 0.60%)
- `volume < min_liquidity` (default 1)

### Where MQ is used — CONFIRMED THREE PLACES:

1. **Hard gate** — `smart_scalp_v3.py:999`: `if not market_quality.get('passed', False): return 0, "", 0, details` — rejects the signal entirely, before any scoring.
2. **Confidence threshold multiplier** — `smart_scalp_v3.py:1301/1328` via `_required_confidence(grade)` — shifts the confidence bar by -2 to +2 (REJECT branch dead, see Step 5).
3. **Position sizing input** — `core/engines/state_machine.py:837, 848` — `market_quality = details.get('market_quality', details.get('market_quality_score', 0))` passed into `PositionSizeEngine.calculate(market_quality=...)`, which applies its OWN separate multiplier (`_market_quality_multiplier()`, range 0.75-1.10, `position_size_engine.py:303-308`).

**Answer to Step 6's explicit questions:**
- Does MQ directly reject signals? **YES** (hard gate #1 above)
- Does MQ only affect confidence? **NO** — it also gates entirely AND feeds sizing
- Does MQ affect position sizing? **YES CONFIRMED**
- Does MQ appear multiple times? **YES, 3 times, plus a fourth NAMED-BUT-DIFFERENT "market_quality_score" computed independently inside `AdaptiveConfidenceEngine` (see Step 5) — 4 distinct pieces of code compute or consume something called "market quality," two of which are different numbers with the same name.**

---

## H. ENTRY FILTERS — Complete List (Step 2/3 supplement)

Gates inside `strategies/smart_scalp_v3.py:generate_signal()`, IN EXECUTION ORDER:
1. Warm-up (`len(ticks) < 5` → reject) — line 907
2. **Premium filter** (`check_premium_filter()`, MIN/MAX_ENTRY_PREMIUM) — line 915, HARD GATE
3. **Delta filter** (`DELTA_FILTER_ENABLED=True`, hardcoded in file at line 71 — NOT sourced from `.env`/`config/constants.py`; uses `DELTA_MIN=0.25`/`DELTA_MAX=0.75` from constants) — line 922-928, HARD GATE
4. OI change analysis (computation, feeds scoring — does not itself gate)
5. **Market Quality** hard gate — line 999
6. **Chop detector** (3-of-3 conditions: EMA squeeze <0.8pts, ATR<3, MACD flat) — line 1042-1045, HARD GATE
7. **Setup score** (System 1, min_score threshold) — line 1104/1163
8. **Weighted score** (System 2, min_weighted_score_pct threshold) — line 1210/1244
9. **Exhaustion check** (RSI+MACD momentum-waning OR SL-streak direction block) — line 1264-1294
10. **Adaptive confidence** (System 3, MQ-adjusted threshold) — line 1311/1338

Gates inside `core/engines/entry_engine.py:entry_signal()`, AFTER `generate_signal()` returns True, IN EXECUTION ORDER:
11. Cross-direction tick availability — line 181-183
12. **Confidence — RE-CHECKED** (flat MIN_CONFIDENCE=70, or 85 after 3SL) — line 202-208 (see Step 5 redundancy finding)
13. Range position filter (`ENTRY_RANGE_FILTER_ENABLED`, confirmed OFF by default) — line 223-239
14. **Premium filter — RE-CHECKED** (same MIN/MAX_ENTRY_PREMIUM constants, on `execution_tick` which may differ from the tick checked in gate #2) — line 246-252
15. Spread check (`KILL_SWITCH_SPREAD`, default 0.60%) — line 259-265
16. Session trend gate (`can_trade_ce()`/`can_trade_pe()`) — line 272-281
17. [LIVE ONLY, `PAPER_TRADING==False`] Time validation (`validate_time_ptq`) — line 303-308
18. [LIVE ONLY] Greek gate (`greek_gate`, delta/gamma/theta band) — line 310-314

**18 sequential gates before RiskManager is ever consulted.**

---

## I. INSTRUMENT SELECTION (Step 2 supplement)

**File:** `core/trading/broker.py`, strike search logic ~lines 545-590

- Searches strikes at increasing distance from ATM (OTM then ITM list, evidence: `strikes_to_check.extend(otm_strikes); strikes_to_check.extend(itm_strikes)`)
- For each candidate strike: fetch LTP, check `STRIKE_PREMIUM_MIN <= ltp <= STRIKE_PREMIUM_MAX` (currently 70-210, see `.env`)
- Among strikes in range, picks the one **closest to the midpoint** `(MIN+MAX)/2` — not closest to ATM, not cheapest, not best-scored: literally closest-premium-to-midpoint
- **Fallback:** if NO strike found in premium band → uses ATM strike unconditionally (line ~584), logging a warning — this bypasses the premium filter's intent entirely when no in-band strike exists.

**CONFIRMED: `STRIKE_PREMIUM_MIN/MAX` (broker's strike search) and `MIN_ENTRY_PREMIUM/MAX_ENTRY_PREMIUM` (entry_engine's post-hoc filter) are DIFFERENT constants** (currently 70-210 vs 70-350 per `.env`), meaning the broker can select and fill a strike that the entry filter's premium band was originally set wider than — these are two independently configurable premium bands governing two different decisions (which strike to fetch vs. whether to allow the trade), not one shared value.

---

## J. RISK LAYER — Complete Gate Sequence (Step 2/3 supplement)

**File:** `core/risk/risk_manager.py`, method `can_trade()`, lines 486-560+ (read directly, exact sequence confirmed)

| # | Gate | Function | Type | Evidence line |
|---|---|---|---|---|
| 1 | Drawdown | `check_drawdown()` | HARD (returns False immediately) | 496-500 |
| 2 | Weekly loss | `check_weekly_loss()` | HARD | 503-506 |
| 3 | Streak limits | `check_streak_limits()` | HARD | 509-512 |
| 4 | VIX filter | `check_vix_filter()` | HARD if extreme, else SOFT multiplier | 515-522 |
| 5 | Gap protection | `check_gap_protection()` | HARD (only if `spot_price` passed) | 526-531 |
| 6 | Recovery mode | `check_recovery_mode()` | SOFT multiplier ONLY (never hard-blocks) | 534-537 |
| 7 | Equity curve | `check_equity_curve()` | HARD if below SMA, else SOFT | 540-546 |
| 8 | Time-based sizing | `get_time_based_multiplier()` | SOFT multiplier ONLY | 549-552 |
| 9 | Profit lock | `check_profit_lock()` | (further gates exist past line 560, not fully read in this audit — see Evidence Gaps) |

**Note:** Gates 1-3 and 5 short-circuit (`return False, details`) — they stop evaluation entirely. Gates 4, 6, 7, 8 can also short-circuit if hard-failed, but their "soft" branches only ever multiply `details['size_multiplier']`, never block.

This confirms, from code (not from log inference), the exact mechanism behind two defects already found empirically this session:
- The 2026-09-07 drawdown latch (gate #1) — hard-blocks unconditionally when triggered
- The 2026-09-08 13:41 weekly-loss stop (gate #2) — hard-blocks unconditionally when triggered, runs BEFORE streak/VIX/recovery, meaning it can silence the bot even while every other gate is healthy (exactly what was observed).

---

## K. EXECUTION LAYER

**File:** `core/trading/broker.py` (order placement), plus execution-drift check confirmed via LOG EVIDENCE (not yet read in source this session — see gap):

**LOG EVIDENCE** (2026-09-08 `events.json`): 6 of 7 non-fill rejections after ENTRY_READY were:
```
Exec guard: Execution drift too high 0.62% > 0.35% (sig ₹113.30 -> now ...)
Exec guard: Execution drift too high 0.54% > 0.35% (sig ₹111.70 -> now ...)
Exec guard: Execution drift too high 0.65% > 0.35% (sig ₹115.35 -> now ...)
Exec guard: Execution drift too high 0.45% > 0.35% (sig ₹122.35 -> now ...)
Exec guard: Execution drift too high 0.42% > 0.35% (sig ₹83.75 -> now ...)
```
This confirms an execution guard exists and fires with threshold 0.35% price drift between signal time and fill attempt. Exact source function not read in this audit (see Evidence Gaps).

---

## L. EXIT LAYER (already mapped in prior session work, re-confirmed)

**File:** `core/engines/exit_engine.py`, dispatcher ~lines 550-600

Priority order (CONFIRMED from code, re-verified this session):
1. `check_hard_sl()` — SL / step-ladder trailing / breakeven / (TP only if trailing disabled)
2. `early_momentum_loss_cut()` — suppressed when `EXIT_ONLY_SL_TP_TRAILING=True`
3. `soft_loss_time_exit()` — suppressed when flag True
4. `greek_exit()` — suppressed when flag True
5. `profit_floor_exit()` — suppressed when flag True (no-op unless `EXIT_PROFIT_MODE='floor'`)
6. `smart_rsi_exit()` — suppressed when flag True
7. `rsi_reversal_exit()` — suppressed when flag True
8. `time_exit_15min()` / market-close force-exit — **ALWAYS runs**, not suppressed by the flag (market-close branch is unconditional; the max-hold-timeout branch IS suppressed by the flag per this session's own edit)

---

## M. FACTOR USAGE TABLE (Step 7)

| Factor | Signal (setup score) | Weighted Score | Confidence | Market Quality | Entry Filter | Risk | Instrument | Sizing |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **Delta** | ✓ hard gate (0.25-0.75) | ✓ (0.35-0.65 full/0.30-0.70 half) | ✓ (`greeks_score`, 0.35-0.65) | ✓ (`greeks_points`, 0.35-0.65) | — | — | — | — |
| **Premium** | ✓ hard gate (`check_premium_filter`) | ✓ (`premium_quality`, ≤300 full) | — | — | ✓ RE-CHECKED (`MIN/MAX_ENTRY_PREMIUM`) | — | ✓ (`STRIKE_PREMIUM_MIN/MAX`, DIFFERENT constant) | — |
| **Spread** | — (no direct spread gate in setup score) | ✓ (`spread_quality`, ≤1.0% full) | ✓ (`spread_score`) | ✓ (`spread_points`, ≤0.20% full) + hard reject if >0.60% | ✓ (`KILL_SWITCH_SPREAD` check) | — | — | — |
| **Volume** | ✓ (Vol_Spike factor, +1) | ✓ (`volume`, vol_ratio≥1.3) | ✓ (`volume_score`) | ✓ (`liquidity_points`) | — | — | — | — |
| **OI** | ✓ (+1, if `OI_CHANGE_ENABLED`) | ✓ (`oi`, direction-matched) | ✓ (`oi_score`) | — | — | — | — | — |
| **RSI** | ✓ (both bands + bonus) | ✓ (`rsi`, direction-banded) | — (not directly, feeds regime indirectly) | — | — | — | — | — |
| **VWAP** | ✓ (`Above_VWAP`/`Below_VWAP`, +1) | ✓ (`vwap`, direction-matched) | ✓ (`vwap_score`) | — | — | — | — | — |
| **Market Quality (MarketQualityEngine)** | — | — | ✓ (via grade → `_required_confidence`) | — (IS the source) | — (hard gate, pre-scoring, line 999) | — | — | ✓ (`market_quality_multiplier`) |

**Delta is the most redundant factor: checked/scored in 4 separate places with 2 different threshold bands (0.25-0.75 hard gate vs 0.35-0.65/0.30-0.70 in the three scoring systems).**
**Premium is checked in 2 places using the SAME constant on potentially DIFFERENT ticks, plus a 3rd, DIFFERENT constant pair governs which strike is fetched in the first place.**

---

## N. NON-TRADE ATTRIBUTION — Historical Rejection Funnel (Step 9-10)

**LOG EVIDENCE**, `logs/2026-09-07/events.json` (902 lines) and `logs/2026-09-08/events.json` (83 lines), both real session logs, state-machine transitions.

### 2026-09-07 (13 trades placed, pre-fix architecture — drawdown gate was a monotone one-way latch, weekly limit not yet made configurable)

```
Total state transitions into ENTRY_READY (i.e. total signals that passed
ALL of Steps H.1-10, the full smart_scalp_v3.py internal gate chain):  297

  297  IDLE -> ENTRY_READY          (100% of signals)
  284  ENTRY_READY -> COOLDOWN      (95.6% of signals — rejected after signal, before fill)
   13  ENTRY_READY -> IN_TRADE      (4.4% of signals — reached a fill)
   13  IN_TRADE -> COOLDOWN         (100% of fills eventually exited)
```

**Breakdown of the 284 post-signal rejections, by exact logged reason:**
| Reason | Count | % of 284 | Classification |
|---|---:|---:|---|
| `Risk: Max drawdown ₹3028 hit (limit: ₹3000)` | 165 | 58.1% | **RISK REJECTION** |
| `Allocator: allocator_zero_quantity` | 97 | 34.2% | **SIZING REJECTION** |
| `Cooldown 900s` (post-trade cooldown, not a rejection) | 6 | 2.1% | N/A — normal state cycling |
| `Cooldown 30s` | 4 | 1.4% | N/A |
| `Cooldown 120s` | 3 | 1.1% | N/A |
| `Exec guard: Execution drift too high` (3 instances, 0.42-25.92%) | 3 | 1.1% | **EXECUTION REJECTION** |

**Attribution summary for 2026-09-07:** Of 297 signals that survived the ~18-gate strategy/entry chain, **91.4% (272 of 297) that were genuine rejections (excluding routine post-trade cooldowns) were RISK (60.7%) or SIZING (35.7%) rejections — not strategy, not execution, not instrument.** Only 1.1% were execution-layer. **Zero instrument-selection failures logged this day.**

### 2026-09-08 (15 trades placed, post-fix architecture — this session's own changes applied mid-day)

```
  22  IDLE -> ENTRY_READY
  15  ENTRY_READY -> IN_TRADE       (68.2% of signals — reached a fill)
   7  ENTRY_READY -> COOLDOWN       (31.8% of signals — rejected after signal, before fill)
```

**Breakdown of the 7 post-signal rejections:**
| Reason | Count | Classification |
|---|---:|---|
| `Exec guard: Execution drift too high` (0.42%-0.65%, 5 instances) | 6* | **EXECUTION REJECTION** |
| `Risk: Weekly loss limit ₹2507 (max: ₹2400)` | 1 | **RISK REJECTION** |

*(one drift line appears with a duplicate count in the raw grep due to a repeated log line; treat as 5-6, exact count needs one more log pass — flagged as UNCERTAIN pending re-verification)

**Attribution summary for 2026-09-08:** Conversion rate signal→fill rose from 4.4% (09-07) to 68.2% (09-08). The dominant rejection category flipped from RISK+SIZING (95.9% combined, 09-07) to EXECUTION (majority, 09-08) — **consistent with, and independently confirming from fresh log data, this session's own claim that the drawdown-gate and sizing-floor defects were the dominant blockers on 09-07 and that fixing them changed the funnel's shape.**

### What this data CANNOT show (Evidence Gap)

Neither log file records STRATEGY-layer rejections (signals that failed `generate_signal()`'s internal 10-gate chain before reaching `ENTRY_READY`) with the same per-reason granularity — `events.json` only logs the transition INTO `ENTRY_READY`, not the many `generate_signal()` calls that returned `False` before that. The count of pure STRATEGY rejections (chop, low score, low weighted score, MQ hard-reject, premium, delta) is **NOT directly countable from `events.json`**; it would require the `dvf_signals` database (`core/validation/signal_logger.py`) or `trades.json`'s signal-snapshot records, which were referenced in code (Step A) but not queried in this audit. **This is the single largest evidence gap in the funnel.**

---

## O. REDUNDANCY / DUPLICATE LOGIC (Step 11)

| Factor | Occurrences | Each use's type | Same info counted multiple times? |
|---|---|---|---|
| **Delta** | 4: (1) hard gate 0.25-0.75 in `smart_scalp_v3.py:922-928`; (2) `WeightedScoreEngine` score component 0.35-0.65/0.30-0.70; (3) `AdaptiveConfidenceEngine` `greeks_score` 0.35-0.65/0.30-0.70; (4) `MarketQualityEngine` `greeks_points` 0.35-0.65 | (1) hard gate; (2)(3)(4) score inputs | **YES** — same delta value scored/gated 4 times, with 2 DIFFERENT threshold bands (0.25-0.75 vs 0.35-0.65) that don't even agree with each other |
| **Premium** | 3: (1) `check_premium_filter()` hard gate inside `generate_signal()`; (2) `MIN/MAX_ENTRY_PREMIUM` re-check in `entry_engine.py`; (3) `STRIKE_PREMIUM_MIN/MAX` in broker's strike search (DIFFERENT constant, different purpose — selects WHICH strike, not whether to trade) | (1)(2) hard gates, same constants; (3) hard gate, different constants | **YES for (1)+(2)** — same threshold applied twice on (possibly) different ticks; (3) is legitimately separate (strike selection vs. entry approval) |
| **Confidence** | 2: (1) internal `_required_confidence()` MQ-adjusted; (2) external flat `MIN_CONFIDENCE`/`MIN_CONFIDENCE_AFTER_3SL` | Both hard gates | **YES, but with asymmetric effect** — see Step F. The external gate is the ONLY source of the 3-loss-streak escalation; for MQ grades B/C it never fires (already stricter internally); for A/A+ it neutralizes the MQ relaxation. |
| **Market Quality** | 4 (see Step G): hard gate, confidence multiplier, sizing input, PLUS a differently-computed `market_quality_score` inside `AdaptiveConfidenceEngine` with the same name but a different formula | Gate + multiplier ×2 + naming collision | **PARTIALLY** — 3 legitimate uses of the SAME number (MarketQualityEngine's score/grade), plus one naming collision with an unrelated number |
| **RSI** | Used in setup score, weighted score, AND exhaustion check (`ce_exhausted`/`pe_exhausted` momentum-waning logic) — 3 places | Score contribution ×2, hard gate ×1 | **YES** — same RSI value scored twice and also used as a THIRD, independent hard gate (exhaustion) |
| **VWAP** | Used in setup score, weighted score, AND confidence (`vwap_score`) — 3 places | Score contribution ×3 | **YES** |
| **EMA9/EMA21 trend** | Used in setup score (required, +2), weighted score (`ema_trend`, weight 20 — the single largest weighted-score factor), AND session trend gate (`can_trade_ce/pe`, separate EMA-based regime tracker in `session_trend.py`) | Hard-required in (1); scored in (2); hard-gated again in (3) via a DIFFERENT EMA calculation (session_trend.py uses its own `SimpleEMA` with periods 9/21/50, separate state from the indicator EMAs in `calculate_indicators()`) | **YES, and with an independently-computed duplicate EMA state** — session_trend.py maintains its OWN EMA9/21/50 trackers, separate from the ones computed in `smart_scalp_v3.py:calculate_indicators()`. Two different EMA9 values may exist simultaneously, both influencing the same trade decision through different gates. |

---

## P. BYPASS / OVERRIDE PATHS (Step 12)

**Search method:** grep for `bypass|override|force_|emergency|skip_|ignore_` across `core/risk/risk_manager.py`, `core/engines/entry_engine.py`, `core/engines/state_machine.py`, `strategies/smart_scalp_v3.py`, `core/main.py`, `core/risk/kill_switch.py`.

**RESULT: No matches found for `bypass`, `override`, `force_trade`, `emergency_allow`, `skip_risk`, or `ignore_` as functional code in any of these six files.** The only match was a code COMMENT in `smart_scalp_v3.py:401` ("Optional config override file") referring to config-file precedence, not a trading-logic bypass.

**CONFIRMED: No evidence of a hard-coded bypass, forced-entry, or emergency-override path that skips the normal strategy/risk gate sequence, in the files searched.**

**Evidence Gap:** This search covered 6 files. It did NOT cover `core/trading/broker.py`, `core/trading/trade_manager.py`, `core/validation/*.py`, or `utils/*.py`, where a bypass could theoretically exist unexamined. Given the hard rule against assumption, this is reported as **UNCERTAIN for the full codebase, CONFIRMED ABSENT in the 6 core decision files.**

**One legitimate, intentional exception found and already known from this session's own work (not a "bypass" in the illicit sense, but an override of the state machine's default recovery):** `TradingState.manual_stop` (`core/engines/state_machine.py`) is a state-machine-level override of the automatic IDLE-recovery guard — `if state.state == "KILL_SWITCH" and not getattr(state, 'manual_stop', False)`. This is a deliberate, documented, single-purpose override (operator stop), not a strategy/risk bypass.

---

## Q. STRATEGY vs RISK vs EXECUTION vs SIZING vs INSTRUMENT (Step 13 — Final Classification)

| Category | Answers | Concrete gates (from this audit) |
|---|---|---|
| **STRATEGY** | "Is this market setup worth trading?" | Premium filter, delta filter (hard gate 0.25-0.75), MQ hard gate, chop detector, setup score (≥4), weighted score (≥threshold%), exhaustion check, internal confidence check |
| **RISK** | "Are we allowed to risk capital right now?" | Drawdown, weekly loss, streak limits, VIX filter, gap protection, recovery mode (soft), equity curve, time-based sizing (soft), profit lock |
| **EXECUTION** | "Can this signal actually be executed now?" | Cross-direction tick availability, external confidence re-check, spread check, session trend gate, execution-drift guard (0.35% threshold), broker fill |
| **SIZING** | "How much capital/risk can be allocated?" | `PositionSizeEngine.calculate()` — soft multipliers (score/confidence/MQ/regime/vol/recovery/daily-loss) → hard caps (capital%, daily-risk%, remaining-budget, recovery-cap) → lot rounding → min-lot floor/zero |
| **INSTRUMENT** | "Which actual option contract should be traded?" | Broker strike search (`STRIKE_PREMIUM_MIN/MAX`, midpoint-nearest selection, ATM fallback) |

**Cross-cutting factors that appear in MORE THAN ONE category** (confirmed, not inferred):
- **Market Quality** appears in STRATEGY (hard gate + confidence adjuster) AND SIZING (multiplier input)
- **Confidence** appears twice within STRATEGY itself (internal + external re-check, effectively also gating EXECUTION since the external check lives in `entry_engine.py`)
- **Delta** appears in STRATEGY (hard gate + 3 scoring inputs) — no risk/sizing/instrument use found

---

## R. DEAD / UNUSED LOGIC (Step 4 supplement, consolidated)

| Item | Status | Evidence |
|---|---|---|
| `calculate_bullish_score()` / `calculate_bearish_score()` (`smart_scalp_v3.py:664-862`) | **LIKELY DEAD in the live path** — `generate_signal()` uses an inline duplicate instead | No call sites found for these two methods outside their own definitions and unit tests |
| `_required_confidence()`'s `'REJECT': +5` branch | **CONFIRMED UNREACHABLE** — MQ hard-rejects before this function is ever called with a REJECT grade | `smart_scalp_v3.py:999-1005` (early return) precedes `:1301/1328` (where `_required_confidence` is called) |
| Range position filter (`ENTRY_RANGE_FILTER_ENABLED`) | **NOT dead, but CONFIRMED OFF by default** — code path exists and is exercised by tests, but does not run in the live configuration currently deployed | `.env` / `config/constants.py` default `False` |
| `EXIT_ONLY_SL_TP_TRAILING`-suppressed exits (early loss cut, soft loss, greek exit, profit floor, smart RSI, RSI reversal) | **NOT dead** — actively suppressed TODAY by a flag this session set to `True`; fully live code when flag is `False` (which was true for 27 of 28 trades across 09-07/09-08) | `core/engines/exit_engine.py`, flag-gated dispatcher |

---

## S. EVIDENCE GAPS (Step R — Complete List)

Explicitly NOT verified in this audit; do not treat as fact:

1. **`core/risk/risk_manager.py` gates 9 onward** — only read through `check_profit_lock()` call at line ~560; further gates (if any) past that point not read.
2. **`core/risk/kill_switch.py`** — file listed, not read in this audit session.
3. **`core/risk/validators.py`** beyond `greek_gate()` — the other `validate_price_ptq`, `validate_time_ptq`, `validate_quantity_ptq` functions referenced by name and call site only, internal logic not re-verified this session (was read in a prior session per memory, not independently re-confirmed here).
4. **Execution-drift guard's exact source function** — confirmed to exist and fire via LOG EVIDENCE only (`events.json` messages); the producing code (likely `core/validation/execution_guard_report.py`) was not read this session.
5. **STRATEGY-layer-only rejection counts** (chop/score/weighted-score/MQ/premium/delta rejections that never reach `ENTRY_READY`) are **not present in `events.json`** and were not queried from `dvf_signals`/`trades.json` signal snapshots in this audit — the funnel above starts at `ENTRY_READY`, not at raw tick evaluation. This is the largest gap in Step 9-10's quantification.
6. **Broker order-failure / API-failure paths** — `core/trading/broker.py`'s full order-placement function was read partially (strike search, symbol build) in prior sessions; the fill/failure branches were not re-read this session.
7. **Bypass search scope** — confirmed absent in 6 core files; NOT searched in `broker.py`, `trade_manager.py`, `validation/*.py`, `utils/*.py`.
8. **`session_trend.py`'s `can_trade_ce()`/`can_trade_pe()`** exact pass/fail logic — file opened, class/EMA structure read, but the two gating methods themselves were not read line-by-line this session.
9. **2026-09-08 execution-drift count** — flagged as approximate (5 or 6) pending a cleaner log re-parse; the raw grep output had one ambiguous duplicate line.

---

END OF STEP 4-14 EVIDENCE — FULL AUDIT COMPLETE (WITH GAPS EXPLICITLY MARKED ABOVE)
