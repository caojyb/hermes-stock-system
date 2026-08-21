#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G2: Volume Ratio × Regime — 综合分析 & 产物生成
========================================================
合并 2015-2019 / 2020-2024 两段研究 trace+outcome，映射 regime，
生成全部 VR 研究产物（parquet + summary json + findings）。
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np

CRON_DIR = Path('/home/caojy/.hermes/scripts/cron')
RESEARCH = Path(__file__).resolve().parent.parent.parent  # .../research
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # volume_ratio

import vr_analysis as va

ART = Path(__file__).resolve().parent / 'artifacts'
RESEARCH_VERSION = 'phase-8g2-v1'
OUTCOME_TYPE = 'COUNTERFACTUAL_RESEARCH'


def load_regime_map() -> dict:
    df = pd.read_csv('/home/caojy/.hermes/scripts/cron/research/artifacts/regime_v1/regime_daily.csv')
    m = {}
    for _, r in df.iterrows():
        m[str(r['date'])] = str(r['regime_label'])
    return m


def map_regime_cn_to_en(label: str) -> str:
    return {'🔴高波动': 'HIGH_VOLATILITY', '🟢强趋势': 'STRONG_TREND',
            '⚫低量能': 'LOW_VOLUME', '🟡震荡市': 'SIDEWAYS'}.get(label, 'UNKNOWN')


def load_all() -> pd.DataFrame:
    """合并两段 trace + outcome，映射 regime。"""
    trace_parts, out_parts = [], []
    for seg in ['2015_2019', '2020_2024']:
        t = pd.read_csv(ART / f'vr_trace_{seg}.csv')
        o = pd.read_csv(ART / f'vr_outcomes_{seg}.csv')
        trace_parts.append(t)
        out_parts.append(o)
    trace = pd.concat(trace_parts, ignore_index=True)
    out = pd.concat(out_parts, ignore_index=True)
    # 合并：trace 提供 filter 指标，out 提供 outcome
    df = trace.merge(out[['symbol', 'candidate_date', 'fwd_5d', 'fwd_10d', 'fwd_20d',
                          'mae', 'mfe', 'max_return', 'min_return']],
                     left_on=['symbol', 'as_of_date'], right_on=['symbol', 'candidate_date'],
                     how='left')
    # regime 映射
    rmap = load_regime_map()
    df['regime'] = df['as_of_date'].map(rmap).map(map_regime_cn_to_en)
    df['regime'] = df['regime'].fillna('UNKNOWN')
    df['research_version'] = RESEARCH_VERSION
    df['source'] = 'RESEARCH'
    df['outcome_type'] = OUTCOME_TYPE
    # vr numeric
    df['vr'] = pd.to_numeric(df['vol_ratio'], errors='coerce')
    # market_cap_quality
    df['market_cap_quality'] = df['market_cap'].map(
        lambda x: 'APPROXIMATE' if str(x) == 'APPROXIMATE' else ('UNKNOWN' if str(x) == 'UNKNOWN' else 'PIT_SAFE'))
    df['st_quality'] = 'UNKNOWN'  # 无历史 ST
    df['data_quality'] = 'RESEARCH'
    return df


def main():
    df = load_all()
    print(f'total rows: {len(df)}')
    # 过滤 UNKNOWN regime 与无 vr
    df = df[df['regime'] != 'UNKNOWN'].copy()
    df = df[df['vr'].notna()].copy()
    print(f'after regime/vr filter: {len(df)}')

    # 1. VR distribution
    dist = va.vr_distribution(df)
    with open(ART / 'vr_distribution.json', 'w', encoding='utf-8') as f:
        json.dump(dist, f, ensure_ascii=False, indent=2)
    print('\n=== VR Distribution (ALL) ===')
    print(dist['ALL_REGIMES'])

    # 2. candidate availability by VR band
    avail = va.candidate_availability(df)
    avail.to_parquet(ART / 'vr_candidate_availability.parquet', index=False)
    print('\n=== Candidate Availability by VR Band ===')
    print(avail.to_string())

    # 3. marginal coverage loss
    mcl = va.marginal_coverage_loss(df)
    print('\n=== Marginal Coverage Loss ===')
    print(json.dumps(mcl, indent=2))

    # 4. outcomes by VR band (candidate level)
    band_rows = []
    for band, (lo, hi) in va.VR_BANDS.items():
        if hi == float('inf'):
            bg = df[df['vr'] >= lo]
        else:
            bg = df[(df['vr'] >= lo) & (df['vr'] < hi)]
        st = va.outcome_stats(bg)
        st['vr_band'] = band
        band_rows.append(st)
    cand_outcomes = pd.DataFrame(band_rows)
    cand_outcomes.to_parquet(ART / 'candidate_vr_outcomes.parquet', index=False)
    print('\n=== Candidate Outcomes by VR Band (median) ===')
    for _, r in cand_outcomes.iterrows():
        m5 = r.get('fwd_5d', {}).get('median')
        m10 = r.get('fwd_10d', {}).get('median')
        m20 = r.get('fwd_20d', {}).get('median')
        print(f"{r['vr_band']}: N={r['N']} med5d={m5} med10d={m10} med20d={m20}")

    # 5. matrix
    matrix = va.build_matrix(df)
    matrix.to_parquet(ART / 'vr_regime_matrix.parquet', index=False)
    print('\n=== Regime × VR Matrix (median 20D) ===')
    print(matrix.pivot_table(index='regime', columns='vr_band', values='median_20d').to_string())

    # 6. conditional by market_cap / atr / price_pos
    # market cap bucket
    def mcap_bucket(v):
        s = str(v)
        if s in ('APPROXIMATE', 'UNKNOWN'): return s
        try:
            yi = float(v) / 1e8
        except Exception:
            return 'UNKNOWN'
        if yi < 5: return 'SMALL'
        if yi <= 90: return 'MID'
        return 'LARGE'
    df['market_cap_bucket'] = df['market_cap'].map(mcap_bucket)
    mc_cond = va.conditional_by(df, 'market_cap_bucket')
    mc_cond.to_parquet(ART / 'vr_conditional_marketcap.parquet', index=False)
    # atr bucket
    df['atr_bucket'] = pd.cut(pd.to_numeric(df['atr_pct'], errors='coerce'),
                              bins=[0, 2, 3.5, 100], labels=['LOW', 'MID', 'HIGH'])
    atr_cond = va.conditional_by(df, 'atr_bucket')
    atr_cond.to_parquet(ART / 'vr_conditional_atr.parquet', index=False)
    # price position bucket
    df['price_pos_bucket'] = pd.cut(pd.to_numeric(df['price_pos'], errors='coerce'),
                                    bins=[0, 20, 40, 60, 100], labels=['LOW', 'MIDLOW', 'MIDHIGH', 'HIGH'])
    pp_cond = va.conditional_by(df, 'price_pos_bucket')
    pp_cond.to_parquet(ART / 'vr_conditional_pricepos.parquet', index=False)
    print('\n=== Market Cap Conditional (median 20D by VR) ===')
    print(mc_cond.pivot_table(index='market_cap_bucket', columns='vr_band', values='median_20d').to_string())

    # 7. time stability
    ts = va.time_stability(df)
    ts.to_parquet(ART / 'vr_time_stability.parquet', index=False)
    print('\n=== Time Stability (median 20D by period × VR) ===')
    print(ts.pivot_table(index='period', columns='vr_band', values='median_20d').to_string())

    # 8. sensitivity
    sens = va.sensitivity(df)
    sens.to_parquet(ART / 'vr_sensitivity.parquet', index=False)
    print('\n=== Sensitivity (median 20D) ===')
    print(sens.pivot_table(index='mode', columns='vr_band', values='median_20d').to_string())

    # 9. monotonicity
    med_5 = [r.get('fwd_5d', {}).get('median') for _, r in cand_outcomes.iterrows()]
    med_10 = [r.get('fwd_10d', {}).get('median') for _, r in cand_outcomes.iterrows()]
    med_20 = [r.get('fwd_20d', {}).get('median') for _, r in cand_outcomes.iterrows()]
    mono = {
        '5d': va.monotonicity_status(med_5),
        '10d': va.monotonicity_status(med_10),
        '20d': va.monotonicity_status(med_20),
        'medians_5d': med_5, 'medians_10d': med_10, 'medians_20d': med_20,
    }
    print('\n=== Monotonicity ===', mono)

    # 10. 2.0-2.7 vs >=2.7 incremental
    b5 = df[(df['vr'] >= 2.0) & (df['vr'] < 2.7)]
    b6 = df[df['vr'] >= 2.7]
    inc = {
        'band_2.0-2.7': va.outcome_stats(b5),
        'band_>=2.7': va.outcome_stats(b6),
    }
    print('\n=== 2.0-2.7 vs >=2.7 Incremental ===')
    for k, v in inc.items():
        m5 = v.get('fwd_5d', {}).get('median'); m20 = v.get('fwd_20d', {}).get('median')
        print(f"{k}: N={v['N']} med5d={m5} med20d={m20}")

    # save summary
    summary = {
        'research_version': RESEARCH_VERSION,
        'source': 'RESEARCH',
        'outcome_type': OUTCOME_TYPE,
        'n_rows': int(len(df)),
        'vr_distribution': dist,
        'monotonicity': mono,
        'incremental_2_7_vs_2_0_2_7': inc,
        'marginal_coverage_loss': mcl,
        'regime_counts': df.groupby('regime').size().to_dict(),
        'period_counts': df.assign(period=pd.to_datetime(df['as_of_date']).dt.year.map(va.period_bucket)).groupby('period').size().to_dict(),
    }
    with open(ART / 'vr_research_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print('\nsaved summary + all artifacts to', ART)


if __name__ == '__main__':
    main()
