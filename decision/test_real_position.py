#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 5 — 真实持仓 Unified Decision 测试

Case A-G：
A. 正常持有（无 exit, portfolio OK）→ HOLD
B. 止损 → SELL
C. 移动止盈 → SELL
D. 组合风险 HIGH → REDUCE（含 current/target/delta）
E. 禁新仓 + 正常持仓 → HOLD（不是机械清仓）
F. 禁新仓 + 止损 → SELL
G. ADD 全条件满足 → ADD；任一不满足不 ADD

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_real_position.py -v
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision.engine import DecisionEngine
from decision.adapters import position_ctx
from decision.portfolio import assess_portfolio
from decision.contract import HOLD, SELL, REDUCE, ADD

eng = DecisionEngine(strategy='v1_double', config_version='test', code_version='p5')

def _pos(**kw):
    base = dict(symbol='000001', name='持仓', regime_label='🟢 强趋势', regime_score=80,
                permission={'new_entry':'ALLOW','add_position':'ALLOW','reduce_position':'ALLOW','exit_position':'ALLOW'},
                permission_status='ALLOW', data_health='VALID',
                exit_signal='NONE', exit_triggers=[], current_position=0.05,
                portfolio_risk='OK', portfolio_assessment=None,
                position_count=5, stop_loss=0.08, take_profit=[0.25,0.5,0.8])
    base.update(kw)
    return eng.decide(position_ctx(**base))

# ═══ Case A: 正常持有 → HOLD ═══
def test_caseA_normal_hold():
    d = _pos()
    assert d.action == HOLD
    assert d.current_position == 0.05
    assert d.target_position == 0.05
    assert d.delta_position == 0.0

# ═══ Case B: 止损 → SELL ═══
def test_caseB_stop_loss_sell():
    d = _pos(exit_signal='RISK', exit_triggers=['STOP_LOSS'])
    assert d.action == SELL
    assert d.target_position == 0.0
    assert d.delta_position == -0.05
    assert 'STOP_LOSS' in d.reason_codes

# ═══ Case C: 移动止盈 → SELL ═══
def test_caseC_trailing_stop_sell():
    d = _pos(exit_signal='NORMAL', exit_triggers=['TRAILING_STOP'])
    assert d.action == SELL
    assert d.target_position == 0.0
    assert 'TRAILING_STOP' in d.reason_codes

# ═══ Case D: 组合风险 → REDUCE（目标减半）═══
def test_caseD_portfolio_risk_reduce():
    pa = assess_portfolio(candidate_sector='电子', target_position=0, total_capital=1_000_000,
                          position_count=15, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'电子':2}, drawdown=0.18, drawdown_limit=0.15)
    d = _pos(portfolio_risk='BLOCKED', portfolio_assessment=pa, drawdown=0.18)
    assert d.action == REDUCE
    assert d.current_position == 0.05
    assert d.target_position == 0.025  # 减半
    assert d.delta_position == -0.025
    assert 'DRAWDOWN_BLOCKED' in d.reason_codes

# ═══ Case E: 禁新仓 + 正常持仓 → HOLD（不机械清仓）═══
def test_caseE_no_new_entry_normal_hold():
    d = _pos(permission={'new_entry':'DENY','add_position':'DENY','reduce_position':'ALLOW','exit_position':'ALLOW'},
             permission_status='NO_NEW_ENTRY')
    assert d.action == HOLD  # 禁新仓 ≠ 清仓
    assert d.delta_position == 0.0

# ═══ Case F: 禁新仓 + 止损 → SELL ═══
def test_caseF_no_new_entry_stop_loss_sell():
    d = _pos(permission={'new_entry':'DENY','add_position':'DENY','reduce_position':'ALLOW','exit_position':'ALLOW'},
             permission_status='NO_NEW_ENTRY', exit_signal='RISK', exit_triggers=['STOP_LOSS'])
    assert d.action == SELL  # 禁新仓不阻止必要 SELL

# ═══ Case G: ADD ═══
def test_caseG_add_full_conditions():
    # 全条件满足：add_position ALLOW + entry CONFIRMED + target>current
    d = _pos(entry_signal='CONFIRMED', target_position=0.10)
    assert d.action == ADD
    assert d.target_position == 0.10
    assert d.delta_position == 0.05
    assert 'ADD_ALLOWED' in d.reason_codes

def test_caseG_add_deny_no_add():
    # add_position DENY → 不 ADD
    d = _pos(permission={'new_entry':'ALLOW','add_position':'DENY','reduce_position':'ALLOW','exit_position':'ALLOW'},
             entry_signal='CONFIRMED', target_position=0.10)
    assert d.action != ADD

def test_caseG_add_no_entry_no_add():
    # entry 未确认 → 不 ADD
    d = _pos(entry_signal='NONE', target_position=0.10)
    assert d.action != ADD

def test_caseG_add_target_not_greater_no_add():
    # target <= current → 不 ADD
    d = _pos(entry_signal='CONFIRMED', target_position=0.03)
    assert d.action != ADD

# ═══ NO_NEW_ENTRY 不得机械清仓的隔离验证（与 Rule 六一致）═══
def test_no_new_entry_not_equal_sell():
    # new_entry=DENY, 持仓, 无止损, portfolio 可接受 → HOLD（用户明确要求）
    d = _pos(permission={'new_entry':'DENY','add_position':'DENY','reduce_position':'ALLOW','exit_position':'ALLOW'},
             permission_status='NO_NEW_ENTRY', portfolio_risk='OK')
    assert d.action == HOLD
