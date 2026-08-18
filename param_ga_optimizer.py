#!/usr/bin/env python3
"""
翻倍策略 V1 参数优化（遗传算法）
==================================
优化6个参数：价格分位上限、量比下限、市值下限、市值上限、成交额门槛、ATR下限
流动性约束：成交额 ≥ 参数值，20日均 ≥ 参数值的一半
回测区间：2025-01 ~ 2026-07（18个月，快速验证）
"""
import os, sys, json, math, random, sqlite3, calendar, time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / ".." / ".." / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"))
import backtest_engine as be

# ── 参数搜索空间 ──
PARAM_RANGES = {
    "price_pos_max": list(range(20, 80, 10)),      # 20~70 步长10
    "vol_ratio_min": [x/10 for x in range(12, 33, 3)],  # 1.2~3.0 步长0.3
    "mcap_min": list(range(3, 17, 2)),              # 3~15 步长2
    "mcap_max": list(range(30, 110, 10)),           # 30~100 步长10
    "turnover_min": list(range(1000, 9000, 1000)),  # 1000~8000 步长1000
    "atr_pct_min": list(range(2, 7)),                # 2~6 步长1
}

# ── GA参数 ──
POPULATION_SIZE = 10        # 初始种群
SELECTION_SIZE = 5          # 每代选5个
GENERATIONS = 3             # 迭代3轮
MUTATION_RATE = 0.3         # 每个参数30%概率变异

# ── 回测参数 ──
BACKTEST_START = "2025-01"
BACKTEST_END = "2026-07"
TOP_N = 20
REPORT_FILE = SCRIPT_DIR / "param_optimization_report.json"


def create_strategy_fn(p):
    """根据参数创建策略函数（含流动性约束）"""
    price_pos_max = p["price_pos_max"]
    vol_ratio_min = p["vol_ratio_min"]
    mcap_min = p["mcap_min"]
    mcap_max = p["mcap_max"]
    turnover_min = p["turnover_min"]      # 万元
    atr_pct_min = p["atr_pct_min"]

    # 20日均成交额门槛 = 成交额门槛的一半
    turnover_min_20d = turnover_min // 2   # 万元
    min_turnover_1d = turnover_min * 10000    # 万元→元
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

                # 流动性硬约束1: 信号日成交额
                latest_turnover = kl_raw[-1][3] or 0  # turnover字段是元
                if latest_turnover < min_turnover_1d:
                    continue

                # 流动性硬约束2: 近20日均成交额
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


def random_param():
    """生成随机有效参数组合（保证 mcap_min < mcap_max）"""
    while True:
        p = {
            "price_pos_max": random.choice(PARAM_RANGES["price_pos_max"]),
            "vol_ratio_min": random.choice(PARAM_RANGES["vol_ratio_min"]),
            "mcap_min": random.choice(PARAM_RANGES["mcap_min"]),
            "mcap_max": random.choice(PARAM_RANGES["mcap_max"]),
            "turnover_min": random.choice(PARAM_RANGES["turnover_min"]),
            "atr_pct_min": random.choice(PARAM_RANGES["atr_pct_min"]),
        }
        if p["mcap_min"] < p["mcap_max"]:
            return p


def run_backtest_for_params(p):
    """对一组参数运行回测，返回指标"""
    try:
        strategy_fn = create_strategy_fn(p)
        results = be.run_backtest(
            strategy_fn,
            start_date=BACKTEST_START,
            end_date=BACKTEST_END,
            top_n=TOP_N,
            walk_forward=True,
            walk_window=12,    # 12个月训练
            walk_step=6        # 6个月步进（18个月区间分2段）
        )

        if "error" in results:
            return None

        wf = results.get("walk_forward", {})
        if not wf or wf.get("months", 0) < 3:
            return None

        return {
            "annual_return": wf.get("cagr_pct", -100),
            "max_drawdown": wf.get("max_drawdown_pct", 100),
            "win_rate": wf.get("win_rate_pct", 0),
            "total_return": wf.get("total_return_pct", -100),
            "sharpe": wf.get("sharpe_ratio", 0),
            "calmar": wf.get("calmar_ratio", 0),
            "profit_loss_ratio": wf.get("profit_loss_ratio", 0),
            "months": wf.get("months", 0),
            "trades": wf.get("total_trades", 0),
            "gapup_fails": wf.get("gapup_fails", 0),
        }
    except Exception as e:
        return None


def calc_score(metrics):
    """计算综合得分
    年化收益 × 0.4 + (-最大回撤) × 0.3 + 胜率 × 0.3
    """
    if metrics is None:
        return -9999
    ar = metrics.get("annual_return", -100) or -100
    md = metrics.get("max_drawdown", 100) or 100
    wr = metrics.get("win_rate", 0) or 0
    score = ar * 0.4 + (-md) * 0.3 + wr * 0.3
    # 额外惩罚：负收益直接减半
    if ar < 0:
        score *= 0.5
    return score


def crossover(parent1, parent2):
    """交叉：每个参数随机取自一个父代"""
    child = {}
    for key in PARAM_RANGES:
        child[key] = parent1[key] if random.random() < 0.5 else parent2[key]
    return child


def mutate(child):
    """变异：每个参数以 MUTATION_RATE 概率 ±1步"""
    for key in PARAM_RANGES:
        if random.random() < MUTATION_RATE:
            values = PARAM_RANGES[key]
            idx = values.index(child[key]) if child[key] in values else 0
            step = random.choice([-1, 1])
            new_idx = max(0, min(len(values) - 1, idx + step))
            child[key] = values[new_idx]
    # 保证 mcap_min < mcap_max
    if child["mcap_min"] >= child["mcap_max"]:
        child["mcap_min"] = max(PARAM_RANGES["mcap_min"][0], child["mcap_max"] - 2)
    return child


def param_to_str(p):
    return (f"价格分位≤{p['price_pos_max']}% "
            f"量比≥{p['vol_ratio_min']:.1f} "
            f"市值{p['mcap_min']}-{p['mcap_max']}亿 "
            f"成交额≥{p['turnover_min']}万 "
            f"ATR≥{p['atr_pct_min']}%")


def main():
    print(f"\n{'='*60}")
    print(f"  翻倍策略 V1 参数优化（遗传算法）")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  回测区间: {BACKTEST_START} ~ {BACKTEST_END}")
    print(f"  种群: {POPULATION_SIZE} → 选{SELECTION_SIZE} → {GENERATIONS}代")
    print(f"{'='*60}")

    # ── 第0代：随机生成初始种群 ──
    print(f"\n📡 生成初始种群...")
    population = [random_param() for _ in range(POPULATION_SIZE)]

    all_results = []  # 所有结果
    best_overall = None
    best_score = -9999

    for gen in range(GENERATIONS + 1):
        print(f"\n{'─'*55}")
        print(f"  🧬 第 {gen} 代 ({len(population)} 组)")
        print(f"{'─'*55}")

        gen_results = []
        for i, p in enumerate(population):
            print(f"  [{i+1}/{len(population)}] {param_to_str(p)}", end="", flush=True)
            t0 = time.time()
            metrics = run_backtest_for_params(p)
            elapsed = time.time() - t0

            if metrics is None:
                print(f"  ❌ 失败 ({elapsed:.0f}s)")
                gen_results.append((p, None, -9999))
                continue

            score = calc_score(metrics)
            ar = metrics["annual_return"]
            md = metrics["max_drawdown"]
            wr = metrics["win_rate"]
            print(f"  → 年化{ar:+.1f}% 回撤{md:.1f}% 胜率{wr:.1f}% 得分{score:+.1f} ({elapsed:.0f}s)")

            entry = {
                "params": p,
                "metrics": metrics,
                "score": score,
                "gen": gen,
            }
            gen_results.append((p, metrics, score))
            all_results.append(entry)

            if score > best_score:
                best_score = score
                best_overall = entry
                print(f"    ⭐ 新的最优!")

        # 选前 SELECTION_SIZE 名
        gen_results.sort(key=lambda x: -x[2])
        top_k = [r[0] for r in gen_results[:SELECTION_SIZE] if r[1] is not None]

        print(f"\n  🏆 第{gen}代 Top {len(top_k)}:")
        for j, p in enumerate(top_k):
            print(f"    {j+1}. {param_to_str(p)}")

        # 最后一代不产生子代
        if gen == GENERATIONS or len(top_k) < 2:
            break

        # 生成下一代：交叉 + 变异
        next_pop = []
        # 精英保留：前2直接进入下一代
        next_pop.extend(top_k[:2])

        # 其余通过交叉变异产生
        while len(next_pop) < POPULATION_SIZE:
            p1 = random.choice(top_k)
            p2 = random.choice(top_k)
            child = crossover(p1, p2)
            child = mutate(child)
            next_pop.append(child)

        population = next_pop[:POPULATION_SIZE]
        print(f"\n  🌱 生成第{gen+1}代 ({len(population)} 组)...")

    # ── 最终报告 ──
    print(f"\n{'='*60}")
    print(f"  📊 参数优化完成")
    print(f"  总回测次数: {len(all_results)}")
    print(f"{'='*60}")

    # 按得分排序
    all_results.sort(key=lambda x: -x["score"])

    print(f"\n  🏆 最优 5 组参数组合:")
    print(f"  {'#':>2s} {'参数':<55s} {'年化收益':>8s} {'最大回撤':>8s} {'月胜率':>7s} {'夏普':>6s} {'得分':>6s}")
    print(f"  {'─'*100}")

    for i, entry in enumerate(all_results[:5]):
        p = entry["params"]
        m = entry["metrics"]
        s = entry["score"]
        ps = param_to_str(p)
        print(f"  {i+1:2d} {ps:<55s} {m['annual_return']:>+7.1f}% {m['max_drawdown']:>7.1f}% {m['win_rate']:>6.1f}% {m['sharpe']:>+5.1f} {s:>+5.1f}")

    # 检查是否存在稳定盈利组合
    profitable = [e for e in all_results if e["metrics"]["annual_return"] > 0
                  and e["metrics"]["max_drawdown"] < 30
                  and e["metrics"]["win_rate"] > 45]

    print(f"\n  📋 优化结果分析:")
    print(f"    总有效回测: {len(all_results)}")
    print(f"    盈利组合: {len(profitable)} (年化>0, 回撤<30%, 胜率>45%)")

    if profitable:
        print(f"\n  ✅ 存在稳定盈利参数组合!")
        print(f"  {'#' if len(profitable) > 0 else ''} 推荐使用 Top1 参数替换当前 V1 默认参数:")
        best = profitable[0]
        p = best["params"]
        print(f"    {param_to_str(p)}")
        print(f"    年化 {best['metrics']['annual_return']:+.1f}% | "
              f"回撤 {best['metrics']['max_drawdown']:.1f}% | "
              f"胜率 {best['metrics']['win_rate']:.1f}%")
    else:
        print(f"\n  ❌ 在流动性约束下，翻倍策略 V1 无法稳定盈利。")
        print(f"     需要调整底层选股逻辑，或改用其他策略框架。")

    # 参数敏感性分析
    print(f"\n  📊 参数敏感性分析:")
    print(f"    分析各参数与年化收益的相关性...")

    # 按每个参数分组看平均年化
    param_impact = {}
    for key in PARAM_RANGES:
        by_value = {}
        for entry in all_results:
            v = entry["params"][key]
            ar = entry["metrics"]["annual_return"]
            if v not in by_value:
                by_value[v] = []
            by_value[v].append(ar)
        # 计算最大值-最小值的差距
        if by_value:
            avg_by_val = {v: sum(ars)/len(ars) for v, ars in by_value.items()}
            spread = max(avg_by_val.values()) - min(avg_by_val.values())
            param_impact[key] = spread

    param_impact_sorted = sorted(param_impact.items(), key=lambda x: -x[1])
    print(f"    {'参数':<20s} {'影响幅度':>10s}")
    print(f"    {'─'*30}")
    for key, spread in param_impact_sorted:
        label = {
            "price_pos_max": "价格分位上限",
            "vol_ratio_min": "量比下限",
            "mcap_min": "市值下限",
            "mcap_max": "市值上限",
            "turnover_min": "成交额门槛",
            "atr_pct_min": "ATR下限",
        }.get(key, key)
        bar = "█" * max(1, int(spread / 2))
        print(f"    {label:<20s} {spread:>6.1f}% {bar}")

    # 保存结果
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_runs": len(all_results),
        "profitable_count": len(profitable),
        "top5": [
            {
                "params": e["params"],
                "metrics": e["metrics"],
                "score": e["score"],
            }
            for e in all_results[:5]
        ],
        "has_profitable": len(profitable) > 0,
        "param_impact": {k: round(v, 2) for k, v in param_impact_sorted},
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 报告已保存: {REPORT_FILE}")
    print(f"\n{'='*60}")
    print(f"  ✅ 参数优化完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
