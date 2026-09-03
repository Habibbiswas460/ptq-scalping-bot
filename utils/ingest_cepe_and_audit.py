#!/usr/bin/env python3
"""Rebuild of the historical CE/PE ingestion utility referenced by
data/historical/v3_5_0/EXTERNAL_DATA_INSTRUCTIONS.md (the original was never
committed to git and is gone — see archive/audits/ORIGINAL_CEPE_GENERATOR_AUDIT.md
for that history).

Transforms a raw vendor CE/PE export (wide format: one row per
timestamp+strike, ce_*/pe_* columns — the shape already defined by this
repo's data/historical/v3_5_0/REQUIRED_CE_PE_SCHEMA.csv) plus an optional
separate spot file into the approved canonical LONG format defined in
core/historical/schema.py (one row per instrument).

Note on expiry format: the source's expiry column (--expiry-col) is
assumed to already be ISO 'YYYY-MM-DD'. This is the single format the
canonical schema stores expiry in, and symbols are built from it using
the exact same DDMMMYY conversion core/trading/broker.py uses live
(core.historical.schema.build_option_symbol) — a source row whose expiry
doesn't parse as ISO is skipped (row dropped, counted, and reported), not
guessed at.

Explicit, reproducible, no interpolation:
  - Column mapping is CLI-driven and printed back in the run summary, so the
    exact raw->canonical mapping used is always visible, not implicit.
  - A field the source doesn't provide (bid/ask/oi/Greeks are commonly
    absent from OHLC-candle vendor exports) is left NULL in the canonical
    output — never fabricated. The downstream quality gate is expected to
    fail on missing required fields; that is correct behavior, not a bug
    in this script.
  - spot_ref is populated only from a real SPOT row within
    --spot-join-tolerance-sec of the option row's timestamp; if none exists
    within tolerance, spot_ref is left NULL rather than approximated.

Usage:
    python utils/ingest_cepe_and_audit.py \\
        --source /path/to/provider_cepe.csv \\
        --out data/historical/v3_5_0/canonical/NIFTY_CEPE_canonical.csv \\
        --spot-source /path/to/provider_spot.csv \\
        [--load-db]
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Dict, List, Optional, Tuple

from core.historical.schema import CANONICAL_COLUMNS, build_option_symbol


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None


def _parse_spot_source(path: str, timestamp_col: str, ltp_col: str) -> List[Tuple[str, float]]:
    points = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get(timestamp_col)
            ltp = _to_float(row.get(ltp_col))
            if ts and ltp is not None:
                points.append((_normalize_ts(ts), ltp))
    points.sort()
    return points


def _normalize_ts(ts: str) -> str:
    """Normalize a vendor timestamp to 'YYYY-MM-DD HH:MM:SS' — strips a
    trailing timezone offset (e.g. '+05:30') and a 'T' separator if present,
    without shifting the clock value (vendor is assumed to already export
    IST, matching every other timestamp convention in this repo)."""
    t = ts.replace("T", " ")
    for suffix_len in (6, 5):  # '+05:30' or '+0530'
        if len(t) > suffix_len and t[-suffix_len] in ("+", "-"):
            t = t[: -suffix_len]
            break
    return t.strip()


def _nearest_spot(spot_points: List[Tuple[str, float]], ts: str, tolerance_sec: float) -> Optional[float]:
    if not spot_points:
        return None
    from datetime import datetime

    def parse(s):
        try:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    target = parse(ts)
    if target is None:
        return None
    best = None
    best_delta = None
    for spot_ts, spot_ltp in spot_points:
        spot_dt = parse(spot_ts)
        if spot_dt is None:
            continue
        delta = abs((spot_dt - target).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = spot_ltp, delta
    if best_delta is not None and best_delta <= tolerance_sec:
        return best
    return None


def ingest(
    source_csv: str,
    out_csv: str,
    column_map: Dict[str, str],
    spot_source: Optional[str] = None,
    spot_timestamp_col: str = "timestamp",
    spot_ltp_col: str = "close",
    spot_join_tolerance_sec: float = 5.0,
) -> Dict:
    """Raw wide-format CE/PE source -> canonical long-format CSV.

    Returns a summary dict (rows read, rows written, fields left null per
    column) for the caller to print/log — makes the transform's actual
    behavior visible rather than a black box.
    """
    spot_points = _parse_spot_source(spot_source, spot_timestamp_col, spot_ltp_col) if spot_source else []

    rows_read = 0
    rows_skipped_bad_expiry = 0
    canonical_rows: List[Dict] = []
    null_counts = {c: 0 for c in CANONICAL_COLUMNS}

    with open(source_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for src in reader:
            rows_read += 1
            ts = _normalize_ts(src.get(column_map["timestamp"], ""))
            expiry = src.get(column_map["expiry"]) or None
            strike = _to_int(src.get(column_map["strike"]))

            for side in ("ce", "pe"):
                ltp_col = column_map.get(f"{side}_ltp")
                if not ltp_col:
                    continue
                ltp = _to_float(src.get(ltp_col))
                if ltp is None:
                    continue  # no data for this side at this timestamp — skip, don't fabricate

                itype = "CE" if side == "ce" else "PE"
                symbol = build_option_symbol(expiry, strike, itype)
                if symbol is None:
                    rows_skipped_bad_expiry += 1
                    continue  # expiry didn't parse as ISO — skip, don't guess a format
                spot_ref = _nearest_spot(spot_points, ts, spot_join_tolerance_sec) if spot_points else None

                row = {
                    "timestamp": ts,
                    "instrument_type": itype,
                    "symbol": symbol,
                    "expiry": expiry,
                    "strike": strike,
                    "ltp": ltp,
                    "bid": _to_float(src.get(column_map.get(f"{side}_bid", ""), None)),
                    "ask": _to_float(src.get(column_map.get(f"{side}_ask", ""), None)),
                    "volume": _to_int(src.get(column_map.get(f"{side}_volume", ""), None)),
                    "oi": _to_int(src.get(column_map.get(f"{side}_oi", ""), None)),
                    "delta": _to_float(src.get(column_map.get(f"{side}_delta", ""), None)),
                    "gamma": _to_float(src.get(column_map.get(f"{side}_gamma", ""), None)),
                    "theta": _to_float(src.get(column_map.get(f"{side}_theta", ""), None)),
                    "vega": _to_float(src.get(column_map.get(f"{side}_vega", ""), None)),
                    "iv": _to_float(src.get(column_map.get(f"{side}_iv", ""), None)),
                    "spot_ref": spot_ref,
                }
                for col in CANONICAL_COLUMNS:
                    if row.get(col) is None:
                        null_counts[col] += 1
                canonical_rows.append(row)

    # Also emit SPOT rows themselves, if a spot source was given.
    if spot_source:
        for spot_ts, spot_ltp in spot_points:
            canonical_rows.append(
                {
                    "timestamp": spot_ts,
                    "instrument_type": "SPOT",
                    "symbol": "NIFTY",
                    "expiry": None,
                    "strike": None,
                    "ltp": spot_ltp,
                    "bid": None,
                    "ask": None,
                    "volume": None,
                    "oi": None,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                    "iv": None,
                    "spot_ref": spot_ltp,
                }
            )

    canonical_rows.sort(key=lambda r: (r["timestamp"], r["symbol"]))

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CANONICAL_COLUMNS))
        writer.writeheader()
        writer.writerows(canonical_rows)

    return {
        "source_rows_read": rows_read,
        "canonical_rows_written": len(canonical_rows),
        "rows_skipped_bad_expiry": rows_skipped_bad_expiry,
        "null_counts": null_counts,
        "spot_points_loaded": len(spot_points),
        "column_map_used": column_map,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Raw wide-format CE/PE CSV from the vendor")
    parser.add_argument("--out", required=True, help="Canonical long-format output CSV path")
    parser.add_argument("--spot-source", default=None, help="Optional raw spot CSV to also emit SPOT rows and join spot_ref")
    parser.add_argument("--spot-timestamp-col", default="timestamp")
    parser.add_argument("--spot-ltp-col", default="close")
    parser.add_argument("--spot-join-tolerance-sec", type=float, default=5.0)
    parser.add_argument("--load-db", action="store_true", help="Also load the canonical rows into the HistoricalStore")
    parser.add_argument("--store-dir", default=None, help="Override HistoricalStore directory (default: data/historical/canonical)")

    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--expiry-col", default="expiry")
    parser.add_argument("--strike-col", default="strike")
    for side in ("ce", "pe"):
        parser.add_argument(f"--{side}-ltp-col", default=f"{side}_close")
        parser.add_argument(f"--{side}-bid-col", default=None)
        parser.add_argument(f"--{side}-ask-col", default=None)
        parser.add_argument(f"--{side}-volume-col", default=f"{side}_volume")
        parser.add_argument(f"--{side}-oi-col", default=None)
        parser.add_argument(f"--{side}-delta-col", default=None)
        parser.add_argument(f"--{side}-gamma-col", default=None)
        parser.add_argument(f"--{side}-theta-col", default=None)
        parser.add_argument(f"--{side}-vega-col", default=None)
        parser.add_argument(f"--{side}-iv-col", default=None)

    args = parser.parse_args(argv)

    column_map = {
        "timestamp": args.timestamp_col,
        "expiry": args.expiry_col,
        "strike": args.strike_col,
    }
    for side in ("ce", "pe"):
        for field in ("ltp", "bid", "ask", "volume", "oi", "delta", "gamma", "theta", "vega", "iv"):
            val = getattr(args, f"{side}_{field}_col")
            if val:
                column_map[f"{side}_{field}"] = val

    summary = ingest(
        source_csv=args.source,
        out_csv=args.out,
        column_map=column_map,
        spot_source=args.spot_source,
        spot_timestamp_col=args.spot_timestamp_col,
        spot_ltp_col=args.spot_ltp_col,
        spot_join_tolerance_sec=args.spot_join_tolerance_sec,
    )

    print(f"Source rows read:        {summary['source_rows_read']}")
    print(f"Canonical rows written:  {summary['canonical_rows_written']}")
    print(f"Rows skipped (bad expiry): {summary['rows_skipped_bad_expiry']}")
    print(f"Spot points loaded:      {summary['spot_points_loaded']}")
    print(f"Column map used:         {summary['column_map_used']}")
    print("Null counts per canonical column (fields the source didn't provide):")
    for col, count in summary["null_counts"].items():
        if count:
            print(f"  {col}: {count}")
    print(f"\nWrote: {args.out}")

    if args.load_db:
        from core.historical.storage import HistoricalStore, DEFAULT_STORE_DIR

        store = HistoricalStore(args.store_dir or DEFAULT_STORE_DIR)
        with open(args.out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                for col in ("strike", "volume", "oi"):
                    r[col] = _to_int(r[col]) if r[col] else None
                for col in ("ltp", "bid", "ask", "delta", "gamma", "theta", "vega", "iv", "spot_ref"):
                    r[col] = _to_float(r[col]) if r[col] else None
                rows.append(r)
        written = store.write_rows(rows)
        print(f"Loaded into HistoricalStore ({store.store_dir}): {written} new rows")

    print(
        "\nNext step: run utils/phase1_data_audit.py against this output "
        "before treating it as backtest-ready — this script performs no "
        "validation itself."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
