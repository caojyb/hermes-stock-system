#!/usr/bin/env python3
"""
分钟级数据缓存模块
==================
数据源: push2delay.eastmoney.com trends2 接口
功能:
1. 获取候选池23只标的的日内分钟级数据（256点/日/只）
2. 缓存到本地 SQLite
3. 聚合为 5分钟 K线
4. 计算盘中信号 A（站上MA20）和 B（倍量启动）
"""
import os, sys, json, sqlite3, time, requests
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader

CACHE_DB = os.path.join(os.path.dirname(__file__), 'intraday_cache.db')
MARKET_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'

TRENDS2_URL = 'http://push2delay.eastmoney.com/api/qt/stock/trends2/get'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def init_db():
    """初始化缓存数据库"""
    conn = sqlite3.connect(CACHE_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS minute_data (
            code TEXT,
            ts TEXT,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume INTEGER,
            amount REAL,
            PRIMARY KEY (code, ts)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS kline_5min (
            code TEXT,
            ts TEXT,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume INTEGER,
            amount REAL,
            PRIMARY KEY (code, ts)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            code TEXT,
            trade_date TEXT,
            signal_type TEXT,
            triggered_at TEXT,
            details TEXT,
            PRIMARY KEY (code, trade_date, signal_type)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    return conn

def load_pool():
    """加载候选池（统一从 double_up_scores 表读取）"""
    return pool_loader.load_pool()

def get_secid(code):
    """根据代码返回 secid"""
    if code.startswith(('60', '688', '689')):
        return f'1.{code}'
    else:
        return f'0.{code}'

def fetch_minute_data(stocks):
    """
    批量获取分钟级数据
    返回: {code: [(ts, open, close, high, low, volume, amount), ...]}
    """
    results = {}
    errors = []
    
    # push2delay 不走代理，代理会拦截返回空
    no_proxy = {'http': None, 'https': None}
    
    for s in stocks:
        code = s['code'] if isinstance(s, dict) else s
        secid = get_secid(code)
        
        try:
            r = requests.get(TRENDS2_URL, params={
                'secid': secid,
                'fields1': 'f1,f2,f3',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57',
                'ndays': '1',
                'lmt': '500'
            }, timeout=10, headers=HEADERS, proxies=no_proxy)
            
            trends = r.json().get('data', {}).get('trends', [])
            if not trends:
                errors.append(f'{code}: 无数据')
                continue
            
            parsed = []
            for t in trends:
                parts = t.split(',')
                if len(parts) >= 7:
                    ts = parts[0]
                    o = float(parts[1])
                    c = float(parts[2])
                    h = float(parts[3])
                    l = float(parts[4])
                    v = int(parts[5]) if parts[5] else 0
                    amt = float(parts[6]) if parts[6] else 0
                    parsed.append((ts, o, c, h, l, v, amt))
            
            results[code] = parsed
        except Exception as e:
            errors.append(f'{code}: {e}')
    
    if errors:
        print(f'  ⚠️ 获取失败: {"; ".join(errors[:5])}')
    
    return results

def save_minute_data(conn, data):
    """保存分钟级数据到数据库"""
    cur = conn.cursor()
    saved = 0
    today = date.today().isoformat()
    
    for code, points in data.items():
        for ts, o, c, h, l, v, amt in points:
            cur.execute('''
                INSERT OR REPLACE INTO minute_data (code, ts, open, close, high, low, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (code, ts, o, c, h, l, v, amt))
            saved += 1
    
    conn.commit()
    return saved

def aggregate_5min(data):
    """
    将分钟级数据聚合为5分钟K线
    返回: {code: [(ts, open, close, high, low, volume, amount), ...]}
    """
    result = {}
    for code, points in data.items():
        # 按5分钟分组
        groups = defaultdict(list)
        for ts, o, c, h, l, v, amt in points:
            # ts格式: 2026-07-24 09:15
            try:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M')
                # 5分钟槽: 09:15->09:15, 09:20->09:20, ...
                minute_slot = (dt.minute // 5) * 5
                slot_key = dt.replace(minute=minute_slot, second=0)
                groups[slot_key].append((o, c, h, l, v, amt))
            except:
                continue
        
        klines = []
        for slot_key in sorted(groups.keys()):
            items = groups[slot_key]
            o = items[0][0]  # 第一根的开盘
            c = items[-1][1]  # 最后一根的收盘
            h = max(it[2] for it in items)
            l = min(it[3] for it in items)
            v = sum(it[4] for it in items)
            amt = sum(it[5] for it in items)
            ts_str = slot_key.strftime('%Y-%m-%d %H:%M')
            klines.append((ts_str, o, c, h, l, v, amt))
        
        result[code] = klines
    
    return result

def save_5min_kline(conn, data):
    """保存5分钟K线"""
    cur = conn.cursor()
    saved = 0
    for code, klines in data.items():
        for ts, o, c, h, l, v, amt in klines:
            cur.execute('''
                INSERT OR REPLACE INTO kline_5min (code, ts, open, close, high, low, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (code, ts, o, c, h, l, v, amt))
            saved += 1
    conn.commit()
    return saved

def get_ma20_from_daily(code):
    """从日K线数据库获取最近20日均线值"""
    try:
        mkt_conn = sqlite3.connect(MARKET_DB)
        mkt_cur = mkt_conn.cursor()
        mkt_cur.execute('''
            SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 20
        ''', (code,))
        closes = [r[0] for r in mkt_cur.fetchall()]
        mkt_conn.close()
        if len(closes) >= 20:
            return sum(closes) / len(closes)
        return None
    except:
        return None

def check_signal_a(code, klines_5min, ma20):
    """
    信号A: 站上20日均线 + 连续3根5分钟K线站上MA20
    返回: (触发, 当前连续根数)
    """
    if ma20 is None or len(klines_5min) < 3:
        return False, 0
    
    # 从最近开始检查连续站上
    consecutive = 0
    for k in reversed(klines_5min):
        if k[1] > ma20:  # close > MA20
            consecutive += 1
        else:
            break
    
    return consecutive >= 3, consecutive

def check_signal_b(code, klines_5min):
    """
    信号B: 倍量启动
    当前5分钟成交量 > 前10根5分钟均量 × 1.8
    返回: (触发, 倍率)
    """
    if len(klines_5min) < 11:
        return False, 0
    
    current_vol = klines_5min[-1][4]  # 最近一根成交量
    avg_vol = sum(k[4] for k in klines_5min[-11:-1]) / 10  # 前10根均量
    
    if avg_vol <= 0:
        return False, 0
    
    ratio = current_vol / avg_vol
    return ratio >= 1.8, round(ratio, 1)

def compute_signals(conn, kline_data):
    """计算盘中信号"""
    cur = conn.cursor()
    today = date.today().isoformat()
    signals_found = []
    
    for code, klines in kline_data.items():
        if len(klines) < 3:
            continue
        
        # 获取日K MA20
        ma20 = get_ma20_from_daily(code)
        
        # 信号A
        a_triggered, a_consecutive = check_signal_a(code, klines, ma20)
        # 信号B
        b_triggered, b_ratio = check_signal_b(code, klines)
        
        code_signals = []
        
        if a_triggered:
            code_signals.append(('A', f'连续{a_consecutive}根5分钟K线站上MA20({ma20:.2f})'))
            # 存入数据库
            cur.execute('''
                INSERT OR REPLACE INTO signals (code, trade_date, signal_type, triggered_at, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (code, today, 'A', klines[-1][0], f'连续{a_consecutive}根站上MA20'))
        
        if b_triggered:
            code_signals.append(('B', f'倍量启动({b_ratio}x)'))
            cur.execute('''
                INSERT OR REPLACE INTO signals (code, trade_date, signal_type, triggered_at, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (code, today, 'B', klines[-1][0], f'成交量倍率{b_ratio}x'))
        
        if code_signals:
            signals_found.append({
                'code': code,
                'signals': code_signals,
                'ma20': round(ma20, 2) if ma20 else None,
                'last_close': klines[-1][1],
                'a_consecutive': a_consecutive if a_triggered else 0,
                'b_ratio': b_ratio if b_triggered else 0,
            })
    
    conn.commit()
    return signals_found

def format_signals(signals, pool_map):
    """格式化信号输出"""
    if not signals:
        return '   ✅ 当前无触发信号'
    
    lines = ['   🚨 盘中信号触发:']
    for s in signals:
        name = pool_map.get(s['code'], s['code'])
        sig_str = ' + '.join(f'{sig[0]}({sig[1]})' for sig in s['signals'])
        lines.append(f'   📌 {s["code"]} {name} | {sig_str}')
        lines.append(f'      最新价{s["last_close"]:.2f} | MA20={s["ma20"]}')
        if s['a_consecutive']:
            lines.append(f'      信号A: 连续{s["a_consecutive"]}根站上MA20')
        if s['b_ratio']:
            lines.append(f'      信号B: 倍量{s["b_ratio"]}x')
    return '\n'.join(lines)

def run():
    """主入口"""
    print('📊 分钟级数据监控')
    print(f'   日期: {date.today().isoformat()}')
    
    conn = init_db()
    
    # 加载候选池
    pool = load_pool()
    if not pool:
        print('   ❌ 候选池为空')
        conn.close()
        return
    
    pool_map = {s['code']: s['name'] for s in pool}
    codes = list(pool_map.keys())
    print(f'   候选池: {len(codes)} 只')
    
    # 获取数据
    print('   📥 获取分钟级数据...')
    minute_data = fetch_minute_data(codes)
    print(f'   获取到 {len(minute_data)} 只股票数据')
    
    # 保存原始分钟数据
    n = save_minute_data(conn, minute_data)
    print(f'   缓存 {n} 条分钟数据')
    
    # 聚合5分钟K线
    kline_5min = aggregate_5min(minute_data)
    n2 = save_5min_kline(conn, kline_5min)
    print(f'   生成 {n2} 条5分钟K线')
    
    # 计算信号
    signals = compute_signals(conn, kline_5min)
    print()
    print(format_signals(signals, pool_map))
    
    conn.close()
    print()
    print(f'   ✅ 完成')

if __name__ == '__main__':
    run()
