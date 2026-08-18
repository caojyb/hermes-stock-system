#!/usr/bin/env python3
"""
赛道宽松通道 — 2026年7月版
=============================
作为现有候选池的补充，独立运行，不影响现有筛选逻辑。

通道条件：
  · 营收增速 > 20%（近2季度）
  · 市值 20-150亿
  · 换手率 > 1%
  · 回撤 20-55%
  · 所属行业在热门赛道列表中
  · 不要求ROE > 15%
  · 不要求利润 > 0%

输出：最多10只，标注【🆕 赛道宽松池】
"""
import sqlite3, json, os, re
from datetime import date, timedelta
from collections import defaultdict

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'

# 热门赛道列表（2026年7月版，主力资金流入验证）
HOT_TRACKS = [
    {
        'name': 'AI算力/光模块/CPO',
        'codes': ['300308','300502','300394','300620','688498','002281','300570','300548','688313'],
        'keywords': ['光模块','光通信','光器件','CPO','AI算力','算力芯片','数据中心','800G','1.6T']
    },
    {
        'name': '低空经济/飞行汽车',
        'codes': ['002085','000099','688631','600990','688568','300975','002023','300424'],
        'keywords': ['低空经济','eVTOL','飞行汽车','无人机','通航','空管','飞行器']
    },
    {
        'name': '人形机器人/减速器',
        'codes': ['688017','603728','002896','601689','300124','688160','002747','300660','002472'],
        'keywords': ['人形机器人','减速器','机器人关节','伺服电机','灵巧手','滚柱丝杠','空心杯']
    },
    {
        'name': '半导体/存储芯片/HBM',
        'codes': ['688256','688525','688981','002371','603986','600703','688012','688072','300661','002049'],
        'keywords': ['半导体','芯片','存储','IC设计','封测','晶圆','HBM','DRAM','NAND','高带宽内存']
    },
    {
        'name': '华为海思/先进封装/Chiplet',
        'codes': ['002156','600584','688072','300672','002185','600703','688981'],
        'keywords': ['华为海思','海思','先进封装','Chiplet','2.5D','3D封装','SiP','异构集成']
    },
    {
        'name': '服务器/PCB/铜缆连接器',
        'codes': ['300476','002463','002916','603228','300394','300563','002130','300252','002475','301205'],
        'keywords': ['服务器','PCB','印制电路','铜缆','连接器','DAC','AEC','高速背板']
    },
    {
        'name': '光刻机/半导体设备/材料',
        'codes': ['688012','002371','300604','300567','688072','300346','300054','300236'],
        'keywords': ['光刻机','光刻胶','半导体设备','刻蚀','薄膜沉积','离子注入','硅片','掩模版']
    },
    {
        'name': '毫米波/6G/卫星通信',
        'codes': ['002792','300570','300548','002151','600118','300342','688568'],
        'keywords': ['毫米波','6G','卫星通信','太赫兹','相控阵','射频','天线']
    },
    {
        'name': '工业气体/特种气体',
        'codes': ['300340','002971','300054','300236','300346','603722','688596'],
        'keywords': ['工业气体','特种气体','电子特气','氦气','高纯气体','稀有气体']
    },
    {
        'name': '玻璃基板/先进封装材料',
        'codes': ['300054','300706','300852','300964','300940','301176','301251'],
        'keywords': ['玻璃基板','封装基板','ABF载板','BT载板','IC载板','封装材料']
    },
    {
        'name': '化工涨价/新材料',
        'codes': ['300641','002455','601216','600352','601208','000830','600989','300919','002812'],
        'keywords': ['化工','化学制品','TMA','MDI','染料','氟化工','磷化工','新材料','碳纤维']
    },
    {
        'name': 'AI应用/大模型',
        'codes': ['300624','002230','688111','300033','688568','300418','300075','688787'],
        'keywords': ['AI应用','大模型','AIGC','多模态','AI智能体','SaaS','AI教育','AI医疗']
    },
    {
        'name': '智能驾驶/自动驾驶',
        'codes': ['002920','002405','601689','300496','688088','600745','002813'],
        'keywords': ['智能驾驶','自动驾驶','ADAS','智驾','激光雷达','域控制器','线控底盘']
    },
    {
        'name': '商业航天/卫星互联网',
        'codes': ['600118','002025','688568','300342','600879','000901','002151'],
        'keywords': ['商业航天','卫星','星链','航天','火箭','卫星互联网','遥感']
    },
    {
        'name': '创新药/减肥药',
        'codes': ['300760','688271','600276','300122','002317','300558','688180','688192'],
        'keywords': ['创新药','减肥药','GLP-1','生物药','抗体','ADC','双抗','CAR-T']
    },
    {
        'name': '固态电池/新能源新材料',
        'codes': ['300750','002074','300014','002709','002812','300568','688005'],
        'keywords': ['固态电池','钠离子','半固态','锂金属','复合集流体','磷酸锰铁锂']
    },
    {
        'name': '数据要素/数据安全',
        'codes': ['300624','300229','688111','300766','002230','300454','300188'],
        'keywords': ['数据要素','数据安全','数据资产','数据确权','隐私计算','数据交易']
    },
    {
        'name': '军工电子/卫星导航',
        'codes': ['600760','600893','600862','000738','600118','002013','600879','600685'],
        'keywords': ['军工电子','卫星导航','雷达','电子对抗','军工信息化','导弹','军机']
    },
    {
        'name': '信创/国产替代',
        'codes': ['688111','600536','002410','000977','300624','688568','688369','688588'],
        'keywords': ['信创','国产替代','国产操作系统','国产数据库','CPU','GPU','EDA','CAD']
    },
    {
        'name': '教育信息化/AI教育',
        'codes': ['300559','300645','300192','002230','300624','688568','300010'],
        'keywords': ['教育信息化','AI教育','智慧教育','在线教育','教育IT','教育SaaS']
    },
    {
        'name': '量子计算/量子通信',
        'codes': ['002222','300297','600120','688027','600260','000555'],
        'keywords': ['量子计算','量子通信','量子芯片','量子','量子比特','量子加密']
    },
    {
        'name': '氢能源/燃料电池',
        'codes': ['300471','002733','600218','002274','000723','300228','688339'],
        'keywords': ['氢能源','燃料电池','氢能','电解水','加氢站','质子交换膜','双极板']
    }
]

# 构建快速查找表
TRACK_CODE_MAP = {}
TRACK_KEYWORD_MAP = []
for track in HOT_TRACKS:
    for c in track['codes']:
        TRACK_CODE_MAP[c] = track['name']
    for kw in track['keywords']:
        TRACK_KEYWORD_MAP.append((kw, track['name']))

def match_track(code, name, sector):
    """匹配股票所属赛道"""
    # 精确匹配
    if code in TRACK_CODE_MAP:
        return TRACK_CODE_MAP[code], '高'
    
    # 关键词匹配
    combined = (name or '') + '|' + (sector or '')
    for kw, track_name in TRACK_KEYWORD_MAP:
        if kw in combined:
            return track_name, '中'
    
    return '', '无'

def run():
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    today = date.today().isoformat()
    
    print(f'\n{"="*60}')
    print(f'🆕 赛道宽松通道扫描 | {today}')
    print(f'{"="*60}')
    print(f'   条件: 营收>20% | 市值20-150亿 | 换手>1% | 回撤20-55% | 热门赛道')
    print(f'   不要求ROE>15% 不要求利润>0%')
    print(f'   赛道列表: 共{len(HOT_TRACKS)}个赛道')
    print()
    
    # 获取最新的2个完整季度（跳过数据不足的季度）
    cur.execute('SELECT DISTINCT report_date FROM financial_data ORDER BY report_date DESC')
    all_q = [r[0] for r in cur.fetchall()]
    # 跳过数据不足的季度（<1000条）
    full_q = []
    for q in all_q:
        cur.execute('SELECT COUNT(*) FROM financial_data WHERE report_date=?', (q,))
        cnt = cur.fetchone()[0]
        if cnt >= 1000:
            full_q.append(q)
        if len(full_q) >= 2:
            break
    if len(full_q) < 2:
        print(f'❌ 财务数据不足2个完整季度')
        return
    
    q1, q2 = full_q[0], full_q[1]
    print(f'最近2个完整季度: {q1}, {q2}')
    
    cur.execute('''
        SELECT f1.code, f1.revenue_growth as r1, f1.profit_growth as p1,
               f1.roe as roe1, f1.debt_ratio as dr1,
               f2.revenue_growth as r2, f2.profit_growth as p2
        FROM financial_data f1
        JOIN financial_data f2 ON f1.code = f2.code AND f2.report_date = ?
        WHERE f1.report_date = ?
          AND f1.revenue_growth IS NOT NULL AND f2.revenue_growth IS NOT NULL
    ''', (q2, q1))
    all_fin = {r['code']: dict(r) for r in cur.fetchall()}
    print(f'有财务数据的股票: {len(all_fin)}只')
    
    # 获取股票基本信息
    cur.execute('SELECT code, name, sector, total_shares_real FROM stocks')
    stocks_info = {r['code']: dict(r) for r in cur.fetchall()}
    
    # 获取换手率
    cur.execute('SELECT code, turnover_rate FROM indicators WHERE turnover_rate IS NOT NULL')
    turnover = {r['code']: r['turnover_rate'] for r in cur.fetchall()}
    
    # 获取最新收盘价和市值
    candidates = []
    processed = 0
    
    for code, fin in all_fin.items():
        sinfo = stocks_info.get(code, {})
        name = sinfo.get('name', '') or ''
        sector = sinfo.get('sector', '') or ''
        ts = sinfo.get('total_shares_real', 0) or 0
        
        # 排除ST/科创板
        if any(name.startswith(p) for p in ('ST','*ST','S','退')): continue
        if code.startswith(('688', '787')): continue
        if not code.startswith(('60', '00', '30')): continue
        
        # 赛道匹配（先筛选赛道，减少计算量）
        track, match_level = match_track(code, name, sector)
        if match_level == '无': continue
        
        # 营收增速 > 20%（近2季度）
        r1 = fin['r1'] or 0
        r2 = fin['r2'] or 0
        if r1 < 20 or r2 < 20: continue
        
        # 市值 20-150亿
        if ts <= 0: continue
        cur.execute('SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1', (code,))
        price_row = cur.fetchone()
        if not price_row: continue
        price = price_row[0]
        mcap = ts * price / 1e8
        if mcap < 20 or mcap > 150: continue
        
        # 换手率 > 1%
        tr = turnover.get(code, 0) or 0
        if tr < 1: continue
        
        # 回撤 20-55%（从250日高点）
        cur.execute('''
            SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 250
        ''', (code,))
        closes = [r[0] for r in cur.fetchall()]
        if len(closes) < 200: continue
        high_250 = max(closes)
        cur_price = closes[0]
        dd = (high_250 - cur_price) / high_250 * 100
        if dd < 20 or dd > 55: continue
        
        candidates.append({
            'code': code,
            'name': name[:10],
            'sector': sector[:14],
            'track': track,
            'match': match_level,
            'rev': round(r1, 1),
            'mcap': round(mcap, 1),
            'turnover': round(tr, 1),
            'dd': round(dd, 1),
        })
        processed += 1
    
    # 按赛道优先级排序 + 营收增速排序
    track_order = {t['name']: i for i, t in enumerate(HOT_TRACKS)}
    candidates.sort(key=lambda x: (track_order.get(x['track'], 99), -x['rev']))
    
    # 最多输出10只
    results = candidates[:10]
    
    print(f'通过赛道筛选: {processed}只')
    print(f'最终输出: {len(results)}只')
    
    print(f'\n{"代码":8s} {"名称":12s} {"赛道":24s} {"营收":8s} {"市值":8s} {"换手":8s} {"回撤":8s}')
    print(f'{"-"*75}')
    for s in results:
        print(f'{s["code"]:8s} {s["name"]:12s} {s["track"][:24]:24s} {s["rev"]:>6.1f}% {s["mcap"]:>6.1f}亿 {s["turnover"]:>5.1f}% {s["dd"]:>5.1f}%')
    
    print(f'\n{"─"*60}')
    print(f'📌 以上为【🆕 赛道宽松池】，仅作人工观察，不参与自动模拟买入')
    print(f'{"="*60}')
    
    # 保存结果到文件（供周报引用）
    out_path = '/home/caojy/.hermes/scripts/cron/track_loose_pool.json'
    with open(out_path, 'w') as f:
        json.dump({'date': today, 'stocks': results}, f, ensure_ascii=False, indent=2)
    print(f'结果已保存: {out_path}')
    
    conn.close()
    return results

if __name__ == '__main__':
    run()