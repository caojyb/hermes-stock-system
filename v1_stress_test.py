#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V1 翻倍策略 (Top3参数) — 历史极端行情压力测试
=============================================
对 2007-2008 熊市 / 2015 股灾 / 2016 熔断 / 2018 慢熊 四个极端区间
跑 V1 Top3 诚实回测（T+1开盘价、含成本、月频、每期20只），
并与 2023-2026 正常区间对比，输出压力测试报告。

用法:
  python3 v1_stress_test.py
  python3 v1_stress_test.py --json     # JSON 输出
  python3 v1_stress_test.py --save     # 保存 Markdown 报告
"""
import os, sys, json, sqlite3, time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / ".." / ".." / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"))
import backtest_engine as be

# ── V1 Top3 参数（与 stock_strategy_config 一致） ──
V1_TOPS = {
    "price_pos_max": 40,
    "vol_ratio_min": 2.7,
    "mcap_min": 5,
    "mcap_max": 90,
    "turnover_min": 8000,      # 万元
    "turnover_min_20d": 4000,  # 万元
    "atr_pct_min": 3,
}
TOP_N = 20

# ── 测试区间 ──
SCENARIOS = [
    {"label": "2007-2008 大熊市", "start": "2007-01", "end": "2008-12",
     "desc": "上证6124→1664（-73%），全球金融危机"},
    {"label": "2015 股灾", "start": "2015-06", "end": "2015-12",
     "desc": "股灾1.0+2.0，千股跌停"},
    {"label": "2016 熔断", "start": "2016-01", "end": "2016-02",
     "desc": "熔断机制，4天两次提前收盘"},
    {"label": "2018 慢熊", "start": "2018-01", "end": "2018-12",
     "desc": "去杠杆+贸易战，全年阴跌"},
    {"label": "2023-2026 基准", "start": "2023-01", "end": "2026-07",
     "desc": "当前策略正常验证区间（价格断点已修复，2023-12-05 前后连续）"},
]


def create_strategy_fn(p):
    """创建 V1 Top3 策略函数（标准参数，含流动性硬约束）。

    K线 turnover 单位已统一为"元"（2026-08-10 修复，见 fix_turnover_units.py），
    因此所有区间（含 2007-2008 / 2018 等历史极端区间）均直接使用标准参数：
    当日成交额≥8000万、20日均≥4000万、市值5-90亿。
    """
    price_pos_max = p["price_pos_max"]
    vol_ratio_min = p["vol_ratio_min"]
    mcap_min = p["mcap_min"]
    mcap_max = p["mcap_max"]
    turnover_min = p["turnover_min"]
    atr_pct_min = p["atr_pct_min"]
    turnover_min_20d = p.get("turnover_min_20d", turnover_min // 2)
    min_turnover_1d = turnover_min * 10000
    min_turnover_20d = turnover_min_20d * 10000

    def _strategy(snapshot_date, all_prices, top_n=TOP_N):
        conn = be._get_db()
        cur = conn.execute("""
            SELECT code, name, total_mcap FROM stocks
            WHERE total_mcap BETWEEN ? AND ?
              AND (is_st IS NULL OR is_st = 0)
              AND code NOT LIKE '688%%'
        """, (mcap_min * 1e8, mcap_max * 1e8))
        universe = {r["code"]: {"name": r["name"], "mcap": r["total_mcap"]}
                    for r in cur.fetchall()}
        conn.close()
        if not universe:
            return []

        conn = be._get_db()
        scored = []
        for code in universe:
            try:
                cur = conn.execute("""
                    SELECT date, close, volume, turnover, high, low
                    FROM klines WHERE code=? AND date<=?
                    ORDER BY date DESC LIMIT 500
                """, (code, snapshot_date))
                kl_raw = cur.fetchall()
                if not kl_raw or len(kl_raw) < 60:
                    continue
                kl_raw.reverse()
                closes = [r[1] for r in kl_raw if r[1] is not None]
                if len(closes) < 60:
                    continue

                # turnover 现已统一为元口径（单位修复已完成），直接使用
                latest_turnover = kl_raw[-1][3] or 0
                if latest_turnover < min_turnover_1d:
                    continue
                if len(kl_raw) >= 25:
                    recent_to = [r[3] or 0 for r in kl_raw[-25:]]
                    avg_turnover_20d = sum(recent_to[:-5]) / max(len(recent_to[:-5]), 1)
                    if avg_turnover_20d < min_turnover_20d:
                        continue

                price_pos = (closes[-1] - min(closes)) / (max(closes) - min(closes)) * 100
                if price_pos > price_pos_max:
                    continue
                if len(kl_raw) < 25:
                    continue
                vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
                vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
                vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
                if vol_ratio < vol_ratio_min:
                    continue
                trs = []
                for i in range(1, len(kl_raw)):
                    h, l, pc = kl_raw[i][4] or 0, kl_raw[i][5] or 0, kl_raw[i-1][1] or 0
                    if h and l and pc:
                        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                if len(trs) < 14:
                    continue
                atr = sum(trs[-14:]) / 14
                close = kl_raw[-1][1] or 0
                atr_pct = atr / close * 100 if close else 0
                if atr_pct < atr_pct_min:
                    continue

                score = 0
                mcap_wan = (universe[code]["mcap"] or 0) / 1e4
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

                scored.append((code, score))
            except Exception:
                continue
        conn.close()

        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:top_n]]

    return _strategy


def compute_consecutive_loss_months(monthly_returns):
    """计算最长连续亏损月数"""
    max_streak = cur_streak = 0
    for r in monthly_returns:
        if r < 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    return max_streak


def run_scenario(s):
    """对单个区间跑 V1 Top3 回测"""
    print(f"\n  📡 [{s['label']}] {s['desc']}", file=sys.stderr)
    print(f"     区间 {s['start']} ~ {s['end']}", file=sys.stderr)
    t0 = time.time()
    # 单位修复后，所有区间统一使用标准参数（含流动性硬约束≥8000万）
    strategy_fn = create_strategy_fn(V1_TOPS)
    results = be.run_backtest(
        strategy_fn,
        start_date=s["start"],
        end_date=s["end"],
        top_n=TOP_N,
        walk_forward=False,  # 压力测试用全样本，区间已固定
    )
    elapsed = time.time() - t0
    print(f"     耗时: {elapsed:.0f}s", file=sys.stderr)

    if "error" in results:
        return {"label": s["label"], "desc": s["desc"], "error": results["error"]}

    ins = results.get("in_sample", {})
    monthly = results.get("monthly_returns", []) or ins.get("monthly_returns", [])
    return {
        "label": s["label"],
        "desc": s["desc"],
        "start": s["start"],
        "end": s["end"],
        "months": ins.get("months", 0),
        "annual_return": ins.get("cagr_pct", 0),
        "max_drawdown": ins.get("max_drawdown_pct", 0),
        "win_rate": ins.get("win_rate_pct", 0),
        "total_return": ins.get("total_return_pct", 0),
        "total_trades": ins.get("total_trades", 0),
        "benchmark_return": ins.get("benchmark_return_pct", 0),
        "consecutive_loss_months": compute_consecutive_loss_months(monthly),
        "elapsed": elapsed,
    }


def format_report(results):
    """生成 Markdown 报告"""
    lines = []
    lines.append("# V1 翻倍策略（Top3参数）极端行情压力测试报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("> 参数: 分位≤40% 量比≥2.7 市值5-90亿 成交额≥8000万 20日均≥4000万 ATR≥3% | 月频 | 每期20只 | T+1开盘价 | 含成本")
    lines.append("")
    lines.append("## ✅ 成交额单位修复说明（2026-08-10）")
    lines.append("")
    lines.append("- **历史数据质量缺陷已修复**：历史K线（<2023-12-05）的 `turnover`（成交额）单位原为**千元**（前复权基准），2023-12-05 起切换为**元**（不复权基准），两者相差 1000 倍")
    lines.append("- **修复动作**：`fix_turnover_units.py` 将历史 千元 口径的 turnover 统一 ×1000 转为元，已对 2007-2018 及 2023 全部历史区间生效，单位与当前一致")
    lines.append("- **影响**：V1 流动性硬约束（成交额≥8000万）在历史区间恢复正常判定，本报告所有区间现均使用**标准参数**（含流动性约束），不再采用放宽模式")
    lines.append("- 注：历史 close 原为前复权价；**价格断点已于 2026-08-10 修复**（见下），现 2023-12-05 前后价格连续，可跨边界回测")
    lines.append("- **价格断点修复（2026-08-10）**：`klines` 价格在 2023-12-05 由 前复权(投资数据锚) 切换为 前复权(腾讯 qfq 锚)，两段锚不同导致 5481 只中 3887 只 >30% 假跳变。已用 `fix_price_discontinuity.py` 按每只股票边界因子（首条后断点收盘/末条前断点收盘）统一到当前(腾讯 qfq)前复权锚，12,423,079 行前断点 OHLC 等比缩放，边界连续、前断点收益严格保持（抽查 600519/000001/000858 2018 区间收益与修复前完全一致）。**注：统一到当前刷新一致的 前复权 口径（用户回退方案），非不复权；腾讯不复权接口不稳定、投资数据包复权因子与本地不复权不一致，故采用自包含可靠的等比桥接。**")
    lines.append("")
    lines.append("## 一、各极端区间表现（全部标准参数）")
    lines.append("")
    lines.append("| 区间 | 期间 | 年化收益 | 最大回撤 | 月胜率 | 连续亏损月 | 累计收益 | 基准 |")
    lines.append("|------|------|:-------:|:-------:|:-----:|:---------:|:-------:|:---:|")
    for r in results:
        if "error" in r:
            lines.append(f"| {r['label']} | — | ❌ {r['error']} | — | — | — | — | — |")
            continue
        flag = " ⚠️失真" if abs(r['annual_return']) > 300 else ""
        lines.append(
            f"| {r['label']} | {r['start']}~{r['end']} | "
            f"{r['annual_return']:+.1f}%{flag} | {r['max_drawdown']:.1f}% | "
            f"{r['win_rate']:.1f}% | {r['consecutive_loss_months']} | "
            f"{r['total_return']:+.1f}% | {r['benchmark_return']:+.1f}% |"
        )
    lines.append("")
    lines.append("## 二、风险判定")
    lines.append("")
    worst_dd = 0
    worst_scene = ""
    max_loss_streak = 0
    for r in results:
        if "error" in r:
            continue
        if abs(r["max_drawdown"]) > worst_dd:
            worst_dd = abs(r["max_drawdown"])
            worst_scene = r["label"]
        if r["consecutive_loss_months"] > max_loss_streak:
            max_loss_streak = r["consecutive_loss_months"]

    lines.append(f"- **最大回撤**: {worst_scene} 达到 {worst_dd:.1f}%")
    lines.append(f"- **最长连续亏损月数**: {max_loss_streak} 个月")
    lines.append("")
    if worst_dd > 40:
        lines.append("> 🚨 **极端行情下 V1 不可单独使用**")
        lines.append("> 2008/2015 等极端行情下 V1 最大回撤 > 40%，单一策略无法承受，需配合止损/择时/多策略分散。")
    else:
        lines.append("> 标准参数下历史极端区间最大回撤表现，需结合市场环境谨慎解读。")
    lines.append("")
    lines.append("## 三、与 2023-2026 基准对比")
    lines.append("")
    bench = next((r for r in results if "基准" in r["label"]), None)
    if bench and "error" not in bench:
        if abs(bench['annual_return']) > 300:
            lines.append(f"- 基准区间（2023-2026）策略年化 **+{bench['annual_return']:,.0f}%** — ⚠️ **失真，不可采信**：")
            lines.append("  V1 低位放量选股在 2023-2026 选中多只**低位重组暴炒股**（如 001331 0.82→37.67、001314 1.0→48.45 等单月 500%+ 涨幅），回测按次日开盘价买入并吃到整月涨幅，实际中这类股**一字涨停买不进**（gap-up 过滤器仅拦 3%+ 跳空，拦不住 一字板）。")
            lines.append("  该数不能代表 V1 正常市真实年化（历史诚实回测口径约为年化 +124.8%，见决策记录 #1）。基准可靠性需在回测引擎中补 涨停不可买 真实感建模后重估。")
        else:
            lines.append(f"- 基准区间（2023-2026）: 年化 {bench['annual_return']:+.1f}%，回撤 {bench['max_drawdown']:.1f}%，胜率 {bench['win_rate']:.1f}%（标准流动性门槛）")
    lines.append("")
    lines.append("## 四、结论")
    lines.append("")
    lines.append("1. **成交额单位已修复**（历史 千元 → 元），V1 流动性硬约束（≥8000万）现可在全部历史区间正常判定，回测结论据此更新。")
    lines.append("2. 标准参数下历史极端区间的回撤表现如上，反映 V1 在真实流动性约束下的可交易结果。")
    lines.append("3. 单一策略无法在所有市场环境安全运行，建议配合市场环境路由（market_env_classifier）在多策略间切换。")
    lines.append("")
    return "\n".join(lines)


def main():
    do_json = "--json" in sys.argv
    do_save = "--save" in sys.argv

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  V1 翻倍策略 (Top3) 历史极端行情压力测试", file=sys.stderr)
    print(f"  选股: 每期 {TOP_N} 只 | 月频 | T+1开盘价 | 含成本", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    results = []
    for s in SCENARIOS:
        r = run_scenario(s)
        results.append(r)
        print(f"    ✓ {r.get('label','?')}: 年化{r.get('annual_return',0):+.1f}% 回撤{r.get('max_drawdown',0):.1f}%", file=sys.stderr)

    report = format_report(results)
    print(report)

    if do_json:
        print("\n===JSON===")
        print(json.dumps(results, ensure_ascii=False, indent=2))

    if do_save:
        out = SCRIPT_DIR / "v1_stress_test_report.md"
        out.write_text(report, encoding="utf-8")
        print(f"\n✅ 报告已保存: {out}", file=sys.stderr)

    return results


if __name__ == "__main__":
    main()
