#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票系统管道状态跟踪模块。

为所有 cron 任务提供：
1. record_status() — 记录任务完成状态
2. check_upstream() — 检查上游任务是否已成功完成
3. check_dependencies() — 批量检查依赖链

用法（脚本末尾）：
    from pipeline_status import record_status
    record_status('daily-data-refresh', 'ok', today_str, row_count=n, message='...')

用法（下游脚本开头）：
    from pipeline_status import check_upstream
    if not check_upstream('stock-market-cache-refresh', max_age_minutes=120):
        print('[WARN] market_cache 未更新，数据可能陈旧')
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ── 数据库路径（与 stock_db_paths.yaml 一致） ──
MARKET_DB = Path(os.path.expanduser(
    '~/.hermes/skills/stock/stock-expert/market_cache.db'
))


def _get_conn():
    """获取 market_cache.db 连接，确保 pipeline_status 表存在"""
    conn = sqlite3.connect(str(MARKET_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_status (
            task_name TEXT NOT NULL,
            status TEXT NOT NULL,          -- ok / error / skipped
            data_date TEXT,                -- 数据日期 (如 2026-08-05)
            row_count INTEGER,             -- 处理行数（可选）
            message TEXT,                  -- 状态描述（可选）
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (task_name, created_at)
        )
    """)
    conn.commit()
    return conn


def record_status(task_name: str, status: str, data_date: str = None,
                  row_count: int = None, message: str = None):
    """
    记录一个 cron 任务的完成状态。

    参数：
        task_name: 任务名称（如 'daily-data-refresh'）
        status: 'ok' / 'error' / 'skipped'
        data_date: 数据对应的日期（如 '2026-08-05'）
        row_count: 处理的数据行数
        message: 状态描述
    """
    conn = _get_conn()
    conn.execute("""
        INSERT INTO pipeline_status (task_name, status, data_date, row_count, message)
        VALUES (?, ?, ?, ?, ?)
    """, (task_name, status, data_date, row_count, message))
    conn.commit()
    conn.close()


def get_latest_status(task_name: str) -> dict:
    """获取指定任务的最新状态记录"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT task_name, status, data_date, row_count, message, created_at
        FROM pipeline_status
        WHERE task_name = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (task_name,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            'task_name': row[0],
            'status': row[1],
            'data_date': row[2],
            'row_count': row[3],
            'message': row[4],
            'created_at': row[5],
        }
    return None


def check_upstream(task_name: str, max_age_minutes: int = 120) -> bool:
    """
    检查上游任务是否已成功完成且数据新鲜。

    返回 True 表示数据可用，False 表示需要告警。

    参数：
        task_name: 上游任务名称
        max_age_minutes: 允许的最大数据年龄（分钟）
    """
    status = get_latest_status(task_name)
    if status is None:
        print(f"  [PIPELINE] ⚠️ {task_name} 从未执行过记录")
        return False

    if status['status'] != 'ok':
        print(f"  [PIPELINE] ⚠️ {task_name} 上次状态为 {status['status']} "
              f"(于 {status['created_at']})")
        return False

    # 检查数据新鲜度
    try:
        created = datetime.strptime(status['created_at'], '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        created = datetime.now() - timedelta(days=365)

    age_minutes = (datetime.now() - created).total_seconds() / 60
    if age_minutes > max_age_minutes:
        print(f"  [PIPELINE] ⚠️ {task_name} 数据已过时 "
              f"({age_minutes:.0f} 分钟前, 限制 {max_age_minutes} 分钟)")
        return False

    print(f"  [PIPELINE] ✅ {task_name} 数据新鲜 "
          f"({age_minutes:.0f} 分钟前, 数据日期 {status.get('data_date', '?')})")
    return True


def check_dependencies(deps: list) -> dict:
    """
    批量检查多个上游依赖。

    参数：
        deps: [(task_name, max_age_minutes), ...]

    返回：
        {'all_ok': bool, 'results': {task_name: bool, ...}}
    """
    results = {}
    all_ok = True
    for task_name, max_age in deps:
        ok = check_upstream(task_name, max_age)
        results[task_name] = ok
        if not ok:
            all_ok = False
    return {'all_ok': all_ok, 'results': results}


def list_recent_runs(task_name: str, limit: int = 5) -> list:
    """列出指定任务最近的运行记录"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT task_name, status, data_date, row_count, message, created_at
        FROM pipeline_status
        WHERE task_name = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (task_name, limit))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            'task_name': r[0],
            'status': r[1],
            'data_date': r[2],
            'row_count': r[3],
            'message': r[4],
            'created_at': r[5],
        }
        for r in rows
    ]


def list_all_tasks() -> list:
    """列出所有有记录的任务及其最新状态"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p1.task_name, p1.status, p1.data_date, p1.row_count, p1.created_at
        FROM pipeline_status p1
        LEFT JOIN pipeline_status p2
            ON p1.task_name = p2.task_name AND p1.created_at < p2.created_at
        WHERE p2.created_at IS NULL
        ORDER BY p1.task_name
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            'task_name': r[0],
            'status': r[1],
            'data_date': r[2],
            'row_count': r[3],
            'created_at': r[4],
        }
        for r in rows
    ]


if __name__ == '__main__':
    # 测试
    print("=== 当前所有任务状态 ===")
    for t in list_all_tasks():
        print(f"  {t['task_name']}: {t['status']} | {t['data_date']} | {t['created_at']}")
