#!/usr/bin/env python3
"""
模拟组合周报 — 每周日随候选池推送
"""
import sqlite3, json
from datetime import date, timedelta
from pathlib import Path
from simulation_db_helper import get_active_sim_db

SIM_DB = str(get_active_sim_db())
MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
TOTAL_CAPITAL = 1_000_000

conn = sqlite3.connect(SIM_DB)
cur = conn.cursor()
mconn = sqlite3.connect(MARKET_DB)
mcur = mconn.cursor()

print("=" * 55)
print("📊 模拟组合周报")
print(f"   日期: {date.today()}")
print("=" * 55)

# 本周交易
week_start = (date.today() - timedelta(days=7)).isoformat()
cur.execute("SELECT * FROM trades WHERE sell_date >= ? OR buy_date >= ? ORDER BY id", (week_start, week_start))
weekly_trades = cur.fetchall()

print(f"\n📋 本周交易汇总 ({len(weekly_trades)}笔)")
print(f"{'代码':<8} {'名称':<10} {'方向':<6} {'价格':<8} {'数量':<6} {'盈亏%':<8}")
print("-" * 50)
for t in weekly_trades:
    if t[8] and t[8] >= week_start:  # 有卖出
        side = '卖出'
        price = t[9]
        qty = t[6]
        pnl = t[11] or 0
        print(f"  {t[1]:<8} {t[2]:<10} {side:<6} {price:<8.2f} {qty:<6} {pnl:<+8.1f}")
    if t[4] and t[4] >= week_start:  # 有买入
        side = '买入'
        price = t[5]
        qty = t[6]
        print(f"  {t[1]:<8} {t[2]:<10} {side:<6} {price:<8.2f} {qty:<6}")

# 当前持仓
cur.execute("SELECT * FROM trades WHERE status IN ('持有','部分止盈')")
holdings = cur.fetchall()
print(f"\n📋 当前持仓 ({len(holdings)}笔)")
if holdings:
    print(f"{'代码':<8} {'名称':<10} {'买入日':<12} {'买入价':<8} {'数量':<6} {'状态':<8}")
    print("-" * 55)
    for h in holdings:
        print(f"  {h[1]:<8} {h[2]:<10} {h[4]:<12} {h[5]:<8.2f} {h[6]:<6} {h[13]:<8}")
else:
    print("  空仓")

# 组合统计
cur.execute("SELECT COALESCE(SUM(profit_amount),0) FROM trades WHERE status IN ('清仓止盈','止损','部分止盈')")
realized_pnl = cur.fetchone()[0]
cur.execute("SELECT COALESCE(SUM(buy_amount),0) FROM trades "
            "WHERE status IN ('持有','部分止盈','止损','清仓止盈','减仓')")
all_bought = cur.fetchone()[0]
cur.execute("SELECT COALESCE(SUM(sell_amount),0) FROM trades WHERE sell_date IS NOT NULL")
all_sold = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL AND profit_amount > 0")
wins = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL")
total_closed = cur.fetchone()[0]
cur.execute("SELECT MAX(total_return_pct) FROM portfolio_snapshots")
max_return = cur.fetchone()[0] or 0
cur.execute("SELECT MIN(total_return_pct) FROM portfolio_snapshots")
min_return = cur.fetchone()[0] or 0

# 实时市值（现价 × 股数），口径与 double_monitor 一致
cash = TOTAL_CAPITAL - all_bought + all_sold
cur.execute("SELECT code, buy_shares, buy_price FROM trades WHERE status IN ('持有','部分止盈')")
mkt_value = 0.0
for code, shares, buy_price in cur.fetchall():
    mcur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    pr = mcur.fetchone()
    if not pr or pr[0] is None:
        continue
    mkt_value += float(pr[0]) * shares
total_value = cash + mkt_value
total_return = (total_value - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100
max_dd = max_return - min_return if max_return > min_return else 0

# 盈亏比
cur.execute("SELECT COALESCE(AVG(profit_amount),0) FROM trades WHERE sell_date IS NOT NULL AND profit_amount > 0")
avg_win = cur.fetchone()[0]
cur.execute("SELECT COALESCE(AVG(ABS(profit_amount)),0) FROM trades WHERE sell_date IS NOT NULL AND profit_amount <= 0")
avg_loss = cur.fetchone()[0]

print(f"\n📊 组合统计")
print(f"{'='*55}")
print(f"  总资产: {total_value:>10,.0f} 元")
print(f"  现金:   {cash:>10,.0f} 元")
print(f"  持仓:   {mkt_value:>10,.0f} 元")
print(f"  累计收益: {total_return:>+8.2f}%")
print(f"  最大回撤: {max_dd:>8.2f}%")
print(f"  胜率:   {wins/max(1,total_closed)*100:>6.1f}% ({wins}/{total_closed})")
print(f"  盈亏比: {avg_win/max(1,avg_loss)*100:>8.2f}%")

# 快照记录
cur.execute("""INSERT INTO portfolio_snapshots 
    (date,total_value,cash,holdings_value,total_return_pct,max_drawdown_pct,win_count,loss_count)
    VALUES (?,?,?,?,?,?,?,?)""",
    (date.today().isoformat(), total_value, cash, mkt_value, total_return, max_dd, wins, total_closed - wins))
conn.commit()
mconn.close()

print(f"\n{'='*55}")
print(f"✅ 周报完成 | {date.today()}")
conn.close()

# ── 生成可视化仪表盘 ──
print()
try:
    from simulation_chart import main as chart_main
    chart_main()
except Exception as e:
    print(f"  ⚠ 图表生成失败: {e}")
    import traceback
    traceback.print_exc()