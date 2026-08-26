#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Holdings H2 Production Wiring Tests（Phase 8-H2）

覆盖：
1. Bitable正常读取 -> Holdings READY
2. Bitable为空 -> Holdings EMPTY
3. Bitable失败 -> Holdings MISSING
4. Holding READY + Account Missing
5. BUY阻断
6. SELL允许
7. Simulation不污染Real
8. 字段漂移检测
9. Cost Quality Warning
10. Observation DEGRADED
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys_path = Path('/home/caojy/.hermes/scripts/cron')
import sys
sys.path.insert(0, str(sys_path))

from decision.real_portfolio_truth import (
    build_real_snapshot,
    get_holdings_status,
    get_account_status,
    get_portfolio_risk_status,
    get_real_portfolio_metadata,
    HoldingsStatus,
    AccountStatus,
    PortfolioRiskStatus,
    REAL_HOLDINGS_SOURCE,
    REAL_HOLDINGS_TABLE,
    BITABLE_FIELD_INDEX,
    _validate_field_order,
    run_daily_snapshot,
    get_account_readiness,
)
from decision.real_portfolio_quality import check_portfolio_quality
from decision.observation import build_daily_observation_report, _derive_holdings_health, _derive_account_health
from decision.daily_decision_contract import (
    build_real_portfolio_section,
    build_account_readiness_section,
    classify_actions,
)
from decision.contract import BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE


# ── fixtures ──

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / 'real_history.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)
    return db


@pytest.fixture
def fixed_today(monkeypatch):
    today = '2026-08-22'
    monkeypatch.setattr('decision.real_portfolio_truth._today_iso', lambda: today)
    monkeypatch.setattr('decision.real_portfolio_truth._now_iso', lambda: datetime.now(timezone.utc).isoformat())
    return today


def _fake_bitable(monkeypatch, holdings):
    # J0-H: 当日缓存存在时必须先失效，否则 mock 的 reader 不会被调用
    from decision import real_portfolio_truth as _rpt
    _rpt.reset_daily_real_holdings_cache()
    monkeypatch.setattr('decision.real_portfolio_truth._read_bitable_holdings', lambda: holdings)


@pytest.fixture(autouse=True)
def _reset_daily_cache_after_test():
    """J0-H 缓存跨测试隔离：每个测试结束后清空当日缓存"""
    yield
    from decision import real_portfolio_truth as _rpt
    _rpt.reset_daily_real_holdings_cache()


# ── 1. Bitable正常读取 ──
def test_bitable_normal_read(monkeypatch):
    _fake_bitable(monkeypatch, [
        {'code': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0, 'sector': '软件'}
    ])
    snap = build_real_snapshot()
    assert snap.get('ok') is True
    assert snap.get('data_quality') == 'PARTIAL'
    assert len(snap.get('holdings', [])) == 1
    assert snap['holdings'][0]['symbol'] == '600588'


# ── 2. Bitable为空 ──
def test_bitable_empty(monkeypatch):
    _fake_bitable(monkeypatch, [])
    snap = build_real_snapshot()
    assert snap.get('ok') is True
    assert snap.get('data_quality') == 'MISSING'
    assert len(snap.get('holdings', [])) == 0
    hs = get_holdings_status(snap)
    assert hs['status'] == HoldingsStatus.EMPTY


# ── 3. Bitable失败 ──
def test_bitable_failure(monkeypatch):
    def boom():
        raise RuntimeError('lark-cli failed')
    monkeypatch.setattr('decision.real_portfolio_truth._read_bitable_holdings', boom)
    snap = build_real_snapshot()
    assert snap.get('ok') is False
    assert snap.get('data_quality') == 'MISSING'
    hs = get_holdings_status(snap)
    assert hs['status'] == HoldingsStatus.MISSING


# ── 4. Holding READY + Account Missing ──
def test_holding_ready_account_missing(monkeypatch, tmp_db, fixed_today):
    _fake_bitable(monkeypatch, [
        {'code': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0, 'sector': '软件'}
    ])
    snap = build_real_snapshot()
    hs = get_holdings_status(snap)
    acct = get_account_status()
    assert hs['status'] == HoldingsStatus.READY
    assert acct['status'] == AccountStatus.MISSING
    assert hs['status'] != HoldingsStatus.MISSING


# ── 5. BUY阻断 ──
def test_buy_blocked_when_account_missing(tmp_path, monkeypatch):
    db = tmp_path / 'real_history.db'
    monkeypatch.setattr('decision.real_portfolio_truth._DEFAULT_HISTORY_DB', db)
    readiness = build_account_readiness_section()
    snapshots = [{
        'decision_id': 'D_BUY1',
        'symbol': '600588',
        'name': '用友网络',
        'action': BUY,
        'reason_codes': ['TEST'],
        'entry': {'entry_price': 12.0, 'target_position': 50000},
        'portfolio': {},
        'risk': {},
        'explanation': '',
    }]
    actions = classify_actions(snapshots, sim_trades=[], readiness=readiness)
    assert actions.get('BUY', []) == []
    assert actions.get('NO_TRADE', []) != []
    assert actions['NO_TRADE'][0]['sizing_status'] == 'BLOCKED'


# ── 6. SELL允许 ──
def test_sell_allowed_when_account_missing(monkeypatch, fixed_today):
    _fake_bitable(monkeypatch, [
        {'code': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0, 'sector': '软件'}
    ])
    readiness = build_account_readiness_section()
    snapshots = [{
        'decision_id': 'D_SELL1',
        'symbol': '600588',
        'name': '用友网络',
        'action': SELL,
        'reason_codes': ['TEST'],
        'entry': {'entry_price': 12.0, 'target_position': 0},
        'portfolio': {},
        'risk': {},
        'explanation': '',
    }]
    actions = classify_actions(snapshots, sim_trades=[], readiness=readiness)
    assert SELL in actions
    assert actions[SELL][0]['action'] == SELL
    assert actions[SELL][0]['sizing_status'] == 'PARTIAL'


# ── 7. Simulation不污染Real ──
def test_simulation_isolation(monkeypatch, tmp_db, fixed_today):
    sim_db = tmp_db.parent / 'sim.db'
    conn = sqlite3.connect(sim_db)
    conn.execute('CREATE TABLE IF NOT EXISTS portfolio_snapshots (date TEXT, total_value REAL, cash REAL, holdings_value REAL)')
    conn.execute('INSERT INTO portfolio_snapshots VALUES (?,?,?,?)', ('2026-08-22', 1500000, 500000, 1000000))
    conn.commit()
    conn.close()

    _fake_bitable(monkeypatch, [
        {'code': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0, 'sector': '软件'}
    ])
    snap = build_real_snapshot()
    assert snap.get('source') == 'bitable'
    serialized = json.dumps(snap)
    assert 'simulation' not in serialized.lower()


# ── 8. 字段漂移检测 ──
def test_field_drift_detection():
    records = [[f'f{i}' for i in range(9)]]  # 9 fields, expected 8
    with pytest.raises(RuntimeError) as exc:
        _validate_field_order(records)
    assert 'BITABLE_SCHEMA_WARNING' in str(exc.value)


# ── 9. Cost Quality Warning ──
def test_cost_quality_warning():
    holdings = [
        {'symbol': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 1000.0, 'current_price': 10.0, 'sector': '软件'}
    ]
    q = check_portfolio_quality(holdings)
    assert q['overall'] == 'WARNING'
    assert q['warning_count'] >= 1
    assert any(c['field'] == 'avg_cost' and c['reason'] == 'OUTLIER' for c in q['flags'])


# ── 10. Observation DEGRADED ──
def test_observation_degraded_account_missing(monkeypatch, tmp_db, fixed_today):
    fake_snap = {
        'ok': True, 'holdings': [{'code': '600588', 'name': '用友网络', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0, 'sector': '软件'}],
        'timestamp': '2026-08-22T10:00:00+00:00', 'as_of_time': '2026-08-22', 'source': 'bitable', 'data_quality': 'PARTIAL',
        'freshness': 'UNKNOWN', 'portfolio': {'holdings_value': 12000.0, 'cash': None, 'total_asset': None, 'position_count': 1, 'drawdown': None, 'drawdown_status': 'UNKNOWN', 'peak_asset': None, 'peak_asset_date': None, 'sector_exposure': {'软件': 1}, 'exposure': 0.0},
        'provenance': {'source': 'bitable'},
    }
    monkeypatch.setattr('decision.real_portfolio_truth.build_real_snapshot', lambda: fake_snap)
    monkeypatch.setattr('decision.observation.monitor', lambda: {'active_pipeline_gap': 0})
    monkeypatch.setattr('decision.observation._count_decision_actions', lambda: {k: 0 for k in ['BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE']})
    monkeypatch.setattr('decision.observation._count_execution_statuses', lambda: {})
    monkeypatch.setattr('decision.observation._count_position_statuses', lambda: {})
    monkeypatch.setattr('decision.observation._count_outcome_lifecycle', lambda: {})
    monkeypatch.setattr('decision.observation._count_data_gaps', lambda: {k: 0 for k in ['decision_without_execution', 'buy_without_execution', 'execution_without_position', 'exit_without_decision', 'closed_without_outcome', 'outcome_without_decision', 'missing_portfolio_snapshot', 'missing_actual_execution', 'missing_exit_regime', 'missing_mae_mfe']})
    monkeypatch.setattr('decision.observation._count_integrity', lambda: {'integrity_score': 1.0})
    monkeypatch.setattr('decision.observation._reconcile_counts', lambda *a, **k: {'anomalies': [], 'reconciliation': {}})

    report = build_daily_observation_report()
    assert report['health'] == 'DEGRADED'
    assert report['holdings_health'] == 'HEALTHY'
    assert report['account_health'] == 'DEGRADED'


# ── 11. Source metadata固化 ──
def test_source_metadata():
    snap = {
        'ok': True,
        'holdings': [{'code': '600588', 'quantity': 1000, 'avg_cost': 10.5, 'current_price': 12.0}],
        'timestamp': '2026-08-22T10:00:00+00:00',
        'data_quality': 'PARTIAL',
    }
    meta = get_real_portfolio_metadata(snap)
    assert meta['source'] == REAL_HOLDINGS_SOURCE
    assert REAL_HOLDINGS_TABLE in meta['source_table']
    assert meta['holding_count'] == 1
    assert meta['holdings_status'] == HoldingsStatus.READY


# ── 12. HoldingsStatus 三态 ──
def test_holdings_status_three_states(monkeypatch):
    _fake_bitable(monkeypatch, [])
    snap = build_real_snapshot()
    hs = get_holdings_status(snap)
    assert hs['status'] == HoldingsStatus.EMPTY

    # 直接测试 MISSING
    bad_snap = {'ok': False, 'error': 'fail'}
    hs2 = get_holdings_status(bad_snap)
    assert hs2['status'] == HoldingsStatus.MISSING
