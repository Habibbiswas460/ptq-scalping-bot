# PTQ SCALPING BOT — PHASE 6: SIZING CONTRACT DECOUPLING (IMPLEMENTATION RECORD)
### Implemented, verified with an 18-case equivalence harness plus a real-PositionSizeEngine sizing-output comparison. Every gate untouched; every value byte-identical.

---

## 1. IMPLEMENTED / STOPPED

**IMPLEMENTED.** Step 1's re-verification (fresh, not trusting Phase 5's report) confirmed
`PositionSizeEngine.calculate()`'s own signature already accepts `weighted_score`/
`confidence` as independent numeric parameters — nothing in that file needed to change. The
actual gap was upstream: the *only* way callers currently obtain these numbers is by reading
the same `'score'`/`'confidence'` keys that also happen to gate the signal (`state_machine.py`)
or by reading `details['weighted_score']` directly (`core/backtest.py`) — there was no
dedicated, self-describing field. Phase 6 adds one, additively, and repoints both consumers
to prefer it with the old extraction kept as a fallback.

---

## 2. CURRENT CONTRACT (re-verified fresh in Step 1, not assumed from Phase 5)

| # | Item | File:line | Fact |
|---|---|---|---|
| 1 | `weighted_score` producer | `strategies/smart_scalp_v3.py:1476` (CE), `:1514`→now `:1519` (PE, shifted by this phase's own insertion) | `details["weighted_score"] = ce_weighted_pct`/`pe_weighted_pct`, set only once each direction's chain reaches the confidence block |
| 2 | `confidence` producer | same blocks, line above weighted_score assignment | `confidence, confidence_components = self.calculate_adaptive_confidence(...)` |
| 3 | Consumers | `smart_scalp_signal()` wrapper (`params["score"]`/`params["confidence"]`), `entry_engine.py`'s `_log_signal_snapshot` (DB/analytics), `core/services/database.py` + `core/validation/signal_logger.py` (DB/analytics), `state_machine.py:835-836` (**live sizing**), `core/backtest.py:296-297` (**offline sizing**), `runtime_state.set_strategy_decision` (confirmed dead — zero readers repo-wide) | Re-confirmed exhaustively, matching Phase 5's list exactly |
| 4 | `PositionSizeEngine` arguments | `state_machine.py:846-856`, `core/backtest.py:299-314` | `weighted_score=weighted_score, confidence=confidence, ...` — unchanged keyword names |
| 5 | Multiplier formulas | `position_size_engine.py:297-301` | `_linear_scale(float(X), 0.0, 100.0, range)` for both — re-read fresh, byte-identical to Phase 5's citation |
| 6 | `state_entry_ready()`'s function name | `core/engines/state_machine.py:757` | Confirmed by direct grep, matches Phase 5 |
| 7 | Whether a rejected signal ever reaches `PositionSizeEngine` | `state_idle()`, `core/engines/state_machine.py:651-751` | **No** — `has_signal=False` returns `"IDLE"` without ever transitioning to `"ENTRY_READY"`, the only state whose handler calls sizing. Re-traced line-by-line, not assumed from Phase 5. |

---

## 3. NEW CONTRACT

```python
# strategies/smart_scalp_v3.py — generate_signal(), inside the CE/PE confidence blocks,
# immediately after the existing details["weighted_score"] = ce_weighted_pct assignment:
details["sizing_inputs"] = {"weighted_score": ce_weighted_pct, "confidence": confidence}
# (and the PE mirror, using pe_weighted_pct)

# smart_scalp_signal() wrapper's success-path return dict — alongside, not replacing,
# the existing "score"/"confidence" keys:
"sizing_inputs": details.get('sizing_inputs'),
```

```python
# core/engines/state_machine.py — state_entry_ready(), replacing the single extraction
# line with a preference order: sizing_inputs (new) -> legacy 'score'/'confidence' (old)
_sizing_inputs = signal_params.get('sizing_inputs') or details.get('sizing_inputs')
if isinstance(_sizing_inputs, dict):
    weighted_score = _sizing_inputs.get('weighted_score', <old extraction>)
    confidence = _sizing_inputs.get('confidence', <old extraction>)
else:
    weighted_score = <old extraction, unchanged>
    confidence = <old extraction, unchanged>
```

```python
# core/backtest.py — _enter_trade(), same preference pattern for weighted_score
# (confidence here is already a direct method parameter, not extracted from details,
# so it needed no change — see Step 1 item 3's note on backtest.py's signature)
_sizing_inputs = details.get('sizing_inputs')
if isinstance(_sizing_inputs, dict) and 'weighted_score' in _sizing_inputs:
    weighted_score = float(_sizing_inputs.get('weighted_score', 0) or 0)
else:
    weighted_score = <old extraction, unchanged>
```

**Every existing gate — the `if ce_weighted_pct < self.min_weighted_score_pct:` and
`if confidence < required_conf:` checks — was not touched, not read, not moved.** They
continue to compute `ce_signal`/`pe_signal`/`signal` exactly as before; `sizing_inputs` is
populated from the *same* already-computed local variables, at the *same* point in the
function, and is never consulted by any gate.

### Why Option A (the prompt's own suggestion) over alternatives

A wrapper class, a dataclass, or a `NamedTuple` sizing-payload type were considered and
rejected: `PositionSizeEngine.calculate()`'s signature already takes `weighted_score`/
`confidence` as plain `Number` keyword arguments (Step 1 item 4), so introducing a typed
object would require *also* changing that signature or unpacking it back into scalars at the
call site — extra surface area for zero benefit, and a violation of Rule 4/17. A plain dict
under one new key, read with a fallback, is the smallest change that (a) makes the values
self-describing at their origin, (b) requires zero change to `PositionSizeEngine` itself, and
(c) cannot break any caller that doesn't know about it yet, since the old keys are untouched.

---

## 4. FILES CHANGED

```
core/backtest.py
core/engines/state_machine.py
strategies/smart_scalp_v3.py
```
(`git diff --name-only`, exactly these three — the minimum boundary named in Rule 17:
Strategy → State Machine → backtest.)

`git diff --stat`:
```
core/backtest.py              |  12 +-
core/engines/state_machine.py |  19 +-
strategies/smart_scalp_v3.py  | 463 ++++++++++++-----  (cumulative with Phase 3+4+5's
                                                          prior uncommitted work on this file)
```

---

## 5. FILES GUARANTEED UNTOUCHED

```
core/risk/                          — empty diff
core/engines/exit_engine.py          — empty diff
core/engines/position_size_engine.py — empty diff (never opened for editing — confirmed
                                        its signature already supports the separation, §2)
core/trading/                        — empty diff (broker/execution)
.env                                  — empty diff
config/                               — empty diff
```
Verified directly via `git diff --stat -- <path>` immediately before writing this report,
each returning empty output.

---

## 6. BEHAVIOUR PRESERVATION

Every change in this phase is one of two kinds: (1) a purely additive dict assignment
(`details["sizing_inputs"] = {...}`, `"sizing_inputs": details.get('sizing_inputs')`) that
cannot alter any existing variable by construction, and (2) an extraction *widening*
(`preferred_source or <exact prior expression>`) at exactly three call sites, where the new
preferred source is populated from the identical variables the old expression would have
read, at the identical point in the program. Neither kind touches a threshold, a comparison
operator, `ce_signal`/`pe_signal`, the `signal`/`direction` return values, or
`PositionSizeEngine`'s own code.

This was not merely argued — it was proven with an 18-case equivalence harness (§9) and a
direct, non-code-path-dependent proof that a rejected signal can never reach sizing at all
(§2 item 7, re-traced independently of Phase 5's own claim).

One incidental discovery while re-verifying: a 5th test failure appeared in this phase's
full-suite run that was **not** present in Phase 3/4/5's runs
(`tests/test_instrument_master.py::test_the_loader_writes_what_this_module_reads`). Rather
than assume it was caused by this phase's changes, it was investigated directly: the test's
own fixture hardcodes an option expiry of `08SEP2026`, and `strike_step()` calls
`nearest_expiry()` with no explicit date, defaulting to `datetime.now().date()`. The session
crossed midnight from 2026-09-08 into 2026-09-09 between the Phase 5 and Phase 6 test runs,
so `08SEP2026` — which *was* "on or after today" when Phase 5's baseline ran — is now in the
past, and `nearest_expiry()` returns `None`, cascading to `strike_step()` returning `None`
instead of the expected `50`. **Proven, not assumed**, by stashing this phase's three changed
files (`git stash`), confirming the identical failure reproduces on the unmodified pre-Phase-6
code, then restoring the changes (`git stash pop`) and re-confirming syntax and targeted tests
still pass. This failure is real, but it is a wall-clock artifact of test fixture design,
entirely unrelated to any phase's code — reported plainly rather than hidden or misattributed.

---

## 7. LIVE DATA-FLOW VERIFICATION

A CE signal and a PE signal, each engineered to pass every gate, were traced through all five
hops named in Phase 5's report — `generate_signal()` → `smart_scalp_signal()` wrapper →
`entry_engine.py`'s `enriched_params` (simulated exactly: `dict(params)` plus the four
unrelated keys it actually adds) → `state_machine.py`'s new extraction logic (executed as
real code, not simulated) → `PositionSizeEngine.calculate()` (the real class, unmodified) —
as part of the 18-case equivalence harness (cases 1, 2, 8, 10, 16, 17). Every hop reported the
identical `weighted_score`/`confidence` values the pre-Phase-6 reference produced, and the
resulting `score_multiplier`, `confidence_multiplier`, `lots`, and `position_size` matched
exactly (`sizing_equal=True` in every case that reached sizing — see §9's table).

---

## 8. BACKTEST DATA-FLOW VERIFICATION

`core/backtest.py`'s extraction line was read and verified by direct inspection (its new
`if isinstance(_sizing_inputs, dict) and 'weighted_score' in _sizing_inputs:` branch reads
from the identical `details['sizing_inputs']` dict `generate_signal()` now populates, falling
back to the exact pre-Phase-6 expression `details.get('weighted_score', details.get('score', 0))`
when absent) rather than exercised through the full `Backtester` class, which requires a
historical candle dataset, `exit_engine` state, and equity-curve bookkeeping well beyond this
phase's boundary to stand up in isolation. This is a narrower verification than the live path
(§7) — flagged honestly as such in §11 rather than glossed over — but the change itself is
structurally identical to the proven-safe `state_machine.py` change (same additive-with-
fallback pattern, same source of truth, same untouched `PositionSizeEngine` call), and
`confidence` in `_enter_trade()` was never extracted from `details` at all (it arrives as a
direct method parameter — see §2 item 3's note), so only the `weighted_score` line needed
the same treatment, and did not need — and did not receive — any other change.

---

## 9. EQUIVALENCE RESULTS

18-case harness, pre-Phase-6 snapshot (`strategies/smart_scalp_v3.py` as it stood at the end
of Phase 5, saved to a same-directory-depth reference file to avoid the `_project_root`
artifact discovered and corrected in Phase 3) vs. current working tree, comparing `signal`,
`direction`, `confidence`, `ce_score`, `pe_score`, `ce_factors`, `pe_factors`,
`weighted_score`, `ce_weighted_score_pct`, `pe_weighted_score_pct`, `reason`, and
`strategy_decision`:

```
1  CE strong pass                                    MATCH  (sizing_equal=True)
2  PE strong pass                                    MATCH  (sizing_equal=True)
3  CE weighted-score boundary FAIL (41, thresh=42)    MATCH
4  CE weighted-score boundary PASS (42)               MATCH  (signal=0 — confidence
                                                                organically too low for
                                                                this indicator set; both
                                                                OLD/NEW agree exactly)
5  PE weighted-score boundary FAIL (41)               MATCH
6  PE weighted-score boundary PASS (42)               MATCH
7  CE confidence boundary FAIL (68, req=69 @ MQ A+)   MATCH
8  CE confidence boundary PASS (69)                   MATCH  (sizing_equal=True)
9  PE confidence boundary FAIL (68)                   MATCH
10 PE confidence boundary PASS (69)                   MATCH  (sizing_equal=True)
11 CE low-quality valid (trend+trigger only)          MATCH
12 PE low-quality valid                               MATCH
13 rejected — invalid trend                           MATCH
14 missing/default indicators                         MATCH
15 CE/PE cross-direction ambiguous (flat market)       MATCH
16 CE pass, deliberately lower sizing inputs           MATCH  (wscore=55/conf=75 vs
   (different quality, same PASS decision)                    case 1's 86/90 —
                                                                sizing_equal=True,
                                                                proving DIFFERENT inputs
                                                                still flow correctly)
17 PE pass, deliberately lower sizing inputs           MATCH  (sizing_equal=True)
18 CE exhaustion case (RSI>70 + MACD declining)        MATCH  (signal=0, never reaches
                                                                sizing in either version)

ALL 18 CASES MATCH — ZERO MISMATCHES
```

Cases 3, 5, 7, 9, 13, 14, 15, 18 additionally prove `signal == 0` in both versions and that
`PositionSizeEngine.calculate()` is never invoked for them (the sizing-comparison branch in
the harness only runs `if old_signal == 1 and new_signal == 1`, so these cases have no
`sizing_equal` line — they never reach that code, in either version, by construction).

Cases 16/17 are the specific proof the brief asked for: *"cases where quality/sizing values
differ while the Strategy decision remains the same, if such states are reachable."* They are
reachable, and the sizing outputs correctly reflect the (deliberately different) inputs while
the Strategy PASS decision is unaffected.

---

## 10. TEST RESULTS

**Targeted** (position-sizing + strategy + entry-engine), identical before and after:
```
tests/test_position_size_engine.py ........ 8 passed
tests/test_position_size_integration.py ...... 3 passed
tests/test_smart_scalp_confidence.py ......... 10 passed, 1 skipped
tests/test_entry_engine_cross_direction.py ... 5 passed
                                             = 27 passed, 1 skipped   (unchanged)
```

**Full suite**, this session's true apples-to-apples baseline (captured on the pre-Phase-6
code, after the midnight rollover, via `git stash`) vs. post-Phase-6:
```
BEFORE (pre-Phase-6 code, current wall-clock date):
  FAILED test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_..._tz_aware
  FAILED test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_...
  FAILED test_instrument_master.py::test_the_loader_writes_what_this_module_reads  [NEW —
         date-rollover artifact, confirmed present BEFORE this phase's changes via git stash]
  FAILED test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
  FAILED test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
  = 5 failures

AFTER (post-Phase-6 code, same wall-clock date):
  identical 5 failures, identical names
  = 5 failures

new failures introduced by Phase 6    : 0
failures fixed by Phase 6             : 0
```
The apparent jump from "4" (Phase 3/4/5's reports) to "5" here is **not** a Phase 6
regression — it is explained fully in §6 and independently re-verified via `git stash` in
this section's own "BEFORE" row.

---

## 11. REMAINING ISSUES

1. **Backtest verification is narrower than live verification** (§8) — the extraction line
   was proven correct by direct code inspection and pattern-matching against the
   already-proven-safe `state_machine.py` change, not by exercising the full `Backtester`
   class end-to-end. A future phase (or this session, if asked) could stand up a minimal
   `Backtester` instance with a synthetic candle feed to close this gap fully.
2. **`test_instrument_master.py`'s date-rollover fragility** is a genuine, pre-existing test
   design issue (a hardcoded expiry date with no `on_or_after` override in the assertion),
   unrelated to any phase's work, surfaced only because this session ran past midnight. Not
   fixed here — fixing a test file is outside every phase's stated file-scope boundary
   (Rule 17), and the fix belongs with whoever owns that test.
3. **`market_quality` and `regime`** (the other two `PositionSizeEngine` arguments extracted
   in `state_machine.py:837-838`) were **not** given the same explicit-contract treatment —
   out of scope per the brief's own Step 2 (only `weighted_score`/`confidence` were named).
   If a future phase wants full sizing-input explicitness, those two are the remaining
   generic-key reads.

---

## 12. PHASE 7 HANDOFF

Not implemented here. Two candidates:

**A. Close the backtest end-to-end gap** (§11.1) — a proper `Backtester`-level equivalence
run, not just a code-pattern match, for full parity with §7/§9's live-path rigor.

**B. Extend the explicit contract to `market_quality`/`regime`** (§11.3) — same additive
pattern, same fallback-preserving extraction change, likely the same risk profile as this
phase's own work, since neither currently gates `ce_signal`/`signal` either (both are purely
informational sizing inputs already, per Phase 0's forensics — worth re-confirming fresh
rather than assumed, per this project's own established practice).

Phase 4's original handoff item B (MQ/Instrument/Execution factor relocation out of
`WeightedScoreEngine`/`AdaptiveConfidenceEngine`) remains the larger, still-untouched
architectural target — it legitimately changes the *numeric value* of `weighted_score`/
`confidence` (removing factors from a weighted sum changes the sum), which is a real
behavioural change requiring its own equivalence approach and explicit owner sign-off, not a
continuation of this phase's byte-for-byte-preservation discipline.

---

## REQUIRED ANSWERS

**A. Is Strategy PASS/FAIL now explicitly independent from the numeric sizing inputs?**
Yes. `strategy_decision[direction]["final"]` (Phase 4) and `sizing_inputs` (Phase 6) are two
separate, independently-populated keys in `details`; neither is derived from the other, and
`sizing_inputs`'s presence or values never influence `ce_signal`/`pe_signal`/`signal`.

**B. Does `PositionSizeEngine` receive the exact same numeric values as before?**
Yes — proven in 18 cases (§9), including two cases (16, 17) engineered to produce sizing
inputs that genuinely differ from any other tested case, to make sure the new extraction path
carries the *actual* value through rather than a stale or default one.

**C. Does the final lot size remain exactly the same?**
Yes — `lots` and `position_size` compared field-by-field against the real
`PositionSizeEngine.calculate()`'s output in every case that reaches sizing; all matched.

**D. Can a previously rejected signal now become a trade?**
**No.** Every threshold check (`ce_weighted_pct < self.min_weighted_score_pct`, `confidence <
required_conf`, the exhaustion checks) is byte-identical to the pre-Phase-6 code — not one
comparison operator, threshold value, or gating variable was touched. Cases 3, 5, 7, 9, 13,
14, 15, 18 in §9 each confirm `signal == 0` in both versions, for the same reasons, using the
same numbers.

**E. Were any risk, execution, exit, or broker behaviours changed?**
**No.** `core/risk/`, `core/engines/exit_engine.py`, `core/trading/`, `.env`, and `config/`
all show an empty `git diff --stat` (§5), confirmed directly, not inferred.

