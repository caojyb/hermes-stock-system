#!/usr/bin/env python3
"""
翻倍策略 V1 参数优化 — 完整 43 个月验证
==========================================
验证遗传算法选出的 Top 3 和 Top 1 参数组合在完整时间区间的表现。
"""
import os, sys, json, math, sqlite3, calendar, time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / ".." / ".." / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"))
import backtest_engine as be

# ── 参数组合 ──
PARAM_SETS = {
    "Top3": {
        "price_pos_max": 40,
        "vol_ratio_min": 2.7,
        "mcap_min": 5,
        "mcap_max": 90,
        "turnover_min": 8000,   # 万元
        "atr_pct_min": 3,
        "turnover_min_20d": 4000,  # 20日均成交额门槛（万元）
    },
    "Top1": {
        "price_pos_max": 30,
        "vol_ratio_min": 3.0,
        "mcap_min": 15,
        "mcap_max": 90,
        "turnover_min": 8000,
        "atr_pct_min": 2,
        "turnover_min_20d": 4000,
    },
}

BACKTEST_START = "2023-01"
BACKTEST_END = "2026-07"
TOP_N = 20


def create_strategy_fn(p):
    """创建策略函数（含流动性约束）"""
    price_pos_max = p["price_pos_max"]
    vol_ratio_min = p["vol_ratio_min"]
    mcap_min = p["mcap_min"]
    mcap_max = p["mcap_max"]
    turnover_min = p["turnover_min"]
    atr_pct_min = p["atr_pct_min"]
    turnover_min_20d = p.get("turnover_min_20d", turnover_min // 2)
    min_turnover_1d = turnover_min * 10000
    min_turnover_20d = turnover_min_20d * 10000

    def _strategy(snapshot_date, all_prices, top_n=TOP_N):
        conn = be._get_db()
        cur = conn.execute("""
            SELECT code, name, total_mcap FROM stocks
            WHERE total_mcap BETWEEN ? AND ?
              AND (is_st IS NULL OR is_st = 0)
              AND code NOT LIKE '688%%'
        """, (mcap_min * 1e8, mcap_max * 1e8))
        universe = {r["code"]: {"name": r["name"], "mcap": r["total_mcap"]}
                    for r in cur.fetchall()}
        conn.close()
        if not universe:
            return []

        conn = be._get_db()
        scored = []
        for code in list(universe.keys())[:2000]:
            try:
                cur = conn.execute("""
                    SELECT date, close, volume, turnover, high, low
                    FROM klines WHERE code=? AND date<=?
                    ORDER BY date DESC LIMIT 500
                """, (code, snapshot_date))
                kl_raw = cur.fetchall()
                if not kl_raw or len(kl_raw) < 60:
                    continue
                kl_raw.reverse()
                closes = [r[1] for r in kl_raw if r[1] is not None]
                if len(closes) < 60:
                    continue

                # 流动性硬约束
                latest_turnover = kl_raw[-1][3] or 0
                if latest_turnover < min_turnover_1d:
                    continue
                if len(kl_raw) >= 25:
                    recent_ts = [r[3] or 0 for r in kl_raw[-25:]]
                    avg_turnover_20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1)
                    if avg_turnover_20d < min_turnover_20d:
                        continue

                price_pos = (closes[-1] - min(closes)) / (max(closes) - min(closes)) * 100
                if price_pos > price_pos_max:
                    continue
                if len(kl_raw) < 25:
                    continue
                vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
                vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
                vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
                if vol_ratio < vol_ratio_min:
                    continue
                trs = []
                for i in range(1, len(kl_raw)):
                    h, l, pc = kl_raw[i][4] or 0, kl_raw[i][5] or 0, kl_raw[i-1][1] or 0
                    if h and l and pc:
                        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                if len(trs) < 14:
                    continue
                atr = sum(trs[-14:]) / 14
                close = kl_raw[-1][1] or 0
                atr_pct = atr / close * 100 if close else 0
                if atr_pct < atr_pct_min:
                    continue

                # 综合评分
                score = 0
                mcap_wan = (universe[code]["mcap"] or 0) / 1e4
                if mcap_min <= mcap_wan <= mcap_min + 15:
                    score += 40
                elif mcap_wan <= mcap_max:
                    score += 30
                if price_pos <= price_pos_max * 0.5:
                    score += 30
                elif price_pos <= price_pos_max:
                    score += 20
                if vol_ratio >= vol_ratio_min * 1.5:
                    score += 20
                elif vol_ratio >= vol_ratio_min:
                    score += 10
                if atr_pct >= atr_pct_min * 1.67:
                    score += 15
                elif atr_pct >= atr_pct_min:
                    score += 10

                scored.append((code, score))
            except Exception:
                continue
        conn.close()

        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:top_n]]

    return _strategy


def param_to_str(p):
    return (f"分位≤{p['price_pos_max']}% 量比≥{p['vol_ratio_min']:.1f} "
            f"市值{p['mcap_min']}-{p['mcap_max']}亿 成交额≥{p['turnover_min']}万 ATR≥{p['atr_pct_min']}%")


def run_single(p, label):
    """对一组参数运行完整回测"""
    print(f"\n  📡 [{label}] {param_to_str(p)}")
    t0 = time.time()
    strategy_fn = create_strategy_fn(p)
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
    print(f"    耗时: {elapsed:.0f}s")

    if "error" in results:
        print(f"    ❌ 失败: {results['error']}")
        return None

    wf = results.get("walk_forward", {})
    if not wf or wf.get("months", 0) < 6:
        print(f"    ⚠️ 数据不足 (仅 {wf.get('months', 0)} 个月)")
        return None

    return {"results": results, "wf": wf, "elapsed": elapsed, "label": label, "params": p}


def estimate_yearly_returns(strategy_fn, start_date_str, end_date_str):
    """估算分年收益"""
    import calendar
    yearly = {}
    for year in [2023, 2024, 2025, 2026]:
        ys = f"{year}-01"
        ye = f"{year}-12"
        if year == 2026:
            ye = "2026-07"
        try:
            r = be.run_backtest(
                strategy_fn,
                start_date=ys,
                end_date=ye,
                top_n=TOP_N,
                walk_forward=False,  # 年分段数据太少，用全样本
            )
            ins = r.get("in_sample", {})
            if ins and ins.get("months", 0) >= 3:
                yearly[year] = {
                    "annual_return": ins.get("cagr_pct"),
                    "max_drawdown": ins.get("max_drawdown_pct"),
                    "win_rate": ins.get("win_rate_pct"),
                    "total_return": ins.get("total_return_pct"),
                    "months": ins.get("months"),
                }
        except Exception as e:
            yearly[year] = {"error": str(e)}
    return yearly


def main():
    print(f"\n{'='*60}")
    print(f"  翻倍策略 V1 参数验证 — 完整 43 个月回测")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  区间: {BACKTEST_START} ~ {BACKTEST_END}")
    print(f"  选股: 每期 {TOP_N} 只, 月频, T+1开盘价")
    print(f"  流动性: 成交额≥8000万, 20日均≥4000万")
    print(f"{'='*60}")

    results = []
    for name, p in PARAM_SETS.items():
        r = run_single(p, name)
        if r:
            results.append(r)

    # ── 输出对比 ──
    print(f"\n{'='*60}")
    print(f"  📊 参数对比结果")
    print(f"{'='*60}")

    print(f"\n  {'参数':<42s} {'年化收益':>8s} {'最大回撤':>8s} {'月胜率':>7s} {'夏普':>6s} {'累计':>8s} {'基准':>7s}")
    print(f"  {'─'*95}")

    for r in results:
        wf = r["wf"]
        p = r["params"]
        ps = param_to_str(p)
        ar = wf.get("cagr_pct", 0)
        md = wf.get("max_drawdown_pct", 0)
        wr = wf.get("win_rate_pct", 0)
        sh = wf.get("sharpe_ratio", 0)
        tr = wf.get("total_return_pct", 0)
        bm = wf.get("benchmark_return_pct", 0)
        print(f"  {r['label']:<5s} {ps:<36s} {ar:>+7.1f}% {md:>7.1f}% {wr:>6.1f}% {sh:>+5.1f} {tr:>+7.1f}% {bm:>+6.1f}%")

    # ── V1/V2 对比 ──
    print(f"\n  ── 与历史结果对比 ──")
    print(f"  {'版本':<30s} {'年化收益':>8s} {'最大回撤':>8s} {'月胜率':>7s}")
    print(f"  {'─'*55}")
    print(f"  {'V1 (无流动性约束, 原默认参数)':<30s} {'+63,162%':>8s} {'18.55%':>8s} {'58.8%':>7s}")
    print(f"  {'V2 (成交额≥5000万, 20日均≥3000万)':<30s} {'-29.08%':>8s} {'47.09%':>8s} {'41.2%':>7s}")
    for r in results:
        wf = r["wf"]
        ar = wf.get("cagr_pct", 0)
        md = wf.get("max_drawdown_pct", 0)
        wr = wf.get("win_rate_pct", 0)
        print(f"  {r['label']:<30s} {ar:>+7.1f}% {md:>7.1f}% {wr:>6.1f}%")

    # ── 候选池数量 ──
    print(f"\n  ── 交易数据 ──")
    for r in results:
        wf = r["wf"]
        trades = wf.get("total_trades", 0)
        gapup = wf.get("gapup_fails", 0)
        smart = wf.get("smart_filtered", 0)
        months = wf.get("months", 0)
        print(f"  {r['label']}: {trades}笔交易, {gapup}次跳空失败, {smart}次聪明钱拦截, {months}个月")

    # ── 判定 ──
    print(f"\n  ── 判定结果 ──")
    for r in results:
        wf = r["wf"]
        ar = wf.get("cagr_pct", 0)
        md = wf.get("max_drawdown_pct", 0)
        wr = wf.get("win_rate_pct", 0)
        label = r["label"]

        if ar > 20 and md < 25:
            print(f"  ✅ [{label}] 年化{ar:.1f}%>20% 且 回撤{md:.1f}%<25% → **可替换当前V1参数**")
        elif ar < 0 or md > 30:
            print(f"  ❌ [{label}] 年化{ar:.1f}%<0 或 回撤{md:.1f}%>30% → **小样本过拟合，需要更多数据验证**")
        else:
            print(f"  ⚠️ [{label}] 年化{ar:.1f}% 回撤{md:.1f}% → 介于两者之间，建议结合更多指标判断")

    # ── 分年表现 ──
    print(f"\n  ── 分年表现（全样本回测，非Walk-Forward） ──")
    for r in results:
        print(f"\n  [{r['label']}]")
        strategy_fn = create_strategy_fn(r["params"])
        yearly = estimate_yearly_returns(strategy_fn, BACKTEST_START, BACKTEST_END)
        print(f"  {'年份':<8s} {'年化收益':>8s} {'最大回撤':>8s} {'月胜率':>7s} {'月数':>5s}")
        print(f"  {'─'*40}")
        for year in [2023, 2024, 2025, 2026]:
            yd = yearly.get(year, {})
            if "error" in yd:
                print(f"  {year:<8d} 错误: {yd['error']}")
            elif yd:
                print(f"  {year:<8d} {yd.get('annual_return',0):>+7.1f}% {yd.get('max_drawdown',0):>7.1f}% {yd.get('win_rate',0):>6.1f}% {yd.get('months',0):>4d}")
            else:
                print(f"  {year:<8d} {'—':>8s}")

    print(f"\n{'='*60}")
    print(f"  ✅ 验证完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
