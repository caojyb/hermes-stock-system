#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forward_outcome.py — Phase 8-G1 候选/signal forward outcome 研究模块
====================================================================
对已重建的候选/信号（counterfactual research）计算 5D/10D/20D forward
收益、MAE、MFE。本模块是研究隔离代码（research/ 下物理隔离），
不 import / 不修改任何生产模块，不修改 market_cache.db。

时间语义（严格）：
  * candidate_date = 信号日 T（候选生成日）
  * planned_entry_time = T+1 开盘（计划进场时刻），entry_price 为该开盘价
  * forward 窗口自 T+1 开始：
        fwd_Nd = close[T+N] / entry_price - 1     (N=5,10,20)
    即用 T+1 起的收盘价序列，N 个交易日后（T+N 收盘）的收益。
  * MAE / MFE 用 entry_price 与未来高低点计算，限定 entry_time < future <= horizon_end：
        horizon_end = T+20（最长 forward 视界）
        MAE = min( low[k] / entry_price - 1 )   for k in (T+1, T+20]
        MFE = max( high[k]/ entry_price - 1 )   for k in (T+1, T+20]
    注意：进场日 T+1 本身（其 open == entry_time）不计入 MAE/MFE
    （严格满足 entry_time < future）。
  * max_return / min_return = 持有窗口 (T+1..T+N) 收盘价相对 entry_price 的
    最大 / 最小收益（N=20，即最长视界）。

数据不足：
  * 若 T+N 收盘价不存在 → 该 fwd_Nd 记为 "UNKNOWN"（绝不填 0）。
  * MAE/MFE/max/min_return 若可用 bar < 1 → "UNKNOWN"。

输出：
  research/artifacts/regime_v1/candidate_outcomes.csv
  每行含 outcome_type = 'COUNTERFACTUAL_RESEARCH'。
"""

import os
import sys
import csv
import json
import sqlite3
from datetime import date as _date

# ---- 常量 ----
HORIZONS = (5, 10, 20)
MAX_HORIZON = max(HORIZONS)          # 20 —— MAE/MFE 的最长视界
OUTCOME_TYPE = "COUNTERFACTUAL_RESEARCH"
UNKNOWN = "UNKNOWN"

# ---- 路径 ----
_HERE = os.path.dirname(os.path.abspath(__file__))
_ARTIFACT_DIR = os.path.join(_HERE, "artifacts", "regime_v1")
DEFAULT_OUTPUT = os.path.join(_ARTIFACT_DIR, "candidate_outcomes.csv")

# 生产数据库（只读）
DEFAULT_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"

# 常见的交易所后缀，用于代码归一化
_SUFFIXES = (".SH", ".SZ", ".BJ")


# ---------------------------------------------------------------- 工具函数
def normalize_code(symbol):
    """归一化股票代码：去掉常见后缀，返回基础 6 位代码（如 600519.SH -> 600519）。"""
    if symbol is None:
        return None
    s = str(symbol).strip().upper()
    for sfx in _SUFFIXES:
        if s.endswith(sfx):
            s = s[: -len(sfx)]
            break
    return s


def _connect(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def _load_klines(con, symbol):
    """读取某股票全部 K 线（date, open, close, high, low），按日期升序。返回 list[dict]。"""
    base = normalize_code(symbol)
    if not base:
        return []
    # 先尝试精确代码，再依次尝试基础代码 + 各后缀
    candidates = [symbol, base]
    for sfx in _SUFFIXES:
        candidates.append(base + sfx.lower())
    seen = set()
    rows = []
    for code in candidates:
        if code in seen:
            continue
        seen.add(code)
        try:
            cur = con.execute(
                "SELECT date, open, close, high, low FROM klines "
                "WHERE code=? ORDER BY date",
                (code,),
            )
        except sqlite3.Error:
            continue
        got = cur.fetchall()
        if got:
            rows = [
                {
                    "date": r[0],
                    "open": r[1],
                    "close": r[2],
                    "high": r[3],
                    "low": r[4],
                }
                for r in got
            ]
            break
    return rows


def _find_index(klines, candidate_date):
    """返回 candidate_date 在 klines 中的下标；未找到返回 -1。"""
    for i, k in enumerate(klines):
        if k["date"] == candidate_date:
            return i
    return -1


# ---------------------------------------------------------------- 核心计算
def compute_one(candidate, con):
    """
    对单条候选记录计算 forward outcome。candidate 需含:
      symbol, candidate_date, entry_price, entry_date, as_of_date
    返回结果 dict（含原始字段 + 计算字段 + outcome_type）。
    """
    out = dict(candidate)
    out["outcome_type"] = OUTCOME_TYPE

    # 默认值初始化（不满足时覆盖为 UNKNOWN）
    for h in HORIZONS:
        out[f"fwd_{h}d"] = UNKNOWN
    out["mae"] = UNKNOWN
    out["mfe"] = UNKNOWN
    out["max_return"] = UNKNOWN
    out["min_return"] = UNKNOWN

    symbol = candidate.get("symbol")
    candidate_date = candidate.get("candidate_date")
    try:
        entry_price = float(candidate.get("entry_price"))
    except (TypeError, ValueError):
        entry_price = None

    if not symbol or not candidate_date or entry_price is None or entry_price <= 0:
        return out

    klines = _load_klines(con, symbol)
    if not klines:
        return out

    i = _find_index(klines, candidate_date)
    if i < 0:
        return out

    n = len(klines)
    # 进场日 T+1 的下标
    i_entry = i + 1

    # --- forward 收益：fwd_Nd = close[T+N] / entry_price - 1 ---
    for h in HORIZONS:
        idx = i + h          # close[T+N]
        if idx < n:
            close_n = klines[idx]["close"]
            if close_n and close_n > 0:
                out[f"fwd_{h}d"] = round(close_n / entry_price - 1.0, 6)
        # 否则保持 UNKNOWN

    # --- max/min return over 持有窗口 close[i_entry .. i+MAX_HORIZON] ---
    closes_win = []
    end = min(n, i + MAX_HORIZON + 1)
    for idx in range(i_entry, end):
        c = klines[idx]["close"]
        if c and c > 0:
            closes_win.append(c / entry_price - 1.0)
    if closes_win:
        out["max_return"] = round(max(closes_win), 6)
        out["min_return"] = round(min(closes_win), 6)

    # --- MAE / MFE：窗口 (entry_time, horizon_end] => bars [i+2 .. i+MAX_HORIZON] ---
    # 严格排除进场 bar T+1（其 open 即 entry_time）
    lows = []
    highs = []
    for idx in range(i_entry + 1, min(n, i + MAX_HORIZON + 1)):
        lo = klines[idx]["low"]
        hi = klines[idx]["high"]
        if lo and lo > 0:
            lows.append(lo / entry_price - 1.0)
        if hi and hi > 0:
            highs.append(hi / entry_price - 1.0)
    if lows:
        out["mae"] = round(min(lows), 6)     # 最大不利偏离（最深的负收益）
    if highs:
        out["mfe"] = round(max(highs), 6)    # 最大有利偏离（最高的正收益）

    return out


def compute_outcomes(candidates, db_path=None, con=None):
    """对候选记录列表批量计算，返回结果 dict 列表。"""
    own_con = None
    if con is None:
        db_path = db_path or DEFAULT_DB
        own_con = _connect(db_path)
        con = own_con
    try:
        results = [compute_one(c, con) for c in candidates]
    finally:
        if own_con is not None:
            own_con.close()
    return results


# ---------------------------------------------------------------- 输出
def _csv_rows(results):
    """固定列顺序写出。"""
    base_cols = ["symbol", "candidate_date", "entry_price", "entry_date", "as_of_date"]
    calc_cols = (
        [f"fwd_{h}d" for h in HORIZONS]
        + ["mae", "mfe", "max_return", "min_return", "outcome_type"]
    )
    cols = base_cols + calc_cols
    rows = []
    for r in results:
        rows.append({c: r.get(c, UNKNOWN) for c in cols})
    return cols, rows


def write_csv(results, output_path=None):
    output_path = output_path or DEFAULT_OUTPUT
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cols, rows = _csv_rows(results)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return output_path


# ---------------------------------------------------------------- 输入读取
def load_candidates(input_path):
    """从 CSV 或 JSON 读取候选记录（dict 列表）。"""
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".json":
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("candidates", [])
    # 默认 CSV
    with open(input_path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- CLI
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    input_path = None
    output_path = DEFAULT_OUTPUT
    db_path = DEFAULT_DB
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--input", "-i"):
            input_path = args[i + 1]
            i += 2
        elif a in ("--output", "-o"):
            output_path = args[i + 1]
            i += 2
        elif a in ("--db",):
            db_path = args[i + 1]
            i += 2
        elif a in ("--help", "-h"):
            print(
                "usage: python forward_outcome.py --input candidates.csv|json "
                "[--output artifacts/regime_v1/candidate_outcomes.csv] [--db PATH]"
            )
            return 0
        else:
            i += 1

    if not input_path:
        print("no --input given; nothing to do", file=sys.stderr)
        return 2

    candidates = load_candidates(input_path)
    results = compute_outcomes(candidates, db_path=db_path)
    written = write_csv(results, output_path)
    print(f"wrote {len(results)} rows -> {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
