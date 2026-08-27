#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/factor_engine.py — Phase 9-B 因子计算引擎（PIT 严格）
================================================================================

在给定交易日 T，只用 date<=T 已公开数据计算因子值。

设计：
  * 价格/成交量类：从 klines 在 date<=T 窗口直接计算（PIT_READY）。
  * 财务类：从 financial_data 取 report_date<=T 的最新一期（PIT_APPROXIMATE，
    因无 announcement_date，保守使用 report_date 作代理，并在结果标注 pit_quality）。
  * 市值类：通过 historical_share_layer.get_market_cap（PIT，但部分为 APPROXIMATE）。

所有函数签名：compute(klines_window, financial_rows, ...) -> float or None
  klines_window: 升序 list[dict(date,open,close,high,low,volume,turnover)]，仅含 date<=T
  financial_rows: 该股票全部 financial_data 行（调用方预加载后由引擎筛选 report_date<=T）

禁止：使用任何 date>T 的数据；禁止用未来财报回填。
"""

from __future__ import annotations

import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

import research.factor_research.factor_definitions as fd_def  # noqa: E402
from research.factor_research.factor_definitions import FACTOR_BY_ID  # noqa: E402


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _safe_div(a, b):
    try:
        if b in (None, 0):
            return None
        return a / b
    except (TypeError, ValueError):
        return None


# ════════════════ 价格/成交量因子（PIT_READY） ════════════════

def f_mom(klines, n):
    if len(klines) < n + 1:
        return None
    c_t = klines[-1]["close"]
    c_prev = klines[-1 - n]["close"]
    return _safe_div(c_t - c_prev, c_prev)


def f_mom_20d(klines, _fin=None): return f_mom(klines, 20)
def f_mom_60d(klines, _fin=None): return f_mom(klines, 60)
def f_mom_120d(klines, _fin=None): return f_mom(klines, 120)
def f_mom_250d(klines, _fin=None): return f_mom(klines, 250)


def f_52w_dist(klines, _fin=None):
    if len(klines) < 250:
        return None
    window = klines[-250:]
    hi = max(r["high"] for r in window)
    if hi in (None, 0):
        return None
    return _safe_div(klines[-1]["close"] - hi, hi)


def f_ma_slope(klines, n, lookback=20):
    if len(klines) < n + lookback:
        return None
    ma_now = _ma([r["close"] for r in klines], n)
    ma_prev = _ma([r["close"] for r in klines[:-lookback]], n)
    if ma_now is None or ma_prev in (None, 0):
        return None
    return _safe_div(ma_now - ma_prev, ma_prev)


def f_ma20_slope(klines, _fin=None): return f_ma_slope(klines, 20, 20)
def f_ma60_slope(klines, _fin=None): return f_ma_slope(klines, 60, 20)


def f_rs(klines, cross_section_median_60d):
    """相对强度：个股 60D 收益 / 横截面中位 60D 收益。cross_section_median_60d 由 runner 提供。"""
    own = f_mom(klines, 60)
    if own is None or cross_section_median_60d in (None, 0):
        return None
    return _safe_div(own, cross_section_median_60d)


def f_vol_ratio(klines, _fin=None):
    if len(klines) < 25:
        return None
    v = [r["volume"] for r in klines[-25:]]
    v5 = sum(v[-5:]) / 5
    v20 = sum(v[:-5]) / 20
    return _safe_div(v5, v20)


def f_turnover_persist(klines, _fin=None):
    """换手稳定度：20 日 turnover 均值 / (标准差+1)，越稳定越接近均值。"""
    if len(klines) < 20:
        return None
    ts = [r.get("turnover") or 0 for r in klines[-20:]]
    if not any(ts):
        return None
    mean = sum(ts) / len(ts)
    if mean == 0:
        return None
    var = sum((x - mean) ** 2 for x in ts) / len(ts)
    sd = var ** 0.5
    if mean + sd == 0:
        return None
    return mean / (mean + sd)


def f_amount_persist(klines, _fin=None):
    """成交额活跃度：20 日成交额均值（万元）。"""
    if len(klines) < 20:
        return None
    ts = [ (r.get("turnover") or 0) / 1e4 for r in klines[-20:] ]
    if not any(ts):
        return None
    return sum(ts) / len(ts)


def f_vol_accel(klines, _fin=None):
    if len(klines) < 45:
        return None
    v = [r["volume"] for r in klines[-45:]]
    v5 = sum(v[-5:]) / 5
    v20 = sum(v[:-5]) / 20
    v5_prev = sum(v[-25:-20]) / 5
    v20_prev = sum(v[:-25]) / 20
    r_now = _safe_div(v5, v20)
    r_prev = _safe_div(v5_prev, v20_prev)
    if r_now is None or r_prev in (None, 0):
        return None
    return _safe_div(r_now - r_prev, abs(r_prev))


# ════════════════ 财务因子（PIT_APPROXIMATE，report_date<=T 最新一期） ════════════════

def _latest_fin(fin_rows, as_of, valid_pred=None):
    """从预加载的财务行中筛选 report_date<=as_of 的最新一期。
    valid_pred: 可选 callable(row)->bool，用于跳过 0.0/缺失的退化行（仍在 report_date<=T 内，不泄漏未来）。
    """
    candidates = [r for r in fin_rows if r.get("report_date") and r["report_date"] <= as_of]
    if valid_pred is not None:
        valid = [r for r in candidates if valid_pred(r)]
        if valid:
            return max(valid, key=lambda r: r["report_date"])
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["report_date"])


def f_from_field(klines, fin_rows, as_of, field, transform=None):
    row = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get(field) is not None and r.get(field) != 0)
    if row is None:
        return None
    val = row.get(field)
    if val in (None, ""):
        return None
    if transform is not None:
        try:
            return transform(val, row)
        except Exception:
            return None
    return float(val)


def f_roe(klines, fin_rows, as_of): return f_from_field(klines, fin_rows, as_of, "roe")
def f_roic(klines, fin_rows, as_of):
    row = _latest_fin(fin_rows, as_of, valid_pred=lambda r: all(
        r.get(k) not in (None, 0) for k in ("operating_profit", "finance_expenses", "total_assets")))
    if row is None:
        return None
    op = row.get("operating_profit"); fa = row.get("finance_expenses"); ta = row.get("total_assets")
    if None in (op, fa, ta) or ta in (None, 0):
        return None
    return _safe_div((op or 0) + (fa or 0), ta)
def f_gross_margin(klines, fin_rows, as_of): return f_from_field(klines, fin_rows, as_of, "gross_margin")
def f_ocf_ni(klines, fin_rows, as_of):
    row = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get("operating_cashflow") not in (None, 0)
                      and r.get("net_profit") not in (None, 0))
    if row is None:
        return None
    ocf = row.get("operating_cashflow"); ni = row.get("net_profit")
    return _safe_div(ocf, ni)
def f_debt_ratio(klines, fin_rows, as_of):
    row = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get("equity_ratio") not in (None, 0))
    if row is None:
        return None
    er = row.get("equity_ratio")
    if er is None:
        return None
    return _safe_div(1 - er, 1)  # 负债率 ≈ 1 - 权益率
def f_rev_growth(klines, fin_rows, as_of): return f_from_field(klines, fin_rows, as_of, "revenue_growth")
def f_profit_growth(klines, fin_rows, as_of): return f_from_field(klines, fin_rows, as_of, "profit_growth")


def f_profit_stability(klines, fin_rows, as_of):
    """过去 8 期 net_profit 变异系数（负值=越不稳定，返回 -CV，值越大越稳定）。"""
    rows = sorted([r for r in fin_rows if r.get("report_date") and r["report_date"] <= as_of
                   and r.get("net_profit") not in (None, 0)],
                  key=lambda r: r["report_date"])
    nps = [r["net_profit"] for r in rows[-8:]]
    if len(nps) < 4:
        return None
    mean = sum(nps) / len(nps)
    if mean == 0:
        return None
    var = sum((x - mean) ** 2 for x in nps) / len(nps)
    cv = (var ** 0.5) / abs(mean)
    return -cv  # 负值越大越不稳定；返回 -cv 使"稳定→正值"


def f_growth_accel(klines, fin_rows, as_of, field):
    rows = sorted([r for r in fin_rows if r.get("report_date") and r["report_date"] <= as_of
                   and r.get(field) not in (None, 0)],
                  key=lambda r: r["report_date"])
    vals = [r.get(field) for r in rows[-2:] if r.get(field) is not None]
    if len(vals) < 2:
        return None
    return vals[-1] - vals[-2]


def f_rev_accel(klines, fin_rows, as_of): return f_growth_accel(klines, fin_rows, as_of, "revenue_growth")
def f_profit_accel(klines, fin_rows, as_of): return f_growth_accel(klines, fin_rows, as_of, "profit_growth")


def f_pe_pct(klines, fin_rows, as_of):
    """个股 PE 在自身历史 PE 分布的分位（需多期且 pe>0）。"""
    rows = [r for r in fin_rows if r.get("report_date") and r["report_date"] <= as_of
            and r.get("pe_ratio") not in (None, 0)]
    pes = [r["pe_ratio"] for r in rows]
    cur = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get("pe_ratio") not in (None, 0))
    if cur is None or not pes:
        return None
    cur_pe = cur.get("pe_ratio")
    if cur_pe is None or cur_pe <= 0:
        return None
    below = sum(1 for p in pes if p <= cur_pe)
    return _safe_div(below, len(pes))


def f_pb_pct(klines, fin_rows, as_of):
    rows = [r for r in fin_rows if r.get("report_date") and r["report_date"] <= as_of
            and r.get("pb_ratio") not in (None, 0)]
    pbs = [r["pb_ratio"] for r in rows]
    cur = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get("pb_ratio") not in (None, 0))
    if cur is None or not pbs:
        return None
    cur_pb = cur.get("pb_ratio")
    if cur_pb is None or cur_pb <= 0:
        return None
    below = sum(1 for p in pbs if p <= cur_pb)
    return _safe_div(below, len(pbs))


def f_peg(klines, fin_rows, as_of):
    row = _latest_fin(fin_rows, as_of, valid_pred=lambda r: r.get("pe_ratio") not in (None, 0)
                      and r.get("profit_growth") not in (None, 0))
    if row is None:
        return None
    pe = row.get("pe_ratio"); g = row.get("profit_growth")
    if pe is None or pe <= 0 or g in (None, 0):
        return None
    return _safe_div(pe, g * 100)


# ════════════════ 分派表 ════════════════

# (factor_id, 计算函数, 是否需要 as_of+financial)
PRICE_FACTORS = {
    "MOM_20D": f_mom_20d, "MOM_60D": f_mom_60d, "MOM_120D": f_mom_120d, "MOM_250D": f_mom_250d,
    "MOM_52W_DIST": f_52w_dist, "MOM_MA20_SLOPE": f_ma20_slope, "MOM_MA60_SLOPE": f_ma60_slope,
    "VOL_RATIO": f_vol_ratio, "VOL_TURNOVER_PERSIST": f_turnover_persist,
    "VOL_AMOUNT_PERSIST": f_amount_persist, "VOL_ACCEL": f_vol_accel,
}
FIN_FACTORS = {
    "QUALITY_ROE": f_roe, "QUALITY_ROIC": f_roic, "QUALITY_GROSS_MARGIN": f_gross_margin,
    "QUALITY_OCF_NI": f_ocf_ni, "QUALITY_DEBT_RATIO": f_debt_ratio,
    "QUALITY_REV_GROWTH": f_rev_growth, "QUALITY_PROFIT_GROWTH": f_profit_growth,
    "QUALITY_PROFIT_STABILITY": f_profit_stability,
    "GROWTH_REV_ACCEL": f_rev_accel, "GROWTH_PROFIT_ACCEL": f_profit_accel,
    "VAL_PE_PCT": f_pe_pct, "VAL_PB_PCT": f_pb_pct, "VAL_PEG": f_peg,
}


def compute_factor(factor_id, klines, fin_rows, as_of, cross_section_median_60d=None):
    """
    统一入口：返回 (value, pit_quality)。
      price 类: (float|None, "PIT_READY")
      fin 类:   (float|None, "PIT_APPROXIMATE")
    不支持的 factor_id → (None, "UNKNOWN_FACTOR")
    """
    if factor_id == "MOM_RS":
        return (f_rs(klines, cross_section_median_60d), "PIT_READY")
    if factor_id in PRICE_FACTORS:
        try:
            return (PRICE_FACTORS[factor_id](klines), "PIT_READY")
        except Exception:
            return (None, "PIT_READY")
    if factor_id in FIN_FACTORS:
        try:
            return (FIN_FACTORS[factor_id](klines, fin_rows, as_of), "PIT_APPROXIMATE")
        except Exception:
            return (None, "PIT_APPROXIMATE")
    return (None, "UNKNOWN_FACTOR")
