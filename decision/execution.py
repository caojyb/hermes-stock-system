#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Execution & Outcome Capture（Phase 6.5 + Phase 6.7 Hardening）
=============================================================
让每个新 Production Decision 进入 Execution → Position → Exit → Outcome 生命周期。

- Execution Record：decision_id → execution_id，planned/actual 严格分离
- Position Lifecycle Identity：每个 Entry Execution 拥有独立 position_id
- Simulation 自动写 Execution（关联 decision_id + position_id）
- Real 人工执行确认（PENDING → EXECUTED/PARTIAL/REJECTED/NOT_EXECUTED）
- Exit / Outcome 优先使用 entry_execution_id 和 position_id 精确关联
- 同股票多次持仓互不串联
- 数据断链 → DATA_GAP / LINKAGE_FALLBACK（不静默丢失）
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

# ═══ Fallback 标记 ═══
LINKAGE_FALLBACK = 'LINKAGE_FALLBACK'
SOURCE_LEGACY_MARKER = 'LEGACY'


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
    # Position Lifecycle Identity（Phase 6.7）
    position_id: str = ''          # 唯一标识一次独立持仓生命周期
    position_status: str = UNKNOWN  # OPEN/CLOSED/PARTIAL
    exit: dict = field(default_factory=dict)      # {price, quantity, time, reason, status}
    # Exit Execution 精确关联（Phase 6.7）
    entry_execution_id: str = ''   # 本笔 Exit 对应的 Entry Execution
    exit_decision_id: str = ''     # 本笔 Exit Decision 的 decision_id
    # provenance
    decision_snapshot_id: str = ''
    portfolio_snapshot_id: str = ''
    created_at: str = ''
    # linkage 元数据
    linkage: str = ''              # LINKAGE_FALLBACK / LEGACY / 空=结构化

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
    """Simulation 自动写 Execution（关联 decision_id + position_id）。"""
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
    # Phase 6.7：position_id 由 Entry Execution 自身生命周期标识
    if _normalize_action(action) in _exec_action_set() and status == EXECUTED:
        ex.position_id = gen_position_id(decision.get('symbol', ''), _now())
    eid = save_execution(ex)
    return eid


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


def record_exit(execution_id, exit_price, exit_quantity, exit_time, exit_reason, status='CLOSED',
                entry_execution_id='', exit_decision_id=''):
    """记录卖出/退出（人工或模拟），支持多段退出（TP1/TP2/TP3/REDUCE）。
    追加 exit segment，更新 Position Lifecycle；最终 CLOSED 后由 build_outcome 计算加权结果。
    Phase 6.7：优先使用 entry_execution_id 精确关联，不依赖 symbol。"""
    ex = get_execution(execution_id)
    if not ex:
        # 若 execution_id 不存在但提供 entry_execution_id：回退到 entry 记录退出段
        target = get_execution(entry_execution_id) if entry_execution_id else None
        if not target:
            return None
        target.setdefault('exit_segments', []).append({
            'price': exit_price, 'quantity': exit_quantity,
            'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
            'status': status, 'exit_decision_id': exit_decision_id, 'linkage': LINKAGE_FALLBACK,
        })
        target['exit'] = {'price': exit_price, 'quantity': exit_quantity,
                          'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
                          'status': status}
        target['position_status'] = status
        with open(_exec_path(entry_execution_id), 'w') as f:
            json.dump(target, f, ensure_ascii=False, indent=2, default=str)
        return entry_execution_id

    segments = ex.setdefault('exit_segments', [])
    segments.append({'price': exit_price, 'quantity': exit_quantity,
                     'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
                     'status': status, 'exit_decision_id': exit_decision_id,
                     'entry_execution_id': entry_execution_id or ex.get('entry_execution_id', '')})
    ex['exit'] = {'price': exit_price, 'quantity': exit_quantity,
                  'time': exit_time or _now(), 'reason': map_exit_reason([exit_reason]),
                  'status': status}
    ex['position_status'] = status
    if entry_execution_id:
        ex['entry_execution_id'] = entry_execution_id
    if exit_decision_id:
        ex['exit_decision_id'] = exit_decision_id
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
    # Phase 6.8：基于完整 position lifecycle 聚合数量/成本
    pid = ex.get('position_id', '')
    pos = aggregate_position(pid) if pid else None
    entry = ex['actual'].get('price', 0)
    if pos and pos.get('total_entry_quantity'):
        total_entry_qty = pos['total_entry_quantity']
        avg_cost = pos['average_entry_price']
        total_exit_qty = pos['total_exit_quantity']
        weighted_exit = pos['weighted_exit_price']
        eff_qty = total_exit_qty
        exit_price = weighted_exit
        if weighted_exit and avg_cost:
            ret = (weighted_exit - avg_cost) / avg_cost
            realized = (weighted_exit - avg_cost) * total_exit_qty
        else:
            ret = (exit_price - entry) / entry if entry else 0
            realized = (exit_price - entry) * eff_qty
    else:
        summary = ex.get('exit_summary')
        if summary and summary.get('total_quantity'):
            exit_price = summary['weighted_avg_price']
            qty = summary['total_quantity']
            entry_qty = ex['actual'].get('quantity', 0)
            eff_qty = qty if not entry_qty else min(qty, entry_qty)
        else:
            exit_price = ex.get('exit', {}).get('price', 0)
            qty = ex['actual'].get('quantity', 0)
            eff_qty = qty
        total_entry_qty = entry_qty if 'entry_qty' in dir() else ex['actual'].get('quantity', 0)
        total_exit_qty = eff_qty
        if not exit_price:
            return None
        ret = (exit_price - entry) / entry if entry else 0
        realized = (exit_price - entry) * eff_qty
        avg_cost = entry
        weighted_exit = exit_price
    if not exit_price:
        return None
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
        actual=Actual(entry_price=entry, position_size=total_entry_qty,
                      exit_price=round(exit_price, 4),
                      realized_pnl=round(realized, 4), return_pct=round(ret, 4),
                      initial_quantity=pos.get('initial_quantity', total_entry_qty) if pos else total_entry_qty,
                      added_quantity=pos.get('added_quantity', 0.0) if pos else 0.0,
                      total_entry_quantity=total_entry_qty,
                      average_entry_price=round(avg_cost, 4) if avg_cost else 0.0,
                      total_exit_quantity=total_exit_qty,
                      weighted_exit_price=round(weighted_exit, 4) if weighted_exit else 0.0,
                      final_quantity=total_entry_qty - total_exit_qty),
        lifecycle_status=CLOSED,
        exit_reason=ex.get('exit', {}).get('reason', UNKNOWN),
        portfolio_snapshot_id=ex.get('portfolio_snapshot_id', ''),
        decision_snapshot_id=ex.get('decision_snapshot_id', ''),
        code_version='p68',
        position_id=pid,
    )
    return o


def aggregate_position(position_id):
    """按 position_id 聚合 Entry/ADD/Exit 数量与成本。"""
    if not position_id:
        return None
    all_execs = find_executions_by_position_id(position_id)
    if not all_execs:
        return None
    initial_qty = 0
    add_qty = 0
    initial_cost = 0.0
    add_cost = 0.0
    total_exit_qty = 0
    total_exit_proceeds = 0.0
    for e in all_execs:
        if not e.get('actual', {}).get('price'):
            continue
        price = float(e['actual'].get('price', 0) or 0)
        qty = float(e['actual'].get('quantity', 0) or 0)
        if e.get('status') == EXECUTED and _normalize_action(e.get('action', '')) in _exec_action_set():
            if e.get('action', '').upper() == 'ADD':
                add_qty += qty
                add_cost += price * qty
            else:
                initial_qty += qty
                initial_cost += price * qty
        for seg in e.get('exit_segments', []):
            eq = float(seg.get('quantity', 0) or 0)
            ep = float(seg.get('price', 0) or 0)
            if eq:
                total_exit_qty += eq
                total_exit_proceeds += ep * eq
    total_entry = initial_qty + add_qty
    total_cost = initial_cost + add_cost
    avg_cost = total_cost / total_entry if total_entry else 0.0
    wavg_exit = total_exit_proceeds / total_exit_qty if total_exit_qty else 0.0
    return {
        'position_id': position_id,
        'initial_quantity': initial_qty,
        'added_quantity': add_qty,
        'total_entry_quantity': total_entry,
        'average_entry_price': round(avg_cost, 4),
        'total_exit_quantity': total_exit_qty,
        'weighted_exit_price': round(wavg_exit, 4),
        'current_quantity': total_entry - total_exit_qty,
        'invested_capital': round(total_cost, 4),
        'realized_pnl': round(total_exit_proceeds - total_cost, 4),
    }


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


def _normalize_action(a: str) -> str:
    return str(a).upper()


def _exec_action_set() -> set[str]:
    return {_normalize_action(x) for x in ('BUY', 'ADD', 'REDUCE')}


def find_entry_execution(symbol, status=EXECUTED, action='BUY'):
    """按 symbol 找 Entry Execution（BUY/ADD 且 status=EXECUTED），可用于历史/replay。
    生产链路优先用 position_id / entry_execution_id；symbol 仅做 fallback。"""
    found = []
    req_action = _normalize_action(action)
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if (e.get('symbol') == symbol and _normalize_action(e.get('action', '')) == req_action
                and e.get('status') == status):
            found.append(e)
    if not found:
        return None
    found.sort(key=lambda x: x.get('created_at', ''))
    return found[-1]


def find_open_entry_execution(symbol, status=EXECUTED, action='BUY'):
    """仅找当前未平仓的 Entry Execution（OPEN/PARTIAL/UNKNOWN）。用于持仓扫描。"""
    found = []
    req_action = _normalize_action(action)
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        ps = e.get('position_status', '')
        if (e.get('symbol') == symbol and _normalize_action(e.get('action', '')) == req_action
                and e.get('status') == status and ps in (OPEN, PARTIAL, UNKNOWN)):
            found.append(e)
    if not found:
        return None
    found.sort(key=lambda x: x.get('created_at', ''))
    return found[0]


def find_entry_execution_by_position_id(position_id):
    if not position_id:
        return None
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if e.get('position_id') == position_id and _normalize_action(e.get('action', '')) in _exec_action_set():
            return e
    return None


def find_executions_by_position_id(position_id):
    if not position_id:
        return []
    out = []
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if e.get('position_id') == position_id:
            out.append(e)
    out.sort(key=lambda x: x.get('created_at', ''))
    return out


def find_exit_executions(entry_execution_id):
    """按 entry_execution_id 找该笔生命周期内全部 Exit Execution。
    当前退出段存储在 entry execution 文件内；未来独立 exit file 时可去掉自身。"""
    if not entry_execution_id:
        return []
    out = []
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if e.get('entry_execution_id') == entry_execution_id:
            out.append(e)
    out.sort(key=lambda x: x.get('created_at', ''))
    return out


def _find_any_execution(symbol, action='BUY', status=EXECUTED):
    """仅用于 Legacy fallback：symbol 最近同 action execution。"""
    found = []
    req_action = _normalize_action(action)
    for f in glob.glob(str(_EXEC_DIR / '*.json')):
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if (e.get('symbol') == symbol and _normalize_action(e.get('action', '')) == req_action
                and e.get('status') == status):
            found.append(e)
    if not found:
        return None
    found.sort(key=lambda x: x.get('created_at', ''))
    return found[-1]


def gen_position_id(symbol: str, created_at: str, suffix: str = '') -> str:
    """生成唯一 position_id（同一股票不同时间 = 不同生命周期）。"""
    base = (created_at or datetime.now(timezone.utc).isoformat()).replace(':', '').replace('-', '')[:18]
    # 高精度后缀避免同秒多次调用重复
    suffix = suffix or uuid4().hex[:6]
    return f"P_{base}_{symbol}_{suffix}"


def record_sim_exit_and_outcome(symbol, exit_price, exit_quantity, exit_reason, exit_time='',
                                decision_id='', entry_execution_id='', position_id='',
                                exit_decision_id=''):
    """Simulation Exit → Execution + Outcome Closure。
    Phase 6.7 精确关联优先级：
    1) entry_execution_id → 2) decision_id + symbol → 3) position_id → 4) Legacy fallback。
    Legacy（无结构化信息）→ 返回 None 且标记 LINKAGE_FALLBACK，不伪造。"""
    from . import outcome_store as os_
    entry = None
    linkage = ''
    if entry_execution_id:
        entry = get_execution(entry_execution_id)
        linkage = 'STRUCTURED'
    if not entry and decision_id:
        exs = find_execution(decision_id)
        # 优先找该 decision 的 entry execution（BUY/ADD）
        entry = next((e for e in exs if _normalize_action(e.get('action', '')) in _exec_action_set()), None)
        linkage = 'STRUCTURED' if entry else ''
    if not entry and position_id:
        entry = find_entry_execution_by_position_id(position_id)
        linkage = 'STRUCTURED' if entry else ''
    if not entry:
        entry = find_entry_execution(symbol)
        linkage = LINKAGE_FALLBACK if entry else SOURCE_LEGACY_MARKER
    if not entry:
        return None, None, linkage
    eid = entry['execution_id']
    pid = entry.get('position_id', position_id)
    record_exit(eid, exit_price, exit_quantity, exit_time, exit_reason,
                entry_execution_id=eid, exit_decision_id=exit_decision_id)
    e = get_execution(eid)
    if e and linkage:
        e['linkage'] = linkage
        with open(_exec_path(eid), 'w') as f:
            json.dump(e, f, ensure_ascii=False, indent=2, default=str)
    o = build_outcome_from_execution(eid)
    if o:
        os_.save_outcome(o)
        e2 = get_execution(eid)
        if e2:
            e2['outcome_id'] = o.outcome_id
            with open(_exec_path(eid), 'w') as f:
                json.dump(e2, f, ensure_ascii=False, indent=2, default=str)
        return eid, o, linkage
    return eid, None, linkage


def lifecycle_replay(outcome_id):
    """恢复完整生命周期链（Phase 6.7）：
    Outcome → Exit Execution(s) → Entry Execution → Entry Decision → Portfolio Snapshot → Regime。
    优先使用 position_id / entry_execution_id；无结构化信息时回退到 symbol/decision_id。"""
    from . import outcome_store as os_
    r = os_.replay(outcome_id)
    if not r['ok']:
        return r
    outcome = r['outcome']
    did = outcome.get('decision_id', '')
    position_id = outcome.get('position_id', '')
    entry_exec = None
    entry_decision = None
    exit_executions = []
    # 1) 有 position_id 优先
    if position_id:
        all_execs = find_executions_by_position_id(position_id)
        entry_exec = next((e for e in all_execs if _normalize_action(e.get('action', '')) in _exec_action_set()), None)
        eid0 = (entry_exec or {}).get('execution_id', '')
        exit_executions = [e for e in all_execs if e.get('entry_execution_id') == eid0 and e.get('execution_id') != eid0]
    # 2) 退而求其次 decision_id
    if not entry_exec and did:
        exs = find_execution(did)
        entry_exec = next((e for e in exs if _normalize_action(e.get('action', '')) in _exec_action_set()), None)
        eid0 = (entry_exec or {}).get('execution_id', '')
        exit_executions = [e for e in exs if e.get('entry_execution_id') == eid0 and e.get('execution_id') != eid0]
    # 3) symbol fallback（兼容历史/Legacy Outcome）
    if not entry_exec:
        entry_exec = _find_any_execution(outcome.get('symbol', ''), action='BUY', status=EXECUTED)
        if entry_exec:
            exit_executions = find_exit_executions(entry_exec.get('execution_id', ''))
    # 当前退出段存储在 entry execution 的 exit_segments 中；若未分离出独立 exit file，
    # 则将 entry execution 作为 exit_executions 的代表，保证 replay 可展示。
    if not exit_executions and entry_exec and entry_exec.get('exit_segments'):
        exit_executions = [entry_exec]
    if did:
        dp = Path(__file__).resolve().parent / 'snapshots' / f"{did}.json"
        if dp.exists():
            entry_decision = json.load(open(dp))
    return {
        'ok': True,
        'outcome': outcome,
        'exit_executions': exit_executions,
        'entry_execution': entry_exec,
        'entry_decision': entry_decision,
        'position_id': position_id,
        'linkage': (entry_exec or {}).get('linkage', ''),
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
    linkage_fallback_count = 0
    production_linkage = 0
    shadow_count = 0

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
    # Execution linkage 统计
    for f in exes:
        try:
            e = json.load(open(f))
        except Exception:
            continue
        if not e.get('actual', {}).get('price'):
            integrity['execution_no_position'] += 1
        if e.get('position_status') == OPEN and not e.get('exit_segments'):
            pass
        link = e.get('linkage', '')
        if link == LINKAGE_FALLBACK:
            linkage_fallback_count += 1
        elif link == 'STRUCTURED':
            production_linkage += 1
        if e.get('source') == SRC_SHADOW or e.get('strategy', '').lower() == 'main_up':
            shadow_count += 1
    # CLOSED position 无 outcome
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
        'linkage_fallback_count': linkage_fallback_count,
        'production_linkage': production_linkage,
        'shadow_count': shadow_count,
    }


def _json_field(f, key):
    try:
        return json.load(open(f)).get(key)
    except Exception:
        return None
