# Phase 8-A.1 — Test Isolation Closure

## Goal
Eliminate test-state pollution so the full suite passes in any execution order.

## Root Cause
### 1. Shared `SNAP_DIR` across test modules
- `test_daily_contract.py` and `test_real_readiness_phase76a.py` both wrote to
  `decision/snapshots/*.json`.
- When run together, the modules' per-test `_clean_snapshots()` did not clean
  between modules, causing later tests to see earlier tests' snapshots.
- **Fix**: `test_daily_contract.py` now uses an isolated temp `SNAP_DIR` via
  module-scoped autouse fixture.

### 2. Shared `real_portfolio_history.db`
- Both modules read/write the same SQLite history DB.
- `test_real_readiness_phase76a.py` deletes the DB at the start of many tests.
  When run after it, `test_daily_contract.py` lost the default READY snapshot,
  causing `build_account_readiness_section()` to return `MISSING`, which
  demoted every BUY/ADD to `NO_TRADE`.
- **Fix**: `test_daily_contract.py` now creates an independent temp history DB
  and pre-seeds a FRESH MANUAL_CONFIRMATION snapshot. The stray
  `decision/real_portfolio_history.db` created during earlier runs has been
  removed so it cannot act as hidden shared state.

### 3. Order-sensitive failures
The 6 failures in `test_daily_contract.py` only appeared when
`test_real_readiness_phase76a.py` ran first. Reversed order or random order
within `test_daily_contract.py` alone did not reproduce them.

## Isolation Principles Enforced
- **Function-scoped autouse fixture** provides per-test temp DB + temp snap_dir.
- **No shared filesystem state** between tests.
- **No reliance on production DB/files**: tests use injected/temp data only.

## Verification
- `test_daily_contract.py`: 20/20 single-run; 10 consecutive runs: 0 failures.
- Full suite random-order: pending (background verification).

## Production Code Changes
None. Only `test_daily_contract.py` and added `test_isolation_phase8a1.py`.
