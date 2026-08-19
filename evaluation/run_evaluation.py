"""
Phase 7：Decision Evaluation & Evidence Audit
只读运行数据，产出 evaluation/ 目录下的统计结果与报告。
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
DEC_EXEC_DIR = ROOT / 'decision' / 'executions'
DEC_OUT_DIR = ROOT / 'decision' / 'outcomes'
DEC_SNAP_DIR = ROOT / 'decision' / 'snapshots'
EVAL_DIR = ROOT / 'evaluation'
ART_DIR = ROOT / 'artifacts' / 'evaluation'
EVAL_DIR.mkdir(exist_ok=True)
ART_DIR.mkdir(parents=True, exist_ok=True)

SRC_SHADOW = 'SHADOW'
SRC_SIM = 'SIMULATION'
SRC_LEGACY = 'LEGACY'
SOURCE_LEGACY = 'LEGACY'
SOURCE_DECISION = 'DECISION'


def _load_json_files(directory: Path):
    out = []
    for fp in directory.glob('*.json'):
        try:
            out.append(json.load(open(fp, 'r', encoding='utf-8')))
        except Exception:
            continue
    return out


def _classify_source(exec_obj: dict) -> str:
    """Phase 7.1: 基于 execution source + decision_id 模式判断真实来源。"""
    src = (exec_obj.get('source') or '').upper()
    strategy = (exec_obj.get('strategy') or '').lower()
    decision_id = (exec_obj.get('decision_id') or '').lower()
    
    # Strategy 判断
    if strategy == 'main_up':
        return 'SHADOW'
    
    # Source 判断
    if src == 'MANUAL_CONFIRMATION':
        return 'PRODUCTION'
    
    # decision_id 模式判断（测试数据有特征前缀）
    if not decision_id or decision_id.startswith('lc_') or decision_id == 'legacy':
        return 'LEGACY'
    
    # 测试标识：p67/p68/test_ 前缀（Phase 6.7/6.8/7 测试）
    if any(decision_id.startswith(prefix) for prefix in ['p67', 'p68', 'test_']):
        return 'TEST'
    
    # 其他 SIMULATION 且无测试标识
    if src == 'SIMULATION':
        return 'SIMULATION'
    
    return 'PRODUCTION'


def _normalize_action(action: str) -> str:
    return (action or '').upper()

def _exec_action_set():
    return {'BUY', 'ADD', 'SELL', 'REDUCE'}

def _outcome_quality(outcome: dict) -> str:
    """Phase 7.1: Outcome data quality 判断。"""
    dq = (outcome.get('data_quality') or '').upper()
    if dq:
        return dq
    
    did = (outcome.get('decision_id') or '').lower()
    if any(did.startswith(prefix) for prefix in ['p67', 'p68', 'p7_', 'test_']):
        return 'TEST'
    if did.startswith('lc_') or not did:
        return 'LEGACY'
    return 'UNKNOWN'


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _pct(v):
    return round(v * 100, 2)


def _safe_div(a, b):
    return a / b if b else 0.0


def build_dataset():
    execs = _load_json_files(DEC_EXEC_DIR)
    outcomes = _load_json_files(DEC_OUT_DIR)
    snapshots = _load_json_files(DEC_SNAP_DIR)

    snap_by_did = {s.get('decision_id'): s for s in snapshots if s.get('decision_id')}
    exec_by_pid = defaultdict(list)
    for e in execs:
        pid = e.get('position_id', '')
        if pid:
            exec_by_pid[pid].append(e)

    production_outcomes = []
    shadow_outcomes = []
    legacy_outcomes = []
    test_outcomes = []  # Phase 7.1: TEST 独立分类
    simulation_outcomes = []  # Phase 7.1: SIMULATION 独立分类
    counterfactual_outcomes = []

    for o in outcomes:
        pid = o.get('position_id', '')
        related_execs = exec_by_pid.get(pid, [])
        source = 'LEGACY'
        if related_execs:
            source = _classify_source(related_execs[0])
        elif o.get('outcome_source') == SOURCE_LEGACY:
            source = 'LEGACY'
        
        # Phase 7.1: Include evaluation metadata
        entry_exec = None
        if related_execs:
            entry_exec = next((e for e in related_execs if _normalize_action(e.get('action', '')) in _exec_action_set()), None)
        
        rec = {
            'outcome_id': o.get('outcome_id', ''),
            'decision_id': o.get('decision_id', ''),
            'symbol': o.get('symbol', ''),
            'strategy': o.get('strategy', ''),
            'action': o.get('action', ''),
            'source': source,
            'data_quality': _outcome_quality(o),
            'exit_reason': o.get('exit_reason', ''),
            'entry_price': _to_float((o.get('actual') or {}).get('average_entry_price') or (o.get('actual') or {}).get('entry_price')),
            'exit_price': _to_float((o.get('actual') or {}).get('exit_price') or (o.get('actual') or {}).get('weighted_exit_price')),
            'total_entry_qty': _to_float((o.get('actual') or {}).get('total_entry_quantity')),
            'total_exit_qty': _to_float((o.get('actual') or {}).get('total_exit_quantity')),
            'return_pct': _to_float((o.get('actual') or {}).get('return_pct')),
            'realized_pnl': _to_float((o.get('actual') or {}).get('realized_pnl')),
            'holding_period_days': _to_float(o.get('holding_period_days')),
            'mae': _to_float((o.get('excursion') or {}).get('mae')),
            'mfe': _to_float((o.get('excursion') or {}).get('mfe')),
            'max_drawdown': _to_float((o.get('excursion') or {}).get('max_drawdown')),
            'entry_regime': o.get('entry_regime', ''),
            'exit_regime': o.get('exit_regime', ''),
            'candidate_score': _to_float((o.get('candidate_score') or (entry_exec or {}).get('candidate_score') or 0)),
            'candidate_rank': int(o.get('candidate_rank') or (entry_exec or {}).get('candidate_rank') or 0),
            'permission_status': o.get('permission_status', '') or (entry_exec or {}).get('permission_status', ''),
            'slippage_price': _to_float(o.get('slippage_price') or (entry_exec or {}).get('slippage_price') or 0),
            'execution_source': o.get('execution_source', '') or (entry_exec or {}).get('source', ''),
            'dec_snap': snap_by_did.get(o.get('decision_id', ''), {}),
        }
        
        if source == 'PRODUCTION':
            production_outcomes.append(rec)
        elif source == 'SHADOW':
            shadow_outcomes.append(rec)
        elif source == 'LEGACY':
            legacy_outcomes.append(rec)
        elif source == 'TEST':
            test_outcomes.append(rec)
        elif source == 'SIMULATION':
            simulation_outcomes.append(rec)
        else:
            counterfactual_outcomes.append(rec)

    return {
        'production': production_outcomes,
        'shadow': shadow_outcomes,
        'legacy': legacy_outcomes,
        'test': test_outcomes,
        'simulation': simulation_outcomes,
        'counterfactual': counterfactual_outcomes,
    }


def compute_stats(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {'N': 0, 'DATA_INSUFFICIENT': True}
    returns = [_to_float(r.get('return_pct') or (r.get('actual') or {}).get('return_pct')) for r in records]
    pnls = [_to_float(r.get('realized_pnl') or (r.get('actual') or {}).get('realized_pnl')) for r in records]
    holding = [_to_float(r.get('holding_period_days')) for r in records]
    maes = [_to_float(r.get('mae') or (r.get('excursion') or {}).get('mae')) for r in records]
    mfes = [_to_float(r.get('mfe') or (r.get('excursion') or {}).get('mfe')) for r in records]
    max_drawdowns = [_to_float(r.get('max_drawdown') or (r.get('excursion') or {}).get('max_drawdown')) for r in records]

    wins = [r for r in records if (_to_float(r.get('return_pct') or (r.get('actual') or {}).get('return_pct'))) > 0]
    losses = [r for r in records if (_to_float(r.get('return_pct') or (r.get('actual') or {}).get('return_pct'))) <= 0]
    gross_profit = sum(_to_float(r.get('realized_pnl') or (r.get('actual') or {}).get('realized_pnl')) for r in wins) if wins else 0.0
    gross_loss = abs(sum(_to_float(r.get('realized_pnl') or (r.get('actual') or {}).get('realized_pnl')) for r in losses)) if losses else 0.0
    profit_factor = _safe_div(gross_profit, gross_loss)

    max_dd = max(max_drawdowns) if max_drawdowns else 0.0

    stats = {
        'N': n,
        'win_rate': _safe_div(len(wins), n),
        'avg_return': sum(returns) / len(returns) if returns else 0.0,
        'median_return': median(returns) if returns else 0.0,
        'profit_factor': profit_factor,
        'avg_holding_period': sum(holding) / len(holding) if holding else 0.0,
        'avg_mae': sum(maes) / len(maes) if maes else 0.0,
        'avg_mfe': sum(mfes) / len(mfes) if mfes else 0.0,
        'max_drawdown': max_dd,
        'return_distribution': {
            'min': min(returns) if returns else 0.0,
            'max': max(returns) if returns else 0.0,
            'median': median(returns) if returns else 0.0,
        },
        'DATA_INSUFFICIENT': n < 5,
    }
    return stats


def group_by(records: list[dict], key: str):
    grouped = defaultdict(list)
    for r in records:
        val = r.get(key) or 'UNKNOWN'
        grouped[val].append(r)
    return grouped


def layer_stats(records: list[dict], key: str, min_n: int = 3) -> dict:
    grouped = group_by(records, key)
    out = {}
    for k, v in grouped.items():
        out[k] = compute_stats(v)
        if out[k].get('DATA_INSUFFICIENT'):
            out[k]['status'] = 'DATA_INSUFFICIENT'
        else:
            out[k]['status'] = 'OK'
    return out


def evaluate_trading_permission(execs: list[dict], outcomes: list[dict]) -> dict:
    snap_to_exec = {e.get('decision_snapshot_id'): e for e in execs}
    pid_map = defaultdict(list)
    for o in outcomes:
        pid = o.get('position_id', '')
        if pid:
            pid_map[pid].append(o)

    # 用 execution linkage / position_status 推断 permission
    # 简化：status != EXECUTED 视为 BLOCKED
    blocked = [e for e in execs if e.get('status') != 'EXECUTED' and _classify_source(e) == 'PRODUCTION']
    allowed = [e for e in execs if e.get('status') == 'EXECUTED' and _classify_source(e) == 'PRODUCTION']
    blocked_pids = {e.get('position_id') for e in blocked if e.get('position_id')}
    allowed_pids = {e.get('position_id') for e in allowed if e.get('position_id')}
    allowed_outs = [o for o in outcomes if o.get('position_id') in allowed_pids]
    blocked_outs = [o for o in outcomes if o.get('position_id') in blocked_pids]
    result = {
        'allowed_N': len(allowed_outs),
        'blocked_N': len(blocked_outs),
        'allowed_stats': compute_stats(allowed_outs),
        'blocked_stats': compute_stats(blocked_outs),
    }
    return result


def time_stability(records: list[dict]) -> dict:
    by_year = group_by(records, 'year')
    by_quarter = group_by(records, 'quarter')
    return {
        'yearly': {k: compute_stats(v) for k, v in by_year.items()},
        'quarterly': {k: compute_stats(v) for k, v in by_quarter.items()},
    }


def main():
    dataset = build_dataset()
    production = dataset['production']
    shadow = dataset['shadow']
    legacy = dataset['legacy']
    counterfactual = dataset['counterfactual']

    # 提取 decision year/quarter（从 outcome_id 或 decision_time）
    for rec in production + shadow + legacy + counterfactual:
        dt_str = rec.get('outcome_id', '')
        try:
            dt = datetime.fromisoformat(dt_str.split('_')[1])
            rec['year'] = str(dt.year)
            rec['quarter'] = f"{dt.year}-Q{(dt.month-1)//3 + 1}"
        except Exception:
            rec['year'] = 'UNKNOWN'
            rec['quarter'] = 'UNKNOWN'

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'baseline': {
            'tag': 'hermes-stock-phase-6.8',
            'commit': 'adbf3ee',
        },
        'dataset': {
            'production': len(production),
            'shadow': len(shadow),
            'legacy': len(legacy),
            'counterfactual': len(counterfactual),
        },
        'data_quality': {
            'production_missing_decision_id': sum(1 for r in production if not r.get('decision_id')),
            'legacy_missing_decision_id': sum(1 for r in legacy if not r.get('decision_id')),
            'unknown_mae_mfe': sum(1 for r in production if r.get('mae') == 0 and r.get('mfe') == 0),
        },
        'production': {
            'base_stats': compute_stats(production),
            'by_regime': layer_stats(production, 'entry_regime'),
            'by_exit_reason': layer_stats(production, 'exit_reason'),
            'by_action': layer_stats(production, 'action'),
            'by_strategy': layer_stats(production, 'strategy'),
            'time_stability': time_stability(production),
        },
        'shadow': {
            'base_stats': compute_stats(shadow),
            'by_regime': layer_stats(shadow, 'entry_regime'),
            'by_strategy': layer_stats(shadow, 'strategy'),
        },
        'legacy': {
            'base_stats': compute_stats(legacy),
        },
        'permission_evaluation': evaluate_trading_permission(
            _load_json_files(DEC_EXEC_DIR),
            production + shadow + legacy,
        ),
        'position_sizing': {},
        'decision_execution_quality': {},
        'no_trade_value': {},
        'hold_reduce_sell': {},
        'regime_transition': {},
        'entry_signal': {},
        'candidate_score': {},
        'facts_evidence_hypotheses': {
            'facts': [],
            'evidence': [],
            'hypotheses': [],
        },
        'final_answers': {},
        'known_limitations': [
            'Outcome MAE/MFE 多为 UNKNOWN（仿真数据未记录 excursion）',
            'Candidate Score 分层暂缺（当前无 score 字段）',
            'Regime Transition 依赖 entry/exit_regime 数据填充',
            'NO_TRADE Counterfactual 缺少候选池',
            'Trading Permission 阻断样本量少，Counterfactual 受样本限制',
            '时间稳定性样本仅覆盖测试期（约 2026-08-19）',
        ],
    }

    # 基于真实数据生成 Facts/Evidence/Hypotheses
    pb = report['production']['base_stats']
    if pb.get('N', 0) > 0:
        report['facts_evidence_hypotheses']['facts'].append(
            f"V1 Production 样本 N={pb['N']}, win rate={_pct(pb['win_rate'])}%, "
            f"avg return={_pct(pb['avg_return'])}%, profit factor={round(pb['profit_factor'],2)}"
        )
    else:
        report['facts_evidence_hypotheses']['hypotheses'].append('Production 样本不足，需积累更多真实 Decision/Outcome')

    # 保存报告
    report_path = EVAL_DIR / 'DECISION_EVALUATION_REPORT.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Markdown 摘要
    md = ['# Decision Evaluation & Evidence Audit（Phase 7）\n']
    md.append(f"生成时间：{report['generated_at']}\n")
    md.append('## Dataset\n')
    md.append(f"- Production: {report['dataset']['production']}")
    md.append(f"- Shadow: {report['dataset']['shadow']}")
    md.append(f"- Legacy: {report['dataset']['legacy']}")
    md.append(f"- Counterfactual: {report['dataset']['counterfactual']}\n")

    md.append('## Production Base Stats\n')
    for k, v in pb.items():
        if k != 'return_distribution':
            md.append(f"- {k}: {round(v,4) if isinstance(v, float) else v}")
    md.append('')

    md.append('## Regime\n')
    for regime, st in report['production']['by_regime'].items():
        md.append(f"- {regime}: N={st['N']} win_rate={_pct(st.get('win_rate',0))}% avg_ret={_pct(st.get('avg_return',0))}%")
    md.append('')

    md.append('## Exit Reasons\n')
    for reason, st in report['production']['by_exit_reason'].items():
        md.append(f"- {reason}: N={st['N']} avg_ret={_pct(st.get('avg_return',0))}%")
    md.append('')

    md.append('## Trading Permission Counterfactual\n')
    perm = report['permission_evaluation']
    md.append(f"- Allowed N={perm['allowed_N']}")
    md.append(f"- Blocked N={perm['blocked_N']}")
    md.append('')

    md.append('## Facts / Evidence / Hypotheses\n')
    for section in ['facts', 'evidence', 'hypotheses']:
        md.append(f"### {section.title()}\n")
        for item in report['facts_evidence_hypotheses'][section]:
            md.append(f"- {item}")
        md.append('')

    md_path = EVAL_DIR / 'DECISION_EVALUATION_REPORT.md'
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print('REPORT_WRITTEN:', report_path)
    print('MD_WRITTEN:', md_path)
    print('DATASET:', report['dataset'])
    print('PRODUCTION_BASE:', {k: (round(v,4) if isinstance(v,float) else v) for k,v in pb.items() if k != 'return_distribution'})


if __name__ == '__main__':
    main()
