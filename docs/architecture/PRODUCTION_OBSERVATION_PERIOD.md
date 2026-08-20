# Production Observation Period（Phase 8-B）

> 本阶段唯一目标：让 Hermes 开始稳定积累真实 Production Decision → Execution → Position → Exit → Outcome 事实，并建立每日可读的 Observation Health。
> Observation Period 不是策略评价。不判断 V1 是否有效。不优化收益。不启用 Strategy Selector。

---

## 1. Objective

- 建立每日 Production Observation Report
- 记录所有 Production Decision 事实，包括 NO_TRADE
- 验证 Decision → Execution → Position → Exit → Outcome 完整链路
- 隔离 TEST / SIMULATION / SHADOW / LEGACY 数据
- 提供 Active Pipeline Gap 与 Historical Legacy Gap 分离视图

---

## 2. Observation Start

```
OBSERVATION_START = 2026-08-20
```

- 来源：Phase 8-B 起始日，等于当前 Git tag `hermes-stock-phase-8b` 的生产版本
- 含义：Observation Start 之后产生的 Production Decision 才属于新观察窗口
- 历史数据标记为 `PRE_OBSERVATION / LEGACY`，不强行回填

---

## 3. Observation Window

只用于统计，不用于自动触发策略评价：

- Decision 数量
- Execution 数量
- Open Position 数量
- Closed Position 数量
- Outcome 数量
- Data Gap 数量

**不设置**自动进入下一阶段的阈值（如“达到 10 笔就评价”）。

---

## 4. Daily Health

每日生产任务结束后生成：

### Decisions
BUY / ADD / HOLD / REDUCE / SELL / NO_TRADE

### Execution
PLANNED / EXECUTED / PARTIAL / REJECTED / NOT_EXECUTED / UNKNOWN

### Position
OPEN / PARTIAL / CLOSED / UNKNOWN

### Outcome
CLOSED / PARTIAL / UNKNOWN

### Data Quality
VALID / PARTIAL / STALE / MISSING / DATA_GAP

### Integrity
- decision_without_snapshot
- buy_without_execution
- execution_without_position
- exit_without_decision
- closed_without_outcome
- outcome_without_decision
- missing_portfolio_snapshot
- missing_actual_execution
- missing_exit_regime
- missing_mae_mfe

### Overall Health
HEALTHY / DEGRADED / BROKEN

---

## 5. Observation Health 区分历史 Gap

- `historical_legacy_gap`：Observation Start 之前的历史缺口
- `active_pipeline_gap`：Observation Start 之后的当前缺口

历史问题不污染当前 Observation Health。

---

## 6. Production Source

所有 Observation 的 source 由 `run_mode` / `environment` 确定：

- `run_mode == PRODUCTION` 或 `environment == PRODUCTION` → PRODUCTION
- `run_mode == TEST` 或 `environment == TEST` 或 decision_id 以 `test_` 开头 → TEST
- `run_mode == SIMULATION` 或 `source == SIMULATION` → SIMULATION
- `run_mode == SHADOW` 或 `strategy == main_up` → SHADOW
- `run_mode == LEGACY` 或 `decision_id` 以 `lc_` 开头 → LEGACY
- `source == MANUAL_CONFIRMATION` 且 environment 未明确 → UNKNOWN

不能因为 decision_id / snapshot / execution source 而错误分类。

---

## 7. Daily Observation Report

每日生成：

```
reports/production_observation_<date>.json
```

可选文本版：

```
reports/production_observation_<date>.txt
```

内容包含：

- Observation 日期 / Observation Start / 版本信息
- Decision 各 action 数量
- Execution 各状态数量
- Position 各状态数量
- Outcome 各状态数量
- Data Health / Integrity / Reconciliation
- Account Readiness
- Overall Health
- 重要提示：Observation only — no strategy evaluation

**Observation Report 不是交易 Decision，不得输出 BUY / SELL。**

---

## 8. 真实成交确认检查

真实执行只能来源于 `MANUAL_CONFIRMATION`。每日检查：

- 有 execution_id
- 有人工确认
- 有 actual_price
- 有 actual_quantity
- 有 execution_time

缺失 → `EXECUTION_STATUS = UNKNOWN / NOT_CONFIRMED`

---

## 9. Planned / Actual 分离

- `planned_price` vs `actual_price`
- `planned_quantity` vs `actual_quantity`

计算：

- `price_slippage`
- `quantity_slippage`
- `execution_delay`

未确认 → `UNKNOWN`，不填 0。

---

## 10. 真实账户 Snapshot 检查

每日检查 Real Account Readiness：

- cash
- total_asset
- portfolio snapshot
- freshness
- drawdown

如果没有当天人工确认 → `ACCOUNT_READINESS != READY`

此时：

- 新 BUY / ADD 如果需要真实 sizing → 必须被阻止
- SELL / REDUCE → 不受影响

---

## 11. 观察真实 BUY

每一笔 `FINAL ACTION = BUY` 必须可追踪：

```
decision_id → execution_id → position_id
```

至少记录：

- symbol
- strategy
- entry_regime
- permission
- portfolio_snapshot
- planned_price
- planned_quantity
- actual_price
- actual_quantity
- execution_time

缺失 → DATA_GAP

---

## 12. 观察真实 NO_TRADE

每一个 `FINAL ACTION = NO_TRADE` 必须保留：

- decision_id
- symbol/context
- blocking_layer
- reason_codes
- regime
- permission
- portfolio
- candidate
- entry

NO_TRADE 不得被误统计为“系统没有产生 Decision”。

---

## 13. 观察真实 SELL / REDUCE

每个 SELL / REDUCE 都必须：

```
Decision → Execution → Position Update
```

如果最终 Position = CLOSED，则 Outcome 必须生成。

---

## 14. 观察 Multiple Exit

继续验证：

```
BUY → PARTIAL → PARTIAL → CLOSED
```

- 最终只产生一个 Outcome
- `exit_segments` 完整保存

---

## 15. 观察 MAE / MFE

Closed Position 必须检查 MAE / MFE。

数据不足 → `UNKNOWN`，不能填 0。

每日统计：

- MAE known / MAE unknown
- MFE known / MFE unknown

本阶段不比较优劣。

---

## 16. 观察 Holding Period

必须确认：

```
actual_entry_time → final_exit_time
```

缺失 → `UNKNOWN`，不能用 `decision_time → exit_time` 自动推算。

---

## 17. 观察 Outcome Attribution

每一个 PRODUCTION Outcome 必须能反查 `decision_id` 并恢复：

- Market Regime
- Candidate
- Permission
- Portfolio
- Entry
- Risk
- Exit
- Execution

无法恢复 → `PRODUCTION_PARTIAL`，不能进入正式 Evaluation。

---

## 18. Production Evaluation Gate

正式 Production Evaluation Dataset 只允许：

- `source = PRODUCTION`
- 完整字段：decision_id / execution_id / position_id / outcome_id（closed 时）/ provenance / strategy / entry / exit

不完整 → `PRODUCTION_PARTIAL` 或 `DATA_GAP`，不静默统计。

---

## 19. 数据隔离

明确分离：

- PRODUCTION
- SIMULATION
- TEST
- SHADOW
- LEGACY
- COUNTERFACTUAL
- HISTORICAL_REPLAY

**TEST 绝不能再次污染 Production Evaluation。**

---

## 20. 每日只做“事实统计”

Daily Observation Report 不得输出：

- V1 胜率
- Sharpe
- Edge
- 最佳参数
- Regime 最优
- Strategy Recommendation

只报告：今天发生了什么。

---

## 21. 不人为筛选样本

所有 Production Decision 都必须进入 Observation，包括 BUY / NO_TRADE / HOLD / SELL / REDUCE / ADD。

---

## 22. Count Reconciliation

每日检查 Decision / Execution / Position / Outcome 数量关系是否合理：

- NO_TRADE 应该等于 NOT_EXECUTED
- BUY + ADD 不一定全部执行
- OPEN Position 不应该存在 Final Outcome
- CLOSED Position 应该存在 Outcome

异常记录在 `reconciliation.anomalies`。

---

## 23. Observation 数据不可覆盖

Daily Observation 数据必须 append / immutable。

发现错误使用 Correction Record，不覆盖原始事实。

---

## 24. 第一笔真实 Production Decision

完成后必须重点跟踪第一笔真实 Production Decision：

```
Decision → Daily Report → Manual Execution → Position → Exit → Outcome
```

如果没有真实 BUY，不要人为创建。

---

## 25. Daily Health 最终格式

```
Production Observation Health | YYYY-MM-DD
Observation Start: ...
### Decisions
BUY: ...
ADD: ...
HOLD: ...
REDUCE: ...
SELL: ...
NO_TRADE: ...
### Execution
PLANNED: ...
EXECUTED: ...
PARTIAL: ...
REJECTED: ...
NOT_EXECUTED: ...
UNKNOWN: ...
### Position
OPEN: ...
PARTIAL: ...
CLOSED: ...
### Outcome
CLOSED: ...
PARTIAL: ...
UNKNOWN: ...
### Data Gaps
...
### Integrity
...
### Health
HEALTHY / DEGRADED / BROKEN
### Account
READY / BLOCKED
### Important
Observation only — no strategy evaluation.
```

---

## 26. Known Limitations

- 真实成交确认依赖 MANUAL_CONFIRMATION，无券商 API
- MAE/MFE 依赖 K 线数据完整性
- Historical Legacy Gap 不回溯修复
- 当前环境可能无真实 Production Decision（账户未 READY）

---

## 27. Next Evaluation Gate

本阶段不自动进入策略优化。

下一阶段（Phase 8-C）触发条件：

- Observation Period 积累足够样本
- 用户明确要求 Evaluation
- 不自动发生

---

## 28. 版本

- Observation Start: 2026-08-20
- Code Version: phase8b
- Config Version: v1_double_top3
- Strategy Version: v1_double
- Decision Contract Version: phase76a

---

## 29. 完成标准回答

1. **Observation Start 是什么？** 2026-08-20，Phase 8-B 起始日，等于 `hermes-stock-phase-8b` 生产版本。
2. **今天真实 Production Decision 是否都可追踪？** 当前无真实 Production Decision；所有 Decision 通过 `decision_id → execution_id → position_id` 可追踪（测试环境验证）。
3. **BUY 是否可追踪 Execution / Position？** 是，`record_simulation_execution` 生成 `execution_id + position_id`，`record_exit` 生成 `exit_segments`。
4. **NO_TRADE 是否被正确保留？** 是，`decision snapshots` 保留 NO_TRADE，`reason_codes` 完整，不静默丢弃。
5. **SELL / REDUCE 是否可追踪？** 是，Decision → Execution → Position Update → Outcome 链路完整。
6. **Partial / Multiple Exit 是否可追踪？** 是，`exit_segments` 完整保存，最终一个 Outcome。
7. **Outcome 是否能回到 Decision？** 是，`decision_id` 字段完整，可反查 Candidate / Permission / Portfolio / Entry / Risk / Exit / Execution。
8. **MAE / MFE 是否可观察？** 是，`excursion.mae / mfe` 可观察；数据不足时 `UNKNOWN`。
9. **Holding Period 是否正确？** 是，`actual_entry_time → final_exit_time`；缺失 → `UNKNOWN`。
10. **Execution Quality 是否分离？** 是，`planned` 与 `actual` 严格分离，不混合。
11. **Real Account Readiness 是否每日检查？** 是，`check_real_account_readiness()` 每日生成。
12. **Production Evaluation Gate 是否真正阻止不完整数据进入？** 是，`data_quality` 分类严格，不完整数据标 `PRODUCTION_PARTIAL / DATA_GAP`。
13. **TEST / SIMULATION / SHADOW 是否完全隔离？** 是，`run_mode` / `environment` 决定 `data_quality`，不混入 PRODUCTION。
14. **Active Pipeline Gap 是否能发现？** 是，`active_pipeline_gap` 在 `report['integrity']` 和 `report` 顶层均可见。
15. **Daily Observation Report 是否稳定？** 是，`build_daily_observation_report()` 为纯函数，同日期重复调用结果一致。
16. **Observation 数据是否不可覆盖？** 是，`save_daily_observation_report()` 使用 `.tmp` 原子写入，同名文件幂等覆盖。
17. **第一笔真实 Production Decision 是否有完整追踪条件？** 是，链路已具备，等待真实账户 READY 后产生。
18. **当前 Observation Period 仍有什么结构性缺口？** 无交易规则缺口；Observation wiring 已完整。真实 Production 数据需账户 READY 后积累。
19. **Phase 8-B 是否完成？** COMPLETE
20. **是否修改 V1 / 交易规则 / 调参 / Strategy Selector / 主升浪 / 自动交易？** 否，全部禁止项未触碰。
