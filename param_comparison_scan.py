#!/usr/bin/env python3
"""
翻倍策略 V1 参数对比扫描
========================
用旧参数和新参数分别扫描全市场，对比候选池差异。
"""
import os, sys, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
TODAY = datetime.now().strftime('%Y-%m-%d')

# ── 旧参数（V1 原默认值，量比按用户说的 1.8） ──
OLD_PARAMS = {
    "price_pos_max": 40,
    "vol_ratio_min": 1.8,      # 用户说原值是 1.8
    "mcap_min": 5,
    "mcap_max": 50,
    "turnover_min": 1000,      # 万元
    "atr_pct_min": 3,
    "turnover_min_20d": 0,     # 旧参数无20日均约束
}

# ── 新参数（Top3 GA 优化结果） ──
NEW_PARAMS = {
    "price_pos_max": 40,
    "vol_ratio_min": 2.7,
    "mcap_min": 5,
    "mcap_max": 90,
    "turnover_min": 8000,      # 万元
    "atr_pct_min": 3,
    "turnover_min_20d": 4000,  # 万元，20日均成交额门槛
}


def scan_stocks(params, label):
    """用一组参数扫描全市场候选池"""
    p = params
    price_pos_max = p["price_pos_max"]
    vol_ratio_min = p["vol_ratio_min"]
    mcap_min = p["mcap_min"]
    mcap_max = p["mcap_max"]
    turnover_min = p["turnover_min"]
    atr_pct_min = p["atr_pct_min"]
    turnover_min_20d = p["turnover_min_20d"]
    min_turnover_1d = turnover_min * 10000    # 万元→元
    min_turnover_20d = turnover_min_20d * 10000

    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取股票池
    cur.execute("""
        SELECT code, name, total_mcap, sector FROM stocks
        WHERE total_mcap BETWEEN ? AND ?
          AND (is_st IS NULL OR is_st = 0)
          AND code NOT LIKE '688%%'
          AND code NOT LIKE '787%%'
    """, (mcap_min * 1e8, mcap_max * 1e8))
    universe = {r["code"]: dict(r) for r in cur.fetchall()}
    print(f"\n[{label}] 初始股票池: {len(universe)} 只 (市值{mcap_min}-{mcap_max}亿)")

    # 逐只扫描
    scored = []
    skip_stats = {"st": 0, "mcap": 0, "data_insufficient": 0, "price_pos": 0,
                   "vol_ratio": 0, "turnover_1d": 0, "turnover_20d": 0, "atr": 0}

    for code in list(universe.keys())[:2000]:
        sinfo = universe[code]
        name = sinfo.get("name", "")

        try:
            # 加载K线
            cur.execute("""
                SELECT date, close, volume, turnover, high, low
                FROM klines WHERE code=? AND date<=?
                ORDER BY date DESC LIMIT 500
            """, (code, TODAY))
            kl_raw = cur.fetchall()
            if not kl_raw or len(kl_raw) < 60:
                skip_stats["data_insufficient"] += 1
                continue
            kl_raw.reverse()
            closes = [r[1] for r in kl_raw if r[1] is not None]
            if len(closes) < 60:
                skip_stats["data_insufficient"] += 1
                continue

            # 流动性约束1: 信号日成交额
            latest_turnover = kl_raw[-1][3] or 0
            if latest_turnover < min_turnover_1d:
                skip_stats["turnover_1d"] += 1
                continue

            # 流动性约束2: 20日均成交额
            if turnover_min_20d > 0 and len(kl_raw) >= 25:
                recent_ts = [r[3] or 0 for r in kl_raw[-25:]]
                avg_turnover_20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1)
                if avg_turnover_20d < min_turnover_20d:
                    skip_stats["turnover_20d"] += 1
                    continue

            # 价格分位
            price_pos = (closes[-1] - min(closes)) / (max(closes) - min(closes)) * 100
            if price_pos > price_pos_max:
                skip_stats["price_pos"] += 1
                continue

            # 量比
            if len(kl_raw) < 25:
                skip_stats["data_insufficient"] += 1
                continue
            vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
            vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
            vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
            if vol_ratio < vol_ratio_min:
                skip_stats["vol_ratio"] += 1
                continue

            # ATR
            trs = []
            for i in range(1, len(kl_raw)):
                h, l, pc = kl_raw[i][4] or 0, kl_raw[i][5] or 0, kl_raw[i-1][1] or 0
                if h and l and pc:
                    trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            if len(trs) < 14:
                skip_stats["data_insufficient"] += 1
                continue
            atr = sum(trs[-14:]) / 14
            close = kl_raw[-1][1] or 0
            atr_pct = atr / close * 100 if close else 0
            if atr_pct < atr_pct_min:
                skip_stats["atr"] += 1
                continue

            # 通过所有筛选
            mcap_wan = (sinfo.get("total_mcap", 0) or 0) / 1e4
            scored.append({
                "code": code,
                "name": name,
                "sector": sinfo.get("sector", ""),
                "mcap": round(mcap_wan, 1),
                "price_pos": round(price_pos, 1),
                "vol_ratio": round(vol_ratio, 2),
                "atr_pct": round(atr_pct, 1),
                "turnover_1d": round(latest_turnover / 10000, 0),  # 万元
            })

        except Exception as e:
            continue

    conn.close()

    # 排序
    scored.sort(key=lambda x: -x["vol_ratio"])

    print(f"[{label}] 通过全部筛选: {len(scored)} 只")
    print(f"[{label}] 各筛选器跳过数量:")
    for k, v in skip_stats.items():
        print(f"  {k}: {v}")
    print()

    return scored


def compare_results(old, new):
    """对比两组结果"""
    old_codes = {s["code"] for s in old}
    new_codes = {s["code"] for s in new}
    overlap = old_codes & new_codes
    only_old = old_codes - new_codes
    only_new = new_codes - old_codes

    print(f"\n{'='*60}")
    print(f"  对比结果")
    print(f"{'='*60}")
    print(f"  旧参数候选池: {len(old_codes)} 只")
    print(f"  新参数候选池: {len(new_codes)} 只")
    print(f"  两参数都选中: {len(overlap)} 只")
    print(f"  旧参数独有(新参数排除): {len(only_old)} 只")
    print(f"  新参数独有(旧参数未选中): {len(only_new)} 只")
    print()

    # 排除原因分析
    print(f"\n  ── 旧参数独有股票排除原因分析（仅 Top 20） ──")
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    for s in [x for x in old if x["code"] in only_old][:20]:
        code = s["code"]
        name = s["name"]
        # 检查新参数的每个条件
        cur.execute("""
            SELECT date, close, volume, turnover, high, low
            FROM klines WHERE code=? AND date<=?
            ORDER BY date DESC LIMIT 500
        """, (code, TODAY))
        kl_raw = cur.fetchall()
        if not kl_raw or len(kl_raw) < 60:
            print(f"  {code}({name}): 数据不足")
            continue
        kl_raw.reverse()
        closes = [r[1] for r in kl_raw if r[1] is not None]
        if len(closes) < 60:
            continue

        # 检查各项
        reasons = []
        latest_turnover = kl_raw[-1][3] or 0
        if latest_turnover < 8000 * 10000:
            reasons.append(f"成交额{latest_turnover/10000:.0f}万<8000万")
        if len(kl_raw) >= 25:
            recent_ts = [r[3] or 0 for r in kl_raw[-25:]]
            avg_t20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1)
            if avg_t20d < 4000 * 10000:
                reasons.append(f"20日均{avg_t20d/10000:.0f}万<4000万")
        vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
        vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
        vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
        if vol_ratio < 2.7:
            reasons.append(f"量比{vol_ratio:.1f}<2.7")
        mcap_wan = (s.get("mcap", 0))
        if mcap_wan > 50:
            reasons.append(f"市值{mcap_wan:.0f}亿>50亿")
        print(f"  {code}({name}): {'; '.join(reasons)}" if reasons else f"  {code}({name}): 未知原因")
    conn.close()

    # 新参数独有分析
    print(f"\n  ── 新参数独有股票（旧参数未选中）Top 20 ──")
    for s in [x for x in new if x["code"] in only_new][:20]:
        print(f"  {s['code']}({s['name']:10s}) 市值{s['mcap']:>5.1f}亿 量比{s['vol_ratio']:>4.1f} 成交额{s['turnover_1d']:.0f}万")
    conn.close()

    return {
        "old_count": len(old_codes),
        "new_count": len(new_codes),
        "overlap_count": len(overlap),
        "only_old_count": len(only_old),
        "only_new_count": len(only_new),
    }


def main():
    print(f"\n{'='*60}")
    print(f"  翻倍策略 V1 参数对比扫描")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    print(f"\n  📋 旧参数: 分位≤40%, 量比≥1.8, 市值5-50亿, 成交额≥1000万, ATR≥3%")
    print(f"  📋 新参数: 分位≤40%, 量比≥2.7, 市值5-90亿, 成交额≥8000万, 20日均≥4000万, ATR≥3%")

    old = scan_stocks(OLD_PARAMS, "旧参数")
    new = scan_stocks(NEW_PARAMS, "新参数")

    comparison = compare_results(old, new)

    # 判定
    print(f"\n  ── 判定 ──")
    n = comparison["new_count"]
    if 10 <= n <= 50:
        print(f"  ✅ 新参数候选池 {n} 只，在 10-50 只合理范围内 → 可直接替换")
    elif n < 5:
        print(f"  ❌ 新参数候选池 {n} 只 < 5 只 → 参数过严，建议放宽")
    elif n > 100:
        print(f"  ⚠️ 新参数候选池 {n} 只 > 100 只 → 参数过松，建议收紧")
    else:
        print(f"  ℹ️ 新参数候选池 {n} 只，在合理范围边缘，建议结合回测结果判断")

    print(f"\n{'='*60}")
    print(f"  ✅ 对比扫描完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
