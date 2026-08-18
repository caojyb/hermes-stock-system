#!/usr/bin/env python3
"""
系统参数自适应优化（滚动优化器）
================================
每周日17:30在候选池刷新之前运行，自动滚动回测三层过滤器参数，
选出过去3年卡玛比率最高的参数组合，作为下周筛选标准。

参数范围：
  营收增速: 10%~50% 步长5% (当前30%)
  回撤下界: 10%~30% 步长5% (当前15%)
  回撤上界: 35%~60% 步长5% (当前45%)
  换手率:   0.5%~5% 步长0.5% (当前1%)
"""
import os, sys, json, math, sqlite3
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ── 参数搜索范围 ──
REV_RANGE = list(range(10, 55, 5))           # 10%~50% 步长5%
DD_LOW_RANGE = list(range(10, 35, 5))        # 10%~30% 步长5%
DD_HIGH_RANGE = list(range(35, 65, 5))       # 35%~60% 步长5%
TR_RANGE = [x / 100 for x in range(50, 550, 50)]  # 0.5%~5% 步长0.5%

# 默认参数（当前固定值）
DEFAULT_REV = 30
DEFAULT_DD_LOW = 15
DEFAULT_DD_HIGH = 45
DEFAULT_TR = 1.0

TOTAL_CAPITAL = 1000000       # 模拟初始资金
COMMISSION = 0.00025          # 佣金万2.5双向
STAMP_TAX = 0.0005            # 印花税千0.5卖出
SLIPPAGE = 0.001              # 滑点0.1%
STOP_LOSS = 0.08              # 止损-8%
TP1, TP2, TP3 = 0.25, 0.50, 0.80  # 止盈三档

def load_data():
    """加载K线数据和财务数据"""
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 加载股票列表
    cur.execute('SELECT code, name, sector, list_date FROM stocks')
    stocks = {r['code']: dict(r) for r in cur.fetchall()}
    
    # 加载K线数据（收盘价）
    cur.execute('SELECT code, date, close FROM klines ORDER BY code, date')
    klines = defaultdict(dict)
    for r in cur.fetchall():
        klines[r['code']][r['date']] = r['close']
    
    # 加载财务数据（季度营收增长率）
    cur.execute('''
        SELECT code, report_date, revenue_growth, profit_growth, debt_ratio
        FROM financial_data
        WHERE revenue_growth IS NOT NULL
        ORDER BY code, report_date DESC
    ''')
    fin = defaultdict(list)
    for r in cur.fetchall():
        fin[r['code']].append(dict(r))
    
    # 加载换手率
    cur.execute('SELECT code, turnover_rate FROM indicators WHERE turnover_rate IS NOT NULL')
    tr_data = {r['code']: r['turnover_rate'] for r in cur.fetchall()}
    
    # 加载总股本
    cur.execute('SELECT code, total_shares_real FROM stocks WHERE total_shares_real IS NOT NULL')
    shares = {r['code']: r['total_shares_real'] for r in cur.fetchall()}
    
    conn.close()
    return stocks, klines, fin, tr_data, shares

def get_rebalance_dates(start_date, end_date):
    """生成每月末的再平衡日期"""
    dates = []
    d = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    while d <= end:
        # 每月最后一天
        next_month = d.month % 12 + 1
        next_year = d.year + (1 if d.month == 12 else 0)
        month_end = datetime(next_year, next_month, 1) - timedelta(days=1)
        if month_end > end:
            month_end = end
        dates.append(month_end.strftime('%Y-%m-%d'))
        d = month_end + timedelta(days=1)
    return sorted(set(dates))

def simulate(rev_th, dd_low, dd_high, tr_th, stocks, klines, fin, tr_data, shares,
             start_date, end_date):
    """
    对一组参数做回测模拟
    返回: (total_return, max_drawdown, calmar_ratio, n_stocks)
    """
    rebalance_dates = get_rebalance_dates(start_date, end_date)
    
    portfolio = {}  # code -> {buy_price, buy_date, shares, cost}
    cash = TOTAL_CAPITAL
    realized_pnl = 0
    peak_value = TOTAL_CAPITAL
    max_drawdown = 0
    
    # 跟踪每期组合市值
    portfolio_values = [TOTAL_CAPITAL]
    
    for rd in rebalance_dates:
        rd_date = rd
        
        # 止盈止损检查
        for code in list(portfolio.keys()):
            pos = portfolio[code]
            prices = klines.get(code, {})
            dates = sorted(prices.keys())
            current_price = None
            for d in dates:
                if d >= rd_date:
                    current_price = prices[d]
                    break
            if current_price is None:
                current_price = list(prices.values())[-1] if prices else pos['buy_price']
            
            ret = (current_price - pos['buy_price']) / pos['buy_price']
            
            if ret <= -STOP_LOSS:
                sell_amount = pos['shares'] * current_price * (1 - COMMISSION - STAMP_TAX - SLIPPAGE)
                pnl = sell_amount - pos['cost']
                realized_pnl += pnl
                cash += sell_amount
                del portfolio[code]
                continue
            
            if ret >= TP3:
                sell_amount = pos['shares'] * current_price * (1 - COMMISSION - STAMP_TAX - SLIPPAGE)
                pnl = sell_amount - pos['cost']
                realized_pnl += pnl
                cash += sell_amount
                del portfolio[code]
                continue
        
        # 计算本期组合市值
        total_value = cash + realized_pnl
        for pos in portfolio.values():
            # 用买入价近似（没有实时价格）
            total_value += pos['cost']
        portfolio_values.append(total_value)
        peak_value = max(peak_value, total_value)
        dd = (peak_value - total_value) / peak_value if peak_value > 0 else 0
        max_drawdown = max(max_drawdown, dd)
        
        # 筛选候选股
        candidates = []
        for code in stocks:
            sinfo = stocks[code]
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S','退')): continue
            if code.startswith(('688', '787')): continue
            
            fin_data = fin.get(code, [])
            if len(fin_data) < 2: continue
            r1g = fin_data[0].get('revenue_growth', 0) or 0
            r2g = fin_data[1].get('revenue_growth', 0) or 0
            if r1g < rev_th or r2g < rev_th: continue
            p1g = fin_data[0].get('profit_growth', 0) or 0
            if p1g < 0: continue
            dr = fin_data[0].get('debt_ratio', 0) or 0
            if dr >= 65: continue
            
            ts = shares.get(code, 0) or 0
            prices = klines.get(code, {})
            if not prices: continue
            last_price = list(prices.values())[-1]
            mcap = ts * last_price / 1e8
            if mcap < 20 or mcap > 200: continue
            
            price_list = sorted(prices.items())
            if len(price_list) < 250: continue
            recent = [p[1] for p in price_list[-250:]]
            high_250 = max(recent)
            cur_p = recent[-1]
            dd_stock = (high_250 - cur_p) / high_250 * 100
            if dd_stock < dd_low or dd_stock > dd_high: continue
            
            tr = tr_data.get(code, 0) or 0
            if tr < tr_th: continue
            
            candidates.append(code)
        
        if not candidates:
            continue
        
        # 买入
        buy_prices = {}
        for code in candidates:
            if code in portfolio: continue
            prices = klines.get(code, {})
            dates = sorted(prices.keys())
            next_price = None
            for d in dates:
                if d > rd_date:
                    next_price = prices[d]
                    break
            if next_price is None or next_price <= 0: continue
            buy_prices[code] = next_price
        
        if not buy_prices: continue
        
        per_invest = TOTAL_CAPITAL * 0.025
        for code in sorted(buy_prices.keys())[:30]:
            price = buy_prices[code]
            shares_buy = int(per_invest / price)
            if shares_buy <= 0: continue
            cost = shares_buy * price * (1 + COMMISSION)
            if cost > cash: continue
            cash -= cost
            portfolio[code] = {
                'buy_price': price, 'buy_date': rd_date,
                'shares': shares_buy, 'cost': cost
            }
    
    # 最终结果
    final_value = cash + realized_pnl
    for pos in portfolio.values():
        final_value += pos['cost']
    
    total_return = (final_value - TOTAL_CAPITAL) / TOTAL_CAPITAL
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    years = (end - start).days / 365.25
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    calmar = annual_return / max_drawdown if max_drawdown > 0 else 0
    
    return total_return, max_drawdown, calmar, len(candidates)

def run():
    """主入口"""
    today = date.today()
    end_date = today.isoformat()
    start_3y = (today - timedelta(days=365*3)).isoformat()
    start_1y = (today - timedelta(days=365)).isoformat()
    
    print(f'📊 系统参数自适应优化 | {today}')
    print(f'   回测区间: {start_3y} ~ {end_date}')
    print(f'   参数组合数: {len(REV_RANGE)}×{len(DD_LOW_RANGE)}×{len(DD_HIGH_RANGE)}×{len(TR_RANGE)}')
    print()
    
    # 加载数据
    print('📥 加载数据...')
    stocks, klines, fin, tr_data, shares = load_data()
    print(f'   股票: {len(stocks)}只')
    print(f'   有K线数据: {len(klines)}只')
    print(f'   有财务数据: {len(fin)}只')
    print()
    
    # 计算总组合数
    total_combos = 0
    for rev in REV_RANGE:
        for dd_low in DD_LOW_RANGE:
            for dd_high in DD_HIGH_RANGE:
                if dd_low >= dd_high:
                    continue
                for tr in TR_RANGE:
                    total_combos += 1
    
    print(f'   有效组合数（排除dd_low>=dd_high）: {total_combos}')
    print()
    
    # 先测试3年回测是否可行
    test_combos = []
    for rev in [20, 30, 40]:
        for dd_low in [10, 15]:
            for dd_high in [40, 50]:
                if dd_low < dd_high:
                    test_combos.append((rev, dd_low, dd_high, 1.0))
    
    print('📊 测试回测（部分组合）...')
    # 新逻辑：在最大回撤 ≤ 30% 的约束下，选年化收益率最高的组合
    best = None  # {rev, dd_low, dd_high, tr, annual_return, max_dd, calmar, n}
    fallback_candidates = []  # 用于无组合满足≤30%时的降级选择
    results = []
    
    for rev, dd_low, dd_high, tr in test_combos:
        try:
            tr_pct, max_dd, calmar, n = simulate(rev, dd_low, dd_high, tr, stocks, klines, fin, tr_data, shares, start_3y, end_date)
            annual_return = (1 + tr_pct) ** (1/3) - 1  # 3年年化
            results.append({
                'rev': rev, 'dd_low': dd_low, 'dd_high': dd_high, 'tr': tr,
                'annual_return': round(annual_return * 100, 1),
                'max_dd': round(max_dd * 100, 1),
                'calmar': round(calmar, 2), 'n_stocks': n
            })
            print(f'   营收>{rev}% 回撤{dd_low}-{dd_high}% 换手>{tr*100:.0f}%  => 年化{annual_return*100:.1f}% 最大回撤{max_dd*100:.1f}% 候选{n}只')
            
            if n < 5:
                continue
            
            # 硬约束：最大回撤 ≤ 30%
            if max_dd <= 0.30:
                if best is None or annual_return > best['annual_return']:
                    best = {
                        'rev': rev, 'dd_low': dd_low, 'dd_high': dd_high, 'tr': tr,
                        'annual_return': annual_return, 'max_dd': max_dd,
                        'calmar': calmar, 'n': n
                    }
            else:
                # 记录降级候选（回撤最小的前3组）
                fallback_candidates.append({
                    'rev': rev, 'dd_low': dd_low, 'dd_high': dd_high, 'tr': tr,
                    'annual_return': annual_return, 'max_dd': max_dd,
                    'calmar': calmar, 'n': n
                })
        except Exception as e:
            print(f'   营收>{rev}% 回撤{dd_low}-{dd_high}% 换手>{tr*100:.0f}%  => 失败: {e}')
    
    # 降级处理：无组合满足回撤≤30%，选回撤最小的前3组中年化最高的
    if best is None:
        fallback_candidates.sort(key=lambda x: x['max_dd'])
        top3 = fallback_candidates[:3]
        if top3:
            top3.sort(key=lambda x: x['annual_return'], reverse=True)
            best = top3[0]
            print(f'\n⚠️ 无组合满足回撤≤30%约束，降级选取回撤最小的前3组中年化最高的')
    
    if best:
        rev = best['rev']; dd_low = best['dd_low']; dd_high = best['dd_high']; tr = best['tr']
        ar = best['annual_return']; md = best['max_dd']
        print(f'\n🏆 最优参数（约束: 最大回撤≤30%）: 营收>{rev}% 回撤{dd_low}-{dd_high}% 换手>{tr*100:.0f}% 年化{ar*100:.1f}% 最大回撤{md*100:.1f}%')
    else:
        print(f'\n⚠️ 所有组合候选池不足5只，使用默认参数: 营收>{DEFAULT_REV}% 回撤{DEFAULT_DD_LOW}-{DEFAULT_DD_HIGH}% 换手>{DEFAULT_TR:.0f}%')
    
    # 保存到数据库
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS param_optimization_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            rev_threshold REAL,
            dd_low REAL,
            dd_high REAL,
            tr_threshold REAL,
            annual_return REAL,
            max_drawdown REAL,
            calmar_ratio REAL,
            test_start TEXT,
            test_end TEXT,
            n_candidates INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    cur.execute('''
        INSERT INTO param_optimization_log 
        (date, rev_threshold, dd_low, dd_high, tr_threshold, annual_return, max_drawdown, calmar_ratio, test_start, test_end, n_candidates)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (today.isoformat(), best['rev'] if best else DEFAULT_REV,
          best['dd_low'] if best else DEFAULT_DD_LOW,
          best['dd_high'] if best else DEFAULT_DD_HIGH,
          best['tr'] if best else DEFAULT_TR,
          best['annual_return'] * 100 if best else 0,
          best['max_dd'] * 100 if best else 0,
          best['calmar'] if best else 0,
          start_3y, end_date, best['n'] if best else 0))
    conn.commit()
    conn.close()
    print(f'   已保存到 param_optimization_log 表')
    
    print(f'\n{"="*55}')
    print(f'📊 本周最优参数组合（约束：最大回撤 ≤ 30%）:')
    if best:
        print(f'   营收 > {best["rev"]}%, 回撤 {best["dd_low"]}%-{best["dd_high"]}%, 换手 > {best["tr"]*100:.0f}%, 年化收益 = {best["annual_return"]*100:.1f}%, 最大回撤 = {best["max_dd"]*100:.1f}%')
    else:
        print(f'   ⚠️ 本周无有效参数优化，沿用上周参数')
        print(f'   营收 > {DEFAULT_REV}%, 回撤 {DEFAULT_DD_LOW}%-{DEFAULT_DD_HIGH}%, 换手 > {DEFAULT_TR:.0f}%')
    print(f'{"="*55}')

if __name__ == '__main__':
    run()
