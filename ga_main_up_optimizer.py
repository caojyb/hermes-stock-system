#!/usr/bin/env python3
"""
主升浪策略 GA 参数优化
======================
优化 6 个参数：ROE 阈值、RSI 上下限、布林带位置上下限、波动率排名
回测区间：2024-01 ~ 2026-07（30个月）
Walk-Forward：24个月训练 + 6个月测试
"""
import os, sys, json, math, sqlite3, statistics, random, time, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent.parent / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"))
import backtest_engine as be

# ── 参数搜索空间 ──
PARAM_RANGES = {
    "roe_min": [x/10 for x in range(100, 275, 25)],           # 10.0~25.0 步长2.5
    "rsi_low": list(range(30, 55, 5)),                        # 30~50 步长5
    "rsi_high": list(range(60, 85, 5)),                       # 60~80 步长5
    "boll_low": list(range(10, 45, 5)),                       # 10~40 步长5
    "boll_high": list(range(60, 95, 5)),                      # 60~90 步长5
    "vol_rank_pct": [x/100 for x in range(20, 55, 5)],       # 0.20~0.50 步长0.05
}

# ── GA 参数 ──
POP_SIZE = 10
SELECT_SIZE = 5
GENERATIONS = 3
MUTATION_RATE = 0.3

# ── 回测参数 ──
BT_START = "2024-01"
BT_END = "2026-07"
TOP_N = 20
WF_WINDOW = 24
WF_STEP = 6

RESULTS_FILE = SCRIPT_DIR / "main_up_ga_results.json"


def create_param_strategy(p):
    """创建参数化主升浪策略"""
    roe_min = p["roe_min"]
    rsi_low = p["rsi_low"]
    rsi_high = p["rsi_high"]
    boll_low = p["boll_low"]
    boll_high = p["boll_high"]
    vol_rank_pct = p["vol_rank_pct"]

    def _strategy(snapshot_date, all_prices, top_n=TOP_N):
        conn = be._get_db()
        cur = conn.execute("""
            SELECT code, AVG(roe) as avg_roe FROM (
                SELECT code, roe, report_date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
                FROM financial_data WHERE roe IS NOT NULL AND report_date <= ?
            ) WHERE rn <= 8 GROUP BY code HAVING avg_roe >= ?
        """, (snapshot_date[:7] + "-01", roe_min))
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
            if len(kline_data[code]) < 80:
                kline_data[code].append(r["close"])
        conn.close()

        scored = []
        for code in codes:
            closes = kline_data.get(code, [])
            if len(closes) < 60:
                continue

            # 均线多头
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60
            if not (ma5 > ma10 > ma20 > ma60):
                continue

            # RSI
            if len(closes) >= 15:
                gains = losses = 0
                for i in range(1, 15):
                    diff = closes[-i] - closes[-i-1]
                    if diff >= 0:
                        gains += diff
                    else:
                        losses -= diff
                rsi = 100 - 100 / (1 + (gains / 14) / (losses / 14)) if losses > 0 else 100.0
                if rsi < rsi_low or rsi > rsi_high:
                    continue

            # 布林带位置
            if len(closes) >= 20:
                recent = closes[-20:]
                boll_ma = sum(recent) / 20
                variance = sum((p - boll_ma) ** 2 for p in recent) / 20
                std = math.sqrt(variance)
                boll_upper = boll_ma + 2 * std
                boll_lower = boll_ma - 2 * std
                if boll_upper != boll_lower:
                    boll_pos = (closes[-1] - boll_lower) / (boll_upper - boll_lower) * 100
                    if boll_pos < boll_low or boll_pos > boll_high:
                        continue

            # 波动率
            logs = [math.log(closes[i+1]/closes[i]) for i in range(len(closes)-1)
                    if closes[i] > 0 and closes[i+1] > 0]
            if len(logs) < 20:
                continue
            vol = statistics.stdev(logs) * math.sqrt(252)
            scored.append((code, vol, high_roe.get(code, 0)))

        if len(scored) < 5:
            return [c for c, _, _ in scored]

        scored.sort(key=lambda x: x[1])
        cutoff = max(5, int(len(scored) * vol_rank_pct))
        return [c for c, _, _ in scored[:top_n]]
    return _strategy


def random_param():
    """生成随机有效参数组合（保证 rsi_low < rsi_high, boll_low < boll_high）"""
    while True:
        p = {
            "roe_min": random.choice(PARAM_RANGES["roe_min"]),
            "rsi_low": random.choice(PARAM_RANGES["rsi_low"]),
            "rsi_high": random.choice(PARAM_RANGES["rsi_high"]),
            "boll_low": random.choice(PARAM_RANGES["boll_low"]),
            "boll_high": random.choice(PARAM_RANGES["boll_high"]),
            "vol_rank_pct": random.choice(PARAM_RANGES["vol_rank_pct"]),
        }
        if p["rsi_low"] < p["rsi_high"] and p["boll_low"] < p["boll_high"]:
            return p


def run_backtest_for(p):
    """运行单次回测"""
    try:
        fn = create_param_strategy(p)
        results = be.run_backtest(
            fn, start_date=BT_START, end_date=BT_END,
            top_n=TOP_N,
            walk_forward=True, walk_window=WF_WINDOW, walk_step=WF_STEP)
        if "error" in results:
            return None
        wf = results.get("walk_forward", {})
        if not wf or wf.get("months", 0) < 4:
            return None
        return {
            "annual_return": wf.get("cagr_pct", -100),
            "max_drawdown": wf.get("max_drawdown_pct", 100),
            "win_rate": wf.get("win_rate_pct", 0),
            "total_return": wf.get("total_return_pct", -100),
            "sharpe": wf.get("sharpe_ratio", 0),
            "calmar": wf.get("calmar_ratio", 0),
            "months": wf.get("months", 0),
            "trades": wf.get("total_trades", 0),
        }
    except Exception as e:
        return None


def calc_score(metrics):
    """综合得分：年化×0.3 + (-回撤)×0.3 + 胜率×0.4"""
    if metrics is None:
        return -9999
    ar = metrics.get("annual_return", -100) or -100
    md = metrics.get("max_drawdown", 100) or 100
    wr = metrics.get("win_rate", 0) or 0
    return ar * 0.3 + (-md) * 0.3 + wr * 0.4


def crossover(p1, p2):
    child = {}
    for key in PARAM_RANGES:
        child[key] = p1[key] if random.random() < 0.5 else p2[key]
    return child


def mutate(child):
    for key in PARAM_RANGES:
        if random.random() < MUTATION_RATE:
            vals = PARAM_RANGES[key]
            idx = vals.index(child[key]) if child[key] in vals else 0
            step = random.choice([-1, 1])
            new_idx = max(0, min(len(vals) - 1, idx + step))
            child[key] = vals[new_idx]
    if child["rsi_low"] >= child["rsi_high"]:
        child["rsi_low"] = max(PARAM_RANGES["rsi_low"][0], child["rsi_high"] - 10)
    if child["boll_low"] >= child["boll_high"]:
        child["boll_low"] = max(PARAM_RANGES["boll_low"][0], child["boll_high"] - 10)
    return child


def param_str(p):
    return (f"ROE≥{p['roe_min']:.0f}% RSI[{p['rsi_low']}-{p['rsi_high']}] "
            f"布林[{p['boll_low']}%-{p['boll_high']}%] 波动率前{int(p['vol_rank_pct']*100)}%")


def main():
    print(f"\n{'='*60}")
    print(f"  主升浪策略 GA 参数优化")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  回测: {BT_START}~{BT_END} Walk-Forward: {WF_WINDOW}+{WF_STEP}")
    print(f"  种群: {POP_SIZE} → 选{SELECT_SIZE} → {GENERATIONS}代")
    print(f"{'='*60}")

    population = [random_param() for _ in range(POP_SIZE)]
    all_results = []
    best_overall = None
    best_score = -9999

    for gen in range(GENERATIONS + 1):
        print(f"\n  🧬 第 {gen} 代 ({len(population)} 组)")
        gen_results = []
        for i, p in enumerate(population):
            print(f"  [{i+1}/{len(population)}] {param_str(p)}", end="", flush=True)
            t0 = time.time()
            metrics = run_backtest_for(p)
            elapsed = time.time() - t0

            if metrics is None:
                print(f"  ❌ ({elapsed:.0f}s)")
                gen_results.append((p, None, -9999))
                continue

            score = calc_score(metrics)
            ar = metrics["annual_return"]
            md = metrics["max_drawdown"]
            wr = metrics["win_rate"]
            print(f"  → 年化{ar:+.1f}% 回撤{md:.1f}% 胜率{wr:.1f}% 得分{score:+.1f} ({elapsed:.0f}s)")

            entry = {"params": p, "metrics": metrics, "score": score, "gen": gen}
            gen_results.append((p, metrics, score))
            all_results.append(entry)
            if score > best_score:
                best_score = score
                best_overall = entry
                print(f"    ⭐ 新最优!")

        gen_results.sort(key=lambda x: -x[2])
        top_k = [r[0] for r in gen_results[:SELECT_SIZE] if r[1] is not None]
        print(f"\n  🏆 Top {len(top_k)}:")
        for j, p in enumerate(top_k):
            print(f"    {j+1}. {param_str(p)}")

        if gen == GENERATIONS or len(top_k) < 2:
            break
        next_pop = list(top_k[:2])
        while len(next_pop) < POP_SIZE:
            p1, p2 = random.choice(top_k), random.choice(top_k)
            child = mutate(crossover(p1, p2))
            next_pop.append(child)
        population = next_pop[:POP_SIZE]

    # 最终报告
    all_results.sort(key=lambda x: -x["score"])
    print(f"\n{'='*60}")
    print(f"  🏆 最优 3 组参数")
    print(f"{'='*60}")
    print(f"  {'#':>2s} {'参数':<50s} {'年化':>7s} {'回撤':>7s} {'胜率':>6s} {'夏普':>5s} {'得分':>6s}")
    print(f"  {'─'*86}")

    for i, entry in enumerate(all_results[:3]):
        p = entry["params"]
        m = entry["metrics"]
        s = entry["score"]
        ps = param_str(p)
        print(f"  {i+1:2d} {ps:<50s} {m['annual_return']:>+6.1f}% {m['max_drawdown']:>6.1f}% {m['win_rate']:>5.1f}% {m['sharpe']:>+4.1f} {s:>+5.1f}")

    # 判定
    profitable = [e for e in all_results
                  if e["metrics"]["annual_return"] > 20
                  and e["metrics"]["max_drawdown"] < 15
                  and e["metrics"]["win_rate"] > 50]
    print(f"\n  ── 判定 ──")
    print(f"  总有效回测: {len(all_results)}")
    print(f"  达标组合(年化>20%, 回撤<15%, 胜率>50%): {len(profitable)}")

    if profitable:
        best = profitable[0]
        bp = best["params"]
        bm = best["metrics"]
        print(f"\n  ✅ 存在达标参数组合!")
        print(f"  Top: {param_str(bp)}")
        print(f"  年化 {bm['annual_return']:+.1f}% | 回撤 {bm['max_drawdown']:.1f}% | 胜率 {bm['win_rate']:.1f}% | 夏普 {bm['sharpe']:.1f}")
        print(f"\n  ✅ → 可加入模拟仓，与翻倍 V1 并行运行")
    else:
        print(f"\n  ❌ 无参数组合满足全部条件")

    # 与翻倍 V1 对比
    print(f"\n  ── 与翻倍 V1 Top3 对比 ──")
    print(f"  {'策略':<40s} {'年化':>7s} {'回撤':>7s} {'胜率':>6s}")
    print(f"  {'─'*62}")
    print(f"  {'翻倍 V1 Top3 (分位40%/量比2.7/成交额8000万)':<40s} {'+124.8%':>7s} {'17.5%':>7s} {'54.5%':>6s}")
    for i, entry in enumerate(all_results[:3]):
        m = entry["metrics"]
        ar = m["annual_return"]
        md = m["max_drawdown"]
        wr = m["win_rate"]
        label = f"主升浪 GA #{i+1}"
        print(f"  {label:<40s} {ar:>+6.1f}% {md:>6.1f}% {wr:>5.1f}%")

    # 参数敏感性
    print(f"\n  📊 参数敏感性分析:")
    param_impact = {}
    for key in PARAM_RANGES:
        by_val = defaultdict(list)
        for entry in all_results:
            v = entry["params"][key]
            ar = entry["metrics"]["annual_return"]
            by_val[v].append(ar)
        if by_val:
            avg = {v: sum(ars)/len(ars) for v, ars in by_val.items()}
            spread = max(avg.values()) - min(avg.values())
            param_impact[key] = spread
    labels = {"roe_min": "ROE阈值", "rsi_low": "RSI下限", "rsi_high": "RSI上限",
               "boll_low": "布林下限", "boll_high": "布林上限", "vol_rank_pct": "波动率排名"}
    for key, spread in sorted(param_impact.items(), key=lambda x: -x[1]):
        bar = "█" * max(1, int(spread))
        print(f"  {labels.get(key, key):<12s} {spread:>5.1f}% {bar}")

    # 保存
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_runs": len(all_results),
        "profitable_count": len(profitable),
        "top3": [{"params": e["params"], "metrics": e["metrics"], "score": e["score"]}
                 for e in all_results[:3]],
        "has_profitable": len(profitable) > 0,
        "param_impact": {k: round(v, 2) for k, v in param_impact.items()},
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 报告已保存: {RESULTS_FILE}")
    print(f"\n{'='*60}")
    print(f"  ✅ GA 优化完成")
    print(f"{'='*60}")


import time
if __name__ == "__main__":
    main()
