"""What a trade actually costs, which nothing in this project has ever counted.

Every P&L figure in the repository — the trades table, the exit-ladder experiments, the
opportunity universe, `after_session` — is GROSS. The bot computes
`(exit - entry) x qty` and stops there. There is no brokerage, STT, exchange transaction
charge, GST or stamp duty anywhere in the codebase, and no backtest artifact behind the
strategy docstring's "Monthly Return: +42.2%".

Applied to the 143 trades recorded up to 2026-09-07 that is not a rounding correction:

    gross   -Rs1,644.50   (46.9% winners)
    costs   -Rs9,123.02   (mean Rs63.80 per trade)
    net    -Rs10,767.52   (33.6% winners)

Cost is 40% of the average winning trade, and 0.982 option points on a single lot at
that mean of Rs63.80 — against a 60-second mean favourable excursion of 1.06 points.
(This line previously read 1.162 points, which is `points()` at a premium of Rs183.83,
not the figure that pairs with a Rs63.80 mean. Rs63.80 / 65 = 0.982.) So the comparisons every
experiment in this repo rests on are all roughly Rs64/trade too optimistic, in the same
direction, which is enough to move several of them across zero.

RATES are Zerodha's published equity-options intraday schedule, read on 2026-09-07
(https://zerodha.com/charges/). They are a discount broker's rates and the STT figure
reflects the Budget 2026 rise to 0.15%; a different broker or a later budget changes the
arithmetic, so the numbers live in one dict rather than being spread through the code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class CostModel:
    """Indian equity-options intraday costs, buy-then-sell within the session."""

    brokerage_per_order: float = 20.0     # flat, per executed order
    stt_sell_pct: float = 0.0015          # 0.15% of sell premium value, sell side only
    exchange_txn_pct: float = 0.0003553   # 0.03553% of premium value, both sides
    sebi_pct: float = 0.000001            # Rs10 per crore, both sides
    stamp_buy_pct: float = 0.00003        # 0.003% of buy value, buy side only
    gst_pct: float = 0.18                 # on brokerage + exchange + SEBI only

    def round_trip(self, entry: float, exit_: float, qty: int) -> float:
        """Total cost in rupees of buying `qty` at `entry` and selling at `exit_`."""
        if qty <= 0 or entry <= 0 or exit_ <= 0:
            return 0.0
        buy_value, sell_value = entry * qty, exit_ * qty
        brokerage = self.brokerage_per_order * 2
        exchange = self.exchange_txn_pct * (buy_value + sell_value)
        sebi = self.sebi_pct * (buy_value + sell_value)
        stt = self.stt_sell_pct * sell_value
        stamp = self.stamp_buy_pct * buy_value
        gst = self.gst_pct * (brokerage + exchange + sebi)
        return brokerage + exchange + sebi + stt + stamp + gst

    def points(self, premium: float, lots: int = 1, lot_size: int = 65) -> float:
        """Round-trip cost expressed in option points per lot — the unit the exit ladder
        is written in, so it can be compared with a stop or a target directly.

        The flat brokerage does not scale, so this falls with size: at a premium of
        Rs183.83, 1.162 points at one lot and 0.527 at eight. Both numbers move with
        premium — at Rs145.55 they are 1.071 and 0.436 — so quote the premium with
        them. It never reaches zero, and at this account's Rs30,000 (NIFTY margin
        ~Rs15,000/lot) only one or two lots are reachable at all.
        """
        if lots <= 0 or lot_size <= 0 or premium <= 0:
            return 0.0
        qty = lots * lot_size
        return self.round_trip(premium, premium, qty) / lots / lot_size


DEFAULT = CostModel()


def net_pnl(gross_pnl: float, entry: float, exit_: float, qty: int,
            model: CostModel = DEFAULT) -> float:
    return gross_pnl - model.round_trip(entry, exit_, qty)


def summarise(trades: Iterable[Dict], model: CostModel = DEFAULT) -> Dict:
    """Gross vs net over rows carrying entry_price, exit_price, qty and pnl.

    Reported together on purpose: a net figure alone invites the assumption that the
    published numbers were already net, and they never were.
    """
    import statistics as st

    gross, cost = [], []
    for t in trades:
        e, x = float(t.get("entry_price") or 0), float(t.get("exit_price") or 0)
        q = int(t.get("qty") or 0) or 65
        p = t.get("pnl")
        if p is None or e <= 0 or x <= 0:
            continue
        gross.append(float(p))
        cost.append(model.round_trip(e, x, q))
    n = len(gross)
    if not n:
        return {"n": 0}
    net = [g - c for g, c in zip(gross, cost)]
    wins_g = [g for g in gross if g > 0]
    wins_n = [v for v in net if v > 0]
    return {
        "n": n,
        "gross_total": round(sum(gross), 2),
        "cost_total": round(sum(cost), 2),
        "net_total": round(sum(net), 2),
        "gross_expectancy": round(sum(gross) / n, 2),
        "net_expectancy": round(sum(net) / n, 2),
        "gross_win_rate": round(100.0 * len(wins_g) / n, 1),
        "net_win_rate": round(100.0 * len(wins_n) / n, 1),
        "mean_cost": round(st.mean(cost), 2),
        "cost_share_of_avg_win": (round(100.0 * st.mean(cost) / st.mean(wins_g), 1)
                                  if wins_g else None),
    }


def breakeven_win_rate(avg_win: float, avg_loss: float, cost: float = 0.0) -> Optional[float]:
    """Win rate needed for zero expectancy. `avg_loss` positive, all in the same unit.

    On the recorded record (avg win Rs159.23, avg loss Rs162.01) this is 50.4% gross and
    55.9% once the Rs63.80 cost is included, against 46.9% actually achieved.
    """
    denom = avg_win + avg_loss
    if denom <= 0:
        return None
    return 100.0 * (avg_loss + cost) / denom
