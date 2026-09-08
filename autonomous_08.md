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
