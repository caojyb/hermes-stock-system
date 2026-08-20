import os
import sys
import tempfile
import sqlite3
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import decision.real_portfolio_truth as real_portfolio_truth
import decision.snapshot as snapshot_mod
from decision import daily_decision_contract as ddc


def _init_history_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS real_asset_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            as_of_time TEXT,
            source TEXT,
            data_quality TEXT,
            cash REAL,
            holdings_value REAL,
            total_asset REAL,
            position_count INTEGER,
            drawdown REAL,
            drawdown_status TEXT,
            peak_asset REAL,
            peak_asset_date TEXT,
            provenance_json TEXT,
            created_at TEXT,
            freshness TEXT
        )
    ''')
    con.commit()
    con.close()


@pytest.fixture()
def isolate_history_db(tmp_path, monkeypatch):
    db = tmp_path / 'real_portfolio_history.db'
    _init_history_db(db)
    monkeypatch.setattr(real_portfolio_truth, '_DEFAULT_HISTORY_DB', db)
    yield db


@pytest.fixture()
def isolate_snapshots(tmp_path, monkeypatch):
    snap_dir = tmp_path / 'snapshots'
    snap_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ddc, 'SNAP_DIR', str(snap_dir))
    monkeypatch.setattr(snapshot_mod, 'SNAP_DIR', str(snap_dir))
    yield snap_dir


FIXED_DATE = '2026-08-20'


@pytest.fixture()
def fix_today(monkeypatch):
    """将 real_portfolio_truth._today_iso 固定为 FIXED_DATE，避免测试依赖真实日期。"""
    monkeypatch.setattr(real_portfolio_truth, '_today_iso', lambda: FIXED_DATE)
    yield FIXED_DATE
