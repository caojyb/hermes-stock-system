#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Portfolio Truth Layer（Phase 5.5）
=======================================
从真实持仓源（当前 = 飞书 Bitable，平安证券截图为真）构建统一 Real Portfolio Snapshot，
作为 Portfolio Assessment / DecisionEngine 的可靠输入。

**REAL 与 SIMULATION 彻底分离**：本模块只读真实持仓源，绝不读取 simulation snapshot。
无法从真实源获得的数据 → DATA_UNAVAILABLE，不伪造、不从 simulation 猜。

真实源能力审计（Bitable 18 字段）：
  ✅ symbol/quantity/avg_cost/current_price/sector（所属板块）
  ❌ cash / total_asset / 历史净值 → DATA_UNAVAILABLE
  → drawdown 历史峰值缺失 → drawdown_status=UNKNOWN（不伪造）
"""
import json, subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

SCRIPT_DIR = Path(__file__).resolve().parent
BITABLE_TOKEN = os.environ.get('BITABLE_APP_TOKEN', '')
TABLE_ID = "tbluYAy8YJx36jpP"

# 数据健康等级
VALID, STALE, PARTIAL, MISSING, UNKNOWN = 'VALID', 'STALE', 'PARTIAL', 'MISSING', 'UNKNOWN'


def _read_bitable():
    """从 Bitable 读取真实持仓。返回 [{code,name,quantity,avg_cost,current_price}]。"""
    result = subprocess.run(
        ['lark-cli', 'base', '+record-list',
         '--base-token', BITABLE_TOKEN, '--table-id', TABLE_ID,
         '--field-id', '股票ID', '--field-id', 'name',
         '--field-id', '买入价格', '--field-id', '现价',
         '--field-id', '是否买入', '--field-id', '买入数量',
         '--field-id', '买入时间', '--field-id', '所属板块',
         '--limit', '100', '--format', 'json'],
        capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli 失败: {result.stderr[:200]}")
    data = json.loads(result.stdout)
    records = data.get('data', {}).get('data', []) or []
    positions = []
    for rec in records:
        code = str(rec[0]).strip()
        name = str(rec[1]).strip()
        cost = float(rec[2] or 0)
        cur = float(rec[3] or 0)
        buy_status = rec[4]
        shares_raw = rec[5]
        sector = str(rec[7] or '').strip() if len(rec) > 7 else ''
        if isinstance(buy_status, list) and '已买入' in buy_status:
            shares = 0
            if shares_raw:
                try:
                    shares = int(float(str(shares_raw).replace(',', '')))
                except (ValueError, TypeError):
                    shares = 0
            positions.append({'code': code, 'name': name, 'quantity': shares,
                              'avg_cost': cost, 'current_price': cur, 'sector': sector})
    return positions


def build_real_snapshot(holdings=None, source='bitable', source_timestamp=None,
                        stale_after_hours=24):
    """构建 Real Portfolio Snapshot。

    holdings: 若 None 则从 Bitable 读取；否则用注入的持仓（测试/隔离）。
    返回 snapshot dict。绝不读 simulation。
    """
    now = datetime.now(timezone.utc).isoformat()
    as_of = date.today().isoformat()
    if holdings is None:
        try:
            holdings = _read_bitable()
        except Exception as e:
            return {'ok': False, 'error': f'真实持仓读取失败: {e}',
                    'data_health': MISSING, 'snapshot_id': '', 'timestamp': now,
                    'source': source, 'as_of_time': as_of}
    if not holdings:
        return {'ok': True, 'snapshot_id': '', 'timestamp': now, 'source': source,
                'as_of_time': as_of, 'data_health': MISSING, 'holdings': [],
                'portfolio': {}, 'provenance': {}}

    # 明细计算
    detail = []
    total_holdings_value = 0.0
    sector_exposure = {}
    position_count = 0
    for h in holdings:
        qty = h.get('quantity') or 0
        cost = h.get('avg_cost') or 0
        price = h.get('current_price') or 0
        mv = qty * price
        pnl = mv - qty * cost
        total_holdings_value += mv
        if mv > 0:
            position_count += 1
            s = h.get('sector', '') or ''
            sector_exposure[s] = sector_exposure.get(s, 0) + 1
        detail.append({
            'symbol': h['code'], 'name': h.get('name', ''),
            'quantity': qty, 'avg_cost': cost, 'current_price': price,
            'market_value': round(mv, 2),
            'unrealized_pnl': round(pnl, 2),
            'position_pct': None,  # 相对总资产占比 → DATA_UNAVAILABLE（无 total_asset）
            'sector': h.get('sector', ''),
        })
    # 相对持仓市值口径的 position_pct（非总资产占比，明确标注）
    for d in detail:
        if total_holdings_value > 0:
            d['position_pct_holdings'] = round(d['market_value'] / total_holdings_value, 4)
        else:
            d['position_pct_holdings'] = 0.0

    # 数据健康
    if all(d['quantity'] > 0 and d['avg_cost'] > 0 and d['current_price'] > 0 for d in detail):
        health = VALID
    elif any(d['quantity'] > 0 or d['avg_cost'] > 0 for d in detail):
        health = PARTIAL
    else:
        health = MISSING
    # 时效
    if source_timestamp and holdings:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(source_timestamp)).total_seconds() / 3600
            if age_h > stale_after_hours:
                health = STALE
        except Exception:
            pass

    snapshot_id = f"real_{now[:10].replace('-','')}_{uuid4().hex[:8]}"
    return {
        'ok': True, 'snapshot_id': snapshot_id, 'timestamp': now, 'as_of_time': as_of,
        'source': source, 'source_timestamp': source_timestamp or now,
        'data_health': health,
        'holdings': detail,
        'portfolio': {
            'total_holdings_value': round(total_holdings_value, 2),
            'cash': 'DATA_UNAVAILABLE',
            'total_asset': 'DATA_UNAVAILABLE',
            'invested_value': round(total_holdings_value, 2),
            'exposure': round(total_holdings_value / total_holdings_value, 4) if total_holdings_value else 0,
            'position_count': position_count,
            'sector_exposure': sector_exposure,
            # 真实仓历史峰值缺失 → drawdown 无法计算，不伪造
            'drawdown': None,
            'drawdown_status': UNKNOWN,
            'drawdown_reason': 'HISTORICAL_BASELINE_INCOMPLETE（无真实账户历史净值）',
        },
        'provenance': {
            'source': source, 'source_timestamp': source_timestamp or now, 'snapshot_id': snapshot_id,
        },
    }


def snapshot_portfolio_context(snap):
    """从 Real Snapshot 提取 Portfolio Assessment 输入。"""
    p = snap.get('portfolio', {})
    return {
        'position_count': p.get('position_count', 0),
        'sector_counts': p.get('sector_exposure', {}),
        'total_holdings_value': p.get('total_holdings_value', 0),
        'drawdown': p.get('drawdown'),
        'drawdown_status': p.get('drawdown_status', UNKNOWN),
    }


if __name__ == '__main__':
    import json as _j
    s = build_real_snapshot()
    print(_j.dumps(s, ensure_ascii=False, indent=2, default=str)[:2500])
