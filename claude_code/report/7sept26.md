# 2026-09-07 — six blockers and a cost model

**Full report (rendered):** https://claude.ai/code/artifact/6361510d-0c35-415a-982d-43fa435caf63
**Source:** [`7sept26.html`](7sept26.html) in this directory.

Live-paper session, branch `experiment/exit-strategy-20260904`, 8 commits `88e07d3`…`e771827`.

## The numbers

| | |
|---|---|
| Gross P&L | **−₹952.25** (13 trades, 4 winners) |
| Transaction cost | **−₹846.21** (₹65.09 per round trip) |
| **Net P&L** | **−₹1,798.46** (−₹138.34/trade) |
| Traded window | 10:16 → 14:15, of 09:15–15:25 available |

All 144 recorded trades, priced at Zerodha's published rates: gross −₹1,768.00 → **net −₹10,956.28**;
expectancy −₹12.28 → **−₹76.09**; win rate 46.5% → 33.3%; break-even win rate needed 50.4% → **70.3%**.

## What happened

The session was booked as the out-of-sample test of the opening-window result. That window was
never traded — the first order went in at 10:16:01. Six independent blockers were stacked behind
one another, each hidden by the one in front:

1. **PE trend-exhaustion filter** — 986 of 986 evaluations rejected before scoring, 0 scored signals in 30 minutes. Now settable; PE half disabled 09:28:35.
2. **Indicators rebuilt from nothing** — my own restart hit the historical-candle rate limit; EMA9/EMA21 0.1–0.7 pts apart against 32. Warm-up now falls back to an on-disk cache, which caught the same failure twice more the same afternoon.
3. **Cross-direction moneyness** — 988 × "Premium too low ₹32 < ₹70". A strike that makes a CE ITM makes the PE OTM. Most plausible reason the tick record holds 297 PE rows against ~73,000 CE.
4. **Open interest could never populate** — option tokens subscribe in mode 2; OI and the best-5 book are only in mode 3. The same gap is why every recorded bid/ask was an `ltp ± 0.3%` estimate.
5. **Streak pause ran 30 minutes, not 15** — two clocks back to back instead of together. Verified both ways: 10:19:44→10:49:47 before, 11:32:30→11:47:32 after.
6. **Recovery mode was a permanent halt** — "size 50%" computes 0.4936 of the budget; one lot needs 0.578. And `recovery_start_date` was never persisted, so after a restart the exit condition could not even be evaluated.

The pattern matters more than the list: each mechanism is defensible alone, and they **compose
multiplicatively and return silently**. The most useful changes today were logging, not logic.

## The finding that explains three months

Every P&L figure this project has produced is **gross**. There is no brokerage, STT, exchange
charge, GST or stamp duty anywhere in the codebase, and no backtest artifact behind the strategy
docstring's "+42.2% monthly".

- Cost is **40.1% of the average winning trade**; 1.162 option points at one lot.
- Not an account-size artefact: at 8 lots the round trip still costs 0.527 pts and break-even still
  needs a 3.94-point average win against the **2.45 observed**.
- Forward excursion after 37 entries is adverse-skewed at **every** horizon (MFE/|MAE| 0.51 at 60s,
  0.65 at 600s). Holding longer does not rescue it. Cutting losses fast is the *correct* response to
  a signal shaped like this — which is why EXP-02's loss-side relaxations all made things worse.

**Gross expectancy across 144 trades is −₹12.28/trade — indistinguishable from zero. The strategy
has no measured edge and pays ₹63.80 a trade for not having one. That is a frequency problem, not a
tuning problem.**

## Both flagship findings failed out of sample

| test | in-sample (09-02/03/04) | out-of-sample (09-07) |
|---|---|---|
| Opening window 09:15–09:45 | +₹114.06 · p=0.0057 | **−₹108.81** · p(better)=0.797 |
| Range gate ≥30 pts, 09:45–15:10 | +₹72.02 · p=0.042 | **−₹177.38** · p(better)=0.913 |

Both reversed. The morning's commit had already flagged that the range threshold was chosen on the
same sessions that scored it across ~21 combinations; that caution was correct. Both findings are
**withdrawn**, not pending.

## Measured for the first time

- **Real bid/ask.** Quote source moved from `100.0% estimated` to `real=1 estimated=0`. Real spread median 0.246% (range 0.054–0.305%) against the flat 0.300% model — the fabrication sat at the top of the real range, worth ~₹8 per round trip. This *refines* the synthetic-bid/ask correction; it does not overturn it, and the spread is not where the expectancy problem lives.
- **Real OI** (1,646,840, moving) against 73,171 historical NULLs. The scorer still cannot use it: classification reads the change between two consecutive ticks against ±1%, and 243 of 246 comparisons were exactly zero. A time-baseline option is written and defaulted off.

## External cross-check

| | this bot, 144 trades | SEBI FY26, all individual F&O traders |
|---|---|---|
| Net losses | −₹10,956 | −₹91,685 crore |
| Transaction costs | ₹9,188 | ₹25,000 crore |
| **Cost / net loss** | **84%** | **27%** |
| Turnover vs capital | 67× | "higher turnover → higher loss rate" |

## What this does NOT establish

- **Not a controlled experiment.** Five settings changed mid-session, six restarts. Switch times in `logs/2026-09-07/SWITCH_pe_exhaustion_off.txt`.
- Excursion figures are n=37 over three sessions, and are the bot's own entries, not a head-to-head against arbitrary timing.
- Real-spread measurement is one contract, two minutes, mid-afternoon.
- Costs are one broker's published rates and reflect the Budget 2026 STT rise to 0.15%.
- Four restarts reset the daily loss counter before that was fixed, so the bot's own `Daily:` figure for today is wrong. Every number here comes from the trades table.

## What follows

1. **Re-read every prior experiment as gross** — EXP-01…EXP-11 are all ~₹64/trade too optimistic, in the same direction.
2. **Stop tuning the exit ladder.** Both sides have been swept four times; no exit policy closes an adverse-skewed forward distribution.
3. **The entry has a known bar now:** an average win above 3.94 pts even at 8 lots, 5.30 at one. Nothing measured comes close to 2.45.
4. **Trade far less often, or not at this size.** With a near-zero gross edge, trade count is the dominant term.
5. Deferred: the recovery trigger reads all-time `total_pnl`, not drawdown from peak, so lifetime losses will cross 8% once and latch.

Sources: [Zerodha charges](https://zerodha.com/charges/) · [SEBI FY26 study](https://openthemagazine.com/business/sebi-fo-loss-study-explained-why-9-in-10-retail-traders-lost-91685-crore-in-fy26)
