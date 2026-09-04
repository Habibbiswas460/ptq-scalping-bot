"""EXP-09 — measure the DELTA repair on its own.

delta is recoverable from history: spot, option LTP, strike and expiry are all persisted, and
GreeksCalculator.calculate_from_ltp is the same routine the live path uses. So the repair can
be measured before it is ever switched on live.

Three questions, in order:
  1. once populated, does delta actually land in the band the scorer rewards (0.35-0.65)?
  2. does the score gain real variance, i.e. can it now rank at all?
  3. does that new variance carry any information against the arbitrary-timing benchmark?
"""
import sys, os, sqlite3, datetime, statistics as st, collections
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, "/home/lora/projects/PTQ-scalping bot")
from utils.greeks import GreeksCalculator
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
DAYS = ("2026-09-03", "2026-09-04")
EXPIRY = datetime.datetime(2026, 9, 8, 15, 30, 0)
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; cur = con.cursor()
b = Book()

def strike_of(sym):
    core = sym.replace("NIFTY", "")
    return float(core[7:-2])

print("=" * 112)
print("(1) DELTA DISTRIBUTION once populated — does it land in the band the scorer rewards?")
print("=" * 112)
print(f"    scorer: full credit at 0.35 <= delta <= 0.65, half credit at 0.30-0.70, else ZERO")
buckets = collections.Counter()
per_sym = collections.defaultdict(list)
rows = []
for day in DAYS:
    cur.execute("SELECT timestamp, symbol, ltp, spot_price FROM ticks WHERE date(timestamp)=? "
                "AND spot_price>0 AND symbol LIKE 'NIFTY%' ORDER BY timestamp", (day,))
    prev = None
    for r in cur.fetchall():
        t = _P(r["timestamp"])
        if prev and (t - prev).total_seconds() < 30:      # 30s sample, enough for a distribution
            continue
        prev = t
        tte = (EXPIRY - t).total_seconds()
        g = GreeksCalculator.calculate_from_ltp(ltp=r["ltp"], spot_price=r["spot_price"],
                                                strike_price=strike_of(r["symbol"]),
                                                time_to_expiry_sec=tte,
                                                option_type=r["symbol"][-2:])
        d = g.get("delta", 0.0)
        per_sym[(day, r["symbol"])].append(d)
        if 0.35 <= d <= 0.65:      buckets["full credit (0.35-0.65)"] += 1
        elif 0.30 <= d <= 0.70:    buckets["half credit (0.30-0.70)"] += 1
        else:                      buckets["ZERO (outside 0.30-0.70)"] += 1
        rows.append((day, t, r["symbol"], d))
tot = sum(buckets.values())
for k in ("full credit (0.35-0.65)", "half credit (0.30-0.70)", "ZERO (outside 0.30-0.70)"):
    print(f"    {k:<28} {buckets[k]:>6} / {tot}  ({100*buckets[k]/tot:>5.1f}%)")
print()
for (day, sym), ds in sorted(per_sym.items()):
    print(f"    {day} {sym:<22} n={len(ds):>5}  delta median={st.median(ds):.3f}  "
          f"min={min(ds):.3f} max={max(ds):.3f}  in-band={100*sum(1 for d in ds if 0.35<=d<=0.65)/len(ds):>5.1f}%")

print()
print("=" * 112)
print("(2) SCORE VARIANCE — what the repair adds to the 105-point score")
print("=" * 112)
full = sum(1 for _, _, _, d in rows if 0.35 <= d <= 0.65)
half = sum(1 for _, _, _, d in rows if 0.30 <= d <= 0.70 and not 0.35 <= d <= 0.65)
print(f"    delta component (weight 10) + greeks component (weight 5): both keyed off the same test")
print(f"      would award 15/15 on {100*full/tot:.1f}% of sampled instants, 7/15 on {100*half/tot:.1f}%, 0/15 on the rest")
print(f"    before the repair both were 0 on 100% of 89,673 recorded signal rows")
add = [15 if 0.35 <= d <= 0.65 else (7 if 0.30 <= d <= 0.70 else 0) for _, _, _, d in rows]
print(f"    added score points: mean {st.mean(add):.1f} / 105, distinct values {sorted(set(add))}")
print(f"    -> normalised score would move by up to {100*15/105:.1f} percentage points between instants")


# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 112)
print("(3) DOES THE NEW VARIANCE CARRY INFORMATION?  delta-in-band as a causal entry filter,")
print("    same exit ladder, same contracts, same cooldown, against the arbitrary benchmark.")
print("=" * 112)
POL = Policy("production exit ladder")
COOLDOWN = 120
UNIV = []
for day in DAYS:
    cur.execute("SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE '%CE'", (day,))
    syms = [r[0] for r in cur.fetchall()]
    idx = {s: {d: p for d, p in b.ticks(s, day)} for s in syms}
    spot = {}
    cur.execute("SELECT timestamp, spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0", (day,))
    for ts, sp in cur.fetchall():
        spot.setdefault(_P(ts), sp)
    t, end = _P(f"{day} 09:30:00"), _P(f"{day} 15:10:00")
    while t <= end:
        pick = None
        for s in syms:
            for off in (0, -1, 1, -2, 2):
                p = idx[s].get(t + datetime.timedelta(seconds=off))
                if p and 70.0 <= p <= 350.0:
                    pick = (s, p); break
            if pick: break
        sp = next((spot[t + datetime.timedelta(seconds=o)] for o in (0, -1, 1, -2, 2)
                   if t + datetime.timedelta(seconds=o) in spot), None)
        if pick and sp:
            g = GreeksCalculator.calculate_from_ltp(ltp=pick[1], spot_price=sp,
                                                    strike_price=strike_of(pick[0]),
                                                    time_to_expiry_sec=(EXPIRY - t).total_seconds(),
                                                    option_type='CE')
            UNIV.append({"day": day, "t": t, "sym": pick[0], "ltp": pick[1],
                         "delta": g.get("delta", 0.0)})
        t += datetime.timedelta(seconds=30)

for u in UNIV:
    u["res"] = simulate(b, u["day"], {"symbol": u["sym"], "direction": "CE",
                                      "entry_time": u["t"].strftime("%Y-%m-%d %H:%M:%S"),
                                      "entry_price": round(u["ltp"] + _half_spread(u["ltp"]), 2)}, POL)

def ev(sel, name):
    out, last = [], {}
    for u in sorted(sel, key=lambda x: (x["day"], x["t"])):
        le = last.get(u["day"])
        if le and (u["t"] - le).total_seconds() < COOLDOWN:
            continue
        out.append(u); last[u["day"]] = u["t"] + datetime.timedelta(seconds=u["res"]["hold"])
    if len(out) < 6:
        print(f"    {name:<42} n={len(out)} (too few)"); return
    rws = [dict(u["res"], day=u["day"], cont3=None, adv3=None) for u in out]
    m = metrics(rws)
    per = {}
    for d in DAYS:
        sub = [r for r in rws if r["day"] == d]
        per[d] = f"{metrics(sub)['exp']:>8.2f}" if len(sub) >= 3 else "     n/a"
    print(f"    {name:<42} n={m['n']:<4} WR={m['wr']:>5.1f}% E=Rs{m['exp']:>8.2f} PF={m['pf']:.2f} "
          f"| 09-03 {per[DAYS[0]]} 09-04 {per[DAYS[1]]}")

ev(UNIV, "ALL instants (benchmark)")
ev([u for u in UNIV if 0.35 <= u["delta"] <= 0.65], "delta IN band 0.35-0.65 (full credit)")
ev([u for u in UNIV if not 0.35 <= u["delta"] <= 0.65], "delta OUT of band")
ev([u for u in UNIV if 0.45 <= u["delta"] <= 0.55], "delta 0.45-0.55 (tightest ATM)")
ev([u for u in UNIV if u["delta"] > 0.65], "delta > 0.65 (deep ITM)")
print()
print("    A component only helps if the in-band arm beats the benchmark on BOTH days.")
