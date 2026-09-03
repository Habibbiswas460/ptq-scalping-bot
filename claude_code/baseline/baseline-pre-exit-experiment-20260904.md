# Baseline Checkpoint — Pre Exit-Strategy Experiment

**Frozen reference point. Do not amend, overwrite, or rebase this baseline.**

This record exists so the exit-strategy experiment can be measured against a
known-good state, and so that state can be restored exactly if the experiment
performs worse.

---

## 1. Identity

| | |
|---|---|
| **Commit SHA** | `8b7490e72b1ea52bea9b07a1cf12f367f37b2bb8` |
| **Short SHA** | `8b7490e` |
| **Tag** | `baseline-pre-exit-experiment-20260904` (annotated) |
| **Branch** | `feature/ptq-scalping-20260808` |
| **Parent commit** | `ee06926` — execution-drift cross-direction fix |
| **Created** | 2026-09-04 |
| **Python** | 3.14.4 |
| **Test count** | **287 passed, 1 skipped** |

**Restore command:**
```bash
git checkout baseline-pre-exit-experiment-20260904
```

⚠️ **Push status: NOT PUSHED.** The commit and tag exist locally only. This
environment has no GitHub credentials (HTTPS remote, no credential helper,
no `gh` CLI, no SSH keys). See §8.

---

## 2. Strategy parameters (effective values)

Values below are the **effective** ones — `.env` overrides the code defaults in
several places, and the `.env` value is what actually runs. Where they differ,
both are shown, because using the code default would silently reproduce a
*different* system.

### Exits under experiment

| Parameter | Effective (.env) | Code default | Note |
|---|---|---|---|
| `EXIT_EARLY_LOSS_CUT_POINTS` | **3.5** | — | Early Loss Cut |
| `EXIT_EARLY_LOSS_CUT_TIME_SEC` | **45** | — | |
| `EXIT_EARLY_CUT_ATR_LOW_POINTS` | **2.5** | 2.5 | ATR-adaptive floor |
| `EXIT_EARLY_CUT_ATR_HIGH_POINTS` | **4.5** | 4.5 | ATR-adaptive ceiling |
| `EXIT_SOFT_LOSS_TIME_SEC` | **75** | 75 | Soft Loss |
| `EXIT_SOFT_LOSS_POINTS` | **1.8** | 1.8 | |

### RSI exits

| Parameter | Effective | Code default |
|---|---|---|
| `RSI_OVERBOUGHT` | 80 | 80 |
| `RSI_OVERSOLD` | 20 | 20 |
| `RSI_EXIT_MIN_PROFIT_POINTS` | 2.0 | 2.0 |
| `RSI_REVERSAL_CE_EXIT` | 60 | 60 |
| `RSI_REVERSAL_PE_EXIT` | 40 | 40 |
| `RSI_REVERSAL_CE_EXTREME` | 75 | 75 |
| `RSI_REVERSAL_PE_EXTREME` | 25 | 25 |
| `RSI_REVERSAL_MIN_PROFIT_POINTS` | **1.65** | 1.5 ⚠ differs |

### SL / TP / trailing

| Parameter | Effective | Note |
|---|---|---|
| `SL_POINTS` / `EXIT_HARD_SL_POINTS` | 7 | never hit in 50 trades |
| `TP_POINTS` | 14 | |
| `EXIT_BREAKEVEN_TRIGGER_POINTS` | 4 | **never activated** — max MFE ever observed is +3.77 |
| `EXIT_BREAKEVEN_BUFFER_POINTS` | 2 | |
| `EXIT_TRAILING_DISTANCE_POINTS` | 2.5 | **never activated** |
| `TRAILING_ATR_NORMAL` / `_EXPIRY` | 1.2 / 1.0 | code defaults |
| `MAX_HOLD_TIME_SEC` | 900 | |
| `MAX_HOLD_TIME_EXPIRY_SEC` | 600 | |

### Entry filters (out of experiment scope — must remain unchanged)

| Parameter | Effective | Code default |
|---|---|---|
| `MIN_SCORE` | 4 | 4 |
| `MIN_CONFIDENCE` | 70 | 70 |
| `MIN_CONFIDENCE_AFTER_3SL` | 85 | 85 |
| `MIN_ENTRY_PREMIUM` / `MAX_ENTRY_PREMIUM` | 70 / 350 | 70 / 350 |
| `DELTA_MIN` / `DELTA_MAX` | 0.25 / **0.75** | 0.25 / 0.80 ⚠ differs |
| `ENTRY_MAX_DRIFT_PCT` | **0.35** | 0.75 ⚠ differs — 0.35 is what logs show |
| `KILL_SWITCH_SPREAD_PCT` | 0.6 | 0.6 — **inert**, see §6 |
| `SPREAD_LIMIT_PCT` | 2.5 | 2.5 — **inert**, see §6 |
| `TICK_TIMEOUT_SEC` | **2** | 3 ⚠ differs |
| `MIN_OPTION_PRICE` | **5** | 1 ⚠ differs |

### Risk controls

| Parameter | Effective |
|---|---|
| `PAPER_TRADING` | **true** — no live order has ever been placed |
| `LOT_SIZE` | 65 |
| `MAX_TRADES_PER_DAY` / `_HOUR` | 30 / 10 |
| `MAX_DAILY_LOSS` / `KILL_SWITCH_LOSS` | 3000 / 3000 |
| `DAILY_LOSS_ALERT` | 1500 |
| `COOLDOWN_AFTER_CONSEC_LOSS` | 900 |
| `COOLDOWN_NORMAL` / `_AFTER_SL` / `_AFTER_PROFIT` | 120 / 120 / 30 |
| `KILL_SWITCH_LATENCY_MS` | 1000 |

---

## 3. Baseline performance metrics (50 real paper trades)

These are the numbers the experiment must beat. **Gross, before costs.**

| Metric | 33-trade baseline<br>(08-28, 08-31, 09-01) | Day 2<br>(09-03) | **Combined (50)** |
|---|---|---|---|
| Trades | 33 | 17 | **50** |
| Wins / Losses | 16 / 15 | 8 / 9 | **24 / 26** |
| Win rate | 51.6% | 47.06% | **48.0%** |
| Avg win | +1.84 pts | +1.75 pts | **+1.85 pts** |
| Avg loss | -2.51 pts | -2.70 pts | **-2.39 pts** |
| R:R | 0.73:1 | 0.65:1 | **0.77:1** |
| Break-even win rate | 57.7% | 60.6% | **56.4%** |
| Gross P&L | ≈ -₹457 | -₹672.10 | **-₹1,129.05** |
| Expectancy / trade | ≈ -₹13.85 | -₹39.54 | **≈ -₹22.58** |
| Profit factor | — | 0.58 | — |
| Max drawdown (Day 2) | — | ₹706.55 | — |
| Hard 7-pt SL hits | 0 | 0 | **0** |
| Trailing activations | 0 | 0 | **0** |
| Max MFE ever | — | +2.63 pts | **+3.77 pts** |

### Day-2 exit-reason distribution (the only tick-level day)

| Exit reason | n | W/L | Avg P&L | Avg MFE | Avg MAE | Post-exit fav / adv |
|---|---|---|---|---|---|---|
| RSI Exit (hard OB) | 2 | 2W | +₹144.30 | +2.40 | -0.19 | +1.76 / -5.05 |
| RSI Reversal | 6 | 6W | +₹103.57 | +1.99 | -1.04 | +2.34 / -1.47 |
| Soft Loss | 6 | 6L | -₹164.34 | +1.06 | -2.48 | +2.56 / -3.75 |
| Early Loss Cut | 3 | 3L | -₹198.68 | +0.11 | -2.89 | +4.33 / -3.70 |
| Trailing / Time | 0 | — | — | — | — | — |

Avg hold: 105.8s overall (91.9s winners, 118.2s losers).

**Loss-exit justification (9 losses, 1-min structure at moment of exit):**
6 justified / 1 clearly premature (#122) / 2 ambiguous.

**Transaction costs:** not modelled anywhere. Estimated realistic cost
≈₹65/trade → Day-2 net would be ≈**-₹1,778** vs -₹672 gross.

---

## 4. Experiment hypothesis (to be tested, NOT assumed)

> Removing or replacing Early Loss Cut and Soft Loss, while strengthening
> RSI/structure/momentum-matched exits, allows trades more room to develop and
> improves payoff asymmetry.

**Evidence currently pointing against it:** 6 of 9 Day-2 losing exits
coincided with a genuine 1-minute structural breakdown; the three fastest
(19s, 31s, 41s) had already broken down within a minute. A fixed 1-3 minute
holding window was tested and **rejected**.

**Evidence currently pointing for it:** trade #120 (Early Loss Cut) reversed
+10.57 pts after exit; #122 (Soft Loss) exited with structure fully intact;
industry literature flags tight ATR stops in scalping as false-stop-out prone.

Required comparison metrics: Win Rate, Avg Win, Avg Loss, R:R, Expectancy,
Profit Factor, Max Drawdown, trade count, exit-reason distribution, avg
holding time, MFE/MAE, post-exit continuation, transaction-cost impact.

---

## 5. Known data limitations

1. **Only ONE clean tick-level day exists** (2026-09-03, 17 trades). Day 1
   (09-02) is bug-contaminated and unusable.
2. **The 33-trade baseline has no persisted ticks** — no MFE/MAE or structure
   reconstruction is possible for it, permanently.
3. **No historical option data.** Canonical store is empty; no vendor sells
   spec-compliant expired-weekly intraday data at retail.
4. **All persisted bid/ask is synthetic** (`ltp ± 0.3%`) — see §6. Any
   spread-derived conclusion from existing ticks is void. LTP-derived
   findings (P&L, MFE/MAE, exit timing) remain valid.
5. **OI is 100% NULL** in existing ticks (mode-2 subscription carries none).
6. **Both sampled sessions were 100% CE.** No PE comparison exists.
7. n=50 across 4 days is far below what would justify a strategy change.
8. Timestamps in the legacy `ticks` table are second-resolution → 5,385
   same-second collisions on Day 2; sub-second ordering is lost.

---

## 6. Known unresolved issues

| Issue | Status |
|---|---|
| **Synthetic bid/ask** — the shared WS parser skips the best-5 depth block (bytes 147-347) entirely, so `best_bid_price` is never set and the fallback fires on every tick | Root cause identified; trading path deliberately **untouched**. Collector parses independently. |
| **Spread filters inert** — `KILL_SWITCH_SPREAD` (0.6%), MQ spread component (25 pts), `weighted_score_engine` spread_quality (5 pts) and validators all receive a constant ~0.2996% and can never fire | Classified SAFETY DEFECT. `quote_source` observability added; **no threshold changed** pending real spread data. |
| **Trailing stop never activates** — 0/50 trades; threshold (+4 pts) exceeds the max MFE ever recorded (+3.77) | Flagged REMOVE-or-recalibrate. Not yet actioned. |
| **No transaction-cost accounting** anywhere | Flagged ADD. Not yet actioned. |
| **Regime classifier returns only "SIDEWAYS"** across both measurable days | Zero discriminative power. INVESTIGATE FURTHER. |
| **Collector never validated on real market data** | Blocked until market open. NOT production-ready. |
| **Concurrent-login safety unverified** | First real collector run must be with the trading bot stopped. |
| **DVF shadow pipeline defects** — Day-1 restart-reconciliation artifact; 08-28 linkage inconsistency | Observability bug, not trading logic. |

---

## 7. Reproducibility checklist

```bash
git checkout baseline-pre-exit-experiment-20260904   # SHA 8b7490e
source venv/bin/activate
python -m pytest tests/                              # expect 287 passed, 1 skipped
```
`.env` is **not** in version control (correctly — it holds credentials). The
effective strategy values are recorded in §2 so `.env` can be reconstructed.
Restoring the tag alone reproduces code, not `.env`.

---

## 8. Outstanding action before the experiment may begin

**The commit and tag are local only.** To complete the checkpoint:

```bash
git push origin feature/ptq-scalping-20260808
git push origin baseline-pre-exit-experiment-20260904
```

Until this succeeds there is no off-machine copy of the baseline, so the
"restore exactly" guarantee depends on this working tree alone.
