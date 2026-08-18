#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6.6 — Production Lifecycle Closure 测试

Case A-H：
A. BUY → OPEN → STOP_LOSS → CLOSED → Outcome
B. BUY → OPEN → TP1 → TP2 → TP3(多段) → CLOSED → Outcome(加权退出)
C. BUY → OPEN → TRAILING_STOP → CLOSED
D. BUY → OPEN → PORTFOLIO_RISK REDUCE → OPEN → 最终 SELL → CLOSED
E. BUY → NOT_EXECUTED（不产生 Outcome）
F. Real BUY → Manual Execution → Real SELL → Manual Exit → Outcome
G. Exit Decision → Exit Execution → Lifecycle Replay
H. 历史 Legacy 交易无 decision_id（保持 LEGACY）

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_lifecycle.py -v
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision import execution as ex
from decision import outcome_store as store
from decision.outcome import CLOSED, OPEN, UNKNOWN, SOURCE_LEGACY, SOURCE_DECISION
from decision.execution import EXECUTED, PLANNED, PARTIAL, NOT_EXECUTED

# ═══ Case A: BUY → STOP_LOSS → CLOSED → Outcome ═══
def test_caseA_stop_loss_lifecycle():
    dec = {'decision_id': 'lc_A', 'symbol': '600001', 'name': 'X', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    assert ex.get_execution(eid)['position_status'] == OPEN
    ex.record_exit(eid, exit_price=9.2, exit_quantity=1000, exit_time='2026-08-18', exit_reason='STOP_LOSS')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None and o.lifecycle_status == CLOSED
    assert o.exit_reason == 'STOP_LOSS'
    assert o.actual.return_pct == pytest.approx(-0.08)

# ═══ Case B: TP1/TP2/TP3 多段退出 → 加权 Outcome ═══
def test_caseB_multiple_exit_weighted():
    dec = {'decision_id': 'lc_B', 'symbol': '600002', 'strategy': 'v1_double', 'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    # 三段分批止盈：TP1 400@12, TP2 300@13, TP3 300@14
    ex.record_exit(eid, 12.0, 400, 't1', 'TAKE_PROFIT', status='PARTIAL')
    assert ex.get_execution(eid)['position_status'] == PARTIAL
    assert ex.build_outcome_from_execution(eid) is None  # 未最终 CLOSED，不生成
    ex.record_exit(eid, 13.0, 300, 't2', 'TAKE_PROFIT', status='PARTIAL')
    assert ex.build_outcome_from_execution(eid) is None
    ex.record_exit(eid, 14.0, 300, 't3', 'TAKE_PROFIT', status='CLOSED')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    # 加权退出价 = (12*400+13*300+14*300)/1000 = (4800+3900+4200)/1000 = 12.9
    assert o.actual.exit_price == pytest.approx(12.9)
    assert o.actual.position_size == 1000

# ═══ Case C: TRAILING_STOP → CLOSED ═══
def test_caseC_trailing_stop():
    dec = {'decision_id': 'lc_C', 'symbol': '600003', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=500)
    ex.record_exit(eid, 13.0, 500, '2026-08-18', 'TRAILING_STOP', status='CLOSED')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None and o.exit_reason == 'TRAILING_STOP'

# ═══ Case D: REDUCE → OPEN → 最终 SELL → CLOSED ═══
def test_caseD_reduce_then_sell():
    dec = {'decision_id': 'lc_D', 'symbol': '600004', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    # 组合风险减仓一半
    ex.record_exit(eid, 10.0, 500, 'r1', 'PORTFOLIO_RISK', status='PARTIAL')
    assert ex.get_execution(eid)['position_status'] == PARTIAL
    assert ex.build_outcome_from_execution(eid) is None  # 未最终平仓
    # 最终 SELL 剩余
    ex.record_exit(eid, 11.0, 500, 's1', 'STOP_LOSS', status='CLOSED')
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.actual.exit_price == pytest.approx(10.5)  # (10*500+11*500)/1000

# ═══ Case E: NOT_EXECUTED 不产生 Outcome ═══
def test_caseE_not_executed():
    dec = {'decision_id': 'lc_E', 'symbol': '600005', 'strategy': 'v1_double'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=0, status=NOT_EXECUTED)
    assert ex.get_execution(eid)['position_status'] == UNKNOWN
    assert ex.build_outcome_from_execution(eid) is None

# ═══ Case F: Real BUY → Manual → Real SELL → Manual Exit → Outcome ═══
def test_caseF_real_manual_lifecycle():
    dec = {'decision_id': 'lc_F', 'symbol': '600006', 'strategy': 'v1_double'}
    ex.confirm_manual_execution('lc_F', actual_price=10.0, actual_quantity=500,
                                execution_time='2026-08-18', status='EXECUTED')
    e = ex.find_execution('lc_F')[-1]
    assert e['source'] == 'MANUAL_CONFIRMATION'
    assert e['position_status'] == OPEN
    ex.record_exit(e['execution_id'], exit_price=9.0, exit_quantity=500,
                   exit_time='2026-08-20', exit_reason='MANUAL')
    o = ex.build_outcome_from_execution(e['execution_id'])
    assert o is not None and o.lifecycle_status == CLOSED

# ═══ Case G: Exit Decision → Exit Execution → Lifecycle Replay ═══
def test_caseG_lifecycle_replay():
    dec = {'decision_id': 'lc_G', 'symbol': '600007', 'strategy': 'v1_double',
           'data_snapshot_id': 'ds_G', 'portfolio_snapshot_id': 'real_G'}
    eid = ex.record_simulation_execution(dec, 'BUY', entry_price=10.0, quantity=1000)
    ex.record_exit(eid, 12.0, 1000, '2026-08-18', 'TAKE_PROFIT', status='CLOSED')
    o = ex.build_outcome_from_execution(eid)
    store.save_outcome(o)
    r = ex.lifecycle_replay(o.outcome_id)
    assert r['ok']
    assert r['outcome']['decision_id'] == 'lc_G'
    assert r['portfolio_snapshot_id'] == 'real_G'
    # entry execution 可通过 symbol 找到
    entry = ex.find_entry_execution('600007')
    assert entry is not None

# ═══ Case H: 历史 Legacy 无 decision_id ═══
def test_caseH_legacy_kept():
    trade = {'code': '600008', 'name': 'L', 'buy_price': 10.0, 'sell_price': 9.0,
             'profit_pct': -10.0, 'status': '止损', 'buy_date': '2024-01-02', 'strategy': 'v1_double'}
    o = store.build_from_trade(trade)
    assert o.decision_id == '' and o.outcome_source == SOURCE_LEGACY  # 不伪造
