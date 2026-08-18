#!/usr/bin/env python3
"""
长持模式历史回测
===============
对指定基准日运行长持种子筛选，跟踪后续股价表现，计算收益/回撤/翻倍率。
"""
import os, sys, json, sqlite3, requests, time, math
from datetime import date, datetime, timedelta
from collections import defaultdict, OrderedDict
from pathlib import Path

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
TOTAL_CAPITAL = 1000000

# 从腾讯财经API获取历史K线（前复权）
def fetch_klines_hist(code, start_date, end_date):
    """获取个股历史K线（支持指定日期范围）- 使用腾讯财经API"""
    # 腾讯API代码格式：sh600519 / sz000001
    prefix = 'sh' if code.startswith(('60', '68')) else 'sz'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start_date},{end_date},1,qfq'
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        data = r.json()
        if data.get('code') != 0:
            return {}
        # 前复权数据在 qfqday 或 day 字段
        klines = data.get('data', {}).get(f'{prefix}{code}', {})
        raw = klines.get('qfqday') or klines.get('day') or []
        result = {}
        for k in raw:
            d = k[0]  # 日期
            close = float(k[2])  # 收盘价
            result[d] = close
        return result
    except Exception as e:
        return {}

def load_fin_data(base_date):
    """加载基准日可用的财务数据"""
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 基准日前最近3个完整季度
    cur.execute('SELECT DISTINCT report_date FROM financial_data WHERE report_date < ? ORDER BY report_date DESC LIMIT 3', (base_date,))
    quarters = [r[0] for r in cur.fetchall()]
    if len(quarters) < 3:
        print(f'  数据不足3个季度: {quarters}')
        conn.close()
        return {}, [], []
    
    q1, q2, q3 = quarters[0], quarters[1], quarters[2]
    
    # 3个季度都有数据的股票
    cur.execute('''
        SELECT f1.code, f1.revenue_growth as r1, f1.profit_growth as p1,
               f1.roe as roe1, f1.debt_ratio as dr1,
               f2.revenue_growth as r2, f2.profit_growth as p2,
               f3.revenue_growth as r3, f3.profit_growth as p3
        FROM financial_data f1
        JOIN financial_data f2 ON f1.code = f2.code AND f2.report_date = ?
        JOIN financial_data f3 ON f1.code = f3.code AND f3.report_date = ?
        WHERE f1.report_date = ?
          AND f1.revenue_growth IS NOT NULL AND f2.revenue_growth IS NOT NULL AND f3.revenue_growth IS NOT NULL
          AND f1.profit_growth IS NOT NULL AND f2.profit_growth IS NOT NULL AND f3.profit_growth IS NOT NULL
    ''', (q2, q3, q1))
    
    stocks_data = {}
    for r in cur.fetchall():
        stocks_data[r['code']] = dict(r)
    
    # 获取股票名称、上市日期、总股本
    cur.execute('SELECT code, name, sector, list_date, total_shares_real FROM stocks')
    stocks_info = {r['code']: dict(r) for r in cur.fetchall()}
    
    # 获取PE分位
    cur.execute('SELECT code, pe_pct, pe_ttm FROM pe_pb_data')
    pe_data = {r['code']: {'pe_pct': r['pe_pct'], 'pe_ttm': r['pe_ttm']} for r in cur.fetchall()}
    
    conn.close()
    return stocks_data, stocks_info, pe_data

def screen(base_date, stocks_data, stocks_info, pe_data):
    """运行长持种子筛选"""
    results = []
    
    for code, fin in stocks_data.items():
        sinfo = stocks_info.get(code, {})
        name = sinfo.get('name', '')
        sector = sinfo.get('sector', '')
        
        # 排除ST/科创板
        if any(name.startswith(p) for p in ('ST','*ST','S','退')): continue
        if code.startswith(('688', '787')): continue
        if not code.startswith(('60', '00', '30')): continue
        
        r1, r2, r3 = fin['r1'], fin['r2'], fin['r3']
        p1, p2, p3 = fin['p1'], fin['p2'], fin['p3']
        roe = fin.get('roe1', 0) or 0
        dr = fin.get('dr1', 0) or 0
        
        # 条件1：营收连续加速
        if not (r1 > r2 > r3): continue
        
        # 条件2：利润连续加速
        if not (p1 > p2 > p3): continue
        
        # 条件3：行业景气度 > 0（跳过，无历史数据）
        
        # 条件4：PE分位 < 50%（使用当前数据近似）
        pe_info = pe_data.get(code, {})
        pe_pct = pe_info.get('pe_pct')
        if pe_pct is not None and pe_pct >= 50: continue
        
        # 条件5：ROE > 15%
        if roe < 15: continue
        
        # 条件6：市值条件（需要股价，稍后计算）
        # 条件7：无资金流/事件风险（跳过）
        
        results.append({
            'code': code,
            'name': name,
            'sector': sector,
            'r1': r1, 'r2': r2, 'r3': r3,
            'p1': p1, 'p2': p2, 'p3': p3,
            'roe': roe,
            'pe_pct': pe_pct,
        })
    
    return results

def fetch_prices_for_stocks(codes, start_date, end_date, stocks_info):
    """批量获取历史股价，按30%估算市值筛选"""
    valid = []
    for code in codes:
        sinfo = stocks_info.get(code, {})
        ts = sinfo.get('total_shares_real', 0) or 0
        
        # 获取2019年初的股价
        prices = fetch_klines_hist(code, start_date, end_date)
        if not prices:
            continue
        
        # 获取基准日附近的价格（基准日后第一个交易日）
        sorted_dates = sorted(prices.keys())
        start_price = None
        for d in sorted_dates:
            if d >= start_date:
                start_price = prices[d]
                break
        
        if not start_price or start_price <= 0:
            continue
        
        # 市值条件 30-200亿
        mcap = ts * start_price / 1e8
        if mcap < 30 or mcap > 200:
            continue
        
        valid.append({
            'code': code,
            'name': sinfo.get('name', ''),
            'sector': sinfo.get('sector', ''),
            'start_price': start_price,
            'mcap': round(mcap, 1),
            'prices': prices,
            'ts': ts,
        })
    
    return valid

def calc_performance(stocks, end_date):
    """计算每只标的的后续表现"""
    perf = []
    
    for s in stocks:
        prices = s['prices']
        start_price = s['start_price']
        
        # 获取结束日期附近的股价
        sorted_dates = sorted(prices.keys())
        end_price = None
        for d in sorted_dates:
            if d >= end_date:
                end_price = prices[d]
                break
        
        if not end_price:
            continue
        
        # 总涨幅
        total_return = (end_price - start_price) / start_price * 100
        
        # 计算最大涨幅和最大回撤
        max_price = start_price
        max_increase = 0
        max_drawdown = 0
        
        for d in sorted_dates:
            p = prices[d]
            if p > max_price:
                max_price = p
            increase = (p - start_price) / start_price * 100
            drawdown = (max_price - p) / max_price * 100
            if increase > max_increase:
                max_increase = increase
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # 翻倍
        doubled = total_return >= 100
        
        perf.append({
            'code': s['code'],
            'name': s['name'],
            'sector': s['sector'],
            'start_price': start_price,
            'end_price': end_price,
            'total_return': round(total_return, 1),
            'max_increase': round(max_increase, 1),
            'max_drawdown': round(max_drawdown, 1),
            'doubled': doubled,
            'mcap': s['mcap'],
        })
    
    return perf

def run_backtest(base_date, label):
    """运行一次完整回测"""
    print(f'\n{"="*60}')
    print(f'📊 长持模式历史回测 | {label}')
    print(f'{"="*60}')
    print(f'基准日: {base_date}')
    
    # 跟踪期3年
    base_dt = datetime.strptime(base_date, '%Y-%m-%d')
    end_date = (base_dt + timedelta(days=365*3)).strftime('%Y-%m-%d')
    print(f'跟踪期: {base_date} ~ {end_date}')
    
    # 1. 加载财务数据
    print(f'\n📥 加载财务数据...')
    stocks_data, stocks_info, pe_data = load_fin_data(base_date)
    print(f'   有财务数据的股票: {len(stocks_data)}只')
    
    # 2. 筛选长持种子
    print(f'\n🔍 筛选长持种子...')
    screened = screen(base_date, stocks_data, stocks_info, pe_data)
    print(f'   符合营收+利润加速+ROE>15%+PE分位<50%: {len(screened)}只')
    
    if not screened:
        print(f'\n❌ 无符合条件标的')
        return None
    
    # 3. 获取历史股价并检查市值
    print(f'\n📈 获取历史股价（按只分批）...')
    codes = [s['code'] for s in screened]
    stocks_with_prices = []
    for i, code in enumerate(codes):
        sinfo = stocks_info.get(code, {})
        ts = sinfo.get('total_shares_real', 0) or 0
        
        prices = fetch_klines_hist(code, base_date, end_date)
        if not prices:
            continue
        
        sorted_dates = sorted(prices.keys())
        start_price = None
        for d in sorted_dates:
            if d >= base_date:
                start_price = prices[d]
                break
        
        if not start_price or start_price <= 0:
            continue
        
        mcap = ts * start_price / 1e8
        if mcap < 30 or mcap > 200:
            continue
        
        stocks_with_prices.append({
            'code': code, 'name': sinfo.get('name',''), 'sector': sinfo.get('sector',''),
            'start_price': start_price, 'mcap': round(mcap, 1), 'prices': prices, 'ts': ts,
        })
        if (i+1) % 20 == 0:
            print(f'   已处理 {i+1}/{len(codes)} 只...')
    
    print(f'   通过市值+股价检查: {len(stocks_with_prices)}只')
    
    if not stocks_with_prices:
        print(f'\n❌ 无通过市值筛选的标的')
        return None
    
    # 4. 计算表现
    print(f'\n📊 计算后续表现...')
    perf = calc_performance(stocks_with_prices, end_date)
    
    if not perf:
        print(f'\n❌ 无有效表现数据')
        return None
    
    # 5. 统计
    perf.sort(key=lambda x: x['total_return'], reverse=True)
    
    doubled = [p for p in perf if p['doubled']]
    avg_return = sum(p['total_return'] for p in perf) / len(perf)
    avg_max_dd = sum(p['max_drawdown'] for p in perf) / len(perf)
    max_return = max(p['total_return'] for p in perf)
    min_return = min(p['total_return'] for p in perf)
    
    # 组合净值（等权）
    combo_value = 0
    for p in perf:
        combo_value += 1 + p['total_return'] / 100
    combo_return = (combo_value / len(perf) - 1) * 100
    
    # 组合最大回撤
    combo_peak = 1
    combo_max_dd = 0
    combo_nav = [1.0]
    for i in range(len(sorted(stocks_with_prices[0]['prices'].keys()))):
        pass  # 简化
    
    print(f'\n{"="*60}')
    print(f'📊 回测结果 | {label}')
    print(f'{"="*60}')
    print(f'   筛选出符合条件标的: {len(perf)}只')
    print(f'   (从{screened}只营收+利润加速中，市值30-200亿筛选后)')
    print()
    print(f'   🏆 翻倍股占比: {len(doubled)}/{len(perf)} ({len(doubled)/len(perf)*100:.1f}%)')
    print(f'   📈 平均涨幅: {avg_return:.1f}%')
    print(f'   📈 最大涨幅: {max_return:.1f}%')
    print(f'   📉 最小涨幅: {min_return:.1f}%')
    print(f'   📉 平均最大回撤: {avg_max_dd:.1f}%')
    print(f'   📊 组合累计收益（等权）: {combo_return:.1f}%')
    print()
    print(f'   【标的名单及后续涨幅】')
    print(f'   {"代码":8s} {"名称":10s} {"行业":12s} {"起始价":8s} {"涨幅":8s} {"最大回撤":8s} {"翻倍?":6s}')
    print(f'   {"-"*60}')
    for p in perf[:30]:
        print(f'   {p["code"]:8s} {p["name"]:10s} {p["sector"][:12]:12s} {p["start_price"]:>8.2f} {p["total_return"]:>+7.1f}% {p["max_drawdown"]:>7.1f}% {"✅" if p["doubled"] else "❌":6s}')
    
    return {
        'base_date': base_date,
        'n_total': len(perf),
        'n_doubled': len(doubled),
        'avg_return': avg_return,
        'max_return': max_return,
        'min_return': min_return,
        'avg_max_dd': avg_max_dd,
        'combo_return': combo_return,
        'label': label,
    }

if __name__ == '__main__':
    # 回测1: 2019-01-01
    r1 = run_backtest('2019-01-01', '2019-2021 牛市初期')
    
    # 回测2: 2016-01-01  
    r2 = run_backtest('2016-01-01', '2016-2018 震荡市')
    
    # 对比
    if r1 and r2:
        print(f'\n\n{"="*60}')
        print(f'📊 两个回测时间点对比')
        print(f'{"="*60}')
        for r in [r1, r2]:
            print(f'\n{r["label"]}:')
            print(f'   候选标的: {r["n_total"]}只 | 翻倍: {r["n_doubled"]}/{r["n_total"]} ({r["n_doubled"]/r["n_total"]*100:.1f}%)')
            print(f'   平均涨幅: {r["avg_return"]:.1f}% | 等权组合: {r["combo_return"]:.1f}%')
    elif r1:
        print(f'\n2019年回测完成，2016年数据不足')
    elif r2:
        print(f'\n2016年回测完成，2019年数据不足')
