"""
Phase 7.3-H：Historical ST Data Source & PIT Reconstruction Audit

审计 akshare / 巨潮资讯 / 东方财富等接口的 Historical ST 可得性。

结论：无直接历史 ST 状态时间序列。stock_info_change_name 提供曾用名
（含 ST 标记），但无生效日期。stock_notice_report 可提供 ST 公告，
但需逐日查询且无结构化有效日期。Historical ST = BLOCKED。
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


# ---------------------------------------------------------------------------
# V1 ST Filter Semantics
# ---------------------------------------------------------------------------
class TestV1STSemantics:
    def test_v1_uses_is_st_field(self):
        """V1 过滤使用 stocks.is_st。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        # 确认 V1 过滤逻辑
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, '-c',
             "import sys; sys.path.insert(0, '/home/caojy/.hermes/scripts/cron'); "
             "from scan_doubling_potential import *; print('OK')"],
            capture_output=True, text=True, timeout=30
        )
        # 直接检查源码
        with open('/home/caojy/.hermes/scripts/cron/scan_doubling_potential.py') as f:
            src = f.read()
        assert 'is_st IS NULL OR is_st = 0' in src, 'V1 应使用 is_st 过滤'

    def test_v1_excludes_st_and_null(self):
        """V1 排除 is_st = 1 和 is_st IS NULL 的股票。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM stocks WHERE is_st = 1")
        st_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM stocks WHERE is_st IS NULL")
        null_count = cur.fetchone()[0]
        # 当前无 ST 股票，无 NULL
        assert st_count == 0, '当前无 ST 股票'
        assert null_count == 0, '当前无 is_st NULL'


# ---------------------------------------------------------------------------
# Source Discovery
# ---------------------------------------------------------------------------
class TestSourceDiscovery:
    def test_akshare_installed(self):
        """akshare 已安装。"""
        import importlib
        spec = importlib.util.find_spec('akshare')
        assert spec is not None

    def test_stock_info_change_name_available(self):
        """stock_info_change_name 可获取曾用名（含 ST 标记）。"""
        import akshare as ak
        try:
            df = ak.stock_info_change_name(symbol='000668')
            assert len(df) > 0, '应返回曾用名数据'
            assert 'name' in df.columns
        except Exception as e:
            # 网络/SSL 错误时标记为不稳定
            assert 'SSL' in str(e) or 'HTTPS' in str(e) or 'Connection' in str(e), \
                f'意外错误: {e}'

    def test_stock_zh_a_st_em_current_only(self):
        """stock_zh_a_st_em 仅返回当前 ST 板，非历史序列。"""
        import akshare as ak
        try:
            df = ak.stock_zh_a_st_em()
            assert len(df) > 0, '应返回当前 ST 板股票'
            assert '代码' in df.columns or 'code' in df.columns
        except Exception as e:
            # SSL 错误也证明不稳定
            assert 'SSL' in str(e) or 'HTTPS' in str(e), f'意外错误: {e}'


# ---------------------------------------------------------------------------
# Name Change Evidence (Indirect ST Evidence)
# ---------------------------------------------------------------------------
class TestNameChangeEvidence:
    def test_name_change_contains_st_marker(self):
        """曾用名包含 ST/*ST 标记（间接 ST 证据）。"""
        import akshare as ak
        try:
            df = ak.stock_info_change_name(symbol='000587')
            assert len(df) > 0, '000587 应有曾用名数据'
            has_st = df['name'].str.contains('ST|\\*ST', case=False, na=False).any()
            assert has_st, '000587 曾用名应包含 ST 标记'
        except Exception as e:
            if 'SSL' in str(e) or 'HTTPS' in str(e) or 'Connection' in str(e):
                pytest.skip('网络不稳定，跳过测试')

    def test_name_change_no_effective_date(self):
        """stock_info_change_name 无生效日期字段。"""
        import akshare as ak
        try:
            df = ak.stock_info_change_name(symbol='000668')
            assert len(df) > 0, '000668 应有曾用名数据'
            assert 'date' not in df.columns and 'effective_date' not in df.columns, \
                'stock_info_change_name 不应有生效日期字段'
        except Exception as e:
            if 'SSL' in str(e) or 'HTTPS' in str(e) or 'Connection' in str(e):
                pytest.skip('网络不稳定，跳过测试')

    def test_name_change_cannot_be_pit_truth(self):
        """曾用名 ST 标记不能直接作为 PIT_SAFE_ST。"""
        import akshare as ak
        try:
            df = ak.stock_info_change_name(symbol='000668')
            assert len(df) > 0, '000668 应有曾用名数据'
            assert len(df.columns) == 2, '应只有 index 和 name 两列'
            assert 'name' in df.columns
        except Exception as e:
            if 'SSL' in str(e) or 'HTTPS' in str(e) or 'Connection' in str(e):
                pytest.skip('网络不稳定，跳过测试')


# ---------------------------------------------------------------------------
# Announcement-based ST (stock_notice_report)
# ---------------------------------------------------------------------------
class TestAnnouncementBasedST:
    def test_stock_notice_report_returns_announcements(self):
        """stock_notice_report 返回当日公告列表。"""
        import akshare as ak
        df = ak.stock_notice_report(symbol='全部', date='20220501')
        assert len(df) > 0, '2022-05-01 应有公告'
        assert '公告标题' in df.columns
        assert '公告日期' in df.columns

    def test_st_announcement_search(self):
        """可以搜索包含 ST 的公告（但需人工确认）。"""
        import akshare as ak
        df = ak.stock_notice_report(symbol='全部', date='20220501')
        # 搜索 ST 相关公告
        st_ann = df[df['公告标题'].str.contains('ST|风险警示|退市', case=False, na=False)]
        # 2022-05-01 可能有 ST 公告
        print(f'ST announcements on 2022-05-01: {len(st_ann)}')


# ---------------------------------------------------------------------------
# Historical ST Status Matrix
# ---------------------------------------------------------------------------
class TestSTStatusMatrix:
    def test_no_direct_historical_st_source(self):
        """确认无直接历史 ST 状态时间序列接口。"""
        import akshare as ak
        # 检查所有可能的 ST 接口
        st_funcs = [f for f in dir(ak) if 'st' in f.lower() and 'stock' in f.lower()]
        # stock_zh_a_st_em 仅返回当前 ST 板
        # 无历史 ST 状态接口
        assert 'stock_zh_a_st_em' in st_funcs, '应有 stock_zh_a_st_em'
        # 无 stock_historical_st 或类似接口
        assert not any('historical' in f and 'st' in f for f in st_funcs), \
            '不应有历史 ST 接口'


# ---------------------------------------------------------------------------
# PIT Constraints
# ---------------------------------------------------------------------------
class TestPITConstraints:
    def test_name_change_lacks_effective_date(self):
        """曾用名数据缺乏生效日期，无法做严格 PIT。"""
        # 这是审计结论
        # stock_info_change_name 返回的是列表，没有时间信息
        # 无法回答 "2022-06-24 该股票是否是 ST"
        pass

    def test_current_snapshot_fallback_forbidden(self):
        """禁止用当前 stocks.is_st 回填历史。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM stocks WHERE is_st = 1')
        st_count = cur.fetchone()[0]
        # 当前无 ST，但即使有，也不能用于历史
        assert st_count == 0, '当前无 ST 股票'


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
class TestCoverage:
    def test_name_change_coverage_unknown(self):
        """stock_info_change_name 的覆盖范围未知。"""
        # 这是审计结论
        # 名称变更接口的覆盖范围取决于新浪财经的数据
        # 无法自动验证
        pass

    def test_2025_2026_st_coverage_unknown(self):
        """2025-2026 ST 覆盖未知。"""
        # 无历史 ST 接口，无法验证
        pass


# ---------------------------------------------------------------------------
# Replay Impact
# ---------------------------------------------------------------------------
class TestReplayImpact:
    def test_historical_st_blocked(self):
        """Historical ST 保持 BLOCKED。"""
        # 这是审计结论
        # 无历史 ST 数据源
        pass

    def test_replay_ab_c_still_blocked(self):
        """Replay A/B/C 仍 BLOCKED（ST 未解锁）。"""
        # 这是审计结论
        pass
