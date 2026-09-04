"""EXP-06 — test each ENTRY SIGNAL COMPONENT against the arbitrary-timing benchmark.

Design: a common universe of candidate CE entry instants on a 30s grid inside each session's
tradable span, each simulated with the SAME production exit ladder. Every instant is annotated
with the entry signal's own component values as recorded in the `signals` table at that moment
(within +/-15s, so strictly the state the bot itself saw). Then:

    benchmark  = expectancy over ALL instants          (arbitrary timing)
    component  = expectancy over instants matching a component condition

A component that carries entry information must beat the benchmark, and must do so on BOTH
sessions. Everything uses real spot/option LTP; bid/ask is fabricated in both arms equally.
"""
import sys, os, json, datetime, sqlite3, random, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DAYS = ("2026-09-03", "2026-09-04")
SPAN = {"2026-09-03": ("09:30:00", "15:10:00"), "2026-09-04": ("09:30:00", "15:10:00")}
STEP, COOLDOWN = 30, 120
b = Book()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
con.row_factory = sqlite3.Row
cur = con.cursor()
POL = Policy("production exit ladder")

# ── signal rows indexed by second ────────────────────────────────────────────
SIG = {}
for day in DAYS:
    cur.execute("SELECT timestamp,score,confidence,factors,rsi,macd_hist,market_quality_score,"
                "market_quality_grade,score_breakdown,confidence_breakdown,result "
                "FROM signals WHERE date(timestamp)=? AND direction='CE' ORDER BY timestamp", (day,))
    for r in cur.fetchall():
        SIG.setdefault(day, {})[_P(r["timestamp"])] = dict(r)

def sig_at(day, t, tol=15):
    d = SIG.get(day, {})
    for k in range(0, tol + 1):
        for s in (t - datetime.timedelta(seconds=k), t + datetime.timedelta(seconds=k)):
            if s in d:
                return d[s]
    return None

# ── universe ─────────────────────────────────────────────────────────────────
UNIV = []
for day in DAYS:
    cur.execute("SELECT DISTINCT symbol FROM ticks WHERE date(timestamp)=? AND symbol LIKE '%CE'", (day,))
    series = {r[0]: b.ticks(r[0], day) for r in cur.fetchall()}
    idx = {s: {d: p for d, p in tk} for s, tk in series.items()}
    a, z = SPAN[day]
    t, end = _P(f"{day} {a}"), _P(f"{day} {z}")
    while t <= end:
        pick = None
        for s in series:
            for off in (0, -1, 1, -2, 2):
                p = idx[s].get(t + datetime.timedelta(seconds=off))
                if p and 70.0 <= p <= 350.0:
                    pick = (s, p); break
            if pick: break
        if pick:
            UNIV.append({"day": day, "t": t, "sym": pick[0], "ltp": pick[1], "sig": sig_at(day, t)})
        t += datetime.timedelta(seconds=STEP)
print(f"universe: {len(UNIV)} candidate CE instants "
      f"({sum(1 for u in UNIV if u['sig'])} with a CE signal row within +/-15s)\n")

# ── simulate every instant once ──────────────────────────────────────────────
for u in UNIV:
    r = simulate(b, u["day"], {"symbol": u["sym"], "direction": "CE",
                               "entry_time": u["t"].strftime("%Y-%m-%d %H:%M:%S"),
                               "entry_price": round(u["ltp"] + _half_spread(u["ltp"]), 2)}, POL)
    u["res"] = r

def apply_cooldown(sel):
    out, last = [], {}
    for u in sorted(sel, key=lambda x: (x["day"], x["t"])):
        le = last.get(u["day"])
        if le and (u["t"] - le).total_seconds() < COOLDOWN:
            continue
        out.append(u)
        last[u["day"]] = u["t"] + datetime.timedelta(seconds=u["res"]["hold"])
    return out

def ev(sel, name, base=None):
    sel = apply_cooldown(sel)
    if len(sel) < 6:
        print(f"  {name:<46} n={len(sel)} (too few)"); return None
    rows = [dict(u["res"], day=u["day"], cont3=None, adv3=None) for u in sel]
    m = metrics(rows)
    per = {}
    for d in DAYS:
        sub = [r for r in rows if r["day"] == d]
        per[d] = metrics(sub)["exp"] if len(sub) >= 3 else None
    delta = f"{m['exp'] - base:+8.2f}" if base is not None else "     ref"
    p3 = f"{per[DAYS[0]]:>8.2f}" if per[DAYS[0]] is not None else "     n/a"
    p4 = f"{per[DAYS[1]]:>8.2f}" if per[DAYS[1]] is not None else "     n/a"
    both = ""
    if base is not None and per[DAYS[0]] is not None and per[DAYS[1]] is not None:
        both = "  BOTH DAYS BETTER" if (per[DAYS[0]] > BASE_D[DAYS[0]] and per[DAYS[1]] > BASE_D[DAYS[1]]) else ""
    print(f"  {name:<46} n={m['n']:<4} WR={m['wr']:>5.1f}% E=Rs{m['exp']:>8.2f} PF={m['pf']:.2f} "
          f"vs base {delta} | 09-03 {p3} 09-04 {p4}{both}")
    return m["exp"], per

print("=" * 140)
print("BENCHMARK — arbitrary CE entries, no signal condition")
print("=" * 140)
BASE, BASE_D = ev(UNIV, "ALL instants (the benchmark)")

print()
print("=" * 140)
print("EXP-06A — the composite signal: does 'signal present' beat 'signal absent'?")
print("=" * 140)
ev([u for u in UNIV if u["sig"]], "signal row PRESENT (CE condition true)", BASE)
ev([u for u in UNIV if not u["sig"]], "signal row ABSENT", BASE)

print()
print("=" * 140)
print("EXP-06B — individual components (only instants where a signal row exists)")
print("=" * 140)
S = [u for u in UNIV if u["sig"]]
def has(u, tok): return tok in (u["sig"]["factors"] or "")
ev([u for u in S if has(u, "Vol_Spike")], "factor: Vol_Spike present", BASE)
ev([u for u in S if not has(u, "Vol_Spike")], "factor: Vol_Spike absent", BASE)
for lo in (55, 60, 62):
    ev([u for u in S if (u["sig"]["rsi"] or 0) >= lo], f"strategy RSI >= {lo}", BASE)
    ev([u for u in S if (u["sig"]["rsi"] or 0) < lo], f"strategy RSI <  {lo}", BASE)
ev([u for u in S if (u["sig"]["macd_hist"] or 0) > 0], "MACD hist > 0", BASE)
ev([u for u in S if (u["sig"]["macd_hist"] or 0) <= 0], "MACD hist <= 0", BASE)
for cut in (85, 91, 92):
    ev([u for u in S if (u["sig"]["market_quality_score"] or 0) >= cut], f"market quality >= {cut}", BASE)
ev([u for u in S if u["sig"]["confidence"] and u["sig"]["confidence"] >= 78], "confidence >= 78", BASE)
ev([u for u in S if u["sig"]["confidence"] and u["sig"]["confidence"] < 78], "confidence <  78", BASE)
ev([u for u in S if u["sig"]["score"] and u["sig"]["score"] >= 63], "score >= 63", BASE)
ev([u for u in S if u["sig"]["score"] and u["sig"]["score"] < 63], "score <  63", BASE)

print()
print("=" * 140)
print("EXP-06C — score sub-components (from score_breakdown), tested one at a time")
print("=" * 140)
keys = set()
for u in S[:200]:
    try: keys |= set(json.loads(u["sig"]["score_breakdown"]).keys())
    except Exception: pass
keys = [k for k in sorted(keys) if k not in ("raw_score", "total_weight", "normalized_score_pct")]
for k in keys:
    vals = []
    for u in S:
        try: vals.append((u, json.loads(u["sig"]["score_breakdown"]).get(k)))
        except Exception: pass
    nums = sorted({v for _, v in vals if v is not None})
    if len(nums) < 2:
        print(f"  {('sub: ' + k):<46} constant at {nums[0] if nums else 'n/a'} — carries no information")
        continue
    med = nums[len(nums) // 2]
    ev([u for u, v in vals if v is not None and v >= med], f"sub: {k} >= {med}", BASE)
    ev([u for u, v in vals if v is not None and v < med], f"sub: {k} <  {med}", BASE)


# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 140)
print("EXP-06D — is 'signal present is worse' a real effect, a time-of-day artifact, or noise?")
print("=" * 140)
import collections
ON = [u for u in UNIV if u["sig"]]
OFF = [u for u in UNIV if not u["sig"]]
print(f"  raw instants: signal ON {len(ON)}, OFF {len(OFF)}")
print(f"  ON clock spread: {min(u['t'].strftime('%H:%M') for u in ON)} - {max(u['t'].strftime('%H:%M') for u in ON)}")

# (i) time-bucket matched comparison: only 30-min buckets where BOTH arms have instants
buck = lambda u: (u["day"], u["t"].hour, u["t"].minute // 30)
onb = collections.Counter(buck(u) for u in ON)
offb = collections.Counter(buck(u) for u in OFF)
shared = set(onb) & set(offb)
print(f"  30-min buckets containing both ON and OFF instants: {len(shared)}")
m_on = ev([u for u in ON if buck(u) in shared], "ON, time-bucket matched", BASE)
m_off = ev([u for u in OFF if buck(u) in shared], "OFF, time-bucket matched", BASE)

# (ii) permutation test on the ON/OFF label, holding the instants fixed
rows_on = [dict(u["res"], day=u["day"]) for u in apply_cooldown(ON)]
rows_off = [dict(u["res"], day=u["day"]) for u in apply_cooldown(OFF)]
obs = metrics(rows_on)["exp"] - metrics(rows_off)["exp"]
pool = [r["pnl"] for r in rows_on] + [r["pnl"] for r in rows_off]
n_on = len(rows_on)
rng = random.Random(3); worse = 0; N = 20000
for _ in range(N):
    rng.shuffle(pool)
    if (st.mean(pool[:n_on]) - st.mean(pool[n_on:])) <= obs:
        worse += 1
print(f"  observed ON-minus-OFF expectancy gap = Rs{obs:.2f}; permutation p(one-sided, ON worse) = {worse/N:.4f} "
      f"({N} resamples, n_on={n_on}, n_off={len(rows_off)})")

print()
print("=" * 140)
print("EXP-06E — MECHANISM: what is the option price doing when the signal fires? (causal)")
print("=" * 140)
def loc(u, sec):
    tk = b.ticks(u["sym"], u["day"])
    w = [p for d, p in tk if u["t"] - datetime.timedelta(seconds=sec) <= d <= u["t"]]
    if len(w) < 3 or max(w) == min(w):
        return None, None
    return 100 * (w[-1] - min(w)) / (max(w) - min(w)), w[-1] - w[0]
for sec in (60, 180, 300):
    for name, grp in (("signal ON ", ON), ("signal OFF", OFF)):
        pos = [loc(u, sec)[0] for u in grp]
        mom = [loc(u, sec)[1] for u in grp]
        pos = [v for v in pos if v is not None]; mom = [v for v in mom if v is not None]
        print(f"  {sec:>3}s window  {name}: option position in trailing range = {st.mean(pos):>5.1f}%   "
              f"trailing momentum into the instant = {st.mean(mom):>+6.2f} pts   (n={len(pos)})")
    print()
print("  Reading: a high position + positive momentum means the signal fires after the option has")
print("  already risen — i.e. it buys strength that has, on these two sessions, tended to revert.")
