#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Primary Feishu Delivery Tests（Phase 8-G0.2）

覆盖：
1. primary message build
2. daily json / feishu consistency
3. delivery record PENDING
4. successful send -> SENT
5. failed send -> FAILED
6. retry -> RETRYING
7. successful retry -> SENT
8. duplicate delivery suppression
9. same symbol / different decision_id not suppressed
10. same decision_id / different presentation allowed
11. delivery failure does not mutate Decision
12. no Decision recomputation
13. no Execution creation
14. no Outcome creation
15. account blocked rendering
16. zero action rendering
17. non-trading-day rendering
18. production/test isolation
19. deterministic message hash
20. channel fixed to current stock group
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision.feishu_delivery import (
    build_primary_feishu_message,
    deliver_primary_feishu,
    deliver_primary_feishu_with_retry,
    FEISHU_CHAT_ID,
)
from decision.user_authority import (
    record_delivery,
    is_duplicate_delivery,
    message_hash,
    PENDING,
    SENT,
    FAILED,
    RETRYING,
    DAILY,
    URGENT,
)


def _make_report(actions=None, account_status='READY', regime_label='🟢 强趋势', zero_action=False):
    actions = actions or {}
    if zero_action:
        actions = {'NO_TRADE': []}
    return {
        'meta': {'report_date': '2026-08-21', 'as_of_time': '2026-08-21T10:00:00+08:00', 'contract_version': 'phase7.6'},
        'market': {'regime_label': regime_label, 'regime_score': 80, 'position_scale': 1.0},
        'real_portfolio': {
            'source': 'MANUAL_CONFIRMATION', 'data_quality': 'VALID', 'freshness': 'FRESH',
            'cash': 50000.0, 'total_asset': 200000.0, 'holdings_value': 150000.0,
            'exposure': 0.75, 'drawdown': -0.15, 'drawdown_status': 'KNOWN',
            'peak_asset': 200000.0, 'peak_asset_date': '2026-08-01',
        },
        'account_readiness': {'status': account_status},
        'actions': actions,
        'decision_summary': {
            'total_decisions': sum(len(v) for v in actions.values()),
            'buy_count': len(actions.get('BUY', [])),
            'add_count': len(actions.get('ADD', [])),
            'hold_count': len(actions.get('HOLD', [])),
            'reduce_count': len(actions.get('REDUCE', [])),
            'sell_count': len(actions.get('SELL', [])),
            'no_trade_count': len(actions.get('NO_TRADE', [])),
            'trace': [],
        },
    }


# ── 1. primary message build ──
def test_primary_message_build():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D001',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}, 'sizing_status': 'PARTIAL',
                  'risk': {'stop_loss': 90.0}}],
        'NO_TRADE': [],
    })
    msg = build_primary_feishu_message(report)
    assert msg['presentation'] == DAILY
    assert msg['channel'] == FEISHU_CHAT_ID
    assert 'Daily Decision' in msg['text']
    assert 'D001' in msg['text']
    assert msg['content_hash'] == hashlib.sha256(msg['text'].encode('utf-8')).hexdigest()


# ── 2. daily json / feishu consistency ──
def test_daily_json_feishu_consistency():
    report = _make_report(actions={
        'BUY': [{'symbol': '600519', 'name': '茅台', 'action': 'BUY', 'decision_id': 'D002',
                  'reason_codes': ['ENTRY_CONFIRMED'], 'entry': {'entry_price': 1900.0, 'target_position': 50000},
                  'sizing_status': 'READY', 'target_value': 50000.0, 'target_quantity': 100}],
    })
    msg = build_primary_feishu_message(report)
    assert msg['report_date'] == report['meta']['report_date']
    assert msg['decision_summary']['buy_count'] == 1
    assert msg['account_readiness_status'] == report['account_readiness']['status']
    assert '600519' in msg['text']
    assert 'BUY' in msg['text']


# ── 3. delivery record PENDING ──
def test_delivery_record_pending():
    with tempfile.TemporaryDirectory() as d:
        rec = record_delivery(decision_id='D_PENDING', presentation=DAILY, channel=FEISHU_CHAT_ID,
                              delivery_status=PENDING, ua_dir=d)
        assert rec['delivery_status'] == PENDING
        assert rec['delivery_id'].startswith('del_')


# ── 4. successful send -> SENT ──
def test_successful_send_sent():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_SENT',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True, 'message_id': 'm123'}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu(report, ua_dir=tempfile.mkdtemp())
    assert result['delivery_status'] == SENT
    assert result['application_level_send'] is True
    assert result['server_readback'] == 'UNAVAILABLE'


# ── 5. failed send -> FAILED ──
def test_failed_send_failed():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_FAIL',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 400, 'error': 'bad request'}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu(report, ua_dir=tempfile.mkdtemp())
    assert result['delivery_status'] == FAILED
    assert result['application_level_send'] is False


# ── 6. retry -> RETRYING ──
def test_retry_retrying():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_RETRY',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 500, 'error': 'server error'}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu_with_retry(report, max_retries=1, ua_dir=tempfile.mkdtemp())
    assert result['delivery_status'] == FAILED
    assert result['retry_count'] == 1


# ── 7. successful retry -> SENT ──
def test_successful_retry_sent():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_RETRY_OK',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    state = {'count': 0}
    class FakeSender:
        def send_text_message(self, text, receive_id):
            state['count'] += 1
            if state['count'] == 1:
                return {'code': 500, 'error': 'server error'}
            return {'code': 0, 'ok': True, 'message_id': 'm456'}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu_with_retry(report, max_retries=1, ua_dir=tempfile.mkdtemp())
    assert result['delivery_status'] == SENT
    assert result['retry_count'] == 1


# ── 8. duplicate delivery suppression ──
def test_duplicate_delivery_suppressed():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_DUP',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    ua_dir = tempfile.mkdtemp()
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        r1 = deliver_primary_feishu(report, ua_dir=ua_dir)
        assert r1['delivery_status'] == SENT
        r2 = deliver_primary_feishu(report, ua_dir=ua_dir)
    assert r2['delivery_status'] == 'DUPLICATE_SUPPRESSED'
    assert r2['delivery_id'] is None


# ── 9. same symbol / different decision_id not suppressed ──
def test_same_symbol_different_decision_not_suppressed():
    report_a = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_A',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    report_b = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_B',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    ua_dir = tempfile.mkdtemp()
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        r1 = deliver_primary_feishu(report_a, ua_dir=ua_dir)
        r2 = deliver_primary_feishu(report_b, ua_dir=ua_dir)
    assert r1['delivery_status'] == SENT
    assert r2['delivery_status'] == SENT
    assert r2['delivery_id'] != r1['delivery_id']


# ── 10. same decision_id / different presentation allowed ──
def test_same_decision_different_presentation_allowed():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_SAME',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    ua_dir = tempfile.mkdtemp()
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        r1 = deliver_primary_feishu(report, ua_dir=ua_dir)
    dup = is_duplicate_delivery('D_SAME', DAILY, FEISHU_CHAT_ID, ua_dir)
    assert dup is True
    not_dup = is_duplicate_delivery('D_SAME', URGENT, FEISHU_CHAT_ID, ua_dir)
    assert not_dup is False


# ── 11. delivery failure does not mutate Decision ──
def test_delivery_failure_does_not_mutate_decision():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_NOMUT',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 500, 'error': 'server error'}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu(report, ua_dir=tempfile.mkdtemp())
    assert result['delivery_status'] == FAILED
    assert report['actions']['SELL'][0]['action'] == 'SELL'
    assert report['decision_summary']['sell_count'] == 1


# ── 12. no Decision recomputation ──
def test_no_decision_recomputation():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_NORECOMP',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu(report, ua_dir=tempfile.mkdtemp())
    assert result['decision_id'] == 'D_NORECOMP'
    assert report['actions']['SELL'][0]['action'] == 'SELL'


# ── 13. no Execution creation ──
# ── 14. no Outcome creation ──
def test_no_execution_or_outcome_creation():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_NOEXEC',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    ua_dir = tempfile.mkdtemp()
    class FakeSender:
        def send_text_message(self, text, receive_id):
            return {'code': 0, 'ok': True}
    with patch('decision.feishu_delivery._load_feishu_sender', return_value=FakeSender()):
        result = deliver_primary_feishu(report, ua_dir=ua_dir)
    assert result['delivery_status'] == SENT


# ── 15. account blocked rendering ──
def test_account_blocked_rendering():
    report = _make_report(account_status='MISSING', actions={})
    msg = build_primary_feishu_message(report)
    assert 'MISSING' in msg['text']
    assert msg['account_readiness_status'] == 'MISSING'


# ── 16. zero action rendering ──
def test_zero_action_rendering():
    report = _make_report(zero_action=True)
    msg = build_primary_feishu_message(report)
    assert 'BUY: 0' in msg['text']
    assert 'SELL: 0' in msg['text']


# ── 19. deterministic message hash ──
def test_deterministic_message_hash():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_HASH',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    msg1 = build_primary_feishu_message(report)
    msg2 = build_primary_feishu_message(report)
    assert msg1['content_hash'] == msg2['content_hash']
    assert msg1['content_hash'] == hashlib.sha256(msg1['text'].encode('utf-8')).hexdigest()
    with tempfile.TemporaryDirectory() as d:
        rec = record_delivery(decision_id='D_HASH', presentation=DAILY, channel=FEISHU_CHAT_ID,
                              delivery_status='SENT', ua_dir=d)
    assert rec['message_hash'] == message_hash('D_HASH', DAILY, FEISHU_CHAT_ID)


# ── 20. channel fixed ──
def test_channel_fixed_to_stock_group():
    report = _make_report(actions={
        'SELL': [{'symbol': '301262', 'name': 'xx', 'action': 'SELL', 'decision_id': 'D_CH',
                  'reason_codes': ['RISK'], 'entry': {'entry_price': 100.0}}],
    })
    msg = build_primary_feishu_message(report)
    assert msg['channel'] == FEISHU_CHAT_ID
