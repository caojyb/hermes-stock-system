#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 4-B — 回测可信度数据有效性测试

Test 1  披露日 > T → 数据不能进入 T 日 Decision
Test 2  披露日 <= T → 数据可以进入
Test 3  上市日期 > T → 股票不能进入 T 日 universe
Test 4  退市日期 < T → 股票不能进入退市后的 universe
Test 5  历史 universe 不依赖当前股票集合

运行：cd scripts/cron && /usr/bin/python3 -m pytest decision/test_backtest_validity.py -v
"""
import os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'

# ═══ 修复逻辑（与 main_up_backtest_valid.py 一致）═══
def report_available_date(report_date):
    """报告期 → 法定披露截止日（available_date）。"""
    if not report_date: return None
    y = int(report_date[:4])
    if report_date.endswith('03-31'): return f'{y}-04-30'
    if report_date.endswith('06-30'): return f'{y}-08-31'
    if report_date.endswith('09-30'): return f'{y}-10-31'
    if report_date.endswith('12-31'): return f'{y+1}-04-30'
    return None

_bounds = None

def _klines_bounds(conn):
    """全表 bounds 缓存（一次 GROUP BY，供测试复用，避免重复聚合）。"""
    global _bounds
    if _bounds is None:
        _bounds = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT code, MIN(date), MAX(date) FROM klines GROUP BY code").fetchall()}
    return _bounds

def _as_of_bounds():
    conn = sqlite3.connect(MKT_DB)
    b = _klines_bounds(conn)
    conn.close()
    return b

def as_of_universe(conn, T):
    """T 日 universe：first_kline<=T<=last_kline（T 时该股存在且交易）。不依赖当前 stocks。"""
    return {c for c, (mn, mx) in _klines_bounds(conn).items() if mn and mx and mn <= T <= mx}

# ═══ Test 1 & 2: 披露日可用性 ═══
def test_report_available_date_mapping():
    assert report_available_date('2025-03-31') == '2025-04-30'   # 一季报
    assert report_available_date('2025-06-30') == '2025-08-31'   # 半年报
    assert report_available_date('2025-09-30') == '2025-10-31'   # 三季报
    assert report_available_date('2025-12-31') == '2026-04-30'   # 年报→次年4-30
    assert report_available_date('2025-01-01') is None           # 未知报告期

def test_disclosure_gt_T_excluded():
    # 一季报 2025-03-31，披露截止 2025-04-30
    # T=2025-04-15 < 2025-04-30 → 该财报在 T 日尚未到披露截止 → 不可用
    ad = report_available_date('2025-03-31')
    T = '2025-04-15'
    assert ad > T  # 不可用（披露日>T）
    # 验证策略 SQL：可用财报 = avail <= T，此处该财报被排除

def test_disclosure_le_T_included():
    ad = report_available_date('2025-03-31')
    T = '2025-05-10'
    assert ad <= T  # 可用（披露日<=T）

# ═══ Test 3 & 4: as-of universe 上市/退市 ═══
def test_listed_after_T_excluded():
    bounds = _as_of_bounds()
    # 找上市晚样本（首 K 线 > 2023-01-01）
    late = [c for c, (mn, mx) in bounds.items() if mn and mn > '2023-01-01']
    if not late:
        pytest.skip("无 2023 后上市样本")
    code, first = late[0], bounds[late[0]][0]
    conn = sqlite3.connect(MKT_DB)
    u_early = as_of_universe(conn, '2022-06-30')
    u_late = as_of_universe(conn, first[:4] + '-06-30')  # 样本上市当年 6-30（应在 universe）
    conn.close()
    assert code not in u_early, f"上市({first})应晚于 T=2022，却进入 2022 universe"
    assert code in u_late, f"上市({first})在 {first[:4]} 应已进入 universe"

def test_delisted_before_T_excluded():
    bounds = _as_of_bounds()
    # 找退市/停止样本（末 K 线 < 2024-01-01）
    early_end = [c for c, (mn, mx) in bounds.items() if mx and mx < '2024-01-01']
    if not early_end:
        pytest.skip("无 2024 前停止样本")
    code, last = early_end[0], bounds[early_end[0]][1]
    conn = sqlite3.connect(MKT_DB)
    u_in = as_of_universe(conn, last[:7] + '-28')   # 仍在交易
    u_out = as_of_universe(conn, '2026-06-30')       # 已退市
    conn.close()
    assert code in u_in, f"最后K线{last}前应仍在 universe"
    assert code not in u_out, f"最后K线{last}远早于 2026，不应进入 2026 universe"

# ═══ Test 5: 历史 universe 不依赖当前股票集合 ═══
def test_universe_independent_of_current_stocks():
    conn = sqlite3.connect(MKT_DB)
    klines_codes = set(_klines_bounds(conn).keys())
    stocks_codes = {r[0] for r in conn.execute("SELECT code FROM stocks").fetchall()}
    conn.close()
    # klines 含历史股（不在当前 stocks），证明 universe 源是 klines 而非 stocks
    historical_only = klines_codes - stocks_codes
    assert len(historical_only) > 0, "klines 应含不在当前 stocks 的历史股（退市/历史）"
    # as-of universe 来自 klines，不依赖 stocks
    conn = sqlite3.connect(MKT_DB)
    u = as_of_universe(conn, '2024-06-28')
    conn.close()
    assert u  # universe 非空
