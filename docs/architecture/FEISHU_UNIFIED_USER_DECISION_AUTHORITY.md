# Feishu Unified User-Facing Decision Authority (Phase 8-F)

> 本文件定义 Hermes 股票系统的 **Unified User-Facing Decision Authority & Lifecycle**。
> 核心原则（锁死）：
> - `FINAL_DECISION_AUTHORITY = DecisionEngine`
> - 只有 DecisionEngine 能产生 Final Action（BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE）
> - Feishu 只能展示已经产生的 Decision，永远不是 Decision Owner / Execution Source
> - 本阶段不改交易规则、不改 DecisionEngine、不改 contract 决策语义。

---

## 1. Objective

解决 Phase 8-F0 已确认的问题：用户层存在多个 Decision-like 输出（double-monitor / opportunity / intraday / stop-loss 等），且 Daily Decision / Observation 未接入 Feishu。

目标不是把 30 条消息减到 1 条，而是：
> 建立统一决策权威 + 生命周期，让 30+ 条消息分层，不再同时承担「最终决策」角色。

---

## 2. Decision Authority

- **唯一 Final Decision Authority**：`DecisionEngine`
- 任何其他生产模块（opportunity / intraday / stop-loss-alert / news / sentiment / 龙虎榜 / observation / risk monitor）：
  - 未经过 DecisionEngine → 不得标记为 FINAL_DECISION
  - 已经过 DecisionEngine → 最终 Action 仍归 DecisionEngine

## 3. Action

Final Action 唯一枚举：`BUY / ADD / HOLD / REDUCE / SELL / NO_TRADE`

## 4. Presentation（展示上下文，非 Action）

`DAILY / URGENT / POSITION / SYSTEM / RESEARCH / INFORMATIONAL / SYSTEM_HEALTH / DEBUG`

> URGENT 不是 Action，不是第二种 Decision Type。
> 正确：`action=SELL, presentation=URGENT`；错误：`action=URGENT`

## 5. Lifecycle（Decision 状态）

`CREATED / ACTIVE / SUPERSEDED / EXPIRED / CANCELLED / EXECUTED / NOT_EXECUTED / CLOSED`

Action 与 Lifecycle 独立。

---

## 6. Daily Decision（TODAY PLAN）

当天综合交易计划，展示：
- Market（Regime / Permission / Position Scale）
- Account（Readiness / Total Asset / Cash / Drawdown，按可见性）
- Actions（BUY / ADD / HOLD / REDUCE / SELL / NO_TRADE）
- 每个 Final Action：symbol / action / effective time / reason / decision_id
- BUY 额外：planned_entry_time / price / target_position_pct / target_value / target_quantity

## 7. Urgent Decision（NOW / URGENT）

独立发送，例如 STOP_LOSS / FORCED_EXIT / PORTFOLIO_RISK / ACCOUNT_RISK。必须来自 DecisionEngine，带 decision_id / action / effective_from / timestamp / symbol / position_id / reason_codes。

## 8. Signal（Opportunity / Intraday）

- 仅信号 → class=SIGNAL，表达「发现机会/信号增强」，不表达 FINAL BUY
- 已进 DecisionEngine → 最终 Action = DecisionEngine Action

## 9. Research

Shadow / Opportunity / Strategy Research 类信息。

## 10. Informational

News / Sentiment / 龙虎榜 / 市场状态。

## 11. System Health

Account Readiness / Observation Health / Data Gap / Runtime Health。不产生交易 Action。

## 12. Debug

原始 stdout / traceback / SQL / 技术日志。默认不作为用户交易指令展示，不进入主消息正文。

---

## 13. Supersession

新 Decision 对同 symbol + position_id 的 ACTIVE 旧 Decision 建立 supersedes 关系：
- `D002.supersedes_decision_id = D001`
- `D001.state = SUPERSEDED, D002.state = ACTIVE`
- 用户界面不继续把 D001 显示为当前有效 Action

## 14. Expiry / Effective Window

`effective_from` / `effective_until`：
- Daily Plan：明确 entry window / trading session
- Urgent：按当前持仓 / 风险生命周期有效，直到 supersede / cancel / position closed

## 15. Latest Effective Decision

对同一 symbol + position_id / lifecycle，当前 Action 按：
1. DecisionEngine-backed
2. lifecycle_state == ACTIVE
3. 当前时间落在 effective window
4. effective_from 最新

得到 `CURRENT_EFFECTIVE_DECISION`。SUPERSEDED / EXPIRED / CANCELLED 不显示为当前指令。

---

## 16. Conflict

真正的 **USER_DECISION_CONFLICT**（同时满足）：
1. 两个用户可见消息都声称是 Final Decision
2. 都来自 DecisionEngine
3. 同一 symbol + position/lifecycle
4. effective window 重叠
5. Action 不一致

Research/Signal 与 Final 的差异只记 `SIGNAL_FINAL_DIFFERENCE`，不误报为冲突。

## 17. Duplicate

- **Message Duplicate**：同一 Decision 发多次 → 用 `decision_id + presentation + channel` 幂等控制
- **Decision Duplicate**：两个真正不同 decision_id，业务层现象，不简单去重

---

## 18. Delivery Contract

`delivery_id / decision_id / channel / presentation / send_time / delivery_status / retry_count / message_hash / error`
状态：`PENDING / SENT / FAILED / RETRYING`

> Decision 已产生 ≠ 用户已收到。

## 19. Delivery Idempotency

同一 `decision_id + presentation + channel` 不因 cron 重跑 / retry 重复发送。已有则 skip / reconcile。

## 20. Feishu 不是 Execution Source

用户看到 `BUY 600540` ≠ `EXECUTED`。只有 MANUAL_CONFIRMATION / 真实 Execution Source 才能形成 EXECUTED。`PLANNED != EXECUTED`。Feishu 回复/阅读/发送成功都不能自动推断成交。

---

## 21. Account Visibility

`PRIVATE / GROUP / TEAM`
- 股票 Feishu 群（oc_88d1）为 GROUP，若含非本人用户：
  - 不默认展示完整账户资产金额
  - 展示 `ACCOUNT_READY / SIZING_READY / drawdown 状态`
  - 完整金额保留在 Snapshot / Detail / Private channel
- 默认策略：GROUP 不显示金额；PRIVATE/TEAM 显示

## 22. Daily Primary 展示结构

### TODAY PLAN
- Market: Regime / Permission / Position Scale
- Account: Readiness / Total Asset / Cash / Drawdown（按可见性）
- Actions: BUY / ADD / HOLD / REDUCE / SELL / NO_TRADE（各带 decision_id）
- BUY 额外：planned_entry_time / price / target_position_pct / target_value / target_quantity
- SELL/REDUCE 额外：current_quantity / target_quantity / delta / exit_reason

## 23. Urgent 展示结构

```
🚨 URGENT DECISION
600540
Action: SELL
Reason: STOP_LOSS
Effective: 10:15
Decision ID: ...
```
明确为 FINAL_DECISION（非 Signal）。

## 24. System Health 展示结构

```
SYSTEM HEALTH
Account: BLOCKED
Observation: HEALTHY
Data: PARTIAL
```
不产生交易 Action。

## 25. Debug 默认不进入用户主消息

原始 double-monitor stdout 中的 Python trace / SQL / internal state / debug details 分类为 DEBUG，不与 Final Decision 混在同一用户消息正文。保留日志能力。

---

## 26. Daily JSON / Feishu 一致性

Daily Decision Contract 与 Feishu DAILY presentation 以下必须一致：
`action / symbol / decision_id / effective_from / effective_until / reason_codes / regime / permission / account_readiness / target_position / target_value / target_quantity`
Feishu 是 JSON 简化展示，不能产生第二套值。

## 27. Urgent JSON / Feishu 一致性

Urgent message 必须来自 Decision Snapshot / Decision Contract，不自行重算 stop / position / quantity / action。

---

## 28. User Decision View

统一用户层视图：
- **TODAY PLAN**：Daily Decision
- **NOW / URGENT**：当前最新有效 Urgent Final Decision
- **RESEARCH / SIGNAL**：Opportunity / Intraday
- **INFORMATION**：News / Sentiment / 龙虎榜
- **SYSTEM HEALTH**：Observation / Account / Data
- **DEBUG**：仅内部

目标不是一天只剩一条消息，而是让 30+ 条消息分层，不再同时承担「最终决策」角色。

## 29. 原有 Cron 功能保留

不关闭 opportunity / intraday / news / sentiment / 龙虎榜 / stop-loss / observation / market-cache / daily-data / weekly tasks。只改变 user-facing classification / routing / authority presentation。

---

## 30. 消息路由表

| Surface | Producer | Authority | Action Source | User-facing | Purpose |
|---|---|---|---|---|---|
| TODAY_PLAN | daily_decision_contract | DecisionEngine | Final Action | ✅ | 当天综合计划 |
| NOW_URGENT | stop-loss / forced-exit | DecisionEngine | Final SELL/REDUCE | ✅ | 立即关注 |
| RESEARCH_SIGNAL | opportunity / intraday | Signal（非 Engine） | 无 Final Action | ✅ | 发现机会 |
| INFORMATION | news / sentiment / lhb | 无 | 无 | ✅ | 市场信息 |
| SYSTEM_HEALTH | observation / account / data | 无 | 无 | ✅ | 健康状态 |
| DEBUG | double-monitor stdout | 无 | 无 | 内部 | 技术日志 |

---

## 31. Decision Timeline / Supersession Audit

选择同 symbol 的多个 Decision（Daily → Urgent / HOLD → SELL / BUY → NO_TRADE / 同 position 多阶段），验证：
- supersedes 关系
- lifecycle state
- current effective decision
- expired / superseded 不再显示 current
不改旧 Decision。

## 32. Delivery Audit

验证首次发送 / retry / duplicate run / same decision_id / different presentation / delivery failure，确认同一 channel + presentation + decision_id 不重复发送。

---

## 33. Known Limitations

- 本阶段建立 user_authority 模块与 lifecycle/delivery registry，**尚未把 Feishu 实际消息渲染切换到新 Surface**（属用户层渲染改造，后续 Phase）
- 当前各 producer 脚本（opportunity / intraday / news 等）仍直接输出到 Feishu 群，classification 由 user_authority 提供能力，尚未强制路由
- Account Visibility 默认 GROUP 不显示金额；若群成员组成变化需复核
- 不改交易规则 / 不改 DecisionEngine / 不改 contract 决策语义

---

*文档版本：Phase 8-F · Unified User-Facing Decision Authority & Lifecycle*
