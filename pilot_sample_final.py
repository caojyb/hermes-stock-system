"""
Phase 7.3-J：Single-Stock Replay Pilot - Fixed Sample

固定、可复现的 Pilot 样本。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

# 候选股票池（排除有 ST 证据的股票）
PILOT_SYMBOLS = [
    # 大盘蓝筹（>90B，会过滤掉）
    '600519',  # 贵州茅台
    '000858',  # 五粮液
    '601318',  # 中国平安
    '600036',  # 招商银行
    '000002',  # 万科A
    '000333',  # 美的集团
    '600276',  # 恒瑞医药
    '000568',  # 泸州老窖
    # 中盘（5-90B）
    '002594',  # 比亚迪
    '002415',  # 海康威视
    '000001',  # 平安银行
    '600028',  # 中国石化
    '601899',  # 紫金矿业
    '002230',  # 科大讯飞
    '300059',  # 东方财富
    '002475',  # 立讯精密
    '000538',  # 云南白药
    '002304',  # 洋河股份
    '600887',  # 伊利股份（有 ST 证据，排除）
    # 更多中盘/小盘
    '000725',  # 京东方A
    '002304',  # 洋河股份
    '600809',  # 山西汾酒
    '000596',  # 古井贡酒
    '002352',  # 顺丰控股
    '601888',  # 中国中免
    '002714',  # 牧原股份
    '300059',  # 东方财富
    '603259',  # 药明康德
    '688981',  # 中芯国际
    '600900',  # 长江电力
]

# 历史日期（每只股票 15 个日期）
PILOT_DATES = [
    # 2000s
    date(2005, 6, 15),
    date(2005, 12, 15),
    date(2007, 10, 15),  # 牛市高点
    date(2008, 6, 15),
    date(2008, 10, 15),  # 熊市低点
    # 2010s
    date(2010, 6, 15),
    date(2012, 12, 15),
    date(2013, 6, 15),   # 震荡市
    date(2015, 6, 15),   # 牛市
    date(2016, 1, 15),   # 股灾后
    date(2018, 10, 15),  # 熊市低点
    date(2019, 4, 15),   # 反弹
    # 2020s
    date(2020, 6, 15),
    date(2021, 2, 15),   # 核心资产高点
    date(2022, 12, 15),
    date(2023, 10, 15),
    date(2024, 6, 15),
]

# 排除有 ST 证据的股票
EXCLUDE_SYMBOLS = {'600887'}  # 伊利股份曾用名含 *ST伊利

# 最终样本
FINAL_SYMBOLS = [s for s in PILOT_SYMBOLS if s not in EXCLUDE_SYMBOLS]


def get_sample() -> pd.DataFrame:
    """生成 Pilot 样本。"""
    rows = []
    for symbol in FINAL_SYMBOLS:
        for target_date in PILOT_DATES:
            rows.append({
                'symbol': symbol,
                'target_date': target_date.isoformat(),
            })
    df = pd.DataFrame(rows)
    return df


if __name__ == '__main__':
    df = get_sample()
    print(f'Total cases: {len(df)}')
    print(f'Symbols: {len(FINAL_SYMBOLS)}')
    print(f'Dates per symbol: {len(PILOT_DATES)}')
    print(f'\nExcluded symbols: {EXCLUDE_SYMBOLS}')
    df.to_csv('pilot_sample_final.csv', index=False)
    print('Sample saved to pilot_sample_final.csv')
