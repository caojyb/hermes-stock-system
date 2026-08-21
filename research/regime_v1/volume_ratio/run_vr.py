#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G2: Volume Ratio × Regime Research — 数据运行脚本（Pilot → Expansion）
================================================================================
从历史 K 线重建 V1 候选（含 VR 全谱，不做 2.7 截断），计算 forward outcome，
按 VR band / Regime 分层分析。

策略：对每个股票，对每个 weekly candidate date，计算完整 filter metrics
（含 VR 连续值），并用 PIT 市值判断 candidate 状态；然后 forward outcome。
"""
from __future__ import annotations
import os, sys, json, sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

CRON_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent  # .../cron
RESEARCH_DIR = Path(__file__).resolve().parent.parent.parent  # .../research
sys.path.insert(0, str(CRON_DIR))
sys.path.insert(0, str(RESEARCH_DIR))
sys.path.insert(0, str(RESEARCH_DIR.parent))  # cron 上级，含 research 包

import research.candidate_pit as cp
import research.regime_pit as rp
import research.forward_outcome as fo

ART = Path(__file__).resolve().parent / 'artifacts'
ART.mkdir(parents=True, exist_ok=True)
RESEARCH_VERSION = 'phase-8g2-v1'


def load_regime_map() -> dict:
    """读取 G1 regime_daily 建立 date->regime 映射（PIT 重建结果）。"""
    # 用 regime_pit 全量重建（分片），这里先读已有 regime_daily.csv
    path = Path('/home/caojy/.hermes/scripts/cron/research/artifacts/regime_v1/regime_daily.csv')
    if path.exists():
        df = pd.read_csv(path)
        m = {}
        for _, r in df.iterrows():
            m[str(r['date'])] = str(r['regime_label'])
        return m
    return {}


def rebuild_regime(start='2005-01-01', end='2024-12-31'):
    """用 regime_pit 全量重建 regime（分片避免内存）。"""
    # 复用 G1 模块
    pit = rp.RegimePIT()
    return pit


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2015-01-01')
    ap.add_argument('--end', default='2024-12-31')
    ap.add_argument('--limit', type=int, default=120, help='股票数量')
    ap.add_argument('--symbols', default='', help='指定股票')
    ap.add_argument('--fixtures', action='store_true', help='用离线 fixture 股本')
    args = ap.parse_args()

    # 1. 股票池
    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()] if args.symbols else None
    universe = cp.load_universe(limit=args.limit, symbols=symbols)
    print(f'[vr] universe: {len(universe)} stocks', file=sys.stderr)

    # 2. 逐股重建 candidate trace（含 VR 连续值），按 weekly cadence
    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    all_trace = []
    con = sqlite3.connect(str(cp.DB))
    for sym in universe:
        try:
            df = cp.build_trace(sym, start_d, end_d, use_fixtures=args.fixtures)
            if df is not None and len(df):
                all_trace.append(df)
        except Exception as e:
            # 数据不足等跳过
            pass
    con.close()
    if not all_trace:
        print('[vr] no trace', file=sys.stderr)
        return 1
    trace = pd.concat(all_trace, ignore_index=True)
    # market_cap 列统一为 str（混合 APPROXIMATE/UNKNOWN/数值）
    if 'market_cap' in trace.columns:
        trace['market_cap'] = trace['market_cap'].astype(str)
    print(f'[vr] trace rows: {len(trace)}', file=sys.stderr)
    # 保存
    trace.to_parquet(ART / 'vr_candidate_trace.parquet', index=False)
    trace.to_csv(ART / 'vr_candidate_trace.csv', index=False)
    print('[vr] saved trace', file=sys.stderr)

    # 3. 计算 forward outcome
    # 时间语义：candidate 日 = as_of_date（weekly 最后交易日），planned entry = T+1 Open。
    # forward_outcome 以 candidate_date 定位 T+1，用 entry_price(=T+1 open)。
    con = sqlite3.connect(str(cp.DB))
    candidates = []
    for _, r in trace.iterrows():
        # 取 T+1 开盘价作为 planned entry price
        entry_open = None
        try:
            cur = con.cursor()
            cur.execute("SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
                        (r['symbol'], r['as_of_date']))
            row = cur.fetchone()
            if row and row[0]:
                entry_open = float(row[0])
        except Exception:
            entry_open = None
        cand = {
            'symbol': r['symbol'],
            'candidate_date': r['as_of_date'],
            'entry_price': entry_open,
            'entry_date': None,
            'as_of_date': r['as_of_date'],
            'price_pos': r.get('price_pos'),
            'vol_ratio': r.get('vol_ratio'),
            'atr_pct': r.get('atr_pct'),
            'final_candidate': r.get('final_candidate'),
        }
        candidates.append(cand)
    results = fo.compute_outcomes(candidates, con=con)
    con.close()
    out_df = pd.DataFrame(results)
    print(f'[vr] outcomes rows: {len(out_df)}', file=sys.stderr)
    out_df.to_parquet(ART / 'vr_outcomes.parquet', index=False)
    out_df.to_csv(ART / 'vr_outcomes.csv', index=False)
    print('[vr] saved outcomes', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
