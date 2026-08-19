"""
Phase 7.3-J：Single-Stock Replay Pilot（扩展版）

固定 Pilot 样本：更多中小盘股票。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap
from historical_replay_engine import get_klines, compute_technical_features, replay_v1_filters

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

# 扩展 Pilot 股票池（增加中小盘）
PILOT_SYMBOLS = [
    # 大盘（可能 >90B）
    '600519', '000858', '601318', '600036', '000002',
    '000333', '000568', '002304',
    # 中盘（5-90B 目标区间）
    '002594', '002415', '000001', '600028', '601899',
    '002230', '300059', '002475', '000538', '601888',
    # 中小盘
    '000725', '002352', '600809', '000596', '603259',
    # 小盘（<5B）
    '002502', '300139', '300346', '002359', '000668',
]

# 历史日期（3 个代表性日期）
PILOT_DATES = [
    date(2008, 6, 15),   # 2000s
    date(2015, 6, 15),   # 2010s
    date(2022, 12, 15),  # 2020s
]

EXCLUDE_SYMBOLS = {'600887'}  # 排除有 ST 证据
PILOT_SYMBOLS = [s for s in PILOT_SYMBOLS if s not in EXCLUDE_SYMBOLS]


def run_pilot():
    """运行 Pilot。"""
    # 共享 Historical Share Layer
    print('Loading Historical Share Layer...')
    layer = HistoricalShareLayer()
    layer.load_symbols(PILOT_SYMBOLS)
    mcap_layer = HistoricalMarketCap(layer)
    print(f'Loaded {len(PILOT_SYMBOLS)} symbols')
    
    cases = []
    for symbol in PILOT_SYMBOLS:
        for target_date in PILOT_DATES:
            klines = get_klines(symbol, target_date)
            if len(klines) < 60:
                continue
            features = compute_technical_features(klines)
            result = mcap_layer.get_market_cap(symbol, target_date)
            mcap_quality = result.quality.value
            st_status = 'UNKNOWN'
            case = replay_v1_filters(
                symbol=symbol,
                as_of_date=target_date,
                features=features,
                mcap=result.market_cap,
                mcap_quality=mcap_quality,
                st_status=st_status,
            )
            cases.append(case)
    
    rows = []
    for c in cases:
        rows.append({
            'replay_case_id': c.replay_case_id,
            'symbol': c.symbol,
            'as_of_date': c.as_of_date,
            'market_cap_quality': c.market_cap_quality,
            'market_cap': c.market_cap,
            'ma20': c.ma20,
            'atr_pct': c.atr_pct,
            'vol_ratio': c.volume_ratio,
            'price_pos': c.price_pos,
            'filter_market_cap': c.filter_market_cap,
            'filter_st': c.filter_st,
            'filter_turnover_1d': c.filter_turnover_1d,
            'filter_turnover_20d': c.filter_turnover_20d,
            'filter_price_pos': c.filter_price_pos,
            'filter_vol_ratio': c.filter_vol_ratio,
            'filter_atr': c.filter_atr,
            'final_candidate': c.final_candidate,
            'exclusion_reason': c.exclusion_reason,
            'pit_confidence': c.pit_confidence,
        })
    
    df = pd.DataFrame(rows)
    return df


def main():
    df = run_pilot()
    
    print('=' * 60)
    print('Phase 7.3-J：Single-Stock Replay Pilot Results')
    print('=' * 60)
    print(f'\nTotal cases: {len(df)}')
    
    print('\n## Final Candidate Distribution')
    print(df['final_candidate'].value_counts().to_string())
    
    print('\n## Filter Failure Analysis')
    for col in ['filter_market_cap', 'filter_st', 'filter_turnover_1d', 
                'filter_turnover_20d', 'filter_price_pos', 'filter_vol_ratio', 'filter_atr']:
        print(f'\n### {col}')
        print(df[col].value_counts().to_string())
    
    print('\n## Market Cap Quality')
    print(df['market_cap_quality'].value_counts().to_string())
    
    print('\n## PIT Confidence Distribution')
    print(df['pit_confidence'].value_counts().to_string())
    
    print('\n## Top Exclusion Reasons')
    all_reasons = []
    for reasons in df['exclusion_reason']:
        if reasons != 'NONE':
            all_reasons.extend(reasons.split('; '))
    reason_counts = pd.Series(all_reasons).value_counts()
    print(reason_counts.head(15).to_string())
    
    df.to_csv('replay_pilot_results.csv', index=False)
    print(f'\nResults saved to replay_pilot_results.csv')
    return df


if __name__ == '__main__':
    main()
