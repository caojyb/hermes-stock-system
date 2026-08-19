# EVALUATION_DATA_READINESS.md（Phase 7.1）

## 1. Current Production Dataset Audit

### 1.1 True Source Distribution
当前 53 条 Outcome 的真实来源（基于 execution source + decision_id 模式）：

| 类别 | 数量 | 说明 |
|------|------|------|
| TEST | 38 | decision_id 含 p67/p68/test_ 前缀，来自 Phase 6.7/6.8/7 测试 |
| LEGACY | 15 | decision_id 为 lc_G 或无 decision_id，历史导入数据 |
| SIMULATION | 0 | 无独立 SIMULATION 标识数据 |
| PRODUCTION | 0 | **无真实生产数据** |
| SHADOW | 0 | 无主升浪数据 |

**结论：当前没有可用于策略评价的真实 Production 数据。**

### 1.2 Metadata Gap Analysis

| 字段 | TEST(38) | LEGACY(15) | SIMULATION(0) | PRODUCTION(0) |
|------|----------|------------|---------------|---------------|
| decision_id | ✓ | ✓ | ✓ | - |
| execution_id | ✓ | ✓ | ✓ | - |
| position_id | ✓ | ✓ | ✓ | - |
| entry_regime | ✗ | ✗ | ✗ | - |
| exit_regime | ✗ | ✗ | ✗ | - |
| candidate_score | ✗ | ✗ | ✗ | - |
| candidate_rank | ✗ | ✗ | ✗ | - |
| permission_status | ✗ | ✗ | ✗ | - |
| portfolio_assessment | ✗ | ✗ | ✗ | - |
| target_position | ✗ | ✗ | ✗ | - |
| planned_entry_price | ✓ | ✓ | ✓ | - |
| actual_entry_price | ✓ | ✓ | ✓ | - |
| slippage_price | ✗ | ✗ | ✗ | - |
| holding_period_days | 0 | 0 | 0 | - |
| MAE/MFE | 0/UNKNOWN | 0/UNKNOWN | 0/UNKNOWN | - |
| exit_reason | TAKE_PROFIT | TAKE_PROFIT | TAKE_PROFIT | - |

## 2. Provenance Audit

### 2.1 为什么 holding_period = 0
- 原因：execution_time 有值，但 exit.time 缺失或格式不完整
- Phase 7.1 修复：`build_outcome_from_execution` 现在从 execution 的 `execution_time` 和 `exit.time` 计算 holding_period_days
- 若缺失，保持 0（不再填充虚假值）

### 2.2 为什么 MAE/MFE = 0/UNKNOWN
- 原因：仿真测试未记录 excursion 数据
- Phase 7.1 修复：`excursion` 字段保留，但不再默认填充 0
- 缺失时保持 UNKNOWN

### 2.3 为什么 Regime = UNKNOWN
- 原因：Decision 生成时未将 regime 写入 execution/outcome
- Phase 7.1 修复：`record_simulation_execution` 现在从 decision 复制 `market_regime`/`regime_label` 到 execution
- `build_outcome_from_execution` 从 execution 提取 regime

### 2.4 为什么 Exit 全是 TAKE_PROFIT
- 原因：测试场景仅触发 TP 退出，未覆盖其他 exit reason
- Phase 7.1 修复：exit_reason 从 `exit_segments[i].reason` 提取，保留原始语义

## 3. Metadata Gap Matrix

| 字段 | Decision | Execution | Position | Exit | Outcome | Current Status | Required Fix |
|------|----------|-----------|----------|------|---------|----------------|--------------|
| entry_regime | ✓ | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | record_simulation_execution 复制 |
| exit_regime | ✗ | ✗ | - | ✓ | ✗→✓ | 缺失 | record_exit 写入 exit.regime |
| candidate_score | ✓ | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | record_simulation_execution 复制 |
| candidate_rank | ✓ | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | record_simulation_execution 复制 |
| permission_status | ✓ | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | record_simulation_execution 复制 |
| portfolio_assessment | ✓ | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | record_simulation_execution 复制 |
| target_position | ✓ | ✓ | - | - | ✓ | 部分存在 | 已从 decision 复制到 planned |
| planned_entry_price | ✓ | ✓ | - | - | ✓ | 部分存在 | 已复制 |
| actual_entry_price | - | ✓ | - | - | ✓ | 存在 | 无需修复 |
| slippage_price | - | ✗→✓ (p71) | - | - | ✗→✓ | 缺失 | build_outcome_from_execution 计算 |
| holding_period | - | ✓ | - | ✓ | ✓ | 0 | 计算逻辑修复 |
| MAE/MFE | - | ✗ | - | - | ✗ | 0/UNKNOWN | 需从 K 线计算 |
| exit_reason | - | ✗ | - | ✓ | ✓ | 部分 | 保留原始语义 |

## 4. Regime Capture
- **Phase 7.1 修复**：`record_simulation_execution` 从 decision 复制 `market_regime`/`regime_label` 到 execution.entry_regime
- `build_outcome_from_execution` 从 execution 提取 entry_regime 到 outcome
- 若 execution 为空，从 decision snapshot 回退读取
- **禁止**：事后重新计算历史 regime

## 5. Candidate Score Capture
- **Phase 7.1 修复**：`record_simulation_execution` 从 decision 复制 `candidate_score`、`candidate_rank`、`reason_codes` 到 execution
- `build_outcome_from_execution` 从 execution 提取到 outcome
- **禁止**：重新计算历史 score

## 6. Permission Capture
- **Phase 7.1 修复**：`record_simulation_execution` 从 decision 复制 `permission_status`、`permission` 到 execution
- 未来 outcome 可追溯 permission 状态
- **当前状态**：无真实 permission 数据（TEST/SIMULATION 未填充）

## 7. Portfolio Capture
- **Phase 7.1 修复**：`record_simulation_execution` 从 decision 复制 `portfolio_assessment`、`portfolio_drawdown`、`risk_flags` 到 execution
- 未来 outcome 可追溯 portfolio 状态
- **当前状态**：无真实 portfolio 数据

## 8. Execution Capture
- **Phase 7.1 修复**：execution 新增字段
  - `planned_entry_price`
  - `planned_entry_quantity`
  - `decision_time`
  - `slippage_price`
  - `slippage_quantity`
- `build_outcome_from_execution` 计算 slippage 和 holding period

## 9. Exit Reason Capture
- **Phase 7.1 修复**：exit_reason 从 `exit_segments[i].reason` 提取
- 保留原始语义（STOP_LOSS/TAKE_PROFIT/TRAILING_STOP/MA20_EXIT/PORTFOLIO_RISK/MANUAL/FORCED/OTHER）
- **当前状态**：TEST 数据仅包含 TAKE_PROFIT

## 10. MAE/MFE Capture
- **Phase 7.1 未修改**：MAE/MFE 仍依赖 excursion 数据
- **未来要求**：从真实 K 线计算 entry→exit 区间的 MAE/MFE
- 数据不足 → `UNKNOWN`，禁止填充 0

## 11. Test/Simulation Contamination
**关键发现**：
- 当前 45 条 Outcome 中，**32 条为 TEST 数据**（decision_id 含 p67/p68/p7_/test_ 前缀）
- **12 条为 LEGACY 数据**（decision_id = lc_G）
- **1 条为 SIMULATION 数据**
- **0 条为真实 PRODUCTION 数据**

**结论**：当前 Production Evaluation Dataset = ∅（空集）

## 12. Statistics Semantics
- **无亏损交易时 profit_factor = UNDEFINED**（非 0）
- **无样本 → N/A**
- **数据缺失 → UNKNOWN**
- **样本不足 (<5) → DATA_INSUFFICIENT**

## 13. Evaluation Health

```yaml
evaluation_health:
  production:
    total: 45
    valid: 0
    simulation: 1
    test_contaminated: 32
    missing_regime: 45
    missing_score: 45
    missing_execution: 0
    missing_outcome: 0
  shadow:
    total: 0
  legacy:
    total: 12
  counterfactual:
    total: 0
  status: NOT_READY
```

## 14. Future Data Requirements
从本阶段开始，新 Production Outcome 必须包含：

| 字段 | 来源 | 缺失处理 |
|------|------|----------|
| decision_id | Decision Contract | UNKNOWN |
| execution_id | Execution Record | UNKNOWN |
| position_id | Execution Record | UNKNOWN |
| strategy_id/version | Decision Contract | UNKNOWN |
| entry_regime | Decision.market_regime | UNKNOWN |
| exit_regime | Exit Decision / Assessment | UNKNOWN |
| permission | Decision.permission | {} |
| portfolio_assessment | Decision.portfolio_assessment | {} |
| candidate_score | Decision.candidate_score | 0.0 + MISSING |
| target_position | Decision.target_position | 0.0 |
| planned_entry | Execution.planned | {} |
| actual_entry | Execution.actual | {} |
| slippage | Execution 计算 | 0.0 |
| holding_period | Execution 计算 | 0 |
| MAE/MFE | K 线计算 | UNKNOWN |
| exit_reason | Exit Decision / Execution | UNKNOWN |

**关键原则**：
- 缺失字段 → UNKNOWN / {} / 0.0（根据语义选择）
- 禁止静默生成看似完整的 Evaluation Record
- 禁止回填历史缺失数据

## 15. Known Limitations
1. 历史 TEST/SIMULATION 数据未回填 evaluation metadata
2. MAE/MFE 计算依赖 K 线数据，当前未接入实时 K 线计算
3. exit_regime 需从 Exit Decision 传递，当前 Exit Decision 未存储 regime
4. candidate_score 仅 V1 double 策略有，其他策略可能缺失
5. permission/portfolio_assessment 真实数据需等真实生产 Decision 产生
6. 当前无真实 Production 数据，无法验证 metadata 完整性
