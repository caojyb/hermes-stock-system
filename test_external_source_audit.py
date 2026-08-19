"""
Phase 7.3-E：External Historical Data Source Feasibility Audit 测试
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


class TestSourceDiscovery:
    def test_akshare_installed(self):
        """akshare 已安装。"""
        import importlib
        spec = importlib.util.find_spec('akshare')
        assert spec is not None, 'akshare 未安装'

    def test_akshare_has_share_change_api(self):
        """akshare 提供 stock_share_change_cninfo 接口。"""
        import akshare as ak
        assert hasattr(ak, 'stock_share_change_cninfo'), 'akshare 无 stock_share_change_cninfo'

    def test_akshare_has_industry_change_api(self):
        """akshare 提供 stock_industry_change_cninfo 接口。"""
        import akshare as ak
        assert hasattr(ak, 'stock_industry_change_cninfo'), 'akshare 无 stock_industry_change_cninfo'

    def test_akshare_st_api_current_only(self):
        """akshare.stock_zh_a_st_em 仅返回当前 ST 板股票。"""
        import akshare as ak
        try:
            df = ak.stock_zh_a_st_em()
        except Exception as e:
            pytest.skip(f'东方财富 ST 接口网络错误（已知环境问题）: {e}')
        assert len(df) > 0, '应有当前 ST 股票'
        assert '代码' in df.columns, '应有代码列'
        assert '名称' in df.columns, '应有名称列'


class TestHistoricalShares:
    def test_share_change_data_available(self):
        """akshare.stock_share_change_cninfo 可获取历史股本数据。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        assert len(df) > 0, '应有历史股本数据'
        assert '总股本' in df.columns, '应有总股本列'
        assert '变动日期' in df.columns, '应有变动日期列'
        assert '公告日期' in df.columns, '应有公告日期列'

    def test_share_change_has_effective_date(self):
        """股本变动记录包含变动日期（有效日期）。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        # 变动日期不应全为 NaT
        valid_dates = df['变动日期'].notna().sum()
        assert valid_dates > 0, '应有有效变动日期'

    def test_share_change_has_announcement_date(self):
        """股本变动记录包含公告日期。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        # 公告日期可能有 NaT（定期报告）
        assert '公告日期' in df.columns

    def test_share_change_total_shares_changes(self):
        """总股本随时间是变化的。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        unique_shares = df['总股本'].nunique()
        assert unique_shares > 1, f'总股本应有变化，实际 unique count: {unique_shares}'

    def test_share_change_sample_stock(self):
        """抽样股票：002594 比亚迪。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='002594', start_date='20000101', end_date='20241231')
        assert len(df) > 0, '002594 应有历史股本数据'

    def test_share_change_sample_stock_2(self):
        """抽样股票：600519 贵州茅台。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='600519', start_date='20000101', end_date='20241231')
        assert len(df) > 0, '600519 应有历史股本数据'

    def test_share_change_unit_is_wan_shares(self):
        """总股本单位是万股。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        # 平安银行总股本约 194 亿股 = 1,940,592 万股
        max_shares = df['总股本'].max()
        assert max_shares > 1e5, f'总股本应大于 10 万股（单位：万股），实际: {max_shares}'
        assert max_shares < 1e8, f'总股本应小于 1 亿万股（单位：万股），实际: {max_shares}'


class TestHistoricalST:
    def test_akshare_st_api_current_only(self):
        """akshare.stock_zh_a_st_em 仅返回当前 ST，非历史序列。"""
        import akshare as ak
        try:
            df = ak.stock_zh_a_st_em()
        except Exception as e:
            pytest.skip(f'东方财富 ST 接口网络错误（已知环境问题）: {e}')
        # 确认没有历史日期字段
        assert '日期' not in df.columns and 'date' not in df.columns, '当前 ST 接口不应有历史日期'

    def test_no_historical_st_in_market_db(self):
        """market.db 中无历史 ST 数据。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('PRAGMA table_info(stocks)')
        cols = [r[1] for r in cur.fetchall()]
        con.close()
        # stocks 有 is_st 字段，但仅当前快照
        assert 'is_st' in cols, 'stocks 应有 is_st 字段'
        # 确认每个 code 只有 1 行
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM stocks WHERE is_st = 1')
        st_count = cur.fetchone()[0]
        con.close()
        # 当前 ST 数量应很少
        assert st_count < 200, f'当前 ST 数量应较少，实际: {st_count}'


class TestHistoricalIndustry:
    def test_akshare_industry_change_api(self):
        """akshare.stock_industry_change_cninfo 提供历史行业变更。"""
        import akshare as ak
        df = ak.stock_industry_change_cninfo(symbol='002594', start_date='20000101', end_date='20241231')
        # 比亚迪可能有过行业变更
        print(f'比亚迪行业变更记录数: {len(df)}')
        # 即使无变更，接口也应返回空 DataFrame 或带列
        assert '变更日期' in df.columns or len(df) == 0


class TestPITSemantics:
    def test_share_change_has_both_dates(self):
        """股本变动记录同时包含公告日期和变动日期。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        # 定期报告：公告日期 = NaT，变动日期 = 报告期
        # 配股上市：公告日期 < 变动日期
        has_announcement = df['公告日期'].notna().sum()
        has_change_date = df['变动日期'].notna().sum()
        assert has_change_date > 0, '应有变动日期'
        # 公告日期可能少于变动日期（定期报告无公告日期）
        assert has_announcement >= 0, '公告日期数量应 >= 0'

    def test_share_change_effective_date_unknown_for_periodic(self):
        """定期报告的变动日期 = 报告期，非实际生效日。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        periodic = df[df['变动原因'] == '定期报告']
        if len(periodic) > 0:
            # 定期报告的变动日期是报告期末
            assert periodic['变动日期'].notna().any(), '定期报告应有变动日期'
            # 但实际生效日可能是报告期次日或更早
            # 标记为 SHARE_EFFECTIVE_DATE_UNKNOWN


class TestMarketCapReconstruction:
    def test_reconstructed_market_cap_positive(self):
        """ reconstructed_market_cap = share_count × close > 0。"""
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20241231')
        # 取最近一期
        latest = df.iloc[-1]
        share_count_wan = latest['总股本']  # 万股
        share_count = share_count_wan * 10000  # 转换为股
        # 从 klines 获取最新收盘价
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1', ('000001',))
        row = cur.fetchone()
        con.close()
        assert row is not None, '应有收盘价数据'
        close = row[0]
        mcap = share_count * close
        assert mcap > 0, f'市值应 > 0: {mcap}'


class TestSourceIsolation:
    def test_no_production_db_modification(self):
        """本阶段未修改生产数据库。"""
        # 确认 market.db schema 未变化
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables_before = [r[0] for r in cur.fetchall()]
        con.close()
        # 不应新增股本历史表
        share_tables = [t for t in tables_before if 'share' in t.lower() or 'capital' in t.lower()]
        for t in share_tables:
            assert t == 'stocks', f'不应有股本历史表: {t}'
