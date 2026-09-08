# Does the holding horizon, and not the signal, explain the losses?

**Date:** 2026-09-08 · **Data:** `data/historical/candles.db` — 160,311 exchange 1-minute
option bars, 46 contracts (23 CE / 23 PE) of the 2026-09-08 expiry, 13 sessions
2026-08-19 … 2026-09-04, plus the matching NIFTY 1-minute index bars.
**Code:** `research/experiments/hold_horizon.py`, `research/experiments/hold_policy.py`,
`tests/test_experiment_hold_horizon.py` (15 tests).
**Nothing in `config/`, `core/`, `strategies/`, `utils/`, `brokers/` or `.env` was read for
values or modified.** The policy sweep rebinds `core.engines.exit_engine` module attributes
inside a `contextlib` scope for the duration of one in-process run and restores them; that is
tested (`test_patch_restores_every_attribute_it_touched`).

---

## 0. The answer, first

**At no holding horizon between 1 and 60 minutes does this become a winning system, and the
horizon is not what is wrong with it.**

The *arithmetic* of the third-party claim is confirmed, and on this data it is stronger than
reported: the hit rate a symmetric ladder would need falls from **105.6% at 1 minute to 54.4%
at 60 minutes**. The claim fails on the other side of the comparison, which the original did
not measure. The hit rate the market actually *delivers* to that same ladder is **42.9% at 1
minute and 49.6% at 60 minutes** — it never reaches the bar. Net expectancy per trade is flat
at **−1.5 to −1.9 option points at every horizon**, and the cluster-bootstrap 95% interval
lies entirely below zero at all eight horizons tested.

The one configuration in the whole study that turned positive — the shipping signal held a
full hour with every stop removed, +₹751 net over 13 sessions — is a directional bet on a
falling market and does not survive the drift control. Its mirror (same minutes, same strikes,
opposite option type) loses **−₹9,948**; direction-balanced it is **−₹190 per trade**, worse
than the shipping ladder's −₹156.

What *does* fall with a longer hold is the total damage, because friction is charged per round
trip and a longer hold means fewer round trips. That is the "trade less" lever, not the "hold
longer" lever, and it is worth saying which one it is.

---

## 1. Method, and the two traps

### 1.1 Friction, priced at each contract's own premium

```
friction(P) = costs.DEFAULT.points(P)  +  0.00239 · P
              └ brokerage/STT/exchange   └ round-trip bid/ask, measured on this
                /SEBI/stamp/GST            project's mode-3 SnapQuote rows (2026-09-07)
```

`research/costs.py` deliberately excludes the spread, because the live bot crosses the book in
its fill and has therefore already paid it. A measurement taken from **mid-price candles has
not**, so exactly one spread is added here. Reproduces the published figures: **0.999 pts at
₹57.4**, **1.634 pts at ₹190.8**.

It is evaluated **per sample, at that sample's entry premium** — never at a pooled mean.
This is item 4 of the brief and it is not cosmetic: friction is 1.00 pts at a ₹57 ATM contract
and 1.63 pts at a ₹191 delta-0.9 contract. Any excursion compared against the project's
"+0.884 gross points" bar without re-pricing friction for the contract actually traded is
wrong by up to 85%.

> **Correction to the friction used in the review being tested.** That table set friction to
> `1.071 fixed points + a measured decay term`, i.e. it **omitted the bid/ask spread**
> (0.348 pts at a ₹145.55 premium) and **added theta separately**. Theta is already inside an
> *empirically measured* MFE — the path decayed while it was being observed — so charging it
> again double-counts. Correcting both: the 1-minute required hit rate rises from 82.1% to
> ~91%, and the 30-minute one falls from 60.6% to ~59%. The errors run in opposite directions
> and partly cancel at long horizons; they do not cancel at short ones.

### 1.2 Overlap — the trap named in the brief

Entries on a 1-minute grid measured over a 30-minute forward window share 29/30 of their path.
The fix used here is **non-overlapping sampling**: each horizon gets a stride equal to itself,
so no two windows for that horizon share a bar inside one contract-session.

| horizon | n on a 1-min grid | n non-overlapping | inflation | naive SE (grid) | naive SE (indep.) | cluster 95% CI on mean MFE |
|---|---|---|---|---|---|---|
| 1 min  | 33,743 | 33,743 | 1.0× | 0.0104 | 0.0104 | [1.066, 1.597] |
| 5 min  | 29,123 | 6,108  | 4.8× | 0.0243 | 0.0561 | [3.342, 4.115] |
| 15 min | 25,393 | 1,843  | 13.8× | 0.0452 | 0.1835 | [6.386, 7.585] |
| 30 min | 22,855 | 863    | 26.5× | 0.0704 | 0.3921 | [9.466, 11.255] |
| 60 min | 19,591 | 408    | 48.0× | 0.1091 | 0.8735 | [13.782, 17.980] |

A naive interval from the grid is **8× too narrow at 60 minutes**, and even the
non-overlapping naive SE is too narrow again, because 46 strikes at the same instant are one
index path wearing 46 hats. **Every interval in this report is therefore a cluster bootstrap
that resamples whole sessions** (13 clusters, 1,500–4,000 reps). Thirteen sessions is not many
and the intervals are wide. That is the sample, not a flaw in the method.

### 1.3 What the bars cannot say

A 1-minute bar reports that its high and its low both occurred; it does not report in which
order. Means of MFE and MAE do not care. First-touch does, so every barrier test is run under
**both** orderings and both are reported.

---

## 2. The MFE / MAE term structure (brief item 1)

Non-overlapping windows, ATM ± 100 points (the band the bot actually trades — the harness
picks the exact ATM strike), friction at each sample's own premium, windows ending by 15:25.

| horizon | n | mean premium | mean MFE | mean \|MAE\| | MFE/\|MAE\| | mean friction | friction as % of MFE | **P(MFE > friction)** | mean close | NIFTY drift | required hit rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 min  | 33,743 | 161.4 | 1.343 | 1.381 | 0.972 | 1.494 | **111%** | 34.5% | −0.012 | −1.04 | **105.6%** |
| 2 min  | 16,328 | 159.6 | 2.130 | 2.195 | 0.970 | 1.486 | 70% | 50.0% | −0.029 | −1.17 | 84.9% |
| 5 min  | 6,108  | 156.2 | 3.744 | 3.824 | 0.979 | 1.470 | 39% | 69.6% | −0.051 | −1.58 | 69.6% |
| 10 min | 2,871  | 153.0 | 5.697 | 5.783 | 0.985 | 1.454 | 26% | 78.3% | −0.108 | −2.43 | 62.8% |
| 15 min | 1,843  | 151.1 | 7.022 | 7.136 | 0.984 | 1.446 | 21% | 82.7% | −0.154 | −2.87 | 60.3% |
| 30 min | 863    | 147.3 | 10.415 | 10.386 | 1.003 | 1.427 | 14% | 85.6% | −0.328 | −5.15 | 56.9% |
| 45 min | 555    | 145.8 | 13.399 | 12.831 | 1.044 | 1.420 | 11% | 83.6% | −0.261 | −7.10 | 55.3% |
| 60 min | 408    | 145.0 | 15.949 | 15.425 | 1.034 | 1.417 | **9%** | 84.1% | −0.584 | −8.91 | **54.4%** |

Same table over **all strikes at premium ≥ 40**, which is the filter the original review used,
for comparability:

| horizon | n | mean premium | mean MFE | mean \|MAE\| | MFE/\|MAE\| | friction % of MFE | P(MFE > friction) | required hit rate |
|---|---|---|---|---|---|---|---|---|
| 1 min | 117,763 | 201.9 | 1.262 | 1.295 | 0.974 | 134% | 27.8% | 116.8% |
| 2 min | 55,011 | 194.8 | 2.187 | 2.241 | 0.976 | 76% | 44.8% | 87.8% |
| 5 min | 19,695 | 185.9 | 3.956 | 4.070 | 0.972 | 41% | 64.9% | 70.4% |
| 10 min | 8,980 | 179.7 | 5.994 | 6.122 | 0.979 | 26% | 74.3% | 63.2% |
| 15 min | 5,666 | 176.5 | 7.355 | 7.592 | 0.969 | 21% | 80.3% | 60.6% |
| 30 min | 2,573 | 170.5 | 10.791 | 11.084 | 0.974 | 14% | 84.5% | 57.1% |
| 45 min | 1,624 | 166.4 | 13.708 | 13.540 | 1.012 | 11% | 82.6% | 55.5% |
| 60 min | 1,164 | 164.4 | 16.188 | 16.094 | 1.006 | 9% | 83.6% | 54.7% |

Cluster-bootstrap intervals on the two quantities that matter:

| horizon | MFE / \|MAE\| [95% CI] | mean MFE − friction, pts [95% CI] |
|---|---|---|
| 1 min | 0.972 [0.953, 0.989] | **−0.151 [−0.512, +0.172]** |
| 2 min | 0.970 [0.948, 0.990] | +0.643 [+0.264, +0.968] |
| 5 min | 0.979 [0.944, 1.009] | +2.275 [+1.839, +2.674] |
| 15 min | 0.984 [0.919, 1.045] | +5.577 [+4.908, +6.155] |
| 30 min | 1.003 [0.915, 1.083] | +8.988 [+8.033, +9.832] |
| 60 min | 1.034 [0.898, 1.151] | +14.532 [+12.371, +16.542] |

**What survives.** The shape of the reported claim is real and robust. Mean MFE grows roughly
as √t; friction is near-flat (it drifts *down* only because longer windows sample slightly
cheaper contracts); friction as a share of MFE collapses from 111% to 9%; the required hit
rate falls from 105.6% to 54.4%. `MFE − friction` crosses zero at **2 minutes** and its 95%
interval is clear of zero from 2 minutes onward. At a 1-minute hold, movement and cost are
statistically indistinguishable — the project's existing finding, reconfirmed on independent
data (this uses exchange candles; the earlier figure came from the bot's own ticks).

**What does not survive: MFE/|MAE| falling with horizon.** The review reported 0.890 → 0.802
from 1 to 30 minutes and read it as the option book mean-reverting. On a direction-balanced
book it is **flat at ~0.97 and if anything rises to 1.03**. §3 shows the falling ratio was the
index, not the option.

---

## 3. Drift control (brief item 2) — and the confound is confirmed, on both sides

NIFTY fell over this window: the 13 sessions sum to **−414.65 points** of intraday move
(24,152.05 open on 2026-08-19 → 23,897.70 close on 2026-09-04). Mean index drift over a
60-minute sampled window is **−8.91 points**. The confound the brief named is present in this
sample too, and here it can be measured because the book is 23 CE / 23 PE.

Same measurement, split (ATM ± 100):

| horizon | **CE** MFE | CE \|MAE\| | CE ratio | CE mean close | **PE** MFE | PE \|MAE\| | PE ratio | PE mean close | index drift |
|---|---|---|---|---|---|---|---|---|---|
| 1 min | 1.460 | 1.470 | 0.993 | −0.052 | 1.228 | 1.294 | 0.949 | +0.027 | −1.04 |
| 5 min | 3.968 | 4.197 | 0.945 | −0.234 | 3.524 | 3.457 | 1.019 | +0.130 | −1.58 |
| 15 min | 7.243 | 7.918 | 0.915 | −0.714 | 6.806 | 6.369 | 1.069 | +0.395 | −2.90 |
| 30 min | 10.396 | 11.811 | **0.880** | −1.760 | 10.433 | 9.035 | **1.155** | +1.031 | −5.44 |
| 45 min | 12.922 | 15.219 | 0.849 | −2.328 | 13.855 | 10.552 | 1.313 | +1.711 | −7.04 |
| 60 min | 15.702 | 17.865 | **0.879** | −3.486 | 16.178 | 13.170 | **1.228** | +2.099 | −9.62 |

The CE column **reproduces the reviewed table almost exactly** (0.880 at 30 min vs their
0.802) and the PE column is its mirror (1.155). Pooled, the ratio is 1.003. So the reviewed
"MFE/MAE decays with horizon" result was a **95% CE sample in a falling market**, exactly as
its own caveat warned. It is withdrawn by this measurement, not confirmed.

The residual after balancing is small and negative — pooled mean close at 60 minutes is
**−0.584 points**, about −0.010 pts/min, which is genuine decay on a ~₹145 contract of the
same order as the −0.017 to −0.025 pts/min the review isolated by regression. **Time decay is
real and it is small. Direction was doing the work.**

---

## 4. The measurement the original did not take: what the ladder actually collects

Mean MFE is the height of the path. A ladder collects the **first** barrier touched, not the
highest point reached, and the two are not the same number. So: symmetric TP = SL = X, with X
set to that horizon's own mean MFE — the review's own rule — walked bar by bar, non-overlapping
windows, ATM ± 100, friction charged at each sample's own premium.

| horizon | X (pts) | n | wins | losses | timeouts | **hit rate achieved** | **hit rate required** | gap | net expectancy (pts) | 95% CI (cluster) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 min  | 1.34 | 33,743 | 9,406 | 12,522 | 11,815 | **42.9%** | 105.6% | 62.7 | −1.618 | [−1.684, −1.553] |
| 2 min  | 2.13 | 16,346 | 5,145 | 5,813 | 5,388 | 47.0% | 84.9% | 37.9 | −1.572 | [−1.653, −1.494] |
| 5 min  | 3.74 | 6,131 | 2,011 | 2,124 | 1,996 | 48.6% | 69.6% | 21.0 | −1.518 | [−1.627, −1.426] |
| 10 min | 5.70 | 2,897 | 888 | 1,029 | 980 | 46.3% | 62.8% | 16.4 | −1.712 | [−1.893, −1.531] |
| 15 min | 7.02 | 1,867 | 562 | 655 | 650 | 46.2% | 60.3% | 14.1 | −1.790 | [−2.078, −1.542] |
| 30 min | 10.42 | 870 | 258 | 301 | 311 | 46.2% | 56.9% | 10.7 | −1.907 | [−2.254, −1.614] |
| 45 min | 13.40 | 559 | 190 | 200 | 169 | 48.7% | 55.3% | 6.6 | −1.631 | [−2.736, −0.711] |
| 60 min | 15.95 | 409 | 137 | 139 | 133 | **49.6%** | **54.4%** | **4.8** | −1.778 | [−3.113, −0.694] |

*(Intrabar ordering: adverse-first. Favourable-first moves only the 1-minute row materially —
hit rate 56.2% instead of 42.9%, net expectancy −1.385 instead of −1.618 — and is identical
from 45 minutes on. Neither ordering changes any sign.)*

**This is the refutation.** The bar comes down from 105.6% to 54.4% exactly as claimed. The
delivered hit rate goes up too — 42.9% → 49.6% — but it converges on 50%, which is what an
unbiased first-touch on a symmetric barrier must do, and 50% is not enough when the bar is
54.4%. The gap narrows from 62.7 points to 4.8 points and **never closes**. Net expectancy is
flat at −1.5 to −1.9 points per round trip at every horizon, and every 95% interval is below
zero.

Read the mechanism plainly: **widening the target in step with the horizon does not help,
because it widens the stop by the same amount.** The excursion grows as √t and so does the
distance to the stop. What friction buys you is a fixed toll per round trip, and the only thing
a longer hold changes is how many tolls you pay per session.

### 4.1 Is there any (horizon, barrier) pair that works?

Net expectancy in points per round trip, ATM ± 100, adverse-first, pooled CE+PE:

| hold ↓ / X → | 1 | 2 | 3 | 5 | 7 | 8 | 10 | 14 | 20 | 30 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 min | −1.66 | −1.56 | −1.52 | −1.52 | −1.51 | −1.51 | −1.51 | −1.51 | −1.51 | −1.50 |
| 2 min | −1.67 | −1.58 | −1.54 | −1.53 | −1.53 | −1.53 | −1.53 | −1.52 | −1.51 | −1.51 |
| 5 min | −1.68 | −1.60 | −1.55 | −1.59 | −1.58 | −1.55 | −1.53 | −1.49 | −1.49 | −1.50 |
| 10 min | −1.65 | −1.57 | −1.55 | −1.59 | −1.71 | −1.69 | −1.65 | −1.58 | −1.54 | −1.53 |
| 15 min | −1.67 | −1.66 | −1.57 | −1.62 | −1.78 | −1.78 | −1.79 | −1.68 | −1.55 | −1.51 |
| 30 min | −1.63 | −1.66 | −1.56 | −1.53 | −1.77 | −1.77 | −1.94 | −1.89 | −1.65 | −1.59 |
| 45 min | −1.66 | −1.55 | −1.56 | −1.44 | −1.67 | −1.56 | −1.68 | −1.62 | −1.59 | −1.65 |
| 60 min | −1.64 | −1.83 | −1.76 | −1.67 | −2.05 | −2.14 | −1.92 | −1.82 | −1.66 | −2.27 |

Eighty cells, all negative, all within about ±0.4 points of the friction line. Arbitrary entry
has no gross edge at any horizon, which is the expected and correct null.

Asymmetric, stop pinned at the declared 7 points, target varied:

| hold ↓ / TP → | 3 | 5 | 7 | 10 | 14 | 20 | 30 | 50 |
|---|---|---|---|---|---|---|---|---|
| 5 min | −1.64 | −1.60 | −1.58 | −1.52 | −1.47 | −1.46 | −1.46 | −1.46 |
| 15 min | −1.53 | −1.58 | −1.78 | −1.85 | −1.74 | −1.53 | −1.42 | −1.43 |
| 30 min | −1.48 | −1.52 | −1.77 | −1.76 | −1.62 | −1.07 | −0.79 | −0.59 |
| 60 min | −1.84 | −1.89 | −2.05 | −1.48 | −1.19 | −0.52 | −0.29 | **+0.98** |

**One positive cell, and it is not a finding.** 60 min / TP 50 / SL 7 produces **26 wins out of
409** windows. Its entire +399-point total comes from two sessions (2026-08-31 +357, 2026-09-01
+286); the other eleven sessions sum to **−244**. It is CE +0.215 vs PE +1.681 — a
long-tail directional profile in a falling market, estimated from a couple of dozen tail events
across 13 days. This project has already retracted an opening-window and a range gate fitted on
2–3 sessions. This is the same shape of artifact and it is rejected on sight.

---

## 5. The policy test on the real engines (brief item 3)

`research/experiments/hold_policy.py` drives `research/backtest/harness.py`, which imports and
runs the shipping `smart_scalp_signal` and `check_exit_conditions`. **The entry signal is
identical in every row** — same minutes, same strikes, same fills. Only exit branches change.

**Spread: the harness already pays it, once.** It fills the entry at `bar + half_spread` and
the exit at `bar − half_spread`, so the crossed book is inside `Trade.gross_pnl` before any
charge is added; `research/costs.py` then adds only brokerage/STT/exchange/SEBI/stamp/GST.
**Nothing extra was added.** The harness default is 0.246% round trip (measured on this
project's recorded ticks); re-running at the 0.239% SnapQuote figure moves the 56-trade
baseline by **₹36 in total** (−₹8,745 → −₹8,709). Both figures are reported and neither
changes anything.

13 sessions, expiry 2026-09-08, 1 lot × 65, intrabar low-first (which the harness docstring
establishes is the *flattering* order for this ladder).

| variant | n | mean hold | gross | net | net/trade | net win% | mean MFE | mean MAE |
|---|---|---|---|---|---|---|---|---|
| **A** baseline (shipping ladder) | 56 | 230 s | −4,862 | **−8,745** | −156 | 17.9% | 3.34 | −2.33 |
| B early cut OFF | 56 | 263 s | −5,291 | −9,173 | −164 | 19.6% | 3.58 | −2.62 |
| C soft loss OFF | 50 | 432 s | −4,541 | −8,033 | −161 | 30.0% | 4.08 | −3.49 |
| D both time cuts OFF | 50 | 520 s | −5,077 | −8,567 | −171 | 36.0% | 4.83 | −4.13 |
| E cuts OFF + max hold 30 min | 48 | 634 s | −4,802 | −8,149 | −170 | 37.5% | 5.47 | −4.39 |
| F cuts OFF + max hold 60 min | 48 | 665 s | −4,218 | −7,566 | −158 | 39.6% | 5.92 | −4.47 |
| G cuts OFF + hold to 15:25 | 48 | 665 s | −4,218 | −7,566 | −158 | 39.6% | 5.92 | −4.47 |
| H cuts OFF, trail OFF, **TP14/SL7**, 30 min | 42 | 1,074 s | −3,094 | −6,038 | −144 | 35.7% | 6.92 | −5.59 |
| I cuts OFF, trail OFF, TP14/SL7, to 15:25 | 40 | 1,323 s | −2,279 | −5,077 | −127 | 30.0% | 8.20 | −6.34 |
| J cuts OFF, trail OFF, SL7 only, 30 min | 42 | 1,189 s | −4,924 | −7,865 | −187 | 33.3% | 7.89 | −5.68 |
| K **pure horizon 30 min** (no SL/TP/greeks-kill) | 32 | 1,791 s | +1,657 | **−590** | −18 | 50.0% | 10.23 | −6.77 |
| L **pure horizon 60 min** (no SL/TP/greeks-kill) | 25 | 3,336 s | +2,506 | **+751** | +30 | 40.0% | 16.03 | −11.23 |
| M pure horizon 5 min | 51 | 341 s | −4,678 | −8,247 | −162 | 21.6% | 3.99 | −3.83 |
| N pure horizon 1 min | 64 | 92 s | −5,421 | −9,888 | −154 | 18.8% | 1.73 | −2.24 |

Three things to read here.

**(a) Nothing that keeps the shipping ladder gets close.** B through J move net expectancy
between −₹127 and −₹187 against a baseline of −₹156. Removing the 45-second cut alone makes it
*worse* (B, −₹164) — that cut is not the problem. The best of them, I (the declared TP14/SL7
run to the close, a ladder that has fired **zero** times in 13 live trades), is −₹127 a trade
over 40 trades. There is no ordering of these knobs that produces a system.

**(b) K and L are not the shipping system.** They remove the hard stop, the take-profit, the
trailing ladder *and* the greeks kill. They are an upper bound on what horizon alone can do,
not a proposal. They are labelled that way in the code.

**(c) L's +₹751 is a directional bet, and it fails the drift control.**

| | variant A (baseline) | variant K (30 min) | variant L (60 min) |
|---|---|---|---|
| own net | −₹4,485 (matched subset) | −₹1,277 | **+₹842** |
| **mirror** — same minute, same strike, **opposite option type**, same hold | −₹6,246 | −₹10,266 | **−₹9,948** |
| **direction-balanced** (half CE, half PE) | −₹128/trade | −₹199/trade | **−₹190/trade** |
| net expectancy, 95% CI (cluster bootstrap over sessions) | −₹156 [−228, −86] | −₹18 [−331, +217] | **+₹30 [−443, +486]** |
| profitable sessions | 2/13 | 7/13 | **5/13** |
| mean NIFTY drift over the trades' own windows | −2.13 pts | −3.85 pts | −3.40 pts |
| CE / PE split | 20 / 36 | 11 / 21 | 9 / 16 |
| CE net / PE net | −4,764 / −3,981 | −3,357 / +2,767 | **−3,305 / +4,056** |

L's whole result is the PE book. Its CE book loses ₹367 a trade. Its per-session net is
`+698, −92, 0, +2012, +730, +1113, −1848, −1702, −2460, −215, −183, +3990, −1292` — one session
(2026-09-03, the day NIFTY fell 124.5 points) supplies **+₹3,990** against a total of +₹751.
Remove it and the configuration is −₹3,239. The 95% interval spans zero by a factor of fifteen.

To be fair to the signal: its direction choice is **not** a static PE bias. It went 0% PE on
2026-09-02 (index +56.5) and 20% PE on 2026-08-25 (index +158.8), so it does track the day.
But it was 0% PE on 2026-08-31 (index −37.1) and lost ₹2,460 there, and 100% PE on four
sessions. Over 25 trades and 13 days that is not enough to separate a directional signal from a
sample that fell 414 points. **The honest statement is that L is unproven, not that it works.**

---

## 6. What this changes about the reviewed claim

| reviewed claim | verdict on this repo's own data |
|---|---|
| MFE rises 1.7 pts @1 min → 7.9 pts @30 min | **Confirmed, shape and magnitude.** Measured here: 1.34 → 10.42 (ATM band), 1.26 → 10.79 (premium ≥ 40). Different sample, same √t growth. |
| Friction falls from 64% to 21% of MFE | **Confirmed in direction, wrong in level.** Correctly priced (spread in, double-counted theta out) it is **111% → 9%**. The reviewed friction omitted the bid/ask spread at short horizons and double-charged decay at long ones. |
| Required hit rate falls 82% → 61% | **Confirmed and understated.** 105.6% → 54.4%. |
| ⇒ therefore a longer hold is the largest lever in the report | **Refuted.** The delivered first-touch hit rate is 42.9% → 49.6% and never reaches the bar. Net expectancy is flat at −1.5 to −1.9 pts at every horizon, 95% CI below zero at all eight. |
| MFE/\|MAE\| falls 0.890 → 0.802 with horizon (book mean-reverts) | **Refuted — it was the drift.** CE-only reproduces it (0.993 → 0.880); PE-only mirrors it (0.949 → 1.228); balanced is flat at 0.97–1.03. |
| The long-horizon ladder sweep that looked terrible was confounded | **Confirmed, and the confound is symmetric.** The *favourable* long-horizon result found here (variant L) is confounded in the same way and by the same market. |

---

## 7. Limitations of this work — read before quoting any number above

1. **Thirteen sessions, one expiry, one direction of market.** Every option contract in
   `candles.db` is the 2026-09-08 weekly. The index fell 414 points across the window. A
   direction-balanced statistic is protected against that; a directional one (variant L, the
   TP50/SL7 cell) is not, and no amount of care inside this sample fixes it.
2. **The bootstrap has 13 clusters.** Percentile intervals from 13 resampled units are crude.
   They are wide, and they should be read as "this is not established", not as calibrated
   probability.
3. **Sub-minute exits cannot be resolved at 1-minute granularity**, and this is the harness's
   own largest disclosed gap. The live early-loss cut fires at ~45 s and the soft-loss at ~75 s;
   here the baseline's mean hold is 230 s against a live median near 60 s. The replay
   **under-fires** exactly the branches this study switches off, so the measured *difference*
   between "cuts on" and "cuts off" is a lower bound on the true difference. It does not change
   the sign of any row — every row is negative — but it means variant A is not a faithful
   reproduction of the live ladder.
4. **Intrabar ordering is invented.** Extremes are stamped at +0/+20/+40/+59 s; the data cannot
   say when they happened. Both orderings are reported for the barrier study; the harness rows
   use the flattering one.
5. **The book is modelled, not measured.** No historical bid/ask exists from any source
   reached. The 0.239% spread comes from one afternoon, three CE strikes, delta 0.52–0.64,
   1 DTE. There is no measurement above delta 0.64 and none for PE at all. If real spreads are
   wider — and every source on option liquidity says deep-ITM books are — every number here is
   optimistic.
6. **The MFE/MAE study uses arbitrary entries**, which is the point (it measures what the
   market offers, not what the signal finds), but it therefore says nothing about whether a
   *better* signal exists. It says only that horizon alone does not supply one.
7. **Multiple comparisons.** §4.1 tests 80 barrier cells and §5 tests 14 policy variants.
   Finding one or two positive cells is expected under a true null; I have treated them as such
   rather than promoting them.
8. **OI is absent and volume unused.** `getCandleData` carries no open interest at any
   interval, so nothing here conditions on it.
9. **Variants K and L disable the greeks kill**, which on 0DTE behaves partly as a time exit.
   They are bounds, not candidate configurations, and should not be run.

---

## 8. Where this points, if anywhere

Not at the exit ladder. The measurement that would actually move this system is the one the
term structure implies and the policy sweep does not test: **friction is charged per round
trip, so the lever with the largest measured effect is round trips per session, not seconds per
trade.** Variant L pays 25 tolls where variant A pays 56 and variant N pays 64; the per-trade
expectancy barely moves but the toll count halves. That is the "≤ 2 entries/day" item already
ranked #1 in `strategy_research_20260908.md`, and this study is consistent with it — but this
study did not test it and cannot claim it.

What would falsify the negative here: a delta-balanced sample spanning at least one full
up-trending month, on which a symmetric long-horizon ladder delivers a first-touch hit rate
that stays above the required rate. On the 13 sessions available it does not, at any horizon.
