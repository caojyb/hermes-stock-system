# PRODUCTION_OBSERVATION.md（Phase 8-A）

## 1. Observation Objective

确保每一个 Production Final Decision 都能被完整证明和评价。
重点不是“V1 是否有效”，而是：
> “V1 产生的每一笔真实 Production Decision，未来能不能被完整证明？”

## 2. Observation Start

```text
Observation Start: hermes-stock-phase-8a
```

从该 Git tag 之后产生的完整 Production Outcome，才进入：
```text
PRODUCTION_EVALUATION_READY
```

之前的数据继续标记为：
```text
LEGACY / PRE_OBSERVATION
```

不回填，不污染当前健康状态。

## 3. Production Observation Graph

| Stage | Producer | Output | Persistence | ID | Next Link | Status |
|---|---|---|---|---|---|---|
| Data | daily_data_refresh / market_cache | klines / indicators / financial | market_cache.db | scan_date / code | Regime / Candidate | PRODUCTION_WIRED |
| Regime | stock_strategy_config / trading_permission | env_scale / permission | memory / stdout | regime_label / permission_status | Permission / Portfolio | PRODUCTION_WIRED |
| Candidate | double_monitor / screening | double_up_scores | market_cache.db | candidate_id (code+date) | Entry | PRODUCTION_WIRED |
| Entry | decision/adapters | entry_ctx | decision/snapshots | decision_id | DecisionEngine | PRODUCTION_WIRED |
| Permission | trading_permission | evaluate() | decision/snapshots | permission_status | DecisionEngine | PRODUCTION_WIRED |
| Portfolio | decision/portfolio | assess_portfolio() | decision/snapshots | portfolio_snapshot_id | DecisionEngine | PRODUCTION_WIRED |
| Decision | decision/engine | Decision | decision/snapshots/*.json | decision_id | Execution / Output | PRODUCTION_WIRED |
| Execution | decision/execution + confirm_execution.py | Execution record | decision/executions/*.json | execution_id | Position | PRODUCTION_WIRED (simulation auto; real manual) |
| Position | decision/execution aggregate_position | Position lifecycle | decision/executions/*.json | position_id | Exit / Outcome | PRODUCTION_WIRED |
| Exit | decision/execution record_exit | Exit segments | decision/executions/*.json | exit_execution_id | Outcome | PRODUCTION_WIRED |
| Outcome | decision/execution build_outcome_from_execution | Outcome | decision/outcomes/*.json | outcome_id | Evaluation | PRODUCTION_WIRED |

## 4. Observation Unit

```text
decision_id
```

从它开始必须能找到：
```text
Decision -> Execution -> Position -> Exit -> Outcome
```

对于 NO_TRADE：
```text
Decision -> NO_TRADE -> Counterfactual / Observation Status
```

## 5. Source Contract

每条 Production Observation 必须明确：
```text
source = PRODUCTION
```

并与以下严格隔离：
```text
TEST / SIMULATION / SHADOW / LEGACY / COUNTERFACTUAL / HISTORICAL_REPLAY
```

判定优先级：
1. `run_mode`
2. `environment`
3. `execution_source`

不得长期依赖 `decision_id` 前缀。

## 6. Decision Snapshot 不可变事实

Production Decision Snapshot：
- 不会被后续重新写入
- 相同 decision_id 不产生不同内容
- 时间字段不会后验覆盖
- 可恢复：配置/策略版本 / Market Regime / Permission / Portfolio / Candidate / Entry / Position Sizing / Risk / Exit Context

当前状态：AUDIT_OK（snapshots/ 目录文件写入后无更新逻辑）

## 7. 真实人工执行归因

Execution 来源：
```text
MANUAL_CONFIRMATION
```

必须记录：
- status
- actual_price
- actual_quantity
- execution_time
- execution_source
- planned_price
- planned_quantity

未确认时：
```text
execution_status = UNKNOWN / PLANNED
```
不得自动推断为 EXECUTED。

当前状态：PRODUCTION_WIRED（confirm_execution.py）

## 8. Production BUY Observation

每个 Production BUY 最终能建立：
```text
Decision -> Execution -> Position
```

关键字段：
- decision_id
- execution_id
- position_id
- symbol
- strategy/version
- entry_regime
- permission
- portfolio_snapshot_id
- planned_price
- actual_price
- planned_quantity
- actual_quantity
- execution_time

当前状态：
- Simulation: PRODUCTION_WIRED（double_monitor.py line 908-909）
- Real: PRODUCTION_WIRED（confirm_execution.py，人工确认）

## 9. Production NO_TRADE Observation

每个 NO_TRADE 保留：
- decision_id
- symbol / context
- blocking_layer
- reason_codes
- market_regime
- permission
- portfolio
- candidate
- entry_assessment

当前状态：PRODUCTION_WIRED（decision/snapshots/*.json）

## 10. Production SELL / REDUCE Observation

真实持仓 SELL / REDUCE：
```text
Decision -> Execution / Manual Confirmation -> Position Update -> Outcome
```

关键字段：
- exit_decision_id
- exit_execution_id
- position_id
- exit_reason
- planned_exit_price
- actual_exit_price
- exit_time
- quantity
- remaining_quantity

当前状态：
- Simulation: PRODUCTION_WIRED（record_exit / build_outcome_from_execution）
- Real: EXISTS_BUT_UNUSED（position_stop_loss_alert.py 输出 Decision，但未写 execution/outcome）

## 11. Partial / Multiple Exit

支持：
```text
BUY -> PARTIAL -> PARTIAL -> FINAL CLOSE
```

最终 Outcome 仅在 Position=CLOSED 时生成。

当前状态：PRODUCTION_WIRED（record_exit 支持多段加权）

## 12. Production Outcome Capture

每个最终关闭的 Production Position 能得到：
- outcome_id
- decision_id
- execution_id
- position_id
- entry
- exit
- return
- realized_pnl
- holding_period
- MAE
- MFE
- exit_reason
- entry_regime
- exit_regime
- strategy/version
- portfolio_snapshot_id

缺失字段：UNKNOWN，不补猜。

当前状态：PRODUCTION_WIRED（build_outcome_from_execution）

## 13. MAE / MFE 生产观察

触发条件：
- actual_entry_price
- actual_entry_time
- final_exit_time
- K-line availability

数据不足：UNKNOWN，不填 0。

当前状态：PRODUCTION_WIRED（_compute_mae_mfe_from_klines）

## 14. Holding Period

来源：
```text
actual_entry_time -> final_exit_time
```

不得用 decision_time -> exit_time 代替。

当前状态：PRODUCTION_WIRED（build_outcome_from_execution）

## 15. Execution Quality

独立于 Decision Quality：
- Decision Quality: planned_price / planned_quantity
- Execution Quality: actual_price / actual_quantity / execution_time

计算：
- price_slippage
- quantity_slippage
- execution_delay

当前状态：PRODUCTION_WIRED（build_outcome_from_execution）

## 16. Real Portfolio Snapshot 关联

每个 Production Decision 尽可能关联：
```text
portfolio_snapshot_id
```

Snapshot 可恢复：
- total_asset
- cash
- holdings
- drawdown
- position_count
- exposure
- freshness
- source

缺失：data_health，不默默使用旧值。

当前状态：PRODUCTION_WIRED（decision/snapshots + real_portfolio_history.db）

## 17. Production Data Health Monitor

Observation Health 检查项：
- decision_no_snapshot
- buy_no_execution
- execution_no_position
- exit_no_decision
- closed_no_outcome
- outcome_no_decision
- missing_portfolio_snapshot
- missing_regime
- missing_permission
- missing_execution_actual
- missing_exit_regime
- missing_mae_mfe

输出：
```text
HEALTHY / DEGRADED / BROKEN
```

区分：
- Historical Legacy Gap: 不污染当前生产健康
- Active Pipeline Gap: 当前生产窗口断裂，影响 Health

当前状态：PRODUCTION_WIRED（decision/execution.py monitor()）

## 18. 每日 Observation Health

每日生产任务结束后输出：
```text
Production Observation Health
Decisions: BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE
Executed: N
Open Positions: N
Closed Positions: N
Outcomes: N
Data Gaps: ...
Health: HEALTHY / DEGRADED / BROKEN
```

当前状态：PRODUCTION_WIRED（decision/execution.py monitor()）

## 19. 第一笔 Production 完整追踪

隔离测试覆盖：
- BUY Production Decision -> Manual Execution -> Position OPEN -> Exit -> Position CLOSED -> Outcome
- 所有 ID 可互相追溯

当前状态：PRODUCTION_WIRED（decision/test_lifecycle.py）

## 20. 未执行测试

Case：
- Production BUY -> NOT_EXECUTED
- 有 Decision
- 有 Execution record
- execution status = NOT_EXECUTED
- 不产生 CLOSED Outcome
- 不伪造 PnL

当前状态：PRODUCTION_WIRED（decision/test_lifecycle.py test_caseF）

## 21. Partial Execution 测试

Case：
- BUY 1000 -> EXECUTED 400
- planned_quantity = 1000
- actual_quantity = 400
- status = PARTIAL
- Position: OPEN
- Outcome: 不得提前 CLOSED

当前状态：PRODUCTION_WIRED（decision/test_execution.py / test_integrity_p67.py）

## 22. 真实持仓 SELL 测试

Case：
- Real Position -> SELL Decision -> MANUAL Confirmation -> CLOSED
- 得到 Outcome
- lifecycle_replay(outcome_id) 可恢复

当前状态：EXISTS_BUT_UNUSED（逻辑存在，但 position_stop_loss_alert.py 未实际写 execution/outcome）

## 23. Observation Data Gate

Production Outcome 进入 Future Evaluation Dataset 前必须满足：
- source = PRODUCTION
- decision_id
- execution_id
- position_id
- outcome_id
- provenance 完整

否则：
```text
PRODUCTION_PARTIAL
```

不得静默进入正式统计。

当前状态：PRODUCTION_WIRED（build_outcome_from_execution data_quality 字段）

## 24. Evaluation Dataset 分离

统计分：
```text
PRODUCTION / SIMULATION / TEST / SHADOW / LEGACY / COUNTERFACTUAL / HISTORICAL_REPLAY
```

禁止混合。TEST 绝不能进入 Production Evaluation Dataset。

当前状态：PRODUCTION_WIRED（build_outcome_from_execution data_quality 分类）

## 25. Daily Observation Report

创建：
```text
docs/architecture/PRODUCTION_OBSERVATION.md
```

包括：
1. Observation Objective
2. Observation Start
3. Decision
4. Execution
5. Position
6. Exit
7. Outcome
8. NO_TRADE
9. Data Health
10. Provenance
11. Real Portfolio
12. Execution Quality
13. Evaluation Gate
14. Production/Simulation Separation
15. Legacy Handling
16. Known Limitations

## 26. Production Observation 根节点

```text
decision_id
```

## 27. 当前 Production Observation 缺口

| 缺口 | 类型 | 说明 |
|---|---|---|
| Real SELL/REDUCE -> execution/outcome | DATA_GAP | position_stop_loss_alert.py 未写 execution/outcome |
| Real BUY -> automatic execution | NON_PRODUCTION | 当前仅 manual confirmation，符合当前阶段要求 |
| Daily Decision -> observation health | EXISTS_BUT_UNUSED | monitor() 存在但未接入日报 |
| Real account BUY target quantity | PARTIAL | total_asset=UNKNOWN 时 BLOCKED，需人工录入 |

## 28. 最终能力矩阵

| Capability | Simulation | Real Position | Production | Status |
|---|---|---|---|---|
| Buy What | ✅ | ✅ | ✅ | COMPLETE |
| When to Buy | ✅ | ✅ | ✅ | COMPLETE |
| How Much | ✅ | PARTIAL | PARTIAL | READY 条件下 COMPLETE |
| When to Sell | ✅ | ✅ | ✅ | COMPLETE |
| Market Regime | ✅ | ✅ | ✅ | COMPLETE |
| Trading Permission | ✅ | ✅ | ✅ | COMPLETE |
| Portfolio Veto | ✅ | ✅ | ✅ | COMPLETE |
| Final Decision | ✅ | ✅ | ✅ | COMPLETE |
| Explainability | ✅ | ✅ | ✅ | COMPLETE |
| Replay | ✅ | ✅ | ✅ | COMPLETE |
| Outcome | ✅ | EXISTS_BUT_UNUSED | PARTIAL | Simulation COMPLETE; Real 待接入 |
| Daily Actionable Output | ✅ | ✅ | ✅ | COMPLETE |
| Observation Health | ✅ | ✅ | ✅ | COMPLETE |
| Provenance | ✅ | ✅ | ✅ | COMPLETE |
| Evaluation Gate | ✅ | ✅ | ✅ | COMPLETE |
