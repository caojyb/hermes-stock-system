#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V1 Forward Validation Baseline（Phase 8-J0D）。
单一权威的验证期边界定义。Evaluation 查询必须使用本模块常量做 date filter。

本模块只定义边界元数据，不包含任何业务逻辑，不修改任何数据。

Historical data was NOT deleted or modified — reset 是逻辑边界，非 data reset。
"""

# ── 新 V1 Forward Validation 边界 ──
VALIDATION_START_DATE = '2026-08-27'
VALIDATION_PLANNED_END = '2026-09-05'
MIN_TRADING_DAYS = 20
MIN_VALIDATION_TRADES = 10

# ── 旧区间（PRE_FIX_LEGACY_RESULT，仅审计用，禁入新评价）──
PRE_FIX_VALIDATION_START = '2026-08-09'
PRE_FIX_VALIDATION_END = '2026-08-26'

# ── 新期间初始状态（来源：2026-08-26 收盘 simulation.db 真实值）──
INITIAL_CASH = 781471.12
INITIAL_HOLDINGS_VALUE = 0.0
INITIAL_OPEN_POSITIONS = 0
INITIAL_TOTAL_ASSET = 781471.12
INITIAL_DRAWDOWN = 0.0

CONTAMINATION_TYPE = 'VALUATION_LAYER_CONTAMINATION_ONLY'
RESET_REASON = 'RESET_REQUIRED (J0C audit: all 11 NAV records in old period contaminated)'


def is_validation_trade(trade_date: str) -> bool:
    """某交易日期是否落入新 V1 Forward Validation 期间。"""
    return trade_date >= VALIDATION_START_DATE


def validation_gate_status(trading_days: int, validation_trades: int) -> str:
    """Gate 判定：样本不足必须 DATA_INSUFFICIENT，禁止提前评价。"""
    if trading_days < MIN_TRADING_DAYS or validation_trades < MIN_VALIDATION_TRADES:
        return 'DATA_INSUFFICIENT'
    return 'EVALUABLE'
