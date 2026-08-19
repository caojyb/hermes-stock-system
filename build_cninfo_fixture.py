"""
Phase 7.3-L：Rebuild CNINFO Fixtures with verified live data
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures'


def build_000001_fixture() -> pd.DataFrame:
    """平安银行：从 live CNINFO 验证的最小股本样本。"""
    rows = [
        # 2000-06-30：定期报告（APPROXIMATE）
        {
            '证券代码': '000001', '变动日期': '2000-06-30', '公告日期': '2000-08-18',
            '变动原因': '定期报告', '总股本': 155184.7092,
        },
        # 2000-12-08：配股上市（KNOWN_EFFECTIVE_DATE）
        {
            '证券代码': '000001', '变动日期': '2000-12-08', '公告日期': '2000-11-06',
            '变动原因': '配股上市', '总股本': 194582.2149,
        },
        # 2000-12-31：定期报告（APPROXIMATE）
        {
            '证券代码': '000001', '变动日期': '2000-12-31', '公告日期': None,
            '变动原因': '定期报告', '总股本': 194582.2149,
        },
        # 2022-06-30：定期报告（APPROXIMATE）
        {
            '证券代码': '000001', '变动日期': '2022-06-30', '公告日期': '2022-08-18',
            '变动原因': '定期报告', '总股本': 1940591.8198,
        },
    ]
    return pd.DataFrame(rows)


def build_002594_fixture() -> pd.DataFrame:
    """比亚迪：从 live CNINFO 验证的最小股本样本。"""
    rows = [
        # 2011-06-30：A股上市+定期报告（KNOWN_EFFECTIVE_DATE，因为含"A股上市"）
        {
            '证券代码': '002594', '变动日期': '2011-06-30', '公告日期': '2011-08-23',
            '变动原因': 'A股上市,定期报告', '总股本': 235410.0,
        },
        # 2014-05-30：配股上市（KNOWN_EFFECTIVE_DATE）
        {
            '证券代码': '002594', '变动日期': '2014-05-30', '公告日期': None,
            '变动原因': '配股上市', '总股本': 247600.0,
        },
        # 2024-05-10：股份回购（KNOWN_EFFECTIVE_DATE）
        {
            '证券代码': '002594', '变动日期': '2024-05-10', '公告日期': None,
            '变动原因': '股份回购', '总股本': 290926.5855,
        },
    ]
    return pd.DataFrame(rows)


def build_600519_fixture() -> pd.DataFrame:
    """贵州茅台：从 live CNINFO 验证的最小股本样本。"""
    rows = [
        # 2001-08-27：A股上市（KNOWN_EFFECTIVE_DATE）
        {
            '证券代码': '600519', '变动日期': '2001-08-27', '公告日期': None,
            '变动原因': 'A股上市', '总股本': 25000.0,
        },
        # 2022-06-30：定期报告（APPROXIMATE）
        {
            '证券代码': '600519', '变动日期': '2022-06-30', '公告日期': '2022-08-03',
            '变动原因': '定期报告', '总股本': 125619.78,
        },
        # 2024-12-31：定期报告（APPROXIMATE）
        {
            '证券代码': '600519', '变动日期': '2024-12-31', '公告日期': '2025-04-03',
            '变动原因': '定期报告', '总股本': 125619.78,
        },
    ]
    return pd.DataFrame(rows)


def save_all_fixtures() -> None:
    """保存所有 fixture。"""
    FIXTURE_DIR.mkdir(exist_ok=True)
    for name, builder in [
        ('cninfo_000001', build_000001_fixture),
        ('cninfo_002594', build_002594_fixture),
        ('cninfo_600519', build_600519_fixture),
    ]:
        df = builder()
        path = FIXTURE_DIR / f'{name}.parquet'
        df.to_parquet(path, index=False)
        print(f'{name}: {len(df)} rows -> {path}')


if __name__ == '__main__':
    save_all_fixtures()
