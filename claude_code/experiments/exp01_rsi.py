"""EXP-01 — Is the 1.65 profit floor doing the work, or does the option tick-RSI add
genuine reversal information?  Read-only replay; no production logic touched."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, compare

b = Book()
P = Policy

print("=" * 150)
print("EXP-01A  — does RSI add anything over a plain profit floor?")
print("=" * 150)
compare([
    P("CONTROL  floor 1.65 + tick-RSI reversal + RSI-OB exit"),
    P("A1  FLOOR-ONLY @1.65 (no RSI at all)", floor_only=True),
    P("A2  RSI exits DISABLED (loss rules + backstops only)",
      rsi_exit_enabled=False, reversal_enabled=False),
], book=b)

print()
print("=" * 150)
print("EXP-01B — floor level sweep (RSI kept on)")
print("=" * 150)
compare([P(f"B{i}  floor={f}", rev_min_profit=f) for i, f in
         enumerate([1.00, 1.35, 1.65, 2.00, 2.50, 3.00], 1)], book=b, per_day=False)

print()
print("=" * 150)
print("EXP-01C — floor-only, level sweep (isolates the floor from RSI entirely)")
print("=" * 150)
compare([P(f"C{i}  floor-only={f}", floor_only=True, rev_min_profit=f) for i, f in
         enumerate([1.00, 1.35, 1.65, 2.00, 2.50, 3.00, 4.00], 1)], book=b, per_day=False)

print()
print("=" * 150)
print("EXP-01D — reversal trigger threshold sweep (how deep must RSI fall back?)")
print("=" * 150)
compare([P(f"D{i}  rev_exit_ce={v}", rev_exit_ce=v, rev_exit_pe=100 - v) for i, v in
         enumerate([45, 50, 55, 60, 65, 70], 1)], book=b, per_day=False)

print()
print("=" * 150)
print("EXP-01E — reversal extreme sweep (how overbought must it have been?)")
print("=" * 150)
compare([P(f"E{i}  rev_extreme_ce={v}", rev_extreme_ce=v, rev_extreme_pe=100 - v) for i, v in
         enumerate([65, 70, 75, 80, 85], 1)], book=b, per_day=False)

print()
print("=" * 150)
print("EXP-01F — confirmation timing: consecutive ticks / delay after the floor is crossed")
print("=" * 150)
compare([P("F1  confirm 1 tick (control)"),
         P("F2  confirm 2 ticks", rev_confirm_ticks=2),
         P("F3  confirm 3 ticks", rev_confirm_ticks=3),
         P("F4  confirm 5 ticks", rev_confirm_ticks=5),
         P("F5  delay 5s after floor", rev_delay_sec=5),
         P("F6  delay 15s after floor", rev_delay_sec=15),
         P("F7  delay 30s after floor", rev_delay_sec=30),
         P("F8  floor-only + 15s delay", floor_only=True, rev_delay_sec=15),
         P("F9  floor-only + 30s delay", floor_only=True, rev_delay_sec=30),
         ], book=b, per_day=False)
