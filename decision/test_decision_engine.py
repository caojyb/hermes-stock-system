#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 — Unified Decision 测试

覆盖 8 类要求 + 多模块冲突场景：
1. Contract Test        — Decision schema 完整
2. Permission Conflict  — Permission 能否决 BUY
3. Exit Override        — 必要 SELL 不被 NO_NEW_ENTRY 阻止
4. Data Failure         — BUY→NO_TRADE 但必要 EXIT 可用
5. Snapshot Test        — 决策生成后能冻结
6. Replay Test          — 给定 decision_id 恢复 snapshot
7. Determinism Test     — 相同输入+版本 → 相同 Decision
8. Simulation Regression— Phase 1 测试继续通过（test_trading_permission）

运行：
  cd scripts/cron && /usr/bin/python3 -m pytest decision/test_decision_engine.py -v
"""
import os, sys, json, tempfile, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision.engine import DecisionEngine
from decision.adapters import entry_ctx, position_ctx, norm_exit_signal
from decision import snapshot as snap
from decision import replay as rp
from decision.contract import BUY, HOLD, SELL, NO_TRADE, REASON, Decision

eng = DecisionEngine(strategy='v1_double', config_version='test', code_version='test')

def _entry(**kw):
    base = dict(symbol='000001', mode='entry', has_position=False, regime_label='强趋势',
                regime_score=80, permission_status='ALLOW', permission={'new_entry': 'ALLOW'},
                data_health='VALID', candidate_qualified=True, candidate_score=75,
                entry_signal='CONFIRMED', entry_signals=['A','B','D'],
                reference_price=10.0, target_position=25000)
    base.update(kw)
    return base

# ═══ 1. Contract Test ═══
def test_contract_schema_complete():
    d = eng.decide(_entry())
    f = d.freeze()
    for field in ['decision_id','timestamp','as_of_time','symbol','action','market_regime',
                  'permission_status','permission','strategy','candidate_qualified','candidate_score',
                  'entry_signal','entry_signals','reference_price','target_position',
                  'portfolio_drawdown','position_count','stop_loss','take_profit',
                  'exit_signal','exit_triggers','reason_codes','explanation',
                  'config_version','code_version']:
        assert field in f, f"缺少字段 {field}"
    assert f['action'] in (BUY, HOLD, SELL, NO_TRADE)

# ═══ 2. Permission Conflict ═══
def test_permission_can_veto_buy():
    d = eng.decide(_entry(permission_status='NO_NEW_ENTRY', permission={'new_entry':'DENY'}))
    assert d.action == NO_TRADE
    assert REASON['PERMISSION_BLOCKED'] in d.reason_codes

# ═══ 3. Exit Override ═══
def test_exit_not_blocked_by_no_new_entry():
    # 已有持仓 + Exit + Permission.new_entry=DENY → SELL（不被禁新仓阻止）
    d = eng.decide(position_ctx(symbol='000003', name='x', regime_label='高波动',
                                permission={'new_entry':'DENY'}, permission_status='NO_NEW_ENTRY',
                                data_health='VALID', exit_signal='RISK', exit_triggers=['STOP_LOSS'],
                                position_count=3))
    assert d.action == SELL

# ═══ 4. Data Failure ═══
def test_data_failure_buy_to_no_trade():
    d = eng.decide(_entry(data_health='INVALID'))
    assert d.action == NO_TRADE

def test_data_failure_necessary_exit_available():
    # 关键数据异常 + 已有持仓 + 退出需求 → SELL
    d = eng.decide(position_ctx(symbol='000004', name='x', regime_label='强趋势',
                                permission={}, permission_status='', data_health='INVALID',
                                exit_signal='RISK', exit_triggers=['STOP_LOSS'], position_count=2))
    assert d.action == SELL

# ═══ 5. Snapshot Test ═══
def test_snapshot_freeze(tmp_path):
    d = eng.decide(_entry())
    path = snap.save_snapshot(d, snap_dir=str(tmp_path))
    assert os.path.exists(path)
    # 冻结后内容不可变：再存不覆盖
    path2 = snap.save_snapshot(d, snap_dir=str(tmp_path))
    assert path == path2

# ═══ 6. Replay Test ═══
def test_replay_restores_snapshot(tmp_path):
    d = eng.decide(_entry(symbol='000005'))
    snap.save_snapshot(d, snap_dir=str(tmp_path))
    r = rp.replay(d.decision_id, snap_dir=str(tmp_path))
    assert r['ok'] is True
    assert r['decision']['action'] == d.action
    assert r['decision']['symbol'] == '000005'
    assert r['decision']['reason_codes'] == d.reason_codes

def test_replay_missing_snapshot(tmp_path):
    r = rp.replay('nonexistent_id_xxx', snap_dir=str(tmp_path))
    assert r['ok'] is False

# ═══ 7. Determinism ═══
def test_determinism_same_input_same_decision():
    d1 = eng.decide(_entry())
    d2 = eng.decide(_entry())
    assert d1.action == d2.action
    assert d1.reason_codes == d2.reason_codes
    assert d1.target_position == d2.target_position

# ═══ 多模块冲突场景（用户二十二节）═══
def test_conflict_candidate_pass_entry_buy_perm_deny():
    # Candidate=PASS, Entry=BUY, Permission=DENY → NO_TRADE
    d = eng.decide(_entry(permission_status='NO_NEW_ENTRY', permission={'new_entry':'DENY'}))
    assert d.action == NO_TRADE

def test_conflict_candidate_fail_entry_buy():
    # Candidate=FAIL, Entry=BUY → NO_TRADE
    d = eng.decide(_entry(candidate_qualified=False))
    assert d.action == NO_TRADE

def test_conflict_entry_insufficient():
    # Entry 未确认 → NO_TRADE
    d = eng.decide(_entry(entry_signal='INSUFFICIENT', entry_signals=['A']))
    assert d.action == NO_TRADE

def test_conflict_data_invalid_exit_required():
    # Data=INVALID + Exit=REQUIRED → SELL
    d = eng.decide(position_ctx(symbol='000006', name='x', regime_label='强趋势',
                                permission={}, permission_status='', data_health='INVALID',
                                exit_signal='FORCED', exit_triggers=['FORCED_EXIT'], position_count=1))
    assert d.action == SELL

# ═══ BUY 必要条件（全部满足才 BUY）═══
def test_buy_requires_all_conditions():
    # 完整条件 → BUY
    assert eng.decide(_entry()).action == BUY
    # 逐个破坏条件 → NO_TRADE
    assert eng.decide(_entry(candidate_qualified=False)).action == NO_TRADE
    assert eng.decide(_entry(entry_signal='INSUFFICIENT')).action == NO_TRADE
    assert eng.decide(_entry(target_position=0)).action == NO_TRADE
    assert eng.decide(_entry(data_health='STALE')).action == NO_TRADE
    assert eng.decide(_entry(permission={'new_entry':'DENY'}, permission_status='REDUCE')).action == NO_TRADE

# ═══ NO_TRADE 是一等公民 ═══
def test_no_trade_is_explicit():
    d = eng.decide(_entry(regime_label='🔴 高波动', permission_status='NO_NEW_ENTRY',
                          permission={'new_entry':'DENY'}))
    assert d.action == NO_TRADE
    assert d.reason_codes  # 有原因，不是空输出

# ═══ Exit 归一 helper（匹配现有模拟交易退出逻辑：止损 + 移动止盈）═══
def test_norm_exit_signal():
    # 止损
    sig, trig = norm_exit_signal(-0.10, 0.05, 0.02, stop_loss=0.08)
    assert 'STOP_LOSS' in trig
    # 移动止盈（peak>=tp1 且 retrace>=peak_retrace）
    sig, trig = norm_exit_signal(0.60, 0.90, 0.10, stop_loss=0.08, tp1=0.25, peak_retrace=0.08)
    assert 'TRAILING_STOP' in trig
    # 未达移动止盈回撤阈值（retrace<0.08）→ 不触发（与现有模拟交易执行段一致）
    sig, trig = norm_exit_signal(0.85, 0.90, 0.05, stop_loss=0.08, tp1=0.25, peak_retrace=0.08)
    assert trig == []
    # 无触发
    sig, trig = norm_exit_signal(0.05, 0.05, 0.01, stop_loss=0.08)
    assert trig == []
