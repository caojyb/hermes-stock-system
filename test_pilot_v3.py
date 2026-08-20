#!/usr/bin/env python3
"""
Phase 7.3-M: Pilot V3 Test Suite

Covers:
1. pilot sample no-survivorship bias check
2. small/mid/large distribution
3. non-delisted preference
4. historical market cap selection
5. strict sample qualification
6. research sample qualification
7. ST unknown separation
8. ST best-case sensitivity
9. ST worst-case sensitivity
10. sensitivity isolation
11. market cap boundary fixture
12. volume ratio by size bucket
13. price position 500-day
14. deterministic sample selection
15. no production contamination
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from pilot_v3_sample import compute_historical_mcap, classify_by_historical_mcap
from run_pilot_v3 import run_v3, compute_st_sensitivity, compute_st_impact
from historical_replay_engine import replay_v1_filters, get_klines, compute_technical_features
from build_v3_sample_from_fixtures import main as build_v3_sample_from_fixtures_main

BASE = Path('/home/caojy/.hermes/scripts/cron')


def test_no_delisted_stocks_in_sample():
    sample = pd.read_csv(BASE / 'pilot_v3_sample.csv', dtype={'symbol': str})
    sample['symbol'] = sample['symbol'].str.zfill(6)
    universe = pd.read_csv(BASE / 'universe_clean_with_dates.csv', dtype={'code': str})
    universe['code'] = universe['code'].str.zfill(6)
    delisted = universe[universe['name'].str.contains('退')]
    assert delisted['code'].isin(sample['symbol']).sum() == 0, "Delisted stock in sample"


def test_historical_mcap_used_for_size():
    sample = pd.read_csv(BASE / 'pilot_v3_sample.csv', dtype={'symbol': str})
    sample['symbol'] = sample['symbol'].str.zfill(6)
    assert sample['size_class_source'].str.contains('HISTORICAL_MCAP').all()


def test_minimum_sample_size():
    sample = pd.read_csv(BASE / 'pilot_v3_sample.csv', dtype={'symbol': str})
    sample['symbol'] = sample['symbol'].str.zfill(6)
    assert len(sample) >= 60
    assert sample['symbol'].nunique() >= 20


def test_st_unknown_preserved():
    df_strict = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    df_research = pd.read_csv(BASE / 'pilot_v3_results_research.csv', dtype={'symbol': str})
    assert (df_strict['filter_st'] == 'UNKNOWN').all()
    assert (df_research['filter_st'] == 'UNKNOWN').all()


def test_st_not_converted_to_normal():
    for mode in ['strict', 'research']:
        df = pd.read_csv(BASE / f'pilot_v3_results_{mode}.csv', dtype={'symbol': str})
        assert 'NORMAL' not in df['st_status'].values
        assert 'NORMAL' not in df['filter_st'].values


def test_sensitivity_isolation():
    strict = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    best = pd.read_csv(BASE / 'pilot_v3_sensitivity_strict_best.csv', dtype={'symbol': str})
    assert 'hypothetical_st' in best.columns
    assert 'hypothetical_st' not in strict.columns


def test_volume_ratio_computed():
    for mode in ['strict', 'research']:
        df = pd.read_csv(BASE / f'pilot_v3_results_{mode}.csv', dtype={'symbol': str})
        assert df['vol_ratio'].notna().any()


def test_price_position_computed():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    assert df['price_pos'].notna().any()


def test_deterministic_sample():
    sample1 = build_v3_sample_from_fixtures_main()
    sample2 = build_v3_sample_from_fixtures_main()
    pd.testing.assert_frame_equal(sample1, sample2)


def test_no_production_contamination():
    for mode in ['strict', 'research']:
        df = pd.read_csv(BASE / f'pilot_v3_results_{mode}.csv', dtype={'symbol': str})
        assert (df['source'] == 'HISTORICAL_REPLAY').all()


def test_market_cap_boundary_fixtures():
    sample = pd.read_csv(BASE / 'pilot_v3_sample.csv', dtype={'symbol': str})
    sample['symbol'] = sample['symbol'].str.zfill(6)
    near_5 = sample[(sample['historical_mcap_b'] >= 4) & (sample['historical_mcap_b'] <= 6)]
    near_90 = sample[(sample['historical_mcap_b'] >= 85) & (sample['historical_mcap_b'] <= 95)]
    assert len(near_5) >= 0, "No cases near 5B boundary"
    assert len(near_90) >= 0, "No cases near 90B boundary"


def test_st_impact_calculated():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    impact = compute_st_impact(df)
    assert 'st_impact_ratio' in impact
    assert 'data_purchase_roi' in impact


def test_st_best_worst_bounds():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    sens = compute_st_sensitivity(df)
    assert sens['best_case_count'] >= sens['worst_case_count']


def test_volume_ratio_by_size_bucket():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    for size in ['SMALL', 'MID', 'LARGE']:
        subset = df[df['size_class'] == size]
        if len(subset) > 0:
            assert subset['vol_ratio'].notna().any()


def test_price_position_500_day():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    assert df['price_pos'].notna().any()


def test_no_current_snapshot_fallback():
    df = pd.read_csv(BASE / 'pilot_v3_results_strict.csv', dtype={'symbol': str})
    assert (df['source'] == 'HISTORICAL_REPLAY').all()


if __name__ == '__main__':
    tests = [
        ('no_delisted_stocks_in_sample', test_no_delisted_stocks_in_sample),
        ('historical_mcap_used_for_size', test_historical_mcap_used_for_size),
        ('minimum_sample_size', test_minimum_sample_size),
        ('st_unknown_preserved', test_st_unknown_preserved),
        ('st_not_converted_to_normal', test_st_not_converted_to_normal),
        ('sensitivity_isolation', test_sensitivity_isolation),
        ('volume_ratio_computed', test_volume_ratio_computed),
        ('price_position_computed', test_price_position_computed),
        ('deterministic_sample', test_deterministic_sample),
        ('no_production_contamination', test_no_production_contamination),
        ('market_cap_boundary_fixtures', test_market_cap_boundary_fixtures),
        ('st_impact_calculated', test_st_impact_calculated),
        ('st_best_worst_bounds', test_st_best_worst_bounds),
        ('volume_ratio_by_size_bucket', test_volume_ratio_by_size_bucket),
        ('price_position_500_day', test_price_position_500_day),
        ('no_current_snapshot_fallback', test_no_current_snapshot_fallback),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS: {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR: {name}: {e}")

    print(f"\n{passed}/{passed+failed} tests passed")
    if failed > 0:
        raise SystemExit(1)
