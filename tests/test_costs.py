"""The cost model is the number every expectancy figure in this repo was missing."""
import pytest

from research.costs import DEFAULT, CostModel, breakeven_win_rate, net_pnl, summarise


def test_round_trip_matches_the_published_schedule():
    """One NIFTY lot at a Rs184 premium, bought and sold flat. Hand-computed from
    Zerodha's rates: Rs40 brokerage + Rs8.50 exchange + Rs17.94 STT + Rs0.36 stamp
    + Rs0.02 SEBI + Rs8.73 GST."""
    c = DEFAULT.round_trip(184.0, 184.0, 65)
    assert c == pytest.approx(75.56, abs=0.5)


def test_the_flat_brokerage_is_most_of_the_cost_at_one_lot():
    c = DEFAULT.round_trip(184.0, 184.0, 65)
    assert 40.0 / c > 0.5


def test_cost_in_points_falls_with_size_but_never_to_zero():
    one = DEFAULT.points(184.0, lots=1)
    eight = DEFAULT.points(184.0, lots=8)
    assert one == pytest.approx(1.162, abs=0.01)
    assert eight == pytest.approx(0.527, abs=0.01)
    assert eight < one
    assert eight > 0.4, "the variable charges survive any amount of scaling"


def test_stt_is_charged_on_the_sell_side_only():
    """A trade closed lower pays less STT than one closed higher."""
    up = DEFAULT.round_trip(100.0, 120.0, 65)
    down = DEFAULT.round_trip(100.0, 80.0, 65)
    assert up > down


def test_net_pnl_subtracts_the_cost():
    assert net_pnl(159.23, 184.0, 186.5, 65) < 159.23


def test_summarise_reports_gross_and_net_together():
    trades = [
        {"entry_price": 184.0, "exit_price": 186.5, "qty": 65, "pnl": 162.5},
        {"entry_price": 184.0, "exit_price": 181.5, "qty": 65, "pnl": -162.5},
    ]
    s = summarise(trades)
    assert s["n"] == 2
    assert s["gross_total"] == 0.0
    assert s["cost_total"] > 0
    assert s["net_total"] < 0
    assert s["gross_win_rate"] == 50.0
    # The Rs162.50 win still clears its own Rs76 round trip, so the win RATE is unchanged;
    # what the cost destroys is the total, because the loss grows by the same Rs76.
    assert s["net_win_rate"] == 50.0
    assert s["net_total"] == pytest.approx(-2 * s["mean_cost"], abs=1.0)


def test_summarise_skips_rows_it_cannot_price():
    assert summarise([{"entry_price": 0, "exit_price": 0, "qty": 65, "pnl": 10}])["n"] == 0


def test_breakeven_win_rate_moves_with_cost():
    """The recorded record: avg win Rs159.23, avg loss Rs162.01, cost Rs63.80."""
    gross = breakeven_win_rate(159.23, 162.01, 0.0)
    net = breakeven_win_rate(159.23, 162.01, 63.80)
    assert gross == pytest.approx(50.4, abs=0.2)
    assert net == pytest.approx(70.2, abs=0.5)
    assert net > gross


def test_a_different_broker_changes_the_answer():
    """Rates live in one place because they are a broker's, not a law of nature."""
    free = CostModel(brokerage_per_order=0.0)
    assert free.round_trip(184.0, 184.0, 65) < DEFAULT.round_trip(184.0, 184.0, 65)
