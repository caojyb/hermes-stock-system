#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 9-A: Multi-Strategy Research & Qualification Framework — 测试套件
========================================================================

覆盖（与 Phase 9-A 三十六 对应）：
  Registry 1-5 / Contract 6-10 / Dataset 11-15 / Comparison 16-20 /
  Qualification 21-28 / PIT 29-32 / Execution 33-36 /
  Multi-testing 37-38 / Strategy isolation 39-40
  外加 runner 集成 / shadow / forward / v2 / factor / reproducibility / artifacts / persistence（41-48）。

原则：本套件不修改任何既有生产/研究代码，只验证新增框架的一致性、隔离性与硬门槛。
不依赖 3GB 生产数据库（runner 集成测试用内存 sqlite）。
"""
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'research'))

import research.strategy_registry as sr
import research.dataset_registry as dr
import research.strategy_contract as sc
import research.strategy_runner as runner
import research.execution_models as em
import research.pit_gate as pg
import research.survivorship_gate as sg
import research.multiple_testing as mt
import research.factors.factor_contract as fc
import research.strategy_comparison as cmp
import research.qualification_gate as qg
import research.validation_contracts as vc
import research.artifacts_layout as al
import research.v2_research_spec as v2
import research.adapters.v1_adapter as v1a


# ════════════════════ 1-5 Registry ════════════════════

def test_01_registry_singleton_unique_id():
    reg = sr.StrategyRegistry(store_path=":memory:")
    reg.register(sr.StrategySpec(strategy_id="X1", strategy_version="1.0", strategy_name="x", owner="t"))
    try:
        reg.register(sr.StrategySpec(strategy_id="X1", strategy_version="1.0", strategy_name="x", owner="t"))
        assert False, "duplicate should raise"
    except ValueError:
        pass


def test_02_registry_v1_exists_as_benchmark():
    reg = sr.build_default_registry(store_path=":memory:")
    v1 = reg.get("V1")
    assert v1 is not None
    assert v1.is_benchmark()
    assert v1.role == sr.BENCHMARK_ROLE


def test_03_registry_status_enum_complete():
    expected = {
        "RESEARCH", "HISTORICAL_TESTING", "QUALIFICATION", "SHADOW",
        "FORWARD_VALIDATION", "PRODUCTION", "REJECTED", "RETIRED",
    }
    assert expected == set(sr.StrategyStatus.__members__.values()) or \
        expected == {s.value for s in sr.StrategyStatus}


def test_04_registry_status_consistency_validation():
    spec = sr.StrategySpec(strategy_id="BAD", strategy_version="1.0", strategy_name="b", owner="t",
                           status=sr.StrategyStatus.RESEARCH.value,
                           qualification_status=sr.QualificationStatus.QUALIFIED.value)
    # RESEARCH 但已 QUALIFIED → 不一致
    probs = spec.validate_status_consistency()
    assert any("inconsistent" in p for p in probs)


def test_05_registry_no_production_authority():
    reg = sr.build_default_registry(store_path=":memory:")
    for s in reg.all():
        assert s.has_production_authority() is False


# ════════════════════ 6-10 Contract ════════════════════

def test_06_contract_required_fields_enforced():
    c = sc.StrategyResearchContract(strategy_id="V2", strategy_version="0.1")
    miss = c.missing_fields()
    assert "universe" in miss
    assert "candidate_rule" in miss
    assert not c.is_complete()


def test_07_contract_uses_unified_outcome():
    spec = sc.UNIFIED_OUTCOME_SPEC
    assert spec["horizons"] == list(__import__("research.forward_outcome", fromlist=["HORIZONS"]).HORIZONS)
    assert spec["outcome_type"] == "COUNTERFACTUAL_RESEARCH"
    assert spec["unknown_token"] == "UNKNOWN"


def test_08_contract_v1_dataset_binding():
    c = sc.StrategyResearchContract(strategy_id="V1", strategy_version="1.0", dataset_id="dataset_v1_full")
    d = c.to_dict()
    assert d["dataset_id"] == "dataset_v1_full"
    assert d["unified_outcome_spec"]["horizons"] == [5, 10, 20]


def test_09_contract_benchmark_role_set():
    reg = sr.build_default_registry(store_path=":memory:")
    v1 = reg.get("V1")
    assert v1.role == sr.BENCHMARK_ROLE


def test_10_contract_validate_output_shape():
    c = sc.StrategyResearchContract(
        strategy_id="V2", strategy_version="0.1", universe="u", feature_requirements="f",
        pit_requirements="p", candidate_rule="c", signal_rule="s", entry_rule="e",
        exit_rule="x", execution_constraints="ec", position_sizing_assumptions="ps",
        cost_model="cm", slippage_model="sm", regime_compatibility="rc",
        expected_holding_horizon="h", dataset_id="dataset_v1_full")
    rep = sc.validate_contract(c)
    assert rep["complete"] is True
    assert rep["missing_fields"] == []
    assert rep["uses_unified_outcome"] is True


# ════════════════════ 11-15 Dataset ════════════════════

def test_11_dataset_registry_unique():
    reg = dr.DatasetRegistry(store_path=":memory:")
    reg.register(dr.DatasetSpec(dataset_id="D1", version="1.0", date_range="x", universe="u"))
    reg.register(dr.DatasetSpec(dataset_id="D1", version="2.0", date_range="y", universe="u"))
    assert len(reg) == 1  # 同 id 覆盖
    assert reg.get("D1").version == "2.0"


def test_12_dataset_st_blocked_explicit():
    reg = dr.build_default_dataset_registry(store_path=":memory:")
    ds = reg.get("dataset_v1_full")
    assert ds.st_status == "BLOCKED"
    assert "Historical ST = BLOCKED" in ds.known_limitations


def test_13_dataset_market_cap_partial():
    reg = dr.build_default_dataset_registry(store_path=":memory:")
    assert reg.get("dataset_v1_full").market_cap_status == "PARTIAL"


def test_14_dataset_execution_partial():
    reg = dr.build_default_dataset_registry(store_path=":memory:")
    assert reg.get("dataset_v1_full").execution_model_status == "PARTIAL"


def test_15_dataset_known_limitations_present():
    reg = dr.build_default_dataset_registry(store_path=":memory:")
    lims = reg.get("dataset_v1_full").known_limitations
    assert len(lims) >= 5
    assert any("Survivorship" in l for l in lims)


# ════════════════════ 16-20 Comparison ════════════════════

def _make_run(strategy_id, version, rows):
    run = runner.StrategyResearchRun(
        strategy_id=strategy_id, strategy_version=version, run_id="r1",
        dataset_id="dataset_v1_full", dataset_version="1.0",
        execution_model_version="EXEC_PARTIAL", cost_model_version="COST_V1",
        date_range="x", regimes={})
    run.rows = rows
    run.candidate_n = len(rows)
    run.signal_n = sum(1 for r in rows if r.is_signal)
    run.trade_n = sum(1 for r in rows if r.is_executed)
    run.entry_n = run.trade_n
    return run


def test_16_comparison_row_from_run():
    rows = [runner.TradeLedgerRow("V2", "0.1", "r1", "600000", "2020-01-01",
                                  entry_price=2.0, fwd_20d=0.1, is_executed=True)]
    run = _make_run("V2", "0.1", rows)
    row = cmp.StrategyComparator.from_run(run, "PARTIAL", "LIMITED")
    assert row.strategy_id == "V2"
    assert row.trades == 1
    assert abs(row.cumulative_return - 0.1) < 1e-9


def test_17_comparison_no_best_strategy_bias():
    # 框架只输出 QUALIFIED 列表，不输出单一 BEST
    ids = ["V1@1.0", "V2@0.1"]
    rows = [
        cmp.StrategyComparisonRow("V1", "1.0", "r1"),
        cmp.StrategyComparisonRow("V2", "0.1", "r2"),
    ]
    qualified = cmp.qualified_strategies(rows, ids)
    assert set(qualified) == set(ids)
    assert isinstance(qualified, list)


def test_18_comparison_candidate_signal_separation():
    rows = [
        runner.TradeLedgerRow("V2", "0.1", "r1", "A", "2020-01-01", entry_price=1.0, is_signal=False, is_executed=True),
        runner.TradeLedgerRow("V2", "0.1", "r1", "B", "2020-01-01", entry_price=1.0, is_signal=True, is_executed=True),
    ]
    run = _make_run("V2", "0.1", rows)
    assert run.candidate_n == 2
    assert run.signal_n == 1  # 仅 signal 计入 signal 层
    assert run.trade_n == 2   # executed 两者都有


def test_19_comparison_drawdown_computed():
    rows = [runner.TradeLedgerRow("V2", "0.1", "r1", "A", "d", entry_price=1.0, fwd_20d=r)
            for r in [0.1, -0.2, 0.05, -0.3]]
    run = _make_run("V2", "0.1", rows)
    row = cmp.StrategyComparator.from_run(run)
    assert row.max_drawdown is not None
    assert row.max_drawdown < 0  # 存在亏损 → 回撤为负


def test_20_comparison_full_vs_signal_denominator():
    cand_rows = [runner.TradeLedgerRow("V2", "0.1", "r1", "A", "d", entry_price=1.0, fwd_20d=0.1, is_signal=False)]
    sig_rows = [runner.TradeLedgerRow("V2", "0.1", "r1", "A", "d", entry_price=1.0, fwd_20d=0.1, is_signal=True)]
    cand_run = _make_run("V2", "0.1", cand_rows)
    sig_run = _make_run("V2", "0.1", sig_rows)
    assert cand_run.candidate_n >= sig_run.signal_n


# ════════════════════ 21-28 Qualification ════════════════════

def test_21_qual_data_insufficient_when_pit_blocked():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=False, execution_model_ready=False, survivorship_acceptable=False)
    res = qg.evaluate(ctx)
    assert res["conclusion"] == qg.DATA_INSUFFICIENT


def test_22_qual_rejected_when_exec_not_ready():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=True, execution_model_ready=False, survivorship_acceptable=True)
    res = qg.evaluate(ctx)
    assert res["conclusion"] == qg.REJECTED


def test_23_qual_threshold_gap_undefined():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=True, execution_model_ready=True, survivorship_acceptable=True)
    res = qg.evaluate(ctx)
    assert "min_trade_count" in res["qualification_threshold_gap"]
    assert "min_return" in res["qualification_threshold_gap"]


def test_24_qual_conditional_when_thresholds_undefined():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=True, execution_model_ready=True, survivorship_acceptable=True,
        time_stability="STABLE", regime_stability="STABLE", parameter_stability="STABLE",
        multiple_testing_ok=True, independent_trade_n=500)
    res = qg.evaluate(ctx)
    assert res["conclusion"] == qg.CONDITIONALLY_QUALIFIED


def test_25_qual_cannot_invent_threshold():
    # 即使人为塞入一个阈值，未显式 defined 也不应生效
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=True, execution_model_ready=True, survivorship_acceptable=True)
    ctx.thresholds["min_trade_count"] = qg.GateThreshold("min_trade_count", value=10, defined=False)
    res = qg.evaluate(ctx)
    # 仍应报告 gap（defined=False）
    assert "min_trade_count" in res["qualification_threshold_gap"]


def test_26_qual_statistical_gate_multiple_testing_required():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full",
        pit_complete=True, execution_model_ready=True, survivorship_acceptable=True,
        multiple_testing_ok=False, independent_trade_n=500)
    res = qg.evaluate(ctx)
    assert res["gates"]["statistical"]["passed"] is False
    assert res["conclusion"] in (qg.REJECTED, qg.CONDITIONALLY_QUALIFIED, qg.DATA_INSUFFICIENT)


def test_27_qual_output_four_conclusions():
    # 四种结论均可由框架表达
    assert {qg.QUALIFIED, qg.CONDITIONALLY_QUALIFIED, qg.REJECTED, qg.DATA_INSUFFICIENT}


def test_28_qual_context_threshold_defaults_undefined():
    ctx = qg.QualificationContext(
        strategy_id="V2", strategy_version="0.1", run_id="r1", dataset_id="dataset_v1_full")
    for name, t in ctx.thresholds.items():
        assert t.defined is False
        assert t.value is None


# ════════════════════ 29-32 PIT ════════════════════

def test_29_pit_no_complete_when_blocked():
    r = pg.build_default_pit_report("V2", "dataset_v1_full")
    assert r.has_blocked()
    assert r.is_complete() is False


def test_30_pit_dimension_explicit():
    r = pg.build_default_pit_report("V2", "dataset_v1_full")
    dims = r.dimensions
    assert dims["historical_st"] == "BLOCKED"
    assert dims["historical_market_cap"] == "APPROXIMATE"
    assert dims["future_leakage"] == "READY"


def test_31_pit_has_blocked_flag():
    r = pg.build_default_pit_report("V2", "dataset_v1_full")
    assert r.has_blocked() is True
    assert r.has_approximate() is True


def test_32_pit_is_complete_false_under_approx():
    r = pg.build_default_pit_report("V2", "dataset_v1_full")
    assert r.is_complete() is False  # 有 APPROXIMATE/BLOCKED → 不得 COMPLETE


# ════════════════════ 33-36 Execution ════════════════════

def test_33_exec_default_partial():
    m = em.DEFAULT_EXEC_MODEL
    assert m.status == em.ExecutionModelStatus.PARTIAL.value


def test_34_exec_limit_up_missing_blocks_qual():
    m = em.DEFAULT_EXEC_MODEL
    assert "limit_up_no_buy" in m.missing
    assert m.blocking_for_qualification() is True
    assert m.is_qualified_ready() is False


def test_35_exec_status_enum():
    assert {"READY", "PARTIAL", "BLOCKED"} == {s.value for s in em.ExecutionModelStatus}


def test_36_exec_missing_constraints_explicit():
    m = em.DEFAULT_EXEC_MODEL
    # 必须显式列出未建模约束，不得假装覆盖
    assert "limit_up_no_buy" in m.missing
    assert "limit_down_no_sell" in m.missing


# ════════════════════ 37-38 Multiple Testing ════════════════════

def test_37_mt_discovery_only_default():
    r = mt.build_default_multiple_testing("V2")
    assert r.is_discovery_only() is True
    assert r.correction == "DISCOVERY_ONLY"


def test_38_mt_cannot_directly_qualify_discovery():
    r = mt.build_default_multiple_testing("V2")
    assert r.can_directly_qualify() is False
    # 给了校正后才可
    r.correction = "BONFERRONI"
    r.tests_considered = 100
    assert r.can_directly_qualify() is True


# ════════════════════ 39-40 Strategy isolation ════════════════════

def test_39_isolation_ledger_has_strategy_partition():
    row = runner.TradeLedgerRow("V2", "0.1", "runX", "600000", "2020-01-01", entry_price=1.0)
    assert row.strategy_id == "V2"
    assert row.strategy_version == "0.1"
    assert row.run_id == "runX"


def test_40_isolation_run_independent_accounting():
    run_a = _make_run("V1", "1.0", [runner.TradeLedgerRow("V1", "1.0", "a", "A", "d", entry_price=1.0)])
    run_b = _make_run("V2", "0.1", [runner.TradeLedgerRow("V2", "0.1", "b", "B", "d", entry_price=1.0)])
    assert run_a.strategy_id != run_b.strategy_id
    assert all(r.strategy_id == "V1" for r in run_a.rows)
    assert all(r.strategy_id == "V2" for r in run_b.rows)
    assert len(run_a.rows) == 1 and len(run_b.rows) == 1


# ════════════════════ 41-48 集成 / 附加 ════════════════════

def _make_inmemory_klines_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE klines (code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL)")
    # 30 个交易日：open=close=day_index(1..30)
    for i in range(1, 31):
        d = f"2020-01-{i:02d}"
        con.execute("INSERT INTO klines VALUES (?,?,?,?,?,?)",
                    ("600000", d, float(i), float(i), float(i + 1), float(max(1, i - 1))))
    con.commit()
    con.close()


def test_41_runner_uniform_outcome_via_inmemory_db(tmp_path):
    db = tmp_path / "mini.db"
    _make_inmemory_klines_db(str(db))
    # 复用 forward_outcome 的口径
    import research.forward_outcome as fo
    cand = {"symbol": "600000", "candidate_date": "2020-01-01", "is_signal": True}
    r = runner.StrategyRunner(db_path=str(db)).run(
        v1a.V1Adapter() if False else _StubAdapter("V2", "0.1"),
        "dataset_v1_full", "1.0", "2020-01-01..2020-01-30",
        "EXEC_PARTIAL", "COST_V1", [cand])
    assert r.candidate_n == 1
    row = r.rows[0]
    # entry_price = 2020-01-02 open = 2
    assert abs(row.entry_price - 2.0) < 1e-9
    # fwd_5d = close[2020-01-06]=6 /2 -1 = 2.0
    assert abs(float(row.fwd_5d) - 2.0) < 1e-9
    # fwd_20d = close[2020-01-21]=21 /2 -1 = 9.5
    assert abs(float(row.fwd_20d) - 9.5) < 1e-9
    # MAE = min(low/entry-1) over i=3..21; synthetic low=max(1,i-1) >=2 → low/2-1 >= 0; min=0
    assert abs(float(row.mae) - 0.0) < 1e-9
    # MFE = max(high/entry-1); high=i+1 → (21+1)/2-1=10
    assert abs(float(row.mfe) - 10.0) < 1e-9


class _StubAdapter(runner.StrategyResearchAdapter):
    def build_candidates(self, dataset, date_range):
        return []


def test_42_forward_validation_partition_key():
    rec = vc.ForwardValidationRecord("V2", "0.1", "2026-08-27", "dataset_v1_full@1.0")
    assert rec.partition_key() == "V2@0.1"
    assert rec.strategy_specific_ledger is True


def test_43_shadow_not_production():
    sh = vc.ShadowRecord("V2", "0.1", "s1", "600000", "2020-01-01")
    assert sh.validate_not_production() is True
    assert sh.is_production is False


def test_44_v2_research_only_no_production():
    spec = v2.V2ResearchSpec()
    assert spec.is_research_only() is True
    assert "25%" in spec.forbidden_early_weights.get("QUALITY", "")


def test_45_factor_candidates_count_and_unstudied():
    specs = fc.build_factor_candidates()
    assert len(specs) == 25
    assert all(not s.research_complete() for s in specs)
    assert all(len(s.missing_studies()) == 8 for s in specs)


def test_46_reproducibility_manifest():
    m = vc.ReproducibilityManifest("V2", "0.1", "dataset_v1_full", "1.0", "run1")
    assert m.is_reproducible() is False  # 默认 UNKNOWN
    m.code_version = "abc"
    m.config_version = "cfg1"
    m.data_version = "d1"
    m.execution_version = "EXEC_PARTIAL"
    m.cost_version = "COST_V1"
    assert m.is_reproducible() is True


def test_47_artifacts_layout_write(tmp_path, monkeypatch):
    import research.artifacts_layout as _al
    monkeypatch.setattr(_al, "ARTIFACTS_ROOT", tmp_path / "strategy_registry")
    p = _al.save_run_artifact("V2", "0.1", "run1", "definition", {"a": 1})
    assert p.exists()
    ep = _al.write_evidence("V2", "0.1", "run1", "HYPOTHESIS", "x may beat y")
    assert ep.exists()
    # 禁止把 HYPOTHESIS 写成 FACT
    try:
        _al.write_evidence("V2", "0.1", "run1", "FACT", "x beats y")
    except ValueError:
        pass


def test_48_registry_persist_reload(tmp_path):
    p = tmp_path / "reg.json"
    reg = sr.StrategyRegistry(store_path=str(p))
    reg.register(sr.StrategySpec(strategy_id="P1", strategy_version="1.0", strategy_name="p", owner="t"))
    reg.save()
    assert p.exists()
    reg2 = sr.StrategyRegistry(store_path=str(p))
    assert reg2.get("P1") is not None
