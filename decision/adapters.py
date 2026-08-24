#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adapters — 把现有模块输出适配成 Decision Engine 的标准输入（Phase 2）

原则：只做适配（字段映射/归一），不重算任何选股/择时/仓位/退出规则。
底层模块（double_monitor/data_filters/risk_controller/market_env/scan）
继续负责专业判断，这里把它们的输出统一成 Assessment 喂给 Decision Engine。
"""
from __future__ import annotations

from .contract import (
    ENTRY_CONFIRMED, ENTRY_INSUFFICIENT, ENTRY_NONE,
    EXIT_NONE, RISK_OK, RISK_BLOCKED, CANDIDATE_QUALIFIED, CANDIDATE_FAIL,
)


def entry_ctx(*, symbol, name='', regime_label='', regime_score=0.0, regime_version='',
              permission=None, permission_status='',
              data_health='', candidate_qualified=False, candidate_score=0.0, candidate_rank=0,
              signals=None, entry_price=0.0, target_position=0.0,
              drawdown=0.0, drawdown_limit=0.15, position_count=0, current_exposure=0.0,
              portfolio_risk=RISK_OK, portfolio_assessment=None,
              stop_loss=0.0, take_profit=None, as_of_time=''):
    """新仓候选 → Decision ctx。"""
    signals = signals or []
    return {
        'symbol': symbol, 'name': name,
        'mode': 'entry', 'has_position': False,
        'regime_label': regime_label, 'regime_score': regime_score, 'regime_version': regime_version,
        'permission': dict(permission or {}), 'permission_status': permission_status,
        'data_health': data_health,
        'candidate_qualified': candidate_qualified, 'candidate_score': candidate_score,
        'candidate_rank': candidate_rank,
        'entry_signal': ENTRY_CONFIRMED if len(signals) >= 2 else ENTRY_INSUFFICIENT,
        'entry_signals': signals,
        'reference_price': entry_price, 'target_position': target_position,
        'drawdown': drawdown, 'drawdown_limit': drawdown_limit,
        'position_count': position_count, 'current_exposure': current_exposure,
        'portfolio_risk': portfolio_risk, 'portfolio_assessment': portfolio_assessment,
        'stop_loss': stop_loss, 'take_profit': list(take_profit or []),
        'as_of_time': as_of_time,
    }


def position_ctx(*, symbol, name='', regime_label='', regime_score=0.0, regime_version='',
                 permission=None, permission_status='', data_health='',
                 exit_signal=EXIT_NONE, exit_triggers=None, forced_exit=False,
                 drawdown=0.0, position_count=0, current_exposure=0.0,
                 stop_loss=0.0, take_profit=None, trailing_stop=0.0, as_of_time='',
                 current_position=0.0, target_position=0.0,
                 portfolio_risk=RISK_OK, portfolio_assessment=None,
                 entry_signal=ENTRY_NONE, reference_price=0.0,
                 portfolio_snapshot_id='', portfolio_source='', portfolio_as_of_time=''):
    """已有持仓 → Decision ctx（Position Management：Exit/REDUCE/ADD/HOLD）。"""
    return {
        'symbol': symbol, 'name': name,
        'mode': 'position', 'has_position': True,
        'regime_label': regime_label, 'regime_score': regime_score, 'regime_version': regime_version,
        'permission': dict(permission or {}), 'permission_status': permission_status,
        'data_health': data_health,
        'exit_signal': exit_signal, 'exit_triggers': list(exit_triggers or []), 'forced_exit': forced_exit,
        'drawdown': drawdown, 'position_count': position_count, 'current_exposure': current_exposure,
        'stop_loss': stop_loss, 'take_profit': list(take_profit or []), 'trailing_stop': trailing_stop,
        'current_position': current_position, 'target_position': target_position,
        'reference_price': reference_price,
        'portfolio_risk': portfolio_risk, 'portfolio_assessment': portfolio_assessment,
        'entry_signal': entry_signal,
        'portfolio_snapshot_id': portfolio_snapshot_id,
        'portfolio_source': portfolio_source,
        'portfolio_as_of_time': portfolio_as_of_time,
        'as_of_time': as_of_time,
    }


def norm_exit_signal(ret, peak_ret, retrace, *, stop_loss=0.08, tp1=0.25, peak_retrace=0.08):
    """把 double_monitor 模拟交易段的止损/止盈数值判断归一成 Exit Assessment。

    **只匹配现有模拟交易执行逻辑（double_monitor 模拟交易段 694-715）**，不新增规则：
      - 止损: ret <= -stop_loss
      - 移动止盈(清仓): peak_ret >= tp1 且 retrace >= peak_retrace
    （注意：double_monitor 展示段有 TP2/TP3 分批 alert，但**模拟交易执行段只有止损+移动止盈**，
    不引入 TP2/TP3 直接清仓，避免改变现有行为。）

    返回 (exit_signal, exit_triggers)
    """
    triggers = []
    if ret is not None and ret <= -stop_loss:
        triggers.append('STOP_LOSS')
    if peak_ret is not None and peak_ret >= tp1 and retrace is not None and retrace >= peak_retrace:
        triggers.append('TRAILING_STOP')
    if not triggers:
        return EXIT_NONE, []
    return 'RISK' if 'STOP_LOSS' in triggers else 'NORMAL', triggers
