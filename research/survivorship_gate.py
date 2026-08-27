#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/survivorship_gate.py — Phase 9-A 十四：Survivorship Gate
=================================================================

策略必须记录 UNIVERSE_BIAS_STATUS：
  CLEAN   — 无幸存者偏差（含退市股）
  LIMITED — 部分覆盖
  BLOCKED — 未覆盖

如果研究没有退市股，不能宣称 SURVIVORSHIP_FREE。
尤其小盘策略，必须明确 delisted coverage。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class UniverseBiasStatus(str, Enum):
    CLEAN = "CLEAN"
    LIMITED = "LIMITED"
    BLOCKED = "BLOCKED"


@dataclass
class SurvivorshipReport:
    strategy_id: str
    dataset_id: str
    status: str = UniverseBiasStatus.LIMITED.value
    delisted_coverage: str = "UNKNOWN"   # 退市股覆盖情况描述
    universe_size_total: Optional[int] = None
    universe_size_delisted: Optional[int] = None
    notes: str = ""

    def is_free(self) -> bool:
        """是否可宣称 SURVIVORSHIP_FREE。仅 CLEAN 为真。"""
        return self.status == UniverseBiasStatus.CLEAN.value

    def summary(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "status": self.status,
            "survivorship_free": self.is_free(),
            "delisted_coverage": self.delisted_coverage,
            "universe_size_total": self.universe_size_total,
            "universe_size_delisted": self.universe_size_delisted,
            "notes": self.notes,
        }


def build_default_survivorship_report(strategy_id: str, dataset_id: str) -> SurvivorshipReport:
    return SurvivorshipReport(
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        status=UniverseBiasStatus.LIMITED.value,
        delisted_coverage="当前研究未显式包含退市股（基于当前 is_st=0 过滤，非历史PIT）",
        notes="当前研究 SURVIVORSHIP=LIMITED，不得宣称 SURVIVORSHIP_FREE。",
    )
