#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Position Sizing（Phase 7.5）
================================
将 Simulation Position Sizing 正确应用到 Real Portfolio Context。

输入：
- total_asset
- current_market_value
- cash
- target_position_pct
- reference_price
- lot_size（A 股默认 100）

输出：
- current_position_pct
- target_position_pct
- target_value
- target_quantity
- delta_value
- delta_quantity
- sizing_status：READY / PARTIAL / BLOCKED

Fail-safe：
- total_asset = UNKNOWN → BUY/ADD BLOCKED，SELL/REDUCE 不受影响
"""
from __future__ import annotations

VALID, STALE, PARTIAL, MISSING, UNKNOWN = 'VALID', 'STALE', 'PARTIAL', 'MISSING', 'UNKNOWN'
READY, BLOCKED = 'READY', 'BLOCKED'
BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE = 'BUY', 'SELL', 'HOLD', 'REDUCE', 'ADD', 'NO_TRADE'
ALLOW, DENY = 'ALLOW', 'DENY'


def compute_real_position_sizing(
    total_asset: float | None,
    current_market_value: float,
    cash: float | None,
    target_position_pct: float,
    reference_price: float,
    lot_size: int = 100,
    max_position_pct: float = 0.05,
) -> dict:
    """
    真实仓 Position Sizing。

    返回：
    {
      current_position_pct,
      target_position_pct,
      target_value,
      target_quantity,
      delta_value,
      delta_quantity,
      sizing_status,
      block_reason,
    }
    """
    current_position_pct = 0.0
    if total_asset and total_asset > 0:
        current_position_pct = current_market_value / total_asset

    target_value = 0.0
    target_quantity = 0
    delta_value = 0.0
    delta_quantity = 0
    sizing_status = READY
    block_reason = ''

    if total_asset is None or total_asset <= 0:
        sizing_status = BLOCKED
        block_reason = 'TOTAL_ASSET_UNKNOWN'
        target_value = None
        target_quantity = None
        delta_value = None
        delta_quantity = None
    else:
        target_value = total_asset * target_position_pct
        if reference_price and reference_price > 0:
            target_quantity = int(target_value / reference_price / lot_size) * lot_size
        else:
            target_quantity = 0
        delta_value = target_value - current_market_value
        if reference_price and reference_price > 0:
            delta_quantity = int(delta_value / reference_price / lot_size) * lot_size
        else:
            delta_quantity = 0
        if target_quantity < 0:
            delta_quantity = -min(abs(delta_quantity), abs(int(current_market_value / reference_price / lot_size) * lot_size))

    return {
        'current_position_pct': round(current_position_pct, 6),
        'target_position_pct': round(target_position_pct, 6),
        'target_value': round(target_value, 2) if isinstance(target_value, float) else target_value,
        'target_quantity': target_quantity,
        'delta_value': round(delta_value, 2) if isinstance(delta_value, float) else delta_value,
        'delta_quantity': delta_quantity,
        'sizing_status': sizing_status,
        'block_reason': block_reason,
    }


def check_sizing_for_action(
    action: str,
    total_asset: float | None,
    current_market_value: float,
    cash: float | None,
    target_position_pct: float,
    reference_price: float,
    lot_size: int = 100,
    max_position_pct: float = 0.05,
) -> dict:
    """
    根据 Action 检查 sizing 是否允许。

    BUY / ADD：
    - total_asset = UNKNOWN → BLOCKED
    - target_quantity <= 0 → BLOCKED（无法执行）

    SELL / REDUCE：
    - total_asset = UNKNOWN → 允许（必要退出不被阻止）
    - 但需要 current_market_value > 0 才能计算可卖数量

    HOLD / NO_TRADE：
    - 不依赖 sizing
    """
    sizing = compute_real_position_sizing(
        total_asset=total_asset,
        current_market_value=current_market_value,
        cash=cash,
        target_position_pct=target_position_pct,
        reference_price=reference_price,
        lot_size=lot_size,
        max_position_pct=max_position_pct,
    )

    allowed = True
    block_reason = sizing['block_reason']

    if action in (BUY, ADD):
        if sizing['sizing_status'] == BLOCKED:
            allowed = False
        elif sizing['target_quantity'] is None or sizing['target_quantity'] <= 0:
            allowed = False
            block_reason = 'TARGET_QUANTITY_ZERO'

    if action in (SELL, REDUCE):
        if sizing['target_quantity'] is None:
            # total_asset unknown 不阻止 SELL，但数量无法精确计算
            sizing['target_quantity'] = 0
            sizing['delta_quantity'] = 0
            sizing['sizing_status'] = PARTIAL
            block_reason = 'TOTAL_ASSET_UNKNOWN_QUANTITY_UNCLEAR'

    sizing['action_allowed'] = allowed
    sizing['action'] = action
    sizing['block_reason'] = block_reason
    return sizing


if __name__ == '__main__':
    import json as _j

    # Case A: 正常
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=4_000, cash=500_000,
                                     target_position_pct=0.025, reference_price=10.0)
    print('=== Case A ===')
    print(_j.dumps(r, ensure_ascii=False, indent=2))

    # Case D: total_asset unknown
    r2 = check_sizing_for_action(action='BUY', total_asset=None, current_market_value=4_000, cash=None,
                                 target_position_pct=0.025, reference_price=10.0)
    print('\n=== Case D (BUY, unknown total_asset) ===')
    print(_j.dumps(r2, ensure_ascii=False, indent=2))

    # Case G: SELL with unknown total_asset
    r3 = check_sizing_for_action(action='SELL', total_asset=None, current_market_value=4_000, cash=None,
                                 target_position_pct=0.0, reference_price=10.0)
    print('\n=== Case G (SELL, unknown total_asset) ===')
    print(_j.dumps(r3, ensure_ascii=False, indent=2))
