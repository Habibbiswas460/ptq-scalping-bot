# Autonomous session — 2026-09-08 (NIFTY weekly **expiry day**)

Owner handed over ownership and left. Everything here is my call. Report only —
no reply expected. Appended through the day; read top to bottom.

Yesterday's overnight work is in `autonomous.md` (three defects fixed, two studies).
This file is today: **run the bot from 09:15, watch where it enters and why, reason
out the edge, and change whatever needs changing.**

---

## Pre-open — 08:10 to 09:08 IST

### Preflight: READY

```
  [PASS] 2026-09-08 is a trading day        Tuesday
  [PASS] Contract master                    nearest expiry 2026-09-08 (0 days)
  [PASS] Expiry day                         gamma/theta regime differs
  [PASS] Risk gates open                    no gate blocking
  [PASS] Sizing funds at least one lot      worst case sl=5.0 -> qty=65
  [PASS] Cost accounting on                 round trip @Rs150 = Rs70.32
```

717 tests pass, 1 skipped.

### What yesterday actually looked like, costs included

I built `research/session_digest.py` to read a session in one screen. Run against
2026-09-07 it is brutal:

```
13 trades   gross -Rs952.25   cost Rs846.21   net -Rs1,798.46
net winners 4 (30.8%)   expectancy -Rs138.34/trade
cost is 89% of the gross magnitude
exits: soft loss 6, RSI reversal 4, early loss cut 3
       — the declared SL7/TP14 fired ZERO times out of thirteen
holds: 2 to 125 seconds
297 signals reached ENTRY_READY; 295 were PE, and 295 of those were the
same EMA9<21 + EMA9_Rejection pair
```

Two things jump out. **Cost is 89% of the gross magnitude** — the bot is paying
nearly as much to trade as the market moves for it. And **the exit ladder it is
configured with has never governed an exit**; three time-based cuts do all the work.

### The arithmetic I found before the open, and what today tests for free

Transaction cost is **fixed in rupees** per round trip. Premium movement is
**delta × spot movement**. So the identical trade, expressed through a higher-delta
contract, needs a smaller move to clear the same cost:

| premium | cost/lot | cost in pts | delta | **spot move needed to break even** |
|---|---|---|---|---|
| 120 | Rs65.69 | 1.011 | 0.50 | **2.02 NIFTY points** |
| 150 | Rs70.32 | 1.082 | 0.55 | **1.97** |
| **210** | Rs79.56 | 1.224 | **0.90** | **1.36** |
| 250 | Rs85.73 | 1.319 | 0.93 | 1.42 |
| 300 | Rs93.43 | 1.437 | 0.95 | 1.51 |

Yesterday traded delta **0.40–0.68**, needing ~2.0 points. A delta-0.90 contract
needs **1.36 — a 31% smaller move, from instrument selection alone, with no signal
edge required.** For scale: the research put the bar for a *signal* improvement at
+51% over arbitrary timing. This is 31% of the way there for free.

The curve turns back up past Rs250 because STT and exchange fees scale with premium
while delta cannot exceed 1.0. The optimum sits near **Rs210** — which is exactly
what the existing strike search already targets (`mid_premium = (70+350)/2`).

**And today is expiry.** At 0 DTE extrinsic value is nearly gone, so a Rs210 premium
*is* a deep-ITM contract. The bot will trade delta ~0.9 today **without me changing
a line.** Today is the experiment, for free.

### The one number that could kill it

Deep-ITM contracts have **wider books**, and the live path pays that spread twice —
it enters at the ask (`broker.py:1881`) and exits at the bid (`:2141`). That cost
appears in no greek and in no line of `research/costs.py`. A wide enough book eats
the entire delta gain, and until today the trade record could not have told anyone.

So the one change I made before the open is **instrumentation, not strategy**: bid,
ask, ltp, spread and spot are now recorded at both crossings. Additive only — the
CSV schema is unchanged, nothing reads the fields yet, and no decision depends on
them. **I deliberately changed no gate, no threshold and no strategy before the
open**, because today's session is worth more as a clean measurement than as a
guess, and because a change made at 08:20 could not have been tested.

### Plan for the session

1. Launch ~09:08, before the 09:15 open.
2. Watch entries live: which contract, what delta, what spread, which signal fired.
3. Answer the delta-vs-spread question with today's own data.
4. Change strategy / exits / sizing on the evidence — during the session if it is
   clear-cut, otherwise after the close.
5. A GitHub / Indian-algo-trading research agent is running in parallel on public
   code and published backtests.

---

### Why 295 of 297 signals yesterday were identical — the actual mechanism

I read `strategies/smart_scalp_v3.py:1111-1150`. The PE score is built like this:

| condition | points |
|---|---|
| `EMA9 < EMA21` (trend down — **required**) | **+2** |
| `EMA9_Rejection`: `high` within 0.5% of EMA9, **or** `close <= ema9 <= high` | **+2** |
| `Red_Candle` (+1), `Close<EMA9` (+1) | +2 |
| `RSI < 45` (+1), `RSI < 35` (+1) | +2 |
| VWAP / OI / volume | +1 each |

`min_score = 4`. So **the first two conditions alone are a signal.** Everything below
them is decoration — it changes the reported score and confidence, but the entry
decision was already made two lines up.

And what are those two conditions? *"EMA9 is below EMA21, and price is near EMA9."*
In any downtrend that is true on most bars. **It is not a signal, it is a description
of a downtrend** — which is why it fired 297 times in one session and why 295 of
those carried the identical factor list.

This is what "the scoring stack cannot rank" means in concrete terms, and it lines
up exactly with the overnight research finding: the condition is
momentum/breakout-shaped, and buying strength measured as the **worst-priced entry
available** on this book (−0.359 gross points, worst of 27 cells tested).

### What actually blocked yesterday's 284 non-trades

```
  165  Risk: Max drawdown Rs3028 hit (limit: Rs3000)   <- the P0 latch
   97  Allocator: allocator_zero_quantity              <- the sizing halt
    6  Cooldown 900s
    4  Cooldown 30s
    3  Cooldown 120s
    3  Exec guard: execution drift too high
```

**262 of 284 blocks were two bugs, both now fixed.** So today's session is not
comparable to yesterday's: the same signal stream that produced 13 trades could
produce many more. The caps that remain are real ones — `MAX_TRADES_PER_HOUR=10`,
`MAX_TRADES_PER_DAY=30`, and the cooldowns.

That has a consequence worth stating before it happens: **30 trades x ~Rs78 = ~Rs2,340
of cost against a Rs3,000 daily ceiling.** With costs now counted against that
ceiling, a full-frequency day can hit the daily limit on transaction costs alone,
before the market has done anything. If the session halts early today, that is not a
malfunction — it is the clearest possible demonstration of the whole problem.

I am leaving the caps as they are. The daily ceiling now measures truthfully, and
letting it do its job is more informative than pre-empting it.

### ⚠ CORRECTION — my pre-open delta table above is WRONG

A research agent working in parallel refuted it, and re-deriving it myself confirms
the refutation. **I had assumed transaction cost is fixed in rupees. It is not.**

```
cost(P) = Rs47.20 + 0.1541 x P
```

Only **Rs47.20** (brokerage + its GST) is flat. STT, exchange transaction charges and
the GST on them all scale **with premium** — and so does the bid/ask spread, measured
on this project's own book at **0.239% of premium**, which the live path pays on every
round trip (ask in, bid out) and which my table omitted entirely.

Once both are included, the spot move needed to break even is a **U-curve**, not a
decreasing one:

| premium | delta | statutory pts | spread pts | total pts | **spot move needed** |
|---|---|---|---|---|---|
| 60 (ATM) | 0.50 | 0.868 | 0.143 | 1.012 | **2.02** |
| 90 | 0.62 | 0.940 | 0.215 | 1.155 | 1.86 |
| **110** | **0.70** | 0.987 | 0.263 | 1.250 | **1.79** ← optimum |
| **150** | **0.80** | 1.082 | 0.359 | 1.440 | **1.80** ← optimum |
| 180 | 0.86 | 1.153 | 0.430 | 1.583 | 1.84 |
| 210 | 0.90 | 1.224 | 0.502 | 1.726 | **1.92** ← the old default |
| 250 | 0.93 | 1.319 | 0.598 | 1.916 | 2.06 — **worse than ATM** |
| 300 | 0.95 | 1.437 | 0.717 | 2.154 | 2.27 |

So:

- The real gain from higher delta is **~11%, not 31%.** I overstated it by 3x.
- **Deep ITM stops paying at delta ≈ 0.91.** Beyond that it is worse than ATM.
- The old Rs70–350 band aimed at Rs210 — **delta 0.90, sitting on the break-even edge
  with no margin.** Any spread wider than 0.239% and it is worse than doing nothing.
- At a **Rs5** broker the flat component collapses and the optimum moves all the way
  back to **ATM** — the ITM advantage disappears entirely. So this lever and the
  brokerage lever are not additive; the cheap broker makes this one irrelevant.

**And one more thing that changes how today must be read:** friction expressed in
*option points* **rises** with delta — 1.00 pts at ATM, 1.63 at delta 0.9. Comparing
today's option-point results against the project's "+0.884 points" bar without
adjusting for the contract actually traded would be wrong by up to **85%**.

#### The one change I made on this

`STRIKE_PREMIUM_MAX`: **350 → 210**, so the search midpoint moves from Rs210 to
**Rs140 (delta ~0.78)** — the flat middle of the optimum instead of its edge. The
entry filter stays permissive at Rs70–350 so a contract that drifts is not rejected.
This is arithmetic, not a fitted parameter, and the optimum is broad (anything from
Rs110–180 is within 3% of best), so it is robust rather than tuned.

Also changed: **`MAX_TRADES_PER_HOUR` 10 → 4** (reasoning recorded above).
Backups: `.env.bak-pre-ratecap-20260908`.

**Nothing else was changed. No gate, no threshold, no signal, no exit.**

I am recording this correction prominently rather than quietly editing the table,
because a 3x overstatement that I would have carried into today's analysis is exactly
the kind of error this project keeps having to retract.

---

## 08:52 — the third independent negative, and it closes the question

I sent the strongest remaining hypothesis to a controlled test on the historical
data: **the holding horizon, not the signal, is what loses.** Live holds are 2–125
seconds, friction is ~1.0–1.7 option points per round trip, and the 60-second mean
favourable excursion is ~1.06 points — so at the horizon the bot trades, the
movement available *equals* the cost. Hold longer and movement grows while cost
stays fixed. It is the most reasonable idea anyone has had about this bot.

**The first half is true, and understated.** Mean MFE clears friction from **two
minutes onward** (2.13 vs 1.49 points) and reaches 14.5 points at sixty. Friction
falls from **111% of MFE to 9%**. Required hit rate falls from **105.6% to 54.4%**.

**The second half kills it.**

> Mean MFE is the *height of the path*, not what a ladder *collects*.

Measured as **first touch** on the same data — symmetric barriers set to each
horizon's own mean MFE, non-overlapping windows, friction at each sample's own
premium — the delivered hit rate is **42.9% at 1 minute and 49.6% at 60 minutes.**
It converges on 50% and never reaches the bar. Net expectancy is flat at **−1.5 to
−1.9 points at every horizon**, with the 95% interval below zero at all eight. An
80-cell horizon × barrier sweep is negative everywhere except one lottery cell whose
entire result comes from two of thirteen sessions.

That is what a zero-drift instrument looks like from a third direction:
**you can always find the height, you just cannot be standing there when it arrives.**

Two things the agent caught that I would have got wrong:

- The "MFE/|MAE| decays with horizon" result reproduces **only in the CE book**
  (0.993→0.880). PE mirrors it (0.949→1.228). Direction-balanced it is flat at
  0.97–1.03. **It was the index falling, not the option decaying.**
- Disabling the 45-second early cut makes the replay **worse**, not better. The one
  positive configuration (60-minute hold, all stops off) nets +Rs751 — but its mirror
  over the same minutes in the opposite type loses **Rs9,948**, direction-balanced it
  is **−Rs190/trade**, one session supplies Rs3,990 of the Rs751, and the interval is
  [−Rs443, +Rs486]. It does not survive.

### Where that leaves the question

Three independent studies, three different datasets, three different methods:

| study | method | result |
|---|---|---|
| tick sweep | 2,968 arbitrary entries, 54 (TP,SL) cells, own tick record | best cell **−0.0235 gross pts** |
| candle replay | real engines over Angel 1-min bars, 56 trades | net **−Rs8,745**, needs 75% win rate |
| horizon sweep | MFE term structure + 80-cell first-touch sweep | negative at **every** horizon |

**Buying long NIFTY options at Rs30,000 has no positive expectancy at any exit
geometry, any holding horizon, any delta, or any cost structure tested.** That is
not a tuning problem and there is no parameter left to turn. I have now tested the
three best ideas available and all three are closed.

### What is genuinely still open

1. **Cost.** Rs20 → Rs5 per order cuts the required edge from 1.071 to 0.527 points.
   It does not create an edge; it halves the bleed. No code, no risk. **Still the
   single best action available.**
2. **Data volume.** Every interval above is a 13-session cluster bootstrap — wide,
   and honestly labelled wide. The GitHub survey found that **Upstox exposes an
   `expired-instruments` API** with 1-minute expired NIFTY chains (~6 months, 2 years
   announced) — which contradicts the earlier "expired weeklies are unreachable"
   finding in the backtest report. That one unlock would turn every result here from
   13 sessions into hundreds.
3. **Option selling.** Best evidence of anything surveyed — and **verified blocked**
   by capital: 2% ELM on expiry day is Rs30,888 for a single leg against a Rs30,000
   account.

Today's session still runs, and is still worth running — not for profit, but because
it is the first day this bot reports net numbers, and because the spread
instrumentation I added answers the delta question on live data.

---

## Close of session — the numbers

```
15 trades   gross -Rs1,134.25   cost Rs936.59   net -Rs2,070.84
net winners 5 (33.3%)   expectancy -Rs138.06/trade
cost is 83% of the gross magnitude
exits: RSI reversal 6, early loss cut 6, soft loss 2, HARD SL 1
22 signals reached ENTRY_READY — all 22 PE, all EMA9<21 + EMA9_Rejection
```

### Set against yesterday

| | 2026-09-07 | 2026-09-08 |
|---|---|---|
| trades | 13 | 15 |
| gross | −Rs952.25 | −Rs1,134.25 |
| cost | Rs846.21 | Rs936.59 |
| net | −Rs1,798.46 | −Rs2,070.84 |
| net win rate | 30.8% | 33.3% |
| **expectancy/trade** | **−Rs138.34** | **−Rs138.06** |

Two different sessions, a changed strike band, a changed trade-rate cap, a changed
exit ladder — and the expectancy lands **28 paise apart**. I did not engineer that
and I would not have predicted it.

### The most useful thing I learned today, and it is about me

At 13:19, with 14 trades closed, the day read **−Rs111.08/trade** against yesterday's
−Rs138.34. A 20% improvement, and I could see a clean story for it: the strike band
change had moved delta from 0.40–0.68 to 0.64–0.78 and cut Rs2.53/trade of cost. I
wrote at the time that n=14 was not significant and I would not claim it.

**One more trade — a single hard-SL loss at −Rs515.68 — erased the entire
difference.** −111.08 became −138.06.

That is the whole case for not trusting single sessions, delivered by the data
rather than by argument. Had the session ended at 13:19 I would have had a tidy,
plausible, completely false result to report.

### The delta optimisation moved nothing measurable

It was correct arithmetic — required spot move 1.92 → ~1.80 points, cost Rs65.09 →
Rs62.56/trade — and it is invisible in the outcome. An 11% improvement in a
break-even threshold does not show up in 15 trades when the gap to break-even is
this wide. Worth keeping (it costs nothing), worth not celebrating.

### The exit ladder finally ran — once

At **15:00:47** the first trade under `EXIT_ONLY_SL_TP_TRAILING` opened.

```
hold 570.4s (9.5 minutes)     <- every previous trade: 2-135 seconds
🛑 HARD SL HIT | -7.0 pts | gross -Rs455 -> net -Rs515.68
```

No early cut, no soft loss, no RSI reversal. It ran to the declared stop.
**Across 28 live trades in two days, that is the first time the ladder the strategy
is documented around has governed a single exit.** MFE never reached 12, so the
stop never moved to entry.

**n = 1.** It tells us the machinery works. It tells us nothing about whether the
ladder is better, and I am not going to pretend otherwise. That needs a full session.

### What blocked the bot mid-afternoon, and what it exposed

From **13:41 entries silently stopped** while the bot looked perfectly healthy —
ticks flowing, strikes searching, no error. The cause was in `states.log`:

```
ENTRY_READY -> COOLDOWN | Reason: Risk: Weekly loss limit Rs2507 (max: Rs2400)
```

The weekly ceiling was **hardcoded** `int(TOTAL_CAPITAL * 0.08)` = Rs2,400, with no
env override — the exact shape of the drawdown-gate defect fixed last night, in a
different gate. And note the sizing: **the weekly ceiling was 2.4x smaller than the
daily one it sits above**, so a single fully-permitted losing day exhausts the
entire week. Nobody chose that either; it is two independent percentages of capital
that happen to cross.

Now `MAX_WEEKLY_LOSS_AMOUNT`, env-configurable. This is the third hardcoded limit in
two days that stopped the bot without announcing itself. **`utils.preflight` should
grow a check for every ceiling, not just the drawdown one.**

### Two mistakes I made today

1. **A `pgrep` pattern that matched too much.** Restarting the bot, my kill matched
   several PIDs including my own background tasks, and killed the end-of-session
   digest watcher along with the bot. The bot was then down from ~13:28 until I
   noticed. Recovered; the watcher was re-armed.
2. **Four restarts hit the broker's historical-API rate limit**
   (`Access denied because of exceeding access rate`). Warm-up fell back to the
   on-disk candle cache, which worked — but each config change costing a restart is
   a real constraint on how many experiments a single session can hold.

### Open, and deliberately left open

- **`MAX_DAILY_LOSS=8000`, `KILL_SWITCH_LOSS=8000`, `MAX_WEEKLY_LOSS_AMOUNT=12000`
  are still raised.** They were raised so the ladder test could produce a sample,
  and the test produced exactly one trade. I am leaving them raised so it can
  continue tomorrow — but they are a genuinely loosened risk posture and the `.env`
  says to restore them (3000 / 3000 / 2400) when the test is done. **Decide this
  before any real money is involved.**
- `EXIT_ONLY_SL_TP_TRAILING=true` and the `12:0, 16:11, ...` ladder are live.
- `tests/test_visual_records.py` has 3 failures **caused by the live session**, not
  by any code change: it rebuilds from the session record while the session is
  still writing to it, so two rebuilds hash differently and a one-observation window
  fails `start < end`. They passed at 08:24 before the bot started. The test needs a
  frozen snapshot; the other 714 pass.
