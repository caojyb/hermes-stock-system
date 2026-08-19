# HISTORICAL_SHARE_LAYER.md（Phase 7.3-F）

## 1. Source

**akshare.stock_share_change_cninfo**（巨潮资讯 p_stock2215）
- 免费、开源
- 覆盖 2000-2024
- 全市场 A 股

## 2. Raw Schema

| 原始字段 | 类型 | 说明 |
|---|---|---|
| 证券代码 | str | 股票代码 |
| 证券简称 | str | 股票名称 |
| 变动日期 | date | 股本变动日期 |
| 公告日期 | date | 公告发布日期 |
| 变动原因 | str | 变动原因（定期报告/配股上市/增发新股上市等） |
| 总股本 | float | 总股本（万股） |
| ... | ... | 其他股份类型明细 |

## 3. Share Event Model

### HistoricalShareEvent（独立规范）
- `symbol`：股票代码
- `share_count`：股本数量（股，已从万股转换）
- `share_type`：`TOTAL_SHARES`
- `effective_date`：有效日期
- `announcement_date`：公告日期
- `date_quality`：`KNOWN_EFFECTIVE_DATE` / `APPROXIMATE_EFFECTIVE_DATE` / `UNKNOWN_EFFECTIVE_DATE`
- `confidence`：置信度（0.0-1.0）
- `limitation_codes`：限制代码
- `source`：数据源
- `feature_source`：`HISTORICAL_REPLAY`

## 4. Effective Date Quality

### 4.1 KNOWN_EFFECTIVE_DATE（16.3%）
- 配股上市
- 增发新股上市
- 限售股份上市
- A股上市
- 股份回购
- 注销
- 拆股/合并

### 4.2 APPROXIMATE_EFFECTIVE_DATE（59.0%）
- 定期报告（年报/中报/季报）
- 变动日期 = 报告期末
- 实际生效日可能早于报告期末

### 4.3 UNKNOWN_EFFECTIVE_DATE（24.7%）
- 无变动日期
- 其他未明确日期的事件

## 5. Timeline

每个股票建立按 `effective_date` 排序的时间线。
- DATED 事件按日期排序
- UNDATED 事件放到末尾

## 6. PIT Query

### 6.1 get_as_of（严格 PIT）
只返回：
- `effective_date <= as_of_date`
- `date_quality == KNOWN_EFFECTIVE_DATE`

如果无 KNOWN 事件，返回 `None`。

### 6.2 get_any_as_of（宽松 PIT）
返回：
- `effective_date <= as_of_date`
- 任意 `date_quality`

用于 coverage 分析，不用于严格 Replay。

## 7. Market Cap

公式：
```
historical_market_cap(T) = historical_total_shares(T) × close(T)
```

- `share_count(T)`：从 Historical Share Layer 获取
- `close(T)`：从 klines 获取（raw close）
- 价格日期 `price_date <= T`

## 8. Unit Semantics

- `share_count`：单位：股（万股 × 10,000）
- `price`：单位：元
- `market_cap`：单位：元

示例：
```
100,000 万股 × 10 元 = 1,000,000,000,000 元
```

## 9. Coverage

### 9.1 Date Coverage
- 最早：2000-02-16（000002 万科）
- 最晚：2024-12-31
- **2025-2026 缺口**：DATA_GAP

### 9.2 Symbol Coverage
- 抽样 10 只股票
- 全部有历史股本数据
- 估计全市场覆盖率：高

### 9.3 Quality Coverage（10 股抽样）
- KNOWN_EFFECTIVE_DATE：110 条（16.3%）
- APPROXIMATE_EFFECTIVE_DATE：399 条（59.0%）
- UNKNOWN_EFFECTIVE_DATE：167 条（24.7%）

### 9.4 PIT_SAFE Coverage
- 严格 PIT（KNOWN）：约 16%
- 包含 APPROXIMATE：约 75%

## 10. Validation

### 10.1 已知案例
- **000001 平安银行**：75 条记录，2000-2024
- **002594 比亚迪**：42 条记录，2011-2024
- **600519 贵州茅台**：63 条记录，2000-2024

### 10.2 单位验证
- 总股本单位：万股 → 股（×10,000）
- 平安银行：155,184.71 万股 → 1,551,847,190 股 ✓

### 10.3 PIT Cutoff
- `effective_date <= as_of_date` 已验证
- 无未来数据泄漏

## 11. 2025+ Gap

- 数据源截止 2024-12-31
- **2025-01-01 至 2026-08-18 缺口**：DATA_GAP
- 标记为 `BLOCKED / DATA_GAP`

## 12. Quality Status

```python
MarketCapQuality = PIT_SAFE | APPROXIMATE | UNKNOWN | BLOCKED
```

- `PIT_SAFE`：KNOWN_EFFECTIVE_DATE + 有价格数据
- `APPROXIMATE`：APPROXIMATE_EFFECTIVE_DATE + 有价格数据
- `UNKNOWN`：无股本数据或无价格数据
- `BLOCKED`：无数据且超出覆盖范围

## 13. Adapter

### 13.1 HistoricalShareLayer
```python
layer = HistoricalShareLayer()
layer.load_symbol('000001')
layer.load_symbols(['000001', '002594', ...])

# PIT 查询
event = layer.get_as_of('000001', date(2022, 6, 24))

# 时间线
timeline = layer.get_timeline('000001')
```

### 13.2 HistoricalMarketCap
```python
mcap = HistoricalMarketCap(layer)
result = mcap.get_market_cap('000001', date(2022, 6, 24))

# 5-90 亿过滤
filter_result = mcap.check_5_90b_filter('000001', date(2022, 6, 24))
# 返回：PASS / FAIL / UNKNOWN
```

## 14. Replay Impact

| 场景 | 状态 | 说明 |
|---|---|---|
| 严格 PIT Replay | PARTIAL | 仅 KNOWN_EFFECTIVE_DATE 可用（16%） |
| 宽松 Replay | RECONSTRUCTABLE | 包含 APPROXIMATE（75%） |
| 2025-2026 | BLOCKED | 数据缺口 |
| 全市场 Replay | PARTIAL | 需批量下载全市场股本数据 |

## 15. Known Limitations

1. **有效日期不确定性**：定期报告的变动日期 = 报告期末，非实际生效日
2. **2025-2026 缺口**：数据源截止 2024-12-31
3. **ST 状态缺失**：无历史 ST 数据
4. **Portfolio 缺失**：无历史账户数据
5. **全市场未下载**：当前仅抽样 10 只股票
6. **去重键稳定性**：依赖 source_record_id 格式

## 16. Recommendation

### 16.1 下一阶段
**全市场股本数据批量下载 + 本地缓存。**
- 使用 akshare.stock_share_change_cninfo 下载全市场
- 缓存到独立 historical_replay/ 目录
- 建立完整 PIT Share Timeline

### 16.2 Replay 策略
- **严格 Replay**：仅使用 KNOWN_EFFECTIVE_DATE（16%）
- **宽松 Replay**：使用 APPROXIMATE + KNOWN（75%），但标记 APPROXIMATE
- **2025-2026**：标记 BLOCKED，不参与 Replay

### 16.3 不要做什么
- 不要用当前股本回填历史
- 不要放宽 V1 的 5-90 亿过滤
- 不要接受 APPROXIMATE 为 PIT_SAFE
- 不要修改 Production DB
