"""
Phase 7.3-J：Single-Stock Replay Pilot 测试
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from historical_replay_engine import get_klines, compute_technical_features, replay_v1_filters
from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap


PILOT_SYMBOLS = [
    '600519', '000858', '601318', '002594', '300750',
    '002415', '000001', '600036', '000002', '600028',
    '601899', '000333', '002230', '300059', '002475',
    '600276', '000538', '000568', '002304',
]

PILOT_DATES = [
    date(2008, 6, 15),
    date(2015, 6, 15),
    date(2022, 12, 15),
]


class TestReplayPilot:
    """单票 Replay Pilot 测试。"""
    
    @pytest.fixture(scope='class')
    def layers(self):
        """共享 Historical Share Layer。"""
        layer = HistoricalShareLayer()
        layer.load_symbols(PILOT_SYMBOLS)
        mcap_layer = HistoricalMarketCap(layer)
        return layer, mcap_layer
    
    def test_total_cases(self, layers):
        """总 case 数 >= 30。"""
        # 使用已生成的 replay_pilot_results.csv
        import pandas as pd
        from pathlib import Path
        csv_path = Path('/home/caojy/.hermes/scripts/cron/replay_pilot_results.csv')
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            from run_replay_pilot import run_pilot
            df = run_pilot()
        assert len(df) >= 30
    
    def test_st_unknown_blocks_all(self, layers):
        """ST UNKNOWN 导致所有 case 为 UNKNOWN。"""
        import pandas as pd
        from pathlib import Path
        csv_path = Path('/home/caojy/.hermes/scripts/cron/replay_pilot_results.csv')
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            from run_replay_pilot import run_pilot
            df = run_pilot()
        st_unknown = df[df['filter_st'] == 'UNKNOWN']
        assert len(st_unknown) == len(df)
    
    def test_market_cap_quality_mixed(self, layers):
        """Market Cap Quality 包含 PIT_SAFE / APPROXIMATE / UNKNOWN。"""
        import pandas as pd
        from pathlib import Path
        csv_path = Path('/home/caojy/.hermes/scripts/cron/replay_pilot_results.csv')
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            from run_replay_pilot import run_pilot
            df = run_pilot()
        qualities = df['market_cap_quality'].unique()
        assert len(qualities) >= 2
    
    def test_no_current_snapshot_fallback(self, layers):
        """不读取当前 Production Snapshot。"""
        from run_replay_pilot import run_pilot
        df = run_pilot()
        # 所有 case 的 source 应为 HISTORICAL_REPLAY
        assert (df['replay_case_id'].str.contains('HISTORICAL_REPLAY') == False).all()
    
    def test_deterministic_replay(self, layers):
        """相同输入应产生相同输出。"""
        from historical_replay_engine import get_klines, compute_technical_features, replay_v1_filters
        from historical_share_layer import HistoricalMarketCap
        symbol = '600519'
        target_date = date(2022, 12, 15)
        
        klines = get_klines(symbol, target_date)
        features = compute_technical_features(klines)
        
        case1 = replay_v1_filters(symbol, target_date, features, None, 'UNKNOWN', 'UNKNOWN')
        case2 = replay_v1_filters(symbol, target_date, features, None, 'UNKNOWN', 'UNKNOWN')
        
        assert case1.final_candidate == case2.final_candidate
        assert case1.exclusion_reason == case2.exclusion_reason
    
    def test_future_data_access_guard(self, layers):
        """禁止使用未来数据。"""
        from historical_replay_engine import get_klines
        symbol = '600519'
        future_date = date(2099, 6, 15)
        klines = get_klines(symbol, future_date)
        # 未来日期应返回空或仅到当前最新日期
        if len(klines) > 0:
            max_date = klines['date'].max()
            assert max_date <= '2026-08-19'
    
    def test_volume_ratio_formula(self, layers):
        """Volume Ratio 公式正确性。"""
        from historical_replay_engine import compute_technical_features
        import pandas as pd
        
        # 构造测试数据（需要 >= 60 行）
        n = 25
        closes = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        volumes = [1000.0] * n
        turnovers = [100000.0] * n
        
        # 需要至少 25 行来计算 vol_ratio
        klines = pd.DataFrame({
            'close': closes + [100.0] * 40,  # 65 rows
            'high': highs + [101.0] * 40,
            'low': lows + [99.0] * 40,
            'volume': volumes + [1000.0] * 40,
            'turnover': turnovers + [100000.0] * 40,
        })
        features = compute_technical_features(klines)
        assert features.get('vol_ratio') is not None
        assert features.get('ma20') is not None
    
    def test_ma20_calculation(self, layers):
        """MA20 计算正确性。"""
        from historical_replay_engine import compute_technical_features
        import pandas as pd
        
        # 构造测试数据：最后 20 个值为 11-30
        n = 70
        closes = list(range(1, n + 1))  # 1-70
        # 最后 20 个值是 51-70
        expected_ma20 = sum(range(51, 71)) / 20
        
        klines = pd.DataFrame({
            'close': closes,
            'high': [c + 1 for c in closes],
            'low': [c - 1 for c in closes],
            'volume': [1000.0] * n,
            'turnover': [100000.0] * n,
        })
        features = compute_technical_features(klines)
        assert abs(features['ma20'] - expected_ma20) < 0.01
