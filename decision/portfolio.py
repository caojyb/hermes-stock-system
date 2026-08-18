#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Assessment — 组合风险评估（Phase 3）

把系统**现有**的组合限制统一成一个 Portfolio Assessment（Assessment/Constraint），
在 BUY 前进入 DecisionEngine，可否决单票 BUY。

原则：不新增组合风控规则，只把已有参数（MAX_POSITION/MAX_SECTOR_CNT/持仓上限/
drawdown/流动性/冷却）统一解释。不重算选股/Entry/Exit/Regime/Permission。
本模块纯逻辑，不连库；数据由调用方采集传入。
"""
from __future__ import annotations

# 状态
OK = 'OK'
BLOCK = 'BLOCK'

# reason codes（与 contract.REASON 对齐）
RC_DRAWDOWN = 'DRAWDOWN_BLOCKED'
RC_DRAWDOWN_UNKNOWN = 'DRAWDOWN_UNKNOWN'
RC_MAX_POS = 'MAX_POSITION_EXCEEDED'
RC_SECTOR = 'SECTOR_LIMIT_EXCEEDED'
RC_COUNT = 'MAX_POSITION_REACHED'
RC_LIQUIDITY = 'LIQUIDITY_BLOCKED'
RC_COOLDOWN = 'COOLDOWN'
RC_EXPOSURE = 'EXPOSURE_BLOCKED'
RC_PORTFOLIO = 'PORTFOLIO_RISK_BLOCKED'


def assess_portfolio(*, candidate_sector='', target_position=0.0, total_capital=1_000_000,
                     position_count=0, max_positions=20,
                     max_position_pct=0.05, max_sector_cnt=3,
                     sector_counts=None,        # dict sector -> 现有持仓数
                     drawdown=None, drawdown_limit=0.15,
                     drawdown_status='KNOWN',   # KNOWN/UNKNOWN（Phase 5.5：真实仓历史峰值缺失）
                     liquidity_ok=True, cooldown_active=False,
                     total_exposure=None, exposure_limit=None):
    """统一评估组合是否允许承担这笔新仓。

    返回 dict: {allowed, action, drawdown, drawdown_status, total_exposure, position_count,
                sector_exposure, single_position_exposure, liquidity, cooldown,
                risk_flags, reason_codes}
    """
    reasons = []
    sector_counts = sector_counts or {}

    # 1. 组合回撤（现有 15% 线；UNKNOWN = 历史峰值缺失，fail-safe 不放行新仓）
    if drawdown_status == 'UNKNOWN':
        reasons.append(RC_DRAWDOWN_UNKNOWN)
    elif drawdown is not None and drawdown_limit and drawdown >= drawdown_limit:
        reasons.append(RC_DRAWDOWN)

    # 2. 持仓数量上限（现有 20）
    if position_count >= max_positions:
        reasons.append(RC_COUNT)

    # 3. 单股上限 MAX_POSITION（现有 5%）：target 不得超过单股上限
    if target_position > 0 and max_position_pct > 0:
        if target_position > max_position_pct * total_capital:
            reasons.append(RC_MAX_POS)

    # 4. 行业上限 MAX_SECTOR_CNT（现有 3）：候选行业 + 现有同行业持仓
    if candidate_sector:
        if sector_counts.get(candidate_sector, 0) >= max_sector_cnt:
            reasons.append(RC_SECTOR)

    # 5. 流动性（现有能力）
    if not liquidity_ok:
        reasons.append(RC_LIQUIDITY)

    # 6. 冷却期（现有能力）
    if cooldown_active:
        reasons.append(RC_COOLDOWN)

    # 7. 总暴露（若现有暴露限制已定义）
    if total_exposure is not None and exposure_limit and total_exposure > exposure_limit:
        reasons.append(RC_EXPOSURE)

    allowed = len(reasons) == 0
    action = OK if allowed else BLOCK
    if not allowed:
        reasons.insert(0, RC_PORTFOLIO)  # 顶层标记

    return {
        'allowed': allowed,
        'action': action,
        'drawdown': drawdown,
        'drawdown_status': drawdown_status,
        'total_exposure': total_exposure,
        'position_count': position_count,
        'sector_exposure': sector_counts,
        'single_position_exposure': round(target_position / total_capital, 4) if total_capital else 0,
        'liquidity': 'OK' if liquidity_ok else 'BLOCKED',
        'cooldown': cooldown_active,
        'risk_flags': list(dict.fromkeys(reasons)),
        'reason_codes': list(dict.fromkeys(reasons)),
    }
