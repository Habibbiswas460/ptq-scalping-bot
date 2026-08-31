# Feature Implementation Report
**Date:** 2026-08-10  
**Feature:** MFE / MAE Integration  
**Status:** Complete

---

## Summary

Maximum Favourable Excursion (MFE) and Maximum Adverse Excursion (MAE) metrics have been fully integrated into the bot — from automated capture at trade exit, through persistent database storage, to on-demand lookup via the run.sh launcher.

---

## What Was Implemented

### 1. Database Schema — `core/services/database.py`
- Added `mfe REAL DEFAULT 0` and `mae REAL DEFAULT 0` columns to the `trades` table.
- Added migration guard (`_ensure_table_columns`) so existing databases get the columns without manual migration.

### 2. Analytics Helper — `core/validation/analytics.py`
- Added `compute_excursion(ticks, entry_price)` — computes MFE and MAE from a list of tick prices relative to the entry price.
- Added `mfe_mae_summary()` — overall MFE/MAE stats across all closed trades.
- Added `mfe_mae_by_session(days=11)` — per-session summary for the last N trading days.

### 3. Automatic Capture on Exit — `core/engines/state_machine.py`
- On every trade exit, recent tick history is passed to `compute_excursion`.
- Computed MFE and MAE values are written to the trade record before the exit is logged.
- All future trades will have MFE and MAE populated automatically at close.

### 4. Validation Report — `core/validation/validation_report.py`
- MFE/MAE summary section added to the DVF validation report output.

### 5. Launcher Shortcut — `run.sh`
- New main-menu option **[9] Trade MFE/MAE** — interactive prompt, enter a paper trade ID and get the stored record printed immediately.
- New CLI flag `--trade-id <paper_trade_id>` — direct non-interactive lookup without entering the menu.
  ```
  ./run.sh --trade-id PAPER_1785749874_0
  ```
- Version & Changelog moved to **[10]**.

### 6. Regression Tests — `tests/test_dvf_pipeline.py`
- Tests added for `compute_excursion` with known tick sequences.
- Tests added for `mfe_mae_by_session` against a seeded test database.
- All existing DVF pipeline tests continue to pass.

---

## Files Changed

| File | Change |
|------|--------|
| `core/services/database.py` | Added `mfe`, `mae` columns + migration guard |
| `core/validation/analytics.py` | Added excursion compute, overall summary, session summary |
| `core/engines/state_machine.py` | Wired auto-capture of MFE/MAE on trade exit |
| `core/validation/validation_report.py` | Added MFE/MAE summary section to report |
| `run.sh` | Added menu option [9] and `--trade-id` CLI flag |
| `tests/test_dvf_pipeline.py` | Added regression tests for new analytics helpers |

---

## How to Use

### Interactive (menu)
```
./run.sh
# Select [9] Trade MFE/MAE
# Enter paper trade ID when prompted
```

### Direct lookup
```
./run.sh --trade-id PAPER_1785749874_0
```

### Python API
```python
from core.validation.analytics import mfe_mae_summary, mfe_mae_by_session

# Overall stats
print(mfe_mae_summary())

# Last 11 sessions
for row in mfe_mae_by_session(days=11):
    print(row)
```

---

## Notes
- Historical trades (before 2026-08-10) have `mfe = None` and `mae = None` because the tick data was not retained. They will remain NULL unless backfilled separately.
- Future trades will have both values populated automatically at exit.
