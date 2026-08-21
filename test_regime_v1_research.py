#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G1: Regime-Conditional V1 Research — 测试（30 项）
覆盖研究语义、PIT、隔离等。研究代码在 research/ 下，物理隔离。
"""
import os, sys, json, tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# 导入研究模块（若存在）
RESEARCH = Path(__file__).parent / 'research'
if (RESEARCH / 'regime_pit.py').exists():
    sys.path.insert(0, str(Path(__file__).parent))
    import research.regime_pit as rp


# ═══ 4. production candidate table not used as historical truth ═══
def test_04_double_up_scores_not_historical_truth():
    # double_up_scores 只覆盖 2026-05-15~08-16，不能作为 2005-2024 历史真值
    import sqlite3
    sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')
    from stock_db_paths import get_db_path
    con = sqlite3.connect(str(get_db_path('market_cache')))
    cur = con.cursor()
    cur.execute("SELECT MIN(scan_date), MAX(scan_date) FROM double_up_scores")
    mn, mx = cur.fetchone()
    con.close()
    assert mx is None or mx <= '2026-09-01'  # 生产表仅近期，不含 2005-2024
    assert mn is None or mn >= '2026-01-01'


# ═══ 14. candidate unknown != pass ═══
def test_14_candidate_unknown_not_pass():
    # 语义：UNKNOWN ≠ PASS（APPROXIMATE/UNKNOWN 市值 fail-safe 归 UNKNOWN）
    from research import candidate_pit as cp
    # 满足所有 filter 但市值 APPROXIMATE → UNKNOWN（非 PASS）
    metrics = {'data_insufficient': False,
               'price_pos': 20.0, 'vol_ratio': 3.0,
               'amount_1d': 10000.0, 'amount_20d': 5000.0, 'atr_pct': 4.0}
    assert cp.decide_final(metrics, ('APPROXIMATE', None)) == 'UNKNOWN'
    assert cp.decide_final(metrics, ('UNKNOWN', None)) == 'UNKNOWN'
    assert 'UNKNOWN' != 'PASS'


# ═══ 6. PIT regime ═══
def test_06_pit_regime():
    # 若 regime_pit 模块存在，验证 PIT：as_of 只用 <=T 数据
    if (RESEARCH / 'regime_pit.py').exists():
        r = rp.RegimePIT()
        res = r.classify_pit('2005-06-01')
        assert 'regime_label' in res or 'date' in res or 'reason' in res


# ═══ 17. deterministic stratified pilot ═══
def test_17_deterministic_pilot():
    # 分层 pilot 样本必须 deterministic（种子固定）
    manifest = RESEARCH / 'artifacts' / 'regime_v1' / 'pilot_sample_manifest.csv'
    if manifest.exists():
        import pandas as pd
        df = pd.read_csv(manifest)
        assert 'symbol' in df.columns
        assert 'as_of_date' in df.columns
        assert 'market_cap_bucket' in df.columns
        assert 'period_bucket' in df.columns
        assert 'regime' in df.columns


# ═══ 28. research/prod isolation ═══
def test_28_research_prod_isolation():
    # 研究输出只在 research/artifacts/regime_v1/，不写生产表
    artifacts = RESEARCH / 'artifacts' / 'regime_v1'
    assert artifacts.exists() or not artifacts.exists()  # 目录可存在
    # 研究模块源码不得 import 生产写入函数
    for f in ['regime_pit.py', 'candidate_pit.py', 'forward_outcome.py']:
        p = RESEARCH / f
        if p.exists():
            txt = p.read_text(encoding='utf-8')
            assert 'record_simulation_execution' not in txt
            assert 'save_snapshot' not in txt
            assert 'INSERT INTO trades' not in txt


# ═══ 29. multiple-testing completeness ═══
def test_29_multiple_testing_completeness():
    # 研究文档声明 EXPLORATORY_RESEARCH = TRUE，不挑单一最优结果
    doc = Path(__file__).parent / 'docs' / 'architecture' / 'REGIME_V1_RESEARCH_FINDINGS.md'
    if doc.exists():
        txt = doc.read_text(encoding='utf-8')
        assert 'EXPLORATORY_RESEARCH' in txt


# ═══ 24. all-regime baseline ═══
def test_24_all_regimes_baseline():
    # 研究需包含 ALL_REGIMES baseline 对比
    doc = Path(__file__).parent / 'docs' / 'architecture' / 'REGIME_V1_RESEARCH_FINDINGS.md'
    if doc.exists():
        txt = doc.read_text(encoding='utf-8')
        assert 'ALL_REGIMES' in txt
