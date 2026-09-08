# Strategy sources — open-source code, published backtests, and the delta/spread break-even

**Date:** 2026-09-08 (NIFTY weekly expiry, Tuesday)
**Scope:** find implementable, evidence-backed intraday strategies that could clear the
established bar of **+0.884 gross option points per trade**; test the "trade higher delta"
hypothesis quantitatively; verify the 2026 margin position at ₹30,000.
**Method:** web/GitHub research plus original measurement on this project's own
`core/data/trades.db` (read-only, `mode=ro`).
**Nothing was modified.** One file written: this one. No code, no config, no `.env` read or
printed, no git operation, no broker order API.

Reads on top of `strategy_research_20260908.md` and `backtest_data_20260908.md` and does not
re-litigate their findings except where I have a **correction**, which is flagged ⚠.

---

## 0. The three things that matter most in this report

1. ⚠ **`backtest_data_20260908.md` §2's "hard boundary" is wrong.** Expired NIFTY weekly option
   chains *are* reachable, at 1-minute granularity, through Upstox's `expired-instruments` API
   family. That endpoint family did not exist when the project's earlier survey was done and it
   is not the public v3 endpoint that was probed. This converts "13 sessions, one chain" into
   ~6 months (2 years announced) of NIFTY weekly option 1-minute data including every expiry
   day. **It is the single highest-value action in this report**, and it is a prerequisite for
   falsifying almost everything else. §1.1.

2. ⚠ **"Higher delta halves the required spot move" is false, and the direction of the error
   matters.** Only the flat brokerage (0.726 of the 1.071 friction points at ₹20) is fixed in
   rupees. STT, exchange charge, GST-on-those and — dominantly — the bid/ask spread are all
   **proportional to premium**, and premium grows roughly linearly with ITM depth while delta
   saturates at 1. Measured on this project's own real order book, the optimum is
   **delta 0.70–0.83**, worth only 10–20% off the required spot move, and the **break-even is
   delta ≈ 0.91**: past that, deep-ITM is *strictly worse than just trading ATM*. At a ₹5
   broker the optimum collapses to ATM and the ITM advantage disappears entirely. Today's
   accidental delta-0.9 selection sits exactly on the break-even. §3.

3. **In option points the bar goes UP with delta, not down.** Friction at 0DTE 12:00, ₹20
   broker: **1.00 points at delta 0.50 → 1.63 at delta 0.90 → 2.31 at delta 0.99.** The
   0.884-point bar in the earlier report was computed at a ₹145 premium. On a delta-0.9 0DTE
   contract the equivalent bar is **1.63 gross points (₹106/lot)** at Zerodha rates, or 1.09
   points at a ₹5 broker. Any signal evaluated today must be scored against that number, not
   0.884.

---

## 1. The candidates worth implementing, ranked

Ranked by (expected effect) × (probability the evidence survives) ÷ (implementation risk).
Every one names how to kill it.

### #1 — Buy the real history: Upstox `expired-instruments` (enabler, not a strategy)

**Mechanism.** Every conclusion in this project is currently drawn from 4–13 sessions on one
option chain, because expired contracts were believed unreachable. They are not.

**The evidence, and what it actually is.**
Upstox publishes four endpoints under `/v2/expired-instruments/`:
`expiries`, `option/contract`, `future/contract`, and
`historical-candle/{expired_instrument_key}/{interval}/{to}/{from}` — the last returning
1/3/5/15/30-minute and daily OHLC **for contracts that have already expired**
([docs](https://upstox.com/developer/api-documentation/expired-instruments/),
[candle endpoint](https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/),
[launch announcement](https://upstox.com/developer/api-documentation/announcements/expired-instruments-api/)).
Upstox staff, in their own developer forum, state: *"OHLC data for expired contracts is
available from the date the first trade occurred for that contract up to its expiry date"*,
currently *"the last six months"*, with *"up to 2 years of data for expired contracts in the
future"*
([thread](https://community.upstox.com/t/historical-availability-retrieval-limit-per-query-for-expired-options-contract/9245)).

This is **verifiable from code, not a README claim**: an independent open-source client
implements exactly these four calls —
[`rajmaurya0904/bhav`](https://github.com/rajmaurya0904/bhav) (26★, pushed 2026-07-19),
`bhav/data/upstox_client.py` lines 40–163, with the endpoint sequence documented in its own
docstrings. A second tool,
[`marketcalls/ExpiryTrack`](https://github.com/marketcalls/ExpiryTrack) (17★, 2026-07-10),
exists solely to bulk-download from the same family.

**Caveat I could not resolve.** The Upstox docs list error `UDAPI1149` for a missing
**Upstox Plus** subscription on this endpoint family, and Upstox's own Plus page lists "OHLC
data for expired contracts" as a Plus feature. **I could not find the Plus price** and am not
going to guess it. Verify before planning around it. There is also an OAuth access token
required (this is *not* the keyless public v3 endpoint the project already probed).

**Expected gross edge:** none directly. What it buys is **statistical power**: ~120 expiry
days instead of 1, on the actual instrument the bot trades.

**How to falsify:** fetch the 2026-09-02…09-04 window for the 08SEP26 chain through the
expired route and reconcile against `data/historical/candles.db`, which already holds the same
minutes from Angel. The project's own Angel-vs-Upstox index cross-check reconciled to
**100.0% identical closes, max |diff| 0.00** — apply the same test. If option closes do not
reconcile to the paisa, the route is not the same book and the finding dies.

**Risk:** low technically (4 REST calls, `bhav`'s client is a working reference), medium
commercially (paid tier, unverified price).

---

### #2 — Stop paying a fixed toll to harvest a 1.7-point excursion: lengthen the hold

**Mechanism.** Round-trip friction is **fixed** (₹69.63 ≈ 1.071 points at ₹20 brokerage plus
the crossed spread) but the available excursion grows roughly as √t. The bot's mean hold is
**47.2 seconds**, where friction is 62% of the whole mean favourable excursion. It is
structurally impossible to win that.

**The evidence — measured here, on this project's ticks.** 1,486 arbitrary entries on a
60-second grid, premium ≥ ₹40, over 20 contract-sessions / 98,434 ticks:

| horizon | n | mean MFE (pts) | mean MAE (pts) | MFE/MAE | friction as % of MFE |
|---|---|---|---|---|---|
| 1 min | 1,486 | 1.715 | 1.928 | 0.890 | **64%** |
| 2 min | 1,468 | 2.411 | 2.734 | 0.882 | 46% |
| 5 min | 1,422 | 3.725 | 4.348 | 0.857 | 31% |
| 10 min | 1,343 | 5.131 | 6.097 | 0.841 | 25% |
| 15 min | 1,268 | 6.157 | 7.252 | 0.849 | 23% |
| 30 min | 1,080 | 7.899 | 9.844 | 0.802 | **21%** |
| 60 min | 795 | 10.674 | 11.959 | 0.893 | 20% |

(friction = 1.071 fixed points + the measured decay term of §2.1 below, at the ₹145.55 mean
premium.)

**Why this matters, in the only unit that counts.** With a symmetric TP=SL=X ladder and no
directional edge, net expectancy is positive iff hit rate `p > 0.5 + friction/(2X)`. Setting
X at the horizon's own mean MFE:

| hold | X ≈ MFE | friction (pts) | **required hit rate** |
|---|---|---|---|
| 1 min | 1.7 | 1.09 | **82.1%** |
| 5 min | 3.7 | 1.19 | 66.0% |
| 30 min | 7.9 | 1.67 | **60.6%** |
| 60 min | 10.7 | 2.10 | 59.8% |

**Lengthening the hold from 47 seconds to 30 minutes cuts the required directional accuracy
from ~82% to ~61%** — a 21-point reduction in the bar, with no new signal, no new instrument
and no new capital. That is larger than every other lever in this report.

**⚠ Why the obvious counter-test does not refute this.** I ran the ladder sweep at long
horizons and it looked terrible — gross expectancy −0.10 pts at TP3/SL2/300s degrading to
−3.78 pts at TP30/SL30/7200s, actual hit rate falling 38.6% → 34.7%. **That result is
confounded and must not be quoted.** The sampled book is ~95% CE and NIFTY fell **−218.6
points net across the four recorded sessions** (+56.5 / −124.5 / −13.2 / −137.4). Regressing
option change on concurrent spot change through the origin:

| horizon | Δ option | Δ spot | realised β | delta-explained | residual (decay) | residual/min |
|---|---|---|---|---|---|---|
| 1 min | −0.098 | −0.26 | 0.518 | −0.137 | +0.039 | +0.039 |
| 5 min | −0.252 | −0.30 | 0.448 | −0.136 | −0.116 | −0.023 |
| 30 min | −1.835 | −2.22 | 0.495 | −1.098 | −0.738 | −0.025 |
| 60 min | −2.011 | −1.99 | 0.494 | −0.985 | −1.027 | −0.017 |

**~55–60% of the long-horizon bleed is a directional bet that lost, not a horizon effect.**
The residual — genuine time decay — is **−0.017 to −0.025 points/minute**, i.e. 1.0–1.5 points
per hour on a ₹145 option. That is real and it is why the friction column above rises with
time, but it does not overturn the MFE arithmetic.

**How to falsify.** Re-run the ladder sweep on a **delta-balanced** sample (equal CE and PE
weight, or β-neutralised by subtracting `β × Δspot` from each outcome). If the required-hit-rate
advantage of long holds survives β-neutralisation but the *realised* hit rate still falls, the
item dies and the reason is that the option book mean-reverts faster than √t. Prerequisite: PE
contracts must actually be subscribed — the cross-direction moneyness defect means the current
record has 2,781 CE windows against 168 PE.

**Risk.** Medium. It is a change to the exit ladder and the trades-per-day cap, not to the
signal — but a 30-minute hold on 0DTE crosses into the terminal gamma regime (§4) and the
existing soft-loss/early-loss branches fire at 45–75 seconds and would have to be removed, not
merely retuned. That is a bigger edit than it sounds.

---

### #3 — GTBR-conditioned intraday momentum: the only non-folklore "gamma blast"

**Mechanism.** Market makers short gamma must delta-rebalance in the direction of the move —
but *only once the move is large enough that gamma loss exceeds theta profit*. The threshold is
computable: the **gamma-theta break-even range (GTBR)**. Inside it, there is no forced hedging
and no gamma-driven momentum. Outside it, momentum is amplified.

**The evidence — an actual academic result with out-of-sample validation.**
*Where does gamma hedge drive the intraday market move?* (June 2024, AFA working paper,
[PDF](https://afajof.org/management/viewp.php?n=129472)) regresses the last-30-minute return on
the first-30-minute return with a `D_GTBR_Hit` interaction, OptionMetrics Ivy DB US data,
Newey-West t-statistics, firm fixed effects. Findings, quoting the paper:

- Breaking the GTBR is significant **beyond** the short-gamma dummy already documented by
  Baltussen et al. (2021) — the coefficient *rises* from **0.96 to 1.18 with larger
  t-statistics** after adding earnings and implied-volatility controls.
- *"intraday stock momentum via MM's gamma imbalance does not exist even when they hold a
  short gamma position, as long as the underlying stock does not reach these breakeven
  points."*
- Out-of-sample R² (Campbell–Thompson) is **positive at every underlying**, and highest in the
  specification containing GTBR.

**Why this is the interesting candidate for *this* bot specifically.** The project's own
measurement found that **buying strength is the worst-priced entry available** (top quintile
of the 60-second range: −0.359 pts; 60s momentum > +1.5: −0.261 pts) and that the bot's
EMA/RSI/volume-spike stack is a momentum detector pointed at that cell. The GTBR paper offers a
mechanism under which that is exactly the expected result: **unconditional momentum has no
edge; momentum conditional on the hedging threshold does.** The bot has been trading the
unconditional version. And as of 2026-09-07 the mode-3 packet supplies real per-strike open
interest, so the dealer-gamma input finally exists in this feed.

**Expected gross edge:** ⚠ **I cannot convert the coefficient to option points.** The paper
states coefficients are "multiplied by 100" but the accessible text does not fix whether the
underlying returns are decimals or percent, and the two readings differ by 100×. Under the
conservative reading (β = 0.0096–0.0118 on decimal returns), a 1% NIFTY morning move predicts
~1 bp ≈ 2.3 index points of extra afternoon move ≈ 1.15 option points at delta 0.5 — *at or
just below* the friction bar, and requiring one trade per day. **Do not size this on my
estimate.** Two further transfer risks: it is US **single stocks**, not an index, and it uses
30-day standardised ATM greeks, not 0DTE.

**How to falsify on this project's data.** Compute a daily NIFTY GTBR from ATM gamma and theta
(the harness already solves greeks; `research/backtest/harness.py` enriches delta with a real
expiry). Then split the existing 2,968 arbitrary-timing windows and the 144 recorded trades
into GTBR-breached and not-breached at the entry instant. **The prediction is specific and
therefore killable: the −0.261-point momentum cell must split, with the not-breached subset
worse than −0.261 and the breached subset materially better.** If the two subsets are
statistically indistinguishable, the mechanism is absent from this book and the item is dead.
Pre-register the split in `research/ledger.py` before looking. n is small; expect this to be
underpowered until #1 lands.

**Risk.** Low to test (research-layer only), high to get right. Do not put it in the trading
path before #1 supplies enough expiry days to have power.

---

### #4 — Sell premium instead of buying it (best evidence in this report; blocked by capital)

**Mechanism.** Every measured drag on the buyer is a credit to the seller. On this project's
own book, the buyer's MFE/MAE ratio is **0.80–0.89 at every horizon from 1 to 60 minutes** —
it never once exceeds 1. For a symmetric ladder the seller's outcome distribution is the
buyer's, negated.

**The evidence, graded.**

- **A.** SEBI FY26 derivatives study: option *sellers* are the **only strategy group with a
  positive median return on capital employed**; ~97% of individual traders are predominantly
  buyers; 87.7% of individuals lost money; ₹91,685 crore aggregate net loss
  ([summary](https://taxguru.in/sebi/sebi-studies-key-trends-retail-participation-trading-behaviour-profitability-equity-derivatives.html)).
- **A/B.** Vilkov, *0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing* (2026),
  with a **public replication package**:
  [github.com/vilkovgr/0dte-strategies](https://github.com/vilkovgr/0dte-strategies) (54★, 21
  forks, pushed 2026-08-26). SPXW Sept-2016…Jan-2026, 10:00 ET entry to 16:00 close, seven
  multi-leg structures, **three cost layers** (mid-quote, half-spread per leg, half-spread plus
  0.5 bp slippage). Result: individual net Sharpes *"typically range from negative to 0.2"*;
  the conditional put-ratio-spread reaches **gross SR 1.18, net 0.93**, and diversified
  equal-weight baskets **~0.82 net**. Conclusion in the paper's own words: unconditional 0DTE
  exposure is *"difficult to justify as a standing allocation once one accounts for realistic
  execution and downside capital usage"*. **Every positive-Sharpe structure is a spread or a
  ratio — i.e. requires margin.** Verifiable from code; the data (Cboe 30-minute SPXW bars +
  ThetaData) is paid, so full reproduction is not free.
- **B, India-specific and cost-inclusive.** Zerodha's *In The Money*
  [ORB study](https://inthemoneybyzerodha.substack.com/p/how-to-trade-opening-range-breakout),
  NIFTY weekly options, Jan 2022 – Feb 2026, strike chosen at ~₹200 premium, 09:15–11:15
  opening range, 20% stop, **post-brokerage and taxes with 0.2% slippage**. Option **buying**:
  win rate ~48%, **max drawdown ~45%**, equity curve breaks down after Jan 2024. Option
  **selling**, identical rules mirrored: **max drawdown ~6%**, *"much smoother"*, **all years
  in the dataset profitable**. Same signal, same instrument, same costs, opposite side — a
  clean natural experiment.
- ⚠ **My own mirror-ladder number is NOT evidence and I am withdrawing it before anyone
  quotes it.** Inverting the buyer's ladder gives the seller +3.78 gross points at TP/SL=30
  over a 2-hour hold. §1.2's decomposition shows **55–60% of that is a short-delta bet in a
  market that fell 218.6 points**, not theta harvested. The defensible part is the residual:
  **1.0–1.5 option points per hour of decay** on a ₹145 near-ATM contract.

**Why it is blocked, with the number.** SEBI's circular of 1 October 2024 levies an
**additional Extreme Loss Margin of 2%** on short index option contracts **expiring that day**,
effective 20 November 2024, applying both to positions open at start of day and to new
same-day-expiry shorts
([Zerodha](https://zerodha.com/z-connect/business-updates/sebis-new-rules-for-index-derivatives-heres-whats-changing),
[circular SEBI/HO/MRD/TPD-1/P/CIR/2024/132](https://www.cse-india.com/upload/upload/Oct_011024.pdf)).
At the spot recorded on 2026-09-07 (23,760) and the Jan-2026 lot of 65:

> **2% × 65 × 23,760 = ₹30,888 of ELM alone, before any SPAN, on a single short NIFTY leg,
> on expiry day.**

The account holds ₹27,210 of equity. **Today, no short NIFTY leg of any kind — hedged, spread,
ratio or naked — is takeable.** And because SEBI simultaneously raised the *minimum contract
value for index derivatives to ₹15–20 lakh*, the same 2% lands at ₹30–40k on **every** index:
BANKNIFTY (30 × ~54,000), SENSEX (20 × ~80,000), FINNIFTY, MIDCPNIFTY. There is no
small-lot index that escapes it — the notional was deliberately normalised.

On a **non**-expiry day a vertical spread is cheaper but still out of reach: a June-2026
BANKNIFTY bull spread quote is **~₹33,500 margin** for ~₹12,510 of debit
([Business Standard](https://www.business-standard.com/markets/news/nifty-bank-strategy-how-to-use-a-bull-spread-for-june-26-expiry-decoded-125060600089_1.html)),
consistent with the project's existing ~₹31,500 July-2026 NIFTY figure and the ~₹34,400
exposure floor. **The project's finding stands, verified against 2026 rules, and is now
strictly worse on expiry day than previously recorded.**

Intraday-margin products do not change it: peak-margin reporting means an intraday short
carries essentially the overnight requirement, and there is no MIS multiplier route. Single
stock derivatives are not an escape either — minimum contract value was raised to **₹7.5 lakh**
and SEBI removed the expiry-day margin benefit for single-stock derivatives in February 2026
([BusinessToday](https://www.businesstoday.in/markets/story/sebi-ends-expiry-day-margin-benefit-for-single-stock-derivatives-to-curb-risk-514876-2026-02-05)).

**How to falsify:** run Zerodha's own basket margin calculator on a 1-lot NIFTY 50-point-wide
vertical for the next non-expiry session and read the number. If it comes back under ₹27,000
this item unblocks and jumps to rank #1. I could not query it (no login, read-only mandate), so
**this is the one number in the report that should be checked by hand before any capital
decision.**

**Honest ranking note:** this is #1 by evidence quality and #4 by implementability. It is
listed so that the capital number, not a belief about strategy, is what closes it.

---

### #5 — Strike selection at delta 0.70–0.83 (marginal, cheap, dies at a ₹5 broker)

**Mechanism.** The flat brokerage is the only cost component a higher delta amortises. §3 works
this out completely.

**Effect size:** at ₹20 brokerage and a spread proportional at the measured 0.239% of premium,
moving from ATM to the optimum reduces the required spot move by **10.0% (09:30) / 14.0%
(12:00) / 20.5% (14:00)** on 0DTE. At a ₹5 broker the optimum *is* ATM and the gain is ≤2%.

**How to falsify — and this is the measurement the project is one config change away from
being able to make.** Subscribe three ITM strikes (roughly delta 0.7 / 0.8 / 0.9) in mode 3
alongside the ATM and run `research/depth.py`'s `spread_profile` per strike for one full
session. §3.3 gives the kill threshold: **if the delta-0.90 strike's median spread exceeds
0.25% (09:30) / 0.32% (12:00) of its premium, deep-ITM is worse than ATM and the item is
dead.** The measured ATM spread is 0.239%, so the margin for error is one to two basis points
of premium. Also re-run `research/transmission.py` per moneyness bucket: if realised β does not
rise with moneyness as Black-Scholes delta predicts, the mechanism is absent from this book.

**Risk:** low. **Value:** a 10–20% improvement on a bar currently missed by ~100%. Do it
because it is cheap and because the *measurement* corrects a live misconfiguration, not because
it is going to make money.

---

## 2. Everything rejected, one line each

**Open-source repositories**

| repo | ★ / last push | why rejected |
|---|---|---|
| [buzzsubash/algo_trading_strategies_india](https://github.com/buzzsubash/algo_trading_strategies_india) | 65 / 2026-06-24 | Best-organised Indian option-selling code I found (straddles, strangles, iron-fly, Zerodha-live, MTM square-off) — but **zero backtests, zero equity curves, zero statistics anywhere in the repo**. Execution scaffolding, not evidence. Also: margin-blocked here regardless. |
| [aeron7/nifty-banknifty-intraday-data](https://github.com/aeron7/nifty-banknifty-intraday-data) | 98 / 2023-09-03 | Data dump only (1-min NIFTY/BANKNIFTY **spot**, no option premium), unmaintained 3 years, superseded by #1. |
| [umeshpalai/…-Banknifty-Straddle](https://github.com/umeshpalai/Algorithmic-Trading---Backtesting---Banknifty-Straddle-using-Python) | 23 / 2022-02-05 | Pre-dates every SEBI change that matters (lot size, weekly-expiry rationalisation, 2% expiry ELM, STT 0.15%). Its cost model cannot be right for 2026. |
| [rbhatia46/Intraday-1-Minute-data-Nifty-BankNifty](https://github.com/rbhatia46/Intraday-1-Minute-data-Nifty-BankNifty) | 13 / 2021-07-29 | Same: spot only, abandoned. |
| [aaryansinha16/AI-trader](https://github.com/aaryansinha16/AI-trader) | 62 / 2026-07-09 | Impressive architecture (tick replay, XGBoost + Q-learning, TimescaleDB) and an explicit "backtested results are not indicative" disclaimer — but **no published metrics at all**, only dashboard screenshots. Nothing to verify, and it is structurally this project with more layers. |
| [sushant1827/Trading_Strategies](https://github.com/sushant1827/Trading_Strategies), [Coderixc/BankNifty_Algo_Strategy](https://github.com/Coderixc/BankNifty_Algo_Strategy), [codblox/BANKNIFTY-Options-Backtest](https://github.com/codblox/BANKNIFTY-Options-Backtest), [TradeEasyWithMe/Best-Banknifty-Option-Strategy-100-Successful](https://github.com/TradeEasyWithMe/Best-Banknifty-Option-Strategy-100-Successful-Strategy-With-backtested-results) | 1–9 | Single-digit stars, no cost model, no out-of-sample split. The last one's repository *name* claims "100% Successful" — that is the tell. |
| [thunderscarf/SPX_0DTE_Options_Selling_Public](https://github.com/thunderscarf/SPX_0DTE_Options_Selling_Public) (2★), [brigoraoul/spy0dte-simulator](https://github.com/brigoraoul/spy0dte-simulator) (1★), [YichengYang-Ethan/0dte-strategy](https://github.com/YichengYang-Ethan/0dte-strategy) (11★), [jacksnydr/gamma-blast](https://github.com/jacksnydr/gamma-blast) (2★) | — | US 0DTE, all short-vol or GEX-triggered, **none publishes a result**. `gamma-blast`'s README states the rules ("range < 1% by 14:30, buy the straddle-structure break, 3:1 TP") and *no numbers whatsoever*. |
| [emlama/gex-backtesting](https://github.com/emlama/gex-backtesting) | 11 / 2026-03-03 | **Kept as a methodology reference, rejected as evidence.** Its design is the best I saw anywhere — pre-registered primary hypotheses, control experiments run *before* results are trusted, Fisher's exact, Benjamini-Hochberg FDR correction, bid-side entry — over 513 days of SPX 0DTE trades with quote-matched side classification. But **no outputs are committed and the notebooks carry no conclusions**: the framework is verifiable, the claim is untested in public. Worth reading `src/statistics.py` and `notebooks/02_multi_metric_backtest.ipynb` for how to structure §1.3's test. |
| [rajmaurya0904/bhav](https://github.com/rajmaurya0904/bhav) | 26 / 2026-07-19 | **Rejected as a strategy source, adopted as a reference client** (see #1). It ships an Indian cost model (STT incl. exercised-ITM, brokerage, exchange, SEBI, stamp, GST), futures-basis ATM selection, Monte-Carlo bootstrap bands — and **publishes no strategy results**. Its examples are demos. |
| [alphabench/raptorbt](https://github.com/alphabench/raptorbt), [mansoor-mamnoon/limit-order-book](https://github.com/mansoor-mamnoon/limit-order-book) | 41 / 17 | Infrastructure, not strategies. No Indian option support. |

**Signals and strategies**

| rejected | why |
|---|---|
| **"Gamma Blast" as commonly published** | The only statistics I found anywhere: *"a significant gamma move (>80 points on Nifty) occurred within 90 minutes in 11 of 13 sessions"*, self-described as *"proprietary tracking across 25+ expiry sessions"* ([marketseasy](https://marketseasy.in/blog/gamma-blast-nifty-options-expiry-day)). n=13, unaudited, no cost model, no out-of-sample, no definition of the trigger that a third party could reproduce. The mechanism is real (§1.3 keeps it); **this presentation of it is folklore.** |
| **Max pain as a price target** | Unfalsifiable as usually stated; the ~20–30% "within one strike" hit rate is mostly an artefact of OI concentrating at the money. Already rejected in `strategy_research_20260908.md` §5.3; nothing new found. |
| **PCR / OI-change directional signals** | No cost-inclusive tested expectancy exists in any source I reached, and on 2026-09-07 this project recorded 243 of 246 consecutive-tick OI comparisons as exactly zero — the ±1% classifier cannot fire. |
| **Raw order-book imbalance as an entry signal** | Genuinely predictive at 3–10 seconds and consistently found *not* to beat spread plus fees. Now that real best-5 exists, the honest use is as an **execution** filter (which side to post on), not a direction signal. See rejected-but-retained note below. |
| **Deep-ITM "stock replacement" as a cost trick** | §3 kills it quantitatively at delta > 0.91. |
| **arXiv 2507.04859, "F&O Expiry vs First-Day SIPs"** | Real paper, real significance (1-yr p=0.0018, 3-yr p=0.0149, 5-yr p=0.0019, Cohen's d up to 4.07 at 5 years, 22 years of NIFTY) — and it measures **multi-year SIP holding periods**, not an intraday effect. Cited here only so nobody mistakes it for expiry-day intraday evidence. It is not. |
| **Increasing lots to dilute the flat fee** | `research/costs.py`'s own `points()` shows cost falls with size — but the account can afford one, at most two, NIFTY lots. Arithmetically true, financially unavailable. |
| **BANKNIFTY / FINNIFTY / MIDCPNIFTY weekly strategies** | Weekly expiry abolished on those since 20 Nov 2024; one weekly index per exchange (NSE: NIFTY Tuesday, BSE: SENSEX Thursday). Any idea assuming a weekly BANKNIFTY is dead on arrival. |
| **SENSEX as a small-capital substitute** | Lot 20 but spot ~80,000 → the same ₹15–16 lakh notional by regulatory design. Identical 2% expiry ELM in rupees. No relief. |
| **MIS / intraday leverage on futures or short options** | Peak-margin reporting removed it. |
| **Broker migration ₹20 → ₹5 as a fix** | Halves the bar; does not clear it. Already correctly ranked #2 in `strategy_research_20260908.md`. ⚠ **New consequence found here:** at a ₹5 broker the optimal delta collapses to ATM (§3.2) — so if the broker moves, candidate #5 must be *reverted*, not kept. |

**Retained-as-diagnostic, not as a strategy:** order-book imbalance from the new best-5 feed.
Use it to decide whether a passive limit at the touch is likely to fill *and* whether that fill
is adversely selected — the falsification test already written in
`strategy_research_20260908.md` #5 is the right one and is unchanged by anything here.

---

## 3. The delta / spread break-even, with numbers

### 3.1 The measurement this rests on (original, from this project's own book)

`core/data/trades.db` holds real exchange bid/ask only for 2026-09-07 (mode-3 SnapQuote,
corroborated by non-zero OI per `research/depth.py`'s rule). Three CE strikes were subscribed at
different moneyness during that session. Per-row implied volatility and Black-Scholes delta
solved to the 2026-09-08 15:30 expiry:

| strike | n rows | window (IST) | spot | premium | ITM depth | IV | **delta** | **spread (pts)** | **spread %** |
|---|---|---|---|---|---|---|---|---|---|
| 23750 CE | 5,544 | 14:12–15:28 | 23,760 | 104.70 | +10 | 0.202 | **0.520** | 0.25 | **0.239%** |
| 23700 CE | 1,348 | 13:53–14:12 | 23,778 | 159.15 | +78 | 0.228 | **0.608** | 0.35 | **0.220%** |
| 23650 CE | 1,541 | 13:29–13:53 | 23,760 | 186.30 | +110 | 0.241 | **0.642** | 0.45 | **0.242%** |

**The single most important line in this section:** the spread in **points** rises with ITM
depth (0.25 → 0.35 → 0.45, +80%) while delta rises only +23%. As a **percentage of premium** it
is flat at **0.22–0.24%**. The whole break-even follows from that.

*Limits, stated before the conclusion:* three strikes, one afternoon, one session, sequential
(not simultaneous) windows, delta range 0.52–0.64 only, CE only, 1 DTE not 0 DTE. **I have no
measurement at all above delta 0.64.** Everything below extrapolates the flat 0.239% spread
outward, which is the *charitable* assumption — real deep-ITM books are thinner, and every
source says so ([liquidity by moneyness](https://www.sciencedirect.com/science/article/abs/pii/S0927538X24000659),
[ETH master's thesis on option bid-ask spreads](https://ethz.ch/content/dam/ethz/special-interest/mtec/chair-of-entrepreneurial-risks-dam/documents/dissertation/master%20thesis/MAS-Thesis_MateNemes_final_Jan13.pdf)).
If the real deep-ITM spread is wider than proportional, the conclusion below strengthens.

### 3.2 The model, and why "delta 0.9 halves the required move" is wrong

Required favourable **spot** move to break even on a round trip:

```
    S*(K) = [ F + k·P(K) + w(K) ] / Δ(K)
```

where `F` = flat brokerage incl. GST = **0.726 points/lot** at ₹20 (0.182 at ₹5);
`k` ≈ **0.00237** (STT 0.15% sell + exchange 0.03553% ×2 + GST on it + stamp + SEBI);
`w` = spread in points ≈ **0.00239 × P** as measured; `P` = premium; `Δ` = delta.

Only `F` is fixed in rupees. `k·P + w` is **proportional to premium** and totals
`κ = 0.00476·P`. Going deep ITM raises `P` roughly linearly with depth while `Δ` saturates at
1 — so the proportional term eventually swamps the delta gain. Differentiating gives the
optimum in closed form:

> **Γ / Δ² = κ / (F + κ·P)**

Numerically, at spot 24,000, IV 0.30, spread held at the measured 0.239%:

| case | broker | **optimal delta** | ITM depth | req. spot move | ATM req. | gain vs ATM |
|---|---|---|---|---|---|---|
| 0DTE 09:30 | ₹20 | **0.727** | 113 | 1.94 | 2.16 | 10.0% |
| 0DTE 12:00 | ₹20 | **0.769** | 105 | 1.72 | 1.99 | 14.0% |
| 0DTE 14:00 | ₹20 | **0.826** | 88 | 1.44 | 1.81 | 20.5% |
| 1DTE 13:30 | ₹20 | 0.657 | 114 | 2.41 | 2.53 | 4.7% |
| 0DTE 09:30 | **₹5** | **0.480** | −10 (ATM) | 1.07 | 1.08 | **0.1%** |
| 0DTE 12:00 | **₹5** | **0.529** | 10 | 0.91 | 0.91 | **0.2%** |
| 0DTE 14:00 | **₹5** | **0.605** | 25 | 0.70 | 0.72 | **2.2%** |

Sensitivity, 0DTE 09:30, ₹20 broker: at a **0.50%** spread the optimum falls to delta 0.652
(gain 4.6%); at **1.00%** it falls to delta 0.559 (gain 0.7%). At a ₹5 broker with a 1% spread
the optimum goes **OTM** (delta 0.32) — because there the proportional term dominates and the
cheapest premium wins.

**So the claim "delta 0.9 needs half the spot move of delta 0.5" would be true only if STT,
exchange charges, GST and the bid/ask spread were all zero.** They are 25% of the friction at
ATM and **56% of it at delta 0.90**.

### 3.3 The break-even number

**Indifference delta** — the deepest ITM strike still no worse than simply trading ATM, spread
held proportional at 0.239%:

| case | broker | ATM req. spot move | **indifference delta** | ITM depth | premium |
|---|---|---|---|---|---|
| 0DTE 09:30 | ₹20 | 2.16 | **0.913** | 254 | 261.6 |
| 0DTE 12:00 | ₹20 | 1.99 | **0.957** | 245 | 247.5 |
| 0DTE 14:00 | ₹20 | 1.81 | **0.991** | 223 | 223.3 |
| 1DTE 13:30 | ₹20 | 2.53 | **0.805** | 244 | 275.3 |
| 0DTE 09:30 | ₹5 | 1.08 | **none — ATM is optimal** | — | — |
| 0DTE 12:00 | ₹5 | 0.91 | 0.556 | 20 | 67.9 |
| 1DTE 13:30 | ₹5 | 1.45 | **none — ATM is optimal** | — | — |

> ### **The number: delta ≈ 0.91.**
> On 0DTE at Zerodha rates with the spread staying proportional at its measured 0.239%,
> a strike deeper than **delta 0.91** requires a *larger* favourable spot move than an ATM
> strike. That is the break-even. Today's ₹70–350 premium band puts the bot at
> **delta ≈ 0.9 — sitting on it, with no margin.**

**Stated the other way — how wide the deep-ITM spread may be before it kills the gain.** Take a
delta-0.90 strike and ask the largest spread at which it still beats ATM:

| case | broker | premium | statutory (pts) | **max tolerable spread** | as % of premium | × the measured ATM 0.239% |
|---|---|---|---|---|---|---|
| 0DTE 09:30 | ₹20 | 248.9 | 1.316 | 0.630 pts | **0.253%** | **1.06×** |
| 0DTE 12:00 | ₹20 | 190.8 | 1.178 | 0.618 pts | **0.324%** | 1.36× |
| 0DTE 14:00 | ₹20 | 125.4 | 1.023 | 0.606 pts | 0.483% | 2.02× |
| 1DTE 13:30 | ₹20 | 378.6 | 1.624 | 0.657 pts | **0.174%** | **0.73×** |
| 0DTE 12:00 | ₹5 | 190.8 | 0.634 | 0.184 pts | **0.096%** | **0.40×** |

**Read the top row.** In the morning, on 0DTE, at ₹20 brokerage, a delta-0.90 strike may carry
a spread only **6% wider** than the ATM's before it becomes the worse trade. Every source on
option liquidity says deep-ITM books are thinner than that margin, and the project has never
measured one. **This is the measurement to take today** (§1.5's falsification). The 1DTE row is
already negative — at 1 DTE a delta-0.9 strike would need a spread *27% narrower* than ATM,
which does not happen.

### 3.4 The consequence nobody has priced yet: the bar in option points goes up

The 0.884-point bar was computed at a ₹145.55 mean premium. Friction at 0DTE 12:00, spot
24,000, IV 0.30, spread 0.239%:

| delta | ITM depth | premium | **friction, ₹20 broker** | **friction, ₹5 broker** |
|---|---|---|---|---|
| 0.501 | 0 | 57.4 | 0.999 pts (₹64.97) | 0.455 pts (₹29.57) |
| 0.603 | 37 | 77.8 | 1.096 pts (₹71.26) | 0.552 pts (₹35.86) |
| 0.700 | 75 | 102.5 | 1.214 pts (₹78.91) | 0.669 pts (₹43.51) |
| 0.801 | 121 | 137.0 | 1.378 pts (₹89.59) | 0.834 pts (₹54.19) |
| **0.901** | **184** | **190.8** | **1.634 pts (₹106.23)** | **1.090 pts (₹70.83)** |
| 0.951 | 236 | 239.0 | 1.864 pts (₹121.15) | 1.319 pts (₹85.75) |
| 0.990 | 333 | 333.5 | 2.314 pts (₹150.40) | 1.769 pts (₹115.00) |

**A signal that must be worth 0.884 points on an ATM contract must be worth 1.63 points on
today's delta-0.9 contract at Zerodha rates.** What falls is the required *spot* move (2.16 →
1.85, −14%); what rises is the *option-point* bar (1.00 → 1.63, +63%). Any measurement taken
today and compared against 0.884 will be wrong by 85%.

### 3.5 How Indian traders actually handle this

The practitioner consensus is ATM for scalping and it is consistent with the arithmetic above:
gamma is highest at the money, ATM strikes have *"the highest liquidity and tightest bid-ask
spreads … often just ₹0.05–0.25 for Nifty options"*, and ATM shows the fastest intraday
response
([sahi.com moneyness guide](https://www.sahi.com/blogs/moneyness-in-options-trading-itm-atm-and-otm-explained-for-indian-f-and-o-traders),
[lemonn on ATM scalping](https://lemonn.co.in/blog/finance/atm-option-in-scalping-india-explained/)).
Deep-ITM is discussed in India as *positional* "stock replacement" — high delta, negligible
theta, stock-like behaviour — and the objection raised against it is always the **capital
requirement per lot**, not the spread
([optionstrading.org](https://www.optionstrading.org/blog/deep-in-the-money-options-explained/)).
The systematic convention in published Indian backtests is neither: it is a **fixed premium**,
e.g. Zerodha's ORB study *"select a strike whose premium is closest to ₹200"* — which
mechanically tracks a roughly constant delta as the underlying moves and is exactly what this
bot's ₹70–350 band is a crude, undeclared version of. If the band stays, **replace it with an
explicit delta target**: it is the same idea, stated in the unit that governs the arithmetic.

---

## 4. Expiry-day (0DTE) specifics for NIFTY — evidence vs folklore

Grading: **A** = regulator order / peer-reviewed / exchange data with an effect size ·
**B** = credible measurement, effect size soft · **C** = folklore.

**A — the structural facts.** 59% of Indian index-option turnover is 0DTE, 75% within one day
of expiry (SEBI FY26). NIFTY weekly expiry is **Tuesday** since 1 September 2025; SENSEX is
Thursday; one weekly index per exchange since 20 November 2024. An additional **2% ELM** on
same-day-expiry short options since 20 November 2024 (§1.4). Calendar-spread margin benefit
withdrawn on expiry day from 10 February 2025 — note this is *calendar* spreads (different
expiries); a **vertical** spread in the same expiry keeps its benefit, a distinction that most
Indian blog coverage blurs
([ICICI Direct](https://www.icicidirect.com/futures-and-options/articles/calendar-spreads-in-f-o-after-sebi-s-new-rules-what-you-need-to-know)).

**A — expiry-day index manipulation is adjudicated fact.** SEBI's interim order against Jane
Street (3 July 2025): 18 expiry days, ₹4,843.57 crore of unlawful gains, the profitable trade
being to **fade** an index level the firm had itself pushed
([Oxford Business Law Blog](https://blogs.law.ox.ac.uk/oblb/blog-post/2025/07/jane-street-and-expiry-day-trap-unpacking-sebis-crackdown-algorithmic)).
Direct implication: on expiry day, index direction is *not reliably information-bearing*, and a
momentum entry into an institutionally-driven leg is by the order's own description the losing
side.

**A/B — the terminal gamma regime.** The mechanism (short-gamma dealers forced to
delta-rebalance with the move) is standard and the AFA paper of §1.3 supplies the sharp,
testable version: **momentum appears only past the gamma-theta break-even range, and does not
appear inside it even when dealers are short gamma**, with positive out-of-sample R² at every
underlying. This is the only formulation I found that is both falsifiable and independently
validated. Its transfer risk to NIFTY 0DTE is real and unmeasured (US single stocks, 30-day
standardised greeks).

**B — premium decay dominates the afternoon.** Practitioner sources put an ATM option at 70–80%
of remaining extrinsic value lost between ~13:00 and 15:00 on expiry. Direction unambiguous,
percentages not peer-reviewed. **Cross-checked against this project's own book:** the residual
(non-directional) drift is **−0.017 to −0.025 points/minute** at 30–60 minute horizons — around
1.0–1.5 points per hour on a ₹145 contract. At the bot's **47-second** mean hold that is
**−0.02 points ≈ ₹1.30 per trade, under 2% of the cost of a trade.** The existing memory note
that *theta cannot explain the MFE/MAE asymmetry* is confirmed a second time from a second
angle. **Do not build a theta story for a 47-second hold.** It becomes a first-order term only
past ~15 minutes — which is precisely the tension inside candidate #2.

**C — pinning as a tradeable target.** The Indian academic literature on expiry effects
(volume spikes, pre-expiry dips, ARMA-EGARCH studies finding *no* effect on mean index returns)
documents volatility and volume effects, not a directional edge. I found **no** study
establishing an intraday *directional* edge on NIFTY expiry day specifically. Absence of
evidence, stated as such.

**C — "last-hour 500–1000 point moves", "hero-zero jackpots", TradingView gamma-blast
detectors.** Every quantitative claim I could find on these traces to a blog's own unaudited
tracking of 13–25 sessions. §2 rejects them by name.

---

## 5. Sources

**Open-source code**
- Vilkov, *0DTE Trading Rules* replication package — https://github.com/vilkovgr/0dte-strategies · annotated paper: https://github.com/vilkovgr/0dte-strategies/blob/main/docs/paper/paper-annotated.md · SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356
- `bhav` — NSE options backtester with expired-chain support and an Indian cost model — https://github.com/rajmaurya0904/bhav
- `ExpiryTrack` — bulk downloader for Upstox expired-instrument data — https://github.com/marketcalls/ExpiryTrack
- `gex-backtesting` — SPX 0DTE GEX toolkit; pre-registration + FDR methodology reference — https://github.com/emlama/gex-backtesting
- `algo_trading_strategies_india` — Indian option-selling execution code, no backtests — https://github.com/buzzsubash/algo_trading_strategies_india
- `AI-trader` — NSE F&O ML platform, no published metrics — https://github.com/aaryansinha16/AI-trader
- Rejected minor repos listed inline in §2.

**Academic / working papers**
- *Where does gamma hedge drive the intraday market move?* (June 2024) — https://afajof.org/management/viewp.php?n=129472
- Dim, Eraker & Vilkov, *0DTEs: Trading, Gamma Risk and Volatility Propagation* — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190
- *F&O Expiry vs First-Day SIPs: A 22-Year Analysis*, arXiv 2507.04859 (multi-year, not intraday) — https://arxiv.org/abs/2507.04859
- Kolm, Turiel & Westray, *Deep order flow imbalance* — https://www.researchgate.net/publication/372568099
- *Determining bid-ask prices for options with stochastic illiquidity* (moneyness/liquidity) — https://www.sciencedirect.com/science/article/abs/pii/S0927538X24000659
- Nemes, *Option Market Liquidity: an empirical study of option bid-ask spreads* (ETH) — https://ethz.ch/content/dam/ethz/special-interest/mtec/chair-of-entrepreneurial-risks-dam/documents/dissertation/master%20thesis/MAS-Thesis_MateNemes_final_Jan13.pdf

**Data access**
- Upstox Expired Instruments API — https://upstox.com/developer/api-documentation/expired-instruments/
- Upstox Expired Historical Candle Data — https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/
- Upstox launch announcement — https://upstox.com/developer/api-documentation/announcements/expired-instruments-api/
- Upstox staff on availability/limits — https://community.upstox.com/t/historical-availability-retrieval-limit-per-query-for-expired-options-contract/9245
- Upstox Plus — https://upstox.com/plus/

**Published India backtests**
- Zerodha *In The Money*, ORB on NIFTY weekly options, Jan 2022–Feb 2026, post-cost, 0.2% slippage — https://inthemoneybyzerodha.substack.com/p/how-to-trade-opening-range-breakout
- Zerodha *In The Money*, 45-DTE on NIFTY — https://inthemoneybyzerodha.substack.com/p/we-backtested-the-famous-45-dte-strategy

**Regulation and margin**
- SEBI circular SEBI/HO/MRD/TPD-1/P/CIR/2024/132, 1 Oct 2024 — https://www.cse-india.com/upload/upload/Oct_011024.pdf
- Zerodha explainer on that circular (2% expiry ELM, ₹15–20 lakh contract value, one weekly index) — https://zerodha.com/z-connect/business-updates/sebis-new-rules-for-index-derivatives-heres-whats-changing
- Calendar-spread benefit withdrawn on expiry day — https://www.icicidirect.com/futures-and-options/articles/calendar-spreads-in-f-o-after-sebi-s-new-rules-what-you-need-to-know
- Single-stock derivatives expiry-day benefit ended, Feb 2026 — https://www.businesstoday.in/markets/story/sebi-ends-expiry-day-margin-benefit-for-single-stock-derivatives-to-curb-risk-514876-2026-02-05
- BANKNIFTY vertical spread ~₹33,500 margin (June 2026) — https://www.business-standard.com/markets/news/nifty-bank-strategy-how-to-use-a-bull-spread-for-june-26-expiry-decoded-125060600089_1.html
- SPAN + exposure margin, 2026 rupee figures — https://onetradejournal.com/glossary/span-margin
- Margin benefit on hedged positions — https://www.5paisa.com/blog/margin-benefits-hedged-option-positions
- Zerodha margin calculator — https://zerodha.com/margin-calculator/Futures/

**SEBI FY26 derivatives study**
- Quantitative summary — https://taxguru.in/sebi/sebi-studies-key-trends-retail-participation-trading-behaviour-profitability-equity-derivatives.html
- Jane Street interim order analysis — https://blogs.law.ox.ac.uk/oblb/blog-post/2025/07/jane-street-and-expiry-day-trap-unpacking-sebis-crackdown-algorithmic

**Practitioner context on moneyness (grade B/C)**
- ATM vs ITM/OTM for Indian F&O — https://www.sahi.com/blogs/moneyness-in-options-trading-itm-atm-and-otm-explained-for-indian-f-and-o-traders
- Why Indian scalpers use ATM — https://lemonn.co.in/blog/finance/atm-option-in-scalping-india-explained/
- Deep-ITM as stock replacement — https://www.optionstrading.org/blog/deep-in-the-money-options-explained/
- "Gamma blast" as usually published (rejected, n=13) — https://marketseasy.in/blog/gamma-blast-nifty-options-expiry-day

---

## 6. Method and limits of my own measurements

**Source.** `core/data/trades.db` opened read-only (`file:...?mode=ro`), 98,434 option ticks,
20 contract-sessions, 2026-09-02…2026-09-07. Costs via `research.costs.CostModel`. Quote-origin
classification reproduces `research/depth.py`'s rule exactly (fallback-pair arithmetic plus
non-zero OI corroboration). Black-Scholes IV solved by bisection to the 2026-09-08 15:30
expiry, zero rate, no dividend.

**What these numbers cannot support.**
- The real-book spread measurement is **three CE strikes, one afternoon, one session,
  sequential windows, delta 0.52–0.64**. Everything above delta 0.64 in §3 is a model
  extrapolation on a flat-percentage spread assumption, which is the *charitable* direction.
- Sampling on a 60-second grid over horizons up to 3,600 seconds means consecutive windows share
  most of their path. Effective n is far below nominal n. **No block bootstrap was run and no
  confidence interval is quoted for the MFE/MAE table** — deliberately, because any interval I
  computed would be too narrow.
- The book is 95% CE over a 4-session period in which NIFTY fell 218.6 points. Every
  long-horizon result is therefore contaminated by direction, and §1.2 says so explicitly
  rather than reporting the ladder sweep as a finding.
- The delta/spread model ignores gamma over the move, assumes the mid is unchanged when
  crossing, and assumes a full spread is paid once per round trip. Real execution is worse.
- I could not verify the Upstox Plus price, and I could not query a live margin calculator.
  Both are flagged where they appear rather than filled in.
- The GTBR coefficient's units could not be resolved from the accessible paper text, so no
  option-point effect size is claimed for candidate #3.

*Research only. No code, config or `.env` was modified, read for values, or printed. All
database access read-only. No broker order API called. No git operation.*
