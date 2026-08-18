#!/usr/bin/env python3
"""
L5-2 连续止损测试
连续 5 个交易日，每天最多 3 只止损；使用 double_up_scores 真实候选池（23 只）
"""
import sqlite3
from datetime import date, timedelta, datetime
from collections import defaultdict

SIM_DB = "/home/caojy/.hermes/scripts/cron/simulation.db"
MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
TOTAL_CAPITAL = 1_000_000.0
POSITION_PCT = 0.20          # 总仓位 20%
STOP_LOSS = 0.08             # 单只止损 -8%
SLIPPAGE = 0.05              # 滑点 5%
PORTFOLIO_DRAWDOWN_LIMIT = 0.15
COOLING_DAYS = 3
EXEMPTION_THRESHOLD = 0.04   # 连续 2 日反弹 >4% 豁免冷却


def calc_transaction_cost(amount, is_buy=True):
    commission = max(amount * 0.00015, 5.0)
    transfer_fee = amount * 0.00001
    if is_buy:
        return commission + transfer_fee
    stamp_tax = amount * 0.0005
    return commission + stamp_tax + transfer_fee


def get_candidates(limit=23):
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute("""
        SELECT code, name, sector, total_score
        FROM double_up_scores
        WHERE scan_date=(SELECT MAX(scan_date) FROM double_up_scores)
        ORDER BY total_score DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


def get_latest_close(code):
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute("""
        SELECT close FROM klines
        WHERE code=? AND close IS NOT NULL AND close > 0
        ORDER BY date DESC LIMIT 1
    """, (code,))
    r = cur.fetchone()
    con.close()
    return r[0] if r else 10.0


def init_portfolio(candidates):
    """用前 10 只候选初始化仓位，每只目标仓位 2%"""
    con = sqlite3.connect(SIM_DB)
    cur = con.cursor()
    cur.execute("DELETE FROM trades")
    cur.execute("DELETE FROM portfolio_snapshots")
    con.commit()
    target = TOTAL_CAPITAL * POSITION_PCT / 10  # 每只 2%
    today = date.today().isoformat()
    for code, name, sector, _ in candidates[:10]:
        price = get_latest_close(code)
        shares = int(target / price) if price > 0 else 0
        if shares <= 0:
            shares = 1
            price = target
        amount = shares * price
        cost = calc_transaction_cost(amount, is_buy=True)
        total_cost = amount + cost
        actual_price = total_cost / shares
        cur.execute("""
            INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares,
                                buy_amount, status, signal_type)
            VALUES (?,?,?,?,?,?,?, '持有', '⭐⭐⭐')
        """, (code, name, sector, today, actual_price, shares, total_cost))
    con.commit()
    con.close()
    print("已初始化前 10 只候选为持仓（每只目标仓位 2%）：")
    for code, name, sector, _ in candidates[:10]:
        print(f"  {code} {name} ({sector})")
    print()


def get_portfolio_stats():
    con = sqlite3.connect(SIM_DB)
    cur = con.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(profit_amount),0)
        FROM trades
        WHERE status IN ('清仓止盈','止损','部分止盈','减仓')
    """)
    realized_pnl = cur.fetchone()[0]
    cur.execute("""
        SELECT COALESCE(SUM(buy_shares * buy_price),0)
        FROM trades
        WHERE status IN ('持有','部分止盈')
    """)
    holding_cost = cur.fetchone()[0]
    cur.execute("""
        SELECT COALESCE(SUM(buy_amount),0)
        FROM trades
        WHERE status IN ('持有','部分止盈')
    """)
    total_invested = cur.fetchone()[0]
    cash = TOTAL_CAPITAL - total_invested
    total_value = cash + holding_cost + realized_pnl
    total_return = (total_value - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100
    con.close()
    return {
        "total_value": total_value,
        "cash": cash,
        "holdings_value": holding_cost,
        "total_return_pct": total_return,
        "realized_pnl": realized_pnl,
    }


def get_holding_count():
    con = sqlite3.connect(SIM_DB)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM trades WHERE status='持有'")
    n = cur.fetchone()[0]
    con.close()
    return n


def run_simulation():
    candidates = get_candidates(23)
    if len(candidates) < 10:
        raise RuntimeError(f"候选不足 10 只：仅 {len(candidates)} 只")
    init_portfolio(candidates)

    # 写入初始快照
    init_stats = get_portfolio_stats()
    con = sqlite3.connect(SIM_DB)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value,
            total_return_pct, win_count, loss_count)
        VALUES (?,?,?,?,?,?,?)
    """, (date.today().isoformat(), init_stats['total_value'], init_stats['cash'],
          init_stats['holdings_value'], init_stats['total_return_pct'], 0, 0))
    con.commit()
    con.close()

    # 5 个交易日场景：每天拟止损 3 只，非止损股 flat（0%）
    days = [
        {"day": 1, "stop_count": 3, "others_pct": 0.0, "csi2000": -1.0},
        {"day": 2, "stop_count": 3, "others_pct": 0.0, "csi2000": -1.0},
        {"day": 3, "stop_count": 3, "others_pct": 0.0, "csi2000": +4.2},
        {"day": 4, "stop_count": 3, "others_pct": 0.0, "csi2000": +4.6},
        {"day": 5, "stop_count": 3, "others_pct": 0.0, "csi2000": +2.0},
    ]

    results = []
    cumulative_stop = 0
    trim_triggered_day = None
    cooling_start_day = None
    csi2000_changes = defaultdict(float)
    day_stop_details = []

    for d in days:
        con = sqlite3.connect(SIM_DB)
        cur = con.cursor()
        day_stop_count = 0
        current_details = []

        cur.execute("""
            SELECT id, code, name, buy_price, buy_shares
            FROM trades
            WHERE status='持有'
            ORDER BY code
        """)
        holdings = cur.fetchall()
        stop_list = holdings[:min(d['stop_count'], len(holdings))]
        others = holdings[d['stop_count']:]

        for pos in stop_list:
            pid, code, name, buy_price, buy_shares = pos
            current_price = buy_price * (1 - STOP_LOSS)
            exit_price = current_price * (1 - SLIPPAGE)
            exit_price = max(exit_price, current_price * 0.9)
            sell_amount = buy_shares * exit_price
            sell_costs = calc_transaction_cost(sell_amount, is_buy=False)
            net_amount = sell_amount - sell_costs
            profit = net_amount - buy_shares * buy_price
            profit_pct = profit / (buy_shares * buy_price) * 100
            cur.execute("""
                UPDATE trades
                SET sell_date=?, sell_price=?, sell_amount=?,
                    profit_pct=?, profit_amount=?, status='止损'
                WHERE id=?
            """, (date.today().isoformat(), exit_price, net_amount,
                  profit_pct, profit, pid))
            day_stop_count += 1
            current_details.append({
                "code": code,
                "name": name,
                "buy_price": buy_price,
                "stop_price": round(current_price, 2),
                "exit_price": round(exit_price, 2),
                "shares": buy_shares,
                "profit_pct": round(profit_pct, 2),
            })

        for pos in others:
            pid = pos[0]
            buy_price = pos[3]
            new_price = buy_price * (1 + d['others_pct'] / 100)
            cur.execute("UPDATE trades SET buy_price=? WHERE id=?", (new_price, pid))

        cumulative_stop += day_stop_count
        con.commit()
        con.close()

        stats = get_portfolio_stats()
        current_value = stats['total_value']
        drawdown_pct = (TOTAL_CAPITAL - current_value) / TOTAL_CAPITAL * 100

        con = sqlite3.connect(SIM_DB)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value,
                total_return_pct, win_count, loss_count)
            VALUES (?,?,?,?,?,?,?)
        """, (date.today().isoformat(), stats['total_value'], stats['cash'],
              stats['holdings_value'], stats['total_return_pct'], 0, day_stop_count))
        con.commit()
        con.close()

        csi2000_changes[date.today().isoformat()] = d['csi2000']

        trim_triggered = False
        if current_value <= TOTAL_CAPITAL * (1 - PORTFOLIO_DRAWDOWN_LIMIT):
            if trim_triggered_day is None:
                trim_triggered = True
                trim_triggered_day = d['day']
                con = sqlite3.connect(SIM_DB)
                cur = con.cursor()
                cur.execute("""
                    SELECT id, buy_shares, buy_price, buy_amount
                    FROM trades
                    WHERE status IN ('持有','部分止盈')
                    ORDER BY (buy_price - ?) / buy_price ASC
                """, (current_value / TOTAL_CAPITAL,))
                holdings = cur.fetchall()
                total_position_value = sum(h[2] * h[1] for h in holdings)
                target_value = total_position_value * 0.5
                sell_value = 0
                for h in holdings:
                    if sell_value >= target_value:
                        break
                    pid, shares, price, amount = h
                    cur.execute("""
                        UPDATE trades
                        SET sell_date=?, sell_price=?, status='减仓',
                            profit_pct=?, profit_amount=?
                        WHERE id=?
                    """, (date.today().isoformat(), price * 0.95,
                          -PORTFOLIO_DRAWDOWN_LIMIT * 100 * 0.5,
                          -amount * PORTFOLIO_DRAWDOWN_LIMIT * 0.5, pid))
                    sell_value += amount
                cur.execute("""
                    INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value,
                        total_return_pct, win_count, loss_count)
                    VALUES (?,?,?,?,?,?,?)
                """, (f"cooling_{date.today().isoformat()}", current_value,
                      TOTAL_CAPITAL - sell_value, sell_value,
                      (current_value - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100, 0, 0))
                con.commit()
                con.close()
                cooling_start_day = d['day']

        exemption = False
        if cooling_start_day is not None and not trim_triggered:
            if len(csi2000_changes) >= 2:
                dates = sorted(csi2000_changes.keys())[-2:]
                if all(csi2000_changes[x] > EXEMPTION_THRESHOLD for x in dates):
                    exemption = True
                    con = sqlite3.connect(SIM_DB)
                    cur = con.cursor()
                    cur.execute("DELETE FROM portfolio_snapshots WHERE date LIKE 'cooling_%'")
                    con.commit()
                    con.close()

        if trim_triggered:
            stats = get_portfolio_stats()

        holding_count = get_holding_count()
        day_stop_details.append(current_details)

        results.append({
            "day": d['day'],
            "stop_today": day_stop_count,
            "stop_cum": cumulative_stop,
            "holdings_value": stats['holdings_value'],
            "cash": stats['cash'],
            "total_value": stats['total_value'],
            "drawdown_pct": drawdown_pct,
            "trim_triggered": trim_triggered,
            "cooling": cooling_start_day is not None,
            "exemption": exemption,
            "holding_count": holding_count,
        })

    return results, trim_triggered_day, day_stop_details, candidates


def print_results(results, trim_day, details, candidates):
    print("=" * 120)
    print("L5-2 连续止损测试结果")
    print("=" * 120)
    print(f"候选池：23 只（double_up_scores 最新一期）")
    print(f"初始持仓：前 10 只，每只 2%，总仓位 20%，现金 80%")
    print(f"参数：单只止损 -8%，滑点 0.95，回撤 >15% 减仓至 50%，冷却期 {COOLING_DAYS} 天")
    print(f"中证2000豁免：连续 2 日反弹 >{EXEMPTION_THRESHOLD*100:.0f}% 可豁免冷却期\n")

    for i, r in enumerate(results):
        print(f"第 {r['day']} 天")
        print("-" * 80)
        if details[i]:
            print(f"  当日止损股票（{len(details[i])} 只）：")
            for s in details[i]:
                print(f"    {s['code']} {s['name']}: 止损价 {s['stop_price']:.2f}，"
                      f"成交价 {s['exit_price']:.2f}，滑点 {s['buy_price']*0.92 - s['exit_price']:.2f}，"
                      f"盈亏 {s['profit_pct']:.2f}%")
        else:
            print("  当日无止损")
        print(f"  收盘后持仓数量：{r['holding_count']} 只")
        print(f"  组合净值：{r['total_value']:,.2f}")
        print(f"  现金余额：{r['cash']:,.2f}")
        print(f"  持仓市值：{r['holdings_value']:,.2f}")
        print(f"  累计回撤（从初始净值算）：{r['drawdown_pct']:.2f}%")
        print(f"  是否触发 15% 减仓：{'是，第{}天触发'.format(r['day']) if r['trim_triggered'] else '否'}")
        print(f"  是否处于冷却期：{'是' if r['cooling'] else '否'}")
        print(f"  冷却期豁免（中证2000连续2日反弹>4%）：{'是' if r['exemption'] else '否'}")
        print()

    print("=" * 80)
    print("汇总表")
    print(f"{'天数':<4} {'当日止损':<6} {'累计止损':<6} {'持仓市值':<10} {'现金':<10} {'总资产':<12} {'回撤%':<8} {'15%减仓':<8} {'冷却期':<8} {'豁免':<6} {'剩余持仓':<8}")
    print("-" * 110)
    for r in results:
        print(f"{r['day']:<4} {r['stop_today']:<6} {r['stop_cum']:<6} "
              f"{r['holdings_value']:<10,.0f} {r['cash']:<10,.0f} {r['total_value']:<12,.0f} "
              f"{r['drawdown_pct']:<8.2f} {'是' if r['trim_triggered'] else '否':<8} "
              f"{'是' if r['cooling'] else '否':<8} {'是' if r['exemption'] else '否':<6} "
              f"{r['holding_count']:<8}")
    print()

    final = results[-1]
    print("最终状态（第 5 天收盘后）：")
    print(f"  剩余仓位：{final['holding_count']} 只")
    print(f"  现金余额：{final['cash']:,.2f}")
    print(f"  组合净值：{final['total_value']:,.2f}")
    if trim_day:
        print(f"  15% 减仓在第 {trim_day} 天触发，冷却期 {(date.today() + timedelta(days=COOLING_DAYS)).isoformat()} 结束")
        print("  冷却期内系统行为：不开新仓，现有持仓继续按正常流程监控止盈止损")
    else:
        print("  15% 减仓线未触发")


if __name__ == "__main__":
    res, trim_day, details, candidates = run_simulation()
    print_results(res, trim_day, details, candidates)
