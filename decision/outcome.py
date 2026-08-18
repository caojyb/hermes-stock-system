#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Outcome & Learning Foundation（Phase 6）
=================================================
统一 Outcome Contract：Decision → Execution → Position → Exit → Outcome 数据闭环。

原则（Observe first, learn later）：
- Outcome 只记录事实，不自动修改策略
- planned 与 actual 严格分离（评估 Decision 是否正确 vs Execution 是否偏离）
- 历史数据不足 → UNKNOWN/LEGACY/PARTIAL，不伪造
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from uuid import uuid4
from datetime import datetime, timezone

# ═══ 生命周期状态 ═══
DECIDED = 'DECIDED'        # 已决策（未执行/未知执行）
EXECUTED = 'EXECUTED'      # 已执行（未平仓）
OPEN = 'OPEN'              # 持仓中
CLOSED = 'CLOSED'          # 已平仓
CANCELLED = 'CANCELLED'    # 已取消
UNKNOWN = 'UNKNOWN'        # 状态未知
OUTCOME_STATUS = (DECIDED, EXECUTED, OPEN, CLOSED, CANCELLED, UNKNOWN)

# ═══ 统一 Exit Reason（映射现有退出语义，不修改）═══
STOP_LOSS = 'STOP_LOSS'
TAKE_PROFIT = 'TAKE_PROFIT'
TRAILING_STOP = 'TRAILING_STOP'
MA20_EXIT = 'MA20_EXIT'
PORTFOLIO_RISK = 'PORTFOLIO_RISK'
MANUAL_EXIT = 'MANUAL_EXIT'
FORCED_EXIT = 'FORCED_EXIT'
OTHER = 'OTHER'
EXIT_REASONS = (STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, MA20_EXIT,
                PORTFOLIO_RISK, MANUAL_EXIT, FORCED_EXIT, OTHER, UNKNOWN)

# ═══ Outcome 来源（Integrity：decision_id 关联性）═══
SOURCE_DECISION = 'DECISION'   # 有关联 decision_id
SOURCE_LEGACY = 'LEGACY'       # 无 decision_id（历史交易）
SOURCE_SHADOW = 'SHADOW'       # Shadow 策略（主升浪）
SOURCE_UNKNOWN = 'UNKNOWN'

# ═══ Counterfactual 时间窗口 ═══
CF_WINDOWS = (5, 10, 20, 40, 60)


def gen_outcome_id():
    return f"out_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


@dataclass
class Planned:
    """计划（Decision 层）：系统认为应该怎样。"""
    entry_price: float = 0.0
    target_position: float = 0.0
    position_size: float = 0.0
    stop_loss: float = 0.0
    take_profit: list = field(default_factory=list)
    exit_signal: str = ''

    def __bool__(self):
        return bool(self.entry_price or self.target_position or self.position_size)


@dataclass
class Actual:
    """实际（Execution 层）：真实发生了什么。"""
    entry_price: float = 0.0
    position_size: float = 0.0
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    return_pct: float = 0.0


@dataclass
class Excursion:
    """持仓期间波动（MAE/MFE）。数据不足 → UNKNOWN。"""
    mae: float = 0.0     # 最大不利波动（%）<=0
    mfe: float = 0.0     # 最大有利波动（%）>=0
    max_drawdown: float = 0.0
    max_profit: float = 0.0
    status: str = UNKNOWN  # OK / UNKNOWN / PARTIAL


@dataclass
class Counterfactual:
    """NO_TRADE 反事实（最小结构，非真实交易）。"""
    eligible: bool = False
    horizon: int = 0          # 交易日窗口
    hypothetical_entry_price: float = 0.0
    hypothetical_position: float = 0.0
    hypothetical_return: float = 0.0
    hypothetical_mae: float = 0.0
    hypothetical_mfe: float = 0.0
    status: str = UNKNOWN     # COMPUTED / UNKNOWN / NOT_ELIGIBLE


@dataclass
class Outcome:
    """统一 Outcome 对象（不可变，可追溯）。"""
    # 标识
    outcome_id: str = ''
    decision_id: str = ''          # 空 = LEGACY/UNKNOWN（不伪造）
    symbol: str = ''
    name: str = ''
    action: str = ''               # BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE
    strategy: str = ''
    strategy_version: str = ''
    outcome_source: str = SOURCE_LEGACY  # DECISION/LEGACY/SHADOW/UNKNOWN

    # 时间
    decision_time: str = ''
    execution_time: str = ''       # 无真实成交时间 → UNKNOWN（不用 decision 冒充）
    exit_time: str = ''
    as_of_time: str = ''

    # planned vs actual
    planned: Planned = field(default_factory=Planned)
    actual: Actual = field(default_factory=Actual)

    # lifecycle
    lifecycle_status: str = UNKNOWN   # DECIDED/EXECUTED/OPEN/CLOSED/CANCELLED/UNKNOWN
    holding_period_days: int = 0
    exit_reason: str = UNKNOWN
    exit_triggers: list = field(default_factory=list)

    # excursion
    excursion: Excursion = field(default_factory=Excursion)

    # market
    entry_regime: str = ''
    exit_regime: str = ''

    # portfolio provenance
    portfolio_snapshot_id: str = ''

    # provenance
    decision_snapshot_id: str = ''
    config_version: str = ''
    code_version: str = ''

    # counterfactual（仅 NO_TRADE）
    counterfactual: Counterfactual = field(default_factory=Counterfactual)

    # quality（Decision vs Execution 分离）
    decision_quality: str = UNKNOWN   # GOOD/BAD/NEUTRAL/UNKNOWN（评估维度见文档）
    execution_quality: str = UNKNOWN  # GOOD/BAD/NEUTRAL/UNKNOWN

    def freeze(self) -> dict:
        return asdict(self)


def map_exit_reason(triggers):
    """把现有退出语义（STOP_LOSS/TRAILING_STOP/MA20_BREAK...及 legacy 中文 status）映射到统一 Exit Reason。
    不修改任何退出参数/语义。"""
    t = [str(x).upper() for x in (triggers or [])]
    joined = ' '.join(t)
    if not t:
        return UNKNOWN
    # legacy 中文 status 映射
    if '止损' in joined or 'STOP_LOSS' in t:
        return STOP_LOSS
    if '止盈' in joined or 'TAKE_PROFIT' in t or '部分止盈' in joined:
        return TAKE_PROFIT
    if 'TRAILING_STOP' in t or '移动止盈' in joined:
        return TRAILING_STOP
    if 'MA20_BREAK' in t or 'MA20_EXIT' in t or 'MA20' in joined:
        return MA20_EXIT
    if 'PORTFOLIO_RISK' in t or 'DRAWDOWN' in t or 'PORTFOLIO' in joined:
        return PORTFOLIO_RISK
    if 'FORCED' in t:
        return FORCED_EXIT
    if 'MANUAL' in t or '人工' in joined:
        return MANUAL_EXIT
    return OTHER
