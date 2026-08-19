# POSITION_QUANTITY_INTEGRITY.md（Phase 6.8）
## 1. Position Lifecycle Quantity
```yaml
position_state:
  position_id: P_<datetime>_<symbol>_<suffix>
  initial_quantity: BUY 数量
  added_quantity: ADD 数量
  total_entry_quantity: initial + add
  total_exit_quantity: 所有退出段总和
  current_quantity: total_entry - total_exit
  average_entry_price: (BUY_cost + ADD_cost) / total_entry
  weighted_exit_price: Σ(exit_price*qty) / total_exit
  invested_capital: BUY_cost + ADD_cost
  realized_pnl: Σ(exit_proceeds) - invested_capital
  status: OPEN / PARTIAL / CLOSED
```

## 2. BUY
- `record_simulation_execution` 创建 Entry Execution
- 自动生成 `position_id`
- 写入 `actual.price / actual.quantity`

## 3. ADD
- 创建独立 Execution（独立 `decision_id/execution_id`）
- **复用同一 `position_id`**
- 不创建独立 Outcome
- 计入 `added_quantity` 和 `add_cost`

## 4. Partial Exit
- `record_exit` 追加 `exit_segments`
- `position_status = PARTIAL`
- 未 CLOSED 前不生成 Outcome

## 5. Multiple Exit
- 多段退出累计 `total_exit_quantity`
- 加权退出价 `weighted_exit_price`
- CLOSED 后生成最终 Outcome

## 6. Cost Basis
- 平均成本 = (BUY_amount + ADD_amount) / (BUY_qty + ADD_qty)
- 不单独用第一笔 BUY 价格

## 7. PnL
- `realized_pnl = total_exit_proceeds - invested_capital`
- `return_pct = (weighted_exit_price - average_entry_price) / average_entry_price`

## 8. Outcome Aggregation
- `build_outcome_from_execution` 调用 `aggregate_position(pid)`
- Outcome.actual 包含：
  - `total_entry_quantity`
  - `average_entry_price`
  - `total_exit_quantity`
  - `weighted_exit_price`
  - `final_quantity`

## 9. Replay
- `lifecycle_replay(outcome_id)` 优先 `position_id` → `decision_id` → `symbol fallback`
- 当前退出段存储在 entry execution `exit_segments`
- replay 将 entry execution 作为 `exit_executions` 代表

## 10. Monitor
```yaml
monitor:
  linkage_fallback_count: 结构化链接缺失数
  production_linkage: 结构化链接数
  shadow_count: Shadow 执行数
  active_pipeline_gap: 生产缺口
  known_legacy_gap: 历史缺口
```

## 11. Tests
新增 Case 12-21（test_integrity_p67.py）：
- aggregate_position
- Partial/Multiple Exit
- 同股多生命周期隔离
- ADD 不独立 Outcome
- Replay
- PnL/Cost/Weighted Exit
- Legacy
- Shadow 分离
- Monitor linkage

## 12. Known Limitations
1. `aggregate_position` 只读取 executions 目录，未落库到 SQLite
2. `find_exit_executions` 当前返回 entry execution 自身（退出段尚未独立为文件）
3. `position_size` 仍保留兼容字段，新字段为 `total_entry_quantity`
