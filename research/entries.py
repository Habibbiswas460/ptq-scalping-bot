"""Entry forensics: strictly causal pre-entry features, uncensored post-entry excursions.

The split matters more than any single number. Everything under `before` is computed from
`as_of(t)` and cannot see past the entry second. Everything under `after` is deliberately
uncensored — measured over fixed horizons regardless of when the exit fired — because using
exit-truncated MFE to judge an exit guarantees the answer.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _st
from typing import Dict, List, Optional, Sequence, Tuple

from research.candles import as_of
from research.candles import build as bars_of
from research.db import Book, parse_ts
from research.opportunities import HORIZONS, excursions


def causal_features(spot: Sequence, opt: Sequence, t: _dt.datetime) -> Dict:
    """As-of-entry only. Nothing here may consult a tick later than `t`."""
    out: Dict = {}
    for sec, lab in ((10, "10s"), (30, "30s"), (60, "1m"), (300, "5m")):
        sw = as_of(spot, t, sec)
        ow = as_of(opt, t, sec)
        out[f"spot_mom_{lab}"] = round(sw[-1][1] - sw[0][1], 2) if len(sw) > 1 else None
        out[f"opt_mom_{lab}"] = round(ow[-1][1] - ow[0][1], 2) if len(ow) > 1 else None
        if len(sw) > 2:
            ps = [p for _, p in sw]
            rng = max(ps) - min(ps)
            out[f"spot_range_{lab}"] = round(rng, 2)
            out[f"spot_pos_{lab}"] = round(100 * (ps[-1] - min(ps)) / rng, 1) if rng else None
            out[f"dist_from_hi_{lab}"] = round(max(ps) - ps[-1], 2)
            out[f"dist_from_lo_{lab}"] = round(ps[-1] - min(ps), 2)
        if len(ow) > 2:
            po = [p for _, p in ow]
            rng = max(po) - min(po)
            out[f"opt_range_{lab}"] = round(rng, 2)
            out[f"opt_pos_{lab}"] = round(100 * (po[-1] - min(po)) / rng, 1) if rng else None
    w60 = as_of(spot, t, 60)
    if len(w60) > 4:
        mid = len(w60) // 2
        out["spot_accel"] = round((w60[-1][1] - w60[mid][1]) - (w60[mid][1] - w60[0][1]), 2)
    # the partial bar an observer at t would have seen — never the completed one
    pb = bars_of(opt, 60, upto=t)
    if pb:
        b = pb[-1]
        out.update({"bar_partial": True, "bar_dir": b["dir"], "bar_body": b["body"],
                    "bar_range": b["range"], "bar_close_pos": b["close_pos"],
                    "bar_upper_wick": b["upper_wick"], "bar_lower_wick": b["lower_wick"],
                    "bar_ticks": b["n"]})
    prev = bars_of(opt, 60, upto=t)[:-1]
    if prev:
        out["prev_bar_dir"] = prev[-1]["dir"]
        run = 1
        for i in range(len(prev) - 2, -1, -1):
            if prev[i]["dir"] == prev[-1]["dir"]:
                run += 1
            else:
                break
        out["consecutive_bars"] = run
    return out


def trade_profile(book: Book, day: str, tr: Dict) -> Optional[Dict]:
    """One trade with causal before-features and uncensored after-excursions."""
    opt = book.option(tr["symbol"], day)
    if not opt:
        return None
    spot, src = book.spot(day)
    e = parse_ts(tr["entry_time"])
    x = parse_ts(tr["exit_time"])
    sgn = 1 if tr["direction"] == "CE" else -1
    spot0 = next((p for ts, p in reversed(spot) if ts <= e), None)
    prof = {
        "id": tr["id"], "day": day, "side": tr["direction"], "symbol": tr["symbol"],
        "entry_t": e, "exit_t": x, "entry": tr["entry_price"], "exit": tr["exit_price"],
        "captured": round(tr["exit_price"] - tr["entry_price"], 2), "pnl": tr["pnl"],
        "hold": tr["hold_time_sec"], "reason": (tr["exit_reason"] or "").split("|")[0].strip(),
        "score": tr["score"], "confidence": tr["confidence"],
        "win": tr["pnl"] > 0, "spot_at_entry": spot0, "spot_src": src,
        "before": causal_features(spot, opt, e),
        "after_option": excursions(opt, e, tr["entry_price"]),
    }
    if spot0 is not None:
        prof["after_spot"] = excursions(spot, e, spot0, sgn)
    in_trade = [p for t, p in opt if e <= t <= x]
    prof["mfe_in_trade"] = round(max(in_trade) - tr["entry_price"], 2) if in_trade else None
    prof["mae_in_trade"] = round(min(in_trade) - tr["entry_price"], 2) if in_trade else None
    for sec, lab in ((30, "30s"), (60, "1m"), (300, "5m")):
        w = [p for t, p in opt if x < t <= x + _dt.timedelta(seconds=sec)]
        prof[f"post_exit_up_{lab}"] = round(max(w) - tr["exit_price"], 2) if w else None
        prof[f"post_exit_dn_{lab}"] = round(min(w) - tr["exit_price"], 2) if w else None
    return prof


def cascade(prof: Dict, horizon: int = 180) -> Dict:
    """Market available → option available → captured, with both ratios separated."""
    s = (prof.get("after_spot") or {}).get(f"mfe_{horizon}")
    o = (prof.get("after_option") or {}).get(f"mfe_{horizon}")
    got = prof["captured"]
    return {"id": prof["id"], "side": prof["side"], "win": prof["win"],
            "spot_avail": s, "opt_avail": o, "mfe_in_trade": prof.get("mfe_in_trade"),
            "captured": got,
            "transmission": round(o / s, 3) if (s and o is not None and s > 0) else None,
            "capture_of_available": round(got / o, 3) if (o and o > 0) else None,
            "capture_of_mfe": round(got / prof["mfe_in_trade"], 3)
                              if prof.get("mfe_in_trade") else None}


def profiles(book: Book, day: str) -> List[Dict]:
    out = []
    for tr in book.trades(day):
        p = trade_profile(book, day, tr)
        if p:
            out.append(p)
    return out


def compare_groups(profs: Sequence[Dict], key: str) -> Dict:
    """Winners vs losers on one causal feature. Descriptive only — no test is implied."""
    w = [p["before"].get(key) for p in profs if p["win"]]
    l = [p["before"].get(key) for p in profs if not p["win"]]
    w = [x for x in w if x is not None]
    l = [x for x in l if x is not None]
    if len(w) < 2 or len(l) < 2:
        return {}
    return {"feature": key, "winners_n": len(w), "losers_n": len(l),
            "winners": round(_st.mean(w), 2), "losers": round(_st.mean(l), 2),
            "gap": round(_st.mean(w) - _st.mean(l), 2)}
