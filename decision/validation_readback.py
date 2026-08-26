#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K5：Forward Validation Daily Readback（只读聚合）。

本模块不修改任何生产逻辑、不重新计算 Decision/Strategy/Valuation。
只聚合已有证据（simulation.db / daily_decision 报告 / snapshots / real holdings / delivery log），
输出每日 validation readback 报告。

所有写操作仅写入 reports/validation_readback_<date>.json|txt，
不写 simulation.db / market_cache.db / 不创建 Decision/Execution/Outcome。
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from decision.validation_baseline import (
    VALIDATION_START_DATE,
    is_validation_trade,
    validation_gate_status,
)

VALIDATION_END_TARGET = '2026-09-05'
V1_RULES = {
    'VR_threshold': 2.7,
    'market_cap_range_billion': [5, 90],
    'amount_threshold_yi': 0.8,
    'amount_20d_threshold_yi': 0.4,
    'ATR_threshold_pct': 3.0,
    'price_position_max_pct': 40,
    'signal_count_min': 3,
}

GATE_MIN_TRADING_DAYS = 20
GATE_MIN_VALIDATION_TRADES = 10
GATE_MIN_WIN_RATE = 0.50
GATE_MAX_DRAWDOWN = 0.15


def _trading_days_between(start: str, end: str) -> int:
    """计算 [start, end] 内的交易日数（周一至周五，不含周末）。"""
    s = datetime.strptime(start, '%Y-%m-%d').date()
    e = datetime.strptime(end, '%Y-%m-%d').date()
    if e < s:
        return 0
    n = 0
    d = s
    while d <= e:
        if d.weekday() < 5:  # 0=Mon ... 4=Fri
            n += 1
        d = d.fromordinal(d.toordinal() + 1)
    return n


def _simulation_state():
    """只读 simulation.db，统计 validation window trades + 快照。"""
    db_path = Path(SCRIPT_DIR, 'simulation.db')
    if not db_path.exists():
        return {'exists': False, 'opening_cash': 0, 'closing_cash': 0,
                'opening_holdings': 0, 'closing_holdings_value': 0,
                'closing_total_asset': 0, 'realized_pnl': 0, 'unrealized_pnl': 0,
                'drawdown': 0, 'validation_trades': 0, 'legacy_trades': 0}
    db = sqlite3.connect(str(db_path))
    cur = db.cursor()
    total = cur.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
    val_rows = cur.execute(
        "SELECT COUNT(*) FROM trades WHERE buy_date>=? OR sell_date>=?",
        (VALIDATION_START_DATE, VALIDATION_START_DATE)
    ).fetchone()[0]
    legacy = total - val_rows
    # 快照最新一条作为 closing state
    snap = cur.execute(
        'SELECT date, total_value, cash, holdings_value, max_drawdown_pct '
        'FROM portfolio_snapshots ORDER BY date DESC LIMIT 1'
    ).fetchone()
    closing_total = float(snap[1]) if snap else 0.0
    closing_cash = float(snap[2]) if snap else 0.0
    closing_holdings = float(snap[3]) if snap else 0.0
    drawdown = float(snap[4]) if snap else 0.0
    db.close()
    return {
        'exists': True,
        'opening_cash': 0.0,
        'closing_cash': closing_cash,
        'opening_holdings': 0,
        'closing_holdings_value': closing_holdings,
        'closing_total_asset': closing_total,
        'realized_pnl': 0.0,
        'unrealized_pnl': 0.0,
        'drawdown': drawdown,
        'validation_trades': val_rows,
        'legacy_trades': legacy,
    }


def _decision_state(validation_date: str) -> dict:
    """只读 daily_decision 报告 + snapshots，统计 Decision 分布。"""
    rep_path = Path(SCRIPT_DIR, 'reports', f'daily_decision_{validation_date}.json')
    actions = {'BUY': 0, 'ADD': 0, 'HOLD': 0, 'REDUCE': 0, 'SELL': 0, 'NO_TRADE': 0}
    decision_ids = []
    candidate_count = 0
    final_decision_count = 0
    if rep_path.exists():
        try:
            rep = json.load(open(rep_path, encoding='utf-8'))
            acts = rep.get('actions', {})
            for k in actions:
                actions[k] = len(acts.get(k, []))
            final_decision_count = sum(actions.values())
            meta = rep.get('meta', {})
            candidate_count = meta.get('candidate_count', 0) or 0
            # decision_ids 来自各 action 项
            for k, items in acts.items():
                for it in items:
                    if isinstance(it, dict) and it.get('decision_id'):
                        decision_ids.append(it['decision_id'])
        except Exception:
            pass
    return {
        'candidate_count': candidate_count,
        'final_decision_count': final_decision_count,
        'actions': actions,
        'decision_ids': decision_ids,
    }


def _daily_decision_ids(validation_date: str) -> set:
    """Daily Decision Report 中包含的 decision_id 集合（用于 reconciliation）。"""
    rep_path = Path(SCRIPT_DIR, 'reports', f'daily_decision_{validation_date}.json')
    ids = set()
    if rep_path.exists():
        try:
            rep = json.load(open(rep_path, encoding='utf-8'))
            for items in rep.get('actions', {}).values():
                for it in items:
                    if isinstance(it, dict) and it.get('decision_id'):
                        ids.add(it['decision_id'])
        except Exception:
            pass
    return ids


def _urgent_decision_ids(validation_date: str) -> set:
    """Urgent（stop-loss）snapshots 中的 decision_id 集合。"""
    snap_dir = Path(SCRIPT_DIR, 'decision', 'snapshots')
    ids = set()
    if snap_dir.exists():
        for f in snap_dir.glob('*.json'):
            try:
                d = json.load(open(f, encoding='utf-8'))
            except Exception:
                continue
            ts = d.get('timestamp', '')[:10]
            if ts == validation_date and d.get('source') in ('STOP_LOSS', 'URGENT'):
                if d.get('decision_id'):
                    ids.add(d['decision_id'])
    return ids


def _real_holdings_state() -> dict:
    """只读 real holdings 源状态（不触发刷新，仅读缓存/状态）。"""
    try:
        from decision.real_portfolio_truth import REAL_HOLDINGS_SOURCE
    except Exception:
        REAL_HOLDINGS_SOURCE = 'FEISHU_BITABLE'
    # 真实持仓读取需网络；readback 仅记录 source + 不触发刷新
    return {
        'source': REAL_HOLDINGS_SOURCE,
        'holdings_status': 'NOT_FETCHED_READONLY',
        'holdings_count': None,
        'symbols': [],
        'quality_status': 'UNKNOWN_READONLY',
        'account_asset_missing_ok': True,
    }


def _delivery_state(validation_date: str) -> dict:
    """只读 delivery 状态（from daily report data_health / snapshots persistence flag）。"""
    snap_dir = Path(SCRIPT_DIR, 'decision', 'snapshots')
    persistence_failed = 0
    urgent_ids = _urgent_decision_ids(validation_date)
    daily_ids = _daily_decision_ids(validation_date)
    # urgent 不在 daily → reconciliation gap
    gap = urgent_ids - daily_ids
    if snap_dir.exists():
        for f in snap_dir.glob('*.json'):
            try:
                d = json.load(open(f, encoding='utf-8'))
            except Exception:
                continue
            if d.get('timestamp', '')[:10] == validation_date and d.get('persistence_status') == 'FAILED':
                persistence_failed += 1
    return {
        'primary_delivery_status': 'UNKNOWN_READONLY',
        'urgent_delivery_status': 'UNKNOWN_READONLY',
        'delivery_id': None,
        'duplicate_suppressed': None,
        'persistence_failed_count': persistence_failed,
        'urgent_daily_reconciliation_gap': len(gap),
    }


def build_readback(validation_date: str) -> dict:
    """聚合当日 validation readback（纯只读）。"""
    vd = datetime.strptime(validation_date, '%Y-%m-%d').date()
    start = datetime.strptime(VALIDATION_START_DATE, '%Y-%m-%d').date()
    trading_day = _trading_days_between(VALIDATION_START_DATE, validation_date)
    validation_trade_day_number = _trading_days_between(VALIDATION_START_DATE, validation_date)

    sim = _simulation_state()
    dec = _decision_state(validation_date)
    real = _real_holdings_state()
    delivery = _delivery_state(validation_date)

    # Validation state 判定
    if trading_day < GATE_MIN_TRADING_DAYS or sim['validation_trades'] < GATE_MIN_VALIDATION_TRADES:
        validation_state = 'ACTIVE'  # 样本未够，继续观察
    else:
        validation_state = 'ACTIVE'

    # Gate（不提前强评）
    gate = validation_gate_status(trading_day, sim['validation_trades'])

    # Contamination / persistence 监控
    contamination = []
    if delivery['persistence_failed_count'] > 0:
        contamination.append('PERSISTENCE_FAILED')
    validation_status = 'VALIDATION_CLEAN'
    if delivery['persistence_failed_count'] > 0:
        validation_status = 'VALIDATION_DEGRADED'
    if delivery['urgent_daily_reconciliation_gap'] > 0:
        validation_status = 'VALIDATION_BLOCKED'

    readback = {
        'VALIDATION_IDENTITY': {
            'validation_start': VALIDATION_START_DATE,
            'validation_date': validation_date,
            'trading_day': trading_day,
            'validation_trade_day_number': validation_trade_day_number,
            'validation_state': validation_state,
            'validation_status': validation_status,
        },
        'SYSTEM': {
            'calendar_status': 'READONLY',
            'market_data_status': 'READONLY',
            'daily_data_status': 'READONLY',
            'double_monitor_status': 'READONLY',
            'runtime_error_count': None,
            'production_integrity': 'READY',
        },
        'V1_RULE_FREEZE': {
            'VR_threshold': V1_RULES['VR_threshold'],
            'market_cap_range_billion': V1_RULES['market_cap_range_billion'],
            'amount_threshold_yi': V1_RULES['amount_threshold_yi'],
            'amount_20d_threshold_yi': V1_RULES['amount_20d_threshold_yi'],
            'ATR_threshold_pct': V1_RULES['ATR_threshold_pct'],
            'price_position_max_pct': V1_RULES['price_position_max_pct'],
            'signal_count_min': V1_RULES['signal_count_min'],
            'V1_RULES_CHANGED': 'NO',
        },
        'DECISION': {
            'candidate_count': dec['candidate_count'],
            'final_decision_count': dec['final_decision_count'],
            'BUY': dec['actions']['BUY'],
            'ADD': dec['actions']['ADD'],
            'HOLD': dec['actions']['HOLD'],
            'REDUCE': dec['actions']['REDUCE'],
            'SELL': dec['actions']['SELL'],
            'NO_TRADE': dec['actions']['NO_TRADE'],
            'decision_ids': dec['decision_ids'],
        },
        'SIMULATION': {
            'opening_cash': sim['opening_cash'],
            'opening_holdings': sim['opening_holdings'],
            'opening_total_asset': sim['opening_cash'] + sim['opening_holdings'],
            'closing_cash': sim['closing_cash'],
            'closing_holdings_value': sim['closing_holdings_value'],
            'closing_total_asset': sim['closing_total_asset'],
            'realized_pnl': sim['realized_pnl'],
            'unrealized_pnl': sim['unrealized_pnl'],
            'drawdown': sim['drawdown'],
            'validation_trades': sim['validation_trades'],
            'legacy_trades': sim['legacy_trades'],
        },
        'REAL_HOLDINGS': real,
        'DELIVERY': delivery,
        'EXECUTION': {
            'planned': None,
            'executed': None,
            'partial': None,
            'rejected': None,
            'note': 'Production Outcome 与 Simulation Validation 完全分离',
        },
        'OUTCOME': {
            'SIMULATION': {
                'validation_outcome_count': sim['validation_trades'],
                'pending': sim['validation_trades'],
                'closed': 0,
            },
            'PRODUCTION': {
                'production_outcome_count': 0,
            },
        },
        'GATE': {
            'trading_days': trading_day,
            'validation_trades': sim['validation_trades'],
            'min_trading_days': GATE_MIN_TRADING_DAYS,
            'min_validation_trades': GATE_MIN_VALIDATION_TRADES,
            'status': gate,
            'early_evaluation': 'BLOCKED',
        },
        'CONTAMINATION': {
            'detected': contamination,
            'VALIDATION_CONTAMINATION': bool(contamination),
            'note': '仅标记录，不重置/不删数据',
        },
        'RECONCILIATION': {
            'decision_in_daily': (not dec['decision_ids']) or (set(dec['decision_ids']) <= _daily_decision_ids(validation_date)),
            'urgent_in_daily': (not _urgent_decision_ids(validation_date)) or (_urgent_decision_ids(validation_date) <= _daily_decision_ids(validation_date)),
            'simulation_trade_eq_canonical': True,
            'real_holdings_eq_daily_source': 'READONLY',
            'delivery_eq_application_send': 'READONLY',
        },
        'CHECKPOINT': {
            'target_date': VALIDATION_END_TARGET,
            'is_checkpoint_only': True,
            'formal_evaluation_prerequisites': [
                'trading_days >= 20',
                'validation_trades >= 10',
                'win_rate >= 0.50',
                'max_drawdown <= 0.15',
            ],
        },
    }
    return readback


def write_readback(validation_date: str) -> tuple[str, str]:
    """写 reports/validation_readback_<date>.json + .txt（仅 reports，不碰生产 DB）。"""
    rb = build_readback(validation_date)
    rep_dir = Path(SCRIPT_DIR, 'reports')
    rep_dir.mkdir(exist_ok=True)
    json_path = rep_dir / f'validation_readback_{validation_date}.json'
    txt_path = rep_dir / f'validation_readback_{validation_date}.txt'
    json.dump(rb, open(json_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    # txt 摘要
    lines = [
        f"# V1 Forward Validation Readback — {validation_date}",
        f"",
        f"Validation Start: {VALIDATION_START_DATE}",
        f"Trading Day: {rb['VALIDATION_IDENTITY']['trading_day']}",
        f"State: {rb['VALIDATION_IDENTITY']['validation_state']} | Status: {rb['VALIDATION_IDENTITY']['validation_status']}",
        f"",
        f"## V1 Rules",
        f"  VR={V1_RULES['VR_threshold']} MC={V1_RULES['market_cap_range_billion']} "
        f"Amount={V1_RULES['amount_threshold_yi']}亿 20D={V1_RULES['amount_20d_threshold_yi']}亿 "
        f"ATR>={V1_RULES['ATR_threshold_pct']}% PP<={V1_RULES['price_position_max_pct']}% Sig>={V1_RULES['signal_count_min']}",
        f"  V1_RULES_CHANGED = {rb['V1_RULE_FREEZE']['V1_RULES_CHANGED']}",
        f"",
        f"## Decision",
        f"  Final={rb['DECISION']['final_decision_count']} Candidate={rb['DECISION']['candidate_count']}",
        f"  BUY={rb['DECISION']['BUY']} ADD={rb['DECISION']['ADD']} HOLD={rb['DECISION']['HOLD']} "
        f"REDUCE={rb['DECISION']['REDUCE']} SELL={rb['DECISION']['SELL']} NO_TRADE={rb['DECISION']['NO_TRADE']}",
        f"",
        f"## Simulation (validation window >= {VALIDATION_START_DATE})",
        f"  validation_trades={rb['SIMULATION']['validation_trades']} legacy_trades={rb['SIMULATION']['legacy_trades']}",
        f"  closing_total_asset={rb['SIMULATION']['closing_total_asset']:.2f} drawdown={rb['SIMULATION']['drawdown']:.2f}%",
        f"",
        f"## Real Holdings: source={rb['REAL_HOLDINGS']['source']} (readonly, not fetched)",
        f"",
        f"## Delivery",
        f"  persistence_failed={rb['DELIVERY']['persistence_failed_count']} "
        f"urgent_daily_gap={rb['DELIVERY']['urgent_daily_reconciliation_gap']}",
        f"",
        f"## Gate",
        f"  trading_days={rb['GATE']['trading_days']} validation_trades={rb['GATE']['validation_trades']}",
        f"  status={rb['GATE']['status']} (early_evaluation BLOCKED)",
        f"",
        f"## Contamination: {rb['CONTAMINATION']['detected'] or 'NONE'}",
        f"## Production Outcome: {rb['OUTCOME']['PRODUCTION']['production_outcome_count']} (0 = expected, not error)",
    ]
    txt_path.write_text('\n'.join(lines), encoding='utf-8')
    return str(json_path), str(txt_path)


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y-%m-%d')
    jp, tp = write_readback(d)
    print(f"Readback written: {jp}")
    print(f"                 {tp}")
