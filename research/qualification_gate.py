#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/qualification_gate.py — Phase 9-A 十九：Qualification Gate
====================================================================

输出（section 19）：
  QUALIFIED / CONDITIONALLY_QUALIFIED / REJECTED / DATA_INSUFFICIENT

至少包含四类 Gate：
  Data Gate        — PIT sufficient / Execution Model sufficient / Survivorship acceptable
  Performance Gate — minimum trade count / return / risk / drawdown
  Robustness Gate  — time stability / regime stability / parameter stability
  Statistical Gate — statistical sufficiency / multiple-testing control

原则（Phase 9-A 十九）：
  * 本阶段不要擅自固定所有数值阈值。
  * 先复用已存在的、此前项目定义的 Gate；没有定义的阈值标记为 UNDEFINED。
  * 禁止为了让某策略通过而发明阈值。

阈值缺失 → 输出 QUALIFICATION_THRESHOLD_GAP。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# 资格结论
QUALIFIED = "QUALIFIED"
CONDITIONALLY_QUALIFIED = "CONDITIONALLY_QUALIFIED"
REJECTED = "REJECTED"
DATA_INSUFFICIENT = "DATA_INSUFFICIENT"

# 阈值标记
UNDEFINED = "UNDEFINED"


@dataclass
class GateThreshold:
    """单个阈值。value=None 表示 UNDEFINED（未定义，不得为通过而发明）。"""
    name: str
    value: Optional[float] = None
    defined: bool = False
    notes: str = ""

    def is_met(self, actual: Optional[float]) -> Optional[bool]:
        if not self.defined or self.value is None:
            return None  # UNDEFINED → 不参与判定，报告 gap
        if actual is None:
            return None
        return actual >= self.value


@dataclass
class QualificationContext:
    """进入 Gate 所需的全部上下文（来自各子模块报告）。"""
    strategy_id: str
    strategy_version: str
    run_id: str
    dataset_id: str

    # --- Data Gate 输入 ---
    pit_complete: bool = False
    execution_model_ready: bool = False
    survivorship_acceptable: bool = False

    # --- Performance Gate 输入 ---
    trade_count: int = 0
    cumulative_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None

    # --- Robustness Gate 输入 ---
    time_stability: Optional[str] = None
    regime_stability: Optional[str] = None
    parameter_stability: Optional[str] = None

    # --- Statistical Gate 输入 ---
    independent_trade_n: Optional[int] = None
    multiple_testing_ok: bool = False

    # --- 阈值（默认 UNDEFINED，不发明） ---
    thresholds: dict = field(default_factory=lambda: {
        "min_trade_count": GateThreshold("min_trade_count", value=None, defined=False),
        "min_return": GateThreshold("min_return", value=None, defined=False),
        "max_drawdown": GateThreshold("max_drawdown", value=None, defined=False),
        "min_independent_trades": GateThreshold("min_independent_trades", value=None, defined=False),
    })

    def threshold_gaps(self) -> list[str]:
        return [name for name, t in self.thresholds.items() if not t.defined]


def evaluate(ctx: QualificationContext) -> dict:
    """
    执行 Qualification Gate。返回结论 + 各 Gate 明细 + threshold gaps。
    原则：任何硬门槛缺失（UNDEFINED）时，不强行通过；缺数据时 DATA_INSUFFICIENT。
    """
    reasons = []
    gates = {}

    # --- Data Gate ---
    data_ok = ctx.pit_complete and ctx.execution_model_ready and ctx.survivorship_acceptable
    gates["data"] = {
        "pit_complete": ctx.pit_complete,
        "execution_model_ready": ctx.execution_model_ready,
        "survivorship_acceptable": ctx.survivorship_acceptable,
        "passed": data_ok,
    }
    if not data_ok:
        if not ctx.pit_complete:
            reasons.append("PIT not complete (Historical ST=BLOCKED / Market Cap=APPROXIMATE)")
        if not ctx.execution_model_ready:
            reasons.append("Execution Model not READY (limit-up not modeled)")
        if not ctx.survivorship_acceptable:
            reasons.append("Survivorship not acceptable (LIMITED)")

    # --- Performance Gate ---
    gaps = ctx.threshold_gaps()
    perf = ctx.thresholds
    defined_thresholds = [t for t in perf.values() if t.defined]
    perf_fails = []
    for t in defined_thresholds:
        actual = {
            "min_trade_count": ctx.trade_count,
            "min_return": ctx.cumulative_return,
            "max_drawdown": ctx.max_drawdown,
            "min_independent_trades": ctx.independent_trade_n,
        }.get(t.name)
        res = t.is_met(actual)
        if res is False:
            perf_fails.append(t.name)
    perf_passed = None if not defined_thresholds else (len(perf_fails) == 0)
    gates["performance"] = {
        "trade_count": ctx.trade_count,
        "cumulative_return": ctx.cumulative_return,
        "max_drawdown": ctx.max_drawdown,
        "thresholds_defined": {k: t.defined for k, t in perf.items()},
        "passed": perf_passed,
    }

    # --- Robustness Gate ---
    rob_provided = [s for s in [ctx.time_stability, ctx.regime_stability, ctx.parameter_stability] if s is not None]
    rob_ok = all(s in ("STABLE", "ACCEPTABLE", "PASS") for s in rob_provided) if rob_provided else None
    gates["robustness"] = {
        "time_stability": ctx.time_stability,
        "regime_stability": ctx.regime_stability,
        "parameter_stability": ctx.parameter_stability,
        "passed": rob_ok,
    }

    # --- Statistical Gate ---
    indep_t = perf["min_independent_trades"]
    indep_ok = indep_t.is_met(ctx.independent_trade_n)  # None if undefined
    if indep_t.defined:
        stats_ok = (indep_ok is True) and ctx.multiple_testing_ok
    else:
        stats_ok = ctx.multiple_testing_ok
    stats_passed = stats_ok
    gates["statistical"] = {
        "independent_trade_n": ctx.independent_trade_n,
        "multiple_testing_ok": ctx.multiple_testing_ok,
        "passed": stats_passed,
    }

    # --- 综合判定 ---
    # 数据门槛是硬约束：不满足 → DATA_INSUFFICIENT 或 REJECTED
    if not data_ok:
        conclusion = DATA_INSUFFICIENT if not ctx.pit_complete else REJECTED
    else:
        has_defined_fail = any(x is False for x in [perf_passed, stats_passed, rob_ok] if x is not None)
        if has_defined_fail:
            conclusion = REJECTED
        elif gaps or not ctx.multiple_testing_ok:
            # 关键阈值未定义或未校正 → 不能 QUALIFIED
            conclusion = CONDITIONALLY_QUALIFIED
        else:
            conclusion = QUALIFIED

    return {
        "strategy_id": ctx.strategy_id,
        "strategy_version": ctx.strategy_version,
        "run_id": ctx.run_id,
        "dataset_id": ctx.dataset_id,
        "conclusion": conclusion,
        "gates": gates,
        "reasons": reasons,
        "qualification_threshold_gap": gaps,
    }
