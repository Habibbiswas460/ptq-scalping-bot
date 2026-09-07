# Strategy research — 2026-09-08

External research (web, 2025–2026 sources) plus original measurement on this project's own
tick record, against the seven established baseline findings. Read-only: no code, config or
`.env` was touched to produce this.

---

## 1. Verdict

**There is no configuration in which this bot has positive net expectancy while it buys long
NIFTY options at ₹30,000.** Not "unlikely" — the arithmetic closes it, and it closes it for a
reason the project has not yet stated precisely enough:

> Cost reduction cannot save a strategy whose **gross** expectancy is zero. And under
> arbitrary timing on this project's own 98,434 option ticks, gross expectancy of a long
> option position is **+0.026 points per trade (₹1.70)** — statistically indistinguishable
> from zero at every exit geometry I tested.

That is the whole problem in one line. Baseline finding 1 (every figure was gross) told the
project that ₹63.80/trade of cost was being ignored. The measurement below adds the part that
makes it terminal: there was never anything for the cost to eat into. A long NIFTY option held
for seconds-to-minutes is a **zero-drift instrument** — a fair coin with a fee stapled to it.
The bot's −₹10,956 is not a strategy that stopped working; it is 144 fees.

### What I measured (details and limits in §6)

Sampling every subscribed option contract on a 30-second grid, premium ≥ ₹40, and simulating a
full TP/SL ladder tick-by-tick over a 300-second maximum hold — **2,968 arbitrary-timing
entries across 11 contracts and 7 sessions**:

| TP | SL | resolved in 300s | gross E (pts) | net @ Zerodha ₹20 | net @ ₹5 broker | net @ ₹5 + real spread |
|---|---|---|---|---|---|---|
| 2 | 2 | 97.1% | −0.0725 | −1.1437 | −0.5991 | −0.9572 |
| **3** | **2** | 93.9% | **−0.0235** | **−1.0947** | **−0.5501** | **−0.9082** |
| 4 | 2 | 89.4% | −0.0245 | −1.0957 | −0.5511 | −0.9091 |
| 5 | 3 | 76.5% | −0.1396 | −1.2109 | −0.6662 | −1.0243 |
| 7 | 5 | 48.2% | −0.2538 | −1.3250 | −0.7804 | −1.1385 |
| 10 | 5 | 39.6% | −0.2397 | −1.3110 | −0.7663 | −1.1244 |
| **14** | **7** *(declared)* | **21.4%** | −0.2737 | −1.3449 | −0.8003 | −1.1584 |

Across a wider sweep of **54 (TP, SL) combinations**, the best gross cell is **−0.0235 points
(−₹1.53)** and **zero of 54 cells are net-positive at any cost structure tested — including a
hypothetical zero-brokerage broker.**

This independently reproduces baseline finding 3 ("no exit geometry clears its own
break-even") from a different direction and extends it: *the reason no exit geometry works is
that there is no gross edge for an exit to harvest, so the sweep is bounded above by ~zero
before costs are applied at all.* It also confirms finding 3's sub-claim that widening the
target widens the gap, with the mechanism made explicit: **the declared TP14/SL7 resolves only
21.4% of the time inside 300 seconds.** A 14-point target on a contract whose 300-second mean
favourable excursion is 3.76 points is not a target; it is a timeout.

### What *would* be required

Anything that changes the answer has to attack the **gross** term. The bar, computed at the
mean sampled premium of ₹145.55, one lot of 65:

| requirement | ₹20 broker | ₹5 broker | ₹5 broker + real 0.246% spread |
|---|---|---|---|
| round-trip friction | 1.071 pts / ₹69.63 | 0.527 pts / ₹34.23 | **0.884 pts / ₹57.50** |
| gross edge needed per trade | > 1.071 pts | > 0.527 pts | **> 0.884 pts** |
| equivalent spot move at delta 0.50 | 2.14 pts | 1.05 pts | 1.77 pts |
| required hit rate at TP3/SL2 | 61.4% | 50.5% | 57.7% |
| arbitrary-timing hit rate at TP3/SL2 | 40.6% | 40.6% | 40.6% |
| **required relative improvement** | **+51%** | **+24%** | **+42%** |

So the project's stated bar of "+58% relative hit rate over arbitrary timing" is the right
*kind* of number and close in magnitude; my independent computation puts it at **+51%** at
Zerodha's rates on the TP3/SL2 geometry, and — this is the actionable part — **at +24% if the
broker changes and the strategy can post rather than cross, or +42% if it must keep crossing
the spread.** Changing broker does not make a non-existent edge exist, but it cuts the size of
the edge that would have to be found by roughly half.

Four routes out, priced:

1. **Find a genuinely different entry edge worth > 0.9 points gross.** §2 and §4 say what to
   look for. Nothing I tested, and nothing I found in the 2025–2026 literature, reaches it.
2. **Stop paying the flat fee 144 times.** Trade frequency is the dominant term (§3.1).
3. **Change instrument** — requires capital the account does not have (§3.6). A defined-risk
   NIFTY spread needed ~₹31,500 margin in July 2026; NIFTY futures need ₹1.0–1.2 lakh/lot and
   post-peak-margin rules mean intraday leverage no longer reduces that.
4. **Stop buying options.** SEBI FY26: option *sellers* were the only strategy group with a
   positive median return on capital employed; ~97% of individual traders are buyers and 92%
   of the ₹91,685 crore of losses came from options. At ₹30,000 the account cannot sell a
   hedged NIFTY spread, so this route is blocked by capital, not by belief.

**Blunt version: the honest capital requirement to run a defined-risk options strategy on
NIFTY in 2026 is ₹35,000–50,000 for one spread with buffer. The account is ₹30,000 and has
₹27,210 of equity. The instrument the account *can* afford is the one instrument that has been
measured, here and by the regulator, to have negative expectancy.**

---

## 2. Cost structure — verified against current sources

### 2.1 The project's model is correct

`research/costs.py` is right. Checked line by line against Zerodha's live charges page
(2026-09-08):

| component | `costs.py` | Zerodha published | verdict |
|---|---|---|---|
| brokerage | ₹20/executed order | "Flat Rs. 20 per executed order" | ✅ |
| STT | 0.15% sell side, on premium | "0.15% on sell side (on premium)" | ✅ |
| exchange txn (NSE) | 0.03553% both sides | "0.03553% (on premium)" | ✅ |
| SEBI | ₹10/crore | "₹10 / crore" | ✅ |
| stamp | 0.003% buy side | "0.003% or ₹300 / crore on buy side" | ✅ |
| GST | 18% on brokerage + exch + SEBI | same | ✅ |

The **0.15% STT is real and current** — Budget 2026 raised options STT from 0.10% to 0.15% of
sell-side premium effective 1 April 2026. The project's model already reflects it. The
"0.15% of intrinsic value on options bought and exercised" line matters only if a position is
carried to expiry ITM, which this bot never does; it is correctly ignored.

**Two documentation corrections (no code change made):**

- `research/costs.py`'s docstring and `points()` docstring both quote **1.162 points** per
  round trip. At the recorded mean entry premium of ₹107.96 the correct figure is **0.982
  points (₹63.84)**; 1.162 points corresponds to a premium near ₹200. The memory note already
  records this correction ("my cost was 0.98 pts not 1.162") but the source file still carries
  the old number in two places.
- The memory note records the broker lever as "break-even 67% → 54.8%". Recomputing from the
  recorded book (avg win ₹159.23, avg loss ₹161.51, n=144) I get **70.3% → 59.2%**. The
  ₹20-case 70.3% matches the 7sept26 report exactly, so the 67% and 54.8% figures appear to
  rest on a different (unstated) win/loss basis. Use 70.3% → 59.2% unless that basis is found.

### 2.2 Where the money actually goes — and why this is the one big lever

One NIFTY lot (65), premium ₹108, buy-and-sell intraday:

| component | ₹ | share |
|---|---|---|
| **brokerage** | **40.00** | **62.7%** |
| STT | 10.53 | 16.5% |
| GST | 8.10 | 12.7% |
| exchange txn | 4.99 | 7.8% |
| stamp | 0.21 | 0.3% |
| SEBI | 0.01 | 0.0% |
| **total** | **63.84** | = 0.982 pts |

**Brokerage plus the GST charged on it is ₹47.20 — 73.9% of the entire cost of a trade.** It
is a *flat* fee, so it does not scale with position value: it is a fixed toll per decision.
That single fact is the most exploitable number in this report, and it has two consequences:

- **Broker choice.** Shoonya (Finvasia) publishes "Flat ₹5 plus GST per executed order in all
  Options"; m.Stock publishes ₹10/order. Moving ₹20 → ₹5 cuts round-trip cost from ₹63.84 to
  **₹28.44 (−55%)**, and the required entry edge from 1.071 to 0.527 points. Note the caveat:
  Shoonya's fully-free F&O model ended 16 December 2024 when SEBI banned the exchange-rebate
  model that funded it; ₹5 is the current published rate, and API terms, static-IP support and
  order-throughput limits must be checked before any migration.
- **Trade count.** Because it is flat and per-decision, it is a straight multiplier on
  frequency. At the recorded gross expectancy of −₹12.28/trade:

| | 13 trades/day | 5/day | 2/day | 1/day |
|---|---|---|---|---|
| ₹20 broker | −₹990/day | −₹381 | −₹152 | −₹76 |
| ₹5 broker | −₹529/day | −₹204 | −₹81 | −₹41 |
| ₹0 brokerage | −₹376/day | −₹145 | −₹58 | −₹29 |

Every cell is negative — correctly, since gross expectancy is negative. **Frequency reduction
does not create profit; it reduces the bleed rate by up to 13×, which buys measurement time.**
That is its entire value, and it is a real value: at 13 trades/day this account is bankrupt in
weeks; at 1 trade/day it survives a year of research.

### 2.3 The cost the project still is not counting: the spread

`costs.py` models statutory charges and brokerage. It does **not** model crossing the bid/ask.
Now that real best-5 depth exists (2026-09-07, median real spread **0.246%**, range
0.054–0.305%), that gap is quantifiable: at the mean sampled premium of ₹145.55 a marketable
round trip (lift the offer in, hit the bid out) costs an additional **0.358 points = ₹23.27**.

**That is 68% as large as the entire brokerage saving from moving ₹20 → ₹5 (₹35.40).** Any
comparison of broker plans that ignores it will overstate the benefit. The honest total
friction is:

| | statutory + brokerage | + spread crossing | total |
|---|---|---|---|
| Zerodha ₹20 | ₹69.63 | ₹23.27 | **₹92.90** |
| ₹5 broker | ₹34.23 | ₹23.27 | **₹57.50** |

This does not overturn the 2026-09-07 finding that "the spread is not where the expectancy
problem lives" — it isn't; the zero-gross-edge result is. But the spread is a first-order term
in the *bar*, and it is the term a limit-order execution policy could attack.

---

## 3. Ranked, testable changes

Ranked by expected net-expectancy impact per unit of implementation risk. Every item names how
to **falsify** it on this project's own data.

### #1 — Cut trade frequency hard (target: ≤ 2 entries/day)
- **Mechanism.** Cost is a flat per-decision toll; gross edge is ~0. Net expectancy is
  therefore ≈ −(cost) × N. N is the only term currently under the project's control.
- **Effect size.** 13 → 2 trades/day at Zerodha rates: −₹990/day → −₹152/day. **~₹840/day,
  ~₹17,000/month of avoided loss.** Larger than every other item on this list combined.
- **Evidence.** SEBI FY26: "trading intensity emerged as one of the strongest characteristics
  associated with trading outcomes — higher turnover relative to capital employed associated
  with higher loss rates". Small-portfolio traders (<₹1 lakh) took **70% of aggregate losses**
  on about half the turnover. This project's own 7sept26 report: turnover 67× capital, costs =
  **84% of net loss** vs 27% for the SEBI population — i.e. this bot is *four times more
  cost-dominated than the average losing retail trader*.
- **Falsification.** Replay the 144-trade record keeping only the first N entries per session
  for N ∈ {1,2,3,5}; net P&L must fall monotonically in N. If it does not, the loss is
  concentrated in a subset that ordering does not select, and the finding is wrong.
- **Risk.** Near zero — it is a counter and a gate, no new logic.
- **Honest caveat.** This does not make money. It converts a fast loss into a slow one and
  buys the time to answer #4.

### #2 — Move the flat fee (broker migration), *after* #1
- **Mechanism.** 73.9% of per-trade cost is a flat fee unrelated to position value.
- **Effect size.** ₹63.84 → ₹28.44/round trip. Required gross edge 1.071 → 0.527 points;
  required relative hit-rate improvement over arbitrary timing **+51% → +24%**.
- **Evidence.** Shoonya published options rate ₹5/order; m.Stock ₹10/order; Zerodha ₹20/order.
- **Falsification.** Re-run `research.costs.summarise` over all 144 trades with
  `CostModel(brokerage_per_order=5.0)`; net total must move from −₹10,956 to approximately
  −₹5,860. If the delta is materially smaller, the flat-fee share was mis-estimated.
- **Risk.** Medium — it is a broker/API migration (Angel One SmartAPI → another vendor),
  touching auth, WebSocket packet parsing (the mode-3/best-5 work would need redoing), the
  instrument master, and static-IP registration. **Do not start this before #1 and #4.** It
  halves the bar; it does not clear it.

### #3 — Price the spread into every future comparison
- **Mechanism.** ₹23.27/round trip is currently invisible in every number the project
  produces, in the same direction every time.
- **Effect size.** Adds 0.358 points to the bar; changes the ₹5-broker required improvement
  from +24% to **+42%**.
- **Falsification.** Extend `CostModel` with a `spread_pct` term defaulting to the measured
  0.246% and re-run `research.synthesis`. Every experiment's net figure must move down by
  ~₹23/trade. Any that does not is reading a fabricated quote.
- **Risk.** Low. It is a research-layer change, not a trading change. **Prerequisite: more
  than one afternoon of real depth data** — the 0.246% median rests on one contract over two
  minutes on 2026-09-07 and must not be treated as a session-wide constant until measured
  across a full day.

### #4 — Replace the scoring stack with a single falsifiable hypothesis test
- **Mechanism.** The stack cannot rank (8/12 score and 7/17 confidence sub-components constant
  across 89,673 evaluations; two distinct (score, confidence) pairs per day). Tuning an
  arithmetic constant is not an experiment.
- **Effect size.** Unknown by construction — that is the point. The bar is explicit:
  **gross expectancy > 0.884 points/trade** (₹5 broker + spread) on a held-out session.
- **Evidence.** §4 below; the 27 conditioning cells I tested; the external falsification
  literature in §4.3.
- **Falsification.** The design is the falsification: one variable, one held-out session,
  pre-registered in `research/ledger.py` before the data is looked at, with the 0.884-point
  threshold written down in advance. The 2026-09-07 reversal of both flagship findings is the
  reason this discipline is non-negotiable.
- **Risk.** Low to implement, high to get right. This is the only item that can produce profit.

### #5 — Post rather than cross (limit-order entry)
- **Mechanism.** Removes up to 0.358 points of spread per round trip; the real best-5 book
  needed to do this now exists in the feed.
- **Effect size.** Up to ₹23.27/trade, i.e. **40% of the total friction at a ₹5 broker.**
- **Evidence, and the reason this is ranked below #4.** The order-flow literature is explicit
  that a resting limit order buys the spread and pays for it in adverse selection: the fills
  you get are disproportionately the ones you did not want. Passive execution converts a
  visible cost into an invisible one, and this project has no instrument that would detect the
  swap.
- **Falsification.** From the real best-5 record, for every entry instant compute whether a
  limit at the bid would have filled within the strategy's tolerance window, and what the
  forward excursion was **conditional on filling**. If mean forward excursion given a passive
  fill is worse than given a marketable fill by more than 0.358 points, passive execution is
  net negative and the item dies.
- **Risk.** High — needs unfilled-order handling, timeout policy, and a fill model this project
  has never built.

### #6 — Instrument change: not available at ₹30,000
Documented so it is not re-litigated. Current 2026 numbers:

| instrument | lot (Jan 2026) | capital needed | verdict at ₹30,000 |
|---|---|---|---|
| NIFTY long option | 65 | premium only (~₹7,000) | affordable — and measured to have zero gross drift |
| NIFTY debit spread | 65 | ~₹31,500 margin (July 2026 quote) | **not affordable** |
| NIFTY futures | 65 | ₹1.0–1.2 lakh (12–14% of ~₹15.5 lakh notional) | not affordable |
| BANKNIFTY | 30 | weekly options **abolished** — monthly only | not applicable |
| FINNIFTY / MIDCPNIFTY | 60 / 120 | weekly options **abolished** | not applicable |
| SENSEX (BSE) | 20 | premium only; weekly expiry Thursday | affordable, same zero-drift problem, and the flat fee is spread over a smaller lot |

Two structural facts the strategy layer should absorb:
- Since the SEBI circular effective 20 November 2024, **each exchange offers weekly expiry on
  one index only** — NSE on NIFTY 50, BSE on SENSEX. BANKNIFTY, FINNIFTY, MIDCPNIFTY,
  BANKEX and SENSEX50 are monthly-only. Any strategy idea that assumed a weekly BANKNIFTY is
  dead on arrival.
- NIFTY weekly expiry moved from Thursday to **Tuesday effective 1 September 2025**; SENSEX
  weekly is Thursday. This corroborates the instrument-master memory note (every NIFTY weekly
  is a Tuesday) and confirms that *no weekday rule* should ever be hardcoded — the calendar
  is the authority, as `utils/trading_calendar.py` already assumes.
- Intraday leverage is gone: peak-margin reporting means an intraday futures or short-option
  position needs broadly the same upfront margin as an overnight one. There is no "MIS
  multiplier" route to a futures position at ₹30,000.

### #7 — Deeper-ITM strike selection (marginal, cheap to test)
- **Mechanism.** The flat fee is fixed per order, so a higher-delta option captures more spot
  movement per rupee of fixed cost. Break-even *spot* move at ₹20 brokerage: **1.96 points at
  delta 0.50, 1.60 points at delta 0.90.**
- **Effect size.** ~18% reduction in required spot move. Real but second-order, and partly
  eaten by wider spreads on ITM strikes.
- **Falsification.** `research/transmission.py` already regresses option change on spot change
  through the origin at six horizons. Run it per-moneyness bucket; if realised beta does not
  rise with moneyness roughly as Black-Scholes delta predicts, the mechanism is not present in
  this book and the item dies.
- **Risk.** Low. But it is a 18% improvement on a bar that is currently missed by ~100%.

### #8 — Do not build: mean-reversion, OI/PCR, max-pain and GEX signals
See §4.3 and §5. None reached the required effect size in the literature or in my own
conditioning test, and several are unfalsifiable as usually stated.

---

## 4. What to change in the entry / scoring / market-quality gates

### 4.1 The gates cannot rank, and the audit already proved it

Established, not re-litigated here: 8 of 12 score sub-components and 7 of 17 confidence
sub-components are constant on every one of 89,673 rows; ~57 of the 105 score weight is a
fixed offset; the stack emits two distinct (score, confidence) pairs per day; acceptance is
75/89,673 = 0.084%. Every varying component tested in round 3 pointed the **wrong way** —
higher score, higher confidence, higher market quality and volume-spike-present all selected
*worse* moments, monotonically, on both sessions.

The recommendation follows mechanically: **do not tune these gates. They are not a ranker with
bad coefficients; they are a near-constant with four binary switches attached.**

### 4.2 My own test of what could replace them

Same 2,949-sample arbitrary-timing universe, TP3/SL2, 300s max hold, each entry conditioned on
a strictly causal 60-second lookback. Unconditional gross expectancy **+0.026 points**. The bar
at a ₹5 broker including the real spread is **0.884 points**.

| conditioning cell | n | gross E (pts) | 95% CI (±) | clears 0.884 bar? |
|---|---|---|---|---|
| **09:00–10:00** | 323 | **+0.548** | 0.572 | no |
| 11:00–12:00 | 475 | +0.310 | 0.369 | no |
| PE contracts | 168 | +0.244 | 0.647 | no |
| 13:00–14:00 | 478 | +0.244 | 0.227 | no |
| 60s momentum −1.5…−0.5 | 457 | +0.227 | 0.384 | no |
| **bottom 20% of 60s range** | 714 | **+0.192** | 0.262 | no |
| 60s momentum < −1.5 | 789 | +0.171 | 0.314 | no |
| 50–80% of range | 758 | +0.176 | 0.258 | no |
| premium ₹140–200 | 976 | +0.086 | 0.275 | no |
| 20–50% of range | 767 | +0.081 | 0.290 | no |
| 60s momentum +0.5…+1.5 | 455 | +0.067 | 0.281 | no |
| CE contracts | 2,781 | +0.013 | 0.146 | no |
| premium ₹90–140 | 1,602 | +0.005 | 0.141 | no |
| 60s momentum −0.5…+0.5 | 550 | −0.022 | 0.214 | no |
| premium ₹200+ | 340 | −0.092 | 0.635 | no |
| 14:00–16:00 | 714 | −0.122 | 0.288 | no |
| 10:00–11:00 | 480 | −0.215 | 0.210 | no |
| **60s momentum > +1.5** | 697 | **−0.261** | 0.334 | no |
| 12:00–13:00 | 479 | −0.361 | 0.454 | no |
| **top 20% of 60s range (breakout)** | 710 | **−0.359** | 0.326 | no |

**Not one of ~27 cells reaches the bar.** The best single cell (09:00–10:00, +0.548 points) is
62% of the way there and its confidence interval contains zero. With ~27 cells tested at
α=0.05 one expects ~1.4 false positives, and 09:00–10:00 is the same window that produced the
+₹114.06/p=0.0057 opening-window finding that **reversed to −₹108.81 out of sample on
2026-09-07**. I am flagging it as a coincidence to be suspicious of, **not** as corroboration.

### 4.3 The one signal-shaped result worth a controlled experiment

Two cells point the same way with a shared mechanism:

- **top 20% of the 60-second range = −0.359 points** (worst cell of 27)
- **60-second momentum > +1.5 points = −0.261 points** (second worst)
- **bottom 20% of the range = +0.192 points** (mean-reverting side, positive)

That is a coherent statement: *on this book, buying strength is the worst-priced entry
available and buying weakness is the best-priced.* It matches the external evidence in §5.2 on
why breakout entries are systematically adversely selected, and it matches the SEBI-documented
Jane Street mechanism, in which the profitable trade was **fading** an index level the firm had
itself pushed.

**And this is exactly what the bot's entry logic does today.** The scoring stack is
EMA-alignment + RSI + volume-spike shaped — a momentum/breakout detector. If the effect is
real, the stack is not merely unable to rank; **it is pointed at the worst cell of the twenty
I measured.**

Two independent reasons to treat this as a hypothesis and not a finding:

1. **My samples overlap.** A 30-second grid over a 300-second horizon means consecutive samples
   share up to 90% of their path. The ±1.96 SE bands above are therefore *too narrow* — the
   effective sample size is materially below 710. I did not compute a block-bootstrap CI, and
   without one the interval is not trustworthy.
2. **Even if real, it does not clear the bar.** +0.192 points against a 0.884-point requirement
   is 22% of what is needed. Reversing the entry from momentum to mean-reversion would move
   the strategy from "losing at −0.36" to "losing at +0.19 gross, −0.69 net". It is a
   diagnosis, not a cure.

**Recommended experiment (the only entry work I would authorise):** one variable — replace the
breakout/momentum condition with its mirror (enter on the bottom quintile of the 60-second
option range), hold everything else fixed, register the hypothesis and the 0.884-point
threshold in the ledger *first*, and score it on a session held out from this measurement.
Expected outcome: it fails the threshold and is recorded as a negative result. That is still
worth doing, because it converts "the gates cannot rank" into "we know which direction the
book actually pays", and it costs one session.

### 4.4 Specific gate recommendations

| gate | recommendation |
|---|---|
| weighted score, adaptive confidence | **Do not tune.** Constant by construction. Either populate `delta`/`oi`/`atr`/`macd` and re-measure discrimination, or delete the components — a weight that can never be earned is dead code pretending to be a model. |
| market-quality grade | **Remove from the accept decision.** Round 3 showed it selects monotonically *worse* moments (MQ≥92 → −₹66.72 vs MQ≥85 → −₹48.05). Keep it as a logged diagnostic. |
| `entry_engine`'s second flat 70/85 confidence floor | **Remove the duplicate.** Two textually identical floors where the stricter always wins means the documented MQ-adjusted scheme has never governed anything post-streak (audit finding 23). Whatever the gate should be, it should exist once. |
| trades-per-day cap | **This is now the primary risk control.** Set to 2. See #1. |
| PE trend-exhaustion filter | Leave disabled. It rejected 986/986 evaluations. |
| new gates | **Add none until #4's threshold test has run.** Every gate added before there is a measured edge adds a place for a future finding to be overfitted. |

---

## 5. How institutions trap retail — with evidence grading

Grading: **A** = regulator order, exchange data or peer-reviewed finding with a stated effect
size · **B** = credible practitioner/industry measurement, mechanism sound, effect size soft ·
**C** = folklore; mechanism plausible but the claim as usually stated is unfalsifiable.

### 5.1 Grade A — established, with numbers

**Expiry-day index manipulation is documented, adjudicated and large (A).** SEBI's interim
order of 3 July 2025 against Jane Street Group found that across **18 expiry days between
January 2023 and March 2025** (15 BANKNIFTY, 3 NIFTY) the firm bought index constituents and
their futures aggressively in the morning — at times over 20% of market-wide traded value in
individual scrips, frequently above the last traded price — while building a large bearish
index-options position, then sold that cash/futures exposure in the afternoon, pushing the
index down into its own options payoff. Unlawful gains computed at **₹4,843.57 crore**. This is
the single best-evidenced "institutions trap retail" claim available anywhere: it is a
regulator's own finding of fact, with the days, the instruments and the rupee amount named.
**Direct implication for this bot:** the intraday direction of a NIFTY index level on an expiry
day is not guaranteed to be an information-bearing signal. A momentum entry into an
institutionally-driven leg is, by the order's own description, the losing side of it.

**Retail is the counterparty, and the winners are algorithms (A).** SEBI's FY26 study:
87.7% of individual traders lost money; aggregate net losses **₹91,685 crore**; gross trading
loss **₹72,000 crore**; transaction costs **₹25,000 crore** in FY26 alone and ~₹1 lakh crore
cumulative over FY22–FY26. On the other side, proprietary traders booked ~**₹44,000 crore**
gross profit and FPIs ~₹14,000 crore, and **99% of FPI and proprietary profits were made by
algo entities**. ~97% of individual traders are predominantly option *buyers*; the ~2% who are
predominantly sellers are the only group with a positive median return on capital employed.

**Concentration and intensity are the strongest correlates of loss (A).** From the same study:
**59% of index-options turnover is 0DTE**, 75% within one day of expiry, 97% within one week.
Small-portfolio traders (<₹1 lakh) took **70% of aggregate losses** on roughly half the
turnover. **~90% of traders who lost in two consecutive years and kept trading lost again.**
Higher turnover relative to capital is associated with higher loss rates.

**Order-book spoofing and layering are real and enforced against in India (A).** SEBI has
brought actions where entities placed large disclosed orders away from the touch with no
intent to execute, transacted on the opposite side, and cancelled the decoy orders after the
real fill — prosecuted under the PFUTP Regulations, 2003, which do not name "spoofing" but
cover it. **Grading caution:** enforcement establishes that spoofing *occurs*. It does not
establish that *your particular* stop was hunted, and no public dataset lets a retail trader
attribute an individual adverse fill to it. Treat spoofing as a reason to distrust
displayed-depth-only signals, not as an explanation for any specific loss.

**Popular retail signals fail formal falsification (A).** *Retail Trader's Ruin: An Anatomy of
Popular Signal Failure* (arXiv 2607.20093) tested five signal families under a three-gate
design (statistical, economic, survival) with data-snooping correction. Results with 10 bps
round-trip retail costs: the **oscillator family — RSI(14, 30/70), MACD(12,26,9), Bollinger —
was REFUTED**, Sharpe gap 95% CI [−0.608, −0.175] and CAGR gap [−0.149, −0.044], both
*significantly negative*. Volume (OBV), calendar and candlestick families were also refuted;
trend and momentum were inconclusive; **zero of six were supported**. **This bot's entry
signal is built on exactly the refuted family.** Corroborating, on intraday data: *Structural
Limits of OHLCV-Based Intraday Signals in MNQ Futures* (arXiv 2605.04004) tested 14 signal
families over **947 trading days of five-minute data, 2021–2025**; gross returns ranged 0.07 to
1.50 points against a 2-point friction assumption; **none of the fourteen met all deployment
criteria**, and the best breakout candidate reached only T=1.50 against a 2.0 threshold. Its
named failure mode — one strong year masking two flat or negative ones — is precisely what
happened to this project's opening-window and range-gate findings across sessions.

**Order-book imbalance predicts, but not past costs (A/B).** Limit-order-book imbalance is
consistently among the most informative features for short-horizon direction, with forecast
accuracy peaking at roughly **3–10 second** horizons. The consistent finding, however, is that
the expected value of buying and selling back on those forecasts **does not beat the bid-ask
spread plus fees**. This is directly relevant now that the project records real best-5 depth:
the feature is genuine, and the reason it will not rescue this strategy is the same 0.884-point
bar as everything else.

### 5.2 Grade B — mechanism sound, effect size soft

**Stop-loss clustering and liquidity sweeps.** Osler (2003) documents empirically that
stop-loss orders cluster at round numbers and around prior swing highs/lows, and Harris (2003)
and Taylor (2005) describe institutional tactics that push price through such clusters and then
reverse. The clustering is well evidenced. **The intent is not.** Most of what retail calls a
"stop hunt" is the mechanical consequence of liquidity being concentrated where everyone put
their stops — order flow seeks liquidity because that is where it can execute, not because
anyone targeted you. **Actionable form of the true part:** a stop placed just beyond an obvious
swing high/low or a round number sits in a queue with thousands of others and will be reached
more often than its distance from price implies. This bot's stops (2.5–7 points on an option)
are not placed at structural levels at all, so it is largely exposed to the *generic* version
of this — its stops are simply very close — rather than the targeted version.

**Expiry-day time decay is brutal for buyers in the afternoon.** Practitioner measurement
reports an ATM option losing 70–80% of remaining extrinsic value between roughly 13:00 and
15:00 on expiry day. Direction is unambiguous; the specific percentages are industry-sourced,
not peer-reviewed. **Cross-check against this project's own data:** my measurement finds mean
forward return of −0.235 points at a 300-second horizon versus −0.002 at 60 seconds, i.e.
roughly −0.047 points/minute of bleed. Over the bot's **47.2-second mean hold** that is
−0.037 points ≈ **₹2.40 per trade.** This independently confirms the existing memory note that
**theta cannot explain the MFE/MAE asymmetry** — at a 47-second hold, decay is 4% of the cost
of a trade. Do not build a theta story.

**Dealer gamma and pinning.** The mechanism — market makers short near-the-money gamma into
expiry must sell rallies and buy dips to stay delta-neutral, compressing range near
heavily-traded strikes — is standard and correct. Its *predictive* value is much weaker than
the mechanism's popularity implies.

### 5.3 Grade C — folklore; do not build on it

- **"Max pain" as a price target.** The underlying finishes within one strike of max pain
  roughly 20–30% of the time for major indices. That is better than uniform-random across all
  strikes, but max pain sits near the current price *by construction* — open interest
  concentrates at the money — so most of the apparent gravity is an artefact of how OI
  distributes, not a force. As usually stated ("price gets pulled to max pain") it is
  unfalsifiable, because any expiry within a couple of strikes is scored as a hit.
- **"Smart money" / ICT-style liquidity-sweep narration.** The vocabulary (liquidity grabs,
  order blocks, sweeps) describes real order-flow phenomena, but the claims are stated after
  the fact, on charts selected after the fact, with no out-of-sample test and no effect size.
  Every practitioner source I found on this topic offered zero statistics. There is nothing
  here to implement and nothing to falsify.
- **"Brokers hunt your stops."** In an exchange-matched, SEBI-supervised order book with
  central limit-order-book matching, an Indian equity-derivatives broker does not control the
  price path. The academic modelling that shows a price-path controller *could* maximise stop
  losses applies to dealing-desk/CFD structures, not to NSE/BSE derivatives.
- **PCR and OI-change directional signals.** No source I found provides a tested,
  cost-inclusive expectancy. This project's own data reinforces the caution: on 2026-09-07,
  243 of 246 consecutive-tick OI comparisons were exactly zero, so the existing ±1%
  classification cannot fire regardless of the signal's merit.

### 5.4 The honest summary of §5

The strongest, best-evidenced institutional-trap findings are **not** about anyone targeting
this account. They are structural:

1. The profitable counterparty is algorithmic and institutional, by the regulator's own
   accounting (₹44,000 crore prop, 99% algo).
2. Cost, not directional wrongness, is the largest identified single drain — ₹25,000 crore
   across retail in FY26, and **84% of this bot's own net loss**.
3. The signal family this bot uses has been formally refuted under multiple-testing correction.
4. High turnover on small capital is the single strongest documented correlate of loss, and
   this bot's turnover is 67× capital.

None of that requires anyone to be hunting you. **The trap is that the instrument is a
zero-drift lottery with a flat fee, and the fee is charged per opinion.**

---

## 6. What I measured myself — method, and what it cannot support

**Source.** `core/data/trades.db`, opened read-only (`mode=ro`). 98,434 option tick rows across
11 contracts and 7 sessions (2026-08-26 … 2026-09-07); 144 closed trades.

**Method.** Per contract, sample entries on a 30-second grid with premium ≥ ₹40. For each, walk
the tick path forward to a 300-second cap and resolve the first of TP / SL / timeout. Cost
applied via `research.costs.CostModel`. Conditioning features use a strictly causal 60-second
lookback — no feature consults a tick at or after the entry second.

**What it cannot support:**

- **Samples overlap heavily.** A 30-second grid over a 300-second horizon shares up to 90% of
  the path between consecutive samples. Reported ±1.96 SE bands are therefore **too narrow**;
  effective n is well below nominal n. No block bootstrap was run. Treat every CI here as an
  optimistic lower bound on uncertainty.
- **11 contracts, 7 sessions, 2,968 windows.** Overwhelmingly CE (2,781 vs 168 PE) — the
  cross-direction moneyness defect means PE was almost never subscribed, so **every PE number
  here is indicative only.**
- **~27 conditioning cells were tested.** At α=0.05 that is ~1.4 expected false positives. No
  cell is presented as a finding; the §4.3 hypothesis is offered *because* it has a mechanism
  and matches external evidence, not because of its interval.
- **The TP/SL simulation is optimistic.** It fills at LTP with no slippage, no queue, no
  partial fills, and no rejected order. Real execution is worse than every number above.
- **The 0.246% real-spread figure is one contract over two minutes on one afternoon.** It is
  the only real measurement that exists; it is not a session constant and must not be treated
  as one.
- **This is not a controlled experiment.** It is a description of what the recorded book
  offered. It cannot establish that any change would improve anything — only that certain
  changes cannot possibly be sufficient.

**Where I agree with the baseline, from independent computation:** findings 1, 2, 3, 4 and 6
all reproduce. **Where I extend it:** the reason no exit geometry works is that gross
expectancy is ~0 *before* costs, so the entire (TP, SL) surface is bounded above by ~zero;
and the required entry edge falls from +51% to +24% relative if the flat fee moves — which is
the largest single lever available that does not require finding an edge. **Where I add a cost
the project was not counting:** ₹23.27/round trip of spread crossing, 68% as large as the
entire ₹20→₹5 brokerage saving.

**Finding 5 (entry worse than arbitrary timing) — status.** My data is consistent with it and
supplies a candidate mechanism (the bot's momentum/breakout shape lands on the worst-measured
cell), but I did not replicate the head-to-head test and round 3 correctly downgraded it to
*suggestive* at p = 0.02–0.14 depending on design. It stays suggestive.

**Finding 7 (SEBI RoCE, buyers −114% / sellers +1%).** I could **not** verify the specific
−114% and +1% figures in any accessible source. What is verifiable and current: SEBI's FY26
study reports option sellers as the only strategy group with a *positive median return on
capital employed*, and buyers as substantially worse — the direction and the ordering hold, but
**the two specific percentages should be re-sourced to the original SEBI study PDF before being
cited again.**

---

## 7. Sources

**Costs, brokerage, contract specifications**
- Zerodha charges — https://zerodha.com/charges/
- Shoonya (Finvasia) pricing — https://shoonya.com/pricing
- m.Stock pricing — https://www.mstock.com/pricing
- STT Budget 2026 change (0.10% → 0.15% options sell side, w.e.f. 1 Apr 2026) — https://www.icicidirect.com/futures-and-options/articles/stt-changes-in-budget-2026-what-f-o-traders-need-to-know
- STT rates overview — https://cleartax.in/s/securities-transaction-tax-stt
- NSE lot-size revision effective Jan 2026 (NIFTY 75→65, BANKNIFTY 35→30, FINNIFTY 65→60, MIDCPNIFTY 140→120) — https://www.venturasecurities.com/blog/fo-lot-size-changes-in-india-what-traders-need-to-know-effective-jan-2026/
- NSE circular, lot-size revision — https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf
- SENSEX lot size 20, BSE weekly Thursday — https://www.sahi.com/blogs/nifty-lot-size-2026-bank-nifty-sensex

**Margin and capital**
- NIFTY futures/spread margin, 2026 — https://onetradejournal.com/glossary/span-margin
- Zerodha margin calculator — https://zerodha.com/margin-calculator/Futures/
- Capital needed for NIFTY options, 2026 — https://niftywise.org/blog/how-much-capital-do-you-need-for-nifty-options-trading

**Regulation and market structure**
- SEBI expiry-day realignment, NSE Tuesday / BSE Thursday from 1 Sep 2025 — https://www.kotakneo.com/news/market-news/sebi-to-end-thursday-expiry/
- One weekly expiry per exchange (circular Oct 2024, effective 20 Nov 2024) — https://www.icicidirect.com/research/equity/finace/sebi-clears-expiry-day-clash-between-nse-and-bse
- SEBI retail algo framework, circular SEBI/HO/MIRSD/MIRSD-PoD/P/2025/0000013 of 4 Feb 2025; 10 orders/sec threshold; static IP; full applicability April 2026 — https://www.icicidirect.com/futures-and-options/articles/algorithmic-trading-new-rules-by-sebi-nse-retail-participation-with-safety-and-structure
- SEBI 2025 algo framework, independent evaluation — https://www.ijllr.com/post/sebi-s-2025-framework-for-safer-retail-participation-in-algorithmic-trading-an-evaluation-of-invest

**SEBI FY26 derivatives study**
- Full quantitative summary (87.7% losing, ₹91,685 cr, ₹25,000 cr costs, 59% 0DTE, 99% algo, 70% of losses from <₹1 lakh portfolios) — https://taxguru.in/sebi/sebi-studies-key-trends-retail-participation-trading-behaviour-profitability-equity-derivatives.html
- Prop ₹44,000 cr / FPI ₹14,000 cr gross profits — https://www.business-standard.com/markets/capital-market-news/prop-traders-stay-biggest-derivatives-winners-as-retail-continues-to-lose-126082101242_1.html
- Headline coverage — https://www.businesstoday.in/markets/story/rs91685-cr-lost-88-of-individual-traders-lost-money-in-fy26-options-drove-92-of-losses-550474-2026-08-21
- Explainer — https://openthemagazine.com/business/sebi-fo-loss-study-explained-why-9-in-10-retail-traders-lost-91685-crore-in-fy26

**Institutional behaviour and manipulation**
- SEBI interim order vs Jane Street, ₹4,843.57 cr, 18 expiry days — https://blogs.law.ox.ac.uk/oblb/blog-post/2025/07/jane-street-and-expiry-day-trap-unpacking-sebis-crackdown-algorithmic
- ECGI analysis of the same — https://www.ecgi.global/publications/blog/expiry-day-and-the-governance-of-algorithmic-trading-the-jane-street-episode
- Reporting — https://www.cnbc.com/2025/07/04/indian-regulator-bars-us-trading-firm-jane-street-from-accessing-securities-market.html
- Spoofing/layering under PFUTP 2003, Indian enforcement — https://www.mondaq.com/india/international-trade-investment/1624344/order-book-manipulation-spoofing
- Spoofing enforcement overview — https://www.finseclaw.com/article/ghosts-in-the-order-book

**Signal falsification literature**
- *Retail Trader's Ruin: An Anatomy of Popular Signal Failure* (oscillator family REFUTED) — https://arxiv.org/html/2607.20093
- *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures* (14 families, 947 days, none deployable) — https://arxiv.org/abs/2605.04004
- ORB profitability assessment (Umeå working paper) — http://www.econ.umu.se/ueslpnr/ues845.pdf

**Microstructure**
- Easley, López de Prado, O'Hara, *From PIN to VPIN: an introduction to order flow toxicity* — https://www.quantresearch.org/From%20PIN%20to%20VPIN.pdf
- Order-book imbalance: predictive at 3–10s, does not beat spread + fees — https://www.emergentmind.com/topics/order-book-imbalance-obi
- Order-book filtration and directional signal extraction at high frequency — https://arxiv.org/html/2507.22712v1
- Limit-order placement and adverse selection risk — https://arxiv.org/pdf/1610.00261
- Schwarz et al., *The "Actual Retail Price" of Equity Trades*, Journal of Finance 2025 — https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13467
- Retail trader sophistication and market quality (brokerage outages) — https://www.sciencedirect.com/science/article/abs/pii/S0304405X22001726

**Expiry-day and gamma dynamics (grade B/C)**
- Max pain: within one strike ~20–30% of the time; OI-clustering artefact caveat — https://fattail.ai/options-max-pain/
- 0DTE decay concentration in the afternoon — https://www.sahi.com/blogs/how-to-trade-options-on-expiry-day
- Cboe 0DTE positioning and market impact — https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact
- Stop clustering (Osler 2003, Harris 2003, Taylor 2005 as cited) — https://legalclarity.org/stop-hunting-in-trading-mechanics-laws-and-strategies/

---

*Research only. No code, config or `.env` was modified. All database access read-only
(`mode=ro`). No broker login. No `.env` value read, printed or copied.*
