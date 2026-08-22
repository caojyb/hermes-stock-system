#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Observation Layer（Phase 8-B）
========================================
只读统计：从 Decision / Execution / Position / Outcome 事实文件
生成每日 Production Observation Report。

原则：
- Observation 数据不可覆盖
- 只报告事实，不生成交易决策
- 严格区分 PRODUCTION / SIMULATION / TEST / SHADOW / LEGACY
"""
import json, os, glob, sqlite3
from datetime import datetime, timezone, date
from pathlib import Path

from decision.execution import (
    monitor, find_execution, find_executions_by_position_id,
    get_execution, build_outcome_from_execution,
    EXECUTED, PARTIAL, NOT_EXECUTED, UNKNOWN,
    SRC_SIM, SRC_MANUAL, SRC_SHADOW, _EXEC_DIR,
    OPEN, CLOSED,
)
from decision.outcome import SOURCE_DECISION, SOURCE_LEGACY, SOURCE_SHADOW, SOURCE_UNKNOWN
from decision.outcome_store import _OUTCOME_DIR as OUTCOME_DIR
from decision.real_portfolio_truth import get_account_readiness, build_real_snapshot

from decision.observation_config import (
    OBSERVATION_START, CODE_VERSION, CONFIG_VERSION,
    STRATEGY_VERSION, DECISION_CONTRACT_VERSION,
)

_REPORTS_DIR = Path(__file__).resolve().parent.parent / 'reports'


def _today_str() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _counts_from_files(dir_path: str, status_key: str) -> dict:
    out = {}
    for fp in glob.glob(os.path.join(dir_path, '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        s = d.get(status_key)
        if not s:
            continue
        out[s] = out.get(s, 0) + 1
    return out


def _count_decision_actions() -> dict:
    counts = {}
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'snapshots'), '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        a = d.get('action', 'NO_TRADE')
        counts[a] = counts.get(a, 0) + 1
    return counts


def _count_execution_statuses() -> dict:
    return _counts_from_files(_EXEC_DIR, 'status')


def _count_position_statuses() -> dict:
    out = {}
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'executions'), '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        ps = d.get('position_status')
        if not ps:
            continue
        out[ps] = out.get(ps, 0) + 1
    return out


def _count_outcome_lifecycle() -> dict:
    out = {}
    for fp in glob.glob(os.path.join(OUTCOME_DIR, '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        ls = d.get('lifecycle_status')
        if not ls:
            continue
        out[ls] = out.get(ls, 0) + 1
    return out


def _count_data_gaps() -> dict:
    gaps = {
        'decision_without_execution': 0,
        'buy_without_execution': 0,
        'execution_without_position': 0,
        'exit_without_decision': 0,
        'closed_without_outcome': 0,
        'outcome_without_decision': 0,
        'missing_portfolio_snapshot': 0,
        'missing_actual_execution': 0,
        'missing_exit_regime': 0,
        'missing_mae_mfe': 0,
    }
    # BUY/ADD decision no execution
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'snapshots'), '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if d.get('action') in ('BUY', 'ADD') and not find_execution(d.get('decision_id', '')):
            gaps['decision_without_execution'] += 1
            gaps['buy_without_execution'] += 1
    # execution without actual price / position
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'executions'), '*.json')):
        try:
            e = json.load(open(fp))
        except Exception:
            continue
        if not e.get('actual', {}).get('price'):
            gaps['execution_without_position'] += 1
        if e.get('position_status') == CLOSED and not e.get('outcome_id'):
            gaps['closed_without_outcome'] += 1
        if not e.get('exit_segments') and e.get('action', '').upper() in ('SELL', 'REDUCE'):
            gaps['missing_exit_regime'] += 1
    # outcome without decision
    for fp in glob.glob(os.path.join(OUTCOME_DIR, '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if not d.get('decision_id'):
            gaps['outcome_without_decision'] += 1
        if d.get('mae_mfe_status') == UNKNOWN or not d.get('excursion'):
            gaps['missing_mae_mfe'] += 1
    return gaps


def _count_integrity() -> dict:
    integrity = {
        'decision_without_snapshot': 0,
        'buy_without_execution': 0,
        'execution_without_position': 0,
        'exit_without_decision': 0,
        'closed_without_outcome': 0,
        'outcome_without_decision': 0,
        'missing_portfolio_snapshot': 0,
        'missing_actual_execution': 0,
        'missing_exit_regime': 0,
        'missing_mae_mfe': 0,
    }
    decision_ids = set()
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'snapshots'), '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        did = d.get('decision_id')
        if not did:
            integrity['decision_without_snapshot'] += 1
            continue
        decision_ids.add(did)
        if d.get('action') in ('BUY', 'ADD') and not find_execution(did):
            integrity['buy_without_execution'] += 1
    for fp in glob.glob(os.path.join(str(Path(__file__).resolve().parent / 'executions'), '*.json')):
        try:
            e = json.load(open(fp))
        except Exception:
            continue
        if not e.get('actual', {}).get('price'):
            integrity['execution_without_position'] += 1
            integrity['missing_actual_execution'] += 1
        if not e.get('portfolio_snapshot_id') and not e.get('decision_snapshot_id'):
            integrity['missing_portfolio_snapshot'] += 1
        if e.get('position_status') == CLOSED and not e.get('outcome_id'):
            integrity['closed_without_outcome'] += 1
        if e.get('action', '').upper() in ('SELL', 'REDUCE') and not e.get('exit_segments'):
            integrity['missing_exit_regime'] += 1
    for fp in glob.glob(os.path.join(OUTCOME_DIR, '*.json')):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if not d.get('decision_id'):
            integrity['outcome_without_decision'] += 1
        if d.get('mae_mfe_status') == UNKNOWN or not d.get('excursion'):
            integrity['missing_mae_mfe'] += 1
    return integrity


def _reconcile_counts(decisions: dict, executions: dict, positions: dict, outcomes: dict) -> dict:
    buy_add = decisions.get('BUY', 0) + decisions.get('ADD', 0)
    no_trade = decisions.get('NO_TRADE', 0)
    executed = executions.get('EXECUTED', 0) + executions.get('PARTIAL', 0)
    open_pos = positions.get('OPEN', 0)
    closed_pos = positions.get('CLOSED', 0)
    closed_outcomes = outcomes.get('CLOSED', 0)
    anomalies = []
    if no_trade != executions.get('NOT_EXECUTED', 0):
        anomalies.append('NO_TRADE count mismatch')
    if buy_add < executed:
        anomalies.append('executed exceeds BUY+ADD')
    if open_pos > 0 and closed_outcomes > 0:
        anomalies.append('OPEN positions with CLOSED outcomes')
    if closed_pos != closed_outcomes:
        anomalies.append('CLOSED positions != CLOSED outcomes')
    return {
        'decision_count': sum(decisions.values()),
        'execution_count': sum(executions.values()),
        'position_count': sum(positions.values()),
        'outcome_count': sum(outcomes.values()),
        'buy_add_count': buy_add,
        'executed_count': executed,
        'open_position_count': open_pos,
        'closed_position_count': closed_pos,
        'closed_outcome_count': closed_outcomes,
        'anomalies': anomalies,
        'reconcile_ok': len(anomalies) == 0,
    }


def _health_from_status(active_gap: int, anomalies: list, account_ready: bool) -> str:
    """
    DEPRECATED：二维健康度已替换为三维健康度 (_derive_account_health / _derive_observation_health)。
    保留此函数仅用于向后兼容，不再被主流程调用。
    """
    if not account_ready or active_gap > 5 or any('CLOSED positions != CLOSED outcomes' in a for a in anomalies):
        return 'BROKEN'
    if active_gap > 0 or anomalies:
        return 'DEGRADED'
    return 'HEALTHY'


def check_real_account_readiness() -> dict:
    try:
        snap = build_real_snapshot()
        r = get_account_readiness()
        return {
            'status': r.get('status', UNKNOWN),
            'reason': r.get('reason', ''),
            'cash': r.get('cash'),
            'total_asset': r.get('total_asset'),
            'freshness': r.get('freshness'),
            'data_quality': r.get('data_quality'),
            'source': snap.get('source', ''),
            'as_of_time': snap.get('as_of_time', ''),
        }
    except Exception as e:
        return {'status': UNKNOWN, 'reason': str(e)}


def _derive_holdings_health(snap: dict | None = None) -> str:
    try:
        from decision.real_portfolio_truth import get_holdings_status, build_real_snapshot
        snap = snap or build_real_snapshot()
        hs = get_holdings_status(snap).get('status')
        return 'HEALTHY' if hs == 'READY' else ('DEGRADED' if hs == 'EMPTY' else 'BROKEN')
    except Exception:
        return 'BROKEN'


def _derive_account_health(account: dict | None = None) -> str:
    try:
        from decision.real_portfolio_truth import get_account_status
        acct = account or get_account_status()
        s = acct.get('status')
        return 'HEALTHY' if s == 'READY' else ('DEGRADED' if s in ('PARTIAL', 'STALE', 'EXPIRED', 'UNKNOWN', 'MISSING') else 'BROKEN')
    except Exception:
        return 'BROKEN'


def build_daily_observation_report(observation_date: str | None = None) -> dict:
    observation_date = observation_date or _today_str()
    base = monitor()
    decisions = _count_decision_actions()
    executions = _count_execution_statuses()
    positions = _count_position_statuses()
    outcomes = _count_outcome_lifecycle()
    data_gaps = _count_data_gaps()
    integrity = _count_integrity()
    reconciliation = _reconcile_counts(decisions, executions, positions, outcomes)
    account = check_real_account_readiness()
    snap = None
    try:
        from decision.real_portfolio_truth import build_real_snapshot
        snap = build_real_snapshot()
    except Exception:
        pass
    holdings_health = _derive_holdings_health(snap)
    account_health = _derive_account_health(account)
    pipeline_health = 'BROKEN' if (account.get('status') == 'UNKNOWN' and base.get('active_pipeline_gap', 0) > 5) else ('DEGRADED' if base.get('active_pipeline_gap', 0) > 0 or reconciliation.get('anomalies') else 'HEALTHY')
    health = min(holdings_health, account_health, pipeline_health, key=lambda x: {'HEALTHY': 2, 'DEGRADED': 1, 'BROKEN': 0}[x])
    report = {
        'observation_date': observation_date,
        'observation_start': OBSERVATION_START,
        'code_version': CODE_VERSION,
        'config_version': CONFIG_VERSION,
        'strategy_version': STRATEGY_VERSION,
        'decision_contract_version': DECISION_CONTRACT_VERSION,
        'generated_at': _now_iso(),
        'decision': decisions,
        'execution': executions,
        'position': positions,
        'outcome': outcomes,
        'data_health': data_gaps,
        'integrity': integrity,
        'reconciliation': reconciliation,
        'account_readiness': account,
        'health': health,
        'holdings_health': holdings_health,
        'account_health': account_health,
        'pipeline_health': pipeline_health,
        'active_pipeline_gap': base.get('active_pipeline_gap', 0),
        'known_legacy_gap': base.get('known_legacy_gap', 0),
        'note': 'Observation only — no strategy evaluation',
    }
    return report


def save_daily_observation_report(observation_date: str | None = None) -> dict:
    report = build_daily_observation_report(observation_date)
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _REPORTS_DIR / f"production_observation_{report['observation_date']}.json"
    txt_path = _REPORTS_DIR / f"production_observation_{report['observation_date']}.txt"
    txt = format_observation_text(report)
    tmp = json_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    tmp.replace(json_path)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt)
    return {'ok': True, 'json_path': str(json_path), 'txt_path': str(txt_path), 'report': report}


def format_observation_text(report: dict) -> str:
    lines = [
        f"Production Observation Health | {report.get('observation_date')}",
        f"Observation Start: {report.get('observation_start')}",
        f"Code: {report.get('code_version')} Config: {report.get('config_version')} Strategy: {report.get('strategy_version')}",
        '',
        '### Decisions',
    ]
    for k in ('BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE'):
        lines.append(f"{k}: {report.get('decision', {}).get(k, 0)}")
    lines.extend([
        '',
        '### Execution',
    ])
    for k in ('PLANNED', 'EXECUTED', 'PARTIAL', 'REJECTED', 'NOT_EXECUTED', 'UNKNOWN'):
        lines.append(f"{k}: {report.get('execution', {}).get(k, 0)}")
    lines.extend([
        '',
        '### Position',
    ])
    for k in ('OPEN', 'PARTIAL', 'CLOSED', 'UNKNOWN'):
        lines.append(f"{k}: {report.get('position', {}).get(k, 0)}")
    lines.extend([
        '',
        '### Outcome',
    ])
    for k in ('CLOSED', 'PARTIAL', 'UNKNOWN'):
        lines.append(f"{k}: {report.get('outcome', {}).get(k, 0)}")
    lines.extend([
        '',
        '### Data Gaps',
    ])
    for k, v in report.get('data_health', {}).items():
        lines.append(f"{k}: {v}")
    lines.extend([
        '',
        '### Integrity',
    ])
    for k, v in report.get('integrity', {}).items():
        lines.append(f"{k}: {v}")
    lines.extend([
        '',
        f"### Health\n{report.get('health')}",
        f"### Account\n{report.get('account_readiness', {}).get('status', 'UNKNOWN')}",
        '',
        'Observation only — no strategy evaluation.',
    ])
    return '\n'.join(lines)
