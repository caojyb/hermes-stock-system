# HISTORICAL_MARKET_CAP_RECONSTRUCTION.md（Phase 7.3-D）

## 1. V1 Market Cap Semantics

### 1.1 生产代码追踪
`scan_doubling_potential.py:51-52`：
```python
SELECT code, name, total_mcap, sector FROM stocks
WHERE total_mcap BETWEEN ? AND ?
```

### 1.2 参数来源
`stock_strategy_config.py`：
- `mcap_min = 5`（亿）
- `mcap_max = 90`（亿）

### 1.3 过滤逻辑
```python
mcap_min * 1e8 = 5亿 = 500,000,000 元
mcap_max * 1e8 = 90亿 = 9,000,000,000 元
```

### 1.4 结论
- **V1 使用**：`stocks.total_mcap`（总市值，单位：元）
- **过滤条件**：`500,000,000 <= total_mcap <= 9,000,000,000`
- **标记**：`V1_MARKET_CAP_SEMANTICS = TOTAL_MARKET_CAP_RMB`

---

## 2. Global Share Data Inventory

### 2.1 搜索范围
已搜索：
- market.db（所有表）
- 本地其他 SQLite 数据库
- CSV/JSON/Parquet 文件
- westock-data 技能（profile 命令）
- cn_financial MCP 工具
- 备份/缓存/历史同步文件

### 2.2 搜索结果
| Source | Table/File | Rows | Codes | Date Range | Share Field | Date Field | PIT Signal | Usable |
|---|---|---:|---:|---|---|---|---|---|
| market_cache.db:stocks | total_shares_real | 0 | 0 | - | - | - | ❌ | ❌ |
| market_cache.db:stocks | circulating_shares_real | 0 | 0 | - | - | - | ❌ | ❌ |
| market_cache.db:financial_data | 无股本字段 | - | - | - | - | - | ❌ | ❌ |
| market_cache.db:klines | 无股本字段 | - | - | - | - | - | ❌ | ❌ |
| market_cache.db:lockup_release | release_shares | 0 | 0 | - | - | - | ❌ | ❌ |
| market_cache.db:holder_change | change_shares | 35 | 7 | 2026-08-12 | 变动股数 | change_date | ❌ | ❌ |
| westock profile | regCapital | 5,187 | 5,187 | 静态 | 注册资本 | - | ❌ | ❌ |
| cn_financial MCP | get_market_capitalization | 超时 | - | - | - | - | ❌ | ❌ |
| cn_financial MCP | get_per_share_data | 有数据 | 部分 | 1989-2026 | 无股本字段 | 报告期 | ❌ | ❌ |
| 本地 CSV/JSON | 无 | - | - | - | - | - | ❌ | ❌ |

### 2.3 结论
**HISTORICAL_SHARE_DATA = NOT_FOUND**

本地环境不存在可信的历史股本数据源。

---

## 3. Historical Share Data Sources

### 3.1 各来源详细审计

#### 3.1.1 market_cache.db:stocks
- `total_shares_real`：全为 NULL
- `circulating_shares_real`：全为 NULL
- `total_mcap`：当前快照（5,026/5,187 有值）
- 无历史股本序列

#### 3.1.2 market_cache.db:financial_data
- 383,639 行，1988-2026
- 字段：EPS、BPS、现金流、ROE、毛利率等
- **无股本字段**（total_shares / float_shares）

#### 3.1.3 market_cache.db:holder_change
- 35 行，2026-08-12
- 字段：change_shares、change_type、change_date
- 仅记录近期股东增减持，**非历史股本**

#### 3.1.4 market_cache.db:lockup_release
- 0 行
- 无解禁数据

#### 3.1.5 westock profile: regCapital
- 返回：`regCapital`（注册资本）
- 性质：**静态注册资金**，非股本数量
- 单位：万元（999747.0888 = ~10 亿元）
- **不能用于计算市值**

#### 3.1.6 cn_financial MCP
- `get_market_capitalization`：超时
- `get_per_share_data`：有 EPS/BPS 等，**无股本字段**
- `get_company_info`：返回错误
- **无法作为历史股本来源**

#### 3.1.7 fix_total_shares_real.py
- 方法：`total_shares_real = total_mcap / close_price`
- 结果：推算当前股本，**非历史股本**
- 限制：仅适用于当前日期

---

## 4. Point-in-Time Rules

### 4.1 当前约束
- 无历史股本数据 → 无法建立 PIT 股本序列
- `stocks.total_mcap` 为当前快照 → 禁止回填历史
- westock `regCapital` 为静态值 → 禁止用于市值计算

### 4.2 硬性规则
```python
# 历史 T 日
historical_market_cap(T) = UNKNOWN
# 原因：无 historical_share_count(T)
```

---

## 5. Share Effective Date

**不适用。** 无历史股本数据，无有效日期。

---

## 6. Corporate Actions

**不适用。** 无历史股本数据，无法追踪 corporate action 对股本的影响。

---

## 7. Historical Market Cap Formula

### 7.1 理想公式
```
historical_market_cap(T) = historical_total_shares(T) × close(T)
```

### 7.2 当前可用数据
- `close(T)`：✅ 可用（klines）
- `historical_total_shares(T)`：❌ 不可用

### 7.3 结论
**无法计算 historical_market_cap(T)**

---

## 8. Validation

### 8.1 与 Production Market Cap 对照
**无法进行。** 无历史股本数据。

### 8.2 如果有历史股本数据
需要验证：
- exact_match
- within_tolerance
- mismatch
- absolute_error
- relative_error
- mismatch_rate

**当前状态**：DATA_INSUFFICIENT

---

## 9. Coverage

### 9.1 股票覆盖率
**0%**（无历史股本数据）

### 9.2 日期覆盖率
**0%**（无历史股本数据）

### 9.3 年份覆盖率
**0%**（无历史股本数据）

---

## 10. 5-90B Filter Historical Feasibility

### 10.1 当前 V1 过滤
```python
WHERE total_mcap BETWEEN 5e8 AND 9e9
```

### 10.2 历史可行性
**不可行。**
- 原因：无 historical_total_mcap(T)
- 如果用当前 total_mcap 回填：LOOKAHEAD_RISK
- 如果用当前 total_shares × historical close：需要 total_shares 历史，但 total_shares_real 全为 NULL

### 10.3 结论
**5-90 亿 V1 Filter 无法历史重放**

---

## 11. Failure / Blocked Cases

| Case | Status | Reason |
|---|---|---|
| IPO 前 | NO_DATA | 无股本数据 |
| 退市后 | NO_DATA | 无股本数据 |
| 正常交易日 | BLOCKED | 无历史股本 |
| 股本变化日 | DATA_INSUFFICIENT | 无 corporate action 记录 |
| 送转/拆股 | DATA_INSUFFICIENT | 无调整因子 |

---

## 12. Universe Relationship

### 12.1 Historical Universe
- 基于 klines 首末交易日：5,837 codes（2024-06-30）
- 包含活跃和已退市股票

### 12.2 Market Cap 与 Universe 关系
- V1 从 Universe 中过滤 `total_mcap BETWEEN 5e8 AND 9e9`
- 历史回放时：Universe 可重建（PARTIAL），但 Market Cap 不可重建
- **结果**：历史 Universe 可得到，但无法应用 V1 的市值过滤

---

## 13. ST Limitation

**保留 Phase 7.3-C 结论：**
- Historical ST = BLOCKED
- 无历史 ST 变更记录
- Replay Impact: HIGH

---

## 14. Portfolio Limitation

**保留 Phase 7.3-C 结论：**
- PORTFOLIO_REPLAY_MODE = NONE
- 无历史账户/持仓/现金快照

---

## 15. Recommendation

### 15.1 下一阶段先做什么
**接入真实历史股本数据源。**

可行方案：
1. **东方财富 Choice / 巨潮资讯**
   - 通过 EMQuantAPI 获取历史股本数据
   - 需要确认：字段名、日期有效性、更新频率

2. **akshare / tushare**
   - akshare 有 `stock_individual_info_em` 等接口
   - 但需要确认是否有历史股本序列

3. **web scraping**
   - 从巨潮资讯网抓取历史股本变动公告
   - 工作量较大，但数据权威

### 15.2 不要做什么
- 不要用当前 `stocks.total_mcap` 回填历史
- 不要用 `westock profile.regCapital` 计算市值
- 不要放宽 V1 的 5-90 亿过滤条件

---

## 16. Known Limitations

1. **无历史股本数据**：本地环境不存在任何可信的历史股本数据源
2. **westock regCapital 非股本**：是注册资本，不能用于市值计算
3. **cn_financial MCP 不稳定**：超时/错误，无法作为可靠数据源
4. **fix_total_shares_real 仅当前**：推算的是当前股本，非历史
5. **holder_change 非股本**：仅记录股东增减持，非总股本变化
6. **lockup_release 为空**：无解禁数据
7. **5-90 亿过滤无法历史重放**：直接阻塞 Replay A/B/C

---

## 17. Final Answers

### 17.1 Hermes 当前所有数据源中是否存在可信 Historical Share Data？
**否。**
- 已搜索：market.db、本地其他数据库、CSV/JSON、westock、cn_financial MCP
- 结论：无任何可信的历史股本数据源

### 17.2 V1 到底使用哪种 Market Cap？
**总市值（total_mcap），单位：元。**
- 过滤条件：5-90 亿（5e8 - 9e9 元）
- 数据来源：`stocks.total_mcap`
- 代码位置：`scan_doubling_potential.py:51-52`

### 17.3 历史市值能否由 Point-in-Time 股本 × 历史价格重建？
**否。**
- 原因：无 historical_share_count(T)
- close(T) 可用（klines），但股本不可用

### 17.4 如果能，覆盖多少？
**0%。**

### 17.5 如果不能，缺什么？
**历史股本数据（total_shares / float_shares）的时间序列。**

### 17.6 哪些年份/股票可重建？
**无。**

### 17.7 股本变动日期是否可靠？
**不适用（无数据）。**

### 17.8 corporate action 是否会产生误差？
**不适用（无数据）。**

### 17.9 5-90 亿 V1 Filter 能否历史重放？
**否。**
- 需要 historical_market_cap(T)
- 但 historical_market_cap(T) = UNKNOWN

### 17.10 Market Cap 当前是否仍为 Replay Blocker？
**是。**
- 状态：BLOCKED
- 影响：HIGH

### 17.11 ST 是否仍为 Blocker？
**是。**
- 状态：BLOCKED
- 影响：HIGH

### 17.12 Portfolio 是否仍为 Blocker？
**是。**
- 状态：NONE
- 影响：HIGH

### 17.13 Replay A/B/C 的状态是否变化？
**否。**
- Replay A: BLOCKED
- Replay B: BLOCKED
- Replay C: BLOCKED

### 17.14 下一步应该先做什么？
**接入真实历史股本数据源（东方财富 Choice / 巨潮资讯 / akshare）。**
- 这是解锁 Historical Market Cap 的唯一路径
- 只有 Market Cap 解锁后，Replay A/B/C 才有可行性
