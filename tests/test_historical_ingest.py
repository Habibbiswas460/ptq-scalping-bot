"""Tests for utils/ingest_cepe_and_audit.py's raw -> canonical transform.

All source files here are tiny synthetic fixtures written to tmp_path —
not real market data.
"""

import csv

import pytest

from utils.ingest_cepe_and_audit import ingest


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


DEFAULT_MAP = {
    "timestamp": "timestamp", "expiry": "expiry", "strike": "strike",
    "ce_ltp": "ce_close", "ce_volume": "ce_volume",
    "pe_ltp": "pe_close", "pe_volume": "pe_volume",
}


def test_ingest_produces_ce_and_pe_rows(tmp_path):
    source = tmp_path / "raw_cepe.csv"
    _write_csv(
        source,
        [{"timestamp": "2026-08-14 09:15:00", "expiry": "2026-08-14", "strike": "24000",
          "ce_close": "105.5", "ce_volume": "1000", "pe_close": "88.2", "pe_volume": "800"}],
        fieldnames=["timestamp", "expiry", "strike", "ce_close", "ce_volume", "pe_close", "pe_volume"],
    )
    out = tmp_path / "canonical.csv"

    summary = ingest(str(source), str(out), DEFAULT_MAP)

    assert summary["source_rows_read"] == 1
    assert summary["canonical_rows_written"] == 2  # one CE + one PE

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    symbols = {r["symbol"] for r in rows}
    # expiry '2026-08-14' -> exchange token '14AUG26', matching
    # core/trading/broker.py's _build_option_symbol() convention exactly.
    assert "NIFTY14AUG2624000CE" in symbols
    assert "NIFTY14AUG2624000PE" in symbols
    ce_row = next(r for r in rows if r["instrument_type"] == "CE")
    assert ce_row["ltp"] == "105.5"
    assert ce_row["bid"] == ""  # not provided by source -> left null, not fabricated


def test_ingest_skips_side_with_no_ltp(tmp_path):
    source = tmp_path / "raw_cepe.csv"
    _write_csv(
        source,
        [{"timestamp": "2026-08-14 09:15:00", "expiry": "2026-08-14", "strike": "24000",
          "ce_close": "105.5", "ce_volume": "1000", "pe_close": "", "pe_volume": ""}],
        fieldnames=["timestamp", "expiry", "strike", "ce_close", "ce_volume", "pe_close", "pe_volume"],
    )
    out = tmp_path / "canonical.csv"

    summary = ingest(str(source), str(out), DEFAULT_MAP)

    assert summary["canonical_rows_written"] == 1  # only CE, PE had no ltp


def test_ingest_joins_spot_ref_within_tolerance(tmp_path):
    source = tmp_path / "raw_cepe.csv"
    _write_csv(
        source,
        [{"timestamp": "2026-08-14 09:15:02", "expiry": "2026-08-14", "strike": "24000",
          "ce_close": "105.5", "ce_volume": "1000", "pe_close": "88.2", "pe_volume": "800"}],
        fieldnames=["timestamp", "expiry", "strike", "ce_close", "ce_volume", "pe_close", "pe_volume"],
    )
    spot_source = tmp_path / "raw_spot.csv"
    _write_csv(
        spot_source,
        [{"timestamp": "2026-08-14 09:15:00", "close": "24000.0"}],
        fieldnames=["timestamp", "close"],
    )
    out = tmp_path / "canonical.csv"

    summary = ingest(
        str(source), str(out), DEFAULT_MAP,
        spot_source=str(spot_source), spot_join_tolerance_sec=5.0,
    )

    assert summary["spot_points_loaded"] == 1

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ce_row = next(r for r in rows if r["instrument_type"] == "CE")
    assert ce_row["spot_ref"] == "24000.0"
    assert any(r["instrument_type"] == "SPOT" for r in rows)


def test_ingest_leaves_spot_ref_null_outside_tolerance(tmp_path):
    source = tmp_path / "raw_cepe.csv"
    _write_csv(
        source,
        [{"timestamp": "2026-08-14 09:20:00", "expiry": "2026-08-14", "strike": "24000",
          "ce_close": "105.5", "ce_volume": "1000", "pe_close": "88.2", "pe_volume": "800"}],
        fieldnames=["timestamp", "expiry", "strike", "ce_close", "ce_volume", "pe_close", "pe_volume"],
    )
    spot_source = tmp_path / "raw_spot.csv"
    _write_csv(
        spot_source,
        [{"timestamp": "2026-08-14 09:15:00", "close": "24000.0"}],  # 5 min away
        fieldnames=["timestamp", "close"],
    )
    out = tmp_path / "canonical.csv"

    ingest(str(source), str(out), DEFAULT_MAP, spot_source=str(spot_source), spot_join_tolerance_sec=5.0)

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ce_row = next(r for r in rows if r["instrument_type"] == "CE")
    assert ce_row["spot_ref"] == ""  # too far outside tolerance -> left null, not approximated
