#!/usr/bin/env python3
"""
龙虎榜数据接入模块
=================
数据源: datacenter.eastmoney.com RPT_DAILYBILLBOARD_DETAILSNEW
功能:
1. 每日收盘后拉取当日龙虎榜数据
2. 与候选池交叉比对
3. 标记机构/游资买入
4. 缓存到本地SQLite
5. 集成到周报
"""
import os, sys, json, sqlite3, requests
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader

CACHE_DB = os.path.join(os.path.dirname(__file__), 'lhb_cache.db')

LHB_API = 'https://datacenter.eastmoney.com/securities/api/data/v1/get'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ── 配置 ──
INSTITUTION_KEYWORDS = ['机构买入', '机构卖出']  # 机构关键字
RETAIL_KEYWORDS = ['普通席位买入', '买一主买', '主力做T']  # 游资/散户关键字

def init_db():
    conn = sqlite3.connect(CACHE_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS lhb_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT,
            trade_date TEXT,
            close_price REAL,
            change_rate REAL,
            net_amt REAL,
            buy_amt REAL,
            sell_amt REAL,
            deal_amt REAL,
            accum_amt REAL,
            turnover_rate REAL,
            free_mcap REAL,
            explain TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(code, trade_date)
        )
    ''')
    conn.commit()
    return conn

def load_pool():
    """加载候选池（统一从 double_up_scores 表读取）"""
    return pool_loader.load_pool()

def fetch_lhb(trade_date=None):
    """
    获取龙虎榜数据
    返回: [{'code','name','close','change','net_amt','buy_amt','sell_amt','explain',...}]
    """
    if trade_date is None:
        trade_date = date.today().isoformat()
    
    params = {
        'reportName': 'RPT_DAILYBILLBOARD_DETAILSNEW',
        'columns': 'SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,BILLBOARD_DEAL_AMT,ACCUM_AMOUNT,TURNOVERRATE,FREE_MARKET_CAP',
        'filter': f"(TRADE_DATE='{trade_date}')",
        'pageNumber': 1,
        'pageSize': 100,
        'sortTypes': -1,
        'sortColumns': 'BILLBOARD_NET_AMT',
    }
    
    try:
        r = requests.get(LHB_API, params=params, timeout=15, headers=HEADERS)
        d = r.json()
        if not d.get('success') or not d.get('result'):
            return [], d.get('message', 'Unknown error')
        
        rows = d['result']['data']
        results = []
        for row in rows:
            code = row.get('SECURITY_CODE', '')
            secucode = row.get('SECUCODE', '')
            # 取6位代码
            if '.' in secucode:
                code = secucode.split('.')[0]
            
            explain = row.get('EXPLAIN', '')
            
            results.append({
                'code': code,
                'secucode': secucode,
                'name': row.get('SECURITY_NAME_ABBR', ''),
                'trade_date': trade_date,
                'close': row.get('CLOSE_PRICE', 0),
                'change': row.get('CHANGE_RATE', 0),
                'net_amt': row.get('BILLBOARD_NET_AMT', 0) or 0,
                'buy_amt': row.get('BILLBOARD_BUY_AMT', 0) or 0,
                'sell_amt': row.get('BILLBOARD_SELL_AMT', 0) or 0,
                'deal_amt': row.get('BILLBOARD_DEAL_AMT', 0) or 0,
                'accum_amt': row.get('ACCUM_AMOUNT', 0) or 0,
                'turnover_rate': row.get('TURNOVERRATE', 0) or 0,
                'free_mcap': row.get('FREE_MARKET_CAP', 0) or 0,
                'explain': explain or '',
                # 判断机构/游资
                'is_institution': 1 if any(kw in (explain or '') for kw in ['机构买入', '机构卖出']) else 0,
                'is_retail': 1 if any(kw in (explain or '') for kw in RETAIL_KEYWORDS) else 0,
            })
        
        return results, None
    
    except Exception as e:
        return [], str(e)

def save_lhb(conn, data):
    """保存龙虎榜数据"""
    cur = conn.cursor()
    saved = 0
    for item in data:
        try:
            cur.execute('''
                INSERT OR REPLACE INTO lhb_data 
                (code, name, trade_date, close_price, change_rate, net_amt, buy_amt, sell_amt, 
                 deal_amt, accum_amt, turnover_rate, free_mcap, explain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item['code'], item['name'], item['trade_date'],
                item['close'], item['change'], item['net_amt'],
                item['buy_amt'], item['sell_amt'], item['deal_amt'],
                item['accum_amt'], item['turnover_rate'], item['free_mcap'],
                item['explain']
            ))
            saved += 1
        except Exception as e:
            print(f"[WARN] lhb_monitor 保存龙虎榜数据失败: {e}")
    conn.commit()
    return saved

def cross_check(pool, lhb_data):
    """与候选池交叉比对"""
    pool_codes = set()
    for s in pool:
        code = s['code'] if isinstance(s, dict) else s
        pool_codes.add(code)
    
    matches = []
    for item in lhb_data:
        if item['code'] in pool_codes:
            # 找到候选池中的名称
            pool_name = ''
            for s in pool:
                if s['code'] == item['code']:
                    pool_name = s['name']
                    break
            
            matches.append({
                'pool_code': item['code'],
                'pool_name': pool_name,
                'lhb_code': item['code'],
                'lhb_name': item['name'],
                'net_amt': item['net_amt'],
                'buy_amt': item['buy_amt'],
                'sell_amt': item['sell_amt'],
                'is_institution': item['is_institution'],
                'is_retail': item['is_retail'],
                'explain': item['explain'],
            })
    
    return matches

def format_report(lhb_all, matches, trade_date):
    """格式化输出报告"""
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"📊 龙虎榜数据 | {trade_date}")
    lines.append(f"{'='*55}")
    
    # 概览
    lines.append(f"\n   总上榜: {len(lhb_all)} 只")
    
    # 机构买入Top 5
    inst_buy = [x for x in lhb_all if x['is_institution'] and x['net_amt'] > 0]
    inst_sell = [x for x in lhb_all if x['is_institution'] and x['net_amt'] < 0]
    lines.append(f"\n🏛️ 机构净买入Top 5:")
    for item in sorted(inst_buy, key=lambda x: -x['net_amt'])[:5]:
        net = item['net_amt'] / 1e8
        lines.append(f"   +{item['name']}({item['code']}) 净买入{net:.2f}亿 {item['explain']}")
    
    lines.append(f"\n⛔ 机构净卖出Top 5:")
    for item in sorted(inst_sell, key=lambda x: x['net_amt'])[:5]:
        net = abs(item['net_amt']) / 1e8
        lines.append(f"   -{item['name']}({item['code']}) 净卖出{net:.2f}亿 {item['explain']}")
    
    # 候选池交叉比对
    if matches:
        lines.append(f"\n{'='*55}")
        lines.append(f"🎯 候选池龙虎榜关联 ({len(matches)}只)")
        lines.append(f"{'='*55}")
        for m in sorted(matches, key=lambda x: -abs(x['net_amt'])):
            net = m['net_amt'] / 1e4
            net_str = f"+{net:.0f}万" if net > 0 else f"{net:.0f}万"
            tag = '🏛️' if m['is_institution'] else '🎯' if m['is_retail'] else '📌'
            lines.append(f"   {tag} {m['lhb_code']} {m['pool_name']} | 净买{net_str} | {m['explain']}")
    else:
        lines.append(f"\n   📌 候选池无龙虎榜关联")
    
    return '\n'.join(lines)

def get_weekly_summary(conn, week_end=None):
    """获取周度龙虎榜汇总"""
    if week_end is None:
        week_end = date.today()
    week_start = week_end - timedelta(days=7)
    
    cur = conn.cursor()
    cur.execute('''
        SELECT code, name, COUNT(*) as cnt, SUM(net_amt) as total_net
        FROM lhb_data 
        WHERE trade_date >= ? AND trade_date <= ?
        GROUP BY code ORDER BY total_net DESC LIMIT 10
    ''', (week_start.isoformat(), week_end.isoformat()))
    
    top = cur.fetchall()
    
    lines = [f"\n📊 本周龙虎榜Top 10 ({week_start} ~ {week_end})"]
    for i, row in enumerate(top, 1):
        net = row[3] / 1e4 if row[3] else 0
        lines.append(f"   {i}. {row[0]} {row[1]} | 上榜{row[2]}次 | 净买{net:+.0f}万")
    
    return '\n'.join(lines)

def run(trade_date=None, pool=None, weekly=False):
    """主入口"""
    if trade_date is None:
        trade_date = date.today().isoformat()
    
    conn = init_db()
    
    # 加载候选池
    if pool is None:
        pool = load_pool()
    
    # 获取龙虎榜数据
    lhb_data, err = fetch_lhb(trade_date)
    if err:
        print(f'❌ 龙虎榜数据获取失败: {err}')
        conn.close()
        return
    
    print(f'📊 龙虎榜数据: {len(lhb_data)} 条')
    
    # 交叉比对（仅内存比对，不写入 cross_check 表；lhb_cache.db 统一由 daily-data-refresh 写入）
    matches = cross_check(pool, lhb_data) if pool else []
    if matches:
        print(f'  候选池关联: {len(matches)} 只（不落库）')
    
    # 输出报告
    report = format_report(lhb_data, matches, trade_date)
    print(report)
    
    if weekly:
        weekly_report = get_weekly_summary(conn)
        print(weekly_report)
    
    conn.close()
    # 记录管道状态
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_status import record_status
        record_status('stock-lhb-daily', 'ok', trade_date,
                      row_count=len(lhb_data), message=f'{len(lhb_data)} 条')
    except Exception as e:
        print(f"[WARN] lhb_monitor 记录管道状态失败: {e}")
    return {
        'total': len(lhb_data),
        'matches': matches,
        'date': trade_date
    }

def _prev_trade_date() -> str:
    """返回应抓取龙虎榜的上一交易日。
    龙虎榜当日约 17:00 才发布，15:35 cron 应抓上一已完成交易日。
    优先用 market_cache 本地 K线最新日期（=上一交易日），兜底跳周末。
    """
    try:
        con = sqlite3.connect('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
        latest = con.execute('SELECT MAX(date) FROM klines').fetchone()[0]
        con.close()
        if latest and latest < date.today().isoformat():
            return latest
    except Exception:
        pass
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:  # 跳过周六周日
        d -= timedelta(days=1)
    return d.isoformat()


if __name__ == '__main__':
    # 动态取上一交易日（旧版硬编码 2026-07-24 导致数据冻结）
    run(trade_date=_prev_trade_date(), weekly=False)
