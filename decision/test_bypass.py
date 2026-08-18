#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3.6 — Decision Bypass Closure 测试

Case A-F：
A. track_flow 候选 + Permission ALLOW → BUY
B. track_flow 候选 + Permission DENY → NO_TRADE → 不能建仓
C. track_flow 候选 + Portfolio BLOCK → NO_TRADE → 不能建仓
D. Risk Controller 触发减仓 → DecisionEngine → SELL → 可执行
E. Risk Controller + NO_NEW_ENTRY → 不影响已有持仓风险退出（SELL）
F. 所有生产交易写入可关联 decision_id（snapshot 冻结）

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_bypass.py -v
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision.engine import DecisionEngine
from decision.adapters import entry_ctx, position_ctx
from decision.portfolio import assess_portfolio
from decision import snapshot as snap
from decision.contract import BUY, SELL, NO_TRADE

eng = DecisionEngine(strategy='v1_double', config_version='test', code_version='bypass_p36')

def _tf_entry(**kw):
    """模拟 track_flow confirm_buy 的 Decision gate 输入（entry assessment 来自 track_flow 候选）。"""
    base = dict(regime_label='🟢 强趋势', regime_score=80,
                permission={'new_entry':'ALLOW','add_position':'ALLOW','reduce_position':'ALLOW','exit_position':'ALLOW'},
                permission_status='ALLOW', data_health='VALID', candidate_qualified=True, candidate_score=0,
                signals=['A','B','D'], entry_price=10.0, target_position=25000,
                position_count=5, portfolio_risk='OK', portfolio_assessment=None,
                stop_loss=0.08, take_profit=[0.25,0.5,0.8])
    base.update(kw)
    return eng.decide(entry_ctx(symbol='600001', name='TF', **base))

# ═══ Case A: track_flow 候选 + Permission ALLOW → BUY ═══
def test_caseA_trackflow_allow_buy():
    d = _tf_entry(permission_status='ALLOW', permission={'new_entry':'ALLOW','add_position':'ALLOW','reduce_position':'ALLOW','exit_position':'ALLOW'})
    assert d.action == BUY

# ═══ Case B: track_flow 候选 + Permission DENY → NO_TRADE（不建仓）═══
def test_caseB_trackflow_deny_no_buy():
    d = _tf_entry(permission_status='NO_NEW_ENTRY', permission={'new_entry':'DENY','add_position':'DENY','reduce_position':'ALLOW','exit_position':'ALLOW'})
    assert d.action == NO_TRADE
    # 对应 confirm_buy: if _dec.action != 'BUY': return False（不执行 INSERT）
    assert d.action != BUY  # gate 拦截 → 不建仓

# ═══ Case C: track_flow 候选 + Portfolio BLOCK → NO_TRADE（不建仓）═══
def test_caseC_trackflow_portfolio_block_no_buy():
    pa = assess_portfolio(candidate_sector='医药', target_position=25000, total_capital=1_000_000,
                          position_count=10, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'医药':3}, drawdown=0.05)
    d = _tf_entry(portfolio_risk='BLOCKED', portfolio_assessment=pa)
    assert d.action == NO_TRADE
    assert 'SECTOR_LIMIT_EXCEEDED' in d.reason_codes
    assert d.action != BUY  # 不建仓

# ═══ Case D: Risk Controller 减仓 → DecisionEngine → SELL（可执行）═══
def test_caseD_risk_reduce_to_sell():
    # 模拟 risk_controller 减仓段：position_ctx(exit=RISK, trigger=PORTFOLIO_DRAWDOWN_REDUCE) → SELL
    d = eng.decide(position_ctx(symbol='000001', name='持仓', regime_label='',
                                permission={}, permission_status='', data_health='VALID',
                                exit_signal='RISK', exit_triggers=['PORTFOLIO_DRAWDOWN_REDUCE'],
                                position_count=5))
    assert d.action == SELL  # 归一为 SELL，减仓可执行

# ═══ Case E: Risk Controller + NO_NEW_ENTRY → 不影响持仓风险退出（SELL）═══
def test_caseE_risk_exit_not_blocked_by_no_new_entry():
    d = eng.decide(position_ctx(symbol='000002', name='持仓2', regime_label='🔴 高波动',
                                permission={'new_entry':'DENY'}, permission_status='NO_NEW_ENTRY',
                                data_health='VALID', exit_signal='RISK', exit_triggers=['PORTFOLIO_DRAWDOWN_REDUCE'],
                                position_count=5))
    assert d.action == SELL  # 禁新仓不影响持仓风险退出

# ═══ Case F: 生产交易写入可关联 decision_id（snapshot 冻结）═══
def test_caseF_decision_id_trackable(tmp_path):
    d = _tf_entry()
    path = snap.save_snapshot(d, snap_dir=str(tmp_path))
    assert os.path.exists(path)
    # decision_id 唯一且含 symbol
    assert d.decision_id
    assert '600001' in d.decision_id
    # 可回放
    from decision import replay as rp
    r = rp.replay(d.decision_id, snap_dir=str(tmp_path))
    assert r['ok'] is True
    assert r['decision']['action'] == d.action

# ═══ 双旁路均不可绕过：track_flow 与 risk_controller 的写入都须 Decision ═══
def test_trackflow_gate_is_fail_safe():
    # confirm_buy 逻辑: Decision 异常/非 BUY → return False（不 INSERT），fail-safe
    # 模拟异常场景：data 异常 → NO_TRADE → 拦截
    d = _tf_entry(data_health='INVALID')
    assert d.action == NO_TRADE
    assert d.action != BUY
