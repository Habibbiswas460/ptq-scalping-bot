# DATA AUDIT REPORT

## Mode

Historical Backtest Validation Mode (v3.5.0)

Generated on: 2026-07-05 19:57:46

## Inputs

- Spot CSV: [data/historical/v3_5_0/NIFTY_SPOT_5MIN_2025-11_to_2026-04.csv](data/historical/v3_5_0/NIFTY_SPOT_5MIN_2025-11_to_2026-04.csv)
- CE/PE CSV: [data/historical/v3_5_0/NIFTY_ATM_CE_PE_5MIN_2025-11_to_2026-04.csv](data/historical/v3_5_0/NIFTY_ATM_CE_PE_5MIN_2025-11_to_2026-04.csv)

## Integrity Summary

Spot metrics:
- rows: 9075
- start: 2025-11-03T09:15:00+05:30
- end: 2026-04-30T15:25:00+05:30
- missing_ohlc_fields: 0
- duplicate_timestamps: 0
- non_monotonic: 0
- gaps_over_10m: 120
- zero_or_neg_volume: 9075

CE/PE metrics:
- rows: 0
- missing_fields: 0
- missing_values: 0
- duplicate_timestamps: 0
- non_monotonic: 0

## Checklist Status

| Check | Status |
|---|---|
| OHLC data complete | PASS |
| Volume missing নয় | FAIL |
| Options premium data available | FAIL |
| CE & PE synchronized | FAIL |
| Timestamp continuous | PASS |
| Duplicate candles নেই | PASS |

## Gate Decision

Overall Phase-1 status: FAIL

Backtest gate: NO-GO
Do not proceed to Phase-2/Phase-3 until all checks pass.
