"""
Phase 7.3-G：Historical Share PIT Quality Upgrade Audit
对 APPROXIMATE_EFFECTIVE_DATE 进行来源审计、日期语义分析、时间线一致性检查。
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def load_audit_data(symbols: list[str]) -> pd.DataFrame:
    """加载多只股票的股本事件并打来源标签。"""
    from historical_share_layer import HistoricalShareLayer, convert_raw_events
    import akshare as ak

    rows = []
    for sym in symbols:
        try:
            df = ak.stock_share_change_cninfo(symbol=sym, start_date='20000101', end_date='20241231')
            events = convert_raw_events(df, sym)
            for e in events:
                rows.append({
                    'symbol': e.symbol,
                    'share_count': e.share_count,
                    'effective_date': e.effective_date,
                    'announcement_date': e.announcement_date,
                    'change_reason': e.raw_change_reason,
                    'date_quality': e.date_quality.value,
                    'confidence': e.confidence,
                    'limitation_codes': e.limitation_codes,
                    'source_record_id': e.source_record_id,
                })
        except Exception as ex:
            print(f'[WARN] {sym} load failed: {ex}')
    return pd.DataFrame(rows)


def classify_source_type(reason: str) -> str:
    if not reason:
        return 'OTHER'
    r = reason.lower()
    if '定期报告' in r:
        return 'PERIODIC_REPORT'
    if '配股' in r:
        return 'ALLOTMENT'
    if '增发' in r:
        return 'RIGHTS_ISSUE'
    if '送股' in r or '转增' in r:
        return 'DIVIDEND_SHARE'
    if '回购' in r:
        return 'BUYBACK'
    if '限售股份上市' in r:
        return 'RESTRICTED_LIFT'
    if 'A股上市' in r or '上市' in r:
        return 'IPO'
    if '注销' in r:
        return 'CANCELLATION'
    if '合并' in r or '拆股' in r:
        return 'SPLIT_MERGE'
    if '其他' in r:
        return 'OTHER'
    return 'OTHER'


def audit_apprximate(df: pd.DataFrame) -> pd.DataFrame:
    """审计 APPROXIMATE 来源分布。"""
    app = df[df['date_quality'] == 'APPROXIMATE_EFFECTIVE_DATE'].copy()
    app['source_type'] = app['change_reason'].apply(classify_source_type)
    app['has_announcement'] = app['announcement_date'].notna()
    app['has_change_date'] = app['effective_date'].notna()
    app['date_relation'] = 'N/A'
    mask = app['has_announcement'] & app['has_change_date']
    app.loc[mask, 'date_relation'] = 'SAME'
    app.loc[mask & (app['effective_date'] < app['announcement_date']), 'date_relation'] = 'CHANGE_BEFORE_ANN'
    app.loc[mask & (app['effective_date'] > app['announcement_date']), 'date_relation'] = 'CHANGE_AFTER_ANN'
    return app


def check_timeline_consistency(df: pd.DataFrame) -> dict:
    """检查时间线一致性。
    
    允许的减少原因：股份回购、注销、期权行权（可能导致总股本减少）。
    定期报告的减少视为数据修订（SUSPICIOUS），需要人工确认。
    不允许：无明确原因的减少、大幅跳变（>10x 或 <0.1x）。
    """
    DECREASE_REASONS = {'股份回购', '注销', '期权行权', '回购'}
    results = {}
    for sym in df['symbol'].unique():
        sdf = df[df['symbol'] == sym].dropna(subset=['effective_date']).sort_values('effective_date')
        if len(sdf) < 2:
            results[sym] = 'INSUFFICIENT'
            continue
        shares = sdf['share_count'].tolist()
        dates = sdf['effective_date'].tolist()
        reasons = sdf['change_reason'].tolist()
        
        issues = []
        for i in range(1, len(shares)):
            if shares[i] > shares[i-1]:
                continue  # 增加总是合法的
            if shares[i] < shares[i-1]:
                # 检查是否合法减少
                reason = reasons[i] if i < len(reasons) else ''
                is_legal_decrease = any(r in str(reason) for r in DECREASE_REASONS)
                if not is_legal_decrease:
                    # 定期报告导致的减少视为数据修订，标记为 SUSPICIOUS
                    if '定期报告' in str(reason):
                        issues.append(f'periodic_report_decrease at {dates[i-1]}->{dates[i]}: {shares[i-1]} -> {shares[i]} (可能的修订)')
                    else:
                        issues.append(f'illegal_decrease at {dates[i-1]}->{dates[i]}: {shares[i-1]} -> {shares[i]}')
                # 检查跳变
                if shares[i-1] > 0:
                    ratio = shares[i] / shares[i-1]
                    if ratio < 0.1:
                        issues.append(f'drop_90pct at {dates[i-1]}->{dates[i]}: {shares[i-1]} -> {shares[i]}')
        
        if issues:
            results[sym] = 'SUSPICIOUS'
        else:
            results[sym] = 'VALID_TIMELINE'
    return results


if __name__ == '__main__':
    # 审计样本
    symbols = ['000001', '002594', '600519', '000002', '601318', '000858', '002415', '600036', '000333', '601398',
               '000908', '002230', '600276', '000538', '002304']
    df = load_audit_data(symbols)
    print('Total events:', len(df))
    print('Quality distribution:')
    print(df['date_quality'].value_counts().to_string())
    print('---')
    app = audit_apprximate(df)
    print('APPROXIMATE source distribution:')
    print(app['source_type'].value_counts().to_string())
    print('---')
    print('APPROXIMATE date relation:')
    print(app['date_relation'].value_counts().to_string())
    print('---')
    timeline = check_timeline_consistency(df)
    print('Timeline consistency:')
    for sym, status in timeline.items():
        print(f'  {sym}: {status}')
    print('---')
    print('APPROXIMATE coverage by source:')
    summary = app.groupby('source_type').agg(
        records=('source_type', 'size'),
        has_ann=('has_announcement', 'sum'),
        has_change=('has_change_date', 'sum'),
    ).reset_index()
    print(summary.to_string(index=False))
