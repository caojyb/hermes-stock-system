# HISTORICAL_MARKET_STATE_RECONSTRUCTION.md（Phase 7.3-C）

## 1. Signal Score Audit

### 1.1 生产代码中的 Signal Score
- `daily_data_refresh.py:363`：硬编码为 `0`
- `indicators` 表中有 `signal_score` 列，但主流程不计算真实值

### 1.2 实际数据中的 Signal Score
- 总行数：5,187
- 非零值：703 (13.6%)
- 分布：主要集中在 2026-08 (535) 和 2022-06 (25)
- 来源：其他脚本/旧系统回写

### 1.3 Signal Score 是否参与 V1 Decision
沿生产代码追踪：
- `decision/engine.py`：无 `signal_score` 引用
- `scan_doubling_potential.py`：不读取 `signal_score`
- `stock_opportunity_scan.py`：读取 `signal_score >= 40` 作为候选筛选
- `track_flow_manager.py`：不读取 `signal_score`

**结论**：
- `signal_score` 不参与 V1 DecisionEngine / Entry / Portfolio / Exit
- 仅用于 `stock_opportunity_scan.py` 的候选股筛选（推送用）
- **标记**：`NON_DECISIONAL_FIELD`
- **Replay 影响**：LOW（不影响 V1 Historical Replay）

---

## 2. ATR Production Source Audit

### 2.1 生产代码中的 ATR
| 脚本 | 是否计算 ATR | 是否写入 indicators |
|---|---|---|
| `daily_data_refresh.py` | ❌ 不计算 | ❌ 写入 NULL |
| `scan_doubling_potential.py` | ✅ 自己计算 | ❌ 不写入 indicators |
| `position_stop_loss_alert.py` | ❌ 不计算 | ✅ 读取 indicators.atr_14 |
| `v1_stress_test.py` | ✅ 自己计算 | ❌ 不写入 indicators |
| `param_verify_full.py` | ✅ 自己计算 | ❌ 不写入 indicators |

### 2.2 indicators.atr_14 实际状态
- 非 NULL 数量：782 (15.1%)
- 时间分布：主要集中在 2026-08 (606)
- 来源：某些脚本/旧系统回写

### 2.3 结论
- **indicators.atr_14 非权威生产 ATR 来源**
- 生产扫描脚本（`scan_doubling_potential.py`）每次运行时从 klines 重新计算 ATR
- **标记**：`PRODUCTION_FEATURE_SEMANTICS_UNKNOWN`
- **Replay 影响**：NONE（ATR 可从 klines 重建）

---

## 3. MA20 Mismatch 分类

### 3.1 对比结果
- 抽样：100 个 samples（production indicators 中 `ma20 IS NOT NULL`）
- EXPECTED_DIFFERENCE（<5%）：62
- FORMULA_DIFFERENCE（>5%）：38

### 3.2 FORMULA_DIFFERENCE 案例分析
**000502 2022-06-24**：
- production ma20 = 1.5075
- historical ma20 = 0.7289
- 相对差异：51.65%

**根因分析**：
1. 000502 在 2022-06-06 出现价格跳跃：从 ~1.4 跳到 0.52
2. 2022-06-27 又从 0.52 跳回 ~1.16
3. 这是真实的市场事件（可能：退市整理期拆细/送转/风险警示）
4. production indicators 使用原始价格序列计算 MA20
5. 历史重建也使用相同价格序列
6. 但 000502 在 2022-06 后名称变为"绿景退"，属于退市股票

**其他可能原因**：
1. **价格语义差异**：production indicators 可能使用了不同的价格源（如前复权 vs 不复权）
2. **数据截断**：production indicators 可能只使用了部分 K 线数据
3. **后验数据**：production indicators 可能包含了后验修正的价格
4. **warm-up 差异**：边界处理不同

### 3.3 分类结果
| 类别 | 数量 | 原因 |
|---|---|---|
| EXPECTED_DIFFERENCE | 62 | 正常计算差异（<5%） |
| FORMULA_DIFFERENCE | 38 | 可能包含后验数据/价格语义差异 |
| DATA_DIFFERENCE | 0 | 无 |
| TIME_ALIGNMENT_DIFFERENCE | 0 | 无（早期数据 warm-up 已处理） |
| PRICE_SEMANTIC_CONFLICT | 0 | 未确认 |

### 3.4 结论
**MA20 PIT validation 不得标记为 FULLY_VALIDATED**
- 38% 的样本存在 FORMULA_DIFFERENCE
- 主要原因：production indicators 可能包含后验数据或不同价格语义
- 本阶段只记录，不修改生产逻辑

---

## 4. Historical Market Cap

### 4.1 当前数据
| 表 | 字段 | 状态 |
|---|---|---|
| `stocks` | `total_mcap` | 当前快照 |
| `stocks` | `total_shares_real` | 全为 NULL |
| `stocks` | `circulating_shares_real` | 全为 NULL |
| `financial_data` | 无股本字段 | - |
| `klines` | 无股本字段 | - |

### 4.2 无法重建的原因
1. 无历史股本数据（total_shares / float_shares）
2. 无历史市值序列
3. `stocks.total_mcap` 是当前快照
4. 无法确认：是否存在配股/增发/送转

### 4.3 结论
**状态**：`BLOCKED`
**原因**：`stocks.total_mcap 为当前快照，无历史股本/历史市值序列`

---

## 5. Historical Universe

### 5.1 基于 klines 的 Universe
```sql
SELECT code, MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as trade_days
FROM klines
WHERE date <= T
GROUP BY code
```

### 5.2 结果
- 2024-06-30：5,837 codes
- 包含活跃股票和已退市股票
- 无法区分：停牌 / ST / 暂停上市

### 5.3 限制
1. **Survivorship Bias**：有 K 线数据的股票在 T 日不一定可交易
2. **ST 状态**：无法识别
3. **上市/退市状态**：无官方确认（仅推断）
4. **停牌**：无停牌信息

### 5.4 结论
**状态**：`PARTIAL`
**可用**：最低限度 Universe（基于 klines 首末交易日）
**不可用**：真实交易状态、ST、停牌

---

## 6. Historical ST Status

### 6.1 当前数据
- `stocks.is_st`：当前快照，全为 0（当前无 ST 股票）
- 无历史 ST 变更记录

### 6.2 V1 是否使用 ST
沿 `scan_doubling_potential.py` 追踪：
```sql
WHERE (is_st IS NULL OR is_st = 0)
```
**结论**：V1 排除 ST/*ST 股票

### 6.3 结论
**状态**：`BLOCKED`
**Replay 影响**：`HIGH`（V1 直接过滤 ST 股票）
**修复方向**：接入历史 ST 变更记录

---

## 7. Historical Industry

### 7.1 当前数据
- `stocks.sw_industry_name`：当前快照
- `stocks.sector`：当前快照
- 无历史行业变更记录

### 7.2 V1 是否使用 Industry
沿 `scan_doubling_potential.py` 追踪：
- `sector` 用于显示（`candidates.append({"sector": sinfo.get("sector", "")})`）
- 未发现用于过滤
- `stock_opportunity_scan.py` 未使用 industry 过滤

### 7.3 结论
**状态**：`BLOCKED`
**Replay 影响**：`LOW`（V1 不用于过滤，仅显示）
**标记**：`HISTORICAL_CLASSIFICATION_RISK`

---

## 8. V1 Dependency Matrix

| Field | 实际是否参与 V1 | 所在模块 | Historical Need | 当前状态 | 是否真正 Block Replay |
|---|---|---|---|---|---|
| Market Cap | ✅ 是 | scan_doubling_potential.py | T 日可知市值 | BLOCKED | ✅ HIGH |
| Industry | ⚠️ 仅显示 | scan_doubling_potential.py | T 日行业分类 | BLOCKED | ⚠️ LOW |
| ST | ✅ 是 | scan_doubling_potential.py | T 日 ST 状态 | BLOCKED | ✅ HIGH |
| Signal Score | ❌ 否 | stock_opportunity_scan.py (推送) | T 日信号评分 | NON_DECISIONAL | ❌ NONE |
| MA20 | ✅ 是 | daily_data_refresh.py | T 日 MA20 | RECONSTRUCTABLE | ❌ NONE |
| ATR | ✅ 是 | scan_doubling_potential.py | T 日 ATR | RECONSTRUCTABLE | ❌ NONE |
| MACD | ⚠️ 部分 | daily_data_refresh.py (signal_d) | T 日 MACD | RECONSTRUCTABLE | ❌ NONE |
| Volume Ratio | ✅ 是 | scan_doubling_potential.py | T 日量比 | RECONSTRUCTABLE | ❌ NONE |

**真正 Replay Blocker**：
1. Market Cap（HIGH）
2. ST Status（HIGH）
3. Universe（PARTIAL，但可最低限度重建）

---

## 9. Historical State Reconstruction Matrix

| Capability | Source | PIT Safe | Reconstructable | Accuracy | Production Dependency | Replay Impact |
|---|---|---|---|---|---|---|
| OHLCV | klines | ✅ | ✅ | HIGH | HIGH | NONE |
| MA20 | klines | ✅ | ✅ | MEDIUM | HIGH | NONE |
| ATR(14) | klines | ✅ | ✅ | HIGH | MEDIUM | NONE |
| MACD | klines | ✅ | ✅ | HIGH | LOW | NONE |
| Volume Ratio | klines | ✅ | ✅ | HIGH | HIGH | NONE |
| Market Cap | ❌ | ❌ | ❌ | ❌ | HIGH | BLOCKER |
| Universe | klines | ✅ | ⚠️ PARTIAL | LOW | HIGH | HIGH |
| ST Status | ❌ | ❌ | ❌ | ❌ | HIGH | BLOCKER |
| Industry | ❌ | ❌ | ❌ | ❌ | LOW | LOW |
| Signal Score | ❌ | ❌ | ❌ | ❌ | NONE | NONE |
| Portfolio | ❌ | ❌ | ❌ | ❌ | HIGH | BLOCKER |

---

## 10. Historical Market State Adapter

### 10.1 文件
`historical_market_state.py`

### 10.2 公开 API
```python
get_historical_market_state(symbol, as_of_date) -> dict
get_universe_as_of(as_of_date) -> dict
get_market_cap(as_of_date, symbol) -> dict
get_st_status(as_of_date, symbol) -> dict
get_industry(as_of_date, symbol) -> dict
```

### 10.3 输出示例
```json
{
  "symbol": "000001",
  "as_of_date": "2024-06-30",
  "source": "HISTORICAL_REPLAY",
  "in_universe": true,
  "market_cap": {
    "market_cap": "UNKNOWN",
    "status": "BLOCKED",
    "reason": "stocks.total_mcap 为当前快照，无历史股本/历史市值序列"
  },
  "st_status": {
    "st_status": "UNKNOWN",
    "status": "BLOCKED",
    "reason": "stocks.is_st 为当前快照，无历史 ST 变更记录"
  },
  "industry": {
    "industry": "UNKNOWN",
    "status": "BLOCKED",
    "reason": "stocks.sw_industry_name/sector 为当前快照，无历史行业序列"
  },
  "limitation_codes": [
    "MARKET_CAP_BLOCKED",
    "ST_STATUS_BLOCKED",
    "INDUSTRY_BLOCKED",
    "PORTFOLIO_NONE"
  ]
}
```

---

## 11. Portfolio Limitation

**PORTFOLIO_REPLAY_MODE = NONE**

无历史账户/持仓/现金快照，无法模拟真实组合效果。

---

## 12. Replay Blockers（最小化后）

| Blocker | 影响 | 是否可绕过 | 说明 |
|---|---|---|---|
| Market Cap | HIGH | ❌ 否 | V1 直接过滤市值 5-90 亿 |
| ST Status | HIGH | ❌ 否 | V1 直接排除 ST 股票 |
| Portfolio | HIGH | ❌ 否 | 无历史账户状态 |
| Industry | LOW | ✅ 可降级 | V1 仅显示，不过滤 |
| Signal Score | NONE | ✅ 已标记 | NON_DECISIONAL_FIELD |

**核心结论**：
- Replay A（Signal Replay）：仍 BLOCKED（Market Cap + ST 是 V1 硬过滤条件）
- Replay B（Decision Replay）：仍 BLOCKED（同上 + Portfolio）
- Replay C（Full Lifecycle Replay）：仍 BLOCKED（同上）

---

## 13. Recommendation

### 13.1 下一阶段先做什么
1. **解决 Market Cap 历史重建**
   - 接入历史股本数据（东方财富 Choice / 巨潮资讯）
   - 或：从 `klines.close × shares_outstanding` 重建（需 shares 历史）
   
2. **解决 ST Status 历史重建**
   - 接入历史 ST 变更公告
   - 或：从股票名称历史推断（含"ST"/"*ST"/"退"）

3. **接受 Portfolio = NONE**
   - 明确：未来 Replay 只能是 `DECISION_WITHOUT_PORTFOLIO`
   - 不能伪装为真实 Production-equivalent Decision

### 13.2 不要做什么
- 不要放宽 V1 的 Market Cap / ST 过滤条件
- 不要用当前 `stocks.total_mcap` 回填历史
- 不要用当前 `stocks.is_st` 回填历史

---

## 14. Known Limitations

1. **MA20 mismatch 38%**：production indicators 可能包含后验数据或不同价格语义，未修复
2. **ATR 生产来源不统一**：indicators.atr_14 非权威，扫描脚本自己计算
3. **Signal Score 非零值**：703 条记录有非零值，但都不参与 V1 Decision
4. **Market Cap 无法重建**：无历史股本数据
5. **ST Status 无法重建**：无历史 ST 变更记录
6. **Industry 无法重建**：无历史行业变更记录
7. **Portfolio = NONE**：无历史账户快照
8. **Universe = PARTIAL**：基于 klines 首末交易日，无法区分停牌/ST/退市

---

## 15. Final Answers

### 15.1 signal_score 是否真正参与 V1？
**否。**
- 不参与 DecisionEngine / Entry / Portfolio / Exit
- 仅用于 `stock_opportunity_scan.py` 候选推送筛选
- **标记**：`NON_DECISIONAL_FIELD`

### 15.2 ATR 的真实 Production 来源是什么？
**无法确认权威来源。**
- `daily_data_refresh.py` 主流程写入 NULL
- `indicators.atr_14` 有 782 个非 NULL（主要集中在 2026-08）
- `scan_doubling_potential.py` 自己计算 ATR（SMA TR, period=14）
- `v1_stress_test.py` / `param_verify_full.py` 使用相同公式
- **标记**：`PRODUCTION_FEATURE_SEMANTICS_UNKNOWN`

### 15.3 MA20 的 mismatch 为什么达到当前水平？
**38% FORMULA_DIFFERENCE。**
- 原因：production indicators 可能包含后验数据或不同价格语义
- 案例：000502 2022-06-24，prod=1.5075 vs hist=0.7289 (51.65%)
- 根因：该股票在 2022-06 有大额交易/退市事件，价格异常
- 其他可能：后复权 vs 不复权、数据截断、warm-up

### 15.4 Historical Market Cap 能否重建？
**否。**
- `stocks.total_shares_real` / `circulating_shares_real` 全为 NULL
- `financial_data` 无股本字段
- **标记**：`BLOCKED`

### 15.5 Historical Universe 能否重建？
**最低限度可以。**
- 基于 klines 首末交易日
- 但无法区分：停牌 / ST / 退市 / 暂停上市
- **标记**：`PARTIAL`

### 15.6 Historical ST 能否重建？
**否。**
- `stocks.is_st` 为当前快照
- 无历史 ST 变更记录
- **标记**：`BLOCKED`
- **Replay 影响**：HIGH（V1 直接过滤 ST）

### 15.7 Historical Industry 能否重建？
**否。**
- `stocks.sw_industry_name` / `sector` 为当前快照
- 无历史行业变更记录
- **标记**：`BLOCKED`
- **Replay 影响**：LOW（V1 仅显示，不过滤）

### 15.8 哪些字段是真正的 V1 Replay Blocker？
1. **Market Cap**（HIGH）- V1 硬过滤 5-90 亿
2. **ST Status**（HIGH）- V1 硬排除 ST
3. **Portfolio**（HIGH）- 无历史账户状态

### 15.9 Portfolio 是否是唯一剩余核心 Blocker？
**否。**
- Market Cap 和 ST Status 也是核心 Blocker
- 三者共同阻塞 Replay A/B/C

### 15.10 Replay A/B/C 是否发生变化？
**否。**
- 当前仍全部 BLOCKED
- 即使 OHLCV 指标可重建，Market Cap + ST + Portfolio 仍阻塞

### 15.11 下一阶段应该先做什么？
**解决 Market Cap 历史重建（最高优先级）。**
- 接入历史股本数据
- 然后解决 ST Status
- Portfolio 保持 NONE（接受限制）
