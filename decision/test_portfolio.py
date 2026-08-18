#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 — Portfolio Decision Layer 测试

覆盖 Case A-F + Portfolio Assessment 单元：
A. 正常 BUY（Portfolio PASS）
B. 组合回撤≥15% → NO_TRADE
C. 超过单股上限 → 不出现超 MAX_POSITION 的 BUY target
D. 行业达上限 → NO_TRADE
E. 已有持仓止损，即使 new_entry=DENY+portfolio=BLOCK → SELL（组合不阻 SELL）
F. 组合风险与 Entry 冲突 → reason_codes 可解释

运行：
  cd scripts/cron && /usr/bin/python3 -m pytest decision/test_portfolio.py -v
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest
from decision.engine import DecisionEngine
from decision.adapters import entry_ctx, position_ctx
from decision.portfolio import assess_portfolio
from decision.contract import BUY, HOLD, SELL, NO_TRADE

eng = DecisionEngine(strategy='v1_double', config_version='test', code_version='p3')

def _buy(regime='🟢 强趋势', perm_status='ALLOW', perm_new='ALLOW', data='VALID',
         pa=None, pa_risk='OK', drawdown=0, **kw):
    base = dict(symbol='000001', name='x', regime_label=regime, regime_score=80,
                permission={'new_entry': perm_new, 'add_position': 'ALLOW',
                            'reduce_position': 'ALLOW', 'exit_position': 'ALLOW'},
                permission_status=perm_status, data_health=data,
                candidate_qualified=True, candidate_score=75,
                entry_signal='CONFIRMED', entry_signals=['A', 'B', 'D'],
                reference_price=10.0, target_position=12500,
                drawdown=drawdown, drawdown_limit=0.15, position_count=0,
                portfolio_risk=pa_risk, portfolio_assessment=pa,
                stop_loss=0.08, take_profit=[0.25, 0.5, 0.8])
    base.update(kw)
    return base

# ═══ Portfolio Assessment 单元 ═══
def test_pa_ok():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'电子': 2}, drawdown=0.05)
    assert pa['allowed'] is True
    assert pa['action'] == 'OK'

def test_pa_drawdown_blocked():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.18, drawdown_limit=0.15)
    assert pa['allowed'] is False
    assert 'DRAWDOWN_BLOCKED' in pa['reason_codes']

def test_pa_max_position_exceeded():
    # 单股 target 超过 MAX_POSITION(5%) → 明确 BLOCK
    pa = assess_portfolio(candidate_sector='电子', target_position=80_000, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.05)
    assert pa['allowed'] is False
    assert 'MAX_POSITION_EXCEEDED' in pa['reason_codes']

def test_pa_sector_limit():
    # 候选行业已有 3 只（达 MAX_SECTOR_CNT=3）→ BLOCK
    pa = assess_portfolio(candidate_sector='医药', target_position=12500, total_capital=1_000_000,
                          position_count=10, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'医药': 3}, drawdown=0.05)
    assert pa['allowed'] is False
    assert 'SECTOR_LIMIT_EXCEEDED' in pa['reason_codes']

def test_pa_position_count():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=20, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.05)
    assert pa['allowed'] is False
    assert 'MAX_POSITION_REACHED' in pa['reason_codes']

def test_pa_liquidity_cooldown():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.05,
                          liquidity_ok=False)
    assert 'LIQUIDITY_BLOCKED' in pa['reason_codes']
    pa2 = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                           position_count=5, max_positions=20, max_position_pct=0.05,
                           max_sector_cnt=3, sector_counts={}, drawdown=0.05, cooldown_active=True)
    assert 'COOLDOWN' in pa2['reason_codes']

# ═══ Case A：正常 BUY ═══
def test_caseA_normal_buy():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'电子': 2}, drawdown=0.05)
    d = eng.decide(_buy(pa=pa, pa_risk='OK'))
    assert d.action == BUY

# ═══ Case B：组合回撤≥15% → NO_TRADE ═══
def test_caseB_drawdown_blocked():
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.18, drawdown_limit=0.15)
    d = eng.decide(_buy(pa=pa, pa_risk='BLOCKED', drawdown=0.18))
    assert d.action == NO_TRADE
    assert 'DRAWDOWN_BLOCKED' in d.reason_codes or 'PORTFOLIO_RISK_BLOCKED' in d.reason_codes

# ═══ Case C：超过单股上限 → 不出现超 MAX_POSITION 的 BUY ═══
def test_caseC_max_position_not_buy():
    pa = assess_portfolio(candidate_sector='电子', target_position=80_000, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.05)
    # target 80k = 8% > MAX_POSITION 5% → BLOCK，不产生 BUY
    assert pa['allowed'] is False
    d = eng.decide(_buy(pa=pa, pa_risk='BLOCKED', target_position=80000))
    assert d.action == NO_TRADE
    assert 'MAX_POSITION_EXCEEDED' in d.reason_codes

# ═══ Case D：行业达上限 → NO_TRADE ═══
def test_caseD_sector_limit():
    pa = assess_portfolio(candidate_sector='医药', target_position=12500, total_capital=1_000_000,
                          position_count=10, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'医药': 3}, drawdown=0.05)
    d = eng.decide(_buy(pa=pa, pa_risk='BLOCKED'))
    assert d.action == NO_TRADE
    assert 'SECTOR_LIMIT_EXCEEDED' in d.reason_codes

# ═══ Case E：组合不阻止必要 SELL ═══
def test_caseE_portfolio_never_blocks_sell():
    # new_entry=DENY + portfolio=BLOCK，但已有持仓止损 → 仍 SELL
    d = eng.decide(position_ctx(symbol='000003', name='x', regime_label='🔴 高波动',
                                permission={'new_entry': 'DENY'}, permission_status='NO_NEW_ENTRY',
                                data_health='VALID', exit_signal='RISK', exit_triggers=['STOP_LOSS'],
                                position_count=5))
    assert d.action == SELL

# ═══ Case F：组合风险与 Entry 冲突 → reason_codes 解释 ═══
def test_caseF_conflict_explained():
    # Entry 通过但组合回撤 BLOCK → NO_TRADE，reason 解释为什么
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.20, drawdown_limit=0.15)
    d = eng.decide(_buy(pa=pa, pa_risk='BLOCKED', drawdown=0.20, entry_signal='CONFIRMED',
                        entry_signals=['A','B','D']))
    assert d.action == NO_TRADE
    # 必须解释为什么没 BUY
    assert d.reason_codes, "reason_codes 不能为空"
    joined = ','.join(d.reason_codes)
    assert any(k in joined for k in ('PORTFOLIO', 'DRAWDOWN')), f"应含组合原因: {joined}"

# ═══ 组合前置 vs 事后：Portfolio Assessment 必须进 Decision 且可否决 ═══
def test_portfolio_enters_decision():
    # 即使 permission ALLOW + entry confirmed + candidate pass，portfolio BLOCK → NO_TRADE
    pa = assess_portfolio(candidate_sector='电子', target_position=12500, total_capital=1_000_000,
                          position_count=5, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={}, drawdown=0.18)
    d = eng.decide(_buy(pa=pa, pa_risk='BLOCKED', drawdown=0.18,
                        perm_status='ALLOW', perm_new='ALLOW'))
    assert d.action == NO_TRADE  # 组合在 BUY 前否决
