# Phase 8-K4 Closeout — Opportunity Session Semantics & Runtime Artifact Hygiene

> 基线：hermes-stock-phase-8k3 / b4fb8fc → 本阶段 tag: hermes-stock-phase-8k4
> 日期：2026-08-26

## 一、M-3：Opportunity Session Semantics（已修复）

### 根因
`stock-opportunity-push` schedule `*/30 9-11,13-15` 含 15:00/15:30 盘后 slot，
且文案硬编码 `【盘中推荐】`，盘后 run 使用 stale 收盘兜底价当实时价。

### 修复
1. **Schedule 收窄**：`*/30 9-11,13-15` → `*/30 9-11,13-14`（真实 cron 语法验证，
   触发点 9:00/9:30/10:00/10:30/11:00/11:30/13:00/13:30/14:00/14:30，不再含 15:00/15:30）
2. **Session 防御**（`stock_opportunity_scan.py` 新增 `current_session()` / `session_label()`）：
   - INTRADAY：9:30–11:30、13:00–15:00（收盘 15:00 整属 POST_CLOSE）
   - POST_CLOSE / NON_TRADING / PRE_OPEN → `__main__` 直接 `sys.exit(0)`（SKIP）
3. **动态文案**：`【盘中推荐 · HH:MM】` → `【{session_label()} · HH:MM】`，
   盘后/非交易时段不再出现"盘中"措辞

### 验证
- `current_session(15:00)` = POST_CLOSE ✓
- `current_session(15:30)` = POST_CLOSE ✓
- `session_label(15:31)` = "盘后候选更新"（非"盘中推荐"）✓
- `session_label(10:00)` = "盘中推荐" ✓
- 盘后 run 在 `__main__` guard 处 SKIP，不输出、不使用 stale 价 ✓

## 二、M-4：Runtime Artifact Hygiene（已修复）

### 根因
hermes-agent cron scheduler（`hermes-agent/cron/scheduler.py`）在 agent 任务本地 md 工件中
内联 `## Prompt`（完整 skill system prompt）；no_agent 任务含 `# Cron Job` runtime metadata。
K3 确认：飞书用户面 clean、secret=0，泄漏仅在本地工件。

### 修复（框架层 runtime，不动股票策略/Feishu channel）
`scheduler.py` agent 成功分支：将 `# Cron Job` metadata + `## Prompt` 从用户可读 output doc 移除，
改写入独立 engineering 工件 `~/.hermes/cron/run_metadata/<job_id>_<ts>.md`；
用户可读 doc 仅保留 `# Cron Job` 简单头 + `## Response`（与飞书同款正文）。

### 验证
- scheduler output 模板不再内联 `## Prompt` ✓
- `run_metadata` 目录写入逻辑存在 ✓
- 飞书投递内容（output 变量）不含 prompt ✓
- secret scan = 0（全 cron output 0 命中）✓

## 三、约束遵守

| 项 | 状态 |
|---|---|
| V1 未修改 | ✅ |
| DecisionEngine 未修改 | ✅ |
| Strategy Selector 仍 OFF | ✅ |
| Auto Trading 仍 OFF | ✅ |
| Production Outcome 仍 0 | ✅ |
| opportunity-push 未删除 | ✅ |
| Feishu channel 未改 | ✅ |
| 无新 Final Decision / decision_id | ✅ |
| 无 Execution / Outcome | ✅ |

## 四、测试

- 新增 `decision/test_k4_session_and_artifacts.py`：20 项（M-3 10 + M-4 10）
- K3 审计测试 `test_opportunity_schedule_has_late_slot` 同步为 K4 后状态（13-14）
- **全量 decision suite：465 passed / 0 failed**

## 五、17 问速答

1. 新 schedule：`*/30 9-11,13-14 * * 1-5`
2. 15:00/15:30 slot 已完全移除 ✓
3. POST_CLOSE 安全 SKIP ✓
4. 不再出现"盘中推荐"但市场已收盘 ✓
5. stale 价不再被描述成实时（盘后直接 SKIP）✓
6. Opportunity 仍 SIGNAL（非 FINAL）✓
7. 无新 Final Decision ✓
8. runtime artifact 与 user output 分离 ✓
9. 新 md 不含 system/skill prompt ✓
10. Engineering log（run_metadata）保留诊断 ✓
11. secret scan = 0 ✓
12. Feishu 用户面保持 clean ✓
13. V1 完全未修改 ✓
14. DecisionEngine 完全未修改 ✓
15. Strategy Selector 仍 OFF ✓
16. Auto Trading 仍 OFF ✓
17. Production Outcome 仍 0 ✓
18. 无新 K3 用户面 HIGH 问题 ✓

## 六、K4_STATUS = COMPLETE

M-3 + M-4 均修复，零策略改动，全量测试通过。停止，不进入消息大整合。
