#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K2 M-5：Debug 分流器。

把 [BRANCH]/[REPORT]/[PERSIST]/[DEBUG] 等工程诊断 print 从 stdout（Feishu 用户面）
分流到 logs/double_monitor_debug.log。完整 Debug 保留，不删除日志。

只拦截 print，不改任何业务逻辑。
"""

import builtins
import os
import sys
from datetime import datetime

_DEBUG_MARKERS = ('[BRANCH]', '[REPORT]', '[PERSIST]', '[DEBUG]', '[RC-REFRESH]')

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
_LOG_PATH = os.path.join(_LOG_DIR, 'double_monitor_debug.log')

_original_print = builtins.print


def _shunted_print(*args, **kwargs):
    try:
        text = ' '.join(str(a) for a in args)
    except Exception:
        return _original_print(*args, **kwargs)
    if any(m in text for m in _DEBUG_MARKERS):
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {text}\n")
        except Exception:
            pass  # 日志失败不得影响主流程
        kwargs_out = {k: v for k, v in kwargs.items() if k == 'file'}
        if kwargs.get('file') is not None:
            return _original_print(*args, **kwargs)
        return None  # 用户面静默
    return _original_print(*args, **kwargs)


builtins.print = _shunted_print
