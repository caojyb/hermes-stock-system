#!/usr/bin/env python3
"""
主升浪策略诚实回测（精简版 — 仅 Walk-Forward）
"""
import os, sys, json, math, sqlite3, statistics, time
from datetime import datetime
from pathlib import Path

FEISHU_DIR = Path("/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable")
sys.path.insert(0, str(FEISHU_DIR))
import backtest_engine as be

MKT_DB = be.MARKET_DB
TODAY = datetime.now().strftime('%Y-%m-%d')

MIN_TURNOVER_1D = 50_000_000
MIN_TURNOVER_20D = 30_000_000
BACKTEST_START = "2023-01"
BACKTEST_END = "2026-07"
TOP_N = 20

# 复用 backtest_engine 的工具函数
_calc_ma = be._calc_ma
_is_ma_bullish = be._is_ma_bullish
_calc_rsi = be._calc_rsi


def create_strategy_main_up_with_liquidity():
    """含流动性约束的主升浪策略"""
    def _strategy(snapshot_date, all_prices, top_n=TOP_N):
        conn = be._get_db()
        cur = conn.execute("""
            SELECT code, AVG(roe) as avg_roe FROM (
                SELECT code, roe, report_date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
                FROM financial_data WHERE roe IS NOT NULL AND report_date <= ?
            ) WHERE rn <= 8 GROUP BY code HAVING avg_roe >= 15
        """, (snapshot_date[:7] + "-01",))
        high_roe = {r["code"]: r["avg_roe"] for r in cur.fetchall()}
        codes = [c for c in all_prices if c in high_roe]
        if not codes:
            conn.close()
            return []

        placeholders = ",".join("?" for _ in codes)
        cur = conn.execute(
            f"""SELECT code, close FROM klines 
                WHERE code IN ({placeholders}) AND date <= ?
                ORDER BY code, date DESC""",
            codes + [snapshot_date])
        kline_data = {}
        for r in cur.fetchall():
            code = r["code"]
            if code not in kline_data:
                kline_data[code] = []
            if len(kline_data[code]) < 60:
                kline_data[code].append(r["close"])

        cur = conn.execute(
            f"""SELECT code, turnover
                FROM klines 
                WHERE code IN ({placeholders}) AND date <= ?
                ORDER BY code, date DESC""",
            codes + [snapshot_date])
        tdata_map = {}
        for r in cur.fetchall():
            code = r["code"]
            if code not in tdata_map:
                tdata_map[code] = []
            if len(tdata_map[code]) < 25:
                tdata_map[code].append(r["turnover"] or 0)
        conn.close()

        scored = []
        for code in codes:
            closes = kline_data.get(code, [])
            if len(closes) < 60:
                continue
            td = tdata_map.get(code, [])
            if len(td) < 1 or td[0] < MIN_TURNOVER_1D:
                continue
            if len(td) >= 25:
                avg_t20d = sum(td[5:]) / max(len(td[5:]), 1)
                if avg_t20d < MIN_TURNOVER_20D:
                    continue
            ma = _calc_ma(closes)
            if not _is_ma_bullish(ma):
                continue
            rsi = _calc_rsi(closes)
            if rsi is None or rsi < 40 or rsi > 70:
                continue
            logs = [math.log(closes[i+1]/closes[i]) for i in range(len(closes)-1)
                    if closes[i] > 0 and closes[i+1] > 0]
            if len(logs) < 20:
                continue
            vol = statistics.stdev(logs) * math.sqrt(252)
            scored.append((code, vol, high_roe.get(code, 0)))
        if len(scored) < 5:
            return [c for c, _, _ in scored]
        scored.sort(key=lambda x: x[1])
        return [c for c, _, _ in scored[:top_n]]
    return _strategy


def main():
    print(f"\n{'='*60}")
    print(f"  主升浪策略诚实回测")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  区间: {BACKTEST_START} ~ {BACKTEST_END}")
    print(f"  选股: {TOP_N} 只/月, 月频, T+1开盘价")
    print(f"  流动性约束: 成交额≥5000万, 20日均≥3000万")
    print(f"  策略条件: ROE≥15% + 均线多头 + RSI 40-70 + 低波动优先")
    print(f"{'='*60}")

    strategy_fn = create_strategy_main_up_with_liquidity()
    t0 = time.time()
    results = be.run_backtest(
        strategy_fn,
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
        top_n=TOP_N,
        walk_forward=True,
        walk_window=24,
        walk_step=12,
    )
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.0f}s\n")

    if "error" in results:
        print(f"\n❌ 错误: {results['error']}")
        return

    wf = results.get("walk_forward", {})
    ar = wf.get("cagr_pct", 0)
    md = wf.get("max_drawdown_pct", 0)
    wr = wf.get("win_rate_pct", 0)
    sh = wf.get("sharpe_ratio", 0)
    tr = wf.get("total_return_pct", 0)
    bm = wf.get("benchmark_return_pct", 0)
    trades = wf.get("total_trades", 0)
    months = wf.get("months", 0)

    print(f"  ── 主升浪策略 Walk-Forward 表现 ──")
    print(f"  {'指标':<20s} {'值':>12s}")
    print(f"  {'─'*32}")
    print(f"  {'年化收益':<20s} {ar:>+10.1f}%")
    print(f"  {'最大回撤':<20s} {md:>10.1f}%")
    print(f"  {'月胜率':<20s} {wr:>9.1f}%")
    print(f"  {'夏普比率':<20s} {sh:>+9.2f}")
    print(f"  {'累计收益':<20s} {tr:>+10.1f}%")
    print(f"  {'基准收益':<20s} {bm:>+9.1f}%")
    print(f"  {'交易笔数':<20s} {trades:>10d}")
    print(f"  {'测试月数':<20s} {months:>10d}")

    if "gapup_fails" in wf:
        gapup = wf.get("gapup_fails", 0)
        print(f"  {'跳空高开失败':<20s} {gapup:>5d}/{trades} ({round(gapup/trades*100,1) if trades else 0}%)")

    print(f"\n  Walk-Forward 分段:")
    for seg in results.get("segments", []):
        print(f"    训练: {seg['train_start']}~{seg['train_end']} → 测试: {seg['test_start']}~{seg['test_end']} ({seg['test_months']}个月)")

    # ── 与翻倍 V1 Top3 对比 ──
    print(f"\n  ── 与翻倍 V1 Top3 对比 ──")
    print(f"  {'策略':<30s} {'年化':>8s} {'回撤':>8s} {'胜率':>7s} {'夏普':>6s}")
    print(f"  {'─'*62}")
    print(f"  {'翻倍 V1 Top3':<30s} {'+124.8%':>8s} {'17.5%':>8s} {'54.5%':>7s} {'1.2':>6s}")
    print(f"  {'主升浪 (流动性约束)':<30s} {ar:>+7.1f}% {md:>7.1f}% {wr:>6.1f}% {sh:>+5.1f}")

    # 判定
    print(f"\n  ── 判定 ──")
    if ar > 20 and md < 25:
        print(f"  ✅ 年化{ar:.1f}%>20% 且 回撤{md:.1f}%<25% → 值得继续优化")
        print(f"  ✅ 可作为翻倍 V1 的互补策略（主升浪=顺势, 翻倍V1=底部放量）")
    elif ar > 0:
        print(f"  ⚠️ 年化{ar:.1f}%>0% 但 <20% → 需要进一步优化参数")
    else:
        print(f"  ❌ 年化{ar:.1f}%<0% → 流动性约束下主升浪策略不成立")

    print(f"\n{'='*60}")
    print(f"  ✅ 主升浪回测完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
