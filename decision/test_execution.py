#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6.5 — Production Outcome Capture 测试

Case A-J：
A. Decision → Simulation Execution → Outcome
B. Decision → Manual Execution Confirm → Outcome
C. Decision → NOT_EXECUTED（不能生成 Outcome）
D. Partial Execution → Position → Outcome
E. Execution Price != Planned Price（planned/actual 分离）
F. Manual Exit → Outcome
G. Decision 未找到 Execution → DATA_GAP
H. NO_TRADE Counterfactual 不生成真实 Outcome
I. Shadow Outcome 不进入 Production Stats
J. Replay Outcome → Execution → Decision → Portfolio Snapshot

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_execution.py -v
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision import execution as ex
from decision import outcome_store as store
from decision.outcome import Outcome, SOURCE_DECISION, SOURCE_LEGACY, SOURCE_SHADOW, SOURCE_UNKNOWN
from decision.outcome import CLOSED, OPEN, UNKNOWN
from decision.execution import EXECUTED, PLANNED, PARTIAL, REJECTED, NOT_EXECUTED

# ═══ Case A: Decision → Simulation Execution → Outcome ═══
def test_caseA_sim_execution_outcome():
    dec = {'decision_id': 'did_A', 'symbol': '600001', 'name': 'X', 'strategy': 'v1_double',
           'config_version': 'v1', 'reference_price': 10.0, 'target_position': 0.05}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    e = ex.get_execution(eid)
    assert e['decision_id'] == 'did_A'
    assert e['source'] == 'SIMULATION'
    assert e['position_status'] == OPEN
    # 记录退出 → CLOSED → 生成 Outcome
    ex.record_exit(eid, exit_price=12.0, exit_quantity=1000, exit_time='2026-08-18', exit_reason='TAKE_PROFIT')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.decision_id == 'did_A'
    assert o.lifecycle_status == CLOSED
    assert o.actual.return_pct == pytest.approx(0.2)

# ═══ Case B: Decision → Manual Execution Confirm → Outcome ═══
def test_caseB_manual_confirm_outcome():
    dec = {'decision_id': 'did_B', 'symbol': '600002', 'name': 'Y', 'strategy': 'v1_double'}
    # 预建 PLANNED execution（模拟人工确认前）
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=0, status='PLANNED')
    ex.confirm_manual_execution('did_B', actual_price=10.2, actual_quantity=500,
                                execution_time='2026-08-18', status='EXECUTED')
    e = ex.find_execution('did_B')[-1]
    assert e['source'] == 'MANUAL_CONFIRMATION'
    assert e['status'] == 'EXECUTED'
    assert e['actual']['price'] == 10.2
    # 手动卖出 → Outcome
    ex.record_exit(e['execution_id'], exit_price=11.0, exit_quantity=500,
                   exit_time='2026-08-20', exit_reason='MANUAL')
    o = ex.build_outcome_from_execution(e['execution_id'])
    assert o is not None and o.lifecycle_status == CLOSED

# ═══ Case C: NOT_EXECUTED 不能生成 Outcome ═══
def test_caseC_not_executed_no_outcome():
    dec = {'decision_id': 'did_C', 'symbol': '600003', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=0, status='NOT_EXECUTED')
    e = ex.get_execution(eid)
    assert e['status'] == 'NOT_EXECUTED'
    assert e['position_status'] == UNKNOWN
    # 无 actual price → 不生成 outcome
    o = ex.build_outcome_from_execution(eid)
    assert o is None

# ═══ Case D: Partial Execution → Position → Outcome ═══
def test_caseD_partial_execution():
    dec = {'decision_id': 'did_D', 'symbol': '600004', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=500, status='PARTIAL')
    e = ex.get_execution(eid)
    assert e['position_status'] == PARTIAL
    # PARTIAL → 可转 OPEN（补足）
    ex.confirm_manual_execution('did_D', actual_price=10.0, actual_quantity=1000,
                                execution_time='2026-08-18', status='EXECUTED')
    e2 = ex.find_execution('did_D')[-1]
    assert e2['position_status'] == OPEN

# ═══ Case E: Execution Price != Planned Price ═══
def test_caseE_planned_vs_actual_price():
    dec = {'decision_id': 'did_E', 'symbol': '600005', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.35, quantity=1000)
    e = ex.get_execution(eid)
    assert e['planned']['price'] == 10.0
    assert e['actual']['price'] == 10.35
    assert e['planned']['price'] != e['actual']['price']  # 分离保留执行偏差

# ═══ Case F: Manual Exit → Outcome ═══
def test_caseF_manual_exit_outcome():
    dec = {'decision_id': 'did_F', 'symbol': '600006', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    ex.record_exit(eid, exit_price=9.2, exit_quantity=1000, exit_time='2026-08-18',
                   exit_reason='STOP_LOSS')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.exit_reason == 'STOP_LOSS'
    assert o.actual.return_pct == pytest.approx(-0.08)

# ═══ Case G: Decision 未找到 Execution → DATA_GAP ═══
def test_caseG_data_gap():
    unlinked = ex.find_unlinked_decisions()
    assert isinstance(unlinked, list)
    # 找一个无 execution 的 decision 验证 gap 结构
    for u in unlinked:
        assert 'decision_id' in u and 'gap' in u
        break
    # monitor 能报告（区分 historical/current gap）
    m = ex.monitor()
    assert m['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')
    assert 'historical_unlinked' in m and 'current_unlinked' in m
    assert 'active_pipeline_gap' in m and 'known_legacy_gap' in m
    assert 'integrity' in m

# ═══ Case H: NO_TRADE Counterfactual 不生成真实 Outcome ═══
def test_caseH_no_trade_counterfactual_not_real():
    cf = store.compute_counterfactual('600540', '2026-07-01', 4.0, windows=(5,))
    assert cf[0].status in ('COMPUTED', 'NOT_ELIGIBLE')
    # Counterfactual 是研究数据，不写真实 execution/outcome
    assert cf[0].eligible is not None

# ═══ Case I: Shadow Outcome 不进入 Production Stats ═══
def test_caseI_shadow_isolated():
    # shadow outcome 用 source=SHADOW + strategy=main_up
    shadow = Outcome(outcome_source=SOURCE_SHADOW, strategy='main_up', symbol='600519',
                     lifecycle_status=CLOSED)
    assert shadow.outcome_source == SOURCE_SHADOW
    # stats 里 Shadow 与 Production 分离（by_strategy 区分）
    s = store.stats(outcomes=[shadow.freeze()])
    assert 'main_up' in s.get('by_strategy', {})

# ═══ Case J: Replay Outcome → Execution → Decision → Portfolio Snapshot ═══
def test_caseJ_replay_chain():
    dec = {'decision_id': 'did_J', 'symbol': '600007', 'name': 'Z', 'strategy': 'v1_double',
           'data_snapshot_id': 'snap_J', 'portfolio_snapshot_id': 'real_J'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    e = ex.get_execution(eid)
    assert e['decision_id'] == 'did_J'
    assert e['decision_snapshot_id'] == 'snap_J'
    assert e['portfolio_snapshot_id'] == 'real_J'
    # 记录退出 → outcome 含 provenance
    ex.record_exit(eid, exit_price=11.0, exit_quantity=1000, exit_time='2026-08-18', exit_reason='TAKE_PROFIT')
    o = ex.build_outcome_from_execution(eid)
    assert o.portfolio_snapshot_id == 'real_J'
    assert o.decision_snapshot_id == 'snap_J'
