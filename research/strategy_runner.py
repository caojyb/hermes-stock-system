#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/strategy_runner.py — Phase 9-A 六/二十三：统一 Historical Research Pipeline
=====================================================================================

目标：
  StrategySpec + Dataset + DateRange
  → StrategyResearchRun（统一口径输出）

统一保证（不同策略不能偷偷使用不同计算口径）：
  - 同样的 outcome 计算（复用 research.forward_outcome）
  - 同样的 PIT（复用 research.candidate_pit / regime_pit）
  - 同样的 execution_model_version / cost_model_version 记录
  - 每笔记录带 strategy_id + strategy_version + run_id（独立记账）

StrategyResearchRun 包含（section 6）：
  candidate rows / signal rows / entry rows / exit rows / trade rows
  5D / 10D / 20D / MAE / MFE / holding period / drawdown / turnover / cost impact

本 runner 不实现具体策略逻辑，而是作为统一"执行器"：
  - 接收一个 StrategyResearchAdapter（产生 candidate/signal），调用统一 outcome 层。
  - 所有策略共享同一 forward_outcome 计算，杜绝口径漂移。

V1 adapter 见 research/adapters/v1_adapter.py（不修改 V1）。
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import research.forward_outcome as forward_outcome  # 统一 outcome 口径

HORIZONS = forward_outcome.HORIZONS  # (5, 10, 20)


@dataclass
class TradeLedgerRow:
    """独立记账的最小交易记录（section 23）。"""
    strategy_id: str
    strategy_version: str
    run_id: str
    symbol: str
    candidate_date: str
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    fwd_5d: object = forward_outcome.UNKNOWN
    fwd_10d: object = forward_outcome.UNKNOWN
    fwd_20d: object = forward_outcome.UNKNOWN
    mae: object = forward_outcome.UNKNOWN
    mfe: object = forward_outcome.UNKNOWN
    regime: Optional[str] = None
    is_signal: bool = False       # candidate vs signal 分层（section 11）
    is_executed: bool = False     # 是否真正进场（execution feasibility）


@dataclass
class StrategyResearchRun:
    """一次统一研究运行的结果（不可变语义的汇总）。"""
    strategy_id: str
    strategy_version: str
    run_id: str
    dataset_id: str
    dataset_version: str
    execution_model_version: str
    cost_model_version: str
    date_range: str
    regimes: dict = field(default_factory=dict)

    candidate_n: int = 0
    signal_n: int = 0
    entry_n: int = 0
    trade_n: int = 0
    # 样本充足性分离（section 20）
    independent_trade_n: Optional[int] = None
    period_n: Optional[int] = None
    regime_n: Optional[int] = None

    rows: list = field(default_factory=list)   # list[TradeLedgerRow]

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "execution_model_version": self.execution_model_version,
            "cost_model_version": self.cost_model_version,
            "date_range": self.date_range,
            "regimes": self.regimes,
            "candidate_n": self.candidate_n,
            "signal_n": self.signal_n,
            "entry_n": self.entry_n,
            "trade_n": self.trade_n,
            "independent_trade_n": self.independent_trade_n,
            "period_n": self.period_n,
            "regime_n": self.regime_n,
            "rows": [r.__dict__ for r in self.rows],
        }


class StrategyResearchAdapter:
    """
    抽象适配器：子类实现 build_candidates()，返回统一格式的 candidate dict 列表。
    每个 candidate dict 需含：symbol, candidate_date, is_signal(bool)。
    runner 统一计算 entry_price（T+1 open）与 forward outcome。

    具体策略（V1 / V2 ...）提供自己的 adapter，但 outcome 计算必须走统一层。
    """

    def __init__(self, strategy_id: str, strategy_version: str):
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version

    def build_candidates(self, dataset, date_range) -> list[dict]:
        raise NotImplementedError("subclass must implement build_candidates")

    def strategy_signature(self) -> str:
        return f"{self.strategy_id}@{self.strategy_version}"


class StrategyRunner:
    """
    统一执行器。接收 adapter + dataset，产出 StrategyResearchRun。
    关键：所有 outcome 用 forward_outcome 统一计算。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or forward_outcome.DEFAULT_DB

    def run(self, adapter: StrategyResearchAdapter, dataset_id: str,
            dataset_version: str, date_range: str,
            execution_model_version: str, cost_model_version: str,
            candidates: list[dict], regimes: Optional[dict] = None) -> StrategyResearchRun:
        run_id = uuid.uuid4().hex[:12]
        run = StrategyResearchRun(
            strategy_id=adapter.strategy_id,
            strategy_version=adapter.strategy_version,
            run_id=run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            execution_model_version=execution_model_version,
            cost_model_version=cost_model_version,
            date_range=date_range,
            regimes=regimes or {},
        )

        import sqlite3
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
        try:
            rows = []
            cand = 0
            sig = 0
            for c in candidates:
                symbol: str = str(c.get("symbol") or "")
                cand_date: str = str(c.get("candidate_date") or "")
                is_sig = bool(c.get("is_signal", False))
                # entry_price = T+1 开盘（统一语义）
                entry_price = None
                try:
                    cur = con.cursor()
                    cur.execute(
                        "SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
                        (symbol, cand_date),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        entry_price = float(row[0])
                except sqlite3.Error:
                    entry_price = None
                cand_dict = {
                    "symbol": symbol,
                    "candidate_date": cand_date,
                    "entry_price": entry_price,
                    "entry_date": None,
                    "as_of_date": cand_date,
                }
                out = forward_outcome.compute_one(cand_dict, con)
                regime = (regimes or {}).get(cand_date)
                ledger = TradeLedgerRow(
                    strategy_id=adapter.strategy_id,
                    strategy_version=adapter.strategy_version,
                    run_id=run_id,
                    symbol=symbol,
                    candidate_date=cand_date,
                    entry_date=None,
                    entry_price=entry_price,
                    exit_date=None,
                    exit_price=None,
                    fwd_5d=out.get("fwd_5d"),
                    fwd_10d=out.get("fwd_10d"),
                    fwd_20d=out.get("fwd_20d"),
                    mae=out.get("mae"),
                    mfe=out.get("mfe"),
                    regime=regime,
                    is_signal=is_sig,
                    is_executed=(entry_price is not None),
                )
                rows.append(ledger)
                cand += 1
                if is_sig:
                    sig += 1
        finally:
            con.close()

        run.rows = rows
        run.candidate_n = cand
        run.signal_n = sig
        run.trade_n = sum(1 for r in rows if r.is_executed)
        run.entry_n = run.trade_n
        return run


def build_run_id() -> str:
    return uuid.uuid4().hex[:12]
