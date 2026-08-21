#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G3: Entry Signal PIT Reconstruction
============================================
从历史 K 线 PIT 重建 V1 Entry Signal A/B/C/D。
严格复用 daily_data_refresh.py 的公式（见 L303-356）。

Signal A: close > MA20 且 MA20 >= 前日 MA20（需 >=21 根 K 线）
Signal B: 3日量 / 10日均量 > 1.8（需 >=13 根）
Signal C: close >= 20日最高 high（需 >=20 根）
Signal D: MACD 金叉（DIF 上穿 DEA）或 DIF>0 & DEA>0 & DIF>DEA（需 >=35 根）

Entry Confirmed: signal_count >= 3（本模块只重建信号，gate 由上层决定）
"""
from __future__ import annotations
import os, sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

CRON_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(CRON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # research/

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
RESEARCH_VERSION = 'phase-8g3-v1'
OUTCOME_TYPE = 'COUNTERFACTUAL_RESEARCH'
SOURCE = 'RESEARCH'


def _ema(vals: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    res = [vals[0]]
    for x in vals[1:]:
        res.append(x * k + res[-1] * (1 - k))
    return res


def compute_signal_a(closes: list[float]) -> int:
    """A: close > MA20 且 MA20 >= 前日 MA20（需 >=21 根）"""
    if len(closes) < 21:
        return 0
    ma20 = sum(closes[-20:]) / 20.0
    ma20_prev = sum(closes[-21:-1]) / 20.0
    if closes[-1] > ma20 and ma20 >= ma20_prev:
        return 1
    return 0


def compute_signal_b(volumes: list[float]) -> int:
    """B: 3日量 / 10日均量 > 1.8（需 >=13 根）"""
    if len(volumes) < 13:
        return 0
    v3 = sum(volumes[-3:])
    v10 = sum(volumes[-13:-3]) / 10.0
    if v10 > 0 and v3 > v10 * 1.8:
        return 1
    return 0


def compute_signal_c(highs: list[float]) -> int:
    """C: close >= 20日最高 high（需 >=20 根）"""
    if len(highs) < 20:
        return 0
    if highs[-1] >= max(highs[-20:]):
        return 1
    return 0


def compute_signal_d(closes: list[float]) -> int:
    """D: MACD 金叉（DIF 上穿 DEA）或 DIF>0 & DEA>0 & DIF>DEA（需 >=35 根）"""
    if len(closes) < 35:
        return 0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = _ema(dif[-20:], 9)  # 用最近 20 个 DIF 值计算 DEA
    if len(dif) < 2 or len(dea) < 2:
        return 0
    dc, dp = dif[-1], dif[-2]
    dea_c, dea_p = dea[-1], dea[-2]
    if (dp < dea_p and dc > dea_c) or (dc > 0 and dea_c > 0 and dc > dea_c):
        return 1
    return 0


def compute_signals(closes: list[float], highs: list[float], volumes: list[float]) -> dict:
    """对单个时间窗口计算 A/B/C/D 信号。"""
    return {
        'signal_a': compute_signal_a(closes),
        'signal_b': compute_signal_b(volumes),
        'signal_c': compute_signal_c(highs),
        'signal_d': compute_signal_d(closes),
        'signal_count': (compute_signal_a(closes) + compute_signal_b(volumes)
                         + compute_signal_c(highs) + compute_signal_d(closes)),
        'entry_confirmed': (compute_signal_a(closes) + compute_signal_b(volumes)
                            + compute_signal_c(highs) + compute_signal_d(closes)) >= 3,
    }


if __name__ == '__main__':
    # 自测
    closes = list(range(100, 121))  # 21 根递增
    print('A:', compute_signal_a(closes))  # 应 1（close>ma20, ma20 上升）
    vols = [100]*10 + [200]*3
    print('B:', compute_signal_b(vols))  # 应 1（3日/10日>1.8）
    highs = list(range(100, 120)) + [119.9]
    print('C:', compute_signal_c(highs))  # 应 0（close=119.9 < max=119）
    print('D:', compute_signal_d(closes))  # 测试
    sigs = compute_signals(closes, highs, vols)
    print('signals:', sigs)
