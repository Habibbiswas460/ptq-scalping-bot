# PTQ SCALPING BOT — PHASE 4: SCORING SIMPLIFICATION (IMPLEMENTATION RECORD)
### The smallest safe change, after evidence showed the requested full collapse would silently change position sizing.

---

## 1. IMPLEMENTED

**Not** a collapse of the three-stage scoring chain into a single boolean gate. Step 1's
forensics (below) found that two of the three stages — Weighted Score and Adaptive
Confidence — have their *raw percentage values*, not just their pass/fail outcome, consumed
live by `PositionSizeEngine` (`state_machine.py:835-848` → `position_size_engine.py:141,
297-298, 300-301`) as the `score_multiplier` and `confidence_multiplier` inputs to lot sizing.
Collapsing either to PASS/FAIL would change the number `PositionSizeEngine` receives, which
changes computed lot size — a Sizing behaviour change, which every version of this project's
hard rules (Phase 3 and Phase 4 alike) explicitly forbids. This is documented in full in
Step 11 (Stop Conditions) below, with exact evidence, rather than implemented around.

**What was implemented instead**, entirely inside `generate_signal()` (already the sole home
of this logic since Phase 3), is the part of "one clearly identifiable Strategy decision,
with rejection attribution that tells us exactly why the current setup failed" that *is*
safe: a single, ordered, per-direction `details["strategy_decision"]` record that threads
through every existing gate — trigger/confirmation (Phase 3's `pullback_strategy` block),
weighted-score threshold, exhaustion, confidence threshold — recording each stage's
pass/fail **without changing what any stage decides**. Previously, "why did CE fail" required
checking up to three independently-shaped signals (`ce_score_threshold_fail`, `exhaustion`,
and a `reason` string that gets overwritten as the function progresses); now it is one
dict with a single `final: PASS/FAIL` and, on failure, one `failed_at` naming the exact
stage. A small helper, `_finalize_strategy_decision()`, is called at every return point so
both directions' records are always complete even when one direction returns before the
other's checks run (see the completeness note in Step 6).

Two algebraic rewrites were also made, both semantics-preserving by construction: `if
ce_weighted_pct < self.min_weighted_score_pct:` became `ce_weighted_pass =
ce_weighted_pct >= self.min_weighted_score_pct; if not ce_weighted_pass:` (and the PE/
confidence equivalents) — `X < T` and `not (X >= T)` are identical for the numeric,
never-NaN values involved here, verified by inspection and by the equivalence run in Step 6.

---

## 2. SCORING BEFORE

```
Setup Score  (inline, 0-11/12 points, extracted into evaluate_pullback_strategy() in Phase 3)
      ↓
Weighted Score  (WeightedScoreEngine, 0-100%, min_weighted_score_pct threshold)
      ↓
Adaptive Confidence  (AdaptiveConfidenceEngine, multiplicative 0-100, MQ-grade-adjusted threshold)
```

---

## 3. SCORING AFTER

**Structurally identical stages, in the identical order, with identical thresholds and
identical numeric outputs.** What changed is observability, not decision-making:

```
evaluate_pullback_strategy()  →  ce_signal/pe_signal (unchanged) + per-condition observability (Phase 3)
      ↓
Weighted Score  (unchanged computation, unchanged threshold)  →  strategy_decision[dir]["weighted_score"] = {value, threshold, pass}
      ↓
Exhaustion check (unchanged)                                  →  strategy_decision[dir]["exhaustion"] = {pass, reason}
      ↓
Adaptive Confidence  (unchanged computation, unchanged threshold) → strategy_decision[dir]["confidence"] = {value, threshold, pass}
      ↓
strategy_decision[dir]["final"] = PASS/FAIL, ["failed_at"] = the first stage that failed, or None
```

`ce_score`/`pe_score`/`ce_weighted_pct`/`pe_weighted_pct`/`confidence` are all still computed
by the exact same functions, still returned in the exact same places, still consumed by the
exact same downstream code (`entry_engine.py`, `state_machine.py`, `PositionSizeEngine`,
the DB/analytics pipeline). Nothing about *what the system decides* changed; what changed is
that *why* it decided that way is now attributable to one specific stage per direction.

---

## 4. FACTOR CLASSIFICATION

| Factor | Classification | Action | Evidence |
|---|---|---|---|
| EMA9 vs EMA21 (trend precondition) | STRATEGY_TRIGGER | KEEP, unchanged | `smart_scalp_v3.py:~926/~995` (evaluate_pullback_strategy) |
| EMA9 proximity | See note below — **not actually a required trigger in the running code** | KEEP, unchanged; re-documented | See "Correction to Phase 2" below |
| Candle direction | STRATEGY_CONFIRMATION | KEEP, unchanged | evaluate_pullback_strategy CE/PE blocks |
| RSI (setup-score role) | STRATEGY_CONFIRMATION | KEEP, unchanged | same |
| RSI (exhaustion role) | STRATEGY-ADJACENT / RISK-SHAPED (suppression, not confirmation) — distinct use of the same value | KEEP, unchanged, already separately classified in Phase 2 §I | `smart_scalp_v3.py` exhaustion block |
| VWAP (setup-score role) | STRATEGY_CONFIRMATION | KEEP, unchanged | evaluate_pullback_strategy |
| VWAP (weighted-score `vwap`, confidence `vwap_score`) | DUPLICATE — re-scores the same side-of-VWAP fact, but the raw % is a live sizing input (see §1) | Cannot relocate without changing sizing — documented, not moved | `weighted_score_engine.py:59-62`, `adaptive_confidence_engine.py:50/53` |
| Volume (setup-score role) | STRATEGY_CONFIRMATION | KEEP, unchanged | evaluate_pullback_strategy |
| Volume (weighted-score, confidence, MQ liquidity) | DUPLICATE across 3 more places, all live-numeric consumers | Documented, not moved | `weighted_score_engine.py:64-67`, `adaptive_confidence_engine.py:57`, `market_quality_engine.py:279-290` |
| OI (setup-score role) | STRATEGY_CONFIRMATION | KEEP, unchanged | evaluate_pullback_strategy |
| OI (weighted-score, confidence) | DUPLICATE, live-numeric consumers | Documented, not moved | `weighted_score_engine.py:81-84`, `adaptive_confidence_engine.py:68-70` |
| MACD (direction + slope) | STRATEGY_CONFIRMATION candidate — **genuinely new information not present in Setup Score at all** | Cannot be promoted into the boolean Strategy layer without either (a) duplicating MACD logic into evaluate_pullback_strategy — which Phase 4's rules forbid ("Do NOT add new indicators... do not change the Pullback trigger itself" — MACD has never been part of it) or (b) removing it from Weighted Score, whose % is sizing-critical. **Left exactly where it is.** | `weighted_score_engine.py:97-100`; also used, separately, in the exhaustion check (`smart_scalp_v3.py`, unchanged) |
| Premium | INSTRUMENT | KEEP, unchanged (hard gate + entry_engine re-check both pre-date and are outside Phase 3/4's scope) | Phase 0 §H/§I |
| Delta | INSTRUMENT | KEEP, unchanged | Phase 0 §H |
| Greeks (gamma/theta) | INSTRUMENT | KEEP, unchanged | Phase 0 §G |
| Spread | MARKET_QUALITY (primary) / DUPLICATE (weighted-score `spread_quality`, entry_engine re-check) | KEEP, unchanged — both are live-numeric/behavioural consumers | Phase 0 §F/§O |
| ATR / volatility | MARKET_QUALITY (primary, MQ `volatility_points`) / DUPLICATE (weighted-score `atr_volatility`) / STRATEGY-ADJACENT (chop filter, unchanged, out of scope) / EXECUTION-EXIT-ADJACENT (SL/TP sizing in `get_entry_params()`, untouched) | KEEP, unchanged in all four uses | Phase 2 §F |
| Market regime | DUPLICATE of trend, computed a 3rd way (EMA21 vs EMA50) | KEEP, unchanged — feeds live weighted-score and confidence numbers | `smart_scalp_v3.py:get_market_regime()`, `weighted_score_engine.py:113-116`, `adaptive_confidence_engine.py:48-53` |
| Session (time-of-day) | MARKET_QUALITY (primary) / DUPLICATE (confidence `session_score`) | KEEP, unchanged | `market_quality_engine.py:320-330`, `adaptive_confidence_engine.py:72` |
| Freshness (tick staleness) | MARKET_QUALITY (primary, hard-reject too) / DUPLICATE (confidence `freshness_score`) | KEEP, unchanged | `market_quality_engine.py:189-207/292-307`, `adaptive_confidence_engine.py:73/163-182` |

---

## Correction to Phase 2's characterization (found during Step 1, re-confirmed by Step 6 testing)

Phase 2 described the Pullback strategy's required conditions as "trend precondition **+**
pullback trigger." **The running code does not actually require the trigger.** In
`evaluate_pullback_strategy()`, only the trend check (`if ema9 > ema21:` / `if ema9 <
ema21:`) gates entry into the scoring block; the EMA9-proximity trigger is scored exactly
like the other confirmation conditions (+2 points), not enforced as a second mandatory gate.
Because candle (+2 max), RSI (+2 max), VWAP (+1), volume (+1), and OI (+1) together can reach
7 points on their own — well above `min_score`'s default of 4 — **a signal can fire with
trend present but the proximity trigger absent**, so long as enough of the other
confirmations line up. This was surfaced empirically: the equivalence harness's
`CE_invalid_proximity` case (engineered with price far from EMA9, expecting a FAIL) instead
returned `signal=1` in **both** the pre-Phase-3 reference and the current working tree —
proving this is pre-existing, unchanged behaviour, not something introduced by any
extraction, and that Phase 2's "two required conditions" framing was an assumption that did
not match the code. `strategy_decision[dir]["trigger_confirmation"]` (built on Phase 3's
already-correct `ce_signal`/`pe_signal`) reflects the real behaviour accurately — it is
named for the combined outcome, not a claim that both sub-conditions were individually
required.

---

## 5. BEHAVIOUR PRESERVATION

Explained precisely, not asserted: every change in this phase is one of exactly three kinds,
and each kind was checked by the method matching its risk:

1. **Purely additive statements** (`strategy_decision[...] = {...}`) — cannot change any
   existing variable's value by construction; verified by re-reading every insertion point
   to confirm no existing line was altered, only new lines inserted around it (`git diff`
   inspected directly, not just re-run — see the "Correction" note above, which was found
   *because* this inspection was done carefully).
2. **Two algebraic sign-inversions** (`X < T` → `not (X >= T)`) — logically identical for
   all real-numbered inputs; no code path produces NaN or None for `ce_weighted_pct`,
   `pe_weighted_pct`, or `confidence` at these points (all are `int`/computed floats from
   `WeightedScoreEngine`/`AdaptiveConfidenceEngine`, never optional there).
3. **A completeness fix** for the new field only (`_finalize_strategy_decision()` called at
   every return point) — this affects only the *new* `strategy_decision` dict's own internal
   completeness, not any pre-existing field, value, or control-flow decision.

None of these three kinds can change `ce_signal`, `pe_signal`, `ce_score`, `pe_score`,
`ce_weighted_pct`, `pe_weighted_pct`, `confidence`, `signal`, `direction`, or `reason` — and
this was verified, not just argued: a 14-case equivalence harness (extending Phase 3's 8
cases with the Step 6-requested weighted-score pass/fail boundary, confidence pass/fail
boundary, MACD sign variations for both directions, and missing/default-indicator cases)
compared pre-Phase-3 git-HEAD against the current working tree (Phase 3 + Phase 4 combined)
across `signal`, `direction`, `confidence`, `ce_score`, `pe_score`, `ce_factors`,
`pe_factors`, `ce_weighted_score_pct`, `pe_weighted_score_pct`, `weighted_score`, and
`reason`. **All 14 cases matched exactly.** The harness also asserted `strategy_decision`
always has a `final` key for both CE and PE in every case (the completeness fix from item 3
above) — this initially failed for one case before the fix (documented, not hidden — see the
`_finalize_strategy_decision()` addition), and passed after it.

---

## 6. TEST RESULTS

**Baseline** (pre-Phase-4, i.e. Phase 3-complete state) and **post-Phase-4**, identical
command, full suite:
```
FAILED tests/test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware
FAILED tests/test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_no_tz_mismatch_crash
FAILED tests/test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
FAILED tests/test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
```
**Identical 4 failures, identical position in the run, before and after.** These are the same
pre-existing, unrelated failures documented in the Phase 3 report (2 exit-engine-parity tests
affected by this session's earlier `.env` change; 2 visual-records tests reading real trade
data from live sessions on 2026-09-08) — neither category touches `strategies/` or
`entry_engine.py`.

```
baseline failures : 4  (test_soft_loss_exit_fires_..., test_naive_timestamps_also_work_...,
                        test_cooldown_window_boundaries_..., test_the_opening_window_states_...)
post-change failures : 4  (identical set)
new failures : 0
fixed failures : 0
```

Targeted tests: `tests/test_smart_scalp_confidence.py` + `tests/test_entry_engine_cross_direction.py`
→ 16 passed, 1 skipped, unchanged before and after.

AST/import validation: `ast.parse()` and `SmartScalpV3()` instantiation both succeed after
every edit (checked incrementally, not just at the end).

---

## 7. FILES CHANGED

```
strategies/smart_scalp_v3.py
```
(`git diff --name-only`, exactly one path.)

Cumulative Phase 3 + Phase 4 diff stat: `+321/-126` lines net for the whole session's work on
this file; Phase 4's own increment on top of Phase 3 added the `strategy_decision` structure,
the two algebraic rewrites, and the `_finalize_strategy_decision()` helper — no other
structural change.

---

## 8. FILES GUARANTEED UNTOUCHED

```
core/risk/                          — empty diff
core/engines/position_size_engine.py — empty diff
core/engines/exit_engine.py          — empty diff
core/trading/                        — empty diff
.env                                 — empty diff
config/                              — empty diff
broker.py (core/trading/broker.py)   — covered by core/trading/, empty diff
entry_engine.py                      — not in the changed-files list; its confidence/premium
                                        re-checks, drift guard, and every other gate are
                                        byte-identical to before this session's Phase 3/4 work
```
Verified by `git diff --stat -- <path>` returning empty output for each, checked directly
(not inferred) immediately before writing this report.

---

## 9. REMAINING ISSUES / EVIDENCE GAPS

1. **The core Phase 4 objective — collapsing Weighted Score and Adaptive Confidence into a
   PASS/FAIL Strategy layer — was not implemented, and per Step 11's explicit stop
   conditions, should not be, without further owner decision.** The evidence is unambiguous:
   both engines' raw percentages are live inputs to `PositionSizeEngine`'s multipliers
   (`state_machine.py:835-848`), not merely gates. A genuine architectural fix exists — e.g.
   separating "the Strategy's own PASS/FAIL opinion" from "a market-quality-and-momentum
   *weight* used only for sizing" would let Strategy simplify to PASS/FAIL while Sizing kept
   receiving a number — but building that separation touches `PositionSizeEngine`'s call
   contract and is therefore Sizing-layer work, explicitly out of Phase 4's (and this
   session's) bounds. This is the honest, load-bearing finding of Phase 4: the "single
   Strategy confirmation decision" the prompt asked for cannot be built inside `strategies/`
   alone, because the numbers it would discard are consumed one layer downstream.
2. **MACD remains trapped inside Weighted Score.** It is the one factor Phase 2 correctly
   flagged as "genuinely new information," and it still cannot be relocated into the boolean
   Strategy layer for the same reason as (1) — Weighted Score's percentage cannot be touched.
3. **The Phase 2 "trend + trigger both required" characterization was wrong** (see the
   correction note above) — corrected here with evidence, not silently carried forward.
4. **`calculate_bullish_score()`/`calculate_bearish_score()`** (Phase 0/1's likely-dead-code
   finding) remain untouched, as instructed.
5. `strategy_decision`'s completeness fix (`_finalize_strategy_decision()`) is now correct
   for the paths tested (14 cases, both directions, all return points) but was not proven
   correct for every theoretically possible path by formal means (e.g. no path was found
   that skips more than one backfill call, but this was verified by test coverage, not by
   exhaustive proof).

---

## 10. PHASE 5 HANDOFF

Not implemented here. Two candidate directions, both flowing directly from this phase's
central finding:

**A. Sizing-input separation** (addresses Remaining Issue #1 directly): define a narrow,
explicit contract for what `PositionSizeEngine` actually needs — a "quality weight" in
[0,100] — and let `Strategy` return that number *alongside* its own independent PASS/FAIL,
rather than having Strategy's PASS/FAIL *be* a byproduct of the same number Sizing consumes.
This is a Sizing-boundary change (touches `state_machine.py`'s call site and possibly
`PositionSizeEngine`'s signature), so it is explicitly not Phase 4/5-strategy-layer work by
this project's own rules — it would need its own phase with RiskManager/PositionSizeEngine
in scope, which every phase so far has deliberately excluded.

**B. MQ/Instrument/Execution relocation** (Phase 2 §F/§K's original target, deferred through
Phases 3 and 4 both): physically move premium/delta/spread/ATR-band out of
`WeightedScoreEngine`'s and `AdaptiveConfidenceEngine`'s factor lists into MQ/Instrument,
recomputing each engine's percentage from a smaller, purely-behavioural factor set. This
does NOT require touching `PositionSizeEngine` (the percentage would still flow to it
unchanged in shape, just computed from fewer/different inputs) and is therefore the more
plausible next phase within this project's established boundaries — but it does change the
*numeric value* of `weighted_score`/`confidence` for any given market state (since factors
are removed from the weighted sum), which is a genuine behavioural change requiring its own
careful equivalence analysis (there is no "same score, minus some inputs" equivalence to
verify against — the score legitimately changes), and its own explicit owner sign-off before
starting, given this project's repeated emphasis on not changing behaviour without
authorization.

**No Phase 5 code was implemented in this task.**

