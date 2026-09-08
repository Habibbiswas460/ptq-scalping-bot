# PTQ SCALPING BOT — PHASE 2: STRATEGY ARCHITECTURE SPECIFICATION
### Simplify → Separate → Define → Freeze. NO CODE CHANGES.
### Synthesizes Phase 0 (`strategy_forensics_20260908.md`) + Phase 1 (`strategy_architecture_phase1_20260908.md`). New evidence this pass marked NEW.

---

## A. EXECUTIVE CONCLUSION (max 10 bullets)

1. The live system has exactly **one genuine, firing entry strategy: Pullback.** Momentum is a nested scoring factor inside it, not independent. Breakout and Reversal do not exist as entry triggers.
2. Three cumulative scoring systems (setup score → weighted score → adaptive confidence) sequentially re-test overlapping information; none is individually dead, but together they let 14 of 18 pre-risk gates each independently kill the identical Pullback setup.
3. Instrument/execution suitability (premium, delta, spread) is scored *inside* Strategy at the same time it is separately checked in MQ/Entry/Instrument — a boundary bleed, not a redundant duplicate of the same layer.
4. Two dead conditions inflate architectural complexity for zero behavioural benefit: `Squeeze_Breakout!` (unreachable, `Was_Squeeze` hardcoded False) and `Supertrend` (computed, never read).
5. Trend is computed **three independent times** (setup-score EMA, weighted-score EMA — same source — plus `session_trend.py`'s own separately-maintained EMA9/21/50) and could theoretically disagree with itself.
6. **Cooldown is not one mechanism — it is two, in different layers** (NEW, §I): a pure time-based post-trade pacer in the state machine, and a per-direction 2-loss/30-minute lock that is *read from inside the Strategy layer* as part of the exhaustion check — genuinely distinct from RiskManager's own separate overall-streak gate.
7. RiskManager (9 gates) and PositionSizeEngine are confirmed clean and require no boundary correction — this was true in Phase 0/1 and is unchanged.
8. Candle/price-action evidence is minimal: direction only (green/red) and EMA-proximity via high/low. No body-size, wick-size, or structural high/low-break logic exists anywhere, live or dead.
9. Exit boundary is **already** SL/TP/trailing-only in the currently deployed `.env` (`EXIT_ONLY_SL_TP_TRAILING=true`, set earlier this session) — this document treats that as the frozen baseline and proposes no exit change.
10. The minimum number of independent decisions to express the CURRENT genuine strategy (§N) is smaller than the current architecture's gate count by roughly a factor of 3 — not because behaviour needs removing, but because the same behaviour is currently asked three times.

---

## B. CURRENT STRATEGY ARCHITECTURE (real pipeline, unchanged from Phase 0/1, restated as fixed reference)

```
tick → warm-up → premium(hard) → delta(hard) → OI(compute) → Market Quality(hard)
     → chop(hard, AND-of-3) → setup score(hard, ≥4) → weighted score(hard, ≥threshold%)
     → exhaustion(hard, incl. direction-cooldown read — NEW, see §I) → adaptive confidence(hard, MQ-adjusted)
     → [generate_signal() returns True] →
     entry_engine: cross-direction tick → confidence RE-CHECK(hard) → range filter(off, default)
     → premium RE-CHECK(hard) → spread(hard) → session trend gate(hard, 2nd independent EMA system)
     → [live only] time + greek RE-CHECK(hard)
     → ENTRY_READY → RiskManager (9 gates) → PositionSizeEngine → broker strike search → fill
```
Evidence: Phase 0 §B/H, Phase 1 §2 — both independently traced to identical line numbers.

---

## C. STRATEGY FAMILY MAP

| Family | Exists? | Independent entry? | Creating code | Required conditions | Confirmation-only conditions | What prevents it firing | Retain? |
|---|---|---|---|---|---|---|---|
| **Pullback** | YES | YES — the only one that ever fires | `smart_scalp_v3.py:1047-1163` ("PULLBACK LOGIC FOR CE/PE" — code's own section name) | EMA9 vs EMA21 (trend precondition) + EMA9-proximity (the trigger) | Candle direction, RSI band, VWAP, volume spike, OI | Premium/delta/MQ/chop hard gates upstream; setup+weighted score thresholds; exhaustion; confidence | KEEP as the base strategy |
| **Momentum** | PARTIALLY — sub-factor only | **NO** — cannot fire without Pullback's EMA9-proximity trigger | RSI band, MACD direction/slope, volume spike, all nested inside Pullback's scoring | N/A as standalone | N/A as standalone | Has no independent trigger path at all — architecturally incapable of firing alone | Extraction = **NEW STRATEGY DESIGN**, not simplification (§5) |
| **Breakout** | `NOT CURRENTLY IMPLEMENTED` | NO | `Squeeze_Breakout!` factor exists but is dead | `was_squeeze and not squeeze and macd_hist` direction | — | `Was_Squeeze` hardcoded `False` at `smart_scalp_v3.py:562`, never updated — **independently re-verified this session** (re-grepped, confirmed unchanged) | Out of scope per hard rules |
| **Reversal** | `NOT CURRENTLY IMPLEMENTED` | NO | None found | — | — | No entry-generating reversal code exists; only exit-side (`rsi_reversal_exit`) and suppression-side (exhaustion) reversal-*shaped* logic, neither of which opens a trade | Out of scope per hard rules |
| **Trend continuation** | NO distinct strategy | NO — trend is a precondition of Pullback, not a standalone trigger | EMA9 vs EMA21 alone never fires a signal without the proximity condition | — | — | Fully subsumed by Pullback | N/A — not a separate family |

---

## D. PULLBACK FORENSICS

```
PULLBACK

Market Structure (REQUIRED — without this the setup cannot logically exist):
    EMA9 vs EMA21 directional relationship
    CE: ema9 > ema21   |   PE: ema9 < ema21
    Evidence: smart_scalp_v3.py:1056 (CE) / 1117 (PE)

Trigger (REQUIRED — this IS the Pullback event):
    Price returns to within 0.5% of EMA9, OR low/high straddles EMA9-to-close
    CE: ema9_proximity < 0.5% or (low <= ema9 <= close)
    PE: ema9_proximity < 0.5% or (close <= ema9 <= high)
    Evidence: smart_scalp_v3.py:1060-1064 (CE) / 1121-1125 (PE)

Confirmation (CONFIRMS but is not the trigger):
    Candle direction (green/red vs prev_close)          — smart_scalp_v3.py:1067-1073/1128-1134
    Close vs EMA9 position                               — same lines, bonus point
    RSI band (45-70 CE / 30-50 PE, ±bonus outside)        — smart_scalp_v3.py:1076-1081/1136-1141
    VWAP side                                             — 1088-1090/1148-1150
    Volume spike + directional candle                    — 1093-1095/~1153
    OI direction match                                    — 1098-1100/~1158

Redundant (repeats information already represented by an earlier condition,
same pipeline, before RiskManager — see Phase 1 §6.A/B for full cross-reference):
    "ema_trend" in Weighted Score — re-scores the SAME EMA9/EMA21 comparison
        already required above, using the same computed values (weighted_score_engine.py:54-57)
    "rsi" in Weighted Score — re-scores the same RSI value already banded in setup score
    "vwap" in Weighted Score — re-scores the same VWAP side already checked in setup score
    session_trend.py's independently-computed EMA9/21/50 — a SEPARATE (not merely
        re-read) trend computation reached later in the pipeline (entry_engine's
        session trend gate), which could in principle disagree with the EMA above

Non-strategy (currently mixed into Pullback's evaluation chain but belongs to
MQ / Instrument / Execution / Risk per the target boundary, §F):
    Premium band check (check_premium_filter) — belongs to Instrument
    Delta band check (0.25-0.75 hard gate)     — belongs to Instrument
    "premium_quality" in Weighted Score        — belongs to Instrument
    "delta"/"greeks" in Weighted Score          — belongs to Instrument
    "spread_quality" in Weighted Score          — belongs to MQ/Execution
    "atr_volatility" in Weighted Score          — arguably MQ (tradable-volatility check), not a directional behaviour
    Market Quality hard gate (currently interleaved BEFORE scoring, not after)
    Exhaustion check's direction-cooldown read (is_direction_blocked) — a
        Strategy-layer read of a Risk-shaped, streak-based state (see §I)

MQ:
    separate (MarketQualityEngine — Phase 0 §G)

Entry:
    separate (RiskManager, PositionSizeEngine, broker instrument selection — untouched, Phase 0 §J/§I)
```

---

## E. SCORING FORENSICS

| System | Inputs consumed | Duplicate with another layer | Genuine market behaviour | Instrument/Execution/MQ concern | Independently rejects trades? | Should eventually disappear from Strategy? |
|---|---|---|---|---|---|---|
| **Setup score** (inline, 0-11/12, `min_score≥4`) | EMA9/21, EMA9-proximity, candle, RSI, VWAP, volume, OI | EMA/RSI/VWAP re-scored by Weighted Score | YES — this is the closest thing to the real behaviour-detector | None directly (premium/delta are separate hard gates upstream, not part of this score) | YES — first gate | **NO — this is closest to the target's PASS/FAIL trigger; it is the candidate to KEEP and simplify from, not remove** |
| **Weighted score** (`WeightedScoreEngine`, 0-100%) | ema_trend, vwap, volume, delta, oi, rsi, macd, atr_volatility, premium_quality, greeks, market_regime, spread_quality | Re-scores 5 of setup score's factors (ema/rsi/vwap/volume/oi) using different weights | Partially — macd is new information, the rest is repeated | YES — delta, premium_quality, greeks, spread_quality, atr_volatility (5 of 12 factors, 30 of 105 weight) are instrument/MQ concerns, not behaviour | YES — second, independent gate on largely the same information | **YES — conceptually should disappear as a second scoring gate; its genuinely new information (MACD) could fold into setup score's confirmation list, and its instrument/MQ factors belong in §F, not here** |
| **Adaptive confidence** (`AdaptiveConfidenceEngine`, multiplicative 0-100) | score_pct, regime, an internally-recomputed "market_quality_score" (DIFFERENT from MarketQualityEngine's, same name — Phase 0 §F naming collision), session, spread/volume/greeks/oi/vwap/freshness (as "execution_quality") | Regime re-duplicates trend a 3rd time; spread/greeks/oi/vwap re-duplicate weighted score's own factors a 3rd time | Marginal — mostly a re-weighting of already-scored information | YES — spread, greeks, oi, vwap are execution/instrument concerns folded into a "confidence" multiplier | YES — third, independent gate | **YES — conceptually should collapse into a single post-Strategy confirmation step, not a third cumulative multiplier chain** |

**Conceptual replacement (Step 8, not implemented):**
```
Strategy Trigger  (EMA9/21 trend + EMA9-proximity — the two REQUIRED conditions in §D)
      ↓
Simple Confirmation  (candle direction + RSI band + volume/OI participation —
                       the CONFIRMATION conditions in §D, evaluated as present/absent,
                       not summed into a number)
      ↓
PASS / FAIL
```
No numeric threshold is proposed. The three current scoring systems collapse conceptually into one behavioural PASS/FAIL gate, with every instrument/MQ/execution factor they currently also carry relocated to its own layer (§F, §K).

---

## F. MQ BOUNDARY

**MQ must answer only:** *"Is the market currently tradable right now?"* (spread, liquidity, freshness, tradable-volatility band, execution health, session window — `MarketQualityEngine`, Phase 0 §G).

**Currently duplicated or embedded elsewhere — classified:**

| Where MQ-shaped information appears | Classification | Reason |
|---|---|---|
| `MarketQualityEngine.evaluate()` hard gate (`smart_scalp_v3.py:971-1005`) | **KEEP** | This IS the correct, dedicated MQ layer |
| MQ grade feeding `_required_confidence()` (`smart_scalp_v3.py:1301/1328`) | **RELOCATE conceptually** — legitimate that confidence should know market quality, but currently this couples MQ's grade directly into a Strategy-layer threshold adjustment rather than MQ being a clean post-Strategy checkpoint per the target pipeline (§G/§L) | Phase 0 §G, this session |
| MQ score feeding `PositionSizeEngine`'s own separate `market_quality_multiplier` (`position_size_engine.py:303-308`) | **KEEP, but REVIEW naming** — legitimate use in Sizing, correctly a different layer, not a duplicate decision | Phase 0 §G |
| `AdaptiveConfidenceEngine`'s internally-recomputed `market_quality_score` (squeeze+vol_ratio based, `adaptive_confidence_engine.py:55`) | **REDUNDANT / naming collision** — a differently-computed number sharing MQ's name, not the same value | Phase 0 §F (naming collision), re-confirmed |
| `spread_quality` in Weighted Score | **RELOCATE to MQ** | Spread is already MQ's job (weight 25/100 there) |
| `spread` check in `entry_engine.py` (`KILL_SWITCH_SPREAD`) | **RELOCATE to MQ/Execution, consolidate with the above** | 3rd independent spread check |
| `atr_volatility` in Weighted Score | **RELOCATE to MQ** | MQ already has its own `volatility_points` (ATR/VIX band) — same concern, currently scored twice in 2 different layers |

---

## G. ENTRY PIPELINE

```
Market Data
    ↓  input: tick stream    output: OHLCV+greeks buffer    decision: none    owner: runtime_state
Indicators / Price Structure
    ↓  input: tick buffer    output: EMA/RSI/MACD/VWAP/ATR/Squeeze/Supertrend    decision: none    owner: calculate_indicators()
Strategy Detection
    ↓  input: indicators     output: ce_signal/pe_signal (Pullback trigger)      decision: PASS/FAIL    owner: smart_scalp_v3.py inline scoring
Strategy Confirmation
    ↓  input: signal+score   output: confidence-gated direction                 decision: PASS/FAIL    owner: AdaptiveConfidenceEngine (currently)
MQ
    ↓  input: tick+broker status  output: passed/grade                         decision: PASS/FAIL    owner: MarketQualityEngine
Entry Validation
    ↓  input: execution_tick  output: drift/spread/session-trend checked        decision: PASS/FAIL    owner: entry_engine.py (post-signal gates)
Risk Permission
    ↓  input: account state   output: can_trade + size_multiplier               decision: PASS/FAIL    owner: RiskManager.can_trade()
Sizing
    ↓  input: risk budget+signal quality  output: lot count                     decision: qty or 0      owner: PositionSizeEngine
Instrument Selection
    ↓  input: direction+premium band  output: specific strike/symbol            decision: which contract  owner: broker.py strike search
Execution
    ↓  input: strike+qty      output: order request                             decision: fill/no-fill    owner: broker.py order placement
Order
    ↓                                                                                                    owner: broker (paper/live)
```

**Rejection attribution — explicit, per the hard rule that a RiskManager block must never be counted as a bad strategy signal (already empirically demonstrated in Phase 0 §N: 2026-09-07's 284 non-fills were 58.1% RISK + 34.2% SIZING, 0% genuine strategy quality issue):**

| If rejected at... | Classification | NOT to be confused with |
|---|---|---|
| Premium/delta/MQ/chop/setup-score/weighted-score/exhaustion/confidence (inside `generate_signal()`) | **STRATEGY REJECTION** (with the caveat that premium/delta/spread/ATR sub-factors inside these gates are actually MQ/Instrument concerns misclassified as Strategy — §D/§F) | MQ rejection, if the MQ hard-gate specifically fired (line 999) |
| `MarketQualityEngine.evaluate().passed == False` | **MQ REJECTION** | Strategy quality — the setup itself was never even scored |
| Cross-direction tick / confidence-recheck / premium-recheck / spread / session-trend / [live] time+greek (`entry_engine.py`) | **EXECUTION REJECTION** (with caveat: confidence/premium re-checks are largely re-testing STRATEGY-layer information, §Phase0 §F/O) | Instrument rejection, if it's specifically a "no strike found" case |
| `RiskManager.can_trade()` returns False | **RISK REJECTION** | Strategy quality — the setup already passed |
| `PositionSizeEngine` returns `position_size=0` | **SIZING REJECTION** | Risk rejection — risk gates already passed; this is purely a budget-vs-lot-size arithmetic outcome |
| Broker strike search finds no strike in `STRIKE_PREMIUM_MIN/MAX`, falls back to ATM | **INSTRUMENT** (degraded, not rejected — fills anyway on ATM) | — |

---

## H. RISK vs STRATEGY SEPARATION — Explicit Examples

| Example | Correctly separated today? | Evidence |
|---|---|---|
| Drawdown, weekly loss, VIX, gap, equity-curve, time-sizing, profit-lock (RiskManager's 7 of 9 gates) | **YES — clean** | `risk_manager.py:486-560`, no strategy-conditions found inside `can_trade()` |
| Overall consecutive-loss streak (`RiskManager.check_streak_limits()`) | **YES — clean, lives entirely in RiskManager** | `risk_manager.py:381-409` |
| Per-direction consecutive-loss lock (`TradingState.is_direction_blocked()`) | **NO — genuine boundary blur (NEW finding, §I)** | Lives in `state_machine.py` (a state-machine/execution-layer object) but is READ FROM INSIDE `smart_scalp_v3.py`'s `generate_signal()` (the Strategy layer) to compute `ce_exhausted`/`pe_exhausted` — a Risk-shaped (streak) concept gating a Strategy-layer decision directly, distinct from and in addition to RiskManager's own separate overall streak gate |
| Position sizing (`PositionSizeEngine`) | **YES — clean, entirely separate from Strategy** | Phase 0 §J confirmed no strategy-condition leakage |

---

## I. COOLDOWN CLASSIFICATION (NEW — investigated fresh this session)

**Two distinct cooldown mechanisms exist, in two different places, doing two different jobs:**

### 1. Post-trade state-machine COOLDOWN (pure pacing, EXECUTION/state-machine layer)
- **Lives in:** `core/engines/state_machine.py`, `state_cooldown()` function (line 1162+)
- **Activated by:** any trade closing (`IN_TRADE → COOLDOWN` transition)
- **Released by:** pure elapsed time — `if now() >= state.cooldown_until: return "IDLE"`. Duration set by `get_cooldown_duration()`, itself driven by win/loss/expiry-day config (`COOLDOWN_NORMAL_SEC`, `COOLDOWN_AFTER_SL_SEC`, etc.)
- **Can it suppress an otherwise-valid Pullback signal?** **YES** — while in COOLDOWN, the state machine is not in IDLE, so `entry_signal()` is never even called (Phase 0 §B: entry evaluation only happens from `state_idle()`). A genuinely valid setup occurring during this window is never evaluated at all.
- **Classification:** **EXECUTION / state-machine pacing**, not Strategy, not Risk (it does not reason about capital or setup quality — it is a fixed timer)

### 2. Per-direction SL-streak lock (Strategy-adjacent, Risk-shaped, lives in state_machine but READ by Strategy)
- **Lives in:** `TradingState.is_direction_blocked()`, `core/engines/state_machine.py` (line ~340-372, re-verified this session)
- **Activated by:** 2+ consecutive losses in ONE direction (`consecutive_ce_losses >= 2` / `consecutive_pe_losses >= 2`)
- **Released by:** EITHER 30 minutes elapsed (`DIRECTION_COOLDOWN_MIN=30`, auto-resets counter to 1 and clears the block) OR a winning trade in that direction resetting the counter (confirmed by code comment at line 520, "Only reset the WINNING direction's counter and cooldown" — exact reset-on-win logic not fully re-traced this pass, flagged `INSUFFICIENT EVIDENCE` for the precise win-reset condition)
- **Read from:** `smart_scalp_v3.py`'s `generate_signal()`, feeding directly into `ce_exhausted`/`pe_exhausted` (Phase 1 §1/§3) — **this is a Strategy-layer decision consuming a Risk-shaped (streak) state object that lives in the state machine, not in RiskManager**
- **Classification:** **Boundary-blurred** — conceptually a Risk-style caution mechanism (recent-loss-driven), architecturally embedded as a Strategy-layer input (feeds `ce_exhausted`), and physically housed in the state machine (neither Strategy's own file nor RiskManager's file)

**Target principle applied:** Per the instruction "Cooldown is NOT evidence that the strategy is bad" — **confirmed correct as a principle**: mechanism #1 can suppress a perfectly valid Pullback signal purely by timing, and mechanism #2 can suppress a valid signal purely because of a *different* recent trade's outcome in the same direction, neither of which reflects on the CURRENT setup's quality. Any non-trade attribution work (Phase 0 §N-style funnels) should count both of these as distinct from a genuine STRATEGY REJECTION, and neither should be attributed to Risk either — they need their own bucket ("EXECUTION-PACING REJECTION" / "DIRECTION-STREAK REJECTION") if precise attribution is ever built.

---

## J. EXIT BOUNDARY (architecture only, no modification proposed)

```
ENTRY
  ↓
POSITION
  ↓
Dynamic SL   (hard SL, -HARD_SL_POINTS, ratchets via step-trailing ladder)
Dynamic TP   (fixed TP_POINTS_FIXED, only reachable when trailing is disabled — currently trailing is on)
Trailing     (step-ladder: MFE-triggered locks, e.g. currently 12→entry(breakeven), 16→+11, ... per today's .env)
  ↓
EXIT
```

Treated as position-management / risk-protection, per instruction — **not re-evaluated or modified.**

Historical/current-code-only mechanisms (present in the codebase, currently suppressed by `EXIT_ONLY_SL_TP_TRAILING=true` per this session's own earlier change, documented not modified):
- Early loss cut, soft loss exit, greek exit, smart RSI exit, RSI reversal exit — all flag-gated off in the CURRENT `.env`; all fully live code when the flag is false (as it was for 27 of 28 trades across 09-07/09-08, per Phase 1 §13's log-verified distance measurements)
- Time exit (15min) / mandatory market-close exit — **NOT suppressed by the flag**, always active

**"Ceiling/floor" = the TP/SL boundary/gap** (user's terminology, applied consistently here) — **not** interpreted as a separate exit indicator, and **not** confused with the code's own unrelated `profit_floor_exit()` function name (Phase 1 §13 flags this naming collision explicitly).

---

## K. KEEP / DISABLE / REMOVE / RELOCATE / REVIEW — FINAL TABLE

| Component | Current role | Target role | Action (future, NOT executed) | Reason | Evidence |
|---|---|---|---|---|---|
| EMA9 vs EMA21 (trend precondition) | Strategy required-condition | Strategy required-condition | **KEEP** | Core, minimal, correctly the base of Pullback | `smart_scalp_v3.py:1056/1117` |
| EMA9-proximity (pullback trigger) | Strategy trigger | Strategy trigger | **KEEP** | This IS the strategy | `smart_scalp_v3.py:1060-1064/1121-1125` |
| Candle direction, RSI band, VWAP, volume spike, OI (setup-score confirmation) | Strategy confirmation | Strategy confirmation | **KEEP** (as presence/absence checks, not summed points — §E) | Genuine behaviour evidence | `smart_scalp_v3.py:1067-1100` |
| `Squeeze_Breakout!` | Dead scoring factor | N/A | **NOT IMPLEMENTED** (fix-or-retire is a future decision, out of scope) | `Was_Squeeze` hardcoded False, re-verified | `smart_scalp_v3.py:562,725-728` |
| `Supertrend` | Dead computation | N/A | **REMOVE candidate** (computed, unread) | No call site found for `indicators['Supertrend']` outside its own assignment | `smart_scalp_v3.py:545-554` |
| `calculate_bullish_score()`/`calculate_bearish_score()` methods | Unreachable duplicate of inline scoring | N/A | **REVIEW** | No call site found in `generate_signal()`; not exhaustively searched repo-wide | Phase 0 §R |
| **Weighted Score Engine** (as a 2nd full scoring gate) | Re-scores 5/12 factors already in setup score; carries 5/12 instrument/MQ factors | Its genuine new info (MACD) folds into Strategy confirmation; its instrument/MQ factors relocate | **MERGE/RELOCATE** (conceptual — not executed) | §E | `weighted_score_engine.py` |
| **Adaptive Confidence Engine** (as a 3rd full scoring gate) | Re-weights info already scored twice; carries its own differently-computed "MQ" | Collapses into a single post-Strategy confirmation step | **MERGE/RELOCATE** (conceptual) | §E | `adaptive_confidence_engine.py` |
| Premium/delta/spread/ATR as Weighted-Score or Confidence factors | Mixed into Strategy scoring | MQ/Instrument | **RELOCATE** | §F | Phase 1 §5/§7 |
| MarketQualityEngine hard gate | Correctly placed, but interleaved mid-scoring-chain | Runs cleanly AFTER Strategy confirmation | **RELOCATE (point of application only, not the engine itself)** | §F, §L | `smart_scalp_v3.py:971-1005` |
| External confidence re-check (flat 70%) | Redundant for MQ grades B/C, neutralizes A/A+ relaxation | — | **DISABLE CANDIDATE** (flat-70% portion only) | Phase 0 §F | `entry_engine.py:202-208` |
| External confidence re-check (85% after 3-loss streak) | Sole source of this escalation | KEEP this specific behaviour, relocate its housing | **KEEP (logic), RELOCATE (housing, since it's actually Risk-shaped)** | Phase 0 §F | same lines |
| External premium re-check | Same constants as internal check | — | **DISABLE CANDIDATE** | Phase 0 §O | `entry_engine.py:246-252` |
| Spread check (`entry_engine.py`) | 3rd independent spread check | MQ/Execution | **RELOCATE, consolidate with MQ's own spread_points and Weighted Score's spread_quality** | §F | `entry_engine.py:259-265` |
| Session trend gate (`session_trend.py`) | Independently-computed 2nd/3rd trend read | — | **REVIEW** (may be intentional double-confirmation, not proven redundant) | Phase 1 §6.B | `session_trend.py` |
| Live-only time+greek gate | 5th touch of delta/greeks | Instrument | **RELOCATE** | Phase 1 §7 | `entry_engine.py:302-314` |
| Per-direction SL-streak lock (`is_direction_blocked`) | Strategy-layer read of a Risk-shaped state, housed in state machine | Needs a decided home (Risk, or a formally-acknowledged Strategy-adjacent input) | **REVIEW** (NEW, §I) | §I | `state_machine.py:340-372`, read at `smart_scalp_v3.py:~1258` |
| Post-trade COOLDOWN state | Pure pacing timer | Execution/state-machine | **KEEP, correctly classified as non-Strategy** | §I | `state_machine.py:1162+` |
| RiskManager (9 gates) | Clean | Clean | **KEEP, unchanged** | Phase 0 §J, re-confirmed | `risk_manager.py:486-560` |
| PositionSizeEngine | Clean | Clean | **KEEP, unchanged** | Phase 0 | `position_size_engine.py` |
| Broker strike search | Clean, separate premium band from entry filter | Clean | **KEEP, unchanged** (REVIEW the two-different-premium-bands point) | Phase 0 §I | `broker.py:545-590` |
| Exit Engine (all mechanisms) | Currently SL/TP/trailing-only, flag-gated | Unchanged | **KEEP, unchanged — out of scope** | §J | `exit_engine.py` |

---

## L. TARGET SIMPLIFIED ARCHITECTURE

```
                    MARKET DATA
                         ↓
               INDICATORS / PRICE
                         ↓
                  MARKET STRUCTURE
                         ↓
              ┌────────────────────┐
              │   STRATEGY LAYER   │
              │                    │
              │ Pullback           │   <- exists, active, the only real one
              │ Momentum*          │   <- nested sub-factor only, NOT independently implemented
              │ Breakout*          │   <- dead code only, NOT IMPLEMENTED
              │ Reversal*          │   <- NOT IMPLEMENTED
              └────────────────────┘
                         ↓
                SIMPLE CONFIRMATION      (replaces 3 stacked scoring systems, §E)
                         ↓
                         MQ                (MarketQualityEngine, run cleanly after Strategy)
                         ↓
                    ENTRY READY            (execution validation: drift, spread-consolidated,
                                             session-trend REVIEW — §K)
                         ↓
                    RISK CHECK             (RiskManager, unchanged)
                         ↓
                      SIZING               (PositionSizeEngine, unchanged)
                         ↓
                   INSTRUMENT              (broker strike search, unchanged)
                         ↓
                    EXECUTION              (order placement, unchanged)
                         ↓
                      ORDER
                         ↓
                     POSITION
                         ↓
               DYNAMIC SL / TP / TRAIL     (unchanged, out of scope — §J)
```
`*` = NOT CURRENTLY IMPLEMENTED, per instruction.

---

## M. OVERFITTING ARCHITECTURE ANALYSIS

Not "there are too many conditions" — the specific structural mechanisms that create overfitting risk, each with its own evidence:

1. **Multiple correlated indicators scored as if independent.** EMA9/21, `ema_trend`, `regime`, and `session_trend.py`'s own EMA are 4 readings of essentially the same directional fact, each contributing separately to a threshold (setup score requires it; weighted score weights it at 20/105, the single largest factor; confidence weights it via `regime_multiplier`; session-trend gates it a 4th time). A model that scores the same underlying fact four times and requires all four to clear a bar is not four confirmations — it is one fact with a quadrupled veto.

2. **Duplicate gates on identical thresholds.** Premium and confidence are each checked twice using the *same* constant (Phase 0 §O). This does not add information; it adds a second dice-roll against the same coin flip, which in backtesting looks like "extra confirmation" but in live trading is just "extra chances to reject on tick-to-tick noise between the two check points" (the cross-direction-tick difference means the two checks can even see *different* values for the same nominal quantity).

3. **Multiple scoring systems compound rather than diversify.** Setup score, weighted score, and confidence each independently threshold overlapping inputs (§E). Statistically, three sequential AND-gates on correlated evidence produce a MUCH lower effective pass rate than any single one calibrated correctly — this is architecturally equivalent to tightening one threshold three times without ever being able to see that it happened, since each gate's threshold was presumably tuned assuming the others weren't also filtering the same information.

4. **Instrument/execution quality mixed into strategy scoring inflates the appearance of "market behaviour agreement."** When premium, delta, spread, and ATR-band are folded into the SAME weighted sum as trend/momentum/participation factors, a trade that looks "well-confirmed" by a high score may actually be well-confirmed on cost/liquidity grounds while being marginal on actual behavioural grounds, or vice versa — the number cannot be decomposed after the fact into "good setup" vs "good execution conditions," which is exactly the ambiguity the target architecture's philosophy (§ Primary Objective) explicitly rejects.

5. **Dead logic increases the SURFACE AREA of the system without any corresponding behavioural coverage.** `Squeeze_Breakout!` and `Supertrend` add code paths, config-adjacent complexity, and reader cognitive load, while contributing zero decisions. This is not overfitting in the statistical sense, but it directly works against the target's "simple, understandable, easy to observe from logs" goals — a log reader or a future maintainer has to first discover these are dead before they can be excluded from reasoning about why a trade did or didn't happen.

6. **A Strategy-layer decision (exhaustion) consumes a Risk-shaped state object housed in a third layer (state machine)** — §I's finding. This means "why didn't this signal fire" can require inspecting Risk-adjacent state even when the question is purely about Strategy, working against the target's explicit goal of unambiguous rejection attribution (§ Final Principle).

### Minimum number of independent decisions required to express the CURRENT genuine strategy

Based strictly on what currently exists and fires (Pullback only, §C):

```
1. Trend precondition       (EMA9 vs EMA21)               — currently computed 3-4x, needed 1x
2. Pullback trigger          (EMA9-proximity)               — currently computed 1x, correct
3. Behavioural confirmation  (candle + RSI + participation) — currently scored across 3 systems, needed as 1 PASS/FAIL check
4. Market tradability        (MQ)                           — currently 1 real engine + 2 shadow re-derivations (Weighted Score's spread/ATR factors, Confidence's own "MQ" number) — needed 1x
5. Execution validity        (drift/spread at fill time)     — currently checked 2-3x with overlapping thresholds — needed 1x
```
**Five independent decisions** express the entirety of what the current system actually does when it fires a trade. The present architecture asks something closer to 14-18 sequential questions (Phase 0 §H) to arrive at the same five answers. This number is descriptive of current evidence, not a numerically-optimized target — no thresholds are proposed.

---

## N. MINIMUM VIABLE STRATEGY ARCHITECTURE

The simplest architecture supported by EXISTING evidence (no new indicators, no new thresholds, only reorganizing what already exists and fires):

```
Strategy = PASS if:
    Trend precondition holds (EMA9 vs EMA21, one computation)
    AND Pullback trigger fires (EMA9-proximity, as currently defined)
    AND at least the behavioural confirmations currently required to
        reach setup-score's own min_score threshold are present
        (candle direction, RSI band, participation — using EXISTING
        per-factor logic, not new logic)

Strategy = FAIL otherwise, with the specific failing condition(s) logged directly
    (not as "score 3/4" but as "trend: yes, trigger: yes, RSI-band: no")
```
This is a direct behavioural restatement of the EXISTING setup score's required + confirmation conditions (§D), with the currently-nested Weighted Score and Adaptive Confidence gates' genuinely-novel information (MACD; the specific multiplicative regime/session weighting) treated as future-design questions rather than assumed necessary — because Phase 0/1 found no evidence that they detect anything the setup score's own conditions do not already detect, only that they re-weight it differently.

---

## O. EVIDENCE GAPS

Carried forward from Phase 0 §S and Phase 1 §Evidence-Gaps, plus new gaps from this session:

1. `risk_manager.py` gates 9+ (past `check_profit_lock()`), `kill_switch.py`, and `validators.py` internals — not read this session or prior sessions in full.
2. Exact win-reset condition for the per-direction SL-streak lock (§I) — code comment references it ("Only reset the WINNING direction's counter and cooldown") but the precise triggering logic was not traced line-by-line this pass. `INSUFFICIENT EVIDENCE` for the exact mechanism.
3. Whether `session_trend.py`'s independent EMA has ever measurably disagreed with the strategy's own EMA in a live session — not measured (Phase 1 gap, still open).
4. Whether `calculate_bullish_score()`/`calculate_bearish_score()` are referenced anywhere outside `strategies/`/`tests/` — not exhaustively searched repo-wide.
5. Execution-guard's exact source function (the 0.35% drift check) — confirmed to exist and fire via log evidence only; producing code not read this session or Phase 0.
6. STRATEGY-layer-only rejection counts (chop/score/MQ failures before `ENTRY_READY`) are not present in `events.json`; would require querying `dvf_signals`/`trades.json` signal snapshots, not done in any phase so far.
7. Whether the two premium checks (`check_premium_filter()` internal vs `entry_engine.py` external) ever actually observe DIFFERENT tick values in practice, given the cross-direction-tick-correction logic — not measured from logs.

---

## P. IMPLEMENTATION BOUNDARY

```
NO CODE CHANGES WERE MADE.
```

No file under `core/`, `strategies/`, `config/`, or `.env` was modified while producing this specification. All KEEP/DISABLE/REMOVE/RELOCATE/REVIEW/NOT-IMPLEMENTED markings in §K are classifications for future discussion and decision, not instructions executed in this session.

**Future implementation sequence (conceptual order only — not implemented, not scheduled, not started):**
```
1. Strategy separation      — extract the 5-decision minimum (§N) as its own explicit path,
                               distinguishing required/confirmation/non-strategy per §D
2. Scoring removal/replacement — collapse the 3 scoring systems into 1 PASS/FAIL confirmation,
                               per §E's conceptual replacement, no numeric threshold decided here
3. MQ separation            — consolidate the currently-triplicated spread/ATR checks and the
                               MQ-grade-vs-confidence coupling into one clean post-Strategy MQ gate, §F
4. Entry simplification      — remove the confirmed-redundant re-checks (confidence flat-70%,
                               premium) while relocating their genuinely distinct logic
                               (85%-streak escalation, drift guard) per §K
5. Logging/observability     — make the STRATEGY / MQ / RISK / SIZING / EXECUTION / INSTRUMENT
                               rejection categories from §G directly loggable per-signal, closing
                               evidence gap §O.6
6. Validation                — replay against the historical funnel data (Phase 0 §N) to confirm
                               the simplified architecture reproduces the same trade set the
                               current one produces on identical input, before any live change
```

