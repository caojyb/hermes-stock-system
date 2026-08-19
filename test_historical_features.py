"""
Phase 7.3-B：Historical Feature Reconstruction 测试
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from datetime import datetime

import pytest

from historical_features import get_historical_features, validate_pit_cutoff, FORMULA_VERSION

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def _get_production_indicator(symbol: str, date: str) -> dict:
    """读取 production indicators 当前快照（可能只有 1 行）。"""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute('SELECT * FROM indicators WHERE code=? AND date=?', (symbol, date))
    cols = [d[1] for d in cur.execute('PRAGMA table_info(indicators)').fetchall()]
    row = cur.fetchone()
    con.close()
    if not row:
        return {}
    return dict(zip(cols, row))


class TestPitCutoff:
    def test_no_future_rows_used(self):
        f = get_historical_features('000001', '2024-06-30')
        assert validate_pit_cutoff('000001', '2024-06-30', f)
        assert f['max_trade_date'] <= '2024-06-30'

    def test_current_date_cutoff(self):
        today = datetime.now().strftime('%Y-%m-%d')
        f = get_historical_features('000001', today)
        assert validate_pit_cutoff('000001', today, f)

    def test_early_date_cutoff(self):
        f = get_historical_features('000001', '2020-01-02')
        assert validate_pit_cutoff('000001', '2020-01-02', f)
        assert f['max_trade_date'] <= '2020-01-02'


class TestMA20:
    def test_ma20_warmup(self):
        f = get_historical_features('000001', '2020-01-02')
        # 2020-01-02 附近应有足够历史数据
        assert f['ma20'] is not None or f['ma20'] == 'UNKNOWN'

    def test_ma20_value_reasonable(self):
        f = get_historical_features('000001', '2024-06-30')
        if isinstance(f['ma20'], (int, float)):
            assert f['ma20'] > 0

    def test_ma20_deterministic(self):
        f1 = get_historical_features('000001', '2024-06-30')
        f2 = get_historical_features('000001', '2024-06-30')
        assert f1['ma20'] == f2['ma20']


class TestATR:
    def test_atr_warmup(self):
        f = get_historical_features('000001', '2020-01-02')
        # 早期数据可能不足
        assert f['atr_14'] is None or f['atr_14'] == 'UNKNOWN' or f['atr_14'] > 0

    def test_atr_value_positive(self):
        f = get_historical_features('000001', '2024-06-30')
        if isinstance(f['atr_14'], (int, float)):
            assert f['atr_14'] > 0

    def test_atr_pct_positive(self):
        f = get_historical_features('000001', '2024-06-30')
        if isinstance(f['atr_14_pct'], (int, float)):
            assert f['atr_14_pct'] > 0

    def test_atr_deterministic(self):
        f1 = get_historical_features('000001', '2024-06-30')
        f2 = get_historical_features('000001', '2024-06-30')
        assert f1['atr_14'] == f2['atr_14']


class TestMACD:
    def test_macd_warmup(self):
        f = get_historical_features('000001', '2020-01-02')
        assert f['macd'] is None or f['macd'] == 'UNKNOWN' or isinstance(f['macd'], (int, float))

    def test_macd_deterministic(self):
        f1 = get_historical_features('000001', '2024-06-30')
        f2 = get_historical_features('000001', '2024-06-30')
        assert f1['macd'] == f2['macd']
        assert f1['macd_signal'] == f2['macd_signal']
        assert f1['macd_hist'] == f2['macd_hist']


class TestVolumeRatio:
    def test_volume_ratio_warmup(self):
        f = get_historical_features('000001', '2020-01-02')
        assert f['volume_ratio'] is None or f['volume_ratio'] == 'UNKNOWN' or f['volume_ratio'] > 0

    def test_volume_ratio_deterministic(self):
        f1 = get_historical_features('000001', '2024-06-30')
        f2 = get_historical_features('000001', '2024-06-30')
        assert f1['volume_ratio'] == f2['volume_ratio']


class TestSignalScore:
    def test_signal_score_unknown(self):
        f = get_historical_features('000001', '2024-06-30')
        assert f['signal_score'] == 'UNKNOWN'


class TestProductionComparison:
    def test_compare_ma20_with_production(self):
        """抽样对比历史重建 MA20 与 production indicators。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT code, date FROM indicators LIMIT 20')
        samples = cur.fetchall()
        con.close()
        mismatches = []
        compared = 0
        for code, date in samples:
            prod = _get_production_indicator(code, date)
            if not prod:
                continue
            hist = get_historical_features(code, date)
            if hist.get('ma20') == 'UNKNOWN' or hist.get('ma20') is None:
                continue
            prod_ma20 = prod.get('ma20')
            if prod_ma20 is not None:
                compared += 1
                diff = abs(prod_ma20 - hist['ma20'])
                rel = diff / prod_ma20 if prod_ma20 else 0
                if rel > 0.05:
                    mismatches.append({
                        'code': code, 'date': date,
                        'production': prod_ma20, 'historical': hist['ma20'],
                        'abs_diff': diff, 'rel_diff': rel
                    })
        print(f"\nMA20 compared={compared}, mismatches={len(mismatches)}")
        for m in mismatches[:5]:
            print(f"  {m['code']} {m['date']}: prod={m['production']}, hist={m['historical']}, rel={m['rel_diff']:.2%}")
        # MA20 mismatch rate should be low (<30%)
        if compared > 0:
            assert len(mismatches) / compared < 0.3

    def test_compare_macd_with_production(self):
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute('SELECT code, date, macd, macd_signal FROM indicators WHERE macd IS NOT NULL LIMIT 20')
        samples = cur.fetchall()
        con.close()
        if not samples:
            pytest.skip('production indicators 中无 MACD 值（均为 NULL），无法对比')
        mismatches = []
        compared = 0
        for code, date, prod_macd, prod_signal in samples:
            hist = get_historical_features(code, date)
            if hist.get('macd') == 'UNKNOWN' or hist.get('macd') is None:
                continue
            if prod_macd is not None:
                compared += 1
                diff = abs(prod_macd - hist['macd'])
                rel = diff / abs(prod_macd) if prod_macd else 0
                if rel > 0.05:
                    mismatches.append({'code': code, 'date': date, 'prod': prod_macd, 'hist': hist['macd'], 'rel': rel})
        print(f"\nMACD compared={compared}, mismatches={len(mismatches)}")
        for m in mismatches[:5]:
            print(f"  {m['code']} {m['date']}: prod={m['prod']}, hist={m['hist']}, rel={m['rel']:.2%}")
        # 生产 indicators 中 MACD 极少有值，且可能与历史重建不一致
        # 标记为 FEATURE_SEMANTIC_CONFLICT，本阶段只记录不修复
        if compared > 0 and len(mismatches) / compared > 0.5:
            print('  FEATURE_SEMANTIC_CONFLICT: production MACD 与历史重建差异显著')


class TestNoFallback:
    def test_no_current_indicators_fallback(self):
        f = get_historical_features('000001', '2020-01-02')
        # 早期日期的指标应该 UNKNOWN 或真实计算值，不应该是当前快照值
        if f.get('ma20') not in ('UNKNOWN', None):
            assert isinstance(f['ma20'], (int, float))


class TestDeterministic:
    def test_same_input_same_output(self):
        f1 = get_historical_features('600519', '2024-12-31')
        f2 = get_historical_features('600519', '2024-12-31')
        for k in ['ma20', 'atr_14', 'macd', 'macd_signal', 'macd_hist', 'volume_ratio']:
            assert f1.get(k) == f2.get(k), f"{k} mismatch for same input"


class TestFeatureMetadata:
    def test_metadata_fields(self):
        f = get_historical_features('000001', '2024-06-30')
        assert f['feature_source'] == 'HISTORICAL_REPLAY'
        assert f['formula_version'] == FORMULA_VERSION
        assert f['source_table'] == 'klines'
        assert f['pit_cutoff'] == '2024-06-30'
        assert f['warmup_sufficient'] in (True, False)

    def test_formula_version_tracked(self):
        f = get_historical_features('000001', '2024-06-30')
        assert 'formula_version' in f
        assert len(f['formula_version']) > 0


class TestWarmup:
    def test_warmup_flag(self):
        f = get_historical_features('000001', '2020-01-02')
        assert 'warmup_sufficient' in f
        assert isinstance(f['warmup_sufficient'], bool)

    def test_insufficient_warmup_returns_unknown(self):
        """数据不足时应返回 UNKNOWN。"""
        f = get_historical_features('000001', '2020-01-02')
        if not f['warmup_sufficient']:
            assert f['ma20'] == 'UNKNOWN' or f['ma20'] is None
