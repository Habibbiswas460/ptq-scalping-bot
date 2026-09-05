"""The persisted schema: tables, timeframes and the provenance vocabulary.

Additive by design. Every table is keyed by `session_id` and carries its own provenance, so a
new session, a new timeframe or a new field is an INSERT — never a migration of what is
already recorded. The visual records live in their own database file; the trading database is
opened read-only everywhere in `research/` and is never touched by this package.
"""
from __future__ import annotations

import os

SCHEMA_VERSION = 5
BUILDER_VERSION = "1.4.0"

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_ROOT, "core", "data", "visual_records.db")

# (label, seconds). Daily is one bar per session; it is a real timeframe here, not a summary.
TIMEFRAMES = (("10s", 10), ("30s", 30), ("1m", 60), ("5m", 300), ("30m", 1800), ("1d", 86400))
TF_SECONDS = dict(TIMEFRAMES)
TF_LABELS = [t for t, _ in TIMEFRAMES]

# Indicator series are persisted at these bucket sizes only. Finer buckets would be noise:
# the strategy computes them on 5-minute spot candles.
INDICATOR_TIMEFRAMES = ("1m", "5m")

# Provenance vocabulary, applied to every persisted row.
#
#   REAL          the live system observed and stored this value as it stands
#                 (a tick's LTP, a trade row, a recorded score)
#   RECONSTRUCTED derived deterministically by this layer from REAL data, with no model
#                 (candles, legs, excursions, capture cascade)
#   ESTIMATED     a model or a fabricated input is involved somewhere in the chain
#                 (anything downstream of the synthetic bid/ask, Black-Scholes delta)
#   MISSING       not present in the source; recorded as absent, never filled in
REAL = "real"
RECONSTRUCTED = "reconstructed"
ESTIMATED = "estimated"
MISSING = "missing"

LEG_THRESHOLDS = (5.0, 10.0, 15.0, 25.0)

# Longest stretch without an evaluation that is still treated as continuous coverage. Beyond it
# the record writes an explicit gap: the strategy was not observed deciding anything there, and
# an as-of lookup inside such a stretch says so instead of returning the last row before it as
# though it were current.
EVALUATION_GAP_SEC = 60

# Provenance is uniform per column across every evaluation row, so it is declared once here
# rather than repeated 180,000 times. `posthoc_*` columns are deliberately absent: they are not
# as-of context and never travel with an as-of answer.
EVALUATION_FIELD_PROVENANCE = {
    "ts": REAL, "direction": REAL, "strategy_name": REAL, "accepted": REAL,
    "score": REAL, "confidence": REAL, "market_quality_score": REAL,
    "market_quality_grade": REAL, "reject_reason_id": REAL, "session_type": REAL,
    "context_id": REAL, "score_breakdown_id": REAL, "confidence_breakdown_id": REAL,
    "gate": RECONSTRUCTED, "state_gate": RECONSTRUCTED, "state_detail": RECONSTRUCTED,
    "floor_value": RECONSTRUCTED, "floor_path": RECONSTRUCTED,
    "floor_confidence": RECONSTRUCTED, "cooldown_side": RECONSTRUCTED,
    "cooldown_losses": RECONSTRUCTED, "cooldown_remaining_min": RECONSTRUCTED,
    "loss_streak": RECONSTRUCTED,
}

# Strategy-state vocabulary. Each entry names a state the record can carry and the strongest
# provenance it can ever have, decided by what the source actually holds:
#
#   session_type            REAL          a column on every evaluation
#   directional_cooldown    RECONSTRUCTED only ever written into the rejection text
#   confidence_floor        RECONSTRUCTED the threshold the text states it was measured against
#   consecutive_loss_streak RECONSTRUCTED counted from closed trades, as of their exit time
#   warm_up                 MISSING       no evaluation in the record carries a warm-up reason
STATE_TYPES = {
    "session_type": REAL,
    "directional_cooldown": RECONSTRUCTED,
    "confidence_floor": RECONSTRUCTED,
    "consecutive_loss_streak": RECONSTRUCTED,
    "warm_up": MISSING,
}

DDL = """
CREATE TABLE IF NOT EXISTS visual_sessions (
    session_id       TEXT PRIMARY KEY,
    day              TEXT NOT NULL,
    kind             TEXT NOT NULL,
    spot_source      TEXT,
    spot_provenance  TEXT,
    first_ts         TEXT,
    last_ts          TEXT,
    n_ticks          INTEGER,
    n_signals        INTEGER,
    n_trades         INTEGER,
    n_symbols        INTEGER,
    n_ce_symbols     INTEGER,
    n_pe_symbols     INTEGER,
    spot_open        REAL,
    spot_high        REAL,
    spot_low         REAL,
    spot_close       REAL,
    spot_range       REAL,
    spot_net         REAL,
    pnl              REAL,
    schema_version   INTEGER NOT NULL,
    builder_version  TEXT NOT NULL,
    source_db        TEXT,
    source_rowcounts TEXT,
    built_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visual_series (
    session_id     TEXT NOT NULL,
    series         TEXT NOT NULL,
    role           TEXT NOT NULL,
    symbol         TEXT,
    source         TEXT NOT NULL,
    provenance     TEXT NOT NULL,
    n_points       INTEGER,
    first_ts       TEXT,
    last_ts        TEXT,
    median_gap_sec REAL,
    max_gap_sec    REAL,
    PRIMARY KEY (session_id, series)
);

CREATE TABLE IF NOT EXISTS visual_candles (
    session_id   TEXT NOT NULL,
    series       TEXT NOT NULL,
    timeframe    TEXT NOT NULL,
    ts           TEXT NOT NULL,
    o REAL, h REAL, l REAL, c REAL,
    n            INTEGER,
    range        REAL,
    body         REAL,
    upper_wick   REAL,
    lower_wick   REAL,
    dir          TEXT,
    body_pct     REAL,
    close_pos    REAL,
    velocity_ppm REAL,
    volume       REAL,
    volume_delta REAL,
    oi           REAL,
    source       TEXT NOT NULL,
    provenance   TEXT NOT NULL,
    PRIMARY KEY (session_id, series, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS visual_timeframe_coverage (
    session_id      TEXT NOT NULL,
    series          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    state           TEXT NOT NULL,
    n_bars          INTEGER,
    n_source_points INTEGER,
    expected_bars   INTEGER,
    coverage_pct    REAL,
    thin_bars       INTEGER,
    first_ts        TEXT,
    last_ts         TEXT,
    note            TEXT,
    PRIMARY KEY (session_id, series, timeframe)
);

CREATE TABLE IF NOT EXISTS visual_indicators (
    session_id  TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    ts          TEXT NOT NULL,
    direction   TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       REAL,
    text_value  TEXT,
    n           INTEGER,
    source      TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    PRIMARY KEY (session_id, timeframe, ts, direction, field)
);

CREATE TABLE IF NOT EXISTS visual_market_legs (
    session_id         TEXT NOT NULL,
    threshold          REAL NOT NULL,
    leg_id             INTEGER NOT NULL,
    start_ts           TEXT,
    end_ts             TEXT,
    dur_min            REAL,
    move               REAL,
    dir                TEXT,
    vel_ppm            REAL,
    mfe                REAL,
    mae                REAL,
    hi                 REAL,
    lo                 REAL,
    vol_before         REAL,
    vol_during         REAL,
    entries            INTEGER,
    aligned            INTEGER,
    signals            INTEGER,
    blocked            INTEGER,
    pnl                REAL,
    entry_position_pct REAL,
    trade_ids          TEXT,
    source             TEXT NOT NULL,
    provenance         TEXT NOT NULL,
    PRIMARY KEY (session_id, threshold, leg_id)
);

CREATE TABLE IF NOT EXISTS visual_trade_overlays (
    session_id           TEXT NOT NULL,
    trade_id             INTEGER NOT NULL,
    symbol               TEXT,
    direction            TEXT,
    side                 TEXT,
    qty                  INTEGER,
    entry_ts             TEXT,
    exit_ts              TEXT,
    entry_price          REAL,
    exit_price           REAL,
    hold_sec             INTEGER,
    pnl                  REAL,
    pnl_pct              REAL,
    captured             REAL,
    mfe_in_trade         REAL,
    mae_in_trade         REAL,
    mfe_stored           REAL,
    mae_stored           REAL,
    sl_price             REAL,
    tp_price             REAL,
    sl_provenance        TEXT,
    tp_provenance        TEXT,
    score                INTEGER,
    confidence           INTEGER,
    score_breakdown      TEXT,
    confidence_breakdown TEXT,
    entry_reason         TEXT,
    exit_reason          TEXT,
    exit_class           TEXT,
    spot_at_entry        REAL,
    spot_source          TEXT,
    cascade_horizon_sec  INTEGER,
    spot_available       REAL,
    option_available     REAL,
    transmission         REAL,
    capture_of_available REAL,
    capture_of_mfe       REAL,
    entry_context        TEXT,
    post_entry           TEXT,
    declared_stop_loss       REAL,
    declared_take_profit     REAL,
    declared_stop_distance   REAL,
    declared_target_distance REAL,
    declared_source          TEXT,
    declared_provenance      TEXT,
    declared_governed_exit   INTEGER,
    declared_reachable_stop  INTEGER,
    field_provenance         TEXT,
    market_quality_score     REAL,
    market_quality_grade     TEXT,
    source               TEXT NOT NULL,
    provenance           TEXT NOT NULL,
    PRIMARY KEY (session_id, trade_id)
);

CREATE TABLE IF NOT EXISTS visual_signal_overlays (
    session_id           TEXT NOT NULL,
    row_id               INTEGER NOT NULL,
    kind                 TEXT NOT NULL,
    ts                   TEXT NOT NULL,
    bucket_sec           INTEGER,
    direction            TEXT,
    accepted             INTEGER,
    reject_reason        TEXT,
    gate                 TEXT,
    n                    INTEGER,
    score_min            REAL,
    score_max            REAL,
    score_mean           REAL,
    conf_min             REAL,
    conf_max             REAL,
    conf_mean            REAL,
    score_breakdown      TEXT,
    confidence_breakdown TEXT,
    source               TEXT NOT NULL,
    provenance           TEXT NOT NULL,
    PRIMARY KEY (session_id, row_id)
);

CREATE TABLE IF NOT EXISTS visual_strategy_state (
    session_id      TEXT NOT NULL,
    row_id          INTEGER NOT NULL,
    state_type      TEXT NOT NULL,
    state_value     TEXT,
    numeric_value   REAL,
    side            TEXT,
    start_ts        TEXT,
    end_ts          TEXT,
    n_evaluations   INTEGER,
    loss_count      INTEGER,
    remaining_start_min REAL,
    remaining_end_min   REAL,
    source          TEXT NOT NULL,
    provenance      TEXT NOT NULL,
    evidence        TEXT,
    PRIMARY KEY (session_id, row_id)
);

CREATE TABLE IF NOT EXISTS visual_evaluations (
    session_id       TEXT NOT NULL,
    decision_id      TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    ts               TEXT NOT NULL,
    direction        TEXT,
    strategy_name    TEXT,
    accepted         INTEGER,
    score            REAL,
    confidence       REAL,
    market_quality_score REAL,
    market_quality_grade TEXT,
    gate             TEXT,
    state_gate       TEXT,
    state_detail     TEXT,
    reject_reason_id TEXT,
    floor_value      REAL,
    floor_path       TEXT,
    floor_confidence REAL,
    cooldown_side    TEXT,
    cooldown_losses  INTEGER,
    cooldown_remaining_min REAL,
    session_type     TEXT,
    loss_streak      REAL,
    context_id       TEXT,
    score_breakdown_id TEXT,
    confidence_breakdown_id TEXT,
    context_provenance TEXT NOT NULL,
    posthoc_trade_id INTEGER,
    posthoc_link_method TEXT,
    posthoc_link_delta_sec REAL,
    source           TEXT NOT NULL,
    provenance       TEXT NOT NULL,
    PRIMARY KEY (session_id, decision_id)
);

CREATE TABLE IF NOT EXISTS visual_evaluation_blobs (
    session_id  TEXT NOT NULL,
    blob_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    n_uses      INTEGER,
    provenance  TEXT NOT NULL,
    PRIMARY KEY (session_id, blob_id)
);

CREATE TABLE IF NOT EXISTS visual_evaluation_gaps (
    session_id TEXT NOT NULL,
    gap_id     INTEGER NOT NULL,
    start_ts   TEXT NOT NULL,
    end_ts     TEXT NOT NULL,
    seconds    REAL,
    provenance TEXT NOT NULL,
    reason     TEXT,
    PRIMARY KEY (session_id, gap_id)
);

CREATE TABLE IF NOT EXISTS visual_data_quality (
    session_id   TEXT NOT NULL,
    field        TEXT NOT NULL,
    state        TEXT NOT NULL,
    reason       TEXT,
    n_present    INTEGER,
    n_total      INTEGER,
    coverage_pct REAL,
    detail       TEXT,
    PRIMARY KEY (session_id, field)
);

CREATE INDEX IF NOT EXISTS ix_candles_lookup
    ON visual_candles (session_id, timeframe, series, ts);
CREATE INDEX IF NOT EXISTS ix_signals_lookup
    ON visual_signal_overlays (session_id, kind, ts);
CREATE INDEX IF NOT EXISTS ix_eval_ts
    ON visual_evaluations (session_id, ts, seq);
CREATE INDEX IF NOT EXISTS ix_eval_trade
    ON visual_evaluations (session_id, posthoc_trade_id);
CREATE INDEX IF NOT EXISTS ix_state_lookup
    ON visual_strategy_state (session_id, state_type, start_ts);
CREATE INDEX IF NOT EXISTS ix_indicators_lookup
    ON visual_indicators (session_id, timeframe, field, ts);
"""

# A migrated database and a freshly created one hold the same columns in a different physical
# ORDER: `ALTER TABLE ADD COLUMN` appends, while the DDL below places a column where it reads
# best. The column set is identical and the records are identical, but nothing may depend on
# column position — every read in this package goes through `sqlite3.Row` by name, and a test
# asserts the two schemas agree as sets.
#
# Columns added after SCHEMA_VERSION 1, applied to an existing database by `Store.migrate()`.
# Additive only: a column may be appended here, never removed, renamed or retyped, because a
# record already written must keep meaning exactly what it meant when it was written.
ADDED_COLUMNS = (
    ("visual_trade_overlays", "declared_stop_loss", "REAL"),
    ("visual_trade_overlays", "declared_take_profit", "REAL"),
    ("visual_trade_overlays", "declared_stop_distance", "REAL"),
    ("visual_trade_overlays", "declared_target_distance", "REAL"),
    ("visual_trade_overlays", "declared_source", "TEXT"),
    ("visual_trade_overlays", "declared_provenance", "TEXT"),
    ("visual_trade_overlays", "declared_governed_exit", "INTEGER"),
    ("visual_trade_overlays", "declared_reachable_stop", "INTEGER"),
    ("visual_trade_overlays", "field_provenance", "TEXT"),
    # v3: a rejection caused by strategy state is not the same event as one caused by a market
    # condition. `gate` keeps meaning exactly what it meant under v1/v2 (research.prefilters
    # .classify); `state_gate` is the new, finer split and never overwrites it.
    ("visual_signal_overlays", "state_gate", "TEXT"),
    ("visual_signal_overlays", "state_detail", "TEXT"),
    ("visual_trade_overlays", "state_at_entry", "TEXT"),
    # v5: the market-quality the live system recorded on the trade itself. It is on 131 of 131
    # source trades, and it is taken from the trade row — never from a nearby evaluation, which
    # would be an inference wearing the trade's name.
    ("visual_trade_overlays", "market_quality_score", "REAL"),
    ("visual_trade_overlays", "market_quality_grade", "TEXT"),
)

# Every table this package owns, in delete-safe order for a session rebuild.
TABLES = ("visual_candles", "visual_timeframe_coverage", "visual_indicators",
          "visual_market_legs", "visual_trade_overlays", "visual_signal_overlays",
          "visual_strategy_state", "visual_evaluations", "visual_evaluation_blobs",
          "visual_evaluation_gaps", "visual_data_quality", "visual_series",
          "visual_sessions")
