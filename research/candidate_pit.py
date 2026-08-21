#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/candidate_pit.py — Phase 8-G1: 历史 V1 候选的 Point-in-Time filter 重建

在历史任意时点 T，用「仅 date<=T 的 klines」重建 V1 Top3 硬过滤条件结果，
输出每只股票每个候选日（每周最后交易日）的 filter trace。

V1 Top3 硬过滤（来自 scan_doubling_potential.py / stock_strategy_config.py v1_double）:
  - price_pos  价格分位 <= 40%            （500 交易日窗口，min/max close 分位）
  - vol_ratio  量比 >= 2.7                （5日均量 / 20日均量，volume 手）
  - market_cap 市值 5 ~ 90 亿              （PIT 重建：股本事件 × 当日收盘价）
  - amount_1d  1日成交额 >= 8000万         （turnover 元 → 万元）
  - amount_20d 20日均成交额 >= 4000万      （turnover 元 → 万元）
  - atr_pct    ATR >= 3%                  （14日 ATR / close）

时间 cadence：weekly（V1 生产周日 17:20 扫描，候选日 = 每周最后交易日）。

market_cap 质量：
  - PIT_SAFE     -> market_cap = 亿元数值，参与 5-90 亿判断
  - APPROXIMATE  -> market_cap = 'APPROXIMATE'，fail-safe：final_candidate = UNKNOWN
  - UNKNOWN      -> market_cap = 'UNKNOWN'，final_candidate = UNKNOWN
  （strict PIT 下 APPROXIMATE 不可用于 PASS，故归 UNKNOWN）

用法（在 /home/caojy/.hermes/scripts/cron/ 下）：
  python3 -m research.candidate_pit --start 2005-01-01 --end 2024-12-31 --limit 200
  python3 -m research.candidate_pit --symbols 000001,002594,600007 \
          --start 2024-01-01 --end 2024-01-31 --fixtures   # 离线小范围测试

不修改生产代码；输出写入 research/artifacts/regime_v1/candidate_filter_trace.csv
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 允许 import 生产模块（只读，不修改） ──────────────────────────────────
CRON_DIR = Path(__file__).resolve().parent.parent          # .../cron
RESEARCH_DIR = Path(__file__).resolve().parent             # .../cron/research
ARTIFACTS_DIR = RESEARCH_DIR / 'artifacts' / 'regime_v1'

SKILL_DIR = Path('/home/caojy/.hermes/skills/stock/stock-expert')
for _p in (str(CRON_DIR), str(SKILL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from stock_strategy_config import DEFAULT_STRATEGY, get_strategy_params  # noqa: E402
from historical_share_layer import (  # noqa: E402
    get_share_layer,
    get_market_cap,
    MarketCapQuality,
)

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

PARAMS = get_strategy_params(DEFAULT_STRATEGY)  # v1_double Top3 参数（生产唯一权威来源）
PRICE_POS_MAX = float(PARAMS['price_pos_max'])      # 40
VOL_RATIO_MIN = float(PARAMS['vol_ratio_min'])      # 2.7
MCAP_MIN_YI = float(PARAMS['mcap_min'])             # 5
MCAP_MAX_YI = float(PARAMS['mcap_max'])             # 90
AMOUNT_1D_MIN_WAN = float(PARAMS['turnover_min'])   # 8000（万元）
AMOUNT_20D_MIN_WAN = float(PARAMS['avg_amount_20d'])  # 4000（万元）
ATR_PCT_MIN = float(PARAMS['atr_pct_min'])          # 3
MIN_ROWS = 60  # 与生产 scan() 的 data_insufficient 阈值一致


def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def weekly_candidate_dates(dates: list[date], start: date, end: date) -> list[date]:
    """每个 ISO 周取最后交易日作为候选日，并裁剪到 [start, end]。"""
    out: list[date] = []
    cur_key = None
    cur_last: Optional[date] = None
    for d in sorted(dates):
        key = (d.isocalendar()[0], d.isocalendar()[1])
        if cur_key != key:
            if cur_key is not None and cur_last is not None:
                out.append(cur_last)
            cur_key = key
        cur_last = d
    if cur_key is not None and cur_last is not None:
        out.append(cur_last)
    return [d for d in out if start <= d <= end]


def load_universe(limit: Optional[int], symbols: Optional[list[str]]) -> list[str]:
    """候选股票池。默认排除 688/787（与生产一致）；limit 限制数量。"""
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    if symbols:
        codes = symbols
    else:
        cur.execute(
            "SELECT code FROM stocks "
            "WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' "
            "AND (is_st IS NULL OR is_st = 0) "
            "ORDER BY code"
        )
        codes = [r[0] for r in cur.fetchall()]
    con.close()
    if limit and not symbols:
        codes = codes[:limit]
    return codes


def load_klines(symbol: str) -> pd.DataFrame:
    """加载单只股票全部 klines（date 升序）。列：date, close, volume, turnover, high, low。"""
    con = sqlite3.connect(str(DB))
    df = pd.read_sql_query(
        "SELECT date, close, volume, turnover, high, low FROM klines WHERE code=? ORDER BY date ASC",
        con, params=(symbol,),
    )
    con.close()
    df['date'] = pd.to_datetime(df['date']).dt.date
    return df


def compute_metrics(window: pd.DataFrame) -> dict:
    """对 date<=T 的最近 500 根 K 线计算 V1 各指标（与生产 scan() 公式一致）。

    返回 dict，字段为 float 或 None（数据不足时）。
    """
    rows = window.tail(500)
    closes = rows['close'].dropna()
    n = len(rows)
    if n < MIN_ROWS or len(closes) < MIN_ROWS:
        # 数据不足：无法判定，price/vol/atr 置 None
        return {
            'price_pos': None, 'vol_ratio': None,
            'amount_1d': None, 'amount_20d': None, 'atr_pct': None,
            'data_insufficient': True,
        }

    # 1日成交额（元 → 万元）
    amount_1d = (rows['turnover'].iloc[-1] or 0) / 1e4

    # 20日均成交额：生产用最近 25 根的前 20 根（排除最近 5 日）
    recent_ts = (rows['turnover'].fillna(0).iloc[-25:]).tolist()
    amount_20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1) / 1e4

    # 价格分位（500 日窗口，close min/max）
    lo, hi = closes.min(), closes.max()
    price_pos = ((closes.iloc[-1] - lo) / (hi - lo) * 100) if hi != lo else None

    # 量比 = 5日均量 / 20日均量（volume）
    vol = rows['volume'].fillna(0)
    vol_5 = vol.iloc[-5:].mean()
    vol_20 = vol.iloc[-25:-5].mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else None

    # ATR（14日），trs 用 high/low/prev_close
    trs = []
    h = rows['high'].tolist()
    l = rows['low'].tolist()
    c = rows['close'].tolist()
    for i in range(1, len(rows)):
        hi_, lo_, pc = h[i] or 0, l[i] or 0, c[i - 1] or 0
        if hi_ and lo_ and pc:
            trs.append(max(hi_ - lo_, abs(hi_ - pc), abs(lo_ - pc)))
    if len(trs) < 14:
        atr_pct = None
    else:
        atr = sum(trs[-14:]) / 14
        close = c[-1] or 0
        atr_pct = atr / close * 100 if close else None

    return {
        'price_pos': price_pos, 'vol_ratio': vol_ratio,
        'amount_1d': amount_1d, 'amount_20d': amount_20d, 'atr_pct': atr_pct,
        'data_insufficient': False,
    }


def mcap_state(symbol: str, as_of: date) -> tuple[str, Optional[float]]:
    """PIT 市值。返回 (kind, value_yi)：
      kind in {'OK','APPROXIMATE','UNKNOWN'}；value 仅 kind=='OK' 时有值（亿元）。
    """
    mc = get_market_cap()
    res = mc.get_market_cap(symbol, as_of)  # 传 datetime.date 对象
    q = res.quality
    if q == MarketCapQuality.PIT_SAFE and res.market_cap is not None:
        return ('OK', res.market_cap / 1e8)
    if q == MarketCapQuality.APPROXIMATE:
        return ('APPROXIMATE', None)
    return ('UNKNOWN', None)


def decide_final(metrics: dict, mcap: tuple[str, Optional[float]]) -> str:
    """PASS / FAIL / UNKNOWN 判定。"""
    # 数据不足 → 无法通过
    if metrics.get('data_insufficient'):
        return 'FAIL'
    checks = [
        metrics['price_pos'] is not None and metrics['price_pos'] <= PRICE_POS_MAX,
        metrics['vol_ratio'] is not None and metrics['vol_ratio'] >= VOL_RATIO_MIN,
        metrics['amount_1d'] is not None and metrics['amount_1d'] >= AMOUNT_1D_MIN_WAN,
        metrics['amount_20d'] is not None and metrics['amount_20d'] >= AMOUNT_20D_MIN_WAN,
        metrics['atr_pct'] is not None and metrics['atr_pct'] >= ATR_PCT_MIN,
    ]
    if not all(checks):
        return 'FAIL'
    kind, value = mcap
    if kind == 'OK':
        return 'PASS' if MCAP_MIN_YI <= value <= MCAP_MAX_YI else 'FAIL'
    return 'UNKNOWN'  # APPROXIMATE / UNKNOWN → fail-safe UNKNOWN


def market_cap_col(mcap: tuple[str, Optional[float]]):
    """trace 的 market_cap 列值：OK→亿元数值，APPROXIMATE/UNKNOWN→对应字符串。"""
    kind, value = mcap
    if kind == 'OK' and value is not None:
        return round(value, 2)
    return kind  # 'APPROXIMATE' or 'UNKNOWN'


def build_trace(symbol: str, start: date, end: date, use_fixtures: bool) -> pd.DataFrame:
    kdf = load_klines(symbol)
    if kdf.empty:
        return pd.DataFrame()
    cand_dates = weekly_candidate_dates(kdf['date'].tolist(), start, end)

    sl = get_share_layer()
    if use_fixtures:
        sl.load_symbols_from_fixtures([symbol])
    else:
        sl.load_symbol(symbol, start_date=start.strftime('%Y%m%d'), end_date=end.strftime('%Y%m%d'))

    rows = []
    dates = kdf['date'].tolist()
    # 预构建 searchsorted 定位
    import bisect
    sorted_dates = sorted(dates)
    for T in cand_dates:
        idx = bisect.bisect_right(sorted_dates, T)  # 所有 date<=T
        if idx == 0:
            continue
        window = kdf.iloc[:idx]
        metrics = compute_metrics(window)
        mcap = mcap_state(symbol, T)
        final = decide_final(metrics, mcap)
        rows.append({
            'symbol': symbol,
            'as_of_date': T.isoformat(),
            'price_pos': round(metrics['price_pos'], 2) if metrics['price_pos'] is not None else None,
            'vol_ratio': round(metrics['vol_ratio'], 2) if metrics['vol_ratio'] is not None else None,
            'amount_1d': round(metrics['amount_1d'], 2) if metrics['amount_1d'] is not None else None,
            'amount_20d': round(metrics['amount_20d'], 2) if metrics['amount_20d'] is not None else None,
            'atr_pct': round(metrics['atr_pct'], 2) if metrics['atr_pct'] is not None else None,
            'market_cap': market_cap_col(mcap),
            'final_candidate': final,
        })
    return pd.DataFrame(rows, columns=[
        'symbol', 'as_of_date', 'price_pos', 'vol_ratio', 'amount_1d',
        'amount_20d', 'atr_pct', 'market_cap', 'final_candidate',
    ])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='历史 V1 候选 PIT filter 重建')
    ap.add_argument('--start', default='2005-01-01', help='起始日期 YYYY-MM-DD')
    ap.add_argument('--end', default='2024-12-31', help='结束日期 YYYY-MM-DD')
    ap.add_argument('--limit', type=int, default=None, help='限制股票数量（便于测试）')
    ap.add_argument('--symbols', default=None, help='指定股票代码，逗号分隔（测试用）')
    ap.add_argument('--fixtures', action='store_true', help='从冻结 fixture 加载股本（离线测试）')
    ap.add_argument('--out', default=None, help='输出 CSV 路径（默认 research/artifacts/regime_v1/...）')
    args = ap.parse_args(argv)

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    symbols_arg = [s.strip() for s in args.symbols.split(',')] if args.symbols else None
    universe = load_universe(args.limit, symbols_arg)

    out_path = Path(args.out) if args.out else ARTIFACTS_DIR / 'candidate_filter_trace.csv'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f'[candidate_pit] start={start} end={end} symbols={len(universe)} '
          f'fixtures={args.fixtures}', file=sys.stderr)

    all_frames = []
    for i, sym in enumerate(universe, 1):
        try:
            df = build_trace(sym, start, end, use_fixtures=args.fixtures)
        except Exception as e:  # noqa: BLE001
            print(f'[WARN] {sym}: {e}', file=sys.stderr)
            continue
        if not df.empty:
            all_frames.append(df)
        if i % 20 == 0:
            print(f'  ... {i}/{len(universe)} symbols done', file=sys.stderr)

    if not all_frames:
        print('[candidate_pit] 无输出（无可用数据）', file=sys.stderr)
        return 1

    result = pd.concat(all_frames, ignore_index=True)
    result.to_csv(out_path, index=False, encoding='utf-8-sig')
    summary = result['final_candidate'].value_counts().to_dict()
    print(f'[candidate_pit] 写入 {out_path} 共 {len(result)} 行', file=sys.stderr)
    print(f'[candidate_pit] final_candidate 分布: {summary}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
