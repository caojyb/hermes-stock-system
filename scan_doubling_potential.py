#!/usr/bin/env python3
"""
翻倍潜力扫描 v2.0 (Top3 参数优化版)
=====================================
扫描全市场，筛选符合翻倍策略 V1 条件的股票，写入 double_up_scores 表。

参数（Top3 GA 优化）：
- 价格分位上限 ≤ 40%
- 量比下限 ≥ 2.7
- 市值范围 5-90亿
- 成交额 ≥ 8000万（硬约束）
- 20日均成交额 ≥ 4000万（硬约束）
- ATR ≥ 3%

用法：
  python3 scan_doubling_potential.py
  python3 scan_doubling_potential.py --json
"""
import os, sys, json, sqlite3, math
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MKT_DB = str(get_db_path('market_cache'))

# ── Top3 优化参数（P2-1：从 stock_strategy_config 集中读取，消除硬编码副本） ──
from stock_strategy_config import DEFAULT_STRATEGY, get_strategy_params
PARAMS = get_strategy_params(DEFAULT_STRATEGY)  # = v1_double 的 Top3 参数

TODAY = date.today().isoformat()


def scan():
    """扫描全市场，返回候选列表"""
    p = PARAMS
    price_pos_max = p["price_pos_max"]
    vol_ratio_min = p["vol_ratio_min"]
    mcap_min = p["mcap_min"]
    mcap_max = p["mcap_max"]
    atr_pct_min = p["atr_pct_min"]
    min_turnover_1d = p["turnover_min"] * 10000
    min_turnover_20d = p["avg_amount_20d"] * 10000

    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 初始股票池
    cur.execute("""
        SELECT code, name, total_mcap, sector FROM stocks
        WHERE total_mcap BETWEEN ? AND ?
          AND (is_st IS NULL OR is_st = 0)
          AND code NOT LIKE '688%%'
          AND code NOT LIKE '787%%'
    """, (mcap_min * 1e8, mcap_max * 1e8))
    universe = {r["code"]: dict(r) for r in cur.fetchall()}
    print(f"  初始股票池: {len(universe)} 只", file=sys.stderr)

    candidates = []
    skip_stats = {"data_insufficient": 0, "price_pos": 0, "vol_ratio": 0,
                   "turnover_1d": 0, "turnover_20d": 0, "atr": 0}

    for code in list(universe.keys()):
        sinfo = universe[code]
        name = sinfo.get("name", "")

        try:
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

            # 流动性硬约束1: 信号日成交额
            latest_turnover = kl_raw[-1][3] or 0
            if latest_turnover < min_turnover_1d:
                skip_stats["turnover_1d"] += 1
                continue

            # 流动性硬约束2: 20日均成交额
            if len(kl_raw) >= 25:
                recent_ts = [(r[3] or 0) for r in kl_raw[-25:]]
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

            # 综合评分
            mcap_wan = (sinfo.get("total_mcap", 0) or 0) / 1e8
            score = 0
            if mcap_min <= mcap_wan <= mcap_min + 15:
                score += 40
            elif mcap_wan <= mcap_max:
                score += 30
            if price_pos <= price_pos_max * 0.5:
                score += 30
            elif price_pos <= price_pos_max:
                score += 20
            if vol_ratio >= vol_ratio_min * 1.5:
                score += 20
            elif vol_ratio >= vol_ratio_min:
                score += 10
            if atr_pct >= atr_pct_min * 1.67:
                score += 15
            elif atr_pct >= atr_pct_min:
                score += 10

            candidates.append({
                "code": code,
                "name": name,
                "sector": sinfo.get("sector", ""),
                "score": score,
                "mcap": round(mcap_wan, 1),
                "price_pos": round(price_pos, 1),
                "vol_ratio": round(vol_ratio, 2),
                "atr_pct": round(atr_pct, 1),
                "turnover_1d": round(latest_turnover / 10000, 0),
                "avg_turnover_20d": round(avg_turnover_20d / 10000, 0) if len(kl_raw) >= 25 else 0,
            })

        except Exception:
            continue

    conn.close()
    candidates.sort(key=lambda x: -x["score"])

    print(f"  通过筛选: {len(candidates)} 只", file=sys.stderr)
    for k, v in skip_stats.items():
        print(f"    跳过-{k}: {v}", file=sys.stderr)

    return candidates


def write_to_db(candidates):
    """写入 double_up_scores 表"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()

    # 删除当天旧数据
    cur.execute("DELETE FROM double_up_scores WHERE scan_date = ?", (TODAY,))
    print(f"  已清除 {TODAY} 旧数据", file=sys.stderr)

    # 写入
    inserted = 0
    for c in candidates:
        cur.execute("""
            INSERT INTO double_up_scores 
            (scan_date, code, name, sector, total_score, industry_score, perf_score, mc_score, turn_score, cat_score, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            TODAY, c["code"], c["name"], c["sector"], c["score"],
            min(40, int(c["score"] * 0.4)),  # industry_score 近似
            min(30, int(c["score"] * 0.3)),  # perf_score 近似
            min(10, int(c["score"] * 0.1)),  # mc_score 近似
            min(20, int(c["score"] * 0.2)),  # turn_score 近似
            0,
            DEFAULT_STRATEGY,  # P2-2: 标记策略来源
        ))
        inserted += 1
    conn.commit()
    conn.close()
    print(f"  已写入 {inserted} 条记录到 double_up_scores", file=sys.stderr)


def check_klines_freshness(scan_date=None):
    """数据新鲜度护栏：K线最新日期若落后 scan_date 超过 1 个交易日，拒绝产出候选池。

    返回 (ok: bool, max_date: str|None, reason: str)
    - 正常：K线 MAX(date) 与 scan_date 差距 ≤ 3 个自然日（覆盖周末+1节假日 = 1 交易日）
    - 停更：差距 > 3 自然日 → 判定 K 线停更，拒绝写池
    """
    try:
        conn = sqlite3.connect(MKT_DB)
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM klines")
        row = cur.fetchone()
        conn.close()
    except Exception as e:
        return False, None, f"查询K线失败: {e}"

    if scan_date is None:
        scan_date = TODAY
    max_date = row[0] if row else None
    if not max_date:
        return False, None, "K线表无任何数据"

    try:
        lag = (datetime.strptime(scan_date, '%Y-%m-%d') - datetime.strptime(max_date, '%Y-%m-%d')).days
    except ValueError:
        return False, max_date, f"日期解析失败 scan={scan_date} max={max_date}"

    # 阈值：3 个自然日 = 周末(2天)+1节假日，等价于 1 个交易日
    if lag > 3:
        return False, max_date, f"K线最新 {max_date} 落后扫描日 {scan_date} 共 {lag} 天(>1交易日)"
    return True, max_date, f"K线最新 {max_date}，差距 {lag} 天，数据新鲜"


def main():

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  翻倍潜力扫描 v2.0 (Top3 参数)", file=sys.stderr)
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}", file=sys.stderr)
    print(f"{'='*55}", file=sys.stderr)

    candidates = scan()

    # ── 数据新鲜度护栏（P0-2）：K线停更时拒绝写入 double_up_scores ──
    fresh_ok, max_date, fresh_reason = check_klines_freshness(TODAY)
    if not fresh_ok:
        print(f"\n[ERROR] K线数据停更，最新日期 {max_date}，扫描日期 {TODAY}，拒绝产出候选池", file=sys.stderr)
        print(f"[ERROR] 原因: {fresh_reason}", file=sys.stderr)
        # 推送飞书告警（静默失败不影响主流程）
        try:
            import urllib.request, os
            token = os.environ.get("FEISHU_WEBHOOK_TOKEN", "")
            if not token:
                for line in open("/home/caojy/.hermes/scripts/cron/stock_opportunity_scan.py", encoding="utf-8"):
                    if "FEISHU_TOKEN" in line and "=" in line and "os.environ" not in line:
                        import re
                        m = re.search(r'=\s*["\']([^"\']+)["\']', line)
                        if m:
                            token = m.group(1); break
            if token:
                payload = json.dumps({"msg_type": "text", "content": {"text":
                    f"🚨 [scan_doubling] K线数据停更告警\n最新日期: {max_date}\n扫描日期: {TODAY}\n原因: {fresh_reason}\n已拒绝产出候选池，防止假新鲜池污染下游"}}).encode("utf-8")
                req = urllib.request.Request("https://open.feishu.cn/open-apis/bot/v2/hook/" + token,
                                             data=payload, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        # 记录 pipeline_status 为 error，让下游/健康监控可感知
        try:
            from pipeline_status import record_status
            record_status('scan-doubling-potential', 'error', TODAY,
                          row_count=0, message=f'K线停更拒绝写池: {fresh_reason}')
        except Exception:
            pass
        return None

    write_to_db(candidates)

    # 输出结果
    print(f"\n{'='*55}")
    print(f"  候选池: {len(candidates)} 只")
    print(f"{'='*55}")

    print(f"\n  {'代码':8s} {'名称':10s} {'行业':10s} {'评分':>4s} {'市值':>6s} {'分位':>5s} {'量比':>5s} {'ATR':>4s} {'成交额':>7s} {'20日均':>7s}")
    print(f"  {'─'*75}")
    for c in candidates[:15]:
        print(f"  {c['code']:8s} {c['name']:10s} {c['sector'][:10]:10s} {c['score']:>4d} "
              f"{c['mcap']:>5.1f}亿 {c['price_pos']:>4.1f}% {c['vol_ratio']:>4.1f} "
              f"{c['atr_pct']:>3.1f}% {c['turnover_1d']:>6.0f}万 {c['avg_turnover_20d']:>6.0f}万")

    # 与 7/28 旧参数对比（从数据库获取上次扫描结果）
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT scan_date FROM double_up_scores ORDER BY scan_date DESC LIMIT 5")
    recent_dates = [r[0] for r in cur.fetchall()]
    print(f"\n  近期扫描记录:", file=sys.stderr)
    for d in recent_dates:
        cur.execute("SELECT COUNT(*) FROM double_up_scores WHERE scan_date=?", (d,))
        cnt = cur.fetchone()[0]
        print(f"    {d}: {cnt} 只", file=sys.stderr)
    conn.close()

    if len(candidates) <= 5:
        print(f"\n  ⚠️ 候选池仅 {len(candidates)} 只，接近过严阈值！")
    elif len(candidates) >= 50:
        print(f"\n  ℹ️ 候选池 {len(candidates)} 只，建议关注是否有过松信号")
    else:
        print(f"\n  ✅ 候选池 {len(candidates)} 只，参数合理")

    print(f"\n{'='*55}")
    print(f"  ✅ 扫描完成")
    print(f"{'='*55}")

    # 记录管道状态
    try:
        from pipeline_status import record_status
        record_status('scan-doubling-potential', 'ok', TODAY,
                      row_count=len(candidates), message=f'扫描到 {len(candidates)} 只')
    except Exception:
        pass

    return candidates


if __name__ == "__main__":
    main()
