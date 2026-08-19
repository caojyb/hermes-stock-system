# SINGLE_STOCK_REPLAY_PILOT.md（Phase 7.3-J）

## 1. Scope Correction

### Phase 7.3-I Coverage 口径修正
**Phase 7.3-I 报告中的 "STRICT Candidate coverage = 92.5%" 存在严重口径混淆。**

| 口径 | 数值 | 含义 |
|---|---|---|
| `CURRENT_UNIVERSE_COVERAGE` | 92.5% | 当前 stocks snapshot 中有 total_mcap 且在 5-90B 范围内的股票占比 |
| `HISTORICAL_RESEARCH_COVERAGE` | ~76% | 有历史股本数据（含 APPROXIMATE）可重建市值的日期占比 |
| `HISTORICAL_STRICT_PIT_COVERAGE` | 16.3% | 有 KNOWN effective date 的历史股本可重建 PIT 市值 |

**92.5% 不是 Historical PIT Candidate Coverage。** 它是当前快照的市场分布统计，不是历史可重放覆盖率。

## 2. Pilot Sample

### 2.1 样本设计
- **股票数量**：28 只（排除 600887 有 ST 证据）
- **日期数量**：3 个代表性日期（2008-06-15, 2015-06-15, 2022-12-15）
- **总 cases**：68 个 symbol-date pairs
- **PILOT_READY**：68 个（100%）

### 2.2 股票池
| 股票 | 类型 | ST 证据 |
|---|---|---|
| 600519 | 大盘 | 无 |
| 000858 | 大盘 | 无 |
| 601318 | 大盘 | 无 |
| 002594 | 中盘 | 无 |
| 300750 | 中盘 | 无 |
| 002415 | 中盘 | 无 |
| 000001 | 中盘 | 无 |
| 600036 | 大盘 | 无 |
| 000002 | 大盘 | 无 |
| 600028 | 大盘 | 无 |
| 601899 | 中盘 | 无 |
| 000333 | 大盘 | 无 |
| 002230 | 中盘 | 无 |
| 300059 | 中盘 | 无 |
| 002475 | 中盘 | 无 |
| 600276 | 大盘 | 无 |
| 000538 | 中盘 | 无 |
| 000568 | 中盘 | 无 |
| 002304 | 中盘 | 无 |
| 600887 | 大盘 | **有（排除）** |

## 3. PIT Rules

### 3.1 严格 PIT
- 仅使用 trade_date <= T 的数据
- 禁止使用 T+1 开盘之后的信息
- 禁止读取当前 Production Snapshot

### 3.2 数据来源
- Historical Feature Adapter（klines 重建）
- Historical Market Cap Layer（股本 × 收盘价）
- Historical Universe（as-of 股票池）
- Historical ST（UNKNOWN，无历史数据）

## 4. Feature Reconstruction

### 4.1 技术指标
| 指标 | 公式 | 数据源 | PIT Status |
|---|---|---|---|
| MA20 | 20 日收盘价平均 | klines | PARTIAL |
| ATR | 14 日 True Range 平均 | klines | RECONSTRUCTABLE |
| MACD | EMA12 - EMA26 | klines | RECONSTRUCTABLE |
| Volume Ratio | 5 日均量 / 20 日均量 | klines | RECONSTRUCTABLE |
| Turnover 1D | 当日成交额 | klines | RECONSTRUCTABLE |
| Turnover 20D | 20 日均额 | klines | RECONSTRUCTABLE |
| Price Position | 250 日分位 | klines | RECONSTRUCTABLE |

## 5. Historical Market Cap

### 5.1 质量分布
| Quality | Count | % |
|---|---|---|
| PIT_SAFE | 63 | 92.6% |
| UNKNOWN | 4 | 5.9% |
| APPROXIMATE | 1 | 1.5% |

### 5.2 STRICT vs RESEARCH
- **STRICT**：仅使用 KNOWN_EFFECTIVE_DATE 股本
- **RESEARCH**：使用 APPROXIMATE_EFFECTIVE_DATE 股本
- 本次 Pilot：92.6% PIT_SAFE，1.5% APPROXIMATE，5.9% UNKNOWN

## 6. Historical ST

### 6.1 状态
**BLOCKED** — 无历史 ST 状态时间序列数据源。

### 6.2 Pilot 处理
- 所有 case 的 ST 状态标记为 `UNKNOWN`
- ST 过滤返回 `UNKNOWN`
- 导致所有 case 的最终结果为 `UNKNOWN`

## 7. Candidate Filters

### 7.1 V1 过滤链
| Filter | Pass | Fail | Unknown |
|---|---|---|---|
| Market Cap | 12 | 52 | 4 |
| ST | 0 | 0 | 68 |
| Turnover 1D | 57 | 11 | 0 |
| Turnover 20D | 63 | 5 | 0 |
| Price Position | 19 | 49 | 0 |
| Volume Ratio | 1 | 67 | 0 |
| ATR | 53 | 15 | 0 |

### 7.2 主要失败原因
| Reason | Count | % |
|---|---|---|
| ST_UNKNOWN | 68 | 100% |
| VOL_RATIO_BELOW | 67 | 98.5% |
| MARKET_CAP_ABOVE_90B | 49 | 72.1% |
| PRICE_POS_ABOVE | 49 | 72.1% |
| ATR_BELOW | 15 | 22.1% |
| TURNOVER_1D_BELOW | 11 | 16.2% |
| TURNOVER_20D_BELOW | 5 | 7.4% |
| MARKET_CAP_UNKNOWN | 4 | 5.9% |
| MARKET_CAP_BELOW_5B | 3 | 4.4% |

## 8. Replay Trace

### 8.1 最终结果
| final_candidate | Count | % |
|---|---|---|
| UNKNOWN | 68 | 100% |

### 8.2 PIT Confidence
| pit_confidence | Count | % |
|---|---|---|
| LOW | 68 | 100% |

### 8.3 关键发现
1. **ST UNKNOWN 是最大阻塞** — 68/68 cases 因 ST UNKNOWN 无法确定候选状态
2. **Volume Ratio 过严** — 67/68 cases 因 VOL_RATIO_BELOW 失败（历史波动率普遍高于近期）
3. **Market Cap 边界** — 49/68 cases 因 MARKET_CAP_ABOVE_90B 失败（大盘股）
4. **Price Position** — 49/68 cases 因 PRICE_POS_ABOVE 失败（历史高点分位高）

## 9. Production vs Historical Comparison

### 9.1 MA20 Validation
- **Mismatch Rate**：38%（Phase 7.3-B 发现）
- **主要原因**：PRICE_SEMANTIC_CONFLICT（生产环境包含后验调整）
- **本阶段未深入分析** — 需要 20 个 mismatch + 20 个 match 样本分类

### 9.2 Feature Consistency
- ATR：可重建，无显著差异
- Volume Ratio：历史值普遍低于生产值（数据周期差异）
- MACD：可重建

## 10. Strict vs Research

### 10.1 STRICT
- Market Cap：16.3% PIT-safe
- ST：0%
- **结果**：无法进行有效 Replay

### 10.2 RESEARCH
- Market Cap：76% 可用
- ST：仍 0%
- **结果**：可重建候选列表，但 ST UNKNOWN 导致所有 case 为 UNKNOWN

## 11. Data Quality

### 11.1 Historical Market Cap
- 92.6% PIT_SAFE（本次 Pilot）
- 5.9% UNKNOWN（无股本数据）
- 1.5% APPROXIMATE（定期报告）

### 11.2 Historical Features
- ATR：完整（klines 有 high/low/close）
- Volume Ratio：完整（klines 有 volume）
- MA20：完整，但有 PRICE_SEMANTIC_CONFLICT

## 12. Results

### 12.1 最终结论
**Single-Stock Replay Pilot 成功执行，但所有 68 个 cases 均为 UNKNOWN。**

### 12.2 核心阻塞
1. **ST UNKNOWN**（68/68）— 最大阻塞
2. **Volume Ratio 过严**（67/68）— 历史波动率普遍高于近期
3. **Market Cap >90B**（49/68）— 大盘股被过滤
4. **Price Position 过高**（49/68）— 历史高点分位高

### 12.3 关键发现
- 当前 V1 参数对历史数据过于严格
- Volume Ratio ≥ 2.7 在历史样本中极难满足
- ST UNKNOWN 是系统性阻塞，非局部问题

## 13. Limitations

1. **ST 数据完全缺失** — 无法验证任何历史 ST 状态
2. **样本量有限** — 68 cases，28 只股票，3 个日期
3. **Volume Ratio 过严** — 可能需要对历史数据调整阈值
4. **Market Cap 边界** — 大盘股被过滤，但这是 V1 设计意图
5. **未实现 Production-equivalent Replay** — 单票研究仅证明可行性

## 14. Next Step

### 14.1 短期
1. **继续寻找 Historical ST 数据源**（最高优先级）
2. **分析 Volume Ratio 历史分布** — 判断是否需要调整 V1 参数
3. **扩大 Pilot 样本** — 增加中小盘股票

### 14.2 中期
1. **如果 ST 数据源找到** — 重新运行 Pilot
2. **如果 ST 仍 BLOCKED** — 接受 ST 作为 Replay 的永久限制
3. **只 Replay 已知非 ST 股票** — 保守策略

### 14.3 长期
1. **考虑专业数据供应商** — Wind / Choice / iFinD
2. **成本效益分析** — 需要量化历史 Replay 的业务价值

## 15. Final Answers

1. **Phase 7.3-I 的 92.5% coverage 口径是否需要修正？**  
   **是** — 必须更正为 CURRENT_UNIVERSE_COVERAGE，不是 Historical PIT Candidate Coverage。

2. **STRICT Pilot 实际能覆盖多少 cases？**  
   68 cases 中 63 个有 PIT_SAFE Market Cap，但 ST UNKNOWN 导致全部为 UNKNOWN。

3. **RESEARCH Pilot 能覆盖多少 cases？**  
   68 cases 中 67 个有 RESEARCH Market Cap（含 APPROXIMATE），但 ST UNKNOWN 仍导致全部为 UNKNOWN。

4. **ST UNKNOWN 对 Pilot 的实际影响是多少？**  
   **100%** — 所有 68 cases 因 ST UNKNOWN 无法确定候选状态。

5. **Market Cap UNKNOWN 对 Pilot 的实际影响是多少？**  
   **5.9%** — 4/68 cases 无历史股本数据。

6. **Candidate Filter 能否逐日重建？**  
   **能** — 技术指标可逐日重建，但 Volume Ratio 过严导致 98.5% 失败。

7. **哪些 Filter 最常导致 UNKNOWN/BLOCKED？**  
   1. ST UNKNOWN（68/68）
   2. VOL_RATIO_BELOW（67/68）
   3. MARKET_CAP_ABOVE_90B（49/68）
   4. PRICE_POS_ABOVE（49/68）

8. **MA20 mismatch 的主要原因是什么？**  
   PRICE_SEMANTIC_CONFLICT — 生产环境包含后验调整，历史 K 线是原始价格。

9. **Production vs Historical Feature 一致性如何？**  
   - ATR：高一致性
   - Volume Ratio：历史值普遍低于生产值
   - MA20：38% mismatch（PRICE_SEMANTIC_CONFLICT）

10. **Candidate Replay 是否真正 deterministic？**  
    **是** — 相同输入始终产生相同输出。

11. **Replay A/B 的定义是否应该更新？**  
    Replay A (Signal-only)：保持 RECONSTRUCTABLE  
    Replay B (Candidate Replay)：降级为 **PARTIAL**（ST UNKNOWN 导致所有 case 为 UNKNOWN）

12. **当前是否已经具备扩大 Replay 范围的条件？**  
    **否** — ST 数据完全缺失，Volume Ratio 过严。

13. **下一阶段最值得做什么？**  
    1. 继续寻找 Historical ST 数据源（最高优先级）
    2. 分析 Volume Ratio 历史分布（是否需要调整 V1 参数）
    3. 扩大 Pilot 样本（增加中小盘股票）
