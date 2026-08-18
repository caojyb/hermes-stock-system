#!/usr/bin/env python3
"""
翻倍策略 V2 — 加入流动性硬约束的诚实回测
==========================================
流动性约束：
1. 信号日成交额 < 5000万 → 跳过（小盘股流动性差，实盘无法成交）
2. 近20日均成交额 < 3000万 → 跳过
3. 以上两项都是硬拒绝，不再是评分加分项

用法: python3 backtest_liquidity.py
"""
import os, sys, json, math, sqlite3, calendar
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / ".." / ".." / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"))

import backtest_engine as be

MARKET_DB = be.MARKET_DB

# ── 流动性参数 ──
MIN_TURNOVER_1D = 50_000_000    # 信号日成交额 >= 5000万
MIN_TURNOVER_20D = 30_000_000   # 近20日均成交额 >= 3000万

def create_strategy_doubling_v2(price_pos_max=40, vol_ratio_min=1.3, atr_pct_min=3,
                                 mcap_min=5, mcap_max=50,
                                 min_turnover_1d=MIN_TURNOVER_1D,
                                 min_turnover_20d=MIN_TURNOVER_20D):
    """翻倍策略 V2 — 加入流动性硬约束"""

    def _strategy(snapshot_date, all_prices, top_n=30):
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
        skipped_liquidity = 0
        skipped_liquidity_20d = 0

        for code in list(universe.keys())[:2000]:
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

                # ── 流动性硬约束1: 信号日成交额 >= min_turnover_1d ──
                # kl_raw[-1][3] 是 turnover (元)
                latest_turnover = kl_raw[-1][3] or 0
                if latest_turnover < min_turnover_1d:
                    skipped_liquidity += 1
                    continue

                # ── 流动性硬约束2: 近20日均成交额 >= min_turnover_20d ──
                if len(kl_raw) >= 25:
                    recent_turnovers = [r[3] or 0 for r in kl_raw[-25:]]
                    avg_turnover_20d = sum(recent_turnovers[:-5]) / max(len(recent_turnovers[:-5]), 1)
                    if avg_turnover_20d < min_turnover_20d:
                        skipped_liquidity_20d += 1
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

                # 综合评分（保留）
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

    _strategy.__name__ = f"doubling_v2_liquidity"
    _strategy.__doc__ = f"翻倍策略 V2 (流动性硬约束: 日成交额>={min_turnover_1d/1e8:.1f}亿, 20日均>={min_turnover_20d/1e8:.2f}亿)"
    return _strategy


def main():
    print(f"\n{'='*60}")
    print(f"  翻倍策略 V2 — 加入流动性硬约束的诚实回测")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"\n📊 流动性约束:")
    print(f"   - 信号日成交额 >= {MIN_TURNOVER_1D/1e8:.1f}亿")
    print(f"   - 近20日均成交额 >= {MIN_TURNOVER_20D/1e8:.2f}亿")
    print(f"\n📡 启动 Walk-Forward 回测...")

    # 创建 V2 策略
    strategy_v2 = create_strategy_doubling_v2(
        price_pos_max=40, vol_ratio_min=1.3, atr_pct_min=3,
        mcap_min=5, mcap_max=50,
        min_turnover_1d=MIN_TURNOVER_1D,
        min_turnover_20d=MIN_TURNOVER_20D
    )

    # 运行 Walk-Forward 回测（参数同之前）
    results = be.run_backtest(
        strategy_v2,
        start_date="2023-01",
        end_date="2026-07",
        top_n=20,
        walk_forward=True,
        walk_window=24,
        walk_step=12
    )

    # 输出结果
    print(f"\n{'='*60}")
    print(f"  回测结果")
    print(f"{'='*60}")

    if "error" in results:
        print(f"\n❌ 错误: {results['error']}")
        return results

    if "walk_forward" in results:
        wf = results["walk_forward"]
        print(f"\n  Walk-Forward 测试集表现:")
        print(f"  期间: {wf.get('start_date', '?')} ~ {wf.get('end_date', '?')} ({wf.get('months', '?')}个月)")
        print(f"  累计收益: {wf.get('total_return_pct', '?'):>8}%")
        print(f"  年化收益: {wf.get('cagr_pct', '?'):>8}%")
        print(f"  最大回撤: {wf.get('max_drawdown_pct', '?'):>8}%")
        print(f"  夏普比率: {wf.get('sharpe_ratio', '?'):>8}")
        print(f"  月胜率:   {wf.get('win_rate_pct', '?'):>8}%")
        print(f"  盈亏比:   {wf.get('profit_loss_ratio', '?'):>8}")
        print(f"  卡玛比率: {wf.get('calmar_ratio', '?'):>8}")
        print(f"  基准收益: {wf.get('benchmark_return_pct', '?'):>8}%")
        print(f"  超额收益: {wf.get('alpha_pct', '?'):>8}%")
        print(f"  Beta:     {wf.get('beta', '?'):>8}")
        print(f"  信息比率: {wf.get('information_ratio', '?'):>8}")
        if "gapup_fails" in wf:
            gapup = wf.get("gapup_fails", 0)
            total = wf.get("total_trades", 0)
            fail_pct = round(gapup / total * 100, 1) if total > 0 else 0
            print(f"  跳空高开无法买入: {gapup}/{total} ({fail_pct}%)")
        if "smart_filtered" in wf:
            print(f"  聪明钱过滤器拦截: {wf.get('smart_filtered', 0)}次")

        # 打印分段详情
        print(f"\n  Walk-Forward 分段:")
        for seg in results.get("segments", []):
            print(f"    训练: {seg['train_start']}~{seg['train_end']} → 测试: {seg['test_start']}~{seg['test_end']} ({seg['test_months']}个月)")

    print(f"\n{'='*60}")
    print(f"  ✅ 回测完成")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    results = main()
