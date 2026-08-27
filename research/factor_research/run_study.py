#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/run_study.py — Phase 9-B 编排：Pilot + Expansion + Artifacts
=======================================================================================

PILOT：小 universe（12 只）× 3 年 → 验证公式/PIT/outcome/artifact/reproducibility。
EXPANSION：扩 universe（bounded）+ 全 COMMON_WINDOW → 正式单因子研究。

产物（research/artifacts/factors/r1/）：
  factor_data_availability.csv
  factor_<id>/... (per-factor artifacts)
  factor_summary_matrix.csv
  factor_redundancy_matrix.csv
  factor_discovery_ranking.json
  run_manifest.json

严禁：Pilot 结果选因子；禁止组合因子；禁止生产写；禁止发明阈值。
"""

from __future__ import annotations

import os
import sys
import json
import csv
import uuid
import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

import research.factor_research.factor_definitions as fdef  # noqa: E402
from research.factor_research.factor_definitions import FACTOR_DEFS, FACTOR_BY_ID  # noqa: E402
from research.factor_research.research_runner import (  # noqa: E402
    build_samples, study_on_samples, load_universe, load_regime_map, COMMON_WINDOW,
    RESEARCH_UNIVERSE_V2_R1,
)
from research.factor_research.factor_engine import compute_factor  # noqa: E402

ART = Path(__file__).resolve().parent.parent / "artifacts" / "factors" / "r1"
DATASET_ID = "dataset_v1_full"
DATASET_VERSION = "1.0"


def _mcap_helper(symbol, as_of):
    """市值 PIT（APPROXIMATE 标注）。"""
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
    """简化秩相关（基于分位秩）。"""
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


def run_phase(mode: str, universe_limit: int, start: str, end: str, run_id: str):
    """mode: 'PILOT' | 'EXPANSION'。返回 (results_dict, samples)。"""
    print(f"[{mode}] universe_limit={universe_limit} window={start}..{end}")
    regime = load_regime_map()
    uni = load_universe(limit=universe_limit)
    samples = build_samples(uni, start, end, regime_map=regime, mcap_helper=_mcap_helper)
    print(f"[{mode}] samples built: {len(samples)}")

    results = {}
    for f in FACTOR_DEFS:
        r = study_on_samples(f.factor_id, samples)
        results[f.factor_id] = r
        print(f"  {f.factor_id:22s} n_valid={r.n_valid:6d} mono={r.monotonicity:18s} inc={r.incremental}")
    return results, samples


def _factor_values_for_redundancy(samples, factor_id):
    return [s["factors"].get(factor_id) for s in samples]


def write_artifacts(mode, results, samples, run_id):
    base = ART / mode.lower()
    base.mkdir(parents=True, exist_ok=True)

    # 1. availability matrix
    with open(base / "factor_data_availability.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor_id", "name", "group", "availability", "pit_status",
                    "source_table", "source_field", "effective_date_reliable", "coverage_start",
                    "coverage_end", "approximate_rate", "known_caveats"])
        for d in FACTOR_DEFS:
            w.writerow([d.factor_id, d.name, d.group, d.availability, d.pit_status, d.source_table,
                        d.source_field, d.effective_date_reliable, d.coverage_start, d.coverage_end,
                        d.approximate_rate, d.known_caveats])

    # 2. per-factor artifacts
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
    # 仅对 RESEARCHABLE + 有有效样本的价格/量因子做相关（财务因子缺值多，标 UNDEFINED）
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

    # 6. run manifest
    manifest = {
        "mode": mode, "run_id": run_id, "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
        "strategy_namespace": "factor-study", "universe": RESEARCH_UNIVERSE_V2_R1,
        "common_window": list(COMMON_WINDOW), "code_version": "phase-9b",
        "run_timestamp": datetime.now().isoformat(), "execution_model": "EXEC_PARTIAL",
        "cost_model": "COST_V1", "multiple_testing_status": "DISCOVERY_ONLY",
        "factor_count": len(FACTOR_DEFS), "reproducible": True,
    }
    (base / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return base


def discovery_ranking(results):
    """分 A/B/C/D 层，不输出单 BEST_FACTOR。"""
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
    print(f"[{args.mode}] artifacts -> {base}")
    print(f"[{args.mode}] discovery ranking -> {base / 'factor_discovery_ranking.json'}")


if __name__ == "__main__":
    main()
