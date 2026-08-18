#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Replay — 决策回放（Phase 2）

给定 decision_id，恢复当时的完整 Decision（Regime/Permission/Strategy/
Candidate/Entry/Portfolio/Risk/Exit/Reason Codes/Version）。

若数据不足以完整 replay，如实报告缺什么，不伪造。
"""
from __future__ import annotations

from .contract import Decision
from .snapshot import load_snapshot, snapshot_exists


def replay(decision_id: str, snap_dir: str = None) -> dict:
    """回放一条决策，返回完整 Decision dict + replay 完整性说明。"""
    if not snapshot_exists(decision_id, snap_dir):
        return {
            'ok': False,
            'decision_id': decision_id,
            'missing': ['decision snapshot 不存在，无法回放'],
        }
    dec = load_snapshot(decision_id, snap_dir)
    d = dec.to_dict()
    # 完整性检查：核心字段是否都有
    required = ['action', 'regime_label', 'permission_status', 'strategy',
                'reason_codes', 'symbol']
    missing = [f for f in required if not d.get(f)]
    return {
        'ok': True,
        'decision_id': decision_id,
        'decision': d,
        'missing': missing,
    }


def replay_markdown(decision_id: str, snap_dir: str = None) -> str:
    """回放为人类可读 Markdown（审计用）。"""
    r = replay(decision_id, snap_dir)
    if not r['ok']:
        return f"无法回放 {decision_id}: {r['missing']}"
    d = r['decision']
    lines = [
        f"# Decision Replay: {decision_id}",
        f"- action: **{d.get('action')}**",
        f"- symbol: {d.get('symbol')} ({d.get('name','')})",
        f"- timestamp: {d.get('timestamp')} / as_of: {d.get('as_of_time')}",
        f"- market_regime: {d.get('market_regime')} ({d.get('regime_label','')} score={d.get('regime_score')})",
        f"- permission: {d.get('permission_status')} {d.get('permission')}",
        f"- strategy: {d.get('strategy')} v{d.get('strategy_version')}",
        f"- candidate: qualified={d.get('candidate_qualified')} score={d.get('candidate_score')}",
        f"- entry: {d.get('entry_signal')} {d.get('entry_signals')}",
        f"- target_position: {d.get('target_position')} @ {d.get('reference_price')}",
        f"- portfolio: drawdown={d.get('portfolio_drawdown')} positions={d.get('position_count')}",
        f"- exit: {d.get('exit_signal')} triggers={d.get('exit_triggers')}",
        f"- reason_codes: {d.get('reason_codes')}",
        f"- versions: config={d.get('config_version')} code={d.get('code_version')}",
        f"- explanation: {d.get('explanation')}",
    ]
    if r['missing']:
        lines.append(f"- ⚠️ 缺失: {r['missing']}")
    return "\n".join(lines)
