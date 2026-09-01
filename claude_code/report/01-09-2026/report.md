# PTQ Scalping Bot — Complete Investigation & Decision Record

**Date of work: 2026-09-01 (session extended into early 2026-09-02).**
**Purpose of this document:** a complete historical/context record of everything investigated, discovered, fixed, validated, and decided during this pass — so that no important reasoning, finding, fix, or decision is lost from memory. This is a durable engineering decision record, not a summary. It preserves the distinction between **confirmed facts**, **observations**, **hypotheses**, **counterfactual evidence**, **decisions**, and **future plans** throughout.

**Related documents:** `claude_code/fixed.md` is the project's ongoing, chronological fix/status log (all fixes below are also recorded there, in sections §17-§22, alongside the rest of the project's fix history from 2026-08-28 onward). This report is the consolidated, single-session narrative specifically for the 2026-09-01 strategy-layer investigation; `fixed.md` is the living index that keeps accumulating.

---

## 1. Investigation Scope and Objective

**The explicit objective, stated at the start of the strategy-layer phase of this work, was not to preserve the existing architecture for its own sake — it was to move the bot toward actual profitability.** The working agreement was:

- **Keep** existing logic when evidence supports it.
- **Modify** logic when evidence supports it.
- **Remove** logic when it is harmful or unnecessary.
- **Add** new logic when evidence suggests it can improve profitability.

No outcome was preferred in advance. The investigation was explicitly evidence-first, following this workflow on every question raised:

1. Review the investigation / report.
2. Understand and explain the findings.
3. Identify what should be kept, removed, modified, or added.
4. Make the decision based on evidence.
5. Only then define the exact patch/fix.
6. Validate the patch afterward.

**Hard rule applied throughout: do not apply strategy changes merely because a hypothesis sounds plausible.** Several plausible-sounding hypotheses were raised and investigated during this session (RSI exits cutting winners too early, Early Loss Cut being systematically premature, the trailing-stop system giving back profit) — all were investigated with real trade data before any decision was made, and most were **not** acted on because the evidence didn't clear the bar. See §25 for the full list of rejected/parked hypotheses.

This report covers two related but distinct phases of work done in this session:
- **Architecture/reliability fixes** (§17-§22 below, also in `fixed.md` §17-§22) — bug fixes, observability, config validation, dead-code cleanup.
- **Strategy-layer investigation** (§2-§16, §23-§26 below) — entry engine trace, exit engine trace, realized R:R analysis, RSI and loss-side counterfactual investigations — which is the primary subject of this report per the user's request.

---

## 2. Full 2026-09-01 Strategy Analysis

**Confirmed facts**, from `core/data/trades.db`'s `trades` table for `date(entry_time)='2026-09-01'`, and from `logs/2026-09-01/bot.log`/`states.log`:

- **10 total signals/trades** fired during the session (08:14–15:30 IST, paper mode).
- **Exactly two mirror-image setup families fired all day — no other entry logic fired at all:**
  - **Bearish setup → PE:** `EMA9 < EMA21` (required) + `EMA9_Rejection` (price touches EMA9 resistance from below) + `Red_Candle` + `Close<EMA9` + `RSI(N)<45` + (usually) `Below_VWAP` + (usually) `Vol_Spike(Nx)`.
  - **Bullish setup → CE:** `EMA9 > EMA21` (required) + `EMA9_Pullback` (price touches EMA9 support from above) + `Green_Candle` + `Close>EMA9` + `RSI(N)>45` + (usually) `Above_VWAP` + (usually) `Vol_Spike(Nx)`.
- **Score was only ever 62 or 66** across all 10 trades (this is the `WeightedScoreEngine`'s 0-100% output, not the raw pattern-match point count — see §6 for the distinction).
- **Confidence was only ever 77% or 82%** across all 10 trades.
- **Market Quality grade was A+ (92-93/100) on every single trade, with zero exceptions.**
- The day was narrow: roughly 5.5 hours of session time (08:14-15:30), but the entry activity was dominated by one setup family repeating, with real trading activity effectively concentrated in the 09:45-11:21 window (all 10 entries fell in that window; the rest of the session, until 15:30, produced zero further entries — see §2's confidence-gate note below).

### PE trades (3 total)

**Confirmed facts:**
| # | Time | Entry→Exit | Points | ₹PnL | Exit reason | Hold |
|---|---|---|---|---|---|---|
| 1 | 09:45:41→09:47:05 | 11.38→13.28 | +1.90 | +₹123.50 | RSI Reversal (RSI 1→79) | 84s |
| 2 | 09:50:41→09:50:46 | 6.03→5.97 | -0.06 | -₹3.90 | Kill switch: Wide spread | 5s |
| 3 | 10:00:50→10:00:55 | 6.12→5.88 | -0.24 | -₹15.60 | Kill switch: Wide spread | 5s |

- **09:45 trade was a clean winner**: entered on RSI≈43 (pullback into the bearish zone), reversed all the way to RSI≈79, exited via RSI Reversal Exit at +₹123.50.
- **09:50 and 10:00 PE entries were killed by the wide-spread kill switch within ~5 seconds of entry**, at premiums of ₹6.03 and ₹6.12 respectively.
- **Observation/hypothesis at the time these were first read:** these two looked like likely low-premium/tick-size artifacts (a single ₹0.05 NSE tick against a ~₹6 premium is already ~0.85-1% spread, over the 0.6% kill-switch threshold, without any real illiquidity) rather than a genuine strategy failure — this hypothesis was later **confirmed as a real, root-caused bug**, not just a plausible read: see §8 (the CE/PE instrument-switch bug). The entry-time checks (premium filter, spread) had validated a *different* contract's data (a subscribed CE at ~₹98) before the bot flipped to and bought the PE at ₹6.03/₹6.12.
- **Real PE result, counting only the trade that wasn't aborted by the kill-switch bug: 1 win / 1 usable trade (1/1).**

### CE trades (7 total)

**Confirmed facts:**
| # | Time | Entry→Exit | Points | ₹PnL | Exit reason | Hold |
|---|---|---|---|---|---|---|
| 4 | 10:15:12→10:15:22 | 105.06→107.39 | +2.33 | +₹151.45 | RSI EXIT (RSI=85 OB) | 10s |
| 5 | 10:16:28→10:17:34 | 109.61→113.38 | +3.77 | +₹245.05 | RSI EXIT (RSI=81 OB) | 66s |
| 6 | 10:20:10→10:20:29 | 113.87→111.13 | -2.74 | -₹178.10 | Early Loss Cut (ATR-thresh) | 20s |
| 7 | 10:30:16→10:30:27 | 124.39→127.46 | +3.07 | +₹199.55 | RSI EXIT (RSI=81 OB) | 11s |
| 8 | 10:31:00→10:31:10 | 126.14→122.82 | -3.32 | -₹215.80 | Early Loss Cut (ATR-thresh) | 10s |
| 9 | 10:35:21→10:35:36 | 123.43→120.52 | -2.91 | -₹189.15 | Early Loss Cut (ATR-thresh) | 15s |
| 10 | 11:20:45→11:21:03 | 139.61→136.89 | -2.72 | -₹176.80 | Early Loss Cut (ATR-thresh) | 18s |

- **10:15-10:30 produced 3 wins**: +₹151.45, +₹245.05, +₹199.55, all via clean RSI-overbought exits (RSI 81-85), exits occurring 10-66 seconds after entry.
- **10:20-11:20 produced 4 losses**: -₹178.10, -₹215.80, -₹189.15, -₹176.80, all via the ATR-based Early Loss Cut mechanism, exits occurring 10-20 seconds after entry.
- **Observation:** the pattern that emerged was that the pullback-continuation setup worked while the underlying was trending (the 3 wins, 10:15-10:30), then stopped working as conditions changed (the 4 losses, 10:20-11:20), while the strategy kept firing the identical setup type into the new conditions with no adaptation. See §3 for why the regime label shown in the logs during this period cannot be trusted as evidence of what the actual regime was.

**MFE/MAE observations (real data, from `trades.mfe`/`trades.mae`, ÷65 qty to convert ₹→points):**
- Trade #8 (10:31 loss): MFE = ₹0.00 → **zero favorable excursion at any point** before the loss cut. Never once ticked favorable.
- Trade #6 (10:20 loss): MFE = ₹40.95 → **+0.63 points** before falling to the -₹178.10 (-2.74pt) loss.
- Trade #9 (10:35 loss): MFE = ₹11.05 → **+0.17 points**.
- Trade #10 (11:21 loss): MFE = ₹12.35 → **+0.19 points**.

**Confidence-bucket observation (small sample, explicitly not acted on):**
- Score 62 / Confidence 77% bucket (3 CE trades, #4/#5/#6): 2 wins / 1 loss.
- Score 66 / Confidence 82% bucket (7 trades total, #1/#2/#3/#7/#8/#9/#10): 2 real wins / 3 real losses, after excluding the 2 kill-switch-aborted PE trades (#2, #3) which never got a chance to play out on their own merits.
- **Decision at the time:** this was explicitly judged **too small a sample to justify any confidence-threshold-related strategy change** — the lower-confidence bucket outperforming the higher-confidence bucket on a 3-vs-7 split within one session is exactly the kind of noise that later cross-day analysis (§4) confirmed does not replicate.

---

## 3. Regime Label Investigation

**Observation:** every single CE entry on 2026-09-01 was logged in `states.log` with the regime string `📉 BEARISH (50%)` (with a `[EMA↗]` or `[EMA➡]` suffix depending on the specific entry). One PE entry showed `BEARISH (80%)`.

**Initial read:** this looked suspicious — a bullish (CE) trade being tagged "BEARISH" by the system's own regime indicator.

**Root-cause finding, from tracing `core/risk/session_trend.py`'s `SessionTrendTracker`:**
- `get_trend_string()` (the function producing this exact log string) always prefixes with the tracker's **primary combined trend classification** (`self.current_trend`, one of `BULLISH`/`BEARISH`/`SIDEWAYS`) and its confidence percentage — this is a real, computed value that does vary (confirmed by cross-day analysis: on PE-only days 08-28/08-31 the percentage varied across 50%/65%/80%, so the *number* is not hardcoded/inert).
- **However, `can_trade_ce()`/`can_trade_pe()` (the actual gate) has 5 independent OR-conditions**, and the *displayed* primary trend is only one of them. A trade can pass through `can_trade_ce()` via a completely different path (EMA-regime sub-factor reading bullish even while the primary blend reads bearish, RSI<40, short-term 20-tick momentum, or a SIDEWAYS classification) — meaning the trade can genuinely be authorized by the gate for a reason that has nothing to do with the "BEARISH X%" string being logged next to it.
- **Conclusion, stated precisely: the `"BEARISH"` word in this log line is not evidence of what actually authorized the CE trade.** It is one (correctly-computed) input among five, and on 2026-09-01 every CE entry happened to pass via a different one of the five paths than the one being displayed (most likely the EMA sub-factor, inferred from the `[EMA↗]` suffix rule in `get_trend_string()`, though this could not be confirmed with certainty from available logs).

**Explicit rule for future readers: do not treat this label as evidence of the actual market regime, and do not treat its presence/absence as confirming or denying whether a trade was "regime-aligned."** The label is real but incomplete information; the gate's true reasoning requires knowing which of the 5 `can_trade_ce()`/`can_trade_pe()` sub-conditions actually passed, which is not separately logged.

---

## 4. Cross-Day Analysis (2026-08-28, 2026-08-31, 2026-09-01)

**Confirmed facts, from `trades` table queries scoped to each date:**

- **2026-08-28 (10 trades) and 2026-08-31 (13 trades) fired PE only — zero CE trades on either day.**
- **2026-09-01 is the only day in this 3-day window with any CE trades at all (7 of them).**
- **Direct consequence: the "CE has a losing edge" read from 2026-09-01's data alone is not yet an established, multi-day finding.** It is one day, one contiguous ~70-minute losing stretch (10:20-11:20), with zero prior-day CE baseline to compare against. See §25 for the explicit rule against over-interpreting this.

**The recurring exit-type pattern, confirmed across all 33 trades from the 3 days combined:**
- **RSI REVERSAL EXIT → 16/16 wins** (100%, zero exceptions).
- **EARLY LOSS CUT → 8/8 losses (100%).** *(Correction note: an early rough tally during this investigation reported this as "9/9" before the dedicated loss-side investigation in §14 produced a precise, SQL-verified count scoped to exactly the three dates in question: 4 on 2026-09-01 + 3 on 2026-08-31 + 1 on 2026-08-28 = 8 total. The later, precise count is authoritative and used throughout this report; the "9/9" figure was a one-trade overcount from the initial rougher pass.)*
- **SOFT LOSS EXIT → 7/7 losses (100%).**
- **Explicit, important caveat stated at the time this was found, and repeated here: this relationship is partly definitional, not purely an empirical discovery.** RSI Reversal/Smart RSI are profit-side exits by construction (they only fire when the position is already in profit above a floor — see §9's exact thresholds), and Early Loss Cut/Soft Loss Exit are loss-side exits by construction (they only fire when the position is adverse below a threshold). The 100%/100%/100% split is expected given the mechanism design; what would have been surprising (and wasn't observed) is any case of a "small win via early profit-take that then reverses" — the outcomes were binary in this sample, with no middle case, which is the part of this finding that carries real information.

---

## 5. MFE/MAE and "Give-Back" Investigation — Initial Suspicion, Then Correction

**Initial suspicion, raised early in the multi-day loss analysis:** several losing trades had non-trivial MFE (favorable excursion) before ending in a loss — e.g., 08-31's 09:45 trade had MFE ₹92.30, 08-31's 11:20 trade had MFE ₹95.55, 08-28 had two losses with MFE ₹118.30/₹163.15. The initial framing was that these looked like the trailing/breakeven profit-protection system **giving back real, meaningful locked profit**.

**Correction, made after checking these MFE rupee figures against the actual trailing-stop trigger points in *option points* (not rupees):**
- Converting MFE from ₹ to points (÷65 qty): 08-31's 09:45 trade's ₹92.30 MFE = **+1.42 points**; its 11:20 trade's ₹95.55 = **+1.47 points**; 08-28's two losses' ₹118.30/₹163.15 = **+1.82/+2.51 points**; 09-01's one loss with MFE was ₹40.95 = **+0.63 points**.
- **The trailing/breakeven ladder's first activation rung requires +4 points of favorable movement** (`EXIT_BREAKEVEN_TRIGGER_POINTS=4`, locking SL at +2) — **none of these losing trades' MFE came remotely close to 4 points.** The largest, 08-28's ₹163.15 (+2.51pts), is still well under half the trigger.
- **Corrected conclusion: these losing trades never had meaningful locked profit to give back. The trailing/breakeven system was not engaged for any of them, and therefore cannot be blamed for their outcome.** They wobbled slightly favorable (well under the protection threshold) and then reversed into a real loss — a different, more mundane phenomenon than "protection failed to hold."

**Explicit rule for future readers: do not conclude that the trailing-stop/profit-protection system was a major driver of the realized loss outcomes in this dataset.** See §9/§10 for the fuller, later-confirmed version of this finding: the trailing ladder never activated even once across all 33 trades in the 3-day sample, because the largest favorable move any trade achieved (+3.77 points, trade #5 above) never reached the 8-point first real trailing rung either.

---

## 6. Entry Engine — Full Trace

This section documents the complete, code-traced entry decision pipeline as it exists after the fix in §8. Where behavior changed as a result of that fix, both before/after states are noted.

### 6.1 Outer wrapper — `core/engines/entry_engine.py:entry_signal(tick, day_type, instrument_type)`

1. Requires ≥10 recent ticks buffered (`runtime_state.get_recent_ticks(max_items=MAX_RECENT_TICKS)`, `MAX_RECENT_TICKS=120`) — else returns `False, "Warming up..."`.
2. Updates `SessionTrendTracker` (`core.risk.session_trend.update_market_price()`) with the current tick's price, and gets a trend display string (`get_trend_display()`) — used for logging only at this stage, not gating.
3. Calls `smart_scalp_signal(recent_ticks)` (from `strategies/smart_scalp_v3.py`) — the real pattern-detection engine, see §6.2.
4. **If `should_enter` is `False`, none of the checks below run** — the function returns immediately with the rejection reason from `generate_signal()`.
5. If `should_enter` is `True`:
   - **[Fix in §8]** Cross-direction instrument check (new as of the §8 fix) — see §8 for full detail.
   - **Confidence re-check:** `required_conf = MIN_CONFIDENCE_AFTER_3SL (85%) if consecutive_losses >= 3 else MIN_CONFIDENCE (70%)`. Both values are `.env`-driven (`config/constants.py`: `MIN_CONFIDENCE = env_int('MIN_CONFIDENCE', 70)`, `MIN_CONFIDENCE_AFTER_3SL = env_int('MIN_CONFIDENCE_AFTER_3SL', 85)`; confirmed unchanged/matching in live `.env`). This is a **second, independent, flat confidence check**, distinct from `generate_signal()`'s own internal MQ-adjusted confidence check (§6.2 step 12) — see §8's note on how these two interact.
   - **Premium re-check:** `MIN_ENTRY_PREMIUM=70` / `MAX_ENTRY_PREMIUM=350` (`.env`-driven, confirmed matching code defaults). **Before the §8 fix, this checked `tick.get('ltp')` — the currently-subscribed contract's premium, not necessarily the contract about to be traded.** After the fix, checks `execution_tick.get('ltp')` (see §8).
   - **[Fix in §8]** New pre-entry spread sanity check, using `execution_tick`'s bid/ask against the same `KILL_SWITCH_SPREAD` (0.6%) ceiling the mid-trade wide-spread kill switch already enforces.
   - **Session-trend gate:** `can_trade_ce(rsi)` / `can_trade_pe(rsi)` (from `core.risk.session_trend`) — confirmed, via code trace, to be **currently very permissive**: 5 independent OR-conditions per direction (see §3 for the full breakdown), returning `False` only if none of the 5 hold.
   - **Live-mode only** (`if not PAPER_TRADING:` — not exercised by any session analyzed in this report, all of which ran in paper mode): time validation (`validate_time_ptq`) and `greek_gate` — both against `execution_tick` after the §8 fix (previously `tick`).
   - Logs the decision (taken or not, with full params) to the DVF signal table via `_log_signal_snapshot()` regardless of outcome — this is what populates `dvf_signals`, used extensively in the counterfactual investigations (§13/§14).

### 6.2 Pattern-detection engine — `strategies/smart_scalp_v3.py:generate_signal(ticks)`

1. **Time filter:** no trades before 09:45 (hardcoded in-function check against `current_time.hour == 9 and current_time.minute < 45`).
2. **Premium filter** (`check_premium_filter()`): same ₹70-350 band as the outer engine's check, **plus an anomaly guard** — rejects if the current premium is `< 0.35 × median(last 10 valid premiums)`, catching abrupt feed collapses.
3. **Delta filter:** rejects if `delta < 0.35` or `delta > 0.65` — this is a **separate, narrower delta band** from the live-mode `greek_gate`'s own band (`config/constants.py`: `DELTA_MIN=0.25`/`DELTA_MAX=0.75`) — two independent delta filters exist in the codebase with different bounds, though only one runs per code path (this one, in paper/all modes via `generate_signal()`; the other, `greek_gate`, only in live mode).
4. **OI direction classification** (`update_oi_data()`) — feeds scoring (see step 9's `oi` contribution), does not gate on its own.
5. **Indicator calculation** (`calculate_indicators()`) — EMA5/9/21/50, RSI, MACD, Bollinger Bands, VWAP, ATR, volume ratio, etc. **Confirmed via code trace: computed from `tick.get('spot_price', tick.get('ltp', 0))` — i.e., NIFTY spot price is preferred over option premium** (explicit code comment: `# Use spot_price for indicators (NIFTY spot), ltp for option premium`). The newer, preferred "canonical candles" path (`runtime_state.get_canonical_candles()`) also prefers `spot_price` first (confirmed in `core/runtime/state.py`). **This confirms pattern detection is direction-agnostic and instrument-independent — see §7.**
6. **Market Quality Engine gate** (`core.engines.market_quality_engine.MarketQualityEngine.evaluate()`) — 100-point scale (spread 25, liquidity 20, freshness 15, volatility 15, execution 10, greeks 10, session 5), needs `quality_score >= minimum_pct` (`config/strategy.json`: `market_quality.minimum_pct = 70`). **Hard rejects regardless of score:** stale tick (staged: ≤500ms normal, 500-800ms warn, 800-1200ms reject, >1200ms hard-reject), market closed, kill-switch active, WebSocket disconnected, API/exchange unhealthy, circuit breaker open, spread > `max_spread_pct` (constructor default 0.60%), volume below minimum liquidity. **This entire gate reads `latest_tick` — the currently-subscribed contract's tick — which was the other half of the §8 bug** (this gate's own spread/liquidity checks were also validating the wrong instrument on a cross-direction signal; the §8 fix does not re-run this specific engine against `execution_tick`, it adds its own separate, narrower spread check downstream in the outer engine instead — see §8's "not done" list).
7. **Chop filter:** blocks **only when all three** of the following are simultaneously true (explicit code comment: "relaxed from 2+"): EMA9/EMA21 squeeze (<0.8 points apart), low ATR (<3), flat MACD (`abs(macd_hist) < 0.25` and `abs(macd_hist - macd_hist_prev) < 0.2`). One or two chop signals alone never block a trade.
8. **Pattern scoring** — the real, live scoring logic (confirmed via code trace to be the ONLY scoring path actually reachable from `generate_signal()`; see §7's note on the dead duplicate scoring functions). Independent CE and PE point counts computed inline, each requiring `ce_score`/`pe_score >= self.min_score` (`config/strategy.json`: `min_score_to_trade = 4`) to set `ce_signal`/`pe_signal = True`.
9. **Weighted-score confirmation** (`core.engines.weighted_score_engine.WeightedScoreEngine.score()`) — a **second, independent, 0-100% scoring system**, run only for whichever side (CE/PE) passed step 8, requiring `>= self.min_weighted_score_pct` (`config/strategy.json`: `min_weighted_score_pct = 42`). **This weighted percentage — not the step-8 point count — is what gets stored as the `score` field in every trade record** (the 61-66 range observed throughout §2/§4).
10. **Trend-exhaustion veto:** CE blocked if `RSI > 70 and MACD declining`, or if the direction is on its own per-direction cooldown (`state_machine.is_direction_blocked()`); PE mirrors this for oversold+rising MACD.
11. **Adaptive confidence** (`core.engines.adaptive_confidence_engine.AdaptiveConfidenceEngine.score()`) — a **third scoring pass**, weighted: score 30%, market_regime 15%, market_quality 10%, spread 8%, volume 8%, greeks 8%, OI 6%, VWAP 5%, session 5%, freshness 5%.
12. **MQ-adjusted confidence gate** (`_required_confidence()`): `required_conf = min_confidence_pct (base 72, from config/strategy.json) + mq_adjustment`. Adjustments (`config/strategy.json`): **A+/A: -3, B: -1, C: +4, REJECT: +8**. For A+/A grade (100% of all 33 trades observed in this report): `72 - 3 = 69%` internal threshold.
13. If confidence clears that internal 69%/71%/etc. threshold, returns `(1, direction, confidence, details)` — `should_enter=True` — back to the outer engine, which then re-checks against its own **flat** 70% (§6.1). **For every A+/A-grade trade observed (100% of the sample), the outer engine's flat 70% is the effectively binding constraint, not the MQ-adjusted 69% computed here** — see §8's related note on this being a separately-noted, not-yet-acted-on observation.

---

## 7. Direction Selection Logic

**Confirmed facts:**
- Pattern scoring (§6.2 step 8) decides CE vs. PE, not a separate direction-classification step.
- **CE requires `EMA9 > EMA21` as a hard prerequisite** before any other CE-side factor is even evaluated (2 of the required 4 minimum points come from this one condition).
- **PE requires `EMA9 < EMA21`** symmetrically.
- **If both `ce_signal` and `pe_signal` pass their respective ≥4-point/≥42%-weighted thresholds in the same evaluation (theoretically possible, not confirmed to have occurred in the observed sample), CE is checked and returned first** — code order (`if ce_signal and not ce_exhausted: ... return 1, "CE", ...` appears before the PE equivalent block) — there is no score-comparison tie-break.
- **Instrument (contract) selection is a logically separate step from direction detection.** Direction comes from spot-based pattern scoring (§6.2 step 5's confirmed spot-price basis); which specific option contract gets traded is decided later, in `core/trading/broker.py:place_order()`, based on `current_strike` and the determined `direction`.
- **This spot-basis is exactly why pattern detection is direction-agnostic with respect to which contract is currently subscribed** — and exactly why the §8 bug was possible: the direction decision doesn't know or care what's subscribed, but (before the fix) several of the checks downstream of that decision implicitly assumed the subscribed contract was the one that mattered.

---

## 8. Critical Bug: CE/PE Instrument-Switch Mismatch — Full Detail, Fix, and Validation

### 8.1 The bug, precisely

**Before the fix:** after `smart_scalp_signal()` (§6.2) determined a direction, every **instrument-specific** check that ran afterward — premium filter, delta filter, the Market Quality Engine's spread/liquidity/freshness checks (§6.2 step 6), the anti-chase drift-guard's reference price, and (in live mode) the Greeks gate — read `tick`/`latest_tick`, which reflects **whichever option contract happens to be currently subscribed at that moment**, not necessarily the contract that `direction` will actually cause to be traded.

Since pattern detection (§6, §7) is legitimately spot-based and direction-agnostic, a signal's direction routinely differs from the subscription — e.g., subscribed to a CE (because that's what the strike-selection/rotation logic defaults to), but the pattern match this cycle is PE.

**`broker.place_order()` does switch the subscription to match at order time** (confirmed via code trace, `core/trading/broker.py` ~line 1519-1524, comment reads: `# CRITICAL FIX: Update current_symbol BEFORE getting tick — This ensures tick data matches the actual symbol being traded`) — but this switch happens **after** every one of the checks above had already run and passed, against the wrong contract's data.

### 8.2 The 2026-09-01 reproduction (confirmed facts, from `bot.log`)

Both of §2's cheap-PE trades show the identical sequence:

```
[SIGNAL] SMART SCALP v3.4 | PE | Conf: 82% | Score: 66 | ...
[Placing BUY order: 65 PE contracts | Strike: 23900]
📍 Symbol switched: NIFTY01SEP2623900CE → NIFTY01SEP2623900PE
[Order filled: @ ₹6.12]
```

- The bot was subscribed to and streaming ticks for the **CE** contract (~₹98 premium range, inferred from the states.log drift-guard messages logged moments earlier: `"sig ₹98.35 -> now ₹99.10"`).
- Every filter that ran — premium range, delta band, the Market Quality Engine's spread/liquidity/freshness (grade A+, 93/100 on both trades) — validated **the CE's tick**.
- The symbol switch happens in the same breath as order placement, **after** every check already passed.
- The bot then bought the **PE** at ₹6.03 and ₹6.12 respectively — 10x below the ₹70 configured minimum, entirely unvalidated by any of the checks that had just run.
- **This directly explains the wide, ~0.85-1.08% spread on these two positions and the resulting wide-spread kill-switch trips** (18 total that session, per the earlier spread-kill-switch analysis in this investigation) — a ₹0.05 NSE tick against a ~₹6 premium is already close to 1%, comfortably over the 0.6% kill-switch threshold, purely from tick granularity.
- **Confirmed as systemic, not a one-off:** both occurrences of the pattern show the identical sequence. A control case (a CE entry where the bot was already subscribed to the matching CE) showed no "Symbol switched" line and no discrepancy — confirming the bug specifically requires a subscription/direction mismatch to manifest.

### 8.3 The fix

**New method, `core/trading/broker.py:BrokerInterface.get_tick_for_direction(direction)`:**
- If the target symbol (`self._build_option_symbol(self.current_strike, direction)`) already equals `self.current_symbol`, returns `self.get_tick()` unchanged (no extra cost on the common, non-mismatched path).
- Otherwise, fetches a **real, fresh tick for the target contract** via `self.broker_client.get_market_tick(symbol=target_symbol, exchange=EXCHANGE)`, enriched the same way `_fetch_option_tick_rest()` already enriches ticks (spot_price, strike, direction, symbol, timestamp fields).
- Returns `None` if no `broker_client` is available, or on any fetch exception (logged, not raised).

**Wired into `core/engines/entry_engine.py:entry_signal()`:**
- Immediately after `instrument = params.get('direction', 'CE')` is determined, checks whether `broker.current_symbol` ends with `instrument`. If it doesn't (cross-direction case), calls `broker.get_tick_for_direction(instrument)`.
- **If that fetch fails, the entry is rejected outright** (`"Cross-direction tick unavailable for {instrument}"`) — the fix does not silently fall back to the wrong contract's data on failure.
- If it succeeds, the resulting `execution_tick` is used for: the premium filter, the new pre-entry spread sanity check (§6.1), the anti-chase drift-guard's `signal_ltp`/`signal_spot_price`/`signal_timestamp` reference values, and (live mode only) the Greeks gate.
- Wrapped in a broad `try/except Exception: pass` (not just `ImportError`) so a broker-access hiccup here degrades safely to the pre-fix behavior (using the original subscribed-contract tick) rather than crashing the entry decision.

**Explicitly, deliberately NOT changed by this fix** (documented at the time, to keep the fix minimal and scoped):
- `can_trade_ce()`/`can_trade_pe()` (the session-trend regime gate) — spot-based, not instrument-price-based, never affected by this bug.
- The confidence gate (both the internal MQ-adjusted one and the outer flat one) — same reasoning.
- The dead, fully-unused duplicate scoring functions `calculate_bullish_score()`/`calculate_bearish_score()` (§6.2's step-8 note) — confirmed via grep to have zero callers anywhere in the codebase; out of scope for this fix.
- The three separate regime-classification systems (`SessionTrendTracker`, `smart_scalp_v3.get_market_regime()`, and the inline EMA9-vs-EMA21 pattern check) — architecturally distinct systems, not touched.
- The permissive 5-way-OR structure of `can_trade_ce()`/`can_trade_pe()` itself (§3) — flagged as an observation, not fixed.
- Any exit-engine logic (§9-§14) — entirely out of scope for this entry-side fix.
- The Market Quality Engine's own internal spread/liquidity checks (§6.2 step 6) still run against the pre-switch tick inside `generate_signal()` — the fix adds a **separate, narrower** post-hoc spread check in the outer engine using `execution_tick`, rather than re-running the full Market Quality Engine a second time. This was a deliberate scope decision to keep the fix surgical rather than duplicating a complex engine.

### 8.4 Validation

- **9 new regression tests**: `tests/test_broker_cross_direction_tick.py` (4 tests, `get_tick_for_direction()` in isolation — same-direction reuses `get_tick()` with no extra fetch, cross-direction fetches the correct target contract not the subscribed one, returns `None` without a broker client, returns `None` on fetch exception) and `tests/test_entry_engine_cross_direction.py` (5 tests, full `entry_signal()` integration — same-direction doesn't fetch, cross-direction rejects on the target contract's own (too-low) premium, cross-direction allows entry when the target's own premium is fine, cross-direction rejects when the target tick is unavailable, cross-direction rejects on the target's own wide spread).
- **The exact 2026-09-01 reproduction was used as a test case**: a signal validated against a subscribed CE's ₹98 premium (which would pass the filter) but the target PE's real premium is ₹6.12 (which must fail) — asserted the entry is now rejected on the PE's own price, not the CE's.
- **Full test suite: 181 → 190 passed, 1 skipped, green throughout** (before-and-after runs, plus import smoke tests after every edit).
- **Commit: `78e6913`** — "fix: validate entry filters against the contract actually being traded".
- Documented in `claude_code/fixed.md` §20.

---

## 9. Exit Engine — Full Trace

**Confirmed facts, from `core/engines/exit_engine.py:check_exit_conditions()` and its constituent functions.** Priority order — checked every tick, first match wins:

1. **Hard SL / Step-Trailing SL** (`check_hard_sl()`)
2. **Early momentum loss cut** (`early_momentum_loss_cut()`, first 45 seconds only)
3. **Soft loss timeout** (`soft_loss_time_exit()`, after 75 seconds)
4. **Greeks kill** (`greek_exit()`, theta/gamma/delta deterioration)
5. **Smart RSI exit** (`smart_rsi_exit()`, momentum exhaustion)
6. **RSI reversal exit** (`rsi_reversal_exit()`, momentum shift from an extreme)
7. **Time exit** (`time_exit_15min()`, 15-minute max hold or 3:25 PM market-close cutoff)

### 9.1 Risk parameters (all confirmed against live `.env`, no drift found)

- `SL_POINTS_FIXED = 7` (`.env`: `SL_POINTS=7`).
- Quantity: 65 (both CE_QUANTITY/PE_QUANTITY confirmed at this value in the observed sample).
- Nominal max loss per trade: `7 × 65 = ₹455` (`MAX_LOSS_PER_TRADE_CE/PE = SL_POINTS_FIXED × qty`).
- Nominal TP: `TP_POINTS_FIXED = 14` (`.env`: `TP_POINTS=14`, R:R 1:2 nominal) — **but this fixed TP is only used when `TRAILING_ENABLED=False`.** Since trailing is enabled (`TSL_ENABLED=true` in live `.env`), the fixed TP is effectively decorative — the step-trailing ladder handles all profit-taking instead.

### 9.2 Step-trailing ladder (`get_step_trailing_sl()`)

Confirmed trigger/lock table, from `.env` (`TSL_LEVELS=8:4,12:7,16:11,20:15,25:20,30:25,40:35,50:45`) plus the separate breakeven rung (`EXIT_BREAKEVEN_TRIGGER_POINTS=4` → lock `EXIT_BREAKEVEN_BUFFER_POINTS=2`):

| Trigger (max favorable points reached) | Locked SL |
|---|---|
| Initial (no trigger yet) | -7 (hard SL) |
| +4 | +2 (breakeven) |
| +8 | +4 |
| +12 | +7 |
| +16 | +11 |
| +20 | +15 |
| +25 | +20 |
| +30 | +25 |
| +40 | +35 |
| +50 | +45 |

- `max_profit_points` is tracked per-trade and **never resets** during the life of the trade.
- SL only ever ratchets up (`highest_sl` tracking), never back down.
- **Confirmed finding: the trailing ladder never activated even once across all 33 trades in the 3-day sample (§10), because the single largest favorable move any trade achieved was +3.77 points (trade #5, §2)** — below even the first breakeven rung (+4), let alone the first real trailing rung (+8). **The trailing system was not the dominant exit mechanism in this dataset — it was never engaged at all.**

### 9.3 Early/soft loss mechanisms

- **Early Momentum Loss Cut** (`early_momentum_loss_cut()`), active only in the **first 45 seconds** (`EXIT_EARLY_LOSS_CUT_TIME_SEC=45`), ATR-adaptive threshold:
  - `ATR < 3` (low volatility): cut at **-2.5 points** (`EXIT_EARLY_CUT_ATR_LOW_POINTS`).
  - `ATR > 6` (high volatility): cut at **-4.5 points** (`EXIT_EARLY_CUT_ATR_HIGH_POINTS`).
  - Otherwise: cut at **-3.5 points** (`EXIT_EARLY_LOSS_CUT_POINTS`, the default).
- **Soft Loss Timeout** (`soft_loss_time_exit()`), active only **after 75 seconds** (`EXIT_SOFT_LOSS_TIME_SEC=75`): triggers if still `<= -1.8 points` (`EXIT_SOFT_LOSS_POINTS`).
- Both mechanisms exist specifically so most losses never reach the full -7 point hard stop — **confirmed: the 7-point hard SL was never hit even once in the 15-trade loss sample (§10, §14)**.

### 9.4 RSI-based profit-taking

- **Smart RSI Exit** (`smart_rsi_exit()`): requires `price_diff >= RSI_EXIT_MIN_PROFIT_POINTS` (**2.0 points**) as a profit floor before it's even evaluated; then CE exits if `RSI > RSI_OVERBOUGHT` (**80**), PE exits if `RSI < RSI_OVERSOLD` (**20**).
- **RSI Reversal Exit** (`rsi_reversal_exit()`): requires `price_diff >= RSI_REVERSAL_MIN_PROFIT_POINTS` (**1.65 points**, live `.env` value) as a profit floor; tracks the trade's own extreme RSI seen so far, then exits on reversal: CE if `max_rsi_seen > RSI_REVERSAL_CE_EXTREME (75)` and current RSI has dropped below `RSI_REVERSAL_CE_EXIT (60)`; PE if `min_rsi_seen < RSI_REVERSAL_PE_EXTREME (25)` and current RSI has risen above `RSI_REVERSAL_PE_EXIT (40)`.

---

## 10. 33-Trade Realized Risk/Reward Analysis

**Confirmed facts, computed directly from `entry_price`/`exit_price` (points, not rupees) for every trade across the 3 days, excluding the 2 kill-switch-aborted PE trades from 2026-09-01 (which never played out on their own merits — see §2/§8):**

| Day | Wins (n, avg pts) | Real losses (n, avg pts) |
|---|---|---|
| 2026-09-01 | 4, **+2.77** | 4, **-2.92** |
| 2026-08-31 | 6, **+1.53** | 7, **-2.49** |
| 2026-08-28 | 6, **+1.53** | 4, **-2.13** |
| **Combined** | **16, +1.84** | **15, -2.51** |

**Derived, confirmed figures:**
- **Realized R:R: 1.84 : 2.51 ≈ 0.73 : 1** — the average winning trade gains less than the average losing trade loses, in points.
- **Break-even win rate at this ratio: 2.51 / (1.84 + 2.51) = 57.7%.**
- **Actual win rate in the sample: 16 / 31 = 51.6%** — below the break-even threshold.
- **The nominal 7-point hard SL was never hit once across all 15 real losses** — every loss exited via Early Loss Cut (8 trades, §14) or Soft Loss Exit (7 trades, §14), both tighter than the hard SL by design (§9.3).
- **Every single winning trade exited via RSI exhaustion/reversal** (16/16, confirmed, §4).
- **Every trade in the 3-day sample, win or lose, closed inside roughly ±0.6R** (using the nominal 7-point SL as 1R — see §12 for the exact per-trade range).

**This aggregate realized R:R (0.73:1, with a win rate below its own break-even threshold) is the single strongest, most robust profitability signal produced by this entire investigation.** It is derived from the full 33-trade dataset, not a small subset, and directly explains why all three sessions analyzed landed flat-to-negative in aggregate gross PnL (§11). It is more reliable than any of the individual-mechanism hypotheses investigated in §13/§14, which were based on much smaller, partially-covered samples.

---

## 11. Gross/Net P&L and Costs

**Confirmed facts (gross PnL, directly from `trades.pnl`, summed per day):**
- 2026-09-01: **-₹59.80** (gross, 10 trades).
- 2026-08-31: **-₹471.25** (gross, 13 trades).
- 2026-08-28: **+₹74.10** (gross, 10 trades).
- **Combined gross: -₹457 (approx.), 33 trades.**

**Confirmed fact: brokerage/transaction charges are not tracked anywhere in the live/paper trade records.** A whole-codebase grep found exactly one commission figure anywhere: `core/backtest.py`'s `commission_per_trade: float = 40` (a ₹40 round-trip assumption) — used only by the offline backtester, never applied to any live/paper session's recorded PnL (`summary.json`, `trades.csv`, `report.txt`, or the DB `pnl` column).

**Illustrative estimate only, explicitly not a recorded actual figure:** applying that same ₹40/round-trip assumption to all 33 trades: `33 × ₹40 ≈ ₹1,320` in estimated charges, which would put the rough combined net figure around **-₹1,777**. **This number must not be cited as an actual recorded net P&L — it is a rough illustration using the only commission figure that exists anywhere in the codebase, applied outside the context (backtesting) it was designed for.**

---

## 12. R-Multiple Distribution

**Confirmed, derived from §10's per-trade point data, using the nominal 7-point SL as the definition of 1R:**
- Winning trades ranged roughly **+0.20R to +0.54R** (e.g., +1.41pts/7 ≈ 0.20R on the smallest 08-28 win, +3.77pts/7 ≈ 0.54R on the largest, trade #5).
- Losing trades ranged roughly **-0.24R to -0.49R** (e.g., -1.8pts/7 ≈ -0.24R on the smallest soft-loss, -3.32pts/7 ≈ -0.49R on the largest early-loss-cut, trade #8).
- **All 33 trades in the sample, win or lose, therefore closed inside approximately ±0.6R** — no trade came anywhere close to using its full nominal risk budget in either direction, in either the favorable or adverse direction.

---

## 13. RSI Exit Counterfactual Investigation

### 13.1 The observability limitation (confirmed, stated upfront because it materially limits the confidence of every finding below)

- **Before the fix in §21, there was no continuous, persisted option-premium tick stream anywhere in the codebase.** The `ticks` DB table existed in schema (columns: timestamp, symbol, ltp, bid, ask, volume, spot_price, oi) but had **zero rows** — the write path was entirely unused.
- The only real premium data available for a post-exit counterfactual came from `bot.log`'s periodic strike-quality re-scan `[LTP RAW]` lines, which fire irregularly (~30-90 seconds apart) and only for strikes currently "in range."
- **Real, multi-point premium coverage in the critical 5-minute post-exit window existed for only 5 of the 33 trades** — all from 2026-09-01's CE cluster (favorable log-line timing, not a systematic property). Everywhere else, 0-1 real premium points were available post-exit — not enough for a trajectory.
- A supplementary, lower-confidence cross-check used the dense underlying NIFTY spot price series from `dvf_signals` (which does log near-continuously), giving directional (not option-premium-precise) coverage for a broader set of trades.

### 13.2 Trade-by-trade counterfactuals (real option-premium data, highest confidence — all 5 from 2026-09-01)

**T1 — RSI EXIT WIN.** Entry 105.06 → Exit 107.39 (+2.33pts, 10s hold, trade #4 in §2).
- Post-exit real prices: +1s 108.25 · +33s 111.65 · +2:13 113.55 · **+2:45 116.00 (peak)** · +3:45 114.75 · +4:45 113.55.
- Price never once dropped back to the exit price within the observed window. Peaked **+8.61 points above** what was actually captured.
- **Conclusion: this RSI exit was clearly premature.**

**T2 — RSI EXIT WIN.** Entry 109.61 → Exit 113.38 (+3.77pts, 66s hold, trade #5 in §2).
- Post-exit: +1s 113.55 · +33s 116.00 · +1:33 114.75 · +2:33 113.55 · **+2:56 111.40 (-1.98 vs. exit)** · **+4:57 120.75 (+7.37 vs. exit)**.
- Genuinely two-sided: real additional upside existed (+7.37 at 5 minutes), but only after first round-tripping through a point worse than the realized exit.
- **Conclusion: this RSI exit's outcome depends on hypothetical stop management during the hold — neither cleanly premature nor cleanly justified.**

**T3 — EARLY LOSS CUT (loss-side control, RSI never triggered).** Entry 113.87 → Exit 111.13 (-2.74pts, 19-20s hold, trade #6 in §2).
- Post-exit: +1s 111.40 · **+2:02 120.75 (+6.88 vs. entry)** · **+3:03 121.85 (+7.98 vs. entry)** · +4:03 116.40 (+2.53 vs. entry).
- This loss-cut exited right before a strong reversal. Holding would have converted a -2.74 loss into as much as +7.98 within 3 minutes.
- **Conclusion: this early-loss cut was clearly premature.**

**T4 — RSI EXIT WIN.** Entry 124.39 → Exit 127.46 (+3.07pts, 11s hold, trade #7 in §2).
- Post-exit: +0s 126.55 · +32s 126.05 · **+44s 123.80 (-0.59 below entry — would be a loss)** · +2:45 129.20 (+1.74 vs. exit, the peak) · +3:45 125.00 · **+4:45 123.25 (-1.14 below entry — losing again)**.
- Holding risked round-tripping into an outright loss on two separate occasions within 5 minutes, for only +1.74 of additional upside at the single best moment.
- **Conclusion: this RSI exit appears justified — it protected real value that was later erased.**

**T5 — EARLY LOSS CUT (loss-side control).** Entry 126.14 → Exit 122.82 (-3.32pts, 10s hold, trade #8 in §2).
- Post-exit: +1s 123.80 · **+2:02 129.20 (+3.06 above entry — would be a win)** · +3:02 125.00 (-1.14 below entry) · +4:03 123.25 (-2.89 below entry, close to the realized loss).
- Transient recovery to a paper win at 2 minutes, reversed back by 3-4 minutes to a loss similar to what was actually realized.
- **Conclusion: mixed / closer to justified than T3 — the recovery did not hold.**

**Summary verdict on this 5-trade real-data sample: 1 RSI winner clearly premature (T1), 1 genuinely two-sided (T2), 1 justified (T4); 1 loss-cut clearly premature (T3), 1 mixed/closer-to-justified (T5).** No unanimous pattern either way. **Explicit conclusion at the time: 5 real trades is not enough data to settle whether RSI exits or Early Loss Cut are systematically mistimed — this was treated as insufficient evidence to patch anything.**

### 13.3 Underlying-spot directional cross-check (lower confidence, 17 trades with usable coverage across the 3 days)

| | n | avg max favorable spot move post-exit | avg max adverse spot move post-exit |
|---|---|---|---|
| RSI-exit wins | 10 | +2.55 | -4.84 |
| Loss trades (RSI never triggered) | 7 | +3.52 | -3.44 |

- **These are NIFTY spot index points, explicitly not option premium points** — kept strictly separate from §13.2's real-premium figures per the methodology rule established during the investigation.
- Directionally, the loss-side trades in this broader (but lower-confidence) sample show a slightly *larger* average favorable move available afterward than the RSI-exit wins, and a *smaller* average adverse move — consistent with, not contradicting, the small-sample lean from §13.2 (T3 was the most dramatic single counterexample). **Neither of the two competing hypotheses ("RSI is too aggressive" vs. "RSI is doing its job") cleanly wins on this evidence.**

---

## 14. Loss-Side Counterfactual Investigation

### 14.1 Scope and coverage (confirmed facts)

- **15 total loss trades across the 3 days: 8 Early Loss Cut, 7 Soft Loss Exit, 0 of any other exit type.**
- **Usable post-exit data existed for only 7 of 15 (47%).**
- **Real option-premium data existed for only 2 of 15 (13%) — both Early Loss Cut trades, both from 2026-09-01 (T3 and T5, reused from §13.2).**
- **5 more had partial underlying-spot coverage** — and in every one of these 5, the data did not start until ~2-4 minutes after exit (a logging-cadence gap, not a market fact), missing the most diagnostic early window.
- **8 of 15 (53%) had zero usable post-exit data of any kind, real or spot.** These could not be assessed and are explicitly recorded as unassessed, not as "justified" or "premature."

### 14.2 Trade-by-trade — real premium data (T3, T5, detail as in §13.2, restated here with recovery-specific framing)

**T3 — Early Loss Cut.** Entry 113.87 → Exit 111.13 (-2.74pts / -₹178.10, 20s hold, pre-exit MFE = ₹40.95 = +0.63pts).
- **Recovered above entry (113.87) at ~2:02 post-exit, and stayed above entry through the rest of the observed window** (+4:03 still +2.53 above entry, at 116.40).
- Max hypothetical value: +7.98pts (≈₹518) vs. the realized -₹178.10 loss — an approximate **₹696 swing**.
- **This recovery was sustained, not a spike. Reads as premature.**

**T5 — Early Loss Cut.** Entry 126.14 → Exit 122.82 (-3.32pts / -₹215.80, 10s hold, pre-exit MFE = ₹0.00 — never once ticked favorable before the cut).
- **Recovered above entry only briefly** (~1 minute, roughly +2:02 to +3:02), then reversed back below entry and stayed there.
- At +4:03 (123.25), marginally better than the realized exit (122.82) but nowhere near entry and clearly declining from its peak.
- **Holding longer would not have meaningfully improved this trade — it would have delayed a very similar loss, not avoided it. Reads as closer to justified.**

### 14.3 Trade-by-trade — underlying spot only (lower confidence; direction/magnitude signal, not option points; coverage starts 2-4 minutes late in every case)

- **`1787892024_2` (Soft Loss, 2026-08-28).** Window +2:01 to +4:20 only. Spot moved steadily adverse the whole time (-3.25 → -8.55 unfavorable points by +3:40). **Supports the exit being justified.**
- **`1787894118_6` (Soft Loss, 2026-08-28).** Window +2:01 to +3:00. Same pattern, adverse and worsening (-3.70 → -5.00). **Supports justified.**
- **`1788149717_0` (Early Loss Cut, 2026-08-31).** Only 2 points, both near the end of the window (+3:47, +4:00). Single favorable tick (+4.65). **Too sparse to conclude anything — inconclusive.**
- **`1788151888_3` (Early Loss Cut, 2026-08-31).** Window +2:12 to +3:00. Modest favorable move already fading by the time data starts (+2.50 → +1.15). **Weak signal, leans mildly premature but data starts too late to be confident.**
- **`1788155428_0` (Soft Loss, 2026-08-31).** Window +2:12 to +3:20. Favorable and growing the whole visible window (+1.45 → +4.70, holding at +4.40). **Leans premature.**

### 14.4 Aggregate (n=7 assessable of 15 — explicitly treat as directional, not definitive, given the coverage gap)

| Exit type | Assessable / total | Premature | Justified | Inconclusive/mixed |
|---|---|---|---|---|
| Early Loss Cut | 4 / 8 | 1 (T3, real) | 0 clear | 1 mixed (T5, real) + 1 weak lean (151888_3) + 1 too-sparse (149717_0) |
| Soft Loss Exit | 3 / 7 | 1 (155428_0) | 2 (892024_2, 894118_6) | 0 |

**Recovery-to-entry rate:** of the 2 real-data trades, both (2/2, 100%) recovered above entry at some point post-exit, but only 1 of 2 (50%) sustained that recovery for the rest of the observed window.

### 14.5 Conclusion, exactly as reached at the time

**Partial support only, and specifically implicating Early Loss Cut more than Soft Loss Exit — not proof, and explicitly not acted on as a patch.** The strongest evidence (the 2 real-data trades, both Early Loss Cut) showed 100% recovered above entry, 50% sustained. The Soft Loss Exit trades with usable data (3 of 7) leaned the *other* way — 2 of 3 showed continued adverse movement, arguing those specific exits were doing their job correctly.

**Explicit decision recorded at the time: this evidence (7 assessable trades, only 2 of them real premium data, 53% of the full 15-trade population entirely unassessed) was judged insufficient to widen or otherwise modify the Early Loss Cut threshold.** The conclusion drawn was "Early Loss Cut is now the more specific suspect, worth a targeted look once better data exists" — not "confirmed, patch it." See §16 for how this fed the priority decision.

---

## 15. Data Quality Problem — 2026-08-28's Anomalous MAE

**Confirmed observation, found while cross-checking §4's cross-day data:** the second trade of 2026-08-28 (`PAPER_1787891119_1`, a PE win, entry ₹80.37 → exit ₹81.78, realized pnl +₹91.65) shows `mae = -2198.95` in the `trades` table — an adverse-excursion figure larger than the entire premium value of the position at entry (₹80.37 × 65 = ₹5,224, so -₹2,198.95 would imply the premium briefly traded near-zero or the calculation glitched, neither plausible for a trade that closed as a modest, clean winner).

**This is recorded as a data-quality/tracking anomaly, not a real economic drawdown.** The specific root cause was not investigated further in this pass (out of scope). **Explicit rule: exclude this trade's MAE value from any future expectancy/drawdown calculation until the cause is understood** — using it as-is would badly distort any MAE-based statistic.

---

## 16. Priority Decisions Made Before Any Fix Was Applied

**Explicit, stated decision, made after all of §2-§15's investigation and before any code was touched:**

**DO NOW (both completed, see §20/§21 for full detail):**
1. Fix the CE/PE symbol-switch/instrument-isolation bug (§8) — judged a confirmed, mechanical defect with clear code-level evidence, not a judgment call requiring more data.
2. Fix the observability gap by wiring up continuous tick persistence (§21) — judged a zero-risk, zero-behavior-change fix that would make every future strategy-layer analysis (starting with the next Early Loss Cut revisit) actually possible with complete data, rather than the 47-53% coverage gaps documented in §13/§14.

**DO NOT PATCH YET (all explicitly left unchanged, with reasoning recorded):**
- RSI exit (Smart RSI + RSI Reversal) — §13.2's 1-clearly-premature/1-two-sided/1-justified split on real data was judged not a pattern, "acting on it would be acting on vibes, not evidence."
- Soft Loss Exit — the available evidence (2 of 3 assessable trades showing continued adverse movement) actually argued *for* keeping this one as-is.
- Early Loss Cut threshold — leaned premature in the real data (T3) but on n=2 real trades, judged insufficient to change a live risk parameter with real-money implications.
- Trailing/breakeven logic — zero evidence of a defect; it simply was never reached given this dataset's typical move sizes (§9.2, §5).
- Confidence logic (the flat-vs-MQ-adjusted threshold interaction noted in §6.2 step 13/§6.1) — noted as an observation, not acted on.
- Broader strategy structure (the three parallel regime systems, the permissive `can_trade_ce/pe` OR-gate, the dead duplicate scoring functions) — all explicitly out of scope for this pass, documented as observations for a future decision.

**Reasoning recorded for this split:** the aggregate realized R:R (§10, 0.73:1 combined with a 51.6% win rate against a 57.7% break-even requirement) is currently the strongest, most robust piece of evidence this investigation produced — derived from the full 33-trade dataset. Every individual-exit-mechanism hypothesis investigated (§13, §14) was based on much smaller, partially-covered samples and did not clear the bar for a confident decision. **The explicit next step was determined to be: collect better data (via the tick-persistence fix), not patch on the current evidence.**

---

## 17. Trade Finalization / DB Accounting Bug (from the earlier architecture-fixing phase of this project, included here because it is directly relevant background to the reliability of the trade records this report's strategy analysis depends on)

### 17.1 WebSocket subscribe/unsubscribe mechanism — background on how it currently works

`core/trading/broker.py` (`_subscribe_with_retry()`/`_unsubscribe_with_verify()`) calls into `brokers/angel_one/client.py`'s `subscribe()`/`unsubscribe()`. The underlying acknowledgement primitives (`_wait_for_ack()`, `_register_ack_waiter()`, `_set_ack_result()`) still exist in the codebase and work as designed: generate a correlation ID, register a `threading.Event`, send the JSON subscribe/unsubscribe request over the WebSocket, and (if actually called) block until the correlation ID's acknowledgement event fires or times out.

**Important, already-established fact (fixed prior to this report's date, confirmed still true via the live-session audit in `fixed.md` §16.2): `subscribe()`/`unsubscribe()` are currently fire-and-forget in production** — the blocking `_wait_for_ack()` call was removed from the hot path back in the 2026-08-31 architecture-fixing pass (`fixed.md` §14.8), because Angel One's real SmartAPI WebSocket protocol never actually sends the JSON acknowledgement frame this mechanism was originally built to wait for (confirmed by cross-referencing Angel One's own official SDK source, and by zero `"✅ ACK Received"` log occurrences across 22 historical sessions). The ACK primitives above were deliberately left in place as dormant, still-tested infrastructure rather than deleted, in case they're needed again — but they are not on the current subscribe/unsubscribe path. This was independently re-confirmed live on 2026-09-01 (`fixed.md` §16.2: zero `"ACK Timeout"` and zero `"ACK Received"` lines in that session's logs).

### 17.2 The `close_position()` / accounting-parity bug (found and fixed during this session's follow-up audit, `fixed.md` §17/§18.1)

**Confirmed bug:** `close_position()` (the write that marks a `database.py` `active_positions` row `CLOSED`) was called from exactly one place — `state_machine.py`'s normal SL/TP/RSI exit block. `core/main.py:close_current_trade()` — the exit path used by every kill-switch, stale-data, high-latency, or manual/error shutdown exit — called `broker.exit_position()` and `state.update_pnl()` but never `close_position()`, `log_trade_exit()`, or `RiskManager.record_trade()`.

**Confirmed live consequence, 2026-09-01:** 2 of that day's 10 trades (the two wide-spread-kill-switch-exited PE trades discussed in §2/§8) were left with `active_positions` rows stuck `ACTIVE` and `trades` rows stuck `OPEN` (with `pnl=0.0`, `exit_price=NULL`), despite having closed correctly in reality. This also meant `RiskManager.daily_pnl` and `RiskManager.consecutive_losses` never counted those two losses — the same counters the §14.7 consecutive-loss pause and live position-sizing logic depend on.

**Fix:** factored the three post-exit accounting calls into a new shared helper, `state_machine.finalize_trade_exit_accounting()`, called from both the normal exit block and `core/main.py:close_current_trade()`. The two orphaned 2026-09-01 rows were backfilled directly against the live DB (using the correct data already present in `trades.csv`) so the crash-recovery halt logic (`fixed.md` §15.11) wouldn't false-trigger on the next restart.

**Tests:** `tests/test_close_current_trade_exit_accounting.py` (3 tests). **Documented in `fixed.md` §17/§18.1.** This fix predates and is separate from this report's §8 CE/PE fix, but both were found via the same broader audit pass and both affect the reliability of the exact trade records this report's strategy analysis (§2-§16) is built on — confirmed reliable as of this report's date, since the affected rows were corrected before this strategy-layer investigation began reading them.

---

## 18. Configuration Validation Fix (background, `fixed.md` §18.2)

- Startup configuration validation was wired directly into `core/main.py:main()` (previously only reachable via a manual `run.sh` menu option, meaning a normal bot start never validated config at all).
- **Hard-error rule added:** `DAILY_LOSS_ALERT < MAX_DAILY_LOSS <= KILL_SWITCH_LOSS`. Live `.env` values (1500 / 3000 / 3000) satisfy this.
- A stale fallback default inside the validator itself (`MAX_DAILY_LOSS` defaulting to a leftover `25000` instead of the current canonical `3000`) was corrected.
- A test-isolation leak was found and fixed in the same pass: `ConfigValidator.load_env()` writes parsed `.env` values directly into the real process `os.environ` with no restore, and two keys (`KILL_SWITCH_LOSS`, `DAILY_LOSS_ALERT`) were missing from the test suite's cleanup list, causing one test's tmp `.env` values to leak into the next test.

---

## 19. Dead Code / Monitoring Cleanup (background, `fixed.md` §18.4/§19)

- `utils/monitoring.py` (`BotMonitor`/`get_monitor()`) was deleted — confirmed fully dead (zero callers anywhere, `BotMonitor()` instantiated fresh per call with no real writers ever feeding it).
- **Self-review before pushing caught a real gap:** `run.sh`'s Tools menu option `[7] Bot Monitor Status` had its own embedded Python (`from utils.monitoring import get_monitor`) that the initial `*.py`-scoped caller search had missed entirely (grep had only covered `.py` files, not `run.sh`'s heredoc). Fixed by replacing that menu option's body with an honest "removed" message, and cleaning up two more stale filename references (`run_syntax_check`'s file list, `PROJECT_STRUCTURE.md`).
- `tests/test_consecutive_loss_pause_regression.py` was hardened against a latent test-pollution risk in the same review pass: its `set_risk_manager()` calls wrote the real module-level `RiskManager` singleton with no restore; an `autouse` fixture was added to reset it after each test.
- **Full test suite at the end of this cleanup phase: 181 passed, 1 skipped.**

---

## 20. Environment/Configuration Documentation Sync (background, `fixed.md` §18.3)

`.env.example` was synchronized to match the live `.env`'s intentionally-tuned values for 6 variables that had drifted from the documented template (not from each other — `.env` itself was never changed by this):

- `DELTA_MAX` (0.75 live vs. 0.80 documented)
- `ENTRY_MAX_DRIFT_PCT` (0.35 live vs. 0.75 documented — this one was actively firing, visible in logs as `"Exec guard: Execution drift too high"` messages)
- `KILL_SWITCH_LATENCY_MS` (1000 live vs. 1500 documented)
- `MIN_OPTION_PRICE` (5 live vs. 1 documented)
- `RSI_REVERSAL_MIN_PROFIT_POINTS` (1.65 live vs. 1.5 documented)
- `TICK_TIMEOUT_SEC` (2 live vs. 3 documented)

**Explicit note, preserved from the original fix record: `.env` itself and `config/constants.py`'s in-code fallback defaults were deliberately left untouched by this sync** — only the documentation template (`.env.example`) was corrected. Changing the actual fallback-safety-net values that fire when a `.env` line goes missing would be a real behavior change to a real-money bot's safety net, not a documentation fix, and was never requested.

---

## 21. Tick Persistence Fix — Full Implementation Detail

**Motivation, directly connecting to §13.1's stated limitation:** the `ticks` table existed in schema with zero rows because nothing ever wrote to it — this was the single biggest reason §13/§14's counterfactual investigations had such large coverage gaps (47-53% of examined trades had no usable post-exit data).

### 21.1 `core/services/database.py`

- Added `DatabaseManager.log_tick(tick: Dict) -> Optional[int]` — inserts into the existing `ticks` table (`timestamp`, `symbol`, `ltp`, `bid`, `ask`, `volume`, `spot_price`, `oi`). No-ops (returns `None`) if `symbol` or `ltp` is missing.
- Added the module-level `log_tick()` wrapper function, matching the codebase's existing convention (`log_trade_entry`, `log_trade_exit`, `close_position`, etc.).
- Added a second index, `idx_ticks_symbol_timestamp ON ticks(symbol, timestamp)`, alongside the pre-existing timestamp-only index — matches the exact `WHERE symbol=? AND timestamp BETWEEN ? AND ?` query shape every counterfactual analysis in §13/§14 needed and had to work around manually via log-grepping.
- `prune_old_signal_rows()` was extended to cover `ticks` alongside its existing `signals`/`dvf_signals` sweep (same 7-day default retention), since `ticks` is now a similarly per-event, unbounded-growth table.

### 21.2 `core/trading/broker.py`

- `BrokerInterface.get_tick()` — the single funnel point all three tick sources (WebSocket, REST, simulation) already converge through — now calls a new `_persist_tick()` helper for every real (non-simulated) tick before returning it.
- `_persist_tick()` **dedupes on `(symbol, ltp, bid, ask)`** — necessary because the existing `get_tick()` logic re-serves the same cached WebSocket tick (with only its timestamp refreshed to "now") at the ~2Hz main-loop cadence whenever the market is quiet; without dedup this would flood the table with thousands of identical rows per idle period. Every row actually written represents a genuine price change.
- Simulated ticks (`data_source == 'SIMULATION'`) are explicitly excluded so synthetic/paper-simulation data never contaminates a future real-session analysis.
- Wrapped in `try/except Exception: pass`, matching the project's established "analytics-only, must never block trading" convention used throughout the codebase (e.g., `_log_signal_snapshot`).

### 21.3 Validation

- **Verified functionally against the real `core/data/trades.db`, not just unit tests:** inserted a real row via `log_tick()`, confirmed the row's contents and both indexes existed, then deleted the test row so it wouldn't pollute real historical data.
- **9 new regression tests** (`tests/test_tick_persistence.py`): `log_tick()` against a real temp-file DB (row insert correctness, no-op on missing symbol/ltp); `_persist_tick()`'s dedup logic (identical consecutive ticks skipped, a genuine price change logged again, no-op without a symbol, never raises on DB failure); `get_tick()` only persisting real ticks, never simulated ones.
- **Full test suite: 190 → 199 passed, 1 skipped, green throughout.**
- **Commit: `3f6528a`** — "feat: wire up the ticks table write path for future strategy analysis".
- Documented in `claude_code/fixed.md` §21.

---

## 22. Startup Pruning / Retention Fix, and a Correction Made Mid-Investigation

**Initial concern, raised while flagging follow-up items after §21:** it appeared that `prune_old_signal_rows()` was only ever called from `app.py`, and that `core/main.py` — believed at the time to be the actual live entry point launched by `run.sh` — never called it, meaning `signals`/`dvf_signals` (and now `ticks`) might be growing completely unpruned in the process that's actually running.

**This concern was later found to be based on an incomplete check, and was explicitly corrected rather than left standing:** the original check had only grepped `core/main.py` itself for `prune_old_signal_rows` and found nothing, without verifying what `run.sh` actually launches. **`run.sh` in fact launches `app.py` directly** (`"$PYTHON_BIN" app.py`, `run.sh:773`), and `app.py` already calls `prune_old_signal_rows(retention_days=7)` once at startup, immediately before calling `core.main.run_with_auto_reconnect()` — the very function whose `"── PTQ SCALPING BOT ── Auto-Reconnect ON ──"` log banner appears in every session analyzed throughout this entire report, confirming it genuinely is the live path. **Pruning was already running in production, once per process start, the whole time.** The corrected record for this is preserved in `fixed.md` §21's own text (amended) and in §22 there.

**What was still done, as genuine defense-in-depth rather than fixing a real gap:** `main()` (not `run_with_auto_reconnect()` or `app.py`) is the function actually re-invoked on every auto-reconnect cycle, and is also independently callable on its own — confirmed by the fact that `tests/test_p0_historical_warmup.py` already calls `core_main.main()` directly, bypassing `app.py` entirely. Wiring the prune call directly into `main()` (right after the §18 config-validation block, same `try/except Exception: pass` safety pattern `app.py` already uses) means pruning runs regardless of entry point, rather than depending on `app.py` specifically remaining the sole launcher forever.

- Runs on every `main()` call, including reconnects — judged acceptable since it's a cheap, idempotent `DELETE WHERE timestamp < cutoff`, the same reasoning already applied to the config-validation call re-running on reconnect.
- **2 new regression tests** (`tests/test_main_startup_pruning.py`): `main()` calls `prune_old_signal_rows(retention_days=7)` before reaching the (mocked-to-abort) readiness check; a pruning failure does not prevent `main()` from continuing past it.
- **Full test suite: 199 → 201 passed, 1 skipped, green throughout.**
- **Commit: `0e77970`** — "fix: wire prune_old_signal_rows into core/main.py's main() directly".
- Documented in `claude_code/fixed.md` §22 (including the correction to §21's earlier text).

---

## 23. Final Validation State (as of this report)

**Latest full test suite run: 201 passed, 1 skipped.**

**Latest relevant commits, in chronological order:**
- `1559856` — exit-accounting parity across all exit paths + startup config validation (§17, §18).
- `b979236` — docs: closed out dangling `findings.md` references in `fixed.md`.
- `eca89d9` — fix: caught `run.sh`'s non-`.py` reference to the deleted `utils/monitoring.py` (§19).
- `78e6913` — **fix: validate entry filters against the contract actually being traded** (§8, the CE/PE instrument-switch bug).
- `3f6528a` — **feat: wire up the ticks table write path for future strategy analysis** (§21).
- `0e77970` — **fix: wire `prune_old_signal_rows` into `core/main.py`'s `main()` directly** (§22).

All commits above are local to the `feature/ptq-scalping-20260808` branch as of this report; push to the remote has not been performed (blocked earlier in the session by an absent GitHub credential in this environment — not a code issue).

---

## 24. Current Decision / Status as of 2026-09-02

**No strategy patch is currently pending or planned for immediate application.** Specifically, as of this report:

- The CE/PE instrument-selection bug is fixed and validated (§8).
- Tick persistence is active for all future sessions (§21).
- Startup pruning is covered from both entry points (§22).
- The trade-finalization/DB-accounting bug is fixed (§17.2).
- Startup configuration validation is wired in and enforced (§18).
- Dead monitoring code has been removed and stale references cleaned (§19).
- The full test suite is green at 201 passed, 1 skipped.

**The next planned step is explicitly NOT another strategy patch.** The plan, as agreed:

1. Collect two clean trading days of live/paper data.
2. **2026-09-02 is Day 1 of that planned two-day collection window.**
3. This will be the **first session with dense, real option-premium tick persistence active** (§21) — the observability gap that limited §13/§14's confidence should not recur for this session's data.
4. After the two-day window, re-analyze, this time with complete data: Early Loss Cut behavior specifically (the leading suspect from §14.5), RSI exit behavior, realized R:R (§10's methodology, repeated), MFE/MAE, post-exit continuation/reversal (§13's counterfactual methodology, repeated with full coverage instead of 5-of-33), entry quality, CE/PE-specific behavior (now with a genuine multi-day CE sample, addressing §4's "not yet established" caveat), and actual profitability including transaction costs where they can be reasonably estimated or better yet, tracked.
5. **Only after that re-analysis will a decision be made on whether to modify, remove, or add any strategy logic.**

**Checkpoint, recorded precisely, not as a permanent state:** at approximately 01:16 AM IST on 2026-09-02, no bot process was running and no `logs/2026-09-02/` directory had yet been created (checked directly: `ps aux` showed no matching python process, `ls logs/` showed no 09-02 entry). This is a point-in-time fact as of that check, expected to change once the trading day begins (market opens 09:15 IST).

---

## 25. Important Interpretation Rules — Explicit, for Future Readers (Human or AI)

To prevent this investigation's findings from being misread or over-extended by anyone (including a future AI session) picking this report up later, the following rules are recorded explicitly:

1. **Do not treat the 2026-09-01 CE losses as a proven CE strategy failure.** 2026-09-01 was the first meaningful CE sample in the available data (§4) — 2026-08-28 and 2026-08-31 fired PE exclusively. One losing stretch on the only sample day is not a multi-day finding.
2. **Do not treat the hardcoded-looking `"📉 BEARISH"` regime label as real regime evidence.** It is one genuinely-computed input among five independent gate conditions, and it demonstrably does not tell you which of the five actually authorized any given trade (§3).
3. **Do not claim the trailing-stop system caused premature exits or "gave back" profit.** It never activated even once across the 33-trade sample — the largest favorable move any trade achieved (+3.77 points) never reached even the first breakeven-lock rung at +4 points, let alone the first real trailing rung at +8 (§5, §9.2).
4. **Do not patch the RSI exit mechanism based solely on the fact that one real counterfactual trade (T1) was clearly premature.** The same 5-trade real-data sample also contained one justified case (T4) and one genuinely two-sided case (T2) (§13.2).
5. **Do not widen or otherwise change the Early Loss Cut threshold based solely on T3 and T5.** Only 2 of the 15 loss trades in this window had real premium data; the broader 7-trade assessable sample (including 5 spot-only, lower-confidence trades) was mixed, and 53% of the full loss population was entirely unassessed due to the (now-fixed) tick-persistence gap (§14.4, §14.5).
6. **Do not treat the estimated ~₹1,320 (33 trades × ₹40) as an actual recorded transaction cost.** It is an illustrative estimate using the only commission figure that exists anywhere in the codebase (`core/backtest.py`'s backtesting-only assumption), applied outside the context it was designed for. No real brokerage/charges tracking exists in the live/paper trade records (§11).
7. **Do not use 2026-08-28's second trade's `mae = -2198.95` in any expectancy or drawdown calculation** until the underlying data-quality issue producing that implausible value is understood (§15).
8. **The strongest current dataset-level profitability signal is the negative realized R:R of approximately 0.73:1 (average win +1.84pts vs. average loss -2.51pts), combined with a ~51.6% actual win rate against a ~57.7% break-even requirement (§10).** This is derived from the complete 33-trade dataset and should be weighted more heavily than any of the individual-mechanism hypotheses in §13/§14, all of which were built on smaller, partially-covered samples.
9. **The next strategy decision must be based on the new, dense tick data collected after the §21 fix — not on speculation, and not on re-running the same partial-coverage methodology from §13/§14 against the same already-examined 33 trades.**

---

## 26. Document Provenance and Cross-Check

This report was written by directly transcribing and cross-checking the investigation, findings, code traces, fixes, and decisions actually made and recorded during the 2026-09-01/09-02 work session, against:
- The live conversation record of the entry-engine trace, exit-engine trace, R:R analysis, and both counterfactual investigations (source of §2-§16, §23-§26's content).
- `claude_code/fixed.md` §17-§22 (source of exact fix detail, file paths, function names, and the §21/§22 correction, cross-checked directly against the file's current content at the time of writing this report).
- `git log` (source of exact commit hashes, cross-checked directly: `78e6913`, `3f6528a`, `0e77970`, plus the earlier `1559856`, `b979236`, `eca89d9`).
- A direct `pytest` run at report-writing time confirming the final test count (201 passed, 1 skipped).
- Direct filesystem/process checks (`ls logs/`, `ps aux`) confirming the exact 2026-09-02 01:16 AM checkpoint state recorded in §24.

No section of the user's original 26-point report specification has been omitted. Where the source material required a small correction for accuracy (the §17 subscribe/unsubscribe mechanism description, updated to reflect its current fire-and-forget state rather than only the original blocking design; the exact Early-Loss-Cut/Soft-Loss-Exit trade-count split underlying the "9/9 losses" combined figure in §4), that correction is noted inline rather than silently applied, consistent with this project's established convention (see `fixed.md` §22's own self-correction) of recording corrections rather than overwriting prior claims silently.
