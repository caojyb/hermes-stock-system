"""
Phase 7.3-B：Historical Feature Reconstruction
从 klines 重建 V1 技术指标，严格 Point-in-Time，不修改生产数据。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from decision.contract import BUY, HOLD, SELL, NO_TRADE, REDUCE, ADD

MARKET_DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
FORMULA_VERSION = 'pit-v1.0'
UNKNOWN = 'UNKNOWN'


def _get_klines(symbol: str, as_of_date: str, lookback_days: int = 120) -> list[dict]:
    """读取 symbol 在 as_of_date 及之前的 K 线，按日期升序。"""
    con = sqlite3.connect(str(MARKET_DB))
    cur = con.cursor()
    cur.execute(
        'SELECT date, open, high, low, close, volume, turnover, amplitude, change_pct '
        'FROM klines WHERE code=? AND date<=? ORDER BY date ASC',
        (symbol, as_of_date)
    )
    rows = []
    for r in cur.fetchall():
        rows.append({
            'date': r[0], 'open': r[1], 'high': r[2], 'low': r[3],
            'close': r[4], 'volume': r[5], 'turnover': r[6],
            'amplitude': r[7], 'change_pct': r[8]
        })
    con.close()
    return rows


def _ema(vals: list[float], period: int) -> list[float]:
    """指数移动平均。"""
    if len(vals) < period:
        return []
    k = 2.0 / (period + 1)
    res = [vals[0]]
    for x in vals[1:]:
        res.append(x * k + res[-1] * (1 - k))
    return res


def _sma(vals: list[float], period: int) -> Optional[float]:
    """简单移动平均。"""
    if len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def _true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[Optional[float]]:
    """True Range 序列。"""
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            prev_close = closes[i - 1]
            tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
            trs.append(tr)
    return trs


# ──────────────────────────────────────────────
# 公开 API
# ──────────────────────────────────────────────

def get_historical_features(symbol: str, as_of_date: str) -> dict:
    """Point-in-Time 历史特征重建。

    所有输入 K 线的 date <= as_of_date。
    返回 deterministic 结果（相同 symbol + as_of_date + formula_version 永远一致）。
    """
    klines = _get_klines(symbol, as_of_date, lookback_days=120)
    if not klines:
        return {
            'symbol': symbol, 'as_of_date': as_of_date, 'feature_source': 'HISTORICAL_REPLAY',
            'formula_version': FORMULA_VERSION, 'calculation_time': datetime.utcnow().isoformat() + 'Z',
            'source_table': 'klines',
            'ma20': UNKNOWN, 'atr_14': UNKNOWN, 'atr_14_pct': UNKNOWN,
            'macd': UNKNOWN, 'macd_signal': UNKNOWN, 'macd_hist': UNKNOWN,
            'volume_ratio': UNKNOWN, 'signal_score': UNKNOWN,
            'warmup_sufficient': False, 'pit_cutoff': as_of_date,
        }

    closes = [k['close'] for k in klines if k['close'] is not None]
    highs = [k['high'] for k in klines if k['high'] is not None]
    lows = [k['low'] for k in klines if k['low'] is not None]
    volumes = [k['volume'] for k in klines if k['volume'] is not None]

    warmup_ok = len(closes) >= 60  # 最多需要 60 日（MACD slow=26 + signal=9 + 缓冲）

    # MA20
    ma20 = _sma(closes, 20) if len(closes) >= 20 else None

    # ATR(14) - SMA 算法（与 v1_stress_test.py / param_verify_full.py 一致）
    atr_14 = None
    atr_14_pct = None
    if len(closes) >= 15:
        trs = _true_range(highs, lows, closes)
        # warm-up: 需要至少 15 根 K 线（14 日 TR + 首日）
        atr_raw = _sma(trs, 14)
        if atr_raw is not None:
            atr_14 = round(atr_raw, 4)
            current_price = closes[-1]
            if current_price:
                atr_14_pct = round(atr_14 / current_price * 100, 4)

    # MACD (12, 26, 9)
    macd = UNKNOWN
    macd_signal = UNKNOWN
    macd_hist = UNKNOWN
    if len(closes) >= 35:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        if len(ema12) == len(ema26) and len(ema12) >= 26:
            dif = [ema12[i] - ema26[i] for i in range(len(ema12))]
            dea = _ema(dif, 9)
            if len(dea) >= 9:
                macd = round(dif[-1], 4)
                macd_signal = round(dea[-1], 4)
                macd_hist = round((macd - macd_signal) * 2, 4)

    # Volume Ratio: 5 日均量 / 20 日均量（与 daily_data_refresh.py:269-271 一致）
    volume_ratio = None
    if len(volumes) >= 20:
        vol_5 = _sma(volumes, 5)
        vol_20 = _sma(volumes, 20)
        if vol_5 is not None and vol_20 is not None and vol_20 > 0:
            volume_ratio = round(vol_5 / vol_20, 4)

    # Signal Score: 生产代码未实现计算逻辑（daily_data_refresh.py 硬编码为 0）
    # 标记为 UNKNOWN，不伪造
    signal_score = UNKNOWN

    return {
        'symbol': symbol,
        'as_of_date': as_of_date,
        'feature_source': 'HISTORICAL_REPLAY',
        'formula_version': FORMULA_VERSION,
        'calculation_time': datetime.utcnow().isoformat() + 'Z',
        'source_table': 'klines',
        'ma20': ma20,
        'atr_14': atr_14,
        'atr_14_pct': atr_14_pct,
        'macd': macd,
        'macd_signal': macd_signal,
        'macd_hist': macd_hist,
        'volume_ratio': volume_ratio,
        'signal_score': signal_score,
        'warmup_sufficient': warmup_ok,
        'pit_cutoff': as_of_date,
        'klines_used': len(klines),
        'max_trade_date': klines[-1]['date'] if klines else None,
    }


def validate_pit_cutoff(symbol: str, as_of_date: str, features: dict) -> bool:
    """Property Test：历史特征使用的最大 trade_date 必须 <= as_of_date。"""
    max_date = features.get('max_trade_date')
    if not max_date:
        return True
    return max_date <= as_of_date
