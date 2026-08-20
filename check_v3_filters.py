import pandas as pd
from pathlib import Path

df = pd.read_csv('pilot_v3_results_strict.csv')
almost = df[
    (df['filter_market_cap'] == 'PASS') &
    (df['filter_turnover_1d'] == 'PASS') &
    (df['filter_turnover_20d'] == 'PASS') &
    (df['filter_price_pos'] == 'PASS') &
    (df['filter_vol_ratio'] == 'PASS') &
    (df['filter_atr'] == 'PASS')
]
print('Cases passing all filters except ST:', len(almost))
if len(almost) > 0:
    print(almost[['symbol', 'as_of_date', 'size_class', 'market_cap_b', 'vol_ratio', 'price_pos', 'atr_pct']].to_string(index=False))

print('\nVolume ratio by size class:')
print(df.groupby('size_class')['vol_ratio'].describe().to_string())

print('\nPrice position by size class:')
print(df.groupby('size_class')['price_pos'].describe().to_string())

print('\nFilter counts by size class:')
for col in ['filter_market_cap', 'filter_turnover_1d', 'filter_turnover_20d', 'filter_price_pos', 'filter_vol_ratio', 'filter_atr']:
    print(f'\n{col}:')
    print(df.groupby('size_class')[col].value_counts().to_string())
