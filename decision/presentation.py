#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Presentation Taxonomy（Phase 8-K2）

只做展示层分类与过滤：
- 六类层级标签：FINAL / URGENT / SIGNAL / INFORMATION / HEALTH / DEBUG
- DEBUG 过滤：debug 标记不进入用户面（工程日志保留）
- 不创建任何 Decision，不改变内容语义。

Hierarchy（展示优先级，非 Authority）：
FINAL > URGENT > SIGNAL > INFORMATION > HEALTH > DEBUG
Authority 仍唯一属于 DecisionEngine。
"""

import re

# ── 层级标签 ──────────────────────────────────────────────
LABEL_FINAL = '【FINAL】'
LABEL_URGENT = '【URGENT · FINAL】'
LABEL_SIGNAL = '【SIGNAL · 非最终决策】'
LABEL_INFO = '【INFO】'
LABEL_HEALTH = '【HEALTH】'

FINAL_ACTIONS = ('BUY', 'ADD', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE')


def final_label(action: str) -> str:
    """Final Action 标签。要求调用方已持有 DecisionEngine 决策与 decision_id。"""
    return LABEL_FINAL


# ── DEBUG 过滤（User Surface Sanitizer）──────────────────
_DEBUG_PATTERNS = (
    r'\[BRANCH\]',
    r'\[DEBUG\]',
    r'\[RC-REFRESH\]',
    r'\[REPORT\]',
    r'\[PERSIST\]',
    r'Traceback \(most recent call last\)',
    r'^  File ".*$",',
    r'^\s*File "/.*\.py", line \d+',
    r'/home/caojy/',
)

_COMPILED = [re.compile(p, re.MULTILINE) for p in _DEBUG_PATTERNS]


def is_debug_line(line: str) -> bool:
    """单行是否属于 Debug/Diagnostic 内容（不得进入用户主消息）。"""
    for c in _COMPILED:
        if c.search(line):
            return True
    return False


def sanitize_user_surface(text: str, max_report: int = 20) -> tuple[str, int]:
    """从用户可见文本中剔除 DEBUG 行。

    返回 (clean_text, removed_count)。工程日志请使用原始文本另行落盘。
    """
    kept, removed = [], 0
    for line in text.splitlines():
        if is_debug_line(line):
            removed += 1
            continue
        kept.append(line)
    clean = '\n'.join(kept)
    # Traceback 整块兜底：若仍有 traceback 关键字，替换为用户可读提示
    if 'Traceback' in clean:
        clean += '\n⚠️ 系统数据异常，请关注 HEALTH 报告。'
        removed += 1
    return clean, removed
