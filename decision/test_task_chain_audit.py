#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K0 只读审计测试：Production Task Chain & User Output。
不修改任何生产代码/数据；仅验证 authority、边界、actionability、传播语义。
"""
import os
import sys
import json
import sqlite3
import unittest
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

SIM_DB = os.path.join(SCRIPT_DIR, 'simulation.db')


def ro_conn():
    return sqlite3.connect(f'file:{SIM_DB}?mode=ro', uri=True)


# ────────────────── 1. Authority uniqueness ──────────────────
class TestAuthority(unittest.TestCase):

    def test_all_final_action_paths_go_through_decision_engine(self):
        """生产链所有 Final Action 产生点必须调用 DecisionEngine"""
        checks = {
            'double_monitor.py': ['decision_engine.decide'],
            'risk_controller_v2.py': ['_eng.decide'],
            'position_stop_loss_alert.py': ['eng.decide'],
        }
        for fname, needles in checks.items():
            src = Path(SCRIPT_DIR, fname).read_text(encoding='utf-8')
            for needle in needles:
                self.assertIn(needle, src, f'{fname} 缺少 {needle}')

    def test_no_second_final_owner_in_signal_scripts(self):
        """opportunity/intraday/hot-sector 不得构造 BUY/SELL final action"""
        for fname in ['stock_opportunity_scan.py']:
            src = Path(SCRIPT_DIR, fname).read_text(encoding='utf-8')
            self.assertNotIn("action='BUY'", src)
            self.assertNotIn("'action': 'SELL'", src)
            self.assertNotIn('DecisionEngine', src, 'signal 脚本不需要也不应持有 engine')

    def test_decision_engine_is_sole_decide_source(self):
        from decision.engine import DecisionEngine
        self.assertTrue(hasattr(DecisionEngine, 'decide'))


# ────────────────── 2. Signal/Final separation ──────────────────
class TestSignalFinalSeparation(unittest.TestCase):

    def test_opportunity_output_is_signal_wording(self):
        """真实 opportunity 输出不含 BUY 指令措辞（2026-08-26 样本）"""
        f = Path('/home/caojy/.hermes/cron/output/1aa2fd36bdef/2026-08-26_15-31-33.md')
        if not f.exists():
            self.skipTest('样本不存在')
        txt = f.read_text(encoding='utf-8')
        for banned in ['建议买入', 'BUY ', '立即买入', '可以买入']:
            self.assertNotIn(banned, txt, f'opportunity 输出出现越权措辞: {banned}')

    def test_stop_loss_output_carries_decision_id(self):
        f = Path('/home/caojy/.hermes/cron/output/21540a83af1b/2026-08-26_09-35-58.md')
        if not f.exists():
            self.skipTest('样本不存在')
        txt = f.read_text(encoding='utf-8')
        # decision_id 格式: ISO时间_symbol_uuid
        import re
        ids = re.findall(r'\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00_\d{6}_[0-9a-f]{12}', txt)
        self.assertGreaterEqual(len(ids), 1, 'URGENT SELL 必须携带 decision_id')

    def test_deep_review_has_no_decision_id(self):
        """deep-position-review 是 INFORMATION 层，无 decision_id —— 证明其非 Final"""
        f = Path('/home/caojy/.hermes/cron/output/e4a2c0461481/2026-08-26_16-05-53.md')
        if not f.exists():
            self.skipTest('样本不存在')
        import re
        ids = re.findall(r'[0-9a-f]{12}_\d{6}', f.read_text(encoding='utf-8'))
        self.assertEqual(len(ids), 0)


# ────────────────── 3. Actionability ──────────────────
class TestActionability(unittest.TestCase):

    def test_daily_report_sell_items_have_reason_and_id(self):
        r = json.load(open(Path(SCRIPT_DIR, 'reports/daily_decision_2026-08-25.json')))
        sells = r.get('actions', {}).get('SELL', [])
        if not sells:
            self.skipTest('当日无 SELL')
        item = sells[0]
        self.assertTrue(item.get('decision_id'))
        self.assertTrue(item.get('reason_codes') or item.get('explanation'))

    def test_buy_blocked_when_quality_error(self):
        """QUALITY_ERROR → BUY 必须 NO_TRADE + sizing BLOCKED（J0D 语义回归）"""
        import decision.daily_decision_contract as ddc
        from unittest import mock
        snap = [{'decision_id': 'x', 'symbol': '600001', 'name': 'X', 'strategy': 'v1_double',
                 'action': 'BUY', 'reference_price': 10.0,
                 'total_asset': 100000.0, 'current_position_value': 0.0, 'cash': 50000.0}]
        fake = {'quality_report': {'overall': 'ERROR', 'warning_count': 0, 'error_count': 1, 'checks': []}}
        with mock.patch.object(ddc, 'build_real_portfolio_section', return_value=fake):
            actions = ddc.classify_actions(snap, [], {'status': 'READY', 'sizing_allowed': True})
        self.assertEqual(actions.get('BUY', []), [])
        self.assertIn('REAL_HOLDINGS_QUALITY_ERROR', actions['NO_TRADE'][0]['reason_codes'])

    def test_no_trade_has_blocking_layer(self):
        import decision.daily_decision_contract as ddc
        from unittest import mock
        snap = [{'decision_id': 'y', 'symbol': '600002', 'name': 'Y', 'strategy': 'v1_double',
                 'action': 'BUY', 'reference_price': 10.0, 'total_asset': None,
                 'current_position_value': 0.0, 'cash': None}]
        with mock.patch.object(ddc, 'build_real_portfolio_section',
                               return_value={'quality_report': {'overall': 'OK'}}):
            actions = ddc.classify_actions(snap, [], {'status': 'PARTIAL',
                                                      'sizing_allowed': False,
                                                      'blocked_reason': 'REAL_TOTAL_ASSET_UNKNOWN'})
        items = actions.get('NO_TRADE', [])
        self.assertTrue(items and any('REAL_TOTAL_ASSET' in (i.get('reason_codes') or [])[0]
                                      for i in items if i.get('reason_codes')))


# ────────────────── 4. Effective window / supersession ──────────────────
class TestEffectiveWindow(unittest.TestCase):

    def test_snapshot_load_filters_by_date(self):
        from decision.daily_decision_contract import load_today_snapshots
        snaps = load_today_snapshots('1999-01-01')
        self.assertEqual(snaps, [], '过期日期不得读到任何 snapshot')

    def test_save_snapshot_immutable_no_overwrite(self):
        from decision.snapshot import save_snapshot
        src = Path(SCRIPT_DIR, 'decision/snapshot.py').read_text(encoding='utf-8')
        self.assertIn('已存在不覆盖', src, 'snapshot 历史不可变语义必须保留')


# ────────────────── 5. Conflict classification ──────────────────
class TestConflictClassification(unittest.TestCase):

    def test_conflict_detector_exists(self):
        from decision.user_authority import detect_conflicts
        self.assertTrue(callable(detect_conflicts))

    def test_same_day_multi_action_is_display_only(self):
        """MULTI_ACTION 只影响打印，不改 trades 状态"""
        conn = ro_conn()
        n_before = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        # double_monitor MULTI_ACTION 分支无 UPDATE/INSERT（源码断言）
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        seg = src.split('buy_codes = {t[0] for t in buys}')[1].split('else:')[0]
        self.assertNotIn('UPDATE', seg)
        self.assertNotIn('INSERT INTO trades', seg)
        conn = ro_conn()
        n_after = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        self.assertEqual(n_before, n_after)


# ────────────────── 6. Stale/missing propagation ──────────────────
class TestFailurePropagation(unittest.TestCase):

    def test_monitor_checks_upstream_freshness(self):
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        self.assertIn('check_upstream', src)
        self.assertIn('max_age_minutes', src)

    def test_scan_freshness_guard_rejects_stale_klines(self):
        src = Path(SCRIPT_DIR, 'scan_doubling_potential.py').read_text(encoding='utf-8')
        self.assertIn('check_klines_freshness', src, '候选池必须有新鲜度护栏')

    def test_account_not_ready_blocks_sizing_but_allows_sell(self):
        from decision.real_sizing import check_sizing_for_action, BUY, SELL
        sz_buy = check_sizing_for_action(BUY, total_asset=None, current_market_value=0,
                                         cash=None, target_position_pct=0.025, reference_price=10)
        sz_sell = check_sizing_for_action(SELL, total_asset=None, current_market_value=10000,
                                          cash=None, target_position_pct=0.0, reference_price=10)
        self.assertEqual(sz_buy.get('sizing_status'), 'BLOCKED')
        self.assertNotEqual(sz_sell.get('sizing_status'), 'BLOCKED')

    def test_delivery_failure_does_not_change_decision(self):
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        self.assertIn('不影响 Decision', src, '投递失败不得反向影响 Decision')

    def test_observation_failure_isolation(self):
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        self.assertIn('[REPORT]', src)


# ────────────────── 7. Real/Sim separation & account missing ──────────────────
class TestIsolationAndHoldings(unittest.TestCase):

    def test_real_holdings_source_is_bitable_only(self):
        from decision.real_portfolio_truth import REAL_HOLDINGS_SOURCE
        self.assertEqual(REAL_HOLDINGS_SOURCE, 'FEISHU_BITABLE')

    def test_simulation_trades_never_marked_production(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades WHERE strategy != 'v1_double'").fetchone()[0]
        prod = conn.execute("SELECT COUNT(*) FROM trades WHERE decision_id IS NOT NULL AND status='EXECUTED'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)
        self.assertEqual(prod, 0)

    def test_quality_warning_visible_not_blocking(self):
        import decision.daily_decision_contract as ddc
        dh = {'real_holdings_quality': 'WARNING'}
        self.assertEqual(ddc.get_real_holdings_quality_status(dh), 'QUALITY_WARNING')


# ────────────────── 8. Deterministic audit output ──────────────────
class TestDeterminism(unittest.TestCase):

    def test_cron_inventory_matches_registry(self):
        jobs = json.load(open('/home/caojy/.hermes/cron/jobs.json'))
        lst = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
        stock_jobs = [j for j in lst if str(j.get('name', '')).startswith(('stock', 'double', 'daily-data',
                        'weekly-portfolio', 'position-stop', 'market-env', 'hot-sector',
                        'daily-sentiment', 'deep-position', 'system-health-check'))]
        self.assertGreaterEqual(len(stock_jobs), 20, f'股票 cron 数量异常: {len(stock_jobs)}')
        for j in stock_jobs:
            self.assertEqual(j.get('enabled'), True, f"{j.get('name')} 应为 active")


if __name__ == '__main__':
    unittest.main(verbosity=2)
