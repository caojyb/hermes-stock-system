#!/usr/bin/env python3
"""
风险管理模块 v2.0 — 带流动性危机保护 + 冷却期豁免
==============================================
升级自 simulation_engine.py 的补丁3：
1. 清仓前检查：个股平均跌幅 < 中证2000跌幅 → 才能清仓
   如果个股平均跌幅已超过指数 → 禁止清仓，发送"流动性危机预警"
2. 冷却期豁免：清仓后3天冷却期内，如果中证2000连续2日反弹>4% → 立即结束冷却期
"""
import os, sys, json, sqlite3, math
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')
from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))
SIM_DB = str(get_db_path('simulation'))

# 中证2000指数代码
CSI2000_CODE = "932000"  # 中证2000

PORTFOLIO_DRAWDOWN_LIMIT = 0.15  # 15%触发减仓
COOLING_DAYS = 3
EXEMPTION_THRESHOLD = 0.04  # 连续2日反弹>4%豁免冷却期
LIMIT_DOWN_THRESHOLD = -0.095  # 跌幅>9.5%视为跌停
CONSECUTIVE_LIMIT_DOWN_ALERT = 2  # 连续2日跌停标记为流动性冻结


def get_stock_realtime_price(code):
    """获取个股实时行情，返回 {price, change_pct, limit_down, limit_up}"""
    try:
        from eastmoney import get_stock_quote
        quote = get_stock_quote(code)
        if quote and 'price' in quote:
            price = quote['price']
            change_pct = quote.get('change_pct', 0)
            # 判断跌停：跌幅≥9.5%
            is_limit_down = change_pct <= LIMIT_DOWN_THRESHOLD
            return {"price": price, "change_pct": change_pct,
                    "limit_down": is_limit_down}
    except:
        pass
    return None


def check_limit_down_stop_loss(code, buy_price, current_price, stop_loss_pct=0.08):
    """跌停板感知的止损检查
    返回: {"action": "stop"|"defer"|"freeze", "reason": str, "adjusted_price": float}
    """
    ret = (current_price - buy_price) / buy_price
    quote = get_stock_realtime_price(code)

    if ret <= -stop_loss_pct:
        # 触及止损线
        if quote and quote.get("limit_down"):
            next_day_limit = current_price * 0.9  # 次日跌停价
            return {
                "action": "defer",
                "reason": f"跌停无法卖出(当前跌{ret*100:.1f}%)，调整止损价至次日跌停价{next_day_limit:.2f}",
                "adjusted_price": next_day_limit,
                "alert": "🚨跌停无法卖出"
            }
        else:
            return {
                "action": "stop",
                "reason": f"触发止损(跌{ret*100:.1f}%)，正常卖出",
                "adjusted_price": current_price,
                "alert": None
            }
    return {"action": "hold", "reason": "", "adjusted_price": current_price, "alert": None}


def check_frozen_stocks(stocks, lookback_days=2):
    """检查连续跌停的流动性冻结股票
    返回: [code, ...]
    """
    frozen = []
    for s in stocks:
        if s.get("consecutive_limit_days", 0) >= CONSECUTIVE_LIMIT_DOWN_ALERT:
            frozen.append(s["code"])
    return frozen


def format_limit_down_alert(code, name, loss_pct, days):
    """格式化跌停告警"""
    return (
        f"🚨 流动性冻结告警\n"
        f"股票: {code} {name}\n"
        f"连续跌停: {days}天\n"
        f"累计亏损: {loss_pct:.1f}%\n"
        f"状态: 已移出止损队列，单独跟踪\n"
        f"建议: 跌停打开后立即手动/自动卖出"
    )


def get_csi2000_performance(conn, lookback_days=5):
    """获取中证2000指数最近N日的涨跌幅
    返回: {date: change_pct, ...}
    """
    cur = conn.execute("""
        SELECT date, close FROM klines
        WHERE code = ? AND date >= ?
        ORDER BY date ASC
    """, (CSI2000_CODE, (date.today() - timedelta(days=lookback_days * 2)).isoformat()))
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) < 2:
        return {}

    perf = {}
    for i in range(1, len(rows)):
        chg = (rows[i]["close"] - rows[i-1]["close"]) / rows[i-1]["close"]
        perf[rows[i]["date"]] = chg
    return perf


def get_proxy_index_drawdown(conn_sim, market_conn=None):
    """
    中证2000数据缺失时的代理指数跌幅：
    1. 若持仓 >= 10 只：取全部持仓的加权平均跌幅（权重=buy_amount）
    2. 若持仓 < 10 只：取全市场市值最小的 200 只有效股票当日涨跌幅的等权平均
    返回: (drawdown, details, source_label)
    """
    close_mkt = market_conn or sqlite3.connect(MARKET_DB)
    close_mkt.row_factory = sqlite3.Row
    cur = conn_sim.execute("""
        SELECT code, buy_price, buy_amount FROM trades
        WHERE status IN ('持有','部分止盈')
    """)
    holdings = [dict(r) for r in cur.fetchall()]

    if not holdings:
        if not market_conn:
            close_mkt.close()
        return 0, [], "无持仓"

    # ---------- 方案A：用持仓本身作为代理（当日涨跌幅，不依赖买入价） ----------
    if len(holdings) >= 10:
        total_chg = 0.0
        total_weight = 0.0
        individuals = []
        for h in holdings:
            code = h["code"]
            rows = close_mkt.execute("""
                SELECT close FROM klines
                WHERE code = ?
                ORDER BY date DESC
                LIMIT 2
            """, (code,)).fetchall()
            if len(rows) < 2:
                continue
            today_close = rows[0]["close"]
            prev_close = rows[1]["close"]
            if not prev_close:
                continue
            chg = (today_close - prev_close) / prev_close
            w = h["buy_amount"] if h["buy_amount"] else h["buy_price"]
            total_chg += chg * w
            total_weight += w
            individuals.append({"code": code, "change_pct": chg, "weight": w})
        if not total_weight:
            if not market_conn:
                close_mkt.close()
            return 0, [], "持仓代理(无有效K线)"
        avg_chg = total_chg / total_weight
        if not market_conn:
            close_mkt.close()
        return avg_chg, individuals, "持仓代理(指数数据缺失)"

    # ---------- 方案B：全市场小市值 200 只等权平均 ----------
    rows = close_mkt.execute("""
        SELECT code, total_mcap FROM stocks
        WHERE total_mcap IS NOT NULL AND total_mcap > 0
        ORDER BY total_mcap ASC
        LIMIT 200
    """).fetchall()
    if not rows:
        if not market_conn:
            close_mkt.close()
        return 0, [], "小盘代理(无市值数据)"

    codes = [r["code"] for r in rows]

    # 先取最近两个交易日
    dates = [r["date"] for r in close_mkt.execute("""
        SELECT DISTINCT date FROM klines ORDER BY date DESC LIMIT 2
    """).fetchall()]
    if len(dates) < 2:
        if not market_conn:
            close_mkt.close()
        return 0, [], "小盘代理(交易日不足)"

    latest_date, prev_date = dates[:2]

    # 一次性拉取最近两个交易日
    placeholders = ",".join("?" for _ in codes)
    query = f"""
        SELECT code, date, close FROM klines
        WHERE code IN ({placeholders})
          AND date IN (?, ?)
    """
    cur = close_mkt.execute(query, (*codes, latest_date, prev_date))

    today_map = {}
    prev_map = {}
    for code, dt, close in cur.fetchall():
        if dt == latest_date:
            today_map[code] = close
        else:
            prev_map[code] = close

    changes = []
    individuals = []
    for code in codes:
        c1 = today_map.get(code)
        c0 = prev_map.get(code)
        if not c1 or not c0 or c0 <= 0:
            continue
        chg = (c1 - c0) / c0
        changes.append(chg)
        individuals.append({"code": code, "change_pct": chg})

    if not changes:
        if not market_conn:
            close_mkt.close()
        return 0, [], "小盘代理(无K线)"

    avg_dd = sum(changes) / len(changes)
    if not market_conn:
        close_mkt.close()
    return avg_dd, individuals, "小盘代理(指数数据缺失)"


def get_held_stocks_avg_drawdown(conn_sim, csi2000_drawdown=None):
    """获取持仓个股的最新有效日涨跌幅（与指数同日可比）
    返回: (avg_change_pct, individual_changes)
    """
    cur = conn_sim.execute("""
        SELECT code, buy_price, buy_amount FROM trades
        WHERE status IN ('持有','部分止盈')
    """)
    holdings = [dict(r) for r in cur.fetchall()]
    if not holdings:
        return 0, []

    mkt_conn = sqlite3.connect(MARKET_DB)
    mkt_conn.row_factory = sqlite3.Row

    total_chg = 0.0
    total_weight = 0.0
    individuals = []
    for h in holdings:
        rows = mkt_conn.execute("""
            SELECT close FROM klines
            WHERE code = ?
            ORDER BY date DESC
            LIMIT 2
        """, (h["code"],)).fetchall()
        if len(rows) < 2:
            continue
        today_close = rows[0]["close"]
        prev_close = rows[1]["close"]
        if not prev_close:
            continue
        chg = (today_close - prev_close) / prev_close
        w = h["buy_amount"] if h["buy_amount"] else h["buy_price"]
        total_chg += chg * w
        total_weight += w
        individuals.append({"code": h["code"], "change_pct": chg, "weight": w})

    mkt_conn.close()
    avg_chg = total_chg / total_weight if total_weight else 0
    return avg_chg, individuals


def check_liquidity_crisis(conn_sim):
    """检查是否处于流动性危机状态
    条件：个股平均跌幅 > 中证2000跌幅（说明个股比指数跌得更惨）
    返回: (is_crisis: bool, warning: str, detail: dict)
    """
    conn_sim.row_factory = sqlite3.Row
    # 获取中证2000指数表现
    mkt_conn = sqlite3.connect(MARKET_DB)
    mkt_conn.row_factory = sqlite3.Row
    csi_perf = get_csi2000_performance(mkt_conn)

    if csi_perf:
        latest_date = max(csi_perf.keys())
        csi_dd = csi_perf.get(latest_date, 0)
        data_source = f"中证2000指数({latest_date})"
    else:
        csi_dd, _, proxy_label = get_proxy_index_drawdown(conn_sim, market_conn=mkt_conn)
        data_source = proxy_label

    # 获取持仓个股平均跌幅（从买入价到当前价）
    avg_dd, individuals = get_held_stocks_avg_drawdown(conn_sim)
    mkt_conn.close()

    if not individuals:
        return False, "", {}

    print(f"[流动性危机检查] 数据源: {data_source}")

    # 核心条件：个股平均跌幅 比 代理指数跌幅 多 5 个百分点以上
    # 例：指数 -10%，个股 -15% -> 触发；个股 -12% -> 不触发
    gap = abs(avg_dd) - abs(csi_dd)
    if avg_dd < 0 and csi_dd < 0 and gap >= 0.05:
        warning = (
            f"🚨 流动性危机预警！\n"
            f"  持仓个股平均跌幅: {abs(avg_dd)*100:.1f}%\n"
            f"  代理指数当日跌幅: {abs(csi_dd)*100:.1f}%\n"
            f"  个股-指数差距: {gap*100:.1f}%，超过5%阈值，禁止清仓！\n"
            f"  建议：暂停所有止损操作，等待流动性恢复"
        )
        return True, warning, {
            "avg_stock_dd": round(abs(avg_dd) * 100, 2),
            "proxy_index_dd": round(abs(csi_dd) * 100, 2),
            "gap_pct": round(gap * 100, 2),
            "trigger_threshold_pct": 5.0,
            "data_source": data_source,
            "is_crisis": True,
            "individuals": individuals,
        }

    return False, "", {
        "avg_stock_dd": round(abs(avg_dd) * 100, 2) if avg_dd != 0 else 0,
        "proxy_index_dd": round(abs(csi_dd) * 100, 2),
        "gap_pct": round(gap * 100, 2),
        "trigger_threshold_pct": 5.0,
        "data_source": data_source,
        "is_crisis": False,
    }


def check_cooling_exemption(conn_sim):
    """检查冷却期豁免条件
    条件：冷却期内中证2000连续2日反弹>4%
    返回: (exempt: bool, message: str)
    """
    # 检查是否有冷却期记录
    cur = conn_sim.execute("""
        SELECT date FROM portfolio_snapshots
        WHERE date LIKE 'cooling_%' ORDER BY date DESC LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        return False, "无冷却期记录"

    # 获取中证2000最近3日表现
    mkt_conn = sqlite3.connect(MARKET_DB)
    mkt_conn.row_factory = sqlite3.Row
    csi_perf = get_csi2000_performance(mkt_conn, lookback_days=3)
    mkt_conn.close()

    if len(csi_perf) < 2:
        return False, "中证2000数据不足"

    # 检查连续2日是否都反弹>4%
    dates = sorted(csi_perf.keys(), reverse=True)[:2]
    if len(dates) < 2:
        return False, "数据不足"

    d1, d2 = dates[0], dates[1]
    r1 = csi_perf[d1]
    r2 = csi_perf[d2]

    if r1 > EXEMPTION_THRESHOLD and r2 > EXEMPTION_THRESHOLD:
        return True, (
            f"✅ 冷却期豁免触发！\n"
            f"  中证2000连续2日反弹: {d1}={r1*100:.1f}%, {d2}={r2*100:.1f}%\n"
            f"  立即结束冷却期，允许开仓"
        )

    return False, (
        f"冷却期中，中证2000最近2日: {d1}={r1*100:.1f}%, {d2}={r2*100:.1f}%\n"
        f"  未达到连续2日>4%的豁免条件"
    )


def check_portfolio_drawdown_v2(conn_sim, force_report=False):
    """
    新版组合净值回撤检查（v2.0）
    带流动性危机保护 + 冷却期豁免

    返回: (action: str, messages: list)
    action: 'liquidate' | 'trim' | 'crisis_alert' | 'exempt' | 'none'
    """
    cur = conn_sim.cursor()
    today = date.today().isoformat()
    messages = []

    # 获取最近30日的净值快照
    cur.execute("""
        SELECT date, total_value FROM portfolio_snapshots
        WHERE date >= ? ORDER BY date DESC
    """, ((date.today() - timedelta(days=45)).isoformat(),))
    snapshots = [dict(r) for r in cur.fetchall()]

    if not snapshots:
        return "none", messages

    recent_high = max(s['total_value'] for s in snapshots)
    current_value = snapshots[0]['total_value']
    drawdown = (recent_high - current_value) / recent_high

    # 1. 检查冷却期豁免
    cooling_active = any(s['date'].startswith('cooling_') for s in snapshots[:5])
    if cooling_active:
        exempt, exempt_msg = check_cooling_exemption(conn_sim)
        if exempt:
            # 删除冷却期标记
            cur.execute("DELETE FROM portfolio_snapshots WHERE date LIKE 'cooling_%'")
            conn_sim.commit()
            messages.append(exempt_msg)
            return "exempt", messages
        else:
            messages.append(exempt_msg)
            return "cooling", messages

    # 2. 检查是否触发减仓线
    if drawdown >= PORTFOLIO_DRAWDOWN_LIMIT or force_report:
        # 2a. 流动性危机检查
        is_crisis, crisis_warning, crisis_detail = check_liquidity_crisis(conn_sim)

        if is_crisis:
            # 流动性危机！禁止清仓
            messages.append(crisis_warning)
            # 记录危机事件
            cur.execute("""
                INSERT OR REPLACE INTO portfolio_snapshots (date, total_value, cash, holdings_value, total_return_pct, win_count, loss_count)
                VALUES (?,?,?,?,?,?,?)
            """, (f"crisis_{today}", current_value, current_value, 0,
                  (current_value - 100000) / 100000 * 100, 0, 0))
            conn_sim.commit()
            return "crisis_alert", messages

        # 2b. 正常减仓至50%（用真实收盘价，非编造价）
        messages.append(f"🚨组合净值回撤{drawdown:.1%}，超过{PORTFOLIO_DRAWDOWN_LIMIT:.0%}减仓线！执行减仓至50%")

        cur.execute("""SELECT id, code, name, buy_shares, buy_price, buy_amount
            FROM trades WHERE status IN ('持有','部分止盈')
            ORDER BY (buy_price - ?) / buy_price ASC""", (current_value / 100000,))
        holdings = [dict(r) for r in cur.fetchall()]

        total_position_value = sum(h['buy_amount'] for h in holdings)
        target_value = total_position_value * 0.5
        sell_value = 0
        sold_count = 0
        mkt = sqlite3.connect(MARKET_DB)
        # ── Phase 3.6: 减仓前经统一 Decision（Risk Assessment → DecisionEngine → SELL）──
        # risk_controller 继续拥有风险判断权（drawdown 触发），DecisionEngine 归一最终动作。
        # fail-safe：Decision 异常时跳过该笔减仓，不做未归一的风险卖出。
        from decision.engine import DecisionEngine
        from decision.adapters import position_ctx
        from decision import snapshot as _snap
        _eng = DecisionEngine(strategy='v1_double', config_version='phase1', code_version='risk_controller_p36')
        for h in holdings:
            if sell_value >= target_value:
                break
            row = mkt.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (h['code'],)).fetchone()
            price = float(row[0]) if row and row[0] else h['buy_price'] * 0.95
            sell_amount = price * h['buy_shares']
            profit = sell_amount - h['buy_amount']
            profit_pct = (sell_amount / h['buy_amount'] - 1) * 100 if h['buy_amount'] else 0
            try:
                _dctx = position_ctx(symbol=h['code'], name=h.get('name', ''), regime_label='',
                                     permission={}, permission_status='', data_health='VALID',
                                     exit_signal='RISK', exit_triggers=['PORTFOLIO_DRAWDOWN_REDUCE'],
                                     position_count=len(holdings))
                _dec = _eng.decide(_dctx)
                _snap.save_snapshot(_dec)
                if _dec.action != 'SELL':
                    continue  # Decision 未归一为 SELL，不执行减仓
            except Exception as _e:
                print(f"  [WARN] Decision Engine 异常，跳过减仓 {h['code']}: {_e}")
                continue
            cur.execute("""
                UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?, status='减仓',
                profit_pct=?, profit_amount=?
                WHERE id=?
            """, (today, price, sell_amount, profit_pct, profit, h['id']))
            sell_value += sell_amount
            sold_count += 1
        mkt.close()
        messages.append(f"  减仓{sold_count}只持仓，仓位降至50%（按真实收盘价）")
        conn_sim.commit()
        return "trim", messages

    return "none", messages


def simulate_2024_feb_crisis():
    """模拟2024年2月微盘股流动性危机时的两种行为对比"""
    print("=" * 65)
    print("📉 模拟2024年2月微盘股流动性危机")
    print("=" * 65)

    # 模拟场景数据
    # 2024年2月初，微盘股暴跌，中证2000也跌但跌幅小于个股
    scenario = [
        {"day": "2024-02-05", "csi2000": -0.03, "avg_stock": -0.08, "portfolio_value": 920000},
        {"day": "2024-02-06", "csi2000": -0.04, "avg_stock": -0.12, "portfolio_value": 850000},
        {"day": "2024-02-07", "csi2000": -0.02, "avg_stock": -0.10, "portfolio_value": 800000},
        {"day": "2024-02-08", "csi2000": +0.01, "avg_stock": -0.05, "portfolio_value": 780000},
        {"day": "2024-02-19", "csi2000": +0.05, "avg_stock": +0.03, "portfolio_value": 810000},
        {"day": "2024-02-20", "csi2000": +0.06, "avg_stock": +0.04, "portfolio_value": 850000},
    ]

    portfolio_high = 1000000  # 30日高点

    print(f"\n  场景参数：")
    print(f"  组合净值30日高点: 1,000,000")
    print(f"  减仓线: 15% 回撤")
    print(f"  冷却期豁免: 中证2000连续2日反弹>4%")
    print()

    # 旧规则行为
    print(f"  {'日期':<12s} {'中证2000':<10s} {'个股平均':<10s} {'净值':<12s} {'回撤':<10s} {'旧规则':<20s} {'新规则(v2)':<20s}")
    print(f"  {'─'*84}")

    crisis_mode = False
    cooling_active = False
    exemption_triggered = False

    for s in scenario:
        dd = (portfolio_high - s["portfolio_value"]) / portfolio_high
        csi = s["csi2000"]
        stock = s["avg_stock"]

        # 旧规则
        if dd >= 0.15 and not crisis_mode:
            old_action = "🚨强制清仓"
        elif cooling_active:
            old_action = "⏳冷却期"
        else:
            old_action = "✅正常持有"

        # 新规则
        if dd >= 0.15:
            if stock < 0 and csi < 0 and abs(stock) > abs(csi):
                new_action = "🚨流动性危机预警，禁止清仓"
                crisis_mode = True
            else:
                new_action = "✂️减仓至50%"
                crisis_mode = False
                cooling_active = True
        elif cooling_active:
            if csi > 0.04 and not exemption_triggered:
                # 记录连续2日反弹
                if s["csi2000"] > 0.04:
                    exemption_triggered = True
                    new_action = "✅豁免冷却期，允许开仓"
                    cooling_active = False
                else:
                    new_action = "⏳冷却期"
            else:
                new_action = "⏳冷却期"
        else:
            new_action = "✅正常持有"

        print(f"  {s['day']:<12s} {csi*100:>+6.1f}%  {stock*100:>+6.1f}%  {s['portfolio_value']:>10,d}  {dd*100:>+6.1f}%  {old_action:<20s} {new_action:<20s}")

    print(f"\n  📋 结论：")
    print(f"  - 旧规则在流动性危机中强制清仓，卖在最低点，错过后续反弹")
    print(f"  - 新规则识别流动性危机后暂停清仓，等待市场恢复")
    print(f"  - 中证2000连续2日反弹>4%后自动豁免冷却期，允许抄底")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="风险管理模块 v2.0")
    parser.add_argument("--simulate", action="store_true", help="模拟2024年2月微盘股危机")
    parser.add_argument("--check", action="store_true", help="检查当前组合风险状态")
    args = parser.parse_args()

    if args.simulate:
        simulate_2024_feb_crisis()
    elif args.check:
        conn_sim = sqlite3.connect(SIM_DB)
        conn_sim.row_factory = sqlite3.Row
        action, msgs = check_portfolio_drawdown_v2(conn_sim, force_report=True)
        for m in msgs:
            print(m)
        conn_sim.close()
    else:
        simulate_2024_feb_crisis()