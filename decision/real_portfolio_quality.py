#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Holdings Data Quality Guard（Phase 8-H2）

只读检查，不修改数据，不自动修正。
输出 quality_flags 列表。
"""
from __future__ import annotations

import json
from pathlib import Path


def _check_holding_quality(holding: dict) -> dict:
    """检查单条持仓的数据质量。"""
    symbol = holding.get('symbol') or holding.get('code') or 'UNKNOWN'
    name = holding.get('name', '')
    avg_cost = holding.get('avg_cost')
    current_price = holding.get('current_price')
    quantity = holding.get('quantity')

    checks = []

    # avg_cost
    if avg_cost is None:
        checks.append({'field': 'avg_cost', 'level': 'WARNING', 'reason': 'MISSING'})
    elif avg_cost <= 0:
        checks.append({'field': 'avg_cost', 'level': 'ERROR', 'reason': 'NON_POSITIVE', 'value': avg_cost})
    else:
        # ratio check
        if current_price is not None and current_price > 0:
            ratio = avg_cost / current_price
            if ratio > 5:
                checks.append({'field': 'avg_cost', 'level': 'WARNING', 'reason': 'OUTLIER', 'detail': f'avg_cost={avg_cost}, current_price={current_price}, ratio={ratio:.2f}'})
            elif ratio < 0.2:
                checks.append({'field': 'avg_cost', 'level': 'WARNING', 'reason': 'OUTLIER', 'detail': f'avg_cost={avg_cost}, current_price={current_price}, ratio={ratio:.2f}'})

    # current_price
    if current_price is None:
        checks.append({'field': 'current_price', 'level': 'WARNING', 'reason': 'MISSING'})
    elif current_price <= 0:
        checks.append({'field': 'current_price', 'level': 'ERROR', 'reason': 'NON_POSITIVE', 'value': current_price})

    # quantity
    if quantity is None:
        checks.append({'field': 'quantity', 'level': 'WARNING', 'reason': 'MISSING'})
    elif quantity <= 0:
        checks.append({'field': 'quantity', 'level': 'ERROR', 'reason': 'NON_POSITIVE', 'value': quantity})
    elif quantity % 100 != 0:
        checks.append({'field': 'quantity', 'level': 'WARNING', 'reason': 'NON_INTEGER', 'detail': f'quantity={quantity}, A股最小单位=100'})

    overall = 'OK'
    if any(c['level'] == 'ERROR' for c in checks):
        overall = 'ERROR'
    elif any(c['level'] == 'WARNING' for c in checks):
        overall = 'WARNING'

    return {
        'symbol': symbol,
        'name': name,
        'checks': checks,
        'overall': overall,
    }


def check_portfolio_quality(holdings: list[dict]) -> dict:
    """
    对整组持仓执行数据质量检查。
    输入：holdings list（来自 _read_bitable_holdings 或 build_real_snapshot().get('holdings')）
    输出：{
        'overall': 'OK'|'WARNING'|'ERROR',
        'flags': [...],
        'error_count': n,
        'warning_count': n
    }
    """
    flags = []
    error_count = 0
    warning_count = 0
    for h in holdings:
        result = _check_holding_quality(h)
        for c in result.get('checks', []):
            flags.append({
                'symbol': result.get('symbol'),
                'name': result.get('name'),
                'field': c.get('field'),
                'level': c.get('level'),
                'reason': c.get('reason'),
                'detail': c.get('detail'),
            })
            if c['level'] == 'ERROR':
                error_count += 1
            elif c['level'] == 'WARNING':
                warning_count += 1

    overall = 'OK'
    if error_count > 0:
        overall = 'ERROR'
    elif warning_count > 0:
        overall = 'WARNING'

    return {
        'overall': overall,
        'flags': flags,
        'error_count': error_count,
        'warning_count': warning_count,
    }


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else '/home/caojy/.hermes/scripts/cron/decision/test_real_holdings_h2.py'
    print(f"quality_guard module loaded: {Path(path).name}")
