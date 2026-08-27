#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/artifacts_layout.py — Phase 9-A 三十四：Research Output 目录结构
=========================================================================

每次研究：
  research/artifacts/strategy_registry/<strategy_id>/<version>/<run_id>/

保存（section 34）：
  definition / universe / factors / candidates / signals / trades /
  outcomes / matrix / robustness / stress / qualification

注意：artifacts/ 整体被 .gitignore 忽略（避免大二进制进 git）。
registry 索引（json）本身在 research/ 根目录，可 git 跟踪。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# artifacts 根（与既有的 research/artifacts 一致）
ARTIFACTS_ROOT = Path(__file__).resolve().parent / "artifacts" / "strategy_registry"

# 每个 run 的子目录内容约定
RUN_ARTIFACT_KEYS = [
    "definition", "universe", "factors", "candidates", "signals",
    "trades", "outcomes", "matrix", "robustness", "stress", "qualification",
]

# 三层证据（section 31）：FACT / EVIDENCE / HYPOTHESIS
EVIDENCE_LAYERS = ["FACT", "EVIDENCE", "HYPOTHESIS"]


def run_dir(strategy_id: str, version: str, run_id: str) -> Path:
    d = ARTIFACTS_ROOT / strategy_id / version / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run_artifact(strategy_id: str, version: str, run_id: str,
                      key: str, content, as_json: bool = True) -> Path:
    """将单个 artifact 写入对应 run 目录。"""
    if key not in RUN_ARTIFACT_KEYS and key not in EVIDENCE_LAYERS:
        raise ValueError(f"unknown artifact key: {key}")
    d = run_dir(strategy_id, version, run_id)
    if isinstance(content, (dict, list)) or as_json:
        import json
        p = d / f"{key}.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2, default=str)
    else:
        p = d / f"{key}.txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(content))
    return p


def write_evidence(strategy_id: str, version: str, run_id: str, layer: str, text: str) -> Path:
    """写入 FACT / EVIDENCE / HYPOTHESIS 三层证据之一（禁止把 HYPOTHESIS 写成 FACT）。"""
    if layer not in EVIDENCE_LAYERS:
        raise ValueError(f"invalid evidence layer: {layer} (need {EVIDENCE_LAYERS})")
    return save_run_artifact(strategy_id, version, run_id, layer, text, as_json=False)
