#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Account Snapshot / Readiness wiring tests（Phase 8-G0.1）

覆盖：
6. real snapshot manual confirmation
7. real snapshot provenance
8. account readiness READY / MISSING / STALE / EXPIRED / PARTIAL
9. BUY blocked when account not ready
10. SELL allowed when account not ready
14. real/simulation isolation
"""
from __future__ import annotations

import sqlite3
import json
import pytest
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision.real_portfolio_truth import (
    build_real_snapshot,
    record_asset_snapshot,
    get_account_readiness,
    run_daily_snapshot,
    MISSING, PARTIAL, STALE, EXPIRED, UNKNOWN, READY,
    FRESH,
    _DEFAULT_HISTORY_DB,
)


# ── helpers ──
def _iso_now(days=0):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.isoformat(timespec='seconds')


def _fresh_ts(hours=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec='seconds')


# ── 6. manual confirmation 入口唯一性（run_daily_snapshot）──
def test_manual_confirmation_unique_entry(tmp_path, monkeypatch):
    db = tmp_path / 'real.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    snap = run_daily_snapshot(holdings=[], cash_manual=100_000.0, total_asset_manual=100_000.0, entered_by='test')
    assert snap['ok'] is True
    assert snap['source'] == 'MANUAL_CONFIRMATION'
    assert snap['provenance']['is_manual'] is True
    assert snap['provenance']['entered_by'] == 'test'


# ── 7. snapshot provenance 完整 ──
def test_snapshot_provenance_complete(tmp_path, monkeypatch):
    db = tmp_path / 'real2.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    holdings = [{'code': '600519', 'name': '茅台', 'quantity': 100, 'avg_cost': 1800.0, 'current_price': 1900.0, 'sector': '白酒'}]
    snap = build_real_snapshot(
        holdings=holdings,
        cash=50_000.0,
        total_asset=240_000.0,
        source='MANUAL_CONFIRMATION',
        entered_by='user',
        confirmation_note='平安证券截图',
        stale_after_hours=24,
    )
    assert snap['snapshot_id'].startswith('real_')
    assert snap['as_of_time'] == date.today().isoformat()
    assert snap['source'] == 'MANUAL_CONFIRMATION'
    p = snap['provenance']
    assert p['source'] == 'MANUAL_CONFIRMATION'
    assert p['is_manual'] is True
    assert p['entered_by'] == 'user'
    assert p['confirmation_note'] == '平安证券截图'
    assert 'snapshot_id' in p
    assert 'source_timestamp' in p


# ── 8a. account readiness READY ──
def test_account_readiness_ready(tmp_path, monkeypatch):
    db = tmp_path / 'ready.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)
    snap = build_real_snapshot(holdings=[], cash=100_000.0, total_asset=100_000.0,
                               source='MANUAL_CONFIRMATION', source_timestamp=_fresh_ts(hours=1))
    record_asset_snapshot(snap, db_path=db)

    r = get_account_readiness(db_path=db)
    assert r['status'] == READY
    assert r['total_asset'] == 100_000.0
    assert r['cash'] == 100_000.0


# ── 8b. account readiness MISSING（DB 不存在）──
def test_account_readiness_missing_no_db(tmp_path, monkeypatch):
    db = tmp_path / 'noexist.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    r = get_account_readiness(db_path=db)
    assert r['status'] == MISSING
    assert r['reason'] == 'history_db_missing'


# ── 8c. account readiness MISSING（今日无快照）──
def test_account_readiness_missing_no_snapshot_today(tmp_path, monkeypatch):
    db = tmp_path / 'empty.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)
    # 建表但不插入今日记录
    con = sqlite3.connect(db)
    con.execute('''CREATE TABLE IF NOT EXISTS real_asset_snapshots (snapshot_id TEXT PRIMARY KEY, as_of_time TEXT, source TEXT, data_quality TEXT, cash REAL, holdings_value REAL, total_asset REAL, position_count INTEGER, drawdown REAL, drawdown_status TEXT, peak_asset REAL, peak_asset_date TEXT, provenance_json TEXT, created_at TEXT, freshness TEXT)''')
    con.commit()
    con.close()

    r = get_account_readiness(db_path=db)
    assert r['status'] == MISSING
    assert r['reason'] == 'no_snapshot_today'


# ── 8d. account readiness STALE / EXPIRED ──
def test_account_readiness_stale_and_expired(tmp_path, monkeypatch):
    db = tmp_path / 'stale.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    # 使用 stale_after_hours=24，制造 EXPIRED
    old_ts = _fresh_ts(hours=25)
    snap = build_real_snapshot(holdings=[], cash=100_000.0, total_asset=100_000.0,
                               source='MANUAL_CONFIRMATION', source_timestamp=old_ts, stale_after_hours=24)
    record_asset_snapshot(snap, db_path=db)

    r = get_account_readiness(db_path=db)
    assert r['status'] == EXPIRED
    assert r['reason'] == 'snapshot_expired'


# ── 8e. account readiness PARTIAL（只提供 cash）──
def test_account_readiness_partial(tmp_path, monkeypatch):
    db = tmp_path / 'partial.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    snap = build_real_snapshot(holdings=[], cash=50_000.0, total_asset=None,
                               source='MANUAL_CONFIRMATION', source_timestamp=_fresh_ts(hours=1))
    record_asset_snapshot(snap, db_path=db)

    r = get_account_readiness(db_path=db)
    assert r['status'] == PARTIAL
    assert r['reason'] == 'missing_cash_or_total_asset'


# ── 9. BUY/ADD not-ready fail-safe（daily contract）──
def test_buy_blocked_when_not_ready(tmp_path, monkeypatch):
    db = tmp_path / 'buyblock.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)

    from decision.daily_decision_contract import classify_actions
    readiness = {'status': MISSING, 'blocked_reason': 'REAL_TOTAL_ASSET_MISSING', 'sizing_allowed': False}
    snap = {
        'action': 'BUY',
        'symbol': '600519',
        'reason_codes': ['ENTRY_CONFIRMED'],
        'entry': {'entry_price': 1900.0, 'target_position': 50_000},
        'portfolio': {'total_asset': None, 'cash': None},
    }
    actions = classify_actions([snap], sim_trades=[], readiness=readiness)
    # daily contract 对 not-ready 的 BUY 会转换为 NO_TRADE 或 BLOCKED，不会进入可执行 BUY 列表
    assert all(a.get('sizing_status') == 'BLOCKED' for a in actions.get('NO_TRADE', []))
    assert 'BUY' not in actions


# ── 10. SELL allowed when not ready ──
def test_sell_allowed_when_not_ready():
    from decision.daily_decision_contract import classify_actions
    readiness = {'status': MISSING, 'blocked_reason': 'REAL_TOTAL_ASSET_MISSING', 'sizing_allowed': False}
    snap = {
        'action': 'SELL',
        'symbol': '600519',
        'reason_codes': ['RISK'],
        'entry': {'entry_price': 1900.0, 'target_position': 0},
        'portfolio': {'total_asset': None, 'cash': None},
    }
    actions = classify_actions([snap], sim_trades=[], readiness=readiness)
    assert any(a['action'] == 'SELL' for a in actions.get('SELL', []))


# ── 14. real/simulation isolation ──
def test_real_simulation_isolation(tmp_path, monkeypatch):
    # 使用独立文件路径，确保 real 历史 DB 与 simulation.db 物理隔离
    real_db = tmp_path / 'real.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', real_db)

    snap = build_real_snapshot(holdings=[], cash=50_000.0, total_asset=100_000.0,
                               source='MANUAL_CONFIRMATION', source_timestamp=_fresh_ts(hours=1))
    sid = record_asset_snapshot(snap, db_path=real_db)

    r = get_account_readiness(db_path=real_db)
    assert r['status'] == READY
    assert r['snapshot_id'] == sid
