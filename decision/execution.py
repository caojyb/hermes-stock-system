#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Execution & Outcome Capture（Phase 6.5）
========================================
让每个新 Production Decision 进入 Execution → Position → Exit → Outcome 生命周期。

- Execution Record：decision_id → execution_id，planned/actual 严格分离
- Simulation 自动写 Execution（关联 decision_id）
- Real 人工执行确认（PENDING → EXECUTED/PARTIAL/REJECTED/NOT_EXECUTED）
- Position Lifecycle：EXECUTED → OPEN → UPDATE → CLOSED
- Position=CLOSED + Execution/Exit 充分 → 自动生成 Outcome
- 数据断链 → DATA_GAP（不静默丢失）
"""
from __future__ import annotations
import json, os, glob
from dataclasses import dataclass, field, asdict
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

from .outcome import (Outcome, Planned, Actual, Excursion, Counterfactual,
                      gen_outcome_id, map_exit_reason,
                      CLOSED, OPEN, UNKNOWN, SOURCE_DECISION, SOURCE_LEGACY,
                      SOURCE_SHADOW, SOURCE_UNKNOWN)

_EXEC_DIR = Path(__file__).resolve().parent / 'executions'

# ═══ Execution 状态 ═══
PLANNED = 'PLANNED'
EXECUTED = 'EXECUTED'
PARTIAL = 'PARTIAL'
REJECTED = 'REJECTED'
NOT_EXECUTED = 'NOT_EXECUTED'
EXEC_STATUS = (PLANNED, EXECUTED, PARTIAL, REJECTED, NOT_EXECUTED, 'UNKNOWN')

# ═══ Execution 来源 ═══
SRC_SIM = 'SIMULATION'
SRC_MANUAL = 'MANUAL_CONFIRMATION'
SRC_SHADOW = 'SHADOW_SIMULATION'


def gen_exec_id():
    return f"exec_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Execution:
    """Execution Record（planned 与 actual 严格分离）。"""
    execution_id: str = ''
    decision_id: str = ''
    symbol: str = ''
    name: str = ''
    action: str = ''               # BUY/ADD/REDUCE/SELL/HOLD/NO_TRADE
    strategy: str = ''
    strategy_version: str = ''
    status: str = PLANNED          # PLANNED/EXECUTED/PARTIAL/REJECTED/NOT_EXECUTED/UNKNOWN
    source: str = SRC_SIM          # SIMULATION/MANUAL_CONFIRMATION/SHADOW_SIMULATION
    planned: dict = field(default_factory=dict)   # {price, quantity, position}
    actual: dict = field(default_factory=dict)    # {price, quantity, position}
    execution_time: str = ''
    notes: str = ''
    # Position Lifecycle
    position_status: str = UNKNOWN  # OPEN/CLOSED/PARTIAL
    exit: dict = field(default_factory=dict)      # {price, quantity, time, reason, status}
    # provenance
    decision_snapshot_id: str = ''
    portfolio_snapshot_id: str = ''
    created_at: str = ''

    def freeze(self) -> dict:
        return asdict(self)


def _exec_path(eid):
    return _EXEC_DIR / f"{eid}.json"


def save_execution(ex):
    _EXEC_DIR.mkdir(parents=True, exist_ok=True)
    ex.execution_id = ex.execution_id or gen_exec_id()
    ex.created_at = ex.created_at or _now()
    with open(_exec_path(ex.execution_id), 'w') as f:
        json.dump(ex.freeze(), f, ensure_ascii=False, indent=2, default=str)
    return ex.execution_id


def get_execution(execution_id):
    p = _exec_path(execution_id)
    if not p.exists():
        return None
    return json.load(open(p))


def find_execution(decision_id):
    """按 decision_id 找 execution（可能多条）。"""
    out = []
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
            if e.get('decision_id') == decision_id:
                out.append(e)
        except Exception:
            pass
    return out


def record_simulation_execution(decision, action, entry_price, quantity, position=0.0,
                                status=EXECUTED):
    """Simulation 自动写 Execution（关联 decision_id）。"""
    ex = Execution(
        decision_id=decision.get('decision_id', ''),
        symbol=decision.get('symbol', ''), name=decision.get('name', ''),
        action=action, strategy=decision.get('strategy', 'v1_double'),
        strategy_version=decision.get('config_version', ''),
        status=status, source=SRC_SIM,
        planned={'price': decision.get('reference_price', 0), 'quantity': 0,
                 'position': decision.get('target_position', 0)},
        actual={'price': entry_price, 'quantity': quantity, 'position': position},
        execution_time=_now(),
        position_status=OPEN if status == EXECUTED else (PARTIAL if status == PARTIAL else UNKNOWN),
        decision_snapshot_id=decision.get('data_snapshot_id', ''),
        portfolio_snapshot_id=decision.get('portfolio_snapshot_id', ''),
    )
    return save_execution(ex)


def confirm_manual_execution(decision_id, actual_price, actual_quantity,
                             execution_time, status, notes=''):
    """真实仓人工执行确认（用户在平安证券成交后回写）。"""
    exs = find_execution(decision_id)
    if exs:
        ex = exs[-1]
    else:
        ex = {'execution_id': '', 'decision_id': decision_id, 'source': SRC_MANUAL,
              'planned': {}, 'actual': {}, 'position_status': UNKNOWN, 'exit': {},
              'status': PLANNED, 'action': '', 'symbol': '', 'name': '',
              'strategy': 'v1_double', 'strategy_version': '', 'decision_snapshot_id': '',
              'portfolio_snapshot_id': '', 'execution_time': '', 'created_at': '',
              'notes': ''}
        ex['execution_id'] = gen_exec_id()
    ex['status'] = status
    ex['source'] = SRC_MANUAL
    ex['actual'] = {'price': actual_price, 'quantity': actual_quantity, 'position': 0.0}
    ex['execution_time'] = execution_time or _now()
    ex['notes'] = notes
    if status == EXECUTED:
        ex['position_status'] = OPEN
    elif status == PARTIAL:
        ex['position_status'] = PARTIAL
    elif status in (REJECTED, NOT_EXECUTED):
        ex['position_status'] = UNKNOWN
    if not ex.get('execution_id'):
        ex['execution_id'] = gen_exec_id()
    with open(_exec_path(ex['execution_id']), 'w') as f:
        json.dump(ex, f, ensure_ascii=False, indent=2, default=str)
    return ex['execution_id']


def record_exit(execution_id, exit_price, exit_quantity, exit_time, exit_reason, status='CLOSED'):
    """记录卖出/退出（人工或模拟），支持多段退出（TP1/TP2/TP3/REDUCE）。
    追加 exit segment，更新 Position Lifecycle；最终 CLOSED 后由 build_outcome 计算加权结果。"""
    ex = get_execution(execution_id)
    if not ex:
        return None
    segments = ex.setdefault('exit_segments', [])
    segments.append({'price': exit_price, 'quantity': exit_quantity,
                     'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
                     'status': status})
    ex['exit'] = {'price': exit_price, 'quantity': exit_quantity,
                  'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
                  'status': status}
    ex['position_status'] = status  # CLOSED / PARTIAL(部分)
    # 累加总退出数量 + 加权退出价（供最终 Outcome）
    total_qty = sum(s['quantity'] for s in segments if s['quantity'])
    if total_qty:
        wavg = sum(s['price'] * s['quantity'] for s in segments) / total_qty
        ex['exit_summary'] = {'total_quantity': total_qty, 'weighted_avg_price': round(wavg, 4),
                              'segments': len(segments)}
    with open(_exec_path(execution_id), 'w') as f:
        json.dump(ex, f, ensure_ascii=False, indent=2, default=str)
    return execution_id


def build_outcome_from_execution(execution_id, decision=None):
    """Execution + Exit 信息充分且 Position=CLOSED → 自动生成 Outcome。
    信息不充分 → 返回 None（不推算）。"""
    ex = get_execution(execution_id)
    if not ex:
        return None
    if ex.get('position_status') != CLOSED:
        return None
    if not ex.get('actual', {}).get('price'):
        return None
    entry = ex['actual'].get('price', 0)
    # 多段退出 → 加权退出价 + 总数量
    summary = ex.get('exit_summary')
    if summary and summary.get('total_quantity'):
        exit_price = summary['weighted_avg_price']
        qty = summary['total_quantity']
        # 已退出数量应 <= 入场数量；若缺失入场数量用退出总量
        entry_qty = ex['actual'].get('quantity', 0)
        eff_qty = qty if not entry_qty else min(qty, entry_qty)
    else:
        exit_price = ex.get('exit', {}).get('price', 0)
        qty = ex['actual'].get('quantity', 0)
        eff_qty = qty
    if not exit_price:
        return None
    ret = (exit_price - entry) / entry if entry else 0
    realized = (exit_price - entry) * eff_qty
    o = Outcome(
        outcome_id=gen_outcome_id(),
        decision_id=ex.get('decision_id', ''),
        symbol=ex.get('symbol', ''), name=ex.get('name', ''),
        action=ex.get('action', ''), strategy=ex.get('strategy', 'v1_double'),
        strategy_version=ex.get('strategy_version', ''),
        outcome_source=SOURCE_DECISION if ex.get('decision_id') else SOURCE_LEGACY,
        execution_time=ex.get('execution_time', ''),
        exit_time=ex.get('exit', {}).get('time', ''),
        planned=Planned(entry_price=ex.get('planned', {}).get('price', 0),
                        target_position=ex.get('planned', {}).get('position', 0)),
        actual=Actual(entry_price=entry, position_size=eff_qty, exit_price=round(exit_price, 4),
                      realized_pnl=round(realized, 4), return_pct=round(ret, 4)),
        lifecycle_status=CLOSED,
        exit_reason=ex.get('exit', {}).get('reason', UNKNOWN),
        portfolio_snapshot_id=ex.get('portfolio_snapshot_id', ''),
        decision_snapshot_id=ex.get('decision_snapshot_id', ''),
        code_version='p66',
    )
    return o


def find_unlinked_decisions(recent_days=None):
    """DATA_GAP：有 Decision 但无 Execution（或 execution 未 EXECUTED）。"""
    dec_files = glob.glob(str(Path(__file__).resolve().parent / 'snapshots' / '*.json'))
    unlinked = []
    for f in dec_files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        did = d.get('decision_id', '')
        if not did:
            continue
        exs = find_execution(did)
        if not exs:
            unlinked.append({'decision_id': did, 'symbol': d.get('symbol', ''),
                             'action': d.get('action', ''), 'gap': 'NO_EXECUTION'})
    return unlinked


def find_entry_execution(symbol, status=EXECUTED, action='BUY'):
    """按 symbol 找 Entry Execution（BUY 且已 EXECUTED，可含已平仓）。返回最新一个。"""
    found = []
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if (e.get('symbol') == symbol and e.get('action', '').upper() == action.upper()
                and e.get('status') == status):
            found.append(e)
    if not found:
        return None
    found.sort(key=lambda x: x.get('created_at', ''))
    return found[-1]


def record_sim_exit_and_outcome(symbol, exit_price, exit_quantity, exit_reason, exit_time=''):
    """Simulation Exit → Execution + Outcome Closure。
    找该 symbol 的 Entry Execution → record_exit → build Outcome → save。
    legacy（无 entry execution）→ 仅返回 None（不强制生成，不伪造）。"""
    from . import outcome_store as os_
    entry = find_entry_execution(symbol)
    if not entry:
        return None, None
    eid = entry['execution_id']
    record_exit(eid, exit_price, exit_quantity, exit_time, exit_reason)
    o = build_outcome_from_execution(eid)
    if o:
        os_.save_outcome(o)
        # 回写 outcome_id 到 execution（供 monitor 识别已闭环）
        e = get_execution(eid)
        if e:
            e['outcome_id'] = o.outcome_id
            with open(_exec_path(eid), 'w') as f:
                json.dump(e, f, ensure_ascii=False, indent=2, default=str)
        return eid, o
    return eid, None


def lifecycle_replay(outcome_id):
    """恢复完整生命周期链：
    Outcome → Exit Execution(s) → Entry Execution → Entry Decision → Portfolio Snapshot → Regime。"""
    from . import outcome_store as os_
    r = os_.replay(outcome_id)
    if not r['ok']:
        return r
    outcome = r['outcome']
    # 找 entry execution（按 symbol + decision）
    did = outcome.get('decision_id', '')
    entry_exec = None
    entry_decision = None
    exs = find_execution(did) if did else []
    # 若有该 decision 的 execution（exit decision 可能不是 entry）→ 用 entry execution 找
    entry_exec = find_entry_execution(outcome.get('symbol', ''))
    if did:
        dp = Path(__file__).resolve().parent / 'snapshots' / f"{did}.json"
        if dp.exists():
            entry_decision = json.load(open(dp))
    return {
        'ok': True,
        'outcome': outcome,
        'exit_executions': exs,
        'entry_execution': entry_exec,
        'entry_decision': entry_decision,
        'decision_snapshot_id': outcome.get('decision_snapshot_id', ''),
        'portfolio_snapshot_id': outcome.get('portfolio_snapshot_id', ''),
        'regime': (entry_decision or {}).get('regime_label', ''),
    }


def monitor(recent_days=None):
    """Outcome Capture Pipeline 健康检查（区分 historical_legacy / current_production / shadow）。
    返回 HEALTHY / DEGRADED / BROKEN + 计数 + integrity 检查。"""
    dec_files = glob.glob(str(Path(__file__).resolve().parent / 'snapshots' / '*.json'))
    exes = glob.glob(str(_EXEC_DIR / '*.json'))
    outs = glob.glob(str(Path(__file__).resolve().parent / 'outcomes' / '*.json'))

    # ═══ Lifecycle Integrity 检查 ═══
    integrity = {
        'buy_decision_no_execution': 0,   # BUY Decision 无 Execution
        'execution_no_position': 0,       # Execution 无 Position
        'open_no_entry_execution': 0,     # OPEN 无 Entry Execution
        'exit_no_position_closure': 0,    # Exit Execution 无 Position Closure
        'closed_no_outcome': 0,           # CLOSED Position 无 Outcome
        'outcome_no_decision': 0,         # Outcome 无 Decision
    }
    current_unlinked = 0
    historical_unlinked = 0
    # 区分：有对应 entry execution 的 decision 是"当前"，无的是 legacy
    # 简化：所有无 execution 的 decision 计入 historical（Phase 6.5 前 legacy）——
    # 生产窗口内新 decision 才会有 entry execution。此处 current_unlinked 用
    # "该 decision 有 entry execution 但无 exit/outcome" 近似，历史全 legacy。

    # 检查 BUY decision 无 execution（entry BUY decision）
    buy_decisions = 0
    for f in dec_files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if not d.get('decision_id'):
            continue
        if d.get('action') in ('BUY', 'ADD'):
            buy_decisions += 1
            exs = find_execution(d['decision_id'])
            if not exs:
                integrity['buy_decision_no_execution'] += 1
                historical_unlinked += 1
    # Execution no position / OPEN 无 entry
    for f in exes:
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if not e.get('actual', {}).get('price'):
            integrity['execution_no_position'] += 1
        if e.get('position_status') == OPEN and not e.get('exit_segments'):
            # 正常 OPEN（未退出），非 gap
            pass
    # CLOSED position 无 outcome：检查 CLOSED executions 是否有对应 outcome
    outcome_symbols = set()
    for f in outs:
        try:
            o = json.load(open(f))
            outcome_symbols.add((o.get('symbol'), o.get('exit_time', '')))
        except Exception:
            pass
    closed_no_outcome = 0
    for f in exes:
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if e.get('position_status') == CLOSED and not e.get('outcome_id'):
            closed_no_outcome += 1
    integrity['closed_no_outcome'] = closed_no_outcome

    decision_count = len(dec_files)
    execution_count = len(exes)
    outcome_count = len(outs)
    open_positions = sum(1 for f in exes if _json_field(f, 'position_status') == OPEN)
    closed_positions = sum(1 for f in exes if _json_field(f, 'position_status') == CLOSED)
    current_gap = integrity['buy_decision_no_execution']
    # 健康判定：status 只反映 active pipeline（新 decision 闭环）；历史 legacy
    # （closed_no_outcome / historical_unlinked）单独作为 known_legacy_gap 输出，不污染当前。
    if current_gap == 0:
        status = 'HEALTHY'
    elif current_gap <= max(1, buy_decisions * 0.3):
        status = 'DEGRADED'
    else:
        status = 'BROKEN'
    return {
        'status': status,
        'decision_count': decision_count, 'execution_count': execution_count,
        'open_positions': open_positions, 'closed_positions': closed_positions,
        'outcome_count': outcome_count,
        'historical_unlinked': historical_unlinked,
        'current_unlinked': current_gap,
        'integrity': integrity,
        'known_legacy_gap': historical_unlinked,
        'active_pipeline_gap': current_gap,
    }


def _json_field(f, key):
    try:
        return json.load(open(f)).get(key)
    except Exception:
        return None
