# MARKET_DB_PIT_REPLAY_AUDIT.md（Phase 7.3-A）

## Executive Summary
**结论：当前 market.db 不足以支撑严格的历史时点重建（Point-in-Time Replay）。**

核心原因：
1. `indicators` 表只有当前快照，无历史时间序列
2. `stocks` 表只有当前快照，无历史 Universe
3. `financial_data` 缺少 announcement_date，无法区分报告期与可用日期
4. `pe_pb_data` 仅覆盖 2026-05-13 至 2026-07-30，且为当前快照
5. `main_fund_flow` / `north_flow_data` / `chip_data` / `margin_data` 均为极近期/空数据
6. V1 关键输入（MA20, ATR, MACD, signal_score, vol_ratio, turnover）依赖 indicators 表当前快照

因此：
- **Replay A（Signal Replay）**：不可行（indicators 无历史）
- **Replay B（Decision Replay）**：不可行（同上 + Portfolio 无历史快照）
- **Replay C（Full Lifecycle Replay）**：不可行（同上 + 无历史 Execution/Outcome）

**唯一可做**：基于 `klines` 表重建 OHLCV 信号，但需重新计算所有技术指标。

---

## 1. market.db Inventory

| Table | Rows | Date Min | Date Max | Codes | Key Columns | Producer / Source | Consumers |
|---|---:|---|---:|---|---|---|
| klines | 18,593,104 | 1991-01-29 | 2026-08-18 | 6,376 | code, date, open, close, high, low, volume, turnover | daily_data_refresh / westock | indicators, simulation, MAE/MFE |
| indicators | 5,187 | 1997-02-28 | 2026-08-18 | 5,187 | code, date, updated_at, ma5/10/20/60, atr_14, macd, signal_score | daily_data_refresh | V1 Decision Engine |
| financial_data | 383,639 | 1988-12-31 | 2026-06-30 | 6,366 | code, report_date, fetched_at, roe, eps, revenue | daily_data_refresh | Candidate, V1 |
| pe_pb_data | 69,604 | 2026-05-13 | 2026-07-30 | 5,188 | code, fetch_date, pe_ttm, pb_mrq | daily_data_refresh | Candidate, V1 |
| double_up_scores | 1,178 | 2026-05-15 | 2026-08-16 | 365 | scan_date, code, total_score, strategy | weekly_scan / pool_loader | Candidate Pool |
| main_fund_flow | 1,453 | 2026-07-17 | 2026-08-18 | 313 | code, date, net_amt | daily_data_refresh | Capital Flow |
| north_flow_data | 0 | - | - | 0 | code, date, change_shares | daily_data_refresh | - |
| chip_data | 50 | 2026-08-12 | 2026-08-18 | 10 | code, trade_date, chip_profit_rate | daily_data_refresh | Chip Analysis |
| margin_data | 35 | 2026-08-12 | 2026-08-18 | 7 | code, trade_date, finance_value | daily_data_refresh | Margin |
| holder_change | 35 | 2026-08-12 | 2026-08-18 | 7 | code, change_date, change_shares | daily_data_refresh | Holder |
| lockup_release | 0 | - | - | 0 | code, release_date | daily_data_refresh | Lockup |
| equity_pledge | 0 | - | - | 0 | code, pledge_ratio | daily_data_refresh | Pledge |
| stocks | 5,187 | - | - | 5,187 | code, name, market, list_date, sw_industry_name, is_st, total_mcap | daily_data_refresh | Universe |
| meta | 2 | - | - | - | key, value | daily_data_refresh | DB Metadata |
| pipeline_status | 67 | 2026-07-24 | 2026-08-18 | - | task_name, status, data_date | pipeline | Monitoring |
| param_optimization_log | 1 | 2026-07-25 | 2026-07-25 | - | date, rev_threshold, dd_low | param_verify | GA Optimization |

**附属：**
- `sqlite_sequence`（SQLite 内部自增序列）
- `sqlite_stat1`（SQLite 统计信息）

---

## 2. Table Semantics

### 2.1 klines（唯一完整历史时间序列）
- **一行代表**：单只股票单个交易日的 OHLCV
- **时间字段**：`date`（交易日）
- **时间语义**：observation_time = availability_time = T 日收盘后可用
- **数据生成**：daily_data_refresh / westock 每日收盘后下载
- **后验修订**：极低概率（A股官方不复权，但 westock 可能做增量修正）
- **未来信息**：无（仅到 T 日）
- **价格语义**：不复权原始价格（未区分前复权/后复权）
- **PIT Safety**：✅ SAFE（严格 T 日及以前）

### 2.2 indicators（当前快照，非时间序列）
- **一行代表**：单只股票当前的技术指标快照
- **时间字段**：`date`（指标计算截止日期）+ `updated_at`（数据更新时间）
- **时间语义**：date 是计算截止日期，updated_at 是 DB 刷新时间
- **关键发现**：每个 code 只有 1 行数据（5187 codes, 5187 rows）
- **数据生成**：daily_data_refresh 每日覆盖写入
- **后验修订**：每日覆盖，历史指标不保留
- **未来信息**：⚠️ 当前快照包含最新指标值，回放历史时会泄露未来
- **PIT Safety**：❌ BLOCKED（无历史指标序列）

### 2.3 financial_data（财务报告期数据）
- **一行代表**：单只股票单个报告期的财务指标
- **时间字段**：`report_date`（报告期截止日期）+ `fetched_at`（抓取时间）
- **时间语义**：
  - report_date = 报告期截止日（如 2025-06-30 表示 Q2 报告期）
  - fetched_at = 数据入库时间（2026-05-17）
- **关键风险**：缺少 `announcement_date`（公告日）和 `available_date`（实际可用日期）
- **后验修订**：可能（财报可能修订）
- **未来信息**：回放时可能提前使用未披露财报
- **PIT Safety**：⚠️ SAFE_WITH_LIMITATION（仅用 report_date 截止日以前的数据，但无法确认公告日）

### 2.4 pe_pb_data（估值数据）
- **一行代表**：单只股票某日的估值快照
- **时间字段**：`fetch_date`
- **时间语义**：fetch_date 是抓取日期，非报告期
- **关键发现**：仅覆盖 2026-05-13 至 2026-07-30，约 2.5 个月
- **PIT Safety**：⚠️ SAFE_WITH_LIMITATION（近期数据可用，历史缺失）

### 2.5 double_up_scores（候选池评分）
- **一行代表**：某 scan_date 对某股票的翻倍潜力评分
- **时间字段**：`scan_date`
- **时间语义**：每周五扫描生成
- **关键发现**：覆盖 2026-05-15 至 2026-08-16，约 3 个月
- **PIT Safety**：⚠️ SAFE_WITH_LIMITATION（仅近期可重建）

### 2.6 main_fund_flow（主力资金流）
- **一行代表**：单只股票单日主力净流入
- **时间字段**：`date`
- **时间语义**：T 日收盘后可用
- **关键发现**：仅覆盖 2026-07-17 至 2026-08-18，约 1 个月
- **PIT Safety**：⚠️ SAFE_WITH_LIMITATION（近期可用，历史缺失）

### 2.7 north_flow_data（北向资金）
- **状态**：空表（0 rows）
- **PIT Safety**：❌ BLOCKED（数据不存在）

### 2.8 stocks（股票静态信息）
- **一行代表**：单只股票的当前静态信息
- **时间字段**：`updated_at`（2026-08-18 16:30:25，所有行同时更新）
- **关键发现**：
  - `list_date`：多为 NULL
  - `sw_industry_code/name`：部分为 NULL
  - `total_mcap`：部分为 NULL
  - `is_st`：当前状态，非历史
- **PIT Safety**：❌ BLOCKED（无历史 Universe，无法重建历史股票状态）

### 2.9 meta（数据库元数据）
- **内容**：
  - `last_full_refresh` = 2026-07-27T16:36:45
  - `last_incremental_update` = 2026-08-18T16:38:47
- **用途**：数据 freshness 判断

---

## 3. V1 Decision Input Matrix

| Decision Input | Producer / Source | DB / Table | Field | Historical Coverage | Availability Known? | PIT Safe? | Risk |
|---|---|---|---|---|---|---|---|
| Market Regime | regime_detector | klines | date, close | 1991-2026 | ✅ observation_time = T 日 | ✅ SAFE | None |
| Candidate Score | candidate_evaluator | klines, indicators | ma20, atr_14, vol_ratio | 1991-2026 (klines only) | ✅ T 日收盘后 | ❌ BLOCKED | indicators 无历史序列 |
| Market Cap | stocks | total_mcap | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK / SURVIVORSHIP_RISK |
| Volume Ratio | indicators | vol_ratio | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK |
| ATR(14) | indicators | atr_14 | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK |
| MA20 | indicators | ma20 | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK |
| MACD | indicators | macd | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK |
| Industry | stocks | sw_industry_name | current snapshot | ❌ 仅当前 | ❌ UNKNOWN | ❌ BLOCKED | HISTORICAL_CLASSIFICATION_RISK |
| Permission | trading_permission | - | runtime | ❌ 无历史 | ❌ UNKNOWN | ⚠️ SAFE_WITH_LIMITATION | 无法重建历史 Portfolio Context |
| Portfolio Assessment | portfolio_assessor | - | runtime | ❌ 无历史 | ❌ UNKNOWN | ⚠️ SAFE_WITH_LIMITATION | 无历史账户/持仓/现金 |
| Entry Signal | entry_assessment | klines, indicators | multiple | ❌ indicators 无历史 | ❌ UNKNOWN | ❌ BLOCKED | LOOKAHEAD_RISK |
| Exit Reason | exit_assessment | - | runtime | ❌ 无历史 | ❌ UNKNOWN | ⚠️ SAFE_WITH_LIMITATION | 需重建完整 Position Lifecycle |

**核心结论**：V1 的 5 个关键技术指标（MA20, ATR, MACD, vol_ratio, signal_score）全部来自 `indicators` 表，而该表只有当前快照。历史 Replay 无法获得 T 日的指标值。

---

## 4. Decision Timing

### 4.1 当前生产时序
```
T 日收盘
  → klines 数据最终可用（T+1 日凌晨）
  → indicators 计算完成（T+1 日盘中）
  → double_up_scores 生成（T+1 日盘中/收盘）
  → Market Regime 计算（T+1 日盘中）
  → Candidate / Entry 评估（T+1 日盘中）
  → Decision 生成（T+1 日盘中）
  → T+1 开盘执行
```

### 4.2 代码验证
- `decision/engine.py:97`：`d.timestamp = datetime.now(timezone.utc).isoformat()`
- `daily_data_refresh.py:46`：`SELECT MAX(date) FROM klines` 判断最新数据
- `track_flow_manager.py:271-272`：`SELECT MAX(date) FROM klines` + `date.today()` 判断数据 freshness

**关键发现**：DecisionEngine 本身不硬编码时间，但调用方 `track_flow_manager.py` 使用 `date.today()` 判断数据是否足够新。历史回放时需替换为 as_of_time。

---

## 5. Point-in-Time Safety Matrix

| Component | T-day Data | Availability Known | Future Leakage Risk | Safe for Replay |
|---|---|---|---|---|
| OHLCV | klines 1991-2026 | ✅ | ❌ None | ✅ SAFE |
| Market Regime | klines-derived | ✅ | ❌ None | ✅ SAFE |
| Candidate Score | indicators current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| Market Cap | stocks current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| Volume Ratio | indicators current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| ATR(14) | indicators current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| MA20 | indicators current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| MACD | indicators current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| Industry | stocks current | ❌ UNKNOWN | ❌ BLOCKED | ❌ BLOCKED |
| Permission | runtime only | ❌ UNKNOWN | ❌ BLOCKED | ⚠️ SAFE_WITH_LIMITATION |
| Portfolio | runtime only | ❌ UNKNOWN | ❌ BLOCKED | ⚠️ SAFE_WITH_LIMITATION |
| Financials | financial_data 1988-2026 | ⚠️ partial | ⚠️ LOW | ⚠️ SAFE_WITH_LIMITATION |
| Capital Flow | main_fund_flow 2026-07 | ⚠️ partial | ❌ None | ⚠️ SAFE_WITH_LIMITATION |
| North Flow | 空表 | ❌ N/A | ❌ N/A | ❌ BLOCKED |
| Events | 无事件表 | ❌ N/A | ❌ N/A | ❌ BLOCKED |

---

## 6. Look-ahead Risks

### 6.1 indicators 表（高危）
- **问题**：每个 code 只有 1 行当前指标值
- **风险**：回放 T 日时，读取到的是 T+n 日的指标值
- **代码位置**：`daily_data_refresh.py` 每日 `INSERT OR REPLACE`
- **修复方向**：建立 indicators 时间序列表，保留每日指标快照

### 6.2 stocks 表（高危）
- **问题**：current snapshot，无历史变更记录
- **风险**：回放时使用当前市值、行业分类、ST 状态
- **代码位置**：`stocks` 表 `updated_at` 全部为 2026-08-18
- **修复方向**：建立 stocks_history 表，或从 klines 重建历史 Universe

### 6.3 financial_data（中危）
- **问题**：缺少 announcement_date
- **风险**：回放 T 日时可能提前使用未披露财报
- **修复方向**：接入真实公告日期，或保守假设 report_date + N 个月后可用

### 6.4 pe_pb_data（中危）
- **问题**：仅覆盖 2026-05-13 至今
- **风险**：历史回放缺少估值数据
- **修复方向**：扩展历史 PE/PB 数据

### 6.5 double_up_scores（低危）
- **问题**：仅 2026-05-15 至今
- **风险**：历史候选池无法重建
- **修复方向**：扩展历史候选评分

### 6.6 track_flow_manager.py:271-272（高危）
- **代码**：
  ```python
  _mx = _m.execute("SELECT MAX(date) FROM klines").fetchone()[0]
  _lag = (date.today() - _dt.strptime(str(_mx)[:10], '%Y-%m-%d').date()).days if _mx else 999
  ```
- **风险**：回放时 `date.today()` 是当前日期，不是历史日期
- **修复方向**：用 as_of_time 替换 date.today()

---

## 7. Survivorship Risks

### 7.1 当前股票 Universe
- `stocks` 表：5,187 条记录
- `klines` 表：6,376 个 distinct codes
- **差异**：1,189 个 codes 在 klines 中有数据，但在 stocks 表中无记录

### 7.2 退市股票
- `stocks` 表中 `list_board` 多为 NULL
- `list_date` 多为 NULL
- 无法区分：当前上市 / 已退市 / 暂停上市
- **风险**：回放时 Universe 包含已退市股票（Survivorship Bias）
- **修复方向**：接入上市/退市日期，建立 as-of Universe 重建逻辑

### 7.3 ST 股票
- `stocks.is_st` 有值，但无历史变更记录
- **风险**：回放时使用当前 ST 状态判断历史
- **修复方向**：建立 ST 历史变更记录

---

## 8. Price Semantics

### 8.1 当前价格定义
- `klines.open/close/high/low`：原始价格，不复权
- `indicators.current_price`：可能是原始价格或后复权价格（未明确）
- `indicators.ma20/macd/atr_14`：基于 indicators 表中的 current_price 计算

### 8.2 复权问题
- **未发现**：前复权/后复权价格字段
- **未发现**：split/dividend 调整记录
- **风险**：MA20/MACD/ATR 可能基于原始价格，但策略可能期望复权价格
- **修复方向**：明确 V1 使用的价格语义，保持一致

### 8.3 价格冲突
- `klines.close` vs `indicators.current_price`：可能不一致
- **标记**：PRICE_SEMANTIC_CONFLICT（待确认）

---

## 9. Portfolio Historical Replay

### 9.1 当前状态
- 无历史账户资产快照
- 无历史持仓快照
- 无历史现金快照
- `real_portfolio.py` 读取实时账户状态

### 9.2 结论
**PORTFOLIO_REPLAY_MODE: NONE**

无法重建历史 Portfolio Context。历史 Replay 只能做：
- **单票策略 Replay**（独立评估每只股票的 Entry/Exit）
- 无法模拟真实组合效果（仓位、回撤、暴露）

### 9.3 与真实 Portfolio Decision 的差异
| 维度 | 真实 Production | 单票 Replay |
|---|---|---|
| 账户资产 | 实时 | ❌ 无 |
| 持仓 | 实时 | ❌ 无 |
| 现金 | 实时 | ❌ 无 |
| 回撤控制 | 真实 | ❌ 无法模拟 |
| 暴露控制 | 真实 | ❌ 无法模拟 |
| 个股评估 | 真实 | ✅ 可模拟 |
| Entry 信号 | 真实 | ✅ 可模拟（需重建指标） |
| Exit 信号 | 真实 | ✅ 可模拟（需重建 K 线） |

---

## 10. Replay A/B/C Feasibility

### 10.1 Replay A：Signal Replay
**目标**：重建 Market Regime + Candidate + Entry

**可行性**：❌ 不可行

**原因**：
1. `indicators` 表无历史序列，无法获取 T 日的 MA20/ATR/MACD
2. `stocks` 表无历史市值/行业
3. 需从 klines 重新计算所有指标（可行但需改造代码）

### 10.2 Replay B：Decision Replay
**目标**：重建 Regime + Permission + Candidate + Entry + Portfolio + DecisionEngine

**可行性**：❌ 不可行

**原因**：
1. 同 Replay A 的所有问题
2. Permission 无历史记录
3. Portfolio 无历史快照

### 10.3 Replay C：Full Lifecycle Replay
**目标**：重建 Decision → Execution → Position → Exit → Outcome

**可行性**：❌ 不可行

**原因**：
1. 同 Replay B 的所有问题
2. 无历史 Execution 记录
3. 无历史 Exit 记录
4. 无历史 Outcome 记录

---

## 11. Historical Replay Gap Matrix

| Requirement | Available | PIT Safe | Coverage | Blocker | Notes |
|---|---|---|---|---|---|
| Universe | ❌ | ❌ | 0% | BLOCKED | stocks 表无历史 |
| OHLCV | ✅ | ✅ | 1991-2026 | None | klines 完整 |
| Market Regime | ✅ | ✅ | 1991-2026 | None | 可从 klines 重建 |
| Market Cap | ❌ | ❌ | 0% | BLOCKED | stocks.total_mcap 当前快照 |
| Candidate Features | ❌ | ❌ | 0% | BLOCKED | indicators 无历史 |
| Regime | ✅ | ✅ | 1991-2026 | None | 可从 klines 重建 |
| Permission | ❌ | ❌ | 0% | BLOCKED | 无历史记录 |
| Portfolio | ❌ | ❌ | 0% | BLOCKED | 无历史快照 |
| Entry | ❌ | ❌ | 0% | BLOCKED | 依赖 indicators 当前快照 |
| Exit | ❌ | ❌ | 0% | BLOCKED | 依赖 indicators + 无历史 Exit |
| Outcome | ❌ | ❌ | 0% | BLOCKED | 无历史 Outcome |

**结论**：当前 market.db 仅支持 **基于 klines 的纯 OHLCV 信号重建**，不支持任何 Decision/Portfolio/Outcome 的历史重建。

---

## 12. Point-in-Time Data Contract

### 12.1 时间字段定义
| 字段 | 语义 | 当前实现 | 缺失 |
|---|---|---|---|
| observation_time | 数据观察/生成时间 | `date`（klines） | ✅ 存在 |
| availability_time | 数据对交易系统可用时间 | `date + 1 日`（klines 次日可用） | ⚠️ 未显式存储 |
| calculation_time | 指标计算时间 | `updated_at`（indicators） | ⚠️ 存在但非时间序列 |
| decision_time | Decision 生成时间 | `timestamp`（Decision） | ✅ 存在 |
| execution_time | 执行时间 | `execution_time`（Execution） | ✅ 存在 |
| report_period | 财报报告期 | `report_date`（financial_data） | ✅ 存在 |
| announcement_date | 公告披露日 | ❌ 缺失 | ❌ 缺失 |
| available_date | 数据实际可用日 | ❌ 缺失 | ❌ 缺失 |

### 12.2 关键问题
1. **financial_data**：`report_date` 存在，但 `announcement_date` / `available_date` 缺失
2. **indicators**：`date` + `updated_at` 存在，但无历史时间序列
3. **pe_pb_data**：`fetch_date` 存在，但无历史序列

---

## 13. Replay Architecture（设计，不实现）

### 13.1 当前架构
```
Production:
  Market Data → Market Regime → Candidate → Permission → Portfolio → DecisionEngine → Decision
  Decision → Execution → Position → Exit → Outcome → Evaluation
```

### 13.2 Historical Replay 架构（建议）
```
Historical Date T:
  Point-in-Time Data Adapter
    ├── klines (T 日及以前)
    ├── indicators_calculator (从 klines 实时计算 T 日指标)
    ├── stocks_snapshot (T 日 Universe)
    ├── financial_data (report_date <= T 且 announcement_date <= T)
    └── portfolio_snapshot (T 日账户状态，若无则用 NONE)
        ↓
  Market Regime (可从 klines 重建)
    ↓
  Candidate (需重建指标)
    ↓
  Permission (若无历史 → NONE)
    ↓
  Portfolio (若无历史 → NONE)
    ↓
  DecisionEngine (需全量输入)
    ↓
  Historical Decision Snapshot
    ↓
  T+1 Execution (模拟)
    ↓
  Future K-lines (Outcome)
    ↓
  HISTORICAL_REPLAY Outcome
```

### 13.3 可复用模块
- ✅ `decision/engine.py` — 纯函数，可直接复用
- ✅ `decision/contract.py` — 数据结构定义
- ✅ `decision/execution.py` — Execution/Outcome 生成逻辑
- ✅ `decision/outcome.py` — Outcome 数据结构
- ✅ `evaluation/run_evaluation.py` — Evaluation Framework
- ✅ `klines` 表 — 完整历史 OHLCV

### 13.4 必须新增
- ❌ **Historical Data Adapter** — 从 klines 重建 T 日 indicators
- ❌ **Universe As-of Service** — 重建 T 日股票 Universe
- ❌ **Portfolio Snapshot Service** — 历史 Portfolio Context（或显式标记 NONE）
- ❌ **Decision Snapshot Store** — 存储 Historical Decision
- ❌ **HISTORICAL_REPLAY source** — 新增数据分类

---

## 14. Production vs Historical Replay 隔离

### 14.1 数据分类扩展
当前：`PRODUCTION / SIMULATION / TEST / SHADOW / LEGACY / COUNTERFACTUAL`
建议增加：`HISTORICAL_REPLAY`

### 14.2 隔离规则
- Historical Replay 数据不得写入：
  - Production Outcome
  - Production Evaluation Dataset
  - Real Positions
  - Real Executions
- Historical Replay 必须独立存储：
  - `historical_decisions/`
  - `historical_outcomes/`
  - `historical_executions/`

### 14.3 代码改造点
1. `decision/execution.py`：`record_simulation_execution` 新增 `run_mode='HISTORICAL_REPLAY'`
2. `evaluation/run_evaluation.py`：`_classify_source` 增加 HISTORICAL_REPLAY 分类
3. `is_production_qualified`：HISTORICAL_REPLAY 永远不进入 Production Evaluation

---

## 15. 特别检查：当前代码是否会偷偷使用未来信息

### 15.1 date.today() 使用
| 文件 | 行号 | 代码 | 风险 |
|---|---|---|---|
| track_flow_manager.py | 163 | `date.today().isoformat()` | 记录当前日期，回放时需替换 |
| track_flow_manager.py | 271-272 | `date.today() - MAX(date)` | 数据 freshness 检查，回放时需替换 |
| simulation_weekly.py | 20,78,112 | `date.today()` / `MAX(date)` | 周报生成，非生产路径 |
| news_sentiment.py | 298,395 | `date.today()` | 新闻情感，非 V1 路径 |
| data_filters.py | 254 | `date.today().isoformat()` | 过滤条件，非 V1 路径 |

### 15.2 MAX(date) / latest 使用
| 文件 | 行号 | 代码 | 风险 |
|---|---|---|---|
| daily_data_refresh.py | 46-47 | `SELECT MAX(date) FROM klines` | 数据刷新判断，非决策路径 |
| simulation_weekly.py | 78 | `SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1` | 获取最新收盘价，回放时需用 as_of_date |
| track_flow_manager.py | 271 | `SELECT MAX(date) FROM klines` | freshness 检查，回放时需替换 |
| heartbeat.py | 68 | `SELECT MAX(date) FROM klines` | 心跳检查，非决策路径 |

### 15.3 结论
**V1 生产决策路径本身不直接调用 `date.today()` 或 `MAX(date)`。**
所有时间信息通过 `ctx` 传入 DecisionEngine。
**风险在于调用方**（`track_flow_manager.py`）在构建 `ctx` 时使用当前日期/最新数据。

---

## 16. 财务披露时间风险

### 16.1 当前状态
- `financial_data` 有 `report_date`（报告期）和 `fetched_at`（入库时间）
- **缺少** `announcement_date`（公告披露日）
- **缺少** `available_date`（数据对交易系统可用日期）

### 16.2 风险场景
1. 2025-06-30 的 Q2 报告，可能在 2025-08-30 才公告
2. 回放 2025-08-15 时，不应使用该财报
3. 当前无法区分：报告期 vs 公告日 vs 可用日

### 16.3 标记
**DISCLOSURE_DATE_UNKNOWN**

---

## 17. 价格/复权语义

### 17.1 当前价格
- `klines`：原始价格，不复权
- `indicators.current_price`：可能为原始或复权（未明确标注）

### 17.2 V1 使用的价格
- `indicators.ma20/atr_14/macd`：基于 indicators 表的 current_price
- `klines.close`：原始价格
- 未发现前复权/后复权字段

### 17.3 风险
**PRICE_SEMANTIC_CONFLICT**
- indicators 表价格可能与 klines 不一致
- 回放时需确保 V1 使用统一的 klines 原始价格

---

## 18. Known Limitations

1. **indicators 表无历史序列**：最大阻塞，无法重建 V1 技术指标
2. **stocks 表无历史**：无法重建历史 Universe、市值、行业
3. **financial_data 无公告日**：无法确认财报披露时间
4. **pe_pb_data 覆盖短**：仅 2.5 个月
5. **main_fund_flow 覆盖短**：仅 1 个月
6. **north_flow_data 为空**：无北向资金数据
7. **无历史 Portfolio Context**：无法模拟真实组合效果
8. **无历史 Permission**：无法重建 Trading Permission
9. **无历史 Execution/Outcome**：无法验证历史决策结果
10. **代码中 date.today()/MAX(date)**：回放时需替换为 as_of_time

---

## 19. Recommendation

### 19.1 短期（立即）
1. **不要运行全市场 Historical Replay**
2. **不要修改 V1 策略**以适配缺失数据
3. **不要放宽指标计算**以“凑合”回放

### 19.2 中期（下一阶段）
1. **建立 indicators 时间序列表**
   - 每日收盘后保存完整指标快照
   - 字段：code, date, ma5, ma10, ma20, ma60, atr_14, macd, signal_score, vol_ratio, ...
2. **建立 stocks_history 表**
   - 记录每日 stocks 快照
   - 字段：code, date, total_mcap, sw_industry_name, is_st, ...
3. **接入 financial_data announcement_date**
   - 从财报公告抓取真实披露日期
4. **扩展 pe_pb_data 历史覆盖**

### 19.3 长期（数据层完善后）
1. 可支持 Replay A（Signal Replay）
2. 可支持 Replay B（Decision Replay，需 Portfolio Snapshot）
3. 可支持 Replay C（Full Lifecycle Replay）

### 19.4 当前唯一可行方案
**基于 klines 的纯价格信号重建**：
1. 从 klines 计算 T 日技术指标（MA, ATR, MACD, Volume Ratio）
2. 从 klines 计算 Market Regime
3. 独立评估 Entry/Exit 信号
4. **不声称这是完整 V1 Replay**，而是“klines-based signal audit”

---

## 20. Final Answer

> **如果把当前已经投入生产的 V1 + Market Regime + Trading Permission + Portfolio Decision + DecisionEngine 放回历史某个交易日，系统能否只使用“当时已经可获得的信息”，真实重建当时应该产生的 Decision？**

**答案：不能。**

原因：
1. V1 的 5 个关键输入（MA20, ATR, MACD, vol_ratio, signal_score）来自 `indicators` 表，该表只有当前快照
2. Market Cap / Industry 来自 `stocks` 表，该表只有当前快照
3. Permission / Portfolio 无历史记录
4. 财务数据缺少公告日，无法确认 T 日是否可用
5. 北向资金/筹码/龙虎榜等数据为空或覆盖极短

**当前 market.db 仅支持基于 klines 的纯 OHLCV 信号重建，不支持严格的历史时点 Decision Replay。**
