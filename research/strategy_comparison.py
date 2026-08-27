#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/strategy_comparison.py — Phase 9-A 十七：Strategy Comparison Contract
==============================================================================

统一比较维度（section 17）：
  Return / Risk / Trade / Execution / Robustness / Data

关键约束（section 十六/十八）：
  * 禁止"冠军策略"思维：输出 QUALIFIED_STRATEGIES，而非单 BEST_STRATEGY。
  * 避免指标作弊：所有分母必须完整记录。
  * Candidate ≠ Signal ≠ Executed Trade（section 11）。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional


def _to_float(v):
    try:
        if v in (None, "UNKNOWN", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(xs):
    vals: list[float] = [_to_float(x) for x in xs if _to_float(x) is not None]  # type: ignore[arg-type]
    return statistics.mean(vals) if vals else None


def _median(xs):
    vals: list[float] = [_to_float(x) for x in xs if _to_float(x) is not None]  # type: ignore[arg-type]
    return statistics.median(vals) if vals else None


def _quantile(xs, q):
    vals: list[float] = sorted(_to_float(x) for x in xs if _to_float(x) is not None)  # type: ignore[arg-type]
    if not vals:
        return None
    idx = min(len(vals) - 1, int(q * len(vals)))
    return vals[idx]


def _max_drawdown(returns):
    """给定每笔收益序列，返回最大回撤（负数为回撤）。"""
    xs: list[float] = [_to_float(r) for r in returns if _to_float(r) is not None]  # type: ignore[arg-type]
    if not xs:
        return None
    peak = 0.0
    equity = 0.0
    mdd = 0.0
    for r in xs:
        equity += r
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


@dataclass
class StrategyComparisonRow:
    """一个策略的可比较指标集合。"""
    strategy_id: str
    strategy_version: str
    run_id: str

    # Return
    cumulative_return: Optional[float] = None
    median_trade_return: Optional[float] = None
    avg_trade_return: Optional[float] = None

    # Risk
    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None
    calmar: Optional[float] = None
    sortino: Optional[float] = None

    # Trade
    win_rate: Optional[float] = None
    payoff_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    trades: int = 0
    holding_period: Optional[float] = None

    # Execution
    turnover: Optional[float] = None
    slippage_sensitivity: Optional[str] = None
    liquidity_failure: Optional[int] = None
    limit_up_block_rate: Optional[float] = None
    limit_down_block_rate: Optional[float] = None

    # Robustness
    time_stability: Optional[str] = None
    regime_stability: Optional[str] = None
    market_cap_stability: Optional[str] = None
    parameter_stability: Optional[str] = None

    # Data
    pit_status: Optional[str] = None
    survivorship_status: Optional[str] = None
    missing_rate: Optional[float] = None
    approximate_data: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "cumulative_return": self.cumulative_return,
            "median_trade_return": self.median_trade_return,
            "avg_trade_return": self.avg_trade_return,
            "max_drawdown": self.max_drawdown,
            "volatility": self.volatility,
            "calmar": self.calmar,
            "sortino": self.sortino,
            "win_rate": self.win_rate,
            "payoff_ratio": self.payoff_ratio,
            "profit_factor": self.profit_factor,
            "trades": self.trades,
            "holding_period": self.holding_period,
            "turnover": self.turnover,
            "slippage_sensitivity": self.slippage_sensitivity,
            "liquidity_failure": self.liquidity_failure,
            "limit_up_block_rate": self.limit_up_block_rate,
            "limit_down_block_rate": self.limit_down_block_rate,
            "time_stability": self.time_stability,
            "regime_stability": self.regime_stability,
            "market_cap_stability": self.market_cap_stability,
            "parameter_stability": self.parameter_stability,
            "pit_status": self.pit_status,
            "survivorship_status": self.survivorship_status,
            "missing_rate": self.missing_rate,
            "approximate_data": self.approximate_data,
        }


class StrategyComparator:
    """从多个 StrategyResearchRun 生成 ComparisonRow（公平、同口径）。"""

    @staticmethod
    def from_run(run, pit_status=None, survivorship_status=None) -> StrategyComparisonRow:
        fwd20 = [r.fwd_20d for r in run.rows]
        known: list[float] = [_to_float(x) for x in fwd20 if _to_float(x) is not None]  # type: ignore[arg-type]
        exec_rows = [r for r in run.rows if r.is_executed]
        wins = sum(1 for x in known if x > 0)
        losses: list[float] = [x for x in known if x < 0]
        gains: list[float] = [x for x in known if x > 0]
        win_rate = (wins / len(known)) if known else None
        avg_gain: float = _mean(gains) if gains else 0.0  # type: ignore[assignment]
        avg_loss: float = abs(_mean(losses)) if losses else 0.0  # type: ignore[arg-type]
        payoff = (avg_gain / avg_loss) if avg_loss else None
        gross_gain: float = sum(gains)
        gross_loss: float = abs(sum(losses))
        profit_factor = (gross_gain / gross_loss) if gross_loss else None
        cumulative: float = sum(known) if known else None  # type: ignore[assignment]
        mdd = _max_drawdown(known)
        vol = statistics.pstdev(known) if len(known) > 1 else None
        calmar = (cumulative / abs(mdd)) if (cumulative is not None and mdd not in (None, 0)) else None
        return StrategyComparisonRow(
            strategy_id=run.strategy_id,
            strategy_version=run.strategy_version,
            run_id=run.run_id,
            cumulative_return=cumulative,
            median_trade_return=_median(known),
            avg_trade_return=_mean(known),
            max_drawdown=mdd,
            volatility=vol,
            calmar=calmar,
            win_rate=win_rate,
            payoff_ratio=payoff,
            profit_factor=profit_factor,
            trades=len(exec_rows),
            pit_status=pit_status,
            survivorship_status=survivorship_status,
        )

    @staticmethod
    def compare(runs_with_meta: list) -> list[StrategyComparisonRow]:
        """
        runs_with_meta: list of (run, pit_status, survivorship_status)
        返回 ComparisonRow 列表（不做排名，仅并列呈现）。
        """
        return [StrategyComparator.from_run(r, pit, surv)
                for (r, pit, surv) in runs_with_meta]


def qualified_strategies(rows: list[StrategyComparisonRow], qualified_ids: list[str]) -> list[str]:
    """返回被标记为 QUALIFIED 的策略 id 列表（非"最佳"）。"""
    ids = {f"{r.strategy_id}@{r.strategy_version}" for r in rows}
    return [q for q in qualified_ids if q in ids]
