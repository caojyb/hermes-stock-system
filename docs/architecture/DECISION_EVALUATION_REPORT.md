# DECISION_EVALUATION_REPORT.md（Phase 7）

## 1. Dataset Definition
```yaml
dataset:
  production: 29
  shadow: 0
  legacy: 11
  counterfactual: 1
```

## 2. Data Quality
```yaml
data_quality:
  production_missing_decision_id: 0
  legacy_missing_decision_id: 11
  unknown_mae_mfe: 29
```

## 3. Production Results
```yaml
production_base_stats:
  N: 29
  win_rate: 100.0%
  avg_return: 16.28%
  median_return: 10.0%
  profit_factor: 0.0
  avg_holding_period: 0.0
  avg_mae: 0.0
  avg_mfe: 0.0
  max_drawdown: 0.0
```

## 4. Regime Results
所有 29 条 Production outcome 的 `entry_regime` = `UNKNOWN`（仿真测试未填充 Regime 字段）。
统计结果：
```yaml
by_regime:
  UNKNOWN:
    N: 29
    win_rate: 100.0%
    avg_return: 16.28%
    status: OK
```

## 5. Entry Results
Entry action 分层：
```yaml
by_action:
  BUY:
    N: 29
    win_rate: 100.0%
    avg_return: 16.28%
```

## 6. Candidate Score
当前 outcomes 中无 `candidate_score` 字段。
```yaml
candidate_score: DATA_INSUFFICIENT
```

## 7. Permission Value
```yaml
permission_evaluation:
  allowed_N: 29
  blocked_N: 0
  blocked_stats: DATA_INSUFFICIENT
```

## 8. Portfolio Gate Value
无 Portfolio Gate 阻断记录。
```yaml
portfolio_gate: DATA_INSUFFICIENT
```

## 9. Exit Results
```yaml
by_exit_reason:
  TAKE_PROFIT:
    N: 29
    avg_return: 16.28%
  UNKNOWN:
    N: 0
```

## 10. Position Sizing
未记录 `target_position` 分层数据。
```yaml
position_sizing: DATA_INSUFFICIENT
```

## 11. Decision vs Execution
无 slippage 字段。
```yaml
decision_execution_quality: DATA_INSUFFICIENT
```

## 12. NO_TRADE Value
Counterfactual 仅 1 条，不足统计。
```yaml
no_trade_value: DATA_INSUFFICIENT
```

## 13. HOLD / REDUCE / SELL
当前 outcomes 全部为 BUY → CLOSED，无 HOLD/REDUCE 记录。
```yaml
hold_reduce_sell: DATA_INSUFFICIENT
```

## 14. Regime Transition
entry_regime / exit_regime 均为 UNKNOWN。
```yaml
regime_transition: DATA_INSUFFICIENT
```

## 15. Time Stability
样本仅覆盖 2026-08-19。
```yaml
time_stability:
  yearly:
    2026:
      N: 29
      win_rate: 100.0%
  quarterly:
    2026-Q3:
      N: 29
      win_rate: 100.0%
```

## 16. Shadow Results
无 Shadow outcomes。
```yaml
shadow_results: DATA_INSUFFICIENT
```

## 17. Evidence
- V1 Production 29 笔全部盈利（win_rate = 100%）
- 全部通过 TAKE_PROFIT 退出
- MAE/MFE 均为 UNKNOWN（仿真数据未记录 excursion）
- 无任何 STOP_LOSS / TRAILING_STOP / MA20_EXIT 退出记录
- 无任何 NO_NEW_ENTRY / Portfolio Gate 阻断样本
- 无 Regime 分层数据

## 18. Hypotheses
- 当前 100% 胜率可能来自仿真数据偏差（小样本、无滑点、无冲击成本）
- MAE/MFE 缺失导致无法评估最大不利/有利波动
- 缺乏 STOP_LOSS 退出样本，无法评估止损机制有效性
- 缺乏真实 Regime 标签，无法评估市场环境适应性
- Candidate Score 字段缺失，无法评估评分单调性
- 需要积累更多真实 Decision/Outcome（含 Regime、 excursion、 slippage）才能得出统计显著结论

## 19. DATA_INSUFFICIENT
- Regime 分层：29 条全部 UNKNOWN
- Candidate Score：无字段
- Permission Counterfactual：0 条阻断
- Portfolio Gate：0 条阻断
- Position Sizing：无 target_position 分层
- Decision vs Execution：无 slippage
- NO_TRADE：1 条 counterfactual
- HOLD/REDUCE/SELL：0 条
- Regime Transition：29 条全部 UNKNOWN
- Shadow：0 条
- Exit Reasons：仅 TAKE_PROFIT（29 条）

## 20. Known Limitations
- 当前 outcomes 全部来自仿真测试（2026-08-19 单日）
- MAE/MFE 未填充（ excursion.status = UNKNOWN）
- entry_regime / exit_regime 未填充
- 无真实 slippage / execution quality 数据
- 无 Candidate Score 字段
- 无 Portfolio Gate 阻断记录
- 无 HOLD/REDUCE/SELL 样本
- 样本量不足以进行时间稳定性分析（仅单日）
- Shadow 策略未产生 outcomes
- Counterfactual 样本仅 1 条
