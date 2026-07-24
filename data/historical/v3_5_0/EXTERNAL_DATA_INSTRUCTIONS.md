# External CE/PE Data Ingestion Instructions

Use this when your provider gives CE/PE historical intraday data in a different column format.

## 1. Minimum required columns in project schema

- timestamp
- expiry
- strike
- ce_open, ce_high, ce_low, ce_close, ce_volume
- pe_open, pe_high, pe_low, pe_close, pe_volume

## 2. Ingest external file into project schema

If source already has the same column names:

```bash
/home/lora/projects/PTQ-scalping bot/venv/bin/python utils/ingest_cepe_and_audit.py \
  --source /path/to/your/provider_cepe.csv
```

If source uses different names, map columns explicitly:

```bash
/home/lora/projects/PTQ-scalping bot/venv/bin/python utils/ingest_cepe_and_audit.py \
  --source /path/to/your/provider_cepe.csv \
  --timestamp-col ts \
  --expiry-col exp_date \
  --strike-col strike_price \
  --ce-open-col CE_O \
  --ce-high-col CE_H \
  --ce-low-col CE_L \
  --ce-close-col CE_C \
  --ce-volume-col CE_V \
  --pe-open-col PE_O \
  --pe-high-col PE_H \
  --pe-low-col PE_L \
  --pe-close-col PE_C \
  --pe-volume-col PE_V
```

Output target:
- data/historical/v3_5_0/NIFTY_ATM_CE_PE_5MIN_2025-11_to_2026-04.csv

## 3. Re-run Phase-1 gate

```bash
/home/lora/projects/PTQ-scalping bot/venv/bin/python utils/phase1_data_audit.py
```

## 4. Decision

- If report says PASS: proceed to Phase-2 configuration freeze.
- If report says FAIL: do not proceed to backtest.
