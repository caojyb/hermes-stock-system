#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Risk Regression Tests（Phase 8-G0.1）

覆盖：
1. check_portfolio_drawdown_v2 正常输入
2. check_portfolio_drawdown_v2 异常输入（malformed）
3. check_portfolio_drawdown_v2 空输入
4. check_portfolio_drawdown_v2 legacy 输入（旧表结构/缺失列场景，通过 monkeypatch 模拟）
5. check_portfolio_drawdown_v2 production-shaped 输入（模拟真实 2026-08-21 数据）
6. assess_portfolio 正常输入
7. assess_portfolio 异常输入
8. assess_portfolio 空输入
9. assess_portfolio legacy 输入
10. assess_portfolio regression（确保风控规则不变）
"""
from __future__ import annotations

import sqlite3
import pytest
from unittest.mock import patch
from datetime import date, timedelta

# 确保可导入
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision.portfolio import assess_portfolio
from risk_controller_v2 import check_portfolio_drawdown_v2


# ── Fixtures ──
@pytest.fixture
def mem_conn():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, total_value REAL, cash REAL,
            holdings_value REAL, total_return_pct REAL,
            max_drawdown_pct REAL, win_count INTEGER, loss_count INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    cur.execute('''
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT, name TEXT, sector TEXT,
            buy_date TEXT, buy_price REAL, buy_shares INTEGER,
            buy_amount REAL, sell_date TEXT, sell_price REAL,
            sell_amount REAL, profit_pct REAL, profit_amount REAL,
            status TEXT, signal_type TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            hold_mode TEXT DEFAULT 'normal'
        )
    ''')
    cur.execute('''
        CREATE TABLE klines (
            code TEXT, date TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, amount REAL, adjust_flag REAL,
            turn REAL, pct_chg REAL
        )
    ''')
    con.commit()
    yield con
    con.close()


def _insert_snapshot(cur, date_str, total_value, cash=None, holdings_value=None):
    cur.execute('''
        INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value, total_return_pct, max_drawdown_pct, win_count, loss_count)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (date_str, total_value, cash, holdings_value, 0.0, 0.0, 0, 0))


# ── 1. check_portfolio_drawdown_v2 正常输入 ──
def test_risk_controller_drawdown_normal(mem_conn):
    cur = mem_conn.cursor()
    today = date.today().isoformat()
    for i in range(5):
        d = (date.today() - timedelta(days=i)).isoformat()
        _insert_snapshot(cur, d, 1_000_000 - i * 10_000)
    mem_conn.commit()

    with patch('risk_controller_v2.check_liquidity_crisis', return_value=(False, '', '')):
        action, msgs = check_portfolio_drawdown_v2(mem_conn, force_report=False)
    assert action == 'none'
    assert not msgs


# ── 2. check_portfolio_drawdown_v2 异常输入（malformed）──
def test_risk_controller_drawdown_malformed(mem_conn):
    cur = mem_conn.cursor()
    today = date.today().isoformat()
    # 插入 total_value 为字符串的异常行
    cur.execute('INSERT INTO portfolio_snapshots (date,total_value) VALUES (?,?)', (today, 'not_a_number'))
    mem_conn.commit()

    with patch('risk_controller_v2.check_liquidity_crisis', return_value=(False, '', '')):
        action, msgs = check_portfolio_drawdown_v2(mem_conn, force_report=False)
    # fail-safe：异常行被跳过，空结果 → none
    assert action == 'none'
    assert msgs == []


# ── 3. check_portfolio_drawdown_v2 空输入 ──
def test_risk_controller_drawdown_empty(mem_conn):
    with patch('risk_controller_v2.check_liquidity_crisis', return_value=(False, '', '')):
        action, msgs = check_portfolio_drawdown_v2(mem_conn, force_report=False)
    assert action == 'none'
    assert msgs == []


# ── 4. check_portfolio_drawdown_v2 legacy 输入（旧数据 total_value 为 None）──
def test_risk_controller_drawdown_legacy(mem_conn):
    cur = mem_conn.cursor()
    today = date.today().isoformat()
    _insert_snapshot(cur, today, None)
    mem_conn.commit()

    with patch('risk_controller_v2.check_liquidity_crisis', return_value=(False, '', '')):
        action, msgs = check_portfolio_drawdown_v2(mem_conn, force_report=False)
    assert action == 'none'


# ── 5. check_portfolio_drawdown_v2 production-shaped 输入 ──
def test_risk_controller_drawdown_production_shaped(mem_conn):
    cur = mem_conn.cursor()
    today = date.today().isoformat()
    # 模拟真实回撤 >15%
    _insert_snapshot(cur, '2026-08-11', 1_000_000)
    _insert_snapshot(cur, today, 800_000)
    mem_conn.commit()

    with patch('risk_controller_v2.check_liquidity_crisis', return_value=(False, '', '')):
        action, msgs = check_portfolio_drawdown_v2(mem_conn, force_report=False)
    assert action == 'trim'
    assert any('减仓' in m for m in msgs)


# ── 6. assess_portfolio 正常输入 ──
def test_assess_portfolio_normal():
    pa = assess_portfolio(candidate_sector='电子', target_position=50_000,
                          total_capital=1_000_000, position_count=5,
                          max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'电子': 2},
                          drawdown=0.10, drawdown_limit=0.15)
    assert pa['allowed'] is True
    assert pa['action'] == 'OK'


# ── 7. assess_portfolio 异常输入 ──
def test_assess_portfolio_malformed():
    # total_capital 为 0 应 fail-safe
    pa = assess_portfolio(candidate_sector='电子', target_position=50_000,
                          total_capital=0, position_count=5)
    assert pa['allowed'] is False
    assert 'EXPOSURE_BLOCKED' in pa['reason_codes'] or 'PORTFOLIO_RISK_BLOCKED' in pa['reason_codes']


# ── 8. assess_portfolio 空输入 ──
def test_assess_portfolio_empty():
    pa = assess_portfolio()
    assert pa['allowed'] is True
    assert pa['action'] == 'OK'


# ── 9. assess_portfolio legacy 输入（drawdown=None）──
def test_assess_portfolio_legacy():
    pa = assess_portfolio(candidate_sector='医药', target_position=10_000,
                          total_capital=1_000_000, position_count=0,
                          drawdown=None, drawdown_status='UNKNOWN')
    assert pa['allowed'] is False
    assert 'DRAWDOWN_UNKNOWN' in pa['reason_codes']


# ── 10. assess_portfolio regression（阈值不漂移）──
def test_assess_portfolio_regression():
    # 回测已知阈值：drawdown=0.15 应刚好触发
    pa = assess_portfolio(candidate_sector='电子', target_position=10_000,
                          total_capital=1_000_000, position_count=0,
                          drawdown=0.15, drawdown_limit=0.15)
    assert pa['allowed'] is False
    assert 'DRAWDOWN_BLOCKED' in pa['reason_codes']
