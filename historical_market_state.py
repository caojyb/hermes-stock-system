"""
Phase 7.3-C：Historical Market State Reconstruction Audit
非 OHLCV 市场状态审计与最小 Adapter（不修改生产数据）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

MARKET_DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
FORMULA_VERSION = 'pit-v1.0'


def _conn():
    return sqlite3.connect(str(MARKET_DB))


# ──────────────────────────────────────────────
# Historical Universe（基于 klines 首末交易日）
# ──────────────────────────────────────────────

def get_universe_as_of(as_of_date: str) -> dict:
    """构造 T 日最低限度 Universe：有 K 线数据的 code + first/last trade date。"""
    con = _conn()
    cur = con.cursor()
    cur.execute('''
        SELECT code, MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as trade_days
        FROM klines
        WHERE date <= ?
        GROUP BY code
    ''', (as_of_date,))
    rows = cur.fetchall()
    con.close()
    return {
        'as_of_date': as_of_date,
        'source': 'HISTORICAL_REPLAY',
        'universe': [
            {'code': r[0], 'first_date': r[1], 'last_date': r[2], 'trade_days': r[3]}
            for r in rows
        ],
        'count': len(rows),
    }


# ──────────────────────────────────────────────
# Historical Market Cap（当前无法重建）
# ──────────────────────────────────────────────

def get_market_cap(as_of_date: str, symbol: str) -> dict:
    """历史市值：当前 stocks 表无历史股本，无法重建。"""
    return {
        'symbol': symbol,
        'as_of_date': as_of_date,
        'source': 'HISTORICAL_REPLAY',
        'market_cap': 'UNKNOWN',
        'status': 'BLOCKED',
        'reason': 'stocks.total_mcap 为当前快照，无历史股本/历史市值序列',
    }


# ──────────────────────────────────────────────
# Historical ST Status（当前无法重建）
# ──────────────────────────────────────────────

def get_st_status(as_of_date: str, symbol: str) -> dict:
    """历史 ST 状态：无历史 ST 变更记录。"""
    return {
        'symbol': symbol,
        'as_of_date': as_of_date,
        'source': 'HISTORICAL_REPLAY',
        'st_status': 'UNKNOWN',
        'status': 'BLOCKED',
        'reason': 'stocks.is_st 为当前快照，无历史 ST 变更记录',
    }


# ──────────────────────────────────────────────
# Historical Industry（当前无法重建）
# ──────────────────────────────────────────────

def get_industry(as_of_date: str, symbol: str) -> dict:
    """历史行业分类：无历史行业变更记录。"""
    return {
        'symbol': symbol,
        'as_of_date': as_of_date,
        'source': 'HISTORICAL_REPLAY',
        'industry': 'UNKNOWN',
        'status': 'BLOCKED',
        'reason': 'stocks.sw_industry_name/sector 为当前快照，无历史行业序列',
    }


# ──────────────────────────────────────────────
# Historical Market State 聚合
# ──────────────────────────────────────────────

def get_historical_market_state(symbol: str, as_of_date: str) -> dict:
    """Point-in-Time 市场状态查询（只读，不修改生产数据）。"""
    universe = get_universe_as_of(as_of_date)
    in_universe = any(u['code'] == symbol for u in universe['universe'])

    return {
        'symbol': symbol,
        'as_of_date': as_of_date,
        'source': 'HISTORICAL_REPLAY',
        'formula_version': FORMULA_VERSION,
        'in_universe': in_universe,
        'universe_source': 'klines first/last trade date',
        'market_cap': get_market_cap(as_of_date, symbol),
        'st_status': get_st_status(as_of_date, symbol),
        'industry': get_industry(as_of_date, symbol),
        'pit_cutoff': as_of_date,
        'limitation_codes': [
            'MARKET_CAP_BLOCKED',
            'ST_STATUS_BLOCKED',
            'INDUSTRY_BLOCKED',
            'PORTFOLIO_NONE',
        ],
    }
