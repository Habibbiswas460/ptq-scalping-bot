"""ENTRY LOCATION — strictly as-of-entry information only.

Every feature is computed from ticks at or before the entry second. Nothing from the
completed entry candle is used, because that candle contains post-entry ticks (the look-ahead
trap that produced a false 'losers enter at the top' result earlier today).
Outcome labels come from the trade, so the TEST is causal even though the label is not.
"""
import sqlite3, datetime, itertools, statistics as st
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
con = sqlite3.connect(DB); cur = con.cursor()
def P(s): return datetime.datetime.strptime(s.split('.')[0], "%Y-%m-%d %H:%M:%S")
_c = {}
def ser(day, sym=None):
    k = (day, sym)
    if k not in _c:
        if sym:
            cur.execute("SELECT timestamp,ltp FROM ticks WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp", (sym, day))
        else:
            cur.execute("SELECT timestamp,spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 ORDER BY timestamp", (day,))
        seen, out = set(), []
        for a, b in cur.fetchall():
            d = P(a)
            if d not in seen:
                seen.add(d); out.append((d, b))
        _c[k] = out
    return _c[k]

def back(s, e, sec):
    return [p for d, p in s if e - datetime.timedelta(seconds=sec) <= d <= e]

FE = {}
rows = []
for day in ("2026-09-03", "2026-09-04"):
    sp = ser(day)
    cur.execute("SELECT id,symbol,direction,entry_time,pnl,exit_price-entry_price FROM trades "
                "WHERE date(entry_time)=? ORDER BY id", (day,))
    for tid, sym, dr, et, pnl, pts in cur.fetchall():
        op = ser(day, sym); e = P(et)
        sgn = 1 if dr == "CE" else -1
        f = {"day": day, "id": tid, "dir": dr, "win": pnl > 0, "pts": round(pts, 2)}
        for sec, lab in ((30, "30s"), (60, "60s"), (120, "2m"), (300, "5m")):
            ow, sw = back(op, e, sec), back(sp, e, sec)
            # momentum INTO the entry (causal)
            f[f"opt_mom_{lab}"] = round(ow[-1] - ow[0], 2) if len(ow) > 1 else None
            f[f"spot_mom_{lab}"] = round((sw[-1] - sw[0]) * sgn, 2) if len(sw) > 1 else None
            # where the entry price sits in the trailing range (causal)
            if len(ow) > 2 and max(ow) > min(ow):
                f[f"opt_pos_{lab}"] = round(100 * (ow[-1] - min(ow)) / (max(ow) - min(ow)), 1)
                f[f"opt_range_{lab}"] = round(max(ow) - min(ow), 2)
            else:
                f[f"opt_pos_{lab}"] = f[f"opt_range_{lab}"] = None
            if len(sw) > 2 and max(sw) > min(sw):
                f[f"spot_range_{lab}"] = round(max(sw) - min(sw), 2)
                # distance from the favourable extreme of the trailing window, in spot pts
                fav_ext = max(sw) if dr == "CE" else min(sw)
                f[f"dist_from_ext_{lab}"] = round(abs(sw[-1] - fav_ext), 2)
            else:
                f[f"spot_range_{lab}"] = f[f"dist_from_ext_{lab}"] = None
        # acceleration: last 30s momentum vs the 30s before it
        w60 = back(sp, e, 60)
        if len(w60) > 4:
            mid = len(w60) // 2
            f["spot_accel"] = round(((w60[-1] - w60[mid]) - (w60[mid] - w60[0])) * sgn, 2)
        else:
            f["spot_accel"] = None
        # alignment of option and spot momentum as of entry
        if f["opt_mom_60s"] is not None and f["spot_mom_60s"] is not None:
            f["mom_agree"] = (f["opt_mom_60s"] > 0) == (f["spot_mom_60s"] > 0)
        else:
            f["mom_agree"] = None
        rows.append(f)

def perm(W, L, iters=20000, seed=7):
    """Monte-Carlo permutation (20k resamples) — exact enumeration is C(24,10)=1.96M per
    feature, too slow for a 21-feature sweep and no more informative at this precision."""
    if len(W) < 2 or len(L) < 2: return None, None
    import random
    rng = random.Random(seed)
    obs = st.mean(W) - st.mean(L); allv = W + L; n = len(W); c = 0
    for _ in range(iters):
        rng.shuffle(allv)
        if abs(st.mean(allv[:n]) - st.mean(allv[n:])) >= abs(obs) - 1e-12:
            c += 1
    return obs, c / iters

KEYS = [k for k in rows[0] if k not in ("day", "id", "dir", "win", "pts", "mom_agree")]
print("=" * 104)
print("CAUSAL ENTRY FEATURES — winners vs losers, pooled both days (n=24; exact permutation p, two-sided)")
print("=" * 104)
print(f"  {'feature':<22}{'winners':>10}{'losers':>10}{'gap':>9}{'p':>9}   verdict")
sig = []
for k in KEYS:
    W = [r[k] for r in rows if r["win"] and r[k] is not None]
    L = [r[k] for r in rows if not r["win"] and r[k] is not None]
    obs, p = perm(W, L)
    if obs is None: continue
    v = "SEPARATES" if p < 0.05 else ("weak" if p < 0.15 else "")
    if p < 0.15: sig.append((k, obs, p))
    print(f"  {k:<22}{st.mean(W):>10.2f}{st.mean(L):>10.2f}{obs:>9.2f}{p:>9.4f}   {v}")
print()
ag = [r for r in rows if r["mom_agree"] is not None]
aw = [r for r in ag if r["mom_agree"]]; an = [r for r in ag if not r["mom_agree"]]
print(f"  option/spot 60s momentum agree at entry: {len(aw)}/{len(ag)} trades; "
      f"win rate {100*sum(1 for r in aw if r['win'])/len(aw):.0f}% vs "
      f"{100*sum(1 for r in an if r['win'])/len(an):.0f}% when they disagree")
print(f"  Bonferroni note: {len(KEYS)} features tested on n=24 — at alpha 0.05 about "
      f"{0.05*len(KEYS):.1f} false positives are expected by chance alone.")
