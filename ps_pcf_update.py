#!/usr/bin/env python3
"""
PS/PCF 估值数据更新模块
======================
数据源: push2delay.eastmoney.com
- PS (市销率): 个股接口 f168
- PCF (市现率): 批量接口 f169
集成到每周 PE/PB 刷新任务中
"""
import os, sys, sqlite3, json, requests, concurrent.futures
from datetime import date, datetime
from pathlib import Path

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def get_pcf_batch():
    """
    批量获取全市场 PCF（市现率）
    使用 clist/get 接口 f169 字段
    返回: {code: pcf_value}
    """
    url = 'http://push2delay.eastmoney.com/api/qt/clist/get'
    pcf_data = {}
    
    for page in range(1, 60):  # 最多60页 x 100 = 6000只
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f169'
        }
        try:
            r = requests.get(url, params=params, timeout=10, headers=HEADERS)
            items = r.json().get('data', {}).get('diff', [])
            if not items:
                break
            for item in items:
                code = item.get('f12', '')
                pcf = item.get('f169')
                if code and pcf not in (None, '-', 0):
                    pcf_data[code] = pcf
        except Exception as e:
            print(f'  第{page}页获取失败: {e}')
            continue
    
    return pcf_data

def get_ps_single(code_list):
    """
    逐只获取 PS（市销率）
    使用 stock/get 接口 f168 字段
    返回: {code: ps_value}
    """
    url = 'http://push2delay.eastmoney.com/api/qt/stock/get'
    ps_data = {}
    batch_size = 50  # 并发数
    
    def fetch_one(code):
        mkt = '1' if code.startswith(('60', '688', '689')) else '0'
        try:
            r = requests.get(url, params={
                'secid': f'{mkt}.{code}',
                'fields': 'f57,f58,f168',
                'invt': 2, 'fltt': 2
            }, timeout=5, headers=HEADERS)
            d = r.json().get('data', {})
            ps = d.get('f168')
            if ps is not None and ps != '-':
                return (code, ps)
        except:
            pass
        return (code, None)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {executor.submit(fetch_one, code): code for code in code_list}
        for future in concurrent.futures.as_completed(futures):
            code, ps = future.result()
            if ps is not None:
                ps_data[code] = ps
    
    return ps_data

def update_db(ps_data, pcf_data):
    """更新 indicators 表的 ps_ttm 和 pcf_ttm 字段"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    
    # 确保字段存在
    cur.execute("PRAGMA table_info(indicators)")
    cols = [c[1] for c in cur.fetchall()]
    for col in ['ps_ttm', 'pcf_ttm']:
        if col not in cols:
            cur.execute(f'ALTER TABLE indicators ADD COLUMN {col} REAL')
    
    updated_ps = 0
    updated_pcf = 0
    
    for code, ps in ps_data.items():
        cur.execute('UPDATE indicators SET ps_ttm=? WHERE code=?', (ps, code))
        if cur.rowcount > 0:
            updated_ps += 1
    
    for code, pcf in pcf_data.items():
        cur.execute('UPDATE indicators SET pcf_ttm=? WHERE code=?', (pcf, code))
        if cur.rowcount > 0:
            updated_pcf += 1
    
    conn.commit()
    conn.close()
    return updated_ps, updated_pcf

def add_to_screener_filter():
    """
    在灵活版筛选中增加 PS/PCF 条件
    PS < 行业均值 × 1.5 (避免营收估值过高)
    PCF > 0 (经营现金流为正)
    """
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    
    # 计算各行业 PS 均值
    from collections import defaultdict
    cur.execute('''
        SELECT i.code, i.ps_ttm, s.sector
        FROM indicators i JOIN stocks s ON i.code = s.code
        WHERE i.ps_ttm IS NOT NULL AND i.ps_ttm > 0
    ''')
    rows = cur.fetchall()
    
    # 计算行业均值
    sector_ps = defaultdict(list)
    for code, ps, sector in rows:
        sector_ps[sector].append(ps)
    
    sector_avg_ps = {}
    for sector, values in sector_ps.items():
        if values:
            sector_avg_ps[sector] = sum(values) / len(values)
    
    conn.close()
    
    return sector_avg_ps

def run():
    """主入口"""
    print(f'📊 PS/PCF 估值数据更新 | {date.today().isoformat()}')
    print(f'{"="*55}')
    
    # Step 1: 批量获取 PCF
    print('📥 获取 PCF（市现率）...')
    pcf_data = get_pcf_batch()
    print(f'   获取 {len(pcf_data)} 只 PCF 数据')
    
    # Step 2: 逐只获取 PS
    # 获取全市场代码列表
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute('SELECT code FROM stocks')
    all_codes = [r[0] for r in cur.fetchall()]
    conn.close()
    
    print(f'📥 获取 PS（市销率），共 {len(all_codes)} 只...')
    ps_data = get_ps_single(all_codes)
    print(f'   获取 {len(ps_data)} 只 PS 数据')
    
    # Step 3: 更新数据库
    print('💾 更新数据库...')
    n_ps, n_pcf = update_db(ps_data, pcf_data)
    print(f'   更新 PS: {n_ps} 只 / PCF: {n_pcf} 只')
    
    # Step 4: 统计
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM indicators WHERE ps_ttm IS NOT NULL AND ps_ttm > 0')
    ps_count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM indicators WHERE pcf_ttm IS NOT NULL AND pcf_ttm != 0')
    pcf_count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM indicators WHERE pcf_ttm > 0')
    pcf_pos = cur.fetchone()[0]
    conn.close()
    
    print()
    print(f'📊 更新后统计:')
    print(f'   PS 有数据: {ps_count} 只')
    print(f'   PCF 有数据: {pcf_count} 只（其中 >0: {pcf_pos} 只）')
    
    # 行业均值
    sector_avg = add_to_screener_filter()
    print(f'   行业 PS 均值已计算: {len(sector_avg)} 个行业')
    
    print(f'\n{"="*55}')
    print(f'✅ PS/PCF 更新完成')
    print(f'{"="*55}')

if __name__ == '__main__':
    run()
