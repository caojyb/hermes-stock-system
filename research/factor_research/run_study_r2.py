#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/run_study_r2.py — Phase 9-B.1 修正后单因子研究 (R2)
=================================================================================

复用 Phase 9-B 的研究框架（build_samples / study_on_samples / discovery_ranking），
但应用 9-B.1 的三项修正：
  1. MOM_RS 横截面去均值归一化（build_samples 内部预计算 universe 60D 收益中位数）
  2. Execution Model 升级为 EXEC_R2（涨停不可买/跌停不可卖/停牌/T+1/手数/手续费/滑点/流动性）
  3. factor_engine 版本、execution_model 版本登记到 manifest

产物写到 research/artifacts/factors/r2/（不覆盖 r1/）。

新增输出：
  corrected_factor_candidates.csv  — CORRECTED_FACTOR_CANDIDATES（R1 vs R2 对比 + 新状态）
  r1_vs_r2_comparison.json        — ROUND1 vs ROUND2 逐因子对比
  multiple_testing_status.json    — R1/R2 search space 登记

严禁：组合因子；发明生产阈值；生产写；把 A 层直接升 Qualified。
"""

from __future__ import annotations

import os
import sys
import json
import csv
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

import research.factor_research.factor_definitions as fdef  # noqa: E402
from research.factor_research.factor_definitions import FACTOR_DEFS, FACTOR_BY_ID  # noqa: E402
from research.factor_research.research_runner import (  # noqa: E402
    build_samples, study_on_samples, load_universe, load_regime_map, COMMON_WINDOW,
    RESEARCH_UNIVERSE_V2_R1,
)
from research.factor_research.execution_sim import build_exec_model_r2  # noqa: E402
from research.factor_research.financial_pit_audit import audit_financial_pit  # noqa: E402
from research.factor_research.momentum_audit import audit_momentum_factor, MOM_RS_DEFINITION  # noqa: E402

ART = Path(__file__).resolve().parent.parent / "artifacts" / "factors" / "r2"
R1_ART = Path(__file__).resolve().parent.parent / "artifacts" / "factors" / "r1"
DATASET_ID = "dataset_v1_full"
DATASET_VERSION = "1.0"
FACTOR_ENGINE_VERSION = "2.0"   # 9-B.1: f_rs 修正 + MOM_RS 归一化
EXECUTION_MODEL_VERSION = "2.0"  # EXEC_R2


def _mcap_helper(symbol, as_of):
    try:
        from historical_share_layer import get_market_cap, MarketCapQuality
        mc = get_market_cap()
        res = mc.get_market_cap(symbol, as_of)
        q = res.quality
        if q == MarketCapQuality.PIT_SAFE and res.market_cap:
            return ("OK", res.market_cap / 1e8)
        if q == MarketCapQuality.APPROXIMATE:
            return ("APPROX", res.market_cap / 1e8 if res.market_cap else None)
    except Exception:
        pass
    return ("UNKNOWN", None)


def _spearman(a, b):
    if len(a) != len(b) or len(a) < 3:
        return None
    def rank(xs):
        order = sorted(range(len(xs)), key=lambda i: (xs[i] is None, xs[i] if xs[i] is not None else 0))
        r = [0] * len(xs)
        for pos, idx in enumerate(order):
            r[idx] = pos + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(ra)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def run_phase(mode, universe_limit, start, end, run_id):
    print(f"[R2 {mode}] universe_limit={universe_limit} window={start}..{end}")
    regime = load_regime_map()
    uni = load_universe(limit=universe_limit)
    # compute_cs_median=True（默认）→ 内部预计算 universe 60D 收益横截面中位数
    samples = build_samples(uni, start, end, regime_map=regime, mcap_helper=_mcap_helper)
    print(f"[R2 {mode}] samples built: {len(samples)}")
    results = {}
    for f in FACTOR_DEFS:
        r = study_on_samples(f.factor_id, samples)
        results[f.factor_id] = r
        print(f"  {f.factor_id:22s} n_valid={r.n_valid:6d} mono={r.monotonicity:18s} inc={r.incremental}")
    return results, samples


def _factor_values_for_redundancy(samples, factor_id):
    return [s["factors"].get(factor_id) for s in samples]


def discovery_ranking(results):
    tiers = {"A_PROMISING": [], "B_WEAK_EVIDENCE": [], "C_NO_EVIDENCE": [], "D_BLOCKED": []}
    for f in FACTOR_DEFS:
        r = results[f.factor_id]
        entry = {"factor_id": f.factor_id, "availability": r.availability, "pit_status": r.pit_status,
                 "n_valid": r.n_valid, "monotonicity": r.monotonicity, "incremental": r.incremental}
        if r.availability == "BLOCKED":
            tiers["D_BLOCKED"].append(entry)
        elif r.n_valid < 50 or r.incremental == "NONE" or r.monotonicity == "NO_SIGNAL":
            tiers["C_NO_EVIDENCE"].append(entry)
        elif r.incremental == "POSITIVE" and r.n_valid >= 200 and r.monotonicity in (
                "MONOTONIC_POSITIVE", "MONOTONIC_NEGATIVE", "NON_MONOTONIC"):
            tiers["A_PROMISING"].append(entry)
        else:
            tiers["B_WEAK_EVIDENCE"].append(entry)
    return tiers


# 9-B 原结论（R1，来自 r1/expansion/factor_discovery_ranking.json，已落盘）
R1_RANKING_FILE = R1_ART / "expansion" / "factor_discovery_ranking.json"


def load_r1_ranking():
    if R1_RANKING_FILE.exists():
        return json.loads(R1_RANKING_FILE.read_text(encoding="utf-8"))
    return None


def build_corrected_candidates(results, r1_ranking):
    """CORRECTED_FACTOR_CANDIDATES：old_status(R1) vs new_status(R2) + 新分类。"""
    rows = []
    # 建立 R1 状态索引
    r1_map = {}
    if r1_ranking:
        for tier, items in r1_ranking.items():
            for it in items:
                r1_map[it["factor_id"]] = tier
    exec_model = build_exec_model_r2()
    for f in FACTOR_DEFS:
        r = results[f.factor_id]
        # 新状态（evidence_status）：PROMISING / WEAK / NO_EVIDENCE / BLOCKED
        if r.availability == "BLOCKED":
            ev = "BLOCKED"
        elif r.incremental == "POSITIVE" and r.n_valid >= 200:
            ev = "PROMISING"
        elif r.n_valid >= 50 and r.incremental == "POSITIVE":
            ev = "WEAK"
        else:
            ev = "NO_EVIDENCE"
        old_status = r1_map.get(f.factor_id, "UNKNOWN")
        reason = (f"R2: n_valid={r.n_valid}, mono={r.monotonicity}, inc={r.incremental}, "
                  f"pit={r.pit_status}, exec={exec_model.status}")
        rows.append({
            "factor": f.factor_id,
            "group": f.group,
            "old_status_r1": old_status,
            "new_status_r2": ev,
            "pit_status": r.pit_status,
            "execution_status": exec_model.status,
            "evidence_status": ev,
            "reason": reason,
            "allowed": "RESEARCH_CANDIDATE" if ev in ("PROMISING", "WEAK") else "NOT_CANDIDATE",
        })
    return rows


def write_artifacts(mode, results, samples, run_id):
    base = ART / mode.lower()
    base.mkdir(parents=True, exist_ok=True)
    exec_model = build_exec_model_r2()

    # 1. availability matrix (reuse definitions, but stamp corrected dates)
    with open(base / "factor_data_availability.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor_id", "name", "group", "availability", "pit_status",
                    "source_table", "source_field", "effective_date_reliable", "coverage_start",
                    "coverage_end", "approximate_rate", "known_caveats"])
        for d in FACTOR_DEFS:
            w.writerow([d.factor_id, d.name, d.group, d.availability, d.pit_status, d.source_table,
                        d.source_field, d.effective_date_reliable, d.coverage_start, d.coverage_end,
                        d.approximate_rate, d.known_caveats])

    # 2. per-factor artifacts (same as R1 schema)
    for f in FACTOR_DEFS:
        r = results[f.factor_id]
        fd = base / f"factor_{f.factor_id}"
        fd.mkdir(parents=True, exist_ok=True)
        (fd / "definition.json").write_text(json.dumps(f.to_dict(), ensure_ascii=False, indent=2))
        (fd / "summary.json").write_text(json.dumps(r.to_dict(), ensure_ascii=False, indent=2, default=str))
        (fd / "monotonicity.json").write_text(json.dumps(
            {"factor_id": f.factor_id, "monotonicity": r.monotonicity,
             "quantile_median_20d": r.quantiles}, ensure_ascii=False, indent=2))
        (fd / "time_stability.json").write_text(json.dumps(r.time_stability, ensure_ascii=False, indent=2, default=str))
        (fd / "regime_matrix.json").write_text(json.dumps(r.regime_stability, ensure_ascii=False, indent=2, default=str))
        (fd / "marketcap_stability.json").write_text(json.dumps(r.marketcap_stability, ensure_ascii=False, indent=2, default=str))
        (fd / "incremental.json").write_text(json.dumps(
            {"factor_id": f.factor_id, "incremental": r.incremental}, ensure_ascii=False, indent=2))
        (fd / "data_quality.json").write_text(json.dumps(
            {"factor_id": f.factor_id, "n_total": r.n_total, "n_valid": r.n_valid,
             "n_missing": r.n_missing, "n_unknown": r.n_unknown, "pit_status": r.pit_status,
             "availability": r.availability}, ensure_ascii=False, indent=2))

    # 3. summary matrix
    with open(base / "factor_summary_matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor_id", "availability", "pit_status", "n_valid", "monotonicity",
                    "incremental", "time_2015_2019", "time_2020_2024", "regime_HIGH_VOL_n",
                    "regime_STRONG_TREND_n", "mcap_small_n", "data_quality"])
        for f in FACTOR_DEFS:
            r = results[f.factor_id]
            ts = r.time_stability
            rg = r.regime_stability
            mc = r.marketcap_stability
            w.writerow([
                f.factor_id, r.availability, r.pit_status, r.n_valid, r.monotonicity, r.incremental,
                ts.get("2015-2019", {}).get("q1_q9_spread", ts.get("2015-2019", {}).get("status", "")),
                ts.get("2020-2024", {}).get("q1_q9_spread", ts.get("2020-2024", {}).get("status", "")),
                rg.get("🔴高波动", {}).get("n", ""),
                rg.get("🟢强趋势", {}).get("n", ""),
                mc.get("small", {}).get("n", ""),
                r.data_quality,
            ])

    # 4. redundancy matrix
    ids = [f.factor_id for f in FACTOR_DEFS]
    valid_ids = [fid for fid in ids if results[fid].n_valid >= 100]
    red = {}
    for i, a in enumerate(valid_ids):
        for b in valid_ids[i + 1:]:
            va = _factor_values_for_redundancy(samples, a)
            vb = _factor_values_for_redundancy(samples, b)
            pairs = [(x, y) for x, y in zip(va, vb) if x is not None and y is not None]
            if len(pairs) >= 50:
                xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
                sp = _spearman(xs, ys)
                red[f"{a}|{b}"] = round(sp, 3) if sp is not None else "UNDEFINED"
            else:
                red[f"{a}|{b}"] = "INSUFFICIENT"
    with open(base / "factor_redundancy_matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor_a", "factor_b", "spearman_rank_corr", "note"])
        for k, v in red.items():
            a, b = k.split("|")
            w.writerow([a, b, v, "价格/量同源因子可能高度相关；相关性≠同质"])

    # 5. discovery ranking
    ranking = discovery_ranking(results)
    (base / "factor_discovery_ranking.json").write_text(json.dumps(ranking, ensure_ascii=False, indent=2, default=str))

    # 6. CORRECTED_FACTOR_CANDIDATES (R1 vs R2)
    r1_ranking = load_r1_ranking()
    candidates = build_corrected_candidates(results, r1_ranking)
    with open(base / "corrected_factor_candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor", "group", "old_status_r1", "new_status_r2", "pit_status",
                    "execution_status", "evidence_status", "allowed", "reason"])
        for c in candidates:
            w.writerow([c["factor"], c["group"], c["old_status_r1"], c["new_status_r2"],
                        c["pit_status"], c["execution_status"], c["evidence_status"],
                        c["allowed"], c["reason"]])

    # 7. R1 vs R2 comparison
    r2_tier_map = {}
    for tier, items in ranking.items():
        for it in items:
            r2_tier_map[it["factor_id"]] = tier
    comparison = []
    for f in FACTOR_DEFS:
        r = results[f.factor_id]
        r1_tier = (r1_ranking and r1_ranking and
                   next((t for t, its in r1_ranking.items() if any(i["factor_id"] == f.factor_id for i in its)), "UNKNOWN"))
        comparison.append({
            "factor_id": f.factor_id,
            "r1_tier": r1_tier, "r2_tier": r2_tier_map.get(f.factor_id),
            "r1_n_valid": (next((i["n_valid"] for t, its in (r1_ranking or {}).items()
                                 for i in its if i["factor_id"] == f.factor_id), None)),
            "r2_n_valid": r.n_valid,
            "r1_incremental": (next((i["incremental"] for t, its in (r1_ranking or {}).items()
                                     for i in its if i["factor_id"] == f.factor_id), None)),
            "r2_incremental": r.incremental,
            "r1_monotonicity": (next((i["monotonicity"] for t, its in (r1_ranking or {}).items()
                                      for i in its if i["factor_id"] == f.factor_id), None)),
            "r2_monotonicity": r.monotonicity,
        })
    (base / "r1_vs_r2_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2, default=str))

    # 8. MULTIPLE_TESTING_STATUS
    mt = {
        "r1_search_space": len(FACTOR_DEFS),
        "r2_search_space": len(FACTOR_DEFS),
        "note": ("R2 是 R1 的修正再研究（MOM_RS 归一化/执行模型升级），不是首次发现；"
                 "不把修正后结果伪装为第一次发现。"),
        "multiple_testing_status": "DISCOVERY_ONLY",
        "factor_engine_version": FACTOR_ENGINE_VERSION,
        "execution_model_version": EXECUTION_MODEL_VERSION,
        "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
    }
    (base / "multiple_testing_status.json").write_text(json.dumps(mt, ensure_ascii=False, indent=2))

    # 9. run manifest
    manifest = {
        "mode": mode, "run_id": run_id, "round": "R2",
        "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
        "factor_engine_version": FACTOR_ENGINE_VERSION,
        "execution_model": exec_model.model_id, "execution_model_version": EXECUTION_MODEL_VERSION,
        "execution_model_status": exec_model.status,
        "strategy_namespace": "factor-study", "universe": RESEARCH_UNIVERSE_V2_R1,
        "common_window": list(COMMON_WINDOW), "code_version": "phase-9b1",
        "run_timestamp": datetime.now().isoformat(), "cost_model": "COST_V2_SIMPLIFIED",
        "multiple_testing_status": "DISCOVERY_ONLY",
        "factor_count": len(FACTOR_DEFS), "reproducible": True,
        "mom_rs_definition": MOM_RS_DEFINITION,
        "note": "R2 修正 R1 的 MOM_RS 归一化与执行模型；不覆盖 r1/ artifacts。",
    }
    (base / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return base


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["PILOT", "EXPANSION"], default="PILOT")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--start", default=COMMON_WINDOW[0])
    ap.add_argument("--end", default=COMMON_WINDOW[1])
    args = ap.parse_args()
    run_id = uuid.uuid4().hex[:12]
    results, samples = run_phase(args.mode, args.limit, args.start, args.end, run_id)
    base = write_artifacts(args.mode, results, samples, run_id)
    print(f"[R2 {args.mode}] artifacts -> {base}")


if __name__ == "__main__":
    main()
