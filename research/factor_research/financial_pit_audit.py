#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/financial_pit_audit.py — Phase 9-B.1 Part A：财务 PIT 完成审计
=======================================================================================

结论（实测自 market_cache.db，19 张表全局审计）：
  * 全库无任何 announcement_date / publish_date / disclosure_date / effective_date 字段。
  * financial_data 仅有 report_date + fetched_at；fetched_at 中位较 report_date 滞后
    ~2606 天（≈7 年），系批量 reload 产物，不能当作披露日。
  * akshare 财务上游接口仅返回 REPORT_DATE，无披露日。
  * pe_pb_data 含 pe_ttm/pb_mrq/pe_pct/pb_pct，但仅 2026-05~07 共 14 个 fetch_date 的快照序列，
    非“按报告期”的历史估值序列 → 仅支持“近期估值快照”因子，不支持历史估值 PIT。
  * 因此：财务因子无法从本地数据变为 PIT_READY；维持 PIT_APPROXIMATE（report_date 代理），
    且因披露滞后不可证明 → 存在潜在 future leakage → 仅能 PARTIAL，不得进入严格 Qualification。

本模块产出 FINANCIAL_PIT_SOURCE_MATRIX 与披露滞后量化，不伪造任何日期。
"""

from __future__ import annotations

import os
import sys
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"


@dataclass
class FinancialPitRow:
    factor: str
    source_table: str
    report_date: str
    announcement_date: str
    effective_date: str
    available_at: str
    pit_status: str
    coverage: str
    notes: str = ""


def _connect():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    con.text_factory = str
    return con


def audit_financial_pit() -> list[FinancialPitRow]:
    """
    生成 FINANCIAL_PIT_SOURCE_MATRIX。所有 announcement_date/effective_date 均为 'UNAVAILABLE'。
    """
    con = _connect()
    # 披露滞后量化（fetched_at - report_date，仅作上界，证明不可用）
    lag_rows = con.execute(
        "SELECT report_date, fetched_at FROM financial_data "
        "WHERE fetched_at IS NOT NULL AND fetched_at >= report_date "
        "AND report_date >= '2015-01-01' LIMIT 20000").fetchall()
    import datetime as dt
    lags = []
    for rd, fa in lag_rows:
        try:
            lags.append((dt.datetime.strptime(fa[:10], "%Y-%m-%d") -
                         dt.datetime.strptime(rd[:10], "%Y-%m-%d")).days)
        except Exception:
            pass
    lags.sort()
    median_lag = lags[len(lags) // 2] if lags else -1
    p90_lag = lags[int(len(lags) * 0.9)] if lags else -1
    con.close()

    lag_note = (f"fetched_at 中位较 report_date 滞后 {median_lag} 天(p90={p90_lag})，"
                f"系批量 reload，不能作披露日；披露滞后不可证明 → 潜在 future leakage")

    rows = [
        FinancialPitRow("QUALITY_ROE", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at(滞后~2606d)", "PIT_APPROXIMATE",
                       "383,639 行 roe 有值", lag_note),
        FinancialPitRow("QUALITY_ROIC", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "BLOCKED",
                       "operating_profit/total_assets 全 0", "字段无真实值 → 数据不可用"),
        FinancialPitRow("QUALITY_GROSS_MARGIN", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "gross_margin 有值", lag_note),
        FinancialPitRow("QUALITY_OCF_NI", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "BLOCKED", "operating_cashflow 全 0", "字段无真实值 → 数据不可用"),
        FinancialPitRow("QUALITY_DEBT_RATIO", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "equity_ratio 有值", lag_note),
        FinancialPitRow("QUALITY_REV_GROWTH", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "revenue_growth 有值", lag_note),
        FinancialPitRow("QUALITY_PROFIT_GROWTH", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "profit_growth 有值", lag_note),
        FinancialPitRow("QUALITY_PROFIT_STABILITY", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "net_profit 有值", lag_note),
        FinancialPitRow("GROWTH_REV_ACCEL", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "revenue_growth 差分", lag_note),
        FinancialPitRow("GROWTH_PROFIT_ACCEL", "financial_data", "report_date", "UNAVAILABLE", "UNAVAILABLE",
                       "fetched_at", "PIT_APPROXIMATE", "profit_growth 差分", lag_note),
        FinancialPitRow("VAL_PE_PCT", "pe_pb_data", "fetch_date(snapshot)", "UNAVAILABLE", "UNAVAILABLE",
                       "fetch_date", "BLOCKED_FOR_PIT",
                       "pe_pct 仅 4787 行且为 2026 快照，非按报告期历史序列",
                       "仅支持近期估值快照因子，不支持历史估值 PIT"),
        FinancialPitRow("VAL_PB_PCT", "pe_pb_data", "fetch_date(snapshot)", "UNAVAILABLE", "UNAVAILABLE",
                       "fetch_date", "BLOCKED_FOR_PIT", "pb_pct 同上", "同上"),
        FinancialPitRow("VAL_PEG", "pe_pb_data+financial_data", "fetch_date(snapshot)", "UNAVAILABLE",
                       "UNAVAILABLE", "fetch_date", "BLOCKED_FOR_PIT", "需 pe+growth 同存", "同上"),
    ]
    return rows


def can_become_pit_ready() -> dict:
    """回答 20 问之 1-4：哪些可 READY / 仍 APPROXIMATE / 仍 BLOCKED。"""
    rows = audit_financial_pit()
    out = {"PIT_READY": [], "PIT_APPROXIMATE": [], "BLOCKED": [], "BLOCKED_FOR_PIT": []}
    for r in rows:
        if r.pit_status == "PIT_APPROXIMATE":
            out["PIT_APPROXIMATE"].append(r.factor)
        elif r.pit_status == "BLOCKED":
            out["BLOCKED"].append(r.factor)
        elif r.pit_status == "BLOCKED_FOR_PIT":
            out["BLOCKED_FOR_PIT"].append(r.factor)
    return out


if __name__ == "__main__":
    for r in audit_financial_pit():
        print(f"{r.factor:24s} {r.pit_status:18s} ann={r.announcement_date}")
    print("\ncan_become_pit_ready:", can_become_pit_ready())
