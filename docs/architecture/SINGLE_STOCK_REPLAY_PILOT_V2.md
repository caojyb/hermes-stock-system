# SINGLE_STOCK_REPLAY_PILOT_V2.md（Phase 7.3-L）

## 1. Sample Design

### Data Source Isolation
- **Unit Tests**: 使用冻结 CNINFO fixtures（`fixtures/cninfo_*.parquet`），不访问网络
- **Integration Tests**: 标记 `@pytest.mark.slow`，可访问 live CNINFO API
- **Pilot V2**: 使用 `universe_clean_with_dates.csv` 作为采样源，不依赖当前 `stocks.is_st` 或 `market_cap`

### Fixture Coverage
| Symbol | Fixture Rows | Date Range | Quality Mix |
|--------|-------------|------------|-------------|
| 000001 | 4 | 2000-06-30 ~ 2022-06-30 | APPROXIMATE + KNOWN |
| 002594 | 3 | 2011-06-30 ~ 2024-05-10 | KNOWN + APPROXIMATE |
| 600519 | 3 | 2001-08-27 ~ 2024-12-31 | KNOWN + APPROXIMATE |

### Sample Construction
- Source: `universe_clean_with_dates.csv`（4,412 stocks, excluding delisted）
- Filter: `first_kline_date <= target_date`
- Stratification: SMALL (<5B) / MID (5-90B) / LARGE (>90B)
- Target dates: 2005, 2007, 2008, 2012, 2015, 2018, 2020, 2021, 2022, 2024

## 2. Sample Bias

### Current Limitation
**Pilot V2 样本仍存在系统性偏差：**

| Size Group | Target | Actual | Issue |
|------------|--------|--------|-------|
| SMALL (<5B) | 20 | 35 | 包含退市股（天龙退、退市太和等） |
| MID (5-90B) | 20 | 58 | 部分当前小盘股历史为大盘 |
| LARGE (>90B) | 20 | 55 | 分布合理 |

### Root Cause
- `universe_clean.csv` 过滤了 `name LIKE '%退%'`，但 `pilot_v2_sample.py` 仍使用旧版 `get_current_universe()` 未过滤
- SMALL cap 组在当前 Universe 中仅 1 只（元道通信 4.55B），其余均为退市股
- 历史 K 线可用性受制于 DB 覆盖（2005 年仅 1,455 stocks）

### Quantified Bias
- **Delisted stocks in sample**: 36/148 = 24.3%
- **Current SMALL (<5B) non-delisted**: 仅 元道通信 1 只
- **Historical SMALL coverage**: 2005-06-15 有 K 线的最小市值 = 14.5B（江西长运）

**结论：Pilot V2 样本仍偏重大盘股，不能用于评价 V1 参数行为。**

## 3. Data Quality

### Kline Availability by Year
| Year | Stocks with Klines | Sample Cases |
|------|-------------------|--------------|
| 2005 | 1,455 | 16 |
| 2007 | N/A | 18 |
| 2008 | N/A | 19 |
| 2012 | N/A | 7 |
| 2015 | 2,921 | 11 |
| 2018 | N/A | 23 |
| 2020 | N/A | 20 |
| 2021 | N/A | 17 |
| 2022 | 5,409 | 9 |
| 2024 | N/A | 8 |

### Market Cap Quality
- **STRICT Mode**: 仅接受 KNOWN_EFFECTIVE_DATE
- **RESEARCH Mode**: 接受 KNOWN + APPROXIMATE
- **UNKNOWN**: 无历史股本数据

## 4. PIT Rules

- 所有历史查询严格 as-of T
- 仅使用 `trade_date <= T` 的 K 线
- Decision 为 T 日收盘后，Execution 为 T+1 开盘
- 禁止使用当前 Production Snapshot（stocks.is_st, total_mcap）

## 5. Feature Semantics

| Feature | Production Formula | Historical Formula | Status |
|---------|-------------------|-------------------|--------|
| Volume Ratio | vol_5 / vol_20 | vol_5 / vol_20 | ✅ MATCH |
| MA20 | SMA(close, 20) | SMA(close, 20) | ✅ MATCH |
| ATR | SMA(TR, 14) | SMA(TR, 14) | ✅ MATCH |
| Price Position | 500 日分位 | 500 日分位 | ✅ FIXED |
| Turnover 1D | amount | amount | ✅ MATCH |
| Turnover 20D | SMA(amount, 20) | SMA(amount, 20) | ✅ MATCH |

## 6. Market Cap

### STRICT Mode
- Only `KNOWN_EFFECTIVE_DATE` → `PIT_SAFE`
- `APPROXIMATE_EFFECTIVE_DATE` → `UNKNOWN`
- Coverage: 16.3% of historical events

### RESEARCH Mode
- `KNOWN_EFFECTIVE_DATE` → `PIT_SAFE`
- `APPROXIMATE_EFFECTIVE_DATE` → `APPROXIMATE`
- Coverage: 76% of historical events

## 7. ST

**Historical ST = BLOCKED**
- 无任何历史 ST 状态时间序列数据源
- 所有 case 标记 `ST_FILTER = UNKNOWN`
- 不伪造、不推断、不用当前 `is_st` 回填

## 8. Price Position

- Production: 500 日窗口（`scan_doubling_potential.py:99`）
- Historical: 500 日窗口（已修正）
- Phase 7.3-J 的 72% PRICE_POS_ABOVE 主要来自 250 日窗口错误

## 9. Volume Ratio

- Production: `kl_raw[-5:].volume.sum() / kl_raw[-25:-5].volume.sum()`
- Historical: `volumes[-5:].sum() / volumes[-25:-5].sum()`
- 公式完全一致
- Phase 7.3-J 的 67/68 VOL_RATIO_BELOW 来自 Pilot Sample Bias（大盘股+成熟期）

## 10. Candidate Filters

| Filter | Production | Historical | Status |
|--------|-----------|------------|--------|
| Market Cap 5-90B | `total_mcap` | `share_count * close` | ⚠️ SEMANTIC_CONFLICT |
| ST | `is_st IS NULL OR is_st = 0` | UNKNOWN | 🔴 BLOCKED |
| Volume Ratio >= 2.7 | 5/20 volume sum | 5/20 volume sum | ✅ MATCH |
| Price Position < X | 500 日分位 | 500 日分位 | ✅ FIXED |
| ATR >= 3% | SMA(TR, 14) | SMA(TR, 14) | ✅ MATCH |
| Turnover 1D >= 8000万 | amount | amount | ✅ MATCH |
| Turnover 20D >= 4000万 | SMA(amount, 20) | SMA(amount, 20) | ✅ MATCH |

## 11. Production Differential

### Historical vs Production Comparison
- **Volume Ratio**: MAE=0.0000, Threshold Disagreement=0%
- **MA20**: MAE=0.0000（同数据源）
- **ATR**: 差异来自 TIME_SEMANTIC_DIFFERENCE（Production 使用截至 TODAY）
- **Price Position**: 500 日窗口修正确实消除了主要差异

## 12. Strict vs Research

| Mode | Total Cases | PASS | FAIL | UNKNOWN |
|------|-------------|------|------|---------|
| STRICT | 115 | 0 | 0 | 115 |
| RESEARCH | 115 | 0 | 0 | 115 |

**所有 case 均为 UNKNOWN，原因：**
1. ST UNKNOWN（100% cases）
2. MARKET_CAP UNKNOWN（大多数 cases，因 fixtures 仅覆盖 3 只股票）

## 13. Replay Confidence

| Confidence | Count | Reason |
|------------|-------|--------|
| BLOCKED | 115 | ST UNKNOWN 或 MARKET_CAP UNKNOWN |
| HIGH | 0 | 无 |
| MEDIUM | 0 | 无 |
| LOW | 0 | 无 |

## 14. Results

### Final Candidate Distribution
| Final Candidate | STRICT | RESEARCH |
|----------------|--------|----------|
| UNKNOWN | 115 | 115 |

### Filter Distribution
| Filter | STRICT UNKNOWN | RESEARCH UNKNOWN |
|--------|----------------|------------------|
| Market Cap | 115 | 115 |
| ST | 115 | 115 |
| Volume Ratio | 110 FAIL, 5 PASS | 110 FAIL, 5 PASS |
| Price Position | 45 FAIL, 43 PASS, 27 UNKNOWN | 45 FAIL, 43 PASS, 27 UNKNOWN |
| ATR | 97 PASS, 18 FAIL | 97 PASS, 18 FAIL |

### Key Findings
1. **ST UNKNOWN 仍是 100% 阻塞** — 所有 case 因 ST 无法确定候选状态
2. **Market Cap UNKNOWN 主要因 fixtures 不足** — 仅 3 只股票有 fixture，其余 48 只无数据
3. **Volume Ratio 失败率 = 95.7%** — 110/115，但这是样本偏差（大盘股+成熟期），非公式错误
4. **Price Position 失败率 = 49.6%** — 45/91（不含 UNKNOWN），需更多中小盘样本验证
5. **ATR 通过率 = 84.3%** — 97/115

## 15. Known Limitations

1. **Fixtures 覆盖不足** — 仅 3 只股票，导致 115/148 cases 因 MARKET_CAP UNKNOWN 被阻塞
2. **样本偏差** — 33/148 cases 为退市股，SMALL cap 组代表性不足
3. **历史 K 线覆盖** — 2005 年前仅有 1,455 stocks，限制早期样本构建
4. **ST 数据完全缺失** — 无法建立 Historical ST Event 模型
5. **Market Cap 严格覆盖率低** — STRICT 仅 16.3%，需更多 KNOWN_EFFECTIVE_DATE 事件

## 16. Recommendation

### Immediate
1. **扩展 CNINFO Fixtures** — 至少覆盖 Pilot V2 中的 51 只股票，优先选择有 KNOWN 事件的股票（配股、增发、IPO）
2. **过滤退市股** — 在 `pilot_v2_sample.py` 中使用 `universe_clean_with_dates.csv`，排除 `name.contains('退')`

### Short-term
3. **扩大 SMALL cap 样本** — 当前 Universe 中 SMALL(<5B) 仅 1 只非退市股，需接受当前市值 <10B 的股票作为历史小盘代表
4. **建立 Historical ST 代理** — 虽然完全历史 ST 数据不可得，但可探索 `stock_info_change_name` 的ST标记作为最低置信度代理

### Long-term
5. **购买专业历史数据** — ST 状态时间序列是最大阻塞，Market Cap 可通过更多 fixtures 改善
6. **Replay B 恢复路径** — 在扩展 fixtures + ST 代理后，RESEARCH 模式下可达到 PARTIAL 而非全 UNKNOWN
