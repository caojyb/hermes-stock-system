#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/execution_models.py — Phase 9-A：Backtest Execution Model 状态登记
=============================================================================

当前 Historical Backtest 已知存在："涨停不可买"未完整建模。
这个问题不能继续假装不存在（Phase 9-A 十二）。

每个执行模型必须显式声明覆盖/未覆盖的执行约束：
  - 涨停不可买
  - 跌停不可卖
  - 停牌
  - 缺失价格
  - 一手 100
  - T+1
  - 滑点
  - 手续费
  - 流动性
  - 开盘/收盘执行语义

状态枚举：
  READY    — 完整建模，可支撑 QUALIFIED
  PARTIAL  — 部分建模（如涨停未建模）；可研究但不得 QUALIFIED 直到达标
  BLOCKED  — 关键约束不可用
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExecutionModelStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


# 标准执行约束清单（Phase 9-A 十二）
EXECUTION_CONSTRAINTS = [
    "limit_up_no_buy",       # 涨停不可买
    "limit_down_no_sell",    # 跌停不可卖
    "suspension",            # 停牌
    "missing_price",         # 缺失价格
    "lot_100",               # 一手 100
    "t_plus_1",              # T+1
    "slippage",              # 滑点
    "commission",            # 手续费
    "liquidity",             # 流动性
    "open_close_semantics",  # 开盘/收盘执行语义
]


@dataclass
class ExecutionModelSpec:
    """一个执行模型声明其覆盖的执行约束。"""
    model_id: str
    version: str
    status: str = ExecutionModelStatus.PARTIAL.value
    # 已建模的约束集合
    covered: list[str] = field(default_factory=list)
    # 未建模的约束集合（必须显式列出，不允许"假装覆盖"）
    missing: list[str] = field(default_factory=list)
    notes: str = ""

    def is_qualified_ready(self) -> bool:
        """是否足以支撑 QUALIFIED。仅当 status=READY 且关键约束全覆盖。"""
        return self.status == ExecutionModelStatus.READY.value \
            and "limit_up_no_buy" in self.covered \
            and "limit_down_no_sell" in self.covered \
            and "t_plus_1" in self.covered \
            and "commission" in self.covered \
            and "slippage" in self.covered

    def blocking_for_qualification(self) -> bool:
        """是否直接阻断资格认证（BLOCKED 或缺失关键约束）。"""
        if self.status == ExecutionModelStatus.BLOCKED.value:
            return True
        critical = {"limit_up_no_buy", "limit_down_no_sell", "t_plus_1"}
        return not critical.issubset(set(self.covered))


# 默认执行模型（Phase 9-A 十二）：当前 = PARTIAL（涨停不可买未建模）
DEFAULT_EXEC_MODEL = ExecutionModelSpec(
    model_id="EXEC_PARTIAL",
    version="1.0",
    status=ExecutionModelStatus.PARTIAL.value,
    covered=["lot_100", "t_plus_1", "commission", "open_close_semantics", "missing_price"],
    missing=["limit_up_no_buy", "limit_down_no_sell", "slippage", "liquidity", "suspension"],
    notes="已知涨停不可买未建模（Phase 9-A 十二）。可研究但不得 QUALIFIED，直到 limit_up_no_buy 等达成。",
)


if __name__ == "__main__":
    m = DEFAULT_EXEC_MODEL
    print("status:", m.status)
    print("qualified_ready:", m.is_qualified_ready())
    print("blocking:", m.blocking_for_qualification())
    print("missing:", m.missing)
