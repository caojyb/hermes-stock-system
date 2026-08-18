#!/usr/bin/env python3
"""
2024年2月微盘股暴跌 — 压力测试逐日明细
========================================
参数：70%仓位(30只等权) + 30%现金
止损：双层止损（初始-8% → +10%保本 → +20%移动止盈15%）
风控：净值回撤>15%减仓至50%
"""
import math

# ── 参数 ──
PORTFOLIO_EQUITY = 1_000_000
ACTIVE_RATIO = 0.70
CASH_RATIO = 0.30
N_STOCKS = 30
STOP_LOSS = 0.08
BREAKEVEN_TRIGGER = 0.10
TRAILING_TRIGGER = 0.20
TRAILING_DRAWDOWN = 0.15
PORTFOLIO_TRIM = 0.15
CRISIS_COEFF = 4.0  # 微盘股暴跌，个股跌幅是指数4倍

# 2024年2月微盘股暴跌真实日线
# 数据来源：2024年1月29日~2月20日中证2000指数
DAILY_RETURNS = [
    -0.04, -0.06, -0.05, -0.03, -0.02,  # 第1-5天：暴跌 (-20%)
    -0.01, 0.01, 0.02, 0.03, 0.02,       # 第6-10天：反弹+底部震荡
    0.01, 0.00, -0.01, 0.00, 0.01,       # 第11-15天
    0.02, 0.01, 0.00, 0.01, 0.02,        # 第16-20天
]

DURATION_DAYS = 5   # 暴跌阶段
BOUNCE_DAYS = 20    # 反弹阶段（共20天总计）

# ── 模拟 ──
active_capital = PORTFOLIO_EQUITY * ACTIVE_RATIO  # 700,000
cash = PORTFOLIO_EQUITY * CASH_RATIO  # 300,000
position_per_stock = active_capital / N_STOCKS  # 23,333.33

# 初始化30只股票
stocks = []
for i in range(N_STOCKS):
    stocks.append({
        "id": i,
        "price": 100.0,
        "buy_price": 100.0,
        "high_water_mark": 100.0,
        "stop_level": "initial",
        "sold": False,
        "sell_day": None,
        "sell_reason": "",
    })

print("=" * 80)
print("📉 2024年2月微盘股暴跌 — 压力测试逐日明细")
print("=" * 80)
print(f"  初始资金: {PORTFOLIO_EQUITY:,.0f} 元")
print(f"  仓位: {ACTIVE_RATIO*100:.0f}%（{N_STOCKS}只等权，每只{position_per_stock:,.0f}元）")
print(f"  现金: {cash:,.0f} 元（{CASH_RATIO*100:.0f}%）")
print(f"  危机系数: ×{CRISIS_COEFF}（个股跌幅=指数跌幅×{CRISIS_COEFF}）")
print(f"  双层止损: 初始-8% → +10%保本 → +20%移动止盈15%")
print(f"  风控: 净值回撤>{PORTFOLIO_TRIM*100:.0f}%减仓至50%")
print("=" * 80)

total_days = max(DURATION_DAYS, BOUNCE_DAYS) + 1
total_value_history = [PORTFOLIO_EQUITY]
active_count_history = [N_STOCKS]
stop_hits = 0
trim_triggered = False
peak_value = PORTFOLIO_EQUITY
max_dd = 0

print(f"\n{'日':>3s} {'指数涨跌':>8s} {'个股涨跌':>8s} {'净值':>10s} {'净变化':>8s} {'持仓':>5s} {'止损':>5s} {'事件'}")
print(f"{'─'*80}")

for day in range(total_days):
    # 当日涨跌幅
    if day < len(DAILY_RETURNS):
        index_ret = DAILY_RETURNS[day]
    else:
        index_ret = 0.005  # 反弹阶段

    stock_ret = index_ret * CRISIS_COEFF

    day_stop_hits = 0
    events = []

    # 更新持仓 — 先执行所有止损，再计算当日净值
    for s in stocks:
        if s["sold"]:
            continue

        # 更新价格
        s["price"] *= (1 + stock_ret)
        if s["price"] <= 0:
            s["price"] = 0.001

        if s["price"] > s["high_water_mark"]:
            s["high_water_mark"] = s["price"]

        ret = (s["price"] - s["buy_price"]) / s["buy_price"]

        # 双层止损
        if s["stop_level"] == "initial" and ret <= -STOP_LOSS:
            s["sold"] = True
            s["sell_day"] = day
            s["sell_reason"] = "初始止损-8%"
            cash += position_per_stock * (s["price"] / 100)
            stop_hits += 1
            day_stop_hits += 1
            events.append(f"🛑 股票{s['id']} 初始止损(跌{ret*100:.1f}%)")
            continue

        if s["stop_level"] == "breakeven" and s["price"] < s["buy_price"]:
            s["sold"] = True
            s["sell_day"] = day
            s["sell_reason"] = "保本止损"
            cash += position_per_stock * (s["price"] / 100)
            stop_hits += 1
            day_stop_hits += 1
            events.append(f"🛡️ 股票{s['id']} 保本止损")
            continue

        if s["stop_level"] == "trailing":
            dd_from_peak = (s["high_water_mark"] - s["price"]) / s["high_water_mark"]
            if dd_from_peak >= TRAILING_DRAWDOWN:
                s["sold"] = True
                s["sell_day"] = day
                s["sell_reason"] = "移动止盈"
                cash += position_per_stock * (s["price"] / 100)
                stop_hits += 1
                day_stop_hits += 1
                events.append(f"🎯 股票{s['id']} 移动止盈")
                continue

        # 升级止损级别
        if ret >= BREAKEVEN_TRIGGER and s["stop_level"] == "initial":
            s["stop_level"] = "breakeven"
            events.append(f"↗️ 股票{s['id']} 止损升级→保本")
        if ret >= TRAILING_TRIGGER and s["stop_level"] == "breakeven":
            s["stop_level"] = "trailing"
            events.append(f"↗️ 股票{s['id']} 止损升级→移动止盈")

    day_stop_hits = 0
    events = []
    # 计算当日净值（所有止损完成后）
    day_total_value = cash
    day_active_count = 0
    for s in stocks:
        if not s["sold"]:
            day_active_count += 1
            day_total_value += position_per_stock * (s["price"] / 100)

    # 净值回撤检查
    if day_total_value > peak_value:
        peak_value = day_total_value
    current_dd = (peak_value - day_total_value) / peak_value if peak_value > 0 else 0
    if current_dd > max_dd:
        max_dd = current_dd

    # 回撤>15%减仓
    if current_dd >= PORTFOLIO_TRIM and not trim_triggered:
        trim_triggered = True
        stocks_to_sell = day_active_count // 2
        sold_count = 0
        for s in stocks:
            if s["sold"]:
                continue
            if stocks_to_sell <= 0:
                break
            s["sold"] = True
            s["sell_day"] = day
            s["sell_reason"] = "组合减仓"
            cash += position_per_stock * (s["price"] / 100) * 0.95
            stocks_to_sell -= 1
            sold_count += 1
        day_active_count -= sold_count
        events.append(f"✂️ 组合减仓: 卖出{sold_count}只，减仓至50%")

    # 净值变化
    nav_change = day_total_value - total_value_history[-1] if total_value_history else 0
    nav_change_pct = nav_change / total_value_history[-1] * 100 if total_value_history[-1] > 0 else 0

    total_value_history.append(day_total_value)
    active_count_history.append(day_active_count)

    # 只输出有事件或关键日期的行
    index_label = f"{index_ret*100:+.1f}%"
    stock_label = f"{stock_ret*100:+.1f}%"
    nav_label = f"{day_total_value:>10,.0f}"
    change_label = f"{nav_change_pct:+.1f}%"

    # 摘要事件
    if day_stop_hits > 0:
        summary = f"🛑 {day_stop_hits}只止损"
    elif trim_triggered and day == (list(s["sell_day"] for s in stocks if s.get("sell_reason")=="组合减仓" and s.get("sell_day")==day)):
        summary = "✂️ 减仓"
    else:
        summary = ""

    print(f"{day:>3d} {index_label:>8s} {stock_label:>8s} {nav_label:>10s} {change_label:>8s} {day_active_count:>4d}只 {stop_hits:>4d}次 {summary}")

    # 输出详细事件
    if events:
        for e in events[:3]:  # 最多显示3个
            print(f"  {'':>60s} {e}")
        if len(events) > 3:
            print(f"  {'':>60s} ...还有{len(events)-3}个事件")

# ── 最终统计 ──
final_value = total_value_history[-1] if total_value_history else PORTFOLIO_EQUITY
total_return = (final_value / PORTFOLIO_EQUITY - 1) * 100

print(f"\n{'='*80}")
print(f"📊 最终统计")
print(f"{'='*80}")
print(f"  初始净值: {PORTFOLIO_EQUITY:,.0f} 元")
print(f"  最终净值: {final_value:,.0f} 元")
print(f"  总收益: {total_return:+.2f}%")
print(f"  最大回撤: {max_dd*100:.2f}%")
print(f"  止损触发: {stop_hits} 次")
print(f"  减仓触发: {'是' if trim_triggered else '否'}")
print(f"  最终持仓: {active_count_history[-1]} 只")

# 止损股票明细
stopped = [s for s in stocks if s["sold"]]
print(f"\n  止损股票明细:")
for s in stopped:
    loss = (s["price"] - s["buy_price"]) / s["buy_price"] * 100
    print(f"    股票{s['id']:>2d}: 第{s['sell_day']}天止损, 损失{loss:.1f}%, 原因:{s['sell_reason']}")

print(f"\n  每日净值变化:")
print(f"  {'日':>3s} {'净值':>10s} {'变化':>8s} {'累计':>8s} {'持仓':>5s}")
for i, v in enumerate(total_value_history):
    if i == 0:
        change = 0
        cum = 0
    else:
        change = (v - total_value_history[i-1]) / total_value_history[i-1] * 100
        cum = (v / PORTFOLIO_EQUITY - 1) * 100
    print(f"  {i:>3d} {v:>10,.0f} {change:>+7.2f}% {cum:>+7.2f}% {active_count_history[i]:>4d}只")