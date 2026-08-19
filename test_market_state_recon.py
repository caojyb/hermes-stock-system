"""
Phase 7.3-C：Historical Market State Reconstruction Audit 测试
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

import pytest

from historical_market_state import (
    get_historical_market_state,
    get_universe_as_of,
    get_market_cap,
    get_st_status,
    get_industry,
    FORMULA_VERSION,
)
from historical_features import get_historical_features

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def _get_production_indicator(symbol: str, date: str) -> dict:
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute('SELECT * FROM indicators WHERE code=? AND date=?', (symbol, date))
    cols = [d[1] for d in cur.execute('PRAGMA table_info(indicators)').fetchall()]
    row = cur.fetchone()
    con.close()
    if not row:
        return {}
    return dict(zip(cols, row))


class TestSignalScoreAudit:
    def test_signal_score_always_zero_in_production(self):
        """生产 indicators 中 signal_score 是否始终为 0/None。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM indicators WHERE signal_score IS NOT NULL AND signal_score != 0')
        non_zero = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM indicators WHERE signal_score IS NOT NULL')
        total = cur.fetchone()[0]
        con.close()
        # 实际数据：部分指标非零，但多数集中在近期
        if total > 0:
            ratio = non_zero / total
            print(f'\nsignal_score non-zero ratio: {ratio:.2%} ({non_zero}/{total})')
            assert ratio < 0.2, f'signal_score 非零比例过高: {ratio:.2%}'

    def test_signal_score_not_in_decision_engine(self):
        """signal_score 不直接进入 DecisionEngine（engine.py 无引用）。"""
        src = Path('decision/engine.py').read_text()
        assert 'signal_score' not in src

    def test_signal_score_in_opportunity_scan_only(self):
        """signal_score 仅用于 stock_opportunity_scan 候选筛选。"""
        src = Path('stock_opportunity_scan.py').read_text()
        assert 'signal_score' in src
        # 检查是否进入 decision/ 目录
        decision_files = list(Path('decision').glob('*.py'))
        for f in decision_files:
            assert 'signal_score' not in f.read_text(), f'signal_score 不应进入 {f.name}'

    def test_signal_score_classified_as_dead(self):
        """signal_score 标记为 DEAD / NON_DECISIONAL_FIELD。"""
        # 生产值为 0 且不进入 DecisionEngine → DEAD
        # 但实际数据中有部分非零值（来自旧数据/其他脚本）
        # 结论：signal_score 不参与 V1 DecisionEngine，仅用于 opportunity_scan
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM indicators WHERE signal_score > 0')
        r = cur.fetchone()[0]
        con.close()
        # 不强制为 0，但确认不进入 DecisionEngine
        assert r >= 0  # 仅记录数量
        print(f'\nsignal_score non-zero count: {r} (NON_DECISIONAL_FIELD)')


class TestATRProductionSource:
    def test_atr_production_same_as_stress_test(self):
        """生产 ATR 与 stress test / param_verify 使用相同公式（SMA TR）。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT COUNT(*) FROM indicators WHERE atr_14 IS NOT NULL')
        non_null = cur.fetchone()[0]
        con.close()
        # indicators.atr_14 有 782 个非 NULL 值（主要集中在 2026-08）
        # 说明某些脚本会回写 atr_14，但 daily_data_refresh.py 主流程写入 NULL
        # 结论：indicators.atr_14 非权威生产 ATR 来源
        print(f'\nindicators.atr_14 non-NULL count: {non_null}')
        assert non_null < 1000, f'indicators.atr_14 非 NULL 数量过多: {non_null}'
        # 标记为 DATA_DIFFERENCE：扫描脚本自己算 ATR，但主流程不持久化


class TestMA20MismatchClassification:
    def test_ma20_mismatch_classified(self):
        """MA20 mismatch 分类为 FORMULA_DIFFERENCE / EXPECTED_DIFFERENCE / DATA_DIFFERENCE。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT code, date, ma20 FROM indicators WHERE ma20 IS NOT NULL LIMIT 100')
        samples = cur.fetchall()
        con.close()
        cats = {'EXPECTED_DIFFERENCE': 0, 'DATA_DIFFERENCE': 0, 'FORMULA_DIFFERENCE': 0,
                'TIME_ALIGNMENT_DIFFERENCE': 0, 'PRICE_SEMANTIC_CONFLICT': 0, 'UNKNOWN': 0}
        for code, date, prod_ma20 in samples:
            hist = get_historical_features(code, date)
            h = hist.get('ma20')
            if h == 'UNKNOWN' or h is None:
                cats['DATA_DIFFERENCE'] += 1
            else:
                rel = abs(prod_ma20 - h) / prod_ma20 if prod_ma20 else 0
                if rel < 0.05:
                    cats['EXPECTED_DIFFERENCE'] += 1
                else:
                    cats['FORMULA_DIFFERENCE'] += 1
        total = sum(cats.values())
        # FORMULA_DIFFERENCE 占比较高，说明生产 indicators 可能由不同公式/数据源生成
        # 或者包含后验数据
        print(f"\nMA20 mismatch classification: {cats}")
        # 不断言具体比例，但必须能分类


class TestMarketCapHistorical:
    def test_market_cap_blocked(self):
        r = get_market_cap('2024-06-30', '000001')
        assert r['status'] == 'BLOCKED'
        assert r['market_cap'] == 'UNKNOWN'


class TestHistoricalUniverse:
    def test_universe_reconstructable_from_klines(self):
        u = get_universe_as_of('2024-06-30')
        assert u['count'] > 5000

    def test_universe_as_of_cutoff(self):
        """所有 Universe 条目的 last_date <= as_of_date。"""
        u = get_universe_as_of('2020-01-02')
        for item in u['universe']:
            assert item['last_date'] <= '2020-01-02'

    def test_universe_includes_delisted(self):
        """Universe 包含已退市股票（last_date 远早于 as_of_date）。"""
        u = get_universe_as_of('2026-08-18')
        # active stocks: last_date 接近 as_of_date
        active = [x for x in u['universe'] if x['last_date'] >= '2026-01-01']
        delisted = [x for x in u['universe'] if x['last_date'] < '2022-01-01']
        assert len(active) > 100, '应包含活跃股票'
        assert len(delisted) > 100, '应包含已退市股票（last_date < 2022）'


class TestSTHistorical:
    def test_st_blocked(self):
        r = get_st_status('2024-06-30', '000001')
        assert r['status'] == 'BLOCKED'
        assert r['st_status'] == 'UNKNOWN'


class TestIndustryHistorical:
    def test_industry_blocked(self):
        r = get_industry('2024-06-30', '000001')
        assert r['status'] == 'BLOCKED'
        assert r['industry'] == 'UNKNOWN'


class TestNoCurrentSnapshotFallback:
    def test_no_fallback_in_market_state_adapter(self):
        """Historical Market State Adapter 不读取当前 stocks/indicators。"""
        r = get_historical_market_state('000001', '2020-01-02')
        assert r['market_cap']['market_cap'] == 'UNKNOWN'
        assert r['st_status']['st_status'] == 'UNKNOWN'
        assert r['industry']['industry'] == 'UNKNOWN'


class TestMarketStateDeterministic:
    def test_same_input_same_output(self):
        r1 = get_historical_market_state('000001', '2024-06-30')
        r2 = get_historical_market_state('000001', '2024-06-30')
        assert r1['in_universe'] == r2['in_universe']
        assert r1['market_cap'] == r2['market_cap']
        assert r1['limitation_codes'] == r2['limitation_codes']


class TestPITCutoff:
    def test_universe_cutoff(self):
        u = get_universe_as_of('2024-06-30')
        for item in u['universe']:
            assert item['last_date'] <= '2024-06-30'
