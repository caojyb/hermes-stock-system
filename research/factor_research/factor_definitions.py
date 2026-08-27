#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/factor_definitions.py — Phase 9-B 因子定义与数据可用性审计
========================================================================================

对 Phase 9-A 已登记候选因子（25 个）做 Data Availability Audit。
逐因子确认：source table / field / formula / effective date / PIT available /
start / end / coverage / missing rate / approximate rate / unit / update freq /
known caveats。

输出 FACTOR_DATA_AVAILABILITY_MATRIX，每个因子得 RESEARCHABLE / PARTIAL / BLOCKED。

关键（Phase 9-B 三/四）：不能因为字段存在就判 RESEARCHABLE。
  * 财务因子无 announcement_date → PIT 无法证明披露滞后 → 不能当 PIT_SAFE。
  * indicators 表是稀疏快照（134 个日期，非逐日时间序列）→ 不依赖它做历史时间序列因子。
  * 价格/成交量因子从 klines 直接计算（date<=T，严格 PIT）→ RESEARCHABLE。

数据库事实（来自 market_cache.db 实测）：
  klines: 18.6M 行, 1991-01-29..2026-08-26, 1391 只代码有 2005 前数据。
  financial_data: 6366 代码, report_date 1988..2026-06-30, 无 announcement_date。
  indicators: 134 个 distinct date, 最新日 ~5009 行（稀疏快照，非时间序列）。
  stocks: is_st 当前全 0（非历史 PIT）；total_mcap 当前值（非历史）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# PIT 结论
class FactorAvailability(str, Enum):
    RESEARCHABLE = "RESEARCHABLE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


# 数据库路径
DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"


@dataclass
class FactorDef:
    """单因子定义 + 数据可用性审计结论。"""
    factor_id: str
    name: str
    group: str
    formula: str
    source_table: str
    source_field: str
    unit: str
    update_freq: str
    pit_basis: str                 # 因子值在 T 日如何保证只用 T 及之前数据
    availability: str = FactorAvailability.PARTIAL.value
    pit_status: str = "UNKNOWN"    # PIT_READY / PIT_APPROXIMATE / PIT_BLOCKED
    effective_date_reliable: bool = False
    coverage_start: str = "UNKNOWN"
    coverage_end: str = "UNKNOWN"
    missing_rate: str = "UNKNOWN"
    approximate_rate: str = "UNKNOWN"
    known_caveats: str = ""
    factor_index: int = 0

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id, "name": self.name, "group": self.group,
            "formula": self.formula, "source_table": self.source_table,
            "source_field": self.source_field, "unit": self.unit,
            "update_freq": self.update_freq, "pit_basis": self.pit_basis,
            "availability": self.availability, "pit_status": self.pit_status,
            "effective_date_reliable": self.effective_date_reliable,
            "coverage_start": self.coverage_start, "coverage_end": self.coverage_end,
            "missing_rate": self.missing_rate, "approximate_rate": self.approximate_rate,
            "known_caveats": self.known_caveats, "factor_index": self.factor_index,
        }


# ── 25 因子定义（依据 market_cache.db 实测 schema）─────────────────────────
# 价格/成交量类：从 klines 在 date<=T 窗口直接计算 → PIT_READY → RESEARCHABLE
# 财务类：从 financial_data（report_date 代理，无 announcement_date）→ PIT_APPROXIMATE → PARTIAL
# 估值类（PE/PB/PEG）：财务派生，PIT_APPROXIMATE → PARTIAL

def _build_defs() -> list[FactorDef]:
    K = "klines"
    FD = "financial_data"
    M = "market_cap (historical_share_layer)"
    defs = []

    # ── QUALITY（财务，PARTIAL：无 announcement_date）──
    defs += [
        FactorDef("QUALITY_ROE", "ROE", "QUALITY", "净利润/净资产", FD, "roe",
                  "%", "季度/年度", "取 report_date<=T 最新一期财报 roe",
                  availability="PARTIAL", pit_status="PIT_APPROXIMATE",
                  effective_date_reliable=False, coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="部分代码/早期缺失", approximate_rate="披露滞后未知→APPROXIMATE",
                  known_caveats="无 announcement_date；report_date 不等于市场可得日；存在未来财报回填 T 之前风险（保守标 APPROXIMATE）",
                  factor_index=1),
        FactorDef("QUALITY_ROIC", "ROIC", "QUALITY", "近似 (operating_profit+finance_exp)/total_assets", FD,
                  "operating_profit,total_assets,finance_expenses", "%", "季度/年度",
                  "取 report_date<=T 最新一期", availability="BLOCKED", pit_status="PIT_BLOCKED",
                  effective_date_reliable=False, coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="100% (字段全为 0)", approximate_rate="N/A",
                  known_caveats="实测 financial_data 中 operating_profit/finance_expenses/total_assets 全部为 0；字段不可用 → BLOCKED", factor_index=2),
        FactorDef("QUALITY_GROSS_MARGIN", "Gross Margin", "QUALITY", "gross_margin", FD, "gross_margin",
                  "%", "季度/年度", "report_date<=T 最新一期", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="无披露日", factor_index=3),
        FactorDef("QUALITY_OCF_NI", "OCF / Net Income", "QUALITY", "operating_cashflow/net_profit", FD,
                  "operating_cashflow,net_profit", "ratio", "季度/年度", "report_date<=T 最新一期",
                  availability="BLOCKED", pit_status="PIT_BLOCKED", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="100% (operating_cashflow 字段全为 0)", approximate_rate="N/A",
                  known_caveats="实测 operating_cashflow 全为 0；字段不可用 → BLOCKED", factor_index=4),
        FactorDef("QUALITY_DEBT_RATIO", "Debt Ratio", "QUALITY", "total_liabilities/total_assets (1-equity_ratio)", FD,
                  "equity_ratio", "%", "季度/年度", "report_date<=T 最新一期", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="无披露日", factor_index=5),
        FactorDef("QUALITY_REV_GROWTH", "Revenue Growth", "QUALITY", "revenue_growth (YoY)", FD, "revenue_growth",
                  "%", "季度/年度", "report_date<=T 最新一期", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="YoY 需去年同期；无披露日", factor_index=6),
        FactorDef("QUALITY_PROFIT_GROWTH", "Profit Growth", "QUALITY", "profit_growth (YoY)", FD, "profit_growth",
                  "%", "季度/年度", "report_date<=T 最新一期", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="负基数扭曲；无披露日", factor_index=7),
        FactorDef("QUALITY_PROFIT_STABILITY", "Profit Stability", "QUALITY",
                  "过去 N 期 net_profit 变异系数(负值=不稳定)", FD, "net_profit", "ratio", "季度/年度",
                  "report_date<=T 最近 8 期", availability="PARTIAL", pit_status="PIT_APPROXIMATE",
                  effective_date_reliable=False, coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="部分缺失", approximate_rate="APPROXIMATE",
                  known_caveats="需多期序列；早期不足；无披露日", factor_index=8),
    ]

    # ── GROWTH ACCELERATION（财务派生，PARTIAL）──
    defs += [
        FactorDef("GROWTH_REV_ACCEL", "Revenue Acceleration", "GROWTH",
                  "本期 revenue_growth - 上期 revenue_growth", FD, "revenue_growth",
                  "pp", "季度/年度", "report_date<=T 最近两期差分", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="需连续两期；无披露日", factor_index=9),
        FactorDef("GROWTH_PROFIT_ACCEL", "Profit Acceleration", "GROWTH",
                  "本期 profit_growth - 上期 profit_growth", FD, "profit_growth",
                  "pp", "季度/年度", "report_date<=T 最近两期差分", availability="PARTIAL",
                  pit_status="PIT_APPROXIMATE", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30", missing_rate="部分缺失",
                  approximate_rate="APPROXIMATE", known_caveats="负值基数的差分噪声；无披露日", factor_index=10),
    ]

    # ── MOMENTUM（从 klines 直接计算，RESEARCHABLE）──
    defs += [
        FactorDef("MOM_20D", "20D Return", "MOMENTUM", "close[T]/close[T-20]-1", K, "close",
                  "%", "日", "date<=T 窗口 20 交易日", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="新上市不足 20 日缺失",
                  approximate_rate="0", known_caveats="需 20 交易日历史", factor_index=11),
        FactorDef("MOM_60D", "60D Return", "MOMENTUM", "close[T]/close[T-60]-1", K, "close",
                  "%", "日", "date<=T 窗口 60 交易日", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="不足 60 日缺失",
                  approximate_rate="0", known_caveats="需 60 交易日历史", factor_index=12),
        FactorDef("MOM_120D", "120D Return", "MOMENTUM", "close[T]/close[T-120]-1", K, "close",
                  "%", "日", "date<=T 窗口 120 交易日", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="不足 120 日缺失",
                  approximate_rate="0", known_caveats="需 120 交易日历史", factor_index=13),
        FactorDef("MOM_250D", "250D Return", "MOMENTUM", "close[T]/close[T-250]-1", K, "close",
                  "%", "日", "date<=T 窗口 250 交易日", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="不足 250 日缺失",
                  approximate_rate="0", known_caveats="需 250 交易日历史", factor_index=14),
        FactorDef("MOM_RS", "Relative Strength", "MOMENTUM", "个股 60D 收益 / 全市场中位 60D 收益", K, "close",
                  "ratio", "日", "date<=T 横截面分位", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="横截面样本不足缺失",
                  approximate_rate="0", known_caveats="需足够横截面样本", factor_index=15),
        FactorDef("MOM_52W_DIST", "Distance to 52-Week High", "MOMENTUM",
                  "close[T]/max(high[T-250..T])-1", K, "close,high", "%", "日",
                  "date<=T 窗口 250 交易日", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足 250 日缺失", approximate_rate="0",
                  known_caveats="需 250 交易日 high 历史", factor_index=16),
        FactorDef("MOM_MA20_SLOPE", "MA20 Slope", "MOMENTUM", "(ma20[T]-ma20[T-20])/ma20[T-20]", K, "close",
                  "%", "日", "date<=T MA20 序列", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足 MA 历史缺失", approximate_rate="0", known_caveats="需 MA20", factor_index=17),
        FactorDef("MOM_MA60_SLOPE", "MA60 Slope", "MOMENTUM", "(ma60[T]-ma60[T-20])/ma60[T-20]", K, "close",
                  "%", "日", "date<=T MA60 序列", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足 MA60 历史缺失", approximate_rate="0", known_caveats="需 MA60", factor_index=18),
    ]

    # ── VOLUME / CAPITAL（从 klines 直接计算，RESEARCHABLE）──
    defs += [
        FactorDef("VOL_RATIO", "Volume Ratio", "VOLUME", "vol_5avg/vol_20avg", K, "volume",
                  "ratio", "日", "date<=T 成交量窗口", availability="RESEARCHABLE",
                  pit_status="PIT_READY", effective_date_reliable=True,
                  coverage_start="1991", coverage_end="2026-08-26", missing_rate="新上市不足缺失",
                  approximate_rate="0", known_caveats="与 V1 VR 同源（2.7 阈值属 V1，本因子仅取原始比值）", factor_index=19),
        FactorDef("VOL_TURNOVER_PERSIST", "Turnover Persistence", "VOLUME",
                  "turnover 20日标准差倒数(稳定度)", K, "turnover", "ratio", "日",
                  "date<=T turnover 窗口", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足缺失", approximate_rate="0", known_caveats="turnover 单位=元", factor_index=20),
        FactorDef("VOL_AMOUNT_PERSIST", "Amount Persistence", "VOLUME",
                  "成交额 20日均值(活跃度代理)", K, "turnover", "万元", "日",
                  "date<=T turnover 窗口", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足缺失", approximate_rate="0", known_caveats="turnover/1e4=万元", factor_index=21),
        FactorDef("VOL_ACCEL", "Volume Acceleration", "VOLUME", "vol_5avg/vol_20avg 变化率", K, "volume",
                  "ratio", "日", "date<=T 双窗口", availability="RESEARCHABLE", pit_status="PIT_READY",
                  effective_date_reliable=True, coverage_start="1991", coverage_end="2026-08-26",
                  missing_rate="不足缺失", approximate_rate="0", known_caveats="需双窗口", factor_index=22),
    ]

    # ── VALUATION（财务派生，PARTIAL）──
    defs += [
        FactorDef("VAL_PE_PCT", "PE Percentile", "VALUATION",
                  "个股 PE 在自身历史 PE 分位", FD, "pe_ratio", "%", "季度/年度",
                  "report_date<=T 历史 PE 分布", availability="BLOCKED", pit_status="PIT_BLOCKED",
                  effective_date_reliable=False, coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="100% (pe_ratio 字段全为 0)", approximate_rate="N/A",
                  known_caveats="实测 pe_ratio 全为 0；字段不可用 → BLOCKED", factor_index=23),
        FactorDef("VAL_PB_PCT", "PB Percentile", "VALUATION",
                  "个股 PB 在自身历史 PB 分位", FD, "pb_ratio", "%", "季度/年度",
                  "report_date<=T 历史 PB 分布", availability="BLOCKED", pit_status="PIT_BLOCKED",
                  effective_date_reliable=False, coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="100% (pb_ratio 字段全为 0)", approximate_rate="N/A",
                  known_caveats="实测 pb_ratio 全为 0；字段不可用 → BLOCKED", factor_index=24),
        FactorDef("VAL_PEG", "PEG", "VALUATION", "PE / (profit_growth*100)", FD, "pe_ratio,profit_growth",
                  "ratio", "季度/年度", "report_date<=T 最新一期", availability="BLOCKED",
                  pit_status="PIT_BLOCKED", effective_date_reliable=False,
                  coverage_start="1988", coverage_end="2026-06-30",
                  missing_rate="100% (pe_ratio 字段全为 0)", approximate_rate="N/A",
                  known_caveats="pe_ratio 全为 0 → BLOCKED；且 PIT 弱", factor_index=25),
    ]
    return defs


# 全局因子表（顺序即 Phase 9-B 二 的编号）
FACTOR_DEFS: list[FactorDef] = _build_defs()
FACTOR_BY_ID: dict[str, FactorDef] = {d.factor_id: d for d in FACTOR_DEFS}


def factor_data_availability_matrix() -> list[dict]:
    """FACTOR_DATA_AVAILABILITY_MATRIX：25 行。"""
    return [d.to_dict() for d in FACTOR_DEFS]


def summary_counts() -> dict:
    c = {"RESEARCHABLE": 0, "PARTIAL": 0, "BLOCKED": 0}
    for d in FACTOR_DEFS:
        c[d.availability] = c.get(d.availability, 0) + 1
    return c


if __name__ == "__main__":
    print("factor count:", len(FACTOR_DEFS))
    print("availability:", summary_counts())
    for d in FACTOR_DEFS:
        print(f"  {d.factor_id:24s} {d.availability:12s} {d.pit_status}")
