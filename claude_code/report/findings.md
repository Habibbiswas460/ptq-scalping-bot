# PTQ Scalping Bot — Findings & Fix Log

**Status as of:** Friday, 2026-08-28 (evening), market closed for the weekend.
**Next planned session:** Monday, 2026-08-31 (confirmed correct — the next actual trading day after this weekend; the earlier-stated "25 August" was a mistaken date, 2026-08-25 was a Tuesday earlier that week).
**Mode:** No new fixes are being applied until a clean paper-trading session is collected and reviewed together. This document exists so nothing gets lost between now and then.
**Update (Sunday, 2026-08-30):** An independent multi-agent code review was run against the full working-tree diff (uncommitted changes across 28 files, plus the newly-committed `run.sh`) — separate from the "wait for clean paper-trading data" plan above, since these are correctness/config bugs found by static review, not behavior questions needing live data. All 10 findings from that review were fixed and verified same-day; see **Section 11**.

---

## 0. How to use this document

- **Section 1** = bugs found and fixed this session, with code-verified (unit/isolation-level) confirmation. **None of these have been verified in a live trading session yet** — they need a bot restart.
- **Section 2** = new findings from the Senior Engineering Review that are **not yet fixed**, awaiting a decision on priority/scope.
- **Section 3** = statistical/analytical questions that are open specifically because we lack clean data (pre-fix history is not a fair test).
- **Section 4** = the exact plan agreed with the user for the next session.
- **Section 5** = full list of files touched this session, for reference.

---

## 1. Confirmed fixes (code-verified, NOT yet live-verified)

Every item below passed `pytest` (25 test files, all green) and was independently verified via isolated functional tests. **None have run in a live trading session** — they take effect on the next bot restart.

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
- `STRIKE_PREMIUM_MIN`/`MAX` (strike-selection band in `broker.py`, distinct from `MIN/MAX_ENTRY_PREMIUM`)
- ATR-adaptive SL/TP: `ATR_SL_HIGH/LOW_THRESHOLD`, `ATR_HIGH/LOW_SL/TP_ADJUSTMENT`, `ATR_SL/TP_MIN_POINTS`
- **Files:** `config/constants.py`, `core/engines/exit_engine.py`, `core/trading/broker.py`, `strategies/smart_scalp_v3.py`, `.env`, `.env.example`
- **Still flagged, not resolved:** `STRIKE_PREMIUM_MIN/MAX` (90-150) is still narrower than `MIN/MAX_ENTRY_PREMIUM` (70-350), and the `.env` comment on the latter literally says *"was 150, blocked all ATM options"* — implying the strike-selection band should probably be widened too, but this would be a behavior change, not done without sign-off.

### 1.6 DVF virtual-trade PnL always computed as `0.0`
- **What was wrong:** `record_decision()` in `core/validation/paper_executor.py` read `decision.get("position_size_recommendation")`, which the caller (`entry_engine.py`) never set — defaulted to `0`, making every virtual trade's qty 0, so `pnl = price_diff * 0 = 0` always.
- **Fix:** Falls back to `LOT_SIZE` instead of `0`. Verified end-to-end: a test decision now produces `pnl=975.0` instead of `0.0`.
- **File:** `core/validation/paper_executor.py`

### 1.7 Database bloat — no retention on per-tick tables
- **What was wrong:** `signals` and `dvf_signals` tables logged every strategy evaluation (not just trades), growing to 1.13M rows each — 1.4GB `core/data/trades.db`.
- **Fix:** Added `prune_old_signal_rows(retention_days=7)`, called at `app.py` startup. One-time cleanup already run: deleted 1,062,844 / 1,062,860 rows respectively, no impact on the live bot during the ~6.5min operation (WAL mode). **Note:** file size on disk is unchanged until a `VACUUM` is run — deliberately not done while the bot could be live; do during a maintenance window.
- **Files:** `core/services/database.py`, `app.py`

### 1.8 Signal/cooldown crash-loop (pre-existing, already fixed before this session started)
- Confirmed via log forensics (09:21-10:06 on 08-27): `state_cooldown()` crashed with `TypeError` whenever `cooldown_until` was `None` (several ENTRY_READY→COOLDOWN paths never set it), causing a rapid IDLE→ENTRY_READY→COOLDOWN→crash→IDLE cycle every ~1-2s instead of respecting the real cooldown. The fix (null-check + fallback duration) was already present in the uncommitted working tree when this session began — verified working (pattern stopped exactly at 10:06:10, all later signals correctly spaced).
- **No action needed** — documented here only so the history makes sense.

### 1.9 Cooldown gaps
- `COOLDOWN_AFTER_PROFIT` (30s) was loaded from `.env` but never referenced anywhere in `get_cooldown_duration()` — wins got the same 120s cooldown as everything else. **Not fixed** — flagged, no decision made on it.
- Non-trade blocks (risk block, execution-drift skip, position-size-zero, order failure) reuse the same generic `get_cooldown_duration()` as real trade exits. **Not fixed** — flagged only.

### 1.10 Duplicate bot instance / process management
- **What was wrong:** A restart left the old process suspended (`T` state, likely a stray Ctrl+Z) instead of exiting; a second instance was started on top of it, both hitting Angel One's API simultaneously → the "Access denied — exceeding access rate" error.
- **Fix applied (session-only, not code):** killed the stale process (`kill -9`, since it was stopped and unresponsive to `SIGTERM`). No code change — this was an operational fix, not a bug fix. **Process hygiene note for future restarts:** always confirm `pgrep -af "app.py"` shows the expected count before and after restarting.

### 1.11 Consecutive-loss deadlock — highest-impact fix this session
- **What was wrong:** `RiskManager.check_streak_limits()` blocked new entries permanently after `CONSECUTIVE_LOSS_LIMIT` (2) losses — the only way to clear it was a win, but a win can't happen while blocked. **Real production impact measured:** 2,048 consecutive `"RISK BLOCKED: Consecutive losses: 2, PAUSE"` events from 11:21:18 to 15:16:00 on 2026-08-28 — the bot didn't trade for the last ~4.5 hours of that session.
- **Fix:** Time-based pause reusing the already-existing (but previously unused by this code path) `pause_after_consecutive_loss_sec` / `COOLDOWN_AFTER_CONSEC_LOSS=900` (15min) config — mirrors the pattern already working in `state_machine.check_trade_limits()`. Verified: triggers correctly, auto-clears and resets the streak counter after the window.
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
- **Verified live on 08-28:** `✓ Previous close set for gap protection: ₹24,090.85` at startup; `capital` field in risk-budget logs correctly tracked cumulative PnL trade-by-trade (proof `record_trade()` is live).
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
- **Important:** the old `compute_trade_mfe_mae_from_ticks()` function itself was left in place (still covered by an existing test, `tests/test_dvf_pipeline.py`) — only the *live trade-logging* call site was switched. **All existing DB rows' `mfe`/`mae` values predate this fix and cannot be trusted** — this is the reason we're collecting a fresh session before doing any MFE-capture analysis.
- **Files:** `core/engines/exit_engine.py`, `core/engines/state_machine.py`

### 1.17 Asymmetric spread accounting between wins and losses
- **What was wrong:** `broker.py`'s `exit_position()` used real bid/ask tick pricing for wins, but unconditionally substituted the exit-engine's LTP-based estimate for any loss (originally meant as a safety cap, but implemented as a full override, not a floor). **Confirmed with real data, verified two independent ways:** (1) parsing exit-message embedded amounts vs. stored `pnl` — losses matched the message exactly (~₹0 diff) while wins were systematically lower (avg -₹10 to -₹70 depending on exit type); (2) computing points directly from `entry_price`/`exit_price` fill columns for all 25 trades on 08-27/08-28 — every mismatch between fill-implied and stored pnl was a loss trade, always in the direction of the fill-based version being worse.
- **Fix:** `exit_position()` now uses the real bid/ask PnL for losses too, with the engine's capped value applied only as a hard floor (`pnl_inr = max(pnl_inr, -max_loss)`), not an unconditional substitute.
- **Verified in isolation, all 4 branches:** (a) loss milder than cap → real fill value used (spread cost now included), (b) loss exceeding cap → still floored correctly, (c) win with suspiciously-zero tick PnL → engine value still used (edge case preserved), (d) normal win → unchanged.
- **Real-world magnitude found:** on 08-27, true fill-based net points were **-9.40pts** (~-₹611) vs. the ~-₹557 that was actually recorded; on 08-28, true net was **+0.70pts** (~+₹45.50) vs. the +₹74.10 that was recorded. Both days' true results were worse than what was displayed at the time.
- **File:** `core/trading/broker.py`

---

## 2. Open findings — NOT fixed, pending decision

### 2.1 [Architecture — significant] Backtest and live run completely different exit logic
- `core/backtest.py` does not call `core.engines.exit_engine.check_exit_conditions()` at all. It has its own from-scratch trailing-SL (`trailing_activation_points=5`, `trailing_step_points=1.5` — nothing like live's 8-rung ladder) and presumably separate SL/TP handling.
- **Impact:** any backtest run today tells you nothing about how the *current* live exit logic (including everything fixed this session) would have performed historically. This is likely *why* several of tonight's bugs (TP-ladder conflict, dead breakeven, RSI-floor gap) went unnoticed for as long as they did — a backtest exercising the real exit chain probably would have surfaced them.
- **Proposed fix (not scoped/implemented):** refactor `backtest.py` to call the same `check_exit_conditions()` used live, feeding historical data instead of live ticks.
- **How to test once done:** replay 08-28's known 10 trades through the backtest engine with the same tick history; it should reproduce the same exits/PnL exactly, or it's still not trustworthy.
- **Status: open, needs a scoping conversation — this is a project of its own, not a quick patch.**

### 2.2 [Execution risk] Live (real-money) order path has zero execution history
- Every trade in the DB is `order_id LIKE 'PAPER_%'`. The limit-order price-chasing/market-fallback/status-verification logic in `broker.py`'s live branch (`place_order`/`exit_position`, `PAPER_TRADING=False` path) has never actually run.
- **Status: open — not a code bug, a testing gap. Needs a deliberate small-size live test before scaling, whenever live trading is being considered.**

### 2.3 [Architecture — minor] Inconsistent lock discipline around `broker.last_tick`
- `_on_ws_tick()` (WebSocket thread) always locks `self._tick_lock` around `self.last_tick` access. `check_and_rotate_strike()` (main thread) reads/writes it at `broker.py:414` and `:469` **without** the lock.
- **Assessed severity: low in practice** — CPython's GIL makes the pointer-reassignment pattern here effectively atomic, and an existing token-match guard (`broker.py:1012`) independently prevents the worst-case stale-tick scenario. Still a real inconsistency, not defined-by-design safe.
- **Proposed fix:** wrap both access points in `check_and_rotate_strike()` with `self._tick_lock`, matching every other access site.
- **Status: open, low priority.**

### 2.4 [Execution] One historical warm-up rate-limit failure
- 08-27's first restart hit "Access denied because of exceeding access rate" on `get_historical_candles()`, causing that session to start with indicators from zero.
- **Likely root cause:** the duplicate-instance issue active at the same time (doubled API request volume) — now fixed. Needs more restarts to confirm whether this recurs on its own.
- **Status: open, watch-and-see. No fix proposed until we have evidence it's an independent problem.**

### 2.5 [Config gap, low priority] `COOLDOWN_AFTER_PROFIT` dead, non-trade blocks reuse trade-exit cooldown logic
- `COOLDOWN_AFTER_PROFIT=30s` is loaded but never referenced in `get_cooldown_duration()` — wins get the same 120s cooldown as everything else.
- Non-trade entry blocks (risk block, execution-drift skip, position-size-zero, order failure) fall back to the same generic cooldown-duration function as real trade exits, with no awareness that no capital was ever at risk.
- **Status: open, flagged only, not prioritized.**

### 2.6 [Config inconsistency, low priority] `STRIKE_PREMIUM_MIN/MAX` (90-150) narrower than `MIN/MAX_ENTRY_PREMIUM` (70-350)
- The `.env` comment on `MAX_ENTRY_PREMIUM` literally says *"was 150, blocked all ATM options"* — implying intent to widen the strike-selection band too, which was never done.
- **Status: open, flagged only. Changing it is a real behavior change (affects which options get considered at all), not something to do without discussion.**

### 2.7 [Cosmetic] `MAX_HOLD_TIME_WINNING`/`MAX_HOLD_TIME_LOSING` imported into `exit_engine.py`, never used
- The real 15-minute max-hold is a separately hardcoded `MAX_HOLD_TIME_SEC = 900` (`exit_engine.py:63`) that happens to numerically match the env default but isn't sourced from it.
- **Status: open, zero functional impact today (values coincide). Not prioritized.**

### 2.8 Documentation-only: exit-priority docstring doesn't match actual code order
- `check_exit_conditions()`'s docstring numbering (1, 2, 4-labeled-as-early-cut, 4b, 5, 6...) doesn't match the real execution order in the code. Zero behavioral effect, just confusing to read.
- **Status: open, trivial, not prioritized.**

---

## 3. Statistical / analytical questions — genuinely open, need clean data

These are NOT bugs — they're questions we don't have enough (or trustworthy) data to answer yet:

1. **Does the strategy have positive expectancy?** Pre-fix history (84 trades) is not a fair test — most of it ran under the position-sizing deadlock, the consecutive-loss deadlock, dead risk features, and the spread-accounting asymmetry. The one fair, fill-based sample we have (08-27/08-28, 25 trades) showed **net -8.70 points**, avg loser (-2.08pts) roughly double avg winner (+1.01pts) — real, but far too small a sample (2 days) to conclude anything about expectancy either way.
2. **Are we cutting winners too early (MFE capture)?** Cannot currently be measured — the only historical MFE data is the pre-fix, demonstrably-wrong global-buffer version (19-21% provably impossible). One suggestive but unverifiable data point: trade id=40 shows realized +0.01pts against a recorded (untrustworthy) MFE of +14.37pts.
3. **Is RSI Reversal Exit specifically premature?** Same blocker as #2 — needs trustworthy per-trade MFE broken down by exit condition.
4. **Is the trailing ladder actually letting winners run now that the TP ceiling is removed?** No post-fix data yet.
5. **Is the breakeven step helping or choking trades?** No post-fix data yet.
6. **Do soft-loss/early-loss exits cut trades that would have recovered?** Cannot be assessed without trustworthy MFE.
7. **Does the historical-warm-up rate-limit issue recur independent of the (now-fixed) duplicate-instance issue?** One data point only.

**All seven of these depend on the same next step: a clean paper-trading session with tonight's fixes live, generating trustworthy trade-scoped MFE/MAE data.**

---

## 4. Agreed plan (as of this document)

1. **Do not apply further fixes** until the next session's data is reviewed.
2. **Restart the bot in clean paper-trading mode** for one full session — target date confirmed as **Monday, 2026-08-31**, the next trading day after this weekend.
3. **Collect**: full day's logs (`logs/<date>/bot.log`), trades table (`core/data/trades.db`), and the live crash/error monitor output if re-armed for that session.
4. **Analyze together**, specifically:
   - MFE vs. realized points, broken down by exit condition, with % of MFE captured per trade and per category.
   - Whether any exit category (RSI Reversal, RSI Exit, Early Loss Cut, Soft Loss Exit, Trailing Profit) is systematically leaving profit on the table.
   - Whether the TP-ladder and breakeven fixes behaved as intended in live conditions, not just unit tests.
   - Whether the consecutive-loss pause, gap protection, and daily-loss tracking fire correctly and appropriately during a live session.
   - Cross-check against every open item in Section 2 and Section 3.
5. **Only then** decide priority and scope of the next round of fixes, based on evidence from that session plus everything in this document — not on the 2-day sample alone.

---

## 5. Files touched this session (for reference — all committed to working tree, not yet live)

- `config/constants.py`
- `core/engines/position_size_engine.py`
- `core/engines/exit_engine.py`
- `core/engines/state_machine.py`
- `core/risk/risk_manager.py`
- `core/risk/__init__.py`
- `core/trading/broker.py`
- `core/main.py`
- `core/services/database.py`
- `core/validation/paper_executor.py`
- `strategies/smart_scalp_v3.py`
- `app.py`
- `.env`
- `.env.example`

No production/live trading behavior has been restarted or altered since these edits were made — everything is staged, tested (unit/isolation level only), and waiting for the planned clean session.

---

## 6. `run.sh` review (2026-08-28, investigation only, nothing modified)

### 6.1 [Security] Credentials embedded in a `python -c` command line
- **What's wrong:** `menu_health()`'s API connectivity check (`run.sh:1646-1653`) interpolates the real Angel One API key/client ID/password/TOTP secret directly into a `python -c "..."` command string.
- **Why it matters:** on Linux, a process's full command line (including `-c` script text) is visible to any local user via `ps aux` or `/proc/<pid>/cmdline` by default — this is live, running-process exposure, not just a shell-history concern.
- **Impact:** real credential exposure risk on any shared/multi-user machine; low likelihood on a single-user personal machine but a genuine vulnerability pattern regardless.
- **Proposed fix (not applied):** pass credentials via environment variables to the subprocess instead of string-interpolating them into the script text (env vars are visible only via `/proc/<pid>/environ`, restricted to root/same user — much narrower exposure than `ps aux`).
- **How to test:** run the health check; from another local session, `ps aux | grep python` should no longer show the secrets in plaintext.
- **Status: open, not fixed.**

### 6.2 [Moderate] Two divergent virtualenvs — `venv` (used by `run.sh`) vs `.venv` (used for all testing this session)
- **What's wrong:** `run.sh` exclusively creates/uses `venv/` (36 packages, created 2026-06-14). All testing and verification this entire session used `.venv/` (47 packages, created 2026-07-05) via manual `source .venv/bin/activate`. They are genuinely different environments — different versions of `certifi`, `click`, `idna`, `python-dateutil`, `python-dotenv`; `.venv` additionally has `pandas`, `numpy`, and an entirely unrelated broker SDK (`neo-api-client`, for Kotak Neo) that `venv` doesn't have at all.
- **Why it matters:** every fix verified this session was tested under an environment `run.sh` doesn't actually use to launch the bot.
- **Verification done:** re-ran the full test suite under the real `venv` — **168 passed, 1 skipped** (vs. all passing under `.venv`). The one skip (`test_market_quality_tick_age_accepts_pandas_timestamp_if_available`) uses `pytest.importorskip('pandas')` by design — pandas isn't in `requirements.txt`, no project code imports it, this skip is benign. **All of this session's fixes are confirmed to also pass in the real `venv`** — the divergence didn't invalidate anything found/fixed so far, but it could next time without an explicit cross-check like this one.
- **Proposed fix (not applied):** consolidate to one canonical venv location (`.venv` is the more common modern convention) and either delete the other or document which one is authoritative.
- **How to test:** after consolidating, confirm `run.sh`'s `PYTHON_BIN` resolution finds the single canonical venv and the full test suite passes identically there.
- **Status: open, not fixed. Verified it hasn't invalidated anything so far.**

### 6.3 [Bug, cosmetic] Duplicate menu entry
- `menu_tools()` prints `[8] Market Readiness Pro` twice in a row, verbatim (`run.sh:1712-1713`). Only one `case` handler exists for `8)`, so it's visually broken but not functionally harmful.
- **Status: open, trivial, not fixed.**

### 6.4 [Minor] Version strings hardcoded, no single source of truth
- `BOT_VERSION="v5.1"`, `ENGINE_VERSION="v3.5"`, `READINESS_VERSION="v2.0.0"` are literals at the top of `run.sh`, disconnected from git tags or any versioned file — nothing catches drift if code changes but these aren't bumped.
- **Status: open, flagged only, not prioritized.**

### 6.5 [Minor] Inconsistent `bc`-missing fallback for R:R ratio display
- Two near-identical R:R calculations (`run.sh:1140`, `:1356`) both shell out to `bc`; one falls back to `"?"` if missing, the other silently shows a fabricated `"2"`. Worth deciding on one consistent (honest) fallback.
- **Status: open, trivial, not fixed.**

### 6.6 Checked and confirmed fine (no issue)
- All 25 files referenced in `run_syntax_check()`/`menu_health()` exist — no broken references.
- `summary.json` generation works correctly for all recent sessions (08-26/27/28) — an earlier suspicion of a gap here was a false alarm caused by a truncated `find | head -5`, not a real bug.
- `TRADING_START`/`TRADING_END` env var names match what `config/constants.py` actually reads — no naming mismatch.

---

## 7. Telegram integration — significant dead-wiring finding (2026-08-28, investigation only)

- **What's wrong:** `.env` has Telegram fully configured (`TELEGRAM_ENABLED=true`, real bot token, real chat ID, all four `TELEGRAM_NOTIFY_ENTRIES/EXITS/KILL_SWITCH`/`TELEGRAM_DAILY_SUMMARY` set `true`). But `notify_entry()`, `notify_exit()`, `notify_kill_switch()`, `notify_daily_summary()` — all four complete, correctly-implemented functions (`core/services/telegram_bot.py:697-741`) — are imported once in `core/main.py:64` and **never called anywhere**. The four `TELEGRAM_NOTIFY_*` toggle constants are parsed from `.env` but aren't even added to `CONFIG['telegram']` (which only has `enabled`/`bot_token`/`chat_id`), so they'd do nothing even if the notify calls existed.
- **What does work:** `notify_startup()` fires once at launch (`core/main.py:175`); a handful of genuinely-wired ad-hoc `send_alert()` calls fire for rare edge cases — intraday spike detection (`state_machine.py:197`), PnL capping (`exit_engine.py:481`), high slippage / emergency exit-failure in live trading (`broker.py:1741`, `:1944`).
- **Why it matters:** if entry/exit/kill-switch/daily-summary Telegram messages were expected during any session so far, none were ever sent — only the one-time startup ping and rare emergency alerts. Real gap between configured intent and actual behavior, purely on the monitoring/notification side (zero effect on trading correctness).
- **Proposed fix (not applied):**
  1. Add the four `TELEGRAM_NOTIFY_*` constants to `CONFIG['telegram']` in `config/constants.py`.
  2. Call `notify_entry(trade)` after a successful order in `state_machine.py`'s `state_entry_ready()`, gated on `TELEGRAM_NOTIFY_ENTRIES`.
  3. Call `notify_exit(trade, pnl, exit_reason)` in `state_machine.py`'s exit block (alongside the existing `rm.record_trade()`/`log_trade_exit()` calls), gated on `TELEGRAM_NOTIFY_EXITS`.
  4. Call `notify_kill_switch(reason, details)` at kill-switch state transitions, gated on `TELEGRAM_NOTIFY_KILL_SWITCH`.
  5. Call `notify_daily_summary(summary)` in `core/main.py`'s shutdown sequence next to the existing `logger.daily_summary({...})` call (same data), gated on `TELEGRAM_DAILY_SUMMARY`.
- **How to test:** after wiring, run one paper session and confirm all four message types actually arrive in the configured Telegram chat, matching what logs/DB show for the same trades.
- **Status: open, not fixed. High user-visibility impact, zero trading-correctness impact.**

### 7.1 Follow-up check (2026-08-29): the `send_alert()` transport itself is confirmed working — this is a different, better-off finding than 7's dead functions
- **What I checked:** traced the full path for the 4 `send_alert()`/`get_telegram()` call sites (PnL-capped in `exit_engine.py:481`, spike detection in `state_machine.py:197`, high slippage in `broker.py:1741`, emergency exit-failure in `broker.py:1944`).
- **Verdict: genuinely wired, not dead.** `TelegramBot.send_message()` queues a message; a background thread (`_bg_worker`, started via `TelegramBot.start()`) drains the queue and sends via `aiohttp`. Confirmed `.start()` is actually called — `init_telegram()` (`telegram_bot.py:977-981`) calls it internally, and `core/main.py:167-175` calls `init_telegram()` whenever `TELEGRAM_ENABLED=true` (which it is). `send_alert()` correctly null-checks the module singleton before sending.
- **Real-world evidence it has actually fired, not just wired-on-paper:** grepped the logs — `"PnL CAPPED"` alerts fired **5 times on 08-27, 4 times on 08-28** (9 total), matching exactly the known early-loss-cut/soft-loss-exit trades. Spike/slippage/emergency-exit-failure show 0 occurrences — consistent with those specific conditions simply never having happened, not a bug.
- **What I can't verify from here:** whether those 9 alerts were actually *received* in the Telegram chat (requires checking the Telegram app itself, not available from this environment). Worth a manual glance at Telegram history for 08-27/08-28 to close the loop.
- **One trivial inconsistency, not a bug:** `broker.py:1944` calls `get_telegram().send_message()` directly instead of the `send_alert()` wrapper (which just prepends a 🚨 emoji) — cosmetic only.
- **Net picture on Telegram overall:** works and confirmed firing — `notify_startup()`, plus the ad-hoc `send_alert()` edge-case alerts (PnL cap, spike, slippage, emergency). Never wired, confirmed dead — the four structured `notify_entry/exit/kill_switch/daily_summary` functions (§7 above).
- **Status: informational — no fix needed for this part. Confirms §7's proposed fix can reuse the same, already-working `send_message()`/queue/background-thread transport; no new plumbing required, just the missing call sites.**

---

## 8. `core/services/mode_switch.py` review (2026-08-28, investigation only)

### 8.1 [Significant — affects how to interpret ALL data collected, including Monday's session] AGGRESSIVE↔SAFE↔LOCKDOWN mode-switching is disabled in paper trading, by design
- **What's wrong:** `should_go_safe()` starts with `if PAPER_TRADING: return False, ""` (`mode_switch.py:188-190`). Since `PAPER_TRADING=true` for every session run so far and every session planned through Monday, this function has never once triggered — the bot has run under `AGGRESSIVE_THRESHOLDS` (paper-relaxed: delta 0.15-0.90, looser volume ratio, wider spread tolerance) for every trade analyzed to date.
- **Why it matters:** the adaptive risk-tightening subsystem (downgrading to stricter `SAFE_THRESHOLDS` on consecutive losses, volume deterioration, chop, theta spikes, or late-session decay) has never been exercised. Confirmed NOT dead code — `get_threshold()` is genuinely read by `core/risk/validators.py` for real entry-quality gates (volume ratio, spread, delta range, gamma limits, theta limit); we just haven't seen the SAFE variant apply yet, and Monday's planned session won't either unless this is deliberately addressed.
- **Still active regardless:** `should_lockdown()` has no `PAPER_TRADING` bypass — daily-loss-based LOCKDOWN is a real, live check right now (triggers at 90% of your actual `.env` `MAX_DAILY_LOSS_AMOUNT`).
- **Origin, traced via git history (2026-08-28):** this is a deliberate 7-month-old design decision, not an accidental oversight. Introduced in commit `1ae11b2` ("Major Refactor: PTQ Bot v3.0 - SMART SCALP Strategy", 2026-02-03) — before that commit, `should_go_safe()` had no paper-trading bypass at all; mode-switching ran identically in paper and live. The diff adds the bypass with its own comment (`# Paper trading = stay AGGRESSIVE for testing`), consistent with wanting predictable behavior while developing/debugging the new v3.0 entry logic at the time. That original reasoning doesn't really apply anymore now that paper mode is being used to evaluate real strategy expectancy, not just to shake out bugs in new entry logic.
- **No partial/configurable option exists today** — it's a hard `if PAPER_TRADING: return False, ""` with no separate toggle to exercise mode-switching within paper mode. Lifting it for a session would be a real code change, not a config flag.
- **The decision for Monday, laid out plainly:** (1) leave it as-is — Monday's session stays AGGRESSIVE-only, consistent with every session so far, simplest, zero new risk; or (2) temporarily lift the bypass for Monday specifically — exercises the full mode-switching system for the first time, at the cost of introducing a new untested variable into the exact clean-sample session this is meant to be. Leaning toward (1) for Monday's specific sample, treating a mode-switch test as its own separate exercise later — but this is the user's call.
- **Status: not a bug — a standing data-interpretation caveat requiring a decision before treating any "entry quality" conclusion as complete. Not changed without sign-off.**

### 8.2 [Minor] Inconsistent lock discipline on `_current_mode`
- `update_trading_mode()`/`record_trade_result()`/`reset_mode()` correctly acquire `_mode_lock`; `get_current_mode()`/`is_entries_allowed()`/`get_mode_emoji()` read the same global without it. Same pattern and same low-severity assessment as the `broker.py:last_tick` finding (§6, CPython GIL makes this practically safe, just inconsistent by convention).
- **Status: open, low priority.**

### 8.3 Checked, confirmed not an issue: `reset_mode()` is never called
- Looks like a gap (a "reset for new day" function with zero callers) but isn't a deadlock — the bot's daily process restart naturally reinitializes the module-level `_current_mode = MODE_AGGRESSIVE` on fresh import. Redundant given the architecture, not broken.
- **Status: no action needed.**

### 8.4 [Config gap, low priority] Mode-switching thresholds are 100% hardcoded, no `.env` control
- `CONSECUTIVE_LOSS_TRIGGER=1`, `VOLUME_DETERIORATION_THRESHOLD`, `CHOP_DETECTION_THRESHOLD`, `THETA_DETERIORATION`, `SAFE_HOUR_NORMAL=13`, recovery thresholds, and both full `AGGRESSIVE_THRESHOLDS`/`SAFE_THRESHOLDS` dicts — none are owner-configurable via `.env`.
- Lower urgency than other config gaps found this session, since the subsystem doesn't activate in paper mode anyway (§8.1).
- **Status: open, flagged only.**

---

## 9. `core/services/session_manager.py` review (2026-08-28, investigation only)

### 9.1 [Dead code + latent bug] Entire file is unused, duplicated by a live implementation, with a real bug baked into the unused part
- **What's wrong:** `is_trading_session_allowed()` (`session_manager.py:3`) has the exact same name and logic as a completely separate, independently-implemented function in `state_machine.py:510` (same blackout/expiry/allowed-session checks, just reading config directly instead of via parameters). Confirmed via grep: nothing calls the `session_manager.py` version anywhere; `state_machine.py:621` calls its own local version instead. The "legacy alias" `is_session_allowed()` is also never called. `core/services/__init__.py`'s lazy `__getattr__` lists this module as a lookup candidate, but nothing ever triggers that path for it either.
- **The latent bug, for the record:** `is_session_allowed(session_filter_enabled=True, ...)` uses `session_filter_enabled if session_filter_enabled is not None else SESSION_FILTER_ENABLED` — intended to fall back to the real `.env`-configured value when not explicitly passed, but the default is the literal `True`, not `None`, so `is not None` is always true and the real config value could never be used even if this were called with no arguments. The other three parameters (`blackout_sessions=None` etc.) don't have this problem. **Currently zero impact since nothing calls it** — documented so it doesn't resurface silently if this "legacy" function is ever wired back up later.
- **Proposed fix (not applied):** delete `session_manager.py` (or at least both functions in it) — it's fully superseded by the live `state_machine.py` implementation. If kept for some other reason, fix the default to `session_filter_enabled=None`.
- **How to test:** grep for any reference before deleting; confirm `core/services/__init__.py` still works (it only references the module by string name, not a static import, so removal is safe there).
- **Status: open, not fixed. Low priority, safe cleanup candidate alongside the other dead-code removals from earlier this session.**

---

## 10. `core/services/database.py` review (2026-08-28, investigation only)

### 10.1 [Serious — reliability] No mechanism exists to recover an open position after a crash or restart
- **What's wrong:** a complete, well-built "active positions" subsystem exists — `save_active_position()`, `get_active_positions()`, `close_position_in_db()`, `check_orphan_positions()`, `get_positions_from_last_session()`, `clear_all_active_positions()`, `update_position_price()`, plus module-level wrappers (`save_position`, `close_position`, `check_for_orphans`, `recover_last_session_positions`, `clear_positions`, `update_position`) — **all confirmed zero external callers** anywhere in the codebase.
- **Verified no substitute exists:** `state.restore_from_trades()` (called at startup) only replays `trades.csv` to rebuild aggregate PnL/counters — never reconstructs an actual open position into `state.current_trade`. Grepped for any other place `state.current_trade` gets set from a persisted source at startup — none found.
- **Why it matters:** if the bot crashes or is restarted while a trade is open, the position is completely abandoned — the bot starts fresh in `IDLE` with `current_trade=None`, with zero awareness a position exists. **This is the confirmed root cause of the 4 orphaned `status='OPEN'` trades manually cleaned up earlier this session** (1 from 07-09, 3 from 08-25) — not isolated flukes, a systemic gap. In live trading this would mean a real open position with real capital at risk becomes entirely unmonitored (no SL, no exit logic) after any crash/restart, until a human notices and closes it manually.
- **Proposed fix (not applied):** on startup, call `get_positions_from_last_session()`/`check_orphan_positions()` (the machinery already exists) to detect a leftover open position and either resume monitoring it or safely close it out before starting fresh. Needs careful design — resuming requires reconstructing enough trade-dict state (`entry_price`, `sl_points`, `tp_points`, etc.) to feed back into `check_exit_conditions()` correctly, not just flagging that one exists.
- **How to test:** simulate a crash mid-trade (kill the process with a position open), restart, confirm the bot resumes monitoring or safely closes the position instead of abandoning it.
- **Status: open, not fixed. Highest-priority finding in this file — directly relevant to the reliability/failure-scenario concerns from the Senior Engineering Review (§16 in this document).**

### 10.2 Dead code — confirmed zero callers, safe cleanup candidates
- `log_entry()`/`log_exit()` — complete unused duplicate of the live `log_trade_entry()`/`log_trade_exit()` (same `trades` table).
- `save_bot_state()`/`load_bot_state()` — unused generic state persistence.
- `get_win_streak()` — a *third*, independent, unused streak-tracking implementation, alongside `RiskManager`'s own counters and `TradingState`'s own separate counters — none aware of each other.
- `get_weekly_summary()`, `get_daily_summary()`, `get_trades_by_date()`, `get_performance_by_hour()`, `get_performance_by_direction()` — unused analytics methods.
- `get_dvf_calibration()` (read side) — unused; write side `save_dvf_calibration()` is genuinely active (4 callers), so calibration data is recorded but never read back by anything.
- **Status: open, not fixed. Low risk, same category as the `RiskManager` dead-code cleanup done earlier this session.**

### 10.3 Confirmed alive and working — no issue
- The market-quality/confidence-calibration analytics cluster (`get_market_quality_distribution`, `get_hard_reject_stats`, `get_market_quality_win_rate_bands`, `get_market_quality_grade_win_rate`, `get_confidence_win_rate_bands`, `get_confidence_calibration`, `get_market_quality_grade_avg_pnl`) is genuinely consumed by `utils/mq_validation_report.py`, which runs automatically at shutdown (matches the `"✓ MQ validation archived"` line seen in every session's logs). Real, working feature.

---

## 11. Code-review session (Sunday, 2026-08-30) — 10 findings, all fixed same-day

A multi-agent (8-angle) code review was run against the full scope in play: the committed `run.sh` addition, the entire uncommitted working-tree diff (28 tracked files), and new untracked files (`get_fresh_evidence.py`, `get_old_evidence.py`, 4 new test files). Every finding below was independently confirmed by reading the actual current code (not just trusting the finder agent) before being fixed. All fixes verified with `venv/bin/python -m pytest tests/` (the real venv `run.sh` uses, per §6.2) — full suite green, no regressions, both before listing findings to the user and after applying every fix.

### 11.1 [Critical — real money] `KILL_SWITCH_LOSS` contradicted its own comment, live in both the code default and the actual running `.env`
- **What was wrong:** `config/constants.py:270` set `KILL_SWITCH_LOSS = env_int('KILL_SWITCH_LOSS', 3000)` right next to a comment reading `# Reduced from 900 to 600 (1.5% of 30k capital)` — the value and the comment disagreed by 5x. Worse: the live, gitignored `.env` file (the config actually used at runtime) independently had `KILL_SWITCH_LOSS=3000` too, so this wasn't just a stale template — the bot's real emergency stop-loss was running 5x looser than documented/intended. It also sat *above* `MAX_DAILY_LOSS_AMOUNT` (2500 in the code default), which made the dedicated kill-switch check in `core/risk/kill_switch.py:191` structurally unreachable — the generic daily-loss check at line 195 would always fire first.
- **Fix:** Set the code default back to `600` (matching the comment) and added a comment explaining it must stay below `MAX_DAILY_LOSS_AMOUNT` for the ordering to be correct. Also corrected the live `.env`'s `KILL_SWITCH_LOSS` from `3000` to `600` — this is a real behavior change to the bot's actual current configuration, not just the template.
- **Verified:** `python -c "import config.constants as c; print(c.KILL_SWITCH_LOSS, c.MAX_DAILY_LOSS_AMOUNT)"` now prints `600 3000` (was `3000 3000`) — kill switch will fire first, at the intended tighter threshold.
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
- **What was wrong:** `record_decision()`/`update_open_positions()` (`core/validation/paper_executor.py`, added earlier this session per §1.6) track open virtual positions in a plain in-process dict, `_OPEN_VIRTUAL_POSITIONS`. A position is only ever closed when a *later tick arrives while that same process is still running* — either a symbol-matched virtual SL/TP hit, or a 30-minute (`_MAX_VIRTUAL_HOLD_SEC=1800`) safety expiry checked on any subsequent tick. The `dvf_trades` DB row, however, is `INSERT`ed as `OPEN` immediately at entry. If the bot process restarts before that in-memory safety expiry fires, the dict is wiped clean on the next launch, and the DB row is never revisited — it stays `OPEN` permanently. This is the same underlying failure pattern as §10.1 (no recovery of in-memory position state across a restart), but on the DVF/paper-tracking side rather than the live `active_positions` side.
- **Fix — startup reconciliation, not persistence:**
  - `core/services/database.py`: added `get_open_dvf_trades()` (DB method + module-level wrapper) to fetch all `status='OPEN'` rows.
  - `core/validation/paper_executor.py`: added `reconcile_stale_open_positions(max_age_sec=1800)` — force-closes any DB-side `OPEN` row older than the safety-expiry window via the existing `simulate_exit()` path (flat exit at entry price, `exit_reason="Virtual max hold (reconciled on restart)"`).
  - `core/main.py`: calls it once right after `broker.connect()` succeeds, before the historical warm-up, so every startup sweeps up whatever the previous process instance left dangling.
- **Verified:** ran the reconciler against the real `core/data/trades.db` — closed **252** orphaned `OPEN` rows (all pre-existing, including the 20 the user spotted). `get_open_dvf_trades()` now returns 0. `venv/bin/python -m pytest tests/test_dvf_pipeline.py tests/test_exit_engine_sequence_regression.py tests/test_exit_engine_tsl_steps.py` — all pass, no regressions.
- **Not done:** true persistence (e.g., reconstructing `_OPEN_VIRTUAL_POSITIONS` from DB `OPEN` rows at startup so a position genuinely resumes tick-by-tick tracking instead of being force-closed flat). The reconciliation approach was chosen because DVF is explicitly analytics-only, read-only, never-feeds-back-into-trading (per the module's own "golden rule" comment) — a flat force-close on restart is simpler and safer than trying to resume tracking with a gap in tick history, at the cost of those specific reconciled trades having a synthetic (not real) exit price/pnl. Worth flagging in the eventual Section 3 analysis: any trade with `exit_reason = "Virtual max hold (reconciled on restart)"` should be excluded from PnL/expectancy analysis, same caveat as the pre-fix MFE/MAE data in §1.16.
- **Files:** `core/services/database.py`, `core/validation/paper_executor.py`, `core/main.py`
