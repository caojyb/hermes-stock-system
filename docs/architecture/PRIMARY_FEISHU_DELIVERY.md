# Primary Feishu Delivery（Phase 8-G0.2）

## 1. Purpose
将 Daily Decision Contract 生成的 Primary Decision，安全投递到现有 Feishu 股票主群，并建立可追踪、幂等、失败隔离的 Delivery Lifecycle。

## 2. Source of Truth
`decision/daily_decision_contract.py`
- `build_daily_report()`：生成 Daily Decision Report（dict）
- `save_daily_report()`：落盘 JSON/TXT

Primary Feishu Message **只读** 该 Report，不重算 Decision。

## 3. Primary Message
生成函数：`decision/feishu_delivery.py:build_primary_feishu_message(report)`

内容字段：
- date / presentation = DAILY
- market_regime / position_scale
- account_readiness / real_portfolio（source / quality / freshness / cash / total_asset）
- decision_summary（counts）
- actions（BUY / ADD / HOLD / REDUCE / SELL / NO_TRADE）
- decision_id / reason_codes
- target_position / target_value / target_quantity（如有）
- data_health / trace

若字段缺失，显示 `UNKNOWN / NOT_AVAILABLE`。

## 4. Delivery Contract
模块：`decision/user_authority.py`

状态枚举：
- PENDING
- SENT
- FAILED
- RETRYING

记录字段：
- delivery_id
- decision_id
- presentation
- channel
- message_hash
- send_time
- delivery_status
- retry_count
- error
- source
- server_readback

## 5. Idempotency
唯一键：`decision_id + presentation + channel`

机制：
- `message_hash(decision_id, presentation, channel)` = SHA256
- `find_delivery()` 按 message_hash 查找历史记录
- `is_duplicate_delivery()` 判断是否已发送

重复发送同一键 → `DUPLICATE_SUPPRESSED`

## 6. Retry
入口：`decision/feishu_delivery.py:deliver_primary_feishu_with_retry(report, max_retries=1)`

行为：
- FAILED → RETRYING → 重发同一 Primary Message
- 不重算 Decision
- 不重新 sizing
- 不调用 DecisionEngine

## 7. Failure Isolation
Feishu 发送失败：
- Decision 文件正常落盘
- Observation 正常生成
- Delivery 记录为 FAILED
- 不生成 EXECUTED
- 不生成 Production Outcome
- 不影响任何交易状态

原则：Delivery Failure ≠ Decision Failure

## 8. Channel
固定 Feishu 股票主群：
`oc_88d1817efbb9f328f4376314ab7c8b05`

不得创建新群，不得改变 channel。

## 9. Feishu Send
使用既有发送器：
`~/.hermes/skills/stock/stock-expert/skills/feishu-bitable/feishu_sender.py:send_text_message()`

动态导入，避免硬依赖。

## 10. Server Readback
当前 Feishu API **无** 服务端投递回执。

标记：
`server_readback = UNAVAILABLE`

应用层 `SENT` 仅代表：send function 已成功返回。
不标记 `USER_RECEIVED = TRUE`。

## 11. Double Monitor Wiring
`double_monitor.py` 末尾在 Daily Decision Report 生成后，调用：
`deliver_primary_feishu_with_retry(primary_report, max_retries=1)`

执行顺序：
1. Decision 保存成功
2. Delivery 尝试
3. Delivery failure 不影响 Decision
4. delivery record 独立保存

## 12. Daily / Observation Consistency
Primary Feishu Message 与 `daily_decision_<date>.json` 至少一致：
- date
- action counts
- symbol / action
- decision_id
- reason_codes
- market_regime
- account_readiness
- target_position / value / quantity

## 13. Account Readiness
若状态为 MISSING / PARTIAL / STALE / EXPIRED：
- Primary Message 正确展示当前状态
- 不重新计算 cash / total_asset
- 不猜测缺失值

## 14. Zero Action / Non-Trading Day
- 零决策日：Primary 正常发送，显示 BUY/SELL/NO_TRADE counts = 0
- 非交易日：Primary 正常发送，展示系统健康摘要

## 15. Observation Health
Feishu SENT ≠ Observation HEALTHY

Observation Health 由以下决定：
- Account Readiness
- Data Integrity
- Observation / Decision / Delivery 关键链路

若 account readiness MISSING：Observation 可标记 `DEGRADED`

## 16. Tests
`decision/test_primary_feishu_delivery.py`

覆盖：
1. primary message build
2. daily json / feishu consistency
3. delivery record PENDING
4. successful send → SENT
5. failed send → FAILED
6. retry → RETRYING
7. successful retry → SENT
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

## 17. Runtime Verification
生产等效运行命令：
```bash
cd ~/.hermes/scripts/cron
SIM_MODE=test timeout 180 python3 double_monitor.py
```

验证项：
1. Trading Day / Market Data Ready
2. Daily Decision JSON/TXT 生成
3. Primary Delivery status 输出到 stdout
4. Observation Report 正常
5. 无 EXECUTED
6. 无 Production Outcome 伪造
7. 无自动交易

## 18. Known Limitations
1. Feishu Server Readback 不可用，无法证明用户实际收到
2. 若 `feishu_sender.py` 的 lark-cli 认证失效，Primary Delivery 将 FAILED，需人工修复
3. 当前 retry 上限 1 次，不支持无限重试
4. 不发送富文本卡片，仅发送纯文本消息

## 19. Production Impact
- 新增文件：
  - `decision/feishu_delivery.py`
  - `decision/test_primary_feishu_delivery.py`
- 修改文件：
  - `double_monitor.py`（末尾追加 Primary Delivery wiring）
- 不修改：
  - V1 / 任何策略参数
  - DecisionEngine
  - Portfolio Risk Rule
  - Position Sizing
  - Account Readiness 状态机

## 20. Git
基线：`hermes-stock-phase-8g0.1`
完成：`hermes-stock-phase-8g0.2`
