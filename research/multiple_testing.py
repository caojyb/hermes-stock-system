#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/multiple_testing.py — Phase 9-A 三十三：Multiple Testing 防护
======================================================================

如果研究 100 因子 × 100 阈值 × 20 组合，不能最后只报告最好的一组。
必须记录：
  - research_search_space（搜索空间规模）
  - multiple_testing_status
  - 若未完整校正：明确为 DISCOVERY_ONLY，不能直接 Qualified。

提供简易统计校正壳（Bonferroni / FDR 提示），但本阶段不强制数值阈值，
缺失阈值标记为 UNDEFINED。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MultipleTestingStatus(str, Enum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"     # 仅发现，未校正
    BONFERRONI = "BONFERRONI"
    FDR = "FDR"
    NONE = "NONE"                         # 单假设（无需校正）


@dataclass
class MultipleTestingReport:
    strategy_id: str
    search_space_size: int = 0            # 因子×阈值×组合规模
    tests_considered: int = 0             # 实际纳入统计检验的假设数
    correction: str = MultipleTestingStatus.DISCOVERY_ONLY.value
    alpha_nominal: float = 0.05
    alpha_adjusted: Optional[float] = None  # 校正后阈值；UNDEFINED 时 None
    notes: str = ""

    def requires_correction(self) -> bool:
        return self.tests_considered > 1

    def is_discovery_only(self) -> bool:
        return self.correction == MultipleTestingStatus.DISCOVERY_ONLY.value

    def adjusted_alpha(self) -> Optional[float]:
        """若未能提供校正阈值，返回 None（UNDEFINED）。"""
        if self.alpha_adjusted is not None:
            return self.alpha_adjusted
        if self.correction == MultipleTestingStatus.BONFERRONI.value and self.tests_considered > 0:
            return self.alpha_nominal / self.tests_considered
        return None  # UNDEFINED

    def can_directly_qualify(self) -> bool:
        """DISCOVERY_ONLY 不得直接 Qualified。"""
        return not self.is_discovery_only()

    def summary(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "search_space_size": self.search_space_size,
            "tests_considered": self.tests_considered,
            "correction": self.correction,
            "alpha_nominal": self.alpha_nominal,
            "alpha_adjusted": self.adjusted_alpha(),
            "discovery_only": self.is_discovery_only(),
            "can_directly_qualify": self.can_directly_qualify(),
            "notes": self.notes,
        }


def build_default_multiple_testing(strategy_id: str) -> MultipleTestingReport:
    return MultipleTestingReport(
        strategy_id=strategy_id,
        search_space_size=0,
        tests_considered=0,
        correction=MultipleTestingStatus.DISCOVERY_ONLY.value,
        notes="默认 DISCOVERY_ONLY；完整校正前不得直接 Qualified。",
    )
