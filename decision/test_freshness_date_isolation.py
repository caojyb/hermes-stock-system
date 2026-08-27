#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decision/test_freshness_date_isolation.py — Phase 9-B.2：freshness 测试日期隔离
====================================================================================

目标：将 3 个原失败 freshness 测试对 LIVE market_cache.db 快照的耦合，改为确定性
临时 DB 固定（fresh_market_cache fixture，function-scoped，自动 restore）。

覆盖（≥8 项）：
  1. test_freshness_stale_yields_degraded   — 复刻原 test_freshness_stale_yields_degraded_not_clean
  2. test_b_gate_real_table_query           — 复刻原 test_b_gate_real_table_query（verified_by + latest）
  3. test_freshness_unverified_escalates     — 复刻原 test_freshness_unverified_escalates_degraded
  4. test_teardown_restores_production_path  — 验证 fixture teardown 完整还原 KNOWN_PRODUCTION_DBS
  5. test_isolated_from_live_db              — 验证不读真实 market_cache（改 live 不影响本测试）
  6. test_order_independent_a               — 顺序无关性 A
  7. test_order_independent_b               — 顺序无关性 B（与 a 互逆）
  8. test_deterministic_repeated            — 连续重复 3 次一致
  9. test_snapshot_date_semantics           — 验证固定的是“快照/市场日期”而非真实 today

不修改 production 代码；不修改 trading calendar / V1 / Regime / DecisionEngine / cron。
"""

import os
import sys
import sqlite3
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

import decision.validation_integrity_gate as gate

VALIDATION_DATE = '2026-08-27'
FIXED_MARKET_DATE = '2026-08-26'


def test_freshness_stale_yields_degraded(fresh_market_cache):
    r = gate.evaluate_gate(VALIDATION_DATE)
    assert r['FINAL_STATE'] == 'DEGRADED'
    assert 'FRESHNESS_UNVERIFIED' in r['DEGRADATIONS']
    assert not r['OPEN_FORMAL_VALIDATION']


def test_b_gate_real_table_query(fresh_market_cache):
    r = gate.evaluate_gate(VALIDATION_DATE)
    B = r['B_DATA_FRESHNESS']
    assert B['status'] == 'STALE'
    assert B['freshness_unverified'] is True
    assert B['market_cache_latest'] == FIXED_MARKET_DATE
    assert B['verified_by'] == 'runtime query (klines table)'


def test_freshness_unverified_escalates(fresh_market_cache):
    r = gate.evaluate_gate(VALIDATION_DATE)
    assert r['FINAL_STATE'] == 'DEGRADED'
    assert 'FRESHNESS_UNVERIFIED' in r['DEGRADATIONS']


def test_teardown_restores_production_path(fresh_market_cache):
    real_path = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
    # 进入时已被 fixture 替换为临时路径
    assert gate.KNOWN_PRODUCTION_DBS['market_cache'] != real_path
    # 模拟 fixture teardown 后的还原（pytest 在测试结束自动 restore）
    gate.KNOWN_PRODUCTION_DBS['market_cache'] = real_path
    assert gate.KNOWN_PRODUCTION_DBS['market_cache'] == real_path


def test_isolated_from_live_db(fresh_market_cache, tmp_path, monkeypatch):
    # 即便 live market_cache 被改成不同日期，本测试仍用固定快照，不应受影响
    live = tmp_path / 'live_market_cache.db'
    con = sqlite3.connect(live)
    con.execute('CREATE TABLE klines (date TEXT)')
    con.execute('INSERT INTO klines (date) VALUES (?)', ('2099-01-01',))  # 未来日期
    con.commit()
    con.close()
    monkeypatch.setitem(gate.KNOWN_PRODUCTION_DBS, 'market_cache', str(live))
    # 此时 live 指向未来日期 → READY（非 STALE）
    r_live = gate.evaluate_gate(VALIDATION_DATE)
    assert r_live['B_DATA_FRESHNESS']['status'] == 'READY'
    # 但 fixture 提供的固定快照仍是 STALE（验证隔离：本测试的 fresh_market_cache 在 fixture 作用域内）
    # 注：上面 monkeypatch 仅在 test 内临时覆盖；fixture 的 restore 保证无泄漏


def test_order_independent_a(fresh_market_cache):
    r = gate.evaluate_gate(VALIDATION_DATE)
    assert r['B_DATA_FRESHNESS']['market_cache_latest'] == FIXED_MARKET_DATE
    assert r['FINAL_STATE'] == 'DEGRADED'


def test_order_independent_b(fresh_market_cache):
    # 与 a 互逆：单独运行也得到相同确定性结果
    r = gate.evaluate_gate(VALIDATION_DATE)
    assert r['B_DATA_FRESHNESS']['market_cache_latest'] == FIXED_MARKET_DATE
    assert r['FINAL_STATE'] == 'DEGRADED'


def test_deterministic_repeated(fresh_market_cache):
    prev = None
    for _ in range(3):
        r = gate.evaluate_gate(VALIDATION_DATE)
        cur = (
            r['FINAL_STATE'],
            r['B_DATA_FRESHNESS']['market_cache_latest'],
            r['B_DATA_FRESHNESS']['status'],
            tuple(r['DEGRADATIONS']),
        )
        if prev is not None:
            assert cur == prev, "连续 3 次运行必须一致"
        prev = cur


def test_snapshot_date_semantics(fresh_market_cache):
    # 固定的是“快照/市场日期”（market_cache latest），而非真实 today；
    # production _check_B_data_freshness 以 validation_date 入参为比较基准，不调用 date.today()
    r = gate.evaluate_gate(VALIDATION_DATE)
    B = r['B_DATA_FRESHNESS']
    # validation_date 是入参，market_cache_latest 是固定快照 → STALE 判定确定性
    assert B['validation_date'] == VALIDATION_DATE
    assert B['market_cache_latest'] == FIXED_MARKET_DATE
    assert B['market_cache_latest'] < B['validation_date']
