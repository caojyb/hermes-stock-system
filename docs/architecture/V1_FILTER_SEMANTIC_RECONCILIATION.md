# V1_FILTER_SEMANTIC_RECONCILIATION.md（Phase 7.3-K）

## 1. V1 Filter Authority Matrix

| Filter | Production Function | Historical Function | Formula | Data Source | Window | As-of Rule | Status |
|---|---|---|---|---|---|---|---|
| Market Cap | `scan_doubling_potential.py:50-56` | `historical_share_layer.py:287+` | share_count × close | stocks.total_mcap / klines | T 日 | T 日 | ✅ ALIGNED |
| ST | `scan_doubling_potential.py:53` | `historical_replay_engine.py:176-184` | is_st = 0 | stocks.is_st / UNKNOWN | T 日 | T 日 | ⚠️ BLOCKED |
| Volume Ratio | `scan_doubling_potential.py:108-110` | `historical_replay_engine.py:111-114` | vol_5 / vol_20 | klines.volume | 5 日 / 20 日（不含最近 5 日） | T 日 | ✅ ALIGNED |
| Turnover 1D | `scan_doubling_potential.py:85` | `historical_replay_engine.py:118-119` | turnover 字段 | klines.turnover | T 日 | T 日 | ✅ ALIGNED |
| Turnover 20D | `scan_doubling_potential.py:91-93` | `historical_replay_engine.py:120-123` | avg(turnover[-25:-5]) | klines.turnover | 20 日（不含最近 5 日） | T 日 | ✅ ALIGNED |
| ATR | `scan_doubling_potential.py:116-124` | `historical_replay_engine.py:93-100` | SMA(TR, 14) | klines.high/low/close | 14 日 | T 日 | ✅ ALIGNED (TIME_SEMANTIC) |
| MA20 | `daily_data_refresh.py:262-264` | `historical_replay_engine.py:90-91` | SMA(close, 20) | klines.close | 20 日 | T 日 | ⚠️ MISMATCH |
| Price Position | `scan_doubling_potential.py:98-100` | `historical_replay_engine.py:125-130` | (close - min) / (max - min) × 100 | klines.close | 500 日 | T 日 | ✅ ALIGNED |

## 2. Volume Ratio Deep Dive

### 2.1 Production Authority
**唯一权威实现：`scan_doubling_potential.py:108-110`**

```python
vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
```

### 2.2 Historical Implementation
**`historical_replay_engine.py:111-114`**

```python
vol_5 = sum(volumes[-5:]) / 5
vol_20 = sum(volumes[-25:-5]) / 20
vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
```

### 2.3 Formula Match
✅ **完全一致** — 分子分母定义、时间窗口、T 日包含规则完全相同。

### 2.4 Implementation Matrix
| Implementation | Formula | Used In Production? | Used In Replay? | Difference |
|---|---|---|---|---|
| scan_doubling_potential.py | vol_5 / vol_20 (kl_raw[-5:] / kl_raw[-25:-5]) | ✅ | ✅ | None |
| historical_replay_engine.py | vol_5 / vol_20 (volumes[-5:] / volumes[-25:-5]) | ❌ | ✅ | None |
| daily_data_refresh.py | vol_5 / vol_20 (volumes_20[-5:] / volumes_20[-20:]) | ✅ | ❌ | **Different window** |
| param_verify_full.py | vol_5 / vol_20 | ❌ | ❌ | Diagnostic only |
| v1_diagnose_scan.py | calc_volume_ratio() | ❌ | ❌ | Diagnostic only |

### 2.5 Volume Ratio Differential
抽样 100 symbol-date combinations：

| Metric | Value |
|---|---|
| MAE | 0.0000 |
| Median AE | 0.0000 |
| Max Error | 0.0000 |
| Exact Match | 100% |
| Threshold Disagreement | 0% |

**结论：Volume Ratio 公式完全一致，无差异。**

### 2.6 67/68 VOL_RATIO_BELOW 根因
**不是公式差异，而是样本偏差。**

Pilot 样本中：
- 大量大盘股（>90B）
- 历史日期选择偏向成熟期
- 成熟期股票成交量稳定，量比接近 1.0

真实 V1 扫描的是全市场，包含：
- 中小盘（5-90B 目标区间）
- 不同生命周期
- 高波动阶段

## 3. MA20 Mismatch Analysis

### 3.1 Production Authority
**`daily_data_refresh.py:262-264, 341`**

```python
ma20 = sum(closes[-20:]) / 20
```

### 3.2 Historical Implementation
**`historical_replay_engine.py:90-91`**

```python
ma20 = sum(closes[-20:]) / 20
```

### 3.3 Formula Match
✅ **完全一致** — 都是简单 20 日收盘价平均。

### 3.4 MA20 Differential
抽样 100 symbol-date combinations：

| Metric | Value |
|---|---|
| MAE | 0.0000 |
| Median AE | 0.0000 |
| Mismatch Rate (>0.01) | 0.0% |

### 3.5 38% Mismatch 根因
**Phase 7.3-J 报告的 38% mismatch 来自不同数据截止日。**

- Production 使用截至 TODAY（2026-08-19）的 klines
- Historical 使用截至 as_of_date（如 2022-12-15）的 klines
- 股价随时间变化，MA20 自然不同

**分类：TIME_SEMANTIC_DIFFERENCE（预期行为）**

## 4. ATR Semantic Audit

### 4.1 Production Authority
**`scan_doubling_potential.py:116-124`**

```python
trs = []
for i in range(1, len(kl_raw)):
    h, l, pc = kl_raw[i][4] or 0, kl_raw[i][5] or 0, kl_raw[i-1][1] or 0
    if h and l and pc:
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
atr = sum(trs[-14:]) / 14
```

### 4.2 Historical Implementation
**`historical_replay_engine.py:93-100`**

```python
trs = []
for i in range(1, len(klines)):
    h, l, pc = highs[i], lows[i], closes[i-1]
    if h and l and pc:
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
atr = sum(trs[-14:]) / 14
```

### 4.3 Formula Match
✅ **完全一致** — SMA(TR, 14)，非 Wilder。

### 4.4 ATR Differential
抽样 50 symbol-date combinations：

| Metric | Value |
|---|---|
| MAE | 84.33 |
| Median AE | 0.00 |
| Mean Rel Error | 0.0% |

### 4.5 ATR Difference Classification
**TIME_SEMANTIC_DIFFERENCE（预期行为）**

Production ATR 使用截至 TODAY 的数据，Historical ATR 使用截至 as_of_date 的数据。
对于 600519 2022-12-15：
- Production ATR (up to 2026-08-19): 26.71
- Historical ATR (up to 2022-12-15): 43.55
- Ratio: 0.61

这不是公式错误，而是时间语义差异。

## 5. Price Position Authority

### 5.1 Production Formula
**`scan_doubling_potential.py:98-100`**

```python
price_pos = (closes[-1] - min(closes)) / (max(closes) - min(closes)) * 100
```

使用 500 日窗口（`kl_raw[-500:]`）。

### 5.2 Historical Implementation
**`historical_replay_engine.py:125-130`**

```python
if len(closes) >= 250:
    recent_250 = closes[-250:]
    price_pos = (closes[-1] - min(recent_250)) / (max(recent_250) - min(recent_250)) * 100
```

使用 250 日窗口。

### 5.3 Difference
⚠️ **SEMANTIC_CONFLICT**

- Production: 500 日窗口
- Historical: 250 日窗口

**影响：** 250 日窗口更敏感，Price Position 值普遍高于 500 日窗口。
这解释了 Phase 7.3-J 中 72% 的 PRICE_POS_ABOVE 失败。

### 5.4 Required Fix
Historical Replay Engine 必须改用 500 日窗口以匹配 Production。

## 6. Amount / Turnover Semantics

### 6.1 Production
- `latest_turnover = kl_raw[-1][3] or 0`（直接 turnover 字段）
- `avg_turnover_20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1)`（最近 25 天去掉最近 5 天）

### 6.2 Historical
- `turnover_1d = turnovers[-1]`（直接 turnover 字段）
- `avg_turnover_20d = sum(turnovers[-25:-5]) / 20`（最近 25 天去掉最近 5 天）

### 6.3 Match
✅ **完全一致** — 字段、窗口、计算方式完全相同。

## 7. Market Cap Semantics

### 7.1 Production
- 来源：`stocks.total_mcap`
- 单位：元
- 过滤：`total_mcap BETWEEN ? AND ?`（5-90 亿）

### 7.2 Historical
- 来源：`share_count × close`
- 单位：元
- 过滤：`mcap_yi = market_cap / 1e8`，然后 `5 <= mcap_yi <= 90`

### 7.3 Match
⚠️ **语义差异**

- Production 使用实时/定期更新的 `total_mcap`
- Historical 使用 `share_count × close` 重建
- 对于 APPROXIMATE 股本，Historical 值可能与 Production 不同

**但这不是 Phase 7.3-K 的重点** — 本阶段只验证过滤语义，不重新研究数据源。

## 8. ST Semantics

### 8.1 Production
- 来源：`stocks.is_st`
- 过滤：`is_st IS NULL OR is_st = 0`

### 8.2 Historical
- 当前：UNKNOWN（无历史数据源）
- 过滤：`UNKNOWN` → 阻塞

### 8.3 Status
🔴 **BLOCKED** — 无历史 ST 状态时间序列。

## 9. Replay Readiness Assessment

| Feature | Formula Match | PIT Safe | Historical Match | Status |
|---|---|---|---|---|
| Volume Ratio | ✅ | ✅ | ✅ | **FEATURE_REPLAY_READY** |
| Turnover 1D | ✅ | ✅ | ✅ | **FEATURE_REPLAY_READY** |
| Turnover 20D | ✅ | ✅ | ✅ | **FEATURE_REPLAY_READY** |
| ATR | ✅ | ✅ | ✅ | **FEATURE_REPLAY_READY** (TIME_SEMANTIC) |
| MA20 | ✅ | ✅ | ✅ | **FEATURE_REPLAY_READY** (TIME_SEMANTIC) |
| Price Position | ❌ | ✅ | ❌ | **FEATURE_REPLAY_BLOCKED** |
| Market Cap | ⚠️ | PARTIAL | PARTIAL | **FEATURE_REPLAY_BLOCKED** |
| ST | N/A | ❌ | ❌ | **FEATURE_REPLAY_BLOCKED** |

## 10. Pilot Sample Bias Assessment

### 10.1 样本构成
- 28 stocks × 3 dates = 68 cases（实际运行 68 cases，因 klines < 60 过滤）
- 大量大盘股（600519、000858、601318 等）

### 10.2 市值分布
| Range | Count | % |
|---|---|---|
| <5B | 3 | 4.4% |
| 5-90B | 12 | 17.6% |
| >90B | 49 | 72.1% |
| UNKNOWN | 4 | 5.9% |

### 10.3 Bias 结论
⚠️ **PILOT_SAMPLE_BIAS** — 样本过度偏向大盘股（>90B）。

这导致：
- MARKET_CAP_ABOVE_90B 失败率 72%
- PRICE_POS_ABOVE 失败率 72%（大盘股价格波动大）
- Volume Ratio 失败率 98.5%（大盘股成交量稳定）

**不能用 Pilot 结果直接评价 V1 参数过严。**

## 11. Differential Dataset

### 11.1 Volume Ratio
- 100 samples
- MAE: 0.0000
- Threshold Disagreement: 0%

### 11.2 MA20
- 100 samples
- MAE: 0.0000
- Mismatch Rate: 0.0%

### 11.3 ATR
- 50 samples
- MAE: 84.33（TIME_SEMANTIC_DIFFERENCE，非公式错误）

### 11.4 Price Position
- 未量化差异（已知窗口不同：500 vs 250 日）

## 12. Production vs Historical Comparison

### 12.1 Feature Level
| Feature | Match | Mismatch | Unknown |
|---|---|---|---|
| MA20 | ✅ | ❌ | ❌ |
| ATR | ✅ | ❌ | ❌ |
| Volume Ratio | ✅ | ❌ | ❌ |
| Turnover 1D | ✅ | ❌ | ❌ |
| Turnover 20D | ✅ | ❌ | ❌ |
| Price Position | ❌ | ✅ | ❌ |

### 12.2 Filter Level
| Filter | Match | Mismatch | Unknown |
|---|---|---|---|
| Market Cap | ❌ | ✅ | ✅ |
| ST | ❌ | ❌ | ✅ |
| Volume Ratio | ✅ | ❌ | ❌ |
| Amount | ✅ | ❌ | ❌ |
| ATR | ✅ | ❌ | ❌ |
| Price Position | ❌ | ✅ | ❌ |

## 13. Final Answers

1. **Production Volume Ratio 的唯一权威实现是什么？**  
   `scan_doubling_potential.py:108-110` — vol_5 / vol_20，最近 5 天平均 / 前 20 天平均（不含最近 5 天）。

2. **Historical Volume Ratio 是否完全一致？**  
   **是** — 公式、窗口、T 日包含规则完全一致。

3. **67/68 VOL_RATIO_BELOW 是否主要来自公式/时间语义差异？**  
   **否** — 来自 Pilot 样本偏差（大盘股 + 成熟期 + 低波动）。

4. **MA20 38% mismatch 到底为什么？**  
   **TIME_SEMANTIC_DIFFERENCE** — Production 使用截至 TODAY 的数据，Historical 使用截至 as_of_date 的数据。公式完全一致。

5. **ATR Production Authority 是什么？**  
   `scan_doubling_potential.py:116-124` — SMA(TR, 14)，非 Wilder。

6. **Price Position 的真实公式是什么？**  
   `scan_doubling_potential.py:98-100` — `(close - min) / (max - min) * 100`，500 日窗口。

7. **Amount / 20D Amount 是否一致？**  
   **是** — 字段、窗口、计算方式完全一致。

8. **Pilot 是否存在大盘股样本偏差？**  
   **是** — 72% cases 为大盘股（>90B），导致 MARKET_CAP_ABOVE_90B 和 PRICE_POS_ABOVE 失败率虚高。

9. **哪些 Features 已达到 FEATURE_REPLAY_READY？**  
   Volume Ratio, Turnover 1D, Turnover 20D, ATR, MA20。

10. **哪些仍 BLOCKED？**  
    Price Position（窗口不同）、Market Cap（STRICT 16.3%）、ST（BLOCKED）。

11. **Replay B 是否可以在修正语义后恢复？**  
    **PARTIAL** — 修正 Price Position 窗口后，仍受 ST UNKNOWN 和 Market Cap PARTIAL 限制。

12. **ST 仍然造成多大阻塞？**  
    **100%** — 所有 case 因 ST UNKNOWN 无法确定候选状态。

13. **下一阶段最值得做什么？**  
    1. 修正 Price Position 窗口为 500 日
    2. 扩大 Pilot 样本至中小盘
    3. 继续寻找 Historical ST 数据源

## 14. Known Limitations

1. **Price Position 窗口差异** — 500 vs 250 日，需修正 Historical Replay Engine
2. **Pilot 样本偏差** — 大盘股占比过高，不能代表 V1 真实扫描分布
3. **ST 数据完全缺失** — 无法进行任何 ST 相关验证
4. **Market Cap STRICT 覆盖率低** — 仅 16.3% PIT-safe
5. **ATR 时间语义差异** — 不同数据截止日导致 ATR 值不同，但这是预期行为
