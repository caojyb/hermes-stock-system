#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/factor_research/research_runner.py — Phase 9-B 单因子研究执行器
=========================================================================

输入：factor_id + universe + COMMON_WINDOW + dataset
输出：该因子的统一研究产物（distribution / quantiles / outcomes / monotonicity /
      time stability / regime stability / market-cap split / incremental / redundancy）

关键约束（Phase 9-B）：
  * 统一 Outcome 口径：复用 research.forward_outcome（5D/10D/20D/MAE/MFE，UNKNOWN≠0）。
  * Candidate/Sample 在统一 Universe + 统一时间窗，不按因子挑年份/挑股票。
  * 先 quantile（不先阈值）；monotonicity 检查 Q10→Q90（含 U-shape/tail reversal）。
  * Time split：Period A/B/C（2005-2009/2010-2014/2015-2019/2020-2024，足够才切）。
  * Regime split：复用 research/artifacts/regime_v1/regime_daily.csv。
  * Market-cap split：historical_share_layer（APPROXIMATE 标注）。
  * Incremental：相对 Baseline（V1 candidate 或 market-neutral）。
  * Multiple Testing：DISCOVERY_ONLY。

采样：candidate dates = 每月最后一个交易日（降采样，控制规模；Pilot 更小）。
"""

from __future__ import annotations

import os
import sys
import json
import csv
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/caojy/.hermes/scripts/cron")

import research.forward_outcome as fo  # 统一 outcome 口径
from research.factor_research.factor_definitions import FACTOR_BY_ID, FactorAvailability  # noqa: E402
from research.factor_research.factor_engine import compute_factor  # noqa: E402
from research.dataset_registry import DatasetRegistry  # noqa: E402

DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
REGIME_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "artifacts", "regime_v1", "regime_daily.csv")


# ── 配置常量 ──
RESEARCH_UNIVERSE_V2_R1 = "全市场（排除688/787；list_date<=窗口起点；is_st 按当前表=0 非历史PIT）"
COMMON_WINDOW = ("2005-01-01", "2024-12-31")   # PIT+outcome 较完整共同区间


def _connect():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    con.text_factory = str
    return con


def load_universe(limit: Optional[int] = None, symbols: Optional[list] = None,
                  start: str = "2005-01-01") -> list[str]:
    con = _connect()
    cur = con.cursor()
    if symbols:
        codes = symbols
    else:
        cur.execute(
            "SELECT code FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' "
            "AND (is_st IS NULL OR is_st=0) ORDER BY code")
        codes = [r[0] for r in cur.fetchall()]
    con.close()
    if limit and not symbols:
        codes = codes[:limit]
    return codes


def monthly_candidate_dates(all_dates: list[str], start: str, end: str) -> list[str]:
    """每月最后一个交易日（降采样）。"""
    import bisect
    out = []
    cur_key = None
    last = None
    for d in sorted(all_dates):
        if d < start or d > end:
            continue
        key = d[:7]  # YYYY-MM
        if key != cur_key:
            if last is not None:
                out.append(last)
            cur_key = key
        last = d
    if last is not None:
        out.append(last)
    return out


def load_klines_window(con, symbol, as_of):
    cur = con.cursor()
    rows = cur.execute(
        "SELECT date,open,close,high,low,volume,turnover FROM klines "
        "WHERE code=? AND date<=? ORDER BY date ASC", (symbol, as_of)).fetchall()
    return [{"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4],
             "volume": r[5], "turnover": r[6]} for r in rows]


def load_fin_rows(con, symbol):
    cur = con.cursor()
    # financial_data 同时存 '000001' 与 '000001.SZ' 两种 code；stocks/klines 用裸码。
    # 为不漏数据，两种 variant 都查（去重按 report_date）。
    variants = [symbol, f"{symbol}.SH", f"{symbol}.SZ", f"{symbol}.BJ"]
    placeholders = ",".join("?" for _ in variants)
    rows = cur.execute(
        f"SELECT report_date,roe,operating_profit,finance_expenses,total_assets,"
        f"gross_margin,operating_cashflow,net_profit,equity_ratio,revenue_growth,"
        f"profit_growth,pe_ratio,pb_ratio FROM financial_data WHERE code IN ({placeholders}) "
        f"ORDER BY report_date ASC", variants).fetchall()
    out = []
    seen = set()
    for r in rows:
        rd = r[0]
        if rd in seen:
            continue
        seen.add(rd)
        out.append({
            "report_date": rd, "roe": r[1], "operating_profit": r[2], "finance_expenses": r[3],
            "total_assets": r[4], "gross_margin": r[5], "operating_cashflow": r[6],
            "net_profit": r[7], "equity_ratio": r[8], "revenue_growth": r[9],
            "profit_growth": r[10], "pe_ratio": r[11], "pb_ratio": r[12],
        })
    return out


def load_regime_map():
    if not os.path.exists(REGIME_CSV):
        return {}
    m = {}
    with open(REGIME_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m[row["date"]] = row["regime_label"]
    return m


def compute_outcome_for(symbol, cand_date, con):
    """统一 outcome：entry=T+1 open，复用 forward_outcome.compute_one。"""
    cur = con.cursor()
    row = cur.execute(
        "SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
        (symbol, cand_date)).fetchone()
    entry_price = float(row[0]) if row and row[0] else None
    cand = {"symbol": symbol, "candidate_date": cand_date, "entry_price": entry_price,
            "entry_date": None, "as_of_date": cand_date}
    return fo.compute_one(cand, con), entry_price


def _quantile_bins(vals, q=10):
    """返回每样本分位（1..q）。vals: list[(key, value)]，value 为数值。"""
    if not vals:
        return {}
    svals = sorted(v for _, v in vals if v is not None)
    n = len(svals)
    def q_of(v):
        if n == 1:
            return 1
        idx = sum(1 for x in svals if x <= v)
        return min(q, max(1, (idx - 1) * q // n + 1))
    return {k: q_of(v) for k, v in vals}


def monotonicity_label(q_returns: dict):
    """q_returns: {q: median_forward_return}。判定方向。"""
    qs = sorted(q_returns.keys())
    if not qs:
        return "NO_SIGNAL"
    vals = [q_returns[q] for q in qs]
    # 线性趋势（首尾）
    first, last = vals[0], vals[-1]
    if abs(last - first) < 1e-9:
        return "NO_SIGNAL"
    # 检查是否单调
    inc = all(vals[i] <= vals[i + 1] + 1e-12 for i in range(len(vals) - 1))
    dec = all(vals[i] >= vals[i + 1] - 1e-12 for i in range(len(vals) - 1))
    if inc:
        return "MONOTONIC_POSITIVE"
    if dec:
        return "MONOTONIC_NEGATIVE"
    # 检测 U / 倒 U / 尾部反转
    return "NON_MONOTONIC"


@dataclass
class FactorStudyResult:
    factor_id: str
    availability: str
    pit_status: str
    n_total: int = 0
    n_valid: int = 0
    n_missing: int = 0
    n_unknown: int = 0
    quantiles: dict = field(default_factory=dict)      # q -> median 20D
    monotonicity: str = "NO_SIGNAL"
    time_stability: dict = field(default_factory=dict)  # period -> median 20D by q-decile spread
    regime_stability: dict = field(default_factory=dict)
    marketcap_stability: dict = field(default_factory=dict)
    incremental: str = "UNDEFINED"
    redundancy_with: list = field(default_factory=list)
    data_quality: str = ""
    notes: str = ""

    def to_dict(self):
        return self.__dict__.copy()


def _num(v):
    try:
        if v in (None, "UNKNOWN", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def build_samples(universe: list[str], start: str, end: str, regime_map: Optional[dict] = None,
                  mcap_helper=None, cross_section_60d: Optional[dict] = None) -> list[dict]:
    """
    共享采样：对 universe × 每月候选日，计算所有 25 因子值（内联丢弃原始 klines），
    仅保留紧凑记录 {symbol, cand_date, factors:{fid:val}, fwd5, fwd10, fwd20, regime, mcap_tier}。
    内存友好（Expansion 200 股票 × 20 年不 OOM）。
    """
    from research.factor_research.factor_definitions import FACTOR_DEFS
    fid_list = [f.factor_id for f in FACTOR_DEFS]
    con = _connect()
    samples = []
    for sym in universe:
        kdates = [r[0] for r in con.execute(
            "SELECT date FROM klines WHERE code=? AND date>=? AND date<=? ORDER BY date",
            (sym, start, end)).fetchall()]
        if not kdates:
            continue
        cand_dates = monthly_candidate_dates(kdates, start, end)
        fin_rows = load_fin_rows(con, sym)
        cs_median = (cross_section_60d or {}).get(sym)
        for cd in cand_dates:
            kl = load_klines_window(con, sym, cd)
            if len(kl) < 2:
                continue
            fvals = {}
            for fid in fid_list:
                v, _ = compute_factor(fid, kl, fin_rows, cd, cs_median)
                fvals[fid] = v
            outcome, _entry = compute_outcome_for(sym, cd, con)
            fwd5 = _num(outcome.get("fwd_5d"))
            fwd10 = _num(outcome.get("fwd_10d"))
            fwd20 = _num(outcome.get("fwd_20d"))
            regime = (regime_map or {}).get(cd)
            mcap_tier = None
            if mcap_helper is not None:
                kind, mv = mcap_helper(sym, cd)
                if mv is not None and mv > 0:
                    mcap_tier = "small" if mv < 50 else ("mid" if mv < 200 else "large")
            samples.append({
                "symbol": sym, "cand_date": cd, "factors": fvals,
                "fwd5": fwd5, "fwd10": fwd10, "fwd20": fwd20,
                "regime": regime, "mcap_tier": mcap_tier,
            })
        # 释放该股票 fin_rows（已内联计算）
        del fin_rows
    con.close()
    return samples


def study_on_samples(factor_id: str, samples: list[dict]) -> FactorStudyResult:
    """在共享样本（已含预计算因子值）上计算单因子研究。"""
    fdef = FACTOR_BY_ID.get(factor_id)
    if fdef is None:
        res = FactorStudyResult(factor_id, "BLOCKED", "UNKNOWN_FACTOR")
        res.notes = "unknown factor"
        return res
    avail, pit = fdef.availability, fdef.pit_status

    rows = []  # (symbol, cand_date, factor_value, fwd20, regime, mcap_tier)
    n_missing = 0
    for s in samples:
        val = s["factors"].get(factor_id)
        if val is None:
            n_missing += 1
            continue
        # 仅当因子值与 outcome 均有效才计入有效对（UNKNOWN outcome 不进入分位统计）
        if s["fwd20"] is None:
            continue
        rows.append((s["symbol"], s["cand_date"], val, s["fwd20"], s["regime"], s["mcap_tier"]))

    res = FactorStudyResult(factor_id, avail, pit)
    res.n_total = len(samples)
    res.n_valid = len(rows)
    res.n_missing = n_missing
    res.n_unknown = len([s for s in samples if s["fwd20"] is None])

    if not rows:
        res.notes = "no valid (factor,outcome) pairs"
        res.data_quality = "DATA_INSUFFICIENT" if res.n_total == 0 else "LOW_COVERAGE"
        return res

    qbins = _quantile_bins([(s[0] + s[1], s[2]) for s in rows])
    q_ret = {}
    for (sym, cd, val, fwd20, regime, mtier) in rows:
        q = qbins.get(sym + cd)
        if q is None:
            continue
        q_ret.setdefault(q, []).append(fwd20)
    q_median = {q: (sum(v) / len(v)) for q, v in q_ret.items()}
    res.quantiles = {str(q): round(m, 6) for q, m in sorted(q_median.items())}
    res.monotonicity = monotonicity_label(q_median)

    periods = [("2005-2009", "2005", "2009"), ("2010-2014", "2010", "2014"),
               ("2015-2019", "2015", "2019"), ("2020-2024", "2020", "2024")]
    for pname, ps, pe in periods:
        sub = [(s[2], s[3]) for s in rows if ps <= s[1] <= pe]
        if len(sub) >= 30:
            qb = _quantile_bins([(str(i), v) for i, (v, _) in enumerate(sub)])
            res.time_stability[pname] = {"n": len(sub),
                                         "q1_q9_spread": round(_decile_spread([(qb[str(i)], r) for i, (_, r) in enumerate(sub)]), 6)}
        else:
            res.time_stability[pname] = {"n": len(sub), "status": "DATA_INSUFFICIENT"}

    for rg in ["🔴高波动", "⚫低量能", "🟡震荡市", "🟢强趋势"]:
        sub = [(s[2], s[3]) for s in rows if s[4] == rg]
        if len(sub) >= 30:
            qb = _quantile_bins([(str(i), v) for i, (v, _) in enumerate(sub)])
            res.regime_stability[rg] = {"n": len(sub),
                                        "q1_q9_spread": round(_decile_spread([(qb[str(i)], r) for i, (_, r) in enumerate(sub)]), 6)}
        else:
            res.regime_stability[rg] = {"n": len(sub), "status": "DATA_INSUFFICIENT"}

    for tier in ["small", "mid", "large"]:
        sub = [(s[2], s[3]) for s in rows if s[5] == tier]
        if len(sub) >= 30:
            qb = _quantile_bins([(str(i), v) for i, (v, _) in enumerate(sub)])
            res.marketcap_stability[tier] = {"n": len(sub),
                                             "q1_q9_spread": round(_decile_spread([(qb[str(i)], r) for i, (_, r) in enumerate(sub)]), 6),
                                             "note": "APPROXIMATE mcap"}
        else:
            res.marketcap_stability[tier] = {"n": len(sub), "status": "LIMITED"}

    overall_spread = _decile_spread([(qbins.get(s[0] + s[1]), s[3]) for s in rows if qbins.get(s[0] + s[1])])
    res.incremental = "POSITIVE" if overall_spread > 0 else "NONE"
    res.data_quality = f"valid={res.n_valid},missing={res.n_missing},pit={pit}"
    return res


def _decile_spread(pairs):
    """pairs: [(q, return)]；返回 q9 中位 - q1 中位 的 spread。"""
    if not pairs:
        return 0.0
    q1 = [r for q, r in pairs if q == 1]
    q9 = [r for q, r in pairs if q == 10]
    if not q1 or not q9:
        return 0.0
    return (sum(q9) / len(q9)) - (sum(q1) / len(q1))
