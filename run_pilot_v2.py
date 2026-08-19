"""
Phase 7.3-L：Replay Pilot V2 Runner

使用修正后的 Replay Engine 运行 Pilot V2。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from historical_share_layer import HistoricalShareLayer, HistoricalMarketCap
from historical_replay_engine import get_klines, compute_technical_features, replay_v1_filters

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def load_pilot_v2_sample(csv_path: str = 'pilot_v2_sample.csv') -> pd.DataFrame:
    """加载 Pilot V2 样本。"""
    df = pd.read_csv(csv_path, parse_dates=['target_date'])
    df['target_date'] = pd.to_datetime(df['target_date']).dt.date
    return df


def compute_replay_confidence(case_result: dict) -> str:
    """计算 Replay Confidence。"""
    # BLOCKED: ST UNKNOWN 或核心数据 UNKNOWN
    if case_result.get('filter_st') == 'UNKNOWN':
        return 'BLOCKED'
    if case_result.get('filter_market_cap') == 'UNKNOWN':
        return 'BLOCKED'
    
    # HIGH: 所有关键输入 PIT_SAFE
    if (case_result.get('market_cap_quality') == 'PIT_SAFE'
            and case_result.get('filter_st') == 'PASS'
            and case_result.get('filter_market_cap') == 'PASS'):
        return 'HIGH'
    
    # MEDIUM: 仅存在 RESEARCH Market Cap 等近似数据
    if case_result.get('market_cap_quality') in ('APPROXIMATE', 'RESEARCH'):
        return 'MEDIUM'
    
    # LOW: 多个非关键字段存在限制
    return 'LOW'


def run_pilot_v2(strict_mcap: bool = True) -> pd.DataFrame:
    """运行 Pilot V2。
    
    Args:
        strict_mcap: 如果 True，仅使用 STRICT Market Cap（KNOWN_EFFECTIVE_DATE）。
                     如果 False，使用 RESEARCH Market Cap（含 APPROXIMATE）。
    """
    df_sample = load_pilot_v2_sample()
    
    print(f'Loading Pilot V2 sample: {len(df_sample)} cases')
    print(f'Strict Market Cap: {strict_mcap}')
    
    # 共享 Historical Share Layer
    symbols = df_sample['symbol'].unique().tolist()
    print(f'Loading {len(symbols)} symbols...')
    layer = HistoricalShareLayer()
    layer.load_symbols_from_fixtures(symbols)
    mcap_layer = HistoricalMarketCap(layer)
    
    mode_label = 'STRICT' if strict_mcap else 'RESEARCH'
    print(f'Running {mode_label} Replay...')
    
    cases = []
    for _, row in df_sample.iterrows():
        symbol = row['symbol']
        target_date = row['target_date'].date() if hasattr(row['target_date'], 'date') else row['target_date']
        
        # 检查 klines
        klines = get_klines(symbol, target_date)
        if len(klines) < 60:
            continue
        
        # 计算技术指标
        features = compute_technical_features(klines)
        
        # 获取 Historical Market Cap
        result = mcap_layer.get_market_cap(symbol, target_date, strict=strict_mcap)
        mcap = result.market_cap if result.market_cap is not None else 0
        mcap_quality = result.quality.value
        
        # ST 状态（仍为 UNKNOWN）
        st_status = 'UNKNOWN'
        
        # 执行 V1 过滤
        case = replay_v1_filters(
            symbol=symbol,
            as_of_date=target_date,
            features=features,
            mcap=mcap,
            mcap_quality=mcap_quality,
            st_status=st_status,
        )
        
        # 计算 Replay Confidence
        case_dict = {
            'replay_case_id': case.replay_case_id,
            'symbol': case.symbol,
            'as_of_date': case.as_of_date,
            'size_group': row['size_group'],
            'mcap_b': row['mcap_b'],
            'sector': row['sector'],
            'data_quality': case.data_quality,
            'st_status': case.st_status,
            'market_cap_quality': case.market_cap_quality,
            'market_cap': case.market_cap,
            'ma20': case.ma20,
            'atr_pct': case.atr_pct,
            'macd': case.macd,
            'vol_ratio': case.volume_ratio,
            'price_pos': case.price_pos,
            'turnover_1d': case.turnover_1d,
            'avg_turnover_20d': case.avg_turnover_20d,
            'filter_market_cap': case.filter_market_cap,
            'filter_st': case.filter_st,
            'filter_turnover_1d': case.filter_turnover_1d,
            'filter_turnover_20d': case.filter_turnover_20d,
            'filter_price_pos': case.filter_price_pos,
            'filter_vol_ratio': case.filter_vol_ratio,
            'filter_atr': case.filter_atr,
            'final_candidate': case.final_candidate,
            'exclusion_reason': case.exclusion_reason,
            'pit_confidence': case.pit_confidence,
            'mode': mode_label,
        }
        
        # 添加 replay_confidence
        case_dict['replay_confidence'] = compute_replay_confidence(case_dict)
        
        cases.append(case_dict)
    
    df = pd.DataFrame(cases)
    
    # 生成 case hash（用于 deterministic 验证）
    df['case_hash'] = df.apply(lambda r: hashlib.md5(
        f'{r.symbol}|{r.as_of_date}|{r.market_cap}|{r.vol_ratio}|{r.price_pos}'.encode()
    ).hexdigest()[:8], axis=1)
    
    return df


def main():
    # 运行 STRICT
    df_strict = run_pilot_v2(strict_mcap=True)
    
    # 运行 RESEARCH
    df_research = run_pilot_v2(strict_mcap=False)
    
    # 合并
    df_strict['mode'] = 'STRICT'
    df_research['mode'] = 'RESEARCH'
    df_all = pd.concat([df_strict, df_research], ignore_index=True)
    
    # 保存结果
    df_strict.to_csv('pilot_v2_results_strict.csv', index=False)
    df_research.to_csv('pilot_v2_results_research.csv', index=False)
    df_all.to_csv('pilot_v2_results_all.csv', index=False)
    
    # 输出统计
    print('\n' + '=' * 60)
    print('Phase 7.3-L：Replay Pilot V2 Results')
    print('=' * 60)
    
    for mode in ['STRICT', 'RESEARCH']:
        df_mode = df_all[df_all['mode'] == mode]
        print(f'\n## {mode} Mode')
        print(f'Total cases: {len(df_mode)}')
        
        print(f'\nFinal Candidate:')
        print(df_mode['final_candidate'].value_counts().to_string())
        
        print(f'\nFilter Distribution:')
        for col in ['filter_market_cap', 'filter_st', 'filter_vol_ratio', 
                    'filter_price_pos', 'filter_atr']:
            print(f'\n{col}:')
            print(df_mode[col].value_counts().to_string())
        
        print(f'\nReplay Confidence:')
        print(df_mode['replay_confidence'].value_counts().to_string())
    
    print('\nResults saved to pilot_v2_results_*.csv')
    return df_all


if __name__ == '__main__':
    main()
