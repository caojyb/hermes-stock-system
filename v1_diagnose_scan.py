#!/usr/bin/env python3
"""翻倍策略 V1 诊断扫描：先拆解 Step1 子条件，再执行用户指定 4 步。"""
import sqlite3, random
from datetime import datetime, timedelta

MARKET_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SCAN_DATE = '2026-07-29'
MCAP_LOW = 5e8
MCAP_HIGH = 5e10


def get_db():
    return sqlite3.connect(MARKET_DB)


def load_klines(con, code, limit=1200):
    cur = con.cursor()
    cur.execute('''
        SELECT date, close, volume, turnover, high, low
        FROM klines
        WHERE code=?
        ORDER BY date DESC
        LIMIT ?
    ''', (code, limit))
    rows = cur.fetchall()
    if not rows:
        return []
    rows = [r for r in rows if r[1] is not None and r[2] is not None and 0.5 <= r[1] <= 5000]
    if not rows:
        return []
    rows.reverse()
    return rows


def calc_price_position_2y(klines):
    if not klines:
        return None
    closes = [r[1] for r in klines if r[1] is not None]
    if len(closes) < 60:
        return None
    current = closes[-1]
    lowest = min(closes)
    highest = max(closes)
    if highest == lowest:
        return None
    return (current - lowest) / (highest - lowest) * 100


def calc_volume_ratio(klines):
    if not klines or len(klines) < 21:
        return None
    today = klines[-1]
    prev = klines[-21:-1]
    if not prev:
        return None
    vol_today = today[2] or 0
    vol_avg = sum(r[2] or 0 for r in prev) / len(prev)
    if vol_avg <= 0:
        return None
    return vol_today / vol_avg


def calc_amount_today(klines):
    if not klines:
        return None
    close = klines[-1][1]
    volume = klines[-1][2] or 0
    turnover = klines[-1][3]
    if turnover is not None:
        return turnover / 10000.0
    if not close or not volume:
        return None
    return close * volume / 100.0 / 10000.0


def calc_atr_pct(klines, period=14):
    if not klines or len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = klines[i][4] or 0
        low = klines[i][5] or 0
        prev_close = klines[i-1][1] or 0
        if not high or not low or not prev_close:
            continue
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    close = klines[-1][1] or 0
    if not close:
        return None
    return atr / close * 100


def recent_5d_return(con, code):
    cur = con.cursor()
    cur.execute('''
        SELECT date, close FROM klines
        WHERE code=? AND date <= ?
        ORDER BY date DESC
        LIMIT 6
    ''', (code, SCAN_DATE))
    rows = cur.fetchall()
    if len(rows) < 6:
        return None
    rows.reverse()
    c0 = rows[0][1]
    c5 = rows[5][1]
    if not c0 or not c5:
        return None
    return (c0 - c5) / c5 * 100


def is_excluded_name(name: str) -> bool:
    if not name:
        return False
    n = name.upper()
    for kw in ['PT', '退市', 'ST', '*ST', 'S*']:
        if kw in n:
            return True
    return False


def diagnostics():
    con = get_db()
    scan_dt = datetime.strptime(SCAN_DATE, '%Y-%m-%d').date()
    min_date = (scan_dt - timedelta(days=5)).strftime('%Y-%m-%d')

    cur = con.cursor()
    cur.execute('''
        SELECT code, name, total_mcap
        FROM stocks
        WHERE code NOT LIKE '688%' AND code NOT LIKE '787%'
          AND (is_st IS NULL OR is_st = 0)
    ''')
    stocks = cur.fetchall()
    print(f'Step0 基础池（排除ST/退市/688/787）: {len(stocks)} 只')

    # Decompose Step1 filters independently on Step0
    cnt_name = 0
    cnt_mcap = 0
    cnt_kline = 0
    cnt_future = 0
    cnt_expired = 0
    cnt_price = 0
    cnt_amount = 0
    step1 = []
    for code, name, total_mcap in stocks:
        if is_excluded_name(name):
            cnt_name += 1
            continue
        if total_mcap is None or not (MCAP_LOW <= total_mcap <= MCAP_HIGH):
            cnt_mcap += 1
            continue
        klines = load_klines(con, code)
        if not klines or len(klines) < 60:
            cnt_kline += 1
            continue
        latest_date = klines[-1][0]
        if latest_date and latest_date > SCAN_DATE:
            cnt_future += 1
            continue
        if not latest_date or latest_date < min_date:
            cnt_expired += 1
            continue
        latest_close = klines[-1][1]
        if latest_close < 2:
            cnt_price += 1
            continue
        amount_wan = calc_amount_today(klines)
        if amount_wan is None or amount_wan < 3000:
            cnt_amount += 1
            continue
        step1.append((code, name, total_mcap, klines, amount_wan))
    print('\nStep1 子条件拒绝计数:')
    print(f'  名称排除: {cnt_name}')
    print(f'  市值不在5-50亿: {cnt_mcap}')
    print(f'  K线不足: {cnt_kline}')
    print(f'  未来日期: {cnt_future}')
    print(f'  数据过期: {cnt_expired}')
    print(f'  极端低价<2元: {cnt_price}')
    print(f'  成交额<3000万: {cnt_amount}')
    print(f'Step1 基础条件通过: {len(step1)} 只')

    step2 = []
    for code, name, total_mcap, klines, amount_wan in step1:
        pp = calc_price_position_2y(klines)
        if pp is None or pp > 40:
            continue
        step2.append((code, name, total_mcap, klines, amount_wan, pp))
    print(f'Step2 +price_position_2y<=40%: {len(step2)} 只')

    step3 = []
    for code, name, total_mcap, klines, amount_wan, pp in step2:
        vr = calc_volume_ratio(klines)
        if vr is None or vr < 1.8:
            continue
        step3.append((code, name, total_mcap, klines, amount_wan, pp, vr))
    print(f'Step3 +volume_ratio>=1.8: {len(step3)} 只')

    step4 = []
    for code, name, total_mcap, klines, amount_wan, pp, vr in step3:
        atr = calc_atr_pct(klines)
        if atr is None or atr < 3:
            continue
        step4.append((code, name, total_mcap, klines, amount_wan, pp, vr, atr))
    print(f'Step4 +ATR>=3%: {len(step4)} 只')

    thresholds = [50, 60, 70]
    thresh_counts = {}
    for th in thresholds:
        cnt = 0
        for code, name, total_mcap, klines, amount_wan in step1:
            pp = calc_price_position_2y(klines)
            if pp is not None and pp <= th:
                cnt += 1
        thresh_counts[th] = cnt
    for th, cnt in thresh_counts.items():
        print(f'Step5 price_position_2y<={th}%: {cnt} 只')

    rejected_pct = []
    rejected_vol = []
    for code, name, total_mcap, klines, amount_wan in step1:
        pp = calc_price_position_2y(klines)
        vr = calc_volume_ratio(klines)
        ret5 = recent_5d_return(con, code)
        if pp is None or pp > 40:
            rejected_pct.append((code, name, total_mcap/1e8, pp, vr, ret5))
        elif vr is None or vr < 1.8:
            rejected_vol.append((code, name, total_mcap/1e8, pp, vr, ret5))
        if len(rejected_pct) >= 5 and len(rejected_vol) >= 5:
            break

    print('\n典型被拒样本（分位>40%）:')
    for code, name, mcap, pp, vr, ret5 in rejected_pct[:5]:
        print(f'  {code} {name} 市值={mcap:.1f}亿 price_position={pp:.1f}% volume_ratio={vr} 5日涨跌={ret5}')
    print('\n典型被拒样本（量比<1.8）:')
    for code, name, mcap, pp, vr, ret5 in rejected_vol[:5]:
        print(f'  {code} {name} 市值={mcap:.1f}亿 price_position={pp:.1f}% volume_ratio={vr} 5日涨跌={ret5}')

    con.close()


if __name__ == '__main__':
    diagnostics()
