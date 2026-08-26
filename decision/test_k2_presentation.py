#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K2 测试：User Output Clarification。
只验证 Presentation / Classification，不验证业务决策。
"""

import os
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)


class TestPresentationTaxonomy(unittest.TestCase):

    def test_final_label_constants(self):
        from decision.presentation import (LABEL_FINAL, LABEL_URGENT, LABEL_SIGNAL,
                                            LABEL_INFO, LABEL_HEALTH)
        self.assertIn('FINAL', LABEL_FINAL)
        self.assertIn('URGENT', LABEL_URGENT)
        self.assertIn('SIGNAL', LABEL_SIGNAL)
        self.assertIn('INFO', LABEL_INFO)
        self.assertIn('HEALTH', LABEL_HEALTH)

    def test_debug_line_detection(self):
        from decision.presentation import is_debug_line
        self.assertTrue(is_debug_line('[BRANCH] ENTER_SELL_CHECK open_count=1'))
        self.assertTrue(is_debug_line('  File "/home/caojy/x.py", line 12'))
        self.assertTrue(is_debug_line('[REPORT] Daily Decision Report: /path'))
        self.assertFalse(is_debug_line('301262 → **SELL**'))
        self.assertFalse(is_debug_line('数据刷新正常'))

    def test_sanitize_removes_debug_keeps_content(self):
        from decision.presentation import sanitize_user_surface
        text = ("【URGENT · FINAL】SELL 301262\n"
                "[BRANCH] ENTER_SELL_CHECK open_count=1\n"
                "Decision ID: abc123\n"
                "  File \"/home/caojy/x.py\", line 12, in foo\n")
        clean, removed = sanitize_user_surface(text)
        self.assertNotIn('[BRANCH]', clean)
        self.assertNotIn('/home/caojy/', clean)
        self.assertIn('SELL 301262', clean)
        self.assertIn('Decision ID: abc123', clean)
        self.assertGreaterEqual(removed, 2)

    def test_sanitize_traceback_fallback(self):
        from decision.presentation import sanitize_user_surface
        text = "Traceback (most recent call last):\n  File \"/x.py\", line 12\nNormal line"
        clean, _ = sanitize_user_surface(text)
        self.assertNotIn('Traceback', clean)
        self.assertIn('Normal line', clean)
        self.assertNotIn('/x.py', clean)


class TestDailyFinalLabel(unittest.TestCase):

    def test_daily_report_contains_final_label(self):
        from decision.daily_decision_contract import format_human_readable
        report = {
            'meta': {'report_date': '2026-08-26', 'as_of_time': '2026-08-26T21:00'},
            'market': {'regime_label': '高波动', 'regime_score': 50, 'position_scale': 0.5},
            'data_health': {'market_regime': 'VALID'},
            'real_portfolio': {'source': 'FEISHU_BITABLE', 'data_quality': 'PARTIAL',
                               'freshness': 'FRESH', 'cash': None, 'total_asset': None,
                               'holdings_value': 0, 'exposure': 0, 'drawdown': 0,
                               'drawdown_status': 'OK'},
            'actions': {'SELL': [{'symbol': '600001', 'name': 'T', 'action': 'SELL',
                                  'reason_codes': ['STOP_LOSS'], 'decision_id': 'did_1'}]},
            'decision_summary': {'buy_count': 0, 'add_count': 0, 'hold_count': 0,
                                 'reduce_count': 0, 'sell_count': 1, 'no_trade_count': 0},
        }
        out = format_human_readable(report)
        self.assertIn('【FINAL】SELL', out)
        self.assertIn('Decision ID: did_1', out)
        self.assertIn('### MARKET', out)  # 非交易信息仍保留

    def test_daily_final_requires_decision_id_present(self):
        from decision.daily_decision_contract import format_human_readable
        report = {
            'meta': {'report_date': '2026-08-26', 'as_of_time': 'x'},
            'market': {}, 'data_health': {}, 'real_portfolio': {},
            'actions': {'BUY': [{'symbol': '600001', 'name': 'T', 'action': 'BUY',
                                 'reason_codes': ['ENTRY'], 'decision_id': 'did_2'}]},
            'decision_summary': {'buy_count': 1, 'add_count': 0, 'hold_count': 0,
                                 'reduce_count': 0, 'sell_count': 0, 'no_trade_count': 0},
        }
        out = format_human_readable(report)
        self.assertIn('【FINAL】BUY', out)
        self.assertIn('did_2', out)


class TestUrgentLabel(unittest.TestCase):

    def test_urgent_format_has_urgent_final_label(self):
        import position_stop_loss_alert as m
        from decision.engine import DecisionEngine
        from decision.adapters import position_ctx
        eng = DecisionEngine(strategy='v1_double', config_version='k2', code_version='k2')
        ctx = position_ctx(symbol='600001', name='T', regime_label='震荡', regime_score=50,
                           permission={'status': 'ALLOW', 'new_entry': True, 'add_position': True,
                                       'reduce_position': True, 'exit_position': True},
                           permission_status='ALLOW', data_health='VALID', exit_signal='SELL',
                           exit_triggers=['STOP_LOSS'], drawdown=0, position_count=1,
                           current_exposure=0.02, current_position=0.02, portfolio_risk='OK')
        dec = eng.decide(ctx)
        out = m.format_decisions([{'decision': dec, 'exit_reasons': ['STOP_LOSS']}])
        self.assertTrue(out.startswith('【URGENT · FINAL】'))
        self.assertIn('Decision ID', out)
        self.assertIn('**SELL**', out)
        self.assertNotIn('[BRANCH]', out)  # M-5 过滤


class TestDeepReviewDowngrade(unittest.TestCase):
    """M-1：deep-position-review prompt 不得产出命令式交易措辞"""

    def test_prompt_forbids_command_wording(self):
        import json
        jobs = json.load(open('/home/caojy/.hermes/cron/jobs.json'))
        for j in (jobs if isinstance(jobs, list) else jobs.get('jobs', [])):
            if j.get('name') == 'deep-position-review':
                p = j['prompt']
                self.assertIn('INFORMATION 层分析参考', p)
                self.assertIn('禁止使用', p)
                self.assertNotIn('建议减仓/持有/观察清单', p)  # 旧命令式已移除
                return
        self.fail('deep-position-review job not found')


class TestNoSecondDecisionOwner(unittest.TestCase):

    def test_presentation_does_not_call_engine(self):
        """presentation 模块不得 import DecisionEngine 或调用 decide（docstring 提及不算）"""
        src = Path(SCRIPT_DIR, 'decision/presentation.py').read_text(encoding='utf-8')
        self.assertNotIn('import DecisionEngine', src)
        self.assertNotIn('DecisionEngine(', src)
        self.assertNotIn('decide(', src)

    def test_signal_scripts_no_decision_id_forgery(self):
        # opportunity/intraday/hot-sector 不产生 decision_id（非 Final）
        for f in ['stock_opportunity_scan.py']:
            src = Path(SCRIPT_DIR, f).read_text(encoding='utf-8')
            self.assertNotIn('decision_id', src)


class TestDebugIsolation(unittest.TestCase):

    def test_double_monitor_stdout_no_debug_markers(self):
        # 生产等效 safe run 的 stdout 不含 [BRANCH]/[REPORT]
        log = open('/tmp/k2_run2.log').read()
        self.assertNotIn('[BRANCH]', log)
        # 但工程日志文件有完整记录
        debug_log = Path(SCRIPT_DIR, 'logs/double_monitor_debug.log')
        self.assertTrue(debug_log.exists())
        self.assertIn('[BRANCH]', debug_log.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
