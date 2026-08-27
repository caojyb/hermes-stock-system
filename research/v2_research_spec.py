#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/v2_research_spec.py — Phase 9-A 八/二十七/二十八：V2 第一轮研究定义
================================================================================

本阶段只建立 V2_RESEARCH_SPEC（研究假设 + 研究顺序），不形成 production rule。

研究假设（HYPOTHESIS，不是 FACT，section 二十七）：
  "Quality + Growth + Momentum + Regime + Risk 可能比单纯极端成交量过滤
   （V1）具有更好的跨时期/跨 Regime 稳定性。"

禁止（section 二十八）：
  * 一开始就 100 分模型
  * 手工权重（如 Quality 25% / Momentum 20% / Growth 15%）

第一候选 V2 研究顺序（section 二十八）：
  Step1 Quality → Step2 Growth → Step3 Momentum → Step4 Volume/Capital →
  Step5 Valuation → Step6 Factor correlation → Step7 Incremental value →
  Step8 Candidate construction → Step9 Signal construction →
  Step10 Execution model → Step11 Walk-forward → Step12 Qualification
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# V2 研究假设（明确为 HYPOTHESIS 而非 FACT）
V2_HYPOTHESIS = (
    "Quality + Growth + Momentum + Regime + Risk 组合策略，可能比单纯极端成交量过滤 "
    "(V1 Top3) 具有更好的跨时期 / 跨 Regime 稳定性。此为前提假设，需在 Phase 9-B 因子研究中验证。"
)

# 研究顺序（section 二十八），禁止跳步
V2_RESEARCH_STEPS = [
    "Step1 Quality factors 独立研究",
    "Step2 Growth factors 独立研究",
    "Step3 Momentum factors 独立研究",
    "Step4 Volume / Capital factors 独立研究",
    "Step5 Valuation factors 独立研究",
    "Step6 Factor correlation（相关性，避免重复）",
    "Step7 Incremental value（增量价值）",
    "Step8 Candidate construction（候选构建）",
    "Step9 Signal construction（信号构建）",
    "Step10 Execution model（执行模型）",
    "Step11 Walk-forward（滚动/扩展）",
    "Step12 Qualification（资格认证）",
]

# 禁止在第一轮直接设定的主观权重（section 八）
FORBIDDEN_EARLY_WEIGHTS = {
    "QUALITY": "25%",
    "MOMENTUM": "20%",
    "GROWTH": "15%",
}


@dataclass
class V2ResearchSpec:
    strategy_id: str = "V2"
    strategy_version: str = "0.1-research"
    status: str = "RESEARCH"
    research_only: bool = True
    hypothesis: str = V2_HYPOTHESIS
    research_steps: list = field(default_factory=lambda: list(V2_RESEARCH_STEPS))
    forbidden_early_weights: dict = field(default_factory=lambda: dict(FORBIDDEN_EARLY_WEIGHTS))
    dataset_id: str = "dataset_v1_full"

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "status": self.status,
            "research_only": self.research_only,
            "hypothesis": self.hypothesis,
            "research_steps": self.research_steps,
            "forbidden_early_weights": self.forbidden_early_weights,
            "dataset_id": self.dataset_id,
        }

    def is_research_only(self) -> bool:
        """V2 当前仅允许 RESEARCH_ONLY，不得形成 production rule。"""
        return self.research_only
