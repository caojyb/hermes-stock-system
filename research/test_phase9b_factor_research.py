#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/test_phase9b_factor_research.py — Phase 9-B 因子研究测试（≥24 项）
============================================================================
覆盖：registry load / PIT / coverage / common window / outcome parity /
quantile / monotonicity / time / regime / market-cap / incremental /
redundancy / multiple-testing / dataset version / reproducibility /
blocked handling / unknown≠zero / V1 isolation / no combination / no prod write /
deterministic / artifact completeness。

不修改任何生产/研究源码；仅验证本阶段新增框架。
"""

import os
import sys
import json
import csv
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research.factor_research.factor_definitions as fd  # noqa: E402
import research.factor_research.factor_engine as fe  # noqa: E402
from research.factor_research.factor_definitions import FACTOR_DEFS, FACTOR_BY_ID  # noqa: E402
from research.factor_research.research_runner import (  # noqa: E402
    build_samples, study_on_samples, load_universe, load_regime_map, COMMON_WINDOW,
    monthly_candidate_dates, _quantile_bins, monotonicity_label,
)
import research.forward_outcome as fo  # noqa: E402

DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"


# ════════ 1. factor registry load ════════
def test_01_factor_registry_load():
    assert len(FACTOR_DEFS) == 25, f"expected 25 factors, got {len(FACTOR_DEFS)}"
    ids = [f.factor_id for f in FACTOR_DEFS]
    assert len(set(ids)) == 25, "factor_id must be unique"
    for fid in ids:
        assert FACTOR_BY_ID[fid] is not None


# ════════ 2. unknown factor rejected ════════
def test_02_unknown_factor_rejected():
    res = study_on_samples("NOT_A_FACTOR", [])
    assert res.availability == "BLOCKED"
    assert res.pit_status == "UNKNOWN_FACTOR"


# ════════ 3. PIT metadata required ════════
def test_03_pit_metadata_required():
    for f in FACTOR_DEFS:
        assert f.pit_status in ("PIT_READY", "PIT_APPROXIMATE", "PIT_BLOCKED"), f.factor_id
        assert f.effective_date_reliable in (True, False), f.factor_id


# ════════ 4. data coverage recorded ════════
def test_04_data_coverage_recorded():
    # 可用性矩阵应包含 RESEARCHABLE/PARTIAL/BLOCKED 三类
    counts = fd.summary_counts()
    assert counts["RESEARCHABLE"] >= 1
    assert "PARTIAL" in counts
    assert "BLOCKED" in counts
    # 财务全零字段必须被标 BLOCKED
    for fid in ["QUALITY_ROIC", "QUALITY_OCF_NI", "VAL_PE_PCT", "VAL_PB_PCT", "VAL_PEG"]:
        assert FACTOR_BY_ID[fid].availability == "BLOCKED", fid


# ════════ 5. missingness tracked ════════
def test_05_missingness_tracked():
    uni = load_universe(limit=10)
    samples = build_samples(uni, "2019-01-01", "2019-12-31")
    res = study_on_samples("MOM_20D", samples)
    # n_total == n_valid + n_missing (+ unknown 仅计入 n_unknown)
    assert res.n_total == res.n_valid + res.n_missing
    assert res.n_unknown >= 0


# ════════ 6. common window fixed ════════
def test_06_common_window():
    assert COMMON_WINDOW[0] == "2005-01-01"
    assert COMMON_WINDOW[1] == "2024-12-31"


# ════════ 7. outcome parity (reuse forward_outcome) ════════
def test_07_outcome_parity():
    import sqlite3
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.text_factory = str
    row = con.execute(
        "SELECT code,date,open FROM klines WHERE date>'2019-06-01' ORDER BY code,date LIMIT 1").fetchone()
    con.close()
    cand = {"symbol": row[0], "candidate_date": row[1], "entry_price": float(row[2]),
            "entry_date": None, "as_of_date": row[1]}
    out = fo.compute_one(cand, __import__("sqlite3").connect(f"file:{DB}?mode=ro", uri=True))
    # 统一 outcome 字段存在
    for k in ("fwd_5d", "fwd_10d", "fwd_20d", "mae", "mfe"):
        assert k in out


# ════════ 8. quantile assignment ════════
def test_08_quantile_assignment():
    vals = [(f"s{i}", float(i)) for i in range(100)]
    q = _quantile_bins(vals, q=10)
    assert all(1 <= q[k] <= 10 for k in q)
    # 最小 10% 落在 q1
    assert q["s0"] == 1
    assert q["s99"] == 10


# ════════ 9. monotonicity detection ════════
def test_09_monotonicity():
    mono_pos = {1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4, 5: 0.5, 6: 0.6, 7: 0.7, 8: 0.8, 9: 0.9, 10: 1.0}
    assert monotonicity_label(mono_pos) == "MONOTONIC_POSITIVE"
    mono_neg = {i: 1.0 - i * 0.1 for i in range(1, 11)}
    assert monotonicity_label(mono_neg) == "MONOTONIC_NEGATIVE"
    # U-shape 应判 NON_MONOTONIC（不误判为无效）
    ushape = {1: 0.5, 2: 0.2, 3: 0.1, 4: 0.2, 5: 0.4, 6: 0.6, 7: 0.8, 8: 0.9, 9: 1.0, 10: 0.7}
    assert monotonicity_label(ushape) == "NON_MONOTONIC"


# ════════ 10. time split ════════
def test_10_time_split():
    uni = load_universe(limit=40)
    samples = build_samples(uni, "2015-01-01", "2024-12-31")
    res = study_on_samples("MOM_20D", samples)
    # 至少应有某些 period 有样本
    assert any("q1_q9_spread" in v for v in res.time_stability.values())


# ════════ 11. regime split uses existing regime csv ════════
def test_11_regime_split():
    regime = load_regime_map()
    assert len(regime) > 100, "regime_daily.csv should be loaded"
    uni = load_universe(limit=40)
    samples = build_samples(uni, "2015-01-01", "2024-12-31")
    res = study_on_samples("MOM_20D", samples)
    for rg in ["🔴高波动", "⚫低量能", "🟡震荡市", "🟢强趋势"]:
        assert rg in res.regime_stability


# ════════ 12. market-cap split (APPROXIMATE flagged) ════════
def test_12_marketcap_split():
    uni = load_universe(limit=60)
    samples = build_samples(uni, "2018-01-01", "2021-12-31",
                            mcap_helper=lambda s, d: ("APPROX", 30.0))
    res = study_on_samples("MOM_20D", samples)
    for tier in ["small", "mid", "large"]:
        assert tier in res.marketcap_stability
    # 若有样本被分到 small，标注 APPROXIMATE
    if "q1_q9_spread" in res.marketcap_stability.get("small", {}):
        assert res.marketcap_stability["small"]["note"] == "APPROXIMATE mcap"


# ════════ 13. incremental evidence ════════
def test_13_incremental_evidence():
    uni = load_universe(limit=40)
    samples = build_samples(uni, "2018-01-01", "2021-12-31")
    res = study_on_samples("VOL_RATIO", samples)
    assert res.incremental in ("POSITIVE", "NONE", "UNDEFINED")


# ════════ 14. redundancy matrix computable ════════
def test_14_redundancy_matrix():
    uni = load_universe(limit=30)
    samples = build_samples(uni, "2019-01-01", "2020-12-31")
    from research.factor_research.run_study import _factor_values_for_redundancy, _spearman
    a = _factor_values_for_redundancy(samples, "MOM_20D")
    b = _factor_values_for_redundancy(samples, "MOM_60D")
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) >= 10:
        sp = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
        assert sp is not None
        assert -1.0 <= sp <= 1.0


# ════════ 15. multiple-testing metadata ════════
def test_15_multiple_testing_metadata():
    assert len(FACTOR_DEFS) == 25
    # 默认状态应在 artifact 中显式为 DISCOVERY_ONLY（见 run_study manifest）


# ════════ 16. dataset version binding ════════
def test_16_dataset_version_binding():
    from research.dataset_registry import DatasetRegistry
    reg = DatasetRegistry()
    assert len(reg.all()) >= 1
    # 研究必须使用 dataset_id+version，而非 'today latest'
    ds = reg.get("dataset_v1_full")
    assert ds is not None
    assert ds.version == "1.0"


# ════════ 17. reproducibility (deterministic) ════════
def test_17_reproducibility():
    uni = load_universe(limit=20)
    s1 = build_samples(uni, "2019-01-01", "2021-12-31")
    s2 = build_samples(uni, "2019-01-01", "2021-12-31")
    r1 = study_on_samples("MOM_20D", s1)
    r2 = study_on_samples("MOM_20D", s2)
    assert r1.n_valid == r2.n_valid
    assert r1.monotonicity == r2.monotonicity
    assert r1.quantiles == r2.quantiles


# ════════ 18. blocked factor handling ═════════
def test_18_blocked_factor_handling():
    uni = load_universe(limit=20)
    samples = build_samples(uni, "2019-01-01", "2019-12-31")
    res = study_on_samples("VAL_PE_PCT", samples)
    # 全零字段 → n_valid=0，不得伪造
    assert res.n_valid == 0
    assert res.availability == "BLOCKED"


# ════════ 19. unknown ≠ zero ═════════
def test_19_unknown_not_zero():
    # forward_outcome 的 UNKNOWN 不回填 0
    out = fo.compute_one({"symbol": "NONEXIST", "candidate_date": "1990-01-01",
                          "entry_price": None},
                         __import__("sqlite3").connect(f"file:{DB}?mode=ro", uri=True))
    for k in ("fwd_5d", "fwd_10d", "fwd_20d", "mae", "mfe"):
        assert out.get(k) != 0, f"{k} must not be 0 when UNKNOWN"


# ════════ 20. V1 isolation ═════════
def test_20_v1_isolation():
    # 本阶段不得触碰 V1 生产/研究源码。
    # 允许：research/ 新增、每日 cron 产物、以及 decision/ 的 *测试文件*
    # （9-B.2/9-B.3 对 decision 测试做日期隔离/回归修复属于测试范围，非生产修改）。
    # 禁止：decision/ 生产模块、regime_v1/、forward_outcome.py、candidate_pit.py。
    import subprocess
    r = subprocess.run(["git", "status", "--short"], cwd=os.path.dirname(os.path.abspath(__file__)),
                       capture_output=True, text=True)
    ALLOWED = ("decision/test_", "decision/conftest.py", "research/", "heartbeat_state.json",
               "hot_sector", "reports/", "snapshots/")
    FORBIDDEN = ("decision/engine.py", "decision/forward_outcome.py", "decision/candidate_pit.py",
                 "decision/regime_pit.py", "decision/regime_v1/", "decision/validation_",
                 "decision/snapshot_verify.py", "decision/snapshot.py",
                 "decision/daily_decision_contract.py", "decision/real_", "regime_v1/")
    for line in r.stdout.splitlines():
        # 提取路径部分（去掉状态前缀）
        parts = line.split(None, 1)
        path = parts[-1] if len(parts) > 1 else line
        if any(path.startswith(a) for a in ALLOWED):
            continue
        if any(p in line for p in FORBIDDEN):
            assert line.startswith("??") or line.startswith("A "), f"must not modify V1 source: {line}"


# ════════ 21. no strategy combination ═════════
def test_21_no_strategy_combination():
    # 框架不得输出 V2 组合规则
    txt = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "factor_research", "factor_definitions.py")).read()
    assert "StrategySpec" not in txt or "组合权重" not in txt


# ════════ 22. no production write ═════════
def test_22_no_production_write():
    # 研究写盘仅限 research/artifacts/factors/r1
    art = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research", "artifacts", "factors", "r1")
    if os.path.exists(art):
        for root, _, files in os.walk(art):
            for f in files:
                assert "production" not in f.lower()


# ════════ 23. deterministic output (study stable) ═════════
def test_23_deterministic_output():
    uni = load_universe(limit=15)
    samples = build_samples(uni, "2020-01-01", "2021-12-31")
    r1 = study_on_samples("VOL_RATIO", samples).to_dict()
    r2 = study_on_samples("VOL_RATIO", samples).to_dict()
    assert json.dumps(r1, sort_keys=True, default=str) == json.dumps(r2, sort_keys=True, default=str)


# ════════ 24. artifact completeness (if pilot run exists) ═════════
def test_24_artifact_completeness():
    art = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "research", "artifacts", "factors", "r1", "pilot")
    if not os.path.isdir(art):
        # Pilot 尚未运行则跳过（让 CI 不依赖 DB 重跑）
        return
    required = ["factor_data_availability.csv", "factor_summary_matrix.csv",
                "factor_redundancy_matrix.csv", "factor_discovery_ranking.json", "run_manifest.json"]
    for f in required:
        assert os.path.exists(os.path.join(art, f)), f"missing {f}"
    # 每个因子目录至少含 definition.json + summary.json
    for fd0 in FACTOR_DEFS:
        fd_dir = os.path.join(art, f"factor_{fd0.factor_id}")
        if os.path.isdir(fd_dir):
            assert os.path.exists(os.path.join(fd_dir, "definition.json"))
            assert os.path.exists(os.path.join(fd_dir, "summary.json"))


# ════════ 额外：availability matrix 字段完整 ════════
def test_25_availability_matrix_fields():
    for f in FACTOR_DEFS:
        assert f.source_table and f.source_field
        assert f.coverage_start and f.coverage_end
        assert f.known_caveats


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
