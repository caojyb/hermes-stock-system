#!/usr/bin/env python3
"""持仓三维(股东/筹码/两融)采集 —— westock → market_cache.db
解决 deep-position-review 的"股东/筹码/两融本地库为空"。
用法: python3 fetch_holdings_westock.py [code1 code2 ...]
不带参数则读 Bitable 全部持仓; 也可传 6 位代码。
"""
import subprocess, re, sys, json, sqlite3, os
from datetime import datetime

DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
WESTOCK = "npx -y westock-data-skillhub@1.0.3"
import decision._local_constants as _local_constants
BT_APP = _local_constants.BITABLE_BASE_TOKEN
BT_TABLE = _local_constants.BITABLE_TABLE_ID

def to_westock(code):
    code = str(code).zfill(6)
    if code.startswith('6'): return 'sh' + code
    return 'sz' + code

def read_holdings_codes():
    out = subprocess.run(['lark-cli','base','+record-list','--base-token',BT_APP,
                          '--table-id',BT_TABLE], capture_output=True, text=True, timeout=60).stdout
    return re.findall(r'\|\s*(\d{6})\s*\|', out)

def run_westock(cmd, code):
    import time as _t
    for attempt in range(4):
        try:
            r = subprocess.run(f"{WESTOCK} {cmd} {code} 2>/dev/null".split(),
                               capture_output=True, text=True, timeout=30)
            if r.stdout.strip() and len(r.stdout.strip()) > 30:
                return r.stdout
        except Exception:
            pass
        _t.sleep(2)  # 冷启动/限流重试
    return ""

def parse_pipe(text):
    """westock pipe-delimited → list[dict]"""
    lines = [l for l in text.strip().split('\n') if l.strip() and '---' not in l and 'npm notice' not in l and not l.startswith('####')]
    if not lines: return []
    header = [h.strip() for h in lines[0].split('|') if h.strip()]
    rows = []
    for line in lines[1:]:
        if '|' not in line: continue
        # 保留空字段（split 后首尾是空串），按 header 索引对齐；末尾缺列允许
        cells = [p.strip() for p in line.split('|')]
        # 去掉首尾因管道符产生的空元素
        if cells and cells[0] == '': cells = cells[1:]
        if cells and cells[-1] == '': cells = cells[:-1]
        row = {}
        for i, h in enumerate(header):
            if i < len(cells):
                row[h] = cells[i]
        if row:
            rows.append(row)
    return rows

def get_market_db():
    conn = sqlite3.connect(DB, timeout=30)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS chip_data(
        code TEXT, name TEXT, trade_date TEXT, chip_profit_rate REAL,
        chip_avg_cost REAL, chip_conc90 REAL, chip_conc70 REAL, created_at TEXT,
        PRIMARY KEY(code, trade_date))""")
    c.execute("""CREATE TABLE IF NOT EXISTS margin_data(
        code TEXT, name TEXT, trade_date TEXT, finance_value REAL,
        security_value REAL, finance_buy REAL, finance_refund REAL,
        trading_value REAL, trading_value_dif REAL, created_at TEXT,
        PRIMARY KEY(code, trade_date))""")
    conn.commit()
    return conn, c

def parse_shareholder(text):
    """专用解析: 只取第一张「十大股东」表 (shareholder 输出含 十大股东+十大流通股东 两张表)"""
    lines = text.split('\n')
    # 找到表头行
    hdr_idx = None
    for i, l in enumerate(lines):
        if 'holdChange' in l and '|' in l:
            hdr_idx = i; break
    if hdr_idx is None: return []
    header = [h.strip() for h in lines[hdr_idx].split('|') if h.strip()]
    rows = []
    for l in lines[hdr_idx+1:]:
        if '|' not in l: break          # 遇到非表格行(空/**)即结束, 避免读第二张表
        if '---' in l: continue
        parts = [p.strip() for p in l.split('|') if p.strip()]
        if len(parts) >= len(header):
            rows.append(dict(zip(header, parts)))
        elif len(parts) >= 3:
            rows.append(dict(zip(header, parts)))
    return rows

def main():
    codes = sys.argv[1:] or read_holdings_codes()
    conn, c = get_market_db()
    now = datetime.now().isoformat()
    summary = []
    for raw in codes:
        wc = to_westock(raw)
        name = ""
        # 股东 → holder_change (专用解析)
        sh = parse_shareholder(run_westock('shareholder', wc))
        if sh and all(k in sh[0] for k in ('name','holdChange')):
            try:
                name = sh[0].get('name','')
                def _ch(v):
                    try: return float(str(v).replace(',',''))
                    except: return 0
                changed = [r for r in sh if abs(_ch(r.get('holdChange',0)))>0]
                c.execute("DELETE FROM holder_change WHERE code=? AND change_date=?",
                          (raw, datetime.now().strftime('%Y-%m-%d')))
                for r in (changed or sh[:3]):
                    ch = _ch(r.get('holdChange',0))
                    c.execute("INSERT OR REPLACE INTO holder_change(code,change_date,change_shares,change_type,change_ratio,created_at) VALUES(?,?,?,?,?,?)",
                              (raw, datetime.now().strftime('%Y-%m-%d'), ch,
                               '增持' if ch>0 else ('减持' if ch<0 else '无变化'),
                               _ch(r.get('holdPct',0)), now))
            except Exception as e:
                print(f"  [warn] {raw} 股东写入失败: {e}")
        # 筹码
        chip = parse_pipe(run_westock('chip', wc))
        if chip and 'chipProfitRate' in chip[0]:
            r = chip[0]
            # 优先用 chip 自身返回的股票名（name 可能已被 shareholder 股东名污染）
            chip_name = r.get('name','') or name
            c.execute("""INSERT OR REPLACE INTO chip_data(code,name,trade_date,chip_profit_rate,chip_avg_cost,chip_conc90,chip_conc70,created_at)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (raw, chip_name, r.get('date'), _f(r.get('chipProfitRate')), _f(r.get('chipAvgCost')),
                       _f(r.get('chipConcentration90')), _f(r.get('chipConcentration70')), now))
        # 两融
        mg = parse_pipe(run_westock('margintrade', wc))
        if mg and 'FinanceValue' in mg[0]:
            r = mg[0]
            # 优先用 margintrade 自身返回的股票名
            mg_name = r.get('name','') or name
            c.execute("""INSERT OR REPLACE INTO margin_data(code,name,trade_date,finance_value,security_value,finance_buy,finance_refund,trading_value,trading_value_dif,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (raw, mg_name, r.get('date'), _f(r.get('FinanceValue')), _f(r.get('SecurityValue')),
                       _f(r.get('FinanceBuyValue')), _f(r.get('FinanceRefundValue')),
                       _f(r.get('TradingValue')), _f(r.get('TradingValueDif')), now))
        summary.append(f"{raw} {name}: 股东{len(sh)} 筹码{'ok' if chip else '-'} 两融{'ok' if mg else '-'}")
    conn.commit()
    print(f"写入完成 ({len(codes)}只):")
    for s in summary: print("  " + s)

def _f(v):
    try:
        return float(str(v).replace('%','')) if v not in (None,'') else None
    except: return None

if __name__ == '__main__':
    main()
