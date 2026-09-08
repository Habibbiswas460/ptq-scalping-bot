# PTQ SCALPING BOT — PHASE 5: SIZING-INPUT SEPARATION (FORENSICS + STOP REPORT)
### Forensics-only, as scoped. No code was modified in this phase — evidence led to a documented STOP at Step 4, with the underlying claim proven empirically rather than merely argued.

---

## Correction to the prompt's file references

The brief cites `core/trading/entry_engine.py` and a bare `state_machine.py`. Both live under
`core/engines/`: `core/engines/entry_engine.py` and `core/engines/state_machine.py`. Verified
directly (`find . -name entry_engine.py -o -name state_machine.py`) before using either path
anywhere below.

---

## STEP 1 — CONTRACT MAP

### 1. Current producer of `weighted_score`

`strategies/smart_scalp_v3.py`, inside `generate_signal()`. The raw percentage is computed by
`self.calculate_weighted_score()` → `WeightedScoreEngine.score()` (unchanged since Phase 0).
It is written to `details["weighted_score"]` at **exactly two points**, confirmed by direct
grep (no other producer exists):
```
line 1476:  details["weighted_score"] = ce_weighted_pct   # inside "if ce_signal and not ce_exhausted:"
line 1514:  details["weighted_score"] = pe_weighted_pct   # inside "if pe_signal and not pe_exhausted:"
```
Both sites are reached **only after** trigger/confirmation, the weighted-score threshold
itself, and the exhaustion check have all already passed for that direction — i.e. by the
time `details["weighted_score"]` is ever set, the Strategy's own decision for that direction
is already final in every case except the confidence check immediately following.

### 2. Current producer of `confidence`

Same function, same two blocks, immediately after `details["weighted_score"]` is set:
`self.calculate_adaptive_confidence(...)` → `AdaptiveConfidenceEngine.score()`. `confidence`
is also the third element of `generate_signal()`'s 4-tuple return, so it reaches every caller
of `generate_signal()`/`smart_scalp_signal()` directly, not only through `details`.

### 3. Every caller and consumer (traced exhaustively, not sampled)

| Consumer | File:line | Role |
|---|---|---|
| `smart_scalp_signal()` wrapper | `smart_scalp_v3.py:1529-1610` | Copies `details.get('weighted_score')` into `params["score"]`, `confidence` into `params["confidence"]`, on **both** the failure path (`params["confidence"]` only — no `"score"` key at all on failure, see note below) and the success path (`params["score"]` and `params["confidence"]` both present) |
| `entry_engine.py`'s `entry_signal()` | `core/engines/entry_engine.py:292-299` | `enriched_params = dict(params)` then adds 4 unrelated keys (`signal_ltp`, `signal_spot_price`, `signal_timestamp`, `signal_recorded_at`). **Does not read, write, or touch `score`/`confidence` at all** — confirmed by grep, zero matches for those keys in this function body. `last_signal_params = enriched_params` (module global) |
| `entry_engine.py`'s `_log_signal_snapshot()` | `core/engines/entry_engine.py:82-118` | Reads `details.get('weighted_score')` for `db.log_signal()` — **analytics/DB only**, confirmed no live-decision use in this function |
| `core/services/database.py` | multiple | Persists `weighted_score`/`confidence` as DB columns for the `dvf_signals` analytics table — read extensively by `research/*` tooling (Phase 0 already catalogued this), never fed back into a live decision |
| `core/validation/signal_logger.py:86` | `params.get("score", details.get("weighted_score"))` | Same DB/analytics role |
| `core/engines/state_machine.py:835-848` (`state_entry_ready()`) | `weighted_score = signal_params.get('score', details.get('weighted_score', 0))`; `confidence = signal_params.get('confidence', 0)`; both passed directly into `PositionSizeEngine.calculate(weighted_score=weighted_score, confidence=confidence, ...)` | **The live sizing consumer** — the one that matters |
| `core/backtest.py:297-316` (`_enter_trade()`) | `weighted_score = float(details.get('weighted_score', details.get('score', 0)) or 0)`, passed into a **second, separate** `PositionSizeEngine.calculate()` call | **A second live sizing consumer**, for the offline backtest harness — same pattern, same risk profile, not previously flagged in Phase 4's report (Phase 4 only named the live `state_machine.py` path) |
| `strategy.py`'s own `runtime_state.set_strategy_decision(score=..., confidence=...)` | `smart_scalp_v3.py:1633-1640, 1677-1684` | Writes into `RuntimeState.caches["decision"]` (`core/runtime/state.py:199-219`). Grepped repo-wide for any reader (`get_strategy_decision`, `.strategy_decision`) — **zero results**. Confirmed dead/telemetry-only, no consumer of any kind currently exists |

**Note on the failure path**: `smart_scalp_signal()`'s failure-path return dict
(`smart_scalp_v3.py:1652-1657`) has no `"score"` key at all — only `"confidence"`. This is
irrelevant to sizing, proven in item 7 below: a failed signal never reaches the code path
that calls `PositionSizeEngine`.

### 4. Exact arguments passed into `PositionSizeEngine`

Live path (`state_machine.py:846-856`):
```python
allocation = size_engine.calculate(
    capital=..., risk_budget=..., weighted_score=weighted_score, confidence=confidence,
    market_quality=market_quality, regime=regime, volatility={'vix': state.estimated_vix},
    recovery_mode=..., daily_loss_state=..., sl_points=sl_points, lot_size=lot_size,
)
```
Backtest path (`core/backtest.py:299-314`): same parameter names, same `weighted_score`/
`confidence` arguments, different (offline) values for the rest.

### 5. Exact formulas — `score_multiplier` and `confidence_multiplier`

Re-read directly from `position_size_engine.py:297-301`, confirmed unchanged since earlier
sessions:
```python
def _score_multiplier(self, weighted_score):
    return self._linear_scale(float(weighted_score), 0.0, 100.0, self._range("score"))
def _confidence_multiplier(self, confidence):
    return self._linear_scale(float(confidence), 0.0, 100.0, self._range("confidence"))
```
Both are linear interpolations of the raw 0-100 input onto a configured multiplier range
(`DEFAULT_CONFIG["ranges"]["score"/"confidence"] = [0.80, 1.10]`), then folded into
`_soft_adjustment_multiplier()` — a weighted sum of `(multiplier - 1.0) * weight` across 7
factors (score weight 0.18, confidence weight 0.18) — which scales `base_risk_amount`,
capped, then floor-divided by `sl_points * lot_size` to get `lots`. The **magnitude** of
`weighted_score`/`confidence`, not merely their pass/fail state against a threshold, directly
determines this multiplier and therefore the final lot count.

### 6. Any other live numeric consumer?

Exhaustively re-checked in this phase (Step 1 explicitly required this, not assumed from
Phase 4): no third live consumer was found. The only two are `state_machine.py` (live
trading) and `core/backtest.py` (offline backtest) — both confirmed identical in kind
(both feed `PositionSizeEngine`, both are downstream-only, neither transforms the values).

### 7. Can the Strategy return contract change without changing sizing?

**Only if sizing continues to receive the identical numeric values on the identical set of
paths it currently receives them on.** This was verified, not assumed, by tracing
`state_idle()` (`core/engines/state_machine.py:651-751`): a signal that fails at *any* stage
of `generate_signal()`'s chain returns `has_signal=False` from `entry_signal_func(tick)`,
causing `state_idle()` to `return "IDLE"` **without ever transitioning to `"ENTRY_READY"`** —
and `state_entry_ready()` (the function containing the sizing call) is *only* invoked when
the state machine is in the `"ENTRY_READY"` state. **A rejected signal's `weighted_score`/
`confidence` — whatever they happened to be, even if computed — never reaches
`PositionSizeEngine` under the current architecture, because sizing is never invoked for a
rejected signal at all.** This was proven empirically in a standalone script (not merely
argued): a signal engineered to pass every gate was traced hop-by-hop —
`generate_signal()` → `smart_scalp_signal()` wrapper → `entry_engine.py`'s
`enriched_params` → `state_machine.py`'s extraction → `PositionSizeEngine.calculate()` —
and `weighted_score=86`, `confidence=90` arrived **byte-identical at every hop**, producing
`score_multiplier=1.058`, `confidence_multiplier=1.07`, `lots=1`, `position_size=65`.

---

## STEP 2 — THE SEPARATION, AS DESIGNED, ALREADY EXISTS FOR THE PART THAT MATTERS

The requested contract:
```
A. Strategy decision:  PASS / FAIL + rejection attribution
B. Quality/sizing inputs:  weighted_score: numeric, confidence: numeric
```

Phase 4 already built (A) as an explicit, separate structure: `details["strategy_decision"]
[direction]["final"]` (PASS/FAIL) and `["failed_at"]` (rejection attribution), populated
alongside — never in place of — the raw `weighted_score`/`confidence` numbers, which
continue to be computed by the unchanged `WeightedScoreEngine`/`AdaptiveConfidenceEngine`
and returned unchanged in `details["weighted_score"]` and the `confidence` tuple element.

(B) was never at risk: **the numeric values are never discarded, overwritten, normalized, or
converted to booleans anywhere in the traced path** — confirmed by Step 1's line-by-line
read of every hop. The only sense in which "A" and "B" are not separate today is
*conceptual*: the same threshold check on `weighted_score`/`confidence` serves two purposes
simultaneously — deciding whether `ce_signal`/`pe_signal` survives (Strategy's PASS/FAIL,
part A) and, if it survives, providing the raw number sizing later uses (part B). This is
not a data-corruption risk; it is a design choice about what the numbers *mean*.

---

## STEP 3 — DATA-FLOW DIAGRAM

**Current (verified, not assumed):**
```
Pullback Strategy (evaluate_pullback_strategy, Phase 3)
        ↓ ce_signal/pe_signal (boolean, gates continuation)
Weighted Score (WeightedScoreEngine.score(), unchanged)
        ↓ ce_weighted_pct/pe_weighted_pct — ALSO gates continuation (< threshold -> signal False)
          AND is stored verbatim in details["weighted_score"] if the direction survives
Exhaustion check (unchanged) — gates continuation
        ↓
Adaptive Confidence (AdaptiveConfidenceEngine.score(), unchanged)
        ↓ confidence — ALSO gates the final PASS/FAIL (< required_conf -> signal 0)
          AND is returned verbatim as generate_signal()'s 3rd tuple element regardless
Entry / State Machine (state_idle -> state_entry_ready, ONLY reached if signal==1)
        ↓ signal_params.get('score'/'confidence') — byte-identical to what generate_signal() produced
PositionSizeEngine.calculate(weighted_score=.., confidence=..)
        ↓ score_multiplier, confidence_multiplier (linear_scale, unchanged formula)
lot size
```

**Proposed, evaluated against the evidence above:**
```
Pullback Strategy
        ↓
Strategy Decision = PASS/FAIL      }  <- (A) already exists (Phase 4's strategy_decision)
    +                               }
Quality/Sizing Inputs = weighted_score + confidence   }  <- (B) already preserved byte-for-byte
        ↓
Entry / State Machine
        ↓
PositionSizeEngine
        ↓ same score_multiplier + confidence_multiplier
        ↓ same lot size
```
**This proposed diagram is not a change from the current one — it is a restatement of what
the current architecture already guarantees**, for the one case that matters (a signal that
reaches sizing at all). The diagrams differ only in whether the separation is *drawn
explicitly*; they do not differ in what data reaches `PositionSizeEngine` or in what
`PositionSizeEngine` computes from it.

---

## STEP 4 — STOP CONDITION

**STOP.** Not because the byte-for-byte guarantee is at risk — it already holds, proven
above — but because there is a genuine, different risk in going further than documenting
this, and the brief's own stop conditions cover it precisely.

**The exact blocker**: the only way to make `weighted_score`/`confidence` *stop* gating
`ce_signal`/`signal` — i.e. to make them "purely quality/sizing inputs" in the sense the
brief's Step 2 contract implies, decoupled from whether a trade happens at all — is to
remove or relax the threshold checks at `smart_scalp_v3.py`'s weighted-score and confidence
stages (currently: `if ce_weighted_pct < self.min_weighted_score_pct: ce_signal = False`,
and the analogous confidence check). Doing so would mean **setups that are currently
rejected outright — because their weighted score or confidence is too low — would instead
become trades**, sized down by the now-lower multiplier rather than blocked entirely. This
is not a plumbing change; it is a change to which market states produce a trade at all,
which is:
- a **Strategy decision change** (the Strategy's PASS/FAIL would no longer mean what it
  means today — a signal object that currently means "this cleared every bar" would instead
  mean "this cleared the trigger/confirmation/exhaustion bars only, with the sizing engine
  left to compensate for lower-quality ones"), explicitly the kind of change every phase's
  rules have forbidden ("do not change execution behaviour unless absolutely required");
- a de facto **risk-exposure change** (capital now gets committed to setups the system
  currently refuses to trade at all, even if sized smaller — those setups' downside is not
  proportionally smaller than their reduced size implies, since SL/TP/exit behaviour is
  identical regardless of entry quality); and
- a change to **RiskManager's own streak/cooldown counters** (`consecutive_losses`,
  `is_direction_blocked()`), since the population of trades placed changes, which changes
  when those counters trip — a second-order Risk-layer behaviour change, also out of every
  phase's stated bounds.

This matches the brief's own Step 4 instruction precisely: *"If achieving this separation
requires changing the mathematical sizing formula, changing lot-size behaviour, changing
risk limits, or changing the meaning/range of weighted_score or confidence: STOP."* The
sizing *formula* would not change, and the numeric *range* (0-100) would not change — but
the **meaning** of what `signal==1` represents would change, and that is exactly the
substance that formula/range are proxies for in the brief's own framing.

**The smallest architectural change that WOULD achieve full separation**, reported per Step
4's instruction rather than implemented: introduce a second, independent quality metric —
call it a "sizing weight" — computed from the *same* underlying `WeightedScoreEngine`/
`AdaptiveConfidenceEngine` machinery but **never gating** `ce_signal`/`signal`, while the
existing thresholds keep gating exactly as they do today using the *current* `weighted_score`/
`confidence`. `PositionSizeEngine` would then read the new, purely-informational weight
instead of the gating numbers. This requires no change to what counts as a valid signal (the
existing gates stay exactly as strict as they are today) and no change to
`PositionSizeEngine`'s formula — only a change to *which number* it is handed. But it does
require touching `state_machine.py`'s call site (to pass the new weight instead of the old
gating number) and arguably `PositionSizeEngine`'s parameter semantics/documentation — both
explicitly named as "do not change" surfaces in this phase's own rules, and in every prior
phase's rules. **This is Phase 6+ work, requiring the owner to explicitly bring
RiskManager/PositionSizeEngine's call contract into scope**, which no phase so far has done.

---

## STEP 5 — IMPLEMENTATION

**Not attempted**, per Step 4's explicit instruction ("Do not implement. Report the exact
blocker...").

---

## STEP 6 — TESTING

**Baseline** (this phase's starting state = Phase 4's completed state), captured before any
further action:
```
tests/test_position_size_engine.py .......... 8 passed
tests/test_position_size_integration.py ...... 3 passed
tests/test_smart_scalp_confidence.py ......... 10 passed, 1 skipped
tests/test_entry_engine_cross_direction.py ... 5 passed
                                             = 27 passed, 1 skipped
```
Full suite baseline (unchanged from the Phase 4 report, since no file changed since then):
4 known pre-existing failures (`test_soft_loss_exit_fires_...`,
`test_naive_timestamps_also_work_...`, `test_cooldown_window_boundaries_...`,
`test_the_opening_window_states_...`), none touching `strategies/` or `entry_engine.py`.

**Post-change**: not applicable — no code was changed. The baseline stands as this phase's
final state.

**Equivalence harness**: not applicable in the "before vs after this phase's code" sense,
since no code changed. Instead, a **dataflow-integrity proof** was run against the current
(unmodified) code to empirically verify the property Step 6 would otherwise have tested for:
a signal engineered to pass every gate (CE, full confirmation) was traced through all five
hops named in Step 1 item 7, confirming `weighted_score` and `confidence` arrive
byte-identical at `PositionSizeEngine.calculate()` and produce a specific, reproducible
`score_multiplier=1.058`, `confidence_multiplier=1.07`, `lots=1`, `position_size=65`. This
directly answers the brief's closing instruction — *"Do not claim 'behaviour preserved'
merely because tests pass. Prove it by comparing the numeric sizing inputs and final
lot-size outputs"* — for the property actually at stake in this phase: whether the current
architecture already delivers what Phase 5 set out to build.

---

## STEP 7 — GIT SCOPE

```
git diff --name-only   ->  strategies/smart_scalp_v3.py   (unchanged from Phase 4 — no new diff this phase)
git diff --stat -- core/risk/ core/engines/exit_engine.py core/trading/ .env config/  ->  empty
```
No file was modified in Phase 5. The single tracked change in the working tree is entirely
Phase 3 + Phase 4's prior work, re-verified untouched by this phase's own `git status` check.

---

## STEP 8 — FINAL REPORT

### 1. What was discovered

The separation Phase 5 set out to build — Strategy PASS/FAIL kept explicit while
`weighted_score`/`confidence` reach sizing byte-for-byte unchanged — **already exists** in
the current (Phase 3 + Phase 4) architecture, for the only case where it matters: a signal
that actually reaches `PositionSizeEngine`. This was not assumed; it was traced hop-by-hop
through five files and confirmed with a live, reproducible numeric trace. The genuinely
unresolved entanglement is conceptual, not a plumbing risk: the *same* threshold checks that
gate whether a trade happens at all also happen to be the numbers sizing later reads, and
untangling that fully (making the numbers purely informational, never gating) would change
which market states produce trades — a Strategy/Risk behaviour change, correctly caught by
this phase's own Step 4 stop condition.

A previously-unflagged detail: `core/backtest.py` is a **second, independent** live consumer
of these exact values into a **second** `PositionSizeEngine` call (offline backtesting) —
not mentioned in the Phase 4 handoff, found here by Step 1's requirement to trace "every
caller and consumer" rather than assuming Phase 4's list was exhaustive.

### 2. Current producer/consumer dependency graph

See Step 1 items 1-6 above (full table with file:line evidence).

### 3. Proposed separated contract

See Step 2/3 above — the proposed contract is structurally identical to the current one for
the live-sizing path; the difference is documentation/explicitness, not data flow.

### 4. Whether implementation was safe

**No implementation was attempted.** The reason is not that it was found unsafe in the
"would corrupt data" sense — the opposite was proven — but that going further than
documenting the existing guarantee would require changing what the Strategy's PASS/FAIL
*means*, which this phase's own Step 4 correctly identifies as out of bounds.

### 5. Exact files changed

None, this phase. (`strategies/smart_scalp_v3.py` carries Phase 3 + Phase 4's prior,
already-reported changes only.)

### 6. Exact files untouched

Every file in the repository, this phase, including `strategies/smart_scalp_v3.py` itself.
`core/risk/`, `core/engines/exit_engine.py`, `core/trading/`, `.env`, `config/` all confirmed
empty-diff, consistent with every prior phase.

### 7. Baseline test results

27 passed, 1 skipped (position-sizing + strategy + entry-engine targeted tests); 4 known
pre-existing failures in the full suite, unchanged from Phase 4's report.

### 8. Post-change test results

Identical to baseline — no change was made.

### 9. Equivalence-harness results

Not applicable in the before/after-code sense. The dataflow-integrity proof (Step 6) is the
Phase 5 equivalent: `weighted_score=86`, `confidence=90` traced byte-identical across 4 hops
into `PositionSizeEngine`, producing `score_multiplier=1.058`, `confidence_multiplier=1.07`,
`lots=1`, `position_size=65` — a concrete, reproducible answer to "does the current system
already guarantee this."

### 10. Remaining blockers

Exactly one, stated precisely in Step 4: separating `weighted_score`/`confidence`'s **gating
role** from their **sizing-input role** requires either (a) accepting that previously-rejected
setups will start becoming trades (a Strategy/Risk behaviour change, forbidden here), or (b)
introducing a second, purely-informational "sizing weight" computed alongside the existing
gates without replacing them — which requires touching `PositionSizeEngine`'s call contract
and/or `state_machine.py`'s sizing call site, both explicitly out of bounds for every phase
run so far, this one included.

### 11. Whether Phase 6 can proceed

**Only if the owner explicitly brings `PositionSizeEngine`'s call contract (and, by
necessity, `state_machine.py`'s `state_entry_ready()`) into scope** — every phase through
Phase 5 has treated both as fixed, and the one substantive path forward identified here (a
second, sizing-only weight, computed but never gating) cannot be built without touching
them. Absent that scope expansion, there is no further safe work in this specific direction;
the two remaining candidates named in Phase 4's own handoff (MQ/Instrument relocation,
explicitly excluded from Phase 5 by this brief's own final instructions) remain the more
plausible next step within `strategies/`-only bounds, and were correctly not attempted here.

