# Round 3 — benchmarking each entry-signal component (2026-09-04)

Question: round 2 found the entry signal performing at or below arbitrary timing. Which
component is responsible? Same exit ladder, same contracts, same cooldown everywhere; real
spot/option LTP; fabricated spread in every arm equally.

## 1. STRUCTURAL — most components cannot carry information at all
Measured over **89,673 persisted signal rows** across 2026-09-02/03/04. This is a fact about
the data, not a statistical test.

**Score sub-components (weight 105 total):**
| constant on every row | value |
|---|---|
| `ema` | 20 (always full credit) |
| `premium` | 5 |
| `spread` | 5 (the known inert-spread defect) |
| `regime` | 2 |
| `delta`, `greeks`, `oi`, `macd` | **0 — never earned, ever** |

Only `atr` (2 values), `rsi` (3), `vwap` (2) and `volume` (3, but 96% one value) vary.
**8 of 12 sub-components are constant; 32 of the 105 weight is a fixed offset and ~25 more is
weight that can never be earned.** The score is arithmetically ~4 binary switches.

**Confidence sub-components:** `greeks_score`(10), `oi_score`(50), `regime_score`(50),
`regime_multiplier`(0.85), `session_score`(100), `session_multiplier`(1.2), `spread_score`(100)
are all **constant on every row**; `freshness_score` and `volume_score` are ≥96% one value.
The regime layer applies a flat 0.85 penalty to every signal, always.

**Consequence:** on a given day, CE signals produce only **two** distinct (score, confidence)
pairs — 09-03: (63,78) on 97% of rows; 09-04: (66,82) on 99%. **The stack cannot rank moments,
so no component can select better ones.** That is the mechanism behind round 2.

## 2. BENCHMARK TESTS — nothing in the stack beats arbitrary timing
Universe: 30 s grid, 09:30–15:10, subscribed CE contract, premium ₹70–350.

| arm | n | WR | E/trade | PF | 09-03 | 09-04 |
|---|---|---|---|---|---|---|
| **arbitrary timing (benchmark)** | 157 | 42.0% | **−₹23.42** | 0.76 | −32.51 | −10.87 |
| signal condition TRUE | 66 | 40.9% | −₹60.29 | 0.45 | −74.94 | −53.46 |
| signal ABSENT | 149 | 45.0% | −₹17.94 | 0.81 | −29.11 | −1.38 |
| the strategy's actual 24 entries | 24 | 37.5% | −₹72.04 | 0.36 | −40.30 | −149.13 |

Every varying component tested inside the signal-true set points the **wrong way**:
`confidence ≥78` −52.02 vs `<78` −33.56; `score ≥63` −52.02 vs `<63` −33.56;
`market quality ≥92` −66.72 vs `≥85` −48.05 (monotonically worse); `Vol_Spike present`
−45.74 vs absent −32.06; `volume sub-score ≥10` −52.02 vs `<10` −33.56. The single component
with the right sign is the strategy's own RSI (`≥62` −31.77 vs `<62` −59.42, consistent on
both days) — and it still does not beat the benchmark.
Note score, confidence and volume split identically: they are the same underlying variable.

## 3. HOW STRONG IS THE EFFECT? — design-sensitive, and NOT established
| design | gap vs benchmark | p (one-sided) |
|---|---|---|
| benchmark drawn from the strategy's **active windows**, per-day counts matched (round 2) | −₹63 | **0.0235** |
| benchmark drawn from the **whole tradable day**, 30 s grid (round 3) | −₹48.63 | **0.1434** |
| signal-true vs signal-absent instants | −₹28.42 | 0.2082 |

**Correction to the round-2 headline.** p=0.0235 holds for that design; a reasonable
alternative design gives p=0.14. The defensible statement is: *the entry signal shows no
evidence of positive selection value, point estimates put it below arbitrary timing on both
sessions, but at n=24 the effect is not separated from chance.* The **structural** finding in
§1 does not depend on any of this.

## 4. Not reliable
`was_taken=1` signal rows reconstructed to +₹58.44 (n=10, 09-03 only) while the same day's
real entries were −₹40.30. The reconstruction picks different instants than the real execution
path did. **Ignore it — the real trades are ground truth for that layer.**

## 5. Labels
| claim | label |
|---|---|
| 8/12 score and 7/17 confidence sub-components are constant on every row | **Confirmed** (89,673 rows) |
| the stack produces only 2 distinct score/confidence pairs per day | **Confirmed** |
| `delta`, `greeks`, `oi`, `macd` never contribute anything | **Confirmed** |
| higher score/confidence/market-quality selects better moments | **Contradicted** (all inverted, both days) |
| the entry signal selects worse than arbitrary timing | **Weakened → suggestive**, p 0.02–0.14 by design, n=24 |
| the gate layer adds value | **Unknown** — reconstruction unreliable |
| PE behaviour | **Unknown** — PE contract almost never subscribed |

## 5b. ROOT CAUSE — a family of unpopulated-input defects (verified in code + data)
`grep` over `core/trading/broker.py`: the tick dict never sets **`atr`, `delta`, `oi`,
`open_interest`, `greeks`** — zero occurrences of any of them. The persisted `oi` column is
0/NULL on all **73,171** ticks across the three days. Consequences, each traced to a line:

| input | consumer | effect |
|---|---|---|
| `delta` never set | `weighted_score_engine.py:69` `if 0.35 <= delta <= 0.65` | `delta`(10) **and** `greeks`(5) pinned to 0 forever — one unset key kills two components |
| `oi` never set | `smart_scalp_v3.update_oi_data` returns `NEUTRAL` on `current_oi <= 0` | score `oi`(10) pinned to 0; confidence `oi_score` pinned to 50 |
| `atr` never set | `exit_engine._early_cut_threshold` | Early Loss Cut pinned to 2.5 (the already-known ATR defect — same class) |
| `MACD_Hist_Prev` | `weighted_score_engine.py:92` | `macd`(8) constant 0 on every row |

**25 of the 105 score weight can never be earned**, and another 32 (`ema` 20, `premium` 5,
`spread` 5, `regime` 2) is awarded identically every time. Roughly **57 of 105 is a fixed
offset**; the remaining ~48 is four near-binary switches. This is the same failure mode as the
ATR defect, three more times over, and it is the mechanical reason the score cannot rank.

## 6. Next
1. **The scoring stack needs variance before it can be tuned.** `delta`, `greeks`, `oi`, `macd`
   award zero on every row — find out whether they are unpopulated inputs (like the `atr`
   defect) or genuinely never satisfied. That is an engineering question with a definite answer.
2. Same for the constants: `ema`=20 always and `regime`=2 always mean those tests never fail.
3. Only after the stack can discriminate is it worth re-running these benchmarks.
4. Still blocking everything in rupees: real spread; and PE is still uncollectable.
