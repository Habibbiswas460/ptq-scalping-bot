# My own verification of agent claims (not relayed — checked)

## Architecture agent

### CONFIRMED
- `_get_ws_exchange_type` defined twice in brokers/angel_one/client.py (1226 and 1830).
  inspect.getsourcelines() resolves to 1830 -> the 1226 copy is dead. Verified live.
- run.sh:822-828 if/else sets `export USE_LIVE_DATA=true` on BOTH branches. Verified.
- Constants bind at import: setting os.environ["TOTAL_CAPITAL"]=999999 after importing
  config.constants leaves C.TOTAL_CAPITAL at 30000. Verified.

### CORRECTED — real, but the consequence is smaller than the agent stated
Agent said the validator's auto-fix "is cosmetic for that run" and implied live config
could be stale. Checked:
  - config/configuration.py:27 runs load_dotenv() AT IMPORT, so os.environ carries .env
    before config.constants binds anything.
  - Constants therefore DO get the correct .env values. Spot-checked against .env:
    TOTAL_CAPITAL=30000, SL_POINTS=7, MAX_TRADES_PER_DAY=30 — all match.
  - core/main.py:249 calls validate_config(auto_fix=False). auto_fix=True appears only in
    tests/test_config_validator.py:134.
So: the system is NOT misconfigured. The accurate finding is a LATENT trap — the validator
can only report, never repair, for the running process; if anyone enabled auto_fix
expecting it to take effect on already-imported constants, it silently would not.
Severity: P3 (latent), not P1.

## Data agent

### CONFIRMED (spot-checked earlier in session + agent's own queries)
- bid/ask 100% derived. My own earlier check: every persisted quote sits exactly on the
  midpoint. Agent traced it further to the byte-offset gap at
  brokers/angel_one/client.py:1817-1819 (parser jumps oi@139 -> upper_circuit@347,
  skipping the best-5 depth block) and two fallback formulas (ltp*0.003 for 99.98%,
  ltp*0.001 for 14 rows). That root cause is new and more precise than anything I had.
- OI 0% populated across 73,171 ticks; TICK_OI_ENABLED flipped true only on 2026-09-05,
  after the last tick row (09-04), so it has never run against live traffic.

## Trade-management agent

### CONFIRMED — and it changes my own audit's headline
5 TAKE PROFIT exits total +Rs4,163.90, ALL dated 2026-07-08 and 2026-07-23.
  whole book        -Rs  815.75  (131 trades)
  without those 5   -Rs4,979.65
98 trades since 2026-07-23: ZERO take-profit exits. The guard landed in `fbaac2e`
(agent said edccb5b - minor attribution error, the effect is the same).
=> My cost audit used -Rs815.75 as "reported gross". The honest figure for CURRENT code
   is -Rs4,979.65 gross, which makes the cost arithmetic worse, not better.

### CONFIRMED
- trades.mfe / trades.mae are unreliable. Trade 72: PE, qty 65, held 9.7s, pnl +Rs4.55,
  mae -Rs5,697.90 — against a 7pt x 65 = Rs455 cap. 15 of 89 rows exceed that cap.

### CORRECTED — the agent's warning does NOT reach the memory finding
Agent implied the "MFE 1.79 vs 2.5 stop" finding may rest on the tainted column.
Checked: the research layer does NOT read trades.mfe. It recomputes from ticks —
research/market.py:83-84, research/replay.py:87-88 — and research/opportunities.py:24
states outright that it avoids the stored column because that one "is truncated by an
exit". So the instrument already knew not to trust it. The memory finding stands.

## Strategy agent

### CONFIRMED — and this is the most actionable finding of the whole audit
core/engines/adaptive_confidence_engine.py:58 compares RAW SIGNED delta:
    greeks_score = 100 if 0.35 <= delta <= 0.65 else 50 if 0.30 <= delta <= 0.70 else 10
core/engines/weighted_score_engine.py:73 was already fixed to use abs(delta), with a
comment stating outright that PE deltas are negative (-0.42, -0.68 measured on real
2026-09-04 quotes). The sibling engine never got the same fix.

Effect for an ATM PE at delta -0.45:
    confidence engine  greeks_score = 10
    score engine (abs) greeks_score = 100
greeks_score carries 0.20 of the confidence total (line 77), so a perfectly positioned
PE loses 18 confidence points. The confidence gate is 70-72%.

WHY IT IS URGENT: it is masked today only because delta is always 0 (0 also lands on the
10 branch). But TICK_DELTA_ENABLED is now True in .env — verified live. The next session
that populates delta activates this bug, and it will suppress PE entries specifically.

### CONFIRMED
- 31 distinct (score, confidence) pairs across 89,673 evaluations on the three tick
  sessions. Extends my own earlier one-day check (18 pairs / 30,534 evaluations).
- Acceptance rate 75/89,673 = 0.084%.

## Broker agent

### CONFIRMED — and it collides with the project's strongest finding
2026-09-03: kill-switch "Stale data KILL" fired once a minute from 09:16:01 to 09:25:03;
50 stale-tick rejections that day. First trade of the day: 11:10:14 — nearly two hours
after the open. 2026-09-04 first trade 09:50:10. ZERO trades in 09:15-09:45 on either day.

Why this matters: [[project_ptq_opening_window]] is the project's strongest result
(09:15-09:45 = +Rs114/trade arbitrary vs -Rs34 traded window, p=0.0057) and attributes the
miss to the TIME FILTER. There is a second cause nobody had identified: on 09-03 the option
feed was frozen for the first ~10 minutes of that very window, and the safety net correctly
refused to trade on it. The statistical finding stands (it was computed on the spot series
with arbitrary timing, not on the bot's ability to trade). But ACTING on it needs the feed
to work at the open, which on 09-03 it did not. Opening the time filter alone would not
have captured that day.

### CONFIRMED
- refresh_tokens() defined at brokers/angel_one/client.py:300, called NOWHERE. A mid-session
  token expiry is indistinguishable from a network error and has no path back short of a
  process restart.
- data_source (WEBSOCKET/REST/SIMULATION) is tracked in memory but the ticks table has no
  source column — it is discarded before persistence.
- 18 "Wide spread KILL" events on 2026-09-01 at 0.82-1.08% are artifacts of the REST
  synthetic formula's Rs0.05 floor on a low-premium contract, not real illiquidity.
