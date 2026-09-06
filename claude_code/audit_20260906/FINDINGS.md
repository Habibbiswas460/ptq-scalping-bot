# Full audit findings — 2026-09-06. Five of seven agents reported.
# Every claim below was reported by an agent; the ones I checked myself are marked
# in verified.md, which also records three claims I had to correct.

## P0 — ACT BEFORE THE NEXT SESSION
**PE confidence bug becomes active the moment delta is populated.**
core/engines/adaptive_confidence_engine.py:58 compares RAW SIGNED delta:
    greeks_score = 100 if 0.35 <= delta <= 0.65 else 50 if 0.30 <= delta <= 0.70 else 10
weighted_score_engine.py:73 was already fixed to abs(delta) with a comment saying PE
deltas are negative. The sibling never got it. ATM PE at delta -0.45 scores 10 instead
of 100; greeks_score carries 0.20 of confidence (line 77) => 18 points lost. Gate is
70-72%. Masked today only because delta is always 0. TICK_DELTA_ENABLED is now True.
FIX: use abs(delta), same as the sibling file.

## P1 — the numbers everything else rests on
1. Bid/ask 100% fabricated, root cause located: brokers/angel_one/client.py:1762
   _parse_ws_binary never decodes best_bid_price/best_ask_price; option is subscribed in
   mode 2 (Quote), which carries no depth anyway. Fallbacks: ltp*0.003 (WS, 99.98% of
   73,171 ticks) and ltp*0.001 (REST). Runtime logged "real=0 estimated=37413 (100.0%)"
   for all of 2026-09-04. Every spread filter and the wide-spread kill react to arithmetic
   on ltp. 18 "Wide spread KILL" events on 09-01 were the Rs0.05 REST floor, not illiquidity.
2. Take-profit exits came from a bug since fixed. 5 trades, +Rs4,163.90, all 07-08/07-23.
   98 trades since: zero. Book without them: -Rs4,979.65, not -Rs815.75.
3. Entry signal cannot discriminate: 31 distinct (score, confidence) pairs across 89,673
   evaluations on the three tick sessions. 8/12 score and 7/10 confidence components
   empirically constant. Acceptance 75/89,673 = 0.084%.
4. Position size never varied: qty=65 on all 131 trades despite a 7-factor multiplier
   stack. lots = floor(risk_amount / (SL_POINTS * LOT_SIZE)) quantizes every grade to 1.
5. Declared SL/TP never governed an exit: 0 of the 34 trades where the bracket was
   recorded. Early cut fires at 2.5-4.5pts, soft loss at 1.8pts, against a 7pt hard SL.
6. Cost floor 0.93 pts/round trip (Rs60.46 on Rs6,959 premium value) vs a measured
   capture ceiling of 1-2 pts. STT 0.1% sell side, NSE txn 0.035%, GST 18%.
7. SEBI retail algo framework enforceable since 2026-04-01: Algo-ID per order, static-IP
   whitelisting, broker-side strategy tagging. Codebase implements none.

## P2
8. Opening window has a SECOND cause. 2026-09-03 option feed frozen 09:15:38-09:25:43;
   kill-switch "Stale data" fired every minute 09:16-09:25. First trade 11:10:14. Zero
   trades in 09:15-09:45 on 09-03 or 09-04. The p=0.0057 finding stands (spot series,
   arbitrary timing) but acting on it needs a feed that works at the open.
9. MFE/MAE column unreliable: 15 of 89 rows exceed the 7pt x qty cap; trade 72 shows
   mae -Rs5,697.90 on a 9.7s trade with a Rs455 cap. The research layer does NOT use this
   column (recomputes from ticks) so instrument findings are unaffected.
10. Signals retained 7 days, trades forever: only 47 of 131 trades still have their
    originating decision record. prune_old_signal_rows covers 3 of 11 tables.
11. 82MB (20.5%) of the 399MB trades.db is freelist; auto_vacuum NONE, no VACUUM anywhere.
12. 40.5% of tick rows share a same-second key; sub-second ordering unrecoverable
    (_db_timestamp uses timespec='seconds', and it stores detection time not exchange time).
13. Historical candle retry is dead code: client.get_candle_data swallows the rate-limit
    exception and returns [], caller only retries on a raised exception. Observed
    2026-09-02 11:25:46 — one attempt, indicators cold-started for the session.
14. refresh_tokens() (client.py:300) is never called. Token expiry looks like a network
    error with no path back short of restart.
15. Order-fill timeout is never reconciled: broker.py:1993 treats it as failed;
    get_position_cached() is called only from tests. A late fill is invisible.
16. Entry price-chasing can race a late fill with a fresh order (broker.py:1833-1897,
    cancel wrapped in bare except). Never executed live.
17. DVF paper_executor uses a flat SL/TP model, not check_exit_conditions() — mechanically
    explains why dvf_trades was rejected as a sample.
18. check_gap_protection is a continuous intraday filter, not an opening-gap filter:
    previous_close set once at startup, never updated.
19. data_source not persisted (no column in ticks).
20. Three-way import cycle: smart_scalp_v3 <-> state_machine <-> entry_engine, masked by
    function-local imports.
21. _get_ws_exchange_type defined twice in client.py (1226 dead, 1830 live), different
    fallbacks.
22. run.sh:822-828 if/else sets USE_LIVE_DATA=true on both branches — the paper+simulated
    mode is unreachable from the launcher.
23. entry_engine applies a second, flat confidence floor (70/85) textually identical in
    reject_reason to the strategy's own MQ-adjusted floor. After 3 losses entry_engine's
    85 always wins, so post-streak gating is governed there, not by the documented scheme.
24. DATABASE_PATH / DATABASE_ENABLED / DATABASE_LOG_SIGNALS / DATABASE_LOG_TICKS are read
    into CONFIG and referenced nowhere. .env says LOG_TICKS=false; 73,171 tick rows exist.
25. KILL_SWITCH_LATENCY_MS imported but never used; hardcoded 500 is the real threshold.
26. bot_state and daily_summary tables: 0 rows, no writer.
27. dvf_signals.spread and .volume: 100% NULL though in schema and INSERT.
28. core/historical/ has never run: data/historical/canonical/ does not exist.

## What is genuinely good (from five independent agents, unprompted agreement)
- research/ + visual_records.db per-field provenance; it independently corroborated every
  data finding with zero contradiction, and it already refuses the tainted mfe column.
- Exit-not-confirmed -> KILL_SWITCH + manual_intervention_required, never a fabricated close.
- Crash recovery refuses to auto-manage a leftover position.
- Subscription confirmation requires a real tick, not a send-and-forget ack.
- Multi-layer WS reconnect with heartbeat, backoff, jitter, 429 cooldown — observed working.
- Per-endpoint rate limiting matches Angel One's published caps and actually sleeps.
- RuntimeState guards the one genuinely cross-thread structure with an RLock.
- utils/trading_calendar.py separates declared/inferred/observed and refuses to invert absence.
- Single writer per database, verified by exhaustive grep.
- The delta/OI dead-field problem is documented in-line at the point of the fix.

## Ops/security/compliance agent (7th agent — research-instrument — did not report)

### ACTION REQUIRED
**Rotate the Telegram bot token.** The ops agent's own diagnostic printed the live
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID into its transcript. It disclosed this itself and
did not repeat the values. Revoke via @BotFather (/revoke) and reissue.

### CORRECTION to my earlier audit artifact — SEBI was OVERSTATED
My published report said live trading "would not be compliant" and listed Algo-ID +
static IP as a P1 code gap. Verified against sources, that is wrong for this user:
 - Under 10 orders/sec, a single retail trader running their own strategy needs NO
   individual registration. This bot is nowhere near that rate
   (ORDER_RETRY_DELAY_MS=500, MAX_RETRIES=3, single position).
 - Algo-ID is assigned broker/exchange side, not constructed by the client application.
 - Static-IP whitelisting IS required from 2026-04-01 for order-placement APIs, but it is
   an ACCOUNT setting registered at Angel One (up to 5 IPs per API key), not code.
=> The codebase correctly implements nothing, and correctly needs to implement nothing.
   One account-side action remains: register the static IP with Angel One, else live
   order placement is rejected. Paper trading unaffected.
Sources: angelone.in/knowledge-center SEBI algo rules; angelone.in SmartAPI April 2026.

### Other ops findings
- Market-hours/holiday standby is skipped when PYTEST_CURRENT_TEST is set
  (core/main.py:297-299). Most evidence-consistent explanation for today's 17:28 run,
  though the agent could not confirm the env var was set. An env var, not a deliberate
  flag, disables the market-hours check.
- Kill switch is not a hard ceiling: it blocks new ENTRIES at Rs3,000 realized but does
  not force-close an open position. Worst case ~Rs3,400-3,900 per session, more if
  concurrent positions are possible (no single-position guard found).
- Paper mode is NOT broker-isolated: it uses real credentials and a real live session for
  market data. Only a single `if PAPER_TRADING:` branch separates paper from a real order.
- No backup of trades.db (399MB) anywhere. WAL mode is on; no cron, no script, gitignored.
- app.py / core/main.py have NO confirmation logic — all live-trading safety is in run.sh.
  Any direct `python app.py` runs whatever .env says, with no prompt.
- The 4 ORPHANED rows are paper-only, pnl=0, and the string that wrote them exists nowhere
  in the current source or in ANY commit in git history. Origin unknown.
- requirements.txt is floor-pinned (>=) with no lockfile; venv is Python 3.14.4.
- Telegram chat_id authorization IS correctly enforced on every command and callback.
- No secret has ever been committed to git, across all reachable commits.

## Research-instrument agent (7th — reported after all)

### P1 — the flagship p-values were NOT computed by the audited instrument
research/visual/query.py:10-16 explicitly REFUSES to compute significance ("no p-value,
no confidence interval, no causal statement"). research/experiment.py only renders text a
human typed into research/experiments.json. The actual permutation tests — p=0.0057
opening window, p=0.0235 entry timing — live in claude_code/experiments/*.py
(exit_lab.py, exp11_prefilters.py), which:
  - are covered by ZERO of the 568 tests
  - open the trading DB with plain sqlite3.connect(), NOT mode=ro, so research/db.py's
    "a research bug can never corrupt a session's record" guarantee does not extend to them
  - contain a THIRD independent reimplementation of the exit ladder
    (live state_machine.py, research/replay.py, and exit_lab.py)
=> [[project_ptq_opening_window]] is the project's most-cited result and it rests on
   unaudited, untested code. It is not disproven — it is unverified.

### P1 — Book.spot() silently drops ~20% of ticks
research/db.py:86-92 keeps the FIRST of any same-second duplicate. Measured on 2026-09-04:
5,146 of 25,055 spot ticks dropped (20.5%); 4,575 of those groups (89%) had a genuinely
DIFFERENT price, intra-second swings up to 4.85 points. The collision RATE is disclosed
(provenance.py:48) but the RESOLUTION METHOD is not.
Insulated: opportunities.py:76 and entries.py:78 use the full undeduped book.option()
series, so "what the option offered" / capture-ratio findings are unaffected.
Affected: every spot-phrased metric — session.py, compare.py, transmission.py's regression,
and every spot candle in visual/build.py.
Also inconsistent: opportunities.py:48 resolves the same collision the OPPOSITE way
(dict overwrite keeps the LAST tick) on option ticks.

### P2 — replay.py's own stated fidelity does not reproduce
Docstring claims 22 of 24 exits reproduce by reason and second. Agent replayed all 24:
23/24 match by REASON, but 5 of 9 RSI-driven exits drift 1.3s-213s on timing. All 13
non-RSI exits (8 SOFT_LOSS, 5 EARLY_CUT) matched reason and hold time to within 1s.
The package's own caveat ("loss-side high confidence, RSI-timing directional") is correct
and if anything understates the RSI problem.

### VERIFIED GOOD — stronger than the shipped test checks
- Read-only guarantee HOLDS. Only research/db.py:34 touches trades.db, with mode=ro.
  No write-SQL anywhere else in the package, no core.* bot imports, no broker/login refs.
- Reproducibility re-verified more thoroughly than the shipped test: all 23 sessions, all
  13 visual_* tables (the shipped test checks 5 tables on 1 session) fingerprinted against
  the live 117MB record — byte-for-byte identical except built_at.
- Look-ahead safety is structural and the project has proof it matters: research/README.md:84
  documents a RETRACTED finding (OBS-01, p=0.0042 -> p=0.54) caused by completed-candle
  look-ahead; the fix (candles.as_of) is now enforced by regression tests.
- query.py deliberately refuses significance tests, rankings, causal language and pooling
  of incompatible groups — in direct contrast to the unaudited scripts in finding 1.

### Minor
research/candles.py:16 and research/visual/schema.py:19 both define TIMEFRAMES with
different contents (4 vs 6 widths). Not a bug; a maintenance trap.
