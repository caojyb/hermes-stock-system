#!/usr/bin/env python3
"""
Phase 7.3-M: Replay Pilot V3 Runner

Runs V1 filter trace on Pilot V3 sample, producing STRICT/RESEARCH/SENSITIVITY datasets.
Does NOT modify V1 parameters or production logic.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd

from historical_replay_engine import get_klines, compute_technical_features, replay_v1_filters
from pilot_v3_sample import compute_historical_mcap, classify_by_historical_mcap

DB_PATH = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
SAMPLE_CSV = Path(__file__).resolve().parent / 'pilot_v3_sample.csv'


def run_v3(mode: str = 'STRICT') -> pd.DataFrame:
    """
    Run V1 filter trace on V3 sample.

    Args:
        mode: 'STRICT' or 'RESEARCH'

    Returns:
        DataFrame with one row per case, including all filter traces.
    """
    if not SAMPLE_CSV.exists():
        raise FileNotFoundError(f"{SAMPLE_CSV} not found. Run build_v3_sample_from_fixtures.py first.")

    df_sample = pd.read_csv(SAMPLE_CSV)
    df_sample['target_date'] = pd.to_datetime(df_sample['target_date']).dt.date

    strict = mode == 'STRICT'

    cases = []
    for _, row in df_sample.iterrows():
        symbol = row['symbol']
        target_date = row['target_date']
        size_class = row.get('size_class')
        size_class_source = row.get('size_class_source')
        hist_mcap_b = row.get('historical_mcap_b')
        mcap_quality_sample = row.get('mcap_quality')

        # Klines
        klines = get_klines(symbol, target_date)
        if len(klines) < 60:
            continue

        # Features (production formulas)
        features = compute_technical_features(klines)

        # Historical market cap from fixture (recompute with requested strictness)
        mcap_res = compute_historical_mcap(symbol, target_date, strict=strict)
        mcap = mcap_res['market_cap']
        mcap_quality = mcap_res['quality']
        mcap_b = mcap / 1e9 if mcap is not None else None

        # Recompute historical size class for this strictness
        actual_size_class = classify_by_historical_mcap(mcap_b, mcap_quality)
        if actual_size_class == 'UNKNOWN':
            actual_size_class = size_class

        # ST status: always UNKNOWN in historical replay
        st_status = 'UNKNOWN'

        # V1 filter trace
        case = replay_v1_filters(
            symbol=symbol,
            as_of_date=target_date,
            features=features,
            mcap=mcap,
            mcap_quality=mcap_quality,
            st_status=st_status,
        )

        case_dict = {
            'replay_case_id': case.replay_case_id,
            'symbol': symbol,
            'as_of_date': case.as_of_date,
            'size_class': size_class,
            'size_class_source': size_class_source,
            'actual_size_class': actual_size_class,
            'data_quality': case.data_quality,
            'st_status': case.st_status,
            'st_date_quality': 'BLOCKED',
            'market_cap': case.market_cap,
            'market_cap_b': mcap_b,
            'market_cap_quality': case.market_cap_quality,
            'ma20': case.ma20,
            'atr': case.atr,
            'atr_pct': case.atr_pct,
            'macd': case.macd,
            'vol_ratio': case.volume_ratio,
            'turnover_1d': case.turnover_1d,
            'avg_turnover_20d': case.avg_turnover_20d,
            'price_pos': case.price_pos,
            'filter_market_cap': case.filter_market_cap,
            'filter_st': case.filter_st,
            'filter_turnover_1d': case.filter_turnover_1d,
            'filter_turnover_20d': case.filter_turnover_20d,
            'filter_price_pos': case.filter_price_pos,
            'filter_vol_ratio': case.filter_vol_ratio,
            'filter_atr': case.filter_atr,
            'final_candidate': case.final_candidate,
            'exclusion_reason': case.exclusion_reason,
            'pit_confidence': case.pit_confidence,
            'mode': mode,
            'source': 'HISTORICAL_REPLAY',
        }
        cases.append(case_dict)

    df = pd.DataFrame(cases)

    # Deterministic hash
    if not df.empty:
        df['case_hash'] = df.apply(
            lambda r: hashlib.md5(
                f"{r['symbol']}|{r['as_of_date']}|{r['market_cap']}|{r['vol_ratio']}|{r['price_pos']}".encode()
            ).hexdigest()[:8],
            axis=1,
        )

    return df


def compute_st_sensitivity(df_mode: pd.DataFrame) -> dict:
    """
    Compute ST sensitivity for a given mode dataframe.
    Returns dict with best/worst case hypotheticals.
    """
    # Best case: all UNKNOWN -> assume NORMAL
    best = df_mode.copy()
    best['hypothetical_st'] = 'NORMAL'
    best['final_candidate'] = best.apply(
        lambda r: 'PASS'
        if r['filter_market_cap'] == 'PASS'
        and r['filter_turnover_1d'] == 'PASS'
        and r['filter_turnover_20d'] == 'PASS'
        and r['filter_price_pos'] == 'PASS'
        and r['filter_vol_ratio'] == 'PASS'
        and r['filter_atr'] == 'PASS'
        else 'FAIL',
        axis=1,
    )

    # Worst case: all UNKNOWN -> assume ST
    worst = df_mode.copy()
    worst['hypothetical_st'] = 'ST'
    worst['final_candidate'] = 'FAIL'

    return {
        'best_case_count': int(best['final_candidate'].eq('PASS').sum()),
        'best_case_cases': best[best['final_candidate'] == 'PASS'][
            ['symbol', 'as_of_date', 'size_class', 'market_cap_b', 'vol_ratio', 'price_pos', 'atr_pct']
        ].to_dict('records'),
        'worst_case_count': int(worst['final_candidate'].eq('PASS').sum()),
        'worst_case_cases': worst[worst['final_candidate'] == 'PASS'][
            ['symbol', 'as_of_date', 'size_class', 'market_cap_b', 'vol_ratio', 'price_pos', 'atr_pct']
        ].to_dict('records'),
        'best_case_df': best,
        'worst_case_df': worst,
    }


def compute_st_impact(df_mode: pd.DataFrame) -> dict:
    """
    Quantify ST data value:
    - How many UNKNOWN cases would become PASS if ST were known NORMAL?
    - How many would be filtered if ST were known ST?
    """
    total = len(df_mode)
    st_unknown = int(df_mode['filter_st'].eq('UNKNOWN').sum())
    base_candidates = int(df_mode['final_candidate'].eq('PASS').sum())

    no_st_block = df_mode[
        (df_mode['filter_market_cap'] == 'PASS') &
        (df_mode['filter_turnover_1d'] == 'PASS') &
        (df_mode['filter_turnover_20d'] == 'PASS') &
        (df_mode['filter_price_pos'] == 'PASS') &
        (df_mode['filter_vol_ratio'] == 'PASS') &
        (df_mode['filter_atr'] == 'PASS')
    ]
    hypothetical_pass = len(no_st_block)

    return {
        'total_cases': total,
        'st_unknown_count': st_unknown,
        'st_unknown_pct': round(st_unknown / total * 100, 2) if total else 0.0,
        'base_candidate_count': base_candidates,
        'hypothetical_pass_if_st_normal': hypothetical_pass,
        'st_impact_ratio': round(hypothetical_pass / total * 100, 2) if total else 0.0,
        'data_purchase_roi': 'HIGH' if hypothetical_pass >= 5 else ('MEDIUM' if hypothetical_pass >= 2 else 'LOW'),
    }


def main():
    print("=" * 60)
    print("Phase 7.3-M: Replay Pilot V3 Runner")
    print("=" * 60)

    # STRICT
    df_strict = run_v3('STRICT')
    strict_res = compute_st_sensitivity(df_strict)
    strict_impact = compute_st_impact(df_strict)

    # RESEARCH
    df_research = run_v3('RESEARCH')
    research_res = compute_st_sensitivity(df_research)
    research_impact = compute_st_impact(df_research)

    # Save datasets
    df_strict.to_csv('pilot_v3_results_strict.csv', index=False)
    df_research.to_csv('pilot_v3_results_research.csv', index=False)

    # Sensitivity datasets (hypothetical only)
    strict_res['best_case_df'].to_csv('pilot_v3_sensitivity_strict_best.csv', index=False)
    strict_res['worst_case_df'].to_csv('pilot_v3_sensitivity_strict_worst.csv', index=False)
    research_res['best_case_df'].to_csv('pilot_v3_sensitivity_research_best.csv', index=False)
    research_res['worst_case_df'].to_csv('pilot_v3_sensitivity_research_worst.csv', index=False)

    # Print summary
    print("\n" + "=" * 60)
    print("STRICT MODE")
    print("=" * 60)
    print(f"Total cases: {len(df_strict)}")
    print(f"Final Candidate:\n{df_strict['final_candidate'].value_counts().to_string()}")
    print(f"\nST Impact: {strict_impact}")
    print(f"Best Case (UNKNOWN->NORMAL): {strict_res['best_case_count']} candidates")
    print(f"Worst Case (UNKNOWN->ST): {strict_res['worst_case_count']} candidates")

    print("\n" + "=" * 60)
    print("RESEARCH MODE")
    print("=" * 60)
    print(f"Total cases: {len(df_research)}")
    print(f"Final Candidate:\n{df_research['final_candidate'].value_counts().to_string()}")
    print(f"\nST Impact: {research_impact}")
    print(f"Best Case (UNKNOWN->NORMAL): {research_res['best_case_count']} candidates")
    print(f"Worst Case (UNKNOWN->ST): {research_res['worst_case_count']} candidates")

    print("\nResults saved to pilot_v3_results_*.csv and pilot_v3_sensitivity_*.csv")
    return df_strict, df_research


if __name__ == '__main__':
    main()
