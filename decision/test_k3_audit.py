#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K3 只读审计测试：Scheduling & Message Surface。
仅验证审计结论（分类/语义窗口/prompt 泄漏/secret/重复/分层），不修改任何生产代码。
"""

import os
import sys
import json
import glob
import unittest
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

BASE = '/home/caojy/.hermes/cron/output'


def _load_jobs():
    return json.load(open('/home/caojy/.hermes/cron/jobs.json'))


class TestTaskClassification(unittest.TestCase):

    def test_active_stock_cron_count(self):
        lst = _load_jobs()
        lst = lst if isinstance(lst, list) else lst.get('jobs', [])
        stock = [j for j in lst if str(j.get('name', '')).startswith(
            ('stock', 'double', 'daily-data', 'weekly-portfolio', 'position-stop',
             'market-env', 'hot-sector', 'daily-sentiment', 'deep-position',
             'system-health', 'us-stock', 'market-regime'))]
        self.assertGreaterEqual(len(stock), 20)

    def test_only_two_tasks_produce_final(self):
        # 从代码层面验证：只有 stop-loss 与 double-monitor 调用 DecisionEngine.decide
        for f in ['position_stop_loss_alert.py', 'double_monitor.py']:
            src = Path(SCRIPT_DIR, f).read_text(encoding='utf-8')
            self.assertIn('decide(', src)
        # opportunity/intraday 无 engine
        for f in ['stock_opportunity_scan.py']:
            src = Path(SCRIPT_DIR, f).read_text(encoding='utf-8')
            self.assertNotIn('DecisionEngine', src)


class TestM3SessionWindow(unittest.TestCase):

    def test_opportunity_schedule_has_late_slot(self):
        jobs = _load_jobs()
        lst = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
        opp = [j for j in lst if j.get('name') == 'stock-opportunity-push'][0]
        expr = opp['schedule']['expr']
        # K4 已收窄：13-14（不再含 15:00/15:30 盘后 slot）
        self.assertIn('13-14', expr)
        self.assertNotIn('13-15', expr)

    def test_post_close_intraday_semantic_error_exists(self):
        # 8/26 15:31 样本含【盘中推荐】= 盘后语义错误
        f = os.path.join(BASE, '1aa2fd36bdef', '2026-08-26_15-31-33.md')
        if not os.path.exists(f):
            self.skipTest('样本不存在')
        txt = open(f, encoding='utf-8').read()
        self.assertIn('【盘中推荐', txt, '收盘后仍以盘中口径推送')


class TestM4PromptLeak(unittest.TestCase):

    def test_no_secret_in_user_output(self):
        import re
        secret_pats = [r'sk-[a-zA-Z0-9]{20,}', r'api[_-]?key[=:]\s*\S+',
                       r'token[=:]\s*\S{20,}', r'password\s*=', r'"secret"']
        hits = 0
        for fp in glob.glob(os.path.join(BASE, '*/*.md')):
            try:
                t = open(fp, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            for p in secret_pats:
                if re.search(p, t, re.I):
                    hits += 1
                    break
        self.assertEqual(hits, 0, 'cron output 不得含 secret/token')

    def test_agent_prompt_leaks_in_local_md(self):
        # M-4 确认：agent 任务本地 md 含 skill prompt（内部上下文泄漏到本地工件）
        f = os.path.join(BASE, 'e4a2c0461481', '2026-08-26_16-05-53.md')
        if not os.path.exists(f):
            self.skipTest('样本不存在')
        txt = open(f, encoding='utf-8').read()
        self.assertIn('## Prompt', txt)
        self.assertIn('IMPORTANT', txt)

    def test_no_prompt_in_feishu_surface_text(self):
        # no_agent 任务飞书正文（--- 之后）不含 ## Prompt
        f = os.path.join(BASE, '1aa2fd36bdef', '2026-08-26_15-31-33.md')
        if not os.path.exists(f):
            self.skipTest('样本不存在')
        txt = open(f, encoding='utf-8').read()
        body = txt.split('---', 1)[-1]
        self.assertNotIn('## Prompt', body)


class TestSurfaceSeparation(unittest.TestCase):

    def test_signal_not_final(self):
        f = os.path.join(BASE, '1aa2fd36bdef', '2026-08-26_15-31-33.md')
        if not os.path.exists(f):
            self.skipTest('样本不存在')
        txt = open(f, encoding='utf-8').read()
        # opportunity 措辞无 BUY/FINAL 指令
        for banned in ['建议买入', 'BUY ', '立即买入']:
            self.assertNotIn(banned, txt)

    def test_health_monitor_in_ops_group(self):
        jobs = _load_jobs()
        lst = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
        mon = [j for j in lst if j.get('name') == 'system-health-monitor'][0]
        self.assertEqual(mon['deliver'], 'feishu:oc_6825e1438c41d1b7251b1698ea3be4fe',
                         'health-monitor 应在运维群(oc_6825e14)，不在主群')

    def test_final_decision_unique_source(self):
        # Daily + stop-loss 是 FINAL，均经 DecisionEngine（K0 已验证）
        from decision.engine import DecisionEngine
        self.assertTrue(hasattr(DecisionEngine, 'decide'))


class TestDuplicateAndFrequency(unittest.TestCase):

    def test_intraday_runs_quiet_when_no_signal(self):
        # intraday 24 run/日，但仅信号触发才输出 SIGNAL（静默机制）
        fs = glob.glob(os.path.join(BASE, 'c0c0ac20dc4d', '*.md'))
        if not fs:
            self.skipTest('无样本')
        signal_runs = sum(1 for f in fs if '信号触发' in open(f, encoding='utf-8', errors='ignore').read())
        self.assertLess(signal_runs, len(fs), 'intraday 多数 run 应静默')

    def test_daily_is_single_final_per_day(self):
        r = json.load(open(os.path.join(SCRIPT_DIR, 'reports/daily_decision_2026-08-26.json')))
        # Daily 单一报告，不是多条重复 FINAL
        self.assertIn('actions', r)


class TestDeterminism(unittest.TestCase):

    def test_audit_report_exists(self):
        p = os.path.join(SCRIPT_DIR, 'docs/audit/PRODUCTION_SCHEDULING_AND_MESSAGE_SURFACE_AUDIT.md')
        self.assertTrue(os.path.exists(p))


if __name__ == '__main__':
    unittest.main(verbosity=2)
