# PTQ SCALPING BOT — PHASE 1: STRATEGY ARCHITECTURE SIMPLIFICATION
### Inventory → Classification → Architecture Design → Evidence. NO CODE CHANGES.
### Builds on `claude_code/report/strategy_forensics_20260908.md` (Phase 0). New evidence gathered this session is marked NEW.

---

## 1. CURRENT STRATEGY CONDITION INVENTORY

| Condition | File | Function | Input | What it detects | Hard/Soft | Blocks signal? | Evidence |
|---|---|---|---|---|---|---|---|
| Warm-up | `smart_scalp_v3.py:907` | `generate_signal()` | tick count | Enough history to compute indicators | Hard | Yes | `if len(ticks)<5: return 0,"",0,{...}` |
| Premium filter | `smart_scalp_v3.py:915,321-360` | `check_premium_filter()` | option LTP/bid/ask | Option too cheap/expensive to trade meaningfully | Hard | Yes | `MIN_ENTRY_PREMIUM`/`MAX_ENTRY_PREMIUM` |
| Delta filter | `smart_scalp_v3.py:922-928` | inline, `get_option_delta()` | option delta | Moneyness — too deep OTM or ITM | Hard | Yes | `DELTA_MIN=0.25`/`DELTA_MAX=0.75` |
| OI change | `smart_scalp_v3.py:933+` | `update_oi_data()` | OI delta | Buildup/unwinding direction | Soft (score input only) | No — feeds score | `oi_direction` variable |
| Market Quality | `smart_scalp_v3.py:971-1005` | `MarketQualityEngine.evaluate()` | spread/liquidity/freshness/ATR/greeks/session/execution | Is the market currently tradable/executable | Hard | Yes | `if not passed: return 0,"",0,...` |
| Chop filter | `smart_scalp_v3.py:1014-1045` | inline | EMA separation + ATR + MACD flatness | Sideways/no-momentum condition | Hard, but requires ALL 3 sub-conditions (AND-gate, rare) | Yes | `if len(chop_reason)>=3` |
| EMA trend (setup score) | `smart_scalp_v3.py:1056/1117` | inline | EMA9 vs EMA21 | Directional trend — **required**, not optional | Hard (required for any score) | Yes (0 score without it) | `if ema9>ema21: ce_score+=2` |
| EMA9 pullback/rejection | `smart_scalp_v3.py:1060-1064/1121-1125` | inline | price proximity to EMA9 | Pullback to a moving-average support/resistance | Soft (scored) | No | +2 points |
| Candle direction | `smart_scalp_v3.py:1067-1073/1128-1134` | inline | close vs prev_close, close vs EMA9 | Bullish/bearish confirmation candle | Soft | No | +1/+1 points |
| RSI (setup score) | `smart_scalp_v3.py:1076-1081/1136-1141` | inline | RSI(14) | Momentum confirmation, direction-banded | Soft | No | +1, +1 bonus |
| VWAP (setup score) | `smart_scalp_v3.py:1088-1090/1148-1150` | inline | price vs VWAP | Institutional-reference bias | Soft, gated by `VWAP_ENABLED` | No | +1 |
| Volume spike (setup score) | `smart_scalp_v3.py:1093-1095/~1153` | inline | Vol_Ratio + candle direction | Participation confirming the move | Soft | No | +1 |
| **Squeeze breakout** | `smart_scalp_v3.py:725-728/825-828` | inline | `was_squeeze and not squeeze and macd direction` | Volatility contraction releasing (classic breakout signature) | Soft — **AND CONFIRMED DEAD** (NEW finding, see §5) | No — never fires | `Was_Squeeze` hardcoded `False` at line 562 |
| OI (setup score) | `smart_scalp_v3.py:1098-1100/~1158` | inline | OI direction match | Same OI info as above, re-scored | Soft, gated by `OI_CHANGE_ENABLED` | No | +1 |
| Weighted score (12-factor) | `weighted_score_engine.py:31-130` | `WeightedScoreEngine.score()` | ema_trend/vwap/volume/delta/oi/rsi/macd/atr/premium/greeks/regime/spread | Same behaviours re-scored as a %, plus MACD/ATR/regime/spread/greeks not in setup score | Hard threshold | Yes | `min_weighted_score_pct` |
| Exhaustion check | `smart_scalp_v3.py:1264-1294` | inline | RSI extreme + MACD declining, OR SL-streak direction block | Momentum running out / direction recently punished | Hard | Yes | `if ce_exhausted: return 0,"",0,...` |
| Adaptive confidence | `adaptive_confidence_engine.py:27-118` | `AdaptiveConfidenceEngine.score()` | regime × internal-MQ × session × execution-quality(spread/volume/greeks/oi/vwap/freshness) | Composite "is this a good time/setup" multiplier | Hard threshold, MQ-grade-adjusted | Yes | `_required_confidence()` |
| Session trend gate | `session_trend.py` | `can_trade_ce()`/`can_trade_pe()` | independently-computed EMA9/21/50 + opening displacement + RSI | A SECOND, separately-maintained trend/regime read | Hard | Yes | called in `entry_engine.py:272-281` |
| **Supertrend** | `smart_scalp_v3.py:545-554` | inline | EMA21 ± 1.5×ATR band | A THIRD trend concept | **CONFIRMED DEAD** (NEW finding) | No — computed, never read elsewhere | grep found zero other reads of `indicators['Supertrend']` |
| Confidence re-check (external) | `entry_engine.py:202-208` | inline | same confidence value | Redundant re-application of a threshold | Hard | Yes, in specific cases only (see Phase 0 §F) | `MIN_CONFIDENCE`/`MIN_CONFIDENCE_AFTER_3SL` |
| Premium re-check (external) | `entry_engine.py:246-252` | inline | execution_tick LTP | Redundant re-application of premium band | Hard | Yes | same constants, possibly different tick |
| Spread check | `entry_engine.py:259-265` | inline | execution_tick bid/ask | Execution cost sanity | Hard | Yes | `KILL_SWITCH_SPREAD` |
| Time/Greek gate (live only) | `entry_engine.py:302-314` | `validate_time_ptq()`, `greek_gate()` | time-to-expiry, delta/gamma/theta | Same greek concept re-checked a 5th time | Hard, but **skipped in PAPER_TRADING** | Yes, live only | `if not PAPER_TRADING:` |

**NEW findings this session** (marked above and detailed in §5):
- `Squeeze_Breakout!` — the only breakout-shaped scoring factor in the whole codebase — is **permanently dead**: `Was_Squeeze` is hardcoded `False` and never updated (comment says "will be updated with historical data" — it is not).
- `Supertrend` is computed every cycle and **never read by anything else** — a fourth trend indicator (after setup-score EMA, weighted-score EMA, session_trend's own EMA) that contributes nothing.
- **No price-structure breakout logic exists anywhere** (no "close breaks above prior N-bar high" style condition). The only structural-break concept was the now-dead squeeze release.
- **No candle body/wick-size logic exists** — only direction (`close > prev_close`) and EMA-proximity via high/low. No candle-range, body-to-range ratio, or wick-rejection sizing anywhere.
- **No independent Reversal *entry* strategy exists.** The only reversal-shaped logic in the entire codebase is on the EXIT side (`rsi_reversal_exit()` in `exit_engine.py`) and the entry-side "exhaustion" check, which SUPPRESSES a signal (turns it off) rather than GENERATING an opposite-direction entry. There is no code path where a failed breakout or exhausted move produces a new trade in the other direction.

---

## 2. CURRENT ACTIVE DECISION PATH

(Confirmed identical to Phase 0 report §B/H — restated compactly here as the baseline for simplification.)

```
tick → warm-up → premium(hard) → delta(hard) → OI(compute) → Market Quality(hard)
     → chop(hard, AND-of-3) → setup score(hard, ≥4/11 or /12) → weighted score(hard, ≥threshold%)
     → exhaustion(hard) → adaptive confidence(hard, MQ-adjusted)
     → [generate_signal() returns True] →
     entry_engine: cross-direction tick → confidence RE-CHECK(hard) → range filter(off)
     → premium RE-CHECK(hard) → spread(hard) → session trend gate(hard, 2nd independent EMA system)
     → [live only] time + greek RE-CHECK(hard, 5th delta touch)
     → ENTRY_READY → RiskManager (9 gates) → PositionSizeEngine → broker strike search → fill
```

**18 gates total before RiskManager, confirmed by direct code read (Phase 0 §H), 5 of which are re-checks of information already evaluated earlier in the same chain** (confidence ×2, premium ×2, delta touched in 4 places).

---

## 3. MARKET BEHAVIOUR CLASSIFICATION

Every condition from §1, mapped to the requested behaviour categories. **Only condition names actually found in code are listed — nothing invented.**

### TREND
- EMA9 vs EMA21 (setup score, required base condition) — `smart_scalp_v3.py:1056/1117`
- `ema_trend` weighted-score factor (same underlying EMA comparison, re-scored) — `weighted_score_engine.py:54-57`
- `regime` (`get_market_regime()`, feeds weighted score's `market_regime` factor and confidence's `regime_score`)
- Session Trend Tracker's own EMA9/21/50 (`session_trend.py`) — **independently computed, separate state**
- **Supertrend** (dead, computed only)

### MOMENTUM
- RSI (setup score direction-banded, +1/+1 bonus)
- RSI (weighted score, direction-banded)
- MACD histogram direction+slope (weighted score `macd` factor)
- Volume spike (participation confirming a momentum move) — arguably PARTICIPATION, see below; classified here only where it gates candle-direction confirmation

### PULLBACK
- "EMA9_Pullback" / "EMA9_Rejection" — price returns to EMA9 within 0.5% or between low/high and close — `smart_scalp_v3.py:1060-1064` (CE) / `1121-1125` (PE)
- This is the **base structural condition of the entire strategy** — it is literally named "PULLBACK LOGIC FOR CE/PE" in the code's own section comments (`smart_scalp_v3.py:1047, 1107`)

### BREAKOUT
- `Squeeze_Breakout!` factor — **CONFIRMED DEAD** (see §1, §5). This is the ONLY breakout-shaped condition that exists in the code, and it cannot fire.
- **No other breakout logic found.** No prior-high/prior-low break, no range-break, no volatility-expansion-after-contraction logic besides the dead squeeze factor.

### REVERSAL
- **No entry-side reversal strategy found.** 
- Exhaustion check (`ce_exhausted`/`pe_exhausted`) detects momentum running out but only SUPPRESSES the current-direction signal; it does not generate an opposite-direction trade.
- `rsi_reversal_exit()` (exit-side only, `exit_engine.py`) detects RSI direction-reversal to CLOSE an existing position, not to open a new one.

### PARTICIPATION
- Volume / Vol_Ratio (setup score, weighted score, MQ liquidity component, confidence volume_score) — appears in 4 places
- OI direction (setup score, weighted score, confidence oi_score) — appears in 3 places
- MQ `liquidity_points` (vol_ratio/volume tiered)

### MARKET QUALITY
- `MarketQualityEngine` — spread, liquidity, freshness, volatility(ATR/VIX), execution health, greeks-stability, session-time — the dedicated engine (Phase 0 §G)
- Spread also independently checked in setup path (`spread_quality` in weighted score) and entry path (`KILL_SWITCH_SPREAD` in entry_engine)

### RISK
- **Deliberately NOT mixed in above.** RiskManager's 9 gates (drawdown, weekly loss, streak, VIX, gap, recovery, equity curve, time-sizing, profit lock) are entirely separate from the Strategy layer, confirmed in Phase 0 §J/Q, and are excluded from this classification as instructed.

---

## 4. EXISTING STRATEGY FAMILIES

| Strategy | Exists? | Active? | Core conditions | Hidden dependencies | Score dependency |
|---|---|---|---|---|---|
| **Pullback** | **YES — this is the actual, named strategy.** The code's own section headers literally read "PULLBACK LOGIC FOR CE (BULLISH)" / "PULLBACK LOGIC FOR PE (BEARISH)" (`smart_scalp_v3.py:1047, 1107`). | **YES, this is the ONLY strategy that currently ever fires an entry.** | Required: EMA9 vs EMA21 trend. Scored: EMA9 proximity, candle direction, RSI band, VWAP, volume, OI. | MQ hard gate, chop hard gate, premium/delta hard gates all run first and can block it before it is even evaluated | YES — gated by BOTH the inline setup score (≥4) AND the separate weighted score (≥threshold%) |
| **Momentum** | **PARTIALLY — momentum is used only as a scoring SUB-FACTOR (RSI band, MACD direction, volume spike) inside the Pullback strategy above, not as an independently-triggerable strategy.** There is no standalone "momentum strategy" that can fire a trade on its own without the pullback's required EMA9-proximity condition. | Its components fire, but never independently of Pullback | RSI band, MACD direction/slope, volume spike | Fully nested inside Pullback's gating — cannot fire alone | YES, same score |
| **Breakout** | **NO — does not currently exist as a live, firing strategy.** The only breakout-shaped condition (`Squeeze_Breakout!`) is architecturally present but permanently dead (`Was_Squeeze` hardcoded `False`). No other breakout logic (structural high/low break) exists anywhere in the codebase. | **NO** | N/A | N/A | N/A |
| **Reversal** | **NO — requires further evidence; not found as an entry-generating strategy.** The only reversal-shaped code detects and SUPPRESSES the current signal (exhaustion) or CLOSES an existing position (`rsi_reversal_exit`), neither of which generates a new opposite-direction entry. | N/A | N/A | N/A | N/A |
| **Trend continuation** | **NO distinct strategy — trend is a REQUIRED PRECONDITION of Pullback, not a standalone entry trigger.** EMA9-vs-EMA21 alone (without the pullback-proximity condition) never generates a signal; it only unlocks scoring for the pullback conditions beneath it. | N/A as standalone | N/A | Fully subsumed by Pullback | N/A |

**Conclusion for Step 3:** The current system implements **exactly one entry strategy — Pullback** (trend-required, EMA9-proximity-triggered), decorated with momentum/participation/quality sub-factors as scoring inputs and re-checked through two independent scoring systems plus a confidence layer. Everything the target architecture calls "Momentum," "Breakout," and "Reversal" either (a) exists only as a nested sub-factor of Pullback with no independent trigger path, (b) is architecturally present but permanently dead code, or (c) does not exist at all.

---

## 5. SEPARATING MARKET BEHAVIOUR FROM INDICATOR CONDITIONS

Per the requested format — indicators mapped to the behaviour they are actual evidence for, verified against code:

```
EMA9 > EMA21 (required, +2)                    → behaviour: directional trend (precondition, not a trigger)
Price returns to within 0.5% of EMA9             → behaviour: pullback (THE trigger condition)
  or low <= EMA9 <= close (CE) / high >= EMA9 >= close (PE)
Green/Red candle vs prev_close                   → behaviour: momentum confirmation (single-bar)
Close vs EMA9 (bonus point)                      → behaviour: momentum confirmation (position vs MA)
RSI band (45-70 CE / 30-50 PE, ±bonus)            → behaviour: momentum strength confirmation
VWAP side                                        → behaviour: institutional-reference bias confirmation
Volume spike + directional candle                → behaviour: participation confirming the move
OI direction match                               → behaviour: participation confirming the move (options-specific)
was_squeeze and not squeeze and MACD direction   → behaviour: breakout (INTENDED, but dead — was_squeeze
                                                     is hardcoded False, so this NEVER contributes)
MACD histogram direction+slope (weighted score)  → behaviour: momentum confirmation
ATR band 4-18 (weighted score)                   → behaviour: "tradable volatility" — closer to Market
                                                     Quality than to a directional behaviour
Premium ≤300 (weighted score)                    → behaviour: NOT a market behaviour — an instrument/
                                                     cost-suitability filter mis-classified as a scoring factor
Delta 0.35-0.65 (weighted score + confidence)    → behaviour: NOT a market behaviour — an instrument
                                                     moneyness filter mis-classified as a scoring factor
Spread ≤1.0%/2.0% (weighted score)               → behaviour: NOT a market behaviour — execution quality,
                                                     already covered by MarketQualityEngine
Regime (BULLISH/BEARISH/SIDEWAYS)                → behaviour: directional trend, computed a 2nd/3rd way
                                                     (see §1 TREND — three separate trend computations exist)
```

**Key finding for the architecture redesign:** Of the current setup-score/weighted-score factor list, only **five** conditions genuinely detect a market *behaviour* as the user's target philosophy defines it (trend, pullback, momentum, participation): EMA9-vs-21, EMA9-proximity, candle direction, RSI band, volume spike/OI. The remaining factors (premium, delta, spread, ATR-band) are **instrument-suitability or execution-quality checks that have been folded into the strategy's scoring system**, where — per the target architecture's own separation (Strategy vs MQ vs Instrument vs Execution) — they do not belong. This is itself the clearest evidence for why the current architecture reads as "over-filtered": genuine market-behaviour evidence and execution/instrument suitability are scored together, indistinguishably, in the same weighted sum.

---

## 6. OVER-CONSTRAINT / REDUNDANCY FINDINGS

Reusing and extending Phase 0 §O with the architectural framing requested here:

### A. Same information used repeatedly
```
Delta:      hard gate (0.25-0.75) → weighted score (0.35-0.65) → confidence (0.35-0.65)
            → market quality (0.35-0.65) → [live only] greek gate (5th touch)
            TWO DIFFERENT THRESHOLD BANDS in play simultaneously (0.25-0.75 vs 0.35-0.65)

Premium:    strategy hard gate (check_premium_filter) → weighted score (premium_quality)
            → entry_engine re-check (same constants) → broker strike search (DIFFERENT constants)

Confidence: internal MQ-adjusted gate → external flat re-check (asymmetric effect, Phase 0 §F)

Spread:     weighted score (spread_quality) → MarketQualityEngine (spread_points, hard-reject too)
            → entry_engine spread check (KILL_SWITCH_SPREAD, 3rd application)

EMA9/21:    setup score (required) → weighted score (ema_trend, largest single weight=20)
            → session_trend.py's OWN independently-computed EMA9/21/50 (entry_engine gate)
            → Supertrend (computed from EMA21±ATR, dead)
```

### B. Same market behaviour represented by many indicators
**Trend** is represented by FOUR separate computations: (1) setup-score's `ema9 > ema21`, (2) weighted-score's `ema_trend` factor (same comparison, re-scored), (3) `session_trend.py`'s independently-maintained EMA9/21/50 tracker, (4) `Supertrend` (dead). These are not four independent confirmations of trend — (1) and (2) read the SAME EMA values computed once in `calculate_indicators()`; only (3) is a genuinely separate computation (it maintains its own EMA state) and could theoretically disagree with (1)/(2) at any given tick.

**Pullback confirmation** is scored by 3 overlapping signals that are largely restating the same fact: EMA9-proximity (pullback itself), candle direction (price moved back up/down), close-vs-EMA9 (price position relative to the same MA). These are correlated, not independent, evidence for one behaviour.

### C. Sequential gates that can independently kill the same setup
A single Pullback signal must survive, in order: premium → delta → MQ → chop → setup-score(≥4) → weighted-score(≥threshold) → exhaustion → confidence(MQ-adjusted) → [exit generate_signal] → confidence(re-check) → premium(re-check) → spread → session-trend(independent EMA) → [live] time+greek. **14 of these 18 gates can each independently reject the identical underlying pullback setup**, several of them re-testing information (delta, premium, confidence, trend) already tested by an earlier gate in the same chain.

### D. Conditions that rarely or never contribute
- `Squeeze_Breakout!` — **never contributes** (`Was_Squeeze` hardcoded False)
- `Supertrend` — **computed, never read**
- `calculate_bullish_score()`/`calculate_bearish_score()` methods (lines 664-862) — **likely unreachable**, `generate_signal()` uses an inline duplicate instead (Phase 0 §R)
- `_required_confidence()`'s `'REJECT': +5` branch — **confirmed unreachable** (Phase 0 §F)
- Chop filter's AND-of-3 structure means it fires far less often than an OR-of-2 or OR-of-3 would — architecturally present but statistically rare by design
- `min_lot_floor_enabled=False` by default (Phase 0, sizing) — the entire min-lot-rescue mechanism in `PositionSizeEngine` is present but disabled in the shipped default config

---

## 7. KEEP / DISABLE CANDIDATE / RELOCATE / REVIEW TABLE

| Current Condition | Classification | Reason | Evidence |
|---|---|---|---|
| EMA9 vs EMA21 (trend precondition) | **KEEP** | Core, named behaviour (trend), the required base of the only working strategy | `smart_scalp_v3.py:1056/1117` |
| EMA9-proximity (pullback trigger) | **KEEP** | This IS the strategy — the code's own section name | `smart_scalp_v3.py:1060-1064/1121-1125` |
| Candle direction | **KEEP** | Genuine, minimal price-action confirmation | `smart_scalp_v3.py:1067-1073` |
| RSI band (setup score) | **KEEP** | Genuine momentum confirmation | `smart_scalp_v3.py:1076-1081` |
| VWAP side | **REVIEW** | Genuine behaviour signal but redundant with regime/trend; unclear independent contribution vs EMA trend | `smart_scalp_v3.py:1088-1090` |
| Volume spike | **KEEP** (as PARTICIPATION confirmation) | Genuine, distinct behaviour category from trend/momentum | `smart_scalp_v3.py:1093-1095` |
| OI direction (setup score) | **REVIEW** | Same info scored again in weighted-score and confidence — 3 uses of one signal | `smart_scalp_v3.py:1098-1100` |
| `Squeeze_Breakout!` | **DISABLE CANDIDATE** *(already inert)* | Cannot fire (`Was_Squeeze` hardcoded False) — a decision is needed on whether to fix it into a real breakout detector or formally retire it; either way it does nothing today | `smart_scalp_v3.py:562,725-728` |
| `Supertrend` | **DISABLE CANDIDATE** *(already inert)* | Computed every cycle, read by nothing | `smart_scalp_v3.py:545-554` |
| `calculate_bullish_score()`/`calculate_bearish_score()` methods | **REVIEW** | Likely dead (no call site found), but this audit did not exhaustively search every caller across the repo | Phase 0 §R |
| **Weighted score engine (2nd scoring system)** | **REVIEW** | Re-scores mostly the same behaviours as setup score, PLUS folds in premium/delta/spread (instrument/execution concerns — see RELOCATE below) | §5 |
| Premium, delta, spread, ATR-band as WEIGHTED-SCORE factors | **RELOCATE** | Per the target architecture's own philosophy (Strategy vs MQ vs Instrument), these are not market behaviours — they belong in MQ/Instrument/Execution, not folded into a trend/momentum score | §5 |
| Market Quality hard gate | **KEEP, but RELOCATE the point of application** | The gate itself is legitimate (execution-tradability check) but currently sits in the MIDDLE of the strategy evaluation chain (before scoring); target architecture places MQ AFTER strategy confirmation | §1, target arch §11 |
| Chop filter | **REVIEW** | AND-of-3 structure makes it fire rarely; whether it meaningfully differs from "trend absent" (EMA9≈EMA21, which the pullback's own required precondition already handles) needs verification | §1 |
| Exhaustion check | **REVIEW** | Detects a real behaviour (momentum fading) but currently only SUPPRESSES; the target architecture's "Reversal" family would need this reframed as a trigger, not just a blocker | §3, §4 |
| Internal adaptive confidence gate | **KEEP** | Composite quality-of-setup measure; conceptually sound as a single confirmation step | §1 |
| **External confidence re-check** (`entry_engine.py:202-208`) | **DISABLE CANDIDATE** for the flat-70% portion (redundant, asymmetric per Phase 0 §F) — **KEEP** the 3-loss-streak 85% escalation (the only place that logic exists) | Needs to be split, not removed wholesale | Phase 0 §F |
| **External premium re-check** (`entry_engine.py:246-252`) | **DISABLE CANDIDATE** | Same constants as the strategy's own `check_premium_filter()`, on a possibly-different tick — genuinely redundant unless the cross-direction-tick difference is the deliberate point (needs REVIEW, not outright disable) | §6.A |
| Spread check (`entry_engine.py`) | **RELOCATE** | Belongs to MQ/Execution, not a 3rd independent Strategy-adjacent check | §5 |
| Session trend gate (`session_trend.py`) | **REVIEW** | A genuinely SEPARATE trend computation from the one used inside the strategy — could disagree with it; unclear if this is intentional double-confirmation or accidental duplication | §6.B |
| [Live-only] time + greek gate | **RELOCATE** | Delta/greeks belong to Instrument selection, not a 5th touch inside Entry | §1, §7 |
| RiskManager's 9 gates | **KEEP, unchanged** | Already correctly separated from Strategy (Phase 0 §J/Q) — explicitly out of scope for this redesign per Step 14 | Phase 0 §J |
| PositionSizeEngine | **KEEP, unchanged** | Already correctly separated (Sizing) | Phase 0 |
| Broker strike search | **KEEP, unchanged** | Already correctly separated (Instrument) — note its premium band differs from the entry filter's (Phase 0 §I) | Phase 0 §I |

---

## 8. CE vs PE STRUCTURE

Re-confirmed from Phase 0 §D plus this session's new evidence: **CE and PE are genuinely symmetric at every layer inspected** — setup score, weighted score, confidence, chop, MQ, entry filters. No CE-only or PE-only condition, no asymmetric threshold, found in this audit.

```
Momentum:  CE = bullish momentum (RSI>55 band, MACD>0 rising)     PE = bearish momentum (RSI<45 band, MACD<0 falling)  — SAME STRUCTURE, mirrored bands
Pullback:  CE = price returns to EMA9 from above                  PE = price returns to EMA9 from below                — SAME STRUCTURE
Breakout:  N/A (dead on both sides — Was_Squeeze is False regardless of direction)
Reversal:  N/A (does not exist on either side as an entry trigger)
```

**No genuine asymmetry found.** The one difference worth flagging: the `Squeeze_Breakout!` factor's dead condition (`was_squeeze and not squeeze and macd_hist > 0` for CE, `< 0` for PE) is symmetric in its (non-)effect — it fails identically on both sides.

---

## 9. SCORING SYSTEMS — WHAT WOULD NEED TO BE REPLACED (Step 7, conceptual only, NOT implemented)

Three cumulative-point/percentage mechanisms currently exist and would need conceptual replacement by binary strategy PASS/FAIL, per the target architecture:

1. **Setup score** (`smart_scalp_v3.py` inline, 0-11/12 points, threshold `min_score≥4`) — currently the FIRST scoring gate.
2. **Weighted score** (`WeightedScoreEngine`, 0-100%, threshold `min_weighted_score_pct`) — currently the SECOND scoring gate, re-scoring overlapping behaviours plus non-behavioural instrument/execution factors (§5, §7 relocate candidates).
3. **Adaptive confidence** (`AdaptiveConfidenceEngine`, multiplicative 0-100, MQ-grade-adjusted threshold) — currently the THIRD scoring gate.

**Conceptual replacement target (not implemented):** A single Pullback-strategy PASS/FAIL, built from the behaviourally-genuine conditions identified in §5/§7 KEEP list (trend precondition + pullback-proximity trigger + momentum confirmation + participation confirmation), with premium/delta/spread/ATR-band moved out to MQ/Instrument/Execution where they do not need cumulative scoring at all — they are already binary suitability checks in those layers (Phase 0 §G, §I, §K).

This would collapse 3 sequential scoring systems (each independently capable of rejecting the identical setup, §6.C) into 1 binary strategy confirmation, matching Step 7's explicit instruction. **No replacement code or thresholds are proposed here.**

---

## 10. CANDLE / PRICE-ACTION INVENTORY (Step 9)

**Actually used in code today:**
- `close`, `prev_close` — direction only (green/red)
- `high`, `low` — used ONLY for EMA9-proximity checks (`low <= ema9 <= close`), never for structural break detection
- No candle body size, no wick size, no body-to-range ratio anywhere in `strategies/smart_scalp_v3.py`

**What this means for the target architecture:** The target philosophy's step "Observe the candle → Observe market structure → Identify the setup" is currently only partially realized. Direction (green/red) exists; structural elements (prior-high/low breaks, wick rejection, body dominance) do not exist in any form, live or dead. This is a genuine gap between current code and the target architecture's stated philosophy, not a redundancy — there is nothing to disable here, only something that would need to be newly designed if Breakout/Reversal strategies are to become real (out of scope for Phase 1 per the hard rules).

---

## 11. PROPOSED SIMPLE STRATEGY ARCHITECTURE (Step 11 — design only, no thresholds beyond what already exists)

Based strictly on what currently exists and fires (§4 conclusion: only Pullback is real and active):

```
CANDLE / TICK DATA
        ↓
MARKET STRUCTURE (EMA9/21 trend — ONE computation, not three)
        ↓
STRATEGY DETECTION
        ├── Pullback   [EXISTS, ACTIVE — trend-required, EMA9-proximity trigger,
        │               momentum+participation as confirmation, not as separate gates]
        ├── Momentum   [EXISTS ONLY AS A SUB-FACTOR of Pullback today — would need to be
        │               extracted as an independently-triggerable strategy, which is new
        │               design work, not a simplification of existing code]
        ├── Breakout   [DOES NOT EXIST — dead code only (Squeeze_Breakout).
        │               "Requires further evidence" / new design if pursued]
        └── Reversal   [DOES NOT EXIST as an entry strategy.
                        "Requires further evidence" / new design if pursued]
        ↓
STRATEGY CONFIRMATION (single PASS/FAIL, replacing 3 stacked scoring systems — §9)
        ↓
MQ (moved to run AFTER strategy confirmation, not interleaved before/during scoring)
        ↓
ENTRY
```

Per Step 15's explicit instruction: **"If Reversal is genuinely supported by current code, include it. If not, say: Reversal strategy requires further evidence." — Reversal requires further evidence; it is not supported by current code as an entry strategy.** The same applies to Breakout.

---

## 12. PROPOSED ENTRY ARCHITECTURE (Step 12)

```
Strategy PASS (single Pullback confirmation, §9/§11)
      ↓
MQ PASS (MarketQualityEngine, unchanged — Phase 0 §G)
      ↓
Basic execution validation (spread + drift — currently duplicated across
      strategy-internal and entry_engine-external checks, §6/§7; RELOCATE
      candidates, not yet removed)
      ↓
Risk permission (RiskManager's 9 gates, entirely unchanged — Phase 0 §J)
      ↓
Sizing (PositionSizeEngine, entirely unchanged)
      ↓
Order (broker strike search + fill, entirely unchanged — Phase 0 §I)
```

Current entry gates, classified (consolidating §7's table for this specific step's ask):
| Gate | Classification |
|---|---|
| Confidence re-check (flat 70/85) | DISABLE CANDIDATE for the 70% portion / KEEP the 85%-streak portion |
| Premium re-check | DISABLE CANDIDATE (same constants, likely same tick in practice) |
| Delta touched again at greek gate (live only) | RELOCATE to Instrument |
| Spread check | RELOCATE to MQ/Execution |
| Session trend gate (2nd EMA system) | REVIEW — may be intentional double-confirmation |
| Signal age / price drift (execution guard) | KEEP — this is a genuine EXECUTION-layer concern, correctly placed already (Phase 0 §K) |

---

## 13. EXIT ARCHITECTURE BOUNDARY (Step 13)

**Per instruction: "ceiling/floor" = the user's term for the TP/SL boundary range, not a separate exit indicator. Treated as such throughout.** Note this is DIFFERENT from the code's own unrelated `profit_floor_exit()` function (an experimental, currently-inactive-unless-configured exit mode, `EXIT_PROFIT_MODE='floor'`) — that naming collision is flagged so it is not mistaken for the user's "floor."

**Current exit conditions, historically (i.e., when `EXIT_ONLY_SL_TP_TRAILING=false`, which was the state for 27 of 28 trades across 2026-09-07/09-08):**

| Exit condition | Can close before SL/TP? | Fires inside the SL/TP range? | Strategy exit or risk protection? | Evidence |
|---|---|---|---|---|
| Hard SL / step-trailing / breakeven | N/A — this IS the boundary | N/A | Risk protection (the boundary itself) | `exit_engine.py:120-215` |
| Early momentum loss cut | **YES** | **YES, close to entry** | Risk protection (fast adverse-move cut) | fires at −1.9 to −3.2 pts historically (real log data, both sessions) |
| Soft loss timeout | **YES** | **YES, close to entry** | Risk protection (time+loss combined) | fires at −1.9 to −2.1 pts historically |
| Greek exit (theta/gamma/delta kill) | **YES** | Can fire inside range | Risk protection | `exit_engine.py:450-470` |
| Profit floor exit (experimental) | Only relevant if `EXIT_PROFIT_MODE='floor'` | Inside range on the profit side | Strategy-adjacent (profit-taking discipline) | inactive by default |
| Smart RSI exit | **YES** | Can fire inside range, profit side typically | Strategy exit (momentum-based profit-take) | — |
| RSI reversal exit | **YES** | Can fire inside range | Strategy exit (momentum reversal detected) | fires on wins, both sessions (+30 to +133 gross observed) |
| Time exit (15min) / market close | Fires at time boundary, independent of price | Can be inside range | Risk protection (mandatory) | — |

**Verification of the user's specific observation** ("previous additional exit conditions caused premature exits very close to entry, sometimes around 1-2 points away"): **CONFIRMED BY LOG EVIDENCE**, not merely accepted as reported. Direct measurement from `logs/2026-09-07/session_stdout.log` and `logs/2026-09-08/session_stdout.log`:
```
Early Loss Cut / Soft Loss Exit distances from entry, both sessions combined:
  -1.9pts × 6    -2.0pts × 4    -2.1pts × 2    -2.5pts × 4
  -2.6pts × 6    -2.7pts × 2    -2.8pts × 2    -3.2pts × 2    -5.3pts × 2 (outliers)
```
These exits are well inside the SL7 boundary — the observation is accurate, though the typical distance measured is closer to 2-3 points than 1-2.

**Current state as of THIS session's own earlier work (not historical):** `EXIT_ONLY_SL_TP_TRAILING=true` is presently set in `.env`. Under this flag, early-loss-cut, soft-loss, greek-exit, profit-floor, smart-RSI, and RSI-reversal are **all currently suppressed** — only Hard SL / step-trailing / breakeven / mandatory time-exit fire. This is already exactly the "Dynamic SL / Dynamic TP / Dynamic Trailing only" boundary the target architecture describes. **No Exit Engine changes are proposed in Phase 1** per the hard rules; this section only documents the boundary as it currently is and historically was.

---

## 14. STRATEGY vs MQ vs RISK vs EXECUTION vs INSTRUMENT (Step 14)

Unchanged from Phase 0 §Q, restated as the fixed reference frame for this redesign:

| Category | Answers | Must NOT contain |
|---|---|---|
| **STRATEGY** | "Is this a good setup?" | Spread, liquidity, delta-as-moneyness-filter, premium-as-cost-filter, RiskManager conditions |
| **MQ** | "Is the market tradable?" | Trend/momentum/pullback logic |
| **RISK** | "Are we allowed to risk capital?" | Strategy conditions (already correctly separated — Phase 0 confirms no leakage found) |
| **SIZING** | "How much can we risk?" | Strategy conditions (already correctly separated) |
| **EXECUTION** | "Can this still be executed?" | Strategy conditions (currently HAS leakage — confidence/premium re-checks, §6/§7/§12 RELOCATE candidates) |
| **INSTRUMENT** | "Which contract?" | Strategy conditions (currently HAS leakage — delta/greek re-check at entry_engine's live-only gate, §7) |

**The redesign's main architectural correction, per this audit's evidence, is not in RISK or SIZING (already clean) but in STRATEGY↔MQ↔EXECUTION↔INSTRUMENT boundary bleed** — premium, delta, and spread currently live simultaneously inside the Strategy scoring systems AND their proper MQ/Execution/Instrument homes.

---

## Evidence Gaps (Step 12 of the final output list)

Carried forward from Phase 0 §S, plus new gaps from this session:

1. Whether `session_trend.py`'s independent EMA9/21/50 has ever actually DISAGREED with the strategy's own EMA9/21 in a live session — not measured, would require correlating both values tick-by-tick from logs (not currently logged separately).
2. Whether `calculate_bullish_score()`/`calculate_bearish_score()` (dead-code candidate) are referenced anywhere outside `strategies/`, `tests/`, e.g. in analytics/reporting code that reads the strategy object's methods dynamically — full-repo call-site search not exhaustively performed.
3. All Phase 0 gaps (risk_manager.py gates 9+, kill_switch.py, validators.py internals, execution-guard source function, broker order-failure paths, STRATEGY-layer-only rejection counts from `dvf_signals`) remain unresolved and are not re-verified here.
4. The exact number of live trades where `EXIT_ONLY_SL_TP_TRAILING` was true vs false was not separately isolated in the §13 distance measurement — the −1.9 to −3.2pt figures are pooled across both states from the two available session logs (in practice nearly all of it is from the `false` state, since the flag was only set `true` late on 09-08, but this was not separately filtered).

---

## ARCHITECTURE FREEZE PROPOSAL

```
NO CODE CHANGES PROPOSED IN PHASE 1
```

This document is Inventory → Classification → Architecture Design → Evidence only. Every KEEP/DISABLE CANDIDATE/RELOCATE/REVIEW marking above is a classification for future discussion, not an instruction executed in this session. No file under `core/`, `strategies/`, `config/`, or `.env` was modified while producing this report.

