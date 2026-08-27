#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/strategy_contract.py — Phase 9-A 五：统一 Strategy Research Contract
=============================================================================

统一定义每个策略必须提供（section 5 的 14 项）：
  1. strategy identity
  2. universe
  3. feature requirements
  4. PIT requirements
  5. candidate rule
  6. signal rule
  7. entry rule
  8. exit rule
  9. execution constraints
 10. position sizing assumptions
 11. cost model
 12. slippage model
 13. regime compatibility
 14. expected holding horizon

禁止：每个策略自己定义一套 outcome 计算。
统一复用现有 forward_outcome / MAE / MFE / lifecycle semantics（见 research/forward_outcome.py）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# 复用现有 outcome 语义（不修改）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import research.forward_outcome as forward_outcome  # noqa: E402

# 契约必填字段（section 5）
REQUIRED_FIELDS = [
    "strategy_id",
    "strategy_version",
    "universe",
    "feature_requirements",
    "pit_requirements",
    "candidate_rule",
    "signal_rule",
    "entry_rule",
    "exit_rule",
    "execution_constraints",
    "position_sizing_assumptions",
    "cost_model",
    "slippage_model",
    "regime_compatibility",
    "expected_holding_horizon",
]

# 统一 outcome 口径（所有策略一致，禁止各自定义）
UNIFIED_OUTCOME_SPEC = {
    "horizons": list(forward_outcome.HORIZONS),     # (5, 10, 20)
    "max_horizon": forward_outcome.MAX_HORIZON,     # 20
    "entry_time": "T+1 open",
    "mae_mfe_window": "(T+1, T+20]",
    "outcome_type": forward_outcome.OUTCOME_TYPE,   # COUNTERFACTUAL_RESEARCH
    "unknown_token": forward_outcome.UNKNOWN,       # UNKNOWN（禁止填 0）
}


@dataclass
class StrategyResearchContract:
    """一个策略的研究契约。所有字段为字符串描述（研究层的可解释定义）。"""
    strategy_id: str
    strategy_version: str
    universe: str = ""
    feature_requirements: str = ""
    pit_requirements: str = ""
    candidate_rule: str = ""
    signal_rule: str = ""
    entry_rule: str = ""
    exit_rule: str = ""
    execution_constraints: str = ""
    position_sizing_assumptions: str = ""
    cost_model: str = ""
    slippage_model: str = ""
    regime_compatibility: str = ""
    expected_holding_horizon: str = ""
    dataset_id: Optional[str] = None   # 绑定数据集（公平比较）

    def to_dict(self) -> dict:
        d = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "dataset_id": self.dataset_id,
            "universe": self.universe,
            "feature_requirements": self.feature_requirements,
            "pit_requirements": self.pit_requirements,
            "candidate_rule": self.candidate_rule,
            "signal_rule": self.signal_rule,
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "execution_constraints": self.execution_constraints,
            "position_sizing_assumptions": self.position_sizing_assumptions,
            "cost_model": self.cost_model,
            "slippage_model": self.slippage_model,
            "regime_compatibility": self.regime_compatibility,
            "expected_holding_horizon": self.expected_holding_horizon,
            "unified_outcome_spec": UNIFIED_OUTCOME_SPEC,
        }
        return d

    def missing_fields(self) -> list[str]:
        """返回未填写的必填字段。"""
        miss = []
        for f in REQUIRED_FIELDS:
            if not getattr(self, f, "").strip():
                miss.append(f)
        return miss

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0


def validate_contract(contract: StrategyResearchContract) -> dict:
    """校验契约完整性 + outcome 口径一致性。返回报告。"""
    missing = contract.missing_fields()
    return {
        "strategy_id": contract.strategy_id,
        "strategy_version": contract.strategy_version,
        "complete": len(missing) == 0,
        "missing_fields": missing,
        "outcome_spec": UNIFIED_OUTCOME_SPEC,
        "uses_unified_outcome": True,
    }
