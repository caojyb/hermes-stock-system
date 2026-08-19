"""
Phase 7.3-L：Replay Pilot V2 Sample Builder

构建无偏差、可复现的 Pilot V2 样本。
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
UNIVERSE_CSV = Path(__file__).resolve().parent / 'universe_clean_with_dates.csv'


def get_current_universe() -> pd.DataFrame:
    """获取当前股票池（仅用于采样，不作为历史证据）。"""
    if UNIVERSE_CSV.exists():
        df = pd.read_csv(UNIVERSE_CSV)
        df['first_kline_date'] = pd.to_datetime(df['first_kline_date']).dt.date
        df['mcap_b'] = df['total_mcap'] / 1e8
        df['size_group'] = pd.cut(
            df['mcap_b'],
            bins=[0, 5, 90, float('inf')],
            labels=['SMALL', 'MID', 'LARGE']
        )
        return df

    # fallback：从 DB 读取
    con = sqlite3.connect(str(DB))
    df = pd.read_sql('''
        SELECT code, name, total_mcap, sector
        FROM stocks
        WHERE total_mcap > 0
          AND code NOT LIKE '688%%'
          AND code NOT LIKE '787%%'
          AND name NOT LIKE '%%退%%'
        ORDER BY total_mcap ASC
    ''', con)
    con.close()
    df['mcap_b'] = df['total_mcap'] / 1e8
    df['size_group'] = pd.cut(
        df['mcap_b'],
        bins=[0, 5, 90, float('inf')],
        labels=['SMALL', 'MID', 'LARGE']
    )
    return df


def check_klines_availability(symbol: str, target_date: date, min_rows: int = 60) -> bool:
    """检查 K 线是否充足。"""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM klines
        WHERE code=? AND date<=?
        ORDER BY date DESC
    ''', (symbol, target_date.isoformat()))
    count = cur.fetchone()[0]
    con.close()
    return count >= min_rows


def get_klines_for_sample(symbol: str, target_date: date) -> int:
    """获取 K 线数量。"""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM klines
        WHERE code=? AND date<=?
        ORDER BY date DESC
    ''', (symbol, target_date.isoformat()))
    count = cur.fetchone()[0]
    con.close()
    return count


def build_pilot_v2_sample(
    small_cap_n: int = 20,
    mid_cap_n: int = 20,
    large_cap_n: int = 20,
    dates_per_symbol: int = 3,
) -> pd.DataFrame:
    """构建 Pilot V2 样本。
    
    Args:
        small_cap_n: Small Cap 股票数量
        mid_cap_n: Mid Cap 股票数量
        large_cap_n: Large Cap 股票数量
        dates_per_symbol: 每只股票的历史日期数量
    
    Returns:
        DataFrame with columns: symbol, name, target_date, size_group, mcap_b
    """
    universe = get_current_universe()
    
    # 按 size group 分组
    small = universe[universe['size_group'] == 'SMALL'].head(small_cap_n * 2)
    mid = universe[universe['size_group'] == 'MID'].head(mid_cap_n * 2)
    large = universe[universe['size_group'] == 'LARGE'].head(large_cap_n * 2)
    
    print(f'Universe: Small={len(small)}, Mid={len(mid)}, Large={len(large)}')
    
    # 历史日期（覆盖不同年代）
    target_dates = [
        # 2000s
        date(2005, 6, 15),
        date(2007, 10, 15),  # 牛市高点
        date(2008, 10, 15),  # 熊市低点
        # 2010s
        date(2012, 6, 15),
        date(2015, 6, 15),   # 牛市
        date(2018, 10, 15),  # 熊市低点
        # 2020s
        date(2020, 6, 15),
        date(2021, 10, 15),  # 核心资产高点
        date(2022, 12, 15),  # 近期
        date(2024, 6, 15),
    ]
    
    samples = []
    for group, group_df in [('SMALL', small), ('MID', mid), ('LARGE', large)]:
        target_n = {'SMALL': small_cap_n, 'MID': mid_cap_n, 'LARGE': large_cap_n}[group]
        
        for _, row in group_df.head(target_n).iterrows():
            symbol = row['code']
            name = row['name']
            
            # 为每只股票选择可用的历史日期
            available_dates = []
            for d in target_dates:
                if check_klines_availability(symbol, d):
                    available_dates.append(d)
            
            if len(available_dates) < 2:
                # 数据不足，跳过
                continue
            
            # 选择最多 dates_per_symbol 个日期
            selected_dates = available_dates[:dates_per_symbol]
            
            for d in selected_dates:
                samples.append({
                    'symbol': symbol,
                    'name': name,
                    'target_date': d,
                    'size_group': group,
                    'mcap_b': row['mcap_b'],
                    'sector': row['sector'],
                })
    
    df = pd.DataFrame(samples)
    return df


def main():
    df = build_pilot_v2_sample()
    
    print(f'\nTotal cases: {len(df)}')
    print(f'Symbols: {df["symbol"].nunique()}')
    print(f'Dates: {df["target_date"].nunique()}')
    
    print('\n## Size Group Distribution')
    print(df['size_group'].value_counts().to_string())
    
    print('\n## Year Distribution')
    df['year'] = pd.to_datetime(df['target_date']).dt.year
    print(df['year'].value_counts().sort_index().to_string())
    
    print('\n## Market Cap Distribution')
    print(f'<5B: {len(df[df["mcap_b"] < 5])}')
    print(f'5-90B: {len(df[(df["mcap_b"] >= 5) & (df["mcap_b"] <= 90)])}')
    print(f'>90B: {len(df[df["mcap_b"] > 90])}')
    
    # 保存样本
    df.to_csv('pilot_v2_sample.csv', index=False)
    print(f'\nSample saved to pilot_v2_sample.csv')
    
    return df


if __name__ == '__main__':
    main()
