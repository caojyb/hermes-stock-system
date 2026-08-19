# PRODUCTION_DATA_CAPTURE_READINESS.md（Phase 7.2）

## 1. Source Classification

### 1.1 分类规则（优先级从高到低）
1. **run_mode / environment** 明确标识 → 以标识为准
2. **strategy == 'main_up'** → SHADOW
3. **decision_id 模式** → 仅作为 fallback（p67/p68/test_ → TEST；lc_ → LEGACY）
4. **execution_source == 'MANUAL_CONFIRMATION'** → 不能单独决定 PRODUCTION，必须配合 environment=PRODUCTION
5. 无法确定 → UNKNOWN

### 1.2 分类结果
| 类别 | 判定条件 |
|------|----------|
| PRODUCTION | run_mode=PRODUCTION OR environment=PRODUCTION |
| TEST | run_mode=TEST OR environment=TEST OR decision_id 含 p67/p68/test_ |
| SIMULATION | run_mode=SIMULATION OR source=SIMULATION |
| SHADOW | run_mode=SHADOW OR strategy=main_up |
| LEGACY | run_mode=LEGACY OR decision_id 以 lc_ 开头 OR 无 decision_id |
| UNKNOWN | 其他情况（包括 MANUAL_CONFIRMATION 但 environment 未明确） |

### 1.3 关键约束
- **MANUAL_CONFIRMATION ≠ PRODUCTION**
- 必须 environment=PRODUCTION + MANUAL_CONFIRMATION 才 = PRODUCTION
- 如果 environment 未明确：→ UNKNOWN / DATA_GAP

## 2. Production Capture Contract

未来每一笔真正 Production Decision 必须至少能够进入：

```yaml
production_capture:
  source: PRODUCTION
  decision:
    decision_id:
    timestamp:
    as_of_time:
    symbol:
    action:
    strategy:
    strategy_version:
    market:
      entry_regime:
      regime_version:
    candidate:
      score:
      rank:
      reason_codes:
    permission:
      status:
      new_entry:
      add_position:
      reduce_position:
      exit_position:
      reason_codes:
    portfolio:
      snapshot_id:
      drawdown:
      exposure:
      position_count:
      sector_exposure:
      risk_flags:
    plan:
      entry_price:
      entry_quantity:
      target_position:
      stop_loss:
      take_profit:
  execution:
    execution_id:
    status:
    actual_price:
    actual_quantity:
    execution_time:
    execution_source:
    price_slippage:
    quantity_slippage:
  position:
    position_id:
    exit:
      exit_decision_id:
      exit_regime:
      exit_reason:
      exit_execution_id:
      exit_time:
      exit_price:
  outcome:
    outcome_id:
    holding_period:
    realized_pnl:
    return_pct:
    mae:
    mfe:
    data_quality:
  provenance:
    decision_snapshot_id:
    portfolio_snapshot_id:
    config_version:
    strategy_version:
    code_version:
```

## 3. Exit Regime Provenance

### 3.1 当前实现
- `record_exit` 新增参数 `exit_regime`
- `record_sim_exit_and_outcome` 透传 `exit_regime`
- `build_outcome_from_execution` 从 `exit_segments[0].exit_regime` 提取

### 3.2 规则
- Exit Decision 必须携带当时 Market Regime
- 如果 Exit 时没有可靠 Regime → `exit_regime = UNKNOWN`
- 禁止 Outcome 生成时重新计算当前 Regime

## 4. MAE/MFE Capture

### 4.1 实现
- `_compute_mae_mfe_from_klines(symbol, actual_entry_price, entry_time, exit_time)`
- 数据源：`market_cache.db` → `klines`
- 计算区间：entry_time → exit_time（基于日期）
- 使用 `actual_entry_price`，禁止用 planned_price 冒充

### 4.2 语义
- **MAE**：持仓期间从 entry 价到最低价的最大不利波动
- **MFE**：持仓期间从 entry 价到最高价的最大有利波动
- 数据不足 → `UNKNOWN`（不填 0）
- 状态标记：`mae_mfe_status = COMPUTED / UNKNOWN`

### 4.3 Partial/Multiple Exit
- MAE/MFE 基于整个 Position Lifecycle 的 entry → final close 区间
- 当前版本不拆每个 Exit Segment

## 5. Holding Period

### 5.1 规范
- 必须使用 `actual_entry_time` → `final_exit_time`
- 禁止使用 `decision_time` → `exit_time`
- 如果 actual execution time 缺失 → `UNKNOWN`

### 5.2 当前实现
- `entry_time = execution.execution_time`（优先）或 `created_at`
- `exit_time = exit.time`
- 计算 `holding_period_days`

## 6. Slippage

### 6.1 规范
- 必须保留 `planned_price` 和 `actual_price` 原值
- 计算 `price_slippage = actual_price - planned_price`
- 计算 `quantity_slippage = actual_quantity - planned_quantity`
- 如果 actual 不存在 → `UNKNOWN`

## 7. Production Data Gate

### 7.1 核心字段（缺失 → DATA_GAP）
- source = PRODUCTION
- decision_id
- execution_id
- position_id
- entry_regime（非空）
- permission_status（非空）
- portfolio_assessment（非空）
- actual_entry_price（有值）
- exit_reason（非空，如果已退出）

### 7.2 非核心字段（缺失 → PRODUCTION_PARTIAL）
- exit_regime
- MAE/MFE

### 7.3 函数
- `is_production_qualified(rec) -> dict` 返回 `{qualified, status, missing}`

## 8. Evaluation Health

### 8.1 状态定义
- **NOT_READY**：没有足够 Production 样本，或数据链不完整
- **DEGRADED**：存在 Production，但部分非核心字段缺失
- **READY**：Production 数据链完整到足以开始下一阶段 Evaluation（READY ≠ 策略有效）

### 8.2 函数
- `check_evaluation_health() -> dict`

### 8.3 输出
```yaml
evaluation_health:
  production:
    total: N
    valid: N
    partial: N
    data_gap: N
    missing_regime: N
    missing_score: N
    missing_permission: N
    missing_portfolio: N
    missing_execution: N
    missing_exit: N
    missing_outcome: N
    missing_mae: N
    missing_mfe: N
    missing_slippage: N
  shadow:
    total: N
  legacy:
    total: N
  test:
    total: N
  simulation:
    total: N
  status: NOT_READY / DEGRADED / READY
```

## 9. Test Isolation

### 9.1 原则
- 测试构造的数据必须标记为 TEST
- 即使测试使用了 PRODUCTION context，也不能污染真实 Production Dataset
- `_classify_source` 在测试环境会自动识别并标记为 TEST

### 9.2 验证
- `TestSourceClassification` 已验证：
  - MANUAL_CONFIRMATION + environment=PRODUCTION → PRODUCTION
  - MANUAL_CONFIRMATION 无 environment → UNKNOWN
  - main_up strategy → SHADOW
  - lc_ decision_id → LEGACY
  - p67/p68/test_ prefix → TEST

## 10. Historical Data

### 10.1 当前状态
- TEST = 38
- LEGACY = 15
- SIMULATION = 0
- PRODUCTION = 0
- SHADOW = 0

### 10.2 处理原则
- 不修改历史数据
- 不伪造 regime、score、permission、portfolio、MAE/MFE
- 历史数据保持原有标记（TEST/LEGACY/UNKNOWN）

## 11. Future Production Requirements

从 Phase 7.2 开始，新 Production Outcome 必须包含：

| 字段 | 来源 | 缺失处理 |
|------|------|----------|
| run_mode / environment | 调用方传入 | UNKNOWN |
| entry_regime | decision.market_regime | UNKNOWN |
| exit_regime | exit decision/execution | UNKNOWN |
| candidate_score | decision.candidate_score | 0.0 |
| permission_status | decision.permission_status | 空 |
| portfolio_assessment | decision.portfolio_assessment | 空 |
| planned_entry_price | decision.reference_price | 0.0 |
| actual_entry_price | execution.actual.price | 无 Outcome |
| slippage_price | 自动计算 | 0.0 |
| holding_period | execution_time → exit.time | 0 |
| MAE/MFE | _compute_mae_mfe_from_klines | UNKNOWN |

## 12. Known Limitations

1. MAE/MFE 计算依赖 `market_cache.db` 的 klines 表，数据不足时返回 UNKNOWN
2. exit_regime 需要 Exit Decision 主动传入，当前 Exit Decision 生成逻辑尚未完全接入
3. run_mode/environment 依赖调用方正确传入，目前仅 simulation/manual 函数支持
4. 历史 53 条数据未回填 evaluation metadata，保持原有标记
5. 当前无真实 Production 数据，无法验证完整 Production Data Gate
