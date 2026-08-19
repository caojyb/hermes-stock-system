"""
Phase 7.3-A：market.db Point-in-Time Replay 能力审计测试
覆盖：
1. market.db inventory
2. PIT field classification
3. universe coverage
4. availability semantics
5. current-value leak detection
6. indicators history gap
7. stocks history gap
8. financial disclosure date
9. price semantics
10. portfolio replay limitation
11. source separation design
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def _conn():
    return sqlite3.connect(str(DB))


def test_market_db_exists():
    assert DB.exists(), f'market.db not found at {DB}'


def test_market_db_size_and_tables():
    con = _conn()
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    assert len(tables) >= 15
    assert 'klines' in tables
    assert 'indicators' in tables
    assert 'stocks' in tables
    assert 'financial_data' in tables
    con.close()


def test_klines_full_history():
    con = _conn()
    cur = con.cursor()
    r = cur.execute('SELECT COUNT(*), MIN(date), MAX(date), COUNT(DISTINCT code) FROM klines').fetchone()
    con.close()
    # 14.6M+ rows, 1991+, 6376+ codes
    assert r[0] > 10_000_000
    assert r[1] <= '2000-01-01'
    assert r[2] >= '2026-01-01'
    assert r[3] >= 5000


def test_indicators_only_current_snapshot():
    con = _conn()
    cur = con.cursor()
    r = cur.execute('SELECT COUNT(DISTINCT code), COUNT(*) FROM indicators').fetchone()
    con.close()
    # 每个 code 只有 1 行，说明是当前快照，非时间序列
    assert r[0] == r[1], f'indicators 应该是当前快照: {r}'
    assert r[0] >= 5000


def test_stocks_only_current_snapshot():
    con = _conn()
    cur = con.cursor()
    r = cur.execute('SELECT COUNT(*), MIN(updated_at), MAX(updated_at) FROM stocks').fetchone()
    con.close()
    # 所有行同时更新，说明是快照
    assert r[1] == r[2], f'stocks 应该是同时更新的快照: {r}'


def test_financial_data_missing_announcement_date():
    con = _conn()
    cols = [r[1] for r in con.execute('PRAGMA table_info(financial_data)').fetchall()]
    con.close()
    assert 'report_date' in cols
    assert 'announcement_date' not in cols
    assert 'available_date' not in cols


def test_pe_pb_coverage_short():
    con = _conn()
    r = con.execute('SELECT MIN(fetch_date), MAX(fetch_date), COUNT(*) FROM pe_pb_data').fetchone()
    con.close()
    assert r[2] > 0
    # coverage < 6 months
    from datetime import datetime
    dmin = datetime.fromisoformat(r[0])
    dmax = datetime.fromisoformat(r[1])
    assert (dmax - dmin).days < 180


def test_main_fund_flow_coverage_short():
    con = _conn()
    r = con.execute('SELECT MIN(date), MAX(date), COUNT(DISTINCT code) FROM main_fund_flow').fetchone()
    con.close()
    assert r[2] < 500


def test_north_flow_empty():
    con = _conn()
    r = con.execute('SELECT COUNT(*) FROM north_flow_data').fetchone()
    con.close()
    assert r[0] == 0


def test_chip_data_recent_only():
    con = _conn()
    r = con.execute('SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT code) FROM chip_data').fetchone()
    con.close()
    from datetime import datetime
    dmax = datetime.fromisoformat(r[1])
    today = datetime.now().date()
    assert (today - dmax.date()).days < 30


def test_stocks_universe_incomplete_vs_klines():
    con = _conn()
    klines_codes = {r[0] for r in con.execute('SELECT DISTINCT code FROM klines').fetchall()}
    stock_codes = {r[0] for r in con.execute('SELECT code FROM stocks').fetchall()}
    con.close()
    missing = klines_codes - stock_codes
    # 大量 klines codes 不在 stocks 表中
    assert len(missing) > 100


def test_portfolio_replay_limitation():
    """历史 Portfolio Context 无法重建。"""
    con = _conn()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    con.close()
    # 没有历史账户/持仓/现金表
    assert 'account_snapshots' not in tables
    assert 'portfolio_history' not in tables
    assert 'position_history' not in tables


def test_no_event_or_announcement_table():
    con = _conn()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    con.close()
    assert 'events' not in tables
    assert 'announcements' not in tables
    assert 'news' not in tables


def test_meta_contains_refresh_timestamps():
    con = _conn()
    meta = {r[0]: r[1] for r in con.execute('SELECT key, value FROM meta').fetchall()}
    con.close()
    assert 'last_full_refresh' in meta
    assert 'last_incremental_update' in meta


def test_klines_no_adjusted_price():
    con = _conn()
    cols = [r[1] for r in con.execute('PRAGMA table_info(klines)').fetchall()]
    con.close()
    for c in ['adj_open', 'adj_close', 'adj_high', 'adj_low', 'split_ratio', 'dividend']:
        assert c not in cols, f'klines 不应有复权字段 {c}'


def test_indicators_updated_at_future_leak():
    """indicators.updated_at 是最新的，回放历史时会泄露未来。"""
    con = _conn()
    r = con.execute('SELECT MAX(updated_at) FROM indicators').fetchone()
    con.close()
    from datetime import datetime
    updated = datetime.fromisoformat(r[0])
    now = datetime.now()
    # updated_at 应该在最近 24 小时内
    assert (now - updated).total_seconds() < 86400


def test_double_up_scores_coverage():
    con = _conn()
    r = con.execute('SELECT MIN(scan_date), MAX(scan_date), COUNT(DISTINCT code) FROM double_up_scores').fetchone()
    con.close()
    from datetime import datetime
    dmin = datetime.fromisoformat(r[0])
    dmax = datetime.fromisoformat(r[1])
    assert (dmax - dmin).days < 120  # 约 3 个月


def test_decision_timestamp_is_runtime():
    """DecisionEngine 使用 datetime.now()，不是 as_of_time。"""
    import re
    src = Path('decision/engine.py').read_text()
    assert 'datetime.now' in src or 'datetime.now(' in src
    # 但不应硬编码 date.today()
    assert 'date.today' not in src


def test_source_separation_design():
    """新增 HISTORICAL_REPLAY 分类的设计存在（在文档中）。"""
    doc = Path('docs/architecture/MARKET_DB_PIT_REPLAY_AUDIT.md').read_text()
    assert 'HISTORICAL_REPLAY' in doc
    assert 'PRODUCTION' in doc
    assert 'Replay A/B/C' in doc


def test_market_db_inventory_documented():
    doc = Path('docs/architecture/MARKET_DB_PIT_REPLAY_AUDIT.md').read_text()
    # 审计文档中必须包含关键表清单
    assert 'klines' in doc
    assert 'indicators' in doc
    assert 'stocks' in doc
    assert 'financial_data' in doc
    assert '18,593,104' in doc  # klines row count
    assert '5,187' in doc       # indicators/stocks rows


def test_pit_safety_matrix_documented():
    doc = Path('docs/architecture/MARKET_DB_PIT_REPLAY_AUDIT.md').read_text()
    assert 'Point-in-Time Safety Matrix' in doc
    assert 'SAFE' in doc
    assert 'BLOCKED' in doc
    assert 'LOOKAHEAD_RISK' in doc
    assert 'SURVIVORSHIP_RISK' in doc


def test_replay_gap_matrix_documented():
    doc = Path('docs/architecture/MARKET_DB_PIT_REPLAY_AUDIT.md').read_text()
    assert 'Historical Replay Gap Matrix' in doc
    assert 'Replay A' in doc
    assert 'Replay B' in doc
    assert 'Replay C' in doc
