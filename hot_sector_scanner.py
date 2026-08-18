#!/usr/bin/env python3
"""
热点板块追踪扫描器
==================
开盘后捕捉当日热点板块及强势个股。

流程：
1. 用 akshare 获取今日涨停股票列表
2. 提取涨停股的行业分布，锁定主线板块（涨停数 ≥ 3 只）
3. 对主线板块内所有成分股，从 akshare 获取，按成交额排序取前 20
4. 计算每只股票的 A/B/C/D 信号（站上20日均线/倍量启动/MACD金叉/RSI<30超卖）
5. 输出为独立观察池，标记为【🔥 热点追踪】

用法：
  python3 hot_sector_scanner.py
  python3 hot_sector_scanner.py --date 2026-08-05
"""

import sys, argparse
from datetime import datetime, date
import sqlite3
from pathlib import Path

import akshare as ak
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')
from stock_db_paths import get_db_path

# ── 路径 ──
MKT_DB = str(get_db_path('market_cache'))
OUTPUT_DIR = Path('/home/caojy/.hermes/scripts/cron')


def fetch_limit_up_stocks(trade_date: str) -> list[dict]:
    """用 akshare 获取涨停板列表"""
    # akshare 需要 YYYYMMDD 格式
    trade_date_num = trade_date.replace('-', '')
    try:
        df = ak.stock_zt_pool_em(date=trade_date_num)
    except Exception as e:
        print(f"  akshare 涨停板获取失败: {e}", file=sys.stderr)
        return []

    if df is None or df.empty:
        return []

    stocks = []
    for _, row in df.iterrows():
        stocks.append({
            'code': str(row.get('代码', '')).strip(),
            'name': str(row.get('名称', '')).strip(),
            'change_pct': float(row.get('涨跌幅', 0)),
            'price': float(row.get('最新价', 0)),
            'turnover': float(row.get('成交额', 0) or 0),
            'total_mcap': float(row.get('总市值', 0) or 0) / 1e8,
            'industry': str(row.get('所属行业', '')).strip(),
            'limit_days': int(row.get('连板数', 0)),
        })

    return stocks


def fetch_industry_stocks(industry_name: str) -> list[dict]:
    """从本地 stocks 表获取指定行业的全部成分股"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute("SELECT code, name FROM stocks WHERE sector = ?", (industry_name,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    # 从 klines 获取最新数据作为行情快照
    stocks = []
    for code, name in rows:
        cur2 = sqlite3.connect(MKT_DB)
        cur2.row_factory = sqlite3.Row
        c2 = cur2.cursor()
        c2.execute("SELECT date, close, volume, turnover FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        kl = c2.fetchone()
        cur2.close()
        if kl:
            stocks.append({
                'code': code,
                'name': name,
                'price': float(kl['close'] or 0),
                'turnover': float(kl['turnover'] or 0),
                'industry': industry_name,
                'change_pct': 0,  # 本地库无法获取今日涨跌幅
            })
    return stocks


def fetch_klines(code: str, limit: int = 60) -> list[dict]:
    """从 market_cache.db 获取本地K线"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT date, close, volume, turnover, high, low FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return [{'date': r[0], 'close': r[1], 'volume': r[2], 'turnover': r[3], 'high': r[4], 'low': r[5]} for r in rows]


def calc_signals(code: str) -> dict:
    """计算 A/B/C/D 信号"""
    klines = fetch_klines(code, 60)
    if len(klines) < 25:
        return {'A': False, 'B': False, 'C': False, 'D': False, 'count': 0, 'rsi': None}

    klines.reverse()
    closes = [k['close'] for k in klines if k['close']]
    volumes = [k['volume'] for k in klines if k['volume']]
    if not closes or not volumes:
        return {'A': False, 'B': False, 'C': False, 'D': False, 'count': 0, 'rsi': None}

    signals = {'A': False, 'B': False, 'C': False, 'D': False, 'count': 0, 'rsi': None}
    close = closes[-1]

    # A: 站上20日均线 + 均线拐头
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        ma20_prev = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else ma20
        signals['A'] = close > ma20 and ma20 > ma20_prev

    # B: 倍量启动
    if len(volumes) >= 25:
        vol_5 = sum(volumes[-5:]) / 5
        vol_20 = sum(volumes[-25:-5]) / 20
        signals['B'] = (vol_5 / vol_20) >= 1.8 if vol_20 > 0 else False

    # C: MACD 金叉
    if len(closes) >= 26:
        ema12 = sum(closes[-12:]) / 12
        ema26 = sum(closes[-26:]) / 26
        dif = ema12 - ema26
        dea = sum(closes[-9:]) / 9
        macd = 2 * (dif - dea)

        ema12_p = sum(closes[-13:-1]) / 12
        ema26_p = sum(closes[-27:-1]) / 26
        dif_p = ema12_p - ema26_p
        dea_p = sum(closes[-10:-1]) / 9
        macd_p = 2 * (dif_p - dea_p)

        signals['C'] = macd > 0 and macd_p <= 0

    # D: RSI < 30（超卖）
    if len(closes) >= 14:
        gains = [max(closes[i] - closes[i-1], 0) for i in range(-13, 0)]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(-13, 0)]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        signals['D'] = rsi < 30
        signals['rsi'] = round(rsi, 1)

    signals['count'] = sum([signals[k] for k in ['A', 'B', 'C', 'D']])
    return signals


def format_signal_str(signals: dict) -> str:
    parts = []
    for k in ['A', 'B', 'C', 'D']:
        if signals[k]:
            parts.append(k)
    return '+'.join(parts) if parts else '—'


def main():
    parser = argparse.ArgumentParser(description='热点板块追踪扫描')
    parser.add_argument('--date', type=str, default=date.today().isoformat(),
                       help='扫描日期 (YYYY-MM-DD)')
    args = parser.parse_args()
    scan_date = args.date

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  🔥 热点板块追踪扫描", file=sys.stderr)
    print(f"  {scan_date}", file=sys.stderr)
    print(f"{'='*55}", file=sys.stderr)

    # Step 1: 获取涨停板
    print("\n  步骤1: 获取涨停板列表...", file=sys.stderr)
    limit_stocks = fetch_limit_up_stocks(scan_date)
    if not limit_stocks:
        print("\n  【🔥 热点追踪】今日无涨停板数据", file=sys.stderr)
        return

    print(f"  涨停板: {len(limit_stocks)} 只", file=sys.stderr)

    # Step 2: 行业分布分析
    print("\n  步骤2: 行业分布分析...", file=sys.stderr)
    industry_count = {}
    for s in limit_stocks:
        ind = s.get('industry', '')
        if ind:
            industry_count[ind] = industry_count.get(ind, 0) + 1

    sorted_industries = sorted(industry_count.items(), key=lambda x: -x[1])
    hot_industries = [(ind, cnt) for ind, cnt in sorted_industries if cnt >= 3]

    print(f"  覆盖行业: {len(industry_count)} 个", file=sys.stderr)
    print(f"  主线板块(涨停≥3): {len(hot_industries)} 个", file=sys.stderr)
    for ind, cnt in hot_industries:
        print(f"    {ind}: {cnt} 只涨停", file=sys.stderr)

    if not hot_industries and sorted_industries:
        ind, cnt = sorted_industries[0]
        hot_industries = [(ind, cnt)]
        print(f"  取涨停数最多的: {ind}({cnt})", file=sys.stderr)

    # Step 3: 从涨停板中筛选主线板块Top 20
    # 涨停板本身已包含行业和成交额，直接从涨停板内取主线板块的Top 20
    print("\n  步骤3: 从涨停板中筛选主线板块Top 20...", file=sys.stderr)
    hot_codes = set()
    for s in limit_stocks:
        for ind, cnt in hot_industries:
            if s.get('industry', '') == ind:
                hot_codes.add(s['code'])
                break

    # 从涨停板中取主线板块的股票（含行业信息，按成交额排序）
    hot_from_limit = [s for s in limit_stocks if s['code'] in hot_codes]
    hot_from_limit.sort(key=lambda x: -(x.get('turnover', 0) or 0))
    top20 = hot_from_limit[:20]
    print(f"  主线板块涨停股: {len(hot_from_limit)} 只, Top20 已选出", file=sys.stderr)

    # Step 4: 计算信号
    print("\n  步骤4: 计算 A/B/C/D 信号...", file=sys.stderr)
    results = []
    for s in top20:
        signals = calc_signals(s['code'])
        s['signals'] = signals
        results.append(s)
        turnover_yi = (s.get('turnover', 0) or 0) / 1e8
        signal_str = format_signal_str(signals)
        print(f"    {s['code']} {s['name']:<8} 成交额{turnover_yi:.1f}亿 信号[{signal_str}] RSI={signals['rsi']}", file=sys.stderr)

    # Step 5: 生成报告
    print("\n  步骤5: 生成报告...", file=sys.stderr)
    results.sort(key=lambda x: (-x['signals']['count'], -(x.get('turnover', 0) or 0)))

    lines = []
    lines.append(f"【🔥 热点追踪】{scan_date}")
    lines.append("")
    lines.append(f"涨停板共 **{len(limit_stocks)}** 只 | 覆盖 **{len(industry_count)}** 个行业")
    lines.append("")
    lines.append("**主线板块（涨停≥3只）：**")
    for ind, cnt in hot_industries:
        lines.append(f"- {ind}：涨停 {cnt} 只")
    lines.append("")

    lines.append("**Top 10 观察标的（按信号强度+成交额）：**")
    lines.append("")
    lines.append("| 序号 | 代码 | 名称 | 成交额 | 涨幅 | 信号 | 行业 |")
    lines.append("|:---:|:---:|:---:|:----:|:---:|:---:|:----:|")

    for i, s in enumerate(results[:10], 1):
        code = s['code']
        name = s['name']
        turnover_yi = (s.get('turnover', 0) or 0) / 1e8
        change = s.get('change_pct', 0)
        signal_str = format_signal_str(s['signals'])
        industry = s.get('industry', '')
        lines.append(f"| {i} | {code} | {name} | {turnover_yi:.1f}亿 | {change:+.1f}% | {signal_str} | {industry} |")

    lines.append("")
    lines.append("**信号说明：** A=站上20日均线 B=倍量启动 C=MACD金叉 D=RSI<30超卖")
    lines.append("")

    report = '\n'.join(lines)

    output_path = OUTPUT_DIR / f'hot_sector_{scan_date}.md'
    with open(output_path, 'w') as f:
        f.write(report)
    print(f"\n  报告已保存: {output_path}", file=sys.stderr)
    print(report)

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  ✅ 热点追踪扫描完成", file=sys.stderr)
    print(f"{'='*55}", file=sys.stderr)


if __name__ == '__main__':
    main()
