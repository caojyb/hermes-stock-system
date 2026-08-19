"""
Phase 7.3-J：Single-Stock Historical Replay Pilot

严格 PIT 单票历史 Replay 引擎。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

# V1 参数（从 scan_doubling_potential.py 读取）
PARAMS = {
    'mcap_min': 5,          # 5 亿
    'mcap_max': 90,         # 90 亿
    'atr_pct_min': 3.0,     # ATR%
    'turnover_min': 8000,   # 万
    'avg_amount_20d': 4000, # 万
    'vol_ratio_min': 2.7,
    'price_pos_max': 40.0,  # %
}


@dataclass
class ReplayCase:
    """单票 Replay 案例。"""
    replay_case_id: str
    symbol: str
    as_of_date: str
    data_quality: str
    universe_status: str
    st_status: str
    st_date_quality: str
    market_cap: Optional[float]
    market_cap_quality: str
    ma20: Optional[float]
    atr: Optional[float]
    atr_pct: Optional[float]
    macd: Optional[float]
    volume_ratio: Optional[float]
    turnover_1d: Optional[float]
    avg_turnover_20d: Optional[float]
    price_pos: Optional[float]
    filter_market_cap: str
    filter_st: str
    filter_turnover_1d: str
    filter_turnover_20d: str
    filter_price_pos: str
    filter_vol_ratio: str
    filter_atr: str
    final_candidate: str
    exclusion_reason: str
    pit_confidence: str
    source: str = 'HISTORICAL_REPLAY'


def get_klines(symbol: str, as_of_date: date, lookback: int = 500) -> pd.DataFrame:
    """获取历史 K 线（PIT-safe）。"""
    con = sqlite3.connect(str(DB))
    query = """
        SELECT date, close, volume, turnover, high, low
        FROM klines
        WHERE code = ? AND date <= ?
        ORDER BY date DESC
        LIMIT ?
    """
    df = pd.read_sql_query(query, con, params=(symbol, as_of_date.isoformat(), lookback))
    con.close()
    df = df.iloc[::-1].reset_index(drop=True)  # 升序
    return df


def compute_technical_features(klines: pd.DataFrame) -> dict:
    """计算技术指标。"""
    if len(klines) < 60:
        return {}
    
    closes = klines['close'].dropna().tolist()
    highs = klines['high'].dropna().tolist()
    lows = klines['low'].dropna().tolist()
    volumes = klines['volume'].dropna().tolist()
    turnovers = klines['turnover'].fillna(0).tolist()
    
    # MA20
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    
    # ATR
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = highs[i], lows[i], closes[i-1]
        if h and l and pc:
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else None
    atr_pct = (atr / closes[-1] * 100) if atr and closes[-1] else None
    
    # MACD（简化版）
    if len(closes) >= 26:
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1]
        macd = (ema12 - ema26) / closes[-1] * 100 if closes[-1] else None
    else:
        macd = None
    
    # Volume Ratio（5 日 / 20 日）
    if len(volumes) >= 25:
        vol_5 = sum(volumes[-5:]) / 5
        vol_20 = sum(volumes[-25:-5]) / 20
        vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
    else:
        vol_ratio = None
    
    # Turnover
    turnover_1d = turnovers[-1] if turnovers else None
    if len(turnovers) >= 25:
        avg_turnover_20d = sum(turnovers[-25:-5]) / 20
    else:
        avg_turnover_20d = None
    
    # Price Position（250 日分位）
    if len(closes) >= 250:
        recent_250 = closes[-250:]
        price_pos = (closes[-1] - min(recent_250)) / (max(recent_250) - min(recent_250)) * 100
    else:
        price_pos = None
    
    return {
        'ma20': ma20,
        'atr': atr,
        'atr_pct': atr_pct,
        'macd': macd,
        'vol_ratio': vol_ratio,
        'turnover_1d': turnover_1d,
        'avg_turnover_20d': avg_turnover_20d,
        'price_pos': price_pos,
    }


def replay_v1_filters(symbol: str, as_of_date: date, features: dict, 
                       mcap: Optional[float], mcap_quality: str,
                       st_status: str) -> ReplayCase:
    """执行 V1 过滤链。"""
    case_id = f"{symbol}_{as_of_date.isoformat()}"
    
    # 初始化过滤结果
    results = {
        'market_cap': 'UNKNOWN',
        'st': 'UNKNOWN',
        'turnover_1d': 'UNKNOWN',
        'turnover_20d': 'UNKNOWN',
        'price_pos': 'UNKNOWN',
        'vol_ratio': 'UNKNOWN',
        'atr': 'UNKNOWN',
    }
    
    exclusion_reasons = []
    
    # 1. Market Cap
    if mcap is None or mcap_quality == 'UNKNOWN':
        results['market_cap'] = 'UNKNOWN'
        exclusion_reasons.append('MARKET_CAP_UNKNOWN')
    elif mcap < PARAMS['mcap_min'] * 1e8:
        results['market_cap'] = 'FAIL'
        exclusion_reasons.append('MARKET_CAP_BELOW_5B')
    elif mcap > PARAMS['mcap_max'] * 1e8:
        results['market_cap'] = 'FAIL'
        exclusion_reasons.append('MARKET_CAP_ABOVE_90B')
    else:
        results['market_cap'] = 'PASS'
    
    # 2. ST
    if st_status == 'KNOWN_NORMAL':
        results['st'] = 'PASS'
    elif st_status == 'UNKNOWN':
        results['st'] = 'UNKNOWN'
        exclusion_reasons.append('ST_UNKNOWN')
    else:  # ST / *ST
        results['st'] = 'FAIL'
        exclusion_reasons.append('ST_FILTERED')
    
    # 3. Turnover 1D
    if features.get('turnover_1d') is None:
        results['turnover_1d'] = 'UNKNOWN'
        exclusion_reasons.append('TURNOVER_1D_UNKNOWN')
    elif features['turnover_1d'] < PARAMS['turnover_min'] * 10000:
        results['turnover_1d'] = 'FAIL'
        exclusion_reasons.append('TURNOVER_1D_BELOW')
    else:
        results['turnover_1d'] = 'PASS'
    
    # 4. Turnover 20D
    if features.get('avg_turnover_20d') is None:
        results['turnover_20d'] = 'UNKNOWN'
        exclusion_reasons.append('TURNOVER_20D_UNKNOWN')
    elif features['avg_turnover_20d'] < PARAMS['avg_amount_20d'] * 10000:
        results['turnover_20d'] = 'FAIL'
        exclusion_reasons.append('TURNOVER_20D_BELOW')
    else:
        results['turnover_20d'] = 'PASS'
    
    # 5. Price Position
    if features.get('price_pos') is None:
        results['price_pos'] = 'UNKNOWN'
        exclusion_reasons.append('PRICE_POS_UNKNOWN')
    elif features['price_pos'] > PARAMS['price_pos_max']:
        results['price_pos'] = 'FAIL'
        exclusion_reasons.append('PRICE_POS_ABOVE')
    else:
        results['price_pos'] = 'PASS'
    
    # 6. Volume Ratio
    if features.get('vol_ratio') is None:
        results['vol_ratio'] = 'UNKNOWN'
        exclusion_reasons.append('VOL_RATIO_UNKNOWN')
    elif features['vol_ratio'] < PARAMS['vol_ratio_min']:
        results['vol_ratio'] = 'FAIL'
        exclusion_reasons.append('VOL_RATIO_BELOW')
    else:
        results['vol_ratio'] = 'PASS'
    
    # 7. ATR
    if features.get('atr_pct') is None:
        results['atr'] = 'UNKNOWN'
        exclusion_reasons.append('ATR_UNKNOWN')
    elif features['atr_pct'] < PARAMS['atr_pct_min']:
        results['atr'] = 'FAIL'
        exclusion_reasons.append('ATR_BELOW')
    else:
        results['atr'] = 'PASS'
    
    # 最终判断
    if 'UNKNOWN' in [v for k, v in results.items() if k != 'market_cap']:
        final_candidate = 'UNKNOWN'
        pit_confidence = 'LOW'
    elif 'FAIL' in results.values():
        final_candidate = 'FAIL'
        pit_confidence = 'HIGH'
    else:
        final_candidate = 'PASS'
        pit_confidence = 'HIGH'
    
    return ReplayCase(
        replay_case_id=case_id,
        symbol=symbol,
        as_of_date=as_of_date.isoformat(),
        data_quality='PARTIAL',
        universe_status='PARTIAL',
        st_status=st_status,
        st_date_quality='BLOCKED',
        market_cap=mcap,
        market_cap_quality=mcap_quality,
        ma20=features.get('ma20'),
        atr=features.get('atr'),
        atr_pct=features.get('atr_pct'),
        macd=features.get('macd'),
        volume_ratio=features.get('vol_ratio'),
        turnover_1d=features.get('turnover_1d'),
        avg_turnover_20d=features.get('avg_turnover_20d'),
        price_pos=features.get('price_pos'),
        filter_market_cap=results['market_cap'],
        filter_st=results['st'],
        filter_turnover_1d=results['turnover_1d'],
        filter_turnover_20d=results['turnover_20d'],
        filter_price_pos=results['price_pos'],
        filter_vol_ratio=results['vol_ratio'],
        filter_atr=results['atr'],
        final_candidate=final_candidate,
        exclusion_reason='; '.join(exclusion_reasons) if exclusion_reasons else 'NONE',
        pit_confidence=pit_confidence,
    )
