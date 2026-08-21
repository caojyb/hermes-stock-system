#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Calendar & Data-Readiness Semantics (Phase 8-G0 / CALENDAR_INFRA_FIX)
============================================================================
目标：区分三个独立状态，禁止混为一谈：
- TRADING_DAY       : 今天是不是交易日（日历事实）
- MARKET_DATA_READY : 当天行情是否已刷新（数据就绪）
- LATEST_KLINE_AVAILABLE : 数据库里最新K线日期

核心缺陷修复：此前 double_monitor.py 用 `today_kline_count > 0` 反推交易日，
把"行情未刷新"误判为"非交易日"（2026-08-21 盘中触发时出现）。
本模块提供权威语义判断，不修改任何交易规则。

Authority：
- 日历工作日：weekday 判断（周一至五）
- 节假日：本地无权威交易所休市日历文件；节假日由"当日无K线 + 非周末"在
  double_monitor 侧 fail-safe 兜底（不产生虚假买入信号）。
  本模块对"工作日但无当日K线"标记 DATA_NOT_READY，而非 NON_TRADING_DAY。
"""
from __future__ import annotations
from datetime import date, datetime

# 三个独立状态
TRADING_DAY_YES = 'YES'
TRADING_DAY_NO = 'NO'
TRADING_DAY_UNKNOWN = 'UNKNOWN'

DATA_READY_YES = 'YES'
DATA_READY_NO = 'NO'
DATA_READY_UNKNOWN = 'UNKNOWN'


def is_weekday(d: date) -> bool:
    """周一至周五 = True（不判断节假日，节假日由数据就绪兜底）。"""
    return d.weekday() < 5


def classify_trading_day(d: date | None = None, today_kline_count: int | None = None,
                         latest_kline_date: str | None = None) -> dict:
    """返回交易日/数据就绪/最新K线三态诊断。

    Args:
        d: 目标日期（默认今天）
        today_kline_count: 当天K线条数（None 表示未知）
        latest_kline_date: 数据库最新K线日期（YYYY-MM-DD）
    """
    d = d or date.today()
    today_str = d.isoformat()

    # 1. TRADING_DAY：日历工作日判断（非周末）
    trading_day = TRADING_DAY_YES if is_weekday(d) else TRADING_DAY_NO

    # 2. MARKET_DATA_READY：当天K线是否已刷新
    if today_kline_count is None:
        data_ready = DATA_READY_UNKNOWN
    else:
        data_ready = DATA_READY_YES if today_kline_count > 0 else DATA_READY_NO

    # 3. LATEST_KLINE_AVAILABLE
    latest_kline = latest_kline_date or None

    # 语义：工作日但无当日K线 → DATA_NOT_READY（不是 NON_TRADING_DAY）
    if trading_day == TRADING_DAY_YES and data_ready == DATA_READY_NO:
        semantic = 'DATA_NOT_READY'
        message = (f"今日 {today_str} 为交易日但行情未刷新（无当日K线），"
                   f"跳过买入扫描，仅监控持仓与摘要")
    elif trading_day == TRADING_DAY_NO:
        semantic = 'NON_TRADING_DAY'
        message = f"今日 {today_str} 非交易日（周末/休市），跳过买入扫描"
    elif data_ready == DATA_READY_UNKNOWN:
        semantic = 'UNKNOWN'
        message = f"今日 {today_str} 数据就绪状态未知"
    else:
        semantic = 'TRADING_DAY_READY'
        message = f"今日 {today_str} 交易日且数据就绪"

    return {
        'date': today_str,
        'trading_day': trading_day,
        'market_data_ready': data_ready,
        'latest_kline_available': latest_kline,
        'semantic': semantic,
        'message': message,
    }


def is_buy_eligible(d: date | None = None, today_kline_count: int | None = 0) -> bool:
    """买入资格：必须是交易日（工作日）AND 当天数据就绪。
    保持与原 IS_TRADING_DAY=today_kline_count>0 等价的行为，
    但语义更准（非工作日或数据未就绪都返回 False）。
    """
    if not is_weekday(d or date.today()):
        return False
    return bool(today_kline_count and today_kline_count > 0)


if __name__ == '__main__':
    import json
    # 2026-08-21 = Friday，盘中触发但当日K线未刷新
    r = classify_trading_day(date(2026, 8, 21), today_kline_count=0,
                             latest_kline_date='2026-08-20')
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print('buy_eligible:', is_buy_eligible(date(2026, 8, 21), 0))
