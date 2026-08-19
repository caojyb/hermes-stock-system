# HISTORICAL_FEATURE_RECONSTRUCTION.md（Phase 7.3-B）

## 1. Production Feature Definitions

### 1.1 MA20
- **计算价格**：close（klines.close）
- **窗口长度**：20 个交易日
- **算法**：SMA（简单移动平均）
- **公式**：`ma20 = sum(closes[-20:]) / 20`
- **边界处理**：不足 20 根 K 线返回 `None`（`UNKNOWN`）
- **缺失行为**：无有效 close 则跳过
- **代码位置**：`daily_data_refresh.py:264`, `daily_data_refresh.py:341`
- **价格语义**：klines 原始价格，不复权
- **warm-up**：20 个有效交易日

### 1.2 ATR(14)
- **计算价格**：high, low, close
- **周期**：14
- **True Range 定义**：
  ```
  TR = max(high - low, |high - prev_close|, |low - prev_close|)
  ```
- **算法**：SMA（简单移动平均），非 Wilder 平滑
- **公式**：`atr = sum(trs[-14:]) / 14`
- **边界处理**：不足 14 根 K 线返回 `None`
- **代码位置**：`v1_stress_test.py:125`, `param_verify_full.py:112`
- **价格语义**：klines 原始价格
- **warm-up**：15 个有效交易日（14 日 TR + 首日）

### 1.3 MACD
- **计算价格**：close
- **fast period**：12
- **slow period**：26
- **signal period**：9
- **算法**：EMA（指数移动平均）
- **公式**：
  ```
  EMA12 = EMA(closes, 12)
  EMA26 = EMA(closes, 26)
  DIF = EMA12 - EMA26
  DEA = EMA(DIF, 9)
  MACD_hist = (DIF - DEA) * 2
  ```
- **代码位置**：`daily_data_refresh.py:327-339`
- **warm-up**：35 个有效交易日（26 + 9）
- **注意**：生产 indicators 表中 `macd`, `macd_signal`, `macd_hist` 当前多为 `NULL`

### 1.4 Volume Ratio
- **定义**：5 日均量 / 20 日均量
- **公式**：`vol_ratio = sum(volumes[-5:]) / 5 / (sum(volumes[-20:]) / 20)`
- **使用的量**：volume（成交股数），非 amount（成交金额）
- **包含当前交易日**：是
- **异常值处理**：无特殊处理，分母为 0 时返回 `None`
- **代码位置**：`daily_data_refresh.py:267-271`
- **warm-up**：20 个有效交易日

### 1.5 Signal Score
- **生产定义**：未实现计算逻辑
- **当前值**：`daily_data_refresh.py` 硬编码为 `0`
- **组成**：A/B/C/D 信号（`signal_a`, `signal_b`, `signal_c`, `signal_d`）
- **重建状态**：❌ BLOCKED
- **原因**：生产代码中 `signal_score` 始终为 0，无真实计算公式

---

## 2. Historical Feature Adapter

### 2.1 文件
`historical_features.py`

### 2.2 公开 API
```python
get_historical_features(symbol: str, as_of_date: str) -> dict
validate_pit_cutoff(symbol: str, as_of_date: str, features: dict) -> bool
```

### 2.3 输出格式
```json
{
  "symbol": "000001",
  "as_of_date": "2024-06-30",
  "feature_source": "HISTORICAL_REPLAY",
  "formula_version": "pit-v1.0",
  "calculation_time": "2026-08-19T...Z",
  "source_table": "klines",
  "ma20": 10.5,
  "atr_14": 0.3,
  "atr_14_pct": 2.85,
  "macd": 0.12,
  "macd_signal": 0.08,
  "macd_hist": 0.08,
  "volume_ratio": 1.2,
  "signal_score": "UNKNOWN",
  "warmup_sufficient": true,
  "pit_cutoff": "2024-06-30",
  "klines_used": 120,
  "max_trade_date": "2024-06-30"
}
```

### 2.4 隔离规则
- 仅读取 `klines` 表
- 不读取 `indicators` 表
- 不读取 `stocks` 表
- 不修改 `market.db`
- 输出标记 `feature_source = HISTORICAL_REPLAY`

---

## 3. PIT Rules

### 3.1 时间截断
所有 K 线查询使用：
```sql
WHERE code=? AND date<=? ORDER BY date ASC
```

### 3.2 禁止读取
- 当前 `indicators` 表
- 当前 `stocks` 表
- 当前 `market cap`
- 当前 `industry`
- 当前最新状态

### 3.3 缺失处理
- warm-up 不足 → `UNKNOWN`
- 数据不存在 → `UNKNOWN`
- 不从当前快照 fallback

---

## 4. Warm-up Rules

| Feature | 所需最小交易日 | 不足时结果 |
|---|---|---|
| MA20 | 20 | UNKNOWN |
| ATR(14) | 15 | UNKNOWN |
| MACD | 35 | UNKNOWN |
| Volume Ratio | 20 | UNKNOWN |
| Signal Score | N/A | UNKNOWN（无法重建） |

---

## 5. Feature Availability Matrix

| Feature | Historical Source | PIT Safe | Reconstructable | Production Formula Known | Status |
|---|---|---|---|---|---|
| MA20 | klines | ✅ | ✅ | ✅ | RECONSTRUCTABLE |
| ATR(14) | klines | ✅ | ✅ | ✅ | RECONSTRUCTABLE |
| MACD | klines | ✅ | ✅ | ✅ | RECONSTRUCTABLE |
| Volume Ratio | klines | ✅ | ✅ | ✅ | RECONSTRUCTABLE |
| Signal Score | ❌ | ❌ | ❌ | ❌ | BLOCKED |
| Market Cap | stocks | ❌ | ❌ | ✅ | BLOCKED |
| Industry | stocks | ❌ | ❌ | ✅ | BLOCKED |
| ST Status | stocks | ❌ | ❌ | ✅ | BLOCKED |

---

## 6. Production vs Historical Feature 对照验证

### 6.1 MA20 对比结果
- **抽样**：20 个股票 × 20 个交易日
- **mismatch rate**：< 30%
- **主要差异原因**：
  1. production indicators 中部分日期为 `NULL`
  2. 部分早期数据 warm-up 不足

### 6.2 MACD 对比结果
- **抽样**：20 个样本（production indicators 中 `macd IS NOT NULL`）
- **发现**：production indicators 中 `macd` 几乎全为 `NULL`
- **标记**：FEATURE_SEMANTIC_CONFLICT（生产指标本身不完整）
- **结论**：无法可靠对比，历史重建公式按 `daily_data_refresh.py` 实现

### 6.3 Signal Score
- **生产值**：始终为 0
- **重建值**：UNKNOWN
- **结论**：PRODUCTION_FEATURE_SEMANTICS_UNKNOWN

---

## 7. Price Semantics

### 7.1 当前价格
- `klines.open/close/high/low`：原始价格，不复权
- `indicators.current_price`：可能为原始价格（未明确标注）

### 7.2 V1 使用的价格
- MA20/ATR/MACD/Volume Ratio：基于 klines 原始 close/high/low/volume
- 未发现前复权/后复权字段

### 7.3 结论
- 历史重建使用 klines 原始价格
- 与 production indicators 价格语义一致（klines 原始价格）
- 无 PRICE_SEMANTIC_CONFLICT

---

## 8. Versioning

- `formula_version = 'pit-v1.0'`
- 相同 `symbol + as_of_date + formula_version` 得到确定性一致结果
- 公式变更时需更新 version

---

## 9. Production Isolation

- Historical Feature 仅写入内存/返回值
- 不写入 production `indicators`
- 不写入 production `stocks`
- 不写入 Production Evaluation Dataset
- 不写入 Production Outcome

---

## 10. Tests

| Test | 数量 | 状态 |
|---|---|---|
| PIT cutoff | 3 | ✅ |
| MA20 | 3 | ✅ |
| ATR | 4 | ✅ |
| MACD | 2 | ✅ |
| Volume Ratio | 2 | ✅ |
| Signal Score | 1 | ✅ |
| Production Comparison | 2 | ✅ |
| No Fallback | 1 | ✅ |
| Deterministic | 1 | ✅ |
| Feature Metadata | 2 | ✅ |
| Warmup | 2 | ✅ |
| **Total** | **23** | **passed** |

---

## 11. Known Limitations

1. **Signal Score 无法重建**：生产代码中未实现计算公式
2. **MACD 生产值几乎全为 NULL**：无法可靠对比
3. **Market Cap / Industry / ST 仍无法重建**：Phase 7.3-A 已确认
4. **ATR 使用 SMA 算法**：与 Wilder 平滑不同，但按生产代码实现
5. **Volume Ratio 使用 volume**：非 amount，按生产代码实现

---

## 12. Replay Readiness

### 12.1 当前状态
- ✅ MA20：RECONSTRUCTABLE
- ✅ ATR(14)：RECONSTRUCTABLE
- ✅ MACD：RECONSTRUCTABLE
- ✅ Volume Ratio：RECONSTRUCTABLE
- ❌ Signal Score：BLOCKED
- ❌ Market Cap：BLOCKED
- ❌ Industry：BLOCKED
- ❌ ST Status：BLOCKED
- ❌ Permission：BLOCKED
- ❌ Portfolio：BLOCKED

### 12.2 结论
**Historical Technical Features = RECONSTRUCTABLE**  
**V1 Historical Replay = 仍未解锁**（需 Phase 7.3-C 解决 Market Cap / Industry / Universe / Portfolio）

---

## 13. Code Provenance

| Feature | 公式来源 | 代码位置 |
|---|---|---|
| MA20 | `daily_data_refresh.py:264` | SMA(closes, 20) |
| ATR(14) | `v1_stress_test.py:125` | SMA(TR, 14) |
| MACD | `daily_data_refresh.py:327-339` | EMA(12/26/9) |
| Volume Ratio | `daily_data_refresh.py:269-271` | SMA(vol, 5) / SMA(vol, 20) |
| Signal Score | ❌ 无公式 | `daily_data_refresh.py:363` 硬编码 0 |
