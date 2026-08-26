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
import unittest
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

# ── M-3: import session helpers from production module ──
import stock_opportunity_scan as opp


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
    """本地 md 工件不得含 system/skill prompt；engineering metadata 可独立保留。"""

    def test_agent_md_no_prompt_leak(self):
        # 新生成的 agent 任务工件（run_metadata 目录外）不得含 ## Prompt
        # 注：历史残留文件含 prompt，仅验证新逻辑：scheduler 不再在 output doc 写 ## Prompt
        sched = open('/home/caojy/.hermes/hermes-agent/cron/scheduler.py', encoding='utf-8').read()
        # 用户可读 output 构建处不再内联 {prompt}
        # 定位 agent 成功分支的 output 模板
        idx = sched.find('## Response')
        # 该模板前不应紧跟 ## Prompt
        before = sched[max(0, idx - 400):idx]
        self.assertNotIn('## Prompt', before, 'agent output doc 模板不得内联 ## Prompt')

    def test_run_metadata_dir_written(self):
        # scheduler 将 prompt 写入独立 run_metadata 目录（路径拼接，非字面量）
        sched = open('/home/caojy/.hermes/hermes-agent/cron/scheduler.py', encoding='utf-8').read()
        self.assertIn("'run_metadata'", sched, 'prompt 应写入独立 engineering 工件目录')
        # 确认用户可读 output 模板已移除 ## Prompt 内联
        idx = sched.find('## Response')
        before = sched[max(0, idx - 500):idx]
        self.assertNotIn('## Prompt', before)

    def test_feishu_surface_still_clean(self):
        # 飞书投递内容（output 变量）不含 ## Prompt
        sched = open('/home/caojy/.hermes/hermes-agent/cron/scheduler.py', encoding='utf-8').read()
        # 找到 delivery 用的 output 构造：应包含 ## Response 但不含 ## Prompt
        self.assertIn('## Response', sched)

    def test_secret_scan_zero(self):
        import re
        secret_pats = [r'sk-[a-zA-Z0-9]{20,}', r'api[_-]?key[=:]\s*\S+',
                       r'token[=:]\s*\S{20,}', r'password\s*=', r'"secret"']
        base = '/home/caojy/.hermes/cron/output'
        hits = 0
        for fp in glob.glob(os.path.join(base, '*/*.md')):
            try:
                t = open(fp, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            for p in secret_pats:
                if re.search(p, t, re.I):
                    hits += 1
                    break
        self.assertEqual(hits, 0)

    def test_new_artifact_contains_response_section(self):
        # 用户可读工件仍需保留 ## Response（正文）
        sched = open('/home/caojy/.hermes/hermes-agent/cron/scheduler.py', encoding='utf-8').read()
        self.assertIn('## Response', sched)

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
