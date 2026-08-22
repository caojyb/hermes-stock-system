# Real Holdings H1 Test Plan

## 1. Holdings

### 1.1 Bitable 正常读取
- 模拟 `_read_bitable_holdings()` 返回正常数据
- 验证：`build_real_snapshot()` 产出 `holdings_value > 0`
- 验证：`snapshot_portfolio_context()` 返回 `position_count > 0`

### 1.2 字段缺失
- `avg_cost = None` → quality WARNING
- `current_price = None` → quality WARNING
- `quantity = None` → quality WARNING
- 缺失字段不影响非依赖字段的计算

### 1.3 字段顺序变化
- 模拟 `lark-cli` 返回字段顺序变化
- 验证：使用 `BITABLE_FIELD_INDEX` 后仍能正确解析
- 验证：索引漂移时 `_validate_field_order()` 报错

### 1.4 空持仓
- Bitable 返回 0 条已买入记录
- 验证：`build_real_snapshot()` 返回 `holdings=[]`
- 验证：`data_quality = MISSING`

## 2. Account

### 2.1 无现金
- `run_daily_snapshot(cash_manual=None, total_asset_manual=100000)`
- 验证：`account_readiness = PARTIAL`
- 验证：`sizing_allowed = False`

### 2.2 无总资产
- `run_daily_snapshot(cash_manual=50000, total_asset_manual=None)`
- 验证：`account_readiness = PARTIAL`
- 验证：`sizing_allowed = False`

### 2.3 手工确认
- `run_daily_snapshot(cash_manual=100000, total_asset_manual=200000)`
- 验证：`account_readiness = READY`
- 验证：`sizing_allowed = True`

### 2.4 快照过期
- 插入 25h 前的快照
- 验证：`account_readiness = STALE`
- 验证：`sizing_allowed = False`

## 3. Quality

### 3.1 正常成本
- `avg_cost=10.5, current_price=12.0, quantity=100`
- 验证：所有 checks = OK

### 3.2 异常成本（过高）
- `avg_cost=1000, current_price=10.0`
- 验证：`cost/price ratio` check = WARNING (OUTLIER)

### 3.3 异常成本（为负）
- `avg_cost=-10.0`
- 验证：`avg_cost check = ERROR (NON_POSITIVE)`

### 3.4 异常价格
- `current_price=0` → ERROR (NON_POSITIVE)
- `current_price=-5` → ERROR (NON_POSITIVE)

### 3.5 异常数量
- `quantity=0` → ERROR (NON_POSITIVE)
- `quantity=150` → WARNING (NON_INTEGER)
- `quantity=-100` → ERROR (NON_POSITIVE)

## 4. Decision

### 4.1 无 Account Asset 时 BUY 被禁止
- `account_readiness = MISSING`
- `holdings = READY`
- Decision = BUY
- 验证：`classify_actions()` 转换为 `NO_TRADE` + `sizing_status=BLOCKED`

### 4.2 无 Account Asset 时 ADD 被禁止
- 同上，Decision = ADD
- 验证：转换为 `NO_TRADE` + `BLOCKED`

### 4.3 无 Account Asset 时 SELL 允许
- `account_readiness = MISSING`
- `holdings = READY`
- Decision = SELL
- 验证：`action` 保持 `SELL`，`sizing_status = PARTIAL`

### 4.4 无 Account Asset 时 REDUCE 允许
- 同上，Decision = REDUCE
- 验证：`action` 保持 `REDUCE`，`sizing_status = PARTIAL`

### 4.5 无 Account Asset 时 HOLD 允许
- Decision = HOLD
- 验证：`action` 保持 `HOLD`，`sizing_status` 不涉及

### 4.6 无 Holdings 时 SELL 被禁止
- `holdings = MISSING`
- Decision = SELL
- 验证：不产生 SELL（或标记为 NO_TRADE）

## 5. Observation Health

### 5.1 Account MISSING + Holdings READY → DEGRADED
- 验证：`_health_from_status()` 返回 DEGRADED

### 5.2 Account READY + Holdings PARTIAL → DEGRADED
- 验证：返回 DEGRADED

### 5.3 Account READY + Holdings READY + Pipeline HEALTHY → HEALTHY
- 验证：返回 HEALTHY

### 5.4 任意 BROKEN → BROKEN
- 验证：返回 BROKEN

## 6. Field Mapping

### 6.1 常量引用
- 验证：`BITABLE_FIELD_INDEX` 与 `--field-id` 传参顺序一致
- 验证：新增字段时只需修改常量和传参列表

### 6.2 漂移检测
- 模拟返回字段数 != 期望
- 验证：`_validate_field_order()` 抛出 RuntimeError

## 7. Non-Functional

### 7.1 不修改 Bitable
- 所有测试使用 mock，不调用真实 lark-cli
- 不产生任何 Bitable 写入

### 7.2 不修改 DecisionEngine
- 只测试 `classify_actions()` 行为
- 不调用 `DecisionEngine.decide()`

### 7.3 不修改 V1
- 不涉及任何 V1 参数

## 8. Test Coverage Target
- Holdings: 4 cases
- Account: 4 cases
- Quality: 5 cases
- Decision: 6 cases
- Observation: 4 cases
- Field Mapping: 2 cases
- **Total: 25+ test cases**

## 9. Implementation Notes
- 测试文件：`decision/test_real_holdings_h1.py`
- 使用 pytest + monkeypatch
- 所有 Bitable 调用 mock
- 所有时间函数固定（`_today_iso`, `_now_iso`）
- 使用 `tmp_path` 隔离数据库
