"""Visual record layer: what is persisted must be what was derived, and nothing more.

Two families of test here. The first checks the arithmetic — bucket boundaries, aggregation,
coverage counting — because a chart that quietly disagrees with the numbers beside it is worse
than no chart. The second checks the guarantees the layer exists to make: nothing is
fabricated where data is absent, entry context cannot contain a post-entry tick, a rebuild
reproduces the same rows, and the viewer cannot reach past the store into the trading database.
"""
import ast
import datetime as dt
import json
import os
import re
import sqlite3

import pytest

from research.db import Book
from research.visual import build as vbuild
from research.visual import schema as vschema
from research.visual.audit import audit_all, audit_session, buildable
from research.visual.build import build_session, candle_rows, normalized_series, signal_rows
from research.visual.store import Reader, Store

T0 = dt.datetime(2026, 9, 4, 10, 0, 0)
STATES = {vschema.REAL, vschema.RECONSTRUCTED, vschema.ESTIMATED, vschema.MISSING}


def ramp(n, step_sec, fn, start=T0):
    return [(start + dt.timedelta(seconds=i * step_sec), float(fn(i))) for i in range(n)]


@pytest.fixture(scope="module")
def book():
    return Book()


@pytest.fixture(scope="module")
def tick_day(book):
    days = [s["day"] for s in book.sessions() if s["kind"] == "tick"]
    if not days:
        pytest.skip("no tick-complete session in the database")
    return days[-1]


@pytest.fixture(scope="module")
def built(tmp_path_factory, book, tick_day):
    """One real tick session, built into a throwaway store."""
    path = str(tmp_path_factory.mktemp("visual") / "v.db")
    with Store(path) as st:
        counts = build_session(book, tick_day, st)
    return {"path": path, "day": tick_day, "counts": counts}


# ── candle aggregation and timeframe correctness ──────────────────────────
def test_every_timeframe_is_built_including_30m_and_daily():
    meta = {"role": "spot", "symbol": None, "source": "ticks", "provenance": vschema.REAL,
            "points": ramp(3600, 5, lambda i: 100 + i * 0.01), "quotes": None,
            "median_gap_sec": 5, "max_gap_sec": 5}
    rows, cov = candle_rows("D", "spot", meta)
    got = {c["timeframe"] for c in cov}
    assert got == set(vschema.TF_LABELS)
    assert "30m" in got and "1d" in got
    per_tf = {}
    for r in rows:
        per_tf.setdefault(r["timeframe"], []).append(r)
    # 5 hours of ticks: exactly one daily bar, and coarser frames hold fewer bars
    assert len(per_tf["1d"]) == 1
    assert len(per_tf["10s"]) > len(per_tf["1m"]) > len(per_tf["5m"]) > len(per_tf["30m"])


def test_bars_land_on_the_timeframe_boundary():
    meta = {"role": "spot", "symbol": None, "source": "ticks", "provenance": vschema.REAL,
            "points": ramp(400, 7, lambda i: 100 + i), "quotes": None,
            "median_gap_sec": 7, "max_gap_sec": 7}
    rows, _ = candle_rows("D", "spot", meta)
    for r in rows:
        ts = dt.datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        sec = vschema.TF_SECONDS[r["timeframe"]]
        offset = (ts - ts.replace(hour=0, minute=0, second=0)).total_seconds()
        assert offset % sec == 0, f"{r['timeframe']} bar not aligned to its bucket"


def test_ohlc_survives_the_round_trip(built):
    with Reader(built["path"]) as r:
        bars = r.candles(built["day"], "spot", "1m")
        assert bars, "spot 1m candles must be persisted for a tick session"
        for b in bars:
            assert b["l"] <= b["o"] <= b["h"] and b["l"] <= b["c"] <= b["h"]
            assert b["range"] == pytest.approx(b["h"] - b["l"], abs=1e-6)
            assert b["n"] >= 1


def test_first_bar_volume_delta_is_absent_not_zero():
    quotes = [{"t": T0 + dt.timedelta(seconds=i), "ltp": 100.0 + i, "bid": None, "ask": None,
               "volume": 1000 + 10 * i, "oi": None} for i in range(120)]
    meta = {"role": "ce", "symbol": "X", "source": "ticks", "provenance": vschema.REAL,
            "points": [(q["t"], q["ltp"]) for q in quotes], "quotes": quotes,
            "median_gap_sec": 1, "max_gap_sec": 1}
    rows, _ = candle_rows("D", "ce:X", meta)
    one_min = [r for r in rows if r["timeframe"] == "1m"]
    assert one_min[0]["volume_delta"] is None, "no previous cumulative reading exists"
    assert one_min[1]["volume_delta"] is not None


# ── nothing is fabricated ────────────────────────────────────────────────
def test_a_session_without_market_data_gets_no_candles(book, tmp_path):
    only = [s["day"] for s in book.sessions() if s["kind"] == "trades-only"]
    if not only:
        pytest.skip("no trades-only session")
    path = str(tmp_path / "v.db")
    with Store(path) as st:
        counts = build_session(book, only[0], st)
    assert counts["visual_candles"] == 0, "a session with no series must not produce bars"
    assert counts["visual_trade_overlays"] > 0, "its trades are still real and must be kept"
    with Reader(path) as r:
        assert r.candles(only[0], "spot", "1m") == []
        for t in r.trades(only[0]):
            assert t["sl_price"] is None and t["sl_provenance"] == vschema.MISSING


def test_every_persisted_row_carries_a_known_provenance(built):
    with Reader(built["path"]) as r:
        day = built["day"]
        for row in r.candles(day, "spot", "1m")[:50]:
            assert row["provenance"] in STATES
        for row in r.legs(day)[:50]:
            assert row["provenance"] in STATES
        for row in r.quality(day):
            assert row["state"] in STATES
        for row in r.coverage(day):
            assert row["state"] in STATES | {"missing"}


def test_coverage_counts_thin_bars_rather_than_hiding_them(built):
    with Reader(built["path"]) as r:
        cov = {(c["series"], c["timeframe"]): c for c in r.coverage(built["day"])}
        spot10 = cov[("spot", "10s")]
        assert spot10["n_bars"] > 0 and spot10["expected_bars"] >= spot10["n_bars"]
        assert spot10["thin_bars"] is not None


# ── look-ahead protection ────────────────────────────────────────────────
def test_entry_context_cannot_see_past_the_entry(built):
    """The builder's causal fields must be identical when later ticks are truncated away."""
    with Reader(built["path"]) as r:
        trades = r.trades(built["day"])
    if not trades:
        pytest.skip("session has no trades")
    for t in trades:
        ctx = t["entry_context"]
        if not ctx:
            continue
        assert ctx.get("bar_partial") is True, \
            "entry context must use the partial bar, never the completed one"
        assert not any(k.startswith("post_") for k in ctx), \
            "post-entry fields must not appear in entry context"


def test_post_entry_movement_is_kept_separate(built):
    with Reader(built["path"]) as r:
        trades = [t for t in r.trades(built["day"]) if t["post_entry"]]
    if not trades:
        pytest.skip("session has no trades with an option series")
    for t in trades:
        assert "option" in t["post_entry"]
        assert t["option_available"] is None or isinstance(t["option_available"], float)
        assert t["cascade_horizon_sec"] == vbuild.CASCADE_HORIZON


def test_signal_match_for_a_trade_never_comes_from_the_future(book, tick_day):
    sig = book.signals(tick_day)
    if not sig:
        pytest.skip("no evaluations")
    t = sig[len(sig) // 2]["t"]
    m = vbuild._match_signal(sig, t, None)
    assert m is not None and m["t"] <= t


# ── alignment with the source ────────────────────────────────────────────
def test_trade_overlays_match_the_source_trades(book, built):
    src = {t["id"]: t for t in book.trades(built["day"])}
    with Reader(built["path"]) as r:
        got = r.trades(built["day"])
    assert len(got) == len(src)
    for row in got:
        s = src[row["trade_id"]]
        assert row["symbol"] == s["symbol"] and row["direction"] == s["direction"]
        assert row["pnl"] == s["pnl"]
        assert row["entry_ts"][:19] == str(s["entry_time"])[:19]


def test_accepted_signals_are_persisted_one_for_one(book, built):
    n_accepted = sum(1 for s in book.signals(built["day"]) if s["accepted"])
    with Reader(built["path"]) as r:
        rows = r.signals(built["day"], "accepted")
    assert len(rows) == n_accepted


def test_rejection_buckets_conserve_every_rejected_evaluation(book, tick_day):
    sig = book.signals(tick_day)
    rows = signal_rows(book, tick_day, tick_day)
    rejected = sum(1 for s in sig if not s["accepted"])
    bucketed = sum(r["n"] for r in rows if r["kind"] == "rejected_bucket")
    assert bucketed == rejected, "aggregation must not drop or double-count an evaluation"


# ── reproducibility and consistency ──────────────────────────────────────
def test_rebuild_is_idempotent(book, tmp_path, tick_day):
    path = str(tmp_path / "v.db")
    with Store(path) as st:
        first = build_session(book, tick_day, st)
        second = build_session(book, tick_day, st)
    assert first == second, "a rebuild must not change the row counts"
    with Reader(path) as r:
        assert len(r.sessions()) == 1, "rebuilding must replace, never append"
        assert r.stats()["visual_candles"] == first["visual_candles"]


def test_two_builds_produce_identical_candles(book, tmp_path, tick_day):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    for p in (a, b):
        with Store(p) as st:
            build_session(book, tick_day, st)
    with Reader(a) as ra, Reader(b) as rb:
        ca = [(x["ts"], x["o"], x["h"], x["l"], x["c"], x["n"])
              for x in ra.candles(tick_day, "spot", "5m")]
        cb = [(x["ts"], x["o"], x["h"], x["l"], x["c"], x["n"])
              for x in rb.candles(tick_day, "spot", "5m")]
    assert ca == cb and ca


def test_every_child_row_belongs_to_a_persisted_session(built):
    with Reader(built["path"]) as r:
        ids = {s["session_id"] for s in r.sessions()}
        for tbl in ("visual_candles", "visual_market_legs", "visual_trade_overlays",
                    "visual_signal_overlays", "visual_data_quality"):
            got = {x[0] for x in r.con.execute(f"SELECT DISTINCT session_id FROM {tbl}")}
            assert got <= ids, f"{tbl} references a session that is not persisted"


# ── the structural guarantees ────────────────────────────────────────────
def test_the_viewer_reads_the_store_and_never_the_trading_database():
    src = open(os.path.join("research", "visual", "viewer.py")).read()
    mods = {n.module or "" for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    mods |= {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import)
             for a in n.names}
    assert not any(m.startswith("research.db") for m in mods), \
        "the viewer must read persisted records only"
    assert any(m.startswith("research.visual.store") for m in mods)


def test_the_visual_store_is_not_the_trading_database():
    assert vschema.DB_PATH != Book().path
    assert vschema.DB_PATH.endswith("visual_records.db")


def test_no_session_date_is_hardcoded_in_the_package():
    root = os.path.join("research", "visual")
    for name in os.listdir(root):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(root, name)).read()
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b",
                             "\n".join(l for l in src.splitlines()
                                       if not l.strip().startswith("#")
                                       and "python -m" not in l)), \
            f"{name} hardcodes a session date"


def test_audit_reports_what_can_be_reconstructed(book):
    rows = audit_all(book)
    assert rows and all(set(r["timeframes"]) == set(vschema.TF_LABELS) for r in rows)
    assert set(buildable(rows)) <= {r["day"] for r in rows}
    tick = [r for r in rows if r["kind"] == "tick"]
    if tick:
        assert all(v["state"] == "reconstructable" for v in tick[-1]["timeframes"].values())


def test_audit_of_a_trades_only_session_claims_no_timeframe(book):
    only = [s["day"] for s in book.sessions() if s["kind"] == "trades-only"]
    if not only:
        pytest.skip("no trades-only session")
    a = audit_session(book, only[0])
    assert a["spot_points"] == 0
    assert all(v["state"] == vschema.MISSING for v in a["timeframes"].values())


def test_persisted_entry_context_equals_the_context_of_a_truncated_series(book, built):
    """The strongest form of the guard: recompute the stored context from a series that has
    been cut off at the entry second. If a post-entry tick had leaked in, the two would differ.
    """
    from research.candles import as_of
    from research.db import parse_ts
    from research.entries import causal_features

    day = built["day"]
    with Reader(built["path"]) as r:
        trades = [t for t in r.trades(day) if t["entry_context"]]
    if not trades:
        pytest.skip("session has no trades with an option series")
    spot, _ = book.spot(day)
    checked = 0
    for t in trades[:5]:
        e = parse_ts(t["entry_ts"])
        opt = book.option(t["symbol"], day)
        truncated = causal_features(as_of(spot, e), as_of(opt, e), e)
        stored = t["entry_context"]
        for k, v in truncated.items():
            if isinstance(v, float):
                assert stored.get(k) == pytest.approx(v), f"{k} differs once the future is cut"
            else:
                assert stored.get(k) == v, f"{k} differs once the future is cut"
        checked += 1
    assert checked, "no trade was actually checked"


def test_a_closed_session_is_picked_up_automatically():
    """The post-session command must build the visual record itself, for whatever day it is
    given, so nothing has to be remembered after a live session."""
    import inspect

    from research import after_session

    assert hasattr(after_session, "visual_records")
    src = inspect.getsource(after_session.main)
    assert "visual_records(day)" in src, "after_session must build the record for the day it ran"
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", inspect.getsource(after_session.visual_records))


# ── increment 1: the declared bracket, and per-field provenance ───────────
def test_declared_bracket_join_requires_the_facts_to_agree():
    """A shared order_id is not enough: a row that disagrees on the event is refused."""
    from research.visual.positions import _same_event

    trade = {"symbol": "X", "direction": "CE", "qty": 65, "entry_price": 100.0,
             "entry_time": "2026-09-04 10:00:00"}
    assert _same_event(trade, dict(trade))[0]
    for field, wrong in (("symbol", "Y"), ("direction", "PE"), ("qty", 50),
                         ("entry_price", 100.5), ("entry_time", "2026-09-04 10:00:01")):
        assert not _same_event(trade, dict(trade, **{field: wrong}))[0], \
            f"a mismatch on {field} must refuse the join"


def test_declared_bracket_is_only_attached_where_the_source_has_one(book, built):
    from research.visual.positions import declared_brackets

    src = declared_brackets(book, built["day"])
    with Reader(built["path"]) as r:
        rows = r.trades(built["day"])
    for t in rows:
        if t["trade_id"] in src:
            assert t["declared_stop_loss"] == src[t["trade_id"]]["declared_stop_loss"]
            assert t["declared_provenance"] == vschema.REAL
        else:
            assert t["declared_stop_loss"] is None
            assert t["declared_provenance"] == vschema.MISSING


def test_the_operative_stop_stays_missing_even_where_a_bracket_exists(built):
    """The declared bracket must never be promoted into sl_price/tp_price."""
    with Reader(built["path"]) as r:
        for t in r.trades(built["day"]):
            assert t["sl_price"] is None and t["tp_price"] is None
            assert t["sl_provenance"] == vschema.MISSING
            assert r.field_state(t, "sl_price") == vschema.MISSING
            if t["declared_stop_loss"] is not None:
                assert t["declared_stop_loss"] != t["sl_price"]


def test_whether_the_bracket_governed_the_exit_is_recorded_not_assumed(book, built):
    from research.visual.positions import declared_brackets, governed_exit

    src = {t["id"]: t for t in book.trades(built["day"])}
    br = declared_brackets(book, built["day"])
    with Reader(built["path"]) as r:
        for t in r.trades(built["day"]):
            expected = governed_exit(src[t["trade_id"]], br.get(t["trade_id"]))
            got = t["declared_governed_exit"]
            assert (None if got is None else bool(got)) == expected


def test_field_provenance_is_per_field_not_per_row(built):
    with Reader(built["path"]) as r:
        rows = r.trades(built["day"])
    assert rows, "session has no trades"
    for t in rows:
        fp = t["field_provenance"]
        assert fp, "every trade overlay must carry per-field provenance"
        assert set(fp.values()) <= STATES
        assert fp["entry_price"] == vschema.REAL
        assert fp["captured"] == vschema.RECONSTRUCTED
        assert fp["sl_price"] == vschema.MISSING
        # one row genuinely mixes states — that is the point of recording them separately
        assert len(set(fp.values())) > 1


def test_migration_only_adds_columns(tmp_path):
    """An existing database must survive the upgrade with its rows and meaning intact."""
    import sqlite3

    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE visual_trade_overlays (session_id TEXT NOT NULL, trade_id INTEGER NOT NULL,
            pnl REAL, source TEXT NOT NULL, provenance TEXT NOT NULL,
            PRIMARY KEY (session_id, trade_id));
    """)
    con.execute("INSERT INTO visual_trade_overlays VALUES ('D',1,12.5,'trades','real')")
    con.commit()
    con.close()

    with Store(path) as st:
        st.migrate()
        row = st.con.execute("SELECT pnl, provenance, declared_stop_loss "
                             "FROM visual_trade_overlays WHERE trade_id=1").fetchone()
    assert row[0] == 12.5 and row[1] == "real", "an existing value must not be rewritten"
    assert row[2] is None, "a column added later is absent, not back-filled with a guess"


def test_quality_row_reports_the_bracket_coverage_and_its_reach(built):
    with Reader(built["path"]) as r:
        q = {x["field"]: x for x in r.quality(built["day"])}
    assert q["declared_stop_loss"]["state"] in (vschema.REAL, vschema.MISSING)
    assert q["sl_price"]["state"] == vschema.MISSING
    assert "governed" in (q["sl_price"]["detail"] or ""), \
        "the record must say the declared bracket was not used as the operative stop"


# ── increment 2: strategy state ──────────────────────────────────────────
def test_state_parsers_read_only_what_the_text_actually_says():
    from research.visual.strategy_state import parse_cooldown, parse_floor

    cd = parse_cooldown("CE signal blocked: CE blocked (2 losses, 11min cooldown)")
    assert cd == {"side": "CE", "losses": 2, "remaining_min": 11}
    assert parse_cooldown("CE signal blocked: CE overbought + MACD declining") is None
    assert parse_cooldown(None) is None

    fl = parse_floor("Low confidence 61% < 69% (MQ A+)")
    assert fl == {"confidence": 61, "floor": 69, "mq_grade": "A+", "path": "market_quality"}
    fl2 = parse_floor("Low confidence 82% < 85%")
    assert fl2["floor"] == 85 and fl2["path"] == "directional" and fl2["mq_grade"] is None
    assert parse_floor("Chop filter: EMA squeeze") is None


def test_a_cooldown_rejection_is_not_counted_as_a_plain_directional_block():
    from research.prefilters import classify
    from research.visual.strategy_state import classify_state

    reason = "CE signal blocked: CE blocked (2 losses, 11min cooldown)"
    assert classify(reason) == "CE directional block", "the v1 gate keeps its old meaning"
    assert classify_state(reason) == ("strategy_state", "directional_cooldown")
    assert classify_state("CE signal blocked: CE overbought + MACD declining") == ("market", None)


def test_state_provenance_matches_what_the_source_can_support(built):
    with Reader(built["path"]) as r:
        rows = r.strategy_state(built["day"])
    assert rows, "a tick session must recover some state"
    for row in rows:
        assert row["provenance"] == vschema.STATE_TYPES[row["state_type"]], \
            f"{row['state_type']} must not claim a stronger provenance than its source"
    types = {row["state_type"] for row in rows}
    assert "warm_up" in types, "an unrecoverable state must still be recorded as MISSING"
    for row in rows:
        if row["state_type"] == "warm_up":
            assert row["provenance"] == vschema.MISSING and row["state_value"] is None


def test_session_type_is_real_and_maps_to_the_three_phases(book, built):
    with Reader(built["path"]) as r:
        rows = r.strategy_state(built["day"], "session_type")
    assert rows
    assert {row["state_value"] for row in rows} <= {"OPEN", "MID", "CLOSE"}
    assert all(row["provenance"] == vschema.REAL for row in rows)
    src = {s.get("session_type") for s in book.signals(built["day"])}
    assert {row["state_value"] for row in rows} == {x for x in src if x}


def test_cooldown_window_boundaries_come_from_the_observations(built):
    with Reader(built["path"]) as r:
        rows = r.strategy_state(built["day"], "directional_cooldown")
    if not rows:
        pytest.skip("this session has no cooldown rejection")
    for row in rows:
        assert row["start"] < row["end"], "a window must span the observations it was built from"
        assert row["side"] in ("CE", "PE")
        assert row["loss_count"] is not None
        # the text counts down, so the window ends nearer zero than it began
        assert row["remaining_end_min"] <= row["remaining_start_min"]


def test_the_loss_streak_is_as_of_the_exit_never_the_entry(book, built):
    """A trade may not raise the streak it is itself measured against."""
    with Reader(built["path"]) as r:
        trades = r.trades(built["day"])
        for t in trades:
            if not t["state_at_entry"]:
                continue
            got = t["state_at_entry"]["states"].get("consecutive_loss_streak")
            at_entry = float(got[0]["numeric"]) if got else 0.0
            closed_losses = 0
            streak = 0
            for other in sorted(trades, key=lambda x: x["exit_ts"] or ""):
                if not other["exit_ts"] or other["exit_ts"] > t["entry_ts"]:
                    break
                streak = 0 if (other["pnl"] or 0) > 0 else streak + 1
                closed_losses += 1
            assert at_entry == streak, \
                f"trade {t['trade_id']} saw a streak that includes a trade closing after it"


def test_state_lookup_never_returns_a_state_that_starts_later(built):
    import datetime as _dt

    with Reader(built["path"]) as r:
        rows = r.strategy_state(built["day"])
        starts = [x["start"] for x in rows if x["start"]]
        t = min(starts) - _dt.timedelta(seconds=1)
        assert r.state_at(built["day"], t) == {}, "nothing can be active before anything started"
        mid = starts[len(starts) // 2]
        for st, active in r.state_at(built["day"], mid).items():
            for a in active:
                assert a["start"] <= mid


def test_coexisting_states_are_not_collapsed_into_one(built):
    """Two confidence floors genuinely run at once; the record must keep both."""
    with Reader(built["path"]) as r:
        floors = r.strategy_state(built["day"], "confidence_floor")
        if len({f["numeric_value"] for f in floors}) < 2:
            pytest.skip("this session shows only one floor")
        overlapping = None
        for a in floors:
            for b in floors:
                if a["numeric_value"] != b["numeric_value"] and a["start"] <= b["start"] <= a["end"]:
                    overlapping = b["start"]
                    break
            if overlapping:
                break
        if not overlapping:
            pytest.skip("no overlapping floor windows in this session")
        active = r.state_at(built["day"], overlapping)["confidence_floor"]
    assert len(active) > 1, "both floors in force must both be reported"


def test_no_three_loss_lock_state_is_asserted(built):
    with Reader(built["path"]) as r:
        types = {x["state_type"] for x in r.strategy_state(built["day"])}
    assert not any("lock" in t for t in types), \
        "the lock was never declared by the live system and must not be invented here"


# ── increment 3: the as-of evaluation layer ──────────────────────────────
class _CutBook(Book):
    """A Book that physically has no data after `cut`.

    The point is not to filter results but to make the future *unavailable*: an as-of builder
    that reached for a later row would find nothing there, so any dependence on the future shows
    up as a difference in the output rather than as a judgement call in review.
    """

    def __init__(self, cut):
        super().__init__()
        self.cut = cut

    def signals(self, day):
        return [s for s in super().signals(day) if s["t"] <= self.cut]

    def trades(self, day=None):
        from research.db import parse_ts as _p
        out = []
        for t in super().trades(day):
            if t.get("exit_time") and _p(t["exit_time"]) > self.cut:
                continue
            if t.get("entry_time") and _p(t["entry_time"]) > self.cut:
                continue
            out.append(t)
        return out


def _causal_fields(row):
    from research.visual.evaluations import POSTHOC_FIELDS
    return {k: v for k, v in row.items() if k not in POSTHOC_FIELDS}


def test_same_past_with_no_future_produces_identical_evaluations(book, tick_day):
    """The structural proof: delete everything after T and the record before T must not move."""
    import datetime as _dt

    from research.visual.evaluations import evaluation_rows

    full, _ = evaluation_rows(book, tick_day, tick_day)
    assert full, "session has no evaluations"
    cut = full[len(full) // 2]["ts"]
    cut_dt = _dt.datetime.strptime(cut, "%Y-%m-%d %H:%M:%S")

    cut_rows, _ = evaluation_rows(_CutBook(cut_dt), tick_day, tick_day)
    before = [_causal_fields(r) for r in full if r["ts"] <= cut]
    assert cut_rows, "the truncated build produced nothing"
    assert [_causal_fields(r) for r in cut_rows] == before, \
        "an evaluation before the cut changed once the future was removed"


def test_loss_streak_in_an_evaluation_ignores_trades_that_close_later(book, tick_day):
    from research.db import parse_ts as _p
    from research.visual.evaluations import evaluation_rows

    rows, _ = evaluation_rows(book, tick_day, tick_day)
    trades = [t for t in book.trades(tick_day) if t.get("exit_time")]
    for r in rows[::400]:
        t = _p(r["ts"])
        streak = 0
        for tr in sorted(trades, key=lambda x: str(x["exit_time"])):
            if _p(tr["exit_time"]) > t:
                break
            streak = 0 if (tr["pnl"] or 0) > 0 else streak + 1
        assert r["loss_streak"] == float(streak)


def test_as_of_never_returns_a_later_evaluation(built):
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
        assert rows
        for probe in (rows[0], rows[len(rows) // 3], rows[-1]):
            got = r.as_of_evaluation(built["day"], probe["ts"])
            assert got["ts"] <= probe["ts"]
        earliest = rows[0]["t"] - dt.timedelta(seconds=1)
        assert r.as_of_evaluation(built["day"], earliest) is None


def test_as_of_answer_carries_no_post_hoc_knowledge(built):
    from research.visual.evaluations import POSTHOC_FIELDS

    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
        linked = [x for x in rows if x["posthoc_trade_id"]]
        if not linked:
            pytest.skip("no evaluation is linked to a trade")
        got = r.as_of_evaluation(built["day"], linked[0]["ts"])
    for f in POSTHOC_FIELDS:
        assert f not in got, f"{f} is knowledge from after the instant and must not be returned"


def test_every_source_evaluation_is_persisted_exactly_once(book, built):
    src = book.signals(built["day"])
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    assert len(rows) == len(src), "an evaluation was dropped or duplicated"
    ids = [x["decision_id"] for x in rows]
    assert len(set(ids)) == len(ids), "decision_id must stay unique"
    assert set(ids) == {s["decision_id"] for s in src}


def test_two_evaluations_in_one_second_stay_two_rows(book, built):
    from collections import Counter

    src = Counter(s["t"] for s in book.signals(built["day"]))
    crowded = [t for t, n in src.items() if n > 1]
    if not crowded:
        pytest.skip("no second carries more than one evaluation")
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], crowded[0], crowded[0])
    assert len(rows) == src[crowded[0]], "decisions sharing a second must not be merged"


def test_no_rejection_is_lost_by_the_evaluation_layer(book, built):
    src = sum(1 for s in book.signals(built["day"]) if not s["accepted"])
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    assert sum(1 for x in rows if not x["accepted"]) == src


def test_context_provenance_reflects_whether_a_market_view_existed(book, built):
    have = sum(1 for s in book.signals(built["day"])
               if any(v is not None for v in (s.get("indicators_snapshot") or {}).values()))
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    real = sum(1 for x in rows if x["context_provenance"] == vschema.REAL)
    assert real == have
    assert real < len(rows), "this session should contain pre-scoring rejections with no view"


def test_gaps_are_recorded_and_not_bridged(built):
    with Reader(built["path"]) as r:
        gaps = r.evaluation_gaps(built["day"])
        if not gaps:
            pytest.skip("this session has continuous evaluation coverage")
        for g in gaps:
            assert g["provenance"] == vschema.MISSING
            assert g["seconds"] > vschema.EVALUATION_GAP_SEC
        mid = (dt.datetime.strptime(gaps[0]["start_ts"], "%Y-%m-%d %H:%M:%S")
               + dt.timedelta(seconds=gaps[0]["seconds"] / 2))
        assert r.in_gap(built["day"], mid), "a lookup inside a blind stretch must say so"
        answer = r.as_of_evaluation(built["day"], mid)
        assert answer["in_gap"] is True


def test_trade_link_is_reconstructed_and_reports_its_method(built):
    with Reader(built["path"]) as r:
        trades = r.trades(built["day"])
        if not trades:
            pytest.skip("session has no trades")
        linked = [r.evaluations_for_trade(built["day"], t["trade_id"]) for t in trades]
    found = [x for x in linked if x["linked"]]
    assert found, "no trade could be linked to an evaluation"
    for x in found:
        assert x["link_provenance"] == vschema.RECONSTRUCTED
        assert 0 <= x["link_delta_sec"] <= 2.0
        assert x["linked"]["accepted"] == 1
        assert all(e["t"] <= x["linked"]["t"] for e in x["lead_up"]), \
            "the run-up must end at the linked evaluation, never continue past it"


def test_a_trades_only_session_gets_no_evaluations(book, tmp_path):
    only = [s["day"] for s in book.sessions() if s["kind"] == "trades-only"]
    if not only:
        pytest.skip("no trades-only session")
    path = str(tmp_path / "v.db")
    with Store(path) as st:
        counts = build_session(book, only[0], st)
    assert counts["visual_evaluations"] == 0
    assert counts["visual_evaluation_blobs"] == 0
    with Reader(path) as r:
        assert r.as_of_evaluation(only[0], "2026-09-04 11:00:00") is None
        q = {x["field"]: x for x in r.quality(only[0])}
        assert q["evaluation_layer"]["state"] == vschema.MISSING


def test_evaluation_blobs_are_content_addressed_and_shared(built):
    with Reader(built["path"]) as r:
        rows = r.evaluation_slice(built["day"], "2000-01-01 00:00:00", "2100-01-01 00:00:00")
        blobs = r._rows("SELECT * FROM visual_evaluation_blobs WHERE session_id=?",
                        (built["day"],))
    assert blobs and len(blobs) < len(rows), "the point of the blob store is sharing"
    from research.visual.evaluations import blob_id
    for b in blobs[:50]:
        assert b["blob_id"] == blob_id(b["payload"]), "a blob must be addressed by its content"
    used = {x["score_breakdown_id"] for x in rows if x["score_breakdown_id"]}
    known = {b["blob_id"] for b in blobs}
    assert used <= known, "an evaluation references a payload that was not stored"


def test_rebuild_is_byte_identical_by_content_not_by_row_order(book, tmp_path, tick_day):
    """Idempotency must be checked on content ordered by key.

    Row order in the file is a physical artifact: a rebuild deletes and reinserts, so rowids
    move even when nothing about the record changed. Ordering by primary key is what actually
    tests the record.
    """
    import hashlib

    keys = {"visual_evaluations": "session_id,decision_id",
            "visual_evaluation_blobs": "session_id,blob_id",
            "visual_evaluation_gaps": "session_id,gap_id",
            "visual_strategy_state": "session_id,row_id",
            "visual_trade_overlays": "session_id,trade_id",
            "visual_data_quality": "session_id,field"}

    path = str(tmp_path / "v.db")

    def fingerprint(store):
        # tuple(), not repr(): the store hands back sqlite3.Row objects whose repr is their
        # memory address, which would make any two reads differ for no reason at all
        h = hashlib.sha256()
        for table, pk in sorted(keys.items()):
            for row in store.con.execute(f"SELECT * FROM {table} ORDER BY {pk}"):
                h.update(repr(tuple(row)).encode())
        return h.hexdigest()

    with Store(path) as st:
        build_session(book, tick_day, st)
        first = fingerprint(st)
        build_session(book, tick_day, st)
        second = fingerprint(st)
    assert first == second


# ── increment 4: the chart layer ─────────────────────────────────────────
def _imports_of(path):
    """Every module a file reaches for, including `from pkg import mod` as `pkg.mod`."""
    tree = ast.parse(open(path).read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
            mods |= {f"{n.module}.{a.name}" for a in n.names if n.module}
        elif isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
    return mods


def test_the_chart_layer_touches_no_database_at_all():
    mods = _imports_of(os.path.join("research", "visual", "charts.py"))
    assert not any(m.startswith("research.db") for m in mods)
    assert not any(m.startswith("research.visual.store") for m in mods), \
        "charts.py renders rows it is handed; it must not fetch them"
    assert not any("sqlite" in m for m in mods)


def test_the_viewer_composes_and_does_not_draw():
    src = open(os.path.join("research", "visual", "viewer.py")).read()
    mods = _imports_of(os.path.join("research", "visual", "viewer.py"))
    assert not any(m.startswith("research.db") for m in mods)
    assert "research.visual.charts" in mods
    for mark in ("viewBox", "<rect", "<circle", "<path", "<line x1"):
        assert mark not in src, f"{mark} is drawing; it belongs in the chart layer"


def test_charts_render_deterministically(built):
    from research.visual import charts as C

    with Reader(built["path"]) as r:
        bars = r.candles(built["day"], "spot", "1m")
        trades = r.trades(built["day"])
        legs = r.legs(built["day"], 10.0)
        states = r.strategy_state(built["day"])
    a = C.render_price(bars, title="t", provenance="reconstructed", trades=trades, legs=legs)
    b = C.render_price(bars, title="t", provenance="reconstructed", trades=trades, legs=legs)
    assert a == b and a
    assert C.render_state(states) == C.render_state(states)
    assert C.render_cascade(trades) == C.render_cascade(trades)


def test_a_series_with_no_bars_renders_nothing_rather_than_an_empty_frame():
    from research.visual import charts as C

    assert C.render_price([], title="t", provenance="reconstructed") == ""
    assert C.render_volume([], title="t") == ""
    assert C.render_state([]) == ""
    assert C.render_cascade([]) == ""


def test_a_constant_or_missing_indicator_is_refused_with_a_reason(built):
    from research.visual import charts as C

    with Reader(built["path"]) as r:
        ind = r.indicators(built["day"], "1m")
    refused = {}
    for field in ("regime", "oi_direction", "oi_change_pct", "rsi"):
        svg, why = C.render_indicator(ind, field, title=field)
        refused[field] = (bool(svg), why)
    assert refused["rsi"][0], "a varying REAL series must be drawn"
    for field in ("regime", "oi_direction", "oi_change_pct"):
        drawn, why = refused[field]
        assert not drawn, f"{field} is constant or MISSING and must not be drawn"
        assert why and field in why


def test_gaps_are_drawn_as_gaps_and_the_activity_line_is_broken(built):
    from research.visual import charts as C
    from research.visual.viewer import _gaps_dt

    with Reader(built["path"]) as r:
        gaps = _gaps_dt(r.evaluation_gaps(built["day"]))
        acts = [x for x in r.indicators(built["day"], "1m") if x["field"] == "evaluations"]
    if not gaps:
        pytest.skip("this session has continuous coverage")
    svg = C.render_activity(acts, title="a", gaps=gaps)
    assert "gapfill" in svg, "a blind stretch must be painted, not skipped over"
    with_gaps = svg.count("<path")
    without = C.render_activity(acts, title="a", gaps=()).count("<path")
    assert with_gaps > without, "the line must be broken into segments at the gaps"


def test_the_trade_focus_makes_the_entry_boundary_explicit(built):
    from research.visual import charts as C

    with Reader(built["path"]) as r:
        trades = [t for t in r.trades(built["day"]) if t.get("symbol")]
        if not trades:
            pytest.skip("session has no trades")
        t = trades[0]
        name = next((x["series"] for x in r.series(built["day"])
                     if x["symbol"] == t["symbol"]), None)
        bars = r.candles(built["day"], name, "10s")
    svg = C.render_trade_focus(t, bars)
    assert "AS-OF ENTRY" in svg and "POST-ENTRY OUTCOME" in svg, \
        "the two regions must be named on the chart itself"


def test_the_focus_chart_ignores_data_beyond_its_window(built):
    """Future bars outside the window cannot change what is drawn."""
    import datetime as _dt

    from research.visual import charts as C

    with Reader(built["path"]) as r:
        trades = [t for t in r.trades(built["day"]) if t.get("symbol")]
        if not trades:
            pytest.skip("session has no trades")
        t = trades[0]
        name = next((x["series"] for x in r.series(built["day"])
                     if x["symbol"] == t["symbol"]), None)
        bars = r.candles(built["day"], name, "10s")
    base = C.render_trade_focus(t, bars)
    far = t["exit_t"] + _dt.timedelta(minutes=C.FOCUS_TRAIL_MIN + 30)
    invented = dict(bars[-1], t=far, o=9999.0, h=9999.0, l=9999.0, c=9999.0)
    assert C.render_trade_focus(t, list(bars) + [invented]) == base, \
        "a bar outside the window changed the drawing"


def test_the_declared_bracket_is_labelled_declared_and_never_as_the_stop(built):
    from research.visual import charts as C

    with Reader(built["path"]) as r:
        trades = [t for t in r.trades(built["day"])
                  if t.get("symbol") and t.get("declared_stop_loss") is not None]
        if not trades:
            pytest.skip("no trade carries a declared bracket")
        t = trades[0]
        name = next((x["series"] for x in r.series(built["day"])
                     if x["symbol"] == t["symbol"]), None)
        bars = r.candles(built["day"], name, "10s")
    svg = C.render_trade_focus(t, bars)
    assert "declared SL" in svg and "declared TP" in svg
    assert "exit never reached it" in svg or "exit reached it" in svg
    assert t["sl_price"] is None and t["tp_price"] is None


def test_selection_ids_are_shared_between_chart_and_table(built):
    from research.visual.viewer import session_page

    with Reader(built["path"]) as r:
        trades = r.trades(built["day"])
        html = session_page(r, built["day"]).html()
    if not trades:
        pytest.skip("session has no trades")
    tid = trades[0]["trade_id"]
    assert html.count(f'data-event="t{tid}"') + html.count(f"data-event='t{tid}'") >= 2, \
        "a trade must be selectable in more than one view for selection to synchronise"
    legs = [m for m in re.findall(r'data-event="(leg\d+-\d+)"', html)]
    assert legs, "market legs must be selectable too"


def test_rendering_does_not_alter_the_persisted_records(built):
    import hashlib

    from research.visual.viewer import session_page

    def fingerprint(path):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        h = hashlib.sha256()
        for table in ("visual_candles", "visual_trade_overlays", "visual_evaluations",
                      "visual_strategy_state", "visual_data_quality"):
            for row in con.execute(f"SELECT * FROM {table}"):
                h.update(repr(tuple(row)).encode())
        con.close()
        return h.hexdigest()

    before = fingerprint(built["path"])
    with Reader(built["path"]) as r:
        session_page(r, built["day"]).html()
    assert fingerprint(built["path"]) == before, "rendering must be read-only"


def test_a_rendered_page_stays_within_the_budget(built):
    from research.visual.viewer import PAGE_BUDGET_KB, session_page

    with Reader(built["path"]) as r:
        html = session_page(r, built["day"]).html()
    kb = len(html) / 1024
    assert kb <= PAGE_BUDGET_KB, f"page is {kb:.0f} KB, over the {PAGE_BUDGET_KB} KB budget"


def test_thinning_keeps_the_ends_and_never_flattens_a_spike():
    from research.visual import charts as C

    pts = [(i, 0.0) for i in range(50)]
    pts[25] = (25, 100.0)
    # a projection where many points land in the same pixel cell, as a real chart does
    out = C.thin(pts, lambda p: (p[0] * 0.05, p[1]))
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert (25, 100.0) in out, "a single-point excursion must survive display thinning"
    assert len(out) < len(pts), "co-located points should have been dropped"


# ── increment 5, step 2: trade-level market quality ──────────────────────
def test_v5_migration_adds_the_mq_columns_without_touching_a_row(tmp_path):
    """Written before the columns existed: an ALTER must add, never rewrite or back-fill.

    A v4 database is built by hand here, given a row, then migrated. The row's own values must
    survive untouched and the new columns must be NULL — a column added later is absent on rows
    written earlier, not filled in with a guess.
    """
    import sqlite3 as _sq

    path = str(tmp_path / "v4.db")
    con = _sq.connect(path)
    con.executescript("""
        CREATE TABLE visual_trade_overlays (
            session_id TEXT NOT NULL, trade_id INTEGER NOT NULL, pnl REAL, score INTEGER,
            field_provenance TEXT, source TEXT NOT NULL, provenance TEXT NOT NULL,
            PRIMARY KEY (session_id, trade_id));
    """)
    con.execute("INSERT INTO visual_trade_overlays VALUES "
                "('D',1,12.5,59,'{\"entry_price\":\"real\"}','trades','real')")
    con.commit()
    con.close()

    with Store(path) as st:
        applied = st.migrate()
        row = st.con.execute(
            "SELECT pnl, score, field_provenance, provenance, market_quality_score, "
            "market_quality_grade FROM visual_trade_overlays WHERE trade_id=1").fetchone()
    assert row[0] == 12.5 and row[1] == 59, "an existing value was rewritten"
    assert row[2] == '{"entry_price":"real"}' and row[3] == "real"
    assert row[4] is None and row[5] is None, "a new column must not be back-filled"
    assert any("market_quality" in a for a in applied) or applied == []


def test_trade_market_quality_matches_the_source_exactly(book, built):
    """Every persisted MQ value must equal the source trade's, or both be absent."""
    src = {t["id"]: t for t in book.trades(built["day"])}
    with Reader(built["path"]) as r:
        rows = r.trades(built["day"])
    assert rows, "session has no trades"
    for row in rows:
        s = src[row["trade_id"]]
        assert row["market_quality_score"] == s["market_quality_score"]
        assert row["market_quality_grade"] == s["market_quality_grade"]


def test_market_quality_provenance_is_real_only_where_the_source_has_it(built):
    with Reader(built["path"]) as r:
        rows = r.trades(built["day"])
    for row in rows:
        state = r.field_state(row, "market_quality_score") if False else \
            row["field_provenance"].get("market_quality_score")
        if row["market_quality_score"] is None:
            assert state == vschema.MISSING, "an absent value must not claim REAL"
        else:
            assert state == vschema.REAL, "a value the live system wrote is REAL"
        grade_state = row["field_provenance"].get("market_quality_grade")
        assert grade_state in (vschema.REAL, vschema.MISSING)


def test_market_quality_is_never_inferred_from_the_evaluation_layer(book, built):
    """The trade's own recorded grade is used — never the nearest evaluation's."""
    with Reader(built["path"]) as r:
        rows = r.trades(built["day"])
        for row in rows:
            ev = r.as_of_evaluation(built["day"], row["entry_ts"])
            if not ev or ev.get("market_quality_score") is None:
                continue
            src = {t["id"]: t for t in book.trades(built["day"])}[row["trade_id"]]
            assert row["market_quality_score"] == src["market_quality_score"], \
                "the trade's MQ must come from the trade row, not from an evaluation"


# ── increment 5, step 3: the cross-session query layer ───────────────────
@pytest.fixture(scope="module")
def live_reader():
    from research.visual.schema import DB_PATH
    if not os.path.exists(DB_PATH):
        pytest.skip("no visual records built")
    r = Reader(DB_PATH)
    yield r
    r.close()


def test_query_layer_reads_only_through_the_reader():
    mods = _imports_of(os.path.join("research", "visual", "query.py"))
    assert not any(m.startswith("research.db") for m in mods), \
        "the comparison layer must not reach the trading database"
    assert "research.visual.store.Reader" in mods or "research.visual.store" in mods
    assert not any("sqlite" in m for m in mods)


def test_no_dimension_computes_significance_or_recommends_anything():
    """Scan the code, not the prose: the module docstring is allowed to say it does none of
    this, but no identifier, call or emitted string may."""
    tree = ast.parse(open(os.path.join("research", "visual", "query.py")).read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docstrings.add(d)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                names.add(node.value)
    haystack = " ".join(names).lower()
    for banned in ("p_value", "pvalue", "p-value", "significan", "ttest", "t_test",
                   "chisq", "chi2", "optimi", "recommend", "should_", "threshold_tune"):
        assert banned not in haystack, f"{banned!r} has no place in an evidence layer"


def test_every_dimension_returns_coverage_and_provenance(live_reader):
    from research.visual import query as Q

    out = Q.run_all(live_reader)
    assert len(out) == len(Q.DIMENSIONS)
    for name, d in out.items():
        assert d["dimension"] == name
        if d["excluded"]:
            assert d["groups"] == [] and d["provenance"] == vschema.MISSING
            continue
        assert d["provenance"] in STATES
        assert d["question"]
        for g in d["groups"]:
            assert {"label", "n", "sessions_covered", "provenance", "caveats",
                    "metrics"} <= set(g)
            assert g["provenance"] in STATES


def test_a_thin_group_reports_insufficient_instead_of_a_number(live_reader):
    from research.visual import query as Q

    thin = []
    for d in Q.run_all(live_reader).values():
        for g in d["groups"]:
            if g["n"] < Q.MIN_GROUP_N:
                thin.append(g)
    assert thin, "the record contains groups below the floor; the guard must be exercised"
    for g in thin:
        assert all(v == Q.INSUFFICIENT for v in g["metrics"].values()), \
            f"{g['label']} has {g['n']} rows but reports numbers"
        assert any("below the" in c for c in g["caveats"])


def test_a_thin_group_is_reported_not_dropped(live_reader):
    from research.visual import query as Q

    labels = [g["label"] for g in Q.state_at_entry(live_reader)["groups"]]
    assert any("streak 4" in l or "streak 5" in l for l in labels), \
        "a one-trade group must still appear, marked INSUFFICIENT"


def test_accepted_vs_rejected_refuses_to_pool(live_reader):
    from research.visual import query as Q

    d = Q.accepted_vs_rejected(live_reader)
    assert d["per_session_only"] is True
    assert len(d["groups"]) >= 2
    with pytest.raises(ValueError, match="must not be pooled"):
        Q.accepted_vs_rejected(live_reader, pooled=True)


def test_excluded_dimensions_are_returned_with_their_reason(live_reader):
    from research.visual import query as Q

    for name in ("ce_vs_pe_movement", "regime", "pooled_confidence_band", "cooldown_at_entry"):
        d = Q.DIMENSIONS[name](live_reader)
        assert d["excluded"], f"{name} must state why it cannot be compared"
        assert d["groups"] == []
    assert set(Q.EXCLUDED) <= set(Q.DIMENSIONS), "every exclusion must be reachable"


def test_missingness_is_reported_rather_than_dropped(live_reader):
    from research.visual import query as Q

    cov = Q.coverage_matrix(live_reader)
    assert cov["coverage"]["fields_varying_by_session"] > 0
    labels = {g["label"] for g in cov["groups"]}
    assert "pe_coverage" in labels and "evaluation_layer" in labels

    st = Q.session_type(live_reader)
    assert st["coverage"]["trades_without_session_type"] > 0
    assert any("carry no session type" in c for c in st["caveats"])

    sess = Q.by_session(live_reader)
    only = [g for g in sess["groups"] if any("trades-only" in c for c in g["caveats"])]
    assert only, "trades-only sessions must be present and labelled, not filtered out"


def test_gross_pnl_carries_its_cost_caveat_everywhere_it_appears(live_reader):
    from research.visual import query as Q

    for d in Q.run_all(live_reader).values():
        if d["excluded"]:
            continue
        uses_pnl = any("gross_pnl_sum" in g["metrics"] for g in d["groups"])
        if uses_pnl:
            assert any("gross" in c for c in d["caveats"]), \
                f"{d['dimension']} reports P&L without the missing-cost caveat"


def test_the_opening_window_states_that_no_trade_happened_there(live_reader):
    from research.visual import query as Q

    d = Q.opening_window(live_reader)
    assert d["coverage"]["trades_in_window"] == 0
    assert any("no trade in the record was entered in this window" in c for c in d["caveats"])
    assert any("MISSING and not zero movement" in c for c in d["caveats"])
    market = d["coverage"]["sessions_with_window_market"]
    evals = d["coverage"]["sessions_with_window_evaluations"]
    assert market < evals, "the two coverages differ and both must be reported"


def test_market_quality_bands_use_the_trade_row(live_reader, book):
    from research.visual import query as Q

    d = Q.market_quality_bands(live_reader)
    grades = {g["label"] for g in d["groups"]}
    src = {t["market_quality_grade"] for t in book.trades()}
    assert grades == {g for g in src if g}, "bands must be exactly the recorded grades"
    total = sum(g["metrics"]["trades"] for g in d["groups"]
                if g["metrics"]["trades"] != Q.INSUFFICIENT)
    assert total == len(book.trades())


def test_queries_are_deterministic_and_read_only(live_reader):
    import hashlib

    from research.visual import query as Q

    def digest():
        return hashlib.sha256(
            repr(sorted((k, repr(v)) for k, v in Q.run_all(live_reader).items())).encode()
        ).hexdigest()

    con = sqlite3.connect(f"file:{live_reader.path}?mode=ro", uri=True)
    before = con.execute("SELECT count(*) FROM visual_trade_overlays").fetchone()[0]
    a, b = digest(), digest()
    after = con.execute("SELECT count(*) FROM visual_trade_overlays").fetchone()[0]
    con.close()
    assert a == b, "the same records must produce the same answer"
    assert before == after


def test_the_evaluation_group_by_column_is_whitelisted(live_reader):
    with pytest.raises(ValueError, match="not a groupable"):
        live_reader.evaluation_counts("pnl")
    with pytest.raises(ValueError):
        live_reader.evaluation_counts("1=1; DROP TABLE visual_evaluations")


# ── increment 5, step 4: the evidence page and its CLI ───────────────────
def test_the_compare_page_reads_only_the_query_layer():
    mods = _imports_of(os.path.join("research", "visual", "compare.py"))
    assert not any(m.startswith("research.db") for m in mods)
    assert "research.visual.query" in mods
    src = open(os.path.join("research", "visual", "compare.py")).read()
    for mark in ("viewBox", "<rect", "<circle", "<path"):
        assert mark not in src, f"{mark} is drawing; it belongs in the chart layer"


def test_recorded_facts_survive_the_reporting_floor(live_reader):
    """A thin group withholds comparison values but must still print what the record holds."""
    from research.visual import query as Q

    thin = [g for g in Q.by_session(live_reader)["groups"]
            if g["metrics"].get("trades") == Q.INSUFFICIENT]
    assert thin, "the record contains sessions below the floor"
    for g in thin:
        assert g["facts"], "recorded facts must not be withheld with the metrics"
        assert g["facts"].get("kind"), "the session's kind is a fact, not a comparison"


def test_a_withheld_group_is_hatched_and_never_drawn_as_zero(live_reader):
    from research.visual import charts as C
    from research.visual import query as Q

    d = Q.state_at_entry(live_reader)
    svg = C.render_group_bars(d["groups"], "trades", title="t", subtitle="s")
    withheld = [g for g in d["groups"]
                if any(v == Q.INSUFFICIENT for v in g["metrics"].values())]
    assert withheld, "this dimension has groups below the floor"
    assert svg.count("gapfill") == len(withheld), \
        "each withheld group needs its own placeholder, not a zero-height bar"
    assert svg.count(C.INSUFFICIENT_LABEL) >= len(withheld)


def test_comparison_charts_keep_the_records_order(live_reader):
    """Sorting by size would turn evidence into a ranking."""
    import re as _re

    from research.visual import charts as C
    from research.visual import query as Q

    d = Q.market_quality_bands(live_reader)
    svg = C.render_group_bars(d["groups"], "trades", title="t", subtitle="s")
    drawn = _re.findall(r'class="ax">([^<]+)</text>', svg)
    labels = [g["label"] for g in d["groups"]]
    assert [l for l in drawn if l in labels] == labels, "chart reordered the groups"


def test_the_page_states_every_exclusion(live_reader):
    from research.visual import query as Q
    from research.visual.compare import compare_page

    html = compare_page(live_reader).html()
    for name, reason in Q.EXCLUDED.items():
        assert "EXCLUDED" in html
        assert esc_fragment(reason)[:60] in html, f"{name} exclusion reason is not on the page"


def esc_fragment(s):
    import html as _h
    return _h.escape(s, quote=True)


def test_the_page_never_ranks_or_recommends(live_reader):
    from research.visual.compare import compare_page

    html = compare_page(live_reader).html().lower()
    for banned in ("p-value", "p value", "statistically significant", "we recommend",
                   "you should", "best performing", "worst performing", "optimal threshold"):
        assert banned not in html, f"{banned!r} turns evidence into a verdict"


def test_the_page_shows_missingness_and_coverage(live_reader):
    from research.visual.compare import compare_page

    html = compare_page(live_reader).html()
    assert "Coverage" in html and "pe_coverage" in html
    assert "gross" in html, "the missing-cost caveat must reach the page"
    assert "PER SESSION ONLY" in html, "the pooling refusal must be visible"
    assert "comparisons persisted" in html.lower() or "persisted" in html


def test_rendering_the_page_writes_no_records(live_reader):
    import hashlib

    from research.visual.compare import compare_page

    def fingerprint():
        con = sqlite3.connect(f"file:{live_reader.path}?mode=ro", uri=True)
        h = hashlib.sha256()
        for t in ("visual_trade_overlays", "visual_evaluations", "visual_data_quality"):
            for row in con.execute(f"SELECT count(*) FROM {t}"):
                h.update(repr(tuple(row)).encode())
        con.close()
        return h.hexdigest()

    before = fingerprint()
    compare_page(live_reader).html()
    assert fingerprint() == before


def test_the_page_is_deterministic_and_within_budget(live_reader):
    from research.visual.compare import PAGE_BUDGET_KB, compare_page

    import re as _re
    a = compare_page(live_reader).html()
    b = compare_page(live_reader).html()
    strip = lambda h: _re.sub(r"generated \d{4}-\d\d-\d\d \d\d:\d\d", "", h)
    assert strip(a) == strip(b), "the same records must render the same page"
    assert len(a) / 1024 <= PAGE_BUDGET_KB


def test_the_compare_command_is_wired_and_persists_nothing(tmp_path):
    import inspect

    from research.visual import __main__ as cli

    assert "compare" in inspect.getsource(cli.main)
    src = inspect.getsource(cli.cmd_compare)
    assert "write_compare" in src
    assert "Store" not in src, "the compare command must never open the store for writing"


def test_the_post_session_command_refreshes_the_evidence_page():
    """A new session changes what every comparison is drawn from, so the page is rebuilt with
    the record — and still persists nothing."""
    import inspect

    from research import after_session

    src = inspect.getsource(after_session.visual_records)
    assert "write_compare" in src
    assert "Store()" in src and src.count("Store(") == 1, \
        "only the record build may open the store for writing"
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", src), "no session date may be hardcoded"
