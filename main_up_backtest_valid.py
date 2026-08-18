#!/usr/bin/env python3
"""
主升浪回测可信度修复（Phase 4-B）— 全内存版
==========================================
修复 BLOCKER：
  1. ROE look-ahead：report_date<=当月 → available_date(法定披露截止日)<=T
  2. Survivorship：universe 用全部历史 klines code（as-of 由月快照自动处理）

性能：全部数据（klines + financial ROE + universe）预加载进内存，strategy_fn
完全纯内存（零 DB 调用），回测前只连一次 DB。

策略逻辑冻结（ROE/均线多头/RSI/成交额/20日均/低波动/TopN 完全不变）。
未改数据库 schema。
"""
import os, sys, sqlite3, json, time, math, bisect, statistics, calendar
from pathlib import Path

FEISHU_DIR = Path("/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable")
sys.path.insert(0, str(FEISHU_DIR))
import backtest_engine as be

MKT_DB = be.MARKET_DB
BACKTEST_START = "2023-01"
BACKTEST_END = "2026-07"
TOP_N = 20
MIN_TURNOVER_1D = 50_000_000
MIN_TURNOVER_20D = 30_000_000

_calc_ma = be._calc_ma
_is_ma_bullish = be._is_ma_bullish
_calc_rsi = be._calc_rsi

# 全局预加载
_DAILY = {}      # code -> (dates升序, closes, turnovers)
_FIN = {}        # code -> [(report_date, roe), ...] 按报告期降序

def _avail(report_date):
    """报告期 → 法定披露截止日(available_date)。"""
    if not report_date: return None
    y = int(report_date[:4])
    if report_date.endswith('03-31'): return f'{y}-04-30'
    if report_date.endswith('06-30'): return f'{y}-08-31'
    if report_date.endswith('09-30'): return f'{y}-10-31'
    if report_date.endswith('12-31'): return f'{y+1}-04-30'
    return None

def _load_all():
    conn = be._get_db()
    # klines 预加载
    cur = conn.execute(
        "SELECT code, date, close, turnover FROM klines WHERE date >= ? AND date <= ? ORDER BY code, date",
        (BACKTEST_START + "-01", f"{BACKTEST_END}-31"))
    for code, dt, close, to in cur.fetchall():
        e = _DAILY.setdefault(code, ([], [], []))
        e[0].append(dt); e[1].append(close); e[2].append(to or 0)
    # financial ROE 预加载（报告期降序）
    cur = conn.execute(
        "SELECT code, report_date, roe FROM financial_data WHERE roe IS NOT NULL AND report_date IS NOT NULL "
        "ORDER BY code, report_date DESC")
    for code, rdate, roe in cur.fetchall():
        _FIN.setdefault(code, []).append((rdate, roe))
    conn.close()
    print(f"  [预加载] klines {len(_DAILY)} 只, financial {len(_FIN)} 只", file=sys.stderr)

def _slice(code, snapshot_date, n_close, n_turn):
    e = _DAILY.get(code)
    if not e: return None, None
    dates, closes, tos = e
    i = bisect.bisect_right(dates, snapshot_date)
    if i <= 0: return None, None
    return closes[max(0, i-n_close):i], tos[max(0, i-n_turn):i]

def _high_roe(snapshot_date, use_available_date):
    res = {}
    for code, fin in _FIN.items():
        recent8 = fin[:8]
        usable = [roe for rdate, roe in recent8
                  if (_avail(rdate) if use_available_date else rdate) and
                     (_avail(rdate) if use_available_date else rdate) <= snapshot_date]
        if usable and (sum(usable)/len(usable)) >= 15:
            res[code] = sum(usable)/len(usable)
    return res

def create_strategy(use_available_date):
    def _strategy(snapshot_date, all_prices, top_n=TOP_N):
        high_roe = _high_roe(snapshot_date, use_available_date)
        scored = []
        for code in all_prices:
            if code not in high_roe: continue
            closes, tos = _slice(code, snapshot_date, 60, 25)
            if closes is None or len(closes) < 60: continue
            if len(tos) < 1 or tos[0] < MIN_TURNOVER_1D: continue
            if len(tos) >= 25:
                if sum(tos[5:]) / max(len(tos[5:]), 1) < MIN_TURNOVER_20D: continue
            ma = _calc_ma(closes)
            if not _is_ma_bullish(ma): continue
            rsi = _calc_rsi(closes)
            if rsi is None or rsi < 40 or rsi > 70: continue
            logs = [math.log(closes[i+1]/closes[i]) for i in range(len(closes)-1) if closes[i] > 0 and closes[i+1] > 0]
            if len(logs) < 20: continue
            vol = statistics.stdev(logs) * math.sqrt(252)
            scored.append((code, vol, high_roe.get(code, 0)))
        if len(scored) < 5:
            return [c for c, _, _ in scored]
        scored.sort(key=lambda x: x[1])
        return [c for c, _, _ in scored[:top_n]]
    return _strategy

def run_valid(name, use_available_date):
    _load_all()
    strategy_fn = create_strategy(use_available_date)
    conn = be._get_db()
    codes = set(_DAILY.keys())
    print(f"  [{name}] universe: {len(codes)} 只", file=sys.stderr)
    start_full = BACKTEST_START + "-01"
    y, m = BACKTEST_END.split("-")
    end_full = f"{BACKTEST_END}-{calendar.monthrange(int(y), int(m))[1]:02d}"
    data = be.load_monthly_kline_data(conn, codes, start_full, end_full)
    snapshots = be.get_monthly_snapshots(data)
    bench = be.load_benchmark_data(conn, start_full, end_full)
    bench_m = be.get_benchmark_monthly_returns(bench, [s[0] for s in snapshots])
    conn.close()
    t0 = time.time()
    results = be._run_walk_forward(strategy_fn, snapshots, bench_m, TOP_N, window=24, step=12, data=data)
    print(f"  [{name}] 耗时 {time.time()-t0:.0f}s", file=sys.stderr)
    return results, len(codes)

if __name__ == "__main__":
    rb, n = run_valid("Before(report_date)", False)
    ra, _ = run_valid("After(available_date)", True)
    def s(r):
        w = r.get("walk_forward", {})
        return {"cagr": w.get("cagr_pct",0), "dd": w.get("max_drawdown_pct",0),
                "win": w.get("win_rate_pct",0), "sharpe": w.get("sharpe_ratio",0),
                "total": w.get("total_return_pct",0), "trades": w.get("total_trades",0),
                "months": w.get("months",0), "bench": w.get("benchmark_return_pct",0)}
    out = {"universe_size": n, "before": s(rb), "after": s(ra)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open("/tmp/main_up_valid_results.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("结果已存 /tmp/main_up_valid_results.json")
