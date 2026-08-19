# DECISION_EXECUTION_INTEGRITY.md（Phase 6.7）
## 1. Git Scope Verification
当前 repo = `/home/caojy/.hermes/scripts/cron/`
覆盖：
- `decision/`（contract/engine/execution/outcome/portfolio/snapshot/replay）
- `double_monitor.py`
- 数据/候选池/配置/测试/文档
未纳管目录：上级 Hermes 平台文件（hindsight/heartbeat 等），不属于股票生产链，不扩大 repo。

## 2. Current Linkage
- Decision → decision_id
- Execution → decision_id + execution_id
- Position → position_id（Phase 6.7 新增）
- Exit Execution → entry_execution_id + exit_decision_id
- Outcome → decision_id + position_id

## 3. Decision Identity
- 唯一 `decision_id`
- 快照 frozen 到 `decision/snapshots/`
- 可通过 `find_execution(decision_id)` 查找所有 execution

## 4. Position Identity
- `position_id = P_<datetime>_<symbol>_<suffix>`
- 每个 Entry Execution 新建时自动生成
- 区分同股票第 N 次持仓

## 5. Entry Execution
- `record_simulation_execution()` 写 decision_id + position_id
- `confirm_manual_execution()` 支持真实仓人工确认

## 6. Exit Execution
- `record_exit()` 追加 `exit_segments`
- 支持 `entry_execution_id` / `exit_decision_id`
- 多次退出属于同一 entry_execution / position_id

## 7. Partial Exit
- 状态: PARTIAL → CLOSED
- 未 CLOSED 前不生成 Outcome
- 退出段加权价由 `exit_summary` 维护

## 8. Multiple Exit
- `exit_segments` 多条
- `find_exit_executions(entry_execution_id)` 查询

## 9. ADD
- 记录为独立 Execution，复用同一 position_id
- 不创建新 Outcome
- Known Limitation：当前 outcome.position_size 来自 entry actual.quantity，不含 ADD 聚合

## 10. Outcome
- 只在 `position_status == CLOSED` 后生成
- 多段加权退出价 / 数量
- `position_id` 随 execution 写入

## 11. Replay
- `lifecycle_replay(outcome_id)` 优先 `position_id` → `decision_id` → `symbol fallback`
- 返回 exit_executions / entry_execution / entry_decision

## 12. Health Monitor
- `monitor()` 输出 `active_pipeline_gap` / `known_legacy_gap` / `integrity`
- 不包含 linkage_fallback_count 独立键（可由 linkage 字段推导）

## 13. Legacy
- 无 decision_id → `SOURCE_LEGACY`
- 无结构化信息 → 返回空 linkage / LEGACY 标记
- 不伪造 decision_id

## 14. Tests
原有 88 passed + 新增 11 = 99 passed

## 15. Known Limitations
1. ADD 数量未聚合进 Outcome（position_size 仍为 entry quantity）
2. `find_exit_executions()` 当前主要靠 entry_execution_id；未来可改为独立 exit file
3. `monitor()` 无独立 `linkage_fallback_count` 字段，需解析 execution.linkage

## 16. Git Commit / Tag
- commit: `fix: harden decision execution lifecycle linkage`
- tag: `hermes-stock-phase-6.7`
