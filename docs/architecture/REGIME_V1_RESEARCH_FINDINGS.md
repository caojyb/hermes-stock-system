# Regime-Conditional V1 Research Reconstruction — Findings (Phase 8-G1)

> 本文件是 Phase 8-G1 的研究结果。研究层级严格锁定为 **Candidate / Signal Evidence**，
> 不是完整 Production Strategy Edge。Research 与 Production 物理隔离，
> 不修改任何生产策略 / V1 / 参数 / Regime / DecisionEngine。
> `EXPLORATORY_RESEARCH = TRUE`
> 结论标签：**PRELIMINARY_PATTERN**（Stability Gate 未预先定义，不输出 STABLE_RESEARCH_PATTERN）

---

## 1. Research Objective

重建历史 V1 Candidate / Signal 行为，并按 Production Market Regime 分层，研究
「V1 Candidate Quality 是否具有稳定的 Regime Conditional Pattern」。

## 2. Production Semantics（已确认）

| Stage | Production Time | Frequency | Historical Research Time |
|---|---|---|---|
| Candidate Scan | 周日 17:20 | **Weekly** | 每周最后交易日 |
| Candidate Snapshot | 周日 17:20 | Weekly | 同上 |
| Entry Signal | 每日 16:50 (double_monitor) | Daily | T 日 |
| Planned Entry | T+1 Open | — | T+1 开盘 |
| Entry Price | T+1 Open price | — | T+1 开盘价 |

**Cadence 已确认 = WEEKLY**（周日 `stock-weekly-screener` cron → `scan_doubling_potential.py`）。
Historical Research 按 weekly cadence 重建，**不得用 daily 收盘重算冒充**。

## 3. V1 Production Filter Matrix（已冻结，来源 stock_strategy_config v1_double）

| Filter | 阈值 | PIT 状态 |
|---|---|---|
| Market Cap | 5–90 亿 | PIT-APPROXIMATE（akshare 股本+收盘价） |
| Volume Ratio | ≥ 2.7 | PIT |
| 1D Amount | ≥ 8000 万 | PIT |
| 20D Amount | ≥ 4000 万 | PIT |
| ATR | ≥ 3% | PIT |
| Price Position | 分位 ≤ 40% (500日) | PIT |
| ST | 排除 | **UNKNOWN**（无历史） |

## 4. Regime Definition（Production Authority，唯一）

来自 `market_env_classifier.py::classify_market()`：
- trend 30% + volatility 25% + liquidity 25% + style 20%
- 基于 000300 + 000905 指数 K 线
- 状态：🔴高波动 / 🟢强趋势 / ⚫低量能 / 🟡震荡市
- 研究复用同一公式，仅加 Historical Adapter（as-of 窗口）

## 5. Historical Regime PIT Reconstruction（实证）

- 000300 覆盖 2004-12-31 ~ 2026-07-24（2005-2025 每年 238-246 交易日）
- 000905 覆盖 2001-03-23 ~ 2026-08-20
- **PIT 重建可行**：`research/regime_pit.py` 输出 regime_daily.csv
- 2015-2016 实证分布：高波动 198 / 震荡 165 / 低量能 118 / 强趋势 7
- ⚠️ 000300 2026-07-24 后缺口 → 该日期后 regime 标记 UNKNOWN 或仅用 000905

## 6. Historical V1 Candidate Reconstruction（实证）

- 从历史 K 线 + PIT 特征 + PIT 市值重建（`research/candidate_pit.py`）
- **double_up_scores 仅用于 Production Semantics Validation，非历史真值**
- 实证：18 只中盘股 × 2015-2019 周频 = 4590 行 trace

## 7. PIT Rules & Survivorship

- 所有输入 available_time <= as_of_date
- ST 全部 UNKNOWN（不计 PASS）
- survivorship：as-of universe 基于 klines 首末交易日，无 delist 表 → LIMITED

## 8. Research Health（research_summary.json）

- production_semantics: CONFIRMED
- cadence: CONFIRMED_WEEKLY
- candidate_timing: CONFIRMED_SUNDAY_1720
- entry_timing: CONFIRMED_T_PLUS_1_OPEN
- feature: PIT
- regime: PIT_WITH_INDEX_GAP
- market_cap: PIT_APPROXIMATE
- ST: **UNKNOWN_NO_HISTORY**
- universe: AS_OF_AVAILABLE
- survivorship: LIMITED
- forward_outcome: PIT_T_PLUS_1_OPEN
- baseline: ALL_REGIMES_COMPUTED
- stability: NOT_FORMALLY_DEFINED

→ **RESEARCH_PARTIAL**（ST 完全 UNKNOWN、survivorship 受限、000300 近期缺口）

## 9. Key Empirical Findings（实证）

### FACT
- V1 硬过滤极严格：量比 ≥2.7 在历史样本中**中位仅 ~0.92**，绝大多数股票不满足
- 历史 Regime 可 PIT 重建（指数数据 2004 起完整）
- 历史市值可 PIT-APPROXIMATE 重建（akshare 股本事件 + 收盘价）
- 所选 8-18 只股票 trace 中 final_candidate 多为 FAIL（市值超 90 亿 或 量比<2.7）
- 无历史 ST 数据，ST 全 UNKNOWN

### EVIDENCE
- Volume Ratio 2.7 是极稀缺过滤器：是 V1 候选全市场 PASS 率低的主导性 filter
- 不同 Regime 下候选数量差异初步存在（高波动 vs 震荡），但样本不足

### HYPOTHESIS
- V1 候选生成可能在高波动环境更稀缺（量比/ATR 阈值在高波动时更易触发但流动性约束限制）
- 需全市场扫描（非 fixtures 子集）才能获得足够 PASS 样本做统计

## 10. Data Limitations

1. 候选样本需全市场扫描，fixtures 仅覆盖部分股票（多为中大盘）
2. 无完整 Historical ST
3. 无 delist 表，survivorship 受限
4. 000300 指数 2026-07-24 后缺口
5. Stability Gate 未预先定义 → 最高结论 PRELIMINARY_PATTERN

## 11. Research Conclusion

- **当前最终标签：PRELIMINARY_PATTERN**（Regime×V1 存在初步差异信号，但样本/稳定性不足，Stability Gate 未定义）
- 不做 STABLE_RESEARCH_PATTERN 判定
- 不提供参数建议
- 未启用 Strategy Selector

## 12. No Production Changes

本阶段未修改任何生产策略 / V1 / 参数 / Regime / DecisionEngine / Selector。
研究输出仅落盘 `research/artifacts/regime_v1/`（regime_daily.csv / candidate_filter_trace*.csv / candidate_outcomes.csv / pilot_sample_manifest.csv / research_summary.json），物理隔离。

---

## Research Modules
- `research/regime_pit.py`：历史 Regime PIT 重建
- `research/candidate_pit.py`：历史 V1 候选 PIT filter 重建（支持 --fixtures 离线）
- `research/forward_outcome.py`：5/10/20D forward outcome + MAE/MFE
- 测试：`test_regime_v1_research.py`（7 项核心语义测试）

*Phase 8-G1 · Regime-Conditional V1 Research Reconstruction · 研究结果（PRELIMINARY_PATTERN）*
