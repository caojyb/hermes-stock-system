#!/usr/bin/env python3
"""
系统全面诊断 — 手动触发，全链路检查
"""
import os, sys, sqlite3, json
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path
from simulation_db_helper import get_active_sim_db

MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SIM_DB = str(get_active_sim_db())
# 候选池统一从 double_up_scores 表读取（pool_loader）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pool_loader import load_pool

print("=" * 55)
print("🔍 系统全面诊断")
print(f"   诊断时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 55)

results = {'pass': [], 'fail': []}

def ok(msg):
    results['pass'].append(msg)
    print(f"  ✅ {msg}")

def fail(msg):
    results['fail'].append(msg)
    print(f"  ❌ {msg}")

# ═══ 1. 数据层检查 ═══
print(f"\n{'─'*55}")
print("📋 1. 数据层检查")
print(f"{'─'*55}")

try:
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("SELECT MAX(date) FROM klines")
    last_k = cur.fetchone()[0]
    ok(f"K线最新时间戳: {last_k}")
    
    cur.execute("SELECT COUNT(*) FROM klines WHERE date = (SELECT MAX(date) FROM klines)")
    cnt = cur.fetchone()[0]
    ok(f"最新交易日K线数量: {cnt} 只")
    
    cur.execute("SELECT COUNT(*) FROM stocks WHERE total_shares_real > 0")
    ts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM stocks")
    total = cur.fetchone()[0]
    ok(f"总股本覆盖率: {ts}/{total} ({ts/total*100:.1f}%)")
    
    cur.execute("SELECT COUNT(*) FROM indicators WHERE turnover_rate IS NOT NULL AND turnover_rate > 0")
    tr = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM indicators")
    total_tr = cur.fetchone()[0]
    ok(f"换手率覆盖率: {tr}/{total_tr} ({tr/total_tr*100:.1f}%)")
    
    # 候选池财务数据完整性
    stocks = load_pool()
    if stocks:
        missing_fin = []
        for s in stocks:
            code = s['code']
            cur.execute("SELECT revenue_growth, profit_growth, debt_ratio FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1", (code,))
            r = cur.fetchone()
            if not r or r[0] is None or r[1] is None:
                missing_fin.append(code)
        if missing_fin:
            fail(f"候选池{len(missing_fin)}只缺财务数据: {','.join(missing_fin)}")
        else:
            ok(f"候选池{len(stocks)}只股票财务数据齐全")
    
except Exception as e:
    fail(f"数据层检查异常: {e}")

# ═══ 2. 信号层检查 ═══
print(f"\n{'─'*55}")
print("📋 2. 信号层检查")
print(f"{'─'*55}")

try:
    candidates = load_pool()
    
    # 检查今日信号
    today = date.today().isoformat()
    for s in candidates[:5]:  # 取前5只
        code = s['code']
        cur.execute("SELECT date, close, volume FROM klines WHERE code=? ORDER BY date DESC LIMIT 60", (code,))
        klines = [dict(r) for r in cur.fetchall()]
        if len(klines) < 20:
            continue
        closes = [k['close'] for k in klines]
        volumes = [k['volume'] for k in klines]
        price = closes[0]
        
        sigs = []
        if len(closes) >= 20:
            ma20 = sum(closes[:20])/20
            ma20p = sum(closes[1:21])/20
            if price > ma20 and ma20 >= ma20p: sigs.append('A')
        if len(volumes) >= 13:
            if sum(volumes[:3]) > sum(volumes[3:13])/10*1.8: sigs.append('B')
        if len(closes) >= 20:
            if price >= max(closes[:20]): sigs.append('C')
        
        print(f"  {code} {s['name']:10s} 信号: {''.join(sigs) or '无'} 收盘价{price:.2f}")
    
    ok(f"信号扫描完成，检查了{min(5,len(candidates))}只股票")
    
    # 边界值检查
    print(f"  边界值检查:")
    for s in candidates[:3]:
        code = s['code']
        cur.execute("SELECT close, volume FROM klines WHERE code=? ORDER BY date DESC LIMIT 20", (code,))
        klines = [dict(r) for r in cur.fetchall()]
        if len(klines) < 20: continue
        closes = [k['close'] for k in klines]
        ma20 = sum(closes)/20
        print(f"    {code} {s['name']:10s} 收盘价{closes[0]:.2f} MA20={ma20:.2f} 比值={closes[0]/ma20:.3f}")
    
    ok("信号层检查通过")
except Exception as e:
    fail(f"信号层检查异常: {e}")

# ═══ 3. 模拟交易层检查 ═══
print(f"\n{'─'*55}")
print("📋 3. 模拟交易层检查")
print(f"{'─'*55}")

try:
    if os.path.exists(SIM_DB):
        sim = sqlite3.connect(SIM_DB)
        sim_cur = sim.cursor()
        
        sim_cur.execute("SELECT * FROM trades WHERE status IN ('持有','部分止盈')")
        holdings = [dict(r) for r in sim_cur.fetchall()]
        print(f"  当前持仓: {len(holdings)} 笔")
        for h in holdings:
            code = h[1]; name = h[2]; bp = h[5]; qty = h[6]; status = h[13]
            # 获取当前价
            cur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
            pr = cur.fetchone()
            cp = pr[0] if pr else bp
            ret = (cp - bp) / bp * 100
            print(f"    {code} {name:10s} 数量{qty:>4} 成本{bp:>6.2f} 当前{cp:>6.2f} ({ret:+.1f}%) [{status}]")
            
            # 止盈止损条件单验证
            print(f"      止损: {bp*(1-0.08):.2f}  | 止盈+25%: {bp*1.25:.2f}  | +50%: {bp*1.50:.2f}  | +80%: {bp*1.80:.2f}")
        
        ok(f"模拟交易持仓检查完成，{len(holdings)}笔活跃")
        sim.close()
    else:
        fail("模拟交易数据库不存在")
except Exception as e:
    fail(f"模拟交易检查异常: {e}")

# ═══ 4. 新股虹吸检查 ═══
print(f"\n{'─'*55}")
print("📋 4. 新股虹吸检查")
print(f"{'─'*55}")

try:
    if os.path.exists(SIM_DB):
        sim = sqlite3.connect(SIM_DB)
        sim_cur = sim.cursor()
        sim_cur.execute("SELECT * FROM ipo_blocks WHERE active=1")
        blocks = [dict(r) for r in sim_cur.fetchall()]
        if blocks:
            for b in blocks:
                print(f"  活跃暂缓: {b[1]}({b[0]}) 市值{b[4]/1e8:.0f}亿 行业{b[5]} 暂缓至{b[7]}")
        else:
            print(f"  无活跃暂缓")
        ok(f"新股虹吸检查完成")
        sim.close()
except Exception as e:
    fail(f"新股虹吸检查异常: {e}")

# ═══ 5. 日志检查 ═══
print(f"\n{'─'*55}")
print("📋 5. 日志检查")
print(f"{'─'*55}")

log_dir = os.path.expanduser("~/.hermes/logs")
if os.path.exists(log_dir):
    log_files = sorted([f for f in os.listdir(log_dir) if f.endswith('.log')], reverse=True)[:5]
    for lf in log_files:
        fp = os.path.join(log_dir, lf)
        size = os.path.getsize(fp) / 1024
        # 检查最后几行是否有ERROR
        with open(fp, 'r', errors='ignore') as f:
            lines = f.readlines()[-30:]
        errors = [l for l in lines if 'ERROR' in l or 'Error' in l or 'Traceback' in l]
        if errors:
            print(f"  ⚠️ {lf} ({size:.0f}KB) 最近有{len(errors)}条错误:")
            for e in errors[-3:]:
                print(f"    {e.strip()[:120]}")
        else:
            print(f"  ✅ {lf} ({size:.0f}KB) 无错误")
    ok("日志检查完成")
else:
    fail("日志目录不存在")

conn.close()

# ═══ 结论 ═══
print(f"\n{'='*55}")
print("📊 诊断结论")
print(f"{'='*55}")
print(f"  通过: {len(results['pass'])} 项")
print(f"  异常: {len(results['fail'])} 项")

if not results['fail']:
    print(f"  系统整体状态: ✅ 正常")
elif len(results['fail']) <= 2:
    print(f"  系统整体状态: ⚠️ 需关注（{len(results['fail'])}项异常）")
    for f in results['fail']:
        print(f"    建议: {f}")
else:
    print(f"  系统整体状态: 🔴 严重异常（{len(results['fail'])}项异常）")
    print(f"  建议立即处理!")
    for f in results['fail']:
        print(f"    修复: {f}")

print(f"\n{'='*55}")