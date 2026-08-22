# Real Holdings / Account Asset Separation Design

## 1. Problem Statement
当前系统存在语义混淆：`Real Holdings` 与 `Account Asset` 混用同一状态机。
- `Real Holdings`：来自 Bitable，只反映持仓明细（symbol/quantity/avg_cost/current_price/sector）。
- `Account Asset`：cash + total_asset，当前无自动源，只能 MANUAL_CONFIRMATION。

当前问题：
- Bitable 可正常读取 → `real_portfolio` 有 `holdings_value`
- 但 `cash=None, total_asset=None` → `account_readiness=MISSING`
- MISSING 进一步影响 Observation Health 和 BUY/ADD sizing
- 语义上：**持仓存在 ≠ 账户总资产已知**

## 2. Proposed State Model

### 2.1 Real Holdings States
独立状态机，只反映持仓数据质量：

| State | Condition | Impact on Decision |
|-------|-----------|-------------------|
| READY | 所有持仓 quantity>0, avg_cost>0, current_price>0 | 可用于 SELL/REDUCE/HOLD 的持仓管理 |
| PARTIAL | 部分字段缺失（如 current_price=0） | 禁止依赖当前价的决策；SELL/REDUCE 降级为 PARTIAL |
| MISSING | Bitable 读取失败或 0 条已买入记录 | 禁止所有持仓管理决策；Observation 标记 DEGRADED |

### 2.2 Account Asset States
独立状态机，只反映 cash/total_asset 可用性：

| State | Condition | Impact on Decision |
|-------|-----------|-------------------|
| READY | cash 和 total_asset 均有效且 freshness=FRESH | 允许 BUY/ADD sizing |
| PARTIAL | 仅 cash 或仅 total_asset 有效 | 禁止 BUY/ADD；SELL/REDUCE 允许但 PARTIAL |
| STALE | 快照过期（>24h） | 同 PARTIAL |
| EXPIRED | 快照超期 | 同 PARTIAL |
| MISSING | 无快照或 cash/total_asset 均为 None | 禁止 BUY/ADD；SELL/REDUCE 允许但 PARTIAL |
| UNKNOWN | freshness 未知 | 同 PARTIAL |

### 2.3 Portfolio Risk State
独立状态机，只反映回撤/流动性：

| State | Condition | Impact |
|-------|-----------|--------|
| READY | 有历史峰值或无回撤触发条件 | 正常风控 |
| UNKNOWN | 历史峰值缺失 | 不强制减仓；仅 exit 信号触发 SELL |
| CRISIS | 回撤>15% | 强制减仓至 50%（现有规则不变） |

## 3. Decision Matrix

| Decision Type | Requires Holdings | Requires Account Asset | Notes |
|---------------|-------------------|------------------------|-------|
| SELL | READY/PARTIAL | PARTIAL/MISSING 允许 | 有持仓即可卖出 |
| REDUCE | READY/PARTIAL | PARTIAL/MISSING 允许 | 有持仓即可减仓 |
| HOLD | READY/PARTIAL | 任意 | 持仓存在即可继续持有 |
| BUY | READY | READY | **必须** Account=READY |
| ADD | READY | READY | **必须** Account=READY |

核心原则：
- **没有现金和总资产时**：
  - 允许：HOLD、SELL、REDUCE、风险提醒
  - 禁止：BUY、ADD、任何需要 target_quantity/target_value 的仓位计算
- **没有持仓时**：
  - 禁止：SELL/REDUCE（无仓可卖）
  - 允许：BUY（若 Account=READY）

## 4. Observation Health Calculation

### 4.1 Current Problem
当前 `observation.py:_health_from_status()` 只检查：
- `active_pipeline_gap > 5`
- `CLOSED positions != CLOSED outcomes`
- `account_ready == READY`

若 account_readiness=MISSING 但 Holdings 正常，Observation 可能错误标记 DEGRADED/BROKEN。

### 4.2 Proposed Health Model
三级健康度，独立评估三个维度：

```
Account Health = f(account_readiness)
Holdings Health = f(real_portfolio.data_quality)
Pipeline Health = f(active_gap, reconciliation)

Overall Health = min(Account Health, Holdings Health, Pipeline Health)
```

状态映射：
- READY + READY + HEALTHY → HEALTHY
- PARTIAL/MISSING + READY + HEALTHY → DEGRADED（因 Account 部分缺失）
- READY + PARTIAL/MISSING + HEALTHY → DEGRADED（因 Holdings 部分缺失）
- 任意 BROKEN → BROKEN

关键原则：
- **Feishu SENT ≠ Observation HEALTHY**
- Observation Health 由 Account + Holdings + Pipeline 共同决定
- 若 Account MISSING 但 Holdings READY：标记 DEGRADED，不阻断 SELL/REDUCE

## 5. Data Flow

```yaml
Bitable:
  -> _read_bitable_holdings()
  -> build_real_snapshot()
     -> real_portfolio_history.db (holdings snapshot)
     -> real_portfolio (Daily Contract)
     -> observation (Holdings Health)
     -> feishu_delivery (render only)

Manual Confirmation:
  -> run_daily_snapshot(cash_manual, total_asset_manual)
  -> real_portfolio_history.db
  -> get_account_readiness()
     -> account_readiness (Daily Contract)
     -> observation (Account Health)
     -> feishu_delivery (render only)

Decision:
  -> Daily Contract: classify_actions()
     -> BUY/ADD 需要 sizing_allowed=TRUE (Account=READY)
     -> SELL/REDUCE 只需要 Holdings READY/PARTIAL
```

## 6. Migration Path

### Phase A（当前 Phase 8-H1，只读设计）
- 确认上述状态机与 Decision Matrix
- 文档化当前语义混淆点

### Phase B（后续实现，需明确授权）
- 在 `daily_decision_contract.py:classify_actions()` 引入 Holdings State 独立判断
- 在 `observation.py:_health_from_status()` 拆分为三维评估
- 不修改 DecisionEngine、V1、Portfolio Risk Rule

### Phase C（可选）
- 在 `real_portfolio_truth.py` 增加 `check_holdings_quality()` 返回 Holdings State
- 在 `build_account_readiness_section()` 保持 Account State 独立

## 7. Risk Analysis

| Risk | Mitigation |
|------|-----------|
| 误将 Holdings READY 当作 Account READY | 明确状态机命名：`holdings_state` vs `account_state` |
| Observation 过度敏感 | 三维健康度取最小值，避免单一维度影响全局 |
| BUY/ADD 在 Account MISSING 时被错误触发 | classify_actions() 已有 `sizing_allowed` 门控，保持不变 |
| 旧版 real_portfolio.py 混淆 | 生产链路统一切到 real_portfolio_truth.py，旧版标记 DEPRECATED |

## 8. Key Decisions

1. **Real Holdings ≠ Account Asset**：两者独立状态机，不合并为单一 READY/MISSING。
2. **SELL/REDUCE 不依赖 Account Asset**：有持仓即可执行，sizing 可为 PARTIAL。
3. **BUY/ADD 必须依赖 Account Asset READY**：无 cash/total_asset 时禁止新仓。
4. **Observation Health 三维独立**：Account、Holdings、Pipeline 各自评估后取最小值。
5. **不自动推断现金/总资产**：保持 MANUAL_CONFIRMATION 唯一入口。
6. **不接券商 API**：Account Asset 保持现状。
7. **不修改 DecisionEngine**：只改 classify_actions 的门控条件。
