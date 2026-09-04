"""EXP-05C — randomisation test for 'the entry signal picks worse-than-arbitrary moments'.

Draw many random sets of entry instants from the SAME active windows, same contracts, same
exit ladder and same cooldown rule the strategy obeyed, and see where the strategy's own
expectancy falls in that null distribution.
"""
import sys, os, datetime, sqlite3, random, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DAYS = ("2026-09-03", "2026-09-04")
WIN = {"2026-09-03": ("11:10:14", "14:15:11"), "2026-09-04": ("09:50:10", "11:11:54")}
COOLDOWN = 120
b = Book()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db"); cur = con.cursor()

cands = []
for day in DAYS:
    cur.execute("SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE '%CE'", (day,))
    series = {s[0]: b.ticks(s[0], day) for s in cur.fetchall()}
    a, z = WIN[day]
    t = _P(f"{day} {a}")
    end = _P(f"{day} {z}")
    while t <= end:
        for s, tk in series.items():
            hit = [p for d, p in tk if abs((d - t).total_seconds()) <= 2]
            if hit and 70.0 <= hit[0] <= 350.0:
                cands.append((day, t, s, hit[0])); break
        t += datetime.timedelta(seconds=10)
print(f"candidate CE entry instants inside the strategy's own active windows (10s grid): {len(cands)}")

POL = Policy("production ladder")
def run(sample):
    tr, last = [], {}
    for day, t, sym, ltp in sorted(sample, key=lambda x: (x[0], x[1])):
        le = last.get(day)
        if le and (t - le).total_seconds() < COOLDOWN:
            continue
        r = simulate(b, day, {"symbol": sym, "direction": "CE",
                              "entry_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                              "entry_price": round(ltp + _half_spread(ltp), 2)}, POL)
        tr.append(r); last[day] = t + datetime.timedelta(seconds=r["hold"])
    return tr

# strategy's own
cur.execute("SELECT symbol,direction,entry_time,entry_price FROM trades WHERE date(entry_time) IN (?,?) ORDER BY entry_time", DAYS)
own = [simulate(b, et[:10], {"symbol": s, "direction": d, "entry_time": et, "entry_price": ep}, POL)
       for s, d, et, ep in cur.fetchall()]
obs = metrics(own)["exp"]
print(f"strategy-selected entries: n={len(own)}  E=Rs{obs:.2f}")

rng = random.Random(11)
per_day = {d: [c for c in cands if c[0] == d] for d in DAYS}
n_per_day = {d: sum(1 for r in own if r.get('day') == d) for d in DAYS}
# match the strategy's per-day trade counts so day mix is not a confound
cur.execute("SELECT date(entry_time), count(*) FROM trades WHERE date(entry_time) IN (?,?) GROUP BY 1", DAYS)
n_per_day = dict(cur.fetchall())
print(f"matching per-day counts: {n_per_day}")

null = []
for _ in range(2000):
    samp = []
    for d in DAYS:
        k = min(n_per_day.get(d, 0) * 3, len(per_day[d]))   # oversample, cooldown thins it back
        samp += rng.sample(per_day[d], k)
    tr = run(samp)
    if tr:
        null.append(metrics(tr)["exp"])
null.sort()
worse = sum(1 for v in null if v <= obs)
print()
print(f"null distribution of arbitrary-timed CE entries in the same windows (2000 draws):")
print(f"  mean=Rs{st.mean(null):.2f}  median=Rs{st.median(null):.2f}  "
      f"p05=Rs{null[int(.05*len(null))]:.2f}  p95=Rs{null[int(.95*len(null))]:.2f}")
print(f"  draws at or below the strategy's Rs{obs:.2f}: {worse}/{len(null)}  ->  p = {worse/len(null):.4f}")
print()
print("  Interpretation: a low p means the strategy's entry timing performed worse than")
print("  arbitrary timing in the same windows more often than chance would produce.")
print("  Limits: 2 sessions, n=24 strategy trades, CE only (PE was almost never the")
print("  subscribed contract), synthetic spread in both arms, and the arbitrary arm ignores")
print("  the chop filter / session gates / rotation / drift guard, so it is a BENCHMARK, not")
print("  a deployable alternative.")
