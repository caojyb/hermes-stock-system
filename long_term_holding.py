#!/usr/bin/env python3
"""
翻倍股长持模式（Long-Term Holding Mode）
========================================
在模拟交易系统中增加长持子模式，自动识别"种子选手"并切换宽松止盈止损规则。

长持条件（全部满足）：
  1. 营收增速连续2个季度加速（Q3>Q2>Q1）
  2. 利润增速连续2个季度加速
  3. 行业景气度评分 > 0
  4. PE历史分位 < 50%
  5. ROE > 15%
  6. 市值 30-200亿
  7. 无资金流/事件风险标记

长持卖出规则：
  - 基本面止损：连续2季营收增速下滑或利润转负 → 清仓
  - 大盘系统性风险：沪深300跌破年线且3日未收回 → 清仓
  - 不设技术面止盈（无+25%/+50%/+80%）
  - 保留-15%极端保护止损
"""
import os, sys, json, sqlite3, requests
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path
from simulation_db_helper import get_active_sim_db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SIM_DB = str(get_active_sim_db())
SECTOR_RATING_FILE = os.path.join(os.path.dirname(__file__), 'sector_rating.json')

HEADERS = {'User-Agent': 'Mozilla/5.0'}
TOTAL_CAPITAL = 1000000

# 长持参数
LONG_POSITION_PCT = 0.05       # 首仓5%（普通模式2.5%）
LONG_MAX_POSITION_PCT = 0.08   # 加仓上限8%
LONG_STOP_LOSS = 0.15          # 极端保护止损-15%（普通模式-8%）
LONG_NO_TAKEPROFIT = True      # 取消技术面止盈

def fetch_financial_data(cur, codes):
    """获取最近3个季度财务数据"""
    placeholders = ','.join(['?'] * len(codes))
    cur.execute(f'''
        SELECT code, report_date, revenue_growth, profit_growth, roe, pe_ratio, pb_ratio
        FROM financial_data 
        WHERE code IN ({placeholders})
        ORDER BY code, report_date DESC
    ''', codes)
    by_code = defaultdict(list)
    for r in cur.fetchall():
        by_code[r[0]].append({
            'date': r[1], 'rev': r[2] or 0, 'prof': r[3] or 0,
            'roe': r[4], 'pe': r[5], 'pb': r[6]
        })
    return by_code

def fetch_pe_pct(cur, codes):
    """获取PE历史分位"""
    placeholders = ','.join(['?'] * len(codes))
    cur.execute(f'''
        SELECT code, pe_pct, pb_pct
        FROM pe_pb_data
        WHERE code IN ({placeholders})
    ''', codes)
    return {r[0]: {'pe_pct': r[1], 'pb_pct': r[2]} for r in cur.fetchall()}

def fetch_risk_flags(cur, codes):
    """获取资金流/事件风险标记"""
    placeholders = ','.join(['?'] * len(codes))
    flags = {}
    
    # 资金流风险
    cur.execute(f'''
        SELECT code, SUM(net_amt) as total_flow
        FROM main_fund_flow
        WHERE code IN ({placeholders}) AND date >= date('now', '-3 days')
        GROUP BY code
    ''', codes)
    flow_risk = {r[0]: r[1] for r in cur.fetchall()}
    
    # 事件风险（解禁/减持/质押）——表可能为空
    try:
        cur.execute(f'''
            SELECT code, COUNT(*) as events
            FROM (
                SELECT code FROM lockup_release WHERE code IN ({placeholders})
                UNION ALL
                SELECT code FROM holder_change WHERE code IN ({placeholders}) AND change_type = '减持'
                UNION ALL
                SELECT code FROM equity_pledge WHERE code IN ({placeholders}) AND pledge_ratio > 30
            )
            GROUP BY code
        ''', codes + codes + codes)
        event_risk = {r[0]: r[1] for r in cur.fetchall()}
    except:
        event_risk = {}
    
    for code in codes:
        has_flow = flow_risk.get(code, 0) is not None and flow_risk.get(code, 0) < 0
        has_event = code in event_risk
        flags[code] = {'flow_risk': has_flow, 'event_risk': has_event}
    
    return flags

def load_sector_rating():
    """加载行业景气度评分"""
    if not os.path.exists(SECTOR_RATING_FILE):
        return {}
    try:
        with open(SECTOR_RATING_FILE) as f:
            return json.load(f)
    except:
        return {}

def get_sector_for_code(cur, code):
    """获取股票所属行业"""
    cur.execute('SELECT sector FROM stocks WHERE code=?', (code,))
    r = cur.fetchone()
    return r[0] if r else ''

def check_long_term_seed(code, fins, pe_pct_data, risk_flags, sector_rating, sector):
    """检查是否满足长持种子条件"""
    if len(fins) < 3:
        return False, '财务数据不足3个季度'
    
    q1, q2, q3 = fins[0], fins[1], fins[2]
    r1, r2, r3 = q1['rev'], q2['rev'], q3['rev']
    p1, p2, p3 = q1['prof'], q2['prof'], q3['prof']
    
    # 条件1：营收连续加速
    if not (r1 > r2 > r3):
        return False, f'营收未连续加速: {r1:.0f}>{r2:.0f}>{r3:.0f}'
    
    # 条件2：利润连续加速
    if not (p1 > p2 > p3):
        return False, f'利润未连续加速: {p1:.0f}>{p2:.0f}>{p3:.0f}'
    
    # 条件3：行业景气度 > 0
    sector_score = sector_rating.get(sector, {}).get('score', 0) if sector else 0
    if sector_score <= 0:
        return False, f'行业景气度={sector_score}，需>0'
    
    # 条件4：PE历史分位 < 50%
    pe_info = pe_pct_data.get(code, {})
    pe_pct = pe_info.get('pe_pct')
    if pe_pct is not None and pe_pct >= 50:
        return False, f'PE分位={pe_pct:.0f}%，需<50%'
    
    # 条件5：ROE > 15%
    roe = q1.get('roe', 0) or 0
    if roe < 15:
        return False, f'ROE={roe:.1f}%，需>15%'
    
    # 条件6：市值30-200亿（从外部判断，这里不检查）
    
    # 条件7：无资金流/事件风险
    rf = risk_flags.get(code, {})
    if rf.get('flow_risk'):
        return False, '有资金流风险标记'
    if rf.get('event_risk'):
        return False, '有事件风险标记'
    
    return True, '全部满足'

def scan_long_term_seeds(codes=None):
    """扫描当前候选池，找出长持种子"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    
    if codes is None:
        # 从候选池获取（统一从 double_up_scores 表读取）
        codes = [s['code'] for s in pool_loader.load_pool()]
    
    if not codes:
        print('无候选池数据')
        return []
    
    # 加载数据
    fins_data = fetch_financial_data(cur, codes)
    pe_pct_data = fetch_pe_pct(cur, codes)
    risk_flags = fetch_risk_flags(cur, codes)
    sector_rating = load_sector_rating()
    
    # 获取代码到名称映射
    cur.execute('SELECT code, name FROM stocks')
    names = {r[0]: r[1] for r in cur.fetchall()}
    
    results = []
    for code in codes:
        fins = fins_data.get(code, [])
        name = names.get(code, code)
        sector = get_sector_for_code(cur, code)
        
        if len(fins) < 3:
            results.append({
                'code': code, 'name': name, 'sector': sector,
                'status': '❌ 数据不足',
                'reason': f'仅{len(fins)}个季度财务数据，需≥3'
            })
            continue
        
        is_seed, reason = check_long_term_seed(code, fins, pe_pct_data, risk_flags, sector_rating, sector)
        
        # 检查市值条件
        
        # 检查市值条件
        mcap_pass = True
        if len(fins) >= 1:
            pe = fins[0].get('pe', 0) or 0
            pb = fins[0].get('pb', 0) or 0
            # 粗略估算市值（市净率×净资产）
            # 更准确：从stocks表取总股本
            cur.execute('SELECT total_shares_real FROM stocks WHERE code=?', (code,))
            ts = cur.fetchone()
            if ts and ts[0]:
                # 获取最新收盘价
                cur.execute('SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1', (code,))
                close = cur.fetchone()
                if close:
                    mcap = ts[0] * close[0] / 1e8
                    mcap_pass = 30 <= mcap <= 200
                    if not mcap_pass:
                        reason = f'市值{mcap:.0f}亿，需30-200亿'
        
        if is_seed and mcap_pass:
            results.append({
                'code': code,
                'name': name,
                'sector': sector,
                'status': '✅ 长持种子',
                'reason': reason,
                'roe': round(fins[0].get('roe', 0), 1) if len(fins) >= 1 else None,
                'pe_pct': pe_pct_data.get(code, {}).get('pe_pct'),
            })
        else:
            results.append({
                'code': code,
                'name': name,
                'sector': sector,
                'status': '❌ 不符合',
                'reason': reason,
            })
    
    conn.close()
    return results

def apply_long_mode_to_simulation(conn_sim, cur_sim, code):
    """将现有持仓切换为长持模式"""
    cur_sim.execute('''
        UPDATE trades SET hold_mode = 'long',
        stop_loss_pct = ?, take_profit_pct = NULL,
        take_profit_1 = NULL, take_profit_2 = NULL, take_profit_3 = NULL
        WHERE code = ? AND status IN ('持有','部分止盈')
    ''', (LONG_STOP_LOSS, code))
    conn_sim.commit()

def print_report(results):
    """输出扫描报告"""
    seeds = [r for r in results if r['status'] == '✅ 长持种子']
    nope = [r for r in results if r['status'] != '✅ 长持种子']
    
    print(f"\n{'='*55}")
    print(f"🌱 翻倍股长持种子扫描 | {date.today()}")
    print(f"{'='*55}")
    
    if seeds:
        print(f"\n✅ 长持种子 ({len(seeds)}只):")
        for s in seeds:
            print(f"  {s['code']} {s['name']:10s} {s['sector']:12s} ROE={s['roe']}% PE分位={s['pe_pct']}%")
            print(f"    -> {s['reason']}")
    
    print(f"\n❌ 不符合条件 ({len(nope)}只):")
    for s in nope:
        print(f"  {s['code']} {s['name']:10s} {s['status']} {s['reason']}")
    
    print(f"\n{'─'*55}")
    print(f"📌 长持种子规则:")
    print(f"   首仓: 总资金5% (普通模式2.5%)")
    print(f"   加仓: 可加至8%（回调至20日均线下方）")
    print(f"   止损: -15%极端保护止损（普通模式-8%）")
    print(f"   止盈: 取消技术面止盈（让利润奔跑）")
    print(f"   卖出: 基本面恶化 or 大盘跌破年线3日未收")
    print(f"{'='*55}")

if __name__ == '__main__':
    results = scan_long_term_seeds()
    print_report(results)
