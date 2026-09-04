"""EXP-01B — is 'lower the profit floor' a real effect or a curve fit?
   (a) MFE distribution: what the trades actually offer, independent of any policy
   (b) per-day consistency
   (c) leave-one-out: does the ranking survive dropping any single trade?"""
import sys, os, datetime, statistics
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, run, metrics, _P, DAYS

b = Book()

# ── (a) MFE distribution, policy-independent ──────────────────────────────
print("=" * 100)
print("(a) MAX FAVOURABLE EXCURSION per trade, measured over the first 5 minutes after entry")
print("    (policy-independent: what the entries actually offer, before any exit rule)")
print("=" * 100)
mfes = []
for day, t in b.trades():
    tk = b.ticks(t["symbol"], day)
    e = _P(t["entry_time"])
    w = [p for d, p in tk if e < d <= e + datetime.timedelta(minutes=5)]
    if w:
        mfes.append((t["id"], round(max(w) - t["entry_price"], 2), t["pnl"] > 0))
vals = sorted(v for _, v, _ in mfes)
print(f"    n={len(vals)}  median={statistics.median(vals):.2f}  mean={statistics.mean(vals):.2f}  max={max(vals):.2f}")
print(f"    quartiles: p25={vals[len(vals)//4]:.2f}  p50={statistics.median(vals):.2f}  p75={vals[3*len(vals)//4]:.2f}")
for lvl in (0.5, 1.0, 1.35, 1.65, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0):
    n = sum(1 for v in vals if v >= lvl)
    print(f"    reached +{lvl:<4}: {n:>2}/{len(vals)} ({100*n/len(vals):>5.1f}%)   "
          f"expected gross if all harvested there: {lvl*n/len(vals):.2f} pts/trade")
print(f"\n    for comparison the loss side risks 2.5 (early cut) / 1.8 (soft) / 7.0 (hard SL) pts")
print(f"    synthetic round-trip spread already inside these numbers: ~0.36 pts")

# ── (b) per-day consistency of the leading candidates ─────────────────────
CANDS = [Policy("CONTROL (prod)"),
         Policy("A1 floor-only 1.65", floor_only=True),
         Policy("C1 floor-only 1.00", floor_only=True, rev_min_profit=1.00),
         Policy("C2 floor-only 1.35", floor_only=True, rev_min_profit=1.35),
         Policy("B1 floor 1.00 + RSI", rev_min_profit=1.00)]
print()
print("=" * 100); print("(b) PER-DAY CONSISTENCY (a candidate must win on BOTH days to be taken seriously)"); print("=" * 100)
print(f"    {'policy':<24}{'09-03 E':>10}{'09-04 E':>10}{'pooled E':>10}{'09-03 PF':>10}{'09-04 PF':>10}")
store = {}
for p in CANDS:
    rows = run(b, p)
    store[p.name] = rows
    m3 = metrics([r for r in rows if r["day"] == "2026-09-03"])
    m4 = metrics([r for r in rows if r["day"] == "2026-09-04"])
    mp = metrics(rows)
    print(f"    {p.name:<24}{m3['exp']:>10.2f}{m4['exp']:>10.2f}{mp['exp']:>10.2f}{m3['pf']:>10.2f}{m4['pf']:>10.2f}")

# ── (c) leave-one-out robustness ──────────────────────────────────────────
print()
print("=" * 100); print("(c) LEAVE-ONE-OUT: pooled expectancy of each candidate with each single trade removed"); print("=" * 100)
print(f"    {'policy':<24}{'full':>9}{'LOO min':>9}{'LOO max':>9}{'spread':>9}   worst-case trade dropped")
for name, rows in store.items():
    exps = []
    for i in range(len(rows)):
        sub = rows[:i] + rows[i+1:]
        exps.append((metrics(sub)["exp"], rows[i]["id"]))
    lo, hi = min(exps), max(exps)
    print(f"    {name:<24}{metrics(rows)['exp']:>9.2f}{lo[0]:>9.2f}{hi[0]:>9.2f}{hi[0]-lo[0]:>9.2f}   #{lo[1]}")
print()
print("    Reading: a candidate whose LOO range straddles the control's is not separated at this n.")
