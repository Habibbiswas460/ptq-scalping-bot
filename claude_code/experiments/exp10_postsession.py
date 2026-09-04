"""EXP-10 — run this AFTER the next live-paper session with TICK_DELTA_ENABLED and
TICK_OI_ENABLED on. Attributes what the repair actually did.

Usage:  python claude_code/experiments/exp10_postsession.py YYYY-MM-DD

Both flags are on together, so attribution comes from the per-row breakdowns the signals
table already records, not from running two separate sessions.

Known and accepted before the run (see the pre-flight in the tick-input-repair record):
the repair pushes confidence from ~83 to 98-100, which makes MIN_CONFIDENCE_AFTER_3SL=85
inert. Expect MORE trades and no post-3-loss lock. Section 4 separates that gate effect from
any genuine ranking improvement.
"""
import sys, sqlite3, json, collections, statistics as st

DAY = sys.argv[1] if len(sys.argv) > 1 else None
if not DAY:
    sys.exit("usage: exp10_postsession.py YYYY-MM-DD")
BASE = ("2026-09-03", "2026-09-04")          # the two pre-repair reference sessions
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=" * 100)
print(f"(1) DID THE INPUTS ACTUALLY POPULATE?  {DAY}")
print("=" * 100)
cur.execute("SELECT count(*) n, sum(oi IS NOT NULL AND oi>0) oi_ok FROM ticks WHERE date(timestamp)=?", (DAY,))
r = cur.fetchone()
print(f"    ticks: {r['n']}  with oi>0: {r['oi_ok']} ({100*(r['oi_ok'] or 0)/max(r['n'],1):.1f}%)"
      f"   [was 0.0% on every historical day]")
for day in (DAY,) + BASE:
    cur.execute("SELECT score_breakdown FROM signals WHERE date(timestamp)=? AND score_breakdown<>''", (day,))
    v = collections.defaultdict(set)
    for (blob,) in cur.fetchall():
        try: d = json.loads(blob)
        except Exception: continue
        for k, x in d.items():
            if isinstance(x, (int, float)): v[k].add(round(float(x), 2))
    if not v: continue
    dead = sorted(k for k in v if len(v[k]) == 1 and k not in ("total_weight",))
    print(f"    {day}: constant sub-components = {len(dead)}  -> {dead}")
print("    (delta / greeks / oi leaving that list is the repair working)")

print()
print("=" * 100)
print("(2) SCORE AND CONFIDENCE VARIANCE")
print("=" * 100)
for day in (DAY,) + BASE:
    cur.execute("SELECT score, confidence, count(*) n FROM signals WHERE date(timestamp)=? "
                "AND direction<>'' GROUP BY score, confidence ORDER BY n DESC", (day,))
    rows = cur.fetchall()
    if not rows: continue
    tot = sum(r["n"] for r in rows)
    top = rows[0]
    print(f"    {day}: {len(rows)} distinct (score,confidence) pairs over {tot} rows; "
          f"most common ({top['score']},{top['confidence']}) = {100*top['n']/tot:.1f}%")

print()
print("=" * 100)
print("(3) TRADING OUTCOME vs the two pre-repair sessions")
print("=" * 100)
print(f"    {'day':<12}{'n':>4}{'W/L':>8}{'pnl':>10}{'E/trade':>10}{'avgW':>8}{'avgL':>8}{'hold':>8}")
for day in (DAY,) + BASE:
    cur.execute("SELECT count(*) n, sum(pnl) pnl, sum(pnl>0) w, avg(hold_time_sec) h, "
                "avg(CASE WHEN pnl>0 THEN exit_price-entry_price END) aw, "
                "avg(CASE WHEN pnl<=0 THEN exit_price-entry_price END) al "
                "FROM trades WHERE date(entry_time)=?", (day,))
    r = cur.fetchone()
    if not r["n"]: continue
    print(f"    {day:<12}{r['n']:>4}{str(r['w'])+'/'+str(r['n']-r['w']):>8}{r['pnl']:>10.0f}"
          f"{r['pnl']/r['n']:>10.2f}{(r['aw'] or 0):>8.2f}{(r['al'] or 0):>8.2f}{(r['h'] or 0):>8.0f}")

print()
print("=" * 100)
print("(4) ATTRIBUTION — gate effect vs ranking effect")
print("    Which of the day's entries would the PRE-REPAIR confidence have blocked?")
print("=" * 100)
W = 105
cur.execute("SELECT id, entry_time, pnl, score, confidence FROM trades WHERE date(entry_time)=? "
            "ORDER BY id", (DAY,))
trades = cur.fetchall()
if not trades:
    print("    no trades on that day")
else:
    blocked, allowed = [], []
    for t in trades:
        cur.execute("SELECT score_breakdown, confidence_breakdown FROM signals "
                    "WHERE date(timestamp)=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1",
                    (DAY, t["entry_time"]))
        s = cur.fetchone()
        old_conf = None
        if s and s["score_breakdown"] and s["confidence_breakdown"]:
            try:
                sbd, cbd = json.loads(s["score_breakdown"]), json.loads(s["confidence_breakdown"])
                credit = (sbd.get("delta", 0) + sbd.get("greeks", 0) + sbd.get("oi", 0))
                mult = 1.0
                for k in ("regime_multiplier", "market_quality_multiplier",
                          "session_multiplier", "execution_multiplier"):
                    mult *= cbd.get(k, 1.0)
                old_conf = min(100, round((sbd["raw_score"] - credit) / W * 100 * mult))
            except Exception:
                pass
        (allowed if (old_conf is None or old_conf >= 70) else blocked).append((t, old_conf))
    print(f"    entries the pre-repair confidence would still have allowed: {len(allowed)}")
    print(f"    entries only possible BECAUSE of the repair:               {len(blocked)}")
    for grp, nm in ((allowed, "would have traded anyway"), (blocked, "new, repair-enabled")):
        if grp:
            p = [t["pnl"] for t, _ in grp]
            print(f"      {nm:<26} n={len(p):<3} pnl=Rs{sum(p):>8.0f}  E=Rs{st.mean(p):>8.2f}")
    print()
    print("    Reading: if the 'new' bucket is the losing one, the repair helped by ranking but")
    print("    hurt by opening the gates, and the gates need recalibrating rather than the repair")
    print("    reverting. If both buckets are similar, the repair changed volume, not quality.")
