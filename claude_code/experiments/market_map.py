"""Day-by-day market movement map from persisted spot ticks (2026-09-02/03/04).

Read-only. Spot is real (LTP-derived); bid/ask is NOT used anywhere here, so nothing in this
file is contaminated by the synthetic-spread issue.
"""
import sqlite3, datetime, statistics as st
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
DAYS = ("2026-09-02", "2026-09-03", "2026-09-04")
con = sqlite3.connect(DB); cur = con.cursor()
def P(s): return datetime.datetime.strptime(s.split('.')[0], "%Y-%m-%d %H:%M:%S")

def spot(day):
    cur.execute("SELECT timestamp, spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 "
                "ORDER BY timestamp", (day,))
    seen, out = set(), []
    for ts, p in cur.fetchall():
        d = P(ts)
        if d in seen:      # second-resolution collisions: keep the first print per second
            continue
        seen.add(d); out.append((d, p))
    return out

def max_move_in(series, seconds):
    """Largest up and down move inside any rolling window of `seconds` (two-pointer)."""
    best_up = best_dn = 0.0; up_at = dn_at = None
    j = 0
    lo_i = hi_i = 0
    from collections import deque
    mins, maxs = deque(), deque()   # monotonic deques of indices
    for i, (d, p) in enumerate(series):
        while mins and series[mins[-1]][1] >= p: mins.pop()
        mins.append(i)
        while maxs and series[maxs[-1]][1] <= p: maxs.pop()
        maxs.append(i)
        while (d - series[j][0]).total_seconds() > seconds:
            j += 1
            if mins[0] < j: mins.popleft()
            if maxs[0] < j: maxs.popleft()
        up = p - series[mins[0]][1]
        dn = series[maxs[0]][1] - p
        if up > best_up: best_up, up_at = up, (series[mins[0]][0], d)
        if dn > best_dn: best_dn, dn_at = dn, (series[maxs[0]][0], d)
    return round(best_up, 2), up_at, round(best_dn, 2), dn_at

def legs(series, threshold):
    """Zigzag swing legs. A leg pivot->extreme is emitted once price retraces `threshold`
    from that extreme and the leg itself is at least `threshold` long."""
    out = []
    if len(series) < 2:
        return out
    pivot = series[0]
    hi = lo = series[0]
    for d, p in series[1:]:
        if p > hi[1]:
            hi = (d, p)
        if p < lo[1]:
            lo = (d, p)
        # a down-retrace from the running high confirms a completed UP leg
        if hi[1] - p >= threshold and hi[1] - pivot[1] >= threshold and hi[0] > pivot[0]:
            out.append((pivot[0], hi[0], round(hi[1] - pivot[1], 2)))
            pivot = hi
            hi = lo = (d, p)
            continue
        # an up-retrace from the running low confirms a completed DOWN leg
        if p - lo[1] >= threshold and pivot[1] - lo[1] >= threshold and lo[0] > pivot[0]:
            out.append((pivot[0], lo[0], round(lo[1] - pivot[1], 2)))
            pivot = lo
            hi = lo = (d, p)
    return out


BUCKETS = [("09:15-10:00", "09:15", "10:00"), ("10:00-11:00", "10:00", "11:00"),
           ("11:00-12:00", "11:00", "12:00"), ("12:00-13:00", "12:00", "13:00"),
           ("13:00-14:00", "13:00", "14:00"), ("14:00-15:30", "14:00", "15:30")]

for day in DAYS:
    s = spot(day)
    hi = max(s, key=lambda x: x[1]); lo = min(s, key=lambda x: x[1])
    cur.execute("SELECT count(*), min(time(entry_time)), max(time(exit_time)) FROM trades WHERE date(entry_time)=?", (day,))
    ntr, t0, t1 = cur.fetchone()
    print("=" * 108)
    print(f"{day}   spot ticks={len(s)}  {s[0][0].strftime('%H:%M')}-{s[-1][0].strftime('%H:%M')}"
          f"   trades={ntr}" + (f"  active {t0}-{t1}" if ntr else "  (no trades)"))
    print("=" * 108)
    print(f"  session open={s[0][1]:.2f}  close={s[-1][1]:.2f}  net={s[-1][1]-s[0][1]:+.2f}")
    print(f"  session HIGH={hi[1]:.2f} @{hi[0].strftime('%H:%M:%S')}   LOW={lo[1]:.2f} @{lo[0].strftime('%H:%M:%S')}"
          f"   RANGE={hi[1]-lo[1]:.2f} pts")
    print(f"  {'window':>8}  {'max UP':>8}  when                   {'max DOWN':>9}  when")
    for w, lab in ((30, "30s"), (60, "60s"), (120, "2m"), (180, "3m"), (300, "5m"), (600, "10m")):
        u, ua, d, da = max_move_in(s, w)
        print(f"  {lab:>8}  {u:>8.2f}  {ua[0].strftime('%H:%M:%S')}->{ua[1].strftime('%H:%M:%S')}"
              f"   {d:>9.2f}  {da[0].strftime('%H:%M:%S')}->{da[1].strftime('%H:%M:%S')}")
    print(f"  hourly map (spot):")
    for lab, a, b in BUCKETS:
        seg = [(d, p) for d, p in s if a <= d.strftime("%H:%M") < b]
        if not seg: continue
        h = max(p for _, p in seg); l = min(p for _, p in seg)
        net = seg[-1][1] - seg[0][1]
        cur.execute("SELECT count(*), round(sum(pnl),0) FROM trades WHERE date(entry_time)=? "
                    "AND time(entry_time)>=? AND time(entry_time)<?", (day, a + ":00", b + ":00"))
        n, pnl = cur.fetchone()
        print(f"    {lab:<12} range={h-l:>7.2f}  net={net:>+8.2f}  |  trades={n or 0:>2}  pnl=Rs{pnl or 0:>7.0f}")
    lg = legs(s, 15.0)
    lg_sorted = sorted(lg, key=lambda x: -abs(x[2]))[:8]
    print(f"  major directional legs (>=12 spot pts, retrace-terminated): {len(lg)} total, largest:")
    for a, bnd, mv in lg_sorted:
        dur = (bnd - a).total_seconds() / 60
        cur.execute("SELECT count(*) FROM trades WHERE date(entry_time)=? AND entry_time>=? AND entry_time<=?",
                    (day, a.strftime("%Y-%m-%d %H:%M:%S"), bnd.strftime("%Y-%m-%d %H:%M:%S")))
        inleg = cur.fetchone()[0]
        print(f"    {a.strftime('%H:%M:%S')} -> {bnd.strftime('%H:%M:%S')}  {mv:>+8.2f} pts over {dur:>5.1f} min"
              f"   ({'UP  ' if mv > 0 else 'DOWN'})   strategy entries inside: {inleg}")
    print()
