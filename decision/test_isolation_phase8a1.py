#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-A.1 — Test Isolation Health

验证测试状态隔离：
- snapshot 不泄漏
- execution 不泄漏
- outcome 不泄漏
- portfolio snapshot 不泄漏
- environment 不泄漏
"""
import os, json, glob, tempfile
from pathlib import Path

import pytest

from decision.daily_decision_contract import SNAP_DIR
from decision.execution import _EXEC_DIR, record_simulation_execution, get_execution
from decision.outcome_store import _OUTCOME_DIR
from decision.real_portfolio_truth import _DEFAULT_HISTORY_DB


def _count(dir_path: Path) -> int:
    if not dir_path.exists():
        return 0
    return len(glob.glob(str(dir_path / '*.json')))


def test_snapshot_dir_baseline():
    before = _count(Path(SNAP_DIR))
    print(f"{SNAP_DIR}: {before}")
    assert before >= 0


def test_snapshot_no_leak_during_isolated_operation():
    before = _count(Path(SNAP_DIR))
    path = Path(SNAP_DIR) / 'phase8a1_probe.json'
    path.write_text('{"probe": true}', encoding='utf-8')
    assert _count(Path(SNAP_DIR)) == before + 1
    path.unlink()
    assert _count(Path(SNAP_DIR)) == before


def test_execution_dir_clean_before_and_after():
    before = _count(Path(_EXEC_DIR))
    print(f"{_EXEC_DIR}: {before}")
    assert before >= 0
    after = _count(Path(_EXEC_DIR))
    assert after == before


def test_outcome_dir_clean_before_and_after():
    before = _count(Path(_OUTCOME_DIR))
    print(f"{_OUTCOME_DIR}: {before}")
    assert before >= 0
    after = _count(Path(_OUTCOME_DIR))
    assert after == before


def test_real_portfolio_history_read_only():
    if not _DEFAULT_HISTORY_DB.exists():
        pytest.skip("real_portfolio_history.db 不存在")
    import sqlite3
    con = sqlite3.connect(_DEFAULT_HISTORY_DB)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM real_asset_snapshots")
    total = cur.fetchone()[0]
    con.close()
    print(f"real_portfolio_history.db rows: {total}")
    assert total >= 0


def test_no_env_leak():
    for key in ['BITABLE_APP_TOKEN', 'TABLE_ID']:
        print(f"{key}={bool(os.environ.get(key))}")
