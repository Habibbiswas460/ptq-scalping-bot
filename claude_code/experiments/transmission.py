"""Does the option premium transmit the underlying's movement?  (Hypothesis E)

First a DATA-QUALITY gate: the spot_price column is written on option tick rows, so it must
be checked for staleness before any delta conclusion. Then realised delta is measured by
regressing option changes on spot changes over several horizons.
"""
import sqlite3, datetime, statistics as st
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
con = sqlite3.connect(DB); cur = con.cursor()
def P(s): return datetime.datetime.strptime(s.split('.')[0], "%Y-%m-%d %H:%M:%S")

for day, sym in (("2026-09-03", "NIFTY08SEP2623950CE"),
                 ("2026-09-04", "NIFTY08SEP2623950CE"),
                 ("2026-09-04", "NIFTY08SEP2623850CE")):
    cur.execute("SELECT timestamp, ltp, spot_price FROM ticks WHERE symbol=? AND date(timestamp)=? "
                "AND spot_price>0 ORDER BY timestamp, id", (sym, day))
    raw = [(P(a), b, c) for a, b, c in cur.fetchall()]
    if len(raw) < 100:
        continue
    # de-duplicate to one row per second (second-resolution collisions)
    ser, seen = [], set()
    for d, o, s in raw:
        if d not in seen:
            seen.add(d); ser.append((d, o, s))
    print("=" * 100)
    print(f"{day}  {sym}   {len(ser)} distinct-second rows  {ser[0][0].strftime('%H:%M')}-{ser[-1][0].strftime('%H:%M')}")
    print("=" * 100)

    # ---- data-quality gate ----
    sp_unchanged = sum(1 for i in range(1, len(ser)) if ser[i][2] == ser[i-1][2])
    op_unchanged = sum(1 for i in range(1, len(ser)) if ser[i][1] == ser[i-1][1])
    runs, cur_run, mx = [], 1, 1
    for i in range(1, len(ser)):
        if ser[i][2] == ser[i-1][2]:
            cur_run += 1
        else:
            runs.append(cur_run); mx = max(mx, cur_run); cur_run = 1
    print(f"  DATA QUALITY: spot unchanged tick-to-tick {100*sp_unchanged/(len(ser)-1):.1f}% "
          f"(option {100*op_unchanged/(len(ser)-1):.1f}%);  longest spot-frozen run "
          f"{mx}s, median run {st.median(runs) if runs else 0:.0f}s")

    # ---- realised delta by regression through the origin, several horizons ----
    print(f"  {'horizon':>8}{'n':>7}{'realised delta':>16}{'R^2':>8}{'|d_spot| median':>17}{'|d_opt| median':>16}")
    for sec in (10, 30, 60, 180, 300):
        xs, ys = [], []
        j = 0
        for i in range(len(ser)):
            while j < len(ser) and (ser[j][0] - ser[i][0]).total_seconds() < sec:
                j += 1
            if j >= len(ser):
                break
            dx = ser[j][2] - ser[i][2]
            dy = ser[j][1] - ser[i][1]
            if dx != 0:
                xs.append(dx); ys.append(dy)
        if len(xs) < 30:
            continue
        beta = sum(x*y for x, y in zip(xs, ys)) / sum(x*x for x in xs)
        ss_res = sum((y - beta*x)**2 for x, y in zip(xs, ys))
        ss_tot = sum(y*y for y in ys)
        r2 = 1 - ss_res/ss_tot if ss_tot else 0
        print(f"  {str(sec)+'s':>8}{len(xs):>7}{beta:>16.3f}{r2:>8.3f}"
              f"{st.median([abs(x) for x in xs]):>17.2f}{st.median([abs(y) for y in ys]):>16.2f}")
    print()
