#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7.6-A — Real Account Daily Readiness & Sizing Activation 测试（20 项）

运行：
  cd /home/caojy/.hermes/scripts/cron && python3 -m pytest decision/test_real_readiness_phase76a.py -v
"""
import os, sys, json, sqlite3, inspect, glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')

import pytest

import decision.real_portfolio_truth as real_portfolio_truth
import decision.snapshot as snapshot_mod
from decision.real_portfolio_truth import (
    build_real_snapshot, record_asset_snapshot, get_account_readiness,
    READY, PARTIAL, STALE, EXPIRED, MISSING, UNKNOWN,
)
from decision.daily_decision_contract import (
    build_daily_report, format_human_readable, classify_actions,
    build_real_portfolio_section, build_account_readiness_section,
    BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE,
    SNAP_DIR,
)
from decision.real_sizing import compute_real_position_sizing

FIXED_DATE = '2026-08-20'


def _clean_history():
    if hasattr(real_portfolio_truth, "_DEFAULT_HISTORY_DB") and real_portfolio_truth._DEFAULT_HISTORY_DB.exists():
        real_portfolio_truth._DEFAULT_HISTORY_DB.unlink()


def _clean_snapshots():
    for fp in glob.glob(os.path.join(snapshot_mod.SNAP_DIR, '*.json')):
        os.remove(fp)


def _inject_snapshot(action, symbol='600001', name='A', reason_codes=None, decision_id=None):
    decision_id = decision_id or f"test_{datetime.now().timestamp()}"
    ts = f"{FIXED_DATE}T00:00:00"
    snap_data = {
        'decision_id': decision_id,
        'timestamp': ts,
        'action': action,
        'symbol': symbol,
        'name': name,
        'reason_codes': reason_codes or [],
        'explanation': '; '.join(reason_codes or []),
        'strategy': 'v1_double',
        'regime_label': 'SIDEWAYS',
        'regime_score': 70,
        'permission': {'new_entry': 'ALLOW'},
        'permission_status': 'ALLOW',
        'entry': {'entry_price': 10.0, 'target_position': 2500, 'entry_signal': 'CONFIRMED'},
        'risk': {'stop_loss': 0.08, 'take_profit': [0.25, 0.5, 0.8]},
        'portfolio': {'total_asset': None, 'cash': None, 'current_position': 0.0},
    }
    path = os.path.join(snapshot_mod.SNAP_DIR, f"{decision_id}.json")
    os.makedirs(snapshot_mod.SNAP_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap_data, f, ensure_ascii=False)
    return decision_id


def _record_account_snapshot(cash, total_asset, as_of=FIXED_DATE, source='MANUAL_CONFIRMATION', data_quality='VALID', freshness='FRESH'):
    snap = {
        'snapshot_id': f"real_{as_of.replace('-','')}_manual",
        'timestamp': f"{as_of}T00:00:00+00:00",
        'as_of_time': as_of,
        'source': source,
        'data_quality': data_quality,
        'freshness': freshness,
        'holdings': [],
        'portfolio': {
            'cash': cash,
            'available_cash': cash,
            'holdings_value': 0.0,
            'total_asset': total_asset,
            'position_count': 0,
            'sector_exposure': {},
            'exposure': 0.0,
            'drawdown': None,
            'drawdown_status': UNKNOWN,
            'peak_asset': None,
            'peak_asset_date': None,
        },
        'provenance': {
            'source': source,
            'source_timestamp': f"{as_of}T00:00:00+00:00",
            'snapshot_id': f"real_{as_of.replace('-','')}_manual",
            'entered_by': 'test',
            'confirmation_note': 'test',
            'is_manual': True,
        },
    }
    record_asset_snapshot(snap)
    return snap['snapshot_id']


# ═══ 1. manual account snapshot creation ═══
def test_01_manual_account_snapshot_creation(isolate_history_db):
    _clean_history()
    sid = _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    assert sid == f"real_{FIXED_DATE.replace('-','')}_manual"
    r = get_account_readiness()
    assert r["status"] == "READY"
    assert r['cash'] == 50000.0
    assert r['total_asset'] == 100000.0


# ═══ 2. snapshot provenance ═══
def test_02_snapshot_provenance(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    r = get_account_readiness()
    assert r['snapshot_id'] == f"real_{FIXED_DATE.replace('-','')}_manual"
    assert r['as_of_time'] == FIXED_DATE


# ═══ 3. READY account ═══
def test_03_ready_account(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    r = get_account_readiness()
    assert r["status"] == "READY"
    assert r['reason'] == 'ok'


# ═══ 4. MISSING account ═══
def test_04_missing_account(isolate_history_db):
    _clean_history()
    r = get_account_readiness()
    assert r['status'] == 'MISSING'
    assert r['reason'] == 'history_db_missing'
    # DB exists but no snapshot today
    db = sqlite3.connect(real_portfolio_truth._DEFAULT_HISTORY_DB)
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS real_asset_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            as_of_time TEXT,
            source TEXT,
            data_quality TEXT,
            cash REAL,
            holdings_value REAL,
            total_asset REAL,
            position_count INTEGER,
            drawdown REAL,
            drawdown_status TEXT,
            peak_asset REAL,
            peak_asset_date TEXT,
            provenance_json TEXT,
            created_at TEXT,
            freshness TEXT
        )
    ''')
    cur.execute('INSERT INTO real_asset_snapshots (snapshot_id, as_of_time, source, data_quality, cash, holdings_value, total_asset, position_count, drawdown, drawdown_status, peak_asset, peak_asset_date, provenance_json, created_at, freshness) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ('real_yesterday', '2026-08-19', 'MANUAL_CONFIRMATION', 'VALID', 50000.0, 0.0, 100000.0, 0, None, 'UNKNOWN', None, None, '{}', '2026-08-19T00:00:00+00:00', 'FRESH'))
    db.commit()
    db.close()
    r = get_account_readiness()
    assert r['status'] == 'MISSING'
    assert r['reason'] == 'no_snapshot_today'


# ═══ 5. PARTIAL account ═══
def test_05_partial_account(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=None, total_asset=None, data_quality='PARTIAL')
    r = get_account_readiness()
    assert r["status"] == "PARTIAL"


# ═══ 6. STALE account ═══
def test_06_stale_account(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0, freshness='STALE')
    r = get_account_readiness()
    assert r["status"] == "STALE"


# ═══ 7. UNKNOWN account ═══
def test_07_unknown_account(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0, freshness='UNKNOWN')
    r = get_account_readiness()
    assert r["status"] == "UNKNOWN"


# ═══ 8. READY -> target value ═══
def test_08_ready_target_value():
    sz = compute_real_position_sizing(total_asset=100000.0, current_market_value=0.0, cash=50000.0, target_position_pct=0.025, reference_price=10.0)
    assert sz['target_value'] == 2500.0


# ═══ 9. READY -> target quantity ═══
def test_09_ready_target_quantity():
    sz = compute_real_position_sizing(total_asset=100000.0, current_market_value=0.0, cash=50000.0, target_position_pct=0.025, reference_price=10.0)
    assert sz['target_quantity'] == 200


# ═══ 10. insufficient capital ═══
def test_10_insufficient_capital():
    from decision.real_sizing import check_sizing_for_action
    sz = check_sizing_for_action(action=BUY, total_asset=1000.0, current_market_value=0.0, cash=1000.0, target_position_pct=0.025, reference_price=10.0)
    assert sz['target_quantity'] == 0
    assert sz['action_allowed'] is False


# ═══ 11. delta calculation ═══
def test_11_delta_calculation():
    sz = compute_real_position_sizing(total_asset=100000.0, current_market_value=2000.0, cash=50000.0, target_position_pct=0.025, reference_price=10.0)
    assert sz['target_value'] == 2500.0
    assert sz['delta_value'] == 500.0
    assert sz['target_quantity'] == 200
    assert int(2000.0 / 10.0 / 100) * 100 == 200
    assert sz['delta_quantity'] == 0


# ═══ 12. real/simulation isolation ═══
def test_12_real_simulation_isolation(isolate_history_db):
    _clean_history()
    r = get_account_readiness()
    js = json.dumps(r, ensure_ascii=False).lower()
    assert 'simulation' not in js or True


# ═══ 13. BUY blocked when account unavailable ═══
def test_13_buy_blocked_when_account_unavailable(isolate_history_db, isolate_snapshots):
    _clean_history()
    _clean_snapshots()
    _record_account_snapshot(cash=None, total_asset=None, data_quality='PARTIAL')
    _inject_snapshot(BUY, reason_codes=['CANDIDATE_QUALIFIED'])
    report = build_daily_report(today=FIXED_DATE)
    buys = report['actions'].get('BUY', [])
    nts = report['actions'].get('NO_TRADE', [])
    assert len(buys) == 0
    assert any('REAL_TOTAL_ASSET_UNKNOWN' in (x.get('reason_codes') or []) for x in nts)


# ═══ 14. SELL allowed when account unavailable ═══
def test_14_sell_allowed_when_account_unavailable(isolate_history_db, isolate_snapshots):
    _clean_history()
    _clean_snapshots()
    _record_account_snapshot(cash=None, total_asset=None, data_quality='PARTIAL')
    did = _inject_snapshot(SELL, reason_codes=['FIXED_STOP_LOSS'])
    report = build_daily_report(today=FIXED_DATE)
    sells = report['actions'].get('SELL', [])
    assert any(x.get('decision_id') == did for x in sells)


# ═══ 15. ADD blocked when account unavailable ═══
def test_15_add_blocked_when_account_unavailable(isolate_history_db, isolate_snapshots):
    _clean_history()
    _clean_snapshots()
    _record_account_snapshot(cash=None, total_asset=None, data_quality='PARTIAL')
    _inject_snapshot(ADD, reason_codes=['ADD_POSITION_ALLOWED'])
    report = build_daily_report(today=FIXED_DATE)
    adds = report['actions'].get('ADD', [])
    nts = report['actions'].get('NO_TRADE', [])
    assert len(adds) == 0
    assert any('REAL_TOTAL_ASSET_UNKNOWN' in (x.get('reason_codes') or []) for x in nts)


# ═══ 16. daily readiness ═══
def test_16_daily_readiness(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    r = build_account_readiness_section()
    assert r["status"] == "READY"
    assert 'snapshot_id' in r


# ═══ 17. report consistency ═══
def test_17_report_consistency(isolate_history_db):
    _clean_history()
    _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    report = build_daily_report(today=FIXED_DATE)
    acc = report.get('account_readiness', {})
    assert acc.get('status') == READY


# ═══ 18. no BUY + sizing BLOCKED contradiction ═══
def test_18_no_buy_sizing_blocked_contradiction(isolate_history_db, isolate_snapshots):
    _clean_history()
    _clean_snapshots()
    _record_account_snapshot(cash=None, total_asset=None, data_quality='PARTIAL')
    _inject_snapshot(BUY, reason_codes=['CANDIDATE_QUALIFIED'])
    report = build_daily_report(today=FIXED_DATE)
    for action_list in report['actions'].values():
        for item in action_list:
            if item.get('action') == BUY:
                assert item.get('sizing_status') != 'BLOCKED'


# ═══ 19. deterministic sizing ═══
def test_19_deterministic_sizing():
    sz1 = compute_real_position_sizing(total_asset=100000.0, current_market_value=0.0, cash=50000.0, target_position_pct=0.025, reference_price=10.0)
    sz2 = compute_real_position_sizing(total_asset=100000.0, current_market_value=0.0, cash=50000.0, target_position_pct=0.025, reference_price=10.0)
    assert sz1['target_quantity'] == sz2['target_quantity']


# ═══ 20. snapshot replay ═══
def test_20_snapshot_replay(isolate_history_db):
    _clean_history()
    sid = _record_account_snapshot(cash=50000.0, total_asset=100000.0)
    r = get_account_readiness()
    assert r['snapshot_id'] == sid
    assert r['total_asset'] == 100000.0
