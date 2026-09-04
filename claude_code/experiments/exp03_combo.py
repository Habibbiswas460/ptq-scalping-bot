"""EXP-03 — combine the two independently-supported directions:
   profit side : harvest at a floor near the median MFE instead of waiting for a tick-RSI turn
   loss side   : tighten for trades that never traded above entry, give room to ones that did
Then stress it: per-day, leave-one-out, and sensitivity to the unknown real spread."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, compare, run, metrics
b = Book(); P = Policy

BEST_LOSS = dict(loss_mode="mfe_aware", mfe_tight_pts=1.5, mfe_room_pts=4.0, mfe_arm_pts=1.0)

print("=" * 150); print("EXP-03A — combinations"); print("=" * 150)
cands = [
    P("CONTROL production"),
    P("X1 floor-only 1.00 (best profit side)", floor_only=True, rev_min_profit=1.00),
    P("X2 MFE-aware loss (best loss side)", **BEST_LOSS),
    P("X3 COMBO floor-only 1.00 + MFE-aware", floor_only=True, rev_min_profit=1.00, **BEST_LOSS),
    P("X4 COMBO floor-only 1.35 + MFE-aware", floor_only=True, rev_min_profit=1.35, **BEST_LOSS),
    P("X5 COMBO floor 1.00 + RSI + MFE-aware", rev_min_profit=1.00, **BEST_LOSS),
    P("X6 COMBO floor-only 1.00 + ATR60x0.75", floor_only=True, rev_min_profit=1.00,
      loss_mode="atr_adaptive", atr_window_sec=60, atr_mult=0.75),
]
compare(cands, book=b)

print()
print("=" * 150); print("EXP-03B — leave-one-out robustness of the combination"); print("=" * 150)
print(f"    {'policy':<40}{'full':>9}{'LOO min':>9}{'LOO max':>9}   separated from control?")
ctl_rows = run(b, cands[0]); ctl = metrics(ctl_rows)["exp"]
ctl_loo = [metrics(ctl_rows[:i] + ctl_rows[i+1:])["exp"] for i in range(len(ctl_rows))]
for p in cands:
    rows = run(b, p)
    loo = [metrics(rows[:i] + rows[i+1:])["exp"] for i in range(len(rows))]
    sep = "yes" if min(loo) > max(ctl_loo) else ("n/a (control)" if p is cands[0] else "NO — overlaps control")
    print(f"    {p.name:<40}{metrics(rows)['exp']:>9.2f}{min(loo):>9.2f}{max(loo):>9.2f}   {sep}")

print()
print("=" * 150)
print("EXP-03C — SPREAD SENSITIVITY: the whole result rests on a fabricated 0.3% spread.")
print("          Re-price every fill at wider assumed spreads to see where the edge dies.")
print("=" * 150)
import exit_lab
orig = exit_lab._half_spread
QTY = exit_lab.QTY
print(f"    {'assumed round-trip spread':<34}{'CONTROL E':>12}{'X3 COMBO E':>12}{'X1 floor-only E':>17}")
for pct in (0.30, 0.45, 0.60, 0.90, 1.20):
    exit_lab._half_spread = (lambda q: (lambda ltp: max(0.05, ltp * q / 100.0) / 2.0))(pct)
    extra = (pct - 0.30) / 100.0  # entry fill was recorded at the 0.3% ask; charge the difference
    def adj(pol):
        rows = run(b, pol)
        for r in rows:
            bump = extra * (r["exit_ltp"]) / 2.0
            r["pnl"] -= bump * QTY
        return metrics(rows)["exp"]
    print(f"    {pct:.2f}% ({pct/100*120:.2f} pts on a 120 premium){adj(cands[0]):>12.2f}"
          f"{adj(cands[3]):>12.2f}{adj(cands[1]):>17.2f}")
exit_lab._half_spread = orig
