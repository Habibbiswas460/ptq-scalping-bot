"""Exit-policy replay lab (experiment branch only — no production code imports this).

Replays the real recorded entry sequence tick-by-tick against parameterised exit policies
so that exit hypotheses can be measured before any production logic is touched.

Fidelity notes (read before trusting a number):
  * Ticks are the real persisted option-premium ticks. LTP is real; bid/ask is synthetic
    (ltp +/- 0.3%/2) — see the synthetic-bid/ask correction. Every fill here therefore uses
    the SAME synthetic half-spread production used, so replay P&L is comparable to recorded
    P&L, but the absolute spread cost inside it is fabricated in both.
  * The exit RSI is recomputed exactly as core/engines/state_machine.py::_calculate_rsi does:
    a simple (non-Wilder) RSI(14) over the last 15 raw option LTP ticks, re-evaluated every
    tick. It is NOT the 5-minute spot RSI.
  * Entries are held fixed. Only the exit policy varies. Nothing here says anything about
    entry quality.
  * n is tiny (24 trades / 2 sessions). Treat every result as hypothesis-generating.

Measured fidelity of the control policy against the 24 recorded exits (2026-09-04):
  22/24 reproduce the recorded exit reason and second exactly. The two divergences are both
  RSI-driven (#111 timing, #128 reason). Root cause: the live RSI buffer was fed every tick
  received (42,965 on 2026-09-04) while only 25,055 were persisted, so the replayed tick-RSI
  is computed over a ~1.7x longer wall-clock window and is smoother/slower than the live one.
  Loss-side rules (Early/Soft/hard SL) are time-and-price driven and reproduce exactly.
  => Loss-side conclusions are high-confidence. RSI-timing conclusions are directional only,
     and are most trustworthy when compared BETWEEN policies (all share the same decimation).
"""
from __future__ import annotations
import sqlite3, datetime, statistics
from dataclasses import dataclass, field, replace
from collections import Counter
from typing import Optional

DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
QTY = 65
DAYS = ("2026-09-03", "2026-09-04")


def _P(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")


def _half_spread(ltp: float) -> float:
    """The synthetic half-spread production actually filled at."""
    return max(0.05, ltp * 0.003) / 2.0


# ─────────────────────────── policy ───────────────────────────
@dataclass(frozen=True)
class Policy:
    name: str
    # backstops
    hard_sl: float = 7.0
    tp: float = 14.0
    max_hold: float = 900.0
    # loss side
    early_enabled: bool = True
    early_pts: float = 2.5
    early_sec: float = 45.0
    soft_enabled: bool = True
    soft_pts: float = 1.8
    soft_sec: float = 75.0
    # profit side — smart RSI exit (overbought/oversold)
    rsi_exit_enabled: bool = True
    rsi_ob: float = 80.0
    rsi_os: float = 20.0
    rsi_exit_min_profit: float = 2.0
    # profit side — RSI reversal
    reversal_enabled: bool = True
    rev_extreme_ce: float = 75.0
    rev_exit_ce: float = 60.0
    rev_extreme_pe: float = 25.0
    rev_exit_pe: float = 40.0
    rev_min_profit: float = 1.65
    # experimental profit-side variants
    floor_only: bool = False          # exit on the first tick profit >= rev_min_profit
    rev_confirm_ticks: int = 1        # consecutive ticks the reversal condition must hold
    rev_delay_sec: float = 0.0        # min seconds after the floor is first crossed
    # experimental loss-side variants
    pullback_grace_sec: float = 0.0   # suppress the loss cuts while price is recovering
    require_new_low_ticks: int = 0    # loss cut only if price is making fresh lows
    loss_mode: str = "static"         # static | pullback | freshlow | mfe_aware | atr_adaptive | structure
    atr_window_sec: float = 60.0      # realised-range window for the honest ATR
    atr_mult: float = 1.0             # early-cut threshold = atr_mult * realised range
    atr_floor: float = 1.5            # never tighter than this
    atr_cap: float = 6.0              # never wider than this
    mfe_arm_pts: float = 0.5          # mfe_aware: a trade that got this far earns more room
    mfe_room_pts: float = 4.0         # mfe_aware: the wider stop it then earns
    mfe_tight_pts: float = 2.0        # mfe_aware: stop for a trade that never went positive
    pullback_recover_pts: float = 0.05  # how far off the low counts as "recovering"


# ─────────────────────────── data ───────────────────────────
class Book:
    def __init__(self, db: str = DB):
        self.con = sqlite3.connect(db)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self._tk: dict = {}

    def trades(self, days=DAYS):
        out = []
        for d in days:
            self.cur.execute(
                "SELECT id,symbol,direction,entry_time,exit_time,entry_price,exit_price,"
                "pnl,exit_reason,hold_time_sec FROM trades WHERE date(entry_time)=? ORDER BY id", (d,))
            out += [(d, dict(r)) for r in self.cur.fetchall()]
        return out

    def ticks(self, symbol: str, day: str):
        k = (symbol, day)
        if k not in self._tk:
            self.cur.execute(
                "SELECT timestamp, ltp FROM ticks WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp",
                (symbol, day))
            self._tk[k] = [(_P(t), p) for t, p in self.cur.fetchall()]
        return self._tk[k]


def rsi14(window) -> Optional[float]:
    """Mirror of state_machine._calculate_rsi: simple mean of the last 14 gains/losses."""
    if len(window) < 15:
        return None
    g = l = 0.0
    for i in range(len(window) - 14, len(window)):
        c = window[i] - window[i - 1]
        if c > 0:
            g += c
        else:
            l += -c
    ag, al = g / 14.0, l / 14.0
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


# ─────────────────────────── engine ───────────────────────────
def simulate(book: Book, day: str, tr: dict, pol: Policy) -> dict:
    tk = book.ticks(tr["symbol"], day)
    entry_dt, entry_px, direction = _P(tr["entry_time"]), tr["entry_price"], tr["direction"]
    max_rsi, min_rsi = 0.0, 100.0
    floor_first_dt = None
    rev_streak = 0
    run_min, run_max = None, None
    new_low_streak = 0
    mfe = mae = 0.0

    def close(px, reason, held, i):
        fill = round(px - _half_spread(px), 2)
        return {"exit_ltp": px, "exit_fill": fill, "reason": reason, "hold": held,
                "pts": round(fill - entry_px, 2), "pnl": round((fill - entry_px) * QTY, 2),
                "mfe": round(mfe, 2), "mae": round(mae, 2), "idx": i}

    for i, (dt, px) in enumerate(tk):
        if dt <= entry_dt:
            continue
        held = (dt - entry_dt).total_seconds()
        diff = px - entry_px
        mfe = max(mfe, diff)
        mae = min(mae, diff)
        run_min = px if run_min is None else min(run_min, px)
        run_max = px if run_max is None else max(run_max, px)
        new_low_streak = new_low_streak + 1 if px <= run_min else 0

        # backstops always win
        if diff <= -pol.hard_sl:
            return close(px, "HARD_SL", held, i)
        if diff >= pol.tp:
            return close(px, "TP", held, i)

        # ── loss side ──
        early_pts = pol.early_pts
        allow_cut = True
        if pol.loss_mode == "pullback":
            # a position bouncing off its own low is a pullback, not a failure — hold it
            recovering = run_min is not None and px > run_min + pol.pullback_recover_pts
            allow_cut = not (recovering and held <= pol.pullback_grace_sec)
        elif pol.loss_mode == "freshlow":
            # only cut while the position is actively making new lows
            allow_cut = new_low_streak >= max(1, pol.require_new_low_ticks)
        elif pol.loss_mode == "mfe_aware":
            # a trade that never traded above entry is a different animal from one that did
            early_pts = pol.mfe_room_pts if mfe >= pol.mfe_arm_pts else pol.mfe_tight_pts
        elif pol.loss_mode == "atr_adaptive":
            # the honest version of the ATR branch: realised range of the option itself,
            # measured from the ticks the bot already has, over a trailing window
            w0 = dt - datetime.timedelta(seconds=pol.atr_window_sec)
            wnd = [q for d2, q in tk[max(0, i - 200):i + 1] if d2 >= w0]
            rng = (max(wnd) - min(wnd)) if len(wnd) >= 5 else None
            early_pts = min(pol.atr_cap, max(pol.atr_floor, pol.atr_mult * rng)) if rng else pol.early_pts
        elif pol.loss_mode == "structure":
            # cut only when the option's own 1-min structure has actually broken:
            # price below the previous completed candle's low
            m0 = dt.replace(second=0, microsecond=0) - datetime.timedelta(minutes=1)
            prev = [q for d2, q in tk[max(0, i - 200):i + 1]
                    if m0 <= d2 < m0 + datetime.timedelta(minutes=1)]
            allow_cut = (not prev) or px < min(prev)
        if allow_cut:
            if pol.early_enabled and held <= pol.early_sec and diff <= -early_pts:
                return close(px, "EARLY_CUT", held, i)
            if pol.soft_enabled and held >= pol.soft_sec and diff <= -pol.soft_pts:
                return close(px, "SOFT_LOSS", held, i)

        # ── profit side ──
        if diff >= pol.rev_min_profit and floor_first_dt is None:
            floor_first_dt = dt
        if pol.floor_only:
            if floor_first_dt is not None and (dt - floor_first_dt).total_seconds() >= pol.rev_delay_sec:
                return close(px, "FLOOR", held, i)
        else:
            r = rsi14([q for _, q in tk[max(0, i - 20):i + 1]])
            if r is not None:
                max_rsi = max(max_rsi, r)
                min_rsi = min(min_rsi, r)
                if pol.rsi_exit_enabled and diff >= pol.rsi_exit_min_profit:
                    if direction == "CE" and r > pol.rsi_ob:
                        return close(px, "RSI_EXIT", held, i)
                    if direction == "PE" and r < pol.rsi_os:
                        return close(px, "RSI_EXIT", held, i)
                if pol.reversal_enabled and diff >= pol.rev_min_profit:
                    hit = ((direction == "CE" and max_rsi > pol.rev_extreme_ce and r < pol.rev_exit_ce)
                           or (direction == "PE" and min_rsi < pol.rev_extreme_pe and r > pol.rev_exit_pe))
                    rev_streak = rev_streak + 1 if hit else 0
                    delay_ok = (floor_first_dt is None or
                                (dt - floor_first_dt).total_seconds() >= pol.rev_delay_sec)
                    if rev_streak >= pol.rev_confirm_ticks and delay_ok:
                        return close(px, "RSI_REVERSAL", held, i)

        if held >= pol.max_hold:
            return close(px, "TIME", held, i)
    last_dt, last_px = tk[-1]
    return close(last_px, "EOD", (last_dt - entry_dt).total_seconds(), len(tk) - 1)


def post_exit(book: Book, day: str, tr: dict, res: dict, minutes: int = 3):
    tk = book.ticks(tr["symbol"], day)
    x_dt = _P(tr["entry_time"]) + datetime.timedelta(seconds=res["hold"])
    w = [p for d, p in tk if x_dt < d <= x_dt + datetime.timedelta(minutes=minutes)]
    if not w:
        return None, None
    return round(max(w) - res["exit_ltp"], 2), round(min(w) - res["exit_ltp"], 2)


def run(book: Book, pol: Policy, days=DAYS):
    rows = []
    for day, tr in book.trades(days):
        r = simulate(book, day, tr, pol)
        cont, adv = post_exit(book, day, tr, r)
        r.update(day=day, id=tr["id"], dir=tr["direction"], cont3=cont, adv3=adv)
        rows.append(r)
    return rows


def metrics(rows):
    pnls = [r["pnl"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    aw = statistics.mean(wins) / QTY if wins else 0.0
    al = abs(statistics.mean(losses)) / QTY if losses else 0.0
    gp, gl = sum(wins), abs(sum(losses))
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    def avg(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(v) / len(v), 2) if v else None
    return {"n": len(rows), "wr": 100 * len(wins) / len(rows) if rows else 0,
            "avg_win": round(aw, 2), "avg_loss": round(-al, 2),
            "rr": round(aw / al, 2) if al else 0.0, "pnl": round(sum(pnls), 0),
            "exp": round(statistics.mean(pnls), 2) if pnls else 0.0,
            "pf": round(gp / gl, 2) if gl else 0.0, "mdd": round(mdd, 0),
            "hold": round(statistics.mean([r["hold"] for r in rows]), 0),
            "mfe": avg("mfe"), "mae": avg("mae"), "cont3": avg("cont3"), "adv3": avg("adv3"),
            "exits": dict(Counter(r["reason"] for r in rows))}


def line(label, m):
    return (f"  {label:<40} n={m['n']:<3} WR={m['wr']:>5.1f}% avgW={m['avg_win']:+.2f} avgL={m['avg_loss']:.2f} "
            f"R:R={m['rr']:.2f} E=Rs{m['exp']:>7.2f} PF={m['pf']:.2f} DD=Rs{m['mdd']:.0f} hold={m['hold']:.0f}s "
            f"MFE={m['mfe']} MAE={m['mae']} cont3={m['cont3']} adv3={m['adv3']}")


def compare(policies, days=DAYS, per_day=True, book=None):
    book = book or Book()
    base = book.trades(days)
    rec = [{"pnl": t["pnl"], "hold": t["hold_time_sec"], "reason": t["exit_reason"].split("|")[0].strip(),
            "mfe": None, "mae": None, "cont3": None, "adv3": None} for _, t in base]
    print(line("RECORDED (actual)", metrics(rec)))
    out = {}
    for pol in policies:
        rows = run(book, pol, days)
        m = metrics(rows)
        out[pol.name] = (m, rows)
        print(line(pol.name, m))
        print(f"      exits: {m['exits']}")
        if per_day and len(days) > 1:
            for d in days:
                dm = metrics([r for r in rows if r["day"] == d])
                print(f"      {d}: E=Rs{dm['exp']:>7.2f} PF={dm['pf']:.2f} WR={dm['wr']:.1f}% n={dm['n']}")
    return out
