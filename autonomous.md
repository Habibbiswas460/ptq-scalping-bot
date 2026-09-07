# Autonomous session — night of 2026-09-08 → morning 2026-09-09

Owner went to sleep and handed over full ownership: fix whatever blocks tomorrow,
audit, research strategy from the web, backtest, optimise, commit (do **not** push).
This file is the report. Read it top to bottom in the morning.

**Status: IN PROGRESS — this file is being appended to as work completes.**

---

## 0. The headline, before anything else

**As of tonight the bot could not have placed a single trade tomorrow.** Not "might
not have" — could not. Verified by running the real `RiskManager` against the real
persisted state, not by reading the code:

```
loaded total_pnl   = -2790.45
loaded peak_equity = 30237.90
current_equity     = 27209.55
check_drawdown     = False | Max drawdown Rs3028 hit (limit: Rs3000)
CAN_TRADE          = False
reasons            = ['Max drawdown Rs3028 hit (limit: Rs3000)']
```

`check_drawdown()` is gate #1 in `can_trade()` and returns early, so every other
filter downstream is irrelevant. This is the P0 that was already flagged in the
2026-09-07 risk audit, and it was still live tonight.

Details, root cause and fix are in section 1.

---

## 1. P0 — the drawdown gate was a one-way latch  ✅ FIXED

### What was wrong

Three separate facts combined into a deadlock that nobody chose:

1. `max_drawdown_amount` was hardcoded `int(TOTAL_CAPITAL * 0.10)` = **Rs3,000** —
   which is *exactly* `MAX_DAILY_LOSS`. So a single day that spends its full
   **permitted** loss budget also trips the **lifetime** ceiling.
2. `peak_equity` is a monotone all-time high. It never decays.
3. `check_drawdown()` is gate **#1** in `can_trade()` and returns early.

So: one bad day, ever. And the only thing that lifts the halt is profit — which the
halt forbids earning. On 2026-09-07 it closed at a drawdown of Rs3,028 against a
Rs3,000 ceiling. The escape was **+Rs28.35 that could never be earned.**

This is not a tuning question. It is a deadlock by construction.

### What I changed

| File | Change |
|---|---|
| `config/constants.py` | `MAX_DRAWDOWN_AMOUNT`, `MAX_DRAWDOWN_PCT`, `DRAWDOWN_PEAK_LOOKBACK_SESSIONS` are now env-configurable instead of hardcoded |
| `core/risk/risk_manager.py` | new `effective_peak_equity()` — peak over the last N end-of-day equities instead of the all-time high (N=0 keeps the old behaviour exactly) |
| `core/risk/risk_manager.py` | a blocked gate now logs the **escape arithmetic** (`needs +RsX to re-open`), which is what tells a protective halt apart from a permanent one |
| `core/risk/risk_manager.py` | startup warning if the lifetime ceiling is not strictly above the daily ceiling |
| `.env` | `MAX_DRAWDOWN_AMOUNT=9000` (three full daily budgets), `MAX_DRAWDOWN_PCT=30.0`, `DRAWDOWN_PEAK_LOOKBACK_SESSIONS=10` |
| `tests/test_drawdown_gate.py` | **new**, 6 tests, pins the exact 2026-09-07 state as a regression anchor |

**I did not reset or wipe any P&L history.** `total_pnl` is still -2790.45 and the
all-time `peak_equity` is still recorded. I considered re-baselining the state file —
the loss was earned by code with four since-fixed structural bugs — and decided
against it: the config fix opens the gate legitimately, and wiping the record while
you sleep is not a call I should make silently. If you *want* a clean baseline, say
so and it is a one-line change.

**The per-day protection is untouched.** `MAX_DAILY_LOSS` Rs3,000 and the kill switch
still bind exactly as before. What I changed is only the multi-day backstop, which
was mis-sized at one day.

### Verified, not assumed

```
BEFORE:  CAN_TRADE = False   ['Max drawdown Rs3028 hit (limit: Rs3000)']
AFTER:   CAN_TRADE = True    []
```

Position sizing then re-checked end to end through the real `PositionSizeEngine`
with the real risk budget, across sl_points 5/7/8/10/12 and three signal grades:
**every combination returns qty=65 (1 lot)**. The entry path can produce orders again.

### A second thing that fell out of that check

Sizing is **completely insensitive to signal quality**:

```
sl=8.0  score=4   conf=70  mq=50  -> qty=65
sl=8.0  score=10  conf=95  mq=90  -> qty=65
```

Same size for the worst admissible signal and a near-perfect one. This confirms the
2026-09-07 audit finding that all seven sizing multipliers are arithmetically inert.
The cause is capital, not code: a Rs30,000 account and a 65-unit NIFTY lot admit
exactly **one** possible position size. No amount of scoring work changes that until
capital changes. Worth knowing before anyone tunes a multiplier again.

## 2. P1 — the live path never charged a single rupee of cost  ✅ FIXED

`research/costs.py` already existed and was already correct. Nothing in the running
bot used it. The live code computed `(exit - entry) x qty` and stopped — no
brokerage, no STT, no exchange transaction charge, no GST, no stamp duty.

Two consequences, and the second is the one that matters:

1. Every P&L number the bot reported was **gross**. Known: Rs63.80/trade on the 143
   recorded trades, turning -Rs1,644 gross into -Rs10,767 net.
2. **Every risk limit measured against that number was also gross.** A "Rs3,000 daily
   loss ceiling" was really letting through about Rs3,800 of actual losses, because
   ~13 trades/day x ~Rs64 of uncounted cost never hit the counter. The kill switch,
   the drawdown gate and the recovery-mode trigger all read the same optimistic number.

### What I changed

Costs are charged at `RiskManager.record_trade()` — the single point every exit path
funnels through (normal SL/TP/RSI exits, kill-switch exits, emergency exits). So
daily / weekly / total P&L, the equity curve, and every gate built on them are now net.

- `config/constants.py` — `COST_ACCOUNTING_ENABLED` (default **on**), `COST_BROKERAGE_PER_ORDER` (default Rs20)
- `core/risk/risk_manager.py` — new `transaction_cost()`; `record_trade()` now records net and keeps `gross_pnl` and `cost` alongside it rather than overwriting
- `core/engines/state_machine.py` — passes entry/exit/qty so the cost is computable
- `tests/test_live_cost_accounting.py` — **new**, 7 tests

Rates come from `research/costs.py`, deliberately: the live path and every offline
experiment now share one definition and cannot drift into disagreeing about what a
trade cost. An unpriced trade (entry/exit/qty missing, as some emergency paths are)
is recorded **gross rather than charged an invented cost** — a test pins that.

Measured on the real engine:

```
gross +Rs130.00 win   ->  net  +Rs59.43     (cost Rs70.57)
gross -Rs455.00 loss  ->  net -Rs524.44     (cost Rs69.44)
```

A round trip on one 65-lot at Rs150 premium costs about **Rs70 — 1.08 option points.**
Against a 60-second mean favourable excursion of 1.06 points, that is the whole game.

### The lever this exposes

`COST_BROKERAGE_PER_ORDER` is now a config knob, and brokerage is the only part of
the Rs70 you can actually negotiate. Rs20 -> Rs5 per order saves `2 x 15 x 1.18` =
**Rs35.40 per round trip, half the total cost**, for no change in strategy, no
added risk, and no code. If you do one thing after reading this file, do that one.

> ⚠ **A warning about tomorrow's numbers.** Tomorrow's session will report *worse*
> P&L than any previous session did, and the daily ceiling will bite sooner. That is
> not a regression — it is the first day the bot has told the truth about its own
> results. Do not compare tomorrow's net figures against the older gross ones.

## 3. P1 — the Telegram Stop button did neither thing it claimed  ✅ FIXED

If you had pressed **Stop** during a trade tomorrow, two things would have happened,
neither of them stopping:

1. Telegram wrote `state.state = "KILL_SWITCH"` directly, from the Telegram thread.
   If the state was `"IN_TRADE"`, that **overwrote it** — and only the `IN_TRADE`
   branch of the main loop ever calls the exit path. The open position was
   **orphaned**: still held, no longer watched, no stop-loss, no take-profit.
2. On the very next loop iteration, main.py's *"kill check passed → recover to IDLE"*
   branch set the state back to `IDLE`, because no **automatic** kill condition held.
   **Trading silently resumed within a second of you stopping it.**

The button answered "⏹ Trading stopped" both times.

Root cause: operator intent and machine state were the same variable, written across
threads.

### What I changed
- `core/engines/state_machine.py` — `TradingState.manual_stop`, the operator's intent, held separately
- `core/services/telegram_bot.py` — Stop/Resume (both the buttons and `/stop`, `/resume`) set the flag and **never assign `state.state`**; a test asserts the string `bot_state.state =` no longer appears anywhere in that file
- `core/main.py` — a manual stop is handled *before* the automatic kill switch: it closes any open position through the same `close_current_trade()` path every other exit uses, then halts; and the recover-to-IDLE branch is now guarded so it cannot undo an operator stop
- `tests/test_manual_stop.py` — **new**, 7 tests

Stop now reports "⏹ Stopping — closing any open position", which is what it does.

**Resume was broken in the mirror image** and is fixed the same way: it used to force
`IDLE`, which would have discarded an open position exactly as Stop did.

## 4. New tool — one command that answers "is it ready?"  ✅ ADDED

```bash
./venv/bin/python -m utils.preflight          # defaults to tomorrow
./venv/bin/python -m utils.preflight 2026-09-09
```

`market_readiness_checker` answers *"is the feed alive and is the strategy warm?"*
It needs a live session, and the failure that actually stopped this bot was invisible
to it anyway: on 2026-09-08 every technical check passed, the broker was connected,
ticks were flowing, and no trade could have been placed. `utils.preflight` covers the
facts that are already decided before the open. It reads no credential, opens no
socket, and a test asserts it does not write to the state file it reads.

**Run it in the morning. This is what it says right now:**

```
PRE-OPEN CHECK for 2026-09-09
========================================================================
  [PASS] 2026-09-09 is a trading day        Wednesday
  [PASS] Contract master                    nearest expiry 2026-09-15 (6 days),
                                            lot 65, tick 0.05, strike step 50
  [PASS] Risk gates open                    no gate blocking
  [PASS] Drawdown gate                      equity Rs27,210 vs peak Rs30,000
  [PASS] Lifetime ceiling > daily ceiling   lifetime Rs9000 vs daily Rs3000
  [PASS] Today's loss budget is fresh       daily_pnl Rs+0.00
  [PASS] Recovery mode                      ACTIVE — sizing reduced
  [PASS] Sizing funds at least one lot      worst case sl=5.0 -> qty=65
  [PASS] Cost accounting on                 round trip on one lot at Rs150 = Rs70.32
========================================================================
READY — nothing blocking
```

Note *Recovery mode: ACTIVE* — that is correct and intended. Total P&L is below the
-8% trigger, so sizing is reduced 50%; the min-lot floor added on 2026-09-07 means
that still funds one lot, so it reduces nothing in practice at this account size.
It clears when total P&L recovers above -3% for two days.

---

## 5. Strategy research — the answer is not the one you wanted

I ran a research agent over current (2025-2026) web sources **and** over this
project's own tick record. Full report: `claude_code/report/strategy_research_20260908.md`
(658 lines, sources with URLs). The short version:

### The verdict

> **There is no configuration in which this bot has positive net expectancy while it
> buys long NIFTY options at Rs30,000.**

Not "unlikely". The arithmetic closes it, and the reason is sharper than anything
this project had established before:

> Cost reduction cannot save a strategy whose **gross** expectancy is already zero.

Measured independently, on **98,434 of your own option ticks**: 2,968 arbitrary-timing
entries, full tick-by-tick TP/SL simulation, 300-second max hold, across **54 (TP, SL)
combinations**. The **best** cell is **−0.0235 gross points (−Rs1.53)** — that is
*before a single rupee of cost*. Zero of 54 cells are net-positive at any cost
structure, **including a hypothetical zero-brokerage broker**.

| TP | SL | resolved in 300s | gross E (pts) | net @ Rs20 | net @ Rs5 |
|---|---|---|---|---|---|
| 3 | 2 | 93.9% | **−0.0235** | −1.0947 | −0.5501 |
| 7 | 5 | 48.2% | −0.2538 | −1.3250 | −0.7804 |
| **14** | **7** *(your declared ladder)* | **21.4%** | −0.2737 | −1.3449 | −0.8003 |

A long NIFTY option held for seconds-to-minutes is a **zero-drift instrument — a fair
coin with a fee stapled to it.** The −Rs10,956 is not a strategy that stopped working.
It is 144 fees.

This independently reproduces the earlier finding "no exit geometry clears its own
break-even" from a completely different direction, and explains *why*: there is no
gross edge for an exit to harvest, so the whole exit surface is capped at roughly zero
before costs are applied at all. Your declared TP14/SL7 resolves only **21.4%** of the
time inside 300 seconds — a 14-point target on a contract whose 300-second mean
favourable excursion is 3.76 points is not a target, it is a timeout.

### The single most interesting thing found

Three cells point the same way:

- top 20% of the 60-second range → **−0.359 points** (worst of 27 cells)
- 60-second momentum > +1.5 points → **−0.261 points** (second worst)
- bottom 20% of the range → **+0.192 points** (the only positive cell)

*On this book, buying strength is the worst-priced entry available and buying weakness
is the best.* **And buying strength is exactly what your entry logic does** — the
scoring stack is EMA-alignment + RSI + volume-spike shaped, a momentum/breakout
detector. If the effect is real, the stack is not merely unable to rank; it is aimed
at the worst cell measured.

Two reasons this is a **hypothesis, not a finding**: the samples overlap (a 30-second
grid over a 300-second horizon shares up to 90% of the path, so the error bands are
too narrow and no block-bootstrap was run), and **even if true it does not clear the
bar** — +0.192 against a 0.884-point requirement is 22% of what is needed. It is a
diagnosis, not a cure.

**I deliberately did not implement it tonight.** One untested entry inversion dropped
onto the same session that is meant to verify three infrastructure fixes would
confound both, and this project has already retracted two findings that were fitted
in-sample on two or three sessions. It belongs in the controlled-experiment loop:
register the hypothesis and the 0.884-point threshold first, change one variable,
score it on a held-out session.

### The one thing worth doing that costs nothing

**73.9% of the Rs63.84 per-trade cost is flat brokerage plus GST on it.** Moving from
Rs20/order to Rs5/order cuts the required entry edge from **1.071 to 0.527 points**,
and the required improvement over arbitrary timing from **+51% to +24%**. No strategy
change, no added risk, no code. It does not make the strategy profitable — nothing
does — but it halves the rate of bleeding. `COST_BROKERAGE_PER_ORDER` is now a config
key, so the model follows the moment you switch.

### Corrections the research turned up

- `research/costs.py`'s docstring says the cost is 1.162 points/trade. The correct
  figure is **0.982**. The rupee figures in it are right.
- The remembered "break-even 67% → 54.8%" for the Rs20→Rs5 change should be
  **70.3% → 59.2%**.
- **`costs.py` does not price the bid/ask spread** — a further **Rs23.27 per round
  trip** at the measured 0.246%. *Important:* the **live** path already pays this
  (it enters at the ask, line 1881, and exits at the bid, line 2141), so it must
  **not** be added there or it double-counts. It is missing from *offline* analyses
  that fill at LTP or mid, and every such figure is optimistic by that amount.
- The SEBI "-114% buyers / +1% sellers" RoCE figures could not be verified against a
  primary source. The direction holds; re-source the numbers before quoting them.

---

## 6. Historical data + backtest — built, run, and it agrees

Full report: `claude_code/report/backtest_data_20260908.md`. Code: `research/backtest/`.
Data: `data/historical/candles.db` (78 MB, gitignored — the code is committed, the
database is not).

The project has never had a historical dataset of its own or a replay that runs the
**actual** entry and exit code. Both now exist.

### Where the data came from

Your instinct about keeping the broker login was right — **Angel One's `getCandleData`
beat every free source**: NIFTY index 1-minute back to **2015**, and **real 1-minute
option premium**, which free sources essentially never provide.

- **Upstox `v3/historical-candle`** — free, **no API key at all**, index 1-min back to
  Jan 2022, serves options too. Kept as an independent cross-check.
- **Yahoo** — works, but ~30 days in 8-day windows, and it appends a fake 15:30 bar.
- **Stooq** — proof-of-work solved, still "Access denied". **Dhan / NSE** — 401 / 403.

### One trap worth knowing about, because it destroys data silently

The SmartAPI historical limit is **not** the documented ~30 days. It is a **row cap of
~8,000 candles**. A 30-day request spanning 22 trading days returns exactly 8,000 rows
and **silently truncates its oldest session to 125 bars** — no error, no flag. That day
then reads as a perfectly legitimate half-session. Four days were corrupted this way
before it was caught; requests are now chunked at 20 days.

(`2025-10-21`'s 72 bars turned out to be the **real Diwali Muhurat session** and were
correctly left alone.)

### What was imported

**155,732 index bars** (417 sessions, 99.59% complete) and **160,311 option bars**
(46 contracts, 13 sessions), with per-row provenance.

The cross-vendor check earned its keep immediately: Upstox and Angel agreed on
**100.0% of 1,805 shared minutes**, and the disagreement it *did* find was an **Angel
archive defect** — 70 missing minutes (15:16–15:29) in every session from 2026-08-03,
which Upstox had. **Invisible without a second vendor.** Recorded as gaps, never filled.

Hard boundary: **expired weeklies are unreachable**, at both vendors, from the identical
listing date. That is exchange-side, not a broker quirk — which is why this is 13 option
sessions and not 400.

### The result

| | value |
|---|---|
| trades | 56 over 12 sessions (2026-08-19 … 2026-09-04) |
| **gross** (spread already inside the fill) | **−Rs4,862**, win rate 33.9% |
| statutory + broker charges | Rs3,883 (Rs69.34/trade) |
| **net** | **−Rs8,745**, win rate 17.9% |
| break-even win rate needed | **75.0% net**, against 33.9% achieved |

**This is a second, independent confirmation.** Different data (Angel 1-min candles vs
your own tick record), different method (engine replay vs arbitrary-timing sampling),
same conclusion. The realised spread came out at **Rs23.04/trade** against the
**Rs23.27** measured independently on tick data — the two studies agree to 1%.

### Two defects the agent found in its own work, and disclosed

1. Without delta enrichment the replay fired **zero signals in 3,900 evaluations** —
   `adaptive_confidence_engine` reads an absent delta into an 18-point penalty branch,
   capping confidence at 63% against a 69% gate. A "no trades" result would have been an
   **artifact, not a finding**. (Live `main.py:784` populates delta, so this is a replay
   harness issue, not a live one.)
2. The intrabar ordering chosen as "conservative" is actually the **flattering** one.
   **−Rs8,745 is an upper bound**; the other ordering gives −Rs10,787.

### What it does not prove

13 sessions on one weekly chain, only 3 of them genuine front-weekly conditions. And the
1-minute grid **systematically under-fires the 45-second early-cut and 75-second
soft-loss exits — which are 33 of the 56 exits here.** So the branches that dominate the
result are exactly the ones this granularity resolves worst. The 417-session index
dataset is infrastructure; no conclusion rests on it.

---

## 7. What I did NOT change, and why

You gave me ownership of the gates, the scoring, the strategy and risk. Here is what I
left alone on purpose — each of these is a live recommendation waiting on your call.

| Not changed | Why |
|---|---|
| **Trade frequency** (`MAX_TRADES_PER_DAY` still 30) | The research's #1 recommendation is ≤2/day, saving ~Rs840/day. But **tomorrow is paper**, and its value is *information*, not P&L. Cutting to 2 trades would protect a number that costs nothing and destroy the data that costs everything. Apply this the day real money goes in — not before. |
| **The entry logic** | The mean-reversion inversion is the one lead worth testing, and I built it (§5) — but **off**. Dropping an untested entry change onto the same session that is meant to verify three infrastructure fixes confounds both, and this project has already retracted two findings fitted in-sample on 2–3 sessions. |
| **Market-quality gate** | Evidence says remove it from the accept decision (MQ≥92 → −Rs66.72 vs MQ≥85 → −Rs48.05 — it selects monotonically *worse* moments). Real, but it is a behaviour change that deserves its own controlled run. |
| **The duplicate confidence floor** | `entry_engine` has a second flat 70/85 floor where the stricter always wins, so the documented MQ-adjusted scheme has never governed anything. Removing it is correct — and it changes how many trades fire, so not tonight. |
| **The risk state** | I did **not** wipe `total_pnl` or `peak_equity`. The config fix opened the gate legitimately; erasing history while you sleep is not my call. |
| **Broker credentials** | Untouched, as instructed. Never printed, never logged, never written to any file. |

---

## 8. Your morning checklist

```bash
cd "/home/lora/projects/PTQ-scalping bot"
./venv/bin/python -m utils.preflight        # expect: READY — nothing blocking
./venv/bin/python -m pytest tests/ -q       # expect: 691 passed, 1 skipped
git log --oneline -7                        # 7 commits, NOT pushed — yours to push
```

Then start the bot as usual. Three things to watch that are new tonight:

1. **`🧾 Costs:` lines in the log.** Every exit should print `gross → cost → net`. If
   they are missing, cost accounting did not engage and the session is reporting gross.
2. **P&L will look worse than any previous session.** Expected. It is the first honest
   set of numbers this bot has produced. Do not compare it to older gross figures.
3. **If you press Stop, it now actually stops** — and closes any open position first.
   Worth testing once deliberately while a trade is open.

### The honest bottom line

Tomorrow's session is worth running, and it is worth running for **data**, not for
profit. Two independent studies — one on your own ticks, one on a fresh 1-minute
dataset from a different vendor, using different methods — agree that **long NIFTY
option buying at Rs30,000 has no positive net expectancy at any exit geometry or cost
structure tested.** Nothing I could have changed in the gates tonight would have altered
that, because the problem is not the gates: there is no gross edge for them to select on.

What tomorrow *can* tell you is whether the three fixes hold under a live session, and
it will give you the first day of P&L this project has recorded that is actually true.

**If you do one thing this week, move the flat brokerage from Rs20 to Rs5.** It is 74%
of your cost, it needs no code, and it halves the rate of bleeding while you decide what
to do about the rest.
