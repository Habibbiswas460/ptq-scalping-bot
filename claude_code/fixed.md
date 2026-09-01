# PTQ Scalping Bot — Fixed / Resolved Log

**Originally split from `claude_code/report/findings.md` on 2026-08-31.** `findings.md` was fully retired and deleted on 2026-08-31/09-01 (§15) — every item it still held was fixed or, where it was genuinely not a code bug, absorbed here as an honestly-documented open item instead. **This file is now the sole living fix/status log for the project.** Any older passage below that still says "see findings.md" is a dated snapshot from before the retirement — it means what it says at that point in the timeline, but the file it points to no longer exists; the item it refers to was either fixed later in this same document or is one of the still-open items listed just below. Section/item numbers are kept identical to their original numbering in the fix log (hence non-contiguous in places) so existing cross-references (`see §X.Y`) keep resolving correctly.

**Genuinely still open right now (not code bugs — decisions or more data needed, not further code changes):**
- **§15.7** — AGGRESSIVE↔SAFE↔LOCKDOWN paper-mode bypass: a deliberate design choice, standing until the owner explicitly decides to change it.
- **§15.13/§2.2** — live (real-money) order path has zero execution history; needs a deliberate small-size live test before scaling. A concrete pre-flight test plan exists (from the 2026-09-01 follow-up audit) but hasn't been run.
- **§15.14/§2.4** — one historical rate-limit occurrence; watch-and-see, no fix proposed until it recurs.
- **§15.15/§3** — statistical/expectancy questions that need more live trading data (bigger intraday moves) than exists yet.
- **§15.11's crash-recovery halt** — logic is in place and its write-side gap is now fully closed (§17/§18.1), but the halt path itself has still never been exercised against a real mid-trade crash.
- **§18.1's "not done"** — `mode_switch.py`'s third, dormant consecutive-loss tracker — tied to §15.7 above, not actionable on its own.
- **§18.3/§18.4's "not done"** — `config/constants.py`'s fallback defaults for 6 drifted vars, and `database.py`'s dead `daily_pnl` column — both deliberately left alone (real safety-net values / live schema migration risk), not oversights.

---

## 1. Confirmed fixes (code-verified, from the 2026-08-28 session)

Every item below passed `pytest` (25 test files, all green) and was independently verified via isolated functional tests. Verified live where noted; the rest took effect on the next bot restart.

### 1.1 Position sizing engine — volatility multiplier bug
- **What was wrong:** `_volatility_multiplier()` in `core/engines/position_size_engine.py` always returned exactly `1.0` regardless of VIX/ATR, due to an inverted `ClampRange(max, min)` construction that degenerated the clamp to a constant.
- **Fix:** Rewrote using descending linear interpolation clamped with the correctly-ordered range. Verified: VIX 5→1.0, VIX 20→0.9, VIX 40→0.7.
- **File:** `core/engines/position_size_engine.py`

### 1.2 RSI Reversal Exit — no profit floor (later tuned)
- **What was wrong:** `rsi_reversal_exit()` fired on any `price_diff > 0`, locking wins of a few rupees.
- **Fix:** Added `RSI_REVERSAL_MIN_PROFIT_POINTS` floor (`.env`-configurable), default 1.5, later raised to **1.65** after real fill data showed realized wins landing ~0.1pt under the floor due to bid/ask spread.
- **Evidence of impact:** 08-26 RSI-reversal wins averaged ~₹38 (pre-fix-adjacent); by 08-28 they averaged ~₹100 (post-fix, still pre-1.65-bump).
- **Files:** `config/constants.py`, `core/engines/exit_engine.py`, `.env`, `.env.example`

### 1.3 Position-sizing / risk config — hardcoded, not owner-controllable
- **What was wrong:** `PositionSizeEngine.DEFAULT_CONFIG` (risk %, soft-adjustment weights, ranges, safety caps, allocation grades — ~30 values) had zero `.env` override path.
- **Fix:** Added `POSITION_SIZE_ENV_CONFIG` in `config/constants.py`, merged in as an override layer between `strategy.json` and the constructor arg. Verified: merged runtime config is byte-identical to the old hardcoded defaults (no behavior change until `.env` is edited).
- **Files:** `config/constants.py`, `core/engines/position_size_engine.py`, `.env`, `.env.example`

### 1.4 Dead code removed (confirmed zero external callers before removal)
- `RiskManager.calculate_position_size()`, `get_quantity()`, `get_final_position_size()` — legacy sizing path, fully superseded by `PositionSizeEngine`, never called from the live path.
- `RiskManager.calculate_trailing_sl()`, `get_atr()`, `get_status()`, `set_broker_client()` — all unreferenced.
- Module-level `check_daily_loss_limit()` in `risk_manager.py` — self-labeled `"""Legacy compatibility function"""`, imported into `core/risk/__init__.py` but never called.
- Config cleanup: `MAX_LOTS`, `MIN_LOTS`, `POSITION_SIZING_ENABLED`, `POSITION_SIZING_METHOD` env vars removed (only fed the dead sizing path); `trailing_sl_enabled`/`trailing_activation_amount`/`trailing_atr_multiplier`/`trailing_lock_pct`/`position_size_low/high/normal_vix`/`atr_risk_multiplier`/`vix_low/high_threshold` CONFIG dict entries removed (only read by the dead methods).
- **Files:** `core/risk/risk_manager.py`, `core/risk/__init__.py`, `config/constants.py`, `.env`, `.env.example`

### 1.5 Hardcoded strategy/exit values moved to `.env` (owner-control gap)
Moved to `.env`-driven config, defaults verified identical to prior hardcoded values (pure refactor):
- RSI thresholds: `RSI_OVERBOUGHT`, `RSI_OVERSOLD`, `RSI_EXIT_MIN_PROFIT_POINTS`, `RSI_REVERSAL_CE/PE_EXIT`, `RSI_REVERSAL_CE/PE_EXTREME`
- `REQUIRE_CONSECUTIVE_SIGNALS` (was a literal in the CONFIG dict)
- `STRIKE_PREMIUM_MIN`/`MAX` (strike-selection band in `broker.py`, distinct from `MIN/MAX_ENTRY_PREMIUM`) — later widened to match `MIN/MAX_ENTRY_PREMIUM`, see §14.4.
- ATR-adaptive SL/TP: `ATR_SL_HIGH/LOW_THRESHOLD`, `ATR_HIGH/LOW_SL/TP_ADJUSTMENT`, `ATR_SL/TP_MIN_POINTS`
- **Files:** `config/constants.py`, `core/engines/exit_engine.py`, `core/trading/broker.py`, `strategies/smart_scalp_v3.py`, `.env`, `.env.example`

### 1.6 DVF virtual-trade PnL always computed as `0.0`
- **What was wrong:** `record_decision()` in `core/validation/paper_executor.py` read `decision.get("position_size_recommendation")`, which the caller (`entry_engine.py`) never set — defaulted to `0`, making every virtual trade's qty 0, so `pnl = price_diff * 0 = 0` always.
- **Fix:** Falls back to `LOT_SIZE` instead of `0`. Verified end-to-end: a test decision now produces `pnl=975.0` instead of `0.0`.
- **File:** `core/validation/paper_executor.py`

### 1.7 Database bloat — no retention on per-tick tables
- **What was wrong:** `signals` and `dvf_signals` tables logged every strategy evaluation (not just trades), growing to 1.13M rows each — 1.4GB `core/data/trades.db`.
- **Fix:** Added `prune_old_signal_rows(retention_days=7)`, called at `app.py` startup. One-time cleanup already run: deleted 1,062,844 / 1,062,860 rows respectively, no impact on the live bot during the ~6.5min operation (WAL mode). **Note:** file size on disk is unchanged until a `VACUUM` is run — deliberately not done while the bot could be live; do during a maintenance window.
- **Files:** `core/services/database.py`, `app.py`

### 1.8 Signal/cooldown crash-loop (pre-existing, already fixed before the 08-28 session started)
- Confirmed via log forensics (09:21-10:06 on 08-27): `state_cooldown()` crashed with `TypeError` whenever `cooldown_until` was `None` (several ENTRY_READY→COOLDOWN paths never set it), causing a rapid IDLE→ENTRY_READY→COOLDOWN→crash→IDLE cycle every ~1-2s instead of respecting the real cooldown. The fix (null-check + fallback duration) was already present in the uncommitted working tree when the 08-28 session began — verified working (pattern stopped exactly at 10:06:10, all later signals correctly spaced).
- **No action needed** — documented here only so the history makes sense.

### 1.9 Cooldown gaps — FIXED 2026-08-31, see §14.3
- `COOLDOWN_AFTER_PROFIT` (30s) was loaded from `.env` but never referenced anywhere in `get_cooldown_duration()` — wins got the same 120s cooldown as everything else.
- Non-trade blocks (risk block, execution-drift skip, position-size-zero, order failure) reused the same generic `get_cooldown_duration()` as real trade exits.
- Originally flagged/not fixed during the 08-28 session; fixed as part of the 2026-08-31 full Section 2 sweep — see §14.3 for the actual fix (new `COOLDOWN_AFTER_PROFIT_SEC` wiring and `COOLDOWN_NON_TRADE_BLOCK_SEC`).

### 1.10 Duplicate bot instance / process management
- **What was wrong:** A restart left the old process suspended (`T` state, likely a stray Ctrl+Z) instead of exiting; a second instance was started on top of it, both hitting Angel One's API simultaneously → the "Access denied — exceeding access rate" error.
- **Fix applied (session-only, not code):** killed the stale process (`kill -9`, since it was stopped and unresponsive to `SIGTERM`). No code change — this was an operational fix, not a bug fix. **Process hygiene note for future restarts:** always confirm `pgrep -af "app.py"` shows the expected count before and after restarting. (A code-level single-instance guard was later added — see §11.4.)

### 1.11 Consecutive-loss deadlock — highest-impact fix of the 08-28 session
- **What was wrong:** `RiskManager.check_streak_limits()` blocked new entries permanently after `CONSECUTIVE_LOSS_LIMIT` (2) losses — the only way to clear it was a win, but a win can't happen while blocked. **Real production impact measured:** 2,048 consecutive `"RISK BLOCKED: Consecutive losses: 2, PAUSE"` events from 11:21:18 to 15:16:00 on 2026-08-28 — the bot didn't trade for the last ~4.5 hours of that session.
- **Fix:** Time-based pause reusing the already-existing (but previously unused by this code path) `pause_after_consecutive_loss_sec` / `COOLDOWN_AFTER_CONSEC_LOSS=900` (15min) config — mirrors the pattern already working in `state_machine.check_trade_limits()`. Verified: triggers correctly, auto-clears and resets the streak counter after the window.
- **Later found to have a residual issue (double-pause) and fully consolidated — see §2.9/§14.7.**
- **File:** `core/risk/risk_manager.py`

### 1.12 Logger date-split across midnight
- **What was wrong:** `run_with_auto_reconnect()`'s `temp_logger` is constructed once at process launch and keeps that date forever. When the bot's pre-market standby sleep crosses midnight, the actual trading day's logger (constructed fresh inside `main()`) correctly uses the new date, but `temp_logger`'s final "Trading day completed"/"SESSION ENDED" messages still land in the *previous* day's folder. Confirmed empirically: 08-28's actual trading is in `logs/2026-08-28/bot.log`, but its "Trading day completed"/"SESSION ENDED" lines are in `logs/2026-08-27/bot.log` at `15:30:02`, sitting next to 08-27's own real completion at `15:30:04`.
- **Fix:** `run_with_auto_reconnect()` now checks whether `temp_logger.today_dir` still matches the current date right after `main()` returns, and constructs a fresh `BotLogger` if not. Verified: `BotLogger` safely appends to an existing dated folder rather than truncating it.
- **File:** `core/main.py`

### 1.13 Gap protection / win-streak pause / weekly-loss reset — never wired
- **What was wrong:** Three risk features had working *check* logic that ran every tick, but their corresponding *state-updating* functions were never called from anywhere:
  - `set_previous_close()` — gap protection always saw `previous_close=None`, so it never activated.
  - `record_trade()`/`update_streak()` — never called, so `consecutive_wins`, `self.daily_pnl` (RiskManager-level), and profit-lock all stayed frozen at their initial values regardless of real trading outcomes.
  - `end_of_day()`/`end_of_week()` — never called, so `weekly_pnl` never resets and would accumulate indefinitely across weeks.
- **Fix:**
  - `core/main.py`'s `init_features()` now derives the previous trading day's close from the historical warm-up candles and calls `rm.set_previous_close()`.
  - `state_machine.py`'s trade-exit path now calls `rm.record_trade({...})`.
  - `core/main.py` calls `rm.end_of_day()` at market-close shutdown.
  - `RiskManager.__init__` now persists/reads a `last_active_date` and calls `end_of_week()` automatically when a new ISO week is detected.
- **Verified live on 08-28:** `✓ Previous close set for gap protection: ₹24,090.85` at startup; `capital` field in risk-budget logs correctly tracked cumulative PnL trade-by-trade (proof `record_trade()` is live). Confirmed live again on 08-31 (gap protection fired on both process starts that day).
- **Note:** this fix wiring `record_trade()` into the exit path is the direct trigger for the double-pause bug later found and fixed in §2.9/§14.7 — see that entry's timeline for the full causal chain.
- **Files:** `core/risk/risk_manager.py`, `core/main.py`, `core/engines/state_machine.py`

### 1.14 TP ceiling vs. trailing ladder conflict
- **What was wrong:** A flat `TP_POINTS_FIXED=14` take-profit fired unconditionally in `check_hard_sl()`, cutting off the step-trailing ladder (which goes up to +50) before its higher rungs (+16, +20, +25, +30, +40, +50) could ever be tested. Real evidence: 5 historical "TAKE PROFIT" exits, all landing right at the 14pt line; zero "TRAILING PROFIT" exits show a peak above +14.
- **Fix:** TP check now only applies `if not TRAILING_ENABLED`. Verified: a simulated trade jumping to +16pts in one tick no longer exits at the flat target; it stays open under the ladder's own +11 rung.
- **File:** `core/engines/exit_engine.py`

### 1.15 Missing breakeven step before +8
- **What was wrong:** `EXIT_BREAKEVEN_TRIGGER_POINTS`(4)/`EXIT_BREAKEVEN_BUFFER_POINTS`(2) were imported and assigned to module constants but never used in `get_step_trailing_sl()`'s actual ladder — a trade had zero profit protection between entry and the first real TSL rung at +8.
- **Fix:** Folded into the same ladder as an earlier rung. Verified: a trade at +4pts now locks a stop at +2pts.
- **File:** `core/engines/exit_engine.py`

### 1.16 MFE/MAE tracked from a global tick buffer, not scoped to the trade
- **What was wrong:** `compute_trade_mfe_mae_from_ticks()` used `runtime_state.get_recent_ticks()` — a global rolling buffer shared across the whole bot, not scoped to an individual trade. **Confirmed via sanity check:** realized PnL can never exceed MFE (a logical impossibility if it does) — this failed on 8/42 (19%) of trades with any stored MFE, and 6/42 (14%) on the MAE side, concentrated in short (<5min) trades.
- **Fix:** `check_hard_sl()` now tracks `trade['mfe_inr']`/`trade['mae_inr']` directly on the trade dict every tick (same place `max_profit_points` was already tracked) — trade-scoped by construction. `state_machine.py`'s exit-logging now reads these instead of calling the old global-buffer function.
- **Verified in isolation:** simulated price path 100→103→101→105→98 correctly produced `mfe=+5pts(₹325)`, `mae=-2pts(-₹130)`.
- **Important:** the old `compute_trade_mfe_mae_from_ticks()` function itself was left in place (still covered by an existing test, `tests/test_dvf_pipeline.py`) — only the *live trade-logging* call site was switched. All DB rows predating this fix have `mfe`/`mae` values that cannot be trusted.
- **Post-fix caveat found 2026-08-31:** on the loss side specifically, `mae` isn't a strict floor anymore in every case — see the analysis notes in `findings.md`'s "outstanding follow-ups" for why (interacts with §1.17's real-fill-price change).
- **Files:** `core/engines/exit_engine.py`, `core/engines/state_machine.py`

### 1.17 Asymmetric spread accounting between wins and losses
- **What was wrong:** `broker.py`'s `exit_position()` used real bid/ask tick pricing for wins, but unconditionally substituted the exit-engine's LTP-based estimate for any loss (originally meant as a safety cap, but implemented as a full override, not a floor). **Confirmed with real data, verified two independent ways:** (1) parsing exit-message embedded amounts vs. stored `pnl` — losses matched the message exactly (~₹0 diff) while wins were systematically lower (avg -₹10 to -₹70 depending on exit type); (2) computing points directly from `entry_price`/`exit_price` fill columns for all 25 trades on 08-27/08-28 — every mismatch between fill-implied and stored pnl was a loss trade, always in the direction of the fill-based version being worse.
- **Fix:** `exit_position()` now uses the real bid/ask PnL for losses too, with the engine's capped value applied only as a hard floor (`pnl_inr = max(pnl_inr, -max_loss)`), not an unconditional substitute.
- **Verified in isolation, all 4 branches:** (a) loss milder than cap → real fill value used (spread cost now included), (b) loss exceeding cap → still floored correctly, (c) win with suspiciously-zero tick PnL → engine value still used (edge case preserved), (d) normal win → unchanged.
- **Real-world magnitude found:** on 08-27, true fill-based net points were **-9.40pts** (~-₹611) vs. the ~-₹557 that was actually recorded; on 08-28, true net was **+0.70pts** (~+₹45.50) vs. the +₹74.10 that was recorded. Both days' true results were worse than what was displayed at the time.
- **File:** `core/trading/broker.py`

### 1.18 Files touched during the 08-28 session (for reference)
- `config/constants.py`, `core/engines/position_size_engine.py`, `core/engines/exit_engine.py`, `core/engines/state_machine.py`, `core/risk/risk_manager.py`, `core/risk/__init__.py`, `core/trading/broker.py`, `core/main.py`, `core/services/database.py`, `core/validation/paper_executor.py`, `strategies/smart_scalp_v3.py`, `app.py`, `.env`, `.env.example`

---

## 2. Fixed items originally from the Senior Engineering Review (2026-08-28)

These were opened in the original "Section 2" open-findings list and later fixed — either same-week (§2.1/§2.3/§2.5-§2.10, all fixed 2026-08-31 in the full sweep, see §14 for the actual fix content) or already covered above (§2.5's underlying issue is §1.9/§14.3). §2.2 and §2.4 are **not** here — they're genuinely still open (a testing gap and a watch-and-see item respectively) and live in `findings.md`.

- **§2.1** [Architecture] Backtest ran completely different exit logic than live — **FIXED, see §14.1**.
- **§2.3** [Architecture — minor] Inconsistent lock discipline around `broker.last_tick` in `check_and_rotate_strike()` — **FIXED, see §14.2**.
- **§2.5** [Config gap] `COOLDOWN_AFTER_PROFIT` dead, non-trade blocks reused trade-exit cooldown logic — **FIXED, see §14.3** (same underlying issue as §1.9).
- **§2.6** [Config inconsistency] `STRIKE_PREMIUM_MIN/MAX` (90-150) narrower than `MIN/MAX_ENTRY_PREMIUM` (70-350) — **FIXED, see §14.4**.
- **§2.7** [Cosmetic] `MAX_HOLD_TIME_WINNING`/`MAX_HOLD_TIME_LOSING` imported into `exit_engine.py`, never used — **FIXED, see §14.5**.
- **§2.8** Documentation-only: exit-priority docstring didn't match actual code order — **FIXED, see §14.6**.
- **§2.9** [Moderate] Consecutive-loss pause was double-tracked by two unsynced implementations — **FIXED, see §14.7**. Full investigation detail (three-session timeline: 08-27 baseline, 08-28 deadlock, 08-31 double-pause) is preserved in §14.7 below since it's genuinely useful root-cause history, not just a fix note.
- **§2.10** [Moderate] WebSocket subscribe/unsubscribe ACK-wait was waiting for a confirmation SmartAPI never sends — **FIXED, see §14.8**. Full root-cause investigation (traced against Angel One's own SDK, cross-session evidence back to 2026-08-03) preserved in §14.8.

---

## 4. Plan agreed 2026-08-28 — executed

1. ~~Do not apply further fixes until the next session's data is reviewed.~~ Honored — no further fixes were applied between 08-28 and the 08-31 session.
2. ~~Restart the bot in clean paper-trading mode for one full session — Monday, 2026-08-31.~~ Done — the 08-31 session ran a full day (08:06-15:30), collected in `logs/2026-08-31/`.
3. ~~Collect full day's logs, trades table, live crash/error monitor output.~~ Done.
4. **Analyze together** — done, in the conversation that produced §14 and the log-analysis behind §2.9/§2.10. Specific sub-items:
   - MFE vs. realized points, broken down by exit condition — analyzed; RSI Reversal Exit captured 95-97% of MFE on 08-31 (the first trustworthy data point since §1.16's fix), but the trailing-ladder/breakeven questions (items 4-5 in the old Section 3) remain open — no 08-31 trade's favorable move reached the +4pt breakeven trigger, so those fixes are still functionally unexercised. See `findings.md` Section 3 for what's still genuinely open here.
   - Whether any exit category is systematically leaving profit on the table — partially answered (RSI Reversal: no); others still open.
   - Whether the TP-ladder/breakeven fixes behaved as intended live — inconclusive, no trade reached them.
   - Whether consecutive-loss pause, gap protection, daily-loss tracking fire correctly — analyzed; gap protection confirmed working, consecutive-loss pause found to have the double-pause bug (now fixed, §2.9/§14.7).
   - Cross-checked against Section 2/3 open items — done, resulted in §2.9 and §2.10 being discovered and then the full Section 2 sweep.
5. **Decide priority and scope of the next round of fixes** — done: user asked for (and got) the entire Section 2 backlog fixed, see §14.

---

## 6.6 `run.sh` — checked and confirmed fine (no issue)
*(from the 2026-08-28 `run.sh` review, investigation only — items 6.1-6.5 are still open, see `findings.md`)*
- All 25 files referenced in `run_syntax_check()`/`menu_health()` exist — no broken references.
- `summary.json` generation works correctly for all recent sessions (08-26/27/28) — an earlier suspicion of a gap here was a false alarm caused by a truncated `find | head -5`, not a real bug.
- `TRADING_START`/`TRADING_END` env var names match what `config/constants.py` actually reads — no naming mismatch.

---

## 7.1 Telegram — the `send_alert()` transport itself is confirmed working
*(from the 2026-08-29 follow-up check — the main §7 finding about the four dead `notify_*` functions is still open, see `findings.md`)*

- **What I checked:** traced the full path for the 4 `send_alert()`/`get_telegram()` call sites (PnL-capped in `exit_engine.py:481`, spike detection in `state_machine.py:197`, high slippage in `broker.py:1741`, emergency exit-failure in `broker.py:1944`).
- **Verdict: genuinely wired, not dead.** `TelegramBot.send_message()` queues a message; a background thread (`_bg_worker`, started via `TelegramBot.start()`) drains the queue and sends via `aiohttp`. Confirmed `.start()` is actually called — `init_telegram()` (`telegram_bot.py:977-981`) calls it internally, and `core/main.py:167-175` calls `init_telegram()` whenever `TELEGRAM_ENABLED=true` (which it is). `send_alert()` correctly null-checks the module singleton before sending.
- **Real-world evidence it has actually fired, not just wired-on-paper:** grepped the logs — `"PnL CAPPED"` alerts fired **5 times on 08-27, 4 times on 08-28** (9 total), matching exactly the known early-loss-cut/soft-loss-exit trades; **7 more times on 08-31**. Spike/slippage/emergency-exit-failure show 0 occurrences — consistent with those specific conditions simply never having happened, not a bug.
- **What I can't verify from here:** whether those alerts were actually *received* in the Telegram chat (requires checking the Telegram app itself, not available from this environment). Worth a manual glance at Telegram history to close the loop.
- **One trivial inconsistency, not a bug:** `broker.py:1944` calls `get_telegram().send_message()` directly instead of the `send_alert()` wrapper (which just prepends a 🚨 emoji) — cosmetic only.
- **Net picture on Telegram overall:** works and confirmed firing — `notify_startup()`, plus the ad-hoc `send_alert()` edge-case alerts (PnL cap, spike, slippage, emergency). Never wired, confirmed dead — the four structured `notify_entry/exit/kill_switch/daily_summary` functions (still open, see `findings.md`).
- **Status: informational — no fix needed for this part.** Confirms the still-open §7 fix (wiring the four dead functions) can reuse this same, already-working transport; no new plumbing required, just the missing call sites.

---

## 8.3 `mode_switch.py` — checked, confirmed not an issue: `reset_mode()` is never called
*(from the 2026-08-28 review — §8.1, §8.2, §8.4 are still open, see `findings.md`)*
- Looks like a gap (a "reset for new day" function with zero callers) but isn't a deadlock — the bot's daily process restart naturally reinitializes the module-level `_current_mode = MODE_AGGRESSIVE` on fresh import. Redundant given the architecture, not broken.

---

## 10.3 `database.py` — confirmed alive and working, no issue
*(from the 2026-08-28 review — §10.1, §10.2 are still open, see `findings.md`)*
- The market-quality/confidence-calibration analytics cluster (`get_market_quality_distribution`, `get_hard_reject_stats`, `get_market_quality_win_rate_bands`, `get_market_quality_grade_win_rate`, `get_confidence_win_rate_bands`, `get_confidence_calibration`, `get_market_quality_grade_avg_pnl`) is genuinely consumed by `utils/mq_validation_report.py`, which runs automatically at shutdown (matches the `"✓ MQ validation archived"` line seen in every session's logs). Real, working feature.

---

## 11. Code-review session (Sunday, 2026-08-30) — 10 findings, all fixed same-day

A multi-agent (8-angle) code review was run against the full scope in play: the committed `run.sh` addition, the entire uncommitted working-tree diff (28 tracked files), and new untracked files (`get_fresh_evidence.py`, `get_old_evidence.py`, 4 new test files). Every finding below was independently confirmed by reading the actual current code (not just trusting the finder agent) before being fixed. All fixes verified with `venv/bin/python -m pytest tests/` (the real venv `run.sh` uses, per §6.2) — full suite green, no regressions, both before listing findings to the user and after applying every fix.

### 11.1 [Critical — real money] `KILL_SWITCH_LOSS` contradicted its own comment, live in both the code default and the actual running `.env`
- **What was wrong:** `config/constants.py:270` set `KILL_SWITCH_LOSS = env_int('KILL_SWITCH_LOSS', 3000)` right next to a comment reading `# Reduced from 900 to 600 (1.5% of 30k capital)` — the value and the comment disagreed by 5x. Worse: the live, gitignored `.env` file (the config actually used at runtime) independently had `KILL_SWITCH_LOSS=3000` too, so this wasn't just a stale template — the bot's real emergency stop-loss was running 5x looser than documented/intended. It also sat *above* `MAX_DAILY_LOSS_AMOUNT` (2500 in the code default), which made the dedicated kill-switch check in `core/risk/kill_switch.py:191` structurally unreachable — the generic daily-loss check at line 195 would always fire first.
- **Fix:** Set the code default back to `600` (matching the comment) and added a comment explaining it must stay below `MAX_DAILY_LOSS_AMOUNT` for the ordering to be correct. Also corrected the live `.env`'s `KILL_SWITCH_LOSS` from `3000` to `600` — this is a real behavior change to the bot's actual current configuration, not just the template.
- **Verified:** `python -c "import config.constants as c; print(c.KILL_SWITCH_LOSS, c.MAX_DAILY_LOSS_AMOUNT)"` now prints `600 3000` (was `3000 3000`) — kill switch will fire first, at the intended tighter threshold.
- **Superseded direction 2026-08-31 — see §13:** the user later decided ₹3,000 is the real intended ceiling, not ₹600; the live `.env` was changed again accordingly. §13 has open follow-ups from that (template/code-default drift) — see `findings.md`.
- **Files:** `config/constants.py`, `.env`

### 11.2 [Critical — silently negated all risk retuning] `.env.example` shipped pre-retune values for ~22 constants
- **What was wrong:** The tracked `.env.example` template still had the old values for `RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS`, `MAX_DAILY_LOSS_PCT`, `DAILY_LOSS_ALERT`, `SL_POINTS`, `TP_POINTS`, `MAX_TRADES_PER_DAY`, all four cooldown constants, `KILL_SWITCH_*`, `TICK_TIMEOUT_SEC`, `MIN_OPTION_PRICE`, `DELTA_MAX`, `RSI_PERIOD`, `ENTRY_MAX_DRIFT_PCT`, etc. Since `env_int`/`env_float` (`config/configuration.py`) always prefer an explicit `.env` value over the code default, anyone following the documented `cp .env.example .env` setup would silently get the old, un-retuned config with no warning.
- **Fix:** Wrote a script to extract every `env_int('NAME', default)` / `env_float(...)` call in `config/constants.py` and diff it against `.env.example`'s active (uncommented) values; updated all 22 mismatches to match the current code defaults (post-11.1 fix, so `KILL_SWITCH_LOSS=600` in the template too).
- **Verified:** Re-ran the same diff script — zero mismatches remain.
- **File:** `.env.example`

### 11.3 [Serious — real money] Position-sizing "razor-thin miss rescue" could bypass enforced risk caps
- **What was wrong:** `core/engines/position_size_engine.py:165`'s rescue (rounds a computed 0-lot position up to 1 lot when within `min_lot_rounding_tolerance_pct`, default 5%, enabled by default) compared against `capped_risk_amount` — the value *after* `_apply_risk_caps()` had already clamped it to the daily/recovery/remaining-risk budget. So the rescue could push the actual risk taken above an enforced cap by up to 5%, exactly when the account was already risk-constrained (near daily loss cap or in recovery mode).
- **Fix:** Added a `not capped` condition — the rescue now only fires when the shortfall is due to a wide ATR-adjusted SL against an *uncapped* budget (the case it was designed for), never when a hard risk-budget cap was the reason for the near-zero result.
- **Verified:** Reasoned through `_apply_risk_caps()`'s five cap reasons (`max_capital_allocation_pct`, `daily_risk_cap_pct`, `remaining_risk_amount`, `max_symbol_daily_risk_pct`, `recovery_mode_cap_pct`) — all set `capped=True`, all now correctly block the rescue. Full test suite still green (no test exercised the old bypass behavior).
- **File:** `core/engines/position_size_engine.py`

### 11.4 [Serious — double-trading risk] `run.sh` had no single-instance guard
- **What was wrong:** Nothing in `run.sh` checked for an existing PID file, lock file, or already-running `app.py` process before `launch_bot()` started a new one. Running the launcher twice (two terminals, or a stale session after a disconnect) would start two live processes trading the same broker account concurrently.
- **Fix:** Added a PID-file guard at the top of `launch_bot()` (`$SCRIPT_DIR/.run_bot.pid`): if a live process with that PID exists, refuse to launch and tell the operator; if the PID file is stale (process dead), reclaim it. Writes the current PID and cleans it up via a `RETURN` trap when the function exits normally (a stale file from a hard kill/crash is auto-reclaimed on the next launch attempt regardless).
- **Verified:** `bash -n run.sh` — syntax OK.
- **File:** `run.sh`

### 11.5 [Serious — risk] RSI overbought/oversold and momentum-exhaustion guards had been loosened with no compensating control
- **What was wrong:** `strategies/smart_scalp_v3.py` had loosened four RSI-based guards: overbought disqualify 75→80, oversold disqualify 25→20, CE exhaustion-block 70→80, PE exhaustion-block 30→20 — letting the strategy enter/hold materially deeper into overbought/oversold territory before its own risk brake fired, with nothing else added to compensate.
- **Fix:** Reverted all four thresholds to their prior, stricter values (75/25/70/30) at lines ~707, 775, 807, 1225, 1237.
- **Verified:** Full test suite green (`tests/test_smart_scalp_confidence.py` covers this file).
- **File:** `strategies/smart_scalp_v3.py`

### 11.6 [Moderate — risk tracking] Breakeven trades counted as losses toward the consecutive-loss streak
- **What was wrong:** `RiskManager.record_trade()` called `self.update_streak(pnl > 0)` — a boolean, so a breakeven trade (`pnl == 0`) fell into the `else` (loss) branch, incrementing `consecutive_losses` and feeding the consecutive-loss cooldown gate (§1.11 above) for a trade that didn't actually lose money.
- **Fix:** Changed `update_streak()` to take the raw `pnl` and handle three cases explicitly: `pnl > 0` → win, `pnl < 0` → loss, `pnl == 0` → neither counter moves (true no-op, streak unaffected).
- **Verified:** Only caller (`record_trade()`) updated to pass `pnl` directly; no test referenced the old boolean signature. Full suite green.
- **File:** `core/risk/risk_manager.py`

### 11.7 [Moderate — risk tracking] RiskManager trade-recording failures were silently swallowed
- **What was wrong:** `state_machine.py`'s exit path wraps `rm.record_trade(...)` — the *only* call site that updates `RiskManager`'s `daily_pnl`/`weekly_pnl`/`consecutive_losses` (which `can_trade()`'s weekly-loss and consecutive-loss gates read directly) — in a bare `try/except` that only logged a `warning`. Any transient exception there would silently stop those risk gates from reflecting a real loss, with no visibility.
- **Fix:** Elevated to `logger.error(..., exc_info=True)` with the trade's pnl/direction in the message, and added a `state.risk_tracking_failures` counter so repeated misses are observable/monitorable, without changing the non-fatal control flow (a full kill-switch escalation here would be a bigger behavioral decision than this review's scope).
- **File:** `core/engines/state_machine.py`

### 11.8 [Moderate — data integrity] Live candle buckets mislabeled with a hardcoded IST offset regardless of server timezone
- **What was wrong:** `core/runtime/state.py`'s `get_canonical_candles()`/`rebuild_candles()` converted tick epoch timestamps with `datetime.fromtimestamp(ts_sec)` — which uses the *server's local* timezone — then stamped the resulting bucket key with a literal `+05:30` suffix regardless of whether the server's local time was actually IST. On a UTC-default host (common for cloud/container deployments), this would silently shift every live candle bucket by 5.5 hours relative to AngelOne's genuinely-IST-timestamped historical candles, breaking the merge and corrupting the indicator input series.
- **Fix:** Added an explicit `IST = timezone(timedelta(hours=5, minutes=30))` constant and switched both `datetime.fromtimestamp(ts_sec)` call sites to `datetime.fromtimestamp(ts_sec, tz=IST)` (and the `datetime.now()` fallbacks to `datetime.now(tz=IST)`) — bucket timestamps are now correct regardless of the server's system timezone.
- **File:** `core/runtime/state.py`

### 11.9 [Moderate — indicator correctness] `chunk_size` formula from legacy tick-chunking reused against the new canonical-candle arrays
- **What was wrong:** `strategies/smart_scalp_v3.py:calculate_indicators()`'s canonical-candle path (`prices`/`highs`/`lows` already 1:1 per candle) set `chunk_size = max(1, len(prices) // 60)` — a formula meant for the *legacy* tick-chunking fallback, where it maps a chunk index back into a raw per-tick array. Once merged canonical candles exceeded ~120, this made `chunk_size > 1`, so the ATR loop's `prices[i*chunk_size]` and the `High`/`Low` indicators' `prices[-chunk_size:]` slicing silently pulled data from the wrong candle.
- **Fix:** Removed the override for the canonical path — `chunk_size` now stays at its initializer value of `1` (correct 1:1 indexing) whenever canonical candles are in use; the legacy fallback path (genuinely tick-chunked) keeps its own separate `chunk_size` computation unchanged.
- **File:** `strategies/smart_scalp_v3.py`

### 11.10 [Moderate — operational] Auto-restart loop printed "Restart 1/1" but never actually restarted
- **What was wrong:** With the default `APP_OWNS_RECONNECT=true` (`MAX_RESTARTS=1`), `run.sh`'s restart `while` loop incremented `RESTART_COUNT` to 1 on a crash, printed `"Restart 1/1 in 10s..."`, slept 10s, then immediately hit `RESTART_COUNT -ge MAX_RESTARTS` and broke — `app.py` was never actually re-invoked. The reassuring message implied a restart attempt that never happened, leaving any open position unmanaged by the launcher after a crash.
- **Fix:** Restructured as `while true; do run app.py; ... increment RESTART_COUNT; if > MAX_RESTARTS: stop (no restart message); else: print the restart message, sleep, loop back and actually rerun app.py; done`. With `MAX_RESTARTS=1`, a single crash now genuinely triggers exactly one restart, matching the printed message.
- **Verified:** `bash -n run.sh` — syntax OK.
- **File:** `run.sh`

### 11.11 Files touched this session
`config/constants.py`, `.env.example`, `.env`, `core/engines/position_size_engine.py`, `run.sh`, `strategies/smart_scalp_v3.py`, `core/risk/risk_manager.py`, `core/engines/state_machine.py`, `core/runtime/state.py`. Full test suite (`venv/bin/python -m pytest tests/`) green both before and after — no regressions from any of the 10 fixes above.

---

## 12. DVF virtual trades orphaned OPEN forever after a process restart (Sunday, 2026-08-30, evening)

- **How this was found:** user pulled up the DVF menu's "Recent Virtual Trades" view and saw 20 trades from 2026-08-28 09:45:30-09:45:59, all still `status=OPEN`, `pnl=0.0`, two days later.
- **What was wrong:** `record_decision()`/`update_open_positions()` (`core/validation/paper_executor.py`, added earlier per §1.6) track open virtual positions in a plain in-process dict, `_OPEN_VIRTUAL_POSITIONS`. A position is only ever closed when a *later tick arrives while that same process is still running* — either a symbol-matched virtual SL/TP hit, or a 30-minute (`_MAX_VIRTUAL_HOLD_SEC=1800`) safety expiry checked on any subsequent tick. The `dvf_trades` DB row, however, is `INSERT`ed as `OPEN` immediately at entry. If the bot process restarts before that in-memory safety expiry fires, the dict is wiped clean on the next launch, and the DB row is never revisited — it stays `OPEN` permanently. This is the same underlying failure pattern as §10.1 (no recovery of in-memory position state across a restart), but on the DVF/paper-tracking side rather than the live `active_positions` side.
- **Fix — startup reconciliation, not persistence:**
  - `core/services/database.py`: added `get_open_dvf_trades()` (DB method + module-level wrapper) to fetch all `status='OPEN'` rows.
  - `core/validation/paper_executor.py`: added `reconcile_stale_open_positions(max_age_sec=1800)` — force-closes any DB-side `OPEN` row older than the safety-expiry window via the existing `simulate_exit()` path (flat exit at entry price, `exit_reason="Virtual max hold (reconciled on restart)"`).
  - `core/main.py`: calls it once right after `broker.connect()` succeeds, before the historical warm-up, so every startup sweeps up whatever the previous process instance left dangling.
- **Verified:** ran the reconciler against the real `core/data/trades.db` — closed **252** orphaned `OPEN` rows (all pre-existing, including the 20 the user spotted). `get_open_dvf_trades()` now returns 0. `venv/bin/python -m pytest tests/test_dvf_pipeline.py tests/test_exit_engine_sequence_regression.py tests/test_exit_engine_tsl_steps.py` — all pass, no regressions.
- **Not done:** true persistence (e.g., reconstructing `_OPEN_VIRTUAL_POSITIONS` from DB `OPEN` rows at startup so a position genuinely resumes tick-by-tick tracking instead of being force-closed flat). The reconciliation approach was chosen because DVF is explicitly analytics-only, read-only, never-feeds-back-into-trading (per the module's own "golden rule" comment) — a flat force-close on restart is simpler and safer than trying to resume tracking with a gap in tick history, at the cost of those specific reconciled trades having a synthetic (not real) exit price/pnl. **Any trade with `exit_reason = "Virtual max hold (reconciled on restart)"` should be excluded from PnL/expectancy analysis**, same caveat as the pre-fix MFE/MAE data in §1.16.
- **Files:** `core/services/database.py`, `core/validation/paper_executor.py`, `core/main.py`

---

## 13. Kill switch vs. `MAX_DAILY_LOSS` mismatch, resurfaced and resolved the other direction (Monday, 2026-08-31, live trading day)

- **How this was found:** user asked to check on the running bot mid-session; log/config review of `core/risk/kill_switch.py` and `config/constants.py` found the same class of mismatch as §11.1, but the live `.env` had drifted back to `KILL_SWITCH_LOSS=600` / `MAX_DAILY_LOSS=3000` (i.e. the pre-§11.1 state) by this session, plus a related gap not caught in §11.1: `check_daily_loss_alert()` (a third, `DAILY_LOSS_ALERT=1500` threshold) is fully wired with its own function but has **zero callers** anywhere in the live path — a dead pre-warning that would never fire even if the other two were aligned.
- **What was wrong (confirmed live, this session):** `emergency_check()` checks `KILL_SWITCH_DAILY_LOSS` (=`KILL_SWITCH_LOSS`, 600) before `MAX_DAILY_LOSS_AMOUNT` (3000) — since 600 < 3000, the bot was hard-stopping trading at ₹600 of daily loss, not the ₹3,000 the owner intended as "max daily loss." The `risk_manager.get_risk_budget()` sizing math (`remaining_risk_amount`, `loss_utilization`) computed against the 3000 figure regardless, so position sizing/dashboards reported far more daily-loss runway remaining than the kill switch would actually allow.
- **Decision (explicit, from the user, this session):** ₹3,000 is the real daily loss ceiling. The kill switch must equal that number, not the tighter ₹600 — the opposite direction from §11.1's fix, which had instead pulled `MAX_DAILY_LOSS`/comments down to match the 600 figure. This is a deliberate business/risk-tolerance call, not a correction of §11.1 being wrong at the time.
- **False start (reverted in full before the real fix):** first attempt restructured `config/constants.py`/`core/risk/kill_switch.py` to derive `KILL_SWITCH_LOSS` from `MAX_DAILY_LOSS_AMOUNT` (single source of truth) and set both to 600 — i.e. still the §11.1 direction, before the user's actual preference (3000) was confirmed. User said stop, and asked for a full revert. Reverted precisely (not `git checkout`, since `.env`/`.env.example`/`config/constants.py` already carried unrelated uncommitted work from earlier in the week) — confirmed via `git diff` that `.env` and `core/risk/kill_switch.py` came back byte-identical to their pre-edit state, and that `.env.example`/`config/constants.py` only retained their pre-existing (non-session) diffs.
- **Actual fix applied (minimal, per the user's explicit "kill switch = maximum daily limit"):** changed exactly one line in the live `.env` — `KILL_SWITCH_LOSS=600` → `KILL_SWITCH_LOSS=3000`, matching the existing `MAX_DAILY_LOSS=3000`. No code changes; `KILL_SWITCH_DAILY_LOSS` and `MAX_DAILY_LOSS_AMOUNT` now evaluate to the same 3000 at runtime, so `emergency_check()`'s two checks agree (the second is harmless dead-equal redundancy, not a new bug).
- **Verified live 2026-08-31:** the second bot process that morning (booted 09:49:46, after the first process's restart) logged `Kill: ₹3000 │ Max Loss: ₹3000` at startup, confirming the fix took effect for the rest of that session.
- **Live-effect caveat (resolved):** the bot process already running at the time (PID 147895, started 08:07 that morning) had loaded the old `KILL_SWITCH_LOSS=600` into memory at import time — the `.env` edit didn't affect that process until restart. A restart did happen later that morning (confirmed via the log evidence above), so this is no longer a live caveat.
- **Files:** `.env` only.
- **Note (status as of 2026-08-31):** three follow-up items from this fix (`.env.example` template still stale at 600, `config/constants.py`'s in-code defaults still mismatched, `check_daily_loss_alert()` still dead) were open at the time. **All three are now resolved:** `config/constants.py`'s defaults were updated to 3000/3000/1500 to match `.env` (confirmed by the 2026-09-01 audit, see §1b in that pass's findings); `check_daily_loss_alert()` is wired live at `core/main.py:638` (found already fixed, undocumented, by that same audit); `.env.example`'s loss-ceiling values match `.env` (600 was already gone by the time of the audit) and the 6 unrelated drifted variables found in that audit were synced in §18.3.

---

## 14. Full Section 2 backlog cleared (Monday, 2026-08-31, later the same session)

User explicitly asked to fix the entire Section 2 backlog, including items previously marked as needing a scoping conversation or explicit sign-off before any behavior change (§2.1, §2.6) — confirmed via an explicit choice between "just the two we scoped this session" and "all of Section 2." Every fix below was verified against the full test suite (both `venv/bin/python -m pytest tests/` — the real venv `run.sh` uses, 168 passed/1 skipped — and `.venv/bin/python -m pytest tests/`, 169 passed) before and after, green throughout. §2.2 and §2.4 are genuinely not code bugs (a testing gap and a watch-and-see item respectively) — nothing to change in code for either; re-confirmed and left open in `findings.md`.

### 14.1 §2.1 — Backtest now runs the exact same exit logic as live
- **What was wrong:** `core/backtest.py` had its own from-scratch SL/TP/trailing-SL simulation (`_check_sl_tp`), completely independent of `core.engines.exit_engine.check_exit_conditions()` — meaning no backtest run could tell you how the real, current exit logic (hard SL, step-trailing ladder, breakeven, early/soft loss cuts, greeks kill, RSI exit/reversal, time exit, all in their real priority order) would have performed historically.
- **Fix:** `Backtester` now builds `self.current_trade` as the same dict shape `check_exit_conditions()` expects (`entry_price`, `qty`, `side`, `direction`, `entry_time`, mutated in place with `price_diff`/`current_pnl`/`mfe_inr`/`mae_inr`/`tsl_status`/etc.) and calls the real `check_exit_conditions()` every candle via a new `_check_exit()` method, fed with:
  - a synthetic tick (`ltp`, `spot_price`, `iv`, `tte_sec`) built from the candle,
  - BSM greeks synthesized via `utils.greeks.GreeksCalculator` from an ATM-strike-from-spot approximation (historical OHLC has no real option expiry/IV, so this mirrors the same fallback `exit_engine._validated_greeks_for_exit()` already uses when it can't reach the broker's own Greeks),
  - RSI computed via the same `core.engines.state_machine._calculate_rsi()` live uses, fed the same rolling tick-history window.
  - The CLI's old `--sl`/`--tp`/trailing-SL knobs are gone — exit behavior is now sourced entirely from `config/constants.py`/`.env`, the same single source of truth live uses, not a separate CLI-tunable simulation.
- **A real bug found and fixed along the way:** `exit_engine.py`'s time-based checks (`early_momentum_loss_cut`, `soft_loss_time_exit`, `time_exit_15min`, and the "5 min before close" check) all hardcoded `datetime.now()` — correct for live (trades happen in real time) but nonsensical for backtesting, where "now" must be the historical candle's own timestamp, not today's real wall clock. Discovered via a forced-trade smoke test that crashed on `datetime.now() - trade['entry_time']` (naive vs. tz-aware) — and would otherwise have silently made hold-time-based exits fire immediately/nonsensically on every backtested trade even once the crash was worked around. **Fix:** added an overridable module-level clock (`exit_engine._now()`, backed by `exit_engine._clock_override`) — live code never sets the override, so `_now()` falls through to the real `datetime.now()` exactly as before (zero live behavior change); `backtest.py._check_exit()` sets `_clock_override` to the current candle's timestamp before each exit check and clears it after.
- **Verified:** forced-trade smoke tests (bypassing signal generation to directly exercise the exit path) confirmed a SOFT LOSS EXIT firing correctly at the right simulated hold-time (105s, matching `SOFT_LOSS_TIME_SEC`) with tz-aware timestamps, and an RSI EXIT firing correctly with naive timestamps — both previously would have crashed or fired nonsensically. A full `run_backtest()` pass over 8,000 synthetic candles completed with no errors; confirmed via `git stash` that the pre-existing (unmodified) backtest also produces zero trades on the same synthetic random-walk data, so the "0 trades" outcome on synthetic noise is a pre-existing characteristic of the strategy's strict real entry conditions, not something this fix broke.
- **Not done (open follow-up — see `findings.md`):** no dedicated automated test was added for the new exit-engine integration path itself (only the existing two backtest tests, updated for the new dict-based `current_trade` shape, plus manual smoke tests this session).
- **Follow-on fix required:** `core/validation/walk_forward_backtest.py`'s `_run_window()` constructed `Backtester(..., sl_points=args.sl, tp_points=args.tp, ...)` — both removed constructor params, would have crashed with `TypeError` on the next run. Updated to pass `day_type=args.day_type` instead (new `--day-type` CLI flag replacing the removed `--sl`/`--tp`), and updated the summary-JSON `settings` block accordingly. Also fixed a stale comment at `broker.py:513` (`# ₹120` mid-premium reference, now ₹210 post-§2.6 widening).
- **Files:** `core/backtest.py`, `core/engines/exit_engine.py`, `core/validation/walk_forward_backtest.py`, `core/trading/broker.py`, `tests/test_backtest_execution_guard_regression.py`

### 14.2 §2.3 — Lock discipline around `broker.last_tick` in `check_and_rotate_strike()`
- **Fix:** wrapped both previously-unlocked access points (`broker.py`'s premium-read and the post-rotation `self.last_tick = None` reset) in `self._tick_lock`, matching every other access site in the file.
- **File:** `core/trading/broker.py`

### 14.3 §2.5 — `COOLDOWN_AFTER_PROFIT` wired in; non-trade blocks no longer reuse the real trade-exit cooldown
- **What was wrong:** `COOLDOWN_AFTER_PROFIT` was loaded from `.env` but never referenced in `get_cooldown_duration()` — wins got the same cooldown as any other close. Separately, non-trade entry blocks (risk-gate block, execution-drift skip, position-size-zero, order failure) fell back to the same generic post-trade `get_cooldown_duration()` whenever `state.cooldown_until` was left unset, with no awareness that no capital was ever at risk on those.
- **Fix:**
  - `get_cooldown_duration(state, is_win=False)` now takes an `is_win` flag and returns `COOLDOWN_AFTER_PROFIT_SEC` when there's no active loss streak and the just-closed trade was a win (loss-streak cooldowns still take priority, unchanged). The one real call site (after a trade exit in `state_entry()`) now passes `is_win=not is_loss`.
  - Added a new `COOLDOWN_NON_TRADE_BLOCK_SEC` constant (`.env`-configurable via `COOLDOWN_NON_TRADE_BLOCK`, default 15s — deliberately much shorter than a real trade's cooldown since no capital was at risk) and set `state.cooldown_until` explicitly at all four non-trade-block return sites (risk block, exec-guard skip, position-size-zero, order failure) so they no longer fall through to the generic trade-exit cooldown logic at all.
- **Verified:** full test suite green; behavior for a real trade exit is unchanged unless `.env` is edited (`COOLDOWN_AFTER_PROFIT` already defaulted to 30s, now actually takes effect); non-trade blocks now cool down for 15s instead of 120s (`COOLDOWN_NORMAL`) or worse.
- **Files:** `config/constants.py`, `core/engines/state_machine.py`, `.env`, `.env.example`

### 14.4 §2.6 — `STRIKE_PREMIUM_MIN/MAX` widened to match `MIN/MAX_ENTRY_PREMIUM`
- **What was wrong:** strike *selection* (`_find_strike_by_premium`) searched a ₹90-150 premium band while strike *entry eligibility* (`MIN_ENTRY_PREMIUM`/`MAX_ENTRY_PREMIUM`) allowed ₹70-350 — meaning selection could rotate away from an ATM strike the entry gate would otherwise have allowed. The `.env` comment on `MAX_ENTRY_PREMIUM` ("was 150, blocked all ATM options") already signaled the intent to widen this band; it just hadn't been done for the selection side.
- **Fix:** `STRIKE_PREMIUM_MIN`/`STRIKE_PREMIUM_MAX` defaults changed from 90/150 to 70/350 in `config/constants.py`, `.env`, and `.env.example` — now matching `MIN_ENTRY_PREMIUM`/`MAX_ENTRY_PREMIUM` exactly.
- **This is a real behavior change**, as flagged in the original finding: the bot can now select (and enter) strikes at premiums it previously would have rotated away from. Explicitly authorized by the user's "fix all of Section 2" instruction, which was itself confirmed against a direct choice that named this exact item.
- **Files:** `config/constants.py`, `.env`, `.env.example`

### 14.5 §2.7 — Max hold time now actually sourced from `.env`, and winning/losing thresholds are independently honored
- **What was wrong:** `exit_engine.py` imported `MAX_HOLD_TIME_WINNING`/`MAX_HOLD_TIME_LOSING` from config but never used them — `time_exit_15min()` used a separate hardcoded module-level literal, `MAX_HOLD_TIME_SEC = 900`, that happened to numerically match the env default.
- **Fix:** removed the hardcoded literal; `time_exit_15min()` now picks `MAX_HOLD_TIME_WINNING` or `MAX_HOLD_TIME_LOSING` based on whether the trade is currently ahead or behind, both genuinely `.env`-sourced. (Note: `config/constants.py` currently defines `MAX_HOLD_TIME_LOSING = MAX_HOLD_TIME_WINNING`, i.e. they're still the same value by default — this fix makes the *code path* honor them independently; giving them independently-configurable env vars is a separate, not-yet-requested change.)
- **Verified:** default behavior unchanged (both still resolve to 900s) unless `.env` is edited.
- **File:** `core/engines/exit_engine.py`

### 14.6 §2.8 — Exit-priority docstring corrected to match real execution order
- **Fix:** `check_exit_conditions()`'s docstring now reads 1 → 2 → 2c → 3 → 4 → 4b → 5, matching the actual code order (hard SL/trailing → early loss cut → soft loss cut → greeks → smart RSI exit → RSI reversal → time exit) instead of the previous out-of-order numbering.
- **File:** `core/engines/exit_engine.py`

### 14.7 §2.9 — Consecutive-loss pause consolidated to a single source of truth

**How this was found:** read-only log analysis of the 2026-08-31 clean paper-trading session, then cross-checked against 2026-08-28 and 2026-08-27 to establish when the pattern started.

**What was wrong:** two completely independent consecutive-loss-limit implementations ran in parallel and never shared state:
- `state_machine.check_trade_limits()` — tracked `state.consecutive_losses` / `state.consecutive_loss_pause_until`, logged `"⚠️ Consecutive loss limit hit (N). Pausing until HH:MM:SS"` and, on expiry, `"✅ Pause ended. Resetting consecutive losses."`
- `RiskManager.check_streak_limits()` (added in §1.11) — tracked its own separate `self.consecutive_losses` / `self.streak_pause_until`, logged `"RISK BLOCKED: Consecutive losses: N, PAUSE for Xmin"`.
- Both were fed the same underlying loss events (via their respective `record_trade`/streak-update call sites) but on different clocks. While `state_machine`'s pause was active, entries never reached `RiskManager.check_streak_limits()`, so its own stale `consecutive_losses` counter sat untouched. The instant `state_machine`'s pause cleared and let a signal through, `RiskManager` immediately saw its own leftover count still at the limit and imposed a **second, independent 15-minute pause**, one second after the first one just ended.

**Confirmed live, three-session timeline:**
- **2026-08-27 (baseline, before either bug):** `state_machine`'s tracker fired twice (13:26:08→13:41:08, 14:10:38→14:25:38), each time pausing and resetting cleanly with no follow-on block — **zero "RISK BLOCKED" lines anywhere in the session**. `RiskManager`'s side never triggered at all, because `RiskManager.record_trade()`/`update_streak()` weren't wired into the exit path yet at this point (per §1.13, that wiring landed later) — its `consecutive_losses` counter was simply never being incremented, so it had nothing to fire on. This is the clean single-tracker baseline: the mechanism works exactly as designed when only one tracker exists.
- **2026-08-28:** §1.13's fix wired `RiskManager.record_trade()` into the exit path for the first time, so its counter started getting fed the same loss events as `state_machine`'s — but at this point it still had no pause/reset logic of its own (pre-§1.11), so once triggered it just returned `False` unconditionally forever. Result: **2,048 consecutive "RISK BLOCKED: Consecutive losses: 2, PAUSE" lines from 11:21:18 to 15:16:00** — the incident §1.11 fixed, and the same root cause as this finding, just fully deadlocked instead of merely doubled.
- **2026-08-31:** post-§1.11, `RiskManager`'s side had its own pause/reset — but still on its own independent clock from `state_machine`'s, so the double-pause described above happened twice: 10:41:48→10:56:48 (`state_machine` pause) immediately followed by 10:56:49→~11:11:49 (`RiskManager` pause), and again 11:45:04→12:00:04 followed by 12:00:43→~12:15:43. Each 2-loss streak cost ~30 min of blocked trading instead of the intended 15 — roughly an extra hour lost across the session.
- **Net picture:** this bug wasn't something that had always lurked under the surface — it was a direct, traceable consequence of §1.13's wiring landing before the two trackers were ever reconciled with each other. 08-27 proved the single-tracker design is sound in isolation; 08-28 and 08-31 showed what happens once both trackers are live and unsynced, at two different stages of RiskManager's own fix.

**Why it mattered:** §1.11's fix genuinely worked — it turned a session-ending permanent deadlock into a bounded, self-clearing pause — but it only fixed `RiskManager`'s side in isolation. The underlying duplication (same signal, two independent counters/clocks) was still there, so every consecutive-loss trigger was costing ~2x the configured `pause_after_consecutive_loss_sec`/`COOLDOWN_AFTER_CONSEC_LOSS` instead of 1x. Also the sibling of the dead-code duplication noted in §10.2 ("a *third*, independent, unused streak-tracking implementation... none aware of each other") — except this pair wasn't dead, and actively interacted.

- **Fix, following the direction agreed earlier in the session:** `state_machine.check_trade_limits()` no longer runs its own independent pause/reset clock (`state.consecutive_loss_pause_until` removed entirely from `TradingState`). It now delegates the pause *decision* to `RiskManager.check_streak_limits()` — the same function `RiskManager.can_trade()` already calls — so there is exactly one clock and one counter deciding whether/how long to pause, called first (and usually only) from `state_idle()` before a signal is even evaluated, with `can_trade()`'s own call later in `state_entry_ready()` now naturally idempotent (reads the same already-resolved state).
- **`TradingState.consecutive_losses`/`consecutive_ce_losses`/`consecutive_pe_losses` were deliberately left untouched** — they're still maintained by `update_pnl()` and still used for `get_cooldown_duration()`'s SL-cooldown selection, the separate per-direction (CE/PE) blocking mechanism (its own independent 30-minute cooldown, unrelated to this bug), and the dashboard display. Only the pause *gate* itself moved to `RiskManager`.
- **Verified:** full test suite green. Reasoned through the call graph: since `check_trade_limits()` (called every IDLE tick) now blocks on `RiskManager`'s own counter/clock, and `can_trade()`'s later call reads that same already-current state, the specific double-pause failure mode is structurally no longer possible — there's only one counter and one clock left to fire.
- **Files:** `core/engines/state_machine.py`

### 14.8 §2.10 — WebSocket subscribe/unsubscribe no longer waits for an ACK that SmartAPI never sends

**How this was found:** cross-session log analysis (2026-08-31 vs. 2026-08-28) of the "ACK Timeout" warnings flagged in §2.3/§6, extended back across every available session (2026-08-03→2026-08-31), then traced against the actual code path and Angel One's own official `smartapi-python` SDK source.

**What was wrong:** `brokers/angel_one/client.py`'s `subscribe()`/`unsubscribe()` (client.py:1467-1631) sent a request with a `correlationID`, then blocked up to 5.0s in `_wait_for_ack()` (client.py:1417-1444) waiting for a text/JSON WebSocket frame that echoes that `correlationID` back as a success confirmation (`_on_ws_message()`, client.py:1673-1697). **This confirmation message does not exist in the real SmartAPI WebSocket 2.0 protocol.** Checked Angel One's own official `SmartApi/smartWebSocketV2.py` SDK: its `subscribe()`/`unsubscribe()` are pure fire-and-forget — `ws.send(...)` and return, no ACK-wait, and its message handler has no correlationID-matching branch at all. The server confirms subscribe/unsubscribe implicitly, by starting/stopping binary tick delivery for that token — never by an acknowledgement frame.

**Evidence:** `"✅ ACK Received"` (the only log line that fires on a genuine correlationID match) had **zero occurrences across all 22 available sessions, 2026-08-03 through 2026-08-31** (~700 subscribe/unsubscribe attempts total). Per-session subscribe-attempt vs. ACK-timeout counts were ~95-100% for every single day in that window (e.g. 08-31: 42/42, 08-28: 25/25, 08-05: 95/95, 08-27: 30/30). DEBUG logging was enabled throughout (2,728 DEBUG lines in the 08-31 session alone), so a late-arriving ACK would show up as `"ACK received without pending waiter"` (client.py:1694) — this also had zero occurrences anywhere, ruling out "arrives late, we ignore it." The WS receive loop runs on its own dedicated background thread (`self.ws_thread`, client.py:1293-1303) separate from the blocking caller, and `"WebSocket message error"` (the catch-all exception log in the message handler) never appeared either — ruling out a race/thread/swallowed-exception explanation. Independent evidence that subscriptions functionally work anyway: `_wait_for_first_ws_tick()` (broker.py:576-589) verifies real tick data arrives after subscribe, separate from the ACK mechanism, and every session's trades ran on live ticks regardless.

**Why it mattered:** every subscribe blocked its calling thread for a full 5.0s and every unsubscribe another 5.0s — real, not just cosmetic. Strike rotation calls both synchronously in the main trading-decision path; 08-31 had 19 rotations → roughly 3+ minutes of the session spent purely blocked waiting for a message that would never arrive. This was also the trigger for the existing 180s "recent ACK timeout stress" rotation-suppression cooldown (`broker.py:386-406`), compounding the lost time. Separately, a real (still unverified, not observed) data-integrity gap noted at the time: the ACK-timeout fallback wrote the local subscription cache unconditionally on timeout, and while **subscribe** has independent tick-based verification (`_wait_for_first_ws_tick`), **unsubscribe has no equivalent** — this asymmetry is unchanged by this fix, see below.

- **Fix, per the root-cause investigation's Option 1 (matching Angel One's own official `smartapi-python` SDK):** `brokers/angel_one/client.py`'s `subscribe()`/`unsubscribe()` are now fire-and-forget — send the message, sync the local subscription cache immediately, return. The blocking `_wait_for_ack(correlation_id, timeout=5.0)` call is no longer on this path.
- **The underlying ACK primitives (`_wait_for_ack`, `_register_ack_waiter`, `_set_ack_result`, `_pending_ack_*`, `_clear_pending_ack_state`) were deliberately left in place**, not deleted — they're still covered by their own direct unit tests (`test_ack_waiter_handles_early_ack_signal`, `test_stop_websocket_clears_runtime_state`) and remain harmless, generic infrastructure in case it's ever needed elsewhere; they're just no longer wired into subscribe/unsubscribe.
- **Real confirmation of a successful subscribe still exists and is unchanged:** `broker.py`'s `_wait_for_first_ws_tick()` independently verifies actual tick data arrives for the subscribed token — this was already the more meaningful check even before this fix (`_verify_subscriptions()` was only checking the same local cache the fallback path had just written, not real server state).
- **Not done (open follow-up — see `findings.md`):** no new independent verification was added for unsubscribe (confirming the old token's ticks actually stop). This asymmetry pre-dates this fix and isn't made worse by it — fire-and-forget behaves identically to the old ACK-timeout-fallback path from the subscription-cache's point of view, just without the artificial 5s stall first.
- **Also left in place (now dormant, harmless):** `broker.py`'s `_last_ws_ack_timeout_time`/`_ws_ack_timeout_cooldown_sec` transport-stress-triggered rotation cooldown, driven by the `_broker_ws_ack_timeout_cb` callback that only ever fired from the now-removed blocking wait. It will simply never trigger going forward (no more artificial timeouts to detect) — not removed this pass since it's inert rather than broken.
- **Verified:** updated `test_subscribe_ack_timeout_falls_back_to_local_cache` (renamed `test_subscribe_is_fire_and_forget_no_blocking_ack_wait`) to assert `_wait_for_ack` is never called and the cache still updates immediately; full test suite green.
- **Files:** `brokers/angel_one/client.py`, `tests/test_websocket.py`

### 14.9 Files touched this pass
`core/backtest.py`, `core/engines/exit_engine.py`, `core/engines/state_machine.py`, `core/trading/broker.py`, `brokers/angel_one/client.py`, `core/validation/walk_forward_backtest.py`, `config/constants.py`, `.env`, `.env.example`, `tests/test_backtest_execution_guard_regression.py`, `tests/test_websocket.py`. Full test suite green before and after every fix (`venv/bin/python -m pytest tests/`: 168 passed/1 skipped; `.venv/bin/python -m pytest tests/`: 169 passed).

All of the above (Section 1 through Section 14) was committed in a single commit (`fbaac2e`, "fix: multi-session risk/exit/config hardening + backtest-live exit parity") on 2026-08-31, since it had never been committed across the several sessions it accumulated over.

---

## 15. Remaining findings.md backlog cleared, and findings.md retired (2026-08-31/09-01)

User asked whether anything was left in findings.md, and — since real open items remained, including a serious reliability gap and a security issue — explicitly chose to fix the rest rather than leave them open or move them unfixed. Every item below was fixed, verified with the full test suite (`venv/bin/python -m pytest tests/`) both before and after, and findings.md's content has now been fully absorbed into this file — the four items that are genuinely not code bugs (§15.13-§15.16 below) are documented honestly as still-open/non-actionable-via-code rather than marked fixed. **`.venv` no longer exists as of §15.2 below — `venv/` is the sole canonical environment going forward**, so future sessions should stop cross-checking a second venv.

### 15.1 §6.1 — Credentials no longer appear in `ps aux` during the API health check
- **Fix:** `run.sh`'s `menu_health()` API connectivity check now passes the Angel One credentials via the subprocess's environment (`ANGEL_HC_API_KEY`/`ANGEL_HC_CLIENT_ID`/`ANGEL_HC_PASSWORD`/`ANGEL_HC_TOTP_SECRET`), read via `os.environ` inside the `python -c` script, instead of being string-interpolated directly into the `-c` argument text.
- **Verified:** manually confirmed a value passed this way is invisible to `ps aux | grep` from another shell while still correctly readable by the subprocess itself.
- **File:** `run.sh`

### 15.2 §6.2 — Two divergent virtualenvs consolidated to one
- **What was wrong:** `run.sh` exclusively uses `venv/` (confirmed — grepped every `PYTHON_BIN`/venv reference in the file), but `.venv/` existed in parallel and had been used for all manual test cross-checks across multiple sessions, with different package versions and extra packages (`pandas`, `numpy`, `neo-api-client`) `venv` doesn't have.
- **Fix:** deleted `.venv/` (155MB, gitignored, fully regenerable via `pip install -r requirements.txt` if ever needed again — nothing tracked was lost). Updated `PROJECT_STRUCTURE.md`'s file tree to drop the now-nonexistent `.venv/` entry.
- **Verified:** full test suite still 168 passed/1 skipped under the real `venv/` after removal (the pandas-dependent skip is expected and benign, as previously established).
- **Files:** `PROJECT_STRUCTURE.md` (`.venv/` directory removed from disk, not a tracked file)

### 15.3 §6.3 — Duplicate menu entry removed
- **Fix:** `menu_tools()` printed `[8] Market Readiness Pro` twice, verbatim, back to back. Removed the duplicate line.
- **File:** `run.sh`

### 15.4 §6.4 — Version strings now have a single source of truth
- **Fix:** added a `VERSION` file at repo root (`BOT_VERSION`/`ENGINE_VERSION`/`READINESS_VERSION`, bash-sourceable KEY=VALUE lines). `run.sh` now sources it right after setting its literal fallback defaults, so a fresh checkout still runs even if `VERSION` is ever missing, but normally reads from the one file.
- **Verified:** `bash -c 'source VERSION; echo ...'` prints the expected values; `bash -n run.sh` — syntax OK.
- **Files:** `VERSION` (new), `run.sh`

### 15.5 §6.5 — R:R fallback made consistent (honest `?`, not a fabricated `2`)
- **Fix:** `menu_config()`'s R:R ratio display used to silently show a fabricated `"2"` if `bc` was missing; changed to `"?"`, matching the other R:R display's already-honest fallback.
- **File:** `run.sh`

### 15.6 §7 — All four Telegram notification functions wired up
- **What was wrong:** `notify_entry()`, `notify_exit()`, `notify_kill_switch()`, `notify_daily_summary()` were fully implemented, imported once in `core/main.py`, and never called anywhere. The four `TELEGRAM_NOTIFY_*` toggles weren't even added to `CONFIG['telegram']`.
- **Fix, following the finding's own proposed plan exactly:**
  1. Added `notify_entries`/`notify_exits`/`notify_kill_switch`/`daily_summary` to `CONFIG['telegram']` in `config/constants.py`.
  2. `notify_entry(trade)` now fires in `state_machine.py`'s `state_entry_ready()` right after DB entry logging, gated on `TELEGRAM_NOTIFY_ENTRIES`.
  3. `notify_exit(trade, pnl, exit_reason)` now fires in the exit block, gated on `TELEGRAM_NOTIFY_EXITS`.
  4. `notify_kill_switch(reason, details)` now fires at all four kill-switch transition points in `core/main.py` (stale-data, latency-pause, spread-cooldown, permanent) via a small shared `_notify_kill_switch_telegram()` helper, gated on `TELEGRAM_NOTIFY_KILL_SWITCH`.
  5. `notify_daily_summary(summary)` now fires in `core/main.py`'s shutdown sequence, reusing the exact same payload already built for `logger.daily_summary()`, gated on `TELEGRAM_DAILY_SUMMARY`.
- All five call sites are wrapped in `try/except` (never allowed to affect trading control flow) and reuse the already-confirmed-working `send_message()`/queue/background-thread transport (see §7.1) — no new plumbing.
- **Files:** `config/constants.py`, `core/engines/state_machine.py`, `core/main.py`

### 15.7 §8.1 — AGGRESSIVE↔SAFE↔LOCKDOWN paper-mode bypass: reviewed again, left unchanged
- Not a bug — a deliberate design decision with a genuine tradeoff the finding itself laid out (leave AGGRESSIVE-only in paper mode for simplicity/consistency, vs. temporarily lifting the bypass to exercise the SAFE-mode path at the cost of a new untested variable in whatever session tries it). No new information changes that tradeoff, and flipping real risk-mode-switching behavior unilaterally without the owner's sign-off would be exactly the kind of behavior change this project's own conventions (§2.6, §14.4) require explicit confirmation for.
- **Status: intentionally left as-is. Still a standing data-interpretation caveat — any future "entry quality" conclusion drawn from paper-mode data should account for the fact that mode-switching never activates.**

### 15.8 §8.2 — Lock discipline on `mode_switch.py`'s `_current_mode` fixed completely
- **Fix:** `get_current_mode()`, `get_active_thresholds()`, `get_threshold()`, `is_entries_allowed()`, and `get_mode_emoji()` all now acquire `_mode_lock` around their reads of the shared `_current_mode`/`active_thresholds` globals, matching the write-side functions that already did.
- **File:** `core/services/mode_switch.py`

### 15.9 §8.4 — Mode-switch threshold scalars wired to `.env`
- **Fix:** added 8 new `.env`-configurable constants to `config/constants.py` (`MODE_SWITCH_CONSECUTIVE_LOSS_TRIGGER`, `_VOLUME_DETERIORATION_THRESHOLD`, `_CHOP_DETECTION_THRESHOLD`, `_THETA_DETERIORATION`, `_SAFE_HOUR_NORMAL`, `_VOLUME_RECOVERY_THRESHOLD`, `_RANGE_RECOVERY_THRESHOLD`, `_THETA_RECOVERY_THRESHOLD`) and wired `mode_switch.py`'s switch-condition scalars to read from them. **Deliberately did not** make the two full per-mode threshold dicts (`AGGRESSIVE_THRESHOLDS`/`SAFE_THRESHOLDS`, 8 keys × paper/live variant = 32 values) `.env`-configurable — lower priority given §8.1 (the subsystem doesn't activate in paper mode anyway), and a much larger, more error-prone change for comparatively little value right now.
- **Verified:** defaults match the prior hardcoded literals exactly — zero behavior change unless `.env` is edited.
- **Files:** `config/constants.py`, `core/services/mode_switch.py`, `.env`, `.env.example`

### 15.10 §9.1 — `core/services/session_manager.py` deleted
- **Fix:** confirmed (again) zero callers anywhere, then deleted the file. Also removed its entry from `core/services/__init__.py`'s lazy `__getattr__` module list — leaving that reference in would have made *any* unresolved `core.services.*` attribute lookup raise `ModuleNotFoundError` the moment it tried (and failed) to import the now-deleted module, breaking the lazy-lookup mechanism for the two still-real modules in that list, not just this one.
- **Verified:** full test suite green; `core.services` attribute lookups for `database`/`telegram_bot`/`mode_switch` still resolve correctly.
- **Files:** `core/services/session_manager.py` (deleted), `core/services/__init__.py`

### 15.11 §10.1 — Live position crash-recovery: detect-and-halt, plus the write-side wiring that makes it real
- **What was wrong:** a complete "active positions" recovery subsystem existed in `database.py` (`save_active_position`, `get_active_positions`, `close_position_in_db`, etc.) but **had zero callers on both the write and read side** — nothing ever recorded a position into it, and nothing ever checked it on startup. If the bot crashed or restarted mid-trade, the position was silently abandoned with zero trace it had ever existed.
- **Fix — three parts, all required for this to be a real (not just theoretical) fix:**
  1. **Write side:** `state_machine.py`'s `state_entry_ready()` now calls `save_position(...)` right after a successful order, recording `order_id`/`symbol`/`direction`/`side`/`qty`/`entry_price`/`entry_time`/`stop_loss`/`take_profit` as an `ACTIVE` row.
  2. **Write side (close):** the exit block now calls `close_position(order_id)` right after a confirmed exit, marking the row `CLOSED`.
  3. **Read side (startup):** `core/main.py`, right after `broker.connect()` succeeds (same place the DVF stale-position sweep already runs), now calls `get_active_positions()`. If anything is still `ACTIVE` from a prior process instance, the bot does **not** try to reconstruct SL/TP state and resume monitoring it, and does **not** auto-place a real exit order — both would mean exercising complex, never-before-run live-order-path logic (§2.2: the live order path has zero execution history) with real money, untestable from here. Instead it logs a `CRITICAL`-level alert, sends a Telegram kill-switch notification (reusing §7's new wiring) with the affected order IDs, and sets `state.state = "KILL_SWITCH"` / `state.manual_intervention_required = True` — refusing to open new trades until a human confirms the position situation is resolved. This mirrors the existing "exit not confirmed" kill-switch pattern already used elsewhere in this file for exactly this class of "we don't know what's safe, stop and get a human" situation.
- **Why detect-and-halt instead of auto-resume or auto-close:** this is real capital, on a code path that's never actually executed in production (per §2.2), and I have no way to test either "resume monitoring" or "auto-close" against a real broker connection from here. A loud, fail-safe halt is the responsible choice for a first implementation of this; auto-recovery (in either direction) is a reasonable follow-up once there's real live-trading experience to design it against.
- **Verified end-to-end with a scripted lifecycle test** (temp DB): `save_position()` on entry → `get_active_positions()` returns it (simulating "process died here, nothing closed it") → `close_position()` on a normal exit → `get_active_positions()` correctly returns empty. All four steps behaved exactly as designed.
- **Files:** `core/engines/state_machine.py`, `core/main.py`

### 15.12 §10.2 — Confirmed-dead `database.py` methods removed (with two near-misses caught before landing)
- **Removed, confirmed zero callers anywhere (including within `database.py` itself, checked explicitly after the near-misses below):** `get_trades_by_date()`, `get_daily_summary()`, `get_weekly_summary()`, `save_bot_state()`/`load_bot_state()` (plus their orphaned module-level wrappers `save_state()`/`load_state()`, which also had zero external callers once found), `get_dvf_calibration()` (read side — write side `save_dvf_calibration()` stays, genuinely active), `get_performance_by_hour()`, `get_performance_by_direction()`, `get_win_streak()`.
- **Near-miss #1, caught by the test suite:** the original finding described `log_entry()`/`log_exit()` as "a complete unused duplicate of the live `log_trade_entry()`/`log_trade_exit()`" — this was wrong. `log_trade_entry()`/`log_trade_exit()` are thin wrappers that internally call `db.log_entry()`/`db.log_exit()`; deleting the latter broke the former immediately (`AttributeError`, caught by `tests/test_dvf_pipeline.py` failing right after the deletion). Restored both methods in full.
- **Near-miss #2, caught by an explicit import smoke test (not covered by the test suite):** `save_bot_state()`/`load_bot_state()` had a module-level wrapper pair under *different* names (`save_state()`/`load_state()`) that I initially missed because my caller-search excluded `database.py` itself. `core/main.py` imports `save_state` at module level inside a `try/except ImportError: HAS_DATABASE = False` block — deleting it would have silently disabled the **entire** database layer (including the genuinely-critical `log_trade_entry`/`log_trade_exit`) on every future run, with no visible error. Caught by explicitly running `python3 -c "import core.main"` after the deletion pass, not by pytest. Fixed by removing the now-genuinely-unused `save_state` from that import line (confirmed it's never called anywhere) rather than restoring the dead function.
- **Lesson applied for the rest of this pass:** every subsequent deletion in this session was followed by a real `import` smoke test of every module that could plausibly reference it, not just `pytest` and not just a cross-codebase grep that excludes the file being edited.
- **Files:** `core/services/database.py`, `core/main.py`

### 15.13 §2.2 — Live order path testing gap: reviewed again, unchanged
- Still not a code bug — still needs a deliberate small-size live test before scaling, whenever live trading is actually considered. Nothing to fix in code.

### 15.14 §2.4 — Historical warm-up rate-limit watch item: reviewed again, unchanged
- Still one data point only (08-27). No fix proposed until there's evidence it recurs independent of the (already-fixed) duplicate-instance issue.

### 15.15 §3 — Statistical/analytical questions: still genuinely open
- These were never code bugs — they're questions that need more/better live trading data than exists yet, most of which (trailing ladder behavior, breakeven step effectiveness, overall expectancy) specifically need a session where price moves are large enough to reach those parts of the exit ladder, which 08-31 wasn't. Today's §14/§15 fixes (especially §2.9's double-pause fix and §2.10's ACK removal) haven't been live-verified in an actual trading session yet either. **Next step, unchanged from before:** run a clean paper-trading session with all of today's fixes live, ideally one with bigger intraday moves.
- One item did get answered on 08-31 data specifically: RSI Reversal Exit captures 95-97% of its own MFE — not leaving meaningful profit on the table, at least on a small-moves session. Worth re-confirming on a bigger-moves session before treating it as fully settled.

### 15.16 A new bug found and fixed along the way: DVF daily reports could silently show zero trades for the first ~5.5 hours of each IST calendar day
- **How this was found:** `tests/test_dvf_pipeline.py::test_calibration_and_report_and_export` started failing partway through this session — not from anything touched in this session, confirmed via `git stash` (it failed identically on the last committed state too). The system clock had simply crossed into the next calendar day (2026-08-31 → 2026-09-01) between conversation turns, and the failure was specifically time-of-day-dependent.
- **Root cause:** `core/validation/paper_executor.py` stamped `dvf_trades.virtual_entry_time` (and related internal hold-time timestamps) using `datetime.now(timezone.utc)`, while `core/validation/analytics.py`/`validation_report.py`/`calibration_engine.py`'s report-window anchor used naive **local** `datetime.now()` (IST on this machine, UTC+5:30) — matching the convention used everywhere else in the codebase (`dvf_signals.timestamp`, `trades.entry_time`, `state_machine.py`'s `now()`, etc.). Between local midnight and ~05:30 IST, UTC hasn't rolled over to the new calendar date yet, so a `dvf_trades` row entered "today" (local) still carries "yesterday" (UTC) as its stored date. A **daily** report (`days=1`, a single-day exact-match window) generated in that window would find zero matching rows for real trades that happened minutes earlier, because the two sides of the date comparison meant different calendar days. Wider windows (`days=30`, used by calibration checks) masked this — a one-day-off boundary barely matters inside a 30-day range — which is why only the daily-report path actually failed.
- **Fix:** brought `paper_executor.py` in line with the rest of the codebase's single (naive-local) timestamp convention instead of the other direction (making 3+ other files UTC-aware to match the one outlier) — replaced every `datetime.now(timezone.utc)` in the module with `datetime.now()`, and simplified `_to_datetime()` to normalize tz-aware inputs (including rows already written under the old UTC convention) to local time via `.astimezone().replace(tzinfo=None)`, so old and new rows both compare correctly going forward.
- **Verified:** the previously-failing test passes again; full suite green.
- **File:** `core/validation/paper_executor.py`

### 15.17 Two regressions from earlier today's own §14.1 fix, caught and fixed before they could bite
- **`run.sh`'s backtest menus (`run_quick_backtest`, `run_custom_backtest`) still called `core/backtest.py --sl ... --tp ...`** — both flags removed in §14.1's backtest rewrite. Would have crashed with an argparse error on the next backtest run from the menu. Fixed: quick-backtest no longer passes them at all; custom-backtest's "Step 3/4: SL/TP points" prompts replaced with a single "Step 3: Day Type" prompt, piped through the new `--day-type` flag; the config-summary display and R:R-ratio line (tied to the removed SL/TP inputs) updated accordingly.
- **`core/validation/walk_forward_backtest.py`'s `_run_window()` constructed `Backtester(..., sl_points=args.sl, tp_points=args.tp, ...)`** — same removed constructor params, would have crashed with a `TypeError` on the next run. Fixed: `--sl`/`--tp` CLI args replaced with `--day-type`, passed through as `day_type=args.day_type`; the summary-JSON `settings` block updated to record `day_type` instead of `sl`/`tp`.
- **Files:** `run.sh`, `core/validation/walk_forward_backtest.py`

### 15.18 Missing test coverage added: backtest's exit-engine integration (§14.1's own follow-up)
- Added `tests/test_backtest_exit_engine_parity.py` — 3 tests: (1) a forced trade with a declining price path produces a SOFT LOSS EXIT at the correct simulated hold-time using tz-aware timestamps (this is the exact scenario that crashed before §14.1's clock-override fix), (2) the same with naive timestamps and a rising price path produces an RSI-based exit with no tz-mismatch crash, (3) a monkeypatch-based spy on `core.backtest.check_exit_conditions` confirms `_check_exit()` genuinely calls the real, live `exit_engine` function (same trade dict object, correct `day_type`) rather than a local duplicate.
- **File:** `tests/test_backtest_exit_engine_parity.py`

### 15.19 §2.10's unsubscribe-verification asymmetry: reassessed, found to already be low-risk by an existing guard, strengthened with observability instead of a risky new synchronous check
- **Re-examined the actual risk:** `core/trading/broker.py`'s `_on_ws_tick()` already unconditionally discards any tick whose token doesn't match `self._option_token` (a pre-existing "CRITICAL FIX" guard, confirmed still in place) — and `self._option_token` is reassigned to the *new* token before either the subscribe or unsubscribe call during strike rotation. This means a stale old-token tick — whether from a slow unsubscribe or the fire-and-forget change in §14.8 — can structurally never reach strategy or exit logic; it's dropped at ingestion regardless of what SmartAPI does with the unsubscribe request.
- **Given that, building actual "wait for the old token's ticks to stop" verification would be both harder to get right (there's no clean way to synchronously confirm an *absence* of future messages) and lower-value than originally assessed** — the real protection already exists on the consuming side, not the subscribing side.
- **Fix applied instead:** the discard branch now counts and periodically logs (every 20th occurrence, at DEBUG) when a stale-token tick is dropped, so if this *does* happen in practice it's now observable instead of silently invisible, without adding any new blocking/waiting behavior to the hot tick-processing path.
- **File:** `core/trading/broker.py`

### 15.20 Files touched this pass
`run.sh`, `PROJECT_STRUCTURE.md`, `VERSION` (new), `config/constants.py`, `core/services/mode_switch.py`, `core/services/__init__.py`, `core/services/session_manager.py` (deleted), `core/services/database.py`, `core/engines/state_machine.py`, `core/main.py`, `core/trading/broker.py`, `core/validation/paper_executor.py`, `core/validation/walk_forward_backtest.py`, `.env`, `.env.example`, `tests/test_backtest_exit_engine_parity.py` (new). `.venv/` removed from disk (untracked). Full test suite green throughout (`venv/bin/python -m pytest tests/`: 171 passed, 1 skipped — up from 168 thanks to the 3 new backtest exit-engine tests).

**`claude_code/report/findings.md` has been deleted** — everything it contained is now here, in this file, either as a completed fix (above) or honestly documented as still-open-but-not-a-code-bug (§15.7, §15.13-§15.15).

---

## 16. Live-session audit, 2026-09-01 (paper mode) — §14.7/§14.8/§12/§15.11 all confirmed working live for the first time

Post-close read-only audit of `logs/2026-09-01/` against every fix listed above. Session: paper mode, 08:14-15:30 IST, two process restarts before market open, 10 trades (4W/6L, ₹-59.80 PnL), 18 spread-based kill-switch activations, no crash mid-trade.

### 16.1 §14.7/§2.9 — Consecutive-loss double-pause: confirmed fixed live
- **Zero `"RISK BLOCKED"` lines anywhere in the session** (the old symptom of the second, stale-clock pause firing right after the first one ended).
- Exactly one pause cycle observed: `Consec Losses` climbed 0→1→2 through the morning, then a single `"[11:05:39] [INFO] ✅ Streak pause ended. Resetting win/loss streak."` — one pause, one clean reset, no follow-on second pause immediately after. This is the first live confirmation of §14.7 since it was merged un-verified on 08-31.
- Separately, the still-intentional per-direction CE/PE cooldown (unrelated mechanism, explicitly left alone by §14.7) also behaved correctly: `"CE blocked (2 losses, Nmin cooldown)"` counted cleanly down 14min→1min with no double-fire.

### 16.2 §14.8/§2.10 — WebSocket ACK wait removal: confirmed fixed live
- **Zero `"ACK Timeout"` and zero `"ACK Received"` lines in the entire session** — exactly the expected signature now that `subscribe()`/`unsubscribe()` are fire-and-forget and never wait on the removed `_wait_for_ack()` path. No 5s-per-call stalls observed. First live confirmation since 08-31.

### 16.3 §12 — DVF orphaned-OPEN reconciliation on restart: exercised live, worked correctly
- Bot actually restarted twice before market open (`08:14:01` and `09:10:00` full startup banners, plus an `08:20:22` auto-reconnect). The second restart logged `"[09:10:02] [INFO] DVF: reconciled 3 stale OPEN virtual position(s) from a prior run"` — the reconciler fired and force-closed the 3 stale rows exactly as designed, with no orphaned-forever rows left behind. First live restart-triggered exercise of this fix since it landed 08-30.

### 16.4 §15.11 — Live-position crash-recovery: not exercised (no signal either way)
- Both restarts happened before the first trade (`09:45:41`), so no position was ever open across a restart today. Zero `CRITICAL`/`KILL_SWITCH`(-halt)/`manual_intervention_required` lines, consistent with "never triggered" rather than "triggered and worked" or "should have triggered and didn't." **Still unverified against a real mid-trade crash** — unchanged from §15.13's standing caveat.

### 16.5 §15.16 — DVF daily-report IST/UTC boundary: not exercised (outside the vulnerable window)
- Both restarts (08:14, 09:10) and the end-of-day report generation (19:02:18) all fall well after the 05:30 IST danger window described in §15.16. Nothing to verify today.

### 16.6 New observation, not a bug: entries throttled by design after the 3rd loss for the rest of the session
- Trade 10 (`11:20:45`, 82% confidence) got through just before the 3+ SL-streak confidence gate started actively suppressing entries — the first `"📊 Low conf 82% < 85% (3+ SL streak)"` line appears at `11:55:25`, after `Consec Losses` had already reached 3. From then through `15:30` (end of session) the gate kept suppressing 82%-confidence signals against an 85% floor, and `Consec Losses` stayed pinned at 3 with no further trades. This is existing, intentional confidence-threshold behavior (not part of any fixed.md item) — flagged here only as context for why the session went quiet after 11:21 despite the bot running until 15:30, not as a finding.

**Net result: the two fixes most in need of live verification (§14.7, §14.8) are now both confirmed working correctly under real live conditions, plus a bonus confirmation of §12's restart-reconciliation path. §15.11 and §15.16 remain unverified simply because today's session never exercised their trigger conditions — nothing wrong found, nothing new to fix.**

---

## 17. Bug found during a deep follow-up audit (2026-09-01, evening), then fixed same pass: §15.11's write-side wiring was incomplete — only the "normal" exit path closed the DB position row

**Found independently by two separate lines of investigation (a live-order pre-flight-checklist review, and a broad duplicate-tracker sweep) that converged on the same root cause and the same live repro. Fixed later the same evening — see §18.**

**What's wrong:** `close_position(order_id)` — the write that marks a `database.py` `active_positions` row `CLOSED`, added by §15.11 — is called from exactly one place: `state_machine.py:1006`, inside the normal SL/TP/RSI-exit block. `save_position()` (the entry-side write, same §15.11) fires unconditionally for every trade at `state_machine.py:847`, regardless of how it eventually exits — but `close_position()` does not have a matching unconditional call. `core/main.py`'s `close_current_trade()` (`main.py:199-224`) — the exit path used for every kill-switch exit, network-down emergency exit, and manual/error shutdown, 5 call sites at `main.py:529, 584, 647, 803, 823` — calls `broker.exit_position()` but never `close_position()`.

**Confirmed live, right now, in the real DB:** querying `core/data/trades.db` for 2026-09-01 shows 8 of today's 10 paper trades correctly `CLOSED`, but `PAPER_1788236441_1` (09:50:41) and `PAPER_1788237050_0` (10:00:50) — both closed via `"Kill switch: Wide spread KILL"` per `trades.csv`, and genuinely flat, not actually orphaned — are still sitting `ACTIVE`.

**Why it matters:** on the *next* bot restart, `core/main.py`'s startup check (`get_active_positions()`, the read-side of §15.11) will find these two rows and fire the CRITICAL / `manual_intervention_required` halt §15.11 built for genuinely-orphaned positions — a false positive, for positions that were already closed correctly. Given wide-spread kill-switches fired 18 times in a single session today (see the spread-kill-switch analysis from this same audit pass), this is not a rare edge case — any kill-switch exit followed by a restart before the next real trade will reproduce it.

**A second, more consequential version of the same gap:** `RiskManager.record_trade()` (`daily_pnl +=`, `risk_manager.py:494`) and `update_streak()` (`consecutive_losses`/`consecutive_wins`) are also only called from `state_machine.py:969`, the same normal-exit-only call site. So `RiskManager.daily_pnl` — which actively feeds real gating logic today (profit-lock position sizing, `risk_manager.py:356-358`; `consumed_daily_loss`, `risk_manager.py:463`) — is currently missing every kill-switch/emergency-exit loss, and `RiskManager.consecutive_losses` (the §14.7 pause's own counter) is undercounting losses from the same exit paths for the identical reason. This is the same class of bug §14.7 fixed, on a different exit branch §14.7 never touched.

**Also found in the same sweep:** a third, currently-dormant consecutive-loss tracker — `core/services/mode_switch.py`'s `ModeState.consecutive_losses` (`mode_switch.py:122`, fed from the same `TradingState.update_pnl()` call site as the other two) — is inert only because of the existing, already-documented §15.7 paper-mode bypass. In live mode it would independently drive AGGRESSIVE→SAFE mode switching on its own 60s cooldown, unsynchronized with RiskManager's pause. Not a live bug today; worth registering before live trading starts.

**Status when first written: not fixed, flagged for a decision** — the fix touches the same real-money risk-gating surface §14.7 did, so this was reported rather than changed unilaterally in the same pass as a read-only audit. **User asked to fix it (and the rest of the audit's findings) the same session — see §18.1 for the actual fix.**

**Files implicated:** `core/main.py`, `core/engines/state_machine.py`, `core/services/database.py`, `core/risk/risk_manager.py`.

---

## 18. Same-evening fix pass on the deep-audit findings (§1-§8 of the user's follow-up questions, 2026-09-01)

User asked follow-up questions across 8 areas (config drift, per-session config snapshot, the day's spread kill-switches, regression-test coverage for §14.7/§14.8, a summary.json counter discrepancy, confidence-gate instrumentation, a duplicate-tracker sweep, and a live-order test plan), then said to fix everything actionable that came out of it. Full test suite (`venv/bin/python -m pytest tests/`) green before, throughout, and after every change below (171 → 181 passed, 1 skipped throughout); import smoke tests (`python3 -c "import core.main; ..."`) run after every edit per the §15.12 lesson.

### 18.1 §17 fixed: exit accounting now runs on every exit path, not just the normal one
- **Fix:** factored the three post-exit accounting calls (`RiskManager.record_trade()`, `log_trade_exit()`, `close_position()`) out of `state_machine.py`'s normal SL/TP/RSI exit block into a new shared helper, `finalize_trade_exit_accounting()`, and call it from both there and from `core/main.py`'s `close_current_trade()` — the kill-switch/stale-data/high-latency/manual-shutdown exit path that previously only called `state.update_pnl()` and stopped.
- **Live data corrected:** the two rows this bug left stuck `ACTIVE`/`OPEN` today (`PAPER_1788236441_1`, `PAPER_1788237050_0`) were backfilled with their real exit data (from `trades.csv`, which had it correctly all along) via `log_trade_exit()`/`close_position()`, run directly against the live DB — both now `CLOSED` in `active_positions` and `trades`, matching all 10 of today's trades. This removes the false-positive-halt risk on the next restart.
- **Not done:** `mode_switch.py`'s third, currently-dormant `ModeState.consecutive_losses` tracker (found in the same sweep) was left untouched — it's inert only because of the existing §15.7 paper-mode bypass, which is itself an open design decision needing owner sign-off, not something to fold into this fix unilaterally.
- **Tests:** `tests/test_close_current_trade_exit_accounting.py` (new, 3 tests) — asserts `close_current_trade()` calls the shared finalizer, that a kill-switch exit reaches `close_position()` for the exited order_id, and that it reaches `RiskManager.record_trade()` with the correct pnl/direction.
- **Files:** `core/engines/state_machine.py`, `core/main.py`, `tests/test_close_current_trade_exit_accounting.py` (new).

### 18.2 §1a fixed: startup now validates the loss-ceiling ordering, and actually runs at startup
- **What was wrong:** `config/validator.py` existed but was never called from `core/main.py` — only from `run.sh`'s manual "System Check" menu — so a broken config would never be caught by just starting the bot normally. It also didn't check the KILL_SWITCH_LOSS/MAX_DAILY_LOSS/DAILY_LOSS_ALERT relationship at all.
- **Fix:** added a check to `ConfigValidator._validate_consistency()` asserting `DAILY_LOSS_ALERT < MAX_DAILY_LOSS <= KILL_SWITCH_LOSS`, added as a hard error (not just a warning, given it's a real-money kill-switch ordering). Wired `validate_config()` into the very top of `core/main.py`'s `main()`, before the pre-market standby sleep, so a broken config fails fast (`SystemExit`) instead of surfacing hours later as unexpected kill-switch behavior.
- **Bonus fix found along the way:** `_validate_consistency()`'s own `MAX_DAILY_LOSS` fallback default had drifted to a stale, unrelated `25000` (vs. `config/constants.py`'s actual `3000` default) — corrected to `3000` to match.
- **Bonus fix found along the way:** `ConfigValidator.load_env()` writes every parsed key straight into the real process `os.environ` (pre-existing behavior, left in place — appears intentional for downstream config reads) with no test-side cleanup; this was leaking values between test files (`KILL_SWITCH_LOSS`/`DAILY_LOSS_ALERT` weren't in `tests/test_config_validator.py`'s `CONFIG_ENV_KEYS` cleanup list, so one test's tmp `.env` values leaked into the next). Added both keys to that list.
- **Tests:** `tests/test_config_validator.py` — added `test_validate_config_flags_broken_loss_ceiling_ordering` and `test_validate_config_accepts_correctly_ordered_loss_ceilings`; updated one existing fixture that had an incidental (pre-existing-check-irrelevant) ordering conflict.
- **Files:** `config/validator.py`, `core/main.py`, `tests/test_config_validator.py`.

### 18.3 §1e — `.env.example` synced to the live `.env`'s intentionally-tuned values
- The 6 drifted variables found in the audit (`DELTA_MAX`, `ENTRY_MAX_DRIFT_PCT`, `KILL_SWITCH_LATENCY_MS`, `MIN_OPTION_PRICE`, `RSI_REVERSAL_MIN_PROFIT_POINTS`, `TICK_TIMEOUT_SEC`) are all live tunings tighter/different than the documented example — not bugs in `.env` itself. Synced `.env.example` to match so the template stops being misleading; **`.env` itself and `config/constants.py`'s in-code fallback defaults were deliberately left untouched** — changing the actual fallback-safety-net values that fire when a line goes missing from `.env` is a real behavior change to a real-money bot's safety net, not a documentation fix, and wasn't asked for.
- **File:** `.env.example`.

### 18.4 §7 cleanup — one confirmed-dead module deleted
- `utils/monitoring.py`'s `BotMonitor`/`get_monitor()` (found fully dead in the duplicate-tracker sweep — zero callers anywhere in the codebase, confirmed again directly, including a check for the module itself never being imported anywhere) deleted outright, following the same standard as §15.10's `session_manager.py` deletion.
- **Not done:** `database.py`'s dead `daily_pnl` schema column (also found fully unused) was **left in place** — deleting a live production SQLite column needs a migration, not just a code edit, and the value of removing an inert nullable column is low relative to that risk; noted here instead of acted on.
- **File:** `utils/monitoring.py` (deleted).

### 18.5 Net test count
171 → **181 passed, 1 skipped** (10 new tests: 4 in §4's `test_consecutive_loss_pause_regression.py`, 1 unsubscribe test added to `test_websocket.py`, 3 in §18.1's `test_close_current_trade_exit_accounting.py`, 2 in §18.2's loss-ceiling-ordering tests).

---

## 19. Self-review of §18 caught a real regression before it shipped further: §18.4's deletion missed non-`.py` callers

**How this was found:** user asked to check all files before pushing. Re-verified every file in the two §17/§18 commits diff-by-diff. §18.4's "zero callers anywhere" claim for `utils/monitoring.py` had only been checked with `.py`-scoped greps (matching the original duplicate-tracker-sweep fork's own methodology) — it missed `run.sh`, which embeds Python directly in heredocs.

**What was actually still using it:** `run.sh`'s Tools submenu, option `[7] Bot Monitor Status`, ran `python -c "from utils.monitoring import get_monitor; ..."` to print a live snapshot — this would now hit `ModuleNotFoundError` on every use. Also two harmless stale filename references: the `run_syntax_check` file list (already tolerant of missing files via `-f` checks, and already had one such gap from §15.10's `session_manager.py` deletion going unnoticed), and `PROJECT_STRUCTURE.md`'s file tree/description list.

**Important context — this wasn't actually a regression in the "broke a working feature" sense:** `get_monitor()` was `return BotMonitor()` — a **fresh instance every call**, invoked from a **separate subprocess** with zero shared state with the running bot. Nothing in the live bot process ever called `record_tick()`/`record_trade()` on it (confirmed zero callers, unchanged from the original finding). So this menu option only ever displayed an empty, freshly-initialized status table — it was already non-functional before the deletion, just non-functional in a *quieter* way (wrong data) than after (an exception, caught by the existing `2>/dev/null || printf "Monitor not available"` fallback the menu already had).

**Fix:** replaced the broken subprocess call with a direct, honest message explaining the feature was removed and pointing at the two working alternatives (System Health, Market Readiness Pro) — no renumbering of the menu (lower risk than shifting `[8]`/`[9]` down). Removed the two stale filename references from `run_syntax_check`'s file list and `PROJECT_STRUCTURE.md`.

**Lesson applied:** the §15.12 lesson ("grep excluding the file being edited is not sufficient") needs a corollary — a caller-search for a deleted Python module also needs to cover non-`.py` files that embed Python (shell scripts with heredocs, notebooks, CI YAML), not just `*.py`. Plain `grep -rn ... --include="*.py"` is not sufficient on its own for this codebase, which has `run.sh` doing exactly that.

**Verified:** `bash -n run.sh` (syntax check), full test suite green (181 passed, 1 skipped unchanged), exhaustive whole-repo grep (all file types, not `.py`-scoped) for `utils.monitoring`/`BotMonitor`/`get_monitor` now returns only the new explanatory string itself.

**Files:** `run.sh`, `PROJECT_STRUCTURE.md`, `tests/test_consecutive_loss_pause_regression.py` (unrelated hardening found in the same review pass — see below).

### 19.1 Also found and fixed in the same review pass: a test-pollution risk in §4's new regression tests
`tests/test_consecutive_loss_pause_regression.py`'s tests call `set_risk_manager(rm)`, which writes `core.risk.risk_manager`'s real module-level `_risk_manager` singleton directly, with no built-in restore — the same class of issue as §18.2's `os.environ` test leak. Not currently causing an observed failure (nothing else in the suite reads the singleton without either injecting its own config or monkeypatching `get_risk_manager` entirely), but latent risk for a future test. Added an `autouse` fixture resetting `core.risk.risk_manager._risk_manager` to `None` after each test in that file via `monkeypatch.setattr`.

---

## 20. CE/PE cross-direction entry bug fixed (2026-09-02) — the entry-engine-audit finding from the strategy-layer investigation

**What was wrong (found during a strategy-layer investigation, not a code audit — see conversation history for the full entry/exit engine traces):** pattern detection (`smart_scalp_v3.generate_signal()`) computes its EMA/RSI/VWAP/regime indicators from `tick['spot_price']` (NIFTY spot), not the option premium — confirmed by tracing `calculate_indicators()` and `runtime_state.get_canonical_candles()`, both of which prefer `spot_price` over `ltp`. That makes the pattern match itself direction-agnostic and correctly independent of whichever option contract happens to be subscribed at the time. But every **instrument-specific** check downstream of that — the premium filter (`MIN_ENTRY_PREMIUM`/`MAX_ENTRY_PREMIUM`), the delta filter, and the market-quality gate's spread/liquidity checks — read `tick`/`latest_tick`, which reflects the *currently subscribed* contract, not necessarily the contract the signal's `direction` will actually trade. `broker.place_order()` switches the subscription to match at order time (with its own already-correct fill-price validation, see the entry-engine trace), but by then every one of those checks had already run against the wrong contract.

**Confirmed live:** on 2026-09-01, two PE signals were validated against a CE contract's ~₹98 premium (comfortably clearing the ₹70 floor) while subscribed to that CE, then filled on the PE contract at ₹6.03 and ₹6.12 — 10x below the configured minimum, with a real spread (~0.85-1.08%) that then tripped the wide-spread kill switch 18 times that session (see §16/§18's spread-kill-switch analysis).

**Fix:**
- Added `BrokerInterface.get_tick_for_direction(direction)` (`core/trading/broker.py`) — returns `get_tick()` unchanged when the requested direction already matches the subscribed contract (no extra cost on the common path), otherwise fetches a real, fresh tick for the *other* contract at the current strike via `broker_client.get_market_tick()`, enriched the same way `_fetch_option_tick_rest()` already does.
- Wired this into `entry_engine.entry_signal()`: right after `smart_scalp_signal()` returns a direction, if it doesn't match the subscribed contract's suffix, fetch the correct-instrument tick and use it (`execution_tick`) for every downstream instrument-specific check instead of the original `tick` — the premium filter, a new spread sanity check (same 0.6% ceiling the wide-spread kill switch already enforces mid-trade, now checked *before* entry instead of only after), the anti-chase drift-guard's reference price (`signal_ltp`/`signal_spot_price`/`signal_timestamp`), and the live-mode Greeks gate. If the correct-instrument tick can't be fetched at all, the entry is rejected outright rather than silently falling back to the wrong contract's data.
- Left `can_trade_ce()`/`can_trade_pe()` (the session-trend regime gate) and the confidence gate untouched — both are spot-based/direction-level, not instrument-price-based, so they were never affected by this bug.
- **Not done:** no change to the permissive 5-way-OR regime gate itself, the dead `calculate_bullish_score()`/`calculate_bearish_score()` functions, or any exit-engine logic — all out of scope for this fix, tracked separately as still-open observations from the same investigation.
- **Tests:** `tests/test_broker_cross_direction_tick.py` (4 tests, `get_tick_for_direction()` in isolation) and `tests/test_entry_engine_cross_direction.py` (5 tests, full `entry_signal()` integration) — including the exact repro: a signal validated against a subscribed CE's ₹98 premium but the target PE's real premium is ₹6.12, asserting the entry is now rejected on the PE's own price, not the CE's.
- **Verified:** full test suite green throughout (181 → 190 passed, 1 skipped); import smoke tests after every edit.
- **Files:** `core/trading/broker.py`, `core/engines/entry_engine.py`, `tests/test_broker_cross_direction_tick.py` (new), `tests/test_entry_engine_cross_direction.py` (new).

---

## 21. `ticks` table write path wired up (2026-09-02) — the observability fix recommended after §20's investigation

**What was wrong:** `core/services/database.py`'s `_init_schema()` created a `ticks` table (timestamp, symbol, ltp, bid, ask, volume, spot_price, oi) — including its own index — but nothing anywhere in the codebase ever wrote to it. Every strategy-layer post-exit/counterfactual analysis in this investigation (the RSI-exit and loss-side counterfactuals) had to fall back to sparse ~30-90s `[LTP RAW]` log-line snapshots or the underlying NIFTY spot series from `dvf_signals`, and 8-13 of every ~15 trades examined ended up with zero or partial post-exit data as a result.

**Fix:**
- Added `DatabaseManager.log_tick()` / the module-level `log_tick()` wrapper (`core/services/database.py`), inserting into the existing `ticks` table.
- Added a second index, `idx_ticks_symbol_timestamp ON ticks(symbol, timestamp)`, alongside the pre-existing timestamp-only one — matches the `WHERE symbol=? AND timestamp BETWEEN ? AND ?` query shape every prior analysis in this investigation needed.
- Extended `prune_old_signal_rows()` to cover `ticks` alongside the existing `signals`/`dvf_signals` retention sweep (same 7-day default), since it's now a similarly per-tick, unbounded-growth table.
- Wired the actual write into `BrokerInterface.get_tick()` (`core/trading/broker.py`) — the single funnel point all three tick sources (WebSocket, REST, simulation) already converge through. Every real (non-simulated) tick returned from there is now persisted via a new `_persist_tick()` helper, deduped on `(symbol, ltp, bid, ask)` so the ~2Hz main-loop cadence re-serving an unchanged cached WebSocket tick (the existing "refresh timestamp to NOW" behavior) doesn't flood the table with identical rows — every row now represents an actual price change. Simulated ticks are explicitly excluded so synthetic data never contaminates future real-session analysis. Wrapped in try/except, matching the project's established "analytics-only, must never block trading" convention.
- **Verified functionally**, not just unit-tested: ran `log_tick()` against the real `core/data/trades.db`, confirmed the row and both indexes, then deleted the test row so it doesn't pollute real data.
- **Found but not fixed, out of scope — flagging for a separate decision:** `prune_old_signal_rows()` (now covering `ticks` too) is only ever called from `app.py`, which does **not** appear to be the live entry point (`core/main.py`, launched by `run.sh`, is — confirmed via every session's log banners in this investigation). `core/main.py` has zero references to `prune_old_signal_rows`. This means `signals`/`dvf_signals` (already ~28k-34k rows per session, 120k+ accumulated total) — and now `ticks` too — may never actually get pruned in the process that's actually running. Not touched this pass since it's a separate question (is `app.py` still meant to be the pruning trigger, should `core/main.py` call it directly, on what cadence) rather than a natural extension of "wire up the write path."
- **Tests:** `tests/test_tick_persistence.py` (9 tests) — `log_tick()` against a real temp-file DB (row insert, no-op on missing symbol/ltp), `_persist_tick()`'s dedup logic (identical consecutive ticks skipped, a genuine price change logged again, no-op without a symbol, never raises on DB failure), and `get_tick()` only persisting real ticks, never simulated ones.
- **Verified:** full test suite green throughout (190 → 199 passed, 1 skipped); import smoke tests after every edit.
- **Files:** `core/services/database.py`, `core/trading/broker.py`, `tests/test_tick_persistence.py` (new).
