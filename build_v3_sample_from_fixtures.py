#!/usr/bin/env python3
"""
Phase 7.3-M: Build V3 sample from available fixtures.

Pragmatic approach:
  - 30 available fixtures with PIT_SAFE/APPROXIMATE historical market cap
  - Select 3 dates per symbol where historical mcap is known
  - Do NOT force SMALL/MID/LARGE balance if historical data doesn't support it
  - This honestly quantifies the boundary behavior question

Key insight: Most fixtures are historically SMALL (<5B in 2005-2008).
This is a real structural finding, not a bug to hide.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from pilot_v3_sample import TARGET_DATES, compute_historical_mcap, classify_by_historical_mcap, load_fixture

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures'
DATES_PER_SYMBOL = 3


def main():
    # Load available fixtures
    fixtures = sorted(p.stem.split('_')[1] for p in FIXTURE_DIR.glob('cninfo_*.parquet') if p.is_file())
    print(f"Available fixtures: {len(fixtures)}")

    # Load universe for current size_group reference
    universe = pd.read_csv(Path(__file__).resolve().parent / 'universe_clean_with_dates.csv', dtype={'code': str})
    universe['code'] = universe['code'].str.zfill(6)
    current_size = universe.set_index('code')['size_group'].to_dict()

    # Compute historical market cap for all fixtures at all dates
    records = []
    for symbol in fixtures:
        for d in TARGET_DATES:
            res = compute_historical_mcap(symbol, d, strict=False)
            mcap_b = res['market_cap'] / 1e9 if res['market_cap'] is not None else None
            size_class = classify_by_historical_mcap(mcap_b, res['quality'])
            records.append({
                'symbol': symbol,
                'target_date': d,
                'historical_mcap_b': mcap_b,
                'mcap_quality': res['quality'],
                'size_class': size_class,
                'share_effective_date': res.get('share_effective_date'),
                'share_date_quality': res.get('share_date_quality'),
                'price_date': res.get('price_date'),
                'limitation_codes': ';'.join(res.get('limitation_codes', [])),
                'current_size_group': current_size.get(symbol),
            })

    df_hist = pd.DataFrame(records)
    print(f"Total symbol-date cases: {len(df_hist)}")
    print("Size class distribution:")
    print(df_hist['size_class'].value_counts().to_string())
    print("Market cap quality distribution:")
    print(df_hist['mcap_quality'].value_counts().to_string())

    # Select dates with known market cap (PIT_SAFE or APPROXIMATE)
    df_known = df_hist[df_hist['size_class'] != 'UNKNOWN'].copy()
    df_known['year'] = pd.to_datetime(df_known['target_date']).dt.year

    # For each symbol, pick up to DATES_PER_SYMBOL dates
    # Prefer: PIT_SAFE > APPROXIMATE, multiple years
    final_cases = []
    for symbol in fixtures:
        df_sym = df_known[df_known['symbol'] == symbol].copy()
        if len(df_sym) == 0:
            continue

        # Sort by quality then year
        df_sym['quality_rank'] = df_sym['mcap_quality'].map({'PIT_SAFE': 0, 'APPROXIMATE': 1}).fillna(2)
        df_sym = df_sym.sort_values(['quality_rank', 'year'])

        # Try to pick diverse years
        selected = []
        years_seen = set()
        for _, row in df_sym.iterrows():
            year = row['year']
            if year not in years_seen or len(selected) < DATES_PER_SYMBOL:
                selected.append(row.to_dict())
                years_seen.add(year)
            if len(selected) >= DATES_PER_SYMBOL:
                break

        # If still not enough, fill with whatever
        if len(selected) < DATES_PER_SYMBOL:
            for _, row in df_sym.iterrows():
                if row.to_dict() not in selected:
                    selected.append(row.to_dict())
                if len(selected) >= DATES_PER_SYMBOL:
                    break

        for cr in selected:
            final_cases.append({
                'symbol': str(symbol).zfill(6),
                'target_date': cr['target_date'],
                'size_class': cr['size_class'],
                'size_class_source': f"{cr['mcap_quality']}_HISTORICAL_MCAP",
                'historical_mcap_b': cr['historical_mcap_b'],
                'mcap_quality': cr['mcap_quality'],
                'share_effective_date': cr['share_effective_date'],
                'share_date_quality': cr['share_date_quality'],
                'current_size_group': current_size.get(str(symbol).zfill(6)),
            })

    df_final = pd.DataFrame(final_cases)
    df_final['symbol'] = df_final['symbol'].astype(str).str.zfill(6)
    df_final.to_csv('pilot_v3_sample.csv', index=False)
    print(f"\nFinal sample: {len(df_final)} cases, {df_final['symbol'].nunique()} symbols")
    print(df_final['size_class'].value_counts().to_string())
    print("Year distribution:")
    df_final['year'] = pd.to_datetime(df_final['target_date']).dt.year
    print(df_final['year'].value_counts().sort_index().to_string())
    return df_final


if __name__ == '__main__':
    main()
