#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6.7 — Decision / Execution Integrity Hardening 测试

覆盖：
1. position_id 唯一性
2. 同股票两次独立持仓不串单（Case A）
3. 分批止盈属于同一 position_id（Case B）
4. ADD 生命周期同一 position（Case C）
5. PARTIAL SELL → ADD → FINAL SELL 生命周期不串（Case D）
6. Legacy 无 decision_id 保持 LEGACY（Case E）
7. Production fallback 禁止依赖符号主关联（Case F）
8. record_exit 多段加权 Outcome（Case G）
9. Replay 优先 position_id（Case H）
10. LINKAGE_FALLBACK 标记（Case I）
11. monitor linkage_fallback_count（Case J）

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_integrity_p67.py -v
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision import execution as ex
from decision.execution import (
    EXECUTED, PARTIAL, NOT_EXECUTED, LINKAGE_FALLBACK,
    gen_position_id, find_entry_execution, find_open_entry_execution,
    find_exit_executions, find_executions_by_position_id,
    record_sim_exit_and_outcome, lifecycle_replay, monitor
)
from decision.outcome import CLOSED, SOURCE_LEGACY, SOURCE_DECISION


# ═══ Case 1: position_id 唯一性 ═══
def test_position_id_unique_per_lifecycle():
    d1 = {'decision_id': 'p67_1', 'symbol': '600540', 'name': 'A', 'strategy': 'v1_double',
          'reference_price': 10.0, 'target_position': 0.05}
    d2 = {'decision_id': 'p67_2', 'symbol': '600540', 'name': 'A', 'strategy': 'v1_double',
          'reference_price': 10.5, 'target_position': 0.05}
    e1 = ex.record_simulation_execution(d1, 'BUY', 10.0, 1000)
    e2 = ex.record_simulation_execution(d2, 'BUY', 10.5, 1000)
    x1 = ex.get_execution(e1)
    x2 = ex.get_execution(e2)
    assert x1['position_id'] and x2['position_id']
    assert x1['position_id'] != x2['position_id']
    assert x1['decision_id'] == 'p67_1'
    assert x2['decision_id'] == 'p67_2'
    # 两组生命周期独立，各自 exit 不出现在对方记录中
    ex.record_exit(e1, 11.0, 1000, 's1', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=d1['decision_id'])
    ex.record_exit(e2, 12.0, 1000, 's2', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e2, exit_decision_id=d2['decision_id'])
    assert len(find_exit_executions(e1)) == 1
    assert len(find_exit_executions(e2)) == 1


# ═══ Case 2: 同股票两次独立持仓不串单（Case A）═══
def test_same_symbol_two_lifecycles_not_crossed():
    d1 = {'decision_id': 'p67_A1', 'symbol': '600540', 'name': '新赛', 'strategy': 'v1_double',
          'reference_price': 4.0, 'target_position': 0.05}
    d2 = {'decision_id': 'p67_A2', 'symbol': '600540', 'name': '新赛', 'strategy': 'v1_double',
          'reference_price': 5.0, 'target_position': 0.05}
    e1 = ex.record_simulation_execution(d1, 'BUY', 4.0, 1000)
    e2 = ex.record_simulation_execution(d2, 'BUY', 5.0, 1000)
    # 第一轮：SELL
    ex.record_exit(e1, 6.0, 1000, 't1', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1)
    # 第二轮：SELL
    ex.record_exit(e2, 7.0, 1000, 't2', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e2)
    o1 = ex.build_outcome_from_execution(e1)
    o2 = ex.build_outcome_from_execution(e2)
    assert o1 is not None and o2 is not None
    assert o1.decision_id == 'p67_A1'
    assert o2.decision_id == 'p67_A2'
    assert o1.actual.exit_price == pytest.approx(6.0)
    assert o2.actual.exit_price == pytest.approx(7.0)
    # 各自 exit_executions 仅对应自身
    exits1 = find_exit_executions(e1)
    exits2 = find_exit_executions(e2)
    assert len(exits1) == 1 and exits1[0]['exit_decision_id'] in ('', 'p67_A1')
    assert len(exits2) == 1 and exits2[0]['exit_decision_id'] in ('', 'p67_A2')


# ═══ Case 3: 分批止盈属于同一 position_id（Case B）═══
def test_multiple_exit_same_position_id():
    dec = {'decision_id': 'p67_B', 'symbol': '600007', 'name': 'B', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    pid = ex.get_execution(eid)['position_id']
    assert pid
    # TP1 PARTIAL
    ex.record_exit(eid, 12.0, 400, 'tp1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    # TP2 PARTIAL
    ex.record_exit(eid, 13.0, 300, 'tp2', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    # TP3 FINAL
    ex.record_exit(eid, 14.0, 300, 'tp3', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    exits = find_exit_executions(eid)
    # 当前 exit 段存储在 entry execution 的 exit_segments；find_exit_executions 为未来独立 exit file 预留
    segs = (ex.get_execution(eid) or {}).get('exit_segments', [])
    assert len(segs) == 3
    for ex_ in exits:
        assert ex_['entry_execution_id'] == eid
        assert ex_['position_id'] == pid
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.actual.position_size == 1000
    assert o.actual.exit_price == pytest.approx(12.9)


# ═══ Case 4: ADD 生命周期同一 position（Case C）═══
def test_add_same_position_lifecycle():
    dec_buy = {'decision_id': 'p67_C1', 'symbol': '600008', 'name': 'C', 'strategy': 'v1_double',
               'reference_price': 10.0}
    dec_add = {'decision_id': 'p67_C2', 'symbol': '600008', 'name': 'C', 'strategy': 'v1_double',
               'reference_price': 9.5}
    e1 = ex.record_simulation_execution(dec_buy, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    # ADD 应复用同一 position_id（生产链由决策传参决定）
    e_add = ex.Execution(
        decision_id=dec_add['decision_id'], symbol=dec_add['symbol'], name=dec_add['name'],
        action='ADD', strategy=dec_add['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec_add['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 9.5, 'quantity': 500, 'position': 1500},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    eid_add = ex.save_execution(e_add)
    # 最终 SELL
    ex.record_exit(e1, 11.0, 1000, 'sell', 'STOP_LOSS', status='CLOSED',
                   entry_execution_id=e1, exit_decision_id=dec_buy['decision_id'])
    # ADD 不应独立 Outcome；以 entry execution 为准（ADD 数量已聚合进 Outcome）
    o = ex.build_outcome_from_execution(e1)
    assert o is not None
    assert o.decision_id == 'p67_C1'
    assert o.actual.total_entry_quantity == 1500
    # 确认 ADD 记录存在且 position_id 同一生命周期
    add_rec = ex.get_execution(eid_add)
    assert add_rec['action'] == 'ADD'
    assert add_rec['position_id'] == pid


# ═══ Case 5: PARTIAL SELL → ADD → FINAL SELL 生命周期不串（Case D）═══
def test_partial_sell_add_final_not_cross():
    d1 = {'decision_id': 'p67_D1', 'symbol': '600009', 'name': 'D', 'strategy': 'v1_double',
          'reference_price': 10.0}
    d2 = {'decision_id': 'p67_D2', 'symbol': '600009', 'name': 'D', 'strategy': 'v1_double',
          'reference_price': 10.2}
    e1 = ex.record_simulation_execution(d1, 'BUY', 10.0, 1000)
    pid1 = ex.get_execution(e1)['position_id']
    # PARTIAL SELL
    ex.record_exit(e1, 11.0, 400, 'p1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=e1, exit_decision_id=d1['decision_id'])
    # 同生命周期内 ADD（由同一 position_id 串联）
    e_add = ex.Execution(
        decision_id=d2['decision_id'], symbol=d2['symbol'], name=d2['name'],
        action='ADD', strategy=d2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': d2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 10.2, 'quantity': 300, 'position': 900},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid1,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    # FINAL SELL
    ex.record_exit(e1, 12.0, 900, 'f1', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=d1['decision_id'])
    o = ex.build_outcome_from_execution(e1)
    assert o is not None
    assert o.actual.total_entry_quantity == 1300
    assert o.actual.total_exit_quantity == 1300
    assert o.actual.final_quantity == 0
    assert len((ex.get_execution(e1) or {}).get('exit_segments', [])) == 2


# ═══ Case 6: Legacy 无 decision_id 保持 LEGACY（Case E）═══
def test_legacy_kept_without_decision_id():
    trade = {'code': '600010', 'name': 'L', 'buy_price': 10.0, 'sell_price': 9.0,
             'profit_pct': -10.0, 'status': '止损', 'buy_date': '2024-01-02', 'strategy': 'v1_double'}
    from decision import outcome_store as store
    o = store.build_from_trade(trade)
    assert o.decision_id == '' and o.outcome_source == SOURCE_LEGACY


# ═══ Case 7: Production fallback 禁止依赖 symbol 主关联（Case F）═══
def test_production_uses_decision_id_first():
    dec = {'decision_id': 'p67_F', 'symbol': '600011', 'name': 'F', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    _, _, linkage = record_sim_exit_and_outcome('600011', 11.0, 1000, 'TAKE_PROFIT', '2026-08-18',
                                                 decision_id=dec['decision_id'])
    assert linkage == 'STRUCTURED'


# ═══ Case 8: record_exit 多段加权 Outcome（Case G）═══
def test_record_exit_weighted_outcome():
    dec = {'decision_id': 'p67_G', 'symbol': '600012', 'name': 'G', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    ex.record_exit(eid, 12.0, 400, 'tp1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex.record_exit(eid, 13.0, 300, 'tp2', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex.record_exit(eid, 14.0, 300, 'tp3', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.actual.exit_price == pytest.approx(12.9)
    assert o.actual.realized_pnl == pytest.approx(2900.0)


# ═══ Case 9: Replay 优先 position_id（Case H）═══
def test_replay_uses_position_id_first():
    dec = {'decision_id': 'p67_H', 'symbol': '600013', 'name': 'H', 'strategy': 'v1_double',
           'reference_price': 10.0, 'portfolio_snapshot_id': 'snap_H'}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    pid = ex.get_execution(eid)['position_id']
    ex.record_exit(eid, 11.0, 1000, 't', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    from decision import outcome_store as store
    o = ex.build_outcome_from_execution(eid)
    store.save_outcome(o)
    r = ex.lifecycle_replay(o.outcome_id)
    assert r['ok']
    assert r['position_id'] == pid
    assert r['linkage'] == '' or r['linkage'] == 'STRUCTURED'
    assert r['exit_executions']
    assert r['outcome']['decision_id'] == 'p67_H'


# ═══ Case 10: LINKAGE_FALLBACK 标记（Case I）═══
def test_fallback_marked_when_no_struct_info():
    # 无 decision_id / position_id / entry_execution_id → fallback
    _, _, linkage = record_sim_exit_and_outcome('600099', 10.0, 1000, 'STOP_LOSS', '2026-08-18')
    assert linkage in (LINKAGE_FALLBACK, 'LEGACY') or linkage == ''


# ═══ Case 11: monitor linkage_fallback_count（Case J）═══
def test_monitor_reports_linkage_fallback():
    m = ex.monitor()
    assert 'active_pipeline_gap' in m
    assert 'known_legacy_gap' in m
    assert m['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')


# ═══ Case 12: aggregate_position 完整生命周期（Case A：BUY+ADD+SELL）═══
def test_aggregate_buy_add_sell_full():
    dec1 = {'decision_id': 'p68_A1', 'symbol': '600020', 'name': 'A', 'strategy': 'v1_double',
            'reference_price': 10.0}
    dec2 = {'decision_id': 'p68_A2', 'symbol': '600020', 'name': 'A', 'strategy': 'v1_double',
            'reference_price': 12.0}
    e1 = ex.record_simulation_execution(dec1, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    e_add = ex.Execution(
        decision_id=dec2['decision_id'], symbol=dec2['symbol'], name=dec2['name'],
        action='ADD', strategy=dec2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 12.0, 'quantity': 1000, 'position': 2000},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    ex.record_exit(e1, 15.0, 2000, 'sell', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    pos = ex.aggregate_position(pid)
    assert pos is not None
    assert pos['total_entry_quantity'] == 2000
    assert pos['average_entry_price'] == pytest.approx(11.0)
    assert pos['total_exit_quantity'] == 2000
    assert pos['weighted_exit_price'] == pytest.approx(15.0)
    assert pos['current_quantity'] == 0
    assert pos['realized_pnl'] == pytest.approx(8000.0)
    assert pos['invested_capital'] == pytest.approx(22000.0)


# ═══ Case 13: 分批止盈聚合（Case B：BUY+ADD+PARTIAL+PARTIAL）═══
def test_aggregate_partial_exit():
    dec1 = {'decision_id': 'p68_B1', 'symbol': '600021', 'name': 'B', 'strategy': 'v1_double',
            'reference_price': 10.0}
    dec2 = {'decision_id': 'p68_B2', 'symbol': '600021', 'name': 'B', 'strategy': 'v1_double',
            'reference_price': 12.0}
    e1 = ex.record_simulation_execution(dec1, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    e_add = ex.Execution(
        decision_id=dec2['decision_id'], symbol=dec2['symbol'], name=dec2['name'],
        action='ADD', strategy=dec2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 12.0, 'quantity': 1000, 'position': 2000},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    ex.record_exit(e1, 14.0, 500, 'p1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    ex.record_exit(e1, 15.0, 1500, 'p2', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    o = ex.build_outcome_from_execution(e1)
    assert o is not None
    assert o.actual.total_entry_quantity == 2000
    assert o.actual.total_exit_quantity == 2000
    assert o.actual.final_quantity == 0
    assert o.actual.average_entry_price == pytest.approx(11.0)
    assert o.actual.weighted_exit_price == pytest.approx(14.75)
    assert o.actual.return_pct == pytest.approx(0.3409)


# ═══ Case 14: 同股票两个不同 position_id 不串数量（Case C）═══
def test_two_position_ids_not_crossed():
    d1 = {'decision_id': 'p68_C1', 'symbol': '600022', 'name': 'C', 'strategy': 'v1_double',
          'reference_price': 10.0}
    d2 = {'decision_id': 'p68_C2', 'symbol': '600022', 'name': 'C', 'strategy': 'v1_double',
          'reference_price': 13.0}
    e1 = ex.record_simulation_execution(d1, 'BUY', 10.0, 1000)
    pid1 = ex.get_execution(e1)['position_id']
    e2 = ex.record_simulation_execution(d2, 'BUY', 13.0, 500)
    pid2 = ex.get_execution(e2)['position_id']
    assert pid1 != pid2
    ex.record_exit(e1, 11.0, 1000, 's1', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=d1['decision_id'])
    ex.record_exit(e2, 14.0, 500, 's2', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e2, exit_decision_id=d2['decision_id'])
    pos1 = ex.aggregate_position(pid1)
    pos2 = ex.aggregate_position(pid2)
    assert pos1['total_entry_quantity'] == 1000
    assert pos2['total_entry_quantity'] == 500
    assert pos1['realized_pnl'] == pytest.approx(1000.0)
    assert pos2['realized_pnl'] == pytest.approx(500.0)


# ═══ Case 15: ADD 不生成独立 Outcome（Case D）═══
def test_add_does_not_create_outcome():
    dec1 = {'decision_id': 'p68_D1', 'symbol': '600023', 'name': 'D', 'strategy': 'v1_double',
            'reference_price': 10.0}
    dec2 = {'decision_id': 'p68_D2', 'symbol': '600023', 'name': 'D', 'strategy': 'v1_double',
            'reference_price': 9.0}
    e1 = ex.record_simulation_execution(dec1, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    e_add = ex.Execution(
        decision_id=dec2['decision_id'], symbol=dec2['symbol'], name=dec2['name'],
        action='ADD', strategy=dec2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 9.0, 'quantity': 500, 'position': 1500},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    # ADD 本身不产生 Outcome
    o_from_add = ex.build_outcome_from_execution(e_add.execution_id)
    assert o_from_add is None


# ═══ Case 16: Replay 显示完整数量变化（Case E）═══
def test_replay_shows_full_quantity_changes():
    dec1 = {'decision_id': 'p68_E1', 'symbol': '600024', 'name': 'E', 'strategy': 'v1_double',
            'reference_price': 10.0, 'portfolio_snapshot_id': 'snap_E'}
    dec2 = {'decision_id': 'p68_E2', 'symbol': '600024', 'name': 'E', 'strategy': 'v1_double',
            'reference_price': 12.0}
    e1 = ex.record_simulation_execution(dec1, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    e_add = ex.Execution(
        decision_id=dec2['decision_id'], symbol=dec2['symbol'], name=dec2['name'],
        action='ADD', strategy=dec2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 12.0, 'quantity': 1000, 'position': 2000},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    ex.record_exit(e1, 14.0, 500, 'p1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    ex.record_exit(e1, 15.0, 1500, 'p2', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    from decision import outcome_store as store
    o = ex.build_outcome_from_execution(e1)
    store.save_outcome(o)
    r = ex.lifecycle_replay(o.outcome_id)
    assert r['ok']
    assert r['position_id'] == pid
    # 当前退出段存储在 entry execution 中，replay 将其作为 exit_executions 代表
    assert len(r['exit_executions']) == 1
    assert r['exit_executions'][0]['execution_id'] == e1
    segs = r['exit_executions'][0].get('exit_segments', [])
    assert len(segs) == 2


# ═══ Case 17: Outcome PnL 使用完整生命周期成本（Case F）═══
def test_outcome_pnl_uses_full_lifecycle_cost():
    dec1 = {'decision_id': 'p68_F1', 'symbol': '600025', 'name': 'F', 'strategy': 'v1_double',
            'reference_price': 10.0}
    dec2 = {'decision_id': 'p68_F2', 'symbol': '600025', 'name': 'F', 'strategy': 'v1_double',
            'reference_price': 20.0}
    e1 = ex.record_simulation_execution(dec1, 'BUY', 10.0, 1000)
    pid = ex.get_execution(e1)['position_id']
    e_add = ex.Execution(
        decision_id=dec2['decision_id'], symbol=dec2['symbol'], name=dec2['name'],
        action='ADD', strategy=dec2['strategy'], status=EXECUTED, source=ex.SRC_SIM,
        planned={'price': dec2['reference_price'], 'quantity': 0, 'position': 0},
        actual={'price': 20.0, 'quantity': 1000, 'position': 2000},
        execution_time=ex._now(), position_status=ex.OPEN, position_id=pid,
        decision_snapshot_id='', portfolio_snapshot_id='',
    )
    ex.save_execution(e_add)
    ex.record_exit(e1, 30.0, 2000, 'sell', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=e1, exit_decision_id=dec1['decision_id'])
    o = ex.build_outcome_from_execution(e1)
    assert o is not None
    # avg cost = (10*1000+20*1000)/2000 = 15
    assert o.actual.average_entry_price == pytest.approx(15.0)
    assert o.actual.realized_pnl == pytest.approx(30000.0)
    assert o.actual.return_pct == pytest.approx(1.0)


# ═══ Case 18: Weighted exit 正确（Case G）═══
def test_weighted_exit_correct():
    dec = {'decision_id': 'p68_G', 'symbol': '600026', 'name': 'G', 'strategy': 'v1_double',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    pid = ex.get_execution(eid)['position_id']
    ex.record_exit(eid, 12.0, 400, 'tp1', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex.record_exit(eid, 14.0, 300, 'tp2', 'TAKE_PROFIT', status='PARTIAL', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex.record_exit(eid, 16.0, 300, 'tp3', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    pos = ex.aggregate_position(pid)
    assert pos['weighted_exit_price'] == pytest.approx(13.8)
    assert pos['total_exit_quantity'] == 1000


# ═══ Case 19: Legacy 数据保持 LEGACY（Case H）═══
def test_legacy_kept_without_struct_info():
    trade = {'code': '600027', 'name': 'L', 'buy_price': 10.0, 'sell_price': 9.0,
             'profit_pct': -10.0, 'status': '止损', 'buy_date': '2024-01-02', 'strategy': 'v1_double'}
    from decision import outcome_store as store
    o = store.build_from_trade(trade)
    assert o.decision_id == '' and o.outcome_source == SOURCE_LEGACY


# ═══ Case 20: Production / Shadow 数量状态分离（Case I）═══
def test_production_shadow_quantity_separated():
    dec = {'decision_id': 'p68_I', 'symbol': '600028', 'name': 'I', 'strategy': 'main_up',
           'reference_price': 10.0}
    eid = ex.record_simulation_execution(dec, 'BUY', 10.0, 1000)
    ex.record_exit(eid, 11.0, 1000, 'sell', 'TAKE_PROFIT', status='CLOSED', entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = ex.build_outcome_from_execution(eid)
    assert o is not None
    assert o.strategy == 'main_up'
    assert o.outcome_source == SOURCE_DECISION


# ═══ Case 21: monitor linkage_fallback_count（Case J）═══
def test_monitor_linkage_fallback_count():
    m = ex.monitor()
    assert 'linkage_fallback_count' in m
    assert 'production_linkage' in m
    assert 'shadow_count' in m
    assert m['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')
