"""EXP-08 — decompose the entry stack into its three layers and benchmark each.

  layer 1  the raw CE signal condition   (signal row present)
  layer 2  the gate stack                (what the strategy actually took vs what it skipped
                                          while the condition was true)
  layer 3  arbitrary timing              (the benchmark)
"""
import sys, os, datetime, sqlite3, random, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DAYS = ("2026-09-03", "2026-09-04")
COOLDOWN = 120
b = Book()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
con.row_factory = sqlite3.Row; cur = con.cursor()
POL = Policy("production exit ladder")

def sim(day, sym, t, ltp):
    return simulate(b, day, {"symbol": sym, "direction": "CE",
                             "entry_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                             "entry_price": round(ltp + _half_spread(ltp), 2)}, POL)

def quote(day, t, series, idx):
    for s in series:
        for off in (0, -1, 1, -2, 2):
            p = idx[s].get(t + datetime.timedelta(seconds=off))
            if p and 70.0 <= p <= 350.0:
                return s, p
    return None

def cool(items):
    out, last = [], {}
    for day, t, r in sorted(items, key=lambda x: (x[0], x[1])):
        le = last.get(day)
        if le and (t - le).total_seconds() < COOLDOWN:
            continue
        out.append((day, t, r)); last[day] = t + datetime.timedelta(seconds=r["hold"])
    return out

def show(items, name, apply_cool=True):
    if apply_cool:
        items = cool(items)
    if len(items) < 5:
        print(f"  {name:<52} n={len(items)} (too few)"); return None
    rows = [dict(r, day=d) for d, t, r in items]
    m = metrics(rows)
    per = {}
    for d in DAYS:
        sub = [r for r in rows if r["day"] == d]
        per[d] = metrics(sub)["exp"] if len(sub) >= 3 else None
    fmt = lambda v: f"{v:>8.2f}" if v is not None else "     n/a"
    print(f"  {name:<52} n={m['n']:<4} WR={m['wr']:>5.1f}% E=Rs{m['exp']:>8.2f} PF={m['pf']:.2f} "
          f"| 09-03 {fmt(per[DAYS[0]])} 09-04 {fmt(per[DAYS[1]])}")
    return rows

ARB, ON_TAKEN, ON_SKIPPED = [], [], []
for day in DAYS:
    cur.execute("SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE '%CE'", (day,))
    series = [r[0] for r in cur.fetchall()]
    idx = {s: {d: p for d, p in b.ticks(s, day)} for s in series}

    # arbitrary benchmark: 30s grid over the tradable span
    t, end = _P(f"{day} 09:30:00"), _P(f"{day} 15:10:00")
    while t <= end:
        q = quote(day, t, series, idx)
        if q:
            ARB.append((day, t, sim(day, q[0], t, q[1])))
        t += datetime.timedelta(seconds=30)

    # every CE signal instant, split by whether the gate stack let it through
    cur.execute("SELECT timestamp, was_taken FROM signals WHERE date(timestamp)=? AND direction='CE' "
                "ORDER BY timestamp", (day,))
    seen = set()
    for ts, taken in cur.fetchall():
        t = _P(ts)
        key = t.replace(second=(t.second // 30) * 30)
        if key in seen:
            continue
        seen.add(key)
        q = quote(day, t, series, idx)
        if not q:
            continue
        rec = (day, t, sim(day, q[0], t, q[1]))
        (ON_TAKEN if taken else ON_SKIPPED).append(rec)

print("=" * 128)
print("EXP-08 — the entry stack, layer by layer (same exit ladder, same contracts, same cooldown)")
print("=" * 128)
a = show(ARB, "layer 3: ARBITRARY timing (benchmark)")
s = show(ON_SKIPPED + ON_TAKEN, "layer 1: CE signal condition true (all such instants)")
sk = show(ON_SKIPPED, "layer 2a: condition true but the GATES SKIPPED it")
tk = show(ON_TAKEN, "layer 2b: condition true and the GATES LET IT THROUGH")

# the strategy's real trades, for reference
cur.execute("SELECT symbol,direction,entry_time,entry_price FROM trades WHERE date(entry_time) IN (?,?) "
            "ORDER BY entry_time", DAYS)
real = [(et[:10], _P(et), simulate(b, et[:10], {"symbol": sy, "direction": dr, "entry_time": et,
                                                "entry_price": ep}, POL))
        for sy, dr, et, ep in cur.fetchall()]
show(real, "reference: the strategy's actual entries (real cooldown already applied)", apply_cool=False)

print()
print("  Permutation tests against the arbitrary benchmark (one-sided, 20000 resamples):")
base = [r["pnl"] for r in a]
for rows, nm in ((s, "layer 1 signal condition"), (tk, "layer 2b gates let through"),
                 ([dict(r, day=d) for d, t, r in real], "actual entries (all 24)")):
    if not rows:
        continue
    x = [r["pnl"] for r in rows]
    obs = st.mean(x) - st.mean(base)
    pool = x + base; n = len(x); rng = random.Random(5); c = 0
    for _ in range(20000):
        rng.shuffle(pool)
        if st.mean(pool[:n]) - st.mean(pool[n:]) <= obs:
            c += 1
    print(f"    {nm:<30} gap vs benchmark = Rs{obs:>8.2f}   p(worse than arbitrary) = {c/20000:.4f}   n={n}")
