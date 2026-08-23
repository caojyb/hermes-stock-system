#!/usr/bin/env python3
"""
候选池翻倍潜力诊断 + 赛道补丁
"""
import sqlite3, json, os, sys
from datetime import date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SIM_DB = str(get_active_sim_db())

# 热门赛道列表（2026年7月更新）
HOT_TRACKS = {
    'AI算力/光模块': ['300308', '300502', '300394', '300620', '688498', '002281'],
    '低空经济': ['002085', '000099', '688631', '600990', '688568', '300975'],
    '人形机器人': ['688017', '603728', '002896', '601689', '300124', '688160'],
    '半导体/存储': ['688256', '688525', '688981', '002371', '603986', '600703'],
    'PCB/服务器': ['300476', '002463', '002916', '603228', '300394', '603005'],
    '化工涨价': ['300641', '002455', '601216', '600352', '601208', '000830'],
    '铜缆连接器': ['300563', '002130', '300252', '300570', '002475', '603005'],
    'AI应用': ['300624', '002230', '688111', '300033', '688568', '300418'],
}

# 赛道代表股票代码 → 赛道映射（用于批量匹配）
TRACK_CODE_MAP = {}
for track, codes in HOT_TRACKS.items():
    for c in codes:
        TRACK_CODE_MAP[c] = track

def load_candidate_pool():
    """加载当前候选池（统一从 double_up_scores 表读取）"""
    return pool_loader.load_pool()

def check_track_for_code(code, cur):
    """检查股票是否属于热门赛道"""
    # 精确匹配
    if code in TRACK_CODE_MAP:
        return TRACK_CODE_MAP[code], '高'
    
    # 模糊匹配：通过股票名称和行业
    cur.execute('SELECT name, sector FROM stocks WHERE code=?', (code,))
    r = cur.fetchone()
    if not r:
        return '', '无'
    
    name, sector = r[0] if r[0] else '', r[1] if r[1] else ''
    name_lower = name.lower()
    sector_lower = sector.lower()
    
    # 关键词匹配
    track_keywords = {
        'AI算力/光模块': ['光模块', '光通信', '光器件', '算力', 'AI芯片', '数据中心'],
        '低空经济': ['低空', 'eVTOL', '无人机', '飞行器', '通航'],
        '人形机器人': ['机器人', '减速器', '伺服', '灵巧手', '关节'],
        '半导体/存储': ['半导体', '芯片', '存储', '集成电路', '封测', '晶圆'],
        'PCB/服务器': ['PCB', '服务器', '印制电路', '覆铜板', '算力'],
        '化工涨价': ['化工', '化学', 'TMA', 'MDI', '染料', '氟化工'],
        '铜缆连接器': ['铜缆', '连接器', '高速线缆', 'DAC', 'AEC'],
        'AI应用': ['AI', '人工智能', '大模型', '多模态', 'AIGC', 'SaaS'],
    }
    
    for track, keywords in track_keywords.items():
        for kw in keywords:
            if kw in name or kw in sector:
                return track, '中'
    
    return '', '无'

def run():
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    today = date.today().isoformat()
    
    # ═══ 第一部分：候选池赛道诊断 ═══
    print(f'{"="*60}')
    print(f'📊 候选池翻倍潜力诊断 | {today}')
    print(f'{"="*60}')
    
    pool = load_candidate_pool()
    if not pool:
        # 从数据库扫描
        print('⚠️ 无候选池文件，从数据库获取...')
        cur.execute('''
            SELECT f1.code, s.name, s.sector
            FROM financial_data f1
            JOIN stocks s ON f1.code = s.code
            WHERE f1.report_date = (SELECT MAX(report_date) FROM financial_data)
              AND f1.revenue_growth > 30
              AND f1.profit_growth > 0
              AND (f1.debt_ratio IS NULL OR f1.debt_ratio < 65)
              AND s.total_shares_real IS NOT NULL
            GROUP BY f1.code
            LIMIT 30
        ''')
        pool = [{'code': r['code'], 'name': r['name'], 'sector': r['sector']} for r in cur.fetchall()]
    
    print(f'\n候选池共 {len(pool)} 只股票')
    print(f'\n{"代码":8s} {"名称":12s} {"行业":16s} {"赛道":20s} {"匹配度":6s} {"翻倍基因":6s}')
    print(f'{"-"*70}')
    
    track_high = 0
    track_mid = 0
    track_low = 0
    track_none = 0
    
    for s in pool:
        code = s['code']
        name = s.get('name', '')
        sector = s.get('sector', '')
        
        track, match_level = check_track_for_code(code, cur)
        
        if match_level == '高': track_high += 1
        elif match_level == '中': track_mid += 1
        elif match_level == '低': track_low += 1
        else: track_none += 1
        
        gene = '是' if match_level in ('高', '中') else '否'
        print(f'{code:8s} {name[:12]:12s} {sector[:16]:16s} {track[:20]:20s} {match_level:6s} {gene:6s}')
    
    print(f'\n{"─"*60}')
    print(f'赛道匹配度分布: 高={track_high} 中={track_mid} 低={track_low} 无={track_none}')
    print(f'{":"*60}')
    
    if track_none >= 15:
        print(f'\n🔴 结果C：候选池严重偏离翻倍股赛道（{track_none}只无赛道匹配）')
        print(f'   需要新增"主题驱动"选股模块')
    elif track_high + track_mid < 5:
        print(f'\n🟡 结果B：候选池赛道匹配极少（仅{track_high+track_mid}只匹配）')
        print(f'   需要增加"赛道优先"模式')
    else:
        print(f'\n🟢 结果A：候选池已有赛道匹配的票')
    
    # ═══ 第二部分：2023-2026翻倍股特征分析 ═══
    print(f'\n\n{"="*60}')
    print(f'📈 2023-2026翻倍股特征分析')
    print(f'{"="*60}')
    
    # 找出翻倍股 - 使用正确的首尾价格
    print('\n扫描2023年至今翻倍股...')
    cur.execute('''
        SELECT code, MIN(date) as first_date, 
               MAX(CASE WHEN rn = 1 THEN close END) as first_close,
               MAX(CASE WHEN rn_desc = 1 THEN close END) as last_close
        FROM (
            SELECT code, date, close,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY date) as rn,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn_desc
            FROM klines
            WHERE date >= "2023-01-01" AND date <= "2026-07-25"
        )
        GROUP BY code
        HAVING COUNT(*) > 200
          AND first_close IS NOT NULL AND last_close IS NOT NULL
    ''')
    stocks_list = [{
        'code': r[0],
        'first_date': r[1],
        'first_price': r[2],
        'last_price': r[3],
        'return': (r[3] - r[2]) / r[2] * 100 if r[2] > 0 else 0
    } for r in cur.fetchall()]
    
    doubled = [s for s in stocks_list if s['return'] >= 100]
    doubled.sort(key=lambda x: x['return'], reverse=True)
    print(f'有完整数据的股票: {len(stocks_list)}只')
    print(f'翻倍股（涨幅>100%）: {len(doubled)}只')
    
    # 分析翻倍股的行业分布
    sector_counts = defaultdict(int)
    track_counts = defaultdict(int)
    for s in doubled[:100]:
        cur.execute('SELECT name, sector FROM stocks WHERE code=?', (s['code'],))
        ri = cur.fetchone()
        if ri:
            sector = ri[1] or '未知'
            sector_counts[sector] += 1
            # 检查赛道匹配
            t, _ = check_track_for_code(s['code'], cur)
            if t:
                track_counts[t] += 1
    
    print(f'\n翻倍股行业分布（Top 15）:')
    for sec, cnt in sorted(sector_counts.items(), key=lambda x: -x[1])[:15]:
        print(f'  {sec:20s}: {cnt}只')
    
    print(f'\n翻倍股赛道分布:')
    for tr, cnt in sorted(track_counts.items(), key=lambda x: -x[1]):
        print(f'  {tr:20s}: {cnt}只')
    
    # 翻倍股特征分析
    conn2 = sqlite3.connect(MKT_DB)
    cur2 = conn2.cursor()
    
    print(f'\n翻倍股特征摘要:')
    rev_values = []
    prof_values = []
    roe_values = []
    for s in doubled[:30]:
        code = s['code']
        cur2.execute('''
            SELECT revenue_growth, profit_growth, roe 
            FROM financial_data 
            WHERE code=? AND revenue_growth IS NOT NULL 
            ORDER BY report_date DESC LIMIT 1
        ''', (code,))
        fi = cur2.fetchone()
        if fi:
            if fi[0] is not None: rev_values.append(fi[0])
            if fi[1] is not None: prof_values.append(fi[1])
            if fi[2] is not None: roe_values.append(fi[2])
    conn2.close()
    
    if rev_values:
        print(f'  平均营收增速: {sum(rev_values)/len(rev_values):.1f}%')
    if prof_values:
        print(f'  平均利润增速: {sum(prof_values)/len(prof_values):.1f}%')
    if roe_values:
        print(f'  平均ROE: {sum(roe_values)/len(roe_values):.1f}%')
    
    # ═══ 第三部分：赛道补丁逻辑 ═══
    if track_high + track_mid < 5 or track_none >= 15:
        print(f'\n\n{"="*60}')
        print(f'🛠️ 执行赛道补丁：新增"赛道优先"模式')
        print(f'{"="*60}')
        
        # 搜索赛道相关股票
        track_stocks = []
        all_track_codes = set()
        for codes in HOT_TRACKS.values():
            all_track_codes.update(codes)
        
        for code in all_track_codes:
            # 获取财务数据
            cur.execute('SELECT name, sector, total_shares_real FROM stocks WHERE code=?', (code,))
            sinfo = cur.fetchone()
            if not sinfo: continue
            name, sector, ts = sinfo['name'], sinfo['sector'], sinfo['total_shares_real'] or 0
            
            # 获取最新营收增速
            cur.execute('''
                SELECT revenue_growth, profit_growth 
                FROM financial_data 
                WHERE code=? AND revenue_growth IS NOT NULL 
                ORDER BY report_date DESC LIMIT 1
            ''', (code,))
            fi = cur.fetchone()
            if not fi: continue
            
            rev = fi[0] or 0
            prof = fi[1] or 0
            
            # 放宽条件：营收>20%（不要求30%），市值20-200亿
            if rev < 20: continue
            
            # 市值估算
            cur.execute('SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1', (code,))
            price_row = cur.fetchone()
            if not price_row: continue
            mcap = ts * price_row[0] / 1e8
            if mcap < 20 or mcap > 200: continue
            
            track = TRACK_CODE_MAP.get(code, '')
            track_stocks.append({
                'code': code, 'name': name, 'sector': sector,
                'track': track, 'rev': round(rev, 1), 'mcap': round(mcap, 1)
            })
        
        if track_stocks:
            print(f'\n赛道优先候选池（补充候选）: {len(track_stocks)}只')
            print(f'{"代码":8s} {"名称":12s} {"赛道":20s} {"营收增速":8s} {"市值":8s}')
            print(f'{"-"*55}')
            for s in track_stocks:
                print(f'{s["code"]:8s} {s["name"][:12]:12s} {s["track"][:20]:20s} {s["rev"]:>7.1f}% {s["mcap"]:>6.1f}亿')
            
            print(f'\n📌 以上标的已标注【🆕 赛道股】，不自动买入，仅作人工关注')
        else:
            print(f'\n⚠️ 赛道股中无满足营收>20%+市值20-200亿的标的')
    
    conn.close()

if __name__ == '__main__':
    run()