#!/usr/bin/env python3
"""
压力测试框架 v1.0 — 模拟四个极端场景对组合的影响
==============================================
场景：
1. 2015年6月股灾（一个月内-35%）
2. 2018年全年去杠杆（慢熊-30%）
3. 2022年4月流动性危机（两周-25%）
4. 2024年2月微盘股暴跌（一周-20%）

组合：70%主升浪(聪明钱过滤) + 30%现金
双层止损：初始-8% → +10%保本 → +20%移动止盈15%
"""
import os, sys, json, math
from datetime import datetime, timedelta
from pathlib import Path

# 组合参数
PORTFOLIO_EQUITY = 1_000_000  # 初始资金100万
ACTIVE_RATIO = 0.70  # 70%仓位
CASH_RATIO = 0.30
N_STOCKS = 30  # 最多30只等权
STOP_LOSS = 0.08  # -8%初始止损
BREAKEVEN_TRIGGER = 0.10  # +10%后上移止损
TRAILING_TRIGGER = 0.20  # +20%后启用移动止盈
TRAILING_DRAWDOWN = 0.15  # 回撤15%卖出
PORTFOLIO_TRIM = 0.15  # 净值回撤15%减仓至50%

# 模拟场景
SCENARIOS = {
    "2015_股灾": {
        "description": "2015年6月股灾：一个月内-35%",
        "daily_returns": [-0.03, -0.05, -0.04, -0.06, -0.03, -0.02, -0.04, -0.05, -0.03, -0.02,
                          -0.01, -0.03, -0.02, -0.04, -0.01, -0.02, -0.01, -0.03, -0.05, -0.02,
                          -0.01, -0.01, 0.00, 0.01, -0.02, -0.01, 0.00, 0.01, 0.00, 0.01],
        "total_drop": -0.35,
        "duration_days": 22,
        "bounce_days": 60,  # 假设60天后反弹恢复
    },
    "2018_慢熊": {
        "description": "2018年全年去杠杆：慢熊-30%",
        "daily_returns": [-0.005] * 10 + [-0.01] * 20 + [-0.005] * 15 + [-0.01] * 15 +
                          [-0.003] * 20 + [-0.008] * 15 + [-0.005] * 10 + [-0.01] * 10 +
                          [0.002] * 10 + [-0.005] * 10 + [0.001] * 10,
        "total_drop": -0.30,
        "duration_days": 250,
        "bounce_days": 120,
    },
    "2022_4月": {
        "description": "2022年4月流动性危机：两周-25%",
        "daily_returns": [-0.02, -0.04, -0.03, -0.05, -0.02, -0.03, -0.04, -0.02, -0.01, -0.03,
                          -0.01, 0.00, 0.01, 0.02, 0.01, 0.00, -0.01, 0.00, 0.01, 0.02],
        "total_drop": -0.25,
        "duration_days": 10,
        "bounce_days": 45,
    },
    "2024_微盘": {
        "description": "2024年2月微盘股暴跌：一周-20%",
        "daily_returns": [-0.04, -0.06, -0.05, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.02,
                          0.01, 0.00, -0.01, 0.00, 0.01, 0.02, 0.01, 0.00, 0.01, 0.02],
        "total_drop": -0.20,
        "duration_days": 5,
        "bounce_days": 30,
    },
}

# 个股与指数的差异系数（微盘股暴跌时个股跌幅=指数跌幅×系数）
CRISIS_COEFF = {
    "2015_股灾": 1.2,  # 个股比指数跌得更多
    "2018_慢熊": 1.0,  # 个股与指数同步
    "2022_4月": 1.5,  # 流动性危机个股更惨
    "2024_微盘": 4.0,  # 微盘股暴跌，个股跌幅是指数4倍
}


def simulate_stress_scenario(scenario_name, daily_returns, total_drop, duration_days, bounce_days):
    """模拟单个场景"""
    active_capital = PORTFOLIO_EQUITY * ACTIVE_RATIO
    cash = PORTFOLIO_EQUITY * CASH_RATIO

    # 每只股票的初始仓位
    position_per_stock = active_capital / N_STOCKS

    # 模拟每只股票的价格
    stocks = []
    for i in range(N_STOCKS):
        stocks.append({
            "id": i,
            "price": 100.0,  # 初始价格
            "buy_price": 100.0,
            "high_water_mark": 100.0,
            "stop_level": "initial",  # initial, breakeven, trailing
            "active": True,
            "sold": False,
            "sell_day": None,
            "sell_reason": "",
        })

    total_value_history = [PORTFOLIO_EQUITY]
    active_count_history = [N_STOCKS]
    stop_hits = 0
    trim_triggered = False
    cooling_days_remaining = 0
    peak_value = PORTFOLIO_EQUITY
    max_dd = 0

    for day in range(max(duration_days, bounce_days) + 1):
        # 当天指数涨跌幅
        if day < len(daily_returns):
            index_ret = daily_returns[day]
        else:
            # 反弹阶段：指数反弹，但现金不产生收益
            # 只有尚未止损的股票参与反弹
            index_ret = 0.005

        # 个股跌幅 = 指数跌幅 × 危机系数
        stock_ret = index_ret * CRISIS_COEFF.get(scenario_name, 1.0)

        # 更新持仓
        day_total_value = cash  # 现金部分，不产生收益
        day_active_count = 0

        for s in stocks:
            if s["sold"]:
                continue

            # 更新价格
            old_price = s["price"]
            s["price"] *= (1 + stock_ret)

            # 跳过已涨停/跌停的场景简化
            if s["price"] <= 0:
                s["price"] = old_price * 0.001  # 接近归零

            if s["price"] > s["high_water_mark"]:
                s["high_water_mark"] = s["price"]

            # 计算收益
            ret = (s["price"] - s["buy_price"]) / s["buy_price"]

            # 双层止损检查
            if s["stop_level"] == "initial" and ret <= -STOP_LOSS:
                s["sold"] = True
                s["sell_day"] = day
                s["sell_reason"] = "初始止损-8%"
                stop_hits += 1
                # 回收残值
                cash += position_per_stock * (s["price"] / 100)
                continue

            if s["stop_level"] == "breakeven" and s["price"] < s["buy_price"]:
                s["sold"] = True
                s["sell_day"] = day
                s["sell_reason"] = "保本止损"
                stop_hits += 1
                cash += position_per_stock * (s["price"] / 100)
                continue

            if s["stop_level"] == "trailing":
                dd_from_peak = (s["high_water_mark"] - s["price"]) / s["high_water_mark"]
                if dd_from_peak >= TRAILING_DRAWDOWN:
                    s["sold"] = True
                    s["sell_day"] = day
                    s["sell_reason"] = "移动止盈"
                    stop_hits += 1
                    cash += position_per_stock * (s["price"] / 100)
                    continue

            # 升级止损级别
            if ret >= BREAKEVEN_TRIGGER and s["stop_level"] == "initial":
                s["stop_level"] = "breakeven"
            if ret >= TRAILING_TRIGGER and s["stop_level"] == "breakeven":
                s["stop_level"] = "trailing"

            # 还持有：计算市值
            day_active_count += 1
            day_total_value += position_per_stock * (s["price"] / 100)

        # 加上现金
        day_total_value += cash

        # 组合净值回撤检查
        if day_total_value > peak_value:
            peak_value = day_total_value
        current_dd = (peak_value - day_total_value) / peak_value
        if current_dd > max_dd:
            max_dd = current_dd

        # 净值回撤>15%减仓
        if current_dd >= PORTFOLIO_TRIM and not trim_triggered:
            trim_triggered = True
            # 减仓至50%：卖掉一半持仓
            stocks_to_sell = day_active_count // 2
            sold_value = 0
            for s in stocks:
                if not s["active"] or s["sold"]:
                    continue
                if stocks_to_sell <= 0:
                    break
                s["sold"] = True
                s["sell_day"] = day
                s["sell_reason"] = "组合减仓"
                cash += position_per_stock * (s["price"] / 100) * 0.95
                stocks_to_sell -= 1
                sold_value += 1
            day_active_count -= sold_value

        active_count_history.append(day_active_count)
        total_value_history.append(day_total_value)

    # 计算恢复时间
    recovery_days = None
    for i, v in enumerate(total_value_history):
        if v >= PORTFOLIO_EQUITY:
            recovery_days = i
            break

    # 最终统计
    final_value = total_value_history[-1] if total_value_history else PORTFOLIO_EQUITY
    total_return = (final_value / PORTFOLIO_EQUITY - 1) * 100

    return {
        "scenario": scenario_name,
        "description": SCENARIOS[scenario_name]["description"],
        "initial_value": PORTFOLIO_EQUITY,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "recovery_days": recovery_days if recovery_days else ">60天",
        "stop_hits": stop_hits,
        "trim_triggered": trim_triggered,
        "surviving_stocks": active_count_history[-1] if active_count_history else 0,
    }


def main():
    print("=" * 70)
    print("📊 压力测试框架 v1.0")
    print("   组合：70%主升浪(聪明钱过滤) + 30%现金")
    print("   止损：双层止损（初始-8% → +10%保本 → +20%移动止盈15%）")
    print("   风控：净值回撤>15%减仓至50%")
    print("=" * 70)

    results = []
    for name, scenario in SCENARIOS.items():
        print(f"\n{'─'*70}")
        print(f"📉 场景：{scenario['description']}")
        print(f"{'─'*70}")

        result = simulate_stress_scenario(
            name,
            scenario["daily_returns"],
            scenario["total_drop"],
            scenario["duration_days"],
            scenario["bounce_days"],
        )
        results.append(result)

        print(f"  初始资金: {result['initial_value']:>10,}")
        print(f"  最终资金: {result['final_value']:>10,}")
        print(f"  {'📈 累计收益:':<15s} {result['total_return_pct']:>+7.2f}%")
        print(f"  {'📉 最大回撤:':<15s} {result['max_drawdown_pct']:>7.2f}%")
        print(f"  {'🔄 恢复天数:':<15s} {result['recovery_days']}")
        print(f"  {'💥 止损触发:':<15s} {result['stop_hits']} 次")
        print(f"  {'✂️ 减仓触发:':<15s} {'是' if result['trim_triggered'] else '否'}")
        print(f"  {'🏥 幸存持仓:':<15s} {result['surviving_stocks']}/{N_STOCKS} 只")

    # 汇总
    print(f"\n{'='*70}")
    print("📋 压力测试结果汇总")
    print(f"{'='*70}")
    print(f"  {'场景':<20s} {'最大回撤':<10s} {'累计收益':<10s} {'恢复天数':<10s} {'止损':<8s} {'减仓':<6s}")
    print(f"  {'─'*64}")
    for r in results:
        scenario_label = r["scenario"][:18]
        print(f"  {scenario_label:<20s} {r['max_drawdown_pct']:>6.2f}%  {r['total_return_pct']:>+6.2f}%  {str(r['recovery_days']):<8s} {r['stop_hits']:>3d}次  {'是' if r['trim_triggered'] else '否':<6s}")

    # 风险评估
    print(f"\n  {'─'*40}")
    print(f"  🔍 风险评估")
    print(f"  {'─'*40}")

    max_dd_all = max(r["max_drawdown_pct"] for r in results)
    if max_dd_all > 25:
        print(f"  ❌ 最大回撤 {max_dd_all:.1f}% > 25% 阈值")
        print(f"  ⚠️ 建议：降低仓位比例或加入对冲工具")
    elif max_dd_all > 20:
        print(f"  ⚠️ 最大回撤 {max_dd_all:.1f}% 接近阈值")
        print(f"  💡 建议：考虑加入中证1000期货对冲")
    else:
        print(f"  ✅ 最大回撤 {max_dd_all:.1f}% 在可控范围内")

    # 检查是否所有场景都能恢复
    unrecoverable = [r for r in results if r["recovery_days"] == ">60天"]
    if unrecoverable:
        print(f"  ⚠️ {len(unrecoverable)}个场景在60天内未能恢复净值新高")
        for r in unrecoverable:
            print(f"    - {r['scenario']}: 最终收益{r['total_return_pct']:+.1f}%")
    else:
        print(f"  ✅ 所有场景均能在60天内恢复净值新高")


if __name__ == "__main__":
    main()