#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Permission Gate — 统一交易权限判定（Phase 1）

职责：把系统"已有"的状态（Market Regime / Market Timing / Data Health /
Portfolio Risk / Existing Position）统一解释成交易权限，输出
new_entry / add_position / reduce_position / exit_position 四位的
ALLOW/DENY 与顶层 status（ALLOW/REDUCE/NO_NEW_ENTRY/EXIT_ONLY）。

原则（不新增第二套规则）：
- 不重算市场环境 / 风险 / 选股 / 买点，只统一解释已有状态。
- 关键决策数据无法确认安全 → 不得放行新开仓（fail-safe）。
- NO_NEW_ENTRY ≠ NO_SELL：禁止"禁开仓"时连带"禁退出"。
- 冲突裁决由显式优先级决定，不依赖代码执行顺序偶然性。

本模块为纯逻辑（不连数据库），便于单元测试；数据采集由调用方完成并传入。
"""
from __future__ import annotations

# ── 数据健康等级 ──
VALID = 'VALID'
DEGRADED = 'DEGRADED'
INVALID = 'INVALID'
STALE = 'STALE'
MISSING = 'MISSING'

# ── 四位权限值 ──
ALLOW = 'ALLOW'
DENY = 'DENY'

# ── 顶层状态 ──
STATUS_ALLOW = 'ALLOW'
STATUS_REDUCE = 'REDUCE'
STATUS_NO_NEW = 'NO_NEW_ENTRY'
STATUS_EXIT = 'EXIT_ONLY'

# ── 权限优先级（高→低）。冲突时取最高优先级触发的状态 ──
_PRIORITY_ORDER = [
    'SYSTEM_CRITICAL',      # 1 系统/关键数据严重失败
    'FORCED_EXIT',          # 2 强制退出/关键风险
    'EXIT_ONLY',            # 3 只允许退出
    'NO_NEW_ENTRY',         # 4 禁止新开仓
    'REDUCE',               # 5 只减不加
    'ALLOW',                # 6 正常
]

# Regime 标签 → 对 new_entry/add_position 的意向
# 注意：这里只定义"环境对开仓的倾向"，最终结果还要与 timing/data/组合 叠加
_REGIME_NEW_ENTRY = {
    '强趋势': ALLOW,
    '震荡市': ALLOW,
    '高波动': DENY,
    '低量能': DENY,
}
_REGIME_ADD_POSITION = {
    '强趋势': ALLOW,
    '震荡市': DENY,
    '高波动': DENY,
    '低量能': DENY,
}


def classify_data_health(*, timing_ok, kline_lag_days, signal_lag_days=None,
                         timing_has_data=True):
    """从采集的原始指标归类数据健康等级。

    Args:
        timing_ok:      market timing（沪深300）数据是否成功获取。
        kline_lag_days: 个股 K 线相对最近交易日的滞后天数。
        signal_lag_days: indicators 信号相对最近交易日的滞后天数（可空）。
        timing_has_data: 大盘 timing 是否至少有历史 K 线（MA20 计算基础）。
    Returns:
        VALID / DEGRADED / INVALID / STALE / MISSING
    """
    # 关键数据：大盘 timing 拉取失败或无线 → MISSING（fail-safe）
    if not timing_ok or not timing_has_data:
        return MISSING
    # K 线严重滞后 → INVALID（信号/价格都不可信，无法确认安全）
    if kline_lag_days is None or kline_lag_days > 5:
        return INVALID
    # K 线明显滞后（>3 交易日）→ STALE
    if kline_lag_days > 3:
        return STALE
    # K 线滞后 1-2 日 → DEGRADED（数据可能未完全刷新，但仍可用）
    if kline_lag_days > 1:
        return DEGRADED
    # 信号滞后单独考虑：信号比 K 线旧 1 日以上 → DEGRADED
    if signal_lag_days is not None and signal_lag_days > 1:
        return DEGRADED
    return VALID


def _match_regime(label):
    """从环境标签提取标准 regime 名（容忍 emoji/前后缀）。找不到返回 None。"""
    if not label:
        return None
    for key in _REGIME_NEW_ENTRY:
        if key in label:
            return key
    return None


def evaluate(*, regime_label=None, regime_scale=None,
             timing_safe=None, timing_ok=None,
             data_health=None,
             drawdown=None, drawdown_limit=0.15,
             position_count=0, max_positions=20,
             has_positions=None, critical_exit=False):
    """主入口：输入已有状态 → 输出交易权限。

    这是唯一权限裁决函数。所有输入由调用方采集传入（本函数不连库）。

    Returns:
        dict: {
          'permission': {'new_entry':ALLOW|DENY, 'add_position':..., 'reduce_position':..., 'exit_position':...},
          'status': ALLOW|REDUCE|NO_NEW_ENTRY|EXIT_ONLY,
          'reason_codes': [str, ...],
          'priority': 触发的高优先级标签,
        }
    """
    reasons = []
    # 默认（无持仓时）四个位
    perm = {
        'new_entry': DENY,
        'add_position': DENY,
        'reduce_position': ALLOW,
        'exit_position': ALLOW,
    }
    # has_positions 未给定时，用 position_count 推断
    if has_positions is None:
        has_positions = position_count > 0

    # ── 优先级 1：System/Data Critical Failure → EXIT_ONLY ──
    if critical_exit or data_health in (INVALID, MISSING):
        status = STATUS_EXIT
        reasons.append('SYSTEM_CRITICAL' if critical_exit else 'DATA_' + data_health)
        # 关键数据失败：禁新仓/加仓，但绝不阻止退出与减仓
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        # reduce/exit 保持 ALLOW（保护既有持仓）
        return _finalize(perm, status, reasons, 'SYSTEM_CRITICAL')

    # ── 数据 STALE → NO_NEW_ENTRY（但允许退出）──
    if data_health == STALE:
        status = STATUS_NO_NEW
        reasons.append('DATA_STALE')
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        return _finalize(perm, status, reasons, 'NO_NEW_ENTRY')

    # ── 优先级 2/3：组合回撤 → REDUCE（或更严，视严重度）──
    if drawdown is not None and drawdown_limit and drawdown >= drawdown_limit:
        status = STATUS_REDUCE
        reasons.append('PORTFOLIO_DRAWDOWN')
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        perm['reduce_position'] = ALLOW
        return _finalize(perm, status, reasons, 'REDUCE')

    # ── 优先级：Market Timing（大盘弱势）→ NO_NEW_ENTRY ──
    # 注意：timing 失败(fail-open 修复)已在 data_health=MISSING 时处理，这里只处理明确弱势
    if timing_ok and timing_safe is False:
        status = STATUS_NO_NEW
        reasons.append('MARKET_TIMING_WEAK')
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        return _finalize(perm, status, reasons, 'NO_NEW_ENTRY')

    # ── Regime 影响 new_entry / add_position ──
    regime = _match_regime(regime_label)
    if regime is None:
        # 环境未知：不明确放行新仓（保守），但允许退出
        status = STATUS_NO_NEW if not has_positions else STATUS_REDUCE
        reasons.append('REGIME_UNKNOWN')
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        return _finalize(perm, status, reasons, 'NO_NEW_ENTRY')

    # 明确 regime
    perm['new_entry'] = _REGIME_NEW_ENTRY.get(regime, DENY)
    perm['add_position'] = _REGIME_ADD_POSITION.get(regime, DENY)
    if regime in ('高波动', '低量能'):
        reasons.append('HIGH_VOLATILITY' if regime == '高波动' else 'LOW_VOLUME')
        # 无持仓 → 禁新仓；有持仓 → 可持有但只减不加
        status = STATUS_NO_NEW if not has_positions else STATUS_REDUCE
    elif regime == '震荡市':
        reasons.append('SIDEWAYS')
        status = STATUS_ALLOW  # 允许开新仓（new_entry=ALLOW），但不加仓
    else:  # 强趋势
        reasons.append('STRONG_TREND')
        status = STATUS_ALLOW

    # ── 持仓数量上限 → 禁新仓 ──
    if perm['new_entry'] == ALLOW and position_count >= max_positions:
        perm['new_entry'] = DENY
        perm['add_position'] = DENY
        reasons.append('MAX_POSITION_REACHED')
        if status == STATUS_ALLOW:
            status = STATUS_REDUCE if has_positions else STATUS_NO_NEW

    # ── 数据 DEGRADED：弱化新仓（REDUCE 或保持 ALLOW 取决于严重度）──
    # 仅当上面没有更高优先级触发时，DEGRADED 把 ALLOW 降为 REDUCE 级（少开）
    if data_health == DEGRADED and status == STATUS_ALLOW:
        reasons.append('DATA_DEGRADED')
        # 新仓仍允许（数据可用），但记为 REDUCE 语义（提示谨慎）
        status = STATUS_REDUCE if has_positions else STATUS_ALLOW

    return _finalize(perm, status, reasons, status if status in _PRIORITY_ORDER else 'ALLOW')


def _finalize(perm, status, reasons, priority):
    return {
        'permission': perm,
        'status': status,
        'reason_codes': list(dict.fromkeys(reasons)),  # 去重保序
        'priority': priority,
    }


if __name__ == '__main__':
    import json
    # 简单自测
    cases = [
        ('Case1 正常', dict(regime_label='强趋势', timing_safe=True, timing_ok=True, data_health=VALID, position_count=5, max_positions=20)),
        ('Case2 高波动', dict(regime_label='高波动', timing_safe=True, timing_ok=True, data_health=VALID, position_count=0, max_positions=20)),
        ('Case3 数据失败', dict(regime_label='强趋势', timing_safe=True, timing_ok=False, data_health=MISSING, position_count=5, max_positions=20)),
        ('Case4 持仓+禁新', dict(regime_label='低量能', timing_safe=True, timing_ok=True, data_health=VALID, position_count=3, max_positions=20, has_positions=True)),
    ]
    for name, kw in cases:
        r = evaluate(**kw)
        print(f"{name}: status={r['status']} perm={r['permission']} reasons={r['reason_codes']}")
