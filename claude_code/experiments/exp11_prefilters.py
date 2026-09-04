"""EXP-11 — benchmark the PRE-FILTERS, the gates the scoring stack never sees.

Finding that motivates it (research layer, gate ladder): only 41.3% of evaluations reach the
scoring stack. The rest are rejected earlier by binary pre-filters — chop filter, the CE/PE
directional blocks, the time filter — and none of those is scored, weighted or measured
anywhere. They are the real selection mechanism.

Hypothesis: a pre-filter that earns its place blocks instants that would have LOST. One that
does not is throwing away opportunity.

Method: for every instant a given pre-filter rejected, simulate a CE entry there on the
contract actually subscribed, run the SAME production exit ladder, and compare against
arbitrary entries drawn from the whole tradable span. Cooldown is applied identically to
every arm, which also collapses a persistent condition into episodes rather than counting
one rejection per evaluation row.

Limits: CE only (PE contracts were almost never subscribed); the arms ignore the OTHER gates,
so each is an upper bound on what that one filter cost; fabricated spread in every arm.
"""
import sys, os, datetime, sqlite3, random, statistics as st
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from exit_lab import Policy, Book as LabBook, simulate, metrics, _P, _half_spread

DAYS = ("2026-09-02", "2026-09-03", "2026-09-04")
COOLDOWN = 120
MIN_PREM, MAX_PREM = 70.0, 350.0
POL = Policy("production exit ladder")

GATES = {
    "Chop filter": ("Chop filter",),
    "CE directional block": ("CE signal blocked", "CE blocked"),
    "PE directional block": ("PE signal blocked", "PE blocked"),
    "Time filter": ("Time filter",),
    "No pullback": ("No CE pullback", "No PE pullback"),
}

lab = LabBook()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
con.row_factory = sqlite3.Row
cur = con.cursor()


def quote_index(day):
    syms = [r[0] for r in cur.execute(
        "SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE '%CE'", (day,))]
    return syms, {s: {d: p for d, p in lab.ticks(s, day)} for s in syms}


def quote_at(t, syms, idx):
    for s in syms:
        for off in (0, -1, 1, -2, 2):
            p = idx[s].get(t + datetime.timedelta(seconds=off))
            if p and MIN_PREM <= p <= MAX_PREM:
                return s, p
    return None


def run(instants_by_day, label):
    """instants_by_day: {day: [datetime, ...]} -> metrics after cooldown."""
    rows, episodes = [], 0
    for day, times in instants_by_day.items():
        if not times:
            continue
        syms, idx = quote_index(day)
        if not syms:
            continue
        last = None
        for t in sorted(times):
            if last and (t - last).total_seconds() < COOLDOWN:
                continue
            q = quote_at(t, syms, idx)
            if not q:
                continue
            episodes += 1
            sym, ltp = q
            r = simulate(lab, day, {"symbol": sym, "direction": "CE",
                                    "entry_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                                    "entry_price": round(ltp + _half_spread(ltp), 2)}, POL)
            r.update(day=day, cont3=None, adv3=None)
            rows.append(r)
            last = t + datetime.timedelta(seconds=r["hold"])
    if len(rows) < 8:
        print(f"  {label:<30} n={len(rows)} (too few to read)")
        return None, rows
    m = metrics(rows)
    per = {}
    for d in DAYS:
        sub = [r for r in rows if r["day"] == d]
        per[d] = metrics(sub)["exp"] if len(sub) >= 4 else None
    fmt = lambda v: f"{v:>8.2f}" if v is not None else "     n/a"
    print(f"  {label:<30} n={m['n']:<4} WR={m['wr']:>5.1f}% E=Rs{m['exp']:>8.2f} PF={m['pf']:.2f}"
          f" | 09-02{fmt(per['2026-09-02'])} 09-03{fmt(per['2026-09-03'])} 09-04{fmt(per['2026-09-04'])}")
    return m, rows


# ── build the instant sets ────────────────────────────────────────────────
blocked = {g: {d: [] for d in DAYS} for g in GATES}
scored_days = {d: [] for d in DAYS}
for day in DAYS:
    for ts, ws, rr in cur.execute(
            "SELECT timestamp, weighted_score, reject_reason FROM dvf_signals "
            "WHERE date(timestamp)=? ORDER BY timestamp", (day,)):
        t = _P(ts)
        if ws is None:
            r = (rr or "")
            for g, pats in GATES.items():
                if any(p in r for p in pats):
                    blocked[g][day].append(t)
                    break
        else:
            scored_days[day].append(t)

# arbitrary benchmark: a 30s grid over the whole tradable span, same ladder, same cooldown
arb = {d: [] for d in DAYS}
for day in DAYS:
    t, end = _P(f"{day} 09:30:00"), _P(f"{day} 15:10:00")
    while t <= end:
        arb[day].append(t)
        t += datetime.timedelta(seconds=30)

print("=" * 132)
print("EXP-11 — do the unscored pre-filters block instants that would have lost?")
print("=" * 132)
base_m, base_rows = run(arb, "BENCHMARK arbitrary timing")
print()
print("  Instants each pre-filter rejected, entered anyway:")
results = {}
for g in GATES:
    n_raw = sum(len(v) for v in blocked[g].values())
    if n_raw == 0:
        continue
    m, rows = run(blocked[g], f"blocked by {g}")
    if m:
        results[g] = (m, rows, n_raw)
print()
m, _ = run(scored_days, "reached the scoring stack")

print()
print("=" * 132)
print("VERDICT per gate — protective if entering there is WORSE than arbitrary")
print("=" * 132)
base = [r["pnl"] for r in base_rows]
print(f"  {'gate':<26}{'rows rejected':>14}{'episodes':>10}{'E/trade':>10}{'vs base':>10}{'p':>8}   reading")
for g, (m, rows, n_raw) in sorted(results.items(), key=lambda kv: kv[1][0]["exp"]):
    x = [r["pnl"] for r in rows]
    obs = st.mean(x) - st.mean(base)
    pool = x + base
    n = len(x)
    rng = random.Random(17)
    c = 0
    N = 20000
    for _ in range(N):
        rng.shuffle(pool)
        if st.mean(pool[:n]) - st.mean(pool[n:]) <= obs:
            c += 1
    p = c / N
    verdict = ("PROTECTIVE" if obs < 0 and p < 0.10 else
               "COSTLY" if obs > 0 and (1 - p) < 0.10 else
               "no measurable effect")
    print(f"  {g:<26}{n_raw:>14,}{m['n']:>10}{m['exp']:>10.2f}{obs:>10.2f}{p:>8.3f}   {verdict}")
print()
print("  p is one-sided for 'worse than arbitrary'. Each arm ignores the other gates, so it is")
print("  an upper bound on what that filter alone cost or saved. CE only; fabricated spread in")
print("  every arm equally, so the comparison holds even though the level does not.")
