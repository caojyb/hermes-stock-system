#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一持仓视图 — 合并 Bitable 真实持仓 + simulation.db 模拟持仓
=====================================================
输出一份完整的总资产/总盈亏/行业集中度报告。

用法：
  python3 portfolio_summary.py                     # 标准输出
  python3 portfolio_summary.py --json              # JSON 格式输出
  python3 portfolio_summary.py --send              # 推送到飞书
"""

import os
import sys
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

# ── 路径 ──
SCRIPT_DIR = Path(__file__).resolve().parent
_insert_path = str(SCRIPT_DIR.parent.parent.parent / 'skills/stock/stock-expert')
sys.path.insert(0, _insert_path)
try:
    from stock_db_paths import get_db_path
except ModuleNotFoundError:
    # 兜底：使用绝对路径
    _insert_path = '/home/caojy/.hermes/skills/stock/stock-expert'
    sys.path.insert(0, _insert_path)
    from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))
SIM_DB = str(get_db_path('simulation'))

# 飞书推送
FEISHU_SENDER = str(SCRIPT_DIR.parent / 'skills/stock/stock-expert/skills/feishu-bitable/feishu_sender.py')
FEISHU_CHAT_ID = "oc_88d1817efbb9f328f4376314ab7c8b05"


def get_sim_positions():
    """获取 simulation.db 中的持仓"""
    conn = sqlite3.connect(SIM_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT code, name, sector, buy_date, buy_price, buy_shares, buy_amount,
               signal_type, status
        FROM trades
        WHERE status IN ('持有', '部分止盈')
        ORDER BY buy_date
    """)
    rows = cur.fetchall()
    conn.close()

    positions = []
    for r in rows:
        code, name, sector, buy_date, buy_price, shares, amount, signal, status = r
        positions.append({
            'source': 'simulation',
            'code': code,
            'name': name,
            'sector': sector or '',
            'buy_date': buy_date,
            'buy_price': float(buy_price or 0),
            'shares': int(shares or 0),
            'cost': float(amount or 0),
            'signal_type': signal or '',
            'status': status,
        })
    return positions


def get_real_positions():
    """从飞书 Bitable 获取真实持仓"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR.parent / 'skills/stock/stock-expert/skills/feishu-bitable'))
        from bitable_reader import BitableReader
    except ImportError:
        print("[WARN] bitable_reader 不可用，跳过真实持仓")
        return []

    try:
        reader = BitableReader(limit=100)
        result = reader._execute_command()
        data = json.loads(result.stdout)
        fields = data['data']['fields']
        records_raw = data['data']['data']

        positions = []
        for raw in records_raw:
            record = dict(zip(fields, raw))
            status = record.get('是否买入', [])
            if isinstance(status, list) and '已买入' in status:
                code = str(record.get('股票ID', '')).strip()
                name = str(record.get('name', '')).strip()
                if not code or not name:
                    continue
                cost_price = float(record.get('买入价格', 0) or 0)
                current_price = float(record.get('现价', 0) or 0)
                shares = int(record.get('持仓数量', 0) or 0)
                sector_raw = record.get('所属板块', '?')
                sector = ','.join(sector_raw) if isinstance(sector_raw, list) else str(sector_raw)
                pnl_pct = float(record.get('盈亏率', 0) or 0)
                pnl_abs = float(record.get('盈亏', 0) or 0)

                # 重算盈亏（Bitable 数据可能不准）
                if cost_price > 0 and current_price > 0:
                    calc_pnl_pct = (current_price - cost_price) / cost_price * 100
                    calc_pnl_abs = (current_price - cost_price) * shares
                else:
                    calc_pnl_pct = pnl_pct
                    calc_pnl_abs = pnl_abs

                positions.append({
                    'source': 'bitable',
                    'code': code,
                    'name': name,
                    'sector': sector,
                    'buy_date': str(record.get('买入日期', '') or ''),
                    'buy_price': cost_price,
                    'current_price': current_price,
                    'shares': shares,
                    'cost': cost_price * shares if cost_price > 0 else 0,
                    'market_value': current_price * shares if current_price > 0 else 0,
                    'pnl_pct': calc_pnl_pct,
                    'pnl_abs': calc_pnl_abs,
                    'rsi': record.get('最新RSI', '?'),
                })
        return positions
    except Exception as e:
        print(f"[WARN] Bitable 读取失败: {e}")
        return []


def get_market_prices(codes):
    """从 market_cache.db 获取最新收盘价"""
    if not codes:
        return {}
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()
    prices = {}
    for code in codes:
        cur.execute("SELECT close, change_pct FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        row = cur.fetchone()
        if row:
            prices[code] = {'price': float(row[0]), 'change_pct': float(row[1] or 0)}
    conn.close()
    return prices


def summarize(positions, market_prices):
    """生成汇总报告"""
    total_cost = 0
    total_value = 0
    sector_exposure = {}
    exchange_totals = {'沪': 0, '深': 0, '北': 0, '其他': 0}

    lines = []
    lines.append(f"📊 统一持仓报告 | {date.today()}")
    lines.append(f"{'='*60}")
    lines.append(f"{'来源':<10} {'代码':<8} {'名称':<12} {'盈亏%':<8} {'市值':<10} {'板块':<12}")
    lines.append(f"{'-'*60}")

    for p in positions:
        code = p['code']
        name = p['name']
        sector = p.get('sector', '?')

        # 确定市场
        if code.startswith('6'):
            exchange = '沪'
        elif code.startswith('0') or code.startswith('3'):
            exchange = '深'
        elif code.startswith('8'):
            exchange = '北'
        else:
            exchange = '其他'
        exchange_totals[exchange] += 1

        if p['source'] == 'bitable':
            mkt = market_prices.get(code, {})
            current_price = mkt.get('price', p.get('current_price', 0))
            change = mkt.get('change_pct', 0)
            market_value = current_price * p['shares'] if current_price > 0 else 0
            cost = p['cost']
            pnl_pct = ((current_price - p['buy_price']) / p['buy_price'] * 100) if p['buy_price'] > 0 else 0
            pnl_abs = market_value - cost
            label = f"📗实#{p.get('rsi', '?')}"
            lines.append(f"{label:<10} {code:<8} {name:<12} {pnl_pct:>+6.1f}% {market_value:>8,.0f} {sector:<12}")
        else:
            mkt = market_prices.get(code, {})
            current_price = mkt.get('price', 0)
            change = mkt.get('change_pct', 0)
            market_value = current_price * p['shares'] if current_price > 0 else 0
            cost = p['cost']
            pnl_pct = ((current_price - p['buy_price']) / p['buy_price'] * 100) if p['buy_price'] > 0 else 0
            pnl_abs = market_value - cost
            sig = p.get('signal_type', '')
            label = f"📘模{sig}"
            lines.append(f"{label:<10} {code:<8} {name:<12} {pnl_pct:>+6.1f}% {market_value:>8,.0f} {sector:<12}")

        total_cost += cost
        total_value += market_value

        # 行业集中度
        if sector:
            sector_exposure[sector] = sector_exposure.get(sector, 0) + market_value

    lines.append(f"{'='*60}")
    lines.append(f"💰 总市值: {total_value:>10,.0f} 元")
    lines.append(f"📉 总成本: {total_cost:>10,.0f} 元")
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    lines.append(f"📈 总盈亏: {total_pnl:>+10,.0f} 元 ({total_pnl_pct:>+.1f}%)")
    lines.append(f"📊 持仓数: {len(positions)} 只 (真实 {sum(1 for p in positions if p['source']=='bitable')} / 模拟 {sum(1 for p in positions if p['source']=='simulation')})")
    lines.append(f"🏢 交易所: {', '.join(f'{k}{v}' for k, v in exchange_totals.items() if v > 0)}")

    lines.append(f"\n📊 行业集中度:")
    sorted_sectors = sorted(sector_exposure.items(), key=lambda x: -x[1])
    for sector, exposure in sorted_sectors:
        pct = exposure / total_value * 100 if total_value > 0 else 0
        bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
        warn = ' ⚠️超限' if pct > 30 else ''
        lines.append(f"  {sector:<12} {pct:>5.1f}% {bar}{warn}")

    return '\n'.join(lines), {
        'total_value': total_value,
        'total_cost': total_cost,
        'total_pnl': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'position_count': len(positions),
        'real_count': sum(1 for p in positions if p['source'] == 'bitable'),
        'sim_count': sum(1 for p in positions if p['source'] == 'simulation'),
        'sector_exposure': sector_exposure,
    }


def send_feishu(text):
    """推送到飞书"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR.parent / 'skills/stock/stock-expert/skills/feishu-bitable'))
        from feishu_sender import feishu_send_message
        feishu_send_message(FEISHU_CHAT_ID, text)
        print("✅ 已推送到飞书")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    send = '--send' in sys.argv
    as_json = '--json' in sys.argv

    sim_positions = get_sim_positions()
    real_positions = get_real_positions()
    all_positions = sim_positions + real_positions

    if not all_positions:
        print("⚠️ 无持仓数据")
        return

    # 获取所有持仓的最新市场价格
    all_codes = list(set(p['code'] for p in all_positions))
    market_prices = get_market_prices(all_codes)

    report_text, report_data = summarize(all_positions, market_prices)

    if as_json:
        print(json.dumps(report_data, ensure_ascii=False, indent=2))
    else:
        print(report_text)

    if send:
        send_feishu(report_text)


if __name__ == '__main__':
    main()
