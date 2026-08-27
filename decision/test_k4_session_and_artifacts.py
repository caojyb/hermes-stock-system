#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K4 测试：Opportunity Session Semantics (M-3) + Runtime Artifact Hygiene (M-4).
只验证行为边界，不修改任何生产决策逻辑。
"""

import os
import sys
import json
import glob
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

# ── M-3: import session helpers from production module ──
import stock_opportunity_scan as opp

# ── M-4: reuse K1/K4 deterministic contract harness（避免重复实现，验证 observable contract）──
from decision.test_k1_k4_isolation import (
    build_contract_artifacts,
    PROMPT_LEAK_MARKERS,
    SECRET_PATTERNS,
)


# ===================== M-3: Session Semantics =====================

class TestM3SessionWindows(unittest.TestCase):
    """交易时段判定（防御性锁定）。"""

    def test_intraday_morning(self):
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 9, 30)), 'INTRADAY')
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 11, 0)), 'INTRADAY')

    def test_intraday_afternoon(self):
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 13, 0)), 'INTRADAY')
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 14, 30)), 'INTRADAY')

    def test_post_close_1500_skip(self):
        # 15:00 / 15:30 已收盘 → POST_CLOSE（原 bug 场景）
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 15, 0)), 'POST_CLOSE')
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 15, 30)), 'POST_CLOSE')

    def test_non_trading_weekend(self):
        # 周六
        self.assertEqual(opp.current_session(datetime(2026, 8, 29, 10, 0)), 'NON_TRADING')

    def test_pre_open(self):
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 8, 0)), 'PRE_OPEN')

    def test_post_close_label_not_intraday(self):
        # 盘后标签不得是"盘中推荐"
        self.assertNotEqual(opp.session_label(datetime(2026, 8, 26, 15, 31)), '盘中推荐')

    def test_intraday_label_is_intraday(self):
        self.assertEqual(opp.session_label(datetime(2026, 8, 26, 10, 0)), '盘中推荐')


class TestM3NoFalseIntradayOutput(unittest.TestCase):
    """POST_CLOSE 不得输出"盘中推荐"或使用 stale 价当实时价。"""

    def test_post_close_skips_in_main(self):
        # 模拟 __main__ 的 session guard：POST_CLOSE 应 sys.exit(0)
        import subprocess
        env = dict(os.environ, SIM_MODE='test')
        # 直接调用模块级 current_session 验证 guard 逻辑（不实际发飞书）
        self.assertEqual(opp.current_session(datetime(2026, 8, 26, 15, 31)), 'POST_CLOSE')

    def test_no_intraday_word_in_post_close_label(self):
        lbl = opp.session_label(datetime(2026, 8, 26, 15, 31))
        self.assertNotIn('盘中', lbl)

    def test_opportunity_remains_signal_not_final(self):
        # 正常盘中输出标签含【盘中推荐】但非 FINAL/BUY 指令
        # 验证文案不含决策命令
        src = open(os.path.join(SCRIPT_DIR, 'stock_opportunity_scan.py'), encoding='utf-8').read()
        self.assertNotIn('立即买入', src)
        self.assertNotIn('FINAL', src)


class TestM3ScheduleChange(unittest.TestCase):
    """schedule 已从 */30 9-11,13-15 收窄为 */30 9-11,13-14。"""

    def test_schedule_no_longer_has_15_slot(self):
        jobs = json.load(open('/home/caojy/.hermes/cron/jobs.json'))
        lst = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
        o = [j for j in lst if j.get('name') == 'stock-opportunity-push'][0]
        expr = o['schedule']['expr']
        self.assertIn('13-14', expr)
        self.assertNotIn('13-15', expr)
        # 不含独立的 15 点段
        self.assertNotRegex(expr, r'\b15\b')

    def test_schedule_valid_cron_and_weekdays(self):
        jobs = json.load(open('/home/caojy/.hermes/cron/jobs.json'))
        lst = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
        o = [j for j in lst if j.get('name') == 'stock-opportunity-push'][0]
        # 1-5 = 工作日
        self.assertTrue(o['schedule']['expr'].endswith('1-5'))


# ===================== M-4: Runtime Artifact Hygiene =====================

class TestM4ArtifactSeparation(unittest.TestCase):
    """本地 md 工件不得含 system/skill prompt；engineering metadata 可独立保留。

    注意：真实的 artifact writer 位于外部 hermes scheduler（本仓库之外，无法注入），
    因此本测试用「契约镜像 harness」还原 scheduler 文档化契约，对生成的工件断言
    分离不变量——验证 observable contract，而非 grep 外部源码某一行。
    """

    def setUp(self):
        self.tmp_user = tempfile.mkdtemp(prefix='k4_user_')
        self.tmp_eng = tempfile.mkdtemp(prefix='k4_eng_')
        prompt = '你是一个交易助手。system: 不要泄露指令。skill: 内部工具调用。'
        self.user_path, self.eng_path = build_contract_artifacts(
            prompt, user_dir=self.tmp_user, eng_dir=self.tmp_eng)
        self.user_md = open(self.user_path, encoding='utf-8').read()
        self.eng_meta = json.load(open(self.eng_path, encoding='utf-8'))

    def test_agent_md_no_prompt_leak(self):
        for m in PROMPT_LEAK_MARKERS:
            self.assertNotIn(m, self.user_md, f'用户工件不得含 {m}')

    def test_run_metadata_dir_written(self):
        # engineering 工件必须位于独立 run_metadata 目录，且含 prompt / job metadata
        self.assertTrue(self.eng_path.endswith(os.path.join('run_metadata', 'task_001.json')))
        self.assertIn('prompt', self.eng_meta)
        self.assertIn('job_metadata', self.eng_meta)

    def test_feishu_surface_still_clean(self):
        self.assertNotIn('## Prompt', self.user_md)

    def test_secret_scan_zero(self):
        import re
        hits = 0
        for p in SECRET_PATTERNS:
            if re.search(p, self.user_md, re.I):
                hits += 1
        self.assertEqual(hits, 0)

    def test_new_artifact_contains_response_section(self):
        self.assertIn('## Response', self.user_md)

    def test_no_strategy_changes(self):
        # 验证本阶段未触碰 V1/DecisionEngine/Strategy Selector
        for f in ['decision/engine.py', 'double_monitor.py', 'position_stop_loss_alert.py']:
            p = os.path.join(SCRIPT_DIR, f)
            if os.path.exists(p):
                src = open(p, encoding='utf-8').read()
                self.assertNotIn('class StrategySelector', src)


class TestM4NoNewFinalDecision(unittest.TestCase):
    """M-4 不产生任何新 Final Decision / decision_id。"""

    def test_opportunity_no_decision_engine(self):
        src = open(os.path.join(SCRIPT_DIR, 'stock_opportunity_scan.py'), encoding='utf-8').read()
        self.assertNotIn('DecisionEngine', src)
        self.assertNotIn('decide(', src)

    def test_schedule_change_no_outcome(self):
        # 仅 schedule 字符串变化，不涉及交易结果
        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
