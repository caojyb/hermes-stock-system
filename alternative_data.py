#!/usr/bin/env python3
"""
另类数据模块 v1.0 — 研报情绪 + 新闻情绪 + 互动信号
=================================================
数据源：
1. 东方财富研报中心：抓取近7天个股研报，提取"目标价上调""盈利预测上调""首次覆盖"三类信号
2. 新闻情绪：从财经新闻摘要中提取正面/负面关键词
3. 将上述信号量化为0-10分的另类情绪评分，写入候选池
"""
import os, sys, json, sqlite3, re, math
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))

# 研报信号关键词
REPORT_KEYWORDS = {
    "target_up": ["目标价上调", "上调目标价", "看高至", "目标价看高"],
    "earnings_up": ["盈利预测上调", "上调盈利预测", "业绩超预期", "超预期增长", "上调业绩"],
    "first_cover": ["首次覆盖", "首次给予", "首次评级", "首次关注"],
}

# 新闻情绪关键词
POSITIVE_NEWS = ["突破", "增长", "中标", "签约", "投产", "获批", "放量", "供不应求",
                 "产能扩张", "订单饱满", "大幅增长", "创历史新高", "扭亏为盈"]
NEGATIVE_NEWS = ["下滑", "亏损", "减持", "诉讼", "违约", "召回", "整改", "监管",
                 "跌停", "暴雷", "st", "退市", "立案", "调查", "处罚"]


def fetch_research_reports(days=365):
    """从东方财富研报中心抓取近N天研报
    返回: {code: {target_up: int, earnings_up: int, first_cover: int, reports: list}}
    """
    import akshare as ak
    import pandas as pd

    result = defaultdict(lambda: {"target_up": 0, "earnings_up": 0, "first_cover": 0, "reports": []})

    try:
        df = ak.stock_research_report_em()
        if df is None or df.empty:
            return result

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        for _, row in df.iterrows():
            date_str = str(row.get("日期", ""))
            if date_str < cutoff:
                continue

            code = str(row.get("股票代码", "")).strip()
            if not code or len(code) != 6:
                continue

            title = str(row.get("报告名称", ""))
            rating = str(row.get("东财评级", ""))

            report = {
                "title": title,
                "rating": rating,
                "date": date_str,
                "institution": str(row.get("机构", "")),
            }
            result[code]["reports"].append(report)

            # 关键词匹配
            for keyword in REPORT_KEYWORDS["target_up"]:
                if keyword in title:
                    result[code]["target_up"] += 1
            for keyword in REPORT_KEYWORDS["earnings_up"]:
                if keyword in title:
                    result[code]["earnings_up"] += 1
            for keyword in REPORT_KEYWORDS["first_cover"]:
                if keyword in title:
                    result[code]["first_cover"] += 1

    except Exception as e:
        print(f"⚠️ 研报获取失败: {e}", file=sys.stderr)

    return result


def fetch_news_sentiment(codes, days=3):
    """从财经新闻中提取个股情绪
    返回: {code: sentiment_score}
    """
    if not codes:
        return {}

    import akshare as ak
    result = {}

    try:
        # 获取最近新闻
        news_df = ak.stock_info_global_em()
        if news_df is None or news_df.empty:
            return result

        cutoff = (datetime.now() - timedelta(days=days))
        news_text = ""

        for _, row in news_df.iterrows():
            pub_time = str(row.get("发布时间", ""))
            try:
                pub_dt = datetime.strptime(pub_time, "%Y-%m-%d %H:%M:%S")
                if pub_dt < cutoff:
                    continue
            except:
                continue

            title = str(row.get("标题", ""))
            summary = str(row.get("摘要", ""))
            news_text += title + " " + summary + "\n"

        # 计算整体市场情绪
        pos_count = sum(1 for kw in POSITIVE_NEWS if kw in news_text)
        neg_count = sum(1 for kw in NEGATIVE_NEWS if kw in news_text)
        total = pos_count + neg_count

        if total > 0:
            market_sentiment = (pos_count - neg_count) / total
        else:
            market_sentiment = 0

        # 为每个code分配情绪（基于市场整体情绪+个股相关度）
        for code in codes:
            code_news = news_text[:1000]  # 简化
            code_pos = sum(1 for kw in POSITIVE_NEWS if kw in code_news)
            code_neg = sum(1 for kw in NEGATIVE_NEWS if kw in code_news)
            code_total = code_pos + code_neg
            if code_total > 0:
                code_sent = (code_pos - code_neg) / code_total
            else:
                code_sent = market_sentiment

            # 归一化到0-10
            result[code] = round((code_sent + 1) * 5, 1)  # -1->0, 0->5, 1->10

    except Exception as e:
        print(f"⚠️ 新闻情绪获取失败: {e}", file=sys.stderr)

    return result


def calc_alternative_score(code, report_data, news_sentiment):
    """计算另类情绪评分 (0-10)
    加权：
    - 研报情绪：目标价上调+2分/次, 盈利预测上调+1.5分/次, 首次覆盖+1分/次
    - 新闻情绪：0-10分 (从新闻情绪直接映射)
    """
    score = 5.0  # 中性基准

    # 研报信号
    rd = report_data.get(code, {})
    score += rd.get("target_up", 0) * 2.0
    score += rd.get("earnings_up", 0) * 1.5
    score += rd.get("first_cover", 0) * 1.0

    # 新闻情绪
    news_score = news_sentiment.get(code, 5.0)
    score = score * 0.6 + news_score * 0.4  # 加权混合

    return round(max(0, min(10, score)), 1)


def scan_all_candidates():
    """扫描所有候选股，计算另类情绪评分"""
    if not os.path.exists(MARKET_DB):
        msg = f"🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}"
        print(f"\n{'='*60}\n{msg}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()

    # 获取候选池（从double_up_scores表）
    c.execute("SELECT code FROM double_up_scores WHERE total_score > 0")
    candidates = [r[0] for r in c.fetchall()]

    if not candidates:
        # 回退：从stocks表取前100只
        c.execute("SELECT code FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' LIMIT 100")
        candidates = [r[0] for r in c.fetchall()]

    print(f"📡 扫描 {len(candidates)} 只候选股的另类数据...")

    # 获取研报数据
    report_data = fetch_research_reports(days=365)
    print(f"  研报抓取: {sum(len(v['reports']) for v in report_data.values())} 条, {len(report_data)} 只股票")

    # 获取新闻情绪
    news_sentiment = fetch_news_sentiment(candidates, days=3)
    print(f"  新闻情绪: {len(news_sentiment)} 只")

    # 计算评分
    results = []
    for code in candidates:
        score = calc_alternative_score(code, report_data, news_sentiment)

        detail = []
        rd = report_data.get(code, {})
        if rd.get("target_up", 0) > 0:
            detail.append(f"目标价上调{rd['target_up']}次")
        if rd.get("earnings_up", 0) > 0:
            detail.append(f"盈利预测上调{rd['earnings_up']}次")
        if rd.get("first_cover", 0) > 0:
            detail.append(f"首次覆盖{rd['first_cover']}次")
        if news_sentiment.get(code, 5.0) != 5.0:
            detail.append(f"新闻情绪{news_sentiment.get(code, 5.0):.1f}分")

        results.append({
            "code": code,
            "score": score,
            "detail": " | ".join(detail) if detail else "无信号",
        })

    conn.commit()
    conn.close()

    # 按评分排序输出
    results.sort(key=lambda x: -x["score"])
    print(f"\n📊 另类情绪评分 Top 20:")
    print(f"  {'代码':<8s} {'评分':<6s} {'信号'}")

    # 检查indicators表是否有alternative_score列
    if not os.path.exists(MARKET_DB):
        msg = f"🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}"
        print(f"\n{'='*60}\n{msg}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn2 = sqlite3.connect(MARKET_DB)
    c2 = conn2.cursor()
    c2.execute("PRAGMA table_info(indicators)")
    cols = [r[1] for r in c2.fetchall()]

    if 'alternative_score' not in cols:
        print(f"\n  ⚠️ indicators表缺少alternative_score列，正在添加...")
        try:
            c2.execute("ALTER TABLE indicators ADD COLUMN alternative_score REAL")
            conn2.commit()
            print(f"  ✅ 已添加列")
        except Exception as e:
            print(f"  ❌ 添加列失败: {e}")
            conn2.close()
            conn.close()
            return results

    # 写入数据库
    for r in results:
        try:
            c2.execute("UPDATE indicators SET alternative_score=? WHERE code=?", (r["score"], r["code"]))
        except Exception as e:
            print(f"  ⚠️ 写入{r['code']}失败: {e}")
    conn2.commit()
    conn2.close()

    for r in results[:20]:
        bar = "█" * max(1, int(r["score"]))
        print(f"  {r['code']:<8s} {r['score']:>5.1f}  {bar} {r['detail'][:50]}")

    print(f"\n  📊 评分分布:")
    buckets = {"0-3": 0, "3-5": 0, "5-7": 0, "7-8": 0, "8-10": 0}
    for r in results:
        s = r["score"]
        if s < 3: buckets["0-3"] += 1
        elif s < 5: buckets["3-5"] += 1
        elif s < 7: buckets["5-7"] += 1
        elif s < 8: buckets["7-8"] += 1
        else: buckets["8-10"] += 1
    for bucket, count in buckets.items():
        bar = "█" * max(1, int(count / max(len(results), 1) * 50))
        print(f"    {bucket:<8s}: {count:>4d}  {bar}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="另类数据模块")
    parser.add_argument("--scan", action="store_true", help="扫描候选池")
    parser.add_argument("--report", type=str, help="指定股票代码查看研报")
    args = parser.parse_args()

    if args.report:
        rd = fetch_research_reports(days=30)
        reports = rd.get(args.report, {}).get("reports", [])
        print(f"\n📋 {args.report} 近30天研报 ({len(reports)} 条):")
        for r in reports[:10]:
            print(f"  {r['date']} [{r['rating']}] {r['institution']}: {r['title'][:60]}")
    elif args.scan:
        scan_all_candidates()
    else:
        scan_all_candidates()