# PTQ SCALPING BOT — STRATEGY ARCHITECTURE REBUILD
## PHASE A: FORENSIC REPORT + PHASE B: DESIGN REVIEW / STOP
### No production code modified. Every fact below re-verified against the current working tree (git diff shows only Phase 3-6's prior, already-reported changes) — not copied from earlier reports without a fresh check.

---

## A1. STRATEGY INVENTORY

**Headline fact, re-verified this pass**: `strategies/` contains exactly one file besides
`__init__.py` — `smart_scalp_v3.py`, 1711 lines. `find strategies -name "*.py"` returns
nothing else. There is no second strategy implementation anywhere in the repository — the
"multiple strategies" the target architecture wants do not exist today, in any form, dead or
alive, beyond scoring sub-factors nested inside the one strategy (re-confirmed, matching
Phase 1/2's finding).

`strategies/__init__.py` re-exports exactly three names — `SmartScalpV3`, `get_strategy`,
`smart_scalp_signal` — as the package's public API. **Any new module structure must either
preserve these three names at `strategies/__init__.py`, or update every one of the 9 files
below that import from `strategies`.**

| Component | File | Function/Class | Purpose | Consumers | Classification |
|---|---|---|---|---|---|
| `SmartScalpV3` | `strategies/smart_scalp_v3.py:82` | class | The entire strategy — indicator calc, scoring, confidence, entry-param derivation | `get_strategy()` singleton, tests, `core/backtest.py` | STRATEGY-SPECIFIC (monolithic) |
| `__init__` | `:102-167` | method | Loads config, builds `WeightedScoreEngine`/`AdaptiveConfidenceEngine`/`MarketQualityEngine` instances, sets thresholds | called once per instance | SHARED MARKET CONTEXT (config wiring) + STRATEGY-SPECIFIC (thresholds) |
| `calculate_weighted_score` | `:180-183` | method | Thin delegate to `WeightedScoreEngine.score()` | `generate_signal()` | STRATEGY DECISION (feeds gate) + SIZING (feeds `sizing_inputs`) |
| `calculate_adaptive_confidence` | `:186-189` | method | Thin delegate to `AdaptiveConfidenceEngine.score()` | `generate_signal()` | STRATEGY DECISION (feeds gate) + SIZING |
| `get_option_delta` | `:212-254` | method | BSM delta via `GreeksCalculator`, cached | `generate_signal()`'s delta hard-gate | MARKET GATE-ish (instrument suitability, not market condition) |
| `update_oi_data` | `:256-320` | method | OI-buildup/unwind direction classification | `generate_signal()` (gates + scores) | STRATEGY-SPECIFIC confirmation input |
| `check_premium_filter` | `:322-378` | method | Premium-band hard gate + feed-anomaly detection | `generate_signal()` | MARKET GATE-ish (instrument tradability, not strategy behaviour) — **candidate MOVE** |
| `_required_confidence` | `:380-391` | method | MQ-grade-adjusts the confidence threshold | `generate_signal()` (×2, CE/PE) | STRATEGY DECISION (threshold policy) |
| `calculate_indicators` | `:414-663` | method | EMA/RSI/MACD/VWAP/ATR/BB/KC/Squeeze/Supertrend/Volume from tick buffer | `generate_signal()`, `evaluate_pullback_strategy()` | MARKET CONTEXT (candle structure, trend, volatility) |
| `calculate_bullish_score` / `calculate_bearish_score` | `:665-763` / `:765-863` | methods | A **second, unreferenced** implementation of the CE/PE setup score — re-confirmed 0 call sites this pass | none | **LEGACY / DEAD** |
| `get_market_regime` | `:865-879` | method | BULLISH/BEARISH/SIDEWAYS from EMA21 vs EMA50 (a **third** trend computation, alongside setup-score's EMA9/21 and `session_trend.py`'s own EMA9/21/50) | `evaluate_pullback_strategy()` (no — actually not called there; called from `calculate_weighted_score`/`calculate_adaptive_confidence`'s regime-backfill and `generate_signal()`'s `details['regime']`) | MARKET CONTEXT (duplicate computation, not consolidated) |
| `evaluate_pullback_strategy` | `:882-1096` | method | **The extracted Pullback strategy** (Phase 3) — trend precondition, EMA9-proximity trigger (not actually required, see A5), candle/RSI/VWAP/volume/OI confirmation, cumulative setup score, observability record | `generate_signal()` | STRATEGY DECISION — **the one real, isolable Strategy component in the file** |
| `generate_signal` | `:1098-1565` | method | The 467-line orchestrator: warm-up, premium/delta gates, OI calc, indicators, **Market Quality hard gate**, chop filter, calls `evaluate_pullback_strategy()`, weighted-score gate, exhaustion, confidence gate, `strategy_decision`/`sizing_inputs` construction (Phase 4/6), final return | `smart_scalp_signal()` wrapper | Everything at once — MARKET GATE + STRATEGY DECISION + SIZING packaging, undifferentiated |
| `get_entry_params` | `:1567-1613` | method | SL/TP/regime-based adjustment for the accepted direction | `smart_scalp_signal()` wrapper | STRATEGY-SPECIFIC output, arguably EXECUTION-adjacent (feeds order params) |
| `get_strategy` | `:1615-1621` | module function | Singleton accessor | `smart_scalp_signal()`, `entry_engine.py` (not directly — via the wrapper) | SHARED (module wiring) |
| `smart_scalp_signal` | `:1623-1711` | module function | The public API `entry_engine.py` calls: wraps `generate_signal()`, builds `params` dict (`direction`, `score`, `confidence`, `sizing_inputs`, `sl_points`, `tp_points`, `regime`, `factors`, `details`), writes `runtime_state` telemetry | `entry_engine.py:155`, `research/backtest/harness.py:393` | STRATEGY DECISION + SIZING packaging (the public contract boundary) |

**External callers of `SmartScalpV3`/`generate_signal()`/`smart_scalp_signal()`, re-verified
this pass (a wider set than any single prior phase enumerated — combined here for the first
time)**:
```
tests/test_p0_historical_warmup.py    — from strategies.smart_scalp_v3 import SmartScalpV3
tests/test_time_filters.py            — from strategies import smart_scalp_v3
tests/test_smart_scalp_confidence.py  — strategy.generate_signal(ticks) directly
tests/test_snapquote_depth.py         — from strategies.smart_scalp_v3 import SmartScalpV3 (×3 sites)
tests/test_tick_input_repair.py       — from strategies.smart_scalp_v3 import SmartScalpV3
tests/test_entry_engine_cross_direction.py — via entry_engine.entry_signal()
core/backtest.py                      — strategy.generate_signal(ticks_history)
core/engines/entry_engine.py:155      — smart_scalp_signal(recent_ticks)  [THE LIVE PATH]
utils/market_readiness_checker.py:434 — strategy.generate_signal(sampled_ticks)
research/backtest/harness.py:393      — smart_scalp_signal(...)
```
**Nine files outside `strategies/` itself depend on this exact API shape.** Any rebuild that
changes `SmartScalpV3`'s public methods, or `generate_signal()`'s 4-tuple return, or
`smart_scalp_signal()`'s `params` dict shape, breaks some subset of these nine without a
compatibility shim.

---

## A2. SCORE INVENTORY

| Score | Producer | Consumers | Gates? | Sizing? | Analytics? | Keep/Move/Delete |
|---|---|---|---|---|---|---|
| **Setup score** (`ce_score`/`pe_score`, 0-11/12, inline in `evaluate_pullback_strategy()`) | `smart_scalp_v3.py:930-1093` | own gate only (`>= self.min_score`); `details["ce_score"]`/`pe_score"]` written but re-confirmed (fresh grep, zero hits outside `smart_scalp_v3.py`) read by nothing else | **YES** — the only real Strategy gate | **NO** | Effectively no (write-only key) | **KEEP** — this is the Strategy decision's actual substance |
| **`calculate_bullish_score`/`calculate_bearish_score`** (a duplicate 0-? point setup score) | `:665-863` | **NONE** — re-confirmed 0 call sites | No (unreachable) | No | No | **DELETE candidate** — see A5 for the deletion-safety proof |
| **Weighted score** (`ce_weighted_pct`/`pe_weighted_pct`, `WeightedScoreEngine`, 0-100%) | `weighted_score_engine.py:31-130`, called at `smart_scalp_v3.py:1319/1354` | (1) own gate (`< self.min_weighted_score_pct`) (2) `details["weighted_score"]`/`"bull_score"`/`"bear_score"` → DB/analytics (`core/services/database.py`, `research/*`) (3) `details["sizing_inputs"]["weighted_score"]` (Phase 6) → **live sizing**, `state_machine.py:846`, `core/backtest.py:299` | **YES, dual role** | **YES** — proven byte-for-byte in Phase 6 | **YES** — `dvf_signals` DB, `research/prefilters.py` reads `weighted_score IS NULL` as "rejected before scoring" | **KEEP the number; the GATE role is the thing Rule 8 says needs explicit justification, not automatic removal** |
| **Adaptive confidence** (`confidence`, `AdaptiveConfidenceEngine`, multiplicative 0-100) | `adaptive_confidence_engine.py:27-118`, called at `smart_scalp_v3.py:1483/1531` (approx, post-Phase-6 line shift) | (1) own gate (`< required_conf`, MQ-adjusted) (2) **external** gate in `entry_engine.py:202-208` (flat `MIN_CONFIDENCE`/`MIN_CONFIDENCE_AFTER_3SL`, a SEPARATE threshold — Phase 0 §F redundancy finding, re-confirmed structurally unchanged) (3) `details["sizing_inputs"]["confidence"]` → **live sizing** | **YES, dual role, TWICE (internal + external)** | **YES** | **YES** | **KEEP the number; two gates on it, one of which (external) is the sole source of the 3-loss-streak 85% escalation — cannot be collapsed without losing that** |
| **Market Quality score** (`quality_score`, `MarketQualityEngine`, 0-100, weighted 7-component) | `market_quality_engine.py:34-148`, called `smart_scalp_v3.py:1004` (approx) | (1) hard gate — `passed = quality_score >= minimum_pct` (2) `market_quality_grade` feeds `_required_confidence()`'s adjustment (3) `market_quality` (a DIFFERENT extraction, `details.get('market_quality', details.get('market_quality_score', 0))`) feeds `PositionSizeEngine`'s `_market_quality_multiplier` | **YES, hard gate** | **YES** | Partial | **KEEP — this is the closest thing to a genuine, already-separate Market Gate that exists today (see A6)** |
| **`AdaptiveConfidenceEngine`'s internal `market_quality_score`** (squeeze+vol_ratio based, NOT the same as `MarketQualityEngine`'s score — naming collision, Phase 0 §F, re-confirmed still present unchanged) | `adaptive_confidence_engine.py:55` | feeds `market_quality_multiplier` inside the confidence multiplicative chain only | No (internal to confidence's own math) | Indirectly (via confidence) | No | **REVIEW / MERGE** — two differently-computed numbers sharing one name is a genuine footgun for anyone reading logs |
| **`strategy_decision[dir]["final"]`** (Phase 4) | `smart_scalp_v3.py`, populated at every return point in `generate_signal()` | Nothing yet (new, unread by any consumer outside `details` itself) | Reflects gates, doesn't itself gate | No | Intended for future use | **KEEP — already the explicit PASS/FAIL Rule 8 wants; just not surfaced through the public API yet** |
| **`sizing_inputs`** (Phase 6) | same | `state_machine.py`, `core/backtest.py` (both, preferentially) | No | **YES — the explicit contract** | No | **KEEP — already the explicit quality/sizing payload Rule 10 wants** |

**The headline finding for A2**: **Rules 8 and 10's target architecture — Strategy PASS/FAIL explicitly separated from numeric quality/sizing inputs — was already built in Phases 4 and 6**, inside `smart_scalp_v3.py`'s `details` dict. What is genuinely missing is (a) surfacing `strategy_decision` through the *public* `smart_scalp_signal()`/`generate_signal()` contract rather than leaving it buried in `details`, and (b) the file-level modularity Rule 4 wants (one file doing everything vs. separated Market Gate / Strategy / Selector / Quality modules).

---

## A3. GATE INVENTORY

Eighteen gates, in execution order, re-counted directly from the current file (matching
Phase 0 §H's count, re-verified line-by-line this pass):

| # | Gate | Location | Condition | Input | Result when failed | Current owner | Proposed owner |
|---|---|---|---|---|---|---|---|
| 1 | Warm-up | `smart_scalp_v3.py:1107` | `len(ticks) < 5` | tick count | reject | generate_signal | MARKET CONTEXT |
| 2 | Time filter | `:1104` | wall-clock before `TRADING_NO_TRADE_BEFORE` | tick timestamp | reject | generate_signal | MARKET GATE |
| 3 | Premium filter | `:1119` (`check_premium_filter`) | `MIN/MAX_ENTRY_PREMIUM` | option LTP | reject | generate_signal | **candidate MOVE → Instrument/Market Gate** (not a market-behaviour question) |
| 4 | Delta filter | `:1126-1132` | `DELTA_MIN=0.25`/`DELTA_MAX=0.75` (hardcoded `DELTA_FILTER_ENABLED=True` at line 71, not `.env`-driven) | option delta | reject | generate_signal | **candidate MOVE → Instrument** |
| 5 | Market Quality | `:~1175-1209` | `quality_score >= minimum_pct` (60 default) | tick/broker/greeks | reject | generate_signal | **already logically separable → Market Gate module** |
| 6 | Chop filter | `:~1216-1249` | AND-of-3 (EMA-squeeze, low-ATR, MACD-flat) | indicators | reject | generate_signal | MARKET GATE (arguably) or STRATEGY (it's testing "is there a trend to trade", closer to strategy precondition) — **REVIEW, ambiguous** |
| 7 | Setup score (trend + confirmations) | `evaluate_pullback_strategy()` | `ce_score/pe_score >= self.min_score` (4) | indicators | `ce_signal/pe_signal = False` | evaluate_pullback_strategy (Phase 3) | STRATEGY DECISION — **already correctly owned** |
| 8 | Weighted score | `:~1319/1354` | `< self.min_weighted_score_pct` (42) | indicators+tick, via `WeightedScoreEngine` | `ce_signal/pe_signal = False` | generate_signal | STRATEGY DECISION (per Rule 8's caution — the gate role needs explicit justification before moving, not automatic deletion) |
| 9 | Exhaustion (RSI+MACD) | `:~1408-1420` | `rsi > CE_EXHAUSTION_RSI(70) and macd_hist declining` (CE); PE half disabled (`PE_EXHAUSTION_RSI=0`) | indicators | `ce/pe_exhausted = True` | generate_signal | STRATEGY-SPECIFIC (momentum-fade suppression) |
| 10 | Exhaustion (direction-block / SL-streak) | `:~1414/1430` | `is_direction_blocked()`, `TradingState`, 2-loss/30-min lock | `state_machine.py`'s `TradingState` | `ce/pe_exhausted = True` | **Strategy-layer READ of a Risk-shaped state object owned by state_machine.py** — genuine boundary blur (Phase 2 §I, re-confirmed) | Needs an explicit owner decision — see A5/B |
| 11 | Confidence (internal) | `:~1483/1531` | `confidence >= required_conf` (MQ-grade-adjusted) | indicators+tick, via `AdaptiveConfidenceEngine` | `signal=0` | generate_signal | STRATEGY DECISION |
| 12 | Cross-direction tick | `entry_engine.py:181-183` | fresh tick available for the resolved direction | broker state | reject | entry_engine | EXECUTION |
| 13 | Confidence (external, RE-CHECK) | `entry_engine.py:204-208` | flat `MIN_CONFIDENCE(70)`/`MIN_CONFIDENCE_AFTER_3SL(85)` | `confidence` (same number as gate 11) | reject | entry_engine | **Asymmetric redundancy with gate 11 (Phase 0 §F): for MQ B/C it never fires; for A/A+ it overrides; the 3-loss escalation is its ONLY unique contribution** |
| 14 | Range filter | `entry_engine.py:223-239` | `ENTRY_RANGE_FILTER_ENABLED` (confirmed still `False` by default) | tick range | reject (if enabled) | entry_engine | STRATEGY-SPECIFIC, currently inert |
| 15 | Premium (RE-CHECK) | `entry_engine.py:246-252` | same `MIN/MAX_ENTRY_PREMIUM` constants, on `execution_tick` (possibly different tick than gate 3 saw) | tick | reject | entry_engine | Redundant with gate 3 (Phase 0 §O) |
| 16 | Spread | `entry_engine.py:259-265` | `KILL_SWITCH_SPREAD` | tick bid/ask | reject | entry_engine | MARKET GATE / EXECUTION |
| 17 | Session trend | `entry_engine.py:272-281` | `can_trade_ce()`/`can_trade_pe()`, `session_trend.py`'s OWN independently-computed EMA9/21/50 | separate EMA state | reject | entry_engine | A **fourth** trend computation (Rule 6 relevance: is this a second "strategy" hiding in plain sight, or a confirmation gate? — REVIEW) |
| 18 | Time+Greek (live only) | `entry_engine.py:303-314` | `PAPER_TRADING==False` only | greeks | reject | entry_engine | Instrument, 5th delta touch |

**Rule 9 compliance note**: every threshold value cited above was read directly from the
current file this pass, not carried forward from memory. None is proposed for change in this
report — Phase A is forensics only, per Rule 2.

---

## A4. DATA-FLOW GRAPH (current, re-traced)

```
market data (ticks)
      ↓
calculate_indicators()                          [MARKET CONTEXT — candle/EMA/RSI/MACD/VWAP/
      ↓                                           ATR/BB/KC/Squeeze(dead)/Supertrend(dead)/Vol]
premium gate → delta gate → OI calc              [gates 3-4, INSTRUMENT-shaped, sit ahead of MQ]
      ↓
MarketQualityEngine.evaluate()                   [gate 5 — THE closest thing to a real Market Gate]
      ↓
chop filter                                      [gate 6 — ambiguous MARKET/STRATEGY]
      ↓
evaluate_pullback_strategy()                     [gate 7 — THE ONE STRATEGY]
      ↓ ce_signal/pe_signal (bool) + ce_score/pe_score + observability
weighted score (gate 8) → exhaustion (gates 9-10) → confidence (gate 11)
      ↓ signal (0/1), direction, confidence, details{weighted_score, sizing_inputs,
      ↓          strategy_decision, ce_score, pe_score, reason, ...}
smart_scalp_signal() wrapper                     [packages the public params dict]
      ↓
entry_engine.entry_signal()                      [gates 12-18 — cross-direction, confidence
      ↓                                           RE-CHECK, range, premium RE-CHECK, spread,
      ↓                                           session-trend, live-only time+greek]
      ↓ has_signal (bool)
state_machine.state_idle() → state_entry_ready()
      ↓ (ONLY reached if has_signal==True — a rejected signal never reaches this)
RiskManager.can_trade()                          [9 gates, confirmed clean/separate, Phase 0 §J]
      ↓
sizing_inputs extraction (Phase 6) → PositionSizeEngine.calculate()
      ↓ score_multiplier, confidence_multiplier, ... → lots, position_size
broker order placement                           [untouched by any phase]
```

---

## A5. DUPLICATION / DEAD-CODE REPORT

**Confirmed dead, this pass, with proof of zero consumers:**

1. **`calculate_bullish_score()` / `calculate_bearish_score()`** (`smart_scalp_v3.py:665-863`,
   199 lines combined). Re-grepped this pass: `grep -c "calculate_bullish_score()\|calculate_bearish_score()"`
   returns **0** for call sites (the only matches are the `def` lines themselves).
   `generate_signal()` uses the inline-duplicate logic inside `evaluate_pullback_strategy()`
   instead. **Proof of safety to delete**: no file in the repo (including tests) references
   these method names anywhere except their own definitions — confirmed by the same grep
   command run against `.`, not just `strategies/`.

2. **`Squeeze_Breakout!` factor** (`smart_scalp_v3.py:729-731` CE / `:829-831` PE,
   inside `evaluate_pullback_strategy()`) — permanently unreachable: `Was_Squeeze` is
   hardcoded `False` at line 564, never updated. Re-confirmed this pass (exact same line
   content as Phase 1/2 found). **This is not dead code in the "unreferenced" sense** — it
   IS referenced and IS evaluated every cycle — it simply can never evaluate `True`. Deleting
   the dead branch changes nothing observable; **keeping it costs nothing but complexity**.

3. **`Supertrend`** (`smart_scalp_v3.py:555`) — computed every cycle inside
   `calculate_indicators()`, stored in `indicators['Supertrend']`, re-confirmed this pass to
   have **zero readers** anywhere in the file or repo (`grep -rn "Supertrend" --include=*.py .`
   returns only the assignment line and its own three-line if/elif/else computation).

**Duplicate (not dead — all three re-confirmed as live, gating consumers this pass):**

4. Trend computed 3-4 independent times: setup-score's `ema9`/`ema21` (from
   `calculate_indicators()`), `WeightedScoreEngine`'s `ema_trend` factor (same source values,
   re-scored), `session_trend.py`'s own maintained EMA9/21/50 (a genuinely separate
   computation, entry_engine gate 17), `get_market_regime()`'s EMA21-vs-EMA50 regime (a third
   pairing).

5. Premium checked twice (gates 3 and 15) on the same constants, possibly different ticks.

6. Confidence checked twice (gates 11 and 13) with asymmetric effect (Phase 0 §F).

7. RSI, VWAP, Volume, OI each scored in 2-3 places (setup score + weighted score +, for
   VWAP/volume/OI, confidence too) — re-confirmed unchanged this pass by re-reading
   `weighted_score_engine.py` and `adaptive_confidence_engine.py` fresh.

**No dead caches or dead Strategy decisions were found beyond what's listed above** — a
targeted search for other `= False  #` or similarly-suspicious hardcoded sentinel
assignments in `smart_scalp_v3.py` found nothing beyond `Was_Squeeze`.

---

## A6. PROPOSED FILE STRUCTURE

Not a mandate to blindly create these files — a proposal reasoned from what A1-A5 actually
found, sized to the fact that **exactly one strategy exists today**.

```
strategies/
    __init__.py                    — UNCHANGED public surface: SmartScalpV3, get_strategy,
                                      smart_scalp_signal (Rule: 9 external files depend on
                                      these 3 names; a compatibility shim if internals move)
    market_context.py              — NEW: wraps calculate_indicators() (candle/EMA/RSI/MACD/
                                      VWAP/ATR/BB/KC/Volume) — pure computation, no gating.
                                      Supertrend and the Squeeze/Was_Squeeze machinery move
                                      here too, dead-but-harmless, pending an explicit
                                      DELETE decision (Phase E, not automatic)
    market_gate.py                 — NEW: wraps MarketQualityEngine.evaluate() (already a
                                      clean, separate class — this file would just be the
                                      integration point) + the chop filter (REVIEW: A3 flags
                                      chop as ambiguously Market-vs-Strategy; placing it here
                                      is a design choice this report is NOT making unilaterally)
    pullback_strategy.py           — NEW: evaluate_pullback_strategy(), lifted out of
                                      SmartScalpV3 as the first (and currently only) entry in
                                      a strategies/ family. calculate_bullish_score/
                                      calculate_bearish_score do NOT move here — DELETE
                                      candidate, not a relocation (A5)
    scoring.py                     — NEW: thin re-export of WeightedScoreEngine/
                                      AdaptiveConfidenceEngine (already separate classes in
                                      core/engines/ — no move needed, just a documented
                                      boundary: this is where "quality, not gate" lives
                                      conceptually)
    selector.py                    — NEW, but Rule 7 requires stopping here: no existing
                                      priority/conflict logic was found (A-search, zero
                                      hits), and only one strategy exists to select between.
                                      This file would be a pass-through today
                                      ("if exactly one strategy fired, return it") — NOT a
                                      real selector, because there is nothing to select
                                      between yet. Building real conflict-resolution logic
                                      now would be **inventing a trading rule with no
                                      existing precedent**, which Rule 7 explicitly forbids.
    smart_scalp_v3.py              — SHRINKS to: generate_signal()'s orchestration (calling
                                      the above in sequence), get_entry_params(), the
                                      public smart_scalp_signal()/get_strategy() functions.
                                      This is the piece that currently does everything;
                                      after the move it does only ORCHESTRATION.

core/engines/
    entry_engine.py                — UNCHANGED location; gates 12-18 (cross-direction,
                                      confidence re-check, range, premium re-check, spread,
                                      session-trend, live time+greek) stay here per Rule 11
                                      unless explicitly authorized to relocate — several are
                                      flagged REVIEW/redundant in A3 but relocating them is a
                                      Phase C+ decision requiring the Phase B stop-and-approve
                                      step below, not something this report performs
    market_quality_engine.py       — UNCHANGED, already correctly separate
    weighted_score_engine.py       — UNCHANGED, already correctly separate
    adaptive_confidence_engine.py  — UNCHANGED, already correctly separate
    position_size_engine.py        — UNCHANGED, not opened, per Rule 10/11
    state_machine.py               — UNCHANGED except Phase 6's already-reported
                                      sizing_inputs extraction; the direction-block/SL-streak
                                      state (A3 gate 10) stays here — Strategy reads it, does
                                      not own it (A5's flagged boundary blur, unresolved)
```

**Why not more modules than this**: Rule 6 asks for strategies to be independently
addable, and Rule 4's diagram lists Breakout/Momentum/Reversal as future strategies — but A1
already established none of those exist today, even as dead code. Building empty
`breakout_strategy.py`/`momentum_strategy.py`/`reversal_strategy.py` stub files now would be
inventing strategy scaffolding with no behavioural content, which is architecturally
premature and risks becoming exactly the kind of "excessively strict collection of
conditions nobody asked for" Rule 5 warns against for the Market Gate — the same caution
applies to strategy stubs. **The honest proposal is: build the one real strategy
(`pullback_strategy.py`) as a self-contained module with a clean interface, so that adding a
second strategy later is a matter of writing one new file with the same interface — not
scaffold four empty ones now.**

---

# PHASE B — DESIGN REVIEW / STOP

## SAFE CHANGES (reorganize code/contracts, no behavioural effect — candidates for
## implementation without further owner approval, IF the user authorizes proceeding to Phase C)

1. Splitting `smart_scalp_v3.py` into the module structure in A6, preserving
   `strategies/__init__.py`'s three public names — a pure code-motion, verifiable with the
   same equivalence-harness discipline used in Phases 3, 4, and 6 (byte-for-byte comparison
   of `signal`/`direction`/`confidence`/`ce_score`/`pe_score`/`weighted_score`/
   `sizing_inputs`/`strategy_decision` before and after).
2. Deleting `calculate_bullish_score()`/`calculate_bearish_score()` — proven zero-consumer
   (A5.1), removal changes no observable behaviour.
3. Deleting (or formally documenting-as-permanently-inert-and-removing) the
   `Squeeze_Breakout!` dead branch and the `Supertrend` computation (A5.2-3) — both provably
   inert; removal changes no observable behaviour.
4. Surfacing `strategy_decision` through `smart_scalp_signal()`'s public `params` dict (it
   currently exists only inside `details`, Phase 4) — additive, matches the pattern already
   used successfully for `sizing_inputs` in Phase 6.
5. Merging the naming collision between `MarketQualityEngine`'s `quality_score` and
   `AdaptiveConfidenceEngine`'s internally-recomputed `market_quality_score` (A2) — **only**
   if done as a rename/clarification of the *second* one (e.g. `squeeze_volume_score`), never
   by making them the same number, since they currently measure genuinely different things
   and forcing them equal would be a behaviour change disguised as a rename.

## BEHAVIOUR CHANGES (would alter signal frequency, direction, accepted/rejected outcomes,
## lot size, or risk exposure — NOT implemented, STOPPED here per Rule 9/Phase B, reported
## for explicit owner decision)

1. **Removing or relaxing gate 8 (weighted-score threshold) or gate 11 (confidence
   threshold) as Strategy gates**, even in service of the "PASS/FAIL should not
   automatically be gated by a quality score" principle (Rule 8's own text). Phase 5 already
   proved these two thresholds currently reject setups that never reach sizing at all
   (§2 item 7 of the Phase 5 report, re-confirmed unchanged this pass in A4's data-flow
   trace). Removing them would turn some currently-rejected setups into trades — an explicit
   Rule 9 stop condition. **This report does not propose a specific resolution** (e.g. "keep
   both gates as-is and just make the PASS/FAIL *label* explicit" vs. "genuinely decouple
   quality from gating and accept a wider trade population") because that choice is a
   trading-rule decision, not an architecture decision, and Rule 8 explicitly says "do not
   simply remove its gate" without first determining "what the existing gate represents."
2. **Merging gate 11 (internal confidence) and gate 13 (external confidence re-check)** into
   one check. Phase 0 §F found the external gate is redundant for MQ grades B/C but is the
   **sole source** of the 3-consecutive-loss 85% escalation. Collapsing them without
   preserving that escalation is a Risk-adjacent behaviour change (it currently makes the bot
   harder to re-enter after a losing streak; removing it would not).
3. **Removing gate 15 (the redundant external premium re-check)**. Structurally redundant
   with gate 3 on paper, but they run against `execution_tick` (post cross-direction
   resolution) vs. the tick `evaluate_pullback_strategy()` originally saw — Phase 0 flagged
   this as "possibly different ticks," never empirically measured (an explicit evidence gap
   carried forward from Phase 0 §S, still open). Removing it without first measuring whether
   the two ticks ever actually diverge in a live session is a guess, not a proof.
4. **Relocating the chop filter (gate 6) or the direction-block/SL-streak exhaustion state
   (gate 10)** to a different owner module. Both are architecturally ambiguous (A3 flags
   both REVIEW) but *where a check lives* is safe to change only if *what it does* doesn't
   change with it — and gate 10 specifically is Strategy code reading Risk-shaped state
   owned by `state_machine.py`; relocating either direction (state_machine owns it fully vs.
   Strategy owns a copy of it) changes which layer's tests/logs would show the block,
   which is enough of a behavioural-observability change to warrant asking first.
5. **Building a real Strategy Selector with priority/conflict-resolution rules** (Rule 7).
   No existing rule was found (A1's grep, zero hits) and only one strategy exists to select
   between — any conflict-resolution logic written now would be invented, not extracted,
   which Rule 7 explicitly prohibits without an explicit STOP. **Stopping here, as instructed.**

---

## What Phase A + B conclude, plainly

The target architecture's *hardest* two requirements — Strategy PASS/FAIL explicitly
separated from sizing inputs (Rules 8/10), and no accidental gate-lowering (Rule 9) — are
**already satisfied inside the current file**, built across Phases 4 and 6, verified with
equivalence harnesses at the time. What genuinely remains is (a) file-level modularity (A6)
— real but low-risk, mechanical work, matching the discipline already used in Phases 3-6, and
(b) five specific decisions (Phase B's "Behaviour Changes" list) that are trading-rule
questions, not engineering questions, and cannot be resolved by more forensics — they need
the owner to choose.

**Recommendation, not a decision this report makes unilaterally**: proceed to Phase C for the
SAFE CHANGES list only (items 1-5 above), leave every BEHAVIOUR CHANGE item exactly as it
currently operates, and treat this report's Phase B section as the standing record of what
was deliberately left alone and why.

