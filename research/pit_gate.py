#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/pit_gate.py — Phase 9-A 十三：PIT Integrity Gate
===========================================================

所有历史策略都必须记录 PIT_STATUS。允许：
  READY / PARTIAL / BLOCKED

检查维度：
  - future leakage（未来信息泄漏）
  - survivorship（幸存者偏差）
  - historical market cap（历史市值）
  - historical ST（历史 ST）
  - financial effective date（财报生效日）
  - signal timestamp（信号时间戳）
  - trade timestamp（交易时间戳）

当前已知（Phase 9-A 十三/三十）：
  Historical ST           = BLOCKED
  Market Cap PIT          = 部分近似（APPROXIMATE）

禁止简单输出 PIT_COMPLETE。必须精确记录：
  哪些因子完整 / 哪些 APPROXIMATE / 哪些 UNKNOWN / 哪些 BLOCKED。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PITStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


# PIT 维度
PIT_DIMENSIONS = [
    "future_leakage",
    "survivorship",
    "historical_market_cap",
    "historical_st",
    "financial_effective_date",
    "signal_timestamp",
    "trade_timestamp",
]

# 每个维度的默认质量（基于 Phase 9-A 已知缺口）
DEFAULT_DIMENSION_QUALITY = {
    "future_leakage": "READY",          # 现有研究模块严格 PIT（forward_outcome/candidate_pit/regime_pit）
    "survivorship": "LIMITED",          # 退市股未纳入
    "historical_market_cap": "APPROXIMATE",  # 部分近似
    "historical_st": "BLOCKED",         # Historical ST BLOCKED
    "financial_effective_date": "APPROXIMATE",
    "signal_timestamp": "READY",
    "trade_timestamp": "READY",
}


@dataclass
class PITReport:
    """某策略/某研究的 PIT 完整性报告。"""
    strategy_id: str
    dataset_id: str
    overall: str = PITStatus.PARTIAL.value
    dimensions: dict = field(default_factory=lambda: dict(DEFAULT_DIMENSION_QUALITY))
    notes: str = ""

    def get(self, dim: str) -> str:
        return self.dimensions.get(dim, "UNKNOWN")

    def has_blocked(self) -> bool:
        return any(v == PITStatus.BLOCKED.value for v in self.dimensions.values())

    def has_approximate(self) -> bool:
        return any(v in ("APPROXIMATE", "LIMITED") for v in self.dimensions.values())

    def is_complete(self) -> bool:
        """禁止返回 True 除非全部 READY。"""
        return all(v == PITStatus.READY.value for v in self.dimensions.values())

    def summary(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "overall": self.overall,
            "is_complete": self.is_complete(),
            "has_blocked": self.has_blocked(),
            "has_approximate": self.has_approximate(),
            "dimensions": dict(self.dimensions),
            "notes": self.notes,
        }


def build_default_pit_report(strategy_id: str, dataset_id: str) -> PITReport:
    return PITReport(
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        overall=PITStatus.PARTIAL.value,
        dimensions=dict(DEFAULT_DIMENSION_QUALITY),
        notes="基于已知缺口：Historical ST=BLOCKED, Market Cap=APPROXIMATE, Survivorship=LIMITED。",
    )
