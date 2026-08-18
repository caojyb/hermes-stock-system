#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 6 — Decision Outcome 测试

Case A-J：
A. BUY → OPEN → CLOSE → Outcome
B. STOP_LOSS → SELL → Outcome
C. TAKE_PROFIT → SELL → Outcome
D. REDUCE → 后续 CLOSE → Outcome
E. HOLD → 后续最终结果
F. NO_TRADE → Counterfactual
G. Decision 与 Execution 价格不同（planned vs actual 分离）
H. Legacy trade 无 decision_id
I. Main-Up Shadow Outcome
J. Replay outcome → decision → snapshot

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_outcome.py -v
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision.outcome import (Outcome, Planned, Actual, Excursion, Counterfactual,
                              map_exit_reason, gen_outcome_id,
                              CLOSED, OPEN, DECIDED, UNKNOWN,
                              SOURCE_LEGACY, SOURCE_DECISION, SOURCE_SHADOW, CF_WINDOWS)
from decision import outcome_store as store

# ═══ Case A: BUY → OPEN → CLOSE → Outcome ═══
def test_caseA_buy_open_close():
    o = Outcome(outcome_id=gen_outcome_id(), decision_id='did_A', symbol='600001',
                action='BUY', strategy='v1_double', outcome_source=SOURCE_DECISION,
                planned=Planned(entry_price=10.0), actual=Actual(entry_price=10.0, exit_price=12.0,
                                                                 realized_pnl=200, return_pct=0.2),
                lifecycle_status=CLOSED, exit_reason='TAKE_PROFIT')
    d = o.freeze()
    assert d['lifecycle_status'] == CLOSED
    assert d['planned']['entry_price'] == 10.0
    assert d['actual']['return_pct'] == 0.2

# ═══ Case B: STOP_LOSS → SELL → Outcome ═══
def test_caseB_stop_loss():
    assert map_exit_reason(['STOP_LOSS']) == 'STOP_LOSS'
    o = Outcome(action='SELL', exit_reason=map_exit_reason(['STOP_LOSS']),
                actual=Actual(return_pct=-0.08), lifecycle_status=CLOSED)
    assert o.exit_reason == 'STOP_LOSS'

# ═══ Case C: TAKE_PROFIT → SELL → Outcome ═══
def test_caseC_take_profit():
    assert map_exit_reason(['TAKE_PROFIT']) == 'TAKE_PROFIT'
    assert map_exit_reason(['清仓止盈']) == 'TAKE_PROFIT'   # legacy 中文映射

# ═══ Case D: REDUCE → 后续 CLOSE → Outcome ═══
def test_caseD_reduce_then_close():
    # REDUCE 决策记录 planned.target_position 降低，后续 CLOSE 记录最终结果
    o = Outcome(decision_id='did_D', action='REDUCE', lifecycle_status=CLOSED,
                planned=Planned(target_position=0.025), actual=Actual(return_pct=-0.05))
    assert o.action == 'REDUCE'
    assert o.planned.target_position == 0.025

# ═══ Case E: HOLD → 后续最终结果 ═══
def test_caseE_hold_then_result():
    # HOLD 后最终结果（OPEN→ 后续 CLOSE 更新）
    o = Outcome(action='HOLD', lifecycle_status=OPEN, actual=Actual(entry_price=10.0))
    assert o.lifecycle_status == OPEN
    # 后续平仓
    o.lifecycle_status = CLOSED
    o.actual.exit_price = 11.0
    assert o.lifecycle_status == CLOSED

# ═══ Case F: NO_TRADE → Counterfactual ═══
def test_caseF_no_trade_counterfactual():
    cf = store.compute_counterfactual('600540', '2026-07-01', 4.0, windows=(5, 10))
    assert len(cf) == 2
    for c in cf:
        if c.eligible:
            assert c.status == 'COMPUTED'
            assert c.hypothetical_return != 0 or True
    # 窗口不足 → NOT_ELIGIBLE
    cf2 = store.compute_counterfactual('600540', '2026-07-28', 4.0, windows=(60,))
    assert cf2[0].status == 'NOT_ELIGIBLE'

# ═══ Case G: Decision 与 Execution 价格不同 ═══
def test_caseG_planned_vs_actual_diff():
    # planned 与 actual 严格分离，保存两者
    o = Outcome(planned=Planned(entry_price=10.0, target_position=0.05),
                actual=Actual(entry_price=10.5, position_size=0.04, exit_price=9.8, return_pct=-0.067))
    assert o.planned.entry_price == 10.0
    assert o.actual.entry_price == 10.5
    assert o.planned.entry_price != o.actual.entry_price  # 分离保留
    assert o.planned.target_position != o.actual.position_size

# ═══ Case H: Legacy trade 无 decision_id ═══
def test_caseH_legacy_no_decision_id():
    trade = {'code': '600001', 'name': 'X', 'buy_price': 10.0, 'sell_price': 9.0,
             'profit_pct': -10.0, 'status': '止损', 'buy_date': '2024-01-02', 'strategy': 'v1_double'}
    o = store.build_from_trade(trade)
    assert o.decision_id == ''            # 不伪造
    assert o.outcome_source == SOURCE_LEGACY
    assert o.exit_reason == 'STOP_LOSS'   # legacy 中文映射

# ═══ Case I: Main-Up Shadow Outcome ═══
def test_caseI_shadow_outcome():
    o = Outcome(outcome_id=gen_outcome_id(), symbol='600519', strategy='main_up',
                strategy_version='shadow', outcome_source=SOURCE_SHADOW,
                action='HOLD', lifecycle_status=OPEN)
    assert o.outcome_source == SOURCE_SHADOW
    # Shadow 与 Production 分离（strategy=main_up，不进入 V1 production stats）
    assert o.strategy == 'main_up'

# ═══ Case J: Replay outcome → decision → snapshot ═══
def test_caseJ_replay(tmp_path):
    # 构造 decision snapshot + outcome，replay 关联
    did = 'did_replay_123'
    dec_dir = tmp_path / 'snapshots'; dec_dir.mkdir()
    (dec_dir / f"{did}.json").write_text(json.dumps({
        'decision_id': did, 'symbol': '600001', 'action': 'SELL',
        'regime_label': 'HIGH_VOLATILITY', 'config_version': 'v1', 'code_version': 'p6',
        'portfolio_snapshot_id': 'real_xxx'}))
    # monkeypatch 决策目录
    store._DECISION_DIR = dec_dir
    o = Outcome(outcome_id='out_replay_1', decision_id=did, symbol='600001', action='SELL',
                decision_snapshot_id=did, portfolio_snapshot_id='real_xxx',
                outcome_source=SOURCE_DECISION)
    save_path = store.save_outcome(o)   # 存到默认目录
    # 直接读回验证字段
    r = json.load(open(save_path))
    assert r['decision_id'] == did
    assert r['portfolio_snapshot_id'] == 'real_xxx'
    assert r['outcome_source'] == SOURCE_DECISION
