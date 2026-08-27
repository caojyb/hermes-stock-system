#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factors/factor_contract.py — Phase 9-A 九/十：Factor Research Contract
==============================================================================

每个 Factor 至少需要（section 9）：
  factor_id / name / formula / PIT source / availability_start / coverage /
  missing_rate / known caveats / computation_unit / direction hypothesis /
  monotonicity test / regime split / time split

每个因子必须先独立研究（section 十），回答 10 个问题，至少输出：
  distribution / quantiles / forward outcome / MAE-MFE / monotonicity /
  time stability / regime stability / incremental value

禁止先组合；先研究 FACTORS，再 QUALIFICATION，最后 STRATEGY CONSTRUCTION。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FactorSpec:
    """单个因子的研究契约。"""
    factor_id: str
    name: str
    group: str                       # QUALITY / GROWTH / MOMENTUM / VOLUME / VALUATION
    formula: str = ""
    pit_source: str = ""
    availability_start: Optional[str] = None
    coverage: str = "UNKNOWN"
    missing_rate: str = "UNKNOWN"
    known_caveats: str = ""
    computation_unit: str = ""
    direction_hypothesis: str = ""
    monotonicity_tested: bool = False
    regime_split_tested: bool = False
    time_split_tested: bool = False

    # 研究产出（初始未填，必须先独立研究）
    has_distribution: bool = False
    has_quantiles: bool = False
    has_forward_outcome: bool = False
    has_mae_mfe: bool = False
    has_monotonicity: bool = False
    has_time_stability: bool = False
    has_regime_stability: bool = False
    has_incremental_value: bool = False

    def research_complete(self) -> bool:
        return all([
            self.has_distribution, self.has_quantiles, self.has_forward_outcome,
            self.has_mae_mfe, self.has_monotonicity, self.has_time_stability,
            self.has_regime_stability, self.has_incremental_value,
        ])

    def missing_studies(self) -> list[str]:
        req = [
            ("has_distribution", "distribution"),
            ("has_quantiles", "quantiles"),
            ("has_forward_outcome", "forward_outcome"),
            ("has_mae_mfe", "mae_mfe"),
            ("has_monotonicity", "monotonicity"),
            ("has_time_stability", "time_stability"),
            ("has_regime_stability", "regime_stability"),
            ("has_incremental_value", "incremental_value"),
        ]
        return [label for attr, label in req if not getattr(self, attr)]


# 候选第一批（section 九，只是 Research Candidate，不是默认纳入 V2）
FACTOR_CANDIDATE_LIST = [
    # QUALITY
    ("QUALITY_ROE", "ROE", "QUALITY"),
    ("QUALITY_ROIC", "ROIC", "QUALITY"),
    ("QUALITY_GROSS_MARGIN", "gross margin", "QUALITY"),
    ("QUALITY_OCF_NI", "operating cash flow / net income", "QUALITY"),
    ("QUALITY_DEBT_RATIO", "debt ratio", "QUALITY"),
    ("QUALITY_REV_GROWTH", "revenue growth", "QUALITY"),
    ("QUALITY_PROFIT_GROWTH", "profit growth", "QUALITY"),
    ("QUALITY_PROFIT_STABILITY", "profit stability", "QUALITY"),
    # GROWTH ACCELERATION
    ("GROWTH_REV_ACCEL", "revenue acceleration", "GROWTH"),
    ("GROWTH_PROFIT_ACCEL", "profit acceleration", "GROWTH"),
    # MOMENTUM
    ("MOM_20D", "20D return", "MOMENTUM"),
    ("MOM_60D", "60D return", "MOMENTUM"),
    ("MOM_120D", "120D return", "MOMENTUM"),
    ("MOM_250D", "250D return", "MOMENTUM"),
    ("MOM_RS", "relative strength", "MOMENTUM"),
    ("MOM_52W_DIST", "distance to 52-week high", "MOMENTUM"),
    ("MOM_MA20_SLOPE", "MA20 slope", "MOMENTUM"),
    ("MOM_MA60_SLOPE", "MA60 slope", "MOMENTUM"),
    # VOLUME / CAPITAL
    ("VOL_RATIO", "volume ratio", "VOLUME"),
    ("VOL_TURNOVER_PERSIST", "turnover persistence", "VOLUME"),
    ("VOL_AMOUNT_PERSIST", "amount persistence", "VOLUME"),
    ("VOL_ACCEL", "volume acceleration", "VOLUME"),
    # VALUATION
    ("VAL_PE_PCT", "PE percentile", "VALUATION"),
    ("VAL_PB_PCT", "PB percentile", "VALUATION"),
    ("VAL_PEG", "PEG (if PIT sufficient)", "VALUATION"),
]


def build_factor_candidates() -> list[FactorSpec]:
    """返回第一批因子候选（均为未研究状态，需先独立研究）。"""
    specs = []
    for fid, name, grp in FACTOR_CANDIDATE_LIST:
        specs.append(FactorSpec(factor_id=fid, name=name, group=grp))
    return specs


# 每个因子必须回答的 10 个问题（section 十）
FACTOR_RESEARCH_QUESTIONS = [
    "1. 是否有稳定方向？",
    "2. 是否线性？",
    "3. 是否非线性？",
    "4. 是否存在极端尾部反转？",
    "5. 是否跨时期？",
    "6. 是否跨 Regime？",
    "7. 是否跨市值？",
    "8. 是否具有增量价值？",
    "9. 是否与其他因子高度重复？",
    "10. 是否受到严重数据缺失影响？",
]
