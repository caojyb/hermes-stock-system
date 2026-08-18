#!/usr/bin/env python3
"""
可视化仪表盘 — 生成净值曲线图 + 持仓盈亏分布图
由 simulation_weekly.py 在周报末尾调用
"""
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # 无头模式
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── 中文配置 ──────────────────────────────────────────────
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'SimHei', 'WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ── 路径 ──────────────────────────────────────────────────
BASE = Path('/home/caojy/.hermes/scripts/cron')
SIM_DB = BASE / 'simulation.db'
CHART_DIR = BASE / 'charts'
CHART_DIR.mkdir(parents=True, exist_ok=True)

CSI300_SYMBOL = 'sh000300'  # 沪深300


def fetch_csi300(snapshot_dates):
    """获取沪深300在 snapshot 日期范围内的收盘价"""
    if not snapshot_dates:
        return {}
    import akshare as ak
    try:
        df = ak.stock_zh_index_daily(symbol=CSI300_SYMBOL)
        df['date'] = df['date'].astype(str)
        # 只保留 snapshot 范围内的数据
        start = min(snapshot_dates)
        end = max(snapshot_dates)
        mask = (df['date'] >= start) & (df['date'] <= end)
        df = df[mask].copy()
        return dict(zip(df['date'], df['close']))
    except Exception as e:
        print(f"  ⚠ 获取沪深300数据失败: {e}", file=sys.stderr)
        return {}


def plot_net_value(ax, snapshots, csi300_close):
    """
    净值曲线图（子图）
    snapshots: list of (date_str, total_value, total_return_pct)
    """
    dates = [s[0] for s in snapshots]
    total_values = [s[1] for s in snapshots]
    returns = [s[2] for s in snapshots]

    x = range(len(dates))

    # ── 左轴: 总资产 ──
    color1 = '#2196F3'
    ax.plot(x, total_values, color=color1, marker='o', linewidth=2, label='组合总资产')
    ax.fill_between(x, total_values, alpha=0.1, color=color1)
    ax.set_ylabel('总资产 (元)', color=color1, fontsize=11)
    ax.tick_params(axis='y', labelcolor=color1)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:,.0f}'))

    # ── 右轴: 收益率 + 基准 ──
    ax2 = ax.twinx()
    color2 = '#FF9800'
    ax2.plot(x, returns, color=color2, marker='s', linewidth=2, label='组合收益率%')
    # 基准
    if csi300_close:
        base_dates = [d for d in dates if d in csi300_close]
        if base_dates:
            first_close = csi300_close[base_dates[0]]
            base_returns = [(csi300_close[d] / first_close - 1) * 100 for d in base_dates]
            base_x = [dates.index(d) for d in base_dates]
            ax2.plot(base_x, base_returns, color='#4CAF50', linestyle='--', linewidth=1.5,
                     label='沪深300收益率%')
    ax2.set_ylabel('收益率 (%)', color=color2, fontsize=11)
    ax2.tick_params(axis='y', labelcolor=color2)

    # ── X轴 ──
    n = len(dates)
    if n <= 10:
        ticks = list(range(n))
        labels = dates
    else:
        step = max(1, n // 10)
        ticks = list(range(0, n, step))
        labels = [dates[i] for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=8)
    ax.set_xlabel('日期', fontsize=10)

    # 合并图例
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9)

    ax.set_title('组合净值曲线', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3)


def plot_holdings_pnl(ax, holdings):
    """
    持仓盈亏分布图（子图）— 饼图 + 柱状图
    holdings: list of (code, name, buy_price, buy_shares, profit_pct, profit_amount)
    """
    if not holdings:
        ax.text(0.5, 0.5, '当前无持仓', ha='center', va='center', fontsize=14, transform=ax.transAxes)
        ax.set_title('持仓盈亏分布', fontsize=13, fontweight='bold')
        return

    names = [h[1] or h[0] for h in holdings]
    # profit_pct / profit_amount might be None for holdings not yet sold
    pct_values = []
    valid_idx = []
    for i, h in enumerate(holdings):
        pct = h[4]  # profit_pct
        if pct is not None:
            pct_values.append(pct)
            valid_idx.append(i)
        else:
            # 未平仓的持仓：用当前盈亏 = 0（因为没有卖出，无法计算盈亏）
            pct_values.append(0)
            valid_idx.append(i)

    # 按盈亏比例排序
    pairs = sorted(zip(names, pct_values), key=lambda x: x[1], reverse=True)
    names = [p[0] for p in pairs]
    pct_values = [p[1] for p in pairs]

    colors = ['#f44336' if v < 0 else '#4CAF50' for v in pct_values]

    # ── 柱状图 ──
    bars = ax.bar(range(len(names)), pct_values, color=colors, edgecolor='white', linewidth=0.5)
    ax.axhline(y=0, color='gray', linewidth=0.8)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha='right', fontsize=9)
    ax.set_ylabel('盈亏比例 (%)', fontsize=10)
    ax.set_title('持仓盈亏分布', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # 在柱上标注数值
    for bar, v in zip(bars, pct_values):
        if v != 0:
            y_pos = bar.get_height() + (0.5 if v >= 0 else -1.5)
            ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                    f'{v:+.1f}%', ha='center', va='bottom' if v >= 0 else 'top',
                    fontsize=8, fontweight='bold',
                    color='#f44336' if v < 0 else '#4CAF50')


def main():
    today = date.today().isoformat()
    print(f"📊 生成可视化仪表盘 ({today})")

    if not SIM_DB.exists():
        print(f"  ⚠ 数据库不存在: {SIM_DB}")
        return

    conn = sqlite3.connect(str(SIM_DB))
    cur = conn.cursor()

    # ── 1. 读取净值快照 ──
    cur.execute("SELECT date, total_value, total_return_pct FROM portfolio_snapshots ORDER BY date, id")
    snapshots = cur.fetchall()
    if not snapshots:
        print("  ⚠ 无净值快照数据")
        conn.close()
        return

    # 按日期去重（保留最后一条）
    seen = {}
    for s in snapshots:
        seen[s[0]] = s
    snapshots = sorted(seen.values(), key=lambda x: x[0])

    print(f"  ✓ 读取 {len(snapshots)} 个净值快照")

    # ── 2. 读取当前持仓 ──
    cur.execute("""
        SELECT code, name, buy_price, buy_shares, profit_pct, profit_amount
        FROM trades WHERE status IN ('持有','部分止盈')
    """)
    holdings = cur.fetchall()
    print(f"  ✓ 当前持仓: {len(holdings)} 笔")

    conn.close()

    # ── 3. 获取沪深300基准 ──
    snapshot_dates = [s[0] for s in snapshots]
    csi300_close = fetch_csi300(snapshot_dates)
    if csi300_close:
        print(f"  ✓ 沪深300数据: {len(csi300_close)} 天")
    else:
        print("  ⚠ 无沪深300基准数据")

    # ── 4. 绘图 ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), dpi=120)
    fig.suptitle(f'模拟组合仪表盘 — {today}', fontsize=15, fontweight='bold', y=0.98)

    plot_net_value(ax1, snapshots, csi300_close)
    plot_holdings_pnl(ax2, holdings)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # ── 5. 保存 ──
    output_path = CHART_DIR / f'portfolio_{today}.png'
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✅ 图表已保存: {output_path}")


if __name__ == '__main__':
    main()