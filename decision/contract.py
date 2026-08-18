#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Contract — 统一决策契约（Phase 2）

定义三层模型（Evidence / Assessment / Decision）的最终 Decision 数据结构，
统一 action 枚举与 reason_codes。本模块为纯定义 + 工具函数，不连库、无副作用。

原则：
- Evidence / Assessment 不得直接等价为 Final Decision。
- 所有最终 BUY/HOLD/SELL/NO_TRADE 都通过 Decision Engine（唯一拍板）产出。
- Decision 产生后可冻结为 Snapshot，后续配置变化不改变历史 Decision。
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

# ═══ 统一 action（最终决策唯一枚举）═══
BUY = 'BUY'
HOLD = 'HOLD'
SELL = 'SELL'
NO_TRADE = 'NO_TRADE'
REDUCE = 'REDUCE'   # 持仓管理：减仓（目标仓位 < 当前）
ADD = 'ADD'         # 持仓管理：加仓（目标仓位 > 当前）
ACTIONS = (BUY, HOLD, SELL, NO_TRADE, REDUCE, ADD)

# ═══ Assessment 级别 ═══
# Evidence: 底层事实/信号（信号A/B/C/D、量比、ATR、评分…）
# Assessment: 模块对 Evidence 的专业判断（entry=CONFIRMED、regime=HIGH_VOLATILITY…）
# Decision: 最终系统决定（BUY/HOLD/SELL/NO_TRADE）

# ═══ 统一 reason_codes ═══
REASON = {
    # regime
    'REGIME_ALLOWED': 'REGIME_ALLOWED',
    'REGIME_BLOCKED': 'REGIME_BLOCKED',
    'HIGH_VOLATILITY': 'HIGH_VOLATILITY',
    'LOW_VOLUME': 'LOW_VOLUME',
    'SIDEWAYS': 'SIDEWAYS',
    'STRONG_TREND': 'STRONG_TREND',
    # permission
    'PERMISSION_ALLOWED': 'PERMISSION_ALLOWED',
    'PERMISSION_BLOCKED': 'PERMISSION_BLOCKED',
    'MAX_POSITION_REACHED': 'MAX_POSITION_REACHED',
    # data
    'DATA_VALID': 'DATA_VALID',
    'DATA_DEGRADED': 'DATA_DEGRADED',
    'DATA_STALE': 'DATA_STALE',
    'DATA_INVALID': 'DATA_INVALID',
    'DATA_MISSING': 'DATA_MISSING',
    # candidate
    'CANDIDATE_PASS': 'CANDIDATE_PASS',
    'CANDIDATE_FAIL': 'CANDIDATE_FAIL',
    # entry
    'ENTRY_CONFIRMED': 'ENTRY_CONFIRMED',
    'ENTRY_INSUFFICIENT': 'ENTRY_INSUFFICIENT',
    'SIGNAL_INSUFFICIENT': 'SIGNAL_INSUFFICIENT',
    # portfolio risk
    'PORTFOLIO_RISK_OK': 'PORTFOLIO_RISK_OK',
    'PORTFOLIO_RISK_BLOCKED': 'PORTFOLIO_RISK_BLOCKED',
    'DRAWDOWN_BLOCKED': 'DRAWDOWN_BLOCKED',
    'EXPOSURE_BLOCKED': 'EXPOSURE_BLOCKED',
    'LIQUIDITY_BLOCKED': 'LIQUIDITY_BLOCKED',
    'COOLDOWN': 'COOLDOWN',
    # exit
    'STOP_LOSS': 'STOP_LOSS',
    'TAKE_PROFIT': 'TAKE_PROFIT',
    'TRAILING_STOP': 'TRAILING_STOP',
    'MA20_EXIT': 'MA20_EXIT',
    'FORCED_EXIT': 'FORCED_EXIT',
    'EXIT_SIGNAL': 'EXIT_SIGNAL',
}

# ═══ Assessment 级别常量 ═══
# entry assessment
ENTRY_CONFIRMED = 'CONFIRMED'
ENTRY_INSUFFICIENT = 'INSUFFICIENT'
ENTRY_NONE = 'NONE'
# exit assessment
EXIT_NONE = 'NONE'
EXIT_NORMAL = 'NORMAL'
EXIT_RISK = 'RISK'
EXIT_FORCED = 'FORCED'
# portfolio risk assessment
RISK_OK = 'OK'
RISK_BLOCKED = 'BLOCKED'
# candidate assessment
CANDIDATE_QUALIFIED = 'QUALIFIED'
CANDIDATE_FAIL = 'FAIL'


def gen_decision_id(symbol: str = '', ts: str = '') -> str:
    """生成唯一 decision_id：短 uuid + symbol + 时间戳（唯一、可关联）。"""
    uid = uuid.uuid4().hex[:12]
    sym = (symbol or 'NA').replace('.', '')
    t = (ts or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    return f'{t}_{sym}_{uid}'


@dataclass
class Decision:
    """统一最终决策。可独立描述一次完整交易判断。"""
    # 标识与时间
    decision_id: str = ''
    timestamp: str = ''          # 决策生成时刻（UTC ISO）
    as_of_time: str = ''         # 决策所依据的数据截止时刻
    symbol: str = ''
    name: str = ''
    action: str = NO_TRADE       # BUY/HOLD/SELL/NO_TRADE

    # market & regime（Evidence/Assessment）
    market_regime: str = ''      # 如 HIGH_VOLATILITY
    regime_label: str = ''
    regime_score: float = 0.0
    regime_version: str = ''

    # trading permission（Assessment）
    permission_status: str = ''  # ALLOW/REDUCE/NO_NEW_ENTRY/EXIT_ONLY
    permission: dict = field(default_factory=dict)  # new_entry/add_position/reduce_position/exit_position

    # strategy
    strategy: str = ''
    strategy_version: str = ''

    # candidate（Assessment）
    candidate_qualified: bool = False
    candidate_score: float = 0.0
    candidate_rank: int = 0

    # entry（Assessment + Evidence components）
    entry_signal: str = ENTRY_NONE
    entry_signals: list = field(default_factory=list)  # ['A','B','D']
    entry_components: dict = field(default_factory=dict)

    # planned execution（Position Sizing 产物，Decision 只接收不重算）
    reference_price: float = 0.0
    target_position: float = 0.0

    # position management（Phase 5：真实持仓统一 Decision，动作+目标仓位分离）
    current_position: float = 0.0   # 当前仓位（占组合）
    delta_position: float = 0.0     # 建议调整量 = target - current

    # portfolio context（Assessment）
    portfolio_drawdown: float = 0.0
    position_count: int = 0
    has_position: bool = False
    current_exposure: float = 0.0

    # risk（Assessment）
    stop_loss: float = 0.0
    take_profit: list = field(default_factory=list)
    trailing_stop: float = 0.0
    risk_flags: list = field(default_factory=list)

    # exit（Assessment + triggers）
    exit_signal: str = EXIT_NONE
    exit_triggers: list = field(default_factory=list)

    # final
    reason_codes: list = field(default_factory=list)
    explanation: str = ''

    # provenance（Decision Freeze 关键）
    data_snapshot_id: str = ''
    config_version: str = ''
    code_version: str = ''
    # Phase 5.5: Real Portfolio provenance（Decision → Portfolio Snapshot 反查）
    portfolio_snapshot_id: str = ''
    portfolio_source: str = ''
    portfolio_as_of_time: str = ''

    def freeze(self) -> dict:
        """冻结为不可变 dict（Decision Snapshot）。"""
        return asdict(self)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'Decision':
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
