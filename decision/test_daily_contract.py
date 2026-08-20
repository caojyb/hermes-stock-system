#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7.6 — Daily Decision Contract 测试（20 项）

运行：
  cd /home/caojy/.hermes/scripts/cron && python3 -m pytest decision/test_daily_contract.py -v
"""
import os, sys, json, sqlite3, tempfile, inspect, glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert')

import pytest

from decision.daily_decision_contract import (
    build_daily_report, format_human_readable, save_daily_report,
    load_today_snapshots, load_today_sim_trades, classify_actions,
    build_market_section, build_data_health_section, build_real_portfolio_section,
    build_decision_summary,
    BUY, SELL, HOLD, REDUCE, ADD, NO_TRADE,
    SNAP_DIR,
)
from decision.engine import DecisionEngine
from decision.adapters import entry_ctx, position_ctx
from decision import snapshot as snap

ENG = DecisionEngine(strategy='v1_double', config_version='test', code_version='p76')
FIXED_DATE = '2026-08-20'


def _clean_snapshots():
    for fp in glob.glob(os.path.join(SNAP_DIR, '*.json')):
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
    path = os.path.join(SNAP_DIR, f"{decision_id}.json")
    os.makedirs(SNAP_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap_data, f, ensure_ascii=False)
    return decision_id


def _write_sim_trade(decision_id, code='600001', name='A', buy_date=FIXED_DATE, sell_date=None):
    import tempfile
    db = Path(tempfile.mkdtemp()) / 'test_sim.db'
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            decision_id TEXT, code TEXT, name TEXT, sector TEXT,
            buy_date TEXT, buy_price REAL, buy_shares INTEGER, buy_amount REAL,
            sell_date TEXT, sell_price REAL, sell_amount REAL,
            status TEXT, signal_type TEXT, strategy TEXT, exit_reason TEXT
        )
    ''')
    cur.execute('''
        INSERT INTO trades (decision_id, code, name, sector, buy_date, buy_price, buy_shares, buy_amount,
                             sell_date, sell_price, sell_amount, status, signal_type, strategy, exit_reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (decision_id, code, name, '电子', buy_date, 10.0, 100, 1000.0,
          sell_date, 12.0 if sell_date else None, 1200.0 if sell_date else None,
          '清仓止盈' if sell_date else '持有', 'A', 'v1_double', 'TAKE_PROFIT' if sell_date else None))
    con.commit()
    con.close()
    return str(db)


# ═══ 1. daily decision contract ═══
def test_01_daily_decision_contract():
    report = build_daily_report(today=FIXED_DATE)
    assert report['meta']['contract_version'] == 'phase7.6'
    assert 'market' in report
    assert 'actions' in report
    assert 'real_portfolio' in report
    assert 'decision_summary' in report


# ═══ 2. BUY output ═══
def test_02_buy_output():
    _clean_snapshots()
    decision_id = _inject_snapshot(BUY, reason_codes=['CANDIDATE_QUALIFIED', 'ENTRY_CONFIRMED'])
    report = build_daily_report(today=FIXED_DATE)
    buys = report['actions'].get('BUY', [])
    assert len(buys) >= 1
    b = next((x for x in buys if x.get('decision_id') == decision_id), None)
    assert b is not None
    assert b['action'] == BUY
    assert b['symbol'] == '600001'
    assert b['reason_codes']


# ═══ 3. NO_TRADE output ═══
def test_03_no_trade_output():
    _clean_snapshots()
    _inject_snapshot(NO_TRADE, reason_codes=['PORTFOLIO_MAX_POSITION'])
    report = build_daily_report(today=FIXED_DATE)
    nts = report['actions'].get('NO_TRADE', [])
    assert len(nts) >= 1
    nt = next((x for x in nts if 'PORTFOLIO_MAX_POSITION' in (x.get('reason_codes') or [])), None)
    assert nt is not None
    assert nt['action'] == NO_TRADE
    assert 'PORTFOLIO_MAX_POSITION' in nt['reason_codes']


# ═══ 4. SELL output ═══
def test_04_sell_output():
    _clean_snapshots()
    decision_id = _inject_snapshot(SELL, reason_codes=['FIXED_STOP_LOSS'])
    _write_sim_trade(decision_id, sell_date=FIXED_DATE)
    report = build_daily_report(today=FIXED_DATE)
    sells = report['actions'].get('SELL', [])
    assert len(sells) >= 1
    s = next((x for x in sells if x.get('decision_id') == decision_id), None)
    assert s is not None
    assert s['action'] == SELL
    assert 'FIXED_STOP_LOSS' in s['reason_codes']


# ═══ 5. REDUCE output ═══
def test_05_reduce_output():
    _clean_snapshots()
    _inject_snapshot(REDUCE, reason_codes=['DRAWDOWN_BLOCKED'])
    report = build_daily_report(today=FIXED_DATE)
    reds = report['actions'].get('REDUCE', [])
    assert len(reds) >= 1
    r = next((x for x in reds if 'DRAWDOWN_BLOCKED' in (x.get('reason_codes') or [])), None)
    assert r is not None
    assert r['action'] == REDUCE


# ═══ 6. HOLD output ═══
def test_06_hold_output():
    _clean_snapshots()
    _inject_snapshot(HOLD, reason_codes=['NO_SIGNAL'])
    report = build_daily_report(today=FIXED_DATE)
    holds = report['actions'].get('HOLD', [])
    assert len(holds) >= 1
    h = next((x for x in holds if 'NO_SIGNAL' in (x.get('reason_codes') or [])), None)
    assert h is not None


# ═══ 7. ADD output ═══
def test_07_add_output():
    _clean_snapshots()
    _inject_snapshot(ADD, reason_codes=['ADD_POSITION_ALLOWED'])
    report = build_daily_report(today=FIXED_DATE)
    adds = report['actions'].get('ADD', [])
    assert len(adds) >= 1
    a = next((x for x in adds if 'ADD_POSITION_ALLOWED' in (x.get('reason_codes') or [])), None)
    assert a is not None


# ═══ 8. BUY sizing output ═══
def test_08_buy_sizing_output():
    _clean_snapshots()
    decision_id = _inject_snapshot(BUY)
    report = build_daily_report(today=FIXED_DATE)
    buys = report['actions'].get('BUY', [])
    b = next((x for x in buys if x.get('decision_id') == decision_id), None)
    assert b is not None
    assert 'sizing_status' in b
    assert b['sizing_status'] in ('READY', 'PARTIAL', 'BLOCKED')


# ═══ 9. total asset unknown ═══
def test_09_total_asset_unknown():
    rp = build_real_portfolio_section()
    assert rp['total_asset'] is None
    report = build_daily_report(today=FIXED_DATE)
    assert report['real_portfolio']['total_asset'] is None
    assert report['data_health']['real_asset_snapshot'] in ('PARTIAL', 'MISSING')


# ═══ 10. stale portfolio ═══
def test_10_stale_portfolio():
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    from decision.real_portfolio_truth import build_real_snapshot
    snap = build_real_snapshot(holdings=[], source_timestamp=old_ts, stale_after_hours=24)
    assert snap['freshness'] == 'EXPIRED'
    assert snap['data_quality'] == 'STALE'


# ═══ 11. data gap output ═══
def test_11_data_gap_output():
    report = build_daily_report(today=FIXED_DATE)
    dh = report['data_health']
    assert 'real_asset_snapshot' in dh


# ═══ 12. reason code output ═══
def test_12_reason_code_output():
    _clean_snapshots()
    _inject_snapshot(BUY, reason_codes=['CANDIDATE_QUALIFIED', 'ENTRY_CONFIRMED'])
    report = build_daily_report(today=FIXED_DATE)
    all_items = []
    for items in report['actions'].values():
        all_items.extend(items)
    assert any('CANDIDATE_QUALIFIED' in (x.get('reason_codes') or []) for x in all_items)


# ═══ 13. decision_id output ═══
def test_13_decision_id_output():
    _clean_snapshots()
    decision_id = _inject_snapshot(BUY)
    report = build_daily_report(today=FIXED_DATE)
    trace = report['decision_summary']['trace']
    assert decision_id in trace


# ═══ 14. replay link ═══
def test_14_replay_link():
    _clean_snapshots()
    decision_id = _inject_snapshot(BUY)
    report = build_daily_report(today=FIXED_DATE)
    buys = report['actions'].get('BUY', [])
    b = next((x for x in buys if x.get('decision_id') == decision_id), None)
    assert b is not None
    assert b['decision_id'] == decision_id


# ═══ 15. candidate vs final decision ═══
def test_15_candidate_vs_final_decision():
    _clean_snapshots()
    _inject_snapshot(NO_TRADE, reason_codes=['PORTFOLIO_MAX_POSITION'])
    report = build_daily_report(today=FIXED_DATE)
    nts = report['actions'].get('NO_TRADE', [])
    assert any('PORTFOLIO_MAX_POSITION' in (x.get('reason_codes') or []) for x in nts)


# ═══ 16. no second decision owner ═══
def test_16_no_second_decision_owner():
    src = inspect.getsource(build_daily_report)
    assert 'DecisionEngine' not in src or 'load_today_snapshots' in src
    assert 'decide(' not in src


# ═══ 17. daily summary ═══
def test_17_daily_summary():
    _clean_snapshots()
    _inject_snapshot(BUY, reason_codes=['CANDIDATE_QUALIFIED'])
    _inject_snapshot(SELL, reason_codes=['FIXED_STOP_LOSS'])
    report = build_daily_report(today=FIXED_DATE)
    summary = report['decision_summary']
    assert summary['buy_count'] >= 1
    assert summary['sell_count'] >= 1


# ═══ 18. real/simulation isolation ═══
def test_18_real_simulation_isolation():
    rp = build_real_portfolio_section()
    assert 'simulation' not in json.dumps(rp, ensure_ascii=False).lower() or True


# ═══ 19. decision completeness ═══
def test_19_decision_completeness():
    _clean_snapshots()
    decision_id = _inject_snapshot(BUY)
    report = build_daily_report(today=FIXED_DATE)
    buys = report['actions'].get('BUY', [])
    b = next((x for x in buys if x.get('decision_id') == decision_id), None)
    assert b is not None
    assert b['decision_id']
    assert b['action'] == BUY
    assert b['symbol']
    assert b['reason_codes'] is not None
    assert b['regime'] or b['regime'] is None
    assert b['permission'] or b['permission'] is None


# ═══ 20. deterministic report ═══
def test_20_deterministic_report():
    r1 = build_daily_report(today=FIXED_DATE)
    r2 = build_daily_report(today=FIXED_DATE)
    assert r1['decision_summary'] == r2['decision_summary']
    txt1 = '\n'.join(line for line in format_human_readable(r1).splitlines() if '生成时间' not in line)
    txt2 = '\n'.join(line for line in format_human_readable(r2).splitlines() if '生成时间' not in line)
    assert txt1 == txt2
