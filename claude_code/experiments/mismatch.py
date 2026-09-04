"""Time-scale mismatch: how long the market's legs last vs how long the strategy holds,
and how much of the available option movement each trade actually captured."""
import sys, os, sqlite3, datetime, statistics as st, json
sys.path.insert(0, os.path.dirname(__file__))
from market_map import legs, spot          # reuse the validated zigzag + spot loader
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
con = sqlite3.connect(DB); cur = con.cursor()
def P(s): return datetime.datetime.strptime(s.split('.')[0], "%Y-%m-%d %H:%M:%S")

print("=" * 112)
print("(1) LEG DURATION vs HOLDING TIME — can a 1-2 minute hold capture the market's legs?")
print("=" * 112)
for day in ("2026-09-02", "2026-09-03", "2026-09-04"):
    s = spot(day)
    for thr in (15.0, 25.0):
        lg = legs(s, thr)
        if not lg:
            continue
        durs = [(b - a).total_seconds() / 60 for a, b, _ in lg]
        mvs = [abs(m) for _, _, m in lg]
        print(f"  {day} legs>={thr:>4.0f}pts: n={len(lg):>3}  median duration={st.median(durs):>6.1f} min  "
              f"median size={st.median(mvs):>6.1f} pts  legs under 3 min: "
              f"{sum(1 for d in durs if d <= 3)}/{len(lg)}")
    cur.execute("SELECT count(*), avg(hold_time_sec), max(hold_time_sec) FROM trades WHERE date(entry_time)=?", (day,))
    n, avg_h, max_h = cur.fetchone()
    if n:
        print(f"  {day} strategy: n={n}  avg hold={avg_h:.0f}s ({avg_h/60:.1f} min)  max hold={max_h:.0f}s")
    print()

print("=" * 112)
print("(2) WAS THE STRATEGY ON THE RIGHT SIDE OF THE LEG IT ENTERED INTO?")
print("    (leg membership uses the leg the entry falls inside; direction is as-of the leg's")
print("     eventual outcome, so this is a HINDSIGHT label — it measures alignment, not skill)")
print("=" * 112)
align = {"aligned": 0, "against": 0, "no leg": 0}
detail = []
for day in ("2026-09-03", "2026-09-04"):
    s = spot(day)
    lg = legs(s, 15.0)
    cur.execute("SELECT id,direction,entry_time,exit_price-entry_price,pnl FROM trades "
                "WHERE date(entry_time)=? ORDER BY id", (day,))
    for tid, dr, et, pts, pnl in cur.fetchall():
        e = P(et)
        host = next(((a, b, m) for a, b, m in lg if a <= e <= b), None)
        if host is None:
            align["no leg"] += 1
            detail.append((day, tid, dr, et[11:19], None, None, pts, pnl))
            continue
        a, b, m = host
        ok = (dr == "CE" and m > 0) or (dr == "PE" and m < 0)
        align["aligned" if ok else "against"] += 1
        detail.append((day, tid, dr, et[11:19], round(m, 1), (b - a).total_seconds() / 60, pts, pnl))
print(f"  aligned with the containing leg: {align['aligned']}   against it: {align['against']}   "
      f"no >=15pt leg active: {align['no leg']}   (n={sum(align.values())})")
print(f"  {'day':<12}{'id':>4}{'dir':>4}{'entry':>10}{'leg move':>10}{'leg min':>9}{'capt pts':>10}  side")
for day, tid, dr, et, m, dur, pts, pnl in detail:
    if m is None:
        print(f"  {day:<12}{tid:>4}{dr:>4}{et:>10}{'-':>10}{'-':>9}{pts:>10.2f}  no leg")
    else:
        ok = (dr == "CE" and m > 0) or (dr == "PE" and m < 0)
        print(f"  {day:<12}{tid:>4}{dr:>4}{et:>10}{m:>10.1f}{dur:>9.1f}{pts:>10.2f}  "
              f"{'ALIGNED' if ok else 'AGAINST'}")

print()
print("=" * 112)
print("(3) CAPTURE RATIO — realised / available option movement (uncensored)")
print("=" * 112)
rows = json.load(open("/tmp/claude-1000/-home-lora-projects-PTQ-scalping-bot/8700f2e9-ced8-46f5-909f-b0ded013be02/scratchpad/capture.json"))
for lab in ("3m", "5m", "10m"):
    for grp, sel in (("winners", True), ("losers", False)):
        g = [r for r in rows if r["win"] is sel and r.get(f"oMFE_{lab}") is not None]
        avail = [max(r[f"oMFE_{lab}"], 0) for r in g]
        capt = [r["captured"] for r in g]
        pos_avail = [a for a in avail if a > 0]
        ratio = sum(c for c in capt if c > 0) / sum(pos_avail) if pos_avail else 0
        print(f"  horizon {lab:<4} {grp:<8} n={len(g):<3} avg available={st.mean(avail):>5.2f} pts  "
              f"avg captured={st.mean(capt):>6.2f} pts  capture ratio(positive part)={100*ratio:>5.1f}%")
    print()
