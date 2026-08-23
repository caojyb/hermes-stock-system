#!/usr/bin/env python3
"""
数据全面性升级模块
==================
P0-1: 资金流数据 — 北向资金、主力净流入、连续3日流出标记
P0-2: 事件数据 — 限售股解禁、大股东增减持、股权质押
P1: 估值补充 — PS/PCF估值字段
P2: 行业景气度 — 手动输入接口
"""
import os, sys, sqlite3, json, requests, time
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path
from simulation_db_helper import get_active_sim_db

MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SIM_DB = str(get_active_sim_db())
SECTOR_RATING_FILE = "/home/caojy/.hermes/scripts/cron/sector_rating.json"

def ensure_tables():
    """确保所有升级表存在"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    
    # P0-1: 主力资金流向表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS main_fund_flow (
            code TEXT, date TEXT, net_amt REAL,
            PRIMARY KEY (code, date)
        )
    """)
    
    # P0-1: 北向资金持股表 — 已废弃（north_flow_data 表已于 7/30 删除）
    # 北向资金数据实际存储在 indicators.north_flow
    pass
    
    # P0-2: 限售股解禁表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lockup_release (
            code TEXT, release_date TEXT, release_shares REAL, release_type TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (code, release_date)
        )
    """)
    
    # P0-2: 大股东增减持表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS holder_change (
            code TEXT, change_date TEXT, change_shares REAL, 
            change_type TEXT, change_ratio REAL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (code, change_date)
        )
    """)
    
    # P0-2: 股权质押表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equity_pledge (
            code TEXT, pledge_ratio REAL, pledge_amount REAL,
            fetch_date TEXT DEFAULT (date('now')),
            PRIMARY KEY (code)
        )
    """)
    
    # P1: indicators表增加估值字段
    for col in ['ps_ttm', 'pcf_ttm']:
        try:
            cur.execute(f"ALTER TABLE indicators ADD COLUMN {col} REAL")
        except:
            pass
    
    conn.commit()
    conn.close()

def fetch_main_fund_flow(code):
    """从push2delay获取主力资金流向"""
    market = '1' if code.startswith(('60', '688', '689')) else '0'
    try:
        url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
        params = {'secid': f'{market}.{code}', 'fields': 'f57,f178', 'invt': 2, 'fltt': 2}
        r = requests.get(url, params=params, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json().get('data', {})
        flow_data = d.get('f178')
        if flow_data:
            if isinstance(flow_data, str):
                flow_data = json.loads(flow_data)
            if isinstance(flow_data, list):
                return flow_data
    except:
        pass
    return []

def update_fund_flow(codes):
    """更新主力资金流向数据"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    updated = 0
    
    for code in codes[:50]:  # 每次最多50只
        flows = fetch_main_fund_flow(code)
        for f in flows:
            dt = f.get('date', '')
            amt = f.get('mainNetAmt', 0)
            if dt and amt:
                cur.execute("""
                    INSERT OR REPLACE INTO main_fund_flow (code, date, net_amt)
                    VALUES (?, ?, ?)
                """, (code, dt, amt))
                updated += 1
        time.sleep(0.1)
    
    conn.commit()
    conn.close()
    return updated

def check_fund_flow_risk(code):
    """检查资金流向风险：连续3日主力净流出"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    cur.execute("""
        SELECT date, net_amt FROM main_fund_flow 
        WHERE code=? ORDER BY date DESC LIMIT 3
    """, (code,))
    rows = cur.fetchall()
    conn.close()
    
    if len(rows) < 3:
        return False, "数据不足"
    
    # 连续3日净流出
    all_negative = all(r[1] < 0 for r in rows)
    if all_negative:
        total = sum(r[1] for r in rows)
        return True, f"连续3日主力净流出，合计{total/1e8:.1f}亿"
    
    return False, "暂无风险"

def check_event_risk(code):
    """检查事件风险：限售股解禁/大股东减持/股权质押"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    risks = []
    
    # 限售股解禁（未来30天）
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    cur.execute("""
        SELECT release_date, release_shares, release_type FROM lockup_release
        WHERE code=? AND release_date BETWEEN ? AND ?
        ORDER BY release_date
    """, (code, today, future))
    for r in cur.fetchall():
        risks.append(f"限售解禁:{r[0]} {r[1]/1e4:.0f}万股")
    
    # 大股东减持
    cur.execute("""
        SELECT change_date, change_shares, change_type FROM holder_change
        WHERE code=? AND change_type='减持' AND change_date >= ?
        ORDER BY change_date DESC LIMIT 1
    """, (code, (date.today()-timedelta(days=90)).isoformat()))
    r = cur.fetchone()
    if r:
        risks.append(f"股东减持:{r[0]} {r[1]/1e4:.0f}万股")
    
    # 股权质押
    cur.execute("SELECT pledge_ratio FROM equity_pledge WHERE code=?", (code,))
    r = cur.fetchone()
    if r and r[0] and r[0] > 30:
        risks.append(f"股权质押率{r[0]:.0f}%")
    
    conn.close()
    return risks

def check_north_flow(code):
    """检查北向资金流向"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    cur.execute("SELECT north_flow FROM indicators WHERE code=?", (code,))
    r = cur.fetchone()
    conn.close()
    if r and r[0]:
        return r[0]
    return None

def load_sector_ratings():
    """加载行业景气度评分"""
    if not os.path.exists(SECTOR_RATING_FILE):
        return {}
    try:
        with open(SECTOR_RATING_FILE) as f:
            return json.load(f)
    except:
        return {}

def get_sector_rating(sector_name, ratings):
    """获取行业景气度评分"""
    if not sector_name:
        return None
    # 尝试精确匹配，再尝试模糊匹配
    if sector_name in ratings:
        return ratings[sector_name]
    for key, val in ratings.items():
        if key in sector_name or sector_name in key:
            return val
    return None

def estimate_ps_pcf(code, price):
    """估算PS和PCF（从push2delay的f183/f184等字段）"""
    market = '1' if code.startswith(('60', '688', '689')) else '0'
    try:
        url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
        params = {'secid': f'{market}.{code}', 'fields': 'f57,f183,f184,f185', 'invt': 2, 'fltt': 2}
        r = requests.get(url, params=params, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json().get('data', {})
        f183 = d.get('f183')  # 营业收入
        if f183 and price > 0:
            # 总股本 * 价格 / 营收 = 市销率
            conn = sqlite3.connect(MARKET_DB, timeout=60)
            cur = conn.cursor()
            cur.execute("SELECT total_shares_real FROM stocks WHERE code=?", (code,))
            ts = cur.fetchone()
            conn.close()
            if ts and ts[0] and ts[0] > 0:
                mcap = ts[0] * price
                ps = mcap / f183 if f183 > 0 else None
                return ps, None  # PCF无法从API获得
    except:
        pass
    return None, None

def update_valuation(codes):
    """更新估值数据"""
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    updated = 0
    
    for code in codes[:50]:
        market = '1' if code.startswith(('60', '688', '689')) else '0'
        try:
            url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
            params = {'secid': f'{market}.{code}', 'fields': 'f57,f162,f163,f164,f165,f166,f167,f183', 'invt': 2, 'fltt': 2}
            r = requests.get(url, params=params, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            d = r.json().get('data', {})
            
            # 从财务数据估算PS
            f183 = d.get('f183')  # 营业收入
            if f183:
                price = d.get('f162') or 0
                if price > 0:
                    stock_cur = conn.cursor()
                    stock_cur.execute("SELECT total_shares_real FROM stocks WHERE code=?", (code,))
                    ts = stock_cur.fetchone()
                    if ts and ts[0] and ts[0] > 0:
                        mcap = ts[0] * price
                        ps = mcap / f183 if f183 > 0 else None
                        if ps:
                            cur.execute("UPDATE indicators SET ps_ttm=? WHERE code=?", (ps, code))
                            updated += 1
            time.sleep(0.1)
        except:
            pass
    
    conn.commit()
    conn.close()
    return updated

def format_candidate_risk(candidate_pool):
    """为候选池股票添加资金流/事件风险标注"""
    enriched = []
    for s in candidate_pool:
        code = s['code']
        flags = []
        
        # 资金流风险
        is_risk, reason = check_fund_flow_risk(code)
        if is_risk:
            flags.append(f"⚠️{reason[:20]}")
        
        # 北向资金
        nf = check_north_flow(code)
        if nf is not None:
            try:
                nf = float(nf)
            except (TypeError, ValueError):
                nf = None
            if nf is not None and nf < 0:
                flags.append(f"北向流出{nf:.1f}")
        
        # 事件风险
        event_risks = check_event_risk(code)
        flags.extend(event_risks)
        
        # 行业景气度
        ratings = load_sector_ratings()
        sr = get_sector_rating(s.get('sector', ''), ratings)
        if sr is not None:
            label = {2:'🔥', 1:'👍', 0:'➡️', -1:'👎', -2:'❌'}.get(sr, '➡️')
            flags.append(f"景气{label}{sr}")
        
        s['risk_flags'] = flags
        s['has_risk'] = len([f for f in flags if '减持' in f or '解禁' in f or '质押' in f or '流出' in f]) > 0
        enriched.append(s)
    
    return enriched

def run_all(candidate_pool=None):
    """运行所有升级模块"""
    print("📊 数据全面性升级...")
    
    # 确保表结构
    ensure_tables()
    print("  ✅ 表结构已就绪")
    
    # 获取候选池
    if candidate_pool is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pool_loader import load_pool
        candidate_pool = load_pool()
    
    if candidate_pool:
        codes = [s['code'] for s in candidate_pool if s['code'].startswith(('60','00','30'))]
        
        # P0-1: 更新资金流
        print(f"  🔄 更新主力资金流向 ({len(codes)}只)...")
        n = update_fund_flow(codes)
        print(f"    已更新{n}条记录")
        
        # P1: 更新估值
        print(f"  🔄 更新估值数据 ({len(codes)}只)...")
        n = update_valuation(codes)
        print(f"    已更新{n}条PS估值")
        
        # P0-1/P0-2: 标注风险
        enriched = format_candidate_risk(candidate_pool)
        risk_count = len([s for s in enriched if s.get('has_risk')])
        print(f"  ⚠️ 发现{risk_count}只有风险标记")
        for s in enriched:
            if s.get('risk_flags'):
                print(f"    {s['code']} {s['name']}: {' | '.join(s['risk_flags'])}")
    
    print("  ✅ 数据升级完成")

if __name__ == '__main__':
    run_all()