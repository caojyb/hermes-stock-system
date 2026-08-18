#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一候选池加载器（替代废弃的 double_pool.json）
================================================
统一从 double_up_scores 表（market_cache.db）读取最新一期翻倍 V1 候选池，
替代旧 double_refresh.py 写的 double_pool.json（已停用）。

用法:
    from pool_loader import load_pool, load_pool_codes

    pool = load_pool()          # -> [{'code','name','sector'}, ...]
    codes = load_pool_codes()   # -> ['002212', ...]
"""
import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))


def _record_pool_status(scan_date, reason):
    """候选池为空/异常时记录 pipeline_status=error，让 cron 监控可见。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_status import record_status
        record_status('pool-loader', 'error', scan_date or 'unknown',
                      row_count=0, message=f'候选池空池/异常: {reason}')
    except Exception:
        pass


def load_pool(scan_date=None):
    """读取 double_up_scores 最新一期候选池。

    返回 [{'code','name','sector','total_score'}, ...]，
    与旧 double_pool.json 的 stocks 结构兼容（code/name/sector 字段一致）。
    """
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=30)
        cur = conn.cursor()
        if scan_date is None:
            cur.execute("SELECT MAX(scan_date) FROM double_up_scores")
            scan_date = cur.fetchone()[0]
        if not scan_date:
            conn.close()
            _record_pool_status(None, 'double_up_scores 表为空或无最新一期')
            return []
        cur.execute("""
            SELECT code, name, sector, total_score
            FROM double_up_scores
            WHERE scan_date = ?
            ORDER BY total_score DESC
        """, (scan_date,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _record_pool_status(scan_date, f'最新一期 {scan_date} 候选池为 0 行')
            return []
        return [
            {'code': r[0], 'name': r[1], 'sector': r[2], 'total_score': r[3]}
            for r in rows
        ]
    except Exception as e:
        print(f"[pool_loader] 读取候选池失败: {e}", file=sys.stderr)
        _record_pool_status(scan_date, f'读取异常: {e}')
        return []


def load_pool_codes(scan_date=None):
    """只返回候选池代码列表。"""
    return [p['code'] for p in load_pool(scan_date)]


def load_pool_date():
    """返回最新一期候选池的扫描日期。"""
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=30)
        cur = conn.cursor()
        cur.execute("SELECT MAX(scan_date) FROM double_up_scores")
        sd = cur.fetchone()[0]
        conn.close()
        return sd
    except Exception:
        return None


if __name__ == '__main__':
    print(f"候选池日期: {load_pool_date()}")
    print(f"候选池 {len(load_pool())} 只:")
    for p in load_pool():
        print(f"  {p['code']} {p['name']:10s} {p['sector']}")
