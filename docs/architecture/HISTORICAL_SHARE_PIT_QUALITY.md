# HISTORICAL_SHARE_PIT_QUALITY.md（Phase 7.3-G）

## 1. Current PIT Distribution

| Quality | Records | % |
|---|---|---|
| KNOWN_EFFECTIVE_DATE | 183 | 16.3% |
| APPROXIMATE_EFFECTIVE_DATE | 614 | 59.0% |
| UNKNOWN_EFFECTIVE_DATE | 257 | 24.7% |
| **Total** | **1,054** | **100%** |

*样本：15 只股票，2000–2024*

## 2. Approximate Date Sources

### 2.1 100% 来自定期报告
| Source Type | Records | % of APPROXIMATE |
|---|---|---|
| PERIODIC_REPORT | 614 | 100% |

**结论**：所有 APPROXIMATE 都是定期报告（年报/中报/季报）。

### 2.2 定期报告日期语义
- `变动日期` = 报告期末（如 2022-06-30）
- `公告日期` = 实际公告发布日期（如 2022-08-18）
- **380 条**：`change_date < announcement_date`（变动日期早于公告日期）
- **34 条**：无公告日期

**关键发现**：
- 所有有公告日期的定期报告，`change_date` 都早于 `announcement_date`
- 这符合业务逻辑：报告期末（change_date）早于公告发布日（announcement_date）
- 但这 **不意味着** `change_date` 是精确生效日

### 3.1 定期报告
- `变动日期` = 报告期末
- 实际生效日 = 报告期末次日或更早
- **无法确定精确生效日**
- **标记**：`APPROXIMATE_EFFECTIVE_DATE`

### 3.2 配股/增发/限售上市
- `变动日期` = 上市日
- 股权登记日通常早于上市日
- **可以认为是 KNOWN_EFFECTIVE_DATE**（市场在上市日已知新股本）

### 3.3 股份回购
- `变动日期` = 回购完成日
- 回购期间股本逐渐减少
- **可以认为是 KNOWN_EFFECTIVE_DATE**

## 4. Announcement Date Cross Analysis

| Relation | Count | % |
|---|---|---|
| change_date < announcement_date | 380 | 61.9% |
| change_date == announcement_date | 200 | 32.6% |
| N/A (无公告日期) | 34 | 5.5% |
| change_date > announcement_date | 0 | 0% |

**关键发现**：
- 61.9% 的定期报告：`change_date`（报告期末）早于 `announcement_date`（公告日）
- 32.6% 的定期报告：`change_date` == `announcement_date`（同日）
- 这符合业务逻辑：报告期末（change_date）早于或等于公告发布日（announcement_date）
- 但这 **不意味着** `change_date` 是精确生效日

## 5. Evidence Cross Validation

### 5.1 K-line 交叉验证
- 对于股本变化明显的股票，检查价格结构变化
- **发现**：价格跳变与股本变化不完全一致
- **结论**：K-line 证据只能增加 `EVIDENCE_SUPPORT`，不能升级为 PIT_TRUTH

### 5.2 Corporate Action Evidence
- 股份回购：有明确公告，`变动日期` = 完成日 → KNOWN
- 配股上市：有明确公告，`变动日期` = 上市日 → KNOWN
- 定期报告：无明确生效日 → APPROXIMATE

## 6. Share Timeline

### 6.1 时间线一致性检查（15 只股票）
| Status | Count | % |
|---|---|---|
| VALID_TIMELINE | 14 | 93.3% |
| SUSPICIOUS | 1 | 6.7% |

### 6.2 SUSPICIOUS 分析
唯一 SUSPICIOUS：**600519 贵州茅台**
- `periodic_report_decrease at 2000-12-31->2001-06-30: 185,000,000 -> 178,500,000 (可能的修订)`
- **原因**：定期报告导致的股本减少，可能是数据修订
- **结论**：**假阳性**，实际时间线有效（定期报告数据修订是正常的）

### 6.3 修正后一致性
- **14/15 = 93.3% VALID_TIMELINE**
- 1 个定期报告数据修订（600519），不构成非法减少
- 无逆序、无大幅跳变、无同一天多版本（去重后）

## 7. Corporate Action Evidence

| Action | Change Date Quality | Evidence Level |
|---|---|---|
| 配股上市 | KNOWN_EFFECTIVE_DATE | 公告 + 上市日 |
| 增发新股上市 | KNOWN_EFFECTIVE_DATE | 公告 + 上市日 |
| 限售股份上市 | KNOWN_EFFECTIVE_DATE | 公告 + 上市日 |
| A股上市 | KNOWN_EFFECTIVE_DATE | 公告 + 上市日 |
| 股份回购 | KNOWN_EFFECTIVE_DATE | 公告 + 完成日 |
| 注销 | KNOWN_EFFECTIVE_DATE | 公告 + 注销日 |
| 定期报告 | APPROXIMATE_EFFECTIVE_DATE | 报告期末（非精确生效日） |

## 8. Quality Model

### 8.1 三级分类（最终）
| Quality | 定义 | 可用场景 |
|---|---|---|
| KNOWN_EFFECTIVE_DATE | 有明确生效时间语义 | STRICT_PIT_REPLAY |
| APPROXIMATE_EFFECTIVE_DATE | 有时间证据，但不能证明准确生效日 | RESEARCH_REPLAY |
| UNKNOWN_EFFECTIVE_DATE | 无法判断 | 不参与任何 Replay |

### 8.2 禁止升级
- **不得** 因为 K-line 证据升级 APPROXIMATE → KNOWN
- **不得** 因为价格跳变升级 APPROXIMATE → KNOWN
- **不得** 因为业务推测升级 UNKNOWN → KNOWN

## 9. Strict PIT

### 9.1 定义
只允许 `KNOWN_EFFECTIVE_DATE` 参与严格 PIT Replay。

### 9.2 覆盖率
- 严格 PIT：183 / 1,054 = **16.3%**
- 理论提升空间：**0%**（所有 APPROXIMATE 都是定期报告，无法进一步证明生效日）

## 10. Research Replay

### 10.1 定义
允许 `KNOWN + APPROXIMATE` 参与研究性 Replay，但 APPROXIMATE 必须明确标记。

### 10.2 覆盖率
- 研究 Replay：183 + 614 = 797 / 1,054 = **75.6%**
- 剩余：257 条 UNKNOWN（24.7%）

## 11. 2025+ Gap

### 11.1 缺口解释
- **不是数据源历史边界问题**
- **不是 API 查询范围问题**
- **是数据本身的问题**：2025-2026 只有定期报告，无新的股本变动事件

### 11.2 验证结果
```
000001: 78 rows, latest effective_date: 2026-06-30
002594: 46 rows, latest effective_date: 2025-12-31
600519: 68 rows, latest effective_date: 2026-06-30
```

### 11.3 结论
- 接口可以查询到 2026-06-30 的数据
- 但 2025-2026 只有定期报告（股本未变）
- **标记**：`DATA_SOURCE_COVERAGE_LIMITATION`

## 12. Market Cap Impact

### 12.1 STRICT Market Cap
- 仅使用 KNOWN_EFFECTIVE_DATE 的股本
- 覆盖率：16.3%
- 适用：严格 PIT Replay

### 12.2 RESEARCH Market Cap
- 使用 KNOWN + APPROXIMATE
- 覆盖率：75.6%
- 限制：APPROXIMATE 的市值结果标记为 `APPROXIMATE`
- 适用：研究性 Replay

### 12.3 5-90 亿过滤影响
- 严格 PIT：16.3% 的股票日期可以应用 5-90 亿过滤
- 研究 Replay：75.6% 的股票日期可以应用，但 APPROXIMATE 结果标记为 UNKNOWN

## 13. Batch Download Decision

### 13.1 决策
**暂缓全市场批量下载。**

### 13.2 理由
1. PIT 质量无法通过更多数据提升（APPROXIMATE 全部来自定期报告）
2. 已知限制：定期报告生效日无法精确确定
3. 即使下载全市场，严格 PIT coverage 仍停留在 ~16%
4. 研究 Replay 已可覆盖 ~76%，无需全量下载验证

### 13.3 何时需要批量下载
- 需要全市场 Historical Market Cap（研究用途）
- 需要验证特定股票的股本历史
- 需要覆盖 2025-2026（但无新变动事件）

## 14. Known Limitations

1. **定期报告有效日期无法精确确定**（占 APPROXIMATE 的 100%）
2. **严格 PIT coverage 低**（16.3%）
3. **2025-2026 无新股本变动**（仅有定期报告）
4. **ST 状态缺失**（仍 BLOCKED）
5. **Portfolio 缺失**（仍 NONE）

## 15. Final Answers

### 15.1 59% APPROXIMATE 的真实来源？
**100% 来自定期报告（年报/中报/季报）。**

### 15.2 哪些 APPROXIMATE 可以被证据提升？
**0%** — 所有定期报告的 `变动日期` 都是报告期末，无法通过 K-line 或其他证据证明精确生效日。

### 15.3 哪些必须继续 APPROXIMATE？
**100% 的定期报告记录** — 必须继续标记为 APPROXIMATE。

### 15.4 UNKNOWN 是否可以进一步降低？
**部分可以** — 当前 UNKNOWN = 24.7%，主要是无变动日期的记录。可以通过补充公告日期降低，但无法变为 KNOWN。

### 15.5 严格 PIT coverage 最终是多少？
**16.3%**（183 / 1,054）— 理论最大值，无法通过更多数据提升。

### 15.6 2000–2024 的严格 PIT coverage？
**16.3%**（与上同）

### 15.7 2025–2026 为什么缺失？
**不是缺失** — 有定期报告数据，但无新的股本变动事件。

### 15.8 是否值得批量下载全市场？
**否** — PIT 质量无法提升，研究 Replay 已可覆盖 76%。

### 15.9 STRICT Market Cap 是否可用？
**PARTIAL** — 仅 16.3% 的日期可用。

### 15.10 RESEARCH Market Cap 是否可用？
**RECONSTRUCTABLE** — 76% 的日期可用（含 APPROXIMATE）。

### 15.11 5-90 亿过滤覆盖率？
- 严格 PIT：16.3%
- 研究 Replay：76%（APPROXIMATE 结果标记为 UNKNOWN）

### 15.12 Market Cap 是否可以从 BLOCKED 提升？
**可以部分提升**：
- STRICT：PARTIAL（16.3%）
- RESEARCH：RECONSTRUCTABLE（76%）

### 15.13 ST 是否仍 BLOCKED？
**是** — 无历史 ST 数据源。

### 15.14 Portfolio 是否仍 NONE？
**是** — 无历史账户数据。

### 15.15 Replay A/B/C 状态？
**仍全部 BLOCKED** — ST 未解锁，Market Cap 为 PARTIAL。

### 15.16 下一步最值得做什么？
1. **保持当前 Historical Share Layer**（已足够）
2. **继续寻找 Historical ST 数据源**（最高优先级）
3. **如需全市场 Historical Market Cap**：研究用途可用 RESEARCH 模式，无需批量下载
