# PTQ SCALPING BOT — PHASE D: STRATEGY SELECTION + MARKET ANALYSIS ARCHITECTURE
## IMPLEMENTATION RECORD
### The live decision path (`generate_signal()`) is byte-identical to before this phase. Every addition is a new, additive, currently-unconsumed capability — confirmed by direct diff, not argued.

---

## 1. FILES CREATED

None. (Every addition this phase lives inside the 5 modules Phase C already created.)

## 2. FILES MODIFIED

```
strategies/pullback_strategy.py   232 -> 275 lines  (+43: as_candidates(), Rule 5)
strategies/selector.py             41 ->  77 lines  (+36: select_strategy(), Rule 7)
strategies/market_context.py      273 -> 334 lines  (+61: candle_structure(), Rule 11)
```

**`strategies/smart_scalp_v3.py` — untouched.** Confirmed by direct `diff` against a
snapshot taken *before* this phase's first edit (Rule 19's own instruction, honoured
this time — Phase C's process gap not repeated): byte-identical. `strategies/
market_gate.py` — also confirmed byte-identical, untouched.

`core/backtest.py` (12 lines) and `core/engines/state_machine.py` (19 lines) carry
only Phase 6's prior, already-reported diff — re-confirmed by `git diff --stat`
matching those exact numbers, zero addition from this phase.

## 3. FILES DELETED

None.

---

## 4. EXISTING STRATEGIES

Re-audited fresh (Rule 1), not assumed from the Phase C report: `find strategies
-name "*.py"` still returns exactly 7 files, no `breakout_strategy.py`/
`momentum_strategy.py`/`reversal_strategy.py` anywhere. **One real, executable
strategy: `pullback_strategy.py`.** No second or third strategy was invented this
phase, per Rule 2 — `as_candidates()` reshapes the one existing strategy's output;
it does not create a new strategy.

## 5. MARKET CONTEXT BOUNDARY

Unchanged responsibility: "what is the market doing?" `compute_indicators()` itself
was not touched. One addition — `candle_structure(indicators)` — reads an
already-built indicators dict and returns `direction` (from the same Close-vs-
Prev_Close comparison `pullback_strategy.py` already uses for its own Green/
Red_Candle confirmation, not a new rule), `range` (High−Low), and
`close_position_in_range` (exact, needs no Open). **Explicitly does not expose**
`body`/wick measures or a candle sequence — see §11 for why, stated as a limitation
rather than worked around with an approximation that was tested and found to break.

## 6. MARKET GATE BOUNDARY

**Unchanged.** `market_gate.py` was not opened this phase — confirmed by direct
diff against the pre-phase snapshot, byte-identical. No new condition was added, per
Rule 4/14.

## 7. STRATEGY BOUNDARY

Unchanged responsibility and unchanged existing return shape
(`evaluate_pullback_strategy()`'s dict: `ce_signal/ce_score/ce_factors/pe_signal/
pe_score/pe_factors/observability`, byte-identical). One addition —
`as_candidates(pullback_result)` — reshapes that same, already-computed data into
the Rule 5 candidate format (`{"strategy", "direction", "passed", "score", "reason",
"factors"}`), one entry per direction whose trend precondition held. No score
recalculated, no threshold re-applied; `ce_signal`/`pe_signal` (the actual gates)
are read, never touched.

## 8. SELECTOR BOUNDARY

`select_direction(pullback_result)` (Phase C) — **unchanged**. New:
`select_strategy(strategy_results: List[Dict])` — the Rule 7 forward-looking,
list-shaped interface. Given today's exactly-one-strategy reality, it returns the
one passing candidate (if any) from a list built by `as_candidates()`, in the same
CE-before-PE order `select_direction()` has always used — by construction, not by a
newly invented priority. If it is ever handed more than one simultaneously-passing
candidate, **it raises rather than silently picking a winner** — there is no
existing conflict-resolution rule to extract (Phase A/B's audit found zero, Phase
D's own audit re-confirmed zero), so Rule 7 forbids inventing one; a future
multi-strategy phase is where that logic belongs, extracted from real behaviour at
that point.

## 9. SCORE/CONFIDENCE BOUNDARY

**Unchanged, not opened this phase.** `strategies/scoring.py`,
`core/engines/weighted_score_engine.py`, `core/engines/adaptive_confidence_engine.py`
— none touched. The weighted-score and confidence gates remain exactly where Phase
C's own report left them (inline in `generate_signal()`, per the standing Phase B
stop — moving their *gating* role, as opposed to their *packaging*, was flagged as a
trading-rule-adjacent decision in Phase A/B and no approval to cross that line was
given this phase).

## 10. SIZING BOUNDARY

**Unchanged.** `sizing_inputs = {"weighted_score": ..., "confidence": ...}` — the
exact two lines Phase 6 built, byte-identical (confirmed by the whole-file diff
showing `smart_scalp_v3.py` untouched). `PositionSizeEngine` not opened.

## 11. REMOVED DEAD CODE

None removed this phase. `Squeeze_Breakout!`'s dead branch (flagged, not removed,
in Phase C) remains exactly as it was — re-confirmed present and still unreachable
(`Was_Squeeze` still hardcoded `False`) in this phase's fresh audit (§ audit report,
"DEAD CODE").

**Candle body/wick — attempted, then deliberately not shipped.** Rule 11 asked for
body/upper-wick/lower-wick "if possible from existing data." An implementation using
`Prev_Close` as an Open stand-in was built and tested, and found to produce a
negative wick value on real synthetic data (`Prev_Close` can fall outside the
current chunk's own `[Low, High]` band, because it comes from the *previous*,
non-overlapping chunk) — a value with no sensible reading as a candle shape. Rather
than ship a labelled-but-broken approximation, `body_approx` and `recent_sequence`
are returned as explicit `None` with the reason documented in the function's own
docstring, per Rule 15's spirit ("সন্দেহ থাকলে delete করবে না" applied in reverse:
when correctness is in doubt, don't ship it either).

---

## 12. BEHAVIOUR CHANGES

**None. None were detected, and none were attempted.** Every addition this phase is
a new function in a leaf module, called by nothing in the live path — confirmed
directly: `grep -n "as_candidates\|select_strategy\|candle_structure"
strategies/smart_scalp_v3.py` returns zero matches. `generate_signal()` — the one
function that decides anything — is byte-identical to its pre-Phase-D state.
No Rule 20 "BEHAVIOUR CHANGE DETECTED" report was needed because no behavior-risking
change was proposed at any point; every genuinely trading-rule-adjacent question
(weighted-score/confidence gate relocation, the four trend computations, the
`Squeeze_Breakout` branch) was left exactly where the standing Phase B stop-list and
this phase's own audit put it.

## 13. EQUIVALENCE RESULTS

A pre-Phase-D snapshot of all six strategy-layer files was taken **before** the
first edit (Rule 19 — Phase C's process gap explicitly not repeated). Direct `diff`
against that snapshot after implementation: `strategies/smart_scalp_v3.py` and
`strategies/market_gate.py` **byte-identical**; `pullback_strategy.py`,
`selector.py`, `market_context.py` differ only by the additive functions listed in
§2, each individually unit-tested (§ inline verification during implementation:
`as_candidates()` correctly reshapes a passing CE result; `select_strategy()`
correctly resolves empty/one-pass/no-pass lists; `candle_structure()` returns exact,
sensible values with the broken approximation removed before shipping). Because the
live decision function was never touched, a full 18-case `generate_signal()`
comparison would necessarily reproduce Phase C's own 18/18 result verbatim — re-run
not performed as a separate artifact since it tests a file proven unchanged; the
byte-identical diff is the stronger evidence for this phase's specific scope.

## 14. TARGETED TEST RESULTS

```
tests/test_position_size_engine.py, test_position_size_integration.py,
test_smart_scalp_confidence.py, test_entry_engine_cross_direction.py,
test_p0_historical_warmup.py, test_time_filters.py, test_snapquote_depth.py,
test_tick_input_repair.py
= 85 passed, 1 skipped   (identical to Phase C's own reported baseline)
```

## 15. FULL SUITE RESULTS

```
FAILED tests/test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware
FAILED tests/test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_no_tz_mismatch_crash
FAILED tests/test_instrument_master.py::test_the_loader_writes_what_this_module_reads
FAILED tests/test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
FAILED tests/test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
```
**Identical 5 failures to Phase C's baseline** (the same set Phase C itself inherited
from Phase 6, including the disclosed date-rollover `test_instrument_master.py`
issue, not touched, per instruction). Zero new failures, zero fixed.

git diff audit: `core/risk/`, `core/trading/`, `core/engines/exit_engine.py`,
`core/engines/position_size_engine.py`, `.env`, `config/` — all empty diff, confirmed
directly. `core/engines/entry_engine.py` — not in the changed-files list at all,
any phase.

---

## 16. REMAINING AMBIGUITIES

1. **`select_strategy()` and `as_candidates()` are not wired into `generate_signal()`.**
   This was a deliberate choice, not an oversight: wiring them in would mean
   `generate_signal()`'s control flow starts reading data through a new path
   (candidate list → selector) instead of its current direct `ce_signal`/
   `pe_signal` checks, and even a provably-equivalent rewiring is a bigger, riskier
   change than this phase's brief asked for ("আর্কিটেকচার পরিষ্কার করার নামে... remove
   weighted-score gate... করা যাবে না" — the same caution extends to touching the
   one function every gate currently lives inside). They exist, tested, ready to be
   wired in a future phase once that specific rewiring is itself scoped and approved.
2. **The `Squeeze_Breakout` dead branch** remains unremoved (§11), a second
   consecutive phase choosing not to touch `pullback_strategy.py`'s scoring body
   for a zero-risk cleanup, in favour of keeping this phase's diff strictly to new,
   additive functions.
3. **Weighted-score/confidence gate relocation** (Phase A/B's flagged Rule-9-relevant
   decision) remains open, unresolved, unattempted — exactly where Phase C left it.
4. **The four trend computations** (Rule 12) were re-verified against Rule 12's own
   explicit test this phase and confirmed genuinely non-mergeable — this is now
   documented twice (Phase 0/2 and Phase D), independently, with the same
   conclusion, which is stronger evidence than either alone.
5. **`recent_sequence` and true candle body/wick** remain genuinely unavailable
   without new data collection (per-chunk Open tracking) that Rule 11 did not
   authorize — flagged as a real gap for a future phase to decide on explicitly,
   not silently left unaddressed.

