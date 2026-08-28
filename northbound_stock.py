#!/usr/bin/env python3
"""
个股北向资金数据补全模块
========================
数据源: push2delay.eastmoney.com batch API (clist/get)
字段:
  f62 = 北向资金当日净买入额(元)
  f71 = 北向资金持仓市值(元)
  f184 = 北向持股占流通股比(%)
  f185 = 北向持股占流通股比变化(%)

集成到每日15:00扫描任务中
"""
import os, sys, json, sqlite3, requests
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
NORTH_CACHE = os.path.join(os.path.dirname(__file__), 'north_cache.json')

HEADERS = {'User-Agent': 'Mozilla/5.0'}

def fetch_all_northbound():
    """
    批量获取全市场个股北向资金数据
    返回: {code: {net_buy, hold_value, hold_pct, hold_pct_chg}}
    """
    url = 'http://push2delay.eastmoney.com/api/qt/clist/get'
    result = {}
    
    failed_pages = []
    for page in range(1, 60):  # 最多60页 x 100 = 6000只
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f14,f62,f71,f184,f185'
        }
        # 单页失败重试：最多3次尝试，避免瞬时网络/限流导致整页数据丢失
        got = False
        for attempt in range(1, 4):
            try:
                r = requests.get(url, params=params, timeout=10, headers=HEADERS)
                payload = r.json()
                # 响应为 null / data 为 null → 已无更多数据，提前退出（避免空页报错）
                if not payload or not payload.get('data'):
                    got = True
                    break
                data = payload['data']
                items = data.get('diff', [])
                if not items:
                    got = True
                    break
                for item in items:
                    code = item.get('f12', '')
                    net_buy = item.get('f62', 0)
                    hold_value = item.get('f71', 0)
                    hold_pct = item.get('f184', 0)
                    pct_chg = item.get('f185', 0)

                    def to_num(v, default=0):
                        if v is None:
                            return default
                        if isinstance(v, (int, float)):
                            return v
                        try:
                            return float(str(v).replace(',', ''))
                        except Exception:
                            return default

                    net_buy = to_num(net_buy, 0)
                    hold_value = to_num(hold_value, 0)
                    hold_pct = to_num(hold_pct, 0)
                    pct_chg = to_num(pct_chg, 0)

                    # 过滤掉无效数据 (f62=0且f71=0的说明无北向数据)
                    if net_buy != 0 or hold_value != 0:
                        result[code] = {
                            'net_buy': net_buy,
                            'hold_value': hold_value,
                            'hold_pct': hold_pct,
                            'pct_chg': pct_chg,
                        }
                got = True
                break
            except Exception as e:
                if attempt == 3:
                    print(f'  ⚠️ 第{page}页获取失败（重试3次仍失败）: {e}')
                    failed_pages.append(page)
                else:
                    print(f'  第{page}页第{attempt}次失败，重试中: {e}')
    # 分页失败告警（非静默）：连续失败页数过多提示接口可能异常
    if failed_pages:
        print(f'  ⚠️ 本批次 {len(failed_pages)} 页获取失败: {failed_pages}（这些页的数据缺失，可能导致北向统计不全）')
    
    return result

def update_db(north_data, pool_codes=None):
    """更新数据库中的北向资金数据"""
    conn = sqlite3.connect(MKT_DB, timeout=60)
    cur = conn.cursor()
    
    # 确保字段存在
    cur.execute("PRAGMA table_info(indicators)")
    cols = [c[1] for c in cur.fetchall()]
    
    for col in ['north_flow', 'north_hold_value', 'north_hold_pct']:
        if col not in cols:
            cur.execute(f'ALTER TABLE indicators ADD COLUMN {col} REAL')
    
    updated = 0
    target_codes = pool_codes if pool_codes else north_data.keys()
    
    for code in target_codes:
        if code in north_data:
            nd = north_data[code]
            # north_flow = 净买入额(元)
            cur.execute('UPDATE indicators SET north_flow=?, north_hold_value=?, north_hold_pct=? WHERE code=?',
                       (nd['net_buy'], nd['hold_value'], nd['hold_pct'], code))
            if cur.rowcount > 0:
                updated += 1
    
    conn.commit()
    conn.close()
    return updated

def get_pool_codes():
    """获取候选池代码列表（统一从 double_up_scores 表读取）"""
    return [s['code'] for s in pool_loader.load_pool()]

def analyze_candidates(north_data, pool_codes):
    """分析候选池北向资金状态"""
    results = []
    
    for code in pool_codes:
        nd = north_data.get(code)
        if not nd:
            results.append({
                'code': code,
                'has_data': False,
                'risk': None,
                'bonus': None,
            })
            continue
        
        net_buy = nd['net_buy']
        hold_value = nd['hold_value']
        hold_pct = nd['hold_pct']
        pct_chg = nd['pct_chg']
        
        # 风险/加分标记
        risk = None
        bonus = None
        
        # 单日大幅卖出 > 1000万
        if net_buy < -10_000_000:
            risk = '⚠️北向大幅卖出'
        
        # 检查连续减持/增持 (从缓存读取历史)
        if check_consecutive_sell(code, net_buy):
            risk = '⛔北向连续减持'
        
        if check_consecutive_buy(code, net_buy):
            bonus = '👍北向连续增持'
        
        results.append({
            'code': code,
            'has_data': True,
            'net_buy': net_buy,
            'hold_value': hold_value,
            'hold_pct': hold_pct,
            'pct_chg': pct_chg,
            'risk': risk,
            'bonus': bonus,
        })
    
    return results

def update_north_cache(code, net_buy):
    """更新北向历史缓存"""
    cache = {}
    if os.path.exists(NORTH_CACHE):
        try:
            with open(NORTH_CACHE) as f:
                cache = json.load(f)
        except:
            pass
    
    today = date.today().isoformat()
    if code not in cache:
        cache[code] = []
    
    # 添加今日记录
    cache[code].append({'date': today, 'net_buy': net_buy})
    
    # 保留最近10个交易日
    cache[code] = sorted(cache[code], key=lambda x: x['date'])[-10:]
    
    with open(NORTH_CACHE, 'w') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    return cache[code]

def check_consecutive_sell(code, net_buy):
    """检查连续3日净减持"""
    cache = {}
    if os.path.exists(NORTH_CACHE):
        try:
            with open(NORTH_CACHE) as f:
                cache = json.load(f)
        except:
            pass
    
    history = cache.get(code, [])
    # 加上今日
    today = date.today().isoformat()
    all_records = history + [{'date': today, 'net_buy': net_buy}]
    
    # 检查最近3个交易日是否连续净卖出
    recent = sorted(all_records, key=lambda x: x['date'])[-3:]
    if len(recent) < 3:
        return False
    
    return all(r['net_buy'] < 0 for r in recent)

def check_consecutive_buy(code, net_buy):
    """检查连续5日净增持"""
    cache = {}
    if os.path.exists(NORTH_CACHE):
        try:
            with open(NORTH_CACHE) as f:
                cache = json.load(f)
        except:
            pass
    
    history = cache.get(code, [])
    today = date.today().isoformat()
    all_records = history + [{'date': today, 'net_buy': net_buy}]
    
    recent = sorted(all_records, key=lambda x: x['date'])[-5:]
    if len(recent) < 5:
        return False
    
    return all(r['net_buy'] > 0 for r in recent)

def format_report(pool_analysis, pool_map):
    """格式化输出"""
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"📊 个股北向资金状态 | {date.today().isoformat()}")
    lines.append(f"{'='*55}")
    
    has_data = [r for r in pool_analysis if r['has_data']]
    no_data = [r for r in pool_analysis if not r['has_data']]
    
    if has_data:
        # 按净买入排序
        sorted_data = sorted(has_data, key=lambda x: x['net_buy'])
        lines.append(f"\n📈 北向资金持仓 ({len(sorted_data)}只):")
        for r in sorted_data:
            name = pool_map.get(r['code'], r['code'])
            net = r['net_buy'] / 1e4
            hold = r['hold_value'] / 1e4
            pct = r['hold_pct']
            tag = r['risk'] or r['bonus'] or ''
            lines.append(f"   {r['code']} {name:10s} 净买{net:>8.0f}万 持仓{hold:>8.0f}万 占比{pct}% {tag}")
    
    if no_data:
        names = [pool_map.get(r['code'], r['code']) for r in no_data]
        lines.append(f"\n📌 北向无数据({len(no_data)}只): {', '.join(names)}（非港股通/无持仓）")
    
    # 风险汇总
    risks = [r for r in pool_analysis if r.get('risk')]
    bonuses = [r for r in pool_analysis if r.get('bonus')]
    
    if risks:
        lines.append(f"\n⛔ 风险标记:")
        for r in risks:
            name = pool_map.get(r['code'], r['code'])
            lines.append(f"   {r['code']} {name}: {r['risk']}")
    
    if bonuses:
        lines.append(f"\n👍 加分标记:")
        for r in bonuses:
            name = pool_map.get(r['code'], r['code'])
            lines.append(f"   {r['code']} {name}: {r['bonus']}")
    
    return '\n'.join(lines)

def run(pool_codes=None):
    """主入口"""
    print(f'📊 北向资金个股数据更新 | {date.today().isoformat()}')
    
    # 获取全市场北向数据
    north_data = fetch_all_northbound()
    print(f'   全市场有北向数据: {len(north_data)} 只')
    
    # 更新数据库
    n = update_db(north_data, pool_codes)
    print(f'   更新数据库: {n} 只')
    
    # 获取候选池代码
    if pool_codes is None:
        pool_codes = get_pool_codes()
    
    if not pool_codes:
        print('   候选池为空，跳过分析')
        return
    
    pool_map = {s['code']: s['name'] for s in pool_loader.load_pool()}

    # 回退：从本地数据库补全股票名称，避免北向报告只显示代码
    try:
        db_conn = sqlite3.connect(MKT_DB, timeout=60)
        db_cur = db_conn.cursor()
        db_cur.execute('SELECT code, name FROM stocks WHERE name IS NOT NULL AND name != ""')
        for code, name in db_cur.fetchall():
            if code not in pool_map:
                pool_map[code] = name
        db_conn.close()
    except Exception:
        pass

    analysis = analyze_candidates(north_data, pool_codes)

    # 更新历史缓存
    for r in analysis:
        if r['has_data']:
            update_north_cache(r['code'], r['net_buy'])

    report = format_report(analysis, pool_map)
    print(report)
    return analysis

if __name__ == '__main__':
    run()
