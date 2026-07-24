# CE/PE Historical Data Pipeline Audit

Generated: 2026-07-05
Scope: Audit-only. No code changes.
Target file: data/historical/v3_5_0/NIFTY_ATM_CE_PE_5MIN_2025-11_to_2026-04.csv

## Pipeline Flow

External provider CSV (input)
-> utils/ingest_cepe_and_audit.py:main()
-> ingest(source_csv, out_csv, mapping)
-> csv.DictReader(source_csv)
-> _normalize_row(row, mapping)
-> rows.append(...)
-> csv.DictWriter(out_csv).writeheader()
-> csv.DictWriter(out_csv).writerows(rows)
-> data/historical/v3_5_0/NIFTY_ATM_CE_PE_5MIN_2025-11_to_2026-04.csv

## Findings (Questions 1-11)

1. Which script creates the file?
- Intended script in this repo: utils/ingest_cepe_and_audit.py
- Evidence: default --out path is the exact target file.

2. Which function writes the CSV?
- Function: ingest(source_csv, out_csv, mapping)
- Writer call: writer = csv.DictWriter(...), then writer.writeheader(), writer.writerows(rows)

3. Where are CE historical candles fetched?
- Not fetched in this pipeline. No CE API fetch call exists in utils/ingest_cepe_and_audit.py.
- CE values are copied from external source columns via mapping.

4. Where are PE historical candles fetched?
- Not fetched in this pipeline. No PE API fetch call exists in utils/ingest_cepe_and_audit.py.
- PE values are copied from external source columns via mapping.

5. Which API is used?
- For this CE/PE generation pipeline: none.
- Note: broker API wrapper has get_candle_data() in brokers/angel_one/client.py, but there is no call site for CE/PE file generation.

6. Does the API actually return data?
- Not applicable to this pipeline, because no API request is made during generation.

7. Is symbol generation failing?
- Not in this pipeline. No option symbol generation step is used by the generator.
- The target CSV currently has ce_symbol/pe_symbol headers, but ingest_cepe_and_audit.py does not generate these fields.

8. Is strike selection failing?
- Not in this pipeline. There is no strike-selection logic here; strike is mapped from input column.

9. Is expiry mapping failing?
- No evidence of mapping failure in code path.
- Mapping is direct copy with key lookup; no row drop on mapping failure.

10. Is the filtering logic dropping all rows?
- No. There is no row-filtering logic in ingest().
- Each row from DictReader is normalized and appended.

11. First point where dataset becomes empty
- First empty point is immediately after reading source rows:
  - rows = []
  - for row in csv.DictReader(source): rows.append(...)
  - If source has no data rows, rows remains empty.
- Therefore emptiness starts at source input stage, before normalization/filtering/writing.

## API Response

No API call is executed by the CE/PE generator path in this repository.

## Filtering

No filter stage exists in ingest().
No condition removes rows.

## CSV Writer

CSV writer always writes header.
Data rows are written only from in-memory rows list using writer.writerows(rows).
If rows is empty, output is header-only.

## Root Cause

Exact zero-row stage: source ingestion stage (csv.DictReader loop) in ingest().

Hard evidence from target file:
- File line count is 1 (header only)
- Header present, no data lines

Additional mismatch evidence:
- Current target header includes: date, spot_close_ref, ce_symbol, pe_symbol
- ingest_cepe_and_audit.py output schema does not include these extra fields
- This indicates the current target file was produced by an external export/template path, not by the in-repo ingest writer output format

Conclusion:
Rows become zero before any transform/filter/write step in repository code. The dataset is already empty at input ingestion boundary.
