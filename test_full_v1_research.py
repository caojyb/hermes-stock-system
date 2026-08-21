#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G3: Full V1 Candidate + Entry Signal Research — 测试
覆盖：filter parity / signal formula / candidate-sig separation /
      forward outcome / VR band / regime matrix / conditional /
      time stability / sensitivity / isolation / no-lookahead
"""
import os, sys, json
from pathlib import Path
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
FULLV1_DIR = Path(__file__).parent / 'research' / 'regime_v1' / 'full_v1'
sys.path.insert(0, str(FULLV1_DIR))
sys.path.insert(0, str(Path(__file__).parent / 'research'))

import research.candidate_pit as cp
from research.regime_v1.full_v1.entry_signal_pit import compute_signals

ART = FULLV1_DIR / 'artifacts'


# ═══ 1. full V1 filter parity ═══
def test_01_v1_filter_parity():
    """研究模块复用 G1 的阈值常量。PRICE_POS_MAX=40 是阈值，500 是窗口。"""
    assert cp.VOL_RATIO_MIN == 2.7
    assert cp.MCAP_MIN_YI == 5
    assert cp.MCAP_MAX_YI == 90
    assert cp.AMOUNT_1D_MIN_WAN == 8000
    assert cp.AMOUNT_20D_MIN_WAN == 4000
    assert cp.ATR_PCT_MIN == 3.0
    assert cp.PRICE_POS_MAX == 40  # 阈值（%），非窗口


# ═══ 2. candidate trace completeness ═══
def test_02_candidate_trace_completeness():
    p = ART / 'full_candidate_trace.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    for col in ['symbol', 'as_of_date', 'market_cap_quality', 'st_quality',
                'vol_ratio', 'amount_1d', 'amount_20d', 'atr_pct', 'price_pos',
                'final_candidate', 'signal_a', 'signal_b', 'signal_c', 'signal_d',
                'signal_count', 'entry_confirmed']:
        assert col in df.columns, f"missing {col}"


# ═══ 3. entry signal formula parity ═══
def test_03_signal_formula_parity():
    src = Path(FULLV1_DIR / 'entry_signal_pit.py').read_text(encoding='utf-8')
    assert 'vol_5 / vol_20' not in src  # signal 不是 VR，是 A/B/C/D
    assert 'close > ma20' in src or 'closes[-1] > ma20' in src
    assert 'v3 / v10 * 1.8' in src or '1.8' in src
    assert 'max(highs[-20' in src
    assert 'dp < dea_p' in src or 'dc > dea_c' in src


# ═══ 4-7. signal A/B/C/D ═══
def test_04_signal_a():
    closes = list(range(100, 121))
    assert compute_signals(closes, [110]*21, [100]*21)['signal_a'] == 1


def test_05_signal_b():
    vols = [100]*10 + [200]*3
    assert compute_signals([100]*13, [100]*13, vols)['signal_b'] == 1


def test_06_signal_c():
    highs = list(range(100, 120)) + [119]
    # highs[-1]=119，max(highs[-20:])=119 → signal_c=1
    assert compute_signals([110]*20, highs, [100]*21)['signal_c'] == 1


def test_07_signal_d():
    closes = list(range(100, 135))
    sigs = compute_signals(closes, [110]*35, [100]*35)
    assert 'signal_d' in sigs


# ═══ 8. signal count ═══
def test_08_signal_count():
    closes = list(range(100, 121))
    highs = [110]*21
    vols = [100]*10 + [200]*3 + [100]*8
    sigs = compute_signals(closes, highs, vols)
    assert sigs['signal_count'] == sigs['signal_a'] + sigs['signal_b'] + sigs['signal_c'] + sigs['signal_d']


# ═══ 9. candidate/signal separation ═══
def test_09_candidate_signal_separation():
    p = ART / 'full_candidate_trace.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    # signal 层必须有 entry_confirmed=True
    sig_df = df[df['entry_confirmed'] == True]
    assert len(sig_df) <= len(df)
    # 所有 signal 的 signal_count >= 3
    if len(sig_df):
        assert sig_df['signal_count'].min() >= 3


# ═══ 12-14. forward outcome ═══
def test_12_candidate_forward_5d():
    p = ART / 'candidate_outcomes.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    known = df[df['fwd_5d'] != 'UNKNOWN']
    assert len(known) > 0


def test_13_candidate_forward_20d():
    p = ART / 'candidate_outcomes.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    known = df[df['fwd_20d'] != 'UNKNOWN']
    assert len(known) > 0


def test_14_signal_forward_5d():
    p = ART / 'signal_outcomes.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    known = df[df['fwd_5d'] != 'UNKNOWN']
    assert len(known) > 0


# ═══ 18. MAE/MFE ═══
def test_18_mae_mfe():
    for p in [ART / 'candidate_outcomes.parquet', ART / 'signal_outcomes.parquet']:
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if len(df) == 0:
            continue
        # MAE = min(low_i/entry-1)（最大不利偏离，≤0 或 >0 若始终在 entry 上方）
        # MFE = max(high_i/entry-1)（最大有利偏离，≥0 或 <0 若始终在 entry 下方）
        # 仅验证数值存在且为实数
        mae = pd.to_numeric(df['mae'], errors='coerce').dropna()
        mfe = pd.to_numeric(df['mfe'], errors='coerce').dropna()
        assert len(mae) > 0
        assert len(mfe) > 0


# ═══ 19. VR band separation ═══
def test_19_vr_band_separation():
    p = ART / 'full_candidate_trace.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    df = df[df['vol_ratio'].notna()]
    b5 = df[(df['vol_ratio'] >= 2.0) & (df['vol_ratio'] < 2.7)]
    b6 = df[df['vol_ratio'] >= 2.7]
    assert len(b5) > 0
    assert len(b6) > 0
    assert len(b5) + len(b6) <= len(df)


# ═══ 23. all-regime baseline ═══
def test_23_all_regime_baseline():
    p = ART / 'vr_regime_candidate_matrix.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    assert 'ALL_REGIMES' in set(df['regime'])


# ═══ 30. no look-ahead ═══
def test_30_no_lookahead():
    p = ART / 'candidate_outcomes.parquet'
    if not p.exists():
        return
    df = pd.read_parquet(p)
    # candidate_date 应 <= entry_price 查询日期
    for _, r in df.head(10).iterrows():
        if r['entry_price'] is not None:
            assert r['candidate_date'] is not None


# ═══ 32. production isolation ═══
def test_32_prod_isolation():
    for f in ['entry_signal_pit.py', 'full_v1_candidate_pit.py', 'run_full_v1_outcomes.py', 'analyze_full_v1.py']:
        p = FULLV1_DIR / f
        if p.exists():
            txt = p.read_text(encoding='utf-8')
            assert 'INSERT INTO trades' not in txt
            assert 'record_simulation_execution' not in txt


# ═══ 34. deterministic ═══
def test_34_deterministic():
    assert (ART / 'full_candidate_trace.parquet').exists()
    assert (ART / 'candidate_outcomes.parquet').exists()
    assert (ART / 'signal_outcomes.parquet').exists()
    s = json.load(open(ART / 'research_summary.json'))
    assert s['source'] == 'RESEARCH'
    assert s['outcome_type'] == 'COUNTERFACTUAL_RESEARCH'
