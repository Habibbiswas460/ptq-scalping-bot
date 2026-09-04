"""MARKET -> ENTRY -> POSITION -> EXIT -> REALISED: where the movement is lost.

Uncensored: available movement after entry is measured from the ticks regardless of when the
strategy actually exited, so it is NOT truncated by the exit the way the recorded mfe column is.
Spot is real. Option LTP is real. Bid/ask is never used here except for the recorded fill
prices, which carry the known synthetic half-spread — flagged wherever it matters.
"""
import sqlite3, datetime, statistics as st
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
DAYS = ("2026-09-03", "2026-09-04")
H = ((30, "30s"), (60, "1m"), (120, "2m"), (180, "3m"), (300, "5m"), (600, "10m"))
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; cur = con.cursor()
def P(s): return datetime.datetime.strptime(s.split('.')[0], "%Y-%m-%d %H:%M:%S")

_c = {}
def opt(sym, day):
    if (sym, day) not in _c:
        cur.execute("SELECT timestamp,ltp FROM ticks WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp", (sym, day))
        _c[(sym, day)] = [(P(r[0]), r[1]) for r in cur.fetchall()]
    return _c[(sym, day)]
def spot(day):
    if ("SPOT", day) not in _c:
        cur.execute("SELECT timestamp,spot_price FROM ticks WHERE date(timestamp)=? AND spot_price>0 ORDER BY timestamp", (day,))
        seen, out = set(), []
        for ts, p in cur.fetchall():
            d = P(ts)
            if d not in seen:
                seen.add(d); out.append((d, p))
        _c[("SPOT", day)] = out
    return _c[("SPOT", day)]

def win(series, a, b):
    return [p for d, p in series if a < d <= b]

rows = []
for day in DAYS:
    sp = spot(day)
    cur.execute("SELECT id,symbol,direction,entry_time,exit_time,entry_price,exit_price,pnl,"
                "exit_reason,hold_time_sec FROM trades WHERE date(entry_time)=? ORDER BY id", (day,))
    for t in [dict(r) for r in cur.fetchall()]:
        tk = opt(t["symbol"], day)
        e, x = P(t["entry_time"]), P(t["exit_time"])
        sgn = 1 if t["direction"] == "CE" else -1
        spot_at_e = next((p for d, p in reversed(sp) if d <= e), None)
        r = {"day": day, "id": t["id"], "dir": t["direction"], "e": t["entry_time"][11:19],
             "x": t["exit_time"][11:19], "hold": round(t["hold_time_sec"], 1),
             "entry": t["entry_price"], "exitp": t["exit_price"],
             "captured": round(t["exit_price"] - t["entry_price"], 2),
             "pnl": round(t["pnl"], 2), "win": t["pnl"] > 0,
             "reason": t["exit_reason"].split("|")[0].strip(), "spot_e": spot_at_e}
        for sec, lab in H:
            ow = win(tk, e, e + datetime.timedelta(seconds=sec))
            sw = win(sp, e, e + datetime.timedelta(seconds=sec))
            # option: favourable = premium up (we are always long the option)
            r[f"oMFE_{lab}"] = round(max(ow) - t["entry_price"], 2) if ow else None
            r[f"oMAE_{lab}"] = round(min(ow) - t["entry_price"], 2) if ow else None
            # spot: favourable in the trade's direction
            if sw and spot_at_e is not None:
                favs = [(p - spot_at_e) * sgn for p in sw]
                r[f"sMFE_{lab}"] = round(max(favs), 2)
                r[f"sMAE_{lab}"] = round(min(favs), 2)
            else:
                r[f"sMFE_{lab}"] = r[f"sMAE_{lab}"] = None
        rows.append(r)

def f(v, w=6):
    return f"{v:>{w}}" if v is not None else " " * (w - 3) + "n/a"

for day in DAYS:
    d = [r for r in rows if r["day"] == day]
    print("=" * 132)
    print(f"{day}  n={len(d)}   AVAILABLE movement after entry (uncensored) vs CAPTURED")
    print("=" * 132)
    print(f"{'id':>4}{'dir':>4}{'entry':>9}{'W/L':>4} {'reason':<14}{'capt':>6} |"
          f"{'oMFE30s':>8}{'1m':>7}{'2m':>7}{'3m':>7}{'5m':>7}{'10m':>7} |"
          f"{'sMFE1m':>8}{'sMFE3m':>8}{'sMFE10m':>9}{'sMAE3m':>8}")
    for r in d:
        print(f"{r['id']:>4}{r['dir']:>4}{r['e']:>9}{'W' if r['win'] else 'L':>4} {r['reason'][:14]:<14}"
              f"{r['captured']:>6.2f} |"
              f"{f(r['oMFE_30s'],8)}{f(r['oMFE_1m'],7)}{f(r['oMFE_2m'],7)}{f(r['oMFE_3m'],7)}"
              f"{f(r['oMFE_5m'],7)}{f(r['oMFE_10m'],7)} |"
              f"{f(r['sMFE_1m'],8)}{f(r['sMFE_3m'],8)}{f(r['sMFE_10m'],9)}{f(r['sMAE_3m'],8)}")
    print()

import json
json.dump(rows, open("/tmp/claude-1000/-home-lora-projects-PTQ-scalping-bot/8700f2e9-ced8-46f5-909f-b0ded013be02/scratchpad/capture.json", "w"), indent=1, default=str)
