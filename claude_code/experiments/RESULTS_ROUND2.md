# Round 2 — where the market's movement is lost (2026-09-04)

Scope: the three sessions with persisted ticks — **2026-09-02 (0 trades), 09-03 (17), 09-04 (7)**.
Spot and option LTP are real. Bid/ask is fabricated everywhere, so every rupee figure carries an
unknown execution-cost error; **nothing about market movement itself depends on it.**

## A. Day-by-day market movement (spot)
| | 09-02 | 09-03 | 09-04 |
|---|---|---|---|
| range | 126.40 | 149.40 | 107.70 |
| net | +56.45 | −124.50 | −13.20 |
| max 1-min move | +31.6 / −70.2 | +22.4 / −39.8 | +29.8 / −42.3 |
| max 10-min move | +50.1 / −91.4 | +39.3 / −40.7 | +42.7 / −42.3 |
| legs ≥25 pts | 15 | 12 | 11 |
| median ≥25pt leg duration | 13.2 min | 20.6 min | 17.4 min |
| strategy active | — (none) | 11:10–14:15 | 09:50–11:11 |

**The market moved plenty on all three days.** The largest single moves were consistently in
**09:15–09:35**, before the strategy traded on 09-03 and at the very edge on 09-04. 09-02 had a
126-point range and produced **zero trades**.

## B/C. Where the movement was, and the strategy's presence
Largest legs and entries inside them:
- 09-03 `11:36→12:36  −73.70 pts (60.6 min)` — **4 CE entries inside a 73-point DOWN leg**
- 09-03 `09:27→09:48  +64.60 pts (21.0 min)` — 0 entries (before the window opened)
- 09-04 `09:36→10:04  +65.95 pts (27.4 min)` — 2 entries, one of them **a PE**
- 09-04 `11:39→12:57  −76.70 pts (78.1 min)` — 0 entries (locked out by the SL-streak gate)

## D. Entry location — no causal feature separates winners from losers
25 strictly as-of-entry features (option/spot momentum at 30 s/60 s/2 m/5 m, position in the
trailing range, distance from the trailing favourable extreme, trailing range, acceleration,
option-vs-spot momentum agreement). Monte-Carlo permutation, n=24:
**best p = 0.129**, and 25 tests expect ~1.2 false positives at α=0.05. **Nothing separates.**
Momentum agreement: 41% win rate when option and spot agree vs 50% when they disagree.

**Directional alignment with the containing ≥15 pt leg: 11 aligned / 13 against = 46%.**

## E. Option transmission — realised delta at the strategy's timescale
Data-quality gate first: spot is fresh (unchanged tick-to-tick only 3.5–3.7%, median frozen
run 1 s) on both main series. Regression of Δoption on Δspot:

| horizon | 09-03 23950CE | 09-04 23950CE | R² (09-03 / 09-04) |
|---|---|---|---|
| 10 s | **0.258** | **0.430** | 0.40 / 0.40 |
| 60 s | 0.348 | 0.519 | 0.71 / 0.72 |
| 300 s | 0.402 | 0.511 | 0.86 / 0.80 |

At 10 seconds only **22–40% of the option's variance is explained by spot** — the rest is
option-specific noise. Median |Δspot| over 60 s is 2.1–3.0 pts.

## F. Capture ratio (available measured from ticks, uncensored by the exit)
| horizon | winners avail | winners captured | ratio | losers avail |
|---|---|---|---|---|
| 3 min | 3.37 | 1.72 | **51.1%** | **1.36** |
| 5 min | 4.90 | 1.72 | 35.2% | 1.41 |
| 10 min | 5.27 | 1.72 | 32.7% | 2.41 |

**Losers had almost nothing available (1.36 pts at 3 min).** They are entry failures, not exit
failures. Winners left about half of their 3-minute potential — that part is the exit.

## G. The 1–2 point ceiling — arithmetic, not a rule
`typical option move in the hold = spot velocity × delta × hold`
= (2.1–3.0 pts/min) × (0.26–0.52) × (0.9–1.8 min) ≈ **0.5–2.8 pts.**
Median 5-minute option MFE measured directly: **1.79 pts.**
The strategy holds **0.9–1.8 min** while ≥25 pt legs last **13–21 min** — an order of magnitude
mismatch. Almost no big leg completes inside 3 minutes (1/15, 0/12, 1/11 across the three days).

The 1.65 profit floor is *calibrated to* this ceiling, not the cause of it. Historical support:
before 2026-08-26 the system produced TAKE PROFIT exits averaging **+12.81 pts** (max 13.52) and
TRAILING PROFIT averaging +3.48; since 08-26 there have been **zero** of either, and every
profitable exit is RSI-family with max +1.95 (reversal) / +3.77 (RSI exit).

## H. Entry vs exit contribution (n=24, both days)
- 14/24 trades had ≤1.36 pts of 3-minute upside available → **entry**
- 10/24 winners gave up ~1.65 pts of 3-minute upside each ≈ 16.5 pts total → **exit**
- Round-1 already showed that harvesting more of it costs more elsewhere, because winners and
  losers are indistinguishable at entry.

## I. EXP-05 — does the entry signal add value?
Opportunity universe: 1,421 candidate entry instants (every 30 s, premium ₹70–350, the
contract actually subscribed). **PE could not be tested at all — a PE contract was almost never
the subscribed one (n=0–2).**

No causal directional filter was consistent across both days. Two showed pooled positives
(spot 5 m momentum ≥ +10 → CE: E=+₹49.11; ≥ +20: +₹40.14) but each was driven by a single day
and they split in opposite directions. With ~15 filters tested that is chance.

**The headline result** — same active windows, same contracts, same exit ladder:

| arm | n | WR | E/trade | PF | 09-03 | 09-04 |
|---|---|---|---|---|---|---|
| arbitrary CE entries every 30 s | 72 | 51.4% | **−₹8.58** | 0.89 | −14.96 | +6.93 |
| **strategy-selected entries** | 24 | 37.5% | **−₹72.04** | 0.36 | −40.30 | −149.13 |

Randomisation test (2,000 draws of arbitrary-timed CE entries, per-day counts matched, same
cooldown): null mean −₹25.91, p05 −₹64.51; **the strategy's −₹72.04 sits at p = 0.0235.**

**On these two sessions the entry signal selected worse-than-arbitrary moments inside its own
active windows.** Limits: 2 sessions, n=24, CE only, and the arbitrary arm ignores the chop
filter, session gates, strike rotation and drift guard — it is a **benchmark, not a deployable
alternative**.

## J. Decisions
| item | label | action |
|---|---|---|
| 1–2 pt ceiling is an exit rule | **Contradicted** | it is velocity × delta × hold; the floor is calibrated to it |
| option transmits spot efficiently | **Contradicted** | realised delta 0.26–0.43 at 10–30 s, R² 0.22–0.40 |
| holding window matches the market's legs | **Contradicted** | 0.9–1.8 min hold vs 13–21 min legs |
| entry has a directional edge | **Contradicted** (p=0.0235, 2 sessions) | highest-priority work |
| any simple causal momentum filter fixes it | **Contradicted** | none consistent across both days |
| exit costs ~half the winners' 3-min upside | **Confirmed** | real but second-order |
| PE behaviour | **Unknown** | PE was almost never subscribed — cannot be tested from this data |
| execution cost | **Unknown** | spread still fabricated |

## K. Next
1. **Entry research is now the priority**, not exit tuning. The exit is within ~1.65 pts/winner
   of its ceiling; the entry is losing to a coin flip.
2. Subscribe and persist **both** CE and PE simultaneously — PE is currently untestable, and
   half the directional space is invisible.
3. A hold/leg experiment is only worth running **after** entry direction beats chance.
4. Collector solo run for real spreads (still blocking all rupee conclusions).
