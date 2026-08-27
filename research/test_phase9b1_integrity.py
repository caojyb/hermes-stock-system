#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/test_phase9b1_integrity.py — Phase 9-B.1 因子研究完整性与数据补全测试（≥22 项）
====================================================================================

覆盖：财务 PIT / 执行模型 / Momentum 审计 / R1 vs R2 版本 / 多重检验 / V1 隔离 / 无组合 / 无生产写 / 可复现。

严禁修改 V1/Regime/DecisionEngine/生产规则；不启用 Selector/主升浪/自动交易。
"""

from __future__ import annotations

import os
import sys
import json
import csv
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

from research.factor_research.financial_pit_audit import audit_financial_pit, can_become_pit_ready  # noqa: E402
from research.factor_research.execution_sim import (  # noqa: E402
    build_exec_model_r2, simulate_trade, detect_limit_state,
)
from research.factor_research.momentum_audit import (  # noqa: E402
    audit_momentum_factor, MOM_RS_DEFINITION, NORMALIZATION_STATUS, compute_cross_section_median_map,
)
from research.factor_research.factor_engine import compute_factor, f_rs  # noqa: E402
from research.factor_research.research_runner import (  # noqa: E402
    build_samples, study_on_samples, load_universe,
)
from research.factor_research.factor_definitions import FACTOR_DEFS  # noqa: E402

CRON = "/home/caojy/.hermes/scripts/cron"
ART_R1 = os.path.join(CRON, "research", "artifacts", "factors", "r1")
ART_R2 = os.path.join(CRON, "research", "artifacts", "factors", "r2")


# ════════ 1. financial PIT metadata ════════
def test_01_financial_pit_no_announcement_date():
    rows = audit_financial_pit()
    # 所有因子 announcement_date 必须为 UNAVAILABLE（全库无该字段，已全局审计）
    for r in rows:
        assert r.announcement_date == "UNAVAILABLE", f"{r.factor} 不应有 announcement_date"
    # 覆盖关键财务因子
    fids = {r.factor for r in rows}
    for must in ["QUALITY_ROE", "QUALITY_DEBT_RATIO", "QUALITY_REV_GROWTH", "GROWTH_PROFIT_ACCEL"]:
        assert must in fids


# ════════ 2. approximate PIT handling ════════
def test_02_approximate_pit_quantified():
    rows = audit_financial_pit()
    approx = [r for r in rows if r.pit_status == "PIT_APPROXIMATE"]
    assert len(approx) >= 6, "应至少 6 个财务因子为 PIT_APPROXIMATE"
    # 近似因子必须停留在 PARTIAL（不得进入严格 Qualification）
    blocked = [r for r in rows if r.pit_status == "BLOCKED"]
    assert any(r.factor in ("QUALITY_ROIC", "QUALITY_OCF_NI") for r in blocked)


# ════════ 3. execution model state ════════
def test_03_execution_model_state():
    m = build_exec_model_r2()
    assert m.status == "READY"
    assert "limit_up_no_buy" in m.covered
    assert "limit_down_no_sell" in m.covered
    assert "t_plus_1" in m.covered
    assert m.is_qualified_ready() is True
    assert m.blocking_for_qualification() is False


# ════════ 4. limit-up buy block ════════
def test_04_limit_up_buy_block():
    row = {"date": "2020-01-02", "open": 16.5, "close": 16.5, "high": 16.5, "low": 15.0,
           "volume": 1e6, "change_pct": 10.0}
    et = simulate_trade("000001", row, {"date": "2020-01-03", "open": 16.0, "close": 15.8,
                                        "high": 16.1, "low": 15.7, "volume": 1e6, "change_pct": -1.0})
    assert et.fill_status == "BLOCKED_LIMIT_UP"
    assert et.blocked_reason != ""


# ════════ 5. limit-down sell block ════════
def test_05_limit_down_sell_block():
    entry = {"date": "2020-01-02", "open": 15.0, "close": 15.2, "high": 15.3, "low": 14.9,
             "volume": 1e6, "change_pct": 1.0}
    exit_r = {"date": "2020-01-03", "open": 13.5, "close": 13.5, "high": 14.0, "low": 13.5,
              "volume": 1e6, "change_pct": -10.0}
    et = simulate_trade("000001", entry, exit_r)
    assert et.fill_status == "BLOCKED_LIMIT_DOWN"
    assert et.blocked_reason != ""


# ════════ 6. T+1 ════════
def test_06_t_plus_1_semantics():
    # simulate_trade 默认 entry=次日 open，exit=再次日 open → 隐含 T+1
    entry = {"date": "2020-01-02", "open": 15.0, "close": 15.2, "high": 15.3, "low": 14.9,
             "volume": 1e6, "change_pct": 1.0}
    exit_r = {"date": "2020-01-03", "open": 15.5, "close": 15.6, "high": 15.7, "low": 15.4,
              "volume": 1e6, "change_pct": 0.6}
    et = simulate_trade("000001", entry, exit_r)
    # entry_date 与 exit_date 不同日 → 至少 T+1 持有
    assert et.entry_date != et.exit_date


# ════════ 7. lot-size ════════
def test_07_lot_size():
    entry = {"date": "2020-01-02", "open": 15.0, "close": 15.2, "high": 15.3, "low": 14.9,
             "volume": 1e6, "change_pct": 1.0}
    exit_r = {"date": "2020-01-03", "open": 15.5, "close": 15.6, "high": 15.7, "low": 15.4,
              "volume": 1e6, "change_pct": 0.6}
    et = simulate_trade("000001", entry, exit_r, capital=100000.0)
    assert et.shares % 100 == 0, "股数必须按 100 取整"
    assert et.shares > 0


# ════════ 8. momentum window ════════
def test_08_momentum_window():
    r = audit_momentum_factor("MOM_250D")
    assert r.window_correct is True
    assert r.pit_safe is True
    assert r.uses_future is False


# ════════ 9. momentum PIT ════════
def test_09_momentum_pit_safe_all():
    for fid in ["MOM_20D", "MOM_60D", "MOM_120D", "MOM_250D", "MOM_52W_DIST",
                "MOM_MA20_SLOPE", "MOM_MA60_SLOPE", "VOL_RATIO", "VOL_TURNOVER_PERSIST",
                "VOL_AMOUNT_PERSIST", "VOL_ACCEL"]:
        r = audit_momentum_factor(fid)
        assert r.pit_safe is True, f"{fid} 必须 PIT-safe"
        assert r.uses_future is False, f"{fid} 不得含未来数据"


# ════════ 10. relative-strength formula ════════
def test_10_relative_strength_formula():
    # 验证 f_rs 修正后公式：own - cross_section_median（去均值，无除零）
    # 构造最小 klines：61 个交易日，close 单调使 60D 收益 = 0.10
    kl = [{"date": f"2020-01-{i:02d}" if i <= 31 else f"2020-02-{i-31:02d}",
           "close": 10.0 * (1.10 ** (i / 60.0))} for i in range(61)]
    own_ret = f_rs(kl, 0.05)   # 个股 60D 收益约 0.10 - 中位 0.05
    assert own_ret is not None
    assert abs(own_ret - 0.05) < 0.05  # 去均值后约为个股收益减中位
    # 中位数缺失时回退为原始 60D 收益（至少有值，避免 9-B n_valid=0 假象）
    own_fallback = f_rs(kl, None)
    assert own_fallback is not None and own_fallback > 0
    # 定义字符串正确
    assert "60D 收益" in MOM_RS_DEFINITION
    assert "中位数" in MOM_RS_DEFINITION


# ════════ 11. normalization ════════
def test_11_normalization_status():
    r = audit_momentum_factor("MOM_RS")
    assert "CROSS_SECTIONAL_DEMEANED" in r.normalization
    assert "NOT_NORMALIZED" in r.normalization  # 标注 9-B 缺陷
    # compute_cross_section_median_map 返回 {date: median}
    series = {"A": {"2020-01-01": 0.1, "2020-01-02": 0.2},
              "B": {"2020-01-01": 0.3, "2020-01-02": 0.4}}
    med = compute_cross_section_median_map(series)
    assert abs(med["2020-01-01"] - 0.2) < 1e-9
    assert abs(med["2020-01-02"] - 0.3) < 1e-9


# ════════ 12. quantile (momentum re-run) ════════
def test_12_quantile_momentum():
    uni = load_universe(limit=20)
    samples = build_samples(uni, "2020-01-01", "2021-12-31", compute_cs_median=True)
    res = study_on_samples("MOM_60D", samples)
    # 至少部分样本有效
    assert res.n_valid > 0, "MOM_60D 应有有效样本"
    assert isinstance(res.quantiles, dict)


# ════════ 13. time stability ════════
def test_13_time_stability():
    uni = load_universe(limit=20)
    samples = build_samples(uni, "2015-01-01", "2024-12-31", compute_cs_median=True)
    res = study_on_samples("QUALITY_ROE", samples)
    # time_stability 含 period 键（即使 DATA_INSUFFICIENT 也应有记录）
    assert isinstance(res.time_stability, dict)


# ════════ 14. regime stability ════════
def test_14_regime_stability():
    uni = load_universe(limit=20)
    samples = build_samples(uni, "2015-01-01", "2024-12-31", compute_cs_median=True)
    res = study_on_samples("QUALITY_DEBT_RATIO", samples)
    assert isinstance(res.regime_stability, dict)


# ════════ 15. corrected factor versioning ════════
def test_15_corrected_factor_versioning():
    # r1 与 r2 artifacts 目录独立，不互相覆盖
    assert os.path.isdir(ART_R1), "R1 artifacts 必须保留"
    # r2 目录在 Pilot/Expansion 运行后存在（若已运行）
    # 此处仅验证版本字符串定义存在
    from research.factor_research.run_study_r2 import FACTOR_ENGINE_VERSION, EXECUTION_MODEL_VERSION
    assert FACTOR_ENGINE_VERSION == "2.0"
    assert EXECUTION_MODEL_VERSION == "2.0"


# ════════ 16. original artifacts preserved ════════
def test_16_original_artifacts_preserved():
    # R1 expansion artifacts 必须仍在
    assert os.path.exists(os.path.join(ART_R1, "expansion", "factor_discovery_ranking.json")), \
        "R1 expansion ranking 必须保留"
    assert os.path.exists(os.path.join(ART_R1, "pilot", "run_manifest.json")), \
        "R1 pilot manifest 必须保留"


# ════════ 17. multiple-testing metadata ════════
def test_17_multiple_testing_metadata():
    # 定义层应声明 search space = 25
    from research.factor_research.factor_definitions import FACTOR_DEFS
    assert len(FACTOR_DEFS) == 25
    # 若 R2 manifest 已生成则检查
    mt_file = os.path.join(ART_R2, "expansion", "multiple_testing_status.json")
    if os.path.exists(mt_file):
        mt = json.load(open(mt_file, encoding="utf-8"))
        assert mt["multiple_testing_status"] == "DISCOVERY_ONLY"
        assert mt["r1_search_space"] == 25 and mt["r2_search_space"] == 25


# ════════ 18. V1 isolation ═════════
def test_18_v1_isolation():
    # 本阶段不得修改 V1 相关文件；用 git 检查 working tree 不含 decision/ 变更
    out = subprocess.run(["git", "status", "--short"], cwd=CRON, capture_output=True, text=True)
    changed = [l for l in out.stdout.splitlines() if l.strip()]
    # 允许 research/ 新增与每日 cron 产物；禁止 decision/ forward_outcome.py 等
    for l in changed:
        assert not any(p in l for p in ["decision/", "forward_outcome.py", "candidate_pit.py",
                                        "regime_pit.py", "regime_v1/"]), \
            f"禁止修改 V1/生产模块: {l}"


# ════════ 19. no factor combination ═════════
def test_19_no_factor_combination():
    # 框架不得输出 V2 组合规则
    txt = open(os.path.join(os.path.dirname(__file__), "factor_research", "factor_definitions.py"),
               encoding="utf-8").read()
    assert "组合" not in txt or "不组合" in txt  # 文档可提及“不组合”，但不得实现组合逻辑
    # execution_sim / momentum_audit 不得含 combination/weight 逻辑
    etxt = open(os.path.join(os.path.dirname(__file__), "factor_research", "execution_sim.py"),
                encoding="utf-8").read()
    assert "weight" not in etxt.lower()


# ════════ 20. no production write ═════════
def test_20_no_production_write():
    # 研究框架不写 Production Decision / real holdings
    import research.factor_research.run_study_r2 as r2
    src = open(r2.__file__, encoding="utf-8").read()
    for forbidden in ["real_holdings", "Production Decision", "produce_final_decision",
                      "emit_decision", "BUY", "SELL"]:
        assert forbidden not in src, f"研究框架不得含生产写: {forbidden}"


# ════════ 21. reproducibility ═════════
def test_21_reproducibility():
    uni = load_universe(limit=15)
    s1 = build_samples(uni, "2020-01-01", "2021-12-31", compute_cs_median=True)
    s2 = build_samples(uni, "2020-01-01", "2021-12-31", compute_cs_median=True)
    r1 = study_on_samples("VOL_ACCEL", s1).to_dict()
    r2 = study_on_samples("VOL_ACCEL", s2).to_dict()
    assert r1["n_valid"] == r2["n_valid"]
    assert abs((r1.get("quantiles") or {}).get("q1", 0) - (r2.get("quantiles") or {}).get("q1", 0)) < 1e-9


# ════════ 22. old vs corrected comparison ═════════
def test_22_old_vs_corrected_comparison():
    # 若 R2 expansion 已生成，验证 R1 vs R2 对比文件存在
    cmp_file = os.path.join(ART_R2, "expansion", "r1_vs_r2_comparison.json")
    if os.path.exists(cmp_file):
        cmp = json.load(open(cmp_file, encoding="utf-8"))
        assert isinstance(cmp, list) and len(cmp) == 25
        # MOM_RS 在 R2 应有 n_valid>0（修正归一化），R1 为 0
        mom = next(c for c in cmp if c["factor_id"] == "MOM_RS")
        assert mom["r2_n_valid"] and mom["r2_n_valid"] > 0, "MOM_RS R2 应已修正为有效样本"
        assert mom["r1_n_valid"] == 0, "MOM_RS R1 应为 0（未归一化）"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
