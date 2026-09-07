# Historical 1-minute data, and a replay of the real engines over it

**Date:** 2026-09-08
**Scope:** source free/credentialed 1-minute NIFTY history, import it with provenance,
build and run a backtest of this bot's actual entry and exit code against it.
**Code:** `research/backtest/` · **Data:** `data/historical/candles.db` · **Tests:** `tests/test_backtest_*.py`

---

## 1. The headline

The replay is **negative at every setting tested**, and it agrees with the
independent tick-level study run in parallel.

| | value |
|---|---|
| trades | 56 over 12 sessions (2026-08-19 … 2026-09-04) |
| **GROSS** (spread already paid in the fill) | **−₹4,862.12**, expectancy −₹86.82, win rate 33.9% |
| of which spread crossed | ₹1,290.37 (mean ₹23.04/trade) |
| statutory + broker charges | ₹3,883.25 (mean ₹69.34/trade = 1.067 pts/lot) |
| **NET** | **−₹8,745.37**, expectancy −₹156.17, win rate 17.9% |
| break-even win rate needed | 56.7% gross → **75.0% net**, against 33.9% achieved |

This is not a marginal loss that better parameters would close. The strategy needs
a 75% net win rate and delivers 34%.

**Reconciliation with the parallel study.** A separate agent sampled 2,968
arbitrary-timing entries over 98,434 of this project's own option ticks across 54
(TP, SL) cells and found the best cell at −0.0235 gross points, with zero cells
net-positive. This work reaches the same conclusion from **different data** (Angel
One 1-minute candles, a different period) by a **different method** (replaying the
real signal and the real exit ladder rather than arbitrary timing). Two
independent routes to the same sign is the most useful thing in this report.

---

## 2. What sources actually work

Everything below was **probed, not read off a documentation page**. Constants are
frozen in `tests/test_backtest_sources.py` so a later edit that loosens one has to
be deliberate.

### Angel One SmartAPI `getCandleData` — PRIMARY ✅

| | |
|---|---|
| auth | this repo's existing credentials (names only: `ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET`) |
| index 1-min depth | **2015-01 returns a full month; 2012-01 returns zero.** Deeper than any free source |
| option 1-min | **yes — real option premium**, which free sources essentially never provide |
| bars/session | 375, 09:15–15:29 IST |

**⚠ The documented limit is wrong, and the way it is wrong destroys data silently.**
The cap is a **row count of about 8,000 candles**, not "~30 days". A 30-day chunk
that happens to hold 22 trading days returns exactly 8,000 rows and **truncates its
oldest session to 125 bars** — with no error, no flag, and a day that then looks
exactly like a legitimate half-session.

I hit this on the first import pass. Four sessions (2025-01-01, 2025-06-30,
2026-01-27 and one more) came back at 125/375 bars. Refetched individually, each
returns its full 375. `MAX_WINDOW_DAYS` is now **20 calendar days** (≤15 trading
days ≤5,625 rows) and the re-import produced `clamped=0`.

A genuinely short session does exist and must **not** be "repaired": **2025-10-21
returns 72 bars, 11:17–14:46**, whether fetched alone or in a chunk. That is the
Diwali Muhurat session, and it is real.

Rate limit: the published ~3 rps is not the only limit. 0.45s pacing (~2.2 rps)
still earned `Access denied because of exceeding access rate` on a burst of small
requests. Pacing is now 1.0s with backoff on that specific message only; a bad
token is not retried, because it would fail identically forever and just spend the
budget.

### Upstox `v3/historical-candle` — free, no key, genuinely good ✅

The best free source found, and better than expected:

- **No API key, no OAuth, no account.** Public endpoint.
- NIFTY index 1-minute back to **January 2022** (2021 and 2019 return zero).
- 30-day window cap (31+ → HTTP 400, a real error, not a silent clamp).
- **It serves NIFTY options too**, on `NSE_FO|<token>` keys from a public gzipped
  instrument master — free 1-minute option premium.
- Rate limit: ~10 rapid requests → HTTP 403 for several minutes. 6s pacing survives.

Used here as the **cross-check**, not the feed, because Angel goes deeper. That
role turned out to be worth more than its depth would have been — see §3.

### Everything else ❌

| source | result |
|---|---|
| **Yahoo** `query2/v8/chart/^NSEI` | works, but 1-min only ~30 days back and **8 days per request**. `query1` returned HTTP 429 from this host on every attempt. Appends **one trailing quote bar at 15:30** which is not a traded minute — keeping it puts a duplicate close in the series (`_strip_yahoo_artifact`). Rate-limited us out during the final cross-check run. |
| **Stooq** | solved its SHA-256 proof-of-work challenge and still got `Access denied` on `/q/d/l/`. Unusable. Recorded so nobody spends the hour again. |
| **Dhan** `/v2/charts/intraday` | HTTP 401 `DH-901`. Needs a client id and access token. |
| **NSE** `www.nseindia.com` | HTTP 403 to any non-browser client. |
| **Alpha Vantage / Twelve Data** | require a key; neither lists NIFTY 50 index intraday on the free tier. Not pursued once Upstox proved deeper than both. |

### ⛔ The hard boundary: expired option contracts are unreachable

This is the finding that caps the whole exercise, and it is not a broker quirk.

- The ScripMaster holds **only unexpired contracts**, so an expired weekly's token
  cannot be looked up at all.
- Blind token probes (30000, 33000, 35000, 36000, 38000, 40000, 41000) over a
  July 2026 window returned **zero rows** on every one.
- A listed contract returns data only from its **listing date**: the 2026-09-08
  weekly ATM CE returns 2026-08-19…2026-09-04 and exactly zero rows before that.
- **Upstox hits the identical boundary at the identical listing date.** Two
  unrelated vendors agreeing is corroboration, not coincidence: this is an
  exchange-side archive boundary.

**There is no route, free or credentialed, to a NIFTY weekly option that has
already expired.** Option backtesting is capped at currently-listed chains, which
is why this study covers 13 sessions and not 400.

---

## 3. What was imported

`data/historical/candles.db` — 78 MB, **already gitignored** by the global `*.db`
rule at `.gitignore:66`. No `.gitignore` edit needed.

| dataset | rows | instruments | sessions | range |
|---|---|---|---|---|
| NIFTY 50 index 1-min (Angel) | 155,732 | 1 | 417 | 2025-01-01 … 2026-09-04 |
| NIFTY 08SEP26 chain 1-min (Angel) | 160,311 | 46 (23 CE + 23 PE, 23550–24650) | 13 | 2026-08-19 … 2026-09-04 |
| NIFTY 50 index 1-min (Upstox, cross-check) | 1,875 | 1 | 5 | 2026-08-31 … 2026-09-04 |

Index completeness: **99.59%** of a full 375-bar grid.

### The cross-check earned its keep

Upstox vs Angel over 5 overlapping sessions:

```
broker(angelone): 1805 bars
upstox:           1875 bars, 1805 shared minutes
                  identical close 100.0% | max |diff| 0.00 | mean |diff| 0.0000
```

Two unrelated vendors, **100.0% identical closes to the paisa**. That is strong
evidence the broker feed is undistorted.

It also caught something a single vendor never would: **Upstox returned 1,875 bars
where Angel returned 1,805 — exactly 70 more, 14 per session.** Every Angel session
from 2026-08-03 onward is missing ~13 minutes in the 15:16–15:29 window. Upstox has
those minutes. **This is an Angel archive defect, not a market closure**, and it
would have been invisible without an independent source. Those minutes are recorded
as gaps, not filled.

### Provenance and the no-fabrication rule

Following `research/provenance.py` and `research/visual/schema.py`:

- **`fetch_runs`** — one receipt per request: what was asked, what came back
  (`returned_from`/`returned_to` separately from `requested_from`/`requested_to`),
  row count, error, timestamp, clamp flag. 99 requests recorded.
- **`candles`** — `source` is part of the primary key, so two vendors' views of the
  same minute coexist as two rows and can be compared instead of one silently
  overwriting the other.
- **`gaps`** — every absent session minute is written, never interpolated:
  - INDEX: 26 instrument-sessions, **643 minutes absent** (the Muhurat session plus
    the Angel close-window defect).
  - OPTION: 371 instrument-sessions, 56,064 minutes absent. For an option this
    means **"no trade printed in that minute"**, which is real information about
    liquidity, not a hole to be patched. The harness treats such a minute as the
    contract being untradeable at that instant.
- **`meta.provenance`** declares `oi`, `bid`, `ask`, `spread` as **MISSING** — no
  historical book exists at any granularity from any source reached. A test fails
  if that declaration goes stale.

**Provenance wrinkle, disclosed:** 8 `clamped=1` receipts survive from the first,
defective 30-day pass (timestamps 21:08). They were written under an earlier, naive
flag definition (`returned_from > requested_from`), which also fires whenever a
window merely opens on a weekend. Under the current row-count definition only one
of those eight (the 8,000-row chunk of 2026-01-26) is a true clamp. The rows are
kept rather than rewritten, because a receipt is a record of what happened.

---

## 4. What the backtest measured

`research/backtest/harness.py` **imports and drives the shipping code**. It does not
re-implement it:

- `strategies.smart_scalp_v3.smart_scalp_signal` — the real scoring stack, real
  confidence gate.
- `core.engines.exit_engine.check_exit_conditions` — the real ladder in the real
  priority order (hard SL, step trailing, early loss cut, soft-loss timeout, greeks
  kill, RSI exits, time exit), driven through the `_clock_override` hook the exit
  engine already provides for exactly this.
- Indicators are fed as **real 5-minute candles** via
  `runtime_state.set_historical_candles`, which is the same canonical path the live
  system prefers — so EMA/RSI/VWAP periods match live rather than being a
  1-minute approximation.

### Spread is charged exactly once, and it is charged in the fill

Verified in `core/trading/broker.py`: line 1881 fills a BUY at `tick['ask']`, line
2141 exits at `tick['bid']`. The live bot crosses the book on both legs, so its
gross P&L already pays the full spread; `research/costs.py` correctly covers only
statutory and broker charges.

**This replay does the same**: entry fills at `bar + half_spread`, exit at
`bar - half_spread`, so the spread sits inside `Trade.gross_pnl` and
`costs.round_trip()` is added on top **without overlapping it**. Had fills been
taken at the bar price (which is the natural thing to do with candles, since a
candle has no book), the spread would have been paid nowhere and the result would
be optimistic by roughly ₹23/trade.

The width is **measured on this project's own tick data**, not assumed: **0.246% of
premium round trip, ≈₹23.27 per 65-lot round trip**. It is applied proportionally
to the premium, not as a fixed point count. My first pass used a flat 0.125
pts/side — worth only ~₹16.25 a round trip, optimistic by about a third. The
corrected model produces a realised mean of **₹23.04/trade**, within 1% of the
independently measured figure.

### Look-ahead control

A signal is computed from bars up to and including the **close of minute t**; the
entry fills at the **open of minute t+1**. No bar at or after the fill contributes
to the decision to take it. The strike is chosen from the spot at t. Strategy state
and the tick buffer are reset per session, so yesterday's close cannot shape today's
EMA across the overnight gap.

---

## 5. Two defects found in the replay itself (both fixed, both disclosed)

**A. The replay was not the live system until greeks were enriched.**
`adaptive_confidence_engine` reads delta as
`indicators.get('Delta', 0) or latest_tick.get('delta', 0)`. With delta absent it
lands in the `else 10` branch of
`greeks_score = 100 if 0.35 <= abs_delta <= 0.65 else 50 if ... else 10`, which
carries 0.20 of the confidence total — **an 18-point penalty against a 69% gate**.
Measured: with delta absent, the best confidence reached across a full session was
**63%**, and the stack fired **zero signals in 3,900 evaluations**. Live,
`core/main.py:784` writes delta onto every tick (`TICK_DELTA_ENABLED` is on). The
harness now mirrors that path with the same solver and the contract's real expiry.
Without this correction the backtest would have reported "no trades" and that would
have been an artifact, not a finding.

**B. "Conservative" intrabar ordering is actually the flattering one.**
I assumed adverse-first (open→low→high→close) was cautious. Measured, it is not:

| ordering | net |
|---|---|
| low before high (default) | **−₹8,745.37** over 56 trades |
| high before low ("optimistic") | **−₹10,786.59** over 58 trades |

Stopping out early is *worth* something to this ladder, because the alternative is
arming a trailing stop that then gives the move back. **So the headline number uses
the flattering assumption and the true result is at least as bad.** The ₹2,041
between the two orderings (~₹36/trade) is the size of an assumption that 1-minute
bars cannot resolve.

Note also that `half_spread = 0` is **not** a valid "perfect fills" upper bound:
`market_quality_engine._spread_pct` requires `ask > bid` and returns 99.0
otherwise, so a zero spread hard-rejects every evaluation and produces no trades.

---

## 6. Results

### Exits by branch

| n | gross | branch |
|---|---|---|
| 23 | −₹4,415.69 | ⏳ SOFT LOSS EXIT |
| 19 | +₹2,443.48 | ✅ TRAILING PROFIT |
| 10 | −₹2,836.56 | ⚡ EARLY LOSS CUT |
| 2 | +₹487.36 | ⏰ TIME EXIT (winning) |
| 1 | −₹22.71 | ⏰ MARKET CLOSE EXIT |
| 1 | −₹518.00 | 🛑 HARD SL HIT |

The declared TP/SL geometry governs **1 of 56 exits**. This is consistent with the
existing project finding that declared SL/TP never governed an exit (0/34).

### Sensitivity — every variant is negative

| variant | gross | net |
|---|---|---|
| default (0.246% spread, low-before-high) | −₹4,862.12 | **−₹8,745.37** |
| optimistic intrabar (high before low) | −₹6,779.32 | **−₹10,786.59** |
| fixed 0.125 pts/side (the too-narrow first model) | −₹4,546.75 | −₹8,563.57 |
| fixed 0.25 pts/side | −₹5,317.00 | −₹9,200.00 |

### Concentration check (not out-of-sample)

| half | trades | gross | net |
|---|---|---|---|
| 2026-08-19…08-26 | 18 | +₹593.19 | −₹712.52 |
| 2026-08-27…09-04 | 38 | −₹5,455.31 | −₹8,032.85 |

The first half is **gross-positive and net-negative** — costs alone flip it. The
second half is negative outright. Nothing was fitted on either half, so this is a
concentration check, **not** a walk-forward validation.

### Independent corroboration of known project numbers

| quantity | this study | previously recorded |
|---|---|---|
| statutory cost per round trip | **₹69.34 = 1.067 pts/lot** (mean premium ~₹145) | ₹63.80 = 0.982 pts/lot |
| net break-even win rate | 75.0% | 70.3% |
| spread per round trip | ₹23.04 | ₹23.27 (independently measured) |

The cost figure is premium-dependent and must be quoted with its premium —
`research/costs.py` was corrected during this same session for exactly that reason
(the old "1.162 pts/lot" was `points()` at a ₹183.83 premium, not the figure that
pairs with a ₹63.80 mean). At this study's premiums the two agree: ₹69.34/65 =
1.067.

---

## 7. What this does **NOT** prove

Read this section before quoting anything above.

1. **13 sessions is a small sample, and it is one weekly chain.** 56 trades on the
   2026-09-08 expiry. This is not a regime study, a seasonality study, or evidence
   about any other expiry. The confidence interval on a 34% win rate at n=56 is
   wide.

2. **The 1-minute grid systematically under-fires the two most common exits.** The
   early loss cut fires within 45s of entry and the soft-loss timeout at 75s. On a
   1-minute grid there are at most a couple of decision points inside those
   windows. Those two branches account for **33 of 56 exits here**, so the exits
   that dominate the result are exactly the ones the granularity resolves worst.
   Only tick data fixes this. **This is the single largest fidelity gap.**

3. **The signal evaluation rate is wrong by orders of magnitude.** Live, the
   strategy sees tens of thousands of sub-second ticks per session; here it sees
   375. Indicator *periods* match live (real 5-minute candles), but the number of
   chances to fire does not. Whether that biases the result up or down is
   **unknown and untested**.

4. **Most sessions were not front-weekly conditions.** For 2026-08-19…09-01 the
   true front weekly had already expired and is unreachable, so the 2026-09-08
   contract was traded at 7–14 DTE where live trades the nearest weekly. **Only
   2026-09-02…09-04 are genuine front-weekly conditions.** Gamma and theta differ
   materially across that range.

5. **Open interest was absent throughout**, so `oi_score` sat at its NEUTRAL 50 on
   every evaluation. Live before 2026-09-07 it was also never populated, so the
   replay matches the *historical* live condition — but it does **not** describe
   the bot as configured today, now that real OI is flowing.

6. **The freshness component is a replay artifact.** `_freshness_score` compares
   the tick timestamp to `datetime.now()`; replaying 2026-08 data scores 50 where
   live would score 100. That is 10% of the execution-quality sub-score, biasing
   the replay's confidence **downward**. There is no hook to inject a reference
   time, so it is disclosed rather than corrected. It means the replay fires
   *fewer* signals than live would, not more.

7. **The 0.246% spread was measured on a different (later) period** than the 13
   sessions replayed. It is the best figure available and it is measured rather
   than assumed, but it is transported.

8. **Intrabar ordering is unresolvable** and, as §5B shows, the default is the
   flattering choice. Treat −₹8,745 as an upper bound on performance, not a point
   estimate.

9. **No survivorship claim is made either way.** All 46 contracts in the ±250 band
   were imported and the ATM was selected by spot at signal time, so no contract
   was selected on outcome. But every contract available *is* one that had not
   expired at import time — that is the archive boundary of §2, not a choice.

10. **The 417-session index dataset is infrastructure, not evidence.** Only 12 of
    those sessions fed a trade, because option data bounds the replay. The other
    405 sessions are imported, cross-checked and available — no conclusion in this
    report rests on them.

11. **This measures the bot as currently configured.** `config/constants.py` was
    being edited concurrently by another agent during this session. The replay
    reads live config at import time, so a constants change moves these numbers.

---

## 8. What I ran, and what I did not touch

**Created (all new files):**
```
research/backtest/__init__.py        research/backtest/store.py
research/backtest/sources.py         research/backtest/fetch.py
research/backtest/broker_source.py   research/backtest/harness.py
research/backtest/run.py
tests/test_backtest_store.py         tests/test_backtest_harness.py
tests/test_backtest_sources.py
claude_code/report/backtest_data_20260908.md
data/historical/candles.db           (gitignored)
```

**Not touched:** nothing under `core/`, `strategies/`, `config/`, `brokers/`,
`utils/`, or `.env`. No file in those trees was edited. No `.gitignore` edit
(`*.db` already covers the database). No commit, push, or git state change. No
order API called — `getCandleData` only. No `logout()`/`terminateSession()` call,
per the isolation contract in `utils/run_historical_collector.py`.

**Packages installed:** none. No `pandas`, `numpy` or `yfinance` — everything uses
the stdlib plus the already-present `smartapi-python` and `pyotp`.

**Credentials:** read from `config.constants`, held in local variables, never
printed, logged or written to any file. `credential_status()` returns booleans
only and a test asserts it cannot return anything else.

**Reproduce:**
```bash
./venv/bin/python -m research.backtest.fetch index --from 2025-01-01 --to 2026-09-04
./venv/bin/python -m research.backtest.fetch options --expiry 08SEP26 --band 250 \
    --from 2026-08-19 --to 2026-09-04
./venv/bin/python -m research.backtest.fetch crosscheck --days 5
./venv/bin/python -m research.backtest.run --expiry 2026-09-08 --split
./venv/bin/python -m research.backtest.run --expiry 2026-09-08 --optimistic
./venv/bin/python -m research.backtest.fetch status
```

---

## 9. For the owner — no config change requested

I did not need any `.env` key added or changed. `TICK_DELTA_ENABLED=True` and
`TICK_OI_ENABLED=True` were already set and the replay mirrors them.

One observation worth a decision, since it is in code you own:
`core/engines/adaptive_confidence_engine.py:65` takes `abs(delta)`, which the
in-file comment already flags as unfixed relative to
`weighted_score_engine.py:73`. That comment is correct that it matters — the branch
carries an 18-point swing against a 69% gate. It is **not** a bug I hit (taking
`abs` is what let PE entries score at all here), but the asymmetry between the two
engines is real and is now measured: without delta the stack cannot exceed 63%
confidence and fires zero signals in 3,900 evaluations.
