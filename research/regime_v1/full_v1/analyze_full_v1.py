#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G3: Full V1 Candidate + Entry Signal — 综合分析
========================================================
合并 trace + candidate_outcomes + signal_outcomes，映射 regime，
生成全部产物（matrix/comparison/time_stability/sensitivity/summary）。
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np

# 确保 research 包可导入
for p in [
    Path('/home/caojy/.hermes/scripts/cron'),
    Path('/home/caojy/.hermes/scripts'),
    Path('/home/caojy/.hermes/scripts/cron').parent,
]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import research.regime_v1.volume_ratio.vr_analysis as va

ART = Path(__file__).resolve().parent / 'artifacts'
RESEARCH_VERSION = 'phase-8g3-v1'
OUTCOME_TYPE = 'COUNTERFACTUAL_RESEARCH'
SOURCE = 'RESEARCH'


def map_regime_cn_to_en(label: str) -> str:
    return {'🔴高波动': 'HIGH_VOLATILITY', '🟢强趋势': 'STRONG_TREND',
            '⚫低量能': 'LOW_VOLUME', '🟡震荡市': 'SIDEWAYS'}.get(label, 'UNKNOWN')


def load_regime_map() -> dict:
    df = pd.read_csv('/home/caojy/.hermes/scripts/cron/research/artifacts/regime_v1/regime_daily.csv')
    m = {}
    for _, r in df.iterrows():
        m[str(r['date'])] = str(r['regime_label'])
    return m


def load_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (candidate_df, signal_df)。"""
    trace = pd.read_parquet(ART / 'full_candidate_trace.parquet')
    rmap = load_regime_map()
    trace['regime'] = trace['as_of_date'].map(rmap).map(map_regime_cn_to_en).fillna('UNKNOWN')
    trace['research_version'] = RESEARCH_VERSION
    trace['source'] = SOURCE
    trace['outcome_type'] = OUTCOME_TYPE
    trace['vr'] = pd.to_numeric(trace['vol_ratio'], errors='coerce')

    # 读 outcomes
    cand_out = pd.read_parquet(ART / 'candidate_outcomes.parquet')
    sig_out = pd.read_parquet(ART / 'signal_outcomes.parquet')

    # 合并
    cand = trace.merge(cand_out[['symbol', 'candidate_date', 'fwd_5d', 'fwd_10d', 'fwd_20d',
                                  'mae', 'mfe', 'max_return', 'min_return']],
                       left_on=['symbol', 'as_of_date'], right_on=['symbol', 'candidate_date'],
                       how='left')
    sig = trace[trace['entry_confirmed'] == True].merge(
        sig_out[['symbol', 'candidate_date', 'fwd_5d', 'fwd_10d', 'fwd_20d',
                 'mae', 'mfe', 'max_return', 'min_return']],
        left_on=['symbol', 'as_of_date'], right_on=['symbol', 'candidate_date'],
        how='left')
    return cand, sig


def build_vr_regime_matrix(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Regime × VR(A/B/C) 矩阵。"""
    rows = []
    regimes = ['STRONG_TREND', 'HIGH_VOLATILITY', 'LOW_VOLUME', 'SIDEWAYS', 'ALL_REGIMES']
    # A/B/C 三档
    vr_bins = [('VR<2.0', lambda x: x < 2.0), ('2.0<=VR<2.7', lambda x: (x >= 2.0) & (x < 2.7)), ('VR>=2.7', lambda x: x >= 2.7)]
    for regime in regimes:
        g = df if regime == 'ALL_REGIMES' else df[df['regime'] == regime]
        for bname, bcond in vr_bins:
            bg = g[g['vr'].notna() & bcond(g['vr'])]
            st = va.outcome_stats(bg)
            rows.append({
                'label': label, 'regime': regime, 'vr_stage': bname,
                'N': st['N'],
                'median_5d': st.get('fwd_5d', {}).get('median'),
                'median_10d': st.get('fwd_10d', {}).get('median'),
                'median_20d': st.get('fwd_20d', {}).get('median'),
                'mae': st.get('mae', {}).get('median'),
                'mfe': st.get('mfe', {}).get('median'),
                'unknown_rate': max([st.get(c, {}).get('unknown_rate', 0) for c in ['fwd_5d','fwd_10d','fwd_20d']], default=0),
            })
    return pd.DataFrame(rows)


def conditional_by(df: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    rows = []
    for bucket, g in df.groupby(col):
        for bname, bcond in [('VR<2.0', lambda x: x < 2.0), ('2.0<=VR<2.7', lambda x: (x >= 2.0) & (x < 2.7)), ('VR>=2.7', lambda x: x >= 2.7)]:
            bg = g[g['vr'].notna() & bcond(g['vr'])]
            st = va.outcome_stats(bg)
            rows.append({col: bucket, 'vr_stage': bname, 'N': st['N'],
                         'median_20d': st.get('fwd_20d', {}).get('median'),
                         'mfe': st.get('mfe', {}).get('median'),
                         'mae': st.get('mae', {}).get('median')})
    return pd.DataFrame(rows)


def main():
    cand, sig = load_all()
    print(f'candidate rows: {len(cand)}, signal rows: {len(sig)}')

    # ── 1. Candidate VR×Regime matrix ──
    c_matrix = build_vr_regime_matrix(cand, 'candidate')
    c_matrix.to_parquet(ART / 'vr_regime_candidate_matrix.parquet', index=False)
    print('\n=== Candidate VR×Regime (median 20D) ===')
    print(c_matrix.pivot_table(index='regime', columns='vr_stage', values='median_20d').to_string())

    # ── 2. Signal VR×Regime matrix ──
    s_matrix = build_vr_regime_matrix(sig, 'signal')
    s_matrix.to_parquet(ART / 'vr_regime_signal_matrix.parquet', index=False)
    print('\n=== Signal VR×Regime (median 20D) ===')
    print(s_matrix.pivot_table(index='regime', columns='vr_stage', values='median_20d').to_string())

    # ── 3. Candidate vs Signal comparison ──
    comp = []
    for regime in ['ALL_REGIMES', 'STRONG_TREND', 'HIGH_VOLATILITY', 'LOW_VOLUME', 'SIDEWAYS']:
        cg = cand if regime == 'ALL_REGIMES' else cand[cand['regime'] == regime]
        sg = sig if regime == 'ALL_REGIMES' else sig[sig['regime'] == regime]
        for bname, bcond in [('VR<2.0', lambda x: x < 2.0), ('2.0<=VR<2.7', lambda x: (x >= 2.0) & (x < 2.7)), ('VR>=2.7', lambda x: x >= 2.7)]:
            cb = cg[cg['vr'].notna() & bcond(cg['vr'])]
            sb = sg[sg['vr'].notna() & bcond(sg['vr'])]
            cs = va.outcome_stats(cb); ss = va.outcome_stats(sb)
            comp.append({
                'regime': regime, 'vr_stage': bname,
                'cand_N': cs['N'], 'sig_N': ss['N'],
                'cand_med20d': cs.get('fwd_20d', {}).get('median'),
                'sig_med20d': ss.get('fwd_20d', {}).get('median'),
                'cand_med5d': cs.get('fwd_5d', {}).get('median'),
                'sig_med5d': ss.get('fwd_5d', {}).get('median'),
            })
    comp_df = pd.DataFrame(comp)
    comp_df.to_parquet(ART / 'candidate_vs_signal_comparison.parquet', index=False)
    print('\n=== Candidate vs Signal (median 20D) ===')
    print(comp_df.pivot_table(index=['regime','vr_stage'], columns=[], values=['cand_med20d','sig_med20d','cand_N','sig_N']).to_string())

    # ── 4. Time stability ──
    def period_bucket(year):
        if 2005 <= year <= 2009: return '2005_2009'
        if 2010 <= year <= 2014: return '2010_2014'
        if 2015 <= year <= 2019: return '2015_2019'
        if 2020 <= year <= 2024: return '2020_2024'
        return 'OTHER'
    cand['period'] = pd.to_datetime(cand['as_of_date']).dt.year.map(period_bucket)
    sig['period'] = pd.to_datetime(sig['as_of_date']).dt.year.map(period_bucket)
    ts_rows = []
    for label, g in [('candidate', cand), ('signal', sig)]:
        for period, pg in g.groupby('period'):
            for bname, bcond in [('VR<2.0', lambda x: x < 2.0), ('2.0<=VR<2.7', lambda x: (x >= 2.0) & (x < 2.7)), ('VR>=2.7', lambda x: x >= 2.7)]:
                bg = pg[pg['vr'].notna() & bcond(pg['vr'])]
                st = va.outcome_stats(bg)
                ts_rows.append({'label': label, 'period': period, 'vr_stage': bname,
                                'N': st['N'], 'median_20d': st.get('fwd_20d', {}).get('median')})
    ts_df = pd.DataFrame(ts_rows)
    ts_df.to_parquet(ART / 'time_stability.parquet', index=False)
    print('\n=== Time Stability (median 20D) ===')
    print(ts_df.pivot_table(index=['label','period'], columns='vr_stage', values='median_20d').to_string())

    # ── 5. Sensitivity ──
    sens_rows = []
    for mode, g in [('STRICT', cand[cand['market_cap_quality'] == 'PIT_SAFE']),
                    ('RESEARCH', cand[cand['market_cap_quality'].isin(['PIT_SAFE', 'APPROXIMATE'])]),
                    ('SENSITIVITY', cand)]:
        for bname, bcond in [('VR<2.0', lambda x: x < 2.0), ('2.0<=VR<2.7', lambda x: (x >= 2.0) & (x < 2.7)), ('VR>=2.7', lambda x: x >= 2.7)]:
            bg = g[g['vr'].notna() & bcond(g['vr'])]
            st = va.outcome_stats(bg)
            sens_rows.append({'label': 'candidate', 'mode': mode, 'vr_stage': bname,
                              'N': st['N'], 'median_20d': st.get('fwd_20d', {}).get('median')})
    sens_df = pd.DataFrame(sens_rows)
    sens_df.to_parquet(ART / 'sensitivity.parquet', index=False)
    print('\n=== Sensitivity (candidate median 20D) ===')
    print(sens_df.pivot_table(index='mode', columns='vr_stage', values='median_20d').to_string())

    # ── 6. Conditional analysis ──
    def mcap_bucket(v):
        s = str(v)
        if s in ('APPROXIMATE', 'UNKNOWN'): return s
        try:
            yi = float(v)
        except Exception:
            return 'UNKNOWN'
        if yi < 5: return 'SMALL'
        if yi <= 90: return 'MID'
        return 'LARGE'
    cand['market_cap_bucket'] = cand['market_cap'].map(mcap_bucket)
    mc_cond = conditional_by(cand, 'market_cap_bucket', 'candidate')
    mc_cond.to_parquet(ART / 'vr_conditional_marketcap.parquet', index=False)

    # ATR bucket
    cand['atr_bucket'] = pd.cut(pd.to_numeric(cand['atr_pct'], errors='coerce'),
                                bins=[0, 2, 3.5, 100], labels=['LOW', 'MID', 'HIGH'])
    atr_cond = conditional_by(cand, 'atr_bucket', 'candidate')
    atr_cond.to_parquet(ART / 'vr_conditional_atr.parquet', index=False)

    # Price position bucket
    cand['price_pos_bucket'] = pd.cut(pd.to_numeric(cand['price_pos'], errors='coerce'),
                                      bins=[0, 20, 40, 60, 100], labels=['LOW', 'MIDLOW', 'MIDHIGH', 'HIGH'])
    pp_cond = conditional_by(cand, 'price_pos_bucket', 'candidate')
    pp_cond.to_parquet(ART / 'vr_conditional_pricepos.parquet', index=False)

    print('\n=== Market Cap Conditional (median 20D) ===')
    print(mc_cond.pivot_table(index='market_cap_bucket', columns='vr_stage', values='median_20d').to_string())
    print('\n=== ATR Conditional (median 20D) ===')
    print(atr_cond.pivot_table(index='atr_bucket', columns='vr_stage', values='median_20d').to_string())
    print('\n=== Price Position Conditional (median 20D) ===')
    print(pp_cond.pivot_table(index='price_pos_bucket', columns='vr_stage', values='median_20d').to_string())

    # ── 7. Summary ──
    # G2 follow-up
    c_all = cand[cand['regime'] == 'ALL_REGIMES'] if 'ALL_REGIMES' in cand['regime'].values else cand
    c_neg = c_all[c_all['vr'] >= 2.7]
    c_neg2 = c_all[(c_all['vr'] >= 2.0) & (c_all['vr'] < 2.7)]
    s_all = sig if 'ALL_REGIMES' in sig['regime'].values else sig
    s_neg = s_all[s_all['vr'] >= 2.7]
    s_neg2 = s_all[(s_all['vr'] >= 2.0) & (s_all['vr'] < 2.7)]

    def med20(df):
        v = pd.to_numeric(df['fwd_20d'], errors='coerce').dropna()
        return round(v.median(), 4) if len(v) else None

    summary = {
        'research_version': RESEARCH_VERSION,
        'source': SOURCE,
        'outcome_type': OUTCOME_TYPE,
        'candidate_total': int(len(cand)),
        'signal_total': int(len(sig)),
        'candidate_vr_ge2_7_N': int(len(c_neg)),
        'candidate_vr_2_0_2_7_N': int(len(c_neg2)),
        'signal_vr_ge2_7_N': int(len(s_neg)),
        'signal_vr_2_0_2_7_N': int(len(s_neg2)),
        'candidate_med20d_vr_ge2_7': med20(c_neg),
        'candidate_med20d_vr_2_0_2_7': med20(c_neg2),
        'signal_med20d_vr_ge2_7': med20(s_neg),
        'signal_med20d_vr_2_0_2_7': med20(s_neg2),
        'g2_followup': 'CONFIRMED' if (med20(c_neg) is not None and med20(c_neg2) is not None and med20(c_neg) < med20(c_neg2)) else 'DATA_INSUFFICIENT',
    }
    with open(ART / 'research_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print('\n=== G3 Summary ===')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print('\nsaved all artifacts to', ART)


if __name__ == '__main__':
    main()
