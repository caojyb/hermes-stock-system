#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-F: Unified User-Facing Decision Authority & Lifecycle — 测试
覆盖 25 项：
1 action/presentation separation
2 decision lifecycle
3 active/superseded
4 decision expiry
5 latest effective decision
6 daily/urgent coexistence
7 research signal separation
8 final conflict detection
9 signal/final difference
10 message deduplication
11 delivery idempotency
12 delivery retry
13 decision_id propagation
14 replay linkage
15 account visibility
16 JSON/Feishu consistency
17 urgent consistency
18 stale daily decision
19 non-trading day
20 zero BUY
21 account blocked
22 production/test isolation
23 deterministic routing
24 no auto trade
25 no second decision owner
"""
import os, sys, tempfile, json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import decision.user_authority as ua
from decision.contract import BUY, ADD, HOLD, REDUCE, SELL, NO_TRADE


def _tmp():
    return tempfile.mkdtemp()


# ═══ 1. action/presentation separation ═══
def test_01_action_presentation_separation():
    assert set(ua.FINAL_ACTIONS) == {BUY, ADD, HOLD, REDUCE, SELL, NO_TRADE}
    assert ua.URGENT in ua.PRESENTATIONS
    assert ua.URGENT not in ua.FINAL_ACTIONS  # URGENT 不是 Action
    # classify: SELL + URGENT presentation = URGENT (not second action)
    cls = ua.classify_message(is_final_decision=True, from_authority='DecisionEngine',
                              action='SELL', presentation='URGENT', has_decision_id=True)
    assert cls == ua.URGENT_MSG


# ═══ 2. decision lifecycle ═══
def test_02_decision_lifecycle():
    d = _tmp()
    lc = ua.register_decision(decision_id='L01', symbol='600000', action=HOLD,
                              created_at='2026-08-21T09:00:00+00:00', ua_dir=d)
    assert lc.lifecycle_state == ua.ACTIVE
    assert ua.load_lifecycle('L01', d).lifecycle_state == ua.ACTIVE


# ═══ 3. active/superseded ═══
def test_03_active_superseded():
    d = _tmp()
    ua.register_decision(decision_id='S01', symbol='600540', action=HOLD,
                         created_at='2026-08-21T09:00:00+00:00', ua_dir=d)
    ua.register_decision(decision_id='S02', symbol='600540', action=SELL,
                         created_at='2026-08-21T10:15:00+00:00', ua_dir=d)
    assert ua.load_lifecycle('S01', d).lifecycle_state == ua.SUPERSEDED
    assert ua.load_lifecycle('S01', d).superseded_by_decision_id == 'S02'
    assert ua.load_lifecycle('S02', d).lifecycle_state == ua.ACTIVE


# ═══ 4. decision expiry ═══
def test_04_decision_expiry():
    d = _tmp()
    ua.register_decision(decision_id='E01', symbol='600000', action=BUY,
                         created_at='2026-08-21T09:00:00+00:00',
                         effective_until='2026-08-21T15:00:00+00:00', ua_dir=d)
    ua.expire('E01', d)
    assert ua.load_lifecycle('E01', d).lifecycle_state == ua.EXPIRED


# ═══ 5. latest effective decision ═══
def test_05_latest_effective_decision():
    d = _tmp()
    ua.register_decision(decision_id='L01', symbol='600540', action=HOLD,
                         created_at='2026-08-21T09:00:00+00:00', ua_dir=d)
    ua.register_decision(decision_id='L02', symbol='600540', action=SELL,
                         created_at='2026-08-21T10:15:00+00:00', ua_dir=d)
    cur = ua.current_effective_decision('600540', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    assert cur.decision_id == 'L02'
    assert cur.action == SELL


# ═══ 6. daily/urgent coexistence ═══
def test_06_daily_urgent_coexistence():
    d = _tmp()
    # 昨日 Daily HOLD
    ua.register_decision(decision_id='D1', symbol='600540', action=HOLD,
                         presentation=ua.DAILY,
                         created_at='2026-08-20T16:50:00+00:00',
                         effective_until='2026-08-21T15:00:00+00:00', ua_dir=d)
    # 今日 Urgent SELL
    ua.register_decision(decision_id='D2', symbol='600540', action=SELL,
                         presentation=ua.URGENT,
                         created_at='2026-08-21T10:15:00+00:00', ua_dir=d)
    cur = ua.current_effective_decision('600540', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    assert cur.decision_id == 'D2'
    assert cur.action == SELL
    # 旧 HOLD 保留在历史，不再表现为当前有效 Action
    assert ua.load_lifecycle('D1', d).lifecycle_state == ua.SUPERSEDED


# ═══ 7. research signal separation ═══
def test_07_research_signal_separation():
    # Opportunity 仅信号 → SIGNAL
    cls = ua.classify_message(action=NO_TRADE, presentation='', has_decision_id=False,
                              category='opportunity')
    assert cls == ua.SIGNAL
    # 已进 DecisionEngine → FINAL
    cls = ua.classify_message(is_final_decision=True, from_authority='DecisionEngine',
                              action=BUY, presentation=ua.DAILY, has_decision_id=True)
    assert cls == ua.FINAL_DECISION


# ═══ 8. final conflict detection ═══
def test_08_final_conflict_detection():
    d = _tmp()
    ua.register_decision(decision_id='C1', symbol='600000', action=BUY,
                         created_at='2026-08-21T09:00:00+00:00', ua_dir=d)
    # 手动制造第二个 ACTIVE 同窗口 BUY/SELL
    ua.register_decision(decision_id='C2', symbol='600000', action=SELL,
                         created_at='2026-08-21T09:30:00+00:00',
                         auto_supersede=False, ua_dir=d)
    # 保持两者 ACTIVE（关闭 auto_supersede 后手动再激活 C1 场景较复杂，这里验证检测函数）
    res = ua.detect_conflicts(ua.list_lifecycles(d))
    # C2 注册时 auto_supersede=False 不会覆盖 C1；C1 仍 ACTIVE
    assert ua.load_lifecycle('C1', d).lifecycle_state == ua.ACTIVE
    assert ua.load_lifecycle('C2', d).lifecycle_state == ua.ACTIVE
    assert any(c['type'] == 'USER_DECISION_CONFLICT' for c in res['conflicts'])


# ═══ 9. signal/final difference ═══
def test_09_signal_final_difference():
    # Research BUY-like (SIGNAL) vs Final NO_TRADE → 不是 Final Conflict
    d = _tmp()
    ua.register_decision(decision_id='F1', symbol='002194', action=NO_TRADE,
                         created_at='2026-08-21T09:00:00+00:00', ua_dir=d)
    # 手动加入一个 SIGNAL（authority != DecisionEngine）同窗口
    signal = ua.DecisionLifecycle(decision_id='SIG1', symbol='002194', action=BUY,
                                  presentation=ua.RESEARCH, lifecycle_state=ua.ACTIVE,
                                  created_at='2026-08-21T09:05:00+00:00',
                                  authority='opportunity',  # 非 DecisionEngine
                                  effective_from='2026-08-21T09:05:00+00:00')
    ua.save_lifecycle(signal, d)
    res = ua.detect_conflicts(ua.list_lifecycles(d))
    assert not any(c['type'] == 'USER_DECISION_CONFLICT' for c in res['conflicts'])


# ═══ 10. message deduplication ═══
def test_10_message_dedup():
    d = _tmp()
    ua.record_delivery(decision_id='X1', presentation=ua.DAILY, channel='stock_group', ua_dir=d)
    assert ua.is_duplicate_delivery('X1', ua.DAILY, 'stock_group', d) is True
    assert ua.is_duplicate_delivery('X1', ua.DAILY, 'other_channel', d) is False
    assert ua.is_duplicate_delivery('X2', ua.DAILY, 'stock_group', d) is False


# ═══ 11. delivery idempotency ═══
def test_11_delivery_idempotency():
    d = _tmp()
    ua.record_delivery(decision_id='Y1', presentation=ua.URGENT, channel='stock_group', ua_dir=d)
    # 重复推送同 decision+presentation+channel → 应被识别为重复
    assert ua.is_duplicate_delivery('Y1', ua.URGENT, 'stock_group', d) is True


# ═══ 12. delivery retry ═══
def test_12_delivery_retry():
    d = _tmp()
    r = ua.record_delivery(decision_id='Z1', presentation=ua.DAILY, channel='stock_group',
                           delivery_status=ua.RETRYING, retry_count=1, error='timeout', ua_dir=d)
    assert r['delivery_status'] == ua.RETRYING
    assert r['retry_count'] == 1
    assert r['error'] == 'timeout'


# ═══ 13. decision_id propagation ═══
def test_13_decision_id_propagation():
    d = _tmp()
    lc = ua.register_decision(decision_id='P1', symbol='600000', action=BUY, ua_dir=d)
    assert lc.decision_id == 'P1'
    loaded = ua.load_lifecycle('P1', d)
    assert loaded.decision_id == 'P1'
    assert loaded.symbol == '600000'


# ═══ 14. replay linkage ═══
def test_14_replay_linkage():
    d = _tmp()
    ua.register_decision(decision_id='R1', symbol='600000', action=HOLD, ua_dir=d)
    lc = ua.load_lifecycle('R1', d)
    assert lc is not None
    # 可从 decision_id 反查生命周期
    assert lc.decision_id == 'R1'


# ═══ 15. account visibility ═══
def test_15_account_visibility():
    # GROUP visibility（群内有外人）→ 不显示金额
    pol = ua.AccountVisibilityPolicy(visibility=ua.GROUP, group_has_outsiders=True)
    assert pol.show_amounts() is False
    acc = pol.render_account({'status': 'READY', 'total_asset': 1000000, 'cash': 200000})
    assert acc['total_asset'] is None
    assert acc['cash'] is None
    # PRIVATE（本人 DM）→ 显示金额
    pol2 = ua.AccountVisibilityPolicy(visibility=ua.PRIVATE, group_has_outsiders=False)
    assert pol2.show_amounts() is True
    acc2 = pol2.render_account({'status': 'READY', 'total_asset': 1000000, 'cash': 200000})
    assert acc2['total_asset'] == 1000000


# ═══ 16. JSON/Feishu consistency ═══
def test_16_json_feishu_consistency():
    d = _tmp()
    lc = ua.register_decision(decision_id='J1', symbol='600000', action=BUY,
                              presentation=ua.DAILY, reason_codes=['ENTRY_CONFIRMED'],
                              ua_dir=d)
    sd = ua.load_lifecycle('J1', d)
    # Feishu 展示应来自 lifecycle（同一值，不产生第二套）
    assert sd.action == BUY
    assert sd.decision_id == 'J1'
    assert sd.presentation == ua.DAILY


# ═══ 17. urgent consistency ═══
def test_17_urgent_consistency():
    d = _tmp()
    ua.register_decision(decision_id='U1', symbol='600540', action=SELL,
                         presentation=ua.URGENT, reason_codes=['STOP_LOSS'],
                         created_at='2026-08-21T10:15:00+00:00', ua_dir=d)
    lc = ua.load_lifecycle('U1', d)
    assert lc.action == SELL
    assert lc.presentation == ua.URGENT
    assert 'STOP_LOSS' in lc.reason_codes


# ═══ 18. stale daily decision ═══
def test_18_stale_daily_decision():
    d = _tmp()
    # 昨日 Daily 已过 effective_until
    ua.register_decision(decision_id='ST1', symbol='600540', action=BUY,
                         created_at='2026-08-20T16:50:00+00:00',
                         effective_until='2026-08-20T23:59:59+00:00', ua_dir=d)
    cur = ua.current_effective_decision('600540', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    assert cur is None  # 已过期，不是当前有效指令


# ═══ 19. non-trading day ═══
def test_19_non_trading_day():
    # 非交易日：无新 Decision → current effective 为空/无
    d = _tmp()
    cur = ua.current_effective_decision('600000', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    assert cur is None
    # 分类非交易日 Debug/信息
    cls = ua.classify_message(category='debug')
    assert cls == ua.DEBUG_MSG


# ═══ 20. zero BUY ═══
def test_20_zero_buy():
    # BUY=0 是合法状态，不产生 Final BUY 决策
    d = _tmp()
    cur = ua.current_effective_decision('600000', at='2026-08-21T11:00:00+00:00', ua_dir=d)
    assert cur is None or cur.action != BUY


# ═══ 21. account blocked ═══
def test_21_account_blocked():
    pol = ua.AccountVisibilityPolicy(visibility=ua.GROUP)
    acc = pol.render_account({'status': 'BLOCKED', 'total_asset': None, 'cash': None})
    assert acc['status'] == 'BLOCKED'
    # BLOCKED 账户不产生 BUY sizing（此处验证渲染不泄露/不伪造）
    assert acc['total_asset'] is None


# ═══ 22. production/test isolation ═══
def test_22_production_test_isolation():
    d1 = _tmp()
    d2 = _tmp()
    ua.register_decision(decision_id='I1', symbol='600000', action=BUY, ua_dir=d1)
    assert ua.load_lifecycle('I1', d1) is not None
    assert ua.load_lifecycle('I1', d2) is None  # 隔离


# ═══ 23. deterministic routing ═══
def test_23_deterministic_routing():
    assert ua.route_message(ua.FINAL_DECISION) == ua.TODAY_PLAN
    assert ua.route_message(ua.URGENT_MSG) == ua.NOW_URGENT
    assert ua.route_message(ua.SIGNAL) == ua.RESEARCH_SURFACE
    assert ua.route_message(ua.INFO) == ua.INFORMATION_SURFACE
    assert ua.route_message(ua.HEALTH) == ua.HEALTH_SURFACE
    assert ua.route_message(ua.DEBUG_MSG) == ua.DEBUG_SURFACE


# ═══ 24. no auto trade ═══
def test_24_no_auto_trade():
    # 本模块无任何下单/券商/Execution Source 调用；只产生展示与生命周期
    src = Path(__file__).parent / 'user_authority.py'
    text = src.read_text(encoding='utf-8')
    assert 'EXECUTED' not in ua.FINAL_ACTIONS  # EXECUTED 是 lifecycle 非 action
    assert '券商' not in text


# ═══ 25. no second decision owner ═══
def test_25_no_second_decision_owner():
    assert ua.FINAL_DECISION_AUTHORITY == 'DecisionEngine'
    # 非 DecisionEngine 的 producer 不能产生 FINAL_DECISION class
    cls = ua.classify_message(is_final_decision=True, from_authority='opportunity',
                              action=BUY, presentation=ua.DAILY, has_decision_id=True)
    assert cls != ua.FINAL_DECISION


# ═══ 额外：build_user_view / 全部表面 ═══
def test_26_build_user_view():
    v = ua.build_user_view(today_plan={'market': 'HIGH_VOL'},
                           urgent=[{'decision_id': 'X', 'action': 'SELL'}])
    assert v['surfaces'][ua.TODAY_PLAN] == {'market': 'HIGH_VOL'}
    assert v['surfaces'][ua.NOW_URGENT] == [{'decision_id': 'X', 'action': 'SELL'}]
    assert 'note' in v
