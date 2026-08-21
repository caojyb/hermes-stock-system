# Full V1 Candidate + Entry Signal Research — Findings (Phase 8-G3 Closeout)

> **RESEARCH-ONLY** · 不修改生产 · 不输出参数建议
> `EXPLORATORY_RESEARCH = TRUE`
> `OUTCOME_SAMPLE_STATUS = RESEARCH_SENSITIVITY`

---

## 0. 收口说明（Semantic Reconciliation）

本文件为 Phase 8-G3 Closeout 版本，修正了以下用户指出必须收口的问题：

| 问题 | 收口结论 |
|---|---|
| **Price Position 语义** | `PRICE_POS_WINDOW = 500`（回看窗口），`PRICE_POS_MAX = 40`（分位上限 %），非矛盾 |
| **final_candidate = UNKNOWN** | 全部 15,045 条候选均为 UNKNOWN（Market Cap APPROXIMATE → UNKNOWN），**无严格 PASS 样本** |
| **结论边界** | `G2_FOLLOWUP = CONFIRMED_IN_CURRENT_RESEARCH_SAMPLE`（仅限当前研究样本，不升级为 V1 结论） |
| **样本规模** | 30 股 × 2015–2024 weekly = RESEARCH_SAMPLE，非 FULL_MARKET_RESEARCH |

---

## 1. Research Objective

把 G2 的 Volume Ratio 研究推进到"完整 V1 Candidate + V1 Entry Signal"层，
判断 G2 的现象（VR >=2.7 负向尾部）在真实 V1 选择链中是否仍然存在，
以及 Entry Signal 是否会改变该关系。

---

## 2. Production Semantics（继承 G1/G2，已确认）

- **Cadence**：weekly（周日 17:20）
- **Candidate Time**：每周最后交易日
- **Entry Time**：T+1 Open
- **VR Formula**：`vol_ratio = 5日均量 / 前20日均量(kl[-25:-5])`（FORMULA_MATCH = TRUE）
- **Price Position**：`(close - min) / (max - min) * 100`，500 日窗口，阈值 `<= 40%`
- **Market Cap**：5-90 亿
- **ATR**：14 日 ATR / close * 100 >= 3%
- **Amount**：1D >= 8000 万，20D >= 4000 万
- **ST**：无历史数据 → UNKNOWN
- **Entry Signal A/B/C/D**：见下方

### V1 Entry Signal 审计（锁定）

| Signal | 公式 | 源码 |
|---|---|---|
| A | close > MA20 且 MA20 >= 前日 MA20（需 >=21 根） | daily_data_refresh L309 |
| B | 3日量 / 10日均量 > 1.8（需 >=13 根） | L318 |
| C | close >= 20日最高 high（需 >=20 根） | L324 |
| D | MACD 金叉（DIF 上穿 DEA）或 DIF>0 & DEA>0 & DIF>DEA（需 >=35 根） | L339 |

**Entry Confirmed**：`signal_count >= 3`（double_monitor 482 行）

---

## 3. Full V1 Filter Chain 审计

| Filter | Production Authority | Research Adapter | PIT Status | Research Status |
|---|---|---|---|---|
| Universe | load_universe (G1) | cp.load_universe | PIT | CONFIRMED |
| Market Cap | mcap_state (G1) | cp.mcap_state | PIT-APPROXIMATE | RESEARCH_PARTIAL |
| ST | 无历史数据 | st_pass = None | UNKNOWN | BLOCKED（全 UNKNOWN） |
| Volume Ratio | scan_doubling_potential | cp.compute_metrics | PIT | CONFIRMED |
| Amount 1D | stock_strategy_config | cp.compute_metrics | PIT | CONFIRMED |
| Amount 20D | stock_strategy_config | cp.compute_metrics | PIT | CONFIRMED |
| ATR | stock_strategy_config | cp.compute_metrics | PIT | CONFIRMED |
| Price Position | scan_doubling_potential L100 | cp.compute_metrics | PIT | CONFIRMED |

---

## 4. Research Data

- **30 只股票 × 2015–2024（weekly cadence）**
- **15,555 条候选级记录**，**4,233 条信号级记录**
- 来源：历史 K 线 + PIT 特征 + PIT 市值重建（非 double_up_scores）
- Regime 映射：PIT 重建（2015-2024：高波动794/震荡1280/低量能345/强趋势12）

---

## 5. CANDIDATE_UNKNOWN_BREAKDOWN

| Filter | PASS | FAIL | UNKNOWN | UNKNOWN 原因 |
|---|---:|---:|---:|---|
| Universe | - | - | 15,045 | 全部 |
| Market Cap | 0 | 0 | 15,045 | fixtures 股本事件全为 APPROXIMATE_EFFECTIVE_DATE → APPROXIMATE → UNKNOWN |
| ST | - | - | 15,045 | 无历史 ST 数据源 |
| Volume Ratio | 7,204 | 8,341 | 0 | - |
| Amount 1D | 15,045 | 0 | 0 | - |
| Amount 20D | 14,514 | 531 | 0 | - |
| ATR | 15,000 | 45 | 0 | - |
| Price Position | 6,925 | 8,120 | 0 | - |

**关键**：Market Cap APPROXIMATE 导致 `decide_final()` 返回 `UNKNOWN`（fail-safe）。
`final_candidate` 分布：**UNKNOWN = 15,045 / PASS = 0 / FAIL = 0**

---

## 6. OUTCOME_SAMPLE_STATUS

| Outcome 数据集 | 样本筛选规则 | 状态 |
|---|---|---|
| Candidate Outcome | 全部 final_candidate = UNKNOWN（Market Cap APPROXIMATE） | **RESEARCH_SENSITIVITY** |
| Signal Outcome | entry_confirmed=True 且 final_candidate = UNKNOWN | **RESEARCH_SENSITIVITY** |
| STRICT_SIGNAL | final_candidate = PASS + signal_count >= 3 | **DATA_INSUFFICIENT**（0 条） |

**4,233 条 Signal 全部来自 UNKNOWN Candidate** → 不能称为"严格完整 V1 Entry Signal"，只能称为 `RESEARCH_SIGNAL`。

---

## 7. FACT / EVIDENCE / HYPOTHESIS

### FACT（数据直接显示）
1. **全部 15,045 条候选 final_candidate = UNKNOWN**（Market Cap APPROXIMATE，fixtures 限制）
2. **全部 4,233 条 Signal 均来自 UNKNOWN Candidate**（无 STRICT_SIGNAL 样本）
3. **VR 分布**：中位 1.07，Q90=1.59，Q95=1.92，Q99=2.96，max=13.9
4. **2.7 分位**：约 Q98.5（极尾部）
5. **Candidate-level VR×Outcome（median 20D）**：
   - VR<2.0: **+0.24%** (14,841)
   - 2.0–2.7: **-0.83%** (435)
   - >=2.7: **-2.53%** (279)
6. **Signal-level VR×Outcome（median 20D）**：
   - VR<2.0: **-0.05%** (3,679)
   - 2.0–2.7: **-1.39%** (321)
   - >=2.7: **-2.76%** (233)
7. **G2_FOLLOWUP = CONFIRMED_IN_CURRENT_RESEARCH_SAMPLE**
8. **Monotonicity = NON_MONOTONIC**
9. **Time Stability**：两期均出现（2015-19: B5=-0.43%, B6=-2.34%; 2020-24: B5=-1.72%, B6=-2.64%）

### EVIDENCE
- 在当前研究样本（UNKNOWN Candidate + RESEARCH_SIGNAL）中，VR>=2.7 的负向偏置在 Candidate 与 Signal 层方向一致
- STRONG_TREND 样本极少（5-6条），DATA_INSUFFICIENT
- 所有样本 Market Cap = UNKNOWN（fixtures 限制）

### HYPOTHESIS
- 高 VR（>=2.0）在完整 V1 选择链中仍代表追高风险 / 均值回归，而非 Edge
- Entry Signal 未能修正高 VR 的负向偏置
- 但样本局限于中大盘股 + APPROXIMATE 市值，全市场小市值分布未覆盖

---

## 8. Candidate vs Signal 并列分析

| Layer | VR<2.0 | 2.0–2.7 | >=2.7 |
|---|---|---|---|
| Candidate (med20D) | +0.24% | -0.83% | -2.53% |
| Signal (med20D) | -0.05% | -1.39% | -2.76% |
| Candidate N | 14,841 | 435 | 279 |
| Signal N | 3,679 | 321 | 233 |

**注意**：Signal 层的负向偏置略大于 Candidate 层（B6: -2.76% vs -2.53%），
但所有 Signal 均来自 UNKNOWN Candidate（RESEARCH_SENSITIVITY）。

---

## 9. Regime × VR Matrix（median 20D）

### Candidate

| Regime | VR<2.0 | 2.0–2.7 | >=2.7 |
|---|---|---|---|
| ALL | +0.24% | -0.83% | -2.53% |
| HIGH_VOL | +0.41% | -1.59% | -2.00% |
| LOW_VOLUME | +0.44% | -0.75% | -3.67% |
| SIDEWAYS | +0.13% | -0.71% | -2.44% |
| STRONG_TREND | -1.91% | -6.90% | -3.51% |

### Signal

| Regime | VR<2.0 | 2.0–2.7 | >=2.7 |
|---|---|---|---|
| ALL | -0.05% | -1.39% | -2.76% |
| HIGH_VOL | -0.32% | -2.25% | -1.80% |
| LOW_VOLUME | +0.80% | -2.32% | -4.32% |
| SIDEWAYS | -0.18% | -0.71% | -2.83% |

**注意**：STRONG_TREND 样本极少（5-6条），DATA_INSUFFICIENT。

---

## 10. Time Stability

| Period | Candidate VR<2.0 | Candidate 2.0–2.7 | Candidate >=2.7 | Signal VR<2.0 | Signal 2.0–2.7 | Signal >=2.7 |
|---|---|---|---|---|---|---|
| 2015-2019 | +0.81% | -0.43% | -2.34% | +0.42% | -0.58% | -2.52% |
| 2020-2024 | -0.16% | -1.72% | -2.64% | -0.59% | -2.31% | -2.77% |

**注意**：仅覆盖 2015–2024（无 2005–2014），跨时期结论为 `DIRECTIONALLY_CONSISTENT_BUT_DATA_INSUFFICIENT`。

---

## 11. Confounders

- **Market Cap**：全为 UNKNOWN（fixtures 限制），无法分层
- **ATR**：HIGH/MID/LOW 各桶中 B5/B6 均为负（方向一致）
- **Price Position**：各桶中 B5/B6 均为负（方向一致）

---

## 12. Research Conclusion

### 最终结论标签

| 标签 | 值 |
|---|---|
| **G2_FOLLOWUP** | `CONFIRMED_IN_CURRENT_RESEARCH_SAMPLE` |
| **VR_MONOTONICITY** | `NON_MONOTONIC` |
| **VR_2_7_INCREMENTAL** | `NO_INCREMENTAL_EVIDENCE` |
| **REGIME_CONDITIONAL** | `PRELIMINARY_PATTERN` |

### 核心回答（严格限定在当前研究样本）

1. **G2 的 VR >=2.7 negative pattern 在 Full V1 Research Candidate 中复现**（但 Candidate 全为 UNKNOWN）
2. **G2 的 VR >=2.7 negative pattern 在 Entry Signal 中复现**（但 Signal 全来自 UNKNOWN Candidate）
3. 完整 V1 Filter Chain **未改变** G2 方向
4. Entry Signal **未改善** 高 VR 的负向偏置
5. **无严格 PASS 样本** → 不能声称"完整 V1 Candidate 层已证明"

### 严格边界

- 本研究是**候选级 + 信号级 Counterfactual**，`final_candidate = UNKNOWN`（Market Cap APPROXIMATE）
- **不代表"V1 失效"**，也不代表"2.7 应修改"
- **不输出任何参数建议**
- 未启用 Strategy Selector，未修改生产
- **30 股 × 2015–2024 weekly = RESEARCH_SAMPLE**，不能升级为全市场结论

---

## 13. Data Limitations

1. 全部候选 `final_candidate = UNKNOWN`（Market Cap APPROXIMATE）
2. Signal 层 4,233 条全部来自 UNKNOWN Candidate（RESEARCH_SENSITIVITY）
3. STRONG_TREND 仅 5-6 条（DATA_INSUFFICIENT）
4. 样本为 30 只中大盘股，未覆盖全市场小市值分布
5. 时间窗口仅 2015-2024（无 2005-2014）
6. 市值 APPROXIMATE → 无法展开 STRICT/RESEARCH/SENSITIVITY 对比
7. ST 完全 UNKNOWN

---

## 14. Research Health

**RESEARCH_PARTIAL**

| 维度 | 状态 |
|---|---|
| production_semantics | CONFIRMED |
| VR_formula | CONFIRMED |
| candidate_cadence | CONFIRMED |
| candidate_timing | CONFIRMED |
| entry_timing | CONFIRMED |
| price_position | CONFIRMED（WINDOW=500, MAX=40） |
| feature | CONFIRMED |
| regime | CONFIRMED（STRONG_TREND DATA_INSUFFICIENT） |
| market_cap | RESEARCH_PARTIAL（APPROXIMATE → UNKNOWN） |
| ST | BLOCKED（全 UNKNOWN） |
| forward_outcome | CONFIRMED |
| baseline | CONFIRMED |
| time_stability | DIRECTIONALLY_CONSISTENT_BUT_DATA_INSUFFICIENT |
| regime_coverage | LIMITED |
| survivorship | LIMITED |

---

## 15. 最终回答

| # | 问题 | 回答 |
|---|---|---|
| 1 | Price Position 的真实 Production 语义？ | `(close - min) / (max - min) * 100`，500 日窗口，阈值 <=40% |
| 2 | 500 和 40 各自是什么？ | 500 = 回看窗口，40 = 阈值（%） |
| 3 | Research Adapter 是否完全匹配？ | ✅ 公式/窗口/阈值一致 |
| 4 | test_01 为什么错误/是否真的错误？ | 不错误——断言 `PRICE_POS_MAX == 40` 正确 |
| 5 | final_candidate UNKNOWN 的完整来源？ | Market Cap APPROXIMATE（fixtures 限制）→ UNKNOWN |
| 6 | Candidate Outcome 使用哪类样本？ | RESEARCH_SENSITIVITY（全部 UNKNOWN） |
| 7 | Signal Outcome 使用哪类 Candidate？ | UNKNOWN Candidate（entry_confirmed=True） |
| 8 | STRICT_SIGNAL 样本多少？ | **0**（DATA_INSUFFICIENT） |
| 9 | RESEARCH_SIGNAL 样本多少？ | 4,233 |
| 10 | 4,233 中有多少 Strict？ | **0** |
| 11 | G2 Follow-up 是否仍成立？ | `CONFIRMED_IN_CURRENT_RESEARCH_SAMPLE`（方向一致，但样本受限） |
| 12 | 严格表述？ | "在当前研究样本中，VR>=2.7 负向尾部在 Candidate 与 Signal 层方向一致复现" |
| 13 | Candidate 与 Signal 两层是否方向一致？ | ✅ 是（均 NON_MONOTONIC，B6 最差） |
| 14 | 是否存在 Regime Conditional Pattern？ | PRELIMINARY_PATTERN（各 Regime 高 VR 均偏弱，但样本/覆盖有限） |
| 15 | 是否跨时期稳定？ | DIRECTIONALLY_CONSISTENT_BUT_DATA_INSUFFICIENT（仅两期，无 2005-2014） |
| 16 | 哪些 Period × Regime DATA_INSUFFICIENT？ | 2005-2014（无数据）；STRONG_TREND × 所有 VR Band |
| 17 | Survivorship 影响？ | LIMITED（无 delist 历史） |
| 18 | ST sensitivity 是否改变方向？ | 否（ST 全 UNKNOWN，无法展开） |
| 19 | Market Cap sensitivity 是否改变方向？ | 无法验证（全 UNKNOWN） |
| 20 | 当前最高强度结论？ | "当前研究样本中 VR>=2.7 表现最差，但 Candidate 全为 UNKNOWN，Signal 全来自 UNKNOWN Candidate" |
| 21 | 属于哪一层？ | EVIDENCE（方向一致）+ HYPOTHESIS（高 VR 代表追高/均值回归） |
| 22 | Research Health？ | RESEARCH_PARTIAL |
| 23 | Full V1 Research 是否可以停止？ | **Candidate/Signal 层结构已验证，但 STRICT 层 DATA_INSUFFICIENT。如目标仅为语义验证，可停止；如需更严格结论，需解决 Market Cap APPROXIMATE 问题。** |
| 24-26 | 是否修改 2.7 / 参数 / Selector？ | **否** |

---

*Phase 8-G3 Closeout · Full V1 Candidate + Entry Signal Research · `CONFIRMED_IN_CURRENT_RESEARCH_SAMPLE` / `NON_MONOTONIC` / `NO_INCREMENTAL_EVIDENCE` / `PRELIMINARY_PATTERN` · RESEARCH_PARTIAL*
