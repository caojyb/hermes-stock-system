#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日收盘后数据刷新脚本（Hermes 原生版）
=====================
统一刷新:
1. indicators 日更（与 klines 最新日期对齐）
2. 北向资金 north_flow 写入 indicators
3. 主力资金 main_fund_flow 写入 market_cache（eastmoney MCP + westock 保底）
4. 龙虎榜 lhb_data 写入 lhb_cache.db（eastmoney + westock 保底）
5. 热门概念 board/hot concept 写入 westock_cache.board_cache

数据源:
- Hermes 内建 MCP（eastmoney）
- westock-data-skillhub（腾讯自选股）
- push2delay.eastmoney.com（北向资金保底）
- tdx（可选增强，仅 agent 直连；不参与 cron 主线）

用法:
  python3 daily_data_refresh.py
  python3 daily_data_refresh.py --date 2026-07-24
"""
import os
import sys
import json
import sqlite3
import subprocess
from datetime import datetime
from typing import List, Tuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))
WESTOCK_DB = str(get_db_path('westock_cache'))
LHB_DB = str(get_db_path('lhb_cache'))
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# westock batch script path
WESTOCK_BATCH = '/home/caojy/.hermes/skills/stock/stock-data-sources/scripts/westock_batch.py'


def get_latest_klines_date():
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('SELECT MAX(date) FROM klines')
    latest = cur.fetchone()[0]
    con.close()
    return latest


def get_stocks() -> List[Tuple[str, str, str]]:
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('SELECT code, name, market FROM stocks WHERE code NOT LIKE "688%" AND code NOT LIKE "787%"')
    rows = cur.fetchall()
    con.close()
    return rows


# ======================== 北向资金 ========================

def fetch_northbound_batch():
    """批量获取北向资金数据（全市场）"""
    import requests
    url = 'http://push2delay.eastmoney.com/api/qt/clist/get'
    result = {}
    session = requests.Session()
    session.proxies = {'http': None, 'https': None}
    total_pages = 60
    for page in range(1, total_pages + 1):
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f14,f62,f71,f184,f185'
        }
        try:
            r = session.get(url, params=params, timeout=15, headers=HEADERS)
            payload = r.json() or {}
            data = payload.get('data') or {}
            if isinstance(data, dict):
                total_pages = min(total_pages, max(1, int(data.get('total', 0)) // 100 + 1))
            items = data.get('diff') if isinstance(data, dict) else []
            if not items:
                break
            for item in items:
                code = item.get('f12', '')
                net_buy = item.get('f62', 0) or 0
                hold_value = item.get('f71', 0) or 0
                hold_pct = item.get('f184', 0) or 0
                if code and (net_buy != 0 or hold_value != 0):
                    result[code] = {
                        'net_buy': net_buy,
                        'hold_value': hold_value,
                        'hold_pct': hold_pct,
                    }
        except Exception as e:
            print(f'  北向第{page}页失败: {e}')
            continue
    return result


# ======================== 东方财富 MCP ========================

def fetch_main_fund_rank(date_str):
    """获取主力资金净流入排行（东方财富 push2）"""
    import requests
    url = 'http://push2.eastmoney.com/api/qt/clist/get'
    params = {
        'pn': 1, 'pz': 100, 'po': 1, 'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2, 'invt': 2, 'fid': 'f62',
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': 'f12,f14,f62,f184'
    }
    try:
        r = requests.get(url, params=params, timeout=15, headers=HEADERS)
        data = r.json().get('data', {})
        items = data.get('diff', []) if isinstance(data, dict) else []
        results = []
        for it in items:
            code = it.get('f12', '')
            name = it.get('f14', '')
            net_amt = it.get('f62', 0) or 0
            main_pct = it.get('f184', 0) or 0
            if code:
                results.append({
                    'code': code,
                    'name': name,
                    'net_amt': net_amt,
                    'main_pct': main_pct,
                    'date': date_str,
                })
        return results
    except Exception as e:
        print(f'  主力资金获取失败: {e}')
        return []


def fetch_lhb(date_str):
    """获取龙虎榜数据（带重试，最多3次）"""
    import requests
    import time
    url = 'https://datacenter.eastmoney.com/securities/api/data/v1/get'
    params = {
        'reportName': 'RPT_DAILYBILLBOARD_DETAILSNEW',
        'columns': 'SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,BILLBOARD_DEAL_AMT,ACCUM_AMOUNT,TURNOVERRATE,FREE_MARKET_CAP',
        'filter': f"(TRADE_DATE='{date_str}')",
        'pageNumber': 1,
        'pageSize': 200,
        'sortTypes': -1,
        'sortColumns': 'BILLBOARD_NET_AMT',
    }
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, timeout=20, headers=HEADERS)
            d = r.json()
            if not d.get('success') or not d.get('result'):
                if attempt < max_retries:
                    wait = attempt * 5
                    print(f'  龙虎榜 API 返回空 (第{attempt}次), {wait}s 后重试...')
                    time.sleep(wait)
                    continue
                return []
            rows = d['result']['data']
            results = []
            for row in rows:
                secucode = row.get('SECUCODE', '')
                code = row.get('SECURITY_CODE', '') or secucode.split('.')[0] if '.' in secucode else secucode
                results.append({
                    'code': code,
                    'name': row.get('SECURITY_NAME_ABBR', ''),
                    'trade_date': date_str,
                    'close_price': row.get('CLOSE_PRICE', 0) or 0,
                    'change_rate': row.get('CHANGE_RATE', 0) or 0,
                    'net_amt': row.get('BILLBOARD_NET_AMT', 0) or 0,
                    'buy_amt': row.get('BILLBOARD_BUY_AMT', 0) or 0,
                    'sell_amt': row.get('BILLBOARD_SELL_AMT', 0) or 0,
                    'deal_amt': row.get('BILLBOARD_DEAL_AMT', 0) or 0,
                    'accum_amt': row.get('ACCUM_AMOUNT', 0) or 0,
                    'turnover_rate': row.get('TURNOVERRATE', 0) or 0,
                    'free_mcap': row.get('FREE_MARKET_CAP', 0) or 0,
                    'explain': row.get('EXPLAIN', '') or '',
                    'fetched_at': datetime.now().isoformat(),
                })
            return results
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 5
                print(f'  龙虎榜获取失败: {e} (第{attempt}次), {wait}s 后重试...')
                time.sleep(wait)
            else:
                print(f'  龙虎榜获取失败(已重试{max_retries}次): {e}')
                return []
    return []


# ======================== indicators / northbound ========================

def ensure_indicator_cols(cur):
    cur.execute('PRAGMA table_info(indicators)')
    cols = [r[1] for r in cur.fetchall()]
    for col in ['north_flow', 'north_hold_value', 'north_hold_pct']:
        if col not in cols:
            cur.execute(f'ALTER TABLE indicators ADD COLUMN {col} REAL')
    # A/B/C/D 信号列（翻倍策略统一信号源）
    for col in ['signal_a', 'signal_b', 'signal_c', 'signal_d']:
        if col not in cols:
            cur.execute(f'ALTER TABLE indicators ADD COLUMN {col} INTEGER DEFAULT 0')


def refresh_indicators(latest_date):
    """只更新 indicators 中最新日期落后的股票"""
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    ensure_indicator_cols(cur)

    cur.execute('''
        SELECT s.code, s.name, s.market
        FROM stocks s
        JOIN klines k ON k.code = s.code AND k.date = ?
        WHERE s.code NOT LIKE "688%" AND s.code NOT LIKE "787%"
    ''', (latest_date,))
    missing = cur.fetchall()
    if not missing:
        print('indicators 已是最新，无需更新')
        con.close()
        return 0

    print(f'indicators 重算 {len(missing)} 只股票信号到 {latest_date}')
    updated = 0
    for code, name, market in missing:
        try:
            cur.execute('''
                SELECT close, high, low, volume, turnover, amplitude, change_pct
                FROM klines
                WHERE code=? AND date=?
                ORDER BY ROWID DESC LIMIT 1
            ''', (code, latest_date))
            k = cur.fetchone()
            if not k or not k[0]:
                continue
            close, high, low, volume, turnover, amplitude, change_pct = k
            prev_close = close / (1 + change_pct / 100) if change_pct else close

            # 计算 MA/BOLL/RSI（简化版）
            cur.execute('SELECT close, volume FROM klines WHERE code=? ORDER BY date DESC LIMIT 20', (code,))
            recent = cur.fetchall()
            recent.reverse()
            closes_60 = [r[0] for r in recent if r[0] is not None]
            volumes_20 = [r[1] for r in recent if r[1] is not None]
            closes = closes_60
            cur.execute('SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 60', (code,))
            closes_60_full = [r[0] for r in cur.fetchall() if r[0] is not None]
            closes_60_full.reverse()
            if len(closes_60_full) >= 60:
                closes = closes_60_full

            ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
            ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
            ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None

            vol_ratio = None
            if len(volumes_20) >= 20:
                vol_5 = sum(volumes_20[-5:]) / 5
                vol_20 = sum(volumes_20[-20:]) / 20
                vol_ratio = vol_5 / vol_20 if vol_20 > 0 else None

            boll_mid = ma20
            if len(closes) >= 20:
                boll_std = (sum((x - boll_mid) ** 2 for x in closes[-20:]) / 20) ** 0.5
                boll_upper = boll_mid + 2 * boll_std
                boll_lower = boll_mid - 2 * boll_std
            else:
                boll_upper = boll_lower = None
            boll_position = 50.0
            if boll_upper and boll_lower and boll_upper != boll_lower and close:
                boll_position = (close - boll_lower) / (boll_upper - boll_lower) * 100
                boll_position = max(0.0, min(100.0, boll_position))

            def rsi14(vals):
                if len(vals) < 15:
                    return None
                gains, losses = [], []
                for i in range(-14, 0):
                    delta = vals[i] - vals[i-1]
                    gains.append(max(0, delta))
                    losses.append(max(0, -delta))
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss == 0:
                    return 100.0
                rs = avg_gain / avg_loss
                return 100 - 100 / (1 + rs)

            rsi = rsi14(closes) if len(closes) >= 15 else None

            # ═══ A/B/C/D 信号计算 ═══
            signal_a = signal_b = signal_c = signal_d = 0
            # A: 站上20日均线+均线拐头
            if len(closes) >= 21:
                ma20 = sum(closes[-20:]) / 20
                ma20_prev = sum(closes[-21:-1]) / 20
                if close > ma20 and ma20 >= ma20_prev:
                    signal_a = 1
            # B: 倍量启动（3日量比10日均值>1.8）
            cur.execute('SELECT volume FROM klines WHERE code=? ORDER BY date DESC LIMIT 13', (code,))
            vol_rows = [r[0] for r in cur.fetchall() if r[0] is not None]
            if len(vol_rows) >= 13:
                vol_rows.reverse()
                v3 = sum(vol_rows[-3:])
                v10 = sum(vol_rows[-13:-3]) / 10
                if v10 > 0 and v3 > v10 * 1.8:
                    signal_b = 1
            # C: 创20日新高
            cur.execute('SELECT high FROM klines WHERE code=? ORDER BY date DESC LIMIT 20', (code,))
            high_rows = [r[0] for r in cur.fetchall() if r[0] is not None]
            if len(high_rows) >= 20 and high_rows[0] is not None and close is not None:
                if close >= max(high_rows):
                    signal_c = 1
            # D: MACD零轴上方金叉
            if len(closes) >= 35:
                def ema(vals, period):
                    k = 2 / (period + 1)
                    res = [vals[0]]
                    for x in vals[1:]:
                        res.append(x * k + res[-1] * (1 - k))
                    return res
                dif = [ema(closes, 12)[i] - ema(closes, 26)[i] for i in range(len(closes))]
                dea_full = ema(dif[-20:], 9) if len(dif) >= 20 else [0]
                if len(dif) >= 2 and len(dea_full) >= 2:
                    dc, dp = dif[-1], dif[-2]
                    dea_c, dea_p = dea_full[-1], dea_full[-2]
                    if (dp < dea_p and dc > dea_c) or (dc > 0 and dea_c > 0 and dc > dea_c):
                        signal_d = 1
            # 重算 ma20（防止被信号计算覆盖）
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None

            cur.execute('''
                INSERT OR REPLACE INTO indicators (
                    code, date, current_price, prev_close, change_pct,
                    rsi_14, macd, macd_signal, macd_hist,
                    boll_middle, boll_upper, boll_lower, boll_position,
                    ma5, ma10, ma20, ma60, ma_bullish, atr_14,
                    signal_score, signal_level, updated_at,
                    turnover_rate, turnover_5d_avg, turnover_20d_avg, vol_ratio,
                    limit_up_count_60d, is_60d_high, is_60d_low,
                    north_flow, north_hold_value, north_hold_pct,
                    relative_strength, turnover_zscore,
                    ps_ttm, pcf_ttm,
                    alternative_score,
                    signal_a, signal_b, signal_c, signal_d
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code, latest_date, close, prev_close, change_pct,
                rsi, None, None, None,
                boll_mid, boll_upper, boll_lower, boll_position,
                ma5, ma10, ma20, ma60, 0, None,
                0, 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                turnover, None, None, vol_ratio,
                None, 0, 0,
                None, None, None,
                None, None,
                None, None,
                None,
                signal_a, signal_b, signal_c, signal_d
            ))
            updated += 1
            if updated % 200 == 0:
                con.commit()
                print(f'  indicators 更新进度: {updated}/{len(missing)}')
        except Exception as e:
            if updated < 5:
                print(f'  {code} {name} indicators 更新异常: {e}')
    con.commit()
    con.close()
    print(f'indicators 更新完成: {updated}')
    return updated


def refresh_northbound():
    """刷新北向资金到 indicators"""
    print('刷新北向资金...')
    north = fetch_northbound_batch()
    if not north:
        print('  北向资金获取为空')
        return 0
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    ensure_indicator_cols(cur)
    updated = 0
    for code, v in north.items():
        cur.execute('''
            UPDATE indicators
            SET north_flow=?, north_hold_value=?, north_hold_pct=?
            WHERE code=?
        ''', (v['net_buy'], v['hold_value'], v['hold_pct'], code))
        if cur.rowcount > 0:
            updated += 1
    con.commit()
    con.close()
    print(f'北向资金更新 {updated} 只')
    return updated


# ======================== 主力资金 ========================

def refresh_main_fund_flow(date_str):
    """
    刷新主力资金到 market_cache.main_fund_flow
    数据源：
    1) eastmoney 主力资金排行
    2) westock asfund 逐股查询（持仓/样本股保底）
    """
    print('刷新主力资金...')
    rows = fetch_main_fund_rank(date_str)
    if rows:
        con = sqlite3.connect(MARKET_DB)
        cur = con.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS main_fund_flow (
                code TEXT,
                date TEXT,
                net_amt REAL,
                PRIMARY KEY(code, date)
            )
        ''')
        for r in rows:
            cur.execute('INSERT OR REPLACE INTO main_fund_flow (code, date, net_amt) VALUES (?, ?, ?)',
                        (r['code'], r['date'], r['net_amt']))
        con.commit()
        con.close()
        print(f'主力资金 eastmoney 写入 {len(rows)} 条')

    westock_count = _refresh_westock_main_fund_flow(date_str)
    if westock_count:
        print(f'主力资金 westock 补写 {westock_count} 条')

    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM main_fund_flow WHERE date=?', (date_str,))
    count = cur.fetchone()[0]
    con.close()
    print(f'主力资金合计 {count} 条')
    return count


def _westock_client():
    sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-data-sources/lib')
    from data_client import get_client
    return get_client()


def _market_prefix(code: str) -> str:
    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('SELECT market FROM stocks WHERE code=? ORDER BY ROWID DESC LIMIT 1', (code,))
    row = cur.fetchone()
    con.close()
    if row and row[0]:
        m = str(row[0]).lower()
        if m in ('sz', 'sh'):
            return f'{m}{code}'
    return code


def _refresh_westock_main_fund_flow(date_str: str, batch_size: int = 10) -> int:
    """westock asfund 逐股/小批量保底（已知大批量会返回空，所以只查样本股）"""
    try:
        client = _westock_client()
    except Exception as e:
        print(f'  westock data_client 加载失败: {e}')
        return 0

    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS main_fund_flow (
            code TEXT,
            date TEXT,
            net_amt REAL,
            PRIMARY KEY(code, date)
        )
    ''')
    cur.execute('SELECT code FROM stocks WHERE code NOT LIKE "688%" AND code NOT LIKE "787%" ORDER BY code LIMIT 50')
    rows = cur.fetchall()
    con.close()
    codes = [_market_prefix(r[0]) for r in rows if r and r[0]]
    if not codes:
        return 0

    inserted = 0
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        code_str = ','.join(batch)
        r = client.westock_asfund(code_str, date=date_str)
        if not r.get('success') or not isinstance(r.get('parsed'), list):
            continue
        con = sqlite3.connect(MARKET_DB)
        cur = con.cursor()
        for row in r['parsed']:
            code = row.get('SecuCode') or row.get('code') or ''
            if not code:
                continue
            try:
                main_net = float(row.get('MainNetFlow') or 0)
            except (TypeError, ValueError):
                main_net = 0.0
            try:
                main_pct = float(row.get('MainInflowCircRate') or 0)
            except (TypeError, ValueError):
                main_pct = 0.0
            cur.execute('INSERT OR REPLACE INTO main_fund_flow (code, date, net_amt) VALUES (?, ?, ?)',
                        (code, date_str, main_net))
            inserted += 1
        con.commit()
        con.close()
    return inserted


# ======================== 龙虎榜 ========================

def refresh_lhb(date_str):
    """
    刷新龙虎榜到 lhb_cache.db
    数据源：
    1) eastmoney 龙虎榜
    2) westock lhb 逐股查询（样本股保底）
    """
    print('刷新龙虎榜...')
    eastmoney_count = _refresh_eastmoney_lhb(date_str)
    if eastmoney_count:
        print(f'龙虎榜 eastmoney 写入 {eastmoney_count} 条')

    westock_count = _refresh_westock_lhb(date_str)
    if westock_count:
        print(f'龙虎榜 westock 补写 {westock_count} 条')

    con = sqlite3.connect(LHB_DB)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM lhb_data WHERE trade_date=?', (date_str,))
    count = cur.fetchone()[0]
    con.close()
    print(f'龙虎榜合计 {count} 条')
    return count


def _refresh_eastmoney_lhb(date_str: str) -> int:
    rows = fetch_lhb(date_str)
    if not rows:
        return 0
    con = sqlite3.connect(LHB_DB)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS lhb_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT,
            trade_date TEXT,
            close_price REAL,
            change_rate REAL,
            net_amt REAL,
            buy_amt REAL,
            sell_amt REAL,
            deal_amt REAL,
            accum_amt REAL,
            turnover_rate REAL,
            free_mcap REAL,
            explain TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(code, trade_date)
        )
    ''')
    inserted = 0
    for r in rows:
        try:
            cur.execute('''
                INSERT OR REPLACE INTO lhb_data
                (code, name, trade_date, close_price, change_rate, net_amt,
                 buy_amt, sell_amt, deal_amt, accum_amt, turnover_rate, free_mcap, explain, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                r['code'], r['name'], r['trade_date'], r['close_price'], r['change_rate'],
                r['net_amt'], r['buy_amt'], r['sell_amt'], r['deal_amt'], r['accum_amt'],
                r['turnover_rate'], r['free_mcap'], r['explain'], r['fetched_at']
            ))
            inserted += 1
        except Exception:
            pass
    con.commit()
    con.close()
    return inserted


def _refresh_westock_lhb(date_str: str, batch_size: int = 10) -> int:
    try:
        client = _westock_client()
    except Exception as e:
        print(f'  westock data_client 加载失败: {e}')
        return 0

    con = sqlite3.connect(MARKET_DB)
    cur = con.cursor()
    cur.execute('SELECT code FROM stocks WHERE code NOT LIKE "688%" AND code NOT LIKE "787%" ORDER BY code LIMIT 50')
    rows = cur.fetchall()
    con.close()
    codes = [_market_prefix(r[0]) for r in rows if r and r[0]]
    if not codes:
        return 0

    con = sqlite3.connect(LHB_DB)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS lhb_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT,
            trade_date TEXT,
            close_price REAL,
            change_rate REAL,
            net_amt REAL,
            buy_amt REAL,
            sell_amt REAL,
            deal_amt REAL,
            accum_amt REAL,
            turnover_rate REAL,
            free_mcap REAL,
            explain TEXT,
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(code, trade_date)
        )
    ''')
    inserted = 0
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        for code in batch:
            r = client.westock_lhb(code, date=date_str)
            if not r.get('success') or not isinstance(r.get('parsed'), list):
                continue
            for row in r['parsed']:
                name = row.get('Name', '') or row.get('name', '')
                try:
                    cur.execute('''
                        INSERT OR REPLACE INTO lhb_data
                        (code, name, trade_date, close_price, change_rate, net_amt,
                         buy_amt, sell_amt, deal_amt, accum_amt, turnover_rate, free_mcap, explain, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        code, name, date_str,
                        float(row.get('ClosePrice', 0) or 0),
                        float(row.get('ChangeRate', 0) or 0),
                        float(row.get('NetAmt', 0) or 0),
                        float(row.get('BuyAmt', 0) or 0),
                        float(row.get('SellAmt', 0) or 0),
                        float(row.get('DealAmt', 0) or 0),
                        float(row.get('AccumAmt', 0) or 0),
                        float(row.get('TurnoverRate', 0) or 0),
                        float(row.get('FreeMarketCap', 0) or 0),
                        row.get('Explain', '') or '',
                        datetime.now().isoformat(),
                    ))
                    inserted += 1
                except Exception:
                    pass
        con.commit()
    con.close()
    return inserted


# ======================== 热门概念 ========================

def _run_westock_batch(mode: str, date_str: str, batch_size: int = 10) -> bool:
    if not os.path.isfile(WESTOCK_BATCH):
        print('  westock_batch.py 不存在')
        return False
    cmd = [sys.executable, WESTOCK_BATCH, '--mode', mode, '--date', date_str, '--batch-size', str(batch_size)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        print(p.stdout.strip())
        if p.stderr.strip():
            print('  [stderr]', p.stderr.strip()[:300])
        return p.returncode == 0
    except Exception as e:
        print(f'  westock_batch 执行失败: {e}')
        return False


def refresh_board_concept():
    """刷新热门概念"""
    print('刷新热门概念...')
    ok = _run_westock_batch('board_concept', datetime.now().strftime('%Y-%m-%d'), batch_size=10)
    if not ok:
        print('  热门概念刷新失败')
        return 0

    con = sqlite3.connect(WESTOCK_DB)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*), MAX(date) FROM board_cache')
    cnt, latest = cur.fetchone()
    con.close()
    print(f'  board_cache 当前 {cnt} 条，最新 {latest}')
    return cnt or 0


# ======================== main ========================

def main():
    date_str = None
    if len(sys.argv) >= 3 and sys.argv[1] == '--date':
        date_str = sys.argv[2]
    latest_date = get_latest_klines_date()
    target_date = date_str or latest_date
    print(f'目标日期: {target_date}')

    # ── 上游就绪检查：klines 是否已更新到最近交易日 ──
    # 防止 daily 跑在 market-cache 之前，导致用旧 K 线算当天信号（信号日期错配）
    try:
        from pipeline_status import get_latest_status
        mc = get_latest_status('stock-market-cache-refresh')
        if mc and mc.get('status') == 'ok' and mc.get('data_date'):
            if mc['data_date'] > (latest_date or ''):
                print(f"  [PIPELINE] ⚠️ market-cache 数据日期 {mc['data_date']} 超前于 klines 最新 {latest_date}，信号可能滞后")
    except Exception as e:
        print(f'  [PIPELINE] 上游检查失败: {e}')

    errors = []
    try:
        refresh_indicators(target_date)
    except Exception as e:
        errors.append(f'indicators: {e}')
    try:
        refresh_northbound()
    except Exception as e:
        errors.append(f'northbound: {e}')
    try:
        refresh_main_fund_flow(target_date)
    except Exception as e:
        errors.append(f'main_fund: {e}')
    try:
        refresh_lhb(target_date)
    except Exception as e:
        errors.append(f'lhb: {e}')
    try:
        refresh_board_concept()
    except Exception as e:
        errors.append(f'board_concept: {e}')
    try:
        # 股东/筹码/两融三维采集（westock → holder_change/chip_data/margin_data）
        # 复用 fetch_holdings_westock.py，不带参数时读 Bitable 真实持仓
        import subprocess as _sp
        _fh = os.path.join(os.path.dirname(__file__), 'fetch_holdings_westock.py')
        _r = _sp.run(['python3', _fh], capture_output=True, text=True, timeout=600)
        # 成功标志：输出含「写入完成」
        if '写入完成' in _r.stdout:
            print('股东/筹码/两融采集完成')
        else:
            raise RuntimeError(_r.stdout[-300:] + _r.stderr[-200:])
    except Exception as e:
        errors.append(f'holdings_3d: {e}')

    # 记录管道状态
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from pipeline_status import record_status
        status = 'error' if errors else 'ok'
        msg = '; '.join(errors) if errors else '全部完成'
        record_status('daily-data-refresh', status, target_date, message=msg)
    except Exception as e:
        print(f'pipeline_status 记录失败: {e}')

    if errors:
        print(f'完成（有错误）: {"; ".join(errors)}')
    else:
        print('done')


if __name__ == '__main__':
    main()
