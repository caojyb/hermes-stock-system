# Production Decision Evidence Review Framework（Phase 8-C）

## 1. Objective
建立"Production Decision Evidence Review Framework"，规定未来每一笔真实 Production Decision 完成生命周期后，系统应该如何区分 Decision 问题、Execution 问题、Data 问题、Portfolio / Risk 问题、Exit 问题、Strategy 问题；并建立事实 / 证据 / 假设三级分类，避免未来看到少量交易结果后立即改策略。

## 2. FACT / EVIDENCE / HYPOTHESIS
- FACT：由系统或真实执行数据直接确认的事实。
- EVIDENCE：由多个 FACT 支持的观察。
- HYPOTHESIS：不能由当前样本直接证明的解释，必须标注为 HYPOTHESIS。
禁止把 HYPOTHESIS 写成 FACT。

## 3. Decision Quality
记录系统当时决定了什么：action、symbol、planned_price、planned_quantity、candidate_score。

## 4. Execution Quality
记录实际执行偏离计划多少：actual_price、actual_quantity、execution_delay、slippage。必须与 Decision 分开归因。

## 5. Position Sizing Attribution
目标仓位和实际仓位是否一致：planned_quantity vs actual_quantity，由 position_sizing_quality 单独记录。

## 6. Exit Attribution
最终退出必须分类：STOP_LOSS / TAKE_PROFIT / TRAILING_STOP / MA20_EXIT / PORTFOLIO_RISK / MANUAL / FORCED / OTHER / UNKNOWN。并记录 exit_decision_id、exit_execution_id、position_id。禁止人工解释覆盖系统真实 exit_reason。

## 7. MAE / MFE Evidence
Production Outcome 必须记录 MAE、MFE，允许 UNKNOWN。形成 Excursion Evidence，但只能作为 EVIDENCE，不能直接推导"应该提前卖"。

## 8. Holding Period Evidence
记录 actual_entry_time、final_exit_time、holding_period_days。只能描述事实，禁止直接结论"持仓太久"。

## 9. Regime Evidence
每笔 Production Decision 保存 entry_regime、exit_regime，并记录 regime_transition。本阶段不做 Regime Performance Evaluation，只形成事实数据。

## 10. Permission Evidence
记录 permission_status、permission_reason_codes。只回答"当时系统是否允许交易"。

## 11. Portfolio Evidence
记录 portfolio_assessment、portfolio_risk_flags、drawdown、position_count、sector_exposure。只回答"当时组合风控是否按既定规则工作"。

## 12. NO_TRADE Evidence
未来所有 NO_TRADE 必须可以研究为什么没有买：至少记录 candidate、blocking_layer、reason_codes、market_regime、permission、portfolio、entry、candidate_score。NO_TRADE 不得被误统计为"系统没有产生 Decision"。

## 13. Counterfactual
NO_TRADE 的未来收益只能记为 COUNTERFACTUAL。禁止写成"系统错过了 X%"；后者属于 HYPOTHESIS / ATTRIBUTION。

## 14. Production Review Record
每个 CLOSED Production Outcome 生成 production_review_id，至少包含：outcome_id、decision_id、execution_id、position_id、review_time、facts、evidence、hypotheses、data_quality、attribution。Review 不覆盖原 Outcome；若判断变化，新建 Review Version。

## 15. Evidence Completeness
每笔 CLOSED Production Outcome 计算 EVIDENCE_COMPLETE。至少检查：Decision、Execution、Position、Exit、Outcome、Regime、Permission、Portfolio、planned/actual、exit_reason、MAE/MFE、holding_period、provenance。缺失时返回 PARTIAL，不能强制完整。

## 16. Observation vs Evaluation Ready
- PRODUCTION_OBSERVATION：已经真实发生。
- PRODUCTION_EVALUATION_READY：生命周期闭环并满足 Evaluation Gate。
- PRODUCTION_PARTIAL：真实发生，但关键数据缺失。
不能把 Partial 当 Ready。

## 17. Data Sufficiency vs Statistical Sufficiency
本阶段只定义 Data Sufficiency（complete outcomes、provenance completeness、execution completeness、regime completeness）。Statistical Sufficiency 以后单独定义；不要现在拍板"10 笔 / 20 笔 / 50 笔就算 Edge 有效"。

## 18. Daily Evidence Summary
每日 Observation Report 之外，可增加 Production Evidence Summary，只统计：decisions、executions、closed outcomes、partial outcomes、data gaps、execution gaps、reviewable outcomes、evidence completeness。现在不统计：win rate、Sharpe、alpha、Edge。

## 19. First Production Outcome Review
当第一笔真实 Production Outcome 出现时，系统必须能够自动检查：Decision → Execution → Position → Exit → Outcome → Review Record，并给出 EVIDENCE_COMPLETE 或 PRODUCTION_PARTIAL。不自动判断好坏。

## 20. Known Limitations
- 当前真实 Production Decision = 0，所有链路均通过 isolation test 验证。
- NO_TRADE counterfactual 基于候选票，不等于策略收益。
- Evidence Completeness 受数据源可用性影响；missing 数据不强制补全。
- 本阶段不评价 V1 Edge，不进入 Statistical Sufficiency。
