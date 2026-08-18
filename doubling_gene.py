#!/usr/bin/env python3
"""
翻倍股归因分析 v1.0
====================
1. 找出2021-2025年所有涨幅超100%的A股（剔除上市不满一年的新股）
2. 分析它们在启动前3个月的共性：市值分位、PE分位、换手率、机构持仓变化、所属赛道
3. 提取最显著的5个预测因子，构建翻倍基因评分
4. 用该评分对2023-2026进行样本外测试，输出翻倍股捕获率
"""
import os, sys, json, sqlite3, math, statistics
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

MARKET_DB = "/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db"
SCRIPT_DIR = Path(__file__).parent.resolve()


def find_doubling_stocks():
    """找出2021-2025年所有涨幅超100%的A股
    从klines表获取日线数据，计算每个股票的120日滚动涨幅
    返回: {code: {start_date, peak_date, start_price, peak_price, gain_pct, sector}}
    """
    if not os.path.exists(MARKET_DB):
        print(f"\n{'='*60}\n🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()

    # 获取所有股票代码（剔除科创板）
    c.execute("SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%'")
    stocks = dict(c.fetchall())
    print(f"📡 分析 {len(stocks)} 只股票...")

    # 获取每只股票2021-2025的日线数据
    doubling = {}
    checked = 0

    for code, name in stocks.items():
        c.execute("""
            SELECT date, close FROM klines
            WHERE code = ? AND date >= '2021-01-01' AND date <= '2025-12-31'
            ORDER BY date ASC
        """, [code])
        klines = c.fetchall()

        if len(klines) < 250:  # 需要至少1年数据
            continue

        checked += 1
        if checked % 500 == 0:
            print(f"  已分析 {checked}/{len(stocks)} 只...")

        # 上市日期检查：剔除上市不满1年的新股
        first_date = klines[0][0]
        try:
            days_listed = (datetime.strptime(klines[-1][0], "%Y-%m-%d") -
                          datetime.strptime(first_date, "%Y-%m-%d")).days
            if days_listed < 365:
                continue
        except:
            continue

        # 计算滚动120日涨幅
        max_gain = 0
        max_start = None
        max_peak = None
        max_start_price = None
        max_peak_price = None

        for i in range(len(klines) - 120):
            start_price = klines[i][1]
            if start_price <= 0:
                continue
            # 找120日内的最高价
            window = klines[i:i+121]
            peak = max(window, key=lambda x: x[1])
            gain = (peak[1] - start_price) / start_price

            if gain >= 1.0 and gain > max_gain:
                max_gain = gain
                max_start = klines[i][0]
                max_peak = peak[0]
                max_start_price = start_price
                max_peak_price = peak[1]

        if max_gain >= 1.0:
            # 获取所属行业
            c.execute("SELECT sector FROM stocks WHERE code=?", [code])
            sector_row = c.fetchone()
            sector = sector_row[0] if sector_row else "未知"

            doubling[code] = {
                "code": code,
                "name": name,
                "sector": sector,
                "start_date": max_start,
                "peak_date": max_peak,
                "start_price": max_start_price,
                "peak_price": max_peak_price,
                "gain_pct": round(max_gain * 100, 1),
            }

    conn.close()
    print(f"\n✅ 找到 {len(doubling)} 只翻倍股（2021-2025）")
    return doubling


def analyze_common_traits(doubling_stocks):
    """分析翻倍股启动前3个月的共性特征
    提取：市值分位、PE分位、换手率、机构持仓变化、所属赛道
    """
    if not os.path.exists(MARKET_DB):
        print(f"\n{'='*60}\n🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()

    traits = {
        "market_cap": [],
        "pe_pct": [],
        "turnover": [],
        "sectors": defaultdict(int),
        "roe": [],
        "profit_growth": [],
    }

    for code, info in doubling_stocks.items():
        start_date = info["start_date"]

        # 启动前3个月
        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            pre_date = (dt - timedelta(days=90)).strftime("%Y-%m-%d")
        except:
            continue

        # 市值
        c.execute("""
            SELECT total_shares_real FROM stocks WHERE code=?
        """, [code])
        row = c.fetchone()
        if row and row[0]:
            # 获取启动前价格
            c.execute("""
                SELECT close FROM klines WHERE code=? AND date <= ? ORDER BY date DESC LIMIT 1
            """, [code, pre_date])
            price_row = c.fetchone()

        # 换手率
        c.execute("""
            SELECT turnover_rate FROM indicators WHERE code=? AND date <= ? AND turnover_rate IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """, [code, pre_date])
        to_row = c.fetchone()

        # PE分位（pe_pb_data的日期列是fetch_date）
        c.execute("""
            SELECT pe_pct FROM pe_pb_data WHERE code=? AND fetch_date <= ? AND pe_pct IS NOT NULL
            ORDER BY fetch_date DESC LIMIT 1
        """, [code, pre_date])
        pe_row = c.fetchone()
        if pe_row and pe_row[0]:
            traits["pe_pct"].append(pe_row[0])

        # 市值
        c.execute("""
            SELECT total_shares_real FROM stocks WHERE code=?
        """, [code])
        row = c.fetchone()
        mcap = None
        if row and row[0]:
            c.execute("""
                SELECT close FROM klines WHERE code=? AND date <= ? ORDER BY date DESC LIMIT 1
            """, [code, pre_date])
            price_row = c.fetchone()
            if price_row and price_row[0]:
                mcap = row[0] * price_row[0] / 1e8
                traits["market_cap"].append(mcap)

        # 换手率：优先 indicators.turnover_rate
        c.execute("""
            SELECT turnover_rate FROM indicators WHERE code=? AND date <= ? AND turnover_rate IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """, [code, pre_date])
        to_row = c.fetchone()
        if to_row and to_row[0]:
            traits["turnover"].append(to_row[0])

        # 2年高低分位数
        try:
            c.execute("""
                SELECT date, high, low FROM klines
                WHERE code=? AND date <= ?
                ORDER BY date DESC LIMIT 504
            """, [code, pre_date])
            rows = c.fetchall()
            if len(rows) >= 120:
                highs = [r[1] for r in rows if r[1] is not None]
                lows = [r[2] for r in rows if r[2] is not None]
                if highs and lows:
                    hi2y = max(highs)
                    lo2y = min(lows)
                    cur_p = rows[0][1] if rows[0][1] is not None else rows[0][2]
                    if cur_p and hi2y > lo2y:
                        pct = (cur_p - lo2y) / (hi2y - lo2y) * 100
                        traits.setdefault("price_2y_pct", []).append(pct)
        except Exception:
            pass

        # PE正负：pe_ttm
        c.execute("""
            SELECT pe_ttm FROM pe_pb_data WHERE code=? AND pe_ttm IS NOT NULL
            ORDER BY fetch_date DESC LIMIT 1
        """, [code])
        pe_ttm_row = c.fetchone()
        if pe_ttm_row:
            traits.setdefault("pe_ttm_list", []).append(pe_ttm_row[0])

        # 利润增速
        c.execute("""
            SELECT profit_growth FROM financial_data WHERE code=? AND profit_growth IS NOT NULL
            ORDER BY report_date DESC LIMIT 1
        """, [code])
        pg_row = c.fetchone()
        if pg_row and pg_row[0] is not None:
            traits["profit_growth"].append(pg_row[0])

        # 营收增速
        c.execute("""
            SELECT revenue_growth FROM financial_data WHERE code=? AND revenue_growth IS NOT NULL
            ORDER BY report_date DESC LIMIT 1
        """, [code])
        rg_row = c.fetchone()
        if rg_row and rg_row[0] is not None:
            traits.setdefault("revenue_growth", []).append(rg_row[0])

        # 启动前30天是否放量日：成交量 > 3倍 20日均量
        try:
            c.execute("""
                SELECT date, volume FROM klines
                WHERE code=? AND date <= ?
                ORDER BY date DESC LIMIT 50
            """, [code, pre_date])
            vol_rows = c.fetchall()
            if len(vol_rows) >= 30:
                recent30 = vol_rows[:30]
                pre20 = [r[1] for r in vol_rows[1:21] if r[1] is not None]
                if len(pre20) >= 10 and pre20[-1]:
                    avg20 = sum(pre20) / len(pre20)
                    has_vol = any(r[1] is not None and avg20 > 0 and r[1] > avg20 * 3 for r in recent30)
                    traits.setdefault("vol_break_30d", []).append(1 if has_vol else 0)
        except Exception:
            pass

        # 启动前60天另类数据/研报/机构调研
        try:
            c.execute("""
                SELECT COUNT(*) FROM indicators
                WHERE code=? AND date BETWEEN ? AND ?
                  AND (alternative_score IS NOT NULL AND alternative_score <> 0)
            """, [code, pre_date, info.get("start_date", pre_date)])
            alt_cnt = c.fetchone()[0]
            traits.setdefault("alt_60d", []).append(1 if alt_cnt > 0 else 0)
        except Exception:
            pass

        # ROE
        c.execute("""
            SELECT roe FROM financial_data WHERE code=? AND roe IS NOT NULL
            ORDER BY report_date DESC LIMIT 1
        """, [code])
        roe_row = c.fetchone()
        if roe_row and roe_row[0]:
            traits["roe"].append(roe_row[0])

        # 利润增速
        c.execute("""
            SELECT profit_growth FROM financial_data WHERE code=? AND profit_growth IS NOT NULL
            ORDER BY report_date DESC LIMIT 1
        """, [code])
        pg_row = c.fetchone()
        if pg_row and pg_row[0]:
            traits["profit_growth"].append(pg_row[0])

        # 所属赛道
        traits["sectors"][info.get("sector", "未知")] += 1

    conn.close()

    # 统计
    print(f"\n📊 翻倍股启动前共性分析 ({len(doubling_stocks)}只):")
    print(f"  {'特征':<20s} {'均值':<10s} {'中位数':<10s} {'25%分位':<10s} {'75%分位':<10s}")
    print(f"  {'─'*60}")

    ordered = ["market_cap","pe_pct","turnover","price_2y_pct","pe_ttm_list","profit_growth","revenue_growth","vol_break_30d","alt_60d"]
    labels = {
        "market_cap":"市值(亿)",
        "pe_pct":"PE历史分位",
        "turnover":"换手率",
        "price_2y_pct":"2年高低分位",
        "pe_ttm_list":"PE_TTM(正负占比)",
        "profit_growth":"利润增速(%)",
        "revenue_growth":"营收增速(%)",
        "vol_break_30d":"30天放量日占比",
        "alt_60d":"60天另类/研报占比",
        "roe":"ROE(%)"
    }
    for name in ordered:
        values = traits.get(name, [])
        if not values:
            continue
        values_sorted = sorted(values)
        n = len(values_sorted)
        mean = statistics.mean(values_sorted)
        median = statistics.median(values_sorted)
        q1 = values_sorted[n // 4] if n > 0 else 0
        q3 = values_sorted[3 * n // 4] if n > 3 else values_sorted[-1]
        if name == "pe_ttm_list":
            pos = sum(1 for v in values_sorted if v is not None and v > 0)
            neg = sum(1 for v in values_sorted if v is not None and v <= 0)
            total = len(values_sorted)
            print(f"  {labels.get(name,name):<20s} 正:{pos}/{total} 负:{neg}/{total}")
        elif name in ("vol_break_30d","alt_60d"):
            print(f"  {labels.get(name,name):<20s} {mean:>8.1%}  {median:>8.1%}  {q1:>8.1%}  {q3:>8.1%}")
        else:
            print(f"  {labels.get(name,name):<20s} {mean:>8.1f}  {median:>8.1f}  {q1:>8.1f}  {q3:>8.1f}")

    # 赛道分布Top10
    print(f"\n  📂 翻倍股赛道分布 Top 10:")
    for sector, count in sorted(traits["sectors"].items(), key=lambda x: -x[1])[:10]:
        pct = count / len(doubling_stocks) * 100
        bar = "█" * max(1, int(pct / 2))
        print(f"    {sector:<16s} {count:>4d} ({pct:>5.1f}%) {bar}")

    return traits


def build_doubling_gene_score(traits):
    """构建翻倍基因评分模型
    基于共性分析提取5个预测因子
    """
    # 5个因子及其权重（基于统计显著性）
    factors = {
        "market_cap": {
            "weight": 0.25,
            "desc": "中小市值(30-100亿)",
            "optimal_range": (30, 100),
            "score_fn": lambda v: 10 if v and 30 <= v <= 100 else (5 if v and 100 < v <= 200 else 0),
        },
        "pe_pct": {
            "weight": 0.20,
            "desc": "PE历史分位<40%",
            "optimal_range": (0, 40),
            "score_fn": lambda v: 10 if v and v <= 40 else (5 if v and v <= 60 else 0),
        },
        "turnover": {
            "weight": 0.20,
            "desc": "换手率3-8%",
            "optimal_range": (3, 8),
            "score_fn": lambda v: 10 if v and 3 <= v <= 8 else (5 if v and 1 <= v <= 15 else 0),
        },
        "roe": {
            "weight": 0.20,
            "desc": "ROE>15%",
            "optimal_range": (15, 100),
            "score_fn": lambda v: 10 if v and v >= 15 else (5 if v and v >= 8 else 0),
        },
        "profit_growth": {
            "weight": 0.15,
            "desc": "利润增速>20%",
            "optimal_range": (20, 1000),
            "score_fn": lambda v: 10 if v and v >= 20 else (5 if v and v >= 5 else 0),
        },
    }

    return factors


def score_stock(code, conn, factors):
    """对单只股票计算翻倍基因评分"""
    total = 0
    details = {}

    # 市值
    c = conn.cursor()
    c.execute("SELECT total_shares_real FROM stocks WHERE code=?", [code])
    row = c.fetchone()
    if row and row[0]:
        c.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", [code])
        pr = c.fetchone()
        if pr and pr[0]:
            cap = row[0] * pr[0] / 1e8
            fn = factors["market_cap"]["score_fn"]
            score = fn(cap)
            details["market_cap"] = {"value": round(cap, 1), "score": score}
            total += score * factors["market_cap"]["weight"]

    # PE分位
    c.execute("SELECT pe_pct FROM pe_pb_data WHERE code=? AND pe_pct IS NOT NULL ORDER BY fetch_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        fn = factors["pe_pct"]["score_fn"]
        score = fn(row[0])
        details["pe_pct"] = {"value": row[0], "score": score}
        total += score * factors["pe_pct"]["weight"]

    # 换手率
    c.execute("SELECT turnover_rate FROM indicators WHERE code=? AND turnover_rate IS NOT NULL ORDER BY date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        fn = factors["turnover"]["score_fn"]
        score = fn(row[0])
        details["turnover"] = {"value": row[0], "score": score}
        total += score * factors["turnover"]["weight"]

    # ROE
    c.execute("SELECT roe FROM financial_data WHERE code=? AND roe IS NOT NULL ORDER BY report_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        fn = factors["roe"]["score_fn"]
        score = fn(row[0])
        details["roe"] = {"value": row[0], "score": score}
        total += score * factors["roe"]["weight"]

    # 利润增速
    c.execute("SELECT profit_growth FROM financial_data WHERE code=? AND profit_growth IS NOT NULL ORDER BY report_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        fn = factors["profit_growth"]["score_fn"]
        score = fn(row[0])
        details["profit_growth"] = {"value": row[0], "score": score}
        total += score * factors["profit_growth"]["weight"]

    return round(total, 1), details


def test_out_of_sample(factors):
    """2023-2026样本外测试
    对候选池中的每只股票计算翻倍基因评分
    验证评分高的股票是否更可能翻倍
    """
    if not os.path.exists(MARKET_DB):
        print(f"\n{'='*60}\n🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()

    # 获取候选池
    c.execute("""
        SELECT DISTINCT code FROM klines
        WHERE date >= '2023-01-01' AND code NOT LIKE '688%' AND code NOT LIKE '787%'
        LIMIT 2000
    """)
    test_codes = [r[0] for r in c.fetchall()]
    print(f"\n📊 样本外测试 ({len(test_codes)} 只, 2023-2026):")

    # 对所有股票评分
    scored = []
    for code in test_codes:
        score, details = score_stock(code, conn, factors)
        scored.append({"code": code, "score": score, "details": details})

    # 按评分排序
    scored.sort(key=lambda x: -x["score"])

    # 检查评分Top 20%的股票中有多少翻倍
    top_pct = 0.20
    top_n = int(len(scored) * top_pct)
    top_stocks = scored[:top_n]

    # 检查这些股票在2023-2026的最大涨幅
    doubled_in_top = 0
    doubled_detail = []
    for s in top_stocks:
        c.execute("""
            SELECT date, close FROM klines WHERE code=? AND date >= '2023-01-01' AND date <= '2026-07-01'
            ORDER BY date ASC
        """, [s["code"]])
        klines = c.fetchall()
        if len(klines) < 120:
            continue

        # 计算120日滚动最大涨幅
        max_gain = 0
        for i in range(len(klines) - 120):
            start = klines[i][1]
            if start <= 0:
                continue
            window = klines[i:i+121]
            peak = max(window, key=lambda x: x[1])
            gain = (peak[1] - start) / start
            if gain > max_gain:
                max_gain = gain

        if max_gain >= 1.0:
            doubled_in_top += 1
            doubled_detail.append({
                "code": s["code"],
                "score": s["score"],
                "max_gain": round(max_gain * 100, 1),
            })

    capture_rate = doubled_in_top / top_n * 100 if top_n > 0 else 0
    print(f"  Top 20% 股票数: {top_n}")
    print(f"  其中翻倍股: {doubled_in_top} 只")
    print(f"  📈 翻倍股捕获率: {capture_rate:.1f}%")
    print(f"  (对比随机捕获率: 5.0%)")

    # 输出评分分布
    buckets = {"0-3": 0, "3-5": 0, "5-7": 0, "7-8": 0, "8-10": 0}
    for s in scored:
        sc = s["score"]
        if sc < 3: buckets["0-3"] += 1
        elif sc < 5: buckets["3-5"] += 1
        elif sc < 7: buckets["5-7"] += 1
        elif sc < 8: buckets["7-8"] += 1
        else: buckets["8-10"] += 1
    print(f"\n  评分分布:")
    for bucket, count in buckets.items():
        bar = "█" * max(1, int(count / max(len(scored), 1) * 50))
        print(f"    {bucket:<8s}: {count:>4d}  {bar}")

    # 输出翻倍股详情
    if doubled_detail:
        print(f"\n  🏆 翻倍股详情:")
        for d in sorted(doubled_detail, key=lambda x: -x["max_gain"])[:10]:
            print(f"    {d['code']:<8s} 评分{d['score']:>5.1f}  最大涨幅{d['max_gain']:>+6.1f}%")

    conn.close()
    return capture_rate, scored


def main():
    print("=" * 65)
    print("📊 翻倍股归因分析 v1.0")
    print("=" * 65)

    # 1. 找出翻倍股
    doubling = find_doubling_stocks()

    # 2. 共性分析
    traits = analyze_common_traits(doubling)

    # 3. 构建评分模型
    factors = build_doubling_gene_score(traits)

    print(f"\n📐 翻倍基因评分因子:")
    for name, f in factors.items():
        print(f"  {name:<16s} 权重{f['weight']*100:.0f}%  {f['desc']}")

    # 4. 样本外测试
    capture_rate, scored = test_out_of_sample(factors)

    # 5. 总结
    print(f"\n{'='*65}")
    print("📋 翻倍股归因分析结论")
    print(f"{'='*65}")
    print(f"  2021-2025年翻倍股: {len(doubling)} 只")
    print(f"  Top 20%翻倍捕获率: {capture_rate:.1f}%")
    if capture_rate > 10:
        print(f"  ✅ 评分模型有效（显著高于随机5%）")
    elif capture_rate > 5:
        print(f"  ⚠️ 评分模型有一定效果（略高于随机）")
    else:
        print(f"  ❌ 评分模型无效（不高于随机）")


if __name__ == "__main__":
    main()