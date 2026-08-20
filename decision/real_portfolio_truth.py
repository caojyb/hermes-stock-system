#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Portfolio Truth Layer（Phase 7.5）
======================================
真实账户资产事实层：cash + holdings_value = total_asset。
支持 MANUAL_CONFIRMATION 人工快照，不接券商 API。

原则：
- 不读 simulation
- 不猜现金/总资产
- 历史峰值从每日快照序列计算，不伪造
- drawdown 只在 peak_asset KNOWN 时计算
"""
from __future__ import annotations

import json
import os
import subprocess
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

SCRIPT_DIR = Path(__file__).resolve().parent
BITABLE_TOKEN = os.environ.get('BITABLE_APP_TOKEN', '')
TABLE_ID = "tbluYAy8YJx36jpP"

# 数据健康等级
VALID, STALE, PARTIAL, MISSING, UNKNOWN = 'VALID', 'STALE', 'PARTIAL', 'MISSING', 'UNKNOWN'
FRESH, EXPIRED = 'FRESH', 'EXPIRED'
READY = 'READY'
READY_PARTIAL, READY_STALE, READY_EXPIRED, READY_MISSING, READY_UNKNOWN = 'PARTIAL', 'STALE', 'EXPIRED', 'MISSING', 'UNKNOWN'

# A 股最小交易单位
LOT_SIZE = 100

# 默认历史序列路径
_DEFAULT_HISTORY_DB = SCRIPT_DIR / 'real_portfolio_history.db'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def _read_bitable_holdings() -> list[dict]:
    """从 Bitable 读取真实持仓明细（仅 symbol/quantity/avg_cost/current_price/sector）。"""
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
    holdings = []
    for rec in records:
        buy_status = rec[4]
        if not (isinstance(buy_status, list) and '已买入' in buy_status):
            continue
        code = str(rec[0]).strip()
        name = str(rec[1]).strip()
        cost = float(rec[2] or 0)
        cur = float(rec[3] or 0)
        shares_raw = rec[5]
        sector = str(rec[7] or '').strip() if len(rec) > 7 else ''
        shares = 0
        if shares_raw:
            try:
                shares = int(float(str(shares_raw).replace(',', '')))
            except (ValueError, TypeError):
                shares = 0
        holdings.append({
            'code': code, 'name': name, 'quantity': shares,
            'avg_cost': cost, 'current_price': cur, 'sector': sector,
        })
    return holdings


def build_real_snapshot(
    holdings: list[dict] | None = None,
    cash: float | None = None,
    total_asset: float | None = None,
    available_cash: float | None = None,
    source: str = 'bitable',
    source_timestamp: str | None = None,
    stale_after_hours: float = 24,
    entered_by: str = '',
    confirmation_note: str = '',
    db_path: Path | None = None,
) -> dict:
    """
    构建真实账户资产快照。

    优先级：
    1. 显式注入 cash/total_asset（MANUAL_CONFIRMATION）
    2. Bitable 读取持仓 → holdings_value
    3. 两者都未知 → total_asset = UNKNOWN

    返回：
    {
      ok, snapshot_id, timestamp, as_of_time, source, data_quality, freshness,
      holdings: [...],
      portfolio: {
        cash, available_cash, holdings_value, total_asset,
        position_count, sector_exposure, exposure,
        drawdown, drawdown_status, peak_asset, peak_asset_date,
        position_pct_holdings, ...
      },
      provenance: {...}
    }
    """
    now = _now_iso()
    as_of = _today_iso()
    snapshot_id = f"real_{as_of.replace('-','')}_{uuid4().hex[:8]}"
    provenance = {
        'source': source,
        'source_timestamp': source_timestamp or now,
        'snapshot_id': snapshot_id,
        'entered_by': entered_by,
        'confirmation_note': confirmation_note,
        'is_manual': source == 'MANUAL_CONFIRMATION',
    }

    # 1. Holdings
    if holdings is None:
        try:
            holdings = _read_bitable_holdings()
            provenance['holdings_source'] = 'bitable'
        except Exception as e:
            return {
                'ok': False, 'error': f'真实持仓读取失败: {e}',
                'data_quality': MISSING, 'freshness': UNKNOWN,
                'snapshot_id': snapshot_id, 'timestamp': now, 'as_of_time': as_of,
                'source': source, 'holdings': [], 'portfolio': {}, 'provenance': provenance,
            }
    else:
        provenance['holdings_source'] = 'injected'

    # 2. Holdings value
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
            'market_value': round(mv, 2), 'unrealized_pnl': round(pnl, 2),
            'position_pct': None,
            'position_pct_holdings': 0.0,
            'sector': h.get('sector', ''),
        })

    for d in detail:
        if total_holdings_value > 0:
            d['position_pct_holdings'] = round(d['market_value'] / total_holdings_value, 4)

    # 3. Cash / Total Asset
    if source == 'MANUAL_CONFIRMATION' and (cash is not None or total_asset is not None):
        data_quality = VALID if cash is not None and total_asset is not None else PARTIAL
        cash = cash if cash is not None else (total_asset - total_holdings_value if total_asset is not None else None)
        if total_asset is None:
            total_asset = (cash or 0) + total_holdings_value
        provenance['manual_cash_provided'] = cash is not None
        provenance['manual_total_asset_provided'] = total_asset is not None
    else:
        # 自动源：当前只有 holdings_value，cash/total_asset 不可得
        cash = None
        total_asset = None
        data_quality = PARTIAL if detail else MISSING
        provenance['auto_cash_available'] = False
        provenance['auto_total_asset_available'] = False

    exposure = 0.0
    if total_asset and total_asset > 0:
        exposure = round(total_holdings_value / total_asset, 4)

    # 4. Freshness
    if source_timestamp:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(source_timestamp)).total_seconds() / 3600
            freshness = FRESH if age_h <= stale_after_hours else EXPIRED
            if freshness == EXPIRED:
                data_quality = STALE
        except Exception:
            freshness = UNKNOWN
    else:
        freshness = UNKNOWN

    # 5. Historical peak / drawdown（从历史序列读）
    peak_asset, peak_asset_date, drawdown, drawdown_status = _load_peak_and_drawdown(as_of)

    portfolio = {
        'cash': cash,
        'available_cash': available_cash if available_cash is not None else cash,
        'holdings_value': round(total_holdings_value, 2),
        'total_asset': total_asset,
        'invested_value': round(total_holdings_value, 2),
        'exposure': exposure,
        'position_count': position_count,
        'sector_exposure': sector_exposure,
        'drawdown': drawdown,
        'drawdown_status': drawdown_status,
        'peak_asset': peak_asset,
        'peak_asset_date': peak_asset_date,
    }

    return {
        'ok': True, 'snapshot_id': snapshot_id, 'timestamp': now, 'as_of_time': as_of,
        'source': source, 'data_quality': data_quality, 'freshness': freshness,
        'holdings': detail, 'portfolio': portfolio, 'provenance': provenance,
    }


def record_asset_snapshot(snap: dict, db_path: Path | None = None) -> str:
    """将资产快照写入历史序列表（每日可多次）。"""
    db = Path(db_path) if db_path else _DEFAULT_HISTORY_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS real_asset_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            as_of_time TEXT,
            source TEXT,
            data_quality TEXT,
            cash REAL,
            holdings_value REAL,
            total_asset REAL,
            position_count INTEGER,
            drawdown REAL,
            drawdown_status TEXT,
            peak_asset REAL,
            peak_asset_date TEXT,
            provenance_json TEXT,
            created_at TEXT,
            freshness TEXT
        )
    ''')
    try:
        cur.execute("ALTER TABLE real_asset_snapshots ADD COLUMN freshness TEXT")
    except Exception:
        pass
    p = snap.get('portfolio', {})
    prov = snap.get('provenance', {})
    cur.execute('''
        INSERT INTO real_asset_snapshots
        (snapshot_id, as_of_time, source, data_quality,
         cash, holdings_value, total_asset, position_count,
         drawdown, drawdown_status, peak_asset, peak_asset_date,
         provenance_json, created_at, freshness)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        snap.get('snapshot_id'), snap.get('as_of_time'), snap.get('source'), snap.get('data_quality'),
        p.get('cash'), p.get('holdings_value'), p.get('total_asset'), p.get('position_count'),
        p.get('drawdown'), p.get('drawdown_status'), p.get('peak_asset'), p.get('peak_asset_date'),
        json.dumps(prov, ensure_ascii=False, default=str), _now_iso(), snap.get('freshness'),
    ))
    conn.commit()
    conn.close()
    return snap.get('snapshot_id', '')


def _load_peak_and_drawdown(as_of_date: str, db_path: Path | None = None) -> tuple[float | None, str | None, float | None, str]:
    """从历史序列计算 peak_asset 和 drawdown。"""
    db = Path(db_path) if db_path else _DEFAULT_HISTORY_DB
    if not db.exists():
        return None, None, None, UNKNOWN
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('''
        SELECT as_of_time, total_asset FROM real_asset_snapshots
        WHERE total_asset IS NOT NULL AND as_of_time <= ?
        ORDER BY as_of_time DESC
    ''', (as_of_date,))
    rows = [r for r in cur.fetchall() if r[1] is not None]
    conn.close()
    if not rows:
        return None, None, None, UNKNOWN
    peak_asset = max(r[1] for r in rows)
    peak_asset_date = max(r for r in rows if r[1] == peak_asset)[0]
    latest_total = rows[0][1]
    if peak_asset > 0:
        drawdown = (peak_asset - latest_total) / peak_asset
    else:
        drawdown = None
    return peak_asset, peak_asset_date, drawdown, 'KNOWN' if peak_asset_date else UNKNOWN


def snapshot_portfolio_context(snap: dict) -> dict:
    """从 Real Snapshot 提取 Portfolio Assessment 输入。"""
    p = snap.get('portfolio', {})
    return {
        'position_count': p.get('position_count', 0),
        'sector_counts': p.get('sector_exposure', {}),
        'total_holdings_value': p.get('total_holdings_value', 0),
        'total_asset': p.get('total_asset'),
        'cash': p.get('cash'),
        'drawdown': p.get('drawdown'),
        'drawdown_status': p.get('drawdown_status', UNKNOWN),
        'peak_asset': p.get('peak_asset'),
        'peak_asset_date': p.get('peak_asset_date'),
    }


#  convenience：真实仓每日快照入口
def run_daily_snapshot(holdings: list[dict] | None = None,
                       cash_manual: float | None = None,
                       total_asset_manual: float | None = None,
                       entered_by: str = 'manual') -> dict:
    """每日真实账户快照。"""
    snap = build_real_snapshot(
        holdings=holdings,
        cash=cash_manual,
        total_asset=total_asset_manual,
        source='MANUAL_CONFIRMATION' if cash_manual is not None or total_asset_manual is not None else 'bitable',
        entered_by=entered_by,
    )
    if snap.get('ok'):
        record_asset_snapshot(snap)
    return snap


def get_account_readiness(db_path: Path | None = None) -> dict:
    """
    读取今日最新账户快照，返回 readiness 状态。
    READY: cash/total_asset 均有效且 freshness=FRESH
    PARTIAL: 部分有效但不能完整计算
    STALE/EXPIRED/MISSING/UNKNOWN: 对应状态
    """
    db = Path(db_path) if db_path else _DEFAULT_HISTORY_DB
    today = _today_iso()
    if not db.exists():
        return {'status': 'MISSING', 'reason': 'history_db_missing', 'as_of_time': today, 'snapshot_id': None, 'total_asset': None, 'cash': None, 'freshness': UNKNOWN, 'data_quality': MISSING}
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute('''
        SELECT snapshot_id, as_of_time, source, data_quality, cash, total_asset, freshness, provenance_json
        FROM real_asset_snapshots
        WHERE as_of_time = ?
        ORDER BY created_at DESC
        LIMIT 1
    ''', (today,))
    row = cur.fetchone()
    con.close()
    if not row:
        return {'status': 'MISSING', 'reason': 'no_snapshot_today', 'as_of_time': today, 'snapshot_id': None, 'total_asset': None, 'cash': None, 'freshness': UNKNOWN, 'data_quality': MISSING}
    snapshot_id, as_of, source, dq, cash, total_asset, freshness, prov_json = row
    if dq == MISSING or cash is None or total_asset is None:
        return {'status': 'PARTIAL', 'reason': 'missing_cash_or_total_asset', 'as_of_time': as_of, 'snapshot_id': snapshot_id, 'total_asset': total_asset, 'cash': cash, 'freshness': freshness, 'data_quality': dq}
    if freshness == EXPIRED:
        return {'status': 'EXPIRED', 'reason': 'snapshot_expired', 'as_of_time': as_of, 'snapshot_id': snapshot_id, 'total_asset': total_asset, 'cash': cash, 'freshness': freshness, 'data_quality': dq}
    if freshness == STALE or dq == STALE:
        return {'status': 'STALE', 'reason': 'snapshot_stale', 'as_of_time': as_of, 'snapshot_id': snapshot_id, 'total_asset': total_asset, 'cash': cash, 'freshness': freshness, 'data_quality': dq}
    if freshness == UNKNOWN:
        return {'status': 'UNKNOWN', 'reason': 'freshness_unknown', 'as_of_time': as_of, 'snapshot_id': snapshot_id, 'total_asset': total_asset, 'cash': cash, 'freshness': freshness, 'data_quality': dq}
    return {'status': READY, 'reason': 'ok', 'as_of_time': as_of, 'snapshot_id': snapshot_id, 'total_asset': total_asset, 'cash': cash, 'freshness': freshness, 'data_quality': dq}


if __name__ == '__main__':
    import json as _j
    s = build_real_snapshot()
    print(_j.dumps(s, ensure_ascii=False, indent=2, default=str)[:3000])
