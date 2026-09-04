"""EXP-05 — is there ANY simple causal directional filter that gives the entry an edge?

Finding that motivates it: entries align with the containing >=15pt spot leg 11/24 times
(46%, coin flip) and no causal entry feature separates winners from losers (all p>0.12).
Hypothesis: a spot-momentum-as-of-entry filter can raise alignment and expectancy.

Method: build an opportunity universe — a candidate CE and PE entry every 30s across both
sessions on the contract that was actually subscribed — apply each causal filter, run the
SAME production exit ladder, and measure. This is far larger than n=24 and every filter input
is strictly as-of-entry. It ignores the strategy's own signal, so it tests the FILTER, not
the strategy; the production entries are shown alongside as the reference point.
"""
import sys, os, datetime, sqlite3, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DAYS = ("2026-09-03", "2026-09-04")
STEP = 30
b = Book()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
cur = con.cursor()

def spot(day):
    cur.execute("SELECT timestamp,spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 ORDER BY timestamp", (day,))
    seen, out = set(), []
    for a, p in cur.fetchall():
        d = _P(a)
        if d not in seen:
            seen.add(d); out.append((d, p))
    return out

def symbols(day):
    cur.execute("SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE 'NIFTY%'", (day,))
    return [r[0] for r in cur.fetchall()]

UNIV = []
for day in DAYS:
    sp = spot(day); spd = dict(sp)
    series = {s: b.ticks(s, day) for s in symbols(day)}
    t = sp[0][0].replace(second=0, microsecond=0) + datetime.timedelta(minutes=10)
    end = sp[-1][0] - datetime.timedelta(minutes=12)
    while t <= end:
        # the contract carrying ticks at this instant, premium inside the production band
        act = None
        for s, tk in series.items():
            hit = [p for d, p in tk if abs((d - t).total_seconds()) <= 2]
            if hit and 70.0 <= hit[0] <= 350.0:
                act = (s, hit[0]); break
        sw = [p for d, p in sp if t - datetime.timedelta(seconds=300) <= d <= t]
        if act and len(sw) > 10:
            UNIV.append({"day": day, "t": t, "sym": act[0], "ltp": act[1],
                         "m30": sw[-1] - sw[max(0, len(sw) - 30)], "m60": sw[-1] - sw[max(0, len(sw) - 60)],
                         "m300": sw[-1] - sw[0],
                         "rng60": max(sw[-60:]) - min(sw[-60:]),
                         "is_ce": act[0].endswith("CE")})
        t += datetime.timedelta(seconds=STEP)
print(f"opportunity universe: {len(UNIV)} candidate entry instants across {len(DAYS)} sessions "
      f"(every {STEP}s, premium in Rs70-350)\n")

POL = Policy("production exit ladder")
COOLDOWN = 120

def run_filter(name, pick):
    """pick(u) -> 'CE' | 'PE' | None ; only the contract actually subscribed can be traded,
    so a CE choice is only executable on a CE contract (and likewise PE)."""
    trades, last = [], {}
    for u in UNIV:
        want = pick(u)
        if want is None:
            continue
        if (want == "CE") != u["is_ce"]:
            continue
        le = last.get(u["day"])
        if le and (u["t"] - le).total_seconds() < COOLDOWN:
            continue
        entry = round(u["ltp"] + _half_spread(u["ltp"]), 2)
        r = simulate(b, u["day"], {"symbol": u["sym"], "direction": want,
                                   "entry_time": u["t"].strftime("%Y-%m-%d %H:%M:%S"),
                                   "entry_price": entry}, POL)
        r.update(day=u["day"], cont3=None, adv3=None)
        trades.append(r)
        last[u["day"]] = u["t"] + datetime.timedelta(seconds=r["hold"])
    if len(trades) < 5:
        print(f"  {name:<44} n={len(trades)} (too few)"); return
    m = metrics(trades)
    per = {d: metrics([r for r in trades if r["day"] == d]) for d in DAYS}
    print(f"  {name:<44} n={m['n']:<4} WR={m['wr']:>5.1f}% avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} "
          f"E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} | 09-03 E={per[DAYS[0]]['exp']:>7.2f} 09-04 E={per[DAYS[1]]['exp']:>7.2f}")

print("=" * 132)
print("EXP-05 — causal directional filters, all using the production exit ladder")
print("=" * 132)
run_filter("F0 no filter, always CE", lambda u: "CE")
run_filter("F0b no filter, always PE", lambda u: "PE")
for thr in (2, 5, 10):
    run_filter(f"F1 spot 60s momentum >= +{thr} -> CE", lambda u, t=thr: "CE" if u["m60"] >= t else None)
    run_filter(f"F1 spot 60s momentum <= -{thr} -> PE", lambda u, t=thr: "PE" if u["m60"] <= -t else None)
for thr in (5, 10, 20):
    run_filter(f"F2 spot 5m momentum >= +{thr} -> CE", lambda u, t=thr: "CE" if u["m300"] >= t else None)
    run_filter(f"F2 spot 5m momentum <= -{thr} -> PE", lambda u, t=thr: "PE" if u["m300"] <= -t else None)
run_filter("F3 trend-follow: 5m and 60s agree UP", lambda u: "CE" if (u["m300"] >= 10 and u["m60"] >= 2) else None)
run_filter("F3 trend-follow: 5m and 60s agree DOWN", lambda u: "PE" if (u["m300"] <= -10 and u["m60"] <= -2) else None)
run_filter("F4 mean-revert: 5m down >=10 -> CE", lambda u: "CE" if u["m300"] <= -10 else None)
run_filter("F4 mean-revert: 5m up >=10 -> PE", lambda u: "PE" if u["m300"] >= 10 else None)
run_filter("F5 low-vol only (60s range <=4) -> CE", lambda u: "CE" if u["rng60"] <= 4 else None)
run_filter("F5 high-vol only (60s range >=10) -> CE", lambda u: "CE" if u["rng60"] >= 10 else None)


# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 132)
print("EXP-05B — DOES THE ENTRY SIGNAL ADD VALUE?  Same exit ladder, same active windows,")
print("          strategy-selected entries vs unselected entries every 30s in those windows.")
print("=" * 132)
WINDOWS = {"2026-09-03": ("11:10:14", "14:15:11"), "2026-09-04": ("09:50:10", "11:11:54")}
sel = [u for u in UNIV if WINDOWS[u["day"]][0] <= u["t"].strftime("%H:%M:%S") <= WINDOWS[u["day"]][1]]
print(f"  candidate instants inside the strategy's own active windows: {len(sel)}")

def run_on(cands, name, want="CE"):
    trades, last = [], {}
    for u in cands:
        if (want == "CE") != u["is_ce"]:
            continue
        le = last.get(u["day"])
        if le and (u["t"] - le).total_seconds() < COOLDOWN:
            continue
        entry = round(u["ltp"] + _half_spread(u["ltp"]), 2)
        r = simulate(b, u["day"], {"symbol": u["sym"], "direction": want,
                                   "entry_time": u["t"].strftime("%Y-%m-%d %H:%M:%S"),
                                   "entry_price": entry}, POL)
        r.update(day=u["day"], cont3=None, adv3=None)
        trades.append(r); last[u["day"]] = u["t"] + datetime.timedelta(seconds=r["hold"])
    if len(trades) < 3:
        print(f"  {name:<48} n={len(trades)} (too few)"); return None
    m = metrics(trades)
    per = {d: metrics([r for r in trades if r["day"] == d]) for d in DAYS}
    print(f"  {name:<48} n={m['n']:<4} WR={m['wr']:>5.1f}% avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} "
          f"E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} | 09-03 E={per[DAYS[0]]['exp'] if per[DAYS[0]]['n'] else float('nan'):>7.2f} "
          f"09-04 E={per[DAYS[1]]['exp'] if per[DAYS[1]]['n'] else float('nan'):>7.2f}")
    return m

run_on(sel, "unselected CE entries in the same windows")

# the strategy's own entries, same ladder, for reference
rows, last = [], None
cur.execute("SELECT id,symbol,direction,entry_time,entry_price FROM trades "
            "WHERE date(entry_time) IN (?,?) ORDER BY entry_time", DAYS)
for tid, sym, dr, et, ep in cur.fetchall():
    r = simulate(b, et[:10], {"symbol": sym, "direction": dr, "entry_time": et, "entry_price": ep}, POL)
    r.update(day=et[:10], cont3=None, adv3=None); rows.append(r)
m = metrics(rows); per = {d: metrics([r for r in rows if r["day"] == d]) for d in DAYS}
print(f"  {'strategy-selected entries (production)':<48} n={m['n']:<4} WR={m['wr']:>5.1f}% "
      f"avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} | "
      f"09-03 E={per[DAYS[0]]['exp']:>7.2f} 09-04 E={per[DAYS[1]]['exp']:>7.2f}")
print()
print("  NOTE: the unselected arm ignores the chop filter, session gates, strike rotation and")
print("  drift guard, so it is not a runnable alternative — it is a BENCHMARK for whether the")
print("  signal's entry timing is better than arbitrary timing in the same conditions.")
