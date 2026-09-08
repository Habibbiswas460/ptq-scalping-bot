# PTQ SCALPING BOT — PHASE C: STRATEGY ARCHITECTURE MODULARIZATION
## IMPLEMENTATION RECORD
### 18/18 equivalence cases match. Identical 5 pre-existing test failures before and after. Zero new failures. No trading-rule behaviour changed.

---

## 1. FILES CREATED

```
strategies/market_context.py      (273 lines)  — "what is the market doing?"
strategies/market_gate.py         ( 93 lines)  — "is the market tradable?"
strategies/pullback_strategy.py   (232 lines)  — the one real Strategy: PASS/FAIL
strategies/scoring.py             ( 27 lines)  — thin boundary/re-export, no new engine
strategies/selector.py            ( 41 lines)  — CE/PE resolution, no invented priority
```

Every one of these is a byte-for-byte or parameter-substituted extraction of code that
previously lived inline in `strategies/smart_scalp_v3.py`. None contains a new
threshold, a new condition, or a new formula — each file's docstring says exactly
which original method it was extracted from and states the one class of mechanical
change made (an instance attribute or module constant became an explicit function
parameter, so the extracted code has no dependency on `self`).

## 2. FILES MODIFIED

```
strategies/smart_scalp_v3.py     — 1711 -> 1076 lines (this phase's own reduction;
                                    it is also carrying Phase 3/4/6's prior additions,
                                    still uncommitted, unchanged by this phase)
core/backtest.py                 — UNCHANGED by this phase; its diff (12 lines) is
                                    entirely Phase 6's prior work, re-confirmed by
                                    `git diff --stat` matching Phase 6's own reported
                                    number exactly
core/engines/state_machine.py    — UNCHANGED by this phase; its diff (19 lines) is
                                    entirely Phase 6's prior work, same re-confirmation
```

## 3. FILES DELETED

None. (`calculate_bullish_score`/`calculate_bearish_score` were removed as dead
*methods* from `smart_scalp_v3.py` — see §4 — but no *file* was deleted.)

---

## 4. DEAD CODE REMOVED

Re-verified fresh, immediately before deletion (not carried forward from the Phase
A/B forensic report without re-checking):

1. **`calculate_bullish_score()` / `calculate_bearish_score()`** — re-grepped
   repo-wide immediately before deletion: zero call sites anywhere except their own
   `def` lines. Deleted. A comment in their place records why and points to this
   report.
2. **The `Supertrend` computation** (8 lines inside what is now
   `market_context.compute_indicators()`) — re-grepped repo-wide immediately before
   the extraction was written: zero readers of `indicators['Supertrend']` anywhere.
   Not carried into `market_context.py` at all; a comment marks where it used to be.
3. **NOT removed**: the `Squeeze_Breakout!` dead branch (`Was_Squeeze` hardcoded
   `False`, so `if was_squeeze and ...` can never fire). This is genuinely
   unreachable code, but it is a live *branch inside a scoring loop* someone reading
   `pullback_strategy.py` will still see — removing the branch itself (as opposed to
   the two zero-consumer items above) touches the Strategy's own scoring logic file,
   and the Phase C brief's Rule 1 ("zero trading-rule invention... বর্তমানে যা আছে
   সেটাই preserve করবে") was read conservatively here: the branch cannot fire, so its
   removal cannot change behaviour, but it was left in place this pass to keep this
   phase's diff to code-motion plus two unambiguous, zero-risk deletions, rather than
   also editing the Strategy's own scoring body. Flagged as a clean, low-risk
   follow-up, not silently done.

---

## 5. PUBLIC API COMPATIBILITY

`strategies/__init__.py` was inspected and required **no change** — its existing
three-name export (`SmartScalpV3`, `get_strategy`, `smart_scalp_signal`) was already
exactly the required surface.

`generate_signal(ticks)`'s 4-tuple return (`signal, direction, confidence, details`)
is unchanged. `smart_scalp_signal()`'s `params` dict keys (`direction`, `score`,
`confidence`, `sizing_inputs`, `sl_points`, `tp_points`, `regime`, `factors`,
`details`) are unchanged — none removed, renamed, or added beyond what Phase 6 had
already added (`sizing_inputs`).

**Repo-wide import verification**, run directly (not assumed): every module in the
Phase A/B forensic report's caller list imports cleanly against the refactored code —
```
strategies, strategies.smart_scalp_v3, strategies.market_context, strategies.market_gate,
strategies.pullback_strategy, strategies.scoring, strategies.selector,
core.engines.entry_engine, core.engines.state_machine, core.backtest,
utils.market_readiness_checker, research.backtest.harness
```
all import successfully. The 4 test files newly identified in Phase A/B
(`test_p0_historical_warmup.py`, `test_time_filters.py`, `test_snapquote_depth.py`,
`test_tick_input_repair.py`) plus the already-known targeted suite were run directly
— see §10.

`strategy.evaluate_pullback_strategy(indicators, oi_direction)` — the method Phase 3
established and Phase 6's report referenced — is **still callable exactly this way**;
it is now a 12-line wrapper delegating to `pullback_strategy.evaluate_pullback_strategy()`,
kept as a method (not removed) specifically so any code calling it directly (tests
included) continues to work unchanged.

---

## 6. STRATEGY ARCHITECTURE AFTER REFACTOR

```
ticks
  │
  ▼
strategies/market_context.py   compute_indicators() — EMA/RSI/MACD/VWAP/ATR/BB/KC/
  │                             Volume/Squeeze. Pure. No PASS/FAIL. (Supertrend deleted)
  ▼
smart_scalp_v3.py: premium gate, delta gate, OI calc     (unchanged, still inline —
  │                                                        not in this phase's scope)
  ▼
strategies/market_gate.py      build_market_quality_details() + market_quality_
  │                             rejection_reason() (thin unpack of MarketQualityEngine's
  │                             result, which stays in core/engines/, unmoved) +
  │                             evaluate_chop() (the v3.2 chop detector, verbatim)
  ▼
strategies/pullback_strategy.py  evaluate_pullback_strategy() — the one real Strategy.
  │                               Trend precondition, EMA9-proximity, candle/RSI/VWAP/
  │                               volume/OI confirmation, cumulative setup score,
  │                               PASS/FAIL + full observability. Unchanged math.
  ▼
strategies/selector.py         select_direction() — CE checked before PE (the order
  │                             that already existed); no priority invented. Wired
  │                             additively into generate_signal() as details["selected_
  │                             direction"] — does not replace or gate the existing
  │                             ce_signal/pe_signal control flow.
  ▼
smart_scalp_v3.py: weighted score → exhaustion → confidence   (unchanged, still inline
  │                                                              — see §12 remaining issues)
  ▼
strategies/scoring.py          re-exports WeightedScoreEngine/AdaptiveConfidenceEngine
  │                             (unmoved, in core/engines/) as the named boundary
  ▼
generate_signal()'s return: strategy_decision (Phase 4) + sizing_inputs (Phase 6),
  │                          both unchanged in shape and values
  ▼
entry_engine → state_machine → RiskManager → PositionSizeEngine → broker
  (every one of these: completely untouched by this phase)
```

`strategies/smart_scalp_v3.py` shrank from 1711 to 1076 lines (37%). It is now
orchestration: `SmartScalpV3.__init__` (config + engine wiring), `generate_signal()`
(the sequence above), `get_entry_params()`, `get_strategy()`, `smart_scalp_signal()`,
plus the pieces Phase C's own scope did not name for relocation
(`check_premium_filter`, `get_option_delta`, `update_oi_data`, `get_market_regime`,
`_required_confidence`) — left in place per Rule 19 ("extract, wire, verify — not
rewrite"; the brief's own file list for this phase did not include these).

---

## 7. GATES — CONFIRMATION THAT BEHAVIOUR WAS UNCHANGED

Every one of the 18 gates catalogued in the Phase A/B forensic report (§A3) was
checked against the refactored code:

- Gates 1–2 (warm-up, time filter), 3–4 (premium, delta), the OI calc: **still inline
  in `generate_signal()`, byte-identical**, not moved (outside this phase's named
  scope).
- Gate 5 (Market Quality hard gate): the `MarketQualityEngine.evaluate()` call itself
  is untouched (still in `core/engines/market_quality_engine.py`, still called from
  `generate_signal()` with identical arguments); only the *unpacking* of its result
  into `details[...]` keys moved to `market_gate.build_market_quality_details()` —
  same five keys, same fallback values, verified by the equivalence harness's
  `strategy_decision`/`reason` field comparisons across all 18 cases.
- Gate 6 (chop filter): logic moved to `market_gate.evaluate_chop()` verbatim — same
  three criteria, same "all 3 must fire" threshold, same rejection message format.
  Not exercised as a distinct MISMATCH-triggering path in the 18 cases (none of the
  synthetic indicator sets happened to trigger it), but its code is provably
  unchanged by direct comparison against the pre-extraction text.
- Gate 7 (setup score / Pullback trigger+confirmation): moved to
  `pullback_strategy.evaluate_pullback_strategy()` — the SAME function Phase 3 already
  isolated, now parameter-passed instead of `self`-attribute-read. Directly exercised
  and matched in all 18 equivalence cases.
- Gates 8–11 (weighted score, exhaustion ×2, confidence): **still entirely inline in
  `generate_signal()`, byte-identical** — not moved. Directly exercised via the
  boundary-fail/boundary-pass cases (3–10) and the exhaustion case (18); all matched.
- Gates 12–18 (`entry_engine.py`'s cross-direction, confidence re-check, range,
  premium re-check, spread, session-trend, live-only time+greek): **file not touched
  by this phase at all** (`entry_engine.py` does not appear in `git diff --name-only`).

**No threshold value, no comparison operator, and no gate's position in the execution
order changed.**

---

## 8. 18-CASE EQUIVALENCE RESULT

```
18/18 CASES MATCH — 0 mismatches
```

Methodology, stated precisely because it differs from Phase 3/4/6's in one respect:
those phases snapshotted the pre-change file to a same-directory-depth reference
**before** editing. This phase did not do that proactively (a process gap, disclosed
rather than glossed over) — no committed or stashed "Phase 6 complete" state existed
to diff against, since Phases 3–6 were never committed. The reference used instead
was **reconstructed** from the exact original text captured via this session's own
`Read` tool calls immediately before each edit was made (the calculate_indicators body,
the evaluate_pullback_strategy body, the market-quality/chop block, all captured
verbatim before being replaced) — with the two confirmed-zero-consumer dead methods
(`calculate_bullish_score`/`calculate_bearish_score`) intentionally not restored into
the reference, since by definition nothing calls them and their presence or absence
cannot affect any of the 18 cases' observable output. This is a reconstruction of the
Phase-6-complete *behaviour*, not a literal byte-identical snapshot of that file — a
narrower claim than Phase 3/4/6 could make, stated honestly rather than implied
otherwise.

Cases, matching Phase 6's exact matrix, with results:
```
1  CE strong pass                    MATCH  signal=1 conf=90 wscore=86  sizing_equal=True
2  PE strong pass                    MATCH  signal=1 conf=90 wscore=86  sizing_equal=True
3  CE weighted-score FAIL (41)       MATCH  signal=0                    never reaches sizing
4  CE weighted-score PASS (42)       MATCH  signal=0 (conf too low)     never reaches sizing
5  PE weighted-score FAIL (41)       MATCH  signal=0                    never reaches sizing
6  PE weighted-score PASS (42)       MATCH  signal=0 (conf too low)     never reaches sizing
7  CE confidence FAIL (68)           MATCH  signal=0                    never reaches sizing
8  CE confidence PASS (69)           MATCH  signal=1 conf=69 wscore=86  sizing_equal=True
9  PE confidence FAIL (68)           MATCH  signal=0                    never reaches sizing
10 PE confidence PASS (69)           MATCH  signal=1 conf=69 wscore=86  sizing_equal=True
11 CE low-quality valid              MATCH  signal=0 (conf too low)     never reaches sizing
12 PE low-quality valid              MATCH  signal=0 (conf too low)     never reaches sizing
13 rejected — invalid trend          MATCH  signal=0                    never reaches sizing
14 missing/default indicators        MATCH  signal=0                    never reaches sizing
15 CE/PE ambiguous (flat market)      MATCH  signal=0                    never reaches sizing
16 CE pass, lower sizing inputs      MATCH  signal=1 conf=75 wscore=55  sizing_equal=True
17 PE pass, lower sizing inputs      MATCH  signal=1 conf=75 wscore=55  sizing_equal=True
18 CE exhaustion case                MATCH  signal=0                    never reaches sizing
```

Every numeric value recorded above (86/90, 42/44, 68/69, 63/47, 55/75) is **identical**
to what Phase 6's own report recorded for the same synthetic cases — an independent
cross-check, since Phase 6's numbers were never consulted while writing today's
harness; they simply came out the same, as they should if nothing changed.

---

## 9. POSITIONSIZEENGINE SIZING EQUIVALENCE

For every case that reaches sizing (1, 2, 8, 10, 16, 17), the real
`PositionSizeEngine.calculate()` (unmodified, not opened this phase) was called twice
per case — once with the OLD reference's extracted `weighted_score`/`confidence`,
once with the NEW code's `sizing_inputs` dict — and `score_multiplier`,
`confidence_multiplier`, `market_quality_multiplier`, `regime_multiplier`, `lots`, and
`position_size` were compared. **All six fields matched exactly in all six cases.**
Cases 16/17 are the load-bearing proof: they deliberately use sizing inputs (55/75)
different from every other passing case (86/90, 69/86), so a match there rules out
the extraction accidentally reading a stale or default value.

---

## 10. TARGETED TEST RESULT

```
tests/test_position_size_engine.py ........          8 passed
tests/test_position_size_integration.py ......        3 passed
tests/test_smart_scalp_confidence.py .........s.     10 passed, 1 skipped
tests/test_entry_engine_cross_direction.py .....       5 passed
tests/test_p0_historical_warmup.py ..                 2 passed
tests/test_time_filters.py ......                     6 passed
tests/test_snapquote_depth.py ........................................  40 passed
tests/test_tick_input_repair.py ..........            10 passed
                                                    = 85 passed, 1 skipped
```
The last four files are the additional callers Phase A/B's forensics found beyond
what Phase 6's own baseline checked — included here specifically because this phase
touches the file they import from.

---

## 11. FULL-SUITE RESULT

```
FAILED tests/test_backtest_exit_engine_parity.py::test_soft_loss_exit_fires_at_the_right_simulated_hold_time_tz_aware
FAILED tests/test_backtest_exit_engine_parity.py::test_naive_timestamps_also_work_no_tz_mismatch_crash
FAILED tests/test_instrument_master.py::test_the_loader_writes_what_this_module_reads
FAILED tests/test_visual_records.py::test_cooldown_window_boundaries_come_from_the_observations
FAILED tests/test_visual_records.py::test_the_opening_window_states_that_no_trade_happened_there
```
**Identical 5 failures to Phase 6's own baseline — same names, same count.** Zero new,
zero fixed. Per instruction, `test_instrument_master.py`'s date-rollover failure
(Phase 6's report §6: a hardcoded `08SEP2026` expiry fixture, stale once the session
crossed into 2026-09-09) was **not** touched — confirmed pre-existing, confirmed
reproduced before this phase's changes (it was already present in Phase 6's own
full-suite run) and still present after.

---

## 12. REMAINING ISSUES

1. **`Squeeze_Breakout!`'s dead branch** was not removed this pass (§4.3) — a
   deliberate, disclosed scope narrowing, not an oversight.
2. **Gates 8–11 (weighted score, exhaustion, confidence) remain inline in
   `generate_signal()`**, not extracted into their own module. The Phase C brief's
   own file list (market_context / market_gate / pullback_strategy / scoring /
   selector) did not name a home for them, and Phase A/B's design review flagged
   moving the confidence/weighted-score *gating logic* as a Rule-9-relevant decision
   requiring explicit approval, not a mechanical extraction — left exactly where it
   is, per that standing STOP.
3. **`check_premium_filter`, `get_option_delta`, `update_oi_data`, `get_market_regime`,
   `_required_confidence`** stay in `smart_scalp_v3.py` — none of Phase C's five named
   modules was an obvious home for them (they are orchestration-adjacent helpers, not
   Market Context, Market Gate, Strategy, Scoring, or Selector in the strict sense),
   and moving them was not requested.
4. **The equivalence reference is a reconstruction, not a saved snapshot** (§8) — a
   process gap for this phase specifically; future phases touching this file should
   snapshot before editing, as Phases 3, 4, and 6 did.
5. Test-file-level fixes (`test_instrument_master.py`'s date fragility) remain
   explicitly out of scope, as instructed.

---

## 13. NO ARCHITECTURAL DECISIONS WERE STOPPED THIS PHASE

Every extraction attempted (Market Context, Market Gate's two pieces, Pullback
Strategy, Scoring's boundary, Selector's CE/PE resolution, the two dead-code
deletions) turned out to be mechanically safe — none required inventing a threshold,
a priority, or a new condition, and none hit an ambiguous-ownership question that
couldn't be resolved by "leave it where Phase A/B's design review already said to
leave it." The five items in §12 are scope boundaries this phase chose not to cross
(matching the brief's own Rule 19 and the standing Phase B stop-list), not blocked
decisions requiring a fresh STOP report.

---

## FINAL STATEMENT

```
No trading-rule behaviour was intentionally changed.
No threshold was changed.
No existing gate was removed.
No risk/execution/exit behaviour was changed.
Strategy was modularized without changing its observable decisions.
Sizing inputs remain explicitly separated from Strategy PASS/FAIL.
```

