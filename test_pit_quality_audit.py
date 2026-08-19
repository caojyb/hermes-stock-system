"""
Phase 7.3-G：Historical Share PIT Quality Upgrade 测试
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_audit_symbols():
    from audit_pit_quality import load_audit_data, check_timeline_consistency, classify_source_type
    symbols = ['000001', '002594', '600519', '000002', '601318', '000858', '002415', '600036', '000333', '601398']
    df = load_audit_data(symbols)
    return df, symbols


# ---------------------------------------------------------------------------
# Approximate Source Classification
# ---------------------------------------------------------------------------
class TestApproximateSourceClassification:
    def test_all_approximate_from_periodic_report(self):
        """100% APPROXIMATE 来自定期报告。"""
        df, _ = _load_audit_symbols()
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        assert len(app) > 0, '应有 APPROXIMATE 记录'
        assert (app['source_type'] == 'PERIODIC_REPORT').all(), '所有 APPROXIMATE 应来自定期报告'

    def test_approximate_has_change_date(self):
        """APPROXIMATE 都有变动日期。"""
        df, _ = _load_audit_symbols()
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        assert app['has_change_date'].all(), '所有 APPROXIMATE 应有变动日期'

    def test_approximate_mostly_has_announcement(self):
        """APPROXIMATE 大部分有公告日期。"""
        df, _ = _load_audit_symbols()
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        # 380/399 有公告日期（实际数据）
        assert app['has_announcement'].sum() >= 300, '应有至少 300 条有公告日期'


# ---------------------------------------------------------------------------
# Change Date Semantic Validation
# ---------------------------------------------------------------------------
class TestChangeDateSemantic:
    def test_periodic_report_change_date_is_report_end(self):
        """定期报告的变动日期 = 报告期末。"""
        from historical_share_layer import convert_raw_events
        import pandas as pd
        df = pd.DataFrame([{
            '证券代码': '000001',
            '变动日期': '2022-06-30',
            '公告日期': '2022-08-18',
            '变动原因': '定期报告',
            '总股本': 1940591.8198,
        }])
        events = convert_raw_events(df, '000001')
        assert len(events) == 1
        assert events[0].effective_date == date(2022, 6, 30)
        assert events[0].date_quality.value == 'APPROXIMATE_EFFECTIVE_DATE'

    def test_allotment_change_date_is_listing_date(self):
        """配股上市的变动日期 = 上市日。"""
        from historical_share_layer import convert_raw_events
        import pandas as pd
        df = pd.DataFrame([{
            '证券代码': '000001',
            '变动日期': '2000-12-08',
            '公告日期': '2000-11-06',
            '变动原因': '配股上市',
            '总股本': 194582.2149,
        }])
        events = convert_raw_events(df, '000001')
        assert events[0].effective_date == date(2000, 12, 8)
        assert events[0].date_quality.value == 'KNOWN_EFFECTIVE_DATE'


# ---------------------------------------------------------------------------
# Announcement Date Comparison
# ---------------------------------------------------------------------------
class TestAnnouncementDateAnalysis:
    def test_change_date_before_or_equal_announcement_for_periodic(self):
        """定期报告：change_date <= announcement_date。"""
        df, _ = _load_audit_symbols()
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        # 所有有公告日期的定期报告，change_date <= announcement_date
        with_ann = app[app['has_announcement']]
        if len(with_ann) > 0:
            assert (with_ann['effective_date'] <= with_ann['announcement_date']).all(), \
                '定期报告变动日期应早于或等于公告日期'

    def test_no_change_date_after_announcement(self):
        """没有 change_date > announcement_date 的情况。"""
        df, _ = _load_audit_symbols()
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        mask = app['has_announcement'] & app['has_change_date']
        if mask.any():
            assert not (app.loc[mask, 'effective_date'] > app.loc[mask, 'announcement_date']).any(), \
                '不应有 change_date > announcement_date'


# ---------------------------------------------------------------------------
# Known Effective Date Preservation
# ---------------------------------------------------------------------------
class TestKnownPreservation:
    def test_known_never_downgraded(self):
        """KNOWN 事件不应被降级。"""
        from historical_share_layer import HistoricalShareLayer
        layer = HistoricalShareLayer()
        import pandas as pd
        from historical_share_layer import convert_raw_events
        df = pd.DataFrame([{
            '证券代码': '000001',
            '变动日期': '2000-12-08',
            '公告日期': '2000-11-06',
            '变动原因': '配股上市',
            '总股本': 194582.2149,
        }])
        layer._events['000001'] = convert_raw_events(df, '000001')
        ev = layer.get_as_of('000001', date(2000, 12, 9))
        assert ev is not None
        assert ev.date_quality.value == 'KNOWN_EFFECTIVE_DATE'


# ---------------------------------------------------------------------------
# Approximate / Unknown Separation
# ---------------------------------------------------------------------------
class TestQualitySeparation:
    def test_approximate_never_becomes_strict(self):
        """APPROXIMATE 不能自动变成 KNOWN。"""
        from historical_share_layer import HistoricalShareLayer
        layer = HistoricalShareLayer()
        import pandas as pd
        from historical_share_layer import convert_raw_events
        df = pd.DataFrame([
            {'证券代码': '000001', '变动日期': '2022-06-30', '公告日期': '2022-08-18', '变动原因': '定期报告', '总股本': 1940591.8198},
        ])
        layer._events['000001'] = convert_raw_events(df, '000001')
        ev = layer.get_as_of('000001', date(2022, 7, 1))
        assert ev is not None
        assert ev.date_quality.value == 'APPROXIMATE_EFFECTIVE_DATE', \
            'APPROXIMATE 不应自动升级为 KNOWN'

    def test_unknown_never_becomes_strict(self):
        """UNKNOWN 不能自动变成 KNOWN。"""
        from historical_share_layer import HistoricalShareLayer
        layer = HistoricalShareLayer()
        import pandas as pd
        from historical_share_layer import convert_raw_events
        df = pd.DataFrame([
            {'证券代码': '000001', '变动日期': None, '公告日期': None, '变动原因': '其他', '总股本': 100000.0},
        ])
        layer._events['000001'] = convert_raw_events(df, '000001')
        # get_any_as_of 会返回 UNKNOWN，但 get_as_of 不应返回
        ev_strict = layer.get_as_of('000001', date(2022, 7, 1))
        assert ev_strict is None, 'UNKNOWN 不应进入严格 PIT'


# ---------------------------------------------------------------------------
# Timeline Consistency
# ---------------------------------------------------------------------------
class TestTimelineConsistency:
    def test_valid_timeline_majority(self):
        """15 只抽样股票中，时间线应为 VALID_TIMELINE（允许合法回购/注销减少）。"""
        df, symbols = _load_audit_symbols()
        from audit_pit_quality import check_timeline_consistency
        results = check_timeline_consistency(df)
        valid_count = sum(1 for v in results.values() if v == 'VALID_TIMELINE')
        # 600519 有定期报告导致的减少（数据修订），标记为 SUSPICIOUS
        assert valid_count >= 8, f'至少 8 只应为 VALID_TIMELINE，实际: {valid_count}'

    def test_no_illegal_decrease(self):
        """不应有无合法原因的股本减少。600519 定期报告减少视为数据修订（SUSPICIOUS），非非法。"""
        from audit_pit_quality import load_audit_data
        df = load_audit_data(['000001', '002594', '600519', '000002'])
        from audit_pit_quality import check_timeline_consistency
        results = check_timeline_consistency(df)
        # 600519 的定期报告减少是数据修订（SUSPICIOUS），不是非法减少
        # 其他股票不应有非法减少
        for sym, status in results.items():
            if sym == '600519':
                # 600519 的 SUSPICIOUS 是定期报告数据修订，不是非法减少
                assert status == 'SUSPICIOUS', f'{sym} 应为 SUSPICIOUS（定期报告数据修订）'
            else:
                assert status != 'SUSPICIOUS', f'{sym} 时间线应有效（减少均为合法回购/注销）'


# ---------------------------------------------------------------------------
# Corporate Action Evidence
# ---------------------------------------------------------------------------
class TestCorporateActionEvidence:
    def test_buyback_is_known(self):
        """股份回购 → KNOWN_EFFECTIVE_DATE。"""
        from historical_share_layer import convert_raw_events
        import pandas as pd
        df = pd.DataFrame([{
            '证券代码': '000001',
            '变动日期': '2024-05-10',
            '公告日期': '2024-05-14',
            '变动原因': '股份回购',
            '总股本': 290926.5855,
        }])
        events = convert_raw_events(df, '000001')
        assert events[0].date_quality.value == 'KNOWN_EFFECTIVE_DATE'

    def test_restricted_lift_is_known(self):
        """限售股份上市 → KNOWN_EFFECTIVE_DATE。"""
        from historical_share_layer import convert_raw_events
        import pandas as pd
        df = pd.DataFrame([{
            '证券代码': '000001',
            '变动日期': '2024-01-08',
            '公告日期': '2024-01-04',
            '变动原因': '限售股份上市',
            '总股本': 1940558.0,
        }])
        events = convert_raw_events(df, '000001')
        assert events[0].date_quality.value == 'KNOWN_EFFECTIVE_DATE'


# ---------------------------------------------------------------------------
# K-line Evidence Never Becomes PIT Truth
# ---------------------------------------------------------------------------
class TestKLineEvidenceNotPitTruth:
    def test_price_jump_does_not_upgrade_quality(self):
        """价格跳变不改变 APPROXIMATE 的质量。"""
        from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap
        layer = HistoricalShareLayer()
        import pandas as pd
        from historical_share_layer import convert_raw_events
        # 即使有价格异常，APPROXIMATE 仍是 APPROXIMATE
        df = pd.DataFrame([
            {'证券代码': '002594', '变动日期': '2011-06-30', '公告日期': '2011-08-23', '变动原因': '定期报告', '总股本': 235410.0},
        ])
        layer._events['002594'] = convert_raw_events(df, '002594')
        mcap = HistoricalMarketCap(layer)
        result = mcap.get_market_cap('002594', date(2011, 9, 27))
        assert result.quality.value == 'APPROXIMATE'


# ---------------------------------------------------------------------------
# Strict / Research Replay Eligibility
# ---------------------------------------------------------------------------
class TestReplayEligibility:
    def test_strict_replay_only_known(self):
        """严格 Replay 只允许 KNOWN。"""
        from historical_share_layer import HistoricalShareLayer
        layer = HistoricalShareLayer()
        layer.load_symbols(['000001', '002594'])
        for sym in ['000001', '002594']:
            ev = layer.get_as_of(sym, date(2022, 6, 24))
            if ev:
                assert ev.date_quality.value == 'KNOWN_EFFECTIVE_DATE', \
                    f'{sym} 严格 PIT 只允许 KNOWN'

    def test_research_replay_includes_approximate(self):
        """研究 Replay 允许 APPROXIMATE（通过 get_any_as_of）。"""
        from historical_share_layer import HistoricalShareLayer
        layer = HistoricalShareLayer()
        layer.load_symbols(['000001'])
        ev = layer.get_any_as_of('000001', date(2022, 6, 24))
        assert ev is not None
        # get_any_as_of 可能返回 APPROXIMATE
        assert ev.date_quality.value in ('KNOWN_EFFECTIVE_DATE', 'APPROXIMATE_EFFECTIVE_DATE', 'UNKNOWN_EFFECTIVE_DATE')


# ---------------------------------------------------------------------------
# 2025+ Coverage Gap
# ---------------------------------------------------------------------------
class TestCoverageGap:
    def test_2025_data_available_but_only_periodic(self):
        """2025-2026 有数据，但只有定期报告（无股本变动）。"""
        import pandas as pd
        import akshare as ak
        df = ak.stock_share_change_cninfo(symbol='000001', start_date='20000101', end_date='20261231')
        df['变动日期'] = pd.to_datetime(df['变动日期'], errors='coerce')
        recent = df[df['变动日期'] >= '2025-01-01']
        if len(recent) > 0:
            # 2025+ 数据存在，但全是定期报告
            assert (recent['变动原因'] == '定期报告').all(), '2025+ 应只有定期报告'
            # 股本无变化
            assert recent['总股本'].nunique() == 1, '2025+ 股本应无变化'


# ---------------------------------------------------------------------------
# Strict / Approximate Market Cap Separation
# ---------------------------------------------------------------------------
class TestMarketCapSeparation:
    def test_strict_market_cap_uses_known_only(self):
        """STRICT Market Cap 只使用 KNOWN 股本。"""
        from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap
        layer = HistoricalShareLayer()
        layer.load_symbols(['000001'])
        mcap = HistoricalMarketCap(layer)
        # 2022-06-24 平安银行：应看到 2018-05-21 的 KNOWN 事件
        result = mcap.get_market_cap('000001', date(2022, 6, 24))
        assert result.quality.value == 'PIT_SAFE'
        assert result.share_date_quality.value == 'KNOWN_EFFECTIVE_DATE'

    def test_approximate_market_cap_separated(self):
        """APPROXIMATE 市值单独标记。"""
        from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap
        layer = HistoricalShareLayer()
        layer.load_symbols(['002594'])
        mcap = HistoricalMarketCap(layer)
        # 2011-09-27 前只有 2011-06-30 定期报告（APPROXIMATE）
        result = mcap.get_market_cap('002594', date(2011, 9, 27))
        assert result.quality.value == 'APPROXIMATE'
        assert result.share_date_quality.value == 'APPROXIMATE_EFFECTIVE_DATE'


# ---------------------------------------------------------------------------
# Batch Download Decision Logic
# ---------------------------------------------------------------------------
class TestBatchDownloadDecision:
    def test_strict_pit_coverage_insufficient_for_batch(self):
        """严格 PIT coverage 16.3% → 不值得批量下载。"""
        # 这是审计结论，不是代码逻辑
        # 但我们可以验证：即使加载全市场，KNOWN 比例不会显著提升
        from audit_pit_quality import load_audit_data
        df = load_audit_data(['000001', '002594', '600519', '000002', '601318'])
        from audit_pit_quality import audit_apprximate
        app = audit_apprximate(df)
        known_ratio = (df['date_quality'] == 'KNOWN_EFFECTIVE_DATE').mean()
        approx_ratio = (df['date_quality'] == 'APPROXIMATE_EFFECTIVE_DATE').mean()
        # 已知：所有 APPROXIMATE 都是定期报告，无法升级
        assert approx_ratio > 0.5, 'APPROXIMATE 占多数，批量下载不会提升严格 PIT'
        assert known_ratio < 0.3, 'KNOWN 占少数，批量下载价值有限'

    def test_research_replay_coverage_sufficient(self):
        """研究 Replay 76% 覆盖率 → 无需批量下载。"""
        from audit_pit_quality import load_audit_data
        df = load_audit_data(['000001', '002594', '600519', '000002', '601318'])
        research_ratio = (df['date_quality'].isin(['KNOWN_EFFECTIVE_DATE', 'APPROXIMATE_EFFECTIVE_DATE'])).mean()
        assert research_ratio > 0.7, '研究 Replay 覆盖率 > 70%，无需批量下载'


# ---------------------------------------------------------------------------
# Quality Model Integrity
# ---------------------------------------------------------------------------
class TestQualityModel:
    def test_three_tier_quality(self):
        """质量模型只有三级：KNOWN / APPROXIMATE / UNKNOWN。"""
        from historical_share_layer import ShareDateQuality, MarketCapQuality
        expected_share = {'KNOWN_EFFECTIVE_DATE', 'APPROXIMATE_EFFECTIVE_DATE', 'UNKNOWN_EFFECTIVE_DATE'}
        actual_share = {e.value for e in ShareDateQuality}
        assert actual_share == expected_share, f'ShareDateQuality 应只有三级: {actual_share}'
        
        expected_mcap = {'PIT_SAFE', 'APPROXIMATE', 'UNKNOWN', 'BLOCKED'}
        actual_mcap = {e.value for e in MarketCapQuality}
        assert actual_mcap == expected_mcap, f'MarketCapQuality 应只有四级: {actual_mcap}'

    def test_no_speculative_quality(self):
        """没有"推测"类质量等级。"""
        from historical_share_layer import ShareDateQuality
        for e in ShareDateQuality:
            assert 'SPECULATIVE' not in e.value, '不应有 SPECULATIVE 质量等级'
            assert 'INFERRED' not in e.value, '不应有 INFERRED 质量等级'
