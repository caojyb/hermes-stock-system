#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/validation_contracts.py — Phase 9-A 二十四/二十五/三十二
================================================================

Shadow Validation Contract（section 24）：
  QUALIFIED 策略不能直接进入 Production。必须 QUALIFIED → SHADOW。
  Shadow 至少记录：candidate / signal / hypothetical entry / hypothetical exit /
  hypothetical trade / MAE-MFE / regime / timestamp。
  且 shadow ≠ production。

Forward Validation Contract（section 25）：
  每个策略必须保留：strategy_id / strategy_version / validation_start /
  validation_dataset_version。
  多个策略可以同日起跑，但独立记账。

Reproducibility（section 32）：
  任意研究可经 (strategy_id, strategy_version, dataset_id, dataset_version,
  run_id) 重现。必须记录：code_version / config_version / data_version /
  execution_version / cost_version / random_seed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShadowRecord:
    """单条 Shadow 记录（hypothetical，非真实交易）。"""
    strategy_id: str
    strategy_version: str
    shadow_id: str
    symbol: str
    candidate_date: str
    signal_date: Optional[str] = None
    hypothetical_entry_date: Optional[str] = None
    hypothetical_entry_price: Optional[float] = None
    hypothetical_exit_date: Optional[str] = None
    hypothetical_exit_price: Optional[float] = None
    mae: object = None
    mfe: object = None
    regime: Optional[str] = None
    timestamp: Optional[str] = None
    is_production: bool = False     # 强制 False：shadow ≠ production

    def validate_not_production(self) -> bool:
        return self.is_production is False


@dataclass
class ForwardValidationRecord:
    """前向验证记录（独立记账）。"""
    strategy_id: str
    strategy_version: str
    validation_start: str
    validation_dataset_version: str
    # 独立记账字段
    run_id: Optional[str] = None
    strategy_specific_ledger: bool = True   # section 23：策略专属分类账
    notes: str = ""

    def partition_key(self) -> str:
        """用于分区的唯一键（strategy_id + version）。"""
        return f"{self.strategy_id}@{self.strategy_version}"


@dataclass
class ReproducibilityManifest:
    """研究可重现性清单（section 32）。"""
    strategy_id: str
    strategy_version: str
    dataset_id: str
    dataset_version: str
    run_id: str
    code_version: str = "UNKNOWN"
    config_version: str = "UNKNOWN"
    data_version: str = "UNKNOWN"
    execution_version: str = "UNKNOWN"
    cost_version: str = "UNKNOWN"
    random_seed: Optional[int] = None

    def is_reproducible(self) -> bool:
        required = [self.code_version, self.config_version, self.data_version,
                    self.execution_version, self.cost_version]
        return all(v not in (None, "UNKNOWN", "") for v in required)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "run_id": self.run_id,
            "code_version": self.code_version,
            "config_version": self.config_version,
            "data_version": self.data_version,
            "execution_version": self.execution_version,
            "cost_version": self.cost_version,
            "random_seed": self.random_seed,
            "reproducible": self.is_reproducible(),
        }
