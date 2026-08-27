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


# ── Phase 9-B.2：freshness 测试的确定性 market_cache 快照固定 ──
# 生产 _check_B_data_freshness 查询 LIVE market_cache.db 的 klines MAX(date)。
# 原测试硬断言 market_cache_latest=='2026-08-26'，但 cron 持续刷新使该值随真实日期漂移，
# 导致测试与实时 DB 快照耦合（测试日期污染），非 production bug。
# 此 fixture 构建一个确定性临时 market_cache DB（klines MAX(date)=FIXED_MARKET_DATE），
# monkeypatch 到 gate.KNOWN_PRODUCTION_DBS['market_cache']，保留真实 SELECT 查询路径，
# 测试结束后自动 restore（function-scoped，无状态泄漏）。
FIXED_MARKET_DATE = '2026-08-26'


@pytest.fixture()
def fresh_market_cache(tmp_path, monkeypatch):
    """固定 market_cache 的 klines MAX(date)=FIXED_MARKET_DATE，使 freshness gate 确定性。

    - 不修改 production 代码（_check_B_data_freshness 仍走真实 SELECT MAX(date) FROM klines）
    - function-scoped：每测试独立临时 DB，结束自动 restore
    - 支持“固定快照日期”语义（§四）
    """
    import decision.validation_integrity_gate as gate
    db = tmp_path / 'market_cache.db'
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE klines (date TEXT)')
    con.execute('INSERT INTO klines (date) VALUES (?)', (FIXED_MARKET_DATE,))
    con.commit()
    con.close()
    monkeypatch.setitem(gate.KNOWN_PRODUCTION_DBS, 'market_cache', str(db))
    yield str(db)
