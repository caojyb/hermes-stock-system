#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Portfolio Truth Layer（Phase 7.5 / Phase 8-H2）
======================================
真实账户资产事实层：cash + holdings_value = total_asset。
支持 MANUAL_CONFIRMATION 人工快照，不接券商 API。

原则：
- 不读 simulation
- 不猜现金/总资产
- 历史峰值从每日快照序列计算，不伪造
- drawdown 只在 peak_asset KNOWN 时计算
- Real Holdings ≠ Account Asset
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
import decision._local_constants as _local_constants
BITABLE_TOKEN = _local_constants.BITABLE_BASE_TOKEN
BASE_TOKEN = _local_constants.BITABLE_BASE_TOKEN
TABLE_ID = _local_constants.BITABLE_TABLE_ID

# Phase 8-H2: Real Holdings 唯一来源
REAL_HOLDINGS_SOURCE = "FEISHU_BITABLE"
REAL_HOLDINGS_BASE = _local_constants.REAL_HOLDINGS_BASE
REAL_HOLDINGS_TABLE = _local_constants.BITABLE_TABLE_ID

# 数据健康等级
VALID, STALE, PARTIAL, MISSING, UNKNOWN = 'VALID', 'STALE', 'PARTIAL', 'MISSING', 'UNKNOWN'
FRESH, EXPIRED = 'FRESH', 'EXPIRED'
READY = 'READY'

# Phase 8-H2: 三态独立状态机
class HoldingsStatus:
    """真实持仓状态：只反映 Bitable 持仓数据质量"""
    READY = 'READY'        # Bitable 读取成功且 >=1 持仓，关键字段有效
    EMPTY = 'EMPTY'        # Bitable 成功但无已买入持仓
    MISSING = 'MISSING'    # Bitable 读取失败

class AccountStatus:
    """账户资产状态：只反映 cash/total_asset 可用性"""
    READY = 'READY'        # 存在人工确认且 freshness=FRESH
    MISSING = 'MISSING'    # 无现金/总资产快照
    STALE = 'STALE'        # 快照过期
    EXPIRED = 'EXPIRED'    # 快照超期
    UNKNOWN = 'UNKNOWN'    # 未知

class PortfolioRiskStatus:
    """组合风险状态：只反映回撤/流动性"""
    READY = 'READY'        # 可以计算风险
    UNKNOWN = 'UNKNOWN'    # 缺资产历史

# A 股最小交易单位
LOT_SIZE = 100

# 默认历史序列路径
_DEFAULT_HISTORY_DB = SCRIPT_DIR / 'real_portfolio_history.db'

# Phase 8-H2: Bitable 字段索引常量（禁止散落数字索引）
BITABLE_FIELD_INDEX = {
    'CODE': 0,
    'NAME': 1,
    'AVG_COST': 2,
    'CURRENT_PRICE': 3,
    'BUY_STATUS': 4,
    'QUANTITY': 5,
    'BUY_DATE': 6,
    'SECTOR': 7,
}
_EXPECTED_FIELD_COUNT = len(BITABLE_FIELD_INDEX)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


# ── J0-H: DAILY_REAL_HOLDINGS_SNAPSHOT — 当日进程内单次读取缓存 ──
# 同一生产日首次 build_real_snapshot() 触发 lark-cli，后续调用复用同一 holdings。
# 读取失败不缓存（不伪装 READY）；跨日自动失效；显式注入 holdings 不经过缓存。
_DAILY_HOLDINGS_CACHE: dict | None = None
_DAILY_HOLDINGS_CACHE_DATE: str | None = None
DAILY_HOLDINGS_SCHEMA_VERSION = 'bitable_v1_fieldindex'


def get_daily_real_holdings(refresh: bool = False) -> tuple[list[dict], dict]:
    """当日真实持仓单次读取（J0-H）。

    返回 (holdings, cache_meta)。失败抛异常且不写缓存。
    cache_meta: {'cached': bool, 'captured_at': str, 'schema_version': str, 'source_hash': str}
    """
    global _DAILY_HOLDINGS_CACHE, _DAILY_HOLDINGS_CACHE_DATE
    today = _today_iso()
    if not refresh and _DAILY_HOLDINGS_CACHE is not None and _DAILY_HOLDINGS_CACHE_DATE == today:
        meta = dict(_DAILY_HOLDINGS_CACHE.get('_meta') or {})
        meta['cached'] = True
        return _DAILY_HOLDINGS_CACHE['holdings'], meta
    holdings = _read_bitable_holdings()
    import hashlib as _hashlib
    src_hash = _hashlib.sha256(
        json.dumps(holdings, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    _DAILY_HOLDINGS_CACHE = {
        'holdings': list(holdings),
        '_meta': {
            'cached': False,
            'captured_at': _now_iso(),
            'schema_version': DAILY_HOLDINGS_SCHEMA_VERSION,
            'source_hash': src_hash,
        },
    }
    _DAILY_HOLDINGS_CACHE_DATE = today
    return list(holdings), dict(_DAILY_HOLDINGS_CACHE['_meta'])


def reset_daily_real_holdings_cache() -> None:
    """测试/强制刷新用。"""
    global _DAILY_HOLDINGS_CACHE, _DAILY_HOLDINGS_CACHE_DATE
    _DAILY_HOLDINGS_CACHE = None
    _DAILY_HOLDINGS_CACHE_DATE = None


def _validate_field_order(records: list) -> None:
    """校验返回记录字段数量是否与 BITABLE_FIELD_INDEX 一致。"""
    if not records:
        return
    actual_len = len(records[0])
    if actual_len != _EXPECTED_FIELD_COUNT:
        raise RuntimeError(
            f"BITABLE_SCHEMA_WARNING: expected {_EXPECTED_FIELD_COUNT} fields, got {actual_len}. "
            f"Bitable schema may have changed; BITABLE_FIELD_INDEX needs update."
        )


def _read_bitable_holdings() -> list[dict]:
    """从 Bitable 读取真实持仓明细（仅 symbol/quantity/avg_cost/current_price/sector）。"""
    result = subprocess.run(
        ['lark-cli', 'base', '+record-list',
         '--base-token', BASE_TOKEN, '--table-id', TABLE_ID,
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

    # Phase 8-H2: 字段数量检查，防止 Bitable 结构漂移
    _validate_field_order(records)

    holdings = []
    for rec in records:
        buy_status = rec[BITABLE_FIELD_INDEX['BUY_STATUS']]
        if not (isinstance(buy_status, list) and '已买入' in buy_status):
            continue
        code = str(rec[BITABLE_FIELD_INDEX['CODE']]).strip()
        name = str(rec[BITABLE_FIELD_INDEX['NAME']]).strip()
        cost = float(rec[BITABLE_FIELD_INDEX['AVG_COST']] or 0)
        cur = float(rec[BITABLE_FIELD_INDEX['CURRENT_PRICE']] or 0)
        shares_raw = rec[BITABLE_FIELD_INDEX['QUANTITY']]
        sector = str(rec[BITABLE_FIELD_INDEX['SECTOR']] or '').strip() if len(rec) > BITABLE_FIELD_INDEX['SECTOR'] else ''
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
            holdings, cache_meta = get_daily_real_holdings()
            provenance['holdings_source'] = 'bitable'
            provenance['holdings_cache'] = cache_meta  # J0-H: cached/captured_at/source_hash
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

    # 2b. Data Quality Guard（Cost / Price / Quantity / Ratio 四层校验）
    try:
        from decision.real_portfolio_quality import check_portfolio_quality
        quality_report = check_portfolio_quality(detail)
    except Exception as e:
        quality_report = {'overall': 'UNKNOWN', 'flags': [], 'error_count': 0, 'warning_count': 0, 'guard_error': str(e)}

    # 3. Cash / Total Asset
    if source == 'MANUAL_CONFIRMATION' and (cash is not None or total_asset is not None):
        data_quality = VALID if cash is not None and total_asset is not None else PARTIAL
        # 禁止自动补齐缺失字段，保留 PARTIAL/UNKNOWN 语义
        # cash/total_asset 仅当显式提供时才赋值，否则保持 None
        provenance['manual_cash_provided'] = cash is not None
        provenance['manual_total_asset_provided'] = total_asset is not None
    else:
        # 自动源：当前只有 holdings_value，cash/total_asset 不可得
        cash = None
        total_asset = None
        data_quality = PARTIAL if detail else MISSING
        provenance['auto_cash_available'] = False
        provenance['auto_total_asset_available'] = False

    # 2c. Data Quality Guard 结果优先于自动推断
    qr = locals().get('quality_report', {})
    if qr.get('error_count', 0) > 0:
        data_quality = 'ERROR'
    elif qr.get('warning_count', 0) > 0 and data_quality == 'VALID':
        data_quality = 'WARNING'

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
        'quality_report': quality_report,
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
            freshness TEXT,
            quality_report_json TEXT
        )
    ''')
    try:
        cur.execute("ALTER TABLE real_asset_snapshots ADD COLUMN freshness TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE real_asset_snapshots ADD COLUMN quality_report_json TEXT")
    except Exception:
        pass
    p = snap.get('portfolio', {})
    prov = snap.get('provenance', {})
    cur.execute('''
        INSERT INTO real_asset_snapshots
        (snapshot_id, as_of_time, source, data_quality,
         cash, holdings_value, total_asset, position_count,
         drawdown, drawdown_status, peak_asset, peak_asset_date,
         provenance_json, created_at, freshness, quality_report_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        snap.get('snapshot_id'), snap.get('as_of_time'), snap.get('source'), snap.get('data_quality'),
        p.get('cash'), p.get('holdings_value'), p.get('total_asset'), p.get('position_count'),
        p.get('drawdown'), p.get('drawdown_status'), p.get('peak_asset'), p.get('peak_asset_date'),
        json.dumps(prov, ensure_ascii=False, default=str), _now_iso(), snap.get('freshness'),
        json.dumps(snap.get('quality_report', {}), ensure_ascii=False, default=str),
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


# Phase 8-H2: 三态独立状态机 =========================================================

def get_holdings_status(snap: dict | None = None) -> dict:
    """
    从 Real Snapshot 推导 Holdings Status（独立状态机）。
    READY: Bitable 读取成功且 >=1 持仓，关键字段有效
    EMPTY: Bitable 成功但无已买入持仓
    MISSING: Bitable 读取失败 / 快照本身失败
    """
    if snap is None:
        snap = build_real_snapshot()
    if not snap.get('ok'):
        return {'status': HoldingsStatus.MISSING, 'reason': snap.get('error', 'unknown')}
    holdings = snap.get('holdings', []) or []
    if not holdings:
        return {'status': HoldingsStatus.EMPTY, 'reason': 'no_holdings', 'count': 0}
    # 关键字段有效性检查
    invalid = [h for h in holdings if not (h.get('quantity', 0) > 0 and h.get('avg_cost', 0) > 0 and h.get('current_price', 0) > 0)]
    if invalid:
        return {'status': HoldingsStatus.MISSING, 'reason': 'invalid_holding_fields', 'invalid_count': len(invalid), 'count': len(holdings)}
    return {'status': HoldingsStatus.READY, 'reason': 'ok', 'count': len(holdings)}


def get_account_status(db_path: Path | None = None) -> dict:
    """
    从历史快照推导 Account Status（独立状态机）。
    READY: 存在人工确认且 freshness=FRESH
    MISSING: 无现金/总资产快照
    STALE: 快照过期
    EXPIRED: 快照超期
    UNKNOWN: 未知
    """
    r = get_account_readiness(db_path)
    status = r.get('status', UNKNOWN)
    if status == READY:
        s = AccountStatus.READY
    elif status in (STALE, EXPIRED):
        s = status
    else:
        s = AccountStatus.MISSING if status in (MISSING, PARTIAL) else AccountStatus.UNKNOWN
    return {
        'status': s,
        'reason': r.get('reason'),
        'snapshot_id': r.get('snapshot_id'),
        'as_of_time': r.get('as_of_time'),
        'cash': r.get('cash'),
        'total_asset': r.get('total_asset'),
        'freshness': r.get('freshness'),
        'data_quality': r.get('data_quality'),
    }


def get_portfolio_risk_status(db_path: Path | None = None) -> dict:
    """
    从历史快照推导 Portfolio Risk Status（独立状态机）。
    READY: 可以计算风险（有历史峰值或现价足够）
    UNKNOWN: 缺资产历史
    """
    db = Path(db_path) if db_path else _DEFAULT_HISTORY_DB
    today = _today_iso()
    if not db.exists():
        return {'status': PortfolioRiskStatus.UNKNOWN, 'reason': 'history_db_missing'}
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM real_asset_snapshots WHERE total_asset IS NOT NULL AND as_of_time <= ?', (today,))
    count = cur.fetchone()[0]
    conn.close()
    if count == 0:
        return {'status': PortfolioRiskStatus.UNKNOWN, 'reason': 'no_asset_history'}
    return {'status': PortfolioRiskStatus.READY, 'reason': 'ok', 'history_count': count}


def get_real_portfolio_metadata(snap: dict | None = None) -> dict:
    """
    生成 Real Holdings Source metadata。
    不修改 snap，只提取只读元数据。
    """
    if snap is None:
        snap = build_real_snapshot()
    holdings = snap.get('holdings', []) or []
    return {
        'source': REAL_HOLDINGS_SOURCE,
        'source_table': f"{REAL_HOLDINGS_BASE}/{REAL_HOLDINGS_TABLE}",
        'read_time': snap.get('timestamp'),
        'holding_count': len(holdings),
        'data_quality': snap.get('data_quality'),
        'holdings_status': get_holdings_status(snap).get('status'),
    }


if __name__ == '__main__':
    import json as _j
    s = build_real_snapshot()
    print(_j.dumps(s, ensure_ascii=False, indent=2, default=str)[:3000])
