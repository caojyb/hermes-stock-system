#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G3: Full V1 Candidate PIT Reconstruction
=================================================
从历史 K 线 + PIT 特征重建完整 V1 Candidate（含全部 8 层 Hard Filter）。
严格复用 G1 已锁定的 PIT 语义 / 时间语义 / VR formula / decide_final。
"""
from __future__ import annotations
import os, sys
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np

CRON_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent  # .../cron
sys.path.insert(0, str(CRON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # research/

import research.candidate_pit as cp
from research.regime_v1.full_v1.entry_signal_pit import compute_signals

RESEARCH_VERSION = 'phase-8g3-v1'
SOURCE = 'RESEARCH'
OUTCOME_TYPE = 'COUNTERFACTUAL_RESEARCH'
MIN_ROWS = cp.MIN_ROWS  # 60


def build_full_v1_trace(symbol: str, start: date, end: date,
                        use_fixtures: bool = False) -> pd.DataFrame:
    """对单个股票重建完整 V1 Candidate + Entry Signal trace（PIT）。"""
    # 1. 加载全部 K 线
    full_kl = cp.load_klines(symbol)
    if full_kl is None or len(full_kl) < MIN_ROWS:
        return pd.DataFrame()
    full_kl['date'] = pd.to_datetime(full_kl['date']).dt.date

    # 2. weekly candidate dates（G1 已验证）
    all_dates = sorted(full_kl['date'].tolist())
    cand_dates = cp.weekly_candidate_dates(all_dates, start, end)
    if not cand_dates:
        return pd.DataFrame()

    rows = []
    for as_of in cand_dates:
        # PIT 过滤：仅用 date <= as_of 的 K 线
        pit_kl = full_kl[full_kl['date'] <= as_of].copy()
        if len(pit_kl) < MIN_ROWS:
            continue

        # 3. 用 G1 compute_metrics 计算 V1 指标
        metrics = cp.compute_metrics(pit_kl)
        if metrics.get('data_insufficient'):
            continue

        # 4. 市值（G1 mcap_state）
        mcap = cp.mcap_state(symbol, as_of)
        final = cp.decide_final(metrics, mcap)
        mcap_display = cp.market_cap_col(mcap)

        # 5. ST（历史无数据，全 UNKNOWN）
        st_pass = None  # None = UNKNOWN

        # 6. 从 metrics 提取
        price_pos = metrics.get('price_pos')
        vr = metrics.get('vol_ratio')
        amount_1d = metrics.get('amount_1d')
        amount_20d = metrics.get('amount_20d')
        atr_pct = metrics.get('atr_pct')

        # 7. 失败原因（从 metrics 推断，复用 G1 阈值）
        failures = []
        if price_pos is None or price_pos > cp.PRICE_POS_MAX:
            failures.append('PRICE_POSITION')
        if vr is None or vr < cp.VOL_RATIO_MIN:
            failures.append('VR')
        if amount_1d is None or amount_1d < cp.AMOUNT_1D_MIN_WAN:
            failures.append('AMOUNT_1D')
        if amount_20d is None or amount_20d < cp.AMOUNT_20D_MIN_WAN:
            failures.append('AMOUNT_20D')
        if atr_pct is None or atr_pct < cp.ATR_PCT_MIN:
            failures.append('ATR')
        if mcap[0] != 'OK':
            failures.append('MARKET_CAP')

        if st_pass is None:
            final_candidate = 'UNKNOWN'
        elif final == 'PASS':
            final_candidate = 'PASS'
        else:
            final_candidate = 'FAIL'
        primary = failures[0] if failures else ('UNKNOWN' if st_pass is None else 'NONE')
        all_reasons = '|'.join(failures) if failures else ('NONE' if st_pass is not None else 'UNKNOWN')

        # 8. Entry Signal（PIT，用截至 as_of 的 K 线）
        sig = {'signal_a': None, 'signal_b': None, 'signal_c': None, 'signal_d': None,
               'signal_count': None, 'entry_confirmed': None}
        closes = pit_kl['close'].dropna().tolist()
        highs = pit_kl['high'].dropna().tolist()
        volumes = pit_kl['volume'].dropna().tolist()
        if len(closes) >= 35:
            sigs = compute_signals(closes, highs, volumes)
            sig.update(sigs)

        rows.append({
            'symbol': symbol,
            'as_of_date': str(as_of),
            'latest_date': str(pit_kl['date'].max()),
            'market_cap': mcap_display,
            'market_cap_quality': mcap[0],
            'st_quality': 'UNKNOWN',
            'vol_ratio': round(float(vr), 4) if vr is not None else None,
            'amount_1d': round(float(amount_1d), 2) if amount_1d is not None else None,
            'amount_20d': round(float(amount_20d), 2) if amount_20d is not None else None,
            'atr_pct': round(float(atr_pct), 4) if atr_pct is not None else None,
            'price_pos': round(float(price_pos), 2) if price_pos is not None else None,
            'final_candidate': final_candidate,
            'primary_failure_reason': primary,
            'all_failure_reasons': all_reasons,
            **sig,
            'research_version': RESEARCH_VERSION,
            'source': SOURCE,
        })
    return pd.DataFrame(rows)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2015-01-01')
    ap.add_argument('--end', default='2024-12-31')
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--symbols', default='')
    ap.add_argument('--fixtures', action='store_true')
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()] if args.symbols else None
    universe = cp.load_universe(args.limit, symbols)
    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    print(f'[fullv1] universe={len(universe)} start={start_d} end={end_d}', file=sys.stderr)

    all_df = []
    for sym in universe:
        try:
            df = build_full_v1_trace(sym, start_d, end_d, use_fixtures=args.fixtures)
            if df is not None and len(df):
                all_df.append(df)
        except Exception as e:
            print(f'  {sym}: {e}', file=sys.stderr)
    if not all_df:
        print('[fullv1] no data', file=sys.stderr)
        return 1
    result = pd.concat(all_df, ignore_index=True)
    out = Path(__file__).parent / 'artifacts'
    out.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out / 'full_candidate_trace.parquet', index=False)
    result.to_csv(out / 'full_candidate_trace.csv', index=False)

    # 统计
    print(f'[fullv1] total={len(result)}', file=sys.stderr)
    print('\n=== Full V1 Candidate Stats ===', file=sys.stderr)
    print(result['final_candidate'].value_counts().to_string(), file=sys.stderr)
    if 'entry_confirmed' in result.columns:
        print('\n=== Entry Signal Stats ===', file=sys.stderr)
        for col in ['signal_a', 'signal_b', 'signal_c', 'signal_d']:
            if col in result.columns:
                print(f"{col}: {result[col].sum()}/{len(result)}", file=sys.stderr)
        sig_counts = result['signal_count'].value_counts().sort_index()
        print('signal_count:', sig_counts.to_string(), file=sys.stderr)
        print(f"entry_confirmed: {result['entry_confirmed'].sum()}/{len(result)}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
