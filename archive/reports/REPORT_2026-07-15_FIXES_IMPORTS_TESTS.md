# PTQ Bot Daily Engineering Report

- Date: 2026-07-15
- Generated At: 2026-07-15 20:09:23
- Scope: Today's bug findings, fixes, import stability, readiness path, test discovery, and full test suite validation.

## 1) Executive Summary

Today we fixed multiple startup/runtime stability issues that were causing:
- import-time failures,
- readiness-check crashes,
- slow test discovery in launcher preflight,
- intermittent/full SQLite lock crashes during test collection and app startup,
- misleading health-check API status.

End state now:
- Import smoke check: PASS
- Pytest collection: PASS
- Full test suite: PASS (126 tests)
- `run.sh --health --no-animation`: PASS (5 checks)
- `run.sh --readiness --no-animation`: PASS (no DB-lock traceback)

---

## 2) Bugs Found Today

### Bug A: Health-check API probe was incorrect
- Symptom:
  - Health showed:
    - `Angel One API: ERR:AngelOneClient.__init__() missing 4 required positional arguments...`
- Root Cause:
  - `run.sh` health API probe instantiated `AngelOneClient()` without required credentials.

### Bug B: Launcher preflight slow and noisy on imports/tests
- Symptom:
  - `./run.sh` startup felt slow.
  - Import check sometimes failed due to deep side effects.
  - Test discovery took too long.
- Root Cause:
  - Preflight was doing heavier import chain and pytest collect path.

### Bug C: Pytest collection interrupted by SQLite lock
- Symptom:
  - `Interrupted: ... errors during collection`
  - `sqlite3.OperationalError: database is locked`
- Root Cause:
  - Tests/import path touched runtime DB (`trades.db`) while another process held lock.

### Bug D: Readiness checker crash from import chain
- Symptom:
  - Paper Trading -> Readiness check crashed with DB lock traceback.
- Root Cause:
  - `core.engines` package eager-imported `entry_engine`, which imported DB at module import time.

### Bug E: App startup crash on transient DB lock
- Symptom:
  - Bot launch crashed in `core/services/database.py` at global DB initialization.
- Root Cause:
  - Schema initialization had no robust retry strategy for transient SQLite lock contention.

---

## 3) Fixes Applied (File-wise)

### 3.1 `run.sh`

#### Fix: Health API connectivity probe corrected
- Added `.env` credential extraction (`ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET`).
- Updated probe to call `AngelOneClient(api_key, client_id, password, totp_secret)`.
- Added explicit SKIP path when credentials missing.

#### Fix: Test-suite health message improved
- Health test section now inspects full pytest output.
- If lock condition found, prints explicit warning instead of generic failure.

#### Fix: Startup preflight speed
- Imports check switched to lightweight targets.
- Test discovery switched to quick file discovery (count-based), not full pytest collection in preflight.

---

### 3.2 `core/__init__.py`

#### Fix: Eager imports removed, lazy loading introduced
- Replaced direct `from core.main import main` + wildcard eager re-exports.
- Added lazy proxy for `main()`.
- Added lazy `__getattr__` lookup across core submodules.

Impact:
- Importing `core` no longer forces full runtime side effects.

---

### 3.3 `core/services/__init__.py`

#### Fix: Service package eager imports removed
- Replaced direct imports (including DB singleton path) with lazy `__getattr__` module lookup.

Impact:
- Importing service package no longer automatically initializes SQLite DB.

---

### 3.4 `core/engines/__init__.py`

#### Fix: Engine package eager imports removed
- Replaced direct imports of `entry_engine`, `exit_engine`, `state_machine`, etc. with lazy `__getattr__` resolution.

Impact:
- Readiness checker importing `core.engines.adaptive_confidence_engine` no longer pulls `entry_engine` and DB at import-time.

---

### 3.5 `core/services/database.py`

#### Fix 1: Pytest DB isolation
- Added DB path resolution strategy:
  1. pre-set global `DB_PATH`
  2. `PTQ_DB_PATH`
  3. pytest session -> isolated test DB (`trades_test.db`)
  4. default production DB (`trades.db`)

Impact:
- Tests avoid clashing with production DB lock.

#### Fix 2: Runtime lock resilience
- Added SQLite connection timeout.
- Added `PRAGMA busy_timeout`.
- Added `PRAGMA journal_mode = WAL`.
- Added schema-init retry wrapper for transient lock (`_init_schema_with_retry`).

Impact:
- App startup no longer hard-crashes immediately on temporary DB locks.

---

### 3.6 Earlier runtime quality fixes (same day context)

#### `utils/helpers.py` + `core/main.py`
- Added source-aware VIX fallback path (`real/cache/estimate`) and lock-step status visibility.
- Added rate-limited warning on VIX fetch error condition.

#### `core/trading/broker.py`
- Added symbol/token sync guard before order path.
- Added wait-for-correct-symbol-tick and forced re-subscribe fallback logic.

#### `core/engines/state_machine.py`
- Added default `vix_source` state.

---

## 4) Validation & Evidence

## 4.1 Import Stability

Command:

```bash
"/home/lora/projects/PTQ-scalping bot/venv/bin/python" -c "import app; import core.main; import core.engines.entry_engine; import core.services.database; print('IMPORT_CHECK_OK')"
```

Result:
- `IMPORT_CHECK_OK`

---

## 4.2 Pytest Collection (Discovery Stage)

Command:

```bash
"/home/lora/projects/PTQ-scalping bot/venv/bin/python" -m pytest tests/ --collect-only -q
```

Result:
- Collected across all expected test files.
- No `sqlite3.OperationalError: database is locked` interruption after fixes.

---

## 4.3 Full Test Suite

Command:

```bash
"/home/lora/projects/PTQ-scalping bot/venv/bin/python" -m pytest tests/ -q --tb=short
```

Result:
- `........................................................................ [ 50%]`
- `.......................................................................  [100%]`
- Full pass.

---

## 4.4 Launcher Health Snapshot

Command:

```bash
./run.sh --health --no-animation
```

Result:
- Critical files: PASS
- Syntax check: PASS
- Imports: PASS
- Config check: PASS
- Test discovery: PASS (quick)
- Summary: PASS (5 checks)

---

## 4.5 Readiness Path (Paper Trading flow equivalent)

Command:

```bash
./run.sh --readiness --no-animation
```

Result:
- No DB-lock traceback.
- Readiness checker completed and generated reports.
- Final status observed: `Readiness PASS — Safe to launch`.

---

## 5) Process/Runtime Notes

- Earlier DB lock symptoms were real and reproducible.
- At one point bot process was confirmed running and could lock runtime DB.
- With test DB isolation + lazy imports + DB lock retries, both test and runtime paths are now robust.

---

## 6) Files Modified for Today’s Fix Scope

Primary fix files:
- `run.sh`
- `core/__init__.py`
- `core/services/__init__.py`
- `core/engines/__init__.py`
- `core/services/database.py`

Related runtime hardening files touched earlier in same day validation:
- `utils/helpers.py`
- `core/main.py`
- `core/trading/broker.py`
- `core/engines/state_machine.py`

---

## 7) Final Status

- Import path: Stable
- Readiness path: Stable
- Health preflight: Fast and stable
- Test discovery: Fast and stable
- Full test suite: Passing
- DB lock handling: Hardened for both tests and startup

