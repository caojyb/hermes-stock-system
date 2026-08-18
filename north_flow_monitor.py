#!/usr/bin/env python3
"""
北向资金个股数据监控模块
=======================
数据源: push2delay.eastmoney.com f62字段（北向资金净买入）
功能:
1. 每日获取增持Top 50和减持Top 50
2. 与候选池交叉比对，标记北向资金流向
3. 连续3日减持标记暂缓
4. 北向资金概览（健康检查+周报）
"""
import os, sys, sqlite3, json, requests, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_loader
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

MKT_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SIM_DB = "/home/caojy/.hermes/scripts/cron/simulation.db"
NORTH_LOG = "/home/caojy/.hermes/scripts/cron/north_flow_log.json"

def fetch_north_top(limit=50):
    """
    获取北向资金增持Top N和减持Top N
    返回: (buy_top, sell_top)
    buy_top: [{'code':..., 'name':..., 'net_buy':..., 'hold_value':...}, ...]
    sell_top: 同上，net_buy为负值
    """
    url = "http://push2delay.eastmoney.com/api/qt/clist/get"
    base_params = {
        'pn': 1, 'pz': limit, 'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2, 'invt': 2,
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': 'f12,f14,f62,f71'
    }
    
    def parse_response(params):
        try:
            r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            items = r.json().get('data', {}).get('diff', [])
            result = []
            for item in items:
                code = item.get('f12', '')
                name = item.get('f14', '')
                net_buy = item.get('f62', 0) or 0
                hold_value = item.get('f71', 0) or 0
                if code:
                    result.append({
                        'code': code,
                        'name': name,
                        'net_buy': net_buy,  # 净买入额（元）
                        'hold_value': hold_value,  # 持仓市值（元）
                        'hold_pct': 0  # 持仓占比（需额外计算）
                    })
            return result
        except:
            return []
    
    # 增持Top（降序）
    buy_params = base_params.copy()
    buy_params['fid'] = 'f62'
    buy_params['po'] = 1  # 降序
    buy_top = parse_response(buy_params)
    
    # 减持Top（升序）
    sell_params = base_params.copy()
    sell_params['fid'] = 'f62'
    sell_params['po'] = 0  # 升序
    sell_top = parse_response(sell_params)
    
    return buy_top, sell_top

def update_north_flow_db(buy_top, sell_top):
    """更新数据库中的北向资金数据"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    
    today = date.today().isoformat()
    updated = 0
    
    # 更新indicators表的north_flow字段
    for item in buy_top:
        cur.execute("UPDATE indicators SET north_flow=? WHERE code=?", (item['net_buy'], item['code']))
        if cur.rowcount > 0:
            updated += 1
    for item in sell_top:
        cur.execute("UPDATE indicators SET north_flow=? WHERE code=?", (item['net_buy'], item['code']))
        if cur.rowcount > 0:
            updated += 1
    
    conn.commit()
    conn.close()
    return updated

def cross_check_with_pool(candidates, buy_top, sell_top):
    """
    与候选池交叉比对
    返回: (buy_matches, sell_matches, sell_3day)
    buy_matches: 候选池中出现在增持Top 50的
    sell_matches: 候选池中出现在减持Top 50的
    sell_3day: 连续3日出现在减持Top 50的
    """
    # 构建快速查找字典
    buy_map = {item['code']: item for item in buy_top}
    sell_map = {item['code']: item for item in sell_top}
    
    buy_matches = []
    sell_matches = []
    
    for s in candidates:
        code = s['code'] if isinstance(s, dict) else s
        if code in buy_map:
            b = buy_map[code]
            buy_matches.append({
                'code': code, 'name': s.get('name', '') if isinstance(s, dict) else code,
                'net_buy': b['net_buy'], 'hold_value': b['hold_value']
            })
        if code in sell_map:
            sl = sell_map[code]
            sell_matches.append({
                'code': code, 'name': s.get('name', '') if isinstance(s, dict) else code,
                'net_buy': sl['net_buy'], 'hold_value': sl['hold_value']
            })
    
    # 检查连续3日减持
    sell_3day = []
    north_log = load_north_log()
    today = date.today().isoformat()
    
    # 记录今日减持
    for sm in sell_matches:
        if sm['code'] not in north_log:
            north_log[sm['code']] = []
        north_log[sm['code']].append(today)
        # 保留最近7天
        north_log[sm['code']] = [d for d in north_log[sm['code']] if d >= (date.today()-timedelta(days=7)).isoformat()]
    
    # 检查连续3日
    for code, dates in north_log.items():
        if len(dates) >= 3:
            # 检查是否连续3个交易日
            sorted_dates = sorted(set(dates), reverse=True)
            if len(sorted_dates) >= 3:
                d1, d2, d3 = sorted_dates[0], sorted_dates[1], sorted_dates[2]
                if (datetime.strptime(d1, '%Y-%m-%d') - datetime.strptime(d3, '%Y-%m-%d')).days <= 5:
                    sell_3day.append(code)
    
    save_north_log(north_log)
    
    return buy_matches, sell_matches, sell_3day

def load_north_log():
    """加载北向资金历史日志"""
    if not os.path.exists(NORTH_LOG):
        return {}
    try:
        with open(NORTH_LOG) as f:
            return json.load(f)
    except:
        return {}

def save_north_log(log):
    """保存北向资金历史日志"""
    with open(NORTH_LOG, 'w') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def format_north_summary(buy_top, sell_top, buy_matches, sell_matches, sell_3day):
    """格式化北向资金概览"""
    lines = []
    lines.append("\n" + "=" * 55)
    lines.append("📊 北向资金概览")
    lines.append("=" * 55)
    
    # 增持Top 5
    lines.append(f"\n🏆 北向增持Top 5:")
    for item in buy_top[:5]:
        net = item['net_buy'] / 1e8
        hold = item['hold_value'] / 1e8
        lines.append(f"  +{item['name']:8s}({item['code']:6s}) 净买入{net:>5.1f}亿 持仓{hold:>5.1f}亿")
    
    # 减持Top 5
    lines.append(f"\n⛔ 北向减持Top 5:")
    for item in sell_top[:5]:
        net = abs(item['net_buy']) / 1e8
        hold = item['hold_value'] / 1e8
        lines.append(f"  -{item['name']:8s}({item['code']:6s}) 净卖出{net:>5.1f}亿 持仓{hold:>5.1f}亿")
    
    # 候选池交叉比对
    if buy_matches:
        lines.append(f"\n✅ 候选池北向增持({len(buy_matches)}只):")
        for m in buy_matches:
            net = m['net_buy'] / 1e4
            lines.append(f"  👍 {m['name']}({m['code']}) 净买入{net:.0f}万")
    
    if sell_matches:
        lines.append(f"\n⚠️ 候选池北向减持({len(sell_matches)}只):")
        for m in sell_matches:
            net = abs(m['net_buy']) / 1e4
            lines.append(f"  ⛔ {m['name']}({m['code']}) 净卖出{net:.0f}万")
    
    if sell_3day:
        lines.append(f"\n🔴 连续3日减持({len(sell_3day)}只):")
        for code in sell_3day:
            lines.append(f"  🚫 {code} 暂缓买入")
    
    return '\n'.join(lines)

def run(candidates=None):
    """
    主入口：获取北向资金数据 + 交叉比对
    """
    print("📊 北向资金监控...")
    
    # 获取数据
    buy_top, sell_top = fetch_north_top(50)
    print(f"  获取增持Top {len(buy_top)} / 减持Top {len(sell_top)}")
    
    # 更新数据库
    n = update_north_flow_db(buy_top, sell_top)
    print(f"  更新{n}只股票的北向资金数据")
    
    # 加载候选池（统一从 double_up_scores 表读取）
    if candidates is None:
        candidates = pool_loader.load_pool()
    
    if candidates:
        # 交叉比对
        buy_matches, sell_matches, sell_3day = cross_check_with_pool(candidates, buy_top, sell_top)
        
        print(f"  候选池交叉: 增持{buy_matches}只 / 减持{sell_matches}只")
        
        # 格式化输出
        summary = format_north_summary(buy_top, sell_top, buy_matches, sell_matches, sell_3day)
        print(summary)
        
        return {
            'buy_top': buy_top[:10],
            'sell_top': sell_top[:10],
            'buy_matches': buy_matches,
            'sell_matches': sell_matches,
            'sell_3day': sell_3day
        }
    
    return None

if __name__ == '__main__':
    run()