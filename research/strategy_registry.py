#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/strategy_registry.py — Phase 9-A 多策略竞技场：Strategy Registry
=========================================================================

唯一策略身份登记中心。每个策略（V1 / V2 / V3 ...）在框架中必须有唯一
StrategySpec，状态必须显式记录在数据中（不能仅靠文件夹名字判断）。

设计原则（来自 Phase 9-A 说明）：
  * Strategy Registry 不拥有 Final Decision Authority。
    Strategy 只是"候选策略定义"，最终交易权威仍是 DecisionEngine。
  * Strategy Status 与 Production Authority 完全分离。
  * V1 在此框架中定位 = BENCHMARK_STRATEGY（不参与新资格认证，只作比较基准）。

本模块是纯逻辑（无 DB 依赖、无 pandas 依赖），可被测试/runner 直接 import。
Registry 持久化到 JSON（默认 research/registry_store.json），可被 git 跟踪。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Optional


# ════════════════════════ 状态枚举 ════════════════════════

class StrategyStatus(str, Enum):
    """策略整体生命周期状态（显式，不靠文件夹名推断）。"""
    RESEARCH = "RESEARCH"                       # 研究候选，尚未进入系统测试
    HISTORICAL_TESTING = "HISTORICAL_TESTING"   # 历史回测/稳健性研究中
    QUALIFICATION = "QUALIFICATION"             # 资格认证中
    SHADOW = "SHADOW"                           # 通过后 Shadow Validation
    FORWARD_VALIDATION = "FORWARD_VALIDATION"   # 前向验证中
    PRODUCTION = "PRODUCTION"                   # 进入生产（Selector 未来阶段）
    REJECTED = "REJECTED"                       # 资格未通过/被淘汰
    RETIRED = "RETIRED"                         # 退役（不再使用）


class ResearchStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DISCOVERY = "DISCOVERY"
    IN_SAMPLE = "IN_SAMPLE"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    WALK_FORWARD = "WALK_FORWARD"
    COMPLETE = "COMPLETE"


class QualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    CONDITIONALLY_QUALIFIED = "CONDITIONALLY_QUALIFIED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


class ProductionStatus(str, Enum):
    NONE = "NONE"                 # 从未进入生产
    SHADOW = "SHADOW"
    FORWARD_VALIDATION = "FORWARD_VALIDATION"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"


# 基准策略角色
BENCHMARK_ROLE = "BENCHMARK_STRATEGY"


# ════════════════════════ StrategySpec ════════════════════════

@dataclass
class StrategySpec:
    """唯一策略身份定义。字段至少覆盖 Phase 9-A 三、要求列表。"""
    strategy_id: str
    strategy_version: str
    strategy_name: str
    owner: str

    # 状态（显式，不再靠文件夹名推断）
    status: str = StrategyStatus.RESEARCH.value
    research_status: str = ResearchStatus.NOT_STARTED.value
    qualification_status: str = QualificationStatus.UNQUALIFIED.value
    production_status: str = ProductionStatus.NONE.value

    created_at: str = field(default_factory=lambda: date.today().isoformat())
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None

    # 数据/执行语义版本（用于公平比较的"同一套口径"约束）
    research_dataset_version: Optional[str] = None
    execution_model_version: Optional[str] = None
    cost_model_version: Optional[str] = None

    # 范围/定义（研究契约的一部分，详见 strategy_contract）
    regime_scope: Optional[str] = None
    universe_definition: Optional[str] = None
    parameter_definition: Optional[str] = None
    entry_definition: Optional[str] = None
    exit_definition: Optional[str] = None

    # 角色标记（benchmark 等）
    role: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategySpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    # ── 语义校验 ──
    def is_benchmark(self) -> bool:
        return self.role == BENCHMARK_ROLE

    def is_active_lifecycle(self) -> bool:
        """是否处于"正在被框架处理"的状态（非终态）。"""
        terminal = {StrategyStatus.REJECTED.value, StrategyStatus.RETIRED.value}
        return self.status not in terminal

    def has_production_authority(self) -> bool:
        """策略本身是否直接拥有最终交易权威。架构上永远为 False。"""
        return False

    def validate_status_consistency(self) -> list[str]:
        """检查 status 与子状态是否一致，返回问题列表（空=一致）。"""
        problems = []
        st = self.status
        if st == StrategyStatus.PRODUCTION.value and \
                self.production_status != ProductionStatus.PRODUCTION.value:
            problems.append("status=PRODUCTION but production_status!='PRODUCTION'")
        if st == StrategyStatus.REJECTED.value and \
                self.qualification_status not in (
                    QualificationStatus.REJECTED.value,
                    QualificationStatus.DATA_INSUFFICIENT.value):
            problems.append("status=REJECTED but qualification_status not REJECTED/DATA_INSUFFICIENT")
        if st == StrategyStatus.RESEARCH.value and \
                self.research_status == ResearchStatus.NOT_STARTED.value and \
                self.qualification_status != QualificationStatus.UNQUALIFIED.value:
            problems.append("status=RESEARCH but already qualified (inconsistent)")
        return problems


# ════════════════════════ Registry ════════════════════════

class StrategyRegistry:
    """策略登记中心：用 strategy_id 唯一寻址，支持持久化。"""

    def __init__(self, store_path: Optional[str] = None):
        here = os.path.dirname(os.path.abspath(__file__))
        self.store_path = store_path or os.path.join(here, "registry_store.json")
        self._specs: dict[str, StrategySpec] = {}
        self.load()

    # ── 持久化 ──
    def load(self) -> None:
        self._specs = {}
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for item in data.get("strategies", []):
            spec = StrategySpec.from_dict(item)
            self._specs[spec.strategy_id] = spec

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        payload = {
            "version": "phase-9a",
            "strategies": [s.to_dict() for s in self._specs.values()],
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return self.store_path

    # ── CRUD ──
    def register(self, spec: StrategySpec) -> StrategySpec:
        if spec.strategy_id in self._specs:
            raise ValueError(f"strategy_id already exists: {spec.strategy_id}")
        problems = spec.validate_status_consistency()
        if problems:
            raise ValueError(f"inconsistent StrategySpec: {problems}")
        self._specs[spec.strategy_id] = spec
        return spec

    def upsert(self, spec: StrategySpec) -> StrategySpec:
        """已存在则覆盖（谨慎使用）。"""
        self._specs[spec.strategy_id] = spec
        return spec

    def get(self, strategy_id: str) -> Optional[StrategySpec]:
        return self._specs.get(strategy_id)

    def all(self) -> list[StrategySpec]:
        return list(self._specs.values())

    def list_by_status(self, status: StrategyStatus) -> list[StrategySpec]:
        return [s for s in self._specs.values() if s.status == status.value]

    def benchmarks(self) -> list[StrategySpec]:
        return [s for s in self._specs.values() if s.is_benchmark()]

    def __len__(self) -> int:
        return len(self._specs)


# ════════════════════════ 默认种子（V1 benchmark） ════════════════════════

def default_v1_spec() -> StrategySpec:
    """V1 在新框架中的定位 = BENCHMARK_STRATEGY。不修改 V1，仅登记身份。"""
    return StrategySpec(
        strategy_id="V1",
        strategy_version="1.0",
        strategy_name="V1 Top3 翻倍潜力（量产基线）",
        owner="system",
        status=StrategyStatus.FORWARD_VALIDATION.value,
        research_status=ResearchStatus.COMPLETE.value,
        qualification_status=QualificationStatus.QUALIFIED.value,
        production_status=ProductionStatus.FORWARD_VALIDATION.value,
        created_at="2026-08-27",
        effective_from="2026-08-27",
        research_dataset_version="dataset_v1_full",
        execution_model_version="EXEC_PARTIAL",
        cost_model_version="COST_V1",
        regime_scope="ALL_REGIMES",
        universe_definition="全市场无LIMIT；过滤688/787；is_st=0",
        parameter_definition="price_pos<=40, vol_ratio>=2.7, mcap 5-90亿, "
                             "amount_1d>=8000万, amount_20d>=4000万, atr_pct>=3%",
        entry_definition="候选PASS + 信号A/B/C/D中≥3个确认（T+1开盘）",
        exit_definition="生产退出规则（本框架不修改）",
        role=BENCHMARK_ROLE,
    )


def build_default_registry(store_path: Optional[str] = None) -> StrategyRegistry:
    """建立默认 registry：把 V1 登记为基准策略。"""
    reg = StrategyRegistry(store_path=store_path)
    if reg.get("V1") is None:
        reg.register(default_v1_spec())
    return reg


if __name__ == "__main__":
    r = build_default_registry()
    p = r.save()
    print(f"registry -> {p}")
    print(f"strategies: {[s.strategy_id for s in r.all()]}")
