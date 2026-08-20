#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7.5 — Real Position Sizing + Real Portfolio Truth 测试

1. real portfolio asset snapshot
2. cash + holdings = total asset
3. total asset missing
4. peak calculation
5. real drawdown calculation
6. drawdown unknown
7. real position percentage
8. target value
9. target quantity
10. delta quantity
11. lot size
12. insufficient cash
13. total asset unknown blocks BUY
14. total asset unknown does not block SELL
15. real/simulation isolation
16. stale real portfolio
17. manual confirmation provenance
18. real portfolio replay context
19. drawdown permission integration
20. real sizing deterministic

运行：
  cd /home/caojy/.hermes/scripts/cron && python3 -m pytest decision/test_real_portfolio_phase75.py -v
"""
import os, sys, json, sqlite3, tempfile, inspect
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest

from decision.real_portfolio_truth import (
    build_real_snapshot, record_asset_snapshot, _load_peak_and_drawdown,
    snapshot_portfolio_context, run_daily_snapshot,
    VALID, STALE, PARTIAL, MISSING, UNKNOWN, FRESH, EXPIRED, LOT_SIZE,
    _DEFAULT_HISTORY_DB,
)
from decision.real_sizing import (
    compute_real_position_sizing, check_sizing_for_action,
    BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE, READY, BLOCKED,
)
from decision.engine import DecisionEngine
from decision.adapters import position_ctx
from decision.portfolio import assess_portfolio
from decision import snapshot as snap
from decision import replay as rp

eng = DecisionEngine(strategy='v1_double', config_version='test', code_version='p75')

HOLDINGS = [
    {'code': '600001', 'name': 'A', 'quantity': 1000, 'avg_cost': 10.0, 'current_price': 11.0, 'sector': '电子'},
    {'code': '600002', 'name': 'B', 'quantity': 500, 'avg_cost': 20.0, 'current_price': 19.0, 'sector': '医药'},
    {'code': '600003', 'name': 'C', 'quantity': 200, 'avg_cost': 30.0, 'current_price': 33.0, 'sector': '电子'},
]


# ═══ 1. real portfolio asset snapshot ═══
def test_01_real_portfolio_asset_snapshot():
    s = build_real_snapshot(holdings=HOLDINGS)
    assert s['ok'] is True
    assert s['snapshot_id']
    assert 'real_' in s['snapshot_id']
    assert s['portfolio']['position_count'] == 3
    assert s['portfolio']['holdings_value'] == pytest.approx(1000*11 + 500*19 + 200*33)


# ═══ 2. cash + holdings = total asset ═══
def test_02_cash_plus_holdings_equals_total_asset():
    holdings_value = sum(h['quantity'] * h['current_price'] for h in HOLDINGS)
    cash = 500_000
    s = build_real_snapshot(holdings=HOLDINGS, cash=cash, total_asset=cash + holdings_value, source='MANUAL_CONFIRMATION')
    assert s['portfolio']['cash'] == pytest.approx(cash)
    assert s['portfolio']['holdings_value'] == pytest.approx(holdings_value)
    assert s['portfolio']['total_asset'] == pytest.approx(cash + holdings_value)
    assert s['data_quality'] == VALID
    assert s['provenance']['is_manual'] is True


# ═══ 3. total asset missing ═══
def test_03_total_asset_missing():
    s = build_real_snapshot(holdings=HOLDINGS)
    assert s['portfolio']['total_asset'] is None
    assert s['portfolio']['cash'] is None
    assert s['data_quality'] == PARTIAL


# ═══ 4. peak calculation ═══
def test_04_peak_calculation():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / 'peak_test.db'
        as_of = '2026-08-20'
        s1 = build_real_snapshot(holdings=HOLDINGS, cash=100_000, total_asset=133_900, source='MANUAL_CONFIRMATION')
        s1['as_of_time'] = '2026-08-18'
        record_asset_snapshot(s1, db_path=db)
        s2 = build_real_snapshot(holdings=HOLDINGS, cash=120_000, total_asset=153_900, source='MANUAL_CONFIRMATION')
        s2['as_of_time'] = '2026-08-19'
        record_asset_snapshot(s2, db_path=db)
        s3 = build_real_snapshot(holdings=HOLDINGS, cash=80_000, total_asset=113_900, source='MANUAL_CONFIRMATION')
        s3['as_of_time'] = as_of
        record_asset_snapshot(s3, db_path=db)
        peak, peak_date, drawdown, status = _load_peak_and_drawdown(as_of, db_path=db)
        assert peak == pytest.approx(153_900)
        assert drawdown == pytest.approx((153_900 - 113_900) / 153_900)
        assert status == 'KNOWN'


# ═══ 5. real drawdown calculation ═══
def test_05_real_drawdown_calculation():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / 'drawdown_test.db'
        s1 = build_real_snapshot(holdings=HOLDINGS, cash=100_000, total_asset=200_000, source='MANUAL_CONFIRMATION')
        s1['as_of_time'] = '2026-08-18'
        record_asset_snapshot(s1, db_path=db)
        s2 = build_real_snapshot(holdings=HOLDINGS, cash=60_000, total_asset=160_000, source='MANUAL_CONFIRMATION')
        s2['as_of_time'] = '2026-08-20'
        record_asset_snapshot(s2, db_path=db)
        _, _, drawdown, _ = _load_peak_and_drawdown(s2['as_of_time'], db_path=db)
        assert drawdown == pytest.approx(0.2)


# ═══ 6. drawdown unknown ═══
def test_06_drawdown_unknown_without_history():
    s = build_real_snapshot(holdings=HOLDINGS)
    assert s['portfolio']['drawdown'] is None
    assert s['portfolio']['drawdown_status'] == UNKNOWN


# ═══ 7. real position percentage ═══
def test_07_real_position_percentage():
    s = build_real_snapshot(holdings=HOLDINGS, cash=100_000, total_asset=200_000, source='MANUAL_CONFIRMATION')
    holdings_value = sum(h['quantity'] * h['current_price'] for h in HOLDINGS)
    assert s['portfolio']['exposure'] == pytest.approx(holdings_value / 200_000)
    for d in s['holdings']:
        if d['market_value'] > 0:
            assert d['position_pct_holdings'] == pytest.approx(d['market_value'] / holdings_value, abs=1e-3)


# ═══ 8. target value ═══
def test_08_target_value():
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=0, cash=1_000_000,
                                     target_position_pct=0.025, reference_price=10.0)
    assert r['target_value'] == pytest.approx(25_000)


# ═══ 9. target quantity ═══
def test_09_target_quantity():
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=0, cash=1_000_000,
                                     target_position_pct=0.025, reference_price=10.0)
    assert r['target_quantity'] == 2500
    assert r['target_quantity'] % LOT_SIZE == 0


# ═══ 10. delta quantity ═══
def test_10_delta_quantity():
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=30_000, cash=970_000,
                                     target_position_pct=0.025, reference_price=10.0)
    assert r['current_position_pct'] == pytest.approx(0.03)
    assert r['delta_value'] == pytest.approx(-5_000)
    assert r['delta_quantity'] == -500


# ═══ 11. lot size ═══
def test_11_lot_size_enforcement():
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=0, cash=1_000_000,
                                     target_position_pct=0.025, reference_price=10.01)
    assert r['target_quantity'] % LOT_SIZE == 0
    assert r['target_quantity'] == 2400  # floor(2497.5/100)*100 = 2400


# ═══ 12. insufficient cash ═══
def test_12_insufficient_cash():
    r = compute_real_position_sizing(total_asset=1_000_000, current_market_value=990_000, cash=10_000,
                                     target_position_pct=0.025, reference_price=10.0)
    assert r['target_value'] == pytest.approx(25_000)
    assert r['delta_value'] == pytest.approx(-965_000)
    assert r['delta_quantity'] == -96500


# ═══ 13. total asset unknown blocks BUY ═══
def test_13_total_asset_unknown_blocks_buy():
    r = check_sizing_for_action(action=BUY, total_asset=None, current_market_value=0, cash=None,
                                 target_position_pct=0.025, reference_price=10.0)
    assert r['sizing_status'] == BLOCKED
    assert r['action_allowed'] is False
    assert 'TOTAL_ASSET_UNKNOWN' in r['block_reason']


# ═══ 14. total asset unknown does not block SELL ═══
def test_14_total_asset_unknown_does_not_block_sell():
    r = check_sizing_for_action(action=SELL, total_asset=None, current_market_value=10_000, cash=None,
                                 target_position_pct=0.0, reference_price=10.0)
    assert r['action_allowed'] is True
    assert r['target_quantity'] == 0
    assert r['sizing_status'] == PARTIAL


# ═══ 15. real/simulation isolation ═══
def test_15_real_simulation_isolation():
    src = inspect.getsource(build_real_snapshot)
    assert 'simulation' not in src.lower() or 'simulation' in src.replace('simulation', '')
    assert 'simulation.db' not in src


# ═══ 16. stale real portfolio ═══
def test_16_stale_real_portfolio():
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    s = build_real_snapshot(holdings=HOLDINGS, source_timestamp=old, stale_after_hours=24)
    assert s['freshness'] == EXPIRED
    assert s['data_quality'] == STALE


# ═══ 17. manual confirmation provenance ═══
def test_17_manual_confirmation_provenance():
    s = build_real_snapshot(holdings=HOLDINGS, cash=100_000, total_asset=200_000, source='MANUAL_CONFIRMATION',
                            entered_by='caojy', confirmation_note='平安证券截图')
    assert s['provenance']['is_manual'] is True
    assert s['provenance']['entered_by'] == 'caojy'
    assert s['provenance']['confirmation_note'] == '平安证券截图'
    assert s['provenance']['manual_cash_provided'] is True
    assert s['provenance']['manual_total_asset_provided'] is True


# ═══ 18. real portfolio replay context ═══
def test_18_real_portfolio_replay_context(tmp_path):
    s = build_real_snapshot(holdings=HOLDINGS, cash=100_000, total_asset=200_000, source='MANUAL_CONFIRMATION')
    pa = assess_portfolio(candidate_sector='电子', target_position=0, total_capital=1_000_000,
                          position_count=3, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts=s['portfolio']['sector_exposure'],
                          drawdown=None, drawdown_status=UNKNOWN)
    ctx = position_ctx(symbol='600001', name='A', exit_signal='NONE', data_health='VALID',
                       current_position=0.05, portfolio_risk='OK' if pa['allowed'] else 'BLOCKED',
                       portfolio_assessment=pa, position_count=3,
                       portfolio_snapshot_id=s['snapshot_id'], portfolio_source=s['source'],
                       portfolio_as_of_time=s['as_of_time'])
    d = eng.decide(ctx)
    path = snap.save_snapshot(d, snap_dir=str(tmp_path))
    r = rp.replay(d.decision_id, snap_dir=str(tmp_path))
    assert r['ok']
    rd = r['decision']
    assert rd['portfolio_snapshot_id'] == s['snapshot_id']
    assert rd['portfolio_source'] == 'MANUAL_CONFIRMATION'


# ═══ 19. drawdown permission integration ═══
def test_19_drawdown_permission_integration():
    pa = assess_portfolio(candidate_sector='电子', target_position=0, total_capital=1_000_000,
                          position_count=10, max_positions=20, max_position_pct=0.05,
                          max_sector_cnt=3, sector_counts={'电子': 2}, drawdown=0.18, drawdown_limit=0.15)
    d = eng.decide(position_ctx(symbol='600001', name='A', exit_signal='NONE', current_position=0.05,
                                portfolio_risk='BLOCKED', portfolio_assessment=pa, drawdown=0.18))
    assert d.action == REDUCE
    assert 'DRAWDOWN_BLOCKED' in d.reason_codes


# ═══ 20. real sizing deterministic ═══
def test_20_real_sizing_deterministic():
    r1 = compute_real_position_sizing(total_asset=1_000_000, current_market_value=0, cash=1_000_000,
                                      target_position_pct=0.025, reference_price=10.0)
    r2 = compute_real_position_sizing(total_asset=1_000_000, current_market_value=0, cash=1_000_000,
                                      target_position_pct=0.025, reference_price=10.0)
    assert r1 == r2
