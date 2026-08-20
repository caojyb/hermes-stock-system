#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Decision Contract（Phase 7.6）
====================================
只读聚合层：从已有 Decision Snapshot / Real Portfolio / Market Context
生成统一的 Daily Actionable Decision Output。

严格只做展示，不调用 DecisionEngine.decide()，不重新计算任何决策。
"""
from __future__ import annotations

import json, os, sqlite3, sys, glob
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')
sys.path.insert(0, str(SCRIPT_DIR.parent.parent / 'skills/stock/stock-expert'))
from decision.contract import Decision
from decision import snapshot as snap
from decision.real_portfolio_truth import build_real_snapshot, snapshot_portfolio_context
from decision.real_sizing import compute_real_position_sizing, check_sizing_for_action, BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE, READY, BLOCKED
from stock_strategy_config import get_market_env_scale
from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))
SNAP_DIR = os.path.join(str(SCRIPT_DIR), 'snapshots')


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _today_str() -> str:
    return date.today().isoformat()


def load_today_snapshots(today: str | None = None) -> list[dict]:
    today = today or _today_str()
    out = []
    if not os.path.isdir(SNAP_DIR):
        return out
    for fp in sorted(glob.glob(os.path.join(SNAP_DIR, '*.json'))):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if d.get('timestamp', '').startswith(today):
                out.append(d)
        except Exception:
            pass
    return out


def load_today_sim_trades(today: str | None = None, sim_db: str | None = None) -> list[dict]:
    today = today or _today_str()
    sim_db = sim_db or str(get_db_path('simulation'))
    out = []
    if not os.path.exists(sim_db):
        return out
    try:
        con = sqlite3.connect(sim_db)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            SELECT code, name, sector, buy_date, buy_price, buy_shares, buy_amount,
                    sell_date, sell_price, sell_amount, status, signal_type, strategy,
                    decision_id, exit_reason
            FROM trades
            WHERE buy_date=? OR sell_date=?
        """, (today, today))
        for r in cur.fetchall():
            out.append({k: r[k] for k in r.keys()})
        con.close()
    except Exception:
        pass
    return out


def classify_actions(snapshots: list[dict], sim_trades: list[dict]) -> dict:
    actions = defaultdict(list)
    sim_map = {t['decision_id']: t for t in sim_trades if t.get('decision_id')}

    for d in snapshots:
        action = d.get('action', 'NO_TRADE')
        entry = d.get('entry', {}) or {}
        portfolio = d.get('portfolio', {}) or {}
        risk = d.get('risk', {}) or {}

        item = {
            'decision_id': d.get('decision_id'),
            'symbol': d.get('symbol'),
            'name': d.get('name'),
            'strategy': d.get('strategy'),
            'timestamp': d.get('timestamp'),
            'action': action,
            'reason_codes': d.get('reason_codes', []) or [],
            'explanation': d.get('explanation', ''),
            'regime': d.get('regime_label'),
            'permission': d.get('permission'),
            'portfolio_risk': d.get('portfolio_risk'),
            'entry': {
                'entry_signal': entry.get('entry_signal'),
                'entry_price': entry.get('entry_price'),
                'planned_entry_time': entry.get('planned_entry_time'),
                'target_position': entry.get('target_position'),
            },
            'risk': {
                'stop_loss': risk.get('stop_loss'),
                'take_profit': risk.get('take_profit'),
                'trailing_stop': risk.get('trailing_stop'),
            },
            'sizing_status': 'READY',
            'target_value': entry.get('target_position'),
            'target_quantity': None,
            'delta_value': None,
            'delta_quantity': None,
        }

        # sizing（仅对 BUY/ADD/SELL/REDUCE 计算）
        if action in (BUY, ADD, SELL, REDUCE):
            ref_price = entry.get('entry_price') or entry.get('reference_price')
            total_asset = portfolio.get('total_asset')
            current_mv = portfolio.get('current_position_value') or portfolio.get('current_position')
            cash = portfolio.get('cash')
            target_pct = None
            if action == BUY:
                target_pct = entry.get('target_position_pct') or 0.025
            elif action == SELL:
                target_pct = 0.0
            elif action == REDUCE:
                target_pct = entry.get('target_position_pct') or 0.0

            if total_asset is not None and ref_price:
                try:
                    sz = compute_real_position_sizing(
                        total_asset=float(total_asset),
                        current_market_value=float(current_mv or 0),
                        cash=float(cash or 0),
                        target_position_pct=float(target_pct or 0),
                        reference_price=float(ref_price),
                    )
                    item['target_value'] = sz.get('target_value')
                    item['target_quantity'] = sz.get('target_quantity')
                    item['delta_value'] = sz.get('delta_value')
                    item['delta_quantity'] = sz.get('delta_quantity')
                    item['sizing_status'] = sz.get('sizing_status', 'READY')
                except Exception:
                    item['sizing_status'] = 'PARTIAL'
            else:
                item['sizing_status'] = 'BLOCKED' if action in (BUY, ADD) else 'PARTIAL'
                if total_asset is None:
                    item['target_value'] = None
                    item['target_quantity'] = None

        if action in (BUY, ADD, HOLD, REDUCE, SELL, NO_TRADE):
            actions[action].append(item)
        else:
            actions[NO_TRADE].append(item)
    return actions


def build_real_portfolio_section() -> dict:
    snap = build_real_snapshot()
    p = snap.get('portfolio', {}) or {}
    ctx = snapshot_portfolio_context(snap)
    return {
        'snapshot_id': snap.get('snapshot_id'),
        'as_of_time': snap.get('as_of_time'),
        'source': snap.get('source'),
        'data_quality': snap.get('data_quality'),
        'freshness': snap.get('freshness'),
        'holdings': snap.get('holdings', []),
        'position_count': p.get('position_count', 0),
        'holdings_value': p.get('holdings_value'),
        'cash': p.get('cash'),
        'available_cash': p.get('available_cash'),
        'total_asset': p.get('total_asset'),
        'exposure': p.get('exposure'),
        'drawdown': p.get('drawdown'),
        'drawdown_status': p.get('drawdown_status'),
        'peak_asset': p.get('peak_asset'),
        'peak_asset_date': p.get('peak_asset_date'),
        'sector_exposure': p.get('sector_exposure', {}),
        'provenance': snap.get('provenance', {}),
    }


def build_market_section() -> dict:
    try:
        env_scale, env_label, env_total = get_market_env_scale()
    except Exception:
        env_scale, env_label, env_total = None, 'UNKNOWN', None
    return {
        'regime_label': env_label,
        'regime_score': env_total,
        'position_scale': env_scale,
        'as_of_time': _now_iso(),
    }


def build_data_health_section() -> dict:
    section = {
        'market_regime': 'VALID',
        'permission': 'VALID',
        'portfolio': 'VALID',
        'real_asset_snapshot': 'VALID',
        'candidate': 'VALID',
        'price': 'VALID',
    }
    try:
        rp = build_real_portfolio_section()
        if rp.get('data_quality') in ('STALE', 'EXPIRED'):
            section['real_asset_snapshot'] = rp['data_quality']
        if rp.get('total_asset') is None:
            section['real_asset_snapshot'] = 'PARTIAL'
    except Exception:
        section['real_asset_snapshot'] = 'MISSING'
    return section


def build_decision_summary(actions: dict) -> dict:
    return {
        'total_decisions': sum(len(v) for v in actions.values()),
        'buy_count': len(actions.get('BUY', [])),
        'add_count': len(actions.get('ADD', [])),
        'hold_count': len(actions.get('HOLD', [])),
        'reduce_count': len(actions.get('REDUCE', [])),
        'sell_count': len(actions.get('SELL', [])),
        'no_trade_count': len(actions.get('NO_TRADE', [])),
        'trace': [
            x.get('decision_id') for x in
            actions.get('BUY', []) + actions.get('ADD', []) + actions.get('HOLD', []) +
            actions.get('REDUCE', []) + actions.get('SELL', []) + actions.get('NO_TRADE', [])
            if x.get('decision_id')
        ],
    }


def build_daily_report(today: str | None = None) -> dict:
    today = today or _today_str()
    snapshots = load_today_snapshots(today)
    sim_trades = load_today_sim_trades(today)
    actions = classify_actions(snapshots, sim_trades)

    report = {
        'meta': {
            'as_of_time': _now_iso(),
            'report_date': today,
            'contract_version': 'phase7.6',
            'primary_output': True,
        },
        'market': build_market_section(),
        'data_health': build_data_health_section(),
        'real_portfolio': build_real_portfolio_section(),
        'actions': actions,
        'decision_summary': build_decision_summary(actions),
        'known_limitations': [
            'Historical ST = BLOCKED',
            'Historical Market Cap = PARTIAL',
            'Historical Portfolio = NONE',
            'Real cash/total_asset may be MANUAL_CONFIRMATION only',
        ],
    }
    return report


def format_human_readable(report: dict) -> str:
    lines = []
    meta = report.get('meta', {})
    mkt = report.get('market', {})
    dh = report.get('data_health', {})
    rp = report.get('real_portfolio', {})
    actions = report.get('actions', {})
    summary = report.get('decision_summary', {})

    lines.append(f"📊 Daily Decision Report | {meta.get('report_date')}")
    lines.append(f"生成时间: {meta.get('as_of_time')}")
    lines.append("")
    lines.append("### MARKET")
    lines.append(f"Regime: {mkt.get('regime_label')} (score={mkt.get('regime_score')})")
    lines.append(f"Position Scale: {mkt.get('position_scale')}")
    lines.append("")
    lines.append("### DATA HEALTH")
    for k, v in dh.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("### REAL PORTFOLIO")
    lines.append(f"Source: {rp.get('source')} | Quality: {rp.get('data_quality')} | Freshness: {rp.get('freshness')}")
    lines.append(f"Cash: {rp.get('cash')} | Total Asset: {rp.get('total_asset')}")
    lines.append(f"Holdings: {rp.get('holdings_value')} | Exposure: {rp.get('exposure')}")
    lines.append(f"Drawdown: {rp.get('drawdown')} ({rp.get('drawdown_status')})")
    if rp.get('peak_asset'):
        lines.append(f"Peak Asset: {rp.get('peak_asset')} @ {rp.get('peak_asset_date')}")
    lines.append("")
    lines.append("### DECISION SUMMARY")
    lines.append(f"BUY: {summary.get('buy_count')} | ADD: {summary.get('add_count')} | HOLD: {summary.get('hold_count')} | "
                 f"REDUCE: {summary.get('reduce_count')} | SELL: {summary.get('sell_count')} | NO_TRADE: {summary.get('no_trade_count')}")
    lines.append("")

    for action_key in ('BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE'):
        items = actions.get(action_key, [])
        if not items:
            continue
        label = action_key.upper()
        lines.append(f"### {label}")
        for it in items:
            sym = it.get('symbol') or it.get('name') or 'N/A'
            name = it.get('name', '')
            if sym and name:
                lines.append(f"  {sym} {name}")
            else:
                lines.append(f"  {sym}")
            lines.append(f"    Action: {it.get('action')}")
            lines.append(f"    Reason: {', '.join(it.get('reason_codes', [])) or 'N/A'}")
            if it.get('explanation'):
                lines.append(f"    Explanation: {it.get('explanation')}")
            if it.get('decision_id'):
                lines.append(f"    Decision ID: {it.get('decision_id')}")
            if it.get('entry', {}).get('entry_signal'):
                lines.append(f"    Entry Signal: {it['entry'].get('entry_signal')}")
            if it.get('entry', {}).get('entry_price'):
                lines.append(f"    Entry Price: {it['entry'].get('entry_price')}")
            if it.get('sizing_status') and it.get('action') in (BUY, ADD, SELL, REDUCE):
                lines.append(f"    Sizing: {it.get('sizing_status')}")
                if it.get('target_value') is not None:
                    lines.append(f"    Target Value: {it.get('target_value'):,.0f}")
                if it.get('target_quantity'):
                    lines.append(f"    Target Qty: {it.get('target_quantity'):,}")
                if it.get('delta_value') is not None:
                    lines.append(f"    Delta Value: {it.get('delta_value'):,.0f}")
                if it.get('delta_quantity'):
                    lines.append(f"    Delta Qty: {it.get('delta_quantity'):,}")
            if it.get('risk', {}).get('stop_loss'):
                lines.append(f"    Stop Loss: {it['risk'].get('stop_loss')}")
            if it.get('risk', {}).get('take_profit'):
                lines.append(f"    Take Profit: {it['risk'].get('take_profit')}")
        lines.append("")

    if summary.get('trace'):
        lines.append("### TRACE")
        lines.append(", ".join(summary['trace']))

    return "\n".join(lines)


def save_daily_report(report: dict, out_dir: str | None = None) -> dict:
    out_dir = out_dir or os.path.join(str(SCRIPT_DIR.parent), 'reports')
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    today = report.get('meta', {}).get('report_date') or _today_str()
    json_path = os.path.join(out_dir, f'daily_decision_{today}.json')
    txt_path = os.path.join(out_dir, f'daily_decision_{today}.txt')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(format_human_readable(report))
    return {'json_path': json_path, 'txt_path': txt_path, 'ok': True}


if __name__ == '__main__':
    import glob as _glob
    report = build_daily_report()
    paths = save_daily_report(report)
    print(format_human_readable(report))
    print("\n saved:")
    print(paths)
