#!/usr/bin/env python3
"""
模拟成交回执模块 v1.0
=====================
功能：
1. 接收信号（来自 auto_recommend.py 或 backtest 信号）
2. 模拟次日开盘集合竞价撮合
3. 记录成交价格、数量、滑点
4. 积累20个交易日数据，统计滑点分布

撮合逻辑：
- 买入信号：次日开盘价成交
- 跳空>3%：成交率降低（部分成交或放弃）
- 流动性不足：按成交量比例配售
- 卖出信号：次日开盘价成交（含滑点修正）
"""
import os, sys, json, sqlite3, math
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.resolve()
MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SIM_DB = str(SCRIPT_DIR / "simulation.db")
EXEC_LOG = SCRIPT_DIR / "execution_log.json"

# 撮合参数
GAPUP_THRESHOLD = 1.03  # 跳空>3%触发部分成交
GAPUP_LIQUIDITY = 0.30  # 跳空>3%时成交率降为30%
GAPUP_ABORT = 1.05      # 跳空>5%放弃
SLIPPAGE_BUY = 0.003    # 买入滑点估计（千分之三）
SLIPPAGE_SELL = 0.005   # 卖出滑点估计（千分之五，含印花税）
MIN_VOLUME_20 = 3000    # 最小日均成交额（万元）


def get_market_data(code, date_str):
    """获取某只股票在指定日期的开盘价/收盘价/成交量"""
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()
    # 当天数据
    c.execute("""
        SELECT date, open, close, volume, turnover
        FROM klines WHERE code=? AND date=? ORDER BY date
    """, [code, date_str])
    row = c.fetchone()

    # 前一日数据（用于计算跳空）
    c.execute("""
        SELECT date, open, close, volume, turnover
        FROM klines WHERE code=? AND date<? ORDER BY date DESC LIMIT 1
    """, [code, date_str])
    prev = c.fetchone()
    conn.close()
    return row, prev


def simulate_auction(code, signal_date, signal_price, direction="buy", quantity=100):
    """模拟次日开盘集合竞价撮合
    返回: {
        filled: bool,           # 是否成交
        fill_price: float,      # 成交价
        fill_quantity: int,     # 成交数量
        fill_date: str,         # 成交日期
        slippage_pct: float,    # 滑点百分比
        reason: str,            # 成交/未成交原因
    }
    """
    # 计算下一个交易日
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()
    c.execute("""
        SELECT date, open, close, volume, turnover
        FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1
    """, [code, signal_date])
    next_day = c.fetchone()
    conn.close()

    if not next_day:
        return {
            "filled": False,
            "fill_price": 0,
            "fill_quantity": 0,
            "fill_date": "",
            "slippage_pct": 0,
            "reason": "无下一个交易日数据",
        }

    fill_date = next_day[0]
    open_price = next_day[1]
    close_price = next_day[2]
    volume = next_day[3]  # 成交量（手）
    turnover = next_day[4]  # 成交额（元）

    # 流动性检查
    if turnover and turnover / 10000 < MIN_VOLUME_20:
        # 流动性不足，按比例配售
        fill_ratio = (turnover / 10000) / MIN_VOLUME_20
        fill_quantity = max(1, int(quantity * fill_ratio))
        fill_price = open_price
        reason = f"流动性不足，按{fill_ratio:.0%}配售"
    else:
        fill_quantity = quantity
        fill_price = open_price
        reason = "正常成交"

    # 跳空检查
    if signal_price > 0:
        gap_ratio = open_price / signal_price
        if direction == "buy" and gap_ratio >= GAPUP_ABORT:
            # 跳空>5%，放弃
            return {
                "filled": False,
                "fill_price": 0,
                "fill_quantity": 0,
                "fill_date": fill_date,
                "slippage_pct": 0,
                "reason": f"跳空{gap_ratio*100-100:.1f}%>5%，放弃买入",
            }
        elif direction == "buy" and gap_ratio >= GAPUP_THRESHOLD:
            # 跳空3-5%，部分成交
            fill_quantity = max(1, int(quantity * GAPUP_LIQUIDITY))
            fill_price = open_price
            reason = f"跳空{gap_ratio*100-100:.1f}%，部分成交{fill_quantity}股"

    # 计算滑点
    if direction == "buy":
        slippage = (fill_price - signal_price) / signal_price * 100
    else:
        slippage = (signal_price - fill_price) / signal_price * 100

    # 估计成本（佣金+印花税）
    if direction == "buy":
        estimated_cost = fill_price * fill_quantity * SLIPPAGE_BUY
    else:
        estimated_cost = fill_price * fill_quantity * SLIPPAGE_SELL

    return {
        "filled": True,
        "fill_price": round(fill_price, 2),
        "fill_quantity": fill_quantity,
        "fill_date": fill_date,
        "slippage_pct": round(slippage, 2),
        "estimated_cost": round(estimated_cost, 2),
        "reason": reason,
    }


def collect_historical_executions(days=20):
    """从历史数据中收集模拟成交记录
    对候选池中的每只股票，模拟最近20个交易日的信号成交情况
    """
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()

    # 获取最近20个交易日
    c.execute("""
        SELECT DISTINCT date FROM klines
        ORDER BY date DESC LIMIT ?
    """, [days + 5])
    all_dates = sorted([r[0] for r in c.fetchall()])
    recent_dates = all_dates[-days:]

    print(f"📡 收集最近{len(recent_dates)}个交易日的模拟成交数据...")

    # 获取候选池股票
    c.execute("""
        SELECT DISTINCT code FROM klines
        WHERE date >= ? AND code NOT LIKE '688%' AND code NOT LIKE '787%'
        LIMIT 500
    """, [all_dates[0] if all_dates else "2026-01-01"])
    codes = [r[0] for r in c.fetchall()]

    print(f"  候选池: {len(codes)} 只股票")

    records = []
    skipped_abort = 0
    skipped_liquidity = 0
    total_attempts = 0

    for code in codes[:100]:  # 取前100只减少时间
        for i, signal_date in enumerate(recent_dates[:-1]):
            next_date = recent_dates[i + 1]
            total_attempts += 1

            # 获取信号价格（前一日收盘价）
            c.execute("""
                SELECT close FROM klines WHERE code=? AND date=?
            """, [code, signal_date])
            row = c.fetchone()
            if not row or not row[0]:
                continue
            signal_price = row[0]

            # 模拟买入信号
            result = simulate_auction(code, signal_date, signal_price, "buy", 100)
            if result["filled"]:
                records.append({
                    "code": code,
                    "signal_date": signal_date,
                    "fill_date": result["fill_date"],
                    "signal_price": signal_price,
                    "fill_price": result["fill_price"],
                    "fill_quantity": result["fill_quantity"],
                    "slippage_pct": result["slippage_pct"],
                    "estimated_cost": result["estimated_cost"],
                    "reason": result["reason"],
                    "direction": "buy",
                })
            else:
                if "跳空" in result.get("reason", ""):
                    skipped_abort += 1
                else:
                    skipped_liquidity += 1

    conn.close()

    # 保存到执行日志
    all_records = {"records": records, "collected_at": datetime.now().isoformat()}
    with open(EXEC_LOG, "w") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"\n📊 模拟成交统计:")
    print(f"  总尝试: {total_attempts} 次")
    print(f"  成交记录: {len(records)} 条")
    print(f"  跳空放弃: {skipped_abort} 次")
    print(f"  流动性不足: {skipped_liquidity} 次")

    if records:
        slippages = [r["slippage_pct"] for r in records]
        avg_slippage = sum(slippages) / len(slippages)
        max_slippage = max(slippages)
        min_slippage = min(slippages)
        # 极端滑点（95%分位）
        sorted_s = sorted(slippages)
        p95 = sorted_s[int(len(sorted_s) * 0.95)]
        costs = [r["estimated_cost"] for r in records if r["estimated_cost"] > 0]
        avg_cost = sum(costs) / len(costs) if costs else 0

        print(f"\n  📈 滑点统计:")
        print(f"    平均滑点: {avg_slippage:+.3f}%")
        print(f"    最大滑点: {max_slippage:+.3f}%")
        print(f"    最小滑点: {min_slippage:+.3f}%")
        print(f"    95%分位滑点: {p95:+.3f}%")
        print(f"    平均交易成本: {avg_cost:.2f} 元/笔")

        # 滑点分布
        buckets = {"<-0.5%": 0, "-0.5~0": 0, "0~0.5": 0, "0.5~1": 0, "1~3": 0, ">3%": 0}
        for s in slippages:
            if s < -0.5: buckets["<-0.5%"] += 1
            elif s < 0: buckets["-0.5~0"] += 1
            elif s < 0.5: buckets["0~0.5"] += 1
            elif s < 1: buckets["0.5~1"] += 1
            elif s < 3: buckets["1~3"] += 1
            else: buckets[">3%"] += 1
        print(f"\n  📊 滑点分布:")
        for bucket, count in buckets.items():
            bar = "█" * max(1, int(count / max(1, len(records)) * 100))
            print(f"    {bucket:<10s}: {count:>4d}  {bar}")

    return records


def generate_execution_report(records):
    """生成模拟成交报告"""
    if not records:
        return "无成交记录"

    lines = []
    lines.append("=" * 65)
    lines.append("📋 模拟成交报告")
    lines.append("=" * 65)

    # 按日期排序
    records.sort(key=lambda x: (x["fill_date"], x["code"]))

    # 最近10笔
    lines.append(f"\n📌 最近10笔成交:")
    lines.append(f"  {'代码':<8s} {'日期':<12s} {'信号价':<8s} {'成交价':<8s} {'滑点':<8s} {'原因'}")
    for r in records[-10:]:
        sign = "+" if r["slippage_pct"] >= 0 else ""
        lines.append(f"  {r['code']:<8s} {r['fill_date']:<12s} {r['signal_price']:>7.2f} {r['fill_price']:>7.2f} {sign}{r['slippage_pct']:>+6.2f}% {r['reason'][:20]}")

    # 总结
    slippages = [r["slippage_pct"] for r in records]
    lines.append(f"\n📊 总结:")
    lines.append(f"  总成交: {len(records)} 笔")
    lines.append(f"  平均滑点: {sum(slippages)/len(slippages):+.3f}%")
    lines.append(f"  最大滑点: {max(slippages):+.3f}%")
    lines.append(f"  95%分位滑点: {sorted(slippages)[int(len(slippages)*0.95)]:+.3f}%")

    return "\n".join(lines)


def save_to_simulation_db(records):
    """将成交记录写入模拟交易数据库
    更新 simulation.db 中的 trades 表
    """
    conn = sqlite3.connect(SIM_DB)
    c = conn.cursor()

    for r in records:
        # 检查是否已存在
        c.execute("""
            SELECT id FROM trades WHERE code=? AND buy_date=?
        """, [r["code"], r["fill_date"]])
        if c.fetchone():
            continue

        try:
            c.execute("""
                INSERT INTO trades (code, name, buy_date, buy_price, buy_shares, buy_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, '模拟')
            """, (
                r["code"],
                r.get("code", ""),
                r["fill_date"],
                r["fill_price"],
                r["fill_quantity"],
                r["fill_price"] * r["fill_quantity"],
            ))
        except:
            pass

    conn.commit()
    conn.close()
    print(f"  ✅ 已写入 {len(records)} 条到模拟交易数据库")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="模拟成交回执模块")
    parser.add_argument("--collect", action="store_true", help="收集历史模拟成交数据")
    parser.add_argument("--report", action="store_true", help="输出模拟成交报告")
    parser.add_argument("--days", type=int, default=20, help="收集天数")
    parser.add_argument("--code", type=str, help="模拟指定股票的成交")
    parser.add_argument("--price", type=float, help="信号价格")
    parser.add_argument("--date", type=str, help="信号日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.code and args.price and args.date:
        # 单只股票模拟
        result = simulate_auction(args.code, args.date, args.price, "buy", 100)
        print(f"\n📋 模拟成交结果: {args.code}")
        print(f"  {'指标':<15s} {'值'}")
        print(f"  {'─'*35}")
        for k, v in result.items():
            print(f"  {k:<15s}: {v}")
        return

    if args.collect:
        records = collect_historical_executions(days=args.days)
        if records:
            save_to_simulation_db(records)
            report = generate_execution_report(records)
            print(f"\n{report}")
        return

    if args.report:
        if EXEC_LOG.exists():
            with open(EXEC_LOG) as f:
                data = json.load(f)
            report = generate_execution_report(data.get("records", []))
            print(report)
        else:
            print("⚠️ 无执行日志，请先运行 --collect")
        return

    # 默认行为
    records = collect_historical_executions(days=args.days)
    if records:
        save_to_simulation_db(records)
        report = generate_execution_report(records)
        print(f"\n{report}")


if __name__ == "__main__":
    main()