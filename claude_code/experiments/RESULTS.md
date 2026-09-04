# Exit experiment results — round 1 (2026-09-04)

Baseline: `8b7490e`, tag `baseline-pre-exit-experiment-20260904`. Branch:
`experiment/exit-strategy-20260904`. Production defaults unchanged; every variant below is
flag-gated and OFF unless the flag is set.

Data: the 24 recorded trades of 2026-09-03/04 plus, for EXP-04, the 51 signals the
SL-streak gate blocked on 09-04. **Two sessions. Every number here is hypothesis-generating.**

## Harness fidelity
`exit_lab.py` control policy reproduces **22 of 24** recorded exits by reason and second.
The two misses are RSI-timing (#111, #128): the live RSI buffer saw every tick received
(42,965 on 09-04) while only 25,055 were persisted, so the replayed tick-RSI is smoother.
Loss-side rules reproduce exactly.

## EXP-01 — does the tick-RSI add information over the profit floor?
| policy | E/trade | PF |
|---|---|---|
| CONTROL (floor 1.65 + tick-RSI) | −₹72.04 | 0.36 |
| floor-only 1.65, no RSI | −₹61.24 | 0.41 |
| profit-taking removed entirely | −₹131.11 | 0.16 |

Sweeping `rev_exit_ce` 45→70 moves expectancy from −67 to −59; `rev_extreme_ce` 65/70/75 give
**identical** results. Confirmation delays (1–5 ticks, 5–30 s) move it −72 → −64. The floor
level, by contrast, moves it monotonically. **Verdict: the RSI condition is a delay, not a
signal. The floor is the mechanism.** — *Confirmed within this data.*

## The structural finding (policy-independent)
Median max-favourable-excursion over 5 minutes is **1.79 pts** (p25 1.06, p75 3.93); only
29% of trades reach +3.0. The loss side risks 2.5 / 1.8 / 7.0 pts. **The system risks more
than the median trade offers.** This is measured on the entries themselves and does not
depend on any exit policy.

## EXP-02 — pullback vs genuine failure
| mechanism | E/trade | note |
|---|---|---|
| CONTROL static 2.5/1.8 | −₹72.04 | |
| pullback-tolerant (30 s / 60 s) | −₹72.04 | **no effect at all** |
| fresh-low required (3 / 8 ticks) | −₹78 / −₹92 | cuts become hard SLs |
| structure (below prior candle low) | −₹75.83 | worse |
| MFE-aware 1.5 / 4.0 @arm 1.0 | **−₹53.54** | better on both days |
| realised ATR 60 s × 0.75 | −₹59.77 | better on both days |
| realised ATR 60 s × 1.00 / 1.50 | −₹78 / −₹80 | worse |

**Pullback-tolerance had literally zero effect**: at the moment a cut fires, price is at its
own running low — there is no bounce to detect. Every mechanism that gives *more* room is
worse; the two that help *tighten* for trades that never traded above entry.
**Answer to "can the system tell a pullback from a failure before cutting?" — not from price
alone, at this resolution. What works is not asking, and instead sizing the stop to whether
the trade has proved itself.**

## EXP-03 / EXP-04 — combination, then the check that killed it
Fitted set (n=24): X6 (floor-only 1.00 + realised-ATR×0.75) reached **+₹1.41/trade, PF 1.03**,
positive on both days, LOO-separated from control.

EXP-04 produced a fresh entry set: the **51 signals the SL-streak gate blocked**, never used
to fit anything. Re-running the candidates on it:

| policy | fitted n=24 | near-OOS n≈51-69 |
|---|---|---|
| CONTROL | −₹72.04 (PF 0.36) | −₹40.05 (PF 0.60) |
| X1 floor-only 1.00 | −₹19.23 | −₹34.06 (PF 0.54) |
| **X6 floor-only + realised ATR** | **+₹1.41** | **−₹42.33 (PF 0.48) — WORSE than control** |
| **X3 floor-only + MFE-aware** | −₹8.86 | **−₹24.86 (PF 0.60) — better on both** |

**X6 was an overfit and is rejected.** X3 is the only candidate that improves on both sets,
at every assumed spread (0.20% → 0.60%). It still never reaches positive expectancy.

## EXP-04 — the SL-streak confidence lock
Reality on 09-04: gate ON, zero trades from 11:11 to close. Counterfactual with the gate
relaxed to ≥82: **51 trades, −₹2,042 more**, turning −₹655 into ≈−₹2,697. Fully removed
(≥70): −₹1,302 more. **The lock protected capital. Do not remove it.** (Upper bound on trade
count — chop filter, strike rotation and drift guard were not re-run.)

## Spread dependency — the blocker
All persisted bid/ask is fabricated at 0.3%. X6's positive expectancy died above a **0.36%**
round-trip. X3 keeps its edge over control at every level tested but shrinks as spread widens.
**No exit change can be promoted to production until the collector returns real spreads.**

## Decisions
| item | decision |
|---|---|
| tick-RSI reversal as an information source | **Contradicted** — it is a delayed profit floor |
| profit floor near the median MFE | **Experimental, promising** — keep testing |
| X6 realised-ATR combination | **Reverted** — failed near-OOS |
| X3 floor-only + MFE-aware | **Experimental, leading candidate** — not promoted |
| pullback-tolerant / fresh-low / structure loss gating | **Contradicted** — closed |
| Early or Soft Loss widening/removal | **Contradicted** — closed (round 0 and again here) |
| SL-streak confidence lock | **Keep unchanged** — it saved ₹2,042 |
| ATR defect | real defect; the honest fix is `EXIT_REALISED_ATR_ENABLED`, but the wider stop it produces did not help. Fix for correctness, not for performance |

## Next experiment (smallest useful)
1. **Collector solo run** for real spreads — blocks every promotion decision.
2. A third live-paper session for a genuinely independent entry set.
3. Entry-side work: median MFE 1.79 vs a 2.5 stop is an entry-quality problem, and no exit
   policy tested closes it. Exit tuning has now been pushed close to its ceiling.
