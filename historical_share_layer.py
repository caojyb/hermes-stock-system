"""
Phase 7.3-F：Historical Share Layer & Market Cap Reconstruction
独立、可审计、Point-in-Time 的历史股本层 + 历史市值重建。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


# ---------------------------------------------------------------------------
# Share Event Model
# ---------------------------------------------------------------------------
class ShareDateQuality(str, Enum):
    """股本变动日期可靠性。"""
    KNOWN_EFFECTIVE_DATE = 'KNOWN_EFFECTIVE_DATE'
    APPROXIMATE_EFFECTIVE_DATE = 'APPROXIMATE_EFFECTIVE_DATE'
    UNKNOWN_EFFECTIVE_DATE = 'UNKNOWN_EFFECTIVE_DATE'


class MarketCapQuality(str, Enum):
    """历史市值质量。"""
    PIT_SAFE = 'PIT_SAFE'
    APPROXIMATE = 'APPROXIMATE'
    UNKNOWN = 'UNKNOWN'
    BLOCKED = 'BLOCKED'


@dataclass(frozen=True)
class HistoricalShareEvent:
    """单条历史股本变动事件。"""
    symbol: str
    share_count: int  # 单位：股（统一转换为股）
    share_type: str = 'TOTAL_SHARES'
    effective_date: Optional[date] = None
    announcement_date: Optional[date] = None
    source: str = 'akshare.stock_share_change_cninfo'
    source_query_time: str = field(default_factory=lambda: datetime.utcnow().isoformat() + 'Z')
    source_record_id: Optional[str] = None
    raw_change_reason: Optional[str] = None
    date_quality: ShareDateQuality = ShareDateQuality.UNKNOWN_EFFECTIVE_DATE
    confidence: float = 0.0
    limitation_codes: list[str] = field(default_factory=list)
    feature_source: str = 'HISTORICAL_REPLAY'


@dataclass(frozen=True)
class HistoricalMarketCapResult:
    """历史市值查询结果。"""
    symbol: str
    as_of_date: date
    market_cap: Optional[float] = None
    share_count: Optional[int] = None
    share_effective_date: Optional[date] = None
    share_date_quality: Optional[ShareDateQuality] = None
    price: Optional[float] = None
    price_date: Optional[date] = None
    source: str = 'historical_replay'
    confidence: float = 0.0
    limitation_codes: list[str] = field(default_factory=list)
    quality: MarketCapQuality = MarketCapQuality.BLOCKED
    feature_source: str = 'HISTORICAL_REPLAY'


# ---------------------------------------------------------------------------
# Raw API → HistoricalShareEvent 转换
# ---------------------------------------------------------------------------
def _is_periodic_report(reason: str) -> bool:
    if not reason:
        return False
    r = reason.lower()
    return '定期报告' in r or 'annual' in r or 'quarterly' in r or 'report' in r


def _is_known_effective_event(reason: str) -> bool:
    if not reason:
        return False
    r = reason.lower()
    known_keywords = ['配股上市', '增发新股上市', '限售股份上市', 'A股上市',
                      '股份回购', '注销', '拆股', '合并']
    return any(k in reason for k in known_keywords)


def _make_record_id(row: pd.Series) -> str:
    """稳定业务去重键。"""
    parts = [
        str(row.get('证券代码', '')),
        str(row.get('变动日期', '')),
        str(row.get('变动原因', '')),
        str(row.get('总股本', '')),
    ]
    return '|'.join(parts)


def _parse_date(val) -> Optional[date]:
    if pd.isna(val):
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return pd.to_datetime(val).date()
        except Exception:
            return None
    return None


def convert_raw_events(df: pd.DataFrame, symbol: str) -> list[HistoricalShareEvent]:
    """把 akshare 原始返回转换成 HistoricalShareEvent 列表。"""
    events: list[HistoricalShareEvent] = []
    for _, row in df.iterrows():
        change_reason = str(row.get('变动原因', '')) if pd.notna(row.get('变动原因')) else ''
        effective_date = _parse_date(row.get('变动日期'))
        announcement_date = _parse_date(row.get('公告日期'))
        total_share_wan = float(row.get('总股本', 0)) if pd.notna(row.get('总股本')) else 0.0
        share_count = int(total_share_wan * 10_000)  # 万股 → 股

        if effective_date is None:
            date_quality = ShareDateQuality.UNKNOWN_EFFECTIVE_DATE
            confidence = 0.0
        elif _is_periodic_report(change_reason):
            date_quality = ShareDateQuality.APPROXIMATE_EFFECTIVE_DATE
            confidence = 0.5
        elif _is_known_effective_event(change_reason):
            date_quality = ShareDateQuality.KNOWN_EFFECTIVE_DATE
            confidence = 0.9
        else:
            date_quality = ShareDateQuality.UNKNOWN_EFFECTIVE_DATE
            confidence = 0.3

        limitations: list[str] = []
        if date_quality != ShareDateQuality.KNOWN_EFFECTIVE_DATE:
            limitations.append('SHARE_EFFECTIVE_DATE_UNKNOWN')

        events.append(HistoricalShareEvent(
            symbol=symbol,
            share_count=share_count,
            effective_date=effective_date,
            announcement_date=announcement_date,
            raw_change_reason=change_reason,
            date_quality=date_quality,
            confidence=confidence,
            limitation_codes=limitations,
            source_record_id=_make_record_id(row),
        ))
    return events


# ---------------------------------------------------------------------------
# Historical Share Layer
# ---------------------------------------------------------------------------
class HistoricalShareLayer:
    """独立、只读的历史股本层。"""

    def __init__(self) -> None:
        self._events: dict[str, list[HistoricalShareEvent]] = {}
        self._loaded_symbols: set[str] = set()

    def load_symbol(self, symbol: str, start_date: str = '20000101', end_date: str = '20241231') -> None:
        """从 akshare 加载单只股票的股本事件。"""
        import akshare as ak
        try:
            df = ak.stock_share_change_cninfo(symbol=symbol, start_date=start_date, end_date=end_date)
        except Exception as e:
            print(f'[WARN] {symbol}: akshare 加载失败: {e}', flush=True)
            self._events[symbol] = []
            self._loaded_symbols.add(symbol)
            return
        events = convert_raw_events(df, symbol)
        # 去重：按 source_record_id
        seen: set[str] = set()
        deduped: list[HistoricalShareEvent] = []
        for e in events:
            if e.source_record_id and e.source_record_id in seen:
                continue
            if e.source_record_id:
                seen.add(e.source_record_id)
            deduped.append(e)
        self._events[symbol] = deduped
        self._loaded_symbols.add(symbol)

    def load_symbols(self, symbols: list[str], **kwargs) -> None:
        """批量加载（从 live CNINFO API）。"""
        for s in symbols:
            self.load_symbol(s, **kwargs)

    def load_symbols_from_fixtures(self, symbols: list[str], fixture_dir: str | Path | None = None) -> None:
        """从冻结 fixture 加载（测试用，不访问网络）。"""
        if fixture_dir is None:
            fixture_dir = Path(__file__).resolve().parent / 'fixtures'
        else:
            fixture_dir = Path(fixture_dir)
        import pandas as pd
        for sym in symbols:
            path = fixture_dir / f'cninfo_{sym}.parquet'
            if not path.exists():
                print(f'[WARN] Fixture not found: {path}', flush=True)
                self._events[sym] = []
                self._loaded_symbols.add(sym)
                continue
            df = pd.read_parquet(path)
            events = convert_raw_events(df, sym)
            # 去重
            seen: set[str] = set()
            deduped: list[HistoricalShareEvent] = []
            for e in events:
                if e.source_record_id and e.source_record_id in seen:
                    continue
                if e.source_record_id:
                    seen.add(e.source_record_id)
                deduped.append(e)
            self._events[sym] = deduped
            self._loaded_symbols.add(sym)

    def get_events(self, symbol: str) -> list[HistoricalShareEvent]:
        """获取股票的所有股本事件（未排序）。"""
        return list(self._events.get(symbol, []))

    def get_timeline(self, symbol: str) -> list[HistoricalShareEvent]:
        """返回按 effective_date 排序的时间线。"""
        events = self.get_events(symbol)
        # 无 effective_date 的放到末尾
        dated = [e for e in events if e.effective_date is not None]
        undated = [e for e in events if e.effective_date is None]
        dated.sort(key=lambda e: e.effective_date)
        return dated + undated

    def get_as_of(self, symbol: str, as_of_date: date) -> HistoricalShareEvent | None:
        """PIT 股本查询：返回 as_of_date 之前最后一条 KNOWN_EFFECTIVE_DATE 事件。"""
        timeline = self.get_timeline(symbol)
        candidates = [e for e in timeline
                      if e.effective_date is not None
                      and e.effective_date <= as_of_date
                      and e.date_quality == ShareDateQuality.KNOWN_EFFECTIVE_DATE]
        if candidates:
            return candidates[-1]
        # 降级：APPROXIMATE
        approx = [e for e in timeline
                  if e.effective_date is not None
                  and e.effective_date <= as_of_date
                  and e.date_quality == ShareDateQuality.APPROXIMATE_EFFECTIVE_DATE]
        if approx:
            return approx[-1]
        return None

    def get_any_as_of(self, symbol: str, as_of_date: date) -> HistoricalShareEvent | None:
        """PIT 查询（包含 UNKNOWN）：返回 as_of_date 之前最后一条事件（任意 quality）。"""
        timeline = self.get_timeline(symbol)
        candidates = [e for e in timeline
                      if e.effective_date is not None
                      and e.effective_date <= as_of_date]
        return candidates[-1] if candidates else None

    def coverage_report(self) -> dict:
        """输出 coverage 报告。"""
        report: dict = {
            'total_symbols_loaded': len(self._loaded_symbols),
            'symbols': {},
            'date_range': {'earliest': None, 'latest': None},
            'quality_summary': {
                'KNOWN_EFFECTIVE_DATE': 0,
                'APPROXIMATE_EFFECTIVE_DATE': 0,
                'UNKNOWN_EFFECTIVE_DATE': 0,
            },
        }
        earliest = None
        latest = None
        for sym in self._loaded_symbols:
            events = self.get_events(sym)
            sym_dates = [e.effective_date for e in events if e.effective_date]
            if sym_dates:
                sym_earliest = min(sym_dates)
                sym_latest = max(sym_dates)
                if earliest is None or sym_earliest < earliest:
                    earliest = sym_earliest
                if latest is None or sym_latest > latest:
                    latest = sym_latest
            qc = {'KNOWN_EFFECTIVE_DATE': 0, 'APPROXIMATE_EFFECTIVE_DATE': 0, 'UNKNOWN_EFFECTIVE_DATE': 0}
            for e in events:
                q = e.date_quality.value
                if q in qc:
                    qc[q] += 1
                else:
                    qc[q] = 1
                report['quality_summary'][q] = report['quality_summary'].get(q, 0) + 1
            report['symbols'][sym] = {
                'total_events': len(events),
                'effective_dates': len(sym_dates),
                'earliest': str(sym_dates[0]) if sym_dates else None,
                'latest': str(sym_dates[-1]) if sym_dates else None,
                'quality': qc,
            }
        report['date_range']['earliest'] = str(earliest) if earliest else None
        report['date_range']['latest'] = str(latest) if latest else None
        return report


# ---------------------------------------------------------------------------
# Historical Market Cap
# ---------------------------------------------------------------------------
class HistoricalMarketCap:
    """基于 Historical Share Layer 的历史市值重建。"""

    def __init__(self, share_layer: HistoricalShareLayer) -> None:
        self.share_layer = share_layer

    def get_market_cap(self, symbol: str, as_of_date: date, *, strict: bool = False) -> HistoricalMarketCapResult:
        """查询 as_of_date 的历史总市值（元）。
        
        Args:
            strict: 如果 True，仅接受 KNOWN_EFFECTIVE_DATE 股本（STRICT PIT）。
                    如果 False，接受 KNOWN + APPROXIMATE（RESEARCH）。
        
        Returns:
            HistoricalMarketCapResult with quality:
            - strict=True, KNOWN → PIT_SAFE
            - strict=True, APPROXIMATE/UNKNOWN → UNKNOWN
            - strict=False, KNOWN → PIT_SAFE
            - strict=False, APPROXIMATE → APPROXIMATE
            - strict=False, UNKNOWN → UNKNOWN
        """
        # 使用 get_any_as_of 获取最近可用事件
        share_event = self.share_layer.get_any_as_of(symbol, as_of_date)
        if share_event is None:
            return HistoricalMarketCapResult(
                symbol=symbol,
                as_of_date=as_of_date,
                quality=MarketCapQuality.UNKNOWN,
                limitation_codes=['NO_SHARE_DATA'],
                confidence=0.0,
            )
        # 从 klines 获取 as_of_date 或之前最近一日的 close
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        cur.execute(
            'SELECT date, close FROM klines WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1',
            (symbol, str(as_of_date))
        )
        row = cur.fetchone()
        con.close()
        if row is None:
            return HistoricalMarketCapResult(
                symbol=symbol,
                as_of_date=as_of_date,
                share_count=share_event.share_count,
                share_effective_date=share_event.effective_date,
                share_date_quality=share_event.date_quality,
                quality=MarketCapQuality.BLOCKED,
                limitation_codes=['NO_PRICE_DATA'],
                confidence=0.0,
            )
        price_date_str, close = row
        price_date = datetime.strptime(price_date_str, '%Y-%m-%d').date()
        market_cap = share_event.share_count * close
        
        if share_event.date_quality == ShareDateQuality.KNOWN_EFFECTIVE_DATE:
            quality = MarketCapQuality.PIT_SAFE
            limitations = list(share_event.limitation_codes)
        elif share_event.date_quality == ShareDateQuality.APPROXIMATE_EFFECTIVE_DATE:
            if strict:
                quality = MarketCapQuality.UNKNOWN
                limitations = ['SHARE_DATE_NOT_KNOWN_EFFECTIVE']
                market_cap = None  # STRICT 模式下 APPROXIMATE 不可用
            else:
                quality = MarketCapQuality.APPROXIMATE
                limitations = list(share_event.limitation_codes) + ['SHARE_DATE_APPROXIMATE']
        else:  # UNKNOWN_EFFECTIVE_DATE
            quality = MarketCapQuality.UNKNOWN
            limitations = ['SHARE_DATE_UNKNOWN']
            market_cap = None  # UNKNOWN 日期不可用
        
        return HistoricalMarketCapResult(
            symbol=symbol,
            as_of_date=as_of_date,
            market_cap=market_cap,
            share_count=share_event.share_count,
            share_effective_date=share_event.effective_date,
            share_date_quality=share_event.date_quality,
            price=close,
            price_date=price_date,
            quality=quality,
            limitation_codes=limitations,
            confidence=share_event.confidence,
        )

    def check_5_90b_filter(self, symbol: str, as_of_date: date) -> str:
        """
        用 Historical Market Cap 执行 V1 的 5-90 亿过滤。
        返回：PASS / FAIL / UNKNOWN
        """
        result = self.get_market_cap(symbol, as_of_date)
        if result.market_cap is None or result.quality in (MarketCapQuality.UNKNOWN, MarketCapQuality.BLOCKED):
            return 'UNKNOWN'
        # 先检查质量
        if result.quality == MarketCapQuality.APPROXIMATE:
            return 'UNKNOWN'
        mcap_yi = result.market_cap / 1e8
        if mcap_yi < 5:
            return 'FAIL'
        if mcap_yi > 90:
            return 'FAIL'
        return 'PASS'


# ---------------------------------------------------------------------------
# Singleton Cache（可选）
# ---------------------------------------------------------------------------
_share_layer: HistoricalShareLayer | None = None
_market_cap: HistoricalMarketCap | None = None


def get_share_layer() -> HistoricalShareLayer:
    global _share_layer
    if _share_layer is None:
        _share_layer = HistoricalShareLayer()
    return _share_layer


def get_market_cap() -> HistoricalMarketCap:
    global _market_cap
    if _market_cap is None:
        _market_cap = HistoricalMarketCap(get_share_layer())
    return _market_cap
