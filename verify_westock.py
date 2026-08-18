#!/usr/bin/env python3
import sys, time, subprocess
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable')
from market_cache import _download_klines_tencent, _download_klines_westock, _parse_westock_kline

sampling = [
    ('sh600519', 'sh'),
    ('000001', 'sz'),
    ('002857', 'sz'),
]
for code, market in sampling:
    print('===== ', code, ' =====')
    t0 = time.time()
    tx = _download_klines_tencent(code, market, days=30)
    t1 = time.time()
    print('tencent rows', len(tx), 'ms', round((t1-t0)*1000,1))
    if tx:
        print(' first ', tx[0])
        print(' last  ', tx[-1])
        cmd = (
            "npx -y westock-data-skillhub@1.0.3 "
            f"kline {market}{code} --period day --limit 30"
        )
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        ws = _parse_westock_kline(p.stdout)
        print(' westock rows', len(ws))
        if ws:
            print(' first ', ws[0])
            print(' last  ', ws[-1])
            tx_map = {x['date']: x for x in tx}
            ws_map = {x['date']: x for x in ws}
            common = sorted(set(tx_map) & set(ws_map))[-5:]
            print(' common_dates', common)
            for d in common:
                a = tx_map[d]
                b = ws_map[d]
                print(' ', d, 'tx_close', a['close'], 'ws_close', b['close'], 'tx_amount', a.get('turnover'), 'ws_amount', b.get('turnover'))
    print()
