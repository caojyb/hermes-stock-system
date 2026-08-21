#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-G1: Regime×V1 历史 Market Regime 的 Point-in-Time 重建（研究模块，物理隔离在 research/）。

公式与生产 market_env_classifier.py 完全一致：
    regime_score = trend*0.30 + volatility*0.25 + liquidity*0.25 + style*0.20
维度基于 000300(沪深300) 与 000905(中证500) 指数K线。

关键性质：
    1) 严格 PIT —— 对每个 as_of_date T，只用 date<=T 的指数K线计算，禁止未来数据。
    2) 输出每天 regime_label / regime_score / 各维度得分 / regime_version。
    3) 数据不足(MA20/60/120 需至少120根、ATR 需250根、风格/量能不足)时返回 UNKNOWN，绝不猜测。
    4) 处理 000300 指数只到 2026-07-24 的缺口 —— 该日期之后无新的 000300 数据，
       此时 regime 标记为 UNKNOWN（不做"用旧数据充当当前"的欺骗）。

数据库路径：from stock_db_paths import get_db_path，读取 get_db_path('market_cache')。

独立运行：
    python3 -m research.regime_pit --start 2005-01-01 --end 2024-12-31
输出 CSV 到 research/artifacts/regime_v1/regime_daily.csv

严禁写入生产 trades/execution/outcomes/snapshots 等表。
"""
import os
import sys
import sqlite3
import argparse
import csv
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
                                'skills', 'stock', 'stock-expert'))
from stock_db_paths import get_db_path

LARGE_INDEX = '000300'   # 沪深300
MID_INDEX = '000905'     # 中证500

REGIME_VERSION = 'v1'
UNKNOWN = 'UNKNOWN'


# ═══════════════ 基础指标（与生产一致） ═══════════════

def calc_ma(closes, period):
    """closes: 按时间升序的收盘价列表。返回最后 period 根的均值；不足返回 None。"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_atr(klines, period=20):
    """klines: 升序 [(date, close, high, low, volume), ...]。返回最后 period 根的 ATR；不足返回 None。"""
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i][2] or 0, klines[i][3] or 0, klines[i - 1][1] or 0
        if h and l and pc:
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _kl_restrict(klines, limit):
    """取升序列表最后 limit 根。"""
    return klines[-limit:] if limit is not None else klines


# ═══════════════ PIT 单日分类 ═══════════════

def _classify_window(large_kl, small_kl, as_of):
    """
    对 as_of_date=T 的 (<=T) 数据窗口做一次分类，复刻生产公式。
    large_kl / small_kl：date<=T 的升序K线。
    返回 dict；任何维度数据不足返回 UNKNOWN 语义（regime_label='UNKNOWN'）。
    """
    def unknown(reason):
        return {
            'date': as_of,
            'regime_label': UNKNOWN,
            'regime_score': None,
            'regime_version': REGIME_VERSION,
            'reason': reason,
            'dimensions': {
                'trend': None, 'volatility': None, 'liquidity': None, 'style': None,
            },
        }

    # ── 趋势 trend (30%)：基于 000300，MA20/60/120，需 >=120 根 ──
    if len(large_kl) < 120:
        return unknown(f"trend data insufficient: {len(large_kl)}")
    kl_trend = _kl_restrict(large_kl, 500)
    closes_t = [r[1] for r in kl_trend]
    ma20 = calc_ma(closes_t, 20)
    ma60 = calc_ma(closes_t, 60)
    ma120 = calc_ma(closes_t, 120)
    if None in (ma20, ma60, ma120):
        return unknown("trend MA insufficient")
    if ma20 > ma60 > ma120:
        trend_score = 100
        trend_label = "多头排列"
    elif ma20 < ma60 < ma120:
        trend_score = 0
        trend_label = "空头排列"
    else:
        trend_score = 50
        trend_label = "交织状态"
    if ma20 > ma60 and trend_score == 50:
        trend_score = 65
    elif ma60 > ma20 and trend_score == 50:
        trend_score = 35

    # ── 波动 volatility (25%)：ATR% 历史分位，需 >=250 根 ──
    if len(large_kl) < 250:
        return unknown(f"volatility data insufficient: {len(large_kl)}")
    kl_atr = _kl_restrict(large_kl, 800)
    current_atr = calc_atr(kl_atr, 20)
    current_close = kl_atr[-1][1]
    current_atr_pct = (current_atr / current_close * 100) if current_close and current_atr else 0
    hist_atr_pcts = []
    for i in range(250, len(kl_atr) - 20):
        atr = calc_atr(kl_atr[i - 20:i + 20], 20)
        close = kl_atr[i][1]
        if atr and close:
            hist_atr_pcts.append(atr / close * 100)
    if hist_atr_pcts:
        sorted_hist = sorted(hist_atr_pcts)
        vol_percentile = sum(1 for v in sorted_hist if v < current_atr_pct) / len(sorted_hist) * 100
    else:
        vol_percentile = 50
    vol_score = vol_percentile

    # ── 量能 liquidity (25%)：VOL20/VOL120 比值，需 >=125 根 ──
    if len(large_kl) < 125:
        return unknown(f"liquidity data insufficient: {len(large_kl)}")
    vol_20 = sum((r[4] or 0) for r in large_kl[-20:]) / 20
    vol_120 = sum((r[4] or 0) for r in large_kl[-120:]) / 120
    liq_ratio = vol_20 / vol_120 if vol_120 > 0 else 1
    if liq_ratio > 1.2:
        liq_score = 80
        liq_label = "量能放大"
    elif liq_ratio > 0.8:
        liq_score = 50
        liq_label = "量能正常"
    else:
        liq_score = 20
        liq_label = "量能萎缩"
    if liq_ratio > 1.5:
        liq_score = 100
    elif liq_ratio < 0.5:
        liq_score = 0

    # ── 风格 style (20%)：大盘(000300) vs 小盘(000905) 20日涨幅比，各需 >=20 根 ──
    if len(small_kl) < 20 or len(large_kl) < 20:
        return unknown(f"style data insufficient: small={len(small_kl)} large={len(large_kl)}")
    large_ret = (large_kl[-1][1] - large_kl[-21][1]) / large_kl[-21][1] * 100
    small_ret = (small_kl[-1][1] - small_kl[-21][1]) / small_kl[-21][1] * 100
    style_ratio = large_ret / small_ret if small_ret != 0 else 1
    if style_ratio > 1.1:
        style_score = 80
        style_label = "大盘占优"
    elif style_ratio < 0.9:
        style_score = 20
        style_label = "小盘占优"
    else:
        style_score = 50
        style_label = "风格均衡"

    # ── 综合 ──
    total = trend_score * 0.30 + vol_score * 0.25 + liq_score * 0.25 + style_score * 0.20
    if total > 70 and vol_percentile < 50:
        env_label = "🟢强趋势"
    elif vol_percentile > 70:
        env_label = "🔴高波动"
    elif liq_score < 30:
        env_label = "⚫低量能"
    else:
        env_label = "🟡震荡市"

    return {
        'date': as_of,
        'regime_label': env_label,
        'regime_score': round(total, 2),
        'regime_version': REGIME_VERSION,
        'reason': None,
        'dimensions': {
            'trend': {'score': trend_score, 'label': trend_label,
                      'ma20': round(ma20, 2), 'ma60': round(ma60, 2), 'ma120': round(ma120, 2)},
            'volatility': {'score': round(vol_score, 1), 'label': f"分位{round(vol_percentile, 0):.0f}%",
                           'atr_pct': round(current_atr_pct, 2)},
            'liquidity': {'score': liq_score, 'label': liq_label, 'ratio': round(liq_ratio, 2)},
            'style': {'score': style_score, 'label': style_label, 'ratio': round(style_ratio, 2)},
        },
    }


class RegimePIT:
    """持库并做 PIT 重建的入口。"""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or get_db_path('market_cache'))
        self._conn = None
        self._large = None   # 升序 [(date, close, high, low, volume)]
        self._small = None
        self._large_max_date = None

    def _connect(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _load(self):
        """一次性载入 000300/000905 全部K线，升序。"""
        if self._large is not None:
            return
        conn = self._connect()
        q = "SELECT date, close, high, low, volume FROM klines WHERE code=? ORDER BY date"
        self._large = [tuple(r) for r in conn.execute(q, (LARGE_INDEX,))]
        self._small = [tuple(r) for r in conn.execute(q, (MID_INDEX,))]
        self._large_max_date = self._large[-1][0] if self._large else None

    def _sub_window(self, rows, as_of):
        """取 date<=as_of 的升序子窗口。rows 已升序，用二分快速截断。"""
        lo, hi = 0, len(rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if rows[mid][0] <= as_of:
                lo = mid + 1
            else:
                hi = mid
        return rows[:lo]

    def classify_pit(self, as_of_date):
        """
        对单个 as_of_date=T 做 PIT regime 分类（只使用 date<=T 数据）。
        测试接口兼容 test_regime_v1_research.test_06_pit_regime。
        """
        self._load()
        as_of = str(as_of_date)
        large = self._sub_window(self._large, as_of)
        small = self._sub_window(self._small, as_of)
        # 000300 缺口处理：as_of 在 000300 最后日期之后，无新鲜 000300 数据 -> UNKNOWN
        if self._large_max_date is not None and as_of > self._large_max_date:
            return {
                'date': as_of,
                'regime_label': UNKNOWN,
                'regime_score': None,
                'regime_version': REGIME_VERSION,
                'reason': f"000300 data ends at {self._large_max_date}; no fresh large-index data",
                'dimensions': {'trend': None, 'volatility': None, 'liquidity': None, 'style': None},
            }
        return _classify_window(large, small, as_of)

    def run_range(self, start, end):
        """
        对 [start, end] 内每个 000300 交易日逐日 PIT 重建。
        返回结果 dict 列表（升序）。
        """
        self._load()
        results = []
        for row in self._large:
            d = row[0]
            if d < start or d > end:
                continue
            results.append(self.classify_pit(d))
        return results

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ═══════════════ CSV 输出 ═══════════════

def _flatten(r):
    dims = r.get('dimensions') or {}
    t = dims.get('trend') or {}
    v = dims.get('volatility') or {}
    lq = dims.get('liquidity') or {}
    s = dims.get('style') or {}
    return {
        'date': r['date'],
        'regime_label': r['regime_label'],
        'regime_score': r['regime_score'],
        'regime_version': r['regime_version'],
        'reason': r.get('reason') or '',
        'trend_score': t.get('score'),
        'trend_label': t.get('label'),
        'volatility_score': v.get('score'),
        'volatility_label': v.get('label'),
        'liquidity_score': lq.get('score'),
        'liquidity_label': lq.get('label'),
        'style_score': s.get('score'),
        'style_label': s.get('label'),
    }


def write_csv(results, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = ['date', 'regime_label', 'regime_score', 'regime_version', 'reason',
            'trend_score', 'trend_label', 'volatility_score', 'volatility_label',
            'liquidity_score', 'liquidity_label', 'style_score', 'style_label']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow(_flatten(r))
    return path


# ═══════════════ CLI ═══════════════

def main():
    ap = argparse.ArgumentParser(description='PIT Market Regime 重建')
    ap.add_argument('--start', default='2005-01-01')
    ap.add_argument('--end', default='2024-12-31')
    ap.add_argument('--out', default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'artifacts', 'regime_v1', 'regime_daily.csv'))
    ap.add_argument('--print', action='store_true', help='打印每一行')
    args = ap.parse_args()

    rp = RegimePIT()
    try:
        results = rp.run_range(args.start, args.end)
    finally:
        rp.close()

    path = write_csv(results, args.out)
    print(f"[regime_pit] {len(results)} days -> {path}")

    if args.print:
        for r in results:
            print(_flatten(r))


if __name__ == '__main__':
    main()
