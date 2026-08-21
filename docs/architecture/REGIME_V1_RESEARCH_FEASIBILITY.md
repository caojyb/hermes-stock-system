# Regime × V1 Research Feasibility (Phase 8-G0 / Phase B)

> 本文件评估：V1 策略的表现/候选/信号质量是否显著依赖 Market Regime，
> 以及是否具备进行 Regime-Conditional V1 Research 的数据与条件。
> 本阶段是**研究可行性审计**，不修改生产策略，不回答「改成什么参数」。

---

## 1. Research Objective

判断是否存在「稳定的 Regime Conditional Pattern」——即 V1 的候选生成、信号质量、
Entry 是否在不同市场 Regime 下表现出结构性差异。只做描述性研究，不做参数建议。

## 2. Current Regime Definition

`market_env_classifier.py::classify_market()` 产出 4 个状态：

| Regime | 判定条件 | 输入 | 窗口 |
|---|---|---|---|
| 🟢 强趋势 | total>70 AND vol_percentile<50 | 趋势30% + 波动25% + 量能25% + 风格20% | MA20/60/120, ATR20 |
| 🔴 高波动 | vol_percentile>70 | 同上 | ATR 分位 |
| ⚫ 低量能 | liq_score<30 | 同上 | 量比 vol20/vol120 |
| 🟡 震荡市 | 其余 | 同上 | — |

- 输入：沪深300(000300)、中证500(000905) 指数 K 线
- 权重：trend 30% / volatility 25% / liquidity 25% / style 20%
- 产出：`environment.label`（🔴高波动 等）+ total_score
- 版本：无显式 version 字段（当前代码即为 production 定义）

当前环境（2026-08-21）：🔴 高波动（62.9 分，波动分位 95%）

## 3. Historical Regime Reconstruction（PIT 可行性）

- 指数 K 线覆盖：沪深300 从 2004-12-31、中证500 从 2001-03-23
- 数据基础：足够重建历史 Regime（按 as-of 窗口）
- ⚠️ 数据缺口：**沪深300(000300) 指数 K 线只到 2026-07-24**（中证500 到 8-20）
  → 高波动/强趋势等基于 000300 的历史 Regime 重建受此影响
  → 对近期（7/24 后）的 Regime 重建需标记部分数据缺失
- **PIT 可行性：可行**（指数日线自 2004 年起，as-of 窗口可重建）
- **限制**：000300 近期缺失 7/24-8/20，需单独处理或标记 UNKNOWN

## 4. V1 Candidate Data

- `double_up_scores` 表：**仅覆盖 2026-05-15 ~ 2026-08-16**（16 个 scan_date，1178 行）
- `indicators` 表：138 个日期
- **关键限制**：V1 候选历史数据**不足 3 个月**，无法与 2004-2026 的长周期 Regime 对齐
- 更长周期 V1 候选需要 Historical Replay（本阶段禁止）或历史重跑
  → 当前**不具备完整历史 V1×Regime 研究数据集**

## 5. PIT Rules

- Regime(T) 只使用 as_of(T) 之前可获得的数据（指数日线）→ 可行
- V1 Candidate：需要与 Regime 按 date 关联
- 禁 look-ahead：当前 `double_up_scores` 仅 3 个月，且是最近写入，无未来污染
- 沪深300 缺口需按 as-of 标记 UNKNOWN

## 6. Survivorship Controls

- 无可靠 Historical ST 完整数据
- 本阶段**不做历史股票集合幸存者偏差补偿**（要求 Historical Replay/ST，本阶段禁止）
- 标记 UNKNOWN，不假装解决

## 7-9. Candidate Availability / Signal / Filter Distribution

**受限于数据**：
- V1 候选仅 3 个月（16 个 scan_date），且多集中在近期（2026-08 之前）
- 当前不能对不同 Regime 的候选数量做有统计意义的历史对比
- 需要更多历史候选数据（Historical Replay 或等待自然积累）才能完成

## 10-13. Forward Return / MAE-MFE / Time Stability / Regime Coverage

- **不可行（当前）**：无足够历史 V1 候选样本与完整 Regime 对齐
- 无法判断 5/10/20D forward return、MAE/MFE 是否随 Regime 变化
- 无法做 2005-2009 / 2010-2014 / 2015-2019 / 2020-2024 时间稳定性分析
- Regime 覆盖：高波动（近期）有样本；强趋势/低量能/震荡市在历史需更多数据

## 14-16. FACT / EVIDENCE / HYPOTHESIS

**FACT**（当前可确认）：
- 当前环境为高波动（vol 分位 95%）
- V1 候选数据仅覆盖 2026-05-15 ~ 08-16（3 个月）
- 沪深300 指数 K 线只到 2026-07-24（数据缺口）

**EVIDENCE**（有部分依据，不充分）：
- 高波动环境下 V1 候选数量偏少（近期观察，样本有限）

**HYPOTHESIS**（待验证）：
- V1 可能在不同 Regime 下有候选质量差异（未证实）

## 17. Data Limitations

1. V1 候选历史仅 3 个月 → 无法做长周期 Regime×V1 统计
2. 沪深300 指数近期缺口（7/24-8/20）→ 近期 Regime 重建部分 UNKNOWN
3. 无 Historical ST → 无法做幸存者偏差补偿
4. 无完整历史 Portfolio → 无法做 Entry/Outcome 完整回放

## 18. No Production Changes

本阶段未修改任何生产策略 / V1 / 参数 / Regime 算法 / 交易规则。
仅审计 + trading_calendar 基础设施修复（Phase A）。

## 19. Next Research Gate

进行完整 Regime-Conditional V1 Research 需要：
1. 更长的 V1 候选历史（Historical Replay 或自然积累 ≥ 1 年）
2. 补齐沪深300 指数 K 线缺口
3. 明确 Historical ST 处理（或接受幸存者偏差并标记）
4. 建立 PIT Regime 重建脚本（RESEARCH_ONLY）

---

*Phase 8-G0 · Phase B · Regime×V1 Research Feasibility · 研究可行性审计（未改生产策略）*
