# Phase 8-H1 Design Review — Real Holdings Integrity

## 1. Current Architecture Facts

### 1.1 Data Sources
| Source | Provides | Auto/Manual | Location |
|--------|----------|-------------|----------|
| Bitable `tbluYAy8YJx36jpP` | symbol, quantity, avg_cost, current_price, sector | Auto | `_read_bitable_holdings()` |
| MANUAL_CONFIRMATION | cash, total_asset | Manual | `run_daily_snapshot(cash_manual, total_asset_manual)` |

### 1.2 Modules & Responsibilities
| Module | Responsibility | Reads Real Holdings | Reads Account Asset |
|--------|---------------|---------------------|---------------------|
| `real_portfolio_truth.py` | Real snapshot builder + history DB | YES | YES (if MANUAL_CONFIRMATION) |
| `real_portfolio.py` | Legacy real snapshot (Phase 5.5) | YES | NO |
| `daily_decision_contract.py` | Daily report aggregation | YES (via build_real_snapshot) | YES (via get_account_readiness) |
| `observation.py` | Production observation | YES | YES |
| `feishu_delivery.py` | Primary Feishu rendering | YES (from report) | YES (from report) |
| `user_authority.py` | Delivery registry | NO | NO |

### 1.3 Current State Machine
- `real_portfolio_truth.py`: `data_quality` (VALID/STALE/PARTIAL/MISSING/UNKNOWN)
- `get_account_readiness()`: `status` (READY/PARTIAL/STALE/EXPIRED/MISSING/UNKNOWN)
- **混淆点**: `account_readiness` 同时受 `holdings` 和 `cash/total_asset` 影响

### 1.4 Decision Matrix (Current)
| Action | Holdings Required | Account Required | Current Behavior |
|--------|-------------------|------------------|------------------|
| BUY | YES | YES (sizing_allowed) | Account MISSING → BLOCKED → NO_TRADE |
| ADD | YES | YES (sizing_allowed) | Account MISSING → BLOCKED → NO_TRADE |
| SELL | YES | NO | Account MISSING → PARTIAL (allowed) |
| REDUCE | YES | NO | Account MISSING → PARTIAL (allowed) |
| HOLD | YES | NO | Always allowed |

### 1.5 Observation Health (Current)
```python
health = min(
    Account Health (READY/DEGRADED/BROKEN),
    Pipeline Health (active_gap, reconciliation)
)
```
Holdings Health 不独立参与健康度计算。

## 2. Existing Problems

### 2.1 Semantic Confusion
- **Problem**: `account_readiness=MISSING` 被触发当且仅当 `cash=None and total_asset=None`
- **Consequence**: Holdings 存在且有效时，Account MISSING 仍导致 BUY/ADD 阻断
- **Severity**: Medium（SELL/REDUCE 不受影响，但 Observation 可能误标记 DEGRADED）

### 2.2 Bitable Field Mapping Risk
- **Problem**: `_read_bitable_holdings()` 使用硬编码索引 `rec[0]` 到 `rec[7]`
- **Consequence**: Bitable 字段顺序变化 → 全部持仓解析错位
- **Severity**: High（历史上已发生字段污染事件）
- **Root Cause**: lark-cli `--field-id` 返回顺序 = 传参顺序，但无强制保证

### 2.3 Cost Data Quality
- **Problem**: 无 avg_cost/current_price/quantity 合理性校验
- **Consequence**: 异常成本直接进入 Decision 和 Feishu 输出
- **Severity**: Medium（历史已发生，影响止损告警）

### 2.4 Observation Health Incompleteness
- **Problem**: Holdings 数据质量不独立影响 Observation Health
- **Consequence**: Holdings PARTIAL 但 Account READY → 可能标记 HEALTHY（掩盖问题）
- **Severity**: Low-Medium

### 2.5 Legacy Module Coexistence
- **Problem**: `real_portfolio.py` (Phase 5.5) 与 `real_portfolio_truth.py` (Phase 7.5) 并存
- **Consequence**: 两套实现可能产生不一致
- **Severity**: Low（生产链路已切到 truth）

## 3. Recommended Architecture

### 3.1 Three-State-Machine Model
```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Real Holdings     │     │    Account Asset    │     │   Portfolio Risk    │
│   State Machine     │     │    State Machine    │     │   State Machine     │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│ READY: 持仓完整      │     │ READY: cash+total   │     │ READY: 历史峰值已知  │
│ PARTIAL: 部分字段    │     │ PARTIAL: 仅一项     │     │ UNKNOWN: 无历史峰值  │
│ MISSING: 无持仓      │     │ STALE/EXPIRED       │     │ CRISIS: 回撤>15%    │
└─────────┬───────────┘     │ MISSING: 无快照      │     └─────────────────────┘
          │                 │ UNKNOWN             │
          ▼                 └─────────┬───────────┘
┌─────────────────────────────────────┐      │
│         Decision Matrix             │      │
├─────────────────────────────────────┤      ▼
│ BUY/ADD: Holdings READY +           │  ┌─────────────────┐
│          Account READY              │  │ Portfolio Risk  │
│ SELL/REDUCE: Holdings READY/PARTIAL │  │ Check           │
│ HOLD: Holdings READY/PARTIAL        │  └─────────────────┘
│ Risk Alert: Holdings READY          │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│     Observation Health              │
│   min(Holdings, Account, Pipeline)  │
└─────────────────────────────────────┘
```

### 3.2 Key Principles
1. **Holdings ≠ Account**: 两个独立状态机，不合并
2. **SELL/REDUCE 不依赖 Account**: 有持仓即可执行
3. **BUY/ADD 必须 Account READY**: 无 cash/total_asset 禁止新仓
4. **三维健康度**: Holdings + Account + Pipeline 独立评估
5. **不自动推断**: cash/total_asset 保持 MANUAL_CONFIRMATION

## 4. Data Flow Diagram

```yaml
# Phase 8-H1 Recommended Architecture

Bitable:
  read: _read_bitable_holdings()
    -> quality_guard (NEW)
    -> holdings_state (NEW)
  write: (none, read-only)

Manual Confirmation:
  write: run_daily_snapshot(cash_manual, total_asset_manual)
    -> real_portfolio_history.db
  read: get_account_readiness()
    -> account_state

Decision:
  input: holdings_state + account_state + portfolio_risk_state
  gate: classify_actions()
    BUY/ADD -> require (holdings=READY, account=READY)
    SELL/REDUCE -> require (holdings in [READY, PARTIAL])
    HOLD -> require (holdings in [READY, PARTIAL])
  output: actions with sizing_status

Observation:
  health = min(holdings_health, account_health, pipeline_health)
  output: HEALTHY / DEGRADED / BROKEN

Feishu:
  input: Daily Contract report (read-only)
  output: Primary Message with quality/state markers
```

## 5. Scope of Changes

### 5.1 Phase 8-H1 (Design Only) — 本阶段输出
- `docs/design/REAL_HOLDINGS_ACCOUNT_SEPARATION_DESIGN.md` ✅
- `docs/design/BITABLE_FIELD_MAPPING_DESIGN.md` ✅
- `docs/design/REAL_HOLDINGS_DATA_QUALITY_GUARD.md` ✅
- `docs/design/REAL_HOLDINGS_H1_TEST_PLAN.md` ✅
- `docs/design/PHASE_8_H1_DESIGN_REVIEW.md` ✅ (this file)

### 5.2 Phase I (Future Implementation) — 需明确授权
- `real_portfolio_truth.py`: 增加 `BITABLE_FIELD_INDEX` + `_validate_field_order()`
- `real_portfolio_truth.py`: 增加 `_check_holding_quality()` → quality_guard
- `real_portfolio_truth.py`: 增加 `get_holdings_state()` → 独立状态机
- `daily_decision_contract.py`: `classify_actions()` 引入 Holdings State 判断
- `observation.py`: `_health_from_status()` 拆分为三维评估

### 5.3 Out of Scope (H1)
- 不修改 DecisionEngine
- 不修改 V1 规则
- 不修改 Portfolio Risk Rule
- 不修改 Strategy Selector
- 不接券商 API
- 不自动修正数据

## 6. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 误将 Holdings READY 当作 Account READY | Medium | High | 明确状态机命名 + 代码审查 |
| Bitable 字段漂移导致错位 | Medium | High | `BITABLE_FIELD_INDEX` 常量 + 启动校验 |
| Cost 异常值未检出 | Medium | Medium | Quality Guard 三层校验 |
| Observation 过度敏感 | Low | Medium | 三维取最小值，避免单点影响 |
| 旧版 real_portfolio.py 混淆 | Low | Low | 生产链路统一，旧版标记 DEPRECATED |
| 测试覆盖不足 | Medium | Medium | 25+ test cases 覆盖关键路径 |

## 7. Test Plan Summary

### 7.1 Test Coverage
| Area | Cases | Key Assertions |
|------|-------|----------------|
| Holdings | 4 | 正常/缺失/顺序/空持仓 |
| Account | 4 | 无现金/无总资产/手工/过期 |
| Quality | 5 | 正常/异常成本/异常价格/异常数量 |
| Decision | 6 | BUY/ADD 禁止, SELL/REDUCE 允许 |
| Observation | 4 | 三维健康度计算 |
| Field Mapping | 2 | 常量引用/漂移检测 |

### 7.2 Test File
- `decision/test_real_holdings_h1.py` (25+ cases)

### 7.3 Non-Functional Tests
- 不修改 Bitable
- 不调用真实 lark-cli
- 不修改 DecisionEngine
- 不涉及 V1

## 8. Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Real Holdings ≠ Account Asset | 数据源和能力完全不同 |
| 2 | 独立状态机 | 避免单一 READY/MISSING 掩盖部分可用性 |
| 3 | SELL/REDUCE 不依赖 Account | 有持仓即可执行 |
| 4 | BUY/ADD 必须 Account READY | 无总资产无法计算 target_quantity |
| 5 | Observation 三维健康度 | 更准确反映系统状态 |
| 6 | Bitable 迁移：常量引用 | 最小风险，单点维护 |
| 7 | Quality Guard: 只读告警 | 不自动修正，保持可审计 |
| 8 | 不接券商 API | 保持 MANUAL_CONFIRMATION 唯一入口 |

## 9. Open Questions

1. **Bitable field-id 顺序保证**: lark-cli 是否文档化保证 `--field-id` 顺序 = 返回顺序？
   - 当前实测：是。但未找到官方文档。
2. **Quality Guard 阈值**: `avg_cost/current_price > 10` 是否适用于所有 A 股（含 ST、新股）？
   - 建议：初期设 10，后续根据实际数据调整。
3. **Observation Health 阈值**: `active_pipeline_gap > 5` 是否仍适用？
   - 建议：保持现有阈值，后续根据生产数据调优。

## 10. Next Steps

1. 确认本设计文档
2. 授权进入 Phase I 实现（`BITABLE_FIELD_INDEX` + Quality Guard）
3. 实现 `test_real_holdings_h1.py`
4. 在 `double_monitor.py` 的测试运行中验证

---

**Design Status**: COMPLETE (read-only)
**Code Modified**: None
**Working Tree**: Clean
