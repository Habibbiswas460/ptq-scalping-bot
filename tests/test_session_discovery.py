"""A handful of rows is not a trading session.

Book.sessions() classified a day as "tick" if it held a single tick row. On 2026-09-06 an
accidental 38-second paper run wrote exactly one, and every consumer that asks for "the
latest tick session" — the visual record tests, research.session, after_session, the visual
audit — picked a day with no evaluations and no trades.
"""
import sqlite3

import pytest

from research.db import MIN_SERIES, Book


def _store(tmp_path, ticks=0, signals=0, trades=0, day="2026-09-06"):
    """A trade store shaped like the real one, with the row counts asked for."""
    path = tmp_path / "trades.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE ticks (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT,
                            ltp REAL, bid REAL, ask REAL, volume INTEGER,
                            spot_price REAL, oi INTEGER);
        CREATE TABLE dvf_signals (id INTEGER PRIMARY KEY, timestamp TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY, entry_time TEXT, exit_time TEXT,
                             pnl REAL, qty INTEGER, exit_reason TEXT);
    """)
    for i in range(ticks):
        con.execute("INSERT INTO ticks (timestamp, symbol, ltp, spot_price) VALUES (?,?,?,?)",
                    (f"{day} 09:{20 + i // 60:02d}:{i % 60:02d}", "NIFTY08SEP2623800CE", 100.0, 23900.0))
    for i in range(signals):
        con.execute("INSERT INTO dvf_signals (timestamp) VALUES (?)",
                    (f"{day} 09:{20 + i // 60:02d}:{i % 60:02d}",))
    for i in range(trades):
        con.execute("INSERT INTO trades (entry_time, pnl, qty) VALUES (?,?,?)",
                    (f"{day} 10:{i:02d}:00", 10.0, 65))
    con.commit()
    con.close()
    return Book(str(path))


def test_one_stray_tick_is_not_a_tick_session(tmp_path):
    """The exact shape of the accident: one tick, nothing else."""
    assert _store(tmp_path, ticks=1).sessions() == []


@pytest.mark.parametrize("n", [1, 2, MIN_SERIES - 1])
def test_a_few_ticks_do_not_make_a_series(tmp_path_factory, n):
    book = _store(tmp_path_factory.mktemp(f"t{n}"), ticks=n, trades=1)
    assert book.sessions()[0]["kind"] == "trades-only"


def test_enough_ticks_is_a_tick_session(tmp_path):
    book = _store(tmp_path, ticks=MIN_SERIES, signals=5)
    session = book.sessions()[0]
    assert session["kind"] == "tick"
    assert session["n_ticks"] == MIN_SERIES


def test_evaluations_alone_are_a_coarse_session(tmp_path):
    assert _store(tmp_path, signals=MIN_SERIES).sessions()[0]["kind"] == "coarse"


def test_a_few_evaluations_do_not_make_a_coarse_session(tmp_path):
    book = _store(tmp_path, signals=MIN_SERIES - 1, trades=2)
    assert book.sessions()[0]["kind"] == "trades-only"


def test_trades_alone_are_still_a_session(tmp_path):
    """A day the bot traded is a session even with no series recorded — those days are
    most of the book and must not be dropped by the threshold."""
    session = _store(tmp_path, trades=3).sessions()[0]
    assert session["kind"] == "trades-only"
    assert session["n_trades"] == 3


def test_a_day_with_nothing_usable_and_nothing_traded_is_dropped(tmp_path):
    assert _store(tmp_path, ticks=2, signals=3).sessions() == []


def test_the_real_book_reports_only_sessions_that_hold_something():
    """Against the live store: every session discovered must carry a series or a trade."""
    try:
        sessions = Book().sessions()
    except sqlite3.Error:
        pytest.skip("no trade store")
    assert sessions, "the live book should discover sessions"
    for s in sessions:
        assert s["n_trades"] or s["n_ticks"] >= MIN_SERIES or s["n_signals"] >= MIN_SERIES, s
    for s in sessions:
        if s["kind"] == "tick":
            assert s["n_ticks"] >= MIN_SERIES, s
