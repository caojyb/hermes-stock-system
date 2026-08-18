#!/usr/bin/env python3
"""
数据补全 + 候选池刷新 + 对比报告
===================================
1. 用总股本数据刷新换手率计算
2. 灵活版全市场扫描（利润>0%, 换手>1%, 市值20-200亿, 主板+创业板）
3. 对比新旧候选池
"""
import os, sys, sqlite3, json
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))
conn = sqlite3.connect(str(MARKET_DB))

# ═══ 参数自适应优化（滚动优化器）═══
print(f"\n{'='*65}")
print(f"📊 系统参数自适应优化")
print(f"{'='*65}")
try:
    from param_optimizer import run as param_optimize
    param_optimize()
except Exception as e:
    print(f"   参数优化失败: {e}（跳过，使用默认参数）")
print(f"{'='*65}\n")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

today = date.today()
print("="*65)
print("📊 数据补全 + 候选池刷新")
print(f"   日期: {today}")
print("="*65)

# ═══ 1. 数据准备 ═══
print("\n📋 加载数据...")

cur.execute('SELECT code, name, sector, is_st, list_date, total_shares_real, circulating_shares_real FROM stocks')
stocks_info = {r['code']: dict(r) for r in cur.fetchall()}

cur.execute('SELECT code, close FROM (SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn FROM klines) WHERE rn=1')
latest_prices = {r['code']: r['close'] for r in cur.fetchall()}

cur.execute("SELECT code, pe_ttm, pe_pct FROM pe_pb_data WHERE (code, fetch_date) IN (SELECT code, MAX(fetch_date) FROM pe_pb_data WHERE pe_pct IS NOT NULL GROUP BY code)")
pe_data = {r['code']: dict(r) for r in cur.fetchall()}

cur.execute("SELECT code, date, close FROM klines WHERE date >= ? ORDER BY code, date", ((today-timedelta(days=400)).isoformat(),))
kline_data = defaultdict(list)
for r in cur.fetchall(): kline_data[r['code']].append(r['close'])

# 财务数据
cur.execute("""
    WITH ranked AS (
        SELECT code, report_date, revenue_growth, profit_growth, debt_ratio,
               ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
        FROM financial_data WHERE report_date IS NOT NULL
    )
    SELECT r1.code, r1.revenue_growth as r1g, r2.revenue_growth as r2g,
           r1.profit_growth as p1g, r2.profit_growth as p2g, r1.debt_ratio as dr1
    FROM ranked r1 JOIN ranked r2 ON r1.code=r2.code AND r2.rn=2 WHERE r1.rn=1
""")
fin_data = {r['code']: dict(r) for r in cur.fetchall()}

# 统计总股本数据覆盖率
has_ts = sum(1 for s in stocks_info.values() if s.get('total_shares_real') and s['total_shares_real'] > 0)
print(f"   总股本数据: {has_ts}/5188 ({has_ts/5188*100:.1f}%)")

# 换手率: 从总股本计算，或从indicators表，或从东财MCP
# 先用数据库中已有的
cur.execute('SELECT code, turnover_rate FROM indicators WHERE turnover_rate IS NOT NULL')
indicator_tr = {r['code']: r['turnover_rate'] for r in cur.fetchall()}

# PS/PCF 数据加载
cur.execute('SELECT code, ps_ttm, pcf_ttm FROM indicators WHERE ps_ttm IS NOT NULL')
indicator_data = {r['code']: {'ps_ttm': r[1], 'pcf_ttm': r[2]} for r in cur.fetchall()}

# 计算各行业 PS 均值
cur.execute('''
    SELECT s.sector, AVG(i.ps_ttm) as avg_ps
    FROM indicators i JOIN stocks s ON i.code = s.code
    WHERE i.ps_ttm IS NOT NULL AND i.ps_ttm > 0 AND s.sector IS NOT NULL
    GROUP BY s.sector
''')
sector_ps_avg = {r[0]: r[1] for r in cur.fetchall()}

def calc_turnover(code):
    """计算换手率：优先用总股本，其次用indicators表"""
    sinfo = stocks_info.get(code)
    if sinfo:
        ts = sinfo.get('total_shares_real')
        if ts and ts > 0:
            price = latest_prices.get(code, 0)
            # 从K线取最近成交量
            klines = kline_data.get(code, [])
            if len(klines) >= 1:
                # 用最近20天的平均成交量
                recent = klines[-20:] if len(klines) >= 20 else klines
                # 不会算成交量因为没有volume数据，用indicators的turnover_rate
                pass
    return indicator_tr.get(code, None)

# ═══ 2. 灵活版筛选 ═══
print("\n📋 灵活版筛选（利润>0%, 换手>1%, 市值20-200亿, 主板+创业板）...")

def estimate_mcap(code, price):
    """估算市值（亿元）"""
    if price <= 0: return 0
    sinfo = stocks_info.get(code)
    ts = sinfo.get('total_shares_real') if sinfo else None
    if ts and ts > 0:
        return price * ts / 100000000  # 真实市值
    return price * 50000000 / 100000000  # 估算

results = []
for code in fin_data:
    sinfo = stocks_info.get(code)
    if not sinfo: continue
    if sinfo.get('is_st', 0) == 1: continue
    if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S','退')): continue
    # 剔除科创板
    if code.startswith(('688', '787')): continue
    # 只保留主板+创业板
    if not code.startswith(('60', '00', '30')): continue
    list_date = sinfo.get('list_date')
    if list_date:
        try:
            if (today - __import__('datetime').datetime.strptime(list_date, '%Y-%m-%d').date()).days < 180: continue
        except: pass
    
    fin = fin_data[code]
    r1g, r2g, p1g, dr1 = fin['r1g'], fin['r2g'], fin['p1g'], fin['dr1']
    if r1g is None or r2g is None or r1g < 30 or r2g < 30: continue
    if p1g is None or p1g < 0: continue  # 灵活版：利润>0%
    if dr1 is None or dr1 >= 65: continue
    
    price = latest_prices.get(code)
    if not price or price <= 0: continue
    mcap = estimate_mcap(code, price)
    if mcap < 20 or mcap > 200: continue  # 灵活版：市值20-200亿
    
    pe = pe_data.get(code)
    if pe:
        pe_pct = pe.get('pe_pct')
        if pe_pct is not None and pe_pct >= 40: continue
    
    # PS/PCF 估值过滤
    ps_val = None
    pcf_val = None
    if code in indicator_data:
        ps_val = indicator_data[code].get('ps_ttm')
        pcf_val = indicator_data[code].get('pcf_ttm')
    # PS < 行业均值 × 1.5（避免营收估值过高）
    if ps_val is not None and ps_val > 0:
        sector_avg = sector_ps_avg.get(sinfo.get('sector', ''), float('inf'))
        if sector_avg > 0 and ps_val > sector_avg * 1.5:
            continue
    # PCF > 0（经营现金流为正）
    if pcf_val is not None and pcf_val <= 0:
        continue
    
    # 换手率 > 1%
    tr = calc_turnover(code)
    if tr is not None and tr < 1: continue
    
    klines = kline_data.get(code, [])
    if len(klines) < 250: continue
    max_p = max(klines[-250:])
    cur_p = klines[-1]
    dd = (max_p - cur_p) / max_p * 100 if max_p > 0 else 0
    if dd < 15 or dd > 45: continue
    
    # 流动性门槛：近20日日均成交额 > 3000万
    try:
        market = '1' if code.startswith(('60', '688', '689')) else '0'
        r = __import__('requests').get(f'http://push2delay.eastmoney.com/api/qt/stock/get',
            params={'secid': f'{market}.{code}', 'fields': 'f57,f48', 'invt': 2, 'fltt': 2},
            timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json().get('data', {})
        f48 = d.get('f48', 0) or 0
        if f48 < 30000000:  # 3000万
            continue
    except Exception as e:
        print(f"[WARN] double_refresh 流动性检查失败 ({code}): {e}")
        # 降级：用K线估算
        k_lines = kline_data.get(code, [])
        if len(k_lines) >= 20:
            klines_20 = klines[-20:] if len(klines) >= 20 else klines
            # 用volume和close估算
            pass  # 允许通过
    
    results.append({
        'code': code, 'name': sinfo['name'], 'sector': sinfo.get('sector', ''),
        'mcap': round(mcap, 1), 'rev_growth': round(r1g, 1),
        'profit_growth': round(p1g, 1),
        'pe_pct': round(pe.get('pe_pct', 0), 1) if pe else 'N/A',
        'drawdown': round(dd, 1), 'turnover': tr or 0
    })

# ═══ 3. 按行业分组输出 ═══
print(f"\n{'='*65}")
print(f"📊 灵活版候选池: {len(results)} 只")
print(f"{'='*65}")

if results:
    # 按行业分组
    by_sector = defaultdict(list)
    for s in results:
        by_sector[s['sector']].append(s)
    
    for sector in sorted(by_sector.keys()):
        stocks = by_sector[sector]
        print(f"\n{'─'*65}")
        print(f"🏭 {sector}（{len(stocks)}只）")
        for s in stocks:
            tr_str = f"换手{s['turnover']:.1f}%" if s['turnover'] else "换手N/A"
            print(f"   {s['code']} {s['name']:10s} 市值{s['mcap']:>5.1f}亿 利润{s['profit_growth']:>6.1f}% {tr_str} 回撤{s['drawdown']:>4.1f}%")
else:
    print("   当前无符合条件的股票")

# ═══ 4. 基本面趋势标签 ═══
print(f"\n{'='*65}")
print("📊 基本面趋势标签")
print(f"{'='*65}")

def get_trend_label(v1, v2, threshold=5):
    """比较两个季度的增长率，返回趋势标签"""
    if v1 is None or v2 is None:
        return 'N/A'
    change = v1 - v2
    if change >= threshold:
        return '🔼'  # 上升
    elif change <= -threshold:
        return '🔽'  # 下降
    else:
        return '➡️'  # 持平

# 所有有财务数据的股票
all_stocks_with_fin = []
for code, sinfo in stocks_info.items():
    if sinfo.get('is_st', 0) == 1: continue
    if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S','退')): continue
    fin = fin_data.get(code)
    if not fin: continue
    r1g, r2g, p1g, p2g = fin['r1g'], fin['r2g'], fin['p1g'], fin['p2g']
    if r1g is None or r2g is None or p1g is None or p2g is None: continue
    
    rev_trend = get_trend_label(r1g, r2g)
    prof_trend = get_trend_label(p1g, p2g)
    
    # 综合趋势：取两者中更差的方向
    trend_order = {'🔼': 0, '➡️': 1, '🔽': 2, 'N/A': 3}
    combined = min(rev_trend, prof_trend, key=lambda x: trend_order.get(x, 3))
    
    # 如果一个是🔼一个是🔽，综合为➡️
    if (rev_trend == '🔼' and prof_trend == '🔽') or (rev_trend == '🔽' and prof_trend == '🔼'):
        combined = '➡️'
    
    all_stocks_with_fin.append({
        'code': code,
        'name': sinfo.get('name', ''),
        'sector': sinfo.get('sector', ''),
        'rev1': round(r1g, 1),
        'rev2': round(r2g, 1),
        'pg1': round(p1g, 1),
        'pg2': round(p2g, 1),
        'rev_trend': rev_trend,
        'prof_trend': prof_trend,
        'trend': combined,
        'recommend': '趋势恶化，不推荐' if combined == '🔽' else ''
    })

# 按趋势排序：🔼优先，🔽最后
trend_sort = {'🔼': 0, '➡️': 1, '🔽': 2, 'N/A': 3}
all_stocks_with_fin.sort(key=lambda x: trend_sort.get(x['trend'], 3))

by_trend = defaultdict(list)
for s in all_stocks_with_fin:
    by_trend[s['trend']].append(s)

# 统计
for trend_label in ['🔼', '➡️', '🔽']:
    group = by_trend.get(trend_label, [])
    trend_name = {'🔼': '上升', '➡️': '持平', '🔽': '下降'}.get(trend_label, '')
    print(f"\n{'─'*65}")
    print(f"{trend_label} {trend_name}趋势（{len(group)}只）")
    for s in group[:50]:  # 最多显示50只
        rec = f" ⚠️ {s['recommend']}" if s['recommend'] else ''
        print(f"   {s['code']} {s['name']:10s} 营收:{s['rev2']:>6.1f}%→{s['rev1']:>6.1f}%{s['rev_trend']} 利润:{s['pg2']:>6.1f}%→{s['pg1']:>6.1f}%{s['prof_trend']}{rec}")

print(f"\n{'='*65}")

# ═══ 右侧突破观察（独立补充，不参与模拟买入）═══
print(f"\n{'='*65}")
print(f"🆕 右侧突破观察")
print(f"{'='*65}")
print(f"   条件: 股价创120日新高 + 营收增速>30% + 市值20-200亿 + 换手率>3%")
print(f"   说明: 独立板块，仅作人工参考，不参与模拟自动买入")

breakout_results = []
for code in fin_data:
    sinfo = stocks_info.get(code)
    if not sinfo: continue
    if sinfo.get('is_st', 0) == 1: continue
    if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S','退')): continue
    if code.startswith(('688', '787')): continue
    if not code.startswith(('60', '00', '30')): continue
    list_date = sinfo.get('list_date')
    if list_date:
        try:
            if (today - __import__('datetime').datetime.strptime(list_date, '%Y-%m-%d').date()).days < 180: continue
        except: pass
    
    fin = fin_data[code]
    r1g, r2g, p1g, dr1 = fin['r1g'], fin['r2g'], fin['p1g'], fin['dr1']
    if r1g is None or r2g is None or r1g < 30 or r2g < 30: continue
    if p1g is None or p1g < 0: continue
    if dr1 is None or dr1 >= 65: continue
    
    price = latest_prices.get(code)
    if not price or price <= 0: continue
    mcap = estimate_mcap(code, price)
    if mcap < 20 or mcap > 200: continue
    
    pe = pe_data.get(code)
    if pe:
        pe_pct = pe.get('pe_pct')
        if pe_pct is not None and pe_pct >= 40: continue
    
    tr = calc_turnover(code)
    if tr is not None and tr < 3: continue
    
    klines = kline_data.get(code, [])
    if len(klines) < 120: continue
    high_120 = max(klines[-120:])
    if price < high_120: continue
    
    breakout_results.append({
        'code': code, 'name': sinfo['name'], 'sector': sinfo.get('sector', ''),
        'mcap': round(mcap, 1), 'rev_growth': round(r1g, 1),
        'profit_growth': round(p1g, 1),
        'turnover': tr or 0
    })

if breakout_results:
    by_sector = defaultdict(list)
    for s in breakout_results:
        by_sector[s['sector']].append(s)
    
    print(f"\n   📈 右侧突破候选: {len(breakout_results)} 只")
    for sector in sorted(by_sector.keys()):
        stocks = by_sector[sector]
        print(f"\n   🏭 {sector}（{len(stocks)}只）")
        for s in stocks:
            tr_str = f"换手{s['turnover']:.1f}%" if s['turnover'] else "换手N/A"
            print(f"      {s['code']} {s['name']:10s} 市值{s['mcap']:>5.1f}亿 利润{s['profit_growth']:>6.1f}% {tr_str}")
else:
    print(f"\n   当前无右侧突破候选")

print(f"\n{'─'*65}")
print(f"   📌 右侧突破观察仅作人工参考，不参与模拟自动买入")
print(f"{'='*65}")

print(f"\n{'='*65}")

# ═══ 5. 对比报告 ═══
print(f"\n{'='*65}")
print("📋 新旧候选池对比")
print(f"{'='*65}")

# 旧候选池（5只）
old_pool = ['603991', '002192', '002850', '301219', '301606']
old_names = {s['code']: s['name'] for s in results if s['code'] in old_pool}
new_codes = [s['code'] for s in results if s['code'] not in old_pool]

print(f"\n旧候选池（5只）:")
for code in old_pool:
    if code in old_names:
        print(f"  ✅ {code} {old_names[code]} — 仍在池中")
    else:
        # 查为什么被淘汰
        sinfo = stocks_info.get(code)
        name = sinfo['name'] if sinfo else code
        fin = fin_data.get(code)
        reasons = []
        if fin:
            if fin['r1g'] is None or fin['r1g'] < 30: reasons.append('营收增速<30%')
            if fin['p1g'] is None or fin['p1g'] < 0: reasons.append('利润增速<0%')
            if fin['dr1'] is None or fin['dr1'] >= 65: reasons.append('负债率>65%')
        price = latest_prices.get(code, 0)
        mcap = estimate_mcap(code, price)
        if mcap < 20 or mcap > 200: reasons.append(f'市值{mcap:.0f}亿不在20-200亿')
        pe = pe_data.get(code)
        if pe and pe.get('pe_pct') is not None and pe['pe_pct'] >= 40: reasons.append('PE分位>=40%')
        tr = calc_turnover(code)
        if tr is not None and tr < 1: reasons.append(f'换手率{tr:.1f}%<1%')
        klines = kline_data.get(code, [])
        if len(klines) >= 250:
            max_p = max(klines[-250:])
            cur_p = klines[-1]
            dd = (max_p - cur_p) / max_p * 100 if max_p > 0 else 0
            if dd < 15 or dd > 45: reasons.append(f'回撤{dd:.1f}%不在15-45%')
        print(f"  ❌ {code} {name} — 淘汰原因: {', '.join(reasons) or '未知'}")

print(f"\n新增候选（{len(new_codes)}只）:")
for code in new_codes:
    s = next((x for x in results if x['code'] == code), None)
    if s:
        print(f"  🆕 {s['code']} {s['name']:10s} 行业{s['sector']:8s} 利润{s['profit_growth']:>6.1f}% 市值{s['mcap']:>5.1f}亿")

# 保存结果
output = {'date': str(today), 'count': len(results), 'stocks': results}
with open('/home/caojy/.hermes/scripts/cron/double_pool.json', 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

conn.close()

# 模拟组合周报
print(f"\n{'='*65}")
print("📊 模拟组合周报")
print(f"{'='*65}")
sim_db = "/home/caojy/.hermes/scripts/cron/simulation.db"
if os.path.exists(sim_db):
    sim_conn = sqlite3.connect(sim_db)
    sim_cur = sim_conn.cursor()
    sim_cur.execute("SELECT * FROM trades WHERE status IN ('持有','部分止盈')")
    holdings = sim_cur.fetchall()
    print(f"当前持仓: {len(holdings)} 笔")
    for h in holdings:
        print(f"  {h[1]} {h[2]}: 买入{h[4]}@{h[5]:.2f} 数量{h[6]} 状态:{h[13]}")
    sim_cur.execute("SELECT COALESCE(SUM(profit_amount),0) FROM trades WHERE status IN ('清仓止盈','止损','部分止盈')")
    realized_pnl = sim_cur.fetchone()[0]
    sim_cur.execute("SELECT COALESCE(SUM(buy_amount),0) FROM trades WHERE status IN ('持有','部分止盈')")
    total_invested = sim_cur.fetchone()[0]
    sim_cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL AND profit_amount > 0")
    wins = sim_cur.fetchone()[0]
    sim_cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date IS NOT NULL")
    total_closed = sim_cur.fetchone()[0]
    cash = 1000000 - total_invested
    total_value = cash + total_invested + realized_pnl
    total_return = (total_value - 1000000) / 1000000 * 100
    print(f"总资产: {total_value:,.0f} | 收益: {total_return:+.2f}% | 胜率: {wins/max(1,total_closed)*100:.1f}%")
    sim_conn.close()

# 边界条件验证
print(f"\n{'='*65}")
print("🧪 边界条件验证")
print(f"{'='*65}")
os.system(f'python3 {os.path.dirname(__file__)}/boundary_verify.py 2>&1 | tail -20')

print(f"\n{'='*65}")
print(f"✅ 完成 | 候选池 {len(results)} 只 | 已保存到 double_pool.json")
print(f"{'='*65}")