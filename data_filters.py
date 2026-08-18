#!/usr/bin/env python3
"""
新增四个过滤器模块
1. 隔夜跳空过滤
2. 流动性门槛
3. 大盘择时开关
4. 业绩预告监控
"""
import os, sys, sqlite3, json, requests, time
from datetime import date, datetime, timedelta
from collections import defaultdict

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))
TOTAL_CAPITAL = 1_000_000

# ═══ 1. 隔夜跳空过滤 ═══
def check_gap_up(code, prev_close, today_open=None):
    """
    检查隔夜跳空
    返回: (is_gap, gap_pct, message)
    """
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()
    
    # 获取最近2根K线（昨日收盘，今日开盘）
    cur.execute("SELECT date, close, open FROM klines WHERE code=? ORDER BY date DESC LIMIT 2", (code,))
    klines = cur.fetchall()
    conn.close()
    
    if len(klines) < 2:
        return False, 0, "数据不足"
    
    today_close = klines[0][1]  # 今天收盘价
    yesterday_close = klines[1][1]  # 昨天收盘价
    today_open = today_open or klines[0][2]  # 今天开盘价
    
    if yesterday_close <= 0:
        return False, 0, "昨日收盘价无效"
    
    gap_pct = (today_open - yesterday_close) / yesterday_close * 100
    
    if gap_pct > 3:
        # 计算MA20作为回调价
        cur2 = sqlite3.connect(MARKET_DB).cursor()
        cur2.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 20", (code,))
        closes = [r[0] for r in cur2.fetchall()]
        cur2.connection.close()
        if len(closes) >= 20:
            ma20 = sum(closes) / 20
            return True, round(gap_pct, 2), f"高开{gap_pct:.1f}%>3%触发暂缓，回调参考价{ma20:.2f}(MA20)"
        return True, round(gap_pct, 2), f"高开{gap_pct:.1f}%>3%触发暂缓"
    
    return False, round(gap_pct, 2), f"开盘{gap_pct:.1f}%，正常"

# ═══ 2. 流动性门槛 ═══
def check_liquidity(code, min_daily_amt=30000000):
    """
    检查近20日日均成交额 > min_daily_amt
    返回: (pass, avg_amount, message)
    """
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()
    
    # 从K线取最近20日成交量×收盘价 × 2（近似成交额）
    # 更准确：成交额 = 成交额字段（f48）
    # 但K线表没有成交额字段，用 volume * close * 2 估算（双向）
    # 实际上最好用push2delay的f48字段
    cur.execute("""
        SELECT date, close, volume FROM klines 
        WHERE code=? ORDER BY date DESC LIMIT 20
    """, (code,))
    klines = cur.fetchall()
    conn.close()
    
    if len(klines) < 20:
        return False, 0, f"K线不足20天({len(klines)})"
    
    # 估算每日成交额 = volume * close * 多空系数(约2)
    daily_amts = []
    for k in klines:
        est_amt = k[1] * k[2] * 2  # 估算成交额
        daily_amts.append(est_amt)
    
    avg_amt = sum(daily_amts) / len(daily_amts)
    
    if avg_amt >= min_daily_amt:
        return True, avg_amt, f"日均成交额{avg_amt/1e4:.0f}万，达标"
    else:
        return False, avg_amt, f"日均成交额{avg_amt/1e4:.0f}万 < 3000万，不达标"

# 更准确的流动性检查：从push2delay获取实际成交额
def check_liquidity_accurate(code, min_daily_amt=30000000):
    """从push2delay获取真实成交额"""
    market = '1' if code.startswith(('60', '688', '689')) else '0'
    try:
        url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
        params = {'secid': f'{market}.{code}', 'fields': 'f57,f48', 'invt': 2, 'fltt': 2}
        r = requests.get(url, params=params, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json().get('data', {})
        f48 = d.get('f48')  # 今日成交额
        if f48 and f48 > 0:
            return True, f48, f"今日成交额{f48/1e4:.0f}万"
    except:
        pass
    return check_liquidity(code, min_daily_amt)  # 降级到估算

# ═══ 3. 大盘择时开关 ═══
def check_market_timing():
    """
    检查沪深300是否在20日均线之上
    返回: (safe_to_buy, index_close, ma20, message)
    """
    # 沪深300 = 000300.SH / 399300.SZ
    # 用push2delay获取000300指数数据
    try:
        url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
        params = {'secid': '1.000300', 'fields': 'f57,f43,f44,f45,f46,f47,f48,f169,f170', 'invt': 2, 'fltt': 2}
        r = requests.get(url, params=params, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json().get('data', {})
        close = d.get('f43', 0)  # 最新价
        if close:
            # 从数据库获取沪深300的K线计算MA20
            conn = sqlite3.connect(MARKET_DB)
            cur = conn.cursor()
            cur.execute("SELECT close FROM klines WHERE code='000300' ORDER BY date DESC LIMIT 20")
            klines = [r[0] for r in cur.fetchall()]
            conn.close()
            if len(klines) >= 20:
                ma20 = sum(klines) / 20
                if close < ma20:
                    return False, close, ma20, f"沪深300{close:.0f} < MA20{ma20:.0f}，大盘弱势，暂停买入"
                else:
                    return True, close, ma20, f"沪深300{close:.0f} > MA20{ma20:.0f}，大盘正常"
    except:
        pass
    
    # 降级：从数据库获取
    try:
        conn = sqlite3.connect(MARKET_DB)
        cur = conn.cursor()
        cur.execute("SELECT close FROM klines WHERE code='000300' ORDER BY date DESC LIMIT 20")
        klines = [r[0] for r in cur.fetchall()]
        conn.close()
        if len(klines) >= 20:
            close = klines[0]
            ma20 = sum(klines) / 20
            if close < ma20:
                return False, close, ma20, f"沪深300{close:.0f} < MA20{ma20:.0f}，大盘弱势，暂停买入"
            else:
                return True, close, ma20, f"沪深300{close:.0f} > MA20{ma20:.0f}，大盘正常"
    except:
        pass
    
    # Phase 1 fail-safe: 无法获取沪深300数据时，为安全暂停买入（不再默认放行）
    return False, 0, 0, "无法获取沪深300数据，为安全暂停买入（fail-safe）"

# ═══ 4. 业绩预告监控 ═══
# 业绩预告修正数据从东财数据中心获取
PERFORMANCE_LOG = "/home/caojy/.hermes/scripts/cron/performance_alerts.json"

def fetch_performance_warnings():
    """扫描业绩预告修正/快报"""
    warnings = []
    try:
        # 东财业绩预告修正列表
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            'reportName': 'RPT_PUBLIC_OP_YJYC',
            'columns': 'SECUCODE,SECURITY_NAME_ABBR,NOTICE_DATE,CHANGE_TYPE,FORECAST_CONTENT',
            'pageSize': 50,
            'sortColumns': 'NOTICE_DATE',
            'sortTypes': -1,
            'source': 'HSF10',
            'client': 'WEB'
        }
        r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        if data.get('success') and data.get('result'):
            for item in data['result']:
                code = item.get('SECUCODE', '').replace('.SH', '').replace('.SZ', '')
                name = item.get('SECURITY_NAME_ABBR', '')
                notice_date = item.get('NOTICE_DATE', '')
                change_type = item.get('CHANGE_TYPE', '')
                content = item.get('FORECAST_CONTENT', '')
                
                # 只关注向下修正
                if '修正' in change_type and ('向下' in change_type or '减少' in change_type or '亏损' in change_type or '下降' in change_type):
                    warnings.append({
                        'code': code, 'name': name, 'date': notice_date,
                        'type': change_type, 'content': content[:100],
                        'direction': 'down'
                    })
                # 亏损/预减
                elif '首亏' in change_type or '预减' in change_type or '续亏' in change_type:
                    warnings.append({
                        'code': code, 'name': name, 'date': notice_date,
                        'type': change_type, 'content': content[:100],
                        'direction': 'down'
                    })
    except Exception as e:
        pass
    
    return warnings

def check_holdings_against_warnings(holdings, candidates):
    """检查持仓/候选池中是否有业绩向下修正的股票"""
    warnings = fetch_performance_warnings()
    if not warnings:
        return []
    
    alerts = []
    warning_codes = {w['code'] for w in warnings}
    
    for h in holdings:
        if h['code'] in warning_codes:
            w = [x for x in warnings if x['code'] == h['code']][0]
            alerts.append({
                'type': '持仓预警',
                'code': h['code'], 'name': h['name'],
                'warning': w['type'], 'content': w['content'],
                'action': '立即清仓'
            })
    
    for c in candidates:
        code = c['code'] if isinstance(c, dict) else c
        name = c.get('name', '') if isinstance(c, dict) else ''
        if code in warning_codes:
            w = [x for x in warnings if x['code'] == code][0]
            alerts.append({
                'type': '候选池预警',
                'code': code, 'name': name,
                'warning': w['type'], 'content': w['content'],
                'action': '暂停推荐'
            })
    
    return alerts

def save_performance_log(alerts):
    """保存业绩预警日志"""
    if not alerts:
        return
    history = []
    if os.path.exists(PERFORMANCE_LOG):
        try:
            with open(PERFORMANCE_LOG) as f:
                history = json.load(f)
        except:
            pass
    history.append({
        'date': date.today().isoformat(),
        'alerts': alerts
    })
    history = history[-30:]  # 保留最近30天
    with open(PERFORMANCE_LOG, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ═══ 统一入口 ═══
def run_all_filters(candidates, holdings=None, today_open_prices=None):
    """
    运行所有四个过滤器
    返回: (filtered_candidates, alerts, market_status)
    """
    if holdings is None:
        holdings = []
    if today_open_prices is None:
        today_open_prices = {}
    
    results = []
    alerts = []
    
    # 大盘择时
    market_safe, idx_close, idx_ma20, market_msg = check_market_timing()
    print(f"\n📊 大盘择时: {market_msg}")
    
    if not market_safe:
        alerts.append({'type': '大盘择时', 'message': market_msg})
    
    # 对每只候选股检查
    for s in candidates:
        code = s['code']
        flags = []
        
        # 隔夜跳空检查
        prev_close = s.get('prev_close', 0)
        today_open = today_open_prices.get(code)
        is_gap, gap_pct, gap_msg = check_gap_up(code, prev_close, today_open)
        if is_gap:
            flags.append(f'跳空{gap_pct}%')
            if '回调参考' in gap_msg:
                s['ma20_callback'] = float(gap_msg.split('回调参考价')[1].split('(')[0])
        
        # 流动性检查
        liq_pass, liq_amt, liq_msg = check_liquidity_accurate(code)
        if not liq_pass:
            flags.append(f'流动性不足({liq_amt/1e4:.0f}万)')
        
        # 大盘择时标记
        if not market_safe:
            flags.append('大盘弱势，暂停买入')
        
        s['filters'] = flags
        s['filter_blocked'] = len(flags) > 0 or not market_safe
        results.append(s)
    
    # 业绩预告监控
    perf_alerts = check_holdings_against_warnings(holdings, candidates)
    alerts.extend(perf_alerts)
    if perf_alerts:
        save_performance_log(perf_alerts)
        for a in perf_alerts:
            print(f"  🚨 {a['type']}: {a['name']}({a['code']}) {a['warning']}")
    
    return results, alerts, market_safe

# ═══ 测试入口 ═══
if __name__ == '__main__':
    # 加载候选池（统一从 double_up_scores 表读取）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pool_loader import load_pool
    candidates = load_pool()
    
    print(f"📊 运行四个过滤器 ({len(candidates)}只候选)…")
    results, alerts, market_safe = run_all_filters(candidates)
    
    blocked = [s for s in results if s.get('filter_blocked')]
    print(f"\n📋 过滤结果:")
    print(f"  通过: {len(results) - len(blocked)} 只")
    print(f"  暂缓: {len(blocked)} 只")
    for s in blocked:
        print(f"  ⏸️ {s['code']} {s.get('name','')}: {', '.join(s['filters'])}")
    for a in alerts:
        print(f"  🔔 {a.get('type','')}: {a.get('message','')}")