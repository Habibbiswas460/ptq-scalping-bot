"""An hour is only called "best" when it made money.

The report ranked hours by P&L and labelled the top three "BEST HOURS" whichever way they
pointed. On the recorded book every hour lost money, so it presented three losses --
Rs-33, Rs-98, Rs-125 -- as the best hours of the day. It also printed "WORST HOURS" with
the worst one last, because that list was a tail slice of a descending sort.
"""
import pytest

from utils import analytics as A


def _hours(pnls):
    """{hour: stats} with the shape get_best_worst_hours() returns."""
    return {f"{h:02d}": {"trades": 3, "pnl": p, "wins": 1, "losses": 2,
                         "win_rate": 33.3, "avg_pnl": round(p / 3, 2)}
            for h, p in pnls.items()}


def _ranked(pnls):
    stats = _hours(pnls)
    ordered = sorted(stats.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
    profitable = [h for h in ordered if h[1]["pnl"] > 0]
    losing = [h for h in ordered if h[1]["pnl"] < 0]
    return {
        "hourly_stats": stats,
        "any_profitable": bool(profitable),
        "profitable_hours": profitable[:3],
        "losing_hours": list(reversed(losing))[:3],
        "best_hours": ordered[:3],
        "worst_hours": list(reversed(ordered))[:3],
    }


def test_a_losing_book_is_not_reported_as_having_best_hours(capsys, monkeypatch):
    monkeypatch.setattr(A, "get_best_worst_hours",
                        lambda days=30: _ranked({9: -98.15, 11: -439.40, 14: -33.15}))
    A.print_hourly_performance()
    out = capsys.readouterr().out
    assert "NO HOUR WAS PROFITABLE" in out
    assert "least costly first, not best" in out
    assert "PROFITABLE HOURS" not in out


def test_profitable_hours_are_named_when_they_exist(capsys, monkeypatch):
    monkeypatch.setattr(A, "get_best_worst_hours",
                        lambda days=30: _ranked({9: 120.0, 11: -50.0, 14: 30.0}))
    A.print_hourly_performance()
    out = capsys.readouterr().out
    assert "PROFITABLE HOURS" in out
    assert "NO HOUR WAS PROFITABLE" not in out
    # Only the ones that made money.
    assert "09:00" in out.split("LOSING HOURS")[0]
    assert "11:00" not in out.split("LOSING HOURS")[0]


def test_losing_hours_are_listed_worst_first(capsys, monkeypatch):
    monkeypatch.setattr(A, "get_best_worst_hours",
                        lambda days=30: _ranked({11: -439.40, 12: -535.60, 13: -659.10}))
    out = capsys.readouterr()  # clear
    A.print_hourly_performance()
    body = capsys.readouterr().out.split("LOSING HOURS")[1]
    order = [line.strip()[:5] for line in body.strip().splitlines() if ":00" in line]
    assert order == ["13:00", "12:00", "11:00"], order


def test_one_trade_is_not_reported_as_1_trades(capsys, monkeypatch):
    ranked = _ranked({15: -125.45})
    ranked["best_hours"][0][1]["trades"] = 1
    monkeypatch.setattr(A, "get_best_worst_hours", lambda days=30: ranked)
    A.print_hourly_performance()
    out = capsys.readouterr().out
    assert "1 trade," in out and "1 trades" not in out


def test_no_data_says_so(capsys, monkeypatch):
    monkeypatch.setattr(A, "get_best_worst_hours", lambda days=30: {"hourly_stats": {}})
    A.print_hourly_performance()
    assert "No hourly data available yet" in capsys.readouterr().out


def test_the_split_keeps_zero_out_of_both_lists():
    """A flat hour is neither profitable nor losing, and must not pad either list."""
    ranked = _ranked({9: 10.0, 10: 0.0, 11: -10.0})
    assert [h for h, _ in ranked["profitable_hours"]] == ["09"]
    assert [h for h, _ in ranked["losing_hours"]] == ["11"]


def test_get_best_worst_hours_splits_on_sign(monkeypatch):
    """The real function, driven through a stubbed trade loader."""
    trades = [
        {"entry_time": "2026-09-04 09:20:00", "pnl": 100.0},
        {"entry_time": "2026-09-04 11:05:00", "pnl": -250.0},
        {"entry_time": "2026-09-04 13:40:00", "pnl": -80.0},
    ]
    monkeypatch.setattr(A.TradeAnalytics, "load_trades",
                        lambda self, date=None: trades if date and date.endswith("-04") else [])
    monkeypatch.setattr(A.TradeAnalytics, "get_paired_trades", lambda self, t: t)

    data = A.get_best_worst_hours(days=30)
    if not data["hourly_stats"]:
        pytest.skip("the stubbed date did not fall inside the window")
    assert data["any_profitable"] is True
    assert [h for h, _ in data["profitable_hours"]] == ["09"]
    # Worst first.
    assert [h for h, _ in data["losing_hours"]][0] == "11"
