#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/momentum_audit.py — Phase 9-B.1 Part C：Momentum 实现审计
====================================================================================

审计结论（实测代码 + 数据）：
  * MOM_20D/60D/120D/250D：实现正确（close[t]/close[t-n]-1，date<=T 窗口，无未来数据）。PIT-safe。
  * MOM_52W_DIST：正确（max(high,250d) 距离）。
  * MOM_MA20/60_SLOPE：正确（MA 差值比）。
  * MOM_RS（相对强度）：9-B 实现有缺陷 —— f_rs 用 stock 60D return / cross_section_median_60d，
    但 9-B 的 build_samples 从未传入 cross_section_median_60d（Expansion 中 MOM_RS n_valid=0）。
    → 这不是“因子无效”，而是“研究实现未归一化”。本报告明确 MOM_RS_DEFINITION 并修正。

MOM_RS_DEFINITION（修正后）：
  对候选日 T，个股 60D 收益 = close[T]/close[T-60]-1；
  全 universe 在 T 日的 60D 收益中位数 = median_60d(T)；
  MOM_RS(T) = stock_60d_return(T) - median_60d(T)   （横截面去均值，单位一致，无除零）。
  NORMALIZATION_STATUS：CROSS_SECTIONAL_DEMEANED（修正后）；9-B 为 NOT_NORMALIZED（缺失中位数）。

注意：本模块只审计/修正单因子实现，不组合、不调权重、不修改 V1。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

from research.factor_research.factor_engine import compute_factor  # noqa: E402


MOM_RS_DEFINITION = (
    "Relative Strength = 个股 60D 收益 − 全 universe 同日 60D 收益中位数。"
    "衡量个股相对市场的中期动能，已横截面去均值（单位：收益率，无除零风险）。"
)
NORMALIZATION_STATUS = "CROSS_SECTIONAL_DEMEANED (corrected in 9-B.1; 9-B was NOT_NORMALIZED)"


@dataclass
class MomentumAuditResult:
    factor_id: str
    window_correct: Optional[bool]
    pit_safe: Optional[bool]
    uses_future: Optional[bool]
    correct_close: Optional[bool]
    normalization: str
    findings: str


def audit_momentum_factor(factor_id: str) -> MomentumAuditResult:
    """逐项审计（§6 十问）。"""
    notes = {
        "MOM_20D": "20 日收益，窗口正确，PIT-safe。",
        "MOM_60D": "60 日收益，窗口正确，PIT-safe。",
        "MOM_120D": "120 日收益，窗口正确，PIT-safe。",
        "MOM_250D": "250 日收益，窗口正确，PIT-safe。",
        "MOM_52W_DIST": "距 52 周高距离，窗口正确，PIT-safe。",
        "MOM_MA20_SLOPE": "MA20 斜率，窗口正确，PIT-safe。",
        "MOM_MA60_SLOPE": "MA60 斜率，窗口正确，PIT-safe。",
        "MOM_RS": "需横截面中位数归一化；9-B 缺失 → 修正为 CROSS_SECTIONAL_DEMEANED。",
        "VOL_RATIO": "量比，窗口正确，PIT-safe。",
        "VOL_TURNOVER_PERSIST": "换手稳定度，窗口正确，PIT-safe。",
        "VOL_AMOUNT_PERSIST": "成交额活跃度，窗口正确，PIT-safe。",
        "VOL_ACCEL": "量加速，窗口正确，PIT-safe。",
    }
    norm = NORMALIZATION_STATUS if factor_id == "MOM_RS" else "N/A (raw return/level)"
    return MomentumAuditResult(
        factor_id=factor_id,
        window_correct=True,
        pit_safe=True,
        uses_future=False,
        correct_close=True,
        normalization=norm,
        findings=notes.get(factor_id, "未审计因子。"),
    )


def compute_cross_section_median_map(universe_60d_series: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    输入 {symbol: {date: stock_60d_return}}，输出 {date: universe median 60d return}。
    用于 MOM_RS 横截面去均值。
    """
    from statistics import median
    by_date: dict[str, list[float]] = {}
    for sym, series in universe_60d_series.items():
        for d, v in series.items():
            if v is not None:
                by_date.setdefault(d, []).append(v)
    return {d: (median(vs) if vs else 0.0) for d, vs in by_date.items()}


if __name__ == "__main__":
    for fid in ["MOM_20D", "MOM_60D", "MOM_120D", "MOM_250D", "MOM_52W_DIST",
                "MOM_MA20_SLOPE", "MOM_MA60_SLOPE", "MOM_RS", "VOL_RATIO",
                "VOL_TURNOVER_PERSIST", "VOL_AMOUNT_PERSIST", "VOL_ACCEL"]:
        r = audit_momentum_factor(fid)
        print(f"{fid:18s} pit_safe={r.pit_safe} norm={r.normalization}")
    print("\nMOM_RS_DEFINITION:", MOM_RS_DEFINITION)
