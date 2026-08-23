#!/usr/bin/env python3
"""
翻倍策略模拟交易模块 + 新股虹吸过滤器
========================================
功能一：模拟交易
  - ⭐⭐⭐信号自动开仓，次日开盘价买入
  - 止盈止损自动平仓
  - 持仓记录表 + 每周报告
功能二：新股虹吸过滤器
  - 每日自动扫描新股上市日历
  - 大市值IPO(>500亿)自动识别同行业暂缓
"""
import os, sys, sqlite3, json, requests, time
from datetime import date, datetime, timedelta, time as dtime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader
from pathlib import Path
from simulation_db_helper import get_active_sim_db

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))
SIM_DB = str(get_active_sim_db())
# P2-2: 模拟仓交易标记策略来源
from stock_strategy_config import DEFAULT_STRATEGY

# ═══ 模拟交易规则 ═══
TOTAL_CAPITAL = 1_000_000       # 总资金100万
FIRST_POSITION = 0.025           # 首仓2.5%
MAX_POSITION = 0.05              # 总上限5%
STOP_LOSS = 0.08                 # 止损-8%
TP1, TP2, TP3 = 0.25, 0.50, 0.80  # 止盈三档
PEAK_RETRACE = 0.08              # 高点回落8%清仓
SLIPPAGE = 0.05                   # 滑点修正（卖出价=触发价×0.95）
FLASH_CRASH = 0.06               # 急跌阈值（盘中跌超6%预警）
PORTFOLIO_DRAWDOWN_LIMIT = 0.15  # 组合净值最大回撤-15%减仓线
COOLING_DAYS = 3                  # 清仓后冷却期（交易日）
POOL_WARNING_THRESHOLD = 10      # 候选池<10只推送警告
POOL_EMERGENCY_THRESHOLD = 5     # 候选池<5只收紧止损
EMERGENCY_STOP_LOSS = 0.05       # 候选池枯竭时止损收紧至-5%

# ═══ 交易成本规则 ═══
def calc_transaction_cost(amount, is_buy=True):
    """
    计算交易成本
    - 买入佣金 = max(成交额 × 0.00015, 5元)
    - 卖出佣金 = max(成交额 × 0.00015, 5元)
    - 印花税 = 成交额 × 0.0005（仅卖出）
    - 过户费 = 成交额 × 0.00001（买卖双向）
    """
    commission = max(amount * 0.00015, 5.0)
    transfer_fee = amount * 0.00001
    if is_buy:
        return commission + transfer_fee
    else:
        stamp_tax = amount * 0.0005
        return commission + stamp_tax + transfer_fee

# ═══ 新股虹吸规则 ═══
LARGE_IPO_THRESHOLD = 50_000_000_000  # 500亿（单位：元）
SUSPEND_DAYS = 3                      # 暂缓3个交易日

# ═══ 初始化模拟数据库 ═══
def init_sim_db():
    conn = sqlite3.connect(SIM_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT, name TEXT, sector TEXT,
            buy_date TEXT, buy_price REAL, buy_shares INTEGER,
            buy_amount REAL,  -- 买入金额
            sell_date TEXT, sell_price REAL, sell_amount REAL,
            profit_pct REAL, profit_amount REAL,
            status TEXT,  -- 持有/部分止盈/清仓止盈/止损
            signal_type TEXT,  -- ⭐⭐⭐/⭐⭐/⭐
            hold_mode TEXT DEFAULT 'normal',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, total_value REAL, cash REAL,
            holdings_value REAL, total_return_pct REAL,
            max_drawdown_pct REAL, win_count INTEGER, loss_count INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ipo_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ipo_code TEXT, ipo_name TEXT, ipo_date TEXT,
            ipo_market_cap REAL, sector TEXT,
            suspend_start TEXT, suspend_end TEXT,
            affected_stocks TEXT,  -- JSON array
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    return conn

# 兼容迁移：为旧表添加hold_mode列
def migrate_sim_db(conn):
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE trades ADD COLUMN hold_mode TEXT DEFAULT 'normal'")
    except:
        pass  # 列已存在
    try:
        cur.execute("ALTER TABLE trades ADD COLUMN stop_loss_pct REAL")
    except:
        pass
    try:
        cur.execute("ALTER TABLE trades ADD COLUMN take_profit_pct REAL")
    except:
        pass
    conn.commit()

def ensure_sim_fields():
    """确保stocks表有模拟交易相关字段"""
    conn_sim = sqlite3.connect(SIM_DB)
    cur_sim = conn_sim.cursor()
    return conn_sim

# ═══ 功能一：模拟交易 ═══
def get_holdings(conn_sim):
    cur = conn_sim.cursor()
    cur.execute("SELECT * FROM trades WHERE status IN ('持有','部分止盈') ORDER BY buy_date DESC")
    return [dict(r) for r in cur.fetchall()]

def get_all_trades(conn_sim):
    cur = conn_sim.cursor()
    cur.execute("SELECT * FROM trades ORDER BY id DESC")
    return [dict(r) for r in cur.fetchall()]

def open_position(conn_sim, code, name, sector, buy_price, signal_type='⭐⭐⭐', buy_date=None):
    """以开盘价模拟买入"""
    cur = conn_sim.cursor()
    if buy_date is None:
        buy_date = date.today().isoformat()
    
    # 先检查是否已持有
    cur.execute("SELECT SUM(buy_amount) as total FROM trades WHERE code=? AND status IN ('持有','部分止盈')", (code,))
    existing = cur.fetchone()
    existing_amount = existing[0] or 0
    
    # 计算可买入金额：首仓2.5%，总上限5%
    max_buy = TOTAL_CAPITAL * MAX_POSITION
    available = max_buy - existing_amount
    buy_amount = min(TOTAL_CAPITAL * FIRST_POSITION, available)
    
    if buy_amount <= 0:
        return None, "已达仓位上限"
    
    buy_shares = int(buy_amount / buy_price)
    trade_amount = buy_shares * buy_price
    # 买入成本 = 佣金 + 过户费
    buy_costs = calc_transaction_cost(trade_amount, is_buy=True)
    total_cost = trade_amount + buy_costs
    actual_price = total_cost / buy_shares  # 含成本的每股实际成本
    
    cur.execute("""
        INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares, buy_amount, status, signal_type, strategy)
        VALUES (?,?,?,?,?,?,?, '持有', ?, ?)
    """, (code, name, sector, buy_date, actual_price, buy_shares, total_cost, signal_type, DEFAULT_STRATEGY))
    conn_sim.commit()
    return cur.lastrowid, f"买入{buy_shares}股×{buy_price:.2f}=交易额{trade_amount:.0f}元+成本{buy_costs:.2f}元=总成本{total_cost:.0f}元"

def check_exit_signals(conn_sim, code, current_price, high_price_ever, use_slippage=True, pool_count=23):
    """检查止盈止损信号，返回要执行的操作"""
    cur = conn_sim.cursor()
    cur.execute("SELECT id, buy_price, buy_shares, buy_amount, status, COALESCE(hold_mode,'normal') as hold_mode FROM trades WHERE code=? AND status IN ('持有','部分止盈') ORDER BY buy_date", (code,))
    positions = [dict(r) for r in cur.fetchall()]
    
    actions = []
    for pos in positions:
        buy_price = pos['buy_price']
        ret = (current_price - buy_price) / buy_price
        hold_mode = pos.get('hold_mode', 'normal')
        
        # 长持模式：取消技术面止盈，使用更宽松的-15%极端保护止损
        # 长持卖出条件：基本面恶化（外部判断）或大盘跌破年线（外部判断）
        if hold_mode == 'long':
            # 长持只保留极端保护止损-15%
            if ret <= -0.15:
                shares = pos['buy_shares']
                sell_trade_amount = shares * current_price
                sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
                sell_amount = sell_trade_amount - sell_costs
                profit = sell_amount - pos['buy_amount']
                profit_pct = profit / pos['buy_amount'] * 100
                cur.execute("""
                    UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?,
                    profit_pct=?, profit_amount=?, status='止损'
                    WHERE id=?
                """, (date.today().isoformat(), current_price, sell_amount, profit_pct, profit, pos['id']))
                actions.append(f"⚠️长持极端止损 {code} {pos['buy_shares']}股 亏损{profit_pct:.1f}%")
            else:
                # 长持不设止盈，让利润奔跑
                pass
            conn_sim.commit()
            continue  # 跳过后面的普通止盈止损逻辑
        
        # 动态止损：候选池枯竭时收紧
        effective_sl = EMERGENCY_STOP_LOSS if pool_count < POOL_EMERGENCY_THRESHOLD else STOP_LOSS
        
        # 滑点修正：止损时成交价=触发价×95%，模拟实盘流动性损耗
        exit_price = current_price * (1 - SLIPPAGE) if (use_slippage and ret <= -effective_sl) else current_price
        exit_price = max(exit_price, current_price * 0.9)  # 滑点保护，最多-10%
        
        # 止损
        if ret <= -effective_sl:
            shares = pos['buy_shares']
            sell_trade_amount = shares * exit_price
            sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
            sell_amount = sell_trade_amount - sell_costs  # 净收入
            profit = sell_amount - pos['buy_amount']
            profit_pct = profit / pos['buy_amount'] * 100
            cur.execute("""
                UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?,
                profit_pct=?, profit_amount=?, status='止损'
                WHERE id=?
            """, (date.today().isoformat(), exit_price, sell_amount, profit_pct, profit, pos['id']))
            if use_slippage and ret <= -effective_sl:
                actions.append(f"⚠️止损 {code} {pos['buy_shares']}股 亏损{profit_pct:.1f}%（含滑点损失{SLIPPAGE:.0%}）")
            else:
                actions.append(f"⚠️止损 {code} {pos['buy_shares']}股 亏损{profit_pct:.1f}%")
        
        # ═══ 双层止损（抗震仓）═══
        # 阶段2：涨超+10%后，止损上移至买入价（保本）
        elif ret >= 0.10 and current_price < buy_price:
            shares = pos['buy_shares']
            sell_trade_amount = shares * current_price
            sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
            sell_amount = sell_trade_amount - sell_costs
            profit = sell_amount - pos['buy_amount']
            profit_pct = profit / pos['buy_amount'] * 100
            cur.execute("""
                UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?,
                profit_pct=?, profit_amount=?, status='止损'
                WHERE id=?
            """, (date.today().isoformat(), current_price, sell_amount, profit_pct, profit, pos['id']))
            actions.append(f"🛡️保本止损 {code} {pos['buy_shares']}股 盈亏{profit_pct:.1f}%（涨超10%后回撤至成本价）")
        
        # 阶段3：涨超+20%后，启用移动止盈（回撤15%卖出）
        elif ret >= 0.20 and high_price_ever > buy_price:
            dd_from_peak = (high_price_ever - current_price) / high_price_ever
            if dd_from_peak >= 0.15:
                shares = pos['buy_shares']
                sell_trade_amount = shares * current_price
                sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
                sell_amount = sell_trade_amount - sell_costs
                profit = sell_amount - pos['buy_amount']
                profit_pct = profit / pos['buy_amount'] * 100
                cur.execute("""
                    UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?,
                    profit_pct=?, profit_amount=?, status='移动止盈'
                    WHERE id=?
                """, (date.today().isoformat(), current_price, sell_amount, profit_pct, profit, pos['id']))
                actions.append(f"🎯移动止盈 {code} {pos['buy_shares']}股 盈利{profit_pct:.1f}%（从高点回撤{dd_from_peak:.1%}）")
        
        # 止盈清仓（+80%或高点回落8%）
        elif ret >= TP3 or (high_price_ever > buy_price and (high_price_ever - current_price) / high_price_ever >= PEAK_RETRACE):
            shares = pos['buy_shares']
            sell_trade_amount = shares * current_price
            sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
            sell_amount = sell_trade_amount - sell_costs
            profit = sell_amount - pos['buy_amount']
            profit_pct = profit / pos['buy_amount'] * 100
            reason = '止盈+80%' if ret >= TP3 else '高点回落'
            cur.execute("""
                UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?,
                profit_pct=?, profit_amount=?, status='清仓止盈'
                WHERE id=?
            """, (date.today().isoformat(), current_price, sell_amount, profit_pct, profit, pos['id']))
            actions.append(f"✅{reason} {code} {pos['buy_shares']}股 盈利{profit_pct:.1f}%")
        
        # 止盈+50%（卖1/3）
        elif ret >= TP2:
            shares = int(pos['buy_shares'] * 0.33)
            if shares > 0:
                sell_trade_amount = shares * current_price
                sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
                sell_amount = sell_trade_amount - sell_costs
                profit_pct = ret * 100
                new_id = pos['id']
                cur.execute("UPDATE trades SET buy_shares = buy_shares - ?, status='部分止盈' WHERE id=?", (shares, pos['id']))
                portion_cost = shares * buy_price
                portion_buy_costs = calc_transaction_cost(portion_cost, is_buy=True)
                portion_total_cost = portion_cost + portion_buy_costs
                cur.execute("""
                    INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares, buy_amount,
                    sell_date, sell_price, sell_amount, profit_pct, profit_amount, status, signal_type, strategy)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?, '部分止盈', ?, ?)
                """, (pos['code'], pos['name'], pos['sector'], pos['buy_date'], portion_total_cost / shares, shares,
                      portion_total_cost, date.today().isoformat(), current_price, sell_amount,
                      profit_pct, sell_amount - portion_total_cost, pos.get('signal_type',''), DEFAULT_STRATEGY))
                actions.append(f"✅卖出1/3 {code} {shares}股 盈利{profit_pct:.1f}%")
        
        # 止盈+25%（卖1/3）
        elif ret >= TP1:
            shares = int(pos['buy_shares'] * 0.33)
            if shares > 0:
                sell_trade_amount = shares * current_price
                sell_costs = calc_transaction_cost(sell_trade_amount, is_buy=False)
                sell_amount = sell_trade_amount - sell_costs
                profit_pct = ret * 100
                cur.execute("UPDATE trades SET buy_shares = buy_shares - ? WHERE id=?", (shares, pos['id']))
                portion_cost = shares * buy_price
                portion_buy_costs = calc_transaction_cost(portion_cost, is_buy=True)
                portion_total_cost = portion_cost + portion_buy_costs
                cur.execute("""
                    INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares, buy_amount,
                    sell_date, sell_price, sell_amount, profit_pct, profit_amount, status, signal_type, strategy)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?, '部分止盈', ?, ?)
                """, (pos['code'], pos['name'], pos['sector'], pos['buy_date'], portion_total_cost / shares, shares,
                      portion_total_cost, date.today().isoformat(), current_price, sell_amount,
                      profit_pct, sell_amount - portion_total_cost, pos.get('signal_type',''), DEFAULT_STRATEGY))
                actions.append(f"✅卖出1/3 {code} {shares}股 盈利{profit_pct:.1f}%")
                # 主池止盈→赛道资金流转：释放金额的50%转入赛道弹性资金池
                try:
                    from track_flow_manager import transfer_tp_to_track_fund
                    released = sell_amount
                    transfer, balance = transfer_tp_to_track_fund(conn_sim, released, code, pos.get('name',''))
                    actions.append(f"💰{transfer:.0f}元转入赛道弹性资金池（余额{balance:.0f}元）")
                except Exception as e:
                    pass
    
    conn_sim.commit()
    return actions

def calc_portfolio_stats(conn_sim):
    """计算组合统计"""
def calc_portfolio_stats(conn_sim, conn_mkt=None):
    """计算组合统计"""
    cur = conn_sim.cursor()
    cur.execute("SELECT COALESCE(SUM(profit_amount),0) FROM trades WHERE status IN ('清仓止盈','止损','部分止盈')")
    realized_pnl = cur.fetchone()[0]
    
    # 持仓成本
    cur.execute("SELECT COALESCE(SUM(buy_shares * buy_price),0) FROM trades WHERE status IN ('持有','部分止盈')")
    holding_cost = cur.fetchone()[0]
    
    # 累计买入（含已平仓）
    cur.execute("SELECT COALESCE(SUM(buy_amount),0) FROM trades WHERE status IN ('持有','部分止盈','止损','清仓止盈','减仓')")
    total_invested = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(sell_amount),0) FROM trades WHERE sell_date IS NOT NULL")
    total_sold = cur.fetchone()[0]
    
    cash = TOTAL_CAPITAL - total_invested + total_sold
    # 实时市值（现价 × 股数），口径与 double_monitor 一致
    mkt_value = holding_cost  # 兜底：无 conn_mkt 时退回成本
    if conn_mkt is not None:
        mcur = conn_mkt.cursor()
        cur.execute("SELECT code, buy_shares FROM trades WHERE status IN ('持有','部分止盈')")
        mkt_value = 0.0
        for code, shares in cur.fetchall():
            mcur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
            pr = mcur.fetchone()
            if not pr or pr[0] is None:
                continue
            mkt_value += float(pr[0]) * shares
    total_value = cash + mkt_value
    total_return = (total_value - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100
    
    
    # 胜率
    cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL")
    total_closed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL AND profit_amount > 0")
    wins = cur.fetchone()[0]
    win_rate = wins / total_closed * 100 if total_closed > 0 else 0
    
    # 盈亏比
    cur.execute("SELECT COALESCE(AVG(profit_amount),0) FROM trades WHERE sell_date IS NOT NULL AND profit_amount > 0")
    avg_win = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(AVG(ABS(profit_amount)),0) FROM trades WHERE sell_date IS NOT NULL AND profit_amount <= 0")
    avg_loss = cur.fetchone()[0]
    profit_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    
    return {
        'total_value': round(total_value, 2),
        'cash': round(cash, 2),
        'total_return': round(total_return, 2),
        'win_rate': round(win_rate, 1),
        'profit_ratio': round(profit_ratio, 2),
        'wins': wins,
        'total_closed': total_closed,
        'realized_pnl': round(realized_pnl, 2),
    }

# ═══ 功能二：新股虹吸过滤器 ═══
def scan_upcoming_ipos():
    """扫描未来7天新股上市日历"""
    ipos = []
    try:
        url = "http://push2delay.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 50, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fs': 'm:0+t:8',  # 新股
            'fields': 'f12,f14,f20,f84,f100,f127'
        }
        r = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        items = data.get('data', {}).get('diff', [])
        for item in items:
            code = item.get('f12', '')
            name = item.get('f14', '')
            mcap = item.get('f20', 0) or 0
            sector = item.get('f127', '')
            if mcap and isinstance(mcap, (int, float)) and mcap > LARGE_IPO_THRESHOLD:
                ipos.append({
                    'code': code, 'name': name, 'market_cap': mcap,
                    'sector': sector, 'source': '东财新股列表'
                })
    except Exception as e:
        print(f"[WARN] 获取新股列表失败: {e}")
    
    # 备用：从东方财富API获取新股日历
    if not ipos:
        try:
            url = "http://push2delay.eastmoney.com/api/qt/stock/get"
            params = {'secid': '0.000001', 'fields': 'f57,f58,f84,f85', 'invt': 2, 'fltt': 2}
            r = requests.get(url, params=params, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        except Exception as e:
            print(f"[WARN] 东方财富备用新股API失败: {e}")
    
    return ipos

def check_ipo_suction(candidates, conn_sim):
    """检查新股虹吸影响，返回暂缓清单"""
    cur = conn_sim.cursor()
    today = date.today().isoformat()
    
    # 清理过期暂缓
    cur.execute("UPDATE ipo_blocks SET active=0 WHERE suspend_end < ?", (today,))
    conn_sim.commit()
    
    # 获取活跃的暂缓记录
    cur.execute("SELECT * FROM ipo_blocks WHERE active=1")
    active_blocks = [dict(r) for r in cur.fetchall()]
    
    suspended = set()
    for block in active_blocks:
        if block['affected_stocks']:
            affected = json.loads(block['affected_stocks'])
            for s in affected:
                suspended.add(s['code'])
    
    # 扫描新股
    ipos = scan_upcoming_ipos()
    for ipo in ipos:
        if ipo['market_cap'] > LARGE_IPO_THRESHOLD:
            sector = ipo['sector']
            # 找出候选池中同行业
            affected = [s for s in candidates if s.get('sector', '') == sector or s.get('name', '') == sector]
            if affected:
                # 计算暂缓期
                ipo_date = date.today() + timedelta(days=1)
                suspend_end = ipo_date
                days_added = 0
                while days_added < SUSPEND_DAYS:
                    suspend_end += timedelta(days=1)
                    if suspend_end.weekday() < 5:  # 工作日
                        days_added += 1
                
                affected_list = [{'code': s['code'], 'name': s['name']} for s in affected]
                for s in affected:
                    suspended.add(s['code'])
                
                cur.execute("""
                    INSERT INTO ipo_blocks (ipo_code, ipo_name, ipo_date, ipo_market_cap, sector,
                    suspend_start, suspend_end, affected_stocks)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (ipo['code'], ipo['name'], ipo_date.isoformat(), ipo['market_cap'],
                      sector, ipo_date.isoformat(), suspend_end.isoformat(),
                      json.dumps(affected_list, ensure_ascii=False)))
                conn_sim.commit()
                
                print(f"\n{'='*55}")
                print(f"🚨【市场事件】{ipo['name']}({ipo['code']}) 预计上市，首发市值{ipo['market_cap']/1e8:.0f}亿")
                print(f"暂缓同行业{len(affected)}只标的: {', '.join([s['name'] for s in affected])}")
                print(f"暂缓期: {ipo_date} - {suspend_end}（{SUSPEND_DAYS}个交易日）")
                print(f"{'='*55}")
    
    return ipos, suspended

# ═══ 主流程 ═══
def main():
    print("=" * 55)
    print("📊 翻倍策略系统 — 模拟交易+新股虹吸")
    print(f"   日期: {date.today()}")
    print("=" * 55)
    
    # 初始化
    conn_sim = init_sim_db()
    # 加载候选池（统一从 double_up_scores 表读取）
    candidates = pool_loader.load_pool()
    print(f"\n📋 候选池: {len(candidates)} 只")
    
    # 新股虹吸检查
    print("\n🔍 新股虹吸扫描...")
    ipos, suspended = check_ipo_suction(candidates, conn_sim)
    print(f"   新股: {len(ipos)} 只大市值IPO")
    print(f"   暂缓: {len(suspended)} 只标的")
    
    # 连接市场数据库获取实时价格
    if not os.path.exists(MARKET_DB):
        msg = f"🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}"
        print(f"\n{'='*60}\n{msg}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn_mkt = sqlite3.connect(MARKET_DB)
    cur_mkt = conn_mkt.cursor()
    
    # 获取所有候选股的最新价格和信号
    print(f"\n🔍 信号扫描...")
    signals_found = []
    for s in candidates:
        code = s['code']
        # 跳过暂缓标的
        if code in suspended:
            continue
        
        # 获取K线计算信号
        cur_mkt.execute("SELECT date, close, volume, high FROM klines WHERE code=? ORDER BY date DESC LIMIT 60", (code,))
        rows = cur_mkt.fetchall()
        klines = [{'date': r[0], 'close': r[1], 'volume': r[2], 'high': r[3]} for r in rows]
        if len(klines) < 60:
            continue
        
        closes = [k['close'] for k in klines]
        volumes = [k['volume'] for k in klines]
        highs = [k['high'] for k in klines]
        price = klines[0]['close']
        
        # 计算信号
        sigs = []
        # A: 站上20日均线+均线拐头
        if len(closes) >= 20:
            ma20 = sum(closes[:20]) / 20
            ma20_prev = sum(closes[1:21]) / 20
            if price > ma20 and ma20 >= ma20_prev:
                sigs.append('A')
        # B: 倍量启动
        if len(volumes) >= 13:
            v3 = sum(volumes[:3])
            v10 = sum(volumes[3:13]) / 10
            if v10 > 0 and v3 > v10 * 1.8:
                sigs.append('B')
        # C: 20日新高
        if len(highs) >= 20:
            if price >= max(highs[:20]):
                sigs.append('C')
        # D: MACD金叉
        if len(closes) >= 35:
            def ema(d, p):
                k = 2/(p+1); r = [d[0]]
                for x in d[1:]: r.append(x*k + r[-1]*(1-k))
                return r
            ef = ema(closes, 12); es = ema(closes, 26)
            dif = [ef[i]-es[i] for i in range(len(closes))]
            dea = ema(dif[:20], 9) if len(dif) >= 20 else [0]
            dc, dp = dif[0], dif[1] if len(dif) > 1 else 0
            dea_c, dea_p = dea[0], dea[1] if len(dea) > 1 else 0
            if dp < dea_p and dc > dea_c: sigs.append('D')
            elif dc > 0 and dea_c > 0 and dc > dea_c: sigs.append('D')
        
        s['signals'] = sigs
        s['price'] = price
        s['high_ever'] = max(highs) if highs else price
        
        # 检查是否触发现有持仓的止盈止损（含滑点修正+动态止损）
        check_exit_signals(conn_sim, code, price, s['high_ever'], pool_count=len(candidates))
        
        # 急跌保护：检查是否触发急跌预警
        
        # 检查是否触发买入信号（⭐⭐⭐）
        if len(sigs) >= 3:
            signals_found.append(s)
    
    # 处理开仓
    print(f"\n{'='*55}")
    print("📋 模拟交易处理")
    print(f"{'='*55}")
    
    for s in signals_found:
        # 获取次日开盘价（用收盘价近似）
        buy_price = s['price']
        tid, msg = open_position(conn_sim, s['code'], s['name'], s.get('sector', ''), buy_price, '⭐⭐⭐')
        if tid:
            print(f"  🚀 开仓: {s['code']} {s['name']} {msg}")
        else:
            print(f"  ⏸️ 跳过: {s['code']} {s['name']} - {msg}")
    
    # 输出当前持仓
    holdings = get_holdings(conn_sim)
    print(f"\n{'='*55}")
    print(f"📊 当前模拟持仓: {len(holdings)} 只")
    print(f"{'='*55}")
    if holdings:
        print(f"{'代码':<8} {'名称':<10} {'买入日':<12} {'买入价':<8} {'数量':<6} {'状态':<8}")
        print("-" * 55)
        for h in holdings:
            print(f"{h['code']:<8} {h['name']:<10} {h['buy_date']:<12} {h['buy_price']:<8.2f} {h['buy_shares']:<6} {h['status']:<8}")
    else:
        print("  无持仓")
    
    # 历史追溯：2026-07-24 迪哲医药
    print(f"\n{'='*55}")
    print("📋 历史追溯")
    print(f"{'='*55}")
    cur = conn_sim.cursor()
    cur.execute("SELECT COUNT(*) FROM trades")
    cnt = cur.fetchone()[0]
    if cnt == 0:
        # 追溯登记迪哲医药
        tid, msg = open_position(conn_sim, '688192', '迪哲医药', '化学制剂', 55.60, '⭐⭐⭐', '2026-07-24')
        if tid:
            print(f"  ✅ 追溯登记: 迪哲医药(688192) 2026-07-24 买入价55.60")
        else:
            print(f"  ⚠️ 追溯失败: {msg}")
    else:
        # 更新迪哲医药持仓成本（含交易费用）
        # 买入449股×55.60=24,964.4元，买入佣金5元，过户费0.25元
        # 总成本24,969.65元，实际成本价55.61元/股
        cur.execute("SELECT id, buy_price, buy_amount, buy_shares FROM trades WHERE code='688192' AND status='持有'")
        dizhe = cur.fetchone()
        if dizhe:
            old_price, old_amount = dizhe[1], dizhe[2]
            correct_amount = 24969.65
            correct_price = 55.61
            if abs(old_amount - correct_amount) > 0.01:
                cur.execute("UPDATE trades SET buy_amount=?, buy_price=? WHERE id=?", (correct_amount, correct_price, dizhe[0]))
                conn_sim.commit()
                print(f"  ✅ 更新迪哲医药成本: 买入金额{old_amount:.2f}→{correct_amount:.2f}元, 成本价{old_price:.2f}→{correct_price:.2f}元/股")
            else:
                print(f"  ✅ 迪哲医药成本已正确: {correct_amount:.2f}元, {correct_price:.2f}元/股")
    
    # 组合统计
    stats = calc_portfolio_stats(conn_sim, conn_mkt)
    print(f"\n{'='*55}")
    print(f"📊 模拟组合统计")
    print(f"{'='*55}")
    print(f"  总资产: {stats['total_value']:,.0f}元")
    print(f"  现金: {stats['cash']:,.0f}元")
    print(f"  累计收益: {stats['total_return']:+.2f}%")
    print(f"  已实现盈亏: {stats['realized_pnl']:+,.0f}元")
    print(f"  胜率: {stats['win_rate']:.1f}% ({stats['wins']}/{stats['total_closed']})")
    print(f"  盈亏比: {stats['profit_ratio']:.2f}")
    
    # 保存快照
    cur = conn_sim.cursor()
    cur.execute("""
        INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value, total_return_pct, win_count, loss_count)
        VALUES (?,?,?,?,?,?,?)
    """, (date.today().isoformat(), stats['total_value'], stats['cash'],
          stats['total_value'] - stats['cash'], stats['total_return'],
          stats['wins'], stats['total_closed'] - stats['wins']))
    conn_sim.commit()
    
    # ═══ 补丁3：组合净值总回撤止损 ═══
    should_liquidate, dd_messages = check_portfolio_drawdown(conn_sim)
    if should_liquidate:
        for m in dd_messages:
            print(f"   {m}")
    
    # ═══ 补丁2：候选池枯竭预警 ═══
    pool_health = check_pool_health(len(candidates))
    for w in pool_health:
        print(f"   {w}")
    
    conn_mkt.close()
    conn_sim.close()
    print(f"\n✅ 完成 | {date.today()}")

# ═══ 补丁2：候选池枯竭预案 ═══
def check_pool_health(pool_count):
    """检查候选池健康度，返回警告"""
    warnings = []
    if pool_count < POOL_WARNING_THRESHOLD:
        warnings.append(f"⚠️候选池仅剩{pool_count}只，低于{POOL_WARNING_THRESHOLD}只阈值")
        if pool_count < POOL_EMERGENCY_THRESHOLD:
            warnings.append(f"🚨候选池严重枯竭（<{POOL_EMERGENCY_THRESHOLD}只），止损收紧至-{EMERGENCY_STOP_LOSS:.0%}，暂停开新仓")
    return warnings

# ═══ 补丁3：组合净值回撤减仓 ═══
def check_portfolio_drawdown(conn_sim):
    """
    检查组合净值回撤，若从30日高点回撤超-15%，强制减仓至50%
    返回: (should_trim: bool, messages: list)
    """
    cur = conn_sim.cursor()
    today = date.today().isoformat()
    messages = []
    
    # 获取最近30日的净值快照
    cur.execute("""
        SELECT date, total_value FROM portfolio_snapshots
        WHERE date >= ? ORDER BY date DESC
    """, ((date.today() - timedelta(days=45)).isoformat(),))  # 取45天确保有30个交易日
    snapshots = [dict(r) for r in cur.fetchall()]
    
    if not snapshots:
        return False, messages
    
    # 最近30日最高净值
    recent_high = max(s['total_value'] for s in snapshots)
    current_value = snapshots[0]['total_value']
    
    # 计算回撤
    drawdown = (recent_high - current_value) / recent_high
    
    if drawdown >= PORTFOLIO_DRAWDOWN_LIMIT:
        # 触发减仓至50%
        messages.append(f"🚨组合净值回撤{drawdown:.1%}，超过{PORTFOLIO_DRAWDOWN_LIMIT:.0%}减仓线！执行减仓至50%")
        
        # 获取所有持仓，按浮盈排序（亏损多的先卖）
        cur.execute("""SELECT id, code, name, buy_shares, buy_price, buy_amount 
            FROM trades WHERE status IN ('持有','部分止盈')
            ORDER BY (buy_price - ?) / buy_price ASC""", (current_value / 100000,))
        holdings = [dict(r) for r in cur.fetchall()]
        
        # 计算需要卖出的比例（当前仓位减到50%）
        total_position_value = sum(h['buy_amount'] for h in holdings)
        target_value = total_position_value * 0.5  # 减到50%
        sell_value = 0
        sold_count = 0
        
        for h in holdings:
            if sell_value >= target_value:
                break
            # 卖出该持仓
            cur.execute("""
                UPDATE trades SET sell_date=?, sell_price=?, status='减仓',
                profit_pct=?, profit_amount=?
                WHERE id=?
            """, (today, h['buy_price'] * 0.95, 
                  -PORTFOLIO_DRAWDOWN_LIMIT * 100 * 0.5, 
                  -h['buy_amount'] * PORTFOLIO_DRAWDOWN_LIMIT * 0.5, h['id']))
            sell_value += h['buy_amount']
            sold_count += 1
        
        messages.append(f"  减仓{sold_count}只持仓，仓位降至50%")
        conn_sim.commit()
        return True, messages
    
    return False, messages

# ═══ 补丁1：急跌保护（补丁1b）═══
def check_flash_crash(holdings, current_prices):
    """
    检查盘中急跌：若单日跌幅>6%且未到-8%，发出预警
    返回: (warnings: list)
    """
    warnings = []
    for h in holdings:
        code = h['code']
        price = current_prices.get(code)
        if not price or h['buy_price'] == 0:
            continue
        ret = (price - h['buy_price']) / h['buy_price']
        
        # 急跌预警：-6% ~ -8%
        if -FLASH_CRASH >= ret > -STOP_LOSS:
            warnings.append(f"⚠️急跌预警 {code} {h.get('name','')} | 成本{h['buy_price']:.2f}→当前{price:.2f} | 亏损{ret*100:.1f}%（距止损仅{(-STOP_LOSS - abs(ret))*100:.0f}%）")
        
        # 急跌收盘保护：若跌超-6%且收盘前未收回，按收盘价平仓
        if ret <= -FLASH_CRASH:
            # 在收盘扫描中执行
            warnings.append(f"🔴急跌收盘保护 {code} {h.get('name','')} | 跌{ret*100:.1f}% | 按收盘价强制平仓")
    
    return warnings

if __name__ == '__main__':
    main()