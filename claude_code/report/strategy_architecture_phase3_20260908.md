# PTQ SCALPING BOT — PHASE 3: STRATEGY SEPARATION (IMPLEMENTATION RECORD)
### Extraction only. Behaviour verified byte-exact against pre-extraction reference.

---

## 1. IMPLEMENTED

The Pullback strategy — the only genuine, firing entry strategy (Phase 2 §C) — now has an
explicit, isolated Strategy decision boundary: `SmartScalpV3.evaluate_pullback_strategy(indicators, oi_direction) -> Dict`.

This method is a **byte-for-byte extraction** of the CE/PE inline scoring block that
previously lived directly inside `generate_signal()` (original lines 1047-1163), moved
into its own named method with no change to any condition, threshold, calculation, or
evaluation order. `generate_signal()` now calls it at the exact point the inline block
used to sit — after the chop filter, before the weighted-score/exhaustion/confidence
chain — and unpacks its six return values (`ce_signal`, `ce_score`, `ce_factors`,
`pe_signal`, `pe_score`, `pe_factors`) into the same local variables the rest of the
function already consumed identically.

Alongside the extraction, the method now also returns an `observability` block making
the trend/trigger/confirmation breakdown inspectable per-direction:
```
{"CE": {"trend": "PASS"/"FAIL", "trigger": "PASS"/"FAIL",
        "confirmations": {"candle":.., "rsi":.., "vwap":.., "volume":.., "oi":..},
        "final": "PASS"/"FAIL", "reason": "trend"/"pullback_trigger"/"confirmation_score"/None},
 "PE": {...same shape...}}
```
This is populated by recording each condition's outcome at the exact point it already
fires in the (unmodified) scoring code — it does not branch on anything new, and does not
change `ce_score`/`pe_score`/`ce_signal`/`pe_signal`/`ce_factors`/`pe_factors` in any way.
It is attached to `generate_signal()`'s existing `details` dict as `details["pullback_strategy"]`,
which means it automatically flows through the *existing* signal-logging pipeline
(`entry_engine.py`'s `_log_signal_snapshot()` → `log_decision_event()`/`db.log_signal()`)
with no new logging plumbing required.

A parallel `logging.debug()` line is emitted in the exact format requested — e.g.
`STRATEGY_PULLBACK direction=CE trend=PASS trigger=PASS candle=PASS rsi=PASS ... result=PASS`
— but only when the trend precondition at least held (i.e. not on every one of the ~2
ticks/second where neither EMA relationship is even in play), to avoid flooding the debug
log at the 500ms polling rate with no additional information.

---

## 2. FILES CHANGED

| File | Why |
|---|---|
| `strategies/smart_scalp_v3.py` | The only file touched. Added `import logging` (line 26); added the new `evaluate_pullback_strategy()` method (inserted before `generate_signal()`, ~232 new lines); replaced the inline CE/PE block inside `generate_signal()` with a call to the new method plus unpacking of its six return values and one new `details["pullback_strategy"] = ...` line (~119 lines removed, ~17 lines added at the call site). Net: +232/-119 = +113 lines. |

**No other file was modified.** Confirmed by `git diff --name-only` returning exactly one path, and by `git diff --stat` against `core/risk/`, `core/engines/position_size_engine.py`, `core/engines/exit_engine.py`, `core/trading/`, `.env`, and `config/` all returning empty.

---

## 3. BEHAVIOUR PRESERVED

- **Thresholds unchanged**: `self.min_score`, the 0.5% EMA9-proximity band, the RSI 45/55 (CE) and 45/35 (PE) bands, `VWAP_ENABLED`, `OI_CHANGE_ENABLED` — all read from the exact same names/constants, none altered.
- **Indicators unchanged**: `calculate_indicators()` was not touched; the new method reads `Close`/`Prev_Close`/`High`/`Low`/`EMA_9`/`EMA_21`/`RSI` from the same `indicators` dict `generate_signal()` already computed, using the same `.get()` calls with the same defaults.
- **Pullback conditions unchanged**: verified line-by-line against the pre-extraction version (§5 below) — every `if`, every point increment, every factor string, is copied verbatim; only parallel boolean-recording (`ce_confirmations[...] = ...`) was interleaved, which never gates or alters the original branches.
- **Risk unchanged**: `git diff --stat -- core/risk/` is empty.
- **Sizing unchanged**: `git diff --stat -- core/engines/position_size_engine.py` is empty.
- **Execution unchanged**: `git diff --stat -- core/trading/` is empty; `entry_engine.py` was not touched (it calls `smart_scalp_signal()` → `generate_signal()`, whose external signature and 4-tuple return contract are byte-identical to before).
- **Exit unchanged**: `git diff --stat -- core/engines/exit_engine.py` is empty; `.env`'s `EXIT_ONLY_SL_TP_TRAILING` and every other exit-related setting untouched.
- **Momentum/Breakout/Reversal**: no new strategy was created. No new indicator was introduced. No new file was created except this report.
- **Per-direction cooldown/exhaustion** (`TradingState.is_direction_blocked()`): not touched at all — it is still read at the exact same point in `generate_signal()`, after the pullback call, exactly as before extraction.

---

## 4. TEST RESULTS

**Baseline (pre-extraction, `git stash`-equivalent HEAD state), full suite:**
```
FAILED tests/test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware
FAILED tests/test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_no_tz_mismatch_crash
FAILED tests/test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
FAILED tests/test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
```
All 4 are pre-existing and unrelated to Phase 3: the 2 exit-engine-parity failures trace to
this session's own earlier `EXIT_ONLY_SL_TP_TRAILING=true` change (out of scope, Exit Engine
untouched here); the 2 visual-records failures trace to today's live trading session having
written real (non-zero) trade data into the log directory those tests read from, making
their "expect zero trades in this window" assertions fail against real, current-day data —
neither touches `strategies/`, `core/engines/entry_engine.py`, or anything Phase 3 modified.

**Post-extraction, full suite (identical command):**
```
FAILED tests/test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware
FAILED tests/test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_no_tz_mismatch_crash
FAILED tests/test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
FAILED tests/test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
```
**Identical set, identical count, identical position in the run. Zero new failures. Zero
newly-fixed failures.**

**Targeted tests** (`tests/test_smart_scalp_confidence.py`, `tests/test_entry_engine_cross_direction.py`):
```
16 passed, 1 skipped   (identical before and after)
```

**Syntax/import validation:**
```
python -c "import ast; ast.parse(open('strategies/smart_scalp_v3.py').read())"  → OK
python -c "import strategies.smart_scalp_v3 as m; m.SmartScalpV3()"             → OK, has evaluate_pullback_strategy: True
```

---

## 5. BEHAVIOURAL COMPARISON

A dedicated equivalence harness (built and run, then fully deleted — no artifact left in the
repo) loaded the git-HEAD (pre-extraction) version of `strategies/smart_scalp_v3.py` under a
separate module name **placed at the correct directory depth** (a first attempt using `/tmp`
broke `_project_root = Path(__file__).resolve().parent.parent`, silently changing which
`config/strategy.json` values the OLD instance read — a test-harness artifact, caught,
diagnosed, and corrected before drawing any conclusion; the corrected run is what is reported
here). Both OLD and NEW instances had `check_premium_filter`, `get_option_delta`, and
`market_quality_engine.evaluate` stubbed identically to force-pass the gates that run before
the Pullback block, and had `calculate_indicators()` stubbed to return hand-crafted indicator
dicts covering the requested case matrix, so only the code under test (the extracted block)
could differ between the two runs.

**Eight cases exercised, covering every branch of the extracted logic:**
```
CE valid pullback, full confirmation           → MATCH
CE invalid trend (EMA9 < EMA21)                → MATCH
CE invalid proximity (price far from EMA9)     → MATCH
PE valid pullback, full confirmation           → MATCH
PE invalid trend (EMA9 > EMA21)                → MATCH
PE invalid proximity (price far from EMA9)     → MATCH
CE confirmation-missing (score sits at min_score boundary) → MATCH
PE confirmation-missing (score sits at min_score boundary) → MATCH
```

For every case, `signal`, `direction`, `confidence`, `ce_score`, `pe_score`, `ce_factors`,
`pe_factors`, and the rejection `reason` string were compared field-by-field between OLD and
NEW. **All eight matched exactly, in every field.** This directly exercises: the trend
short-circuit (both pass and fail, both directions), the trigger condition (both pass and
fail, both directions), and all five confirmation conditions (candle/RSI/VWAP/volume/OI)
individually toggling under both true and false, for both directions — which is every
distinct code path the extraction touched.

**Pre- and post-extraction Strategy decisions matched in all cases tested. No discrepancy found.**

---

## 6. REMAINING PHASE 3 ISSUES

None discovered that require action within Phase 3's boundary. Two things are worth
recording as genuine, narrow observations (not implemented, not proposed as changes):

1. The equivalence harness's own `/tmp`-loading artifact (§5) is a reminder that this
   codebase's config loading is directory-depth-sensitive (`_project_root` via `__file__`).
   This is pre-existing behaviour, not something Phase 3 introduced or should fix.
2. `calculate_bullish_score()`/`calculate_bearish_score()` (Phase 0/1's likely-dead-code
   finding) remain exactly as they were — present, unreferenced by `generate_signal()`
   (which now calls `evaluate_pullback_strategy()` instead of either the old inline block or
   these methods, same as before extraction). Per Step 9's explicit instruction, this was
   documented, not removed.

---

## 7. PHASE 4 HANDOFF

Phase 4 will address **SCORING SIMPLIFICATION**, per Phase 2 §E/§N:

```
Setup Score
    +
Weighted Score
    +
Adaptive Confidence
        ↓
single simplified Strategy confirmation
```

Concretely, and only as a pointer for Phase 4 to pick up (not started, not implemented here):
`evaluate_pullback_strategy()` now returns `ce_score`/`pe_score` (cumulative points) exactly
as before, but the underlying `observability` structure it also returns already carries the
PASS/FAIL-per-condition shape (`trend`, `trigger`, `confirmations{candle,rsi,vwap,volume,oi}`)
that a future binary-confirmation redesign would need — this extraction did not build that
redesign, but it did leave the data already computed in a form that would make it easier to
attempt, should Phase 4 choose to use it as a starting point.

**No Phase 4 code was implemented in this task.**

