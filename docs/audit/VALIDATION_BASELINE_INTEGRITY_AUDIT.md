# Validation Baseline Integrity Audit（Phase 8-J0C）

> 日期：2026-08-26。只读审计，未修改任何数据。
> 唯一问题：2026-08-09 起的 Forward Validation 是否仍是"干净验证期"？

## 结论（先行）

```
VALIDATION_BASELINE_RECOMMENDATION = RESET_REQUIRED
CONTAMINATION_LEVEL = CONTAMINATED (VALUATION_LAYER_CONTAMINATION_ONLY)
RECOMMENDED_NEW_VALIDATION_START = 2026-08-27
OLD_VALIDATION_PERIOD 保留：2026-08-09 → 2026-08-26（PRE_FIX_LEGACY_RESULT，不删除）
V1 修改需求 = NO
```

**关键定性**：污染仅发生在估值层（cash/total_asset/return/drawdown）。
V1 的 Decision、Entry/Exit、逐笔盈亏分类、持仓周期等交易事实**未被污染**。

---

## 一、FIX_EFFECTIVE_TIMESTAMP（真实生效时间，非 commit date）

| 时点 | 事件 | 公式状态 |
|---|---|---|
| 2026-08-25 21:24 | commit 763c181（新 cash 公式入库） | 代码正确但未运行 |
| 2026-08-25 16:54 | 当日生产 cron（早于 commit） | **变体 bug 公式** |
| 2026-08-25 22:41 | 手动运行（commit 后） | 新公式 ✓（open_cost 含 27,000 边缘值） |
| **2026-08-26 16:53:39** | **J0B 后首个生产 cron** | **完全干净** ✓ |

首个「正确公式 + 干净输入 + 生产 cron」三者齐备的自然日 = **2026-08-26**。

## 二、VALIDATION_VALUATION_TIMELINE（逐日数值比对）

方法：对每行 portfolio_snapshots 的 recorded_cash 与三套公式逐一重算比对，
并用周备快照（simulation_20260816.db / 20260823.db）交叉证实历史行未被篡改。误差 <1 元。

| 日期 | recorded cash | recorded NAV | 实际使用公式 | 判定 |
|---|---|---|---|---|
| 07-31 | 907,791 | 1,000,000 | （validation 前基准） | LEGACY |
| 08-11 | 156,446 | 659,035 (-34.10%) | TOTAL+realized−open_cost，但输入含**未修复的 7/29 批次**（sell_amount 缺失/profit 造假） | 污染 |
| 08-12 | 156,446 | 664,723 | 同上 | 污染 |
| 08-13 | 154,079 | 655,326 | 同上 | 污染 |
| 08-14 | 156,329 | 650,773 | 同上 | 污染 |
| 08-17 | 156,329 | 648,586 (-35.14%) | 同上（23:27 手动重跑） | 污染 |
| 08-18 | 306,831 | 798,486 | **旧公式 TOTAL−Σbought+Σsold**（精确匹配） | 污染 |
| 08-19 | 415,643 | 779,567 | 旧公式精确匹配 | 污染 |
| 08-20 | 415,643 | 785,013 | 旧公式精确匹配 | 污染 |
| 08-21 | 437,927 | 782,821 | 旧公式精确匹配 | 污染 |
| 08-24 | 2,218,597 | **2,267,248 (+126.72%)** | **变体 bug：cash=TOTAL+Σsell−open_cost**——买入本金从未扣除 | 严重污染 |
| 08-25 | 754,471 | 781,471 (-21.85%) | 16:54 cron 变体 bug；22:41 手动已用新公式（open_cost 含 27,000 边缘值） | 部分污染 |
| **08-26** | **781,471** | **781,471 (-21.85%)** | **正确公式 ✓**（TOTAL+realized=781,471.12，open_cost=0） | 干净 |

### 关键量化

- **受影响天数**：11 天（8/11–8/25），受影响 NAV 记录 11 条
- **NAV 扭曲幅度**：
  - 低估期（8/11–8/17）：recorded -34~-35% vs 当时真实约 -18% → 低估 ~127,672 元
  - 高估日（8/24）：+126.72% vs 真实约 -22% → **虚增 ~148.6pp**
- **假回撤峰值**：max_drawdown=65.53% 由 8/24 虚假峰值 2,267,248 制造，非真实回撤
- **真实当前 NAV**：781,471.12 = 1,000,000 + realized(-218,528.88)，即 **-21.85%**（8/26 已如实落库）

## 三、三层结果（互不覆盖，均保留）

| 层 | 内容 |
|---|---|
| PRE_FIX_LEGACY_RESULT | 2026-07-29 ~ 08-17 全部记录（含 7/29 批次数据问题与 -34% 口径） |
| RAW_VALIDATION_RESULT | 2026-08-09 ~ 08-26 数据库实际记录（11 条污染 NAV + 32 笔 trades 事实） |
| CLEAN_POST_FIX_RESULT | 仅 2026-08-26 一条干净快照；现金 781,471.12，持仓 0 |

## 四、"策略结果 vs 账户统计错误"分离

| 维度 | 受影响？ | 依据 |
|---|---|---|
| Decision count | 否 | trades 无 decision_id（全 LEGACY），决策事实独立于 cash 计算 |
| Entry / Exit 时机 | 否 | buy_date/sell_date 为原始事实 |
| Trade count | 否 | 22 笔 validation 期内平仓记录完整 |
| Win/Loss 分类 | 否 | profit_pct 按单笔 sell/buy 价计算，与账户 cash 无关 |
| Holding period | 否 | 同上 |
| MAE/MFE | 不适用 | validation 期无 Production Outcome（=0） |
| Cash | **是** | 三种错误公式轮番使用 |
| Total asset / Return | **是** | -35%~+127% 区间波动均为计算伪影 |
| Drawdown | **是** | 65.53% 为假峰值产物 |

→ 定性：**VALUATION_LAYER_CONTAMINATION_ONLY**

## 五、GATE_INTEGRITY（PROJECT.md 预设 Gate）

| Gate | 判定 | 说明 |
|---|---|---|
| ≥20 trading days | COUNT VALID / NAV CURVE CONTAMINATED | 交易日计数不受影响；但净值曲线不可作为评估依据 |
| ≥10 trades | VALID (as count) | 22 笔平仓事实真实可用 |
| win rate ≥50% | PARTIAL VALID | 当前样本 10W/12L=45.5%，且 validation 期内**新开仓仅 2 笔**（其余为 7/29–8/6 legacy 持仓平仓），不代表 V1 在验证期的选股产出 |
| max drawdown ≤15% | CONTAMINATED | 65.53% 是假峰值产物，无法与 Gate 对比 |

## 六、Reset 判定与建议

**RESET_REQUIRED** —— 依据：

1. 8/9 以来不存在任何一个自然日同时满足：正确现金公式 + 干净输入数据 + 生产 cron 运行
2. return/drawdown 两个核心 Gate 指标被污染到无法与预设 Gate 对比（区间 -35%~+127%）
3. 无法可靠重算历史（部分历史 sell_amount 曾被人工修复过，自动重放会引入二次失真 → RECALCULATION_LIMITED）

**Reset 定义（锁死，不含任何删除操作）**：

```
OLD_VALIDATION_PERIOD  = 2026-08-09 → 2026-08-26   （保留为 PRE_FIX_LEGACY_RESULT）
NEW_VALIDATION_START   = 2026-08-27                （建议，需用户确认后生效）
NEW_VALIDATION_END     = 2026-09-05 或 满20交易日（以先到者为准，需用户裁定）
初始状态                = 现金 781,471.12、持仓 0（8/26 收盘事实）
```

**为什么是 8/27 有证据支持**：不是主观选择——8/26 是首个完全干净运行日，但其快照在当日
16:53 已写入且持仓清零；从 8/27 起 V1 从零持仓开始建仓，每一笔都经 J0B 后代码 +
统一 Decision 链产生，天然构成干净的起点。禁止提前到 8/26（当日无新决策）或推后（无依据）。

⚠️ 本审计不执行 reset。reset 生效需用户明确指令，且届时仅需：
(a) PROJECT.md 更新 validation start；(b) 可选地为 8/26 快照打 baseline 标记。无需删任何数据。

## 七、最终回答（20 问）

1. 8/9 是否干净起点？**否**（首条快照 8/11 即已污染）
2. fix 真实生效时间？**2026-08-26 16:53:39**（首个干净生产 cron；commit 时间 8/25 21:24 不等于生效）
3. 8/9 后有多少记录用旧逻辑？**11 条 NAV 记录全部受影响**（三种不同错误形态轮番出现）
4. 多少天受影响？**11 天**（8/11–8/25）
5. 多少笔交易受影响？**交易事实 0 笔受影响**；账户统计覆盖全部 32 笔的汇总层
6. Decision count 受影响？**否**
7. Trade count 受影响？**否**
8. Win rate 受影响？**否**（逐笔分类真实；但样本结构见 §五）
9. Return 受影响？**是**（-35%~+127% 均为伪影；真实 -21.85%）
10. Drawdown 受影响？**是**（65.53% 为假峰值）
11. 可继续使用的指标：decision/trade 计数、entry/exit 事实、win/loss 分类、holding period
12. 必须丢弃/重算的指标：return 序列、drawdown、total_asset 曲线（8/26 起重新累积）
13. 污染级别：**CONTAMINATED**（VALUATION_LAYER_CONTAMINATION_ONLY）
14. Reset 建议：**RESET_REQUIRED**
15. 推荐新起点：**2026-08-27**
16. 日期依据：8/26 = 首个"正确公式×干净输入×生产 cron"日，且当日持仓清零，8/27 起所有新交易均走 J0B 后统一决策链——纯证据推导
17. Gate 有效性：20天=count valid；10笔=valid；胜率=partial valid；回撤=contaminated（见 §五）
18. 需要修改 V1？**NO**
19. 需要修改 Strategy Selector？**NO**（保持 OFF）
20. 需要修改 Regime？**NO**

## 八、证据与测试

- 逐日数值重放脚本输出（新旧公式 vs recorded cash，误差<1元）已在本审计执行
- 周备份交叉验证：simulation_20260816.db / 20260823.db 中历史快照与主库一致 → 无事后篡改
- 只读语义测试 `decision/test_j0c_validation_audit.py`（10项：pre/post-fix 行识别、期间切分确定性、无数据变更断言、Gate 分类、reset 建议确定性）
- JSON 证据：`reports/validation_baseline_integrity.json`

## 九、停止声明

本阶段未修改 V1 / Regime / Selector / 任何 simulation 数据。
未自动 reset。VALIDATION_BASELINE_RECOMMENDATION = **RESET_REQUIRED**，
等待用户明确指令后才可执行（且执行动作仅为更新 PROJECT.md 日期 + 打标，不删除数据）。
