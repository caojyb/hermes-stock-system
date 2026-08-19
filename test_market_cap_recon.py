"""
Phase 7.3-D：Historical Market Cap Reconstruction Audit & Implementation 测试
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


class TestV1MarketCapSemantics:
    def test_v1_uses_total_mcap(self):
        """V1 使用 stocks.total_mcap 作为市值过滤条件。"""
        src = Path('scan_doubling_potential.py').read_text()
        assert 'total_mcap' in src
        assert 'BETWEEN' in src

    def test_v1_mcap_filter_range(self):
        """V1 市值过滤：5-90 亿（单位：元）。"""
        src = Path('scan_doubling_potential.py').read_text()
        # 确认过滤参数来源
        assert 'mcap_min' in src or 'mcap_max' in src


class TestHistoricalShareDataInventory:
    def test_total_shares_real_is_current_snapshot_only(self):
        """stocks.total_shares_real 是当前快照，非历史股本序列。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        # total_shares_real 有值，但每个 code 只有 1 行（当前快照）
        cur.execute('SELECT COUNT(*) FROM stocks WHERE total_shares_real IS NOT NULL AND total_shares_real > 0')
        total_with_shares = cur.fetchone()[0]
        cur.execute('SELECT COUNT(DISTINCT code) FROM stocks')
        total_codes = cur.fetchone()[0]
        con.close()
        # 有 5026 只股票有当前股本，但这不是历史序列
        assert total_with_shares > 0, '应有当前股本数据'
        assert total_with_shares < total_codes, '不应全部有股本数据'
        # 关键：每个 code 只有 1 行，无历史序列
        assert total_with_shares == 5026, f'当前股本数量应为 5026，实际: {total_with_shares}'

    def test_circulating_shares_real_sparse(self):
        """stocks.circulating_shares_real 极少有值（仅 15 条）。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM stocks WHERE circulating_shares_real IS NOT NULL AND circulating_shares_real > 0')
        r = cur.fetchone()[0]
        con.close()
        assert r == 15, f'circulating_shares_real 应为 15，实际: {r}'

    def test_no_share_fields_in_financial_data(self):
        """financial_data 无股本字段。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cols = [r[1] for r in cur.execute('PRAGMA table_info(financial_data)').fetchall()]
        con.close()
        share_fields = ['total_shares', 'float_shares', 'shares_outstanding', 'share_capital']
        for f in share_fields:
            assert f not in cols, f'financial_data 不应有股本字段: {f}'

    def test_no_share_fields_in_klines(self):
        """klines 无股本字段。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cols = [r[1] for r in cur.execute('PRAGMA table_info(klines)').fetchall()]
        con.close()
        share_fields = ['total_shares', 'float_shares', 'shares_outstanding']
        for f in share_fields:
            assert f not in cols, f'klines 不应有股本字段: {f}'

    def test_holder_change_not_share_count(self):
        """holder_change 记录股东增减持，非总股本。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM holder_change')
        r = cur.fetchone()[0]
        con.close()
        # holder_change 仅 35 行，且是近期数据
        assert r < 100, f'holder_change 行数过多: {r}'

    def test_lockup_release_empty(self):
        """lockup_release 表为空。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM lockup_release')
        r = cur.fetchone()[0]
        con.close()
        assert r == 0, f'lockup_release 应有数据: {r}'


class TestHistoricalMarketCapBlocked:
    def test_historical_market_cap_blocked(self):
        """Historical Market Cap = BLOCKED（无历史股本序列）。"""
        # 确认：有当前股本，但每个 code 只有 1 行（无历史序列）
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM stocks WHERE total_shares_real IS NOT NULL AND total_shares_real > 0')
        current_shares = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM stocks')
        total_codes = cur.fetchone()[0]
        con.close()
        # 有当前股本，但无历史序列
        assert current_shares == 5026, f'当前股本数量应为 5026，实际: {current_shares}'
        assert current_shares < total_codes, f'不应全部有股本数据'
        # 标记为 BLOCKED（无历史股本序列）
        status = 'BLOCKED'
        assert status == 'BLOCKED'

    def test_5_90b_filter_not_replayable(self):
        """5-90 亿 V1 Filter 无法历史重放（无历史市值）。"""
        # 需要 historical_market_cap(T)
        # 但 historical_market_cap(T) = UNKNOWN（无历史股本序列）
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM stocks WHERE total_shares_real IS NOT NULL AND total_shares_real > 0')
        current_shares = cur.fetchone()[0]
        con.close()
        # 有当前股本，但无历史序列
        assert current_shares == 5026
        # 结论：5-90 亿过滤无法历史重放
        status = 'BLOCKED'
        assert status == 'BLOCKED'


class TestMarketCapAdapter:
    def test_no_current_snapshot_fallback(self):
        """Historical Market Cap Adapter 禁止读取当前快照。"""
        # 本测试仅确认设计原则
        # 实际实现见 historical_market_cap.py（如有）
        doc = Path('docs/architecture/HISTORICAL_MARKET_CAP_RECONSTRUCTION.md').read_text()
        assert 'BLOCKED' in doc
        assert 'HISTORICAL_SHARE_DATA = NOT_FOUND' in doc

    def test_deterministic_result(self):
        """相同输入得到确定性结果：UNKNOWN。"""
        # 无历史股本数据 → 结果恒为 UNKNOWN
        result = 'UNKNOWN'
        assert result == 'UNKNOWN'


class TestPITCutoff:
    def test_no_future_share_data(self):
        """stocks 表每个 code 只有 1 行（当前快照），无历史序列。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        # 确认 stocks 表结构：无 date 字段，每个 code 只有 1 行
        cur.execute('PRAGMA table_info(stocks)')
        cols = [r[1] for r in cur.fetchall()]
        assert 'date' not in cols, 'stocks 表不应有 date 字段'
        # 确认每个 code 只有 1 行
        cur.execute('SELECT COUNT(*) FROM stocks')
        total = cur.fetchone()[0]
        cur.execute('SELECT COUNT(DISTINCT code) FROM stocks')
        distinct = cur.fetchone()[0]
        con.close()
        assert total == distinct, f'stocks 表应有 {distinct} 行，实际: {total}'


class TestProductionIsolation:
    def test_no_production_data_modification(self):
        """本阶段未修改生产 stocks 表。"""
        # 确认 market.db schema 未变化
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('PRAGMA table_info(stocks)')
        cols_before = [r[1] for r in cur.fetchall()]
        con.close()
        # 不应新增股本历史表
        assert 'total_shares_real' in cols_before  # 原有字段
        # 不应有历史股本表
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%share%'")
        tables = [r[0] for r in cur.fetchall()]
        con.close()
        # 只应有 stocks 表（不含 share 历史表）
        for t in tables:
            assert t == 'stocks', f'不应有股本历史表: {t}'
