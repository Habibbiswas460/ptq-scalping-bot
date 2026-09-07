"""Replay the SHIPPING entry and exit code over imported 1-minute candles.

This module imports `strategies.smart_scalp_v3.smart_scalp_signal` and
`core.engines.exit_engine.check_exit_conditions` and drives them. It does not
re-implement either. If the ladder changes in `config/`, this replay changes with
it, which is the whole point: a number produced here is a statement about THIS
bot, not about a model of it.

WHAT IS REAL HERE AND WHAT IS NOT
=================================
REAL
    * Every spot and option price is an exchange 1-minute OHLC bar, cross-checked
      against an unrelated vendor at 100% identical closes on the sample tested.
    * The signal is the real scoring stack, including its confidence gate.
    * The exit is the real ladder: hard SL, step trailing, early loss cut, soft
      loss timeout, greeks kill, RSI exits, time exit — in the real priority order.

SPREAD IS CHARGED EXACTLY ONCE, AND IT IS CHARGED IN THE FILL
=============================================================
The live bot crosses the book on both legs — `core/trading/broker.py:1881` fills a
BUY at `tick['ask']`, and line 2141 exits it at `tick['bid']` — so its gross P&L
has already paid the full spread. `research/costs.py` covers only the statutory
and broker charges (brokerage, STT, exchange, SEBI, stamp, GST) and correctly
excludes spread.

This replay does the same thing: the entry fills at `bar + half_spread` and the
exit at `bar - half_spread`, so the spread is inside `Trade.gross_pnl`, and
`costs.round_trip()` is added ON TOP without overlapping it. A candle carries no
book, so had the fills been taken at the bar price instead, the spread would have
been paid nowhere and the result would be optimistic by roughly Rs23 a trade.

The width is MEASURED ON THIS PROJECT'S OWN TICK DATA, not assumed: 0.246% of
premium round trip, about Rs23.27 per 65-lot round trip. It is applied
proportionally to the premium rather than as a fixed point count, because a fixed
0.125 pts/side silently becomes a different percentage as the premium moves —
that earlier default was worth only ~Rs16.25 a round trip and was optimistic by
about a third.

STILL AN ASSUMPTION
    * That 0.246% held on the 13 sessions replayed here. It was measured on this
      project's recorded ticks, which are a different (later) period.
    * WHERE INSIDE A MINUTE THE HIGH AND LOW HAPPENED. A 1-minute bar says both
      occurred; it does not say in what order. See INTRABAR below.
    * WHERE INSIDE A MINUTE THE HIGH AND LOW HAPPENED. A 1-minute bar says both
      occurred; it does not say in what order. See INTRABAR below.

APPROXIMATED, AND IT MATTERS
    * SUB-MINUTE EXITS CANNOT BE RESOLVED AT 1-MINUTE GRANULARITY. The early loss
      cut fires within 45s of entry and the soft-loss timeout at 75s. On a
      1-minute grid there are at most a couple of decision points inside those
      windows. In the live record these two exits are among the most frequent, so
      a replay at this granularity systematically under-fires them and lets
      trades run further than they would have. This is the single largest
      fidelity gap in the option replay and no amount of care removes it — only
      tick data would.
    * The strategy consumed sub-second ticks live. Here it consumes one row per
      minute. The indicator inputs are fed as REAL 5-minute candles through
      `runtime_state.set_historical_candles`, which is the same path the live
      system prefers, so EMA/RSI/VWAP periods match live. The signal EVALUATION
      RATE does not: 375 evaluations a session instead of tens of thousands.

INTRABAR ORDERING
=================
Each 1-minute bar is presented to the exit engine as four points:

    open -> low -> high -> close        (for a long position: adverse first)

Adverse-first LOOKS like the conservative choice — a stop triggers before the
favourable extreme can arm the trailing ladder. Measured, it is the opposite, and
the naming in `Config.optimistic_intrabar` reflects the intent rather than the
outcome:

    low before low->high (this default)   net -Rs8,563.57 over 58 trades
    high before low ("optimistic")        net -Rs10,644.02 over 60 trades

Stopping out early is WORTH something to this ladder, because the alternative is
arming a trailing stop that then gives the move back. So the default here is the
flattering assumption, not the cautious one, and the true result is at least as
bad as the headline. The Rs2,080 between the two orderings is the size of an
assumption that 1-minute bars cannot resolve — roughly Rs35 a trade, against a
net expectancy of -Rs148.

The four points are stamped at +0s, +20s, +40s and +59s inside the minute so that
the engine's time-based branches engage at roughly the right moment. Those
offsets are invented; the data cannot say when the extremes fell.

A half-spread of exactly 0 is NOT a valid configuration and does not give a
"perfect fills" upper bound: `market_quality_engine._spread_pct` requires
`ask > bid` and returns 99.0 otherwise, so a zero spread hard-rejects every
evaluation and the replay produces no trades at all.

LOOK-AHEAD
==========
A signal is computed from bars up to and including the close of minute t. The
entry fills at the OPEN of minute t+1. No bar at or after the fill contributes to
the decision to take it. The strike is chosen from the spot at t, not from t+1.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research import costs as _costs               # noqa: E402
from research.backtest import store                # noqa: E402

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
ANGEL = "angelone_smartapi"

# Round-trip bid/ask spread as a percentage of premium, measured on this
# project's own recorded option ticks (98,434 ticks): 0.246%, about Rs23.27 per
# 65-lot round trip. Half of it is crossed on each leg.
DEFAULT_SPREAD_PCT = 0.246

# Sub-minute offsets for the four intrabar evaluation points. Invented; see the
# module docstring.
INTRABAR_OFFSETS = (0, 20, 40, 59)


@dataclass
class Config:
    lot_size: int = 65
    lots: int = 1
    spread_pct: float = DEFAULT_SPREAD_PCT   # round-trip, % of premium
    half_spread: Optional[float] = None      # fixed pts/side; overrides spread_pct
    optimistic_intrabar: bool = False      # high before low instead of low before high
    strike_step: float = 50.0              # from the instrument master, not assumed 100
    warmup_bars: int = 60                  # bars fed before the first signal is trusted
    max_trades_per_session: int = 0        # 0 = unlimited; the live limiter is separate
    enrich_greeks: bool = True             # mirror core/main.py's TICK_DELTA_ENABLED path
    cost_model: _costs.CostModel = field(default_factory=lambda: _costs.DEFAULT

                                        )

    @property
    def qty(self) -> int:
        return self.lot_size * self.lots

    def half_spread_at(self, premium: float) -> float:
        """Points crossed on ONE leg at this premium.

        Proportional by default because the spread is a percentage of premium,
        not a constant number of points; `half_spread` pins it to a fixed figure
        for sensitivity runs.
        """
        if self.half_spread is not None:
            return self.half_spread
        return max(premium, 0.0) * (self.spread_pct / 100.0) / 2.0


@dataclass
class Trade:
    session_date: str
    direction: str
    symbol: str
    strike: float
    entry_time: _dt.datetime
    entry_price: float          # already includes the buy-side half spread
    entry_mid: float            # the raw bar price, before slippage
    exit_time: Optional[_dt.datetime] = None
    exit_price: float = 0.0     # already includes the sell-side half spread
    exit_mid: float = 0.0
    exit_reason: str = ""
    qty: int = 65
    confidence: int = 0
    score: Optional[int] = None
    hold_sec: float = 0.0
    mfe_pts: float = 0.0
    mae_pts: float = 0.0

    @property
    def gross_pnl(self) -> float:
        """Points captured x quantity, INCLUDING the modelled spread crossing.

        Named `gross` in this project's sense: before brokerage/STT/GST/stamp.
        The spread is inside it because it is a fill price, not a charge.
        """
        return (self.exit_price - self.entry_price) * self.qty

    def costs(self, model: _costs.CostModel) -> float:
        return model.round_trip(self.entry_price, self.exit_price, self.qty)

    def net_pnl(self, model: _costs.CostModel) -> float:
        return self.gross_pnl - self.costs(model)

    @property
    def spread_paid(self) -> float:
        """Rupees given up to the book, already inside gross_pnl.

        Reported separately so a reader can see it was charged, and charged once.
        """
        return ((self.entry_price - self.entry_mid) +
                (self.exit_mid - self.exit_price)) * self.qty


# ── data shaping ─────────────────────────────────────────────────────────────

def _bar_ts(bar: Dict) -> _dt.datetime:
    return _dt.datetime.fromisoformat(bar["ts_ist"])


def load_session(con, index_key: str, session_date: str,
                 source: str = ANGEL) -> List[Dict]:
    return store.load_candles(con, index_key, source, "1m", session_date=session_date)


def option_series(con, session_date: str, expiry: str, source: str = ANGEL) -> Dict[Tuple[float, str], Dict[int, Dict]]:
    """{(strike, CE|PE): {epoch: bar}} for one session.

    Minutes absent from a contract are absent here too. For an option that means
    "no trade printed in this minute", which is real information; it is not a
    hole to be filled and the harness treats it as the contract being untradeable
    at that instant.
    """
    out: Dict[Tuple[float, str], Dict[int, Dict]] = {}
    q = """SELECT c.*, i.strike, i.kind FROM candles c
           JOIN instruments i ON i.instrument_key = c.instrument_key
           WHERE c.source=? AND c.interval='1m' AND c.session_date=?
             AND i.kind IN ('CE','PE') AND i.expiry=?"""
    for r in con.execute(q, (source, session_date, expiry)):
        out.setdefault((r["strike"], r["kind"]), {})[r["epoch"]] = dict(r)
    return out


def _atm(spot: float, step: float) -> float:
    return step * round(spot / step)


# ── the replay ───────────────────────────────────────────────────────────────

class Replay:
    """One session, one expiry, the real engines."""

    def __init__(self, cfg: Config = None):
        self.cfg = cfg or Config()
        self.trades: List[Trade] = []
        self.rejections: Dict[str, int] = {}
        self.signals = 0
        self.evaluations = 0
        self.entries_blocked_no_contract = 0

    # -- engine access, imported not reimplemented -------------------------
    @staticmethod
    def _engines():
        from strategies.smart_scalp_v3 import smart_scalp_signal, get_strategy
        from core.engines import exit_engine
        from core.runtime.state import runtime_state
        return smart_scalp_signal, get_strategy, exit_engine, runtime_state

    @staticmethod
    def _enrich_greeks(tick: Dict, spot: float, strike: float,
                       expiry_dt: _dt.datetime) -> None:
        """Write delta/gamma/theta/vega onto the tick, exactly as live does.

        core/main.py does this every loop when TICK_DELTA_ENABLED is set (it is,
        in the current config). WITHOUT IT THE REPLAY IS NOT THE LIVE SYSTEM:
        `adaptive_confidence_engine` reads delta as
        `indicators.get('Delta', 0) or latest_tick.get('delta', 0)`, and an
        unpopulated delta lands in the `else 10` branch of

            greeks_score = 100 if 0.35 <= abs_delta <= 0.65 else 50 if ... else 10

        which carries 0.20 of the confidence total — an 18-point penalty against a
        69% gate. Measured: with delta absent, the best confidence reached across
        a full session was 63%, so the stack could never arm. That is a property
        of the replay, not of the strategy, and correcting it is required for the
        comparison to mean anything.

        The values are RECONSTRUCTED (Black-Scholes from the premium), which is the
        same provenance they carry live — see research/provenance.py on `delta`.
        The one improvement over live: the real contract expiry is passed, where
        live falls back to a resolver.
        """
        try:
            from core.risk.greeks_calc import calculate_greeks
            g = calculate_greeks(tick, spot, int(strike), expiry_dt)
        except Exception:  # noqa: BLE001 - a solver failure leaves the tick as it was
            return
        if not g:
            return
        tick["delta"] = g.get("delta", 0.0)
        tick["gamma"] = g.get("gamma", 0.0)
        tick["theta"] = g.get("theta", 0.0)
        tick["vega"] = g.get("vega", 0.0)
        tick["greeks_source"] = g.get("source", "BSM")

    def _reset_strategy_state(self, runtime_state, get_strategy):
        """A fresh strategy and a fresh tick buffer per session.

        Without this the previous session's ticks leak into the next one's
        indicators across the overnight gap, which would be a look-ahead-shaped
        contamination running backwards: yesterday's close shaping today's EMA
        as though it were a continuous series.
        """
        runtime_state.clear_ticks()
        runtime_state.set_historical_candles([])
        import strategies.smart_scalp_v3 as ss
        ss._strategy_instance = None
        get_strategy()

    def run_session(self, con, index_key: str, session_date: str, expiry: str,
                    source: str = ANGEL) -> List[Trade]:
        smart_scalp_signal, get_strategy, exit_engine, runtime_state = self._engines()
        cfg = self.cfg
        spot_bars = load_session(con, index_key, session_date, source)
        if len(spot_bars) < cfg.warmup_bars + 2:
            return []
        chain = option_series(con, session_date, expiry, source)
        if not chain:
            return []
        # Real expiry, 15:30 IST on the expiry date. Live falls back to a resolver;
        # here the contract's own expiry is known, so it is used.
        expiry_dt = _dt.datetime.combine(
            _dt.date.fromisoformat(expiry), _dt.time(15, 30))

        self._reset_strategy_state(runtime_state, get_strategy)
        session_trades: List[Trade] = []
        open_trade: Optional[Trade] = None
        trade_state: Optional[Dict] = None
        open_series: Optional[Dict[int, Dict]] = None

        ticks: List[Dict] = []
        for i, sbar in enumerate(spot_bars):
            ts = _bar_ts(sbar)
            spot = sbar["close"]
            atm = _atm(spot, cfg.strike_step)

            # The tick handed to the strategy carries the ATM CALL premium as
            # `ltp` — the same shape the live feed has, where `ltp` is whatever
            # contract is currently subscribed and `spot_price` is the index.
            ref = chain.get((atm, "CE"), {}).get(sbar["epoch"])
            tick = {
                "ltp": ref["close"] if ref else 0.0,
                "spot_price": spot,
                "volume": ref["volume"] if ref else 0,
                "timestamp": ts.isoformat(),
                "original_timestamp": ts.isoformat(),
                # BID/ASK ARE MODELLED, NOT MEASURED. No historical book exists
                # from any source reached. They cannot simply be omitted: the
                # market-quality engine reads a missing book as a 99% spread and
                # hard-rejects every evaluation (measured: 3,503 of 3,900 on the
                # first run of this replay), so leaving them out does not mean
                # "unknown", it means "always reject".
                #
                # ltp +- half_spread is used instead, and it is worth being clear
                # that this is no worse than live: every bid/ask this project has
                # ever persisted before 2026-09-07 was itself fabricated as
                # ltp+-0.3%. The live system has been running on a modelled book
                # for its entire recorded history. This one is narrower and is
                # labelled ESTIMATED rather than presented as a reading.
                "bid": round(ref["close"] - cfg.half_spread_at(ref["close"]), 2) if ref else 0.0,
                "ask": round(ref["close"] + cfg.half_spread_at(ref["close"]), 2) if ref else 0.0,
                # oi is MISSING from getCandleData at every interval. Omitted
                # rather than zero-filled: a 0 would be read as a reading.
            }
            if cfg.enrich_greeks and ref:
                # option_type matters: PE deltas are negative and the confidence
                # engine takes abs(), but the weighted score engine does not.
                tick["option_type"] = "CE"
                self._enrich_greeks(tick, spot, atm, expiry_dt)
            ticks.append(tick)
            runtime_state.add_tick(tick, max_ticks=400)

            # Feed REAL 5-minute candles so calculate_indicators takes the same
            # canonical path the live system prefers, rather than its tick-chunking
            # fallback. Only bars up to and including `i` are ever visible.
            if i >= cfg.warmup_bars:
                runtime_state.set_historical_candles(
                    store.aggregate(spot_bars[: i + 1], 5))

            # ---- manage an open position ----------------------------------
            if open_trade is not None:
                closed = self._step_exit(exit_engine, open_trade, trade_state,
                                         open_series, sbar, ts, expiry_dt)
                if closed:
                    session_trades.append(open_trade)
                    open_trade, trade_state, open_series = None, None, None

            # ---- look for an entry ----------------------------------------
            if open_trade is not None or i < cfg.warmup_bars or i + 1 >= len(spot_bars):
                continue
            if cfg.max_trades_per_session and len(session_trades) >= cfg.max_trades_per_session:
                continue

            self.evaluations += 1
            try:
                fired, message, params = smart_scalp_signal(
                    runtime_state.get_recent_ticks(max_items=240))
            except Exception as e:  # noqa: BLE001 - a strategy raise is a finding, not a crash
                self.rejections[f"strategy raised {type(e).__name__}"] = \
                    self.rejections.get(f"strategy raised {type(e).__name__}", 0) + 1
                continue
            if not fired:
                key = (message or "unknown").split("|")[0].strip()[:60]
                self.rejections[key] = self.rejections.get(key, 0) + 1
                continue

            self.signals += 1
            direction = params.get("direction") or "CE"
            # Entry fills on the NEXT bar's open. Strike from the spot at signal
            # time, which is what the live system knows when it decides.
            nxt = spot_bars[i + 1]
            series = chain.get((atm, direction))
            entry_bar = series.get(nxt["epoch"]) if series else None
            if not entry_bar:
                self.entries_blocked_no_contract += 1
                continue

            entry_mid = entry_bar["open"]
            open_trade = Trade(
                session_date=session_date, direction=direction,
                symbol=entry_bar["symbol"], strike=atm,
                entry_time=_bar_ts(nxt),
                entry_price=entry_mid + cfg.half_spread_at(entry_mid),
                entry_mid=entry_mid, qty=cfg.qty,
                confidence=int(params.get("confidence") or 0),
                score=params.get("score"),
            )
            trade_state = {
                "entry_price": open_trade.entry_price, "qty": cfg.qty,
                "direction": direction, "side": "BUY",
                "entry_time": open_trade.entry_time,
                "max_profit_points": 0.0,
                # `highest_sl` is deliberately ABSENT, not None: the engine reads it
                # as trade.get('highest_sl', -HARD_SL_POINTS), so a present-but-None
                # key defeats the default and crashes the ladder comparison. Live
                # never sets it at open either.
                "mfe_inr": 0.0, "mae_inr": 0.0,
            }
            open_series = series

        # Anything still open at the last bar is closed on that bar's close, which
        # is what the live force-close does at 15:25. Recorded with its own reason
        # so it is never counted as a strategy exit.
        if open_trade is not None:
            last = spot_bars[-1]
            bar = open_series.get(last["epoch"]) if open_series else None
            px = bar["close"] if bar else open_trade.entry_mid
            self._close(open_trade, px, _bar_ts(last), "SESSION END (forced)")
            session_trades.append(open_trade)

        self.trades.extend(session_trades)
        return session_trades

    # -- exit stepping ------------------------------------------------------
    def _intrabar_points(self, bar: Dict) -> List[Tuple[int, float]]:
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        seq = [o, h, l, c] if self.cfg.optimistic_intrabar else [o, l, h, c]
        return list(zip(INTRABAR_OFFSETS, seq))

    def _step_exit(self, exit_engine, trade: Trade, state: Dict,
                   series: Dict[int, Dict], sbar: Dict, ts: _dt.datetime,
                   expiry_dt: _dt.datetime) -> bool:
        bar = series.get(sbar["epoch"]) if series else None
        if not bar:
            # The contract did not print this minute. The live system would hold;
            # there is nothing to mark against, so the position simply carries.
            return False
        for offset, price in self._intrabar_points(bar):
            at = ts + _dt.timedelta(seconds=offset)
            # The engine's time branches read _now(); replaying against the real
            # wall clock would make every hold-time nonsensical. This override is
            # the hook the exit engine already provides for exactly this.
            exit_engine._clock_override = at
            tick = {"ltp": price, "spot_price": sbar["close"],
                    "option_type": trade.direction,
                    "timestamp": at.isoformat(), "original_timestamp": at.isoformat()}
            # The exit ladder's Priority-3 branch reads greeks['theta_sec'],
            # ['delta'] and ['gamma'] unguarded, so an empty dict is not "no
            # greeks", it is a KeyError. Live, core/main.py computes these every
            # loop and hands them to check_exit_conditions; the same solver is
            # used here, with the contract's real expiry. RECONSTRUCTED, as live.
            greeks = {}
            if self.cfg.enrich_greeks:
                try:
                    from core.risk.greeks_calc import calculate_greeks
                    greeks = calculate_greeks(tick, sbar["close"],
                                              int(trade.strike), expiry_dt) or {}
                except Exception:  # noqa: BLE001
                    greeks = {}
            try:
                hit, reason = exit_engine.check_exit_conditions(
                    state, tick, greeks, "NORMAL", None, None)
            finally:
                exit_engine._clock_override = None
            diff = price - trade.entry_price
            trade.mfe_pts = max(trade.mfe_pts, diff)
            trade.mae_pts = min(trade.mae_pts, diff)
            if hit:
                self._close(trade, price, at, reason)
                return True
        return False

    def _close(self, trade: Trade, mid: float, at: _dt.datetime, reason: str) -> None:
        trade.exit_mid = mid
        trade.exit_price = max(mid - self.cfg.half_spread_at(mid), 0.05)
        trade.exit_time = at
        trade.exit_reason = reason
        trade.hold_sec = (at - trade.entry_time).total_seconds()


# ── summarising ──────────────────────────────────────────────────────────────

def summarise(trades: Sequence[Trade], model: _costs.CostModel = _costs.DEFAULT) -> Dict:
    """Gross and net, side by side and never apart.

    This project has established that every P&L figure it ever published was
    gross. A net number presented alone invites the reader to assume the old ones
    were too, so both are always reported together.
    """
    if not trades:
        return {"n": 0}
    gross = [t.gross_pnl for t in trades]
    cost = [t.costs(model) for t in trades]
    net = [g - c for g, c in zip(gross, cost)]
    wins_g = [g for g in gross if g > 0]
    wins_n = [v for v in net if v > 0]
    losses_g = [-g for g in gross if g <= 0]
    avg_win = sum(wins_g) / len(wins_g) if wins_g else 0.0
    avg_loss = sum(losses_g) / len(losses_g) if losses_g else 0.0
    unit = trades[0].qty
    return {
        "n": len(trades),
        "gross_total": round(sum(gross), 2),
        "cost_total": round(sum(cost), 2),
        "net_total": round(sum(net), 2),
        "gross_expectancy": round(sum(gross) / len(gross), 2),
        "net_expectancy": round(sum(net) / len(net), 2),
        "gross_win_rate": round(100.0 * len(wins_g) / len(gross), 1),
        "net_win_rate": round(100.0 * len(wins_n) / len(net), 1),
        "mean_cost": round(sum(cost) / len(cost), 2),
        "cost_points_per_lot": round((sum(cost) / len(cost)) / unit, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "breakeven_win_rate_gross": _costs.breakeven_win_rate(avg_win, avg_loss, 0.0),
        "breakeven_win_rate_net": _costs.breakeven_win_rate(
            avg_win, avg_loss, sum(cost) / len(cost)),
        "spread_total": round(sum(t.spread_paid for t in trades), 2),
        "mean_spread": round(sum(t.spread_paid for t in trades) / len(trades), 2),
        "mean_hold_sec": round(sum(t.hold_sec for t in trades) / len(trades), 1),
        "mean_mfe_pts": round(sum(t.mfe_pts for t in trades) / len(trades), 3),
        "mean_mae_pts": round(sum(t.mae_pts for t in trades) / len(trades), 3),
        "sessions": len({t.session_date for t in trades}),
    }


def exit_breakdown(trades: Sequence[Trade]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for t in trades:
        # The reason strings carry live formatting; the leading token identifies
        # the branch and is what we group on.
        key = t.exit_reason.split("|")[0].strip() or "UNKNOWN"
        b = out.setdefault(key, {"n": 0, "gross": 0.0})
        b["n"] += 1
        b["gross"] += t.gross_pnl
    for b in out.values():
        b["gross"] = round(b["gross"], 2)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["n"]))
