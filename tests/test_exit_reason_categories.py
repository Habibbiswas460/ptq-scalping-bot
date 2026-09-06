"""Exit reasons must be grouped by the exit that happened, not by words in the sentence.

An exit reason is a sentence: the engine stamps a label on it, then appends the numbers
and an explanation. The categoriser searched the whole sentence for loose substrings, so
it read the commentary as the type. On the 131 trades recorded it filed 62% as "Other",
put 37 Early Loss Cuts under Stop Loss, and reported trades with no recorded exit as clean
market closes.
"""
import pytest

from utils.analytics import TradeAnalytics


@pytest.fixture
def categorise():
    analytics = TradeAnalytics.__new__(TradeAnalytics)
    return analytics._categorize_exit_reason


# Verbatim from core/data/trades.db.
@pytest.mark.parametrize("reason, expected", [
    ("🔄 RSI REVERSAL EXIT | PE | RSI 7→55 | Lock: ₹107", "RSI Reversal"),
    ("📊 RSI EXIT | CE | RSI=85 (OB>80) | Lock profit: ₹162", "RSI Exit"),
    ("⚡ EARLY LOSS CUT | PE | -3.2pts in 18s (ATR-thresh:3) | Loss: ₹211 (saved 2.8pts vs SL)",
     "Early Loss Cut"),
    ("⏳ SOFT LOSS EXIT | PE | -4.1pts | Loss: ₹266", "Soft Loss"),
    ("🎯 TAKE PROFIT | CE | +13.8pts @ ₹141.32 | Profit: ₹894", "Take Profit"),
    ("🛑 HARD SL HIT | PE | -6pts @ ₹178.45 | Loss: ₹390", "Hard Stop Loss"),
    ("✅ TRAILING PROFIT | CE | +9pts | Locked: ₹585", "Trailing Profit"),
    ("⏰ MARKET CLOSE EXIT | P&L: ₹79", "Market Close"),
    ("⏰ TIME EXIT (stale) | Held 240s", "Time Exit"),
    ("Kill switch: Wide spread KILL", "Kill Switch"),
    ("ORPHANED (no exit recorded — closed by cleanup)", "No Exit Recorded"),
])
def test_every_exit_the_engine_writes_is_recognised(categorise, reason, expected):
    assert categorise(reason) == expected


def test_commentary_after_the_label_does_not_decide_the_category(categorise):
    """"(saved 2.8pts vs SL)" is the reason explaining itself, not a stop loss.

    37 of 131 trades were filed as Stop Loss on that phrase alone, which made the report
    show 39 stop-loss exits where only 2 hard stops actually fired.
    """
    reason = ("⚡ EARLY LOSS CUT | CE | -3.0pts in 12s (ATR-thresh:3) | "
              "Loss: ₹195 (saved 3.0pts vs SL)")
    assert categorise(reason) == "Early Loss Cut"
    assert categorise(reason) != "Stop Loss"


def test_a_trade_with_no_exit_is_not_reported_as_a_clean_one(categorise):
    """"closed by cleanup" used to match 'close' and become Market Close."""
    assert categorise("ORPHANED (no exit recorded — closed by cleanup)") == "No Exit Recorded"


def test_the_longer_label_wins(categorise):
    """"RSI REVERSAL EXIT" contains no "RSI EXIT", but order still has to be deliberate:
    a future label that nests inside another must not be swallowed."""
    assert categorise("🔄 RSI REVERSAL EXIT | CE | RSI 6→100 | Lock: ₹101") == "RSI Reversal"
    assert categorise("📊 RSI EXIT | PE | RSI=81 | Lock profit: ₹256") == "RSI Exit"


def test_an_unknown_exit_is_other_not_a_guess(categorise):
    # "Other" should now mean the engine grew an exit nobody told this table about.
    assert categorise("🆕 SOMETHING THE ENGINE LEARNED LATER | CE") == "Other"
    assert categorise("") == "Other"
    assert categorise(None) == "Other"


def test_categories_cover_the_labels_the_engine_emits():
    """Pin the table against the engine, so a new exit reason shows up as a failure here
    rather than as a quiet slice of "Other" in the report."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    source = (root / "core" / "engines" / "exit_engine.py").read_text(encoding="utf-8")
    emitted = set(re.findall(
        r"(RSI REVERSAL EXIT|RSI EXIT|MARKET CLOSE EXIT|TIME EXIT|SOFT LOSS EXIT|"
        r"TRAILING PROFIT|TAKE PROFIT|HARD SL HIT|EARLY LOSS CUT)", source))
    known = {label for label, _ in TradeAnalytics.EXIT_CATEGORIES}
    assert emitted, "no exit labels found in exit_engine.py — has the format changed?"
    assert emitted <= known, f"exit_engine writes labels analytics cannot group: {emitted - known}"


def test_the_recorded_trades_all_land_somewhere(categorise):
    """The whole point: on the real book, nothing should fall into Other any more."""
    import sqlite3

    try:
        con = sqlite3.connect("file:core/data/trades.db?mode=ro", uri=True)
        rows = [r for (r,) in con.execute(
            "SELECT exit_reason FROM trades WHERE exit_reason IS NOT NULL")]
    except sqlite3.Error:
        pytest.skip("no trade store")
    if not rows:
        pytest.skip("no closed trades recorded")
    unknown = sorted({r for r in rows if categorise(r) == "Other"})
    assert unknown == [], f"{len(unknown)} exit reason(s) still ungrouped: {unknown[:3]}"
