#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Snapshot Persistence Self-Check（Phase 8-K1）

职责：确认一个已生成的 Final Decision 确实可靠落盘。
不做任何业务判断、不重新 Decision、不修改 decision_id。

用法（canonical writer 保存后调用）：
    from decision.snapshot_verify import verify_and_ensure_persisted
    status, path_or_err = verify_and_ensure_persisted(decision)

status ∈ {PERSISTED, PERSISTED_EXISTING, FAILED}
"""

import json
import os
from pathlib import Path

SNAP_MODULE = None


def _snap_module():
    global SNAP_MODULE
    if SNAP_MODULE is None:
        import decision.snapshot as s
        SNAP_MODULE = s
    return SNAP_MODULE


def verify_decision_snapshot(decision_id: str, snap_dir: str | None = None) -> tuple[str, str]:
    """校验快照文件存在、可解析、identity 一致。

    返回 (PERSISTED, path) 或 (FAILED, error_message)。
    """
    s = _snap_module()
    dirp = snap_dir or s.SNAP_DIR
    path = os.path.join(dirp, f"{decision_id}.json")
    if not os.path.exists(path):
        return 'FAILED', f'snapshot file missing: {path}'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        return 'FAILED', f'snapshot unreadable/malformed: {path}: {e}'
    # identity 校验：decision_id 必须一致（防错位/覆盖）
    if d.get('decision_id') != decision_id:
        return 'FAILED', (f"decision_id mismatch in {path}: "
                          f"expected {decision_id}, got {d.get('decision_id')}")
    for field in ('symbol', 'action', 'timestamp'):
        if not d.get(field):
            return 'FAILED', f'snapshot missing field {field}: {path}'
    return 'PERSISTED', path


def persist_with_verification(decision, max_retries: int = 2,
                              snap_dir: str | None = None) -> tuple[str, str]:
    """Canonical 持久化 + 自校验 + 受控重试（仅重试写入，绝不重算 Decision）。

    幂等：save_snapshot 已存在即返回不覆盖；verify 通过则 PERSISTED_EXISTING。
    返回 (status, path_or_error)。status ∈ {PERSISTED, PERSISTED_EXISTING, FAILED}
    """
    s = _snap_module()
    dirp = snap_dir or s.SNAP_DIR
    expected_path = os.path.join(dirp, f"{decision.decision_id}.json")

    last_err = ''
    for attempt in range(1, max_retries + 1):
        try:
            s.save_snapshot(decision, snap_dir=dirp)
        except Exception as e:
            last_err = f'save_snapshot raised on attempt {attempt}: {e}'
            continue
        status, info = verify_decision_snapshot(decision.decision_id, dirp)
        if status == 'PERSISTED':
            if os.path.getmtime(expected_path) < ( __import__('time').time() - 5 ):
                # 已存在的历史快照（本次运行前就有）→ 幂等命中
                return 'PERSISTED_EXISTING', expected_path
            return 'PERSISTED', expected_path
        last_err = f'verify failed on attempt {attempt}: {info}'
    return 'FAILED', last_err


def format_persistence_failure(symbol: str, action: str, decision_id: str, error: str,
                               timestamp: str = '') -> str:
    """persistence 失败的醒目告警文本（唯一允许的用户可见变化）。"""
    return (
        "🚨 FINAL DECISION PERSISTENCE FAILED 🚨\n"
        f"  symbol: {symbol}\n"
        f"  action: {action}\n"
        f"  decision_id: {decision_id}\n"
        f"  time: {timestamp}\n"
        f"  error: {error}\n"
        "  ⚠️ 该决策无法回溯，请人工记录！不得视为已入 Daily Decision。\n"
        "  标记: DECISION_PERSISTENCE_FAILED"
    )
