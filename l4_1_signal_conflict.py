#!/usr/bin/env python3
"""
L4-1 信号冲突测试
从 double_up_scores 候选池随机选 5 只，输出五维分析 + 冲突检测
数据源：
- 主升浪评分 / 翻倍基因 / V1 条件 / 基本面：market_cache.db + score_upgrade.py + doubling_gene.py
- 技术指标：本地 K 线计算（通达信 MCP 当前 kline 参数校验问题，改用本地行情计算）
"""
import sqlite3, math, random, subprocess, sys
from datetime import date

DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"

def get_klines(code, limit=120):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT date, close, high, low, volume FROM klines WHERE code=? ORDER BY date DESC LIMIT ?", (code, limit))
    rows = cur.fetchall()
    con.close()
    rows.reverse()
    return rows

def calc_ma(close, n):
    if len(close) < n:
        return None
    return sum(close[-n:]) / n

def ema(vals, n):
    emas = [vals[0]]
    k = 2 / (n + 1)
    for i in range(1, len(vals)):
        emas.append(vals[i] * k + emas[-1] * (1 - k))
    return emas

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(dif))]
    return dif[-1], dea[-1], macd_hist[-1]

def calc_rsi(close, n=14):
    if len(close) < n + 1:
        return None
    deltas = [close[i] - close[i-1] for i in range(1, len(close))]
    gains = [max(d, 0) for d in deltas]
    losses = [-min(d, 0) for d in deltas]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    length = len(close)
    if length < n:
        return None, None, None
    k_vals = [50.0]
    d_vals = [50.0]
    for i in range(n-1, length):
        hh = max(high[i-n+1:i+1])
        ll = min(low[i-n+1:i+1])
        if hh == ll:
            rsv = 50.0
        else:
            rsv = (close[i] - ll) / (hh - ll) * 100
        k = (2/3) * k_vals[-1] + (1/3) * rsv
        d = (2/3) * d_vals[-1] + (1/3) * k
        k_vals.append(k)
        d_vals.append(d)
    j = 3 * k_vals[-1] - 2 * d_vals[-1]
    return k_vals[-1], d_vals[-1], j

def calc_boll(close, n=20, k=2):
    length = len(close)
    if length < n:
        return None, None, None
    window = close[-n:]
    m = sum(window) / n
    variance = sum((x - m) ** 2 for x in window) / n
    std = math.sqrt(variance)
    return m + k * std, m, m - k * std

def run_score_upgrade(code):
    res = subprocess.run(
        [sys.executable, "/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable/score_upgrade.py", "--code", code],
        capture_output=True, text=True
    )
    return res.stdout.strip()

def extract_score_upgrade(text):
    data = {
        'total': None, 'fundamental': None, 'valuation': None,
        'technical': None, 'doubling_gene': None, 'level': None, 'advice': None,
        'risk': []
    }
    if not text:
        return data
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('总分:'):
            try:
                data['total'] = float(s.split(':')[1].split('/')[0].strip())
            except:
                pass
        elif s.startswith('等级:'):
            data['level'] = s.split(':',1)[1].strip()
        elif s.startswith('建议:'):
            data['advice'] = s.split(':',1)[1].strip()
        elif s.startswith('  🧬 翻倍基因'):
            try:
                data['doubling_gene'] = float(s.split(':')[1].split('/')[0].strip())
            except:
                pass
        elif s.startswith('  【基本面'):
            try:
                data['fundamental'] = float(s.split('(')[1].split('/')[0].strip())
            except:
                pass
        elif s.startswith('  估值 ') and '/' in s:
            try:
                data['valuation'] = float(s.split('|')[0].split(' ')[1].split('/')[0].strip())
            except:
                pass
        elif s.startswith('  技术 ') and '/' in s:
            try:
                data['technical'] = float(s.split('|')[0].split(' ')[1].split('/')[0].strip())
            except:
                pass
        elif s.startswith('  🚩 '):
            data['risk'].append(s.split('🚩',1)[1].strip())
    return data

def main():
    random.seed(20260729)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT code, name, sector FROM double_up_scores WHERE scan_date=(SELECT MAX(scan_date) FROM double_up_scores) ORDER BY RANDOM() LIMIT 5")
    candidates = cur.fetchall()
    con.close()

    # preload doubling gene and V1
    from doubling_gene import score_stock, build_doubling_gene_score
    factors = build_doubling_gene_score({})
    pre = {}
    con = sqlite3.connect(DB)
    cur = con.cursor()
    for code, name, sector in candidates:
        dg_score, dg_details = score_stock(code, con, factors)
        cur.execute("""
            SELECT total_score, market_cap, price_position_2y, volume_ratio, atr_pct,
                   revenue, debt_ratio, signal_score, signal_level, passed, amount_wan
            FROM double_up_scores
            WHERE code=? AND scan_date=(SELECT MAX(scan_date) FROM double_up_scores)
        """, (code,))
        v1 = cur.fetchone()
        cur.execute("SELECT roe, profit_growth, revenue_growth, debt_ratio, gross_margin, net_margin FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1", (code,))
        fin = cur.fetchone()
        pre[code] = {'dg_score': dg_score, 'dg_details': dg_details, 'v1': v1, 'fin': fin, 'name': name, 'sector': sector}
    con.close()

    print("=" * 120)
    print("L4-1 信号冲突测试")
    print("=" * 120)
    print(f"候选池：double_up_scores 最新一期")
    print(f"随机抽选：{len(candidates)} 只")
    print(f"技术指标说明：通达信 MCP 的 stock_kline 在本机参数校验异常，改用本地 K 线计算 MA/MACD/RSI/KDJ/BOLL")
    print()

    summary = []
    for code, name, sector in candidates:
        p = pre[code]
        print("=" * 110)
        print(f"【{p['name']}】{code} | {p['sector']}")
        print("=" * 110)

        print("\n[1] 主升浪策略评分（score_upgrade.py）")
        su_text = run_score_upgrade(code)
        print(su_text)
        su = extract_score_upgrade(su_text)

        print("\n[2] 翻倍基因评分（doubling_gene.py 5因子）")
        print(f"  总分: {p['dg_score']}/10")
        for k, v in p['dg_details'].items():
            print(f"    {k}: 值={v['value']}, 得分={v['score']}")

        print("\n[3] 翻倍策略 V1 条件")
        if p['v1']:
            total_score, mcap, pos2y, vol_ratio, atr_pct, rev, debt, sig_score, sig_level, passed, amount = p['v1']
            print(f"  total_score={total_score}, market_cap={mcap}亿, 2y_position={pos2y}%")
            print(f"  volume_ratio={vol_ratio}, atr_pct={atr_pct}%")
            print(f"  revenue={rev}, debt_ratio={debt}%")
            print(f"  signal_score={sig_score}, level={sig_level}, passed={passed}")
            print(f"  amount_wan={amount}")
        else:
            print("  [WARN] 不在 double_up_scores 中")

        print("\n[4] 技术指标（本地 K 线计算）")
        rows = get_klines(code, 120)
        if not rows:
            print("  [WARN] 无 K 线数据")
            tech = {}
        else:
            close = [r[1] for r in rows]
            high = [r[2] for r in rows]
            low = [r[3] for r in rows]
            vol = [r[4] for r in rows]
            latest_date = rows[-1][0]
            latest_close = close[-1]
            ma5 = calc_ma(close, 5)
            ma10 = calc_ma(close, 10)
            ma20 = calc_ma(close, 20)
            ma60 = calc_ma(close, 60)
            dif, dea, macd_val = calc_macd(close)
            rsi_val = calc_rsi(close)
            k, d, j = calc_kdj(high, low, close)
            boll_upper, boll_mid, boll_lower = calc_boll(close)
            tech = {
                'close': latest_close, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
                'dif': dif, 'dea': dea, 'macd': macd_val, 'rsi': rsi_val,
                'k': k, 'd': d, 'j': j, 'boll_upper': boll_upper, 'boll_mid': boll_mid, 'boll_lower': boll_lower
            }
            print(f"  日期={latest_date}, close={latest_close}")
            print(f"  MA: 5={ma5:.2f}, 10={ma10:.2f}, 20={ma20:.2f}, 60={ma60:.2f}")
            print(f"  MACD: DIF={dif:.4f}, DEA={dea:.4f}, MACD={macd_val:.4f}")
            print(f"  RSI14={rsi_val:.2f}")
            print(f"  KDJ: K={k:.2f}, D={d:.2f}, J={j:.2f}")
            print(f"  BOLL: upper={boll_upper:.2f}, mid={boll_mid:.2f}, lower={boll_lower:.2f}")

        print("\n[5] 基本面评级（ROE/毛利率/负债率/利润增速）")
        if p['fin']:
            roe, pg, rg, debt, gm, nm = p['fin']
            print(f"  ROE={roe}%, 利润增速={pg}%, 营收增速={rg}%")
            print(f"  负债率={debt}%, 毛利率={gm}%, 净利率={nm}%")
        else:
            print("  [WARN] 无财务数据")

        # 冲突检测
        steady_score = su['total']
        dg_score = p['dg_score']
        total_score = p['v1'][0] if p['v1'] else None
        passed = p['v1'][9] if p['v1'] else None
        roe, pg, rg, debt, gm, nm = p['fin'] if p['fin'] else (None, None, None, None, None, None)
        conflicts = []
        if roe is None:
            roe = 0
        if debt is None:
            debt = 0

        # 定义金叉：DIF>DEA 且 MACD>0，且收盘价站上 MA5
        gold_cross = False
        if tech:
            gold_cross = (tech['dif'] > tech['dea'] and tech['macd'] > 0 and tech['close'] > tech['ma5'])

        # 定义超买：RSI>70 或 J>80 或 收盘价突破布林上轨
        overbought = False
        if tech:
            overbought = ((tech['rsi'] is not None and tech['rsi'] > 70) or
                          (tech['j'] is not None and tech['j'] > 80) or
                          (tech['boll_upper'] is not None and tech['close'] > tech['boll_upper']))

        # 定义严重超卖：RSI<30 或 J<20 或 收盘价跌破布林下轨
        oversold = False
        if tech:
            oversold = ((tech['rsi'] is not None and tech['rsi'] < 30) or
                        (tech['j'] is not None and tech['j'] < 20) or
                        (tech['boll_lower'] is not None and tech['close'] < tech['boll_lower']))

        # 1) 主升浪强烈推荐(>70) vs 翻倍基因<3
        if steady_score is not None and steady_score > 70 and dg_score < 3:
            conflicts.append(f"主升浪策略强烈推荐(评分={steady_score:.1f}>70)，但翻倍基因评分仅{dg_score:.1f}分")

        # 2) 技术面出现金叉买入信号，但基本面 ROE 为负或负债率 > 70%
        if gold_cross and (roe < 0 or debt > 70):
            detail = []
            if roe < 0:
                detail.append(f"ROE={roe}%为负")
            if debt > 70:
                detail.append(f"负债率={debt}%>70%")
            conflicts.append("技术面出现MACD金叉买入信号，但基本面" + "、".join(detail))

        # 3) V1 筛选通过（在候选池中），但翻倍基因评分仅 1-2 分
        if passed and dg_score <= 2:
            conflicts.append(f"V1 筛选通过(total_score={total_score})，但翻倍基因评分仅{dg_score:.1f}分")

        # 4) 通达信多个技术指标同时给出相反信号
        tech_signals = []
        # MACD 金叉 vs RSI 超买
        if gold_cross and tech['rsi'] is not None and tech['rsi'] > 70:
            tech_signals.append("MACD金叉但RSI超买")
        # MACD 金叉 vs J 超买 / 突破布林上轨
        if gold_cross and (tech['j'] is not None and tech['j'] > 80 or
                           tech['boll_upper'] is not None and tech['close'] > tech['boll_upper']):
            tech_signals.append("MACD金叉但KDJ超买/突破布林上轨")
        # MACD 绿柱/死叉 vs RSI 严重超卖
        if tech['macd'] < 0 and oversold:
            tech_signals.append("MACD偏弱但RSI/KDJ严重超卖")
        if tech_signals:
            conflicts.append("技术指标矛盾: " + "；".join(tech_signals))

        print("\n[冲突检测]")
        if conflicts:
            for c in conflicts:
                print(f"  ⚠️ {c}")
        else:
            print("  ✅ 未发现明显信号冲突")

        print()
        summary.append({
            'code': code, 'name': p['name'], 'sector': p['sector'],
            'steady': steady_score, 'dg': dg_score,
            'v1_total': total_score, 'passed': passed,
            'roe': roe, 'debt': debt,
            'gold_cross': gold_cross, 'overbought': overbought, 'oversold': oversold,
            'tech_signals': tech_signals if conflicts else [],
            'conflicts': conflicts,
            'level': su['level'], 'advice': su['advice']
        })

    print("=" * 120)
    print("汇总")
    print("=" * 120)
    header = f"{'代码':<8} {'主升浪评分':<10} {'翻倍基因':<8} {'V1总分':<8} {'ROE':<8} {'负债率':<8} {'金叉':<6} {'超买/超卖':<12} {'冲突':<40}"
    print(header)
    print("-" * 110)
    for s in summary:
        conflict_types = []
        for c in s['conflicts']:
            if '主升浪' in c:
                conflict_types.append('主升浪vs翻倍')
            if '基本面' in c:
                conflict_types.append('技术vs基本面')
            if 'V1' in c:
                conflict_types.append('V1vs翻倍')
            if '技术指标矛盾' in c:
                conflict_types.append('技术矛盾')
        print(f"{s['code']:<8} {s['steady']:<10} {s['dg']:<8} {s['v1_total']:<8} {s['roe']:<8} {s['debt']:<8} {'是' if s['gold_cross'] else '否':<6} {'超买' if s['overbought'] else ('超卖' if s['oversold'] else '中性'):<12} {','.join(conflict_types) if conflict_types else '-':<40}")

    print("\n冲突原因分析：")
    for s in summary:
        if s['conflicts']:
            print(f"\n{s['code']} {s['name']}:")
            for c in s['conflicts']:
                print(f"  - {c}")
            cause = []
            if s['dg'] <= 2:
                cause.append("翻倍基因受低ROE/利润负增长拖累")
            if s['gold_cross'] and (s['roe'] < 0 or s['debt'] > 60):
                cause.append("技术面反弹领先于基本面改善")
            if s['overbought'] and s['gold_cross']:
                cause.append("短期资金推动导致超买")
            if s['oversold'] and s['dg'] >= 3:
                cause.append("超卖提供安全边际")
            if cause:
                print("  可能原因: " + "；".join(cause))
            else:
                print("  可能原因: 当前处于策略分歧点，需结合下一日量能确认方向")

if __name__ == "__main__":
    main()
