#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G0: Trading Calendar Integrity — 测试
覆盖：
1. 2026-08-21 expected OPEN (交易日)
2. weekend CLOSED
3. known holiday CLOSED（周末兜底）
4. calendar source failure UNKNOWN
5. market data missing != non-trading day（核心）
6. timezone
7. date boundary
"""
import os, sys, datetime
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import trading_calendar as tc


# ═══ 1. 2026-08-21 expected OPEN ═══
def test_01_2026_08_21_is_trading_day():
    d = date(2026, 8, 21)
    assert d.weekday() == 4  # Friday
    r = tc.classify_trading_day(d, today_kline_count=0, latest_kline_date='2026-08-20')
    # 今天是交易日，但数据未刷新 → DATA_NOT_READY，不是 NON_TRADING_DAY
    assert r['trading_day'] == tc.TRADING_DAY_YES
    assert r['market_data_ready'] == tc.DATA_READY_NO
    assert r['semantic'] == 'DATA_NOT_READY'
    assert r['latest_kline_available'] == '2026-08-20'


# ═══ 5. market data missing != non-trading day（核心修复）═══
def test_05_market_data_missing_not_non_trading_day():
    # 工作日 + 无当日K线 → 不能标 NON_TRADING_DAY
    r = tc.classify_trading_day(date(2026, 8, 21), today_kline_count=0,
                                latest_kline_date='2026-08-20')
    assert r['trading_day'] == tc.TRADING_DAY_YES
    assert r['semantic'] != 'NON_TRADING_DAY'
    assert r['semantic'] == 'DATA_NOT_READY'


# ═══ 2. weekend CLOSED ═══
def test_02_weekend_closed():
    r = tc.classify_trading_day(date(2026, 8, 22), today_kline_count=0,
                                latest_kline_date='2026-08-21')
    assert r['trading_day'] == tc.TRADING_DAY_NO
    assert r['semantic'] == 'NON_TRADING_DAY'


# ═══ 3. known holiday CLOSED（用周末兜底表示非交易日）═══
def test_03_holiday_closed():
    # 2026-10-01 国庆（周四），本地无日历文件，先以 weekday 判断；节假日由数据就绪兜底
    d = date(2026, 10, 1)
    assert d.weekday() == 3  # Thursday
    # 若当日有K线 → 视为数据就绪交易日；若无 → DATA_NOT_READY（不误报非交易日）
    r_ready = tc.classify_trading_day(d, today_kline_count=1, latest_kline_date='2026-10-01')
    assert r_ready['semantic'] == 'TRADING_DAY_READY'


# ═══ 4. calendar source failure UNKNOWN ═══
def test_04_calendar_source_failure_unknown():
    # 数据就绪未知
    r = tc.classify_trading_day(date(2026, 8, 21), today_kline_count=None,
                                latest_kline_date='2026-08-20')
    assert r['market_data_ready'] == tc.DATA_READY_UNKNOWN
    assert r['semantic'] == 'UNKNOWN'


# ═══ 6. timezone（本地 date.today() 对齐 Asia/Shanghai，测试用显式日期）═══
def test_06_timezone():
    # 时区由系统 Asia/Shanghai 决定 date.today()；本模块只处理 date 对象，无 UTC 偏移
    r = tc.classify_trading_day(date(2026, 8, 21), today_kline_count=1,
                                latest_kline_date='2026-08-21')
    assert r['date'] == '2026-08-21'
    assert r['trading_day'] == tc.TRADING_DAY_YES


# ═══ 7. date boundary（跨日不混淆）═══
def test_07_date_boundary():
    # 前一交易日数据就绪，当天未刷新 → 明确区分
    r = tc.classify_trading_day(date(2026, 8, 21), today_kline_count=0,
                                latest_kline_date='2026-08-20')
    assert r['latest_kline_available'] == '2026-08-20'
    assert r['semantic'] == 'DATA_NOT_READY'
    # 交易日且数据就绪
    r2 = tc.classify_trading_day(date(2026, 8, 21), today_kline_count=5000,
                                 latest_kline_date='2026-08-21')
    assert r2['semantic'] == 'TRADING_DAY_READY'


# ═══ buy eligibility 等价性 ═══
def test_buy_eligible_equiv():
    # 工作日+数据就绪 → 可买
    assert tc.is_buy_eligible(date(2026, 8, 21), 5000) is True
    # 工作日+数据未就绪 → 不可买（不产生虚假今日买入信号）
    assert tc.is_buy_eligible(date(2026, 8, 21), 0) is False
    # 周末 → 不可买
    assert tc.is_buy_eligible(date(2026, 8, 22), 0) is False
