#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Permission Gate — 单元测试（Phase 1）

覆盖：
- 四类规定场景（正常 / 高波动 / 关键数据失败 / 持仓+NO_NEW_ENTRY）
- 权限优先级冲突裁决
- fail-open 修复（数据失败 → 不再 ALLOW 新仓）
- NO_NEW_ENTRY 不阻止退出/减仓
- classify_data_health 等级分类

运行：
  pytest test_trading_permission.py -v
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from trading_permission import (
    evaluate, classify_data_health,
    VALID, DEGRADED, INVALID, STALE, MISSING,
    ALLOW, DENY,
    STATUS_ALLOW, STATUS_REDUCE, STATUS_NO_NEW, STATUS_EXIT,
)


# ═══ 四类规定场景 ═══

def test_case1_normal_market_allows_new_entry():
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                 data_health=VALID, position_count=5, max_positions=20)
    assert r['permission']['new_entry'] == ALLOW
    assert r['permission']['add_position'] == ALLOW
    assert r['status'] == STATUS_ALLOW


def test_case2_high_volatility_not_default_allow():
    # 无持仓时：高波动必须限制新仓
    r = evaluate(regime_label='高波动', timing_safe=True, timing_ok=True,
                 data_health=VALID, position_count=0, max_positions=20)
    assert r['permission']['new_entry'] != ALLOW  # 不再无条件 ALLOW
    assert r['status'] in (STATUS_NO_NEW, STATUS_REDUCE)
    assert 'HIGH_VOLATILITY' in r['reason_codes']


def test_case3_data_failure_blocks_new_entry_but_allows_exit():
    # 关键数据失败：禁新仓/加仓，但允许减仓/退出（fail-safe，非 fail-open）
    for dh in (MISSING, INVALID):
        r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=False,
                     data_health=dh, position_count=5, max_positions=20)
        assert r['permission']['new_entry'] == DENY
        assert r['permission']['add_position'] == DENY
        assert r['permission']['reduce_position'] == ALLOW
        assert r['permission']['exit_position'] == ALLOW
        assert r['status'] == STATUS_EXIT


def test_case4_existing_position_with_no_new_entry_still_allows_exit():
    r = evaluate(regime_label='低量能', timing_safe=True, timing_ok=True,
                 data_health=VALID, position_count=3, max_positions=20,
                 has_positions=True)
    assert r['permission']['new_entry'] == DENY
    assert r['permission']['reduce_position'] == ALLOW
    assert r['permission']['exit_position'] == ALLOW
    assert r['status'] == STATUS_REDUCE


# ═══ fail-open 修复专项 ═══

def test_fail_open_reversed_timing_failure_blocks_new_entry():
    # 原 check_market_timing 数据失败 → "默认允许买入"（fail-open）
    # 修复后：timing 获取失败（timing_ok=False）→ data_health 应为 MISSING → 禁新仓
    dh = classify_data_health(timing_ok=False, kline_lag_days=0)
    assert dh == MISSING
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=False,
                 data_health=dh, position_count=0, max_positions=20)
    assert r['permission']['new_entry'] == DENY
    assert r['status'] == STATUS_EXIT


def test_fail_open_reversed_kline_invalid():
    # 个股 K 线严重滞后 → INVALID → 禁新仓
    dh = classify_data_health(timing_ok=True, kline_lag_days=10)
    assert dh == INVALID
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                 data_health=dh, position_count=0, max_positions=20)
    assert r['permission']['new_entry'] == DENY


# ═══ NO_NEW_ENTRY ≠ NO_SELL ═══

def test_no_new_entry_never_blocks_exit():
    for dh in (STALE,):
        r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                     data_health=dh, position_count=2, max_positions=20)
        assert r['permission']['new_entry'] == DENY
        assert r['permission']['exit_position'] == ALLOW
        assert r['permission']['reduce_position'] == ALLOW


# ═══ 优先级冲突裁决 ═══

def test_priority_system_critical_wins_over_allow():
    # 即使 regime=强趋势（本应 ALLOW），关键数据失败也必须胜出
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=False,
                 data_health=INVALID, position_count=0, max_positions=20)
    assert r['status'] == STATUS_EXIT
    assert r['permission']['new_entry'] == DENY


def test_priority_drawdown_beats_regime_allow():
    # 组合回撤超限 → 即使强趋势也禁新仓
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                 data_health=VALID, drawdown=0.20, drawdown_limit=0.15,
                 position_count=5, max_positions=20)
    assert r['permission']['new_entry'] == DENY
    assert r['status'] == STATUS_REDUCE
    assert 'PORTFOLIO_DRAWDOWN' in r['reason_codes']


def test_priority_timing_weak_beats_regime():
    # 大盘弱势 → 即使强趋势标签也禁新仓
    r = evaluate(regime_label='强趋势', timing_safe=False, timing_ok=True,
                 data_health=VALID, position_count=0, max_positions=20)
    assert r['permission']['new_entry'] == DENY
    assert r['status'] == STATUS_NO_NEW


# ═══ classify_data_health ═══

def test_data_health_grading():
    assert classify_data_health(timing_ok=True, kline_lag_days=0) == VALID
    assert classify_data_health(timing_ok=True, kline_lag_days=2) == DEGRADED
    assert classify_data_health(timing_ok=True, kline_lag_days=4) == STALE
    assert classify_data_health(timing_ok=True, kline_lag_days=10) == INVALID
    assert classify_data_health(timing_ok=False, kline_lag_days=0) == MISSING
    assert classify_data_health(timing_ok=True, kline_lag_days=0, signal_lag_days=2) == DEGRADED


def test_data_health_signal_lag():
    assert classify_data_health(timing_ok=True, kline_lag_days=0, signal_lag_days=0) == VALID
    assert classify_data_health(timing_ok=True, kline_lag_days=0, signal_lag_days=3) == DEGRADED


# ═══ 组合风险参与 ═══

def test_portfolio_risk_participation():
    # 组合回撤作为输入能影响 Gate（Phase 1 要求：组合风险至少可在 Gate 层发挥作用）
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                 data_health=VALID, drawdown=0.18, drawdown_limit=0.15,
                 position_count=8, max_positions=20)
    assert r['permission']['new_entry'] == DENY


def test_position_count_cap_blocks_new_entry():
    r = evaluate(regime_label='强趋势', timing_safe=True, timing_ok=True,
                 data_health=VALID, position_count=20, max_positions=20)
    assert r['permission']['new_entry'] == DENY
    assert 'MAX_POSITION_REACHED' in r['reason_codes']
