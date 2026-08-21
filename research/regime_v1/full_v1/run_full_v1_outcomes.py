#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G3: Full V1 Candidate + Entry Signal Forward Outcome
============================================================
对 full_candidate_trace 计算：
- Candidate-level forward outcome（所有 final_candidate=PASS/UNKNOWN 都算，但分层）
- Signal-level forward outcome（entry_confirmed=True 才入）
严格 RESEARCH_ONLY，COUNTERFACTUAL_RESEARCH。
"""
from __future__ import annotations
import os, sys, sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

CRON_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(CRON_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import research.forward_outcome as fo

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
ART = Path(__file__).resolve().parent / 'artifacts'
ART.mkdir(parents=True, exist_ok=True)


def compute_candidate_outcomes(trace_path: Path) -> pd.DataFrame:
    """Candidate-level forward outcome。"""
    df = pd.read_parquet(trace_path) if trace_path.suffix == '.parquet' else pd.read_csv(trace_path)
    con = sqlite3.connect(str(DB))
    candidates = []
    for _, r in df.iterrows():
        cur = con.cursor()
        cur.execute("SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
                    (r['symbol'], r['as_of_date']))
        row = cur.fetchone()
        entry_price = float(row[0]) if row and row[0] else None
        cand = {
            'symbol': r['symbol'],
            'candidate_date': r['as_of_date'],
            'entry_price': entry_price,
            'entry_date': None,
            'as_of_date': r['as_of_date'],
            'final_candidate': r.get('final_candidate'),
            'vol_ratio': r.get('vol_ratio'),
            'market_cap_quality': r.get('market_cap_quality'),
            'st_quality': r.get('st_quality'),
            'signal_count': r.get('signal_count'),
            'entry_confirmed': r.get('entry_confirmed'),
        }
        candidates.append(cand)
    results = fo.compute_outcomes(candidates, con=con)
    con.close()
    out = pd.DataFrame(results)
    return out


def compute_signal_outcomes(trace_path: Path) -> pd.DataFrame:
    """Signal-level forward outcome（仅 entry_confirmed=True）。"""
    df = pd.read_parquet(trace_path) if trace_path.suffix == '.parquet' else pd.read_csv(trace_path)
    df = df[df['entry_confirmed'] == True].copy()
    con = sqlite3.connect(str(DB))
    candidates = []
    for _, r in df.iterrows():
        cur = con.cursor()
        cur.execute("SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
                    (r['symbol'], r['as_of_date']))
        row = cur.fetchone()
        entry_price = float(row[0]) if row and row[0] else None
        cand = {
            'symbol': r['symbol'],
            'candidate_date': r['as_of_date'],
            'entry_price': entry_price,
            'entry_date': None,
            'as_of_date': r['as_of_date'],
            'final_candidate': r.get('final_candidate'),
            'vol_ratio': r.get('vol_ratio'),
            'market_cap_quality': r.get('market_cap_quality'),
            'st_quality': r.get('st_quality'),
            'signal_count': r.get('signal_count'),
            'entry_confirmed': r.get('entry_confirmed'),
        }
        candidates.append(cand)
    results = fo.compute_outcomes(candidates, con=con)
    con.close()
    out = pd.DataFrame(results)
    return out


if __name__ == '__main__':
    trace = ART / 'full_candidate_trace.parquet'
    print('[fullv1-outcome] computing candidate outcomes...')
    cand_out = compute_candidate_outcomes(trace)
    cand_out.to_parquet(ART / 'candidate_outcomes.parquet', index=False)
    print(f'  candidate_outcomes: {len(cand_out)} rows')
    print('[fullv1-outcome] computing signal outcomes...')
    sig_out = compute_signal_outcomes(trace)
    sig_out.to_parquet(ART / 'signal_outcomes.parquet', index=False)
    print(f'  signal_outcomes: {len(sig_out)} rows')
    print('done')
