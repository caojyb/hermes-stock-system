#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Snapshot — 决策冻结（Phase 2）

每次最终 Decision 生成后，可冻结为不可变 JSON 文件。
后续配置变化不改变历史 Decision 内容。

存储：复用现有文件系统 JSON（不新建复杂数据库，不改现有 DB schema）。
目录：<SNAP_DIR>/<decision_id>.json
"""
from __future__ import annotations
import json, os, glob
from pathlib import Path

from .contract import Decision

# 默认快照目录（可按需覆盖）
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshots')


def save_snapshot(decision: Decision, snap_dir: str = None, overwrite=False) -> str:
    """冻结 Decision 到 JSON 文件。返回文件路径。"""
    d = decision.freeze()
    dirp = snap_dir or SNAP_DIR
    Path(dirp).mkdir(parents=True, exist_ok=True)
    path = os.path.join(dirp, f"{decision.decision_id}.json")
    if os.path.exists(path) and not overwrite:
        return path  # 已存在不覆盖（历史不可变）
    # 写入前清理过期 snapshot，避免目录无限膨胀
    try:
        prune_old_snapshots(days=30, snap_dir=dirp)
    except Exception:
        pass
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return path


def load_snapshot(decision_id: str, snap_dir: str = None) -> Decision:
    """按 decision_id 恢复冻结的 Decision。"""
    dirp = snap_dir or SNAP_DIR
    path = os.path.join(dirp, f"{decision_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Decision snapshot 不存在: {path}")
    with open(path, encoding='utf-8') as f:
        return Decision.from_dict(json.load(f))


def list_snapshots(snap_dir: str = None) -> list:
    dirp = snap_dir or SNAP_DIR
    if not os.path.isdir(dirp):
        return []
    return sorted(glob.glob(os.path.join(dirp, '*.json')))


def prune_old_snapshots(days: int = 30, snap_dir: str = None) -> int:
    """清理超过 days 天的 snapshot，返回删除数量。"""
    dirp = snap_dir or SNAP_DIR
    if not os.path.isdir(dirp):
        return 0
    cutoff = __import__('datetime').datetime.now().timestamp() - days * 86400
    removed = 0
    for fp in glob.glob(os.path.join(dirp, '*.json')):
        try:
            if os.path.getmtime(fp) < cutoff:
                os.remove(fp)
                removed += 1
        except OSError:
            pass
    return removed


def snapshot_exists(decision_id: str, snap_dir: str = None) -> bool:
    return os.path.exists(os.path.join(snap_dir or SNAP_DIR, f"{decision_id}.json"))
