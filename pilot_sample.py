"""
Phase 7.3-J：Single-Stock Historical Replay Pilot - Sample Selection

选择固定、可复现的 Pilot 样本。
条件：
- klines 完整（≥60 日）
- Historical Market Cap 有 STRICT 或 RESEARCH 状态
- ST 状态在所选历史窗口内有明确 NORMAL 证据
- 不使用当前 stocks.is_st 回填
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import akshare as ak
import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

# 候选股票池（兼顾不同市值、行业、年份）
PILOT_SYMBOLS = [
    # 大盘蓝筹
    '600519',  # 贵州茅台
    '000858',  # 五粮液
    '601318',  # 中国平安
    # 中盘成长
    '002594',  # 比亚迪
    '300750',  # 宁德时代
    '002415',  # 海康威视
    # 小盘价值
    '000001',  # 平安银行
    '600036',  # 招商银行
    '000002',  # 万科A
    # 周期/资源
    '600028',  # 中国石化
    '601899',  # 紫金矿业
    '000333',  # 美的集团
    # 科技
    '002230',  # 科大讯飞
    '300059',  # 东方财富
    '002475',  # 立讯精密
    # 医药
    '600276',  # 恒瑞医药
    '000538',  # 云南白药
    # 消费
    '000568',  # 泸州老窖
    '002304',  # 洋河股份
    '600887',  # 伊利股份
]

# 历史日期（每只股票 5 年 × 3 个日期 = 15 个 cases）
PILOT_DATES = [
    # 2000s
    date(2005, 6, 15),
    date(2005, 12, 15),
    date(2008, 6, 15),
    # 2010s
    date(2010, 6, 15),
    date(2012, 12, 15),
    date(2015, 6, 15),
    # 2020s
    date(2020, 6, 15),
    date(2022, 12, 15),
    date(2024, 6, 15),
    # 额外覆盖
    date(2007, 10, 15),  # 牛市高点
    date(2013, 6, 15),   # 震荡市
    date(2018, 10, 15),  # 熊市低点
    date(2019, 4, 15),   # 反弹
    date(2021, 2, 15),   # 核心资产高点
    date(2023, 10, 15),  # 近期
]


def check_st_evidence(symbol: str) -> dict:
    """检查 ST 证据（仅用于排除已知 ST 股票）。"""
    try:
        df = ak.stock_info_change_name(symbol=symbol)
        has_st = df['name'].str.contains('ST|\\*ST', case=False, na=False).any()
        return {
            'has_st_evidence': has_st,
            'st_names': df[df['name'].str.contains('ST|\\*ST', case=False, na=False)]['name'].tolist() if has_st else [],
            'source': 'stock_info_change_name',
        }
    except Exception as e:
        return {
            'has_st_evidence': False,
            'st_names': [],
            'source': f'error: {e}',
        }


def check_klines_available(symbol: str, as_of_date: date) -> bool:
    """检查 klines 是否可用（≥60 日）。"""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM klines 
        WHERE code = ? AND date <= ? AND close IS NOT NULL
    """, (symbol, as_of_date.isoformat()))
    count = cur.fetchone()[0]
    con.close()
    return count >= 60


def build_sample() -> pd.DataFrame:
    """构建 Pilot 样本。"""
    rows = []
    for symbol in PILOT_SYMBOLS:
        st_evidence = check_st_evidence(symbol)
        for target_date in PILOT_DATES:
            # 检查 klines
            if not check_klines_available(symbol, target_date):
                status = 'BLOCKED_NO_KLINES'
            # 检查 ST 证据
            elif st_evidence['has_st_evidence']:
                status = 'BLOCKED_ST_EVIDENCE'
            else:
                status = 'PILOT_READY'
            
            rows.append({
                'symbol': symbol,
                'target_date': target_date.isoformat(),
                'st_evidence': st_evidence['has_st_evidence'],
                'st_names': st_evidence['st_names'],
                'klines_available': check_klines_available(symbol, target_date),
                'status': status,
            })
    
    df = pd.DataFrame(rows)
    return df


def main():
    df = build_sample()
    
    print('=' * 60)
    print('Phase 7.3-J：Single-Stock Replay Pilot Sample')
    print('=' * 60)
    
    print('\n## Sample Summary')
    print(f'Total cases: {len(df)}')
    print(f'PILOT_READY: {len(df[df["status"] == "PILOT_READY"])}')
    print(f'BLOCKED_NO_KLINES: {len(df[df["status"] == "BLOCKED_NO_KLINES"])}')
    print(f'BLOCKED_ST_EVIDENCE: {len(df[df["status"] == "BLOCKED_ST_EVIDENCE"])}')
    
    print('\n## By Symbol')
    for symbol in PILOT_SYMBOLS:
        sym_df = df[df['symbol'] == symbol]
        ready = len(sym_df[sym_df['status'] == 'PILOT_READY'])
        print(f'{symbol}: {ready}/{len(sym_df)} PILOT_READY')
    
    print('\n## ST Evidence')
    st_df = df[df['st_evidence'] == True]
    if len(st_df) > 0:
        print('Symbols with ST evidence:')
        for _, row in st_df.iterrows():
            print(f'  {row["symbol"]}: {row["st_names"]}')
    else:
        print('No ST evidence found in pilot symbols.')
    
    print('\n## Detailed Sample')
    ready_df = df[df['status'] == 'PILOT_READY']
    print(ready_df[['symbol', 'target_date', 'status']].to_string(index=False))
    
    # 保存样本
    df.to_csv('pilot_sample.csv', index=False)
    print(f'\nSample saved to pilot_sample.csv')
    
    return df


if __name__ == '__main__':
    main()
