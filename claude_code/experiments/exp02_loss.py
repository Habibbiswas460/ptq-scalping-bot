"""EXP-02 — can the system tell a temporary pullback from a genuine movement failure
BEFORE cutting?  Simple widening/removal already failed, so every variant here changes the
MECHANISM, not just the threshold."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from exit_lab import Policy, Book, compare
b = Book(); P = Policy

print("=" * 150)
print("EXP-02A — mechanism variants (all keep the production profit side, so the loss side is the only variable)")
print("=" * 150)
compare([
    P("CONTROL static 2.5/1.8"),
    P("M1 pullback-tolerant 30s", loss_mode="pullback", pullback_grace_sec=30),
    P("M2 pullback-tolerant 60s", loss_mode="pullback", pullback_grace_sec=60),
    P("M3 fresh-low required (3 ticks)", loss_mode="freshlow", require_new_low_ticks=3),
    P("M4 fresh-low required (8 ticks)", loss_mode="freshlow", require_new_low_ticks=8),
    P("M5 MFE-aware 2.0 / 4.0 @arm0.5", loss_mode="mfe_aware"),
    P("M6 MFE-aware 2.0 / 3.0 @arm0.5", loss_mode="mfe_aware", mfe_room_pts=3.0),
    P("M7 MFE-aware 1.5 / 4.0 @arm1.0", loss_mode="mfe_aware", mfe_tight_pts=1.5, mfe_arm_pts=1.0),
    P("M8 structure (below prev candle low)", loss_mode="structure"),
], book=b)

print()
print("=" * 150)
print("EXP-02B — the HONEST ATR: realised option range instead of the never-populated atr field")
print("=" * 150)
compare([
    P("CONTROL static 2.5"),
    P("N1 ATR60s x0.75", loss_mode="atr_adaptive", atr_window_sec=60, atr_mult=0.75),
    P("N2 ATR60s x1.00", loss_mode="atr_adaptive", atr_window_sec=60, atr_mult=1.00),
    P("N3 ATR60s x1.50", loss_mode="atr_adaptive", atr_window_sec=60, atr_mult=1.50),
    P("N4 ATR120s x0.75", loss_mode="atr_adaptive", atr_window_sec=120, atr_mult=0.75),
    P("N5 ATR120s x1.00", loss_mode="atr_adaptive", atr_window_sec=120, atr_mult=1.00),
    P("N6 ATR30s x1.00", loss_mode="atr_adaptive", atr_window_sec=30, atr_mult=1.00),
], book=b)
