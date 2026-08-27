#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/dataset_registry.py — Phase 9-A 多策略竞技场：Dataset Registry
=========================================================================

所有策略研究必须绑定 dataset_id + version。这样未来 V1 vs V2 可以证明：
是不是在同一数据环境里比较。

已知历史数据缺口（Phase 9-A 三十）必须显式进入每条 Dataset 记录：
  1. Historical ST           = BLOCKED
  2. Historical Market Cap   = 部分 APPROXIMATE
  3. Historical Execution     = limit-up 未完整建模 (PARTIAL)
  4. Survivorship            = LIMITED
  5. 某些指数历史存在缺口

这些缺口不得被研究系统隐藏。每条 dataset 必须暴露已知 limitation。

纯逻辑、无 DB 依赖。持久化到 research/dataset_store.json（可 git 跟踪）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class DataQualityStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


# 已知全局数据缺口（Phase 9-A 三十）
GLOBAL_KNOWN_LIMITATIONS = [
    "Historical ST = BLOCKED",
    "Historical Market Cap = 部分 APPROXIMATE",
    "Historical Execution Model = limit-up 未完整建模 (PARTIAL)",
    "Survivorship = LIMITED",
    "某些指数历史存在缺口（如 000300 仅至 2026-07-24）",
]


@dataclass
class DatasetSpec:
    """一个研究数据集（绑定研究环境快照）。"""
    dataset_id: str
    version: str
    date_range: str                         # e.g. "2005-01-01..2024-12-31"
    universe: str
    pit_status: str = DataQualityStatus.PARTIAL.value
    survivorship_status: str = "LIMITED"   # CLEAN/LIMITED/BLOCKED
    market_cap_status: str = DataQualityStatus.PARTIAL.value  # 部分 APPROXIMATE
    st_status: str = DataQualityStatus.BLOCKED.value          # Historical ST BLOCKED
    execution_model_status: str = DataQualityStatus.PARTIAL.value  # limit-up 未建模
    feature_coverage: str = "full_v1_candidate"
    known_limitations: list[str] = field(default_factory=lambda: list(GLOBAL_KNOWN_LIMITATIONS))
    source_db: Optional[str] = None
    created_at: str = field(default_factory=lambda: __import__("datetime").date.today().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def data_sufficiency_blocking(self) -> bool:
        """
        关键缺口是否直接阻断资格认证。
        规则（Phase 9-A 三十）：若策略核心逻辑依赖 ST / 退市 / 涨停执行，且这些为 BLOCKED，
        则本 dataset 不得支撑 QUALIFIED。这里只返回"是否含有 BLOCKED 级核心缺口"。
        是否真正阻断由 Qualification Gate 结合策略逻辑判定。
        """
        return self.st_status == DataQualityStatus.BLOCKED.value \
            or self.execution_model_status == DataQualityStatus.BLOCKED.value


class DatasetRegistry:
    def __init__(self, store_path: Optional[str] = None):
        here = os.path.dirname(os.path.abspath(__file__))
        self.store_path = store_path or os.path.join(here, "dataset_store.json")
        self._ds: dict[str, DatasetSpec] = {}
        self.load()

    def load(self) -> None:
        self._ds = {}
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for item in data.get("datasets", []):
            spec = DatasetSpec.from_dict(item)
            self._ds[spec.dataset_id] = spec

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        payload = {
            "version": "phase-9a",
            "datasets": [d.to_dict() for d in self._ds.values()],
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return self.store_path

    def register(self, spec: DatasetSpec) -> DatasetSpec:
        # 同 dataset_id 唯一；版本不同视为不同 dataset（id 已含版本语义时例外）
        self._ds[spec.dataset_id] = spec
        return spec

    def get(self, dataset_id: str) -> Optional[DatasetSpec]:
        return self._ds.get(dataset_id)

    def all(self) -> list[DatasetSpec]:
        return list(self._ds.values())

    def __len__(self) -> int:
        return len(self._ds)


def default_full_dataset() -> DatasetSpec:
    """V1/V2 公平比较使用的统一全量数据集（显式带已知缺口）。"""
    return DatasetSpec(
        dataset_id="dataset_v1_full",
        version="1.0",
        date_range="2005-01-01..2024-12-31",
        universe="全市场（过滤688/787，is_st=0 基于当前表，非历史PIT）",
        pit_status="PARTIAL",
        survivorship_status="LIMITED",
        market_cap_status="PARTIAL",
        st_status="BLOCKED",
        execution_model_status="PARTIAL",
        feature_coverage="full_v1_candidate + forward_outcome + regime_pit",
        source_db="/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db",
    )


def build_default_dataset_registry(store_path: Optional[str] = None) -> DatasetRegistry:
    reg = DatasetRegistry(store_path=store_path)
    if reg.get("dataset_v1_full") is None:
        reg.register(default_full_dataset())
    return reg


if __name__ == "__main__":
    r = build_default_dataset_registry()
    p = r.save()
    print(f"dataset registry -> {p}")
    print(f"datasets: {[d.dataset_id for d in r.all()]}")
