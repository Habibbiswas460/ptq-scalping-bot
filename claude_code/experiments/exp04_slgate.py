"""EXP-04 — the 3-consecutive-loss confidence lock: does it protect capital or throw away
opportunity?  Counterfactual replay of the signals it actually blocked on 2026-09-04.

Method: from 11:11:54 (the third consecutive loss) to 15:30, walk the recorded signal rows.
Whenever a signal would have passed the RELAXED gate, is out of cooldown, and the subscribed
contract's premium is inside the production entry band, open a trade at that tick's synthetic
ask and run the SAME exit ladder the replay lab uses. Reality (gate ON) took zero trades.

Honest limits: the entry premium band and cooldowns are modelled, but the strike-rotation,
chop filter, session gates and drift guard are NOT re-run — so this is an UPPER BOUND on how
many trades the relaxed gate would have taken, not a prediction.
"""
import sys, os, datetime, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, simulate, metrics, _P, _half_spread

DAY = "2026-09-04"
LOCK_START = "11:11:54"
COOLDOWN_NORMAL, COOLDOWN_AFTER_SL, COOLDOWN_AFTER_PROFIT = 120, 120, 30
MIN_PREM, MAX_PREM = 70.0, 350.0

b = Book()
con = sqlite3.connect("/home/lora/projects/PTQ-scalping bot/core/data/trades.db")
cur = con.cursor()
cur.execute("SELECT timestamp, direction, score, confidence FROM signals "
            "WHERE date(timestamp)=? AND time(timestamp)>? AND direction IS NOT NULL "
            "AND direction<>'' ORDER BY timestamp", (DAY, LOCK_START))
signals = [(_P(t), d, s, c) for t, d, s, c in cur.fetchall()]
print(f"signal rows in the lock window: {len(signals)}  "
      f"({signals[0][0].strftime('%H:%M:%S')} - {signals[-1][0].strftime('%H:%M:%S')})")

# which contract was subscribed at each moment
SYMS = ["NIFTY08SEP2623950CE", "NIFTY08SEP2623900CE", "NIFTY08SEP2623850CE"]
series = {s: b.ticks(s, DAY) for s in SYMS}

def quote_at(dt):
    best = None
    for s, tk in series.items():
        for d, p in reversed(tk):
            if d <= dt:
                if (dt - d).total_seconds() <= 3:
                    if best is None or d > best[0]:
                        best = (d, s, p)
                break
    return best  # (tick_dt, symbol, ltp) or None

POL = Policy("exit ladder = production control")

def counterfactual(min_conf, label):
    last_exit = None
    trades = []
    for dt, direction, score, conf in signals:
        if conf < min_conf:
            continue
        if last_exit and (dt - last_exit[0]).total_seconds() < last_exit[1]:
            continue
        q = quote_at(dt)
        if not q:
            continue
        _, sym, ltp = q
        if not (MIN_PREM <= ltp <= MAX_PREM):
            continue
        entry_px = round(ltp + _half_spread(ltp), 2)
        tr = {"symbol": sym, "direction": direction, "entry_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
              "entry_price": entry_px}
        r = simulate(b, DAY, tr, POL)
        r.update(day=DAY, id=len(trades) + 1, dir=direction, cont3=None, adv3=None,
                 t=dt.strftime("%H:%M:%S"), sym=sym[-9:])
        trades.append(r)
        cd = COOLDOWN_AFTER_PROFIT if r["pnl"] > 0 else COOLDOWN_AFTER_SL
        last_exit = (dt + datetime.timedelta(seconds=r["hold"]), cd)
    if not trades:
        print(f"  {label:<34} no qualifying entries")
        return None
    m = metrics(trades)
    print(f"  {label:<34} n={m['n']:<3} WR={m['wr']:>5.1f}% avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} "
          f"total=Rs{m['pnl']:>8.0f} E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} DD=Rs{m['mdd']:.0f}")
    print(f"      exits: {m['exits']}")
    return trades

print()
print("=" * 120)
print("EXP-04A — what the lock cost (or saved) on 2026-09-04, 11:11:54 -> 15:30")
print("=" * 120)
print(f"  {'GATE ON (what actually happened)':<34} n=0   no trades taken, Rs0 added to the day's -Rs654.55")
res = {}
for mc, lab in [(85, "gate ON, threshold 85 (reality)"),
                (82, "gate OFF-equivalent (>=82)"),
                (80, "threshold lowered to 80"),
                (70, "gate fully removed (>=70 base)")]:
    res[mc] = counterfactual(mc, lab)

print()
print("=" * 120)
print("EXP-04B — per-trade detail of the >=82 counterfactual (the signals actually blocked)")
print("=" * 120)
if res.get(82):
    print(f"  {'#':>3} {'time':>9} {'sym':>10} {'dir':>4} {'entry':>8} {'exit':>8} {'pts':>6} {'hold':>7} {'reason':<14}")
    for r in res[82]:
        print(f"  {r['id']:>3} {r['t']:>9} {r['sym']:>10} {r['dir']:>4} {r['exit_ltp']:>8} "
              f"{r['exit_fill']:>8} {r['pts']:>6} {r['hold']:>7.0f} {r['reason']:<14}")


# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 120)
print("EXP-04C — NEAR OUT-OF-SAMPLE CHECK")
print("  The 51 blocked signals were never used to fit any exit policy, so they are a fresh")
print("  entry set (same two sessions' ticks, so not fully independent — call it near-OOS).")
print("=" * 120)

def rerun(pol, min_conf=82):
    last_exit, trades = None, []
    for dt, direction, score, conf in signals:
        if conf < min_conf:
            continue
        if last_exit and (dt - last_exit[0]).total_seconds() < last_exit[1]:
            continue
        q = quote_at(dt)
        if not q:
            continue
        _, sym, ltp = q
        if not (MIN_PREM <= ltp <= MAX_PREM):
            continue
        entry_px = round(ltp + _half_spread(ltp), 2)
        r = simulate(b, DAY, {"symbol": sym, "direction": direction,
                              "entry_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                              "entry_price": entry_px}, pol)
        r.update(day=DAY, cont3=None, adv3=None)
        trades.append(r)
        last_exit = (dt + datetime.timedelta(seconds=r["hold"]),
                     COOLDOWN_AFTER_PROFIT if r["pnl"] > 0 else COOLDOWN_AFTER_SL)
    return trades

BEST_LOSS = dict(loss_mode="atr_adaptive", atr_window_sec=60, atr_mult=0.75)
for pol in [Policy("CONTROL production ladder"),
            Policy("X1 floor-only 1.00", floor_only=True, rev_min_profit=1.00),
            Policy("X6 floor-only 1.00 + ATR60x0.75", floor_only=True, rev_min_profit=1.00, **BEST_LOSS),
            Policy("X3 floor-only 1.00 + MFE-aware", floor_only=True, rev_min_profit=1.00,
                   loss_mode="mfe_aware", mfe_tight_pts=1.5, mfe_room_pts=4.0, mfe_arm_pts=1.0)]:
    t = rerun(pol)
    m = metrics(t)
    print(f"  {pol.name:<36} n={m['n']:<3} WR={m['wr']:>5.1f}% avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} "
          f"total=Rs{m['pnl']:>8.0f} E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} DD=Rs{m['mdd']:.0f}")
