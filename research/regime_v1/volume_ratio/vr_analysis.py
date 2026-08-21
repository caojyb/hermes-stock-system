#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G2: Volume Ratio × Regime Deep Research — 核心分析模块
================================================================
研究目标：VR 与未来收益关系，及其是否依赖 Market Regime。
严格 RESEARCH_ONLY：只读历史数据，不写生产 trades/execution/outcomes。
继承 G1 已验证的 PIT 语义 / Regime 重建 / Candidate 重建 / forward outcome。

Fixed VR Bands（分析前锁定，不根据结果修改）：
  B1: VR < 1.0
  B2: 1.0 <= VR < 1.3
  B3: 1.3 <= VR < 1.7
  B4: 1.7 <= VR < 2.0
  B5: 2.0 <= VR < 2.7
  B6: VR >= 2.7
2.7 是生产阈值，因此 2.0-2.7 与 >=2.7 必须单独保留。
"""
from __future__ import annotations
import os, sys, json, csv
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np

# ── 路径 ──
CRON_DIR = Path(__file__).resolve().parent.parent.parent.parent  # .../cron
sys.path.insert(0, str(CRON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # research/

ARTIFACTS = Path(__file__).resolve().parent / 'artifacts'
DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

RESEARCH_VERSION = 'phase-8g2-v1'
SOURCE = 'RESEARCH'
OUTCOME_TYPE = 'COUNTERFACTUAL_RESEARCH'

# ── Fixed VR Bands（分析前锁定）──
VR_BANDS = {
    'B1_<1.0':       (0.0, 1.0),
    'B2_1.0-1.3':    (1.0, 1.3),
    'B3_1.3-1.7':    (1.3, 1.7),
    'B4_1.7-2.0':    (1.7, 2.0),
    'B5_2.0-2.7':    (2.0, 2.7),
    'B6_>=2.7':      (2.7, float('inf')),
}
VR_2_7 = 2.7


def vr_band(vr: float | None) -> str | None:
    """将 VR 值分类到 Fixed Band。None 或 NaN → None。"""
    if vr is None or pd.isna(vr):
        return None
    for name, (lo, hi) in VR_BANDS.items():
        if vr >= lo and vr < hi:
            return name
    # VR >= inf 边界（不应发生）
    if vr >= 2.7:
        return 'B6_>=2.7'
    return None


def quantile_band(vr: float | None, q_labels: list[float]) -> str | None:
    """探索性 Quantile Band（可选）。vr<=q0→Q1, ... , >q_last→Q(n+1)。"""
    if vr is None or pd.isna(vr):
        return None
    for i, q in enumerate(q_labels):
        if vr <= q:
            return f'Q{i+1}'
    return f'Q{len(q_labels) + 1}'


def vr_distribution(df: pd.DataFrame) -> dict:
    """第一层：VR 分布统计（ALL_REGIMES 及分 Regime）。"""
    def _stats(vals: pd.Series) -> dict:
        v = vals.dropna()
        if len(v) == 0:
            return {'N': 0}
        qs = v.quantile([0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
        return {
            'N': int(len(v)),
            'mean': round(float(v.mean()), 4),
            'median': round(float(v.median()), 4),
            'min': round(float(v.min()), 4),
            'max': round(float(v.max()), 4),
            'Q10': round(float(qs[0.10]), 4),
            'Q25': round(float(qs[0.25]), 4),
            'Q50': round(float(qs[0.50]), 4),
            'Q75': round(float(qs[0.75]), 4),
            'Q90': round(float(qs[0.90]), 4),
            'Q95': round(float(qs[0.95]), 4),
            'Q99': round(float(qs[0.99]), 4),
        }
    out = {'ALL_REGIMES': _stats(df['vr'])}
    if 'regime' in df.columns:
        for regime, g in df.groupby('regime'):
            out[regime] = _stats(g['vr'])
    return out


def period_bucket(year: int) -> str:
    """时间分桶。"""
    if 2005 <= year <= 2009: return '2005_2009'
    if 2010 <= year <= 2014: return '2010_2014'
    if 2015 <= year <= 2019: return '2015_2019'
    if 2020 <= year <= 2024: return '2020_2024'
    return 'OTHER'


def outcome_stats(g: pd.DataFrame) -> dict:
    """对 5/10/20D forward 收益 + MAE/MFE 的统计。"""
    out = {'N': int(len(g))}
    for col in ['fwd_5d', 'fwd_10d', 'fwd_20d']:
        if col not in g.columns:
            continue
        v = pd.to_numeric(g[col], errors='coerce')
        known = v.dropna()
        unk = v.isna().sum()
        if len(known) == 0:
            out[col] = {'N': 0, 'unknown_rate': round(float(unk / max(len(v), 1)), 4)}
            continue
        qs = known.quantile([0.10, 0.25, 0.75, 0.90])
        out[col] = {
            'N': int(len(known)),
            'mean': round(float(known.mean()), 4),
            'median': round(float(known.median()), 4),
            'win_rate': round(float((known > 0).mean()), 4),
            'Q10': round(float(qs[0.10]), 4),
            'Q25': round(float(qs[0.25]), 4),
            'Q75': round(float(qs[0.75]), 4),
            'Q90': round(float(qs[0.90]), 4),
            'max': round(float(known.max()), 4),
            'min': round(float(known.min()), 4),
            'unknown_rate': round(float(unk / max(len(v), 1)), 4),
        }
    for col in ['mae', 'mfe']:
        if col not in g.columns:
            continue
        v = pd.to_numeric(g[col], errors='coerce')
        known = v.dropna()
        if len(known) == 0:
            out[col] = {'N': 0}
            continue
        out[col] = {
            'N': int(len(known)),
            'mean': round(float(known.mean()), 4),
            'median': round(float(known.median()), 4),
            'Q25': round(float(known.quantile(0.25)), 4),
            'Q75': round(float(known.quantile(0.75)), 4),
        }
    return out


def monotonicity_status(medians: list[float | None]) -> str:
    """检查 VR 上升是否对应 outcome 上升（跨 fixed bands 的 median）。"""
    valid = [(i, m) for i, m in enumerate(medians) if m is not None]
    if len(valid) < 3:
        return 'DATA_INSUFFICIENT'
    increasing = all(valid[i][1] <= valid[i+1][1] for i in range(len(valid)-1))
    non_decreasing = all(valid[i][1] <= valid[i+1][1] + 1e-9 for i in range(len(valid)-1))
    # 检测单调
    if increasing:
        return 'CONSISTENT'
    if non_decreasing:
        return 'PARTIAL'
    return 'NON_MONOTONIC'


def build_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Regime × VR Band 矩阵，每格 median 5/10/20D + MAE/MFE + N。"""
    rows = []
    regimes = ['STRONG_TREND', 'HIGH_VOLATILITY', 'LOW_VOLUME', 'SIDEWAYS', 'ALL_REGIMES']
    for regime in regimes:
        g = df if regime == 'ALL_REGIMES' else df[df['regime'] == regime]
        for band, (lo, hi) in VR_BANDS.items():
            if hi == float('inf'):
                bg = g[(g['vr'] >= lo)] if 'vr' in g else g.iloc[0:0]
            else:
                bg = g[(g['vr'] >= lo) & (g['vr'] < hi)] if 'vr' in g else g.iloc[0:0]
            st = outcome_stats(bg)
            rows.append({
                'regime': regime,
                'vr_band': band,
                'N': st['N'],
                'median_5d': st.get('fwd_5d', {}).get('median'),
                'median_10d': st.get('fwd_10d', {}).get('median'),
                'median_20d': st.get('fwd_20d', {}).get('median'),
                'mae': st.get('mae', {}).get('median'),
                'mfe': st.get('mfe', {}).get('median'),
                'unknown_rate': max([st.get(c, {}).get('unknown_rate', 0) for c in ['fwd_5d','fwd_10d','fwd_20d']], default=0),
            })
    return pd.DataFrame(rows)


def conditional_by(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """按某变量（market_cap/atr/price_pos）分桶后 × VR band 的 median 20D。"""
    rows = []
    for bucket, g in df.groupby(col):
        for band, (lo, hi) in VR_BANDS.items():
            if hi == float('inf'):
                bg = g[g['vr'] >= lo]
            else:
                bg = g[(g['vr'] >= lo) & (g['vr'] < hi)]
            st = outcome_stats(bg)
            rows.append({
                col: bucket,
                'vr_band': band,
                'N': st['N'],
                'median_20d': st.get('fwd_20d', {}).get('median'),
                'mfe': st.get('mfe', {}).get('median'),
                'mae': st.get('mae', {}).get('median'),
            })
    return pd.DataFrame(rows)


def time_stability(df: pd.DataFrame) -> pd.DataFrame:
    """按 period_bucket × VR band 的 median 20D。"""
    rows = []
    df = df.copy()
    df['period'] = pd.to_datetime(df['as_of_date']).dt.year.map(period_bucket)
    for period, g in df.groupby('period'):
        for band, (lo, hi) in VR_BANDS.items():
            if hi == float('inf'):
                bg = g[g['vr'] >= lo]
            else:
                bg = g[(g['vr'] >= lo) & (g['vr'] < hi)]
            st = outcome_stats(bg)
            rows.append({
                'period': period,
                'vr_band': band,
                'N': st['N'],
                'median_20d': st.get('fwd_20d', {}).get('median'),
            })
    return pd.DataFrame(rows)


def sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """STRICT / RESEARCH / SENSITIVITY 的 VR band 结果对比。"""
    rows = []
    modes = []
    # STRICT: 仅 market_cap KNOWN(PIT_SAFE)
    if 'market_cap_quality' in df.columns:
        strict = df[df['market_cap_quality'] == 'PIT_SAFE']
        modes.append(('STRICT', strict))
        research = df[df['market_cap_quality'].isin(['PIT_SAFE', 'APPROXIMATE'])]
        modes.append(('RESEARCH', research))
        # SENSITIVITY: UNKNOWN→NORMAL（全部当作可候选）
        modes.append(('SENSITIVITY', df))
    else:
        modes = [('RESEARCH', df), ('SENSITIVITY', df)]
    for mode, g in modes:
        for band, (lo, hi) in VR_BANDS.items():
            if hi == float('inf'):
                bg = g[g['vr'] >= lo]
            else:
                bg = g[(g['vr'] >= lo) & (g['vr'] < hi)]
            st = outcome_stats(bg)
            rows.append({
                'mode': mode,
                'vr_band': band,
                'N': st['N'],
                'median_20d': st.get('fwd_20d', {}).get('median'),
                'median_5d': st.get('fwd_5d', {}).get('median'),
            })
    return pd.DataFrame(rows)


def candidate_availability(df: pd.DataFrame) -> pd.DataFrame:
    """第三层：每个 VR band 的 PASS/FAIL/UNKNOWN + candidate_rate。"""
    rows = []
    for band, (lo, hi) in VR_BANDS.items():
        if hi == float('inf'):
            bg = df[df['vr'] >= lo]
        else:
            bg = df[(df['vr'] >= lo) & (df['vr'] < hi)]
        if len(bg) == 0:
            rows.append({'vr_band': band, 'total': 0, 'PASS': 0, 'FAIL': 0, 'UNKNOWN': 0,
                         'candidate_rate': 0.0, 'unknown_rate': 0.0})
            continue
        total = len(bg)
        if 'final_candidate' in bg.columns:
            pass_n = int((bg['final_candidate'] == 'PASS').sum())
            fail_n = int((bg['final_candidate'] == 'FAIL').sum())
            unk_n = int((bg['final_candidate'] == 'UNKNOWN').sum())
        else:
            pass_n = fail_n = unk_n = 0
        rows.append({
            'vr_band': band,
            'total': int(total),
            'PASS': pass_n,
            'FAIL': fail_n,
            'UNKNOWN': unk_n,
            'candidate_rate': round(pass_n / total, 4) if total else 0.0,
            'unknown_rate': round(unk_n / total, 4) if total else 0.0,
        })
    return pd.DataFrame(rows)


def marginal_coverage_loss(df: pd.DataFrame) -> dict:
    """第十节：边际候选损失（仅从 VR 条件观察的 threshold 敏感性）。"""
    if 'final_candidate' not in df.columns:
        return {'error': 'no final_candidate'}
    out = {}
    for thr in [1.0, 1.3, 1.7, 2.0, 2.7]:
        g = df[df['vr'] >= thr] if 'vr' in df else df.iloc[0:0]
        out[str(thr)] = {
            'total_in_band': int(len(g)),
            'pass': int((g['final_candidate'] == 'PASS').sum()) if len(g) else 0,
            'relative_to_2_7': round(len(g) / max(len(df[df['vr'] >= 2.7]), 1), 4) if len(df[df['vr'] >= 2.7]) else None,
        }
    return out


if __name__ == '__main__':
    import json
    # 自测
    print('VR_BANDS:', list(VR_BANDS.keys()))
    print('vr_band(0.5)=', vr_band(0.5))
    print('vr_band(1.15)=', vr_band(1.15))
    print('vr_band(2.5)=', vr_band(2.5))
    print('vr_band(2.9)=', vr_band(2.9))
    print('vr_band(None)=', vr_band(None))
    print('monotonicity[1,2,3]=', monotonicity_status([1.0, 2.0, 3.0]))
    print('monotonicity[3,2,1]=', monotonicity_status([3.0, 2.0, 1.0]))
    print('monotonicity[1,None,3]=', monotonicity_status([1.0, None, 3.0]))
