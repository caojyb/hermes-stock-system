# Phase 8-K1 Closeout — Stop-Loss Snapshot Persistence Hardening

> Baseline: hermes-stock-phase-8k0 / 5fbd618 → 本阶段 tag: hermes-stock-phase-8k1
> 日期：2026-08-26

## 一、Root Cause 调查（STEP 1-2）

复现矩阵（position_stop_loss_alert.py，全部真实运行）：

| 运行方式 | 快照落盘 | 备注 |
|---|---|---|
| 系统 python3.12，cwd=cron | ✅ 10 | |
| venv python3.13，cwd=cron | ✅ 10 | |
| cron sanitized env + venv python | ✅ 10 | build_subprocess_env 完整复刻 |
| systemd unit env + 窄 PATH | ❌ 0 | **lark-cli not found**（PATH 无 ~/.npm-global/bin）→ Bitable 读取失败 → 无决策产生 |
| systemd 完整 PATH + venv python | ✅ 10 | |
| runpy bootstrap 方式 | （等价于直接运行） | |

结论：所有可复刻的环境组合均成功。真实 cron 三连败的精确触发条件无法在离线复现中重现
（怀疑方向：gateway 长驻进程的瞬时环境/资源状态，如当天早上的 lark-cli 偶发失败、
或写入时异常被旧版 except 吞掉——9:35 版本代码与当前一致但输出无 WARN 无法回溯）。

**ROOT_CAUSE = UNRESOLVED（env-level）**
→ 因此实施 persistence self-check：无论根因是什么，只要写失败必然被发现并醒目告警。

## 二、修改内容（OLD / FIX / UNCHANGED）

### decision/snapshot_verify.py（新增）
- `verify_decision_snapshot()`：文件存在/JSON可解析/decision_id一致/symbol/action/timestamp 存在
- `persist_with_verification()`：canonical writer(save_snapshot) → verify → 失败重试(仅写,≤2次)
  → 幂等(PERSISTED_EXISTING) → 全败返回 FAILED
- `format_persistence_failure()`：🚨 FINAL DECISION PERSISTENCE FAILED 🚨 + DECISION_PERSISTENCE_FAILED 标记

### position_stop_loss_alert.py（两处 wiring）
- OLD：`snap_mod.save_snapshot(dec)` / `save_snapshot(...)` 后无任何校验；失败静默或仅 [WARN]
- FIX：
  - build_position_decision 内：save → persist_with_verification → FAILED 时打印醒目告警块
  - run_decision 内：逐决策自校验 + 汇总 `⚠️ DECISION_PERSISTENCE_FAILED xN`
- 顺序锁定：Decision → Snapshot → Verify → (Delivery 在 main 中后置) ✅
- UNCHANGED：DecisionEngine.decide() 语义、decision_id、STOP_LOSS/TRAILING_STOP 触发条件、
  Feishu 文案格式、HOLD 静默逻辑 —— 零改动

### decision/test_daily_contract.py（测试工程修复）
- autouse fixture 直接赋值 `_ddc.SNAP_DIR` 不恢复 → 污染全局，导致全量 suite 中
  K1 reconciliation 测试读到空目录。加 teardown 恢复原值。

## 三、测试

| 项 | 结果 |
|---|---|
| 新增 K1 测试（decision/test_k1_persistence.py） | 12 项：persist/verify/malformed/partial-write/id-mismatch/retry保id/幂等existing/全败FAILED/failure消息标记/daily reconciliation/no-executed |
| 全量 decision suite | **421 passed / 0 failed**（387 + 12 K1 + 22 K0 等） |

## 四、Production-equivalent Safe Run（STEP 6-7）

```
stop-loss run: exit=0
[PERSIST] PERSISTED ×10（每只决策独立验证）
URGENT decisions = 10 (SELL 8, HOLD 2)
Daily loaded     = 10 (SELL 8)
missing_from_daily = 0
RECONCILIATION = PASS（urgent_ids ⊆ daily_ids，SELL count 相等）
EXECUTED=0 | Production Outcome=0 | AUTO_TRADING=OFF
```

## 五、Runtime Readback

```
STOP LOSS: detected=10 final_decision_count=10
PERSISTENCE: attempted=10 succeeded=10 failed=0 retried=0 existing=0 error=none
RECONCILIATION: urgent=10 daily=10 missing_from_daily=0
DELIVERY: sent=0(safe run不投递) blocked=0 duplicate_suppressed=n/a
EXECUTION: planned=0 executed=0 partial=0
OUTCOME: production_outcome_count=0
SYSTEM: runtime_status=OK
```

## 六、20 问速答

1. 根因？**UNRESOLVED（env-level）**——所有可复刻组合均成功；已布防 self-check 兜底
2. 手动可以/cron 不可以？疑似 gateway 瞬时环境状态；无法离线复现
3. canonical writer？`decision/snapshot.save_snapshot`（唯一，未新建第二套）
4. snapshot 先于 Delivery？**是**（顺序锁定）
5. self-check 可靠？**是**（存在/可解析/id一致/字段齐全 四层）
6. failure 可发现？**是**（🚨醒目输出，不再静默）
7. fail-safe？**是**（不改action/不改id/不伪造）
8. retry 保持同一 decision_id？**是**（测试锁定）
9. duplicate 幂等？**是**（PERSISTED_EXISTING，单文件）
10. SELL 全部可回溯？**是**（本次 safe run 8/8）
11. Daily 能读到？**是**
12. Urgent/Daily 同 id？**是**（missing=0）
13. 第二 Final Owner？**无**
14. 新 Decision 产生？**否**（safe run 决策为当日真实持仓检查，未执行）
15. EXECUTED？**0**
16. Production Outcome？**0**
17. Auto Trading OFF？**是**
18. V1/Regime/Engine 规则改动？**零**
19. 还有 HIGH task-chain gap？**H-1 已布防**（根因未定但失真必被检测+告警）；其余见 K0 清单
20. K1 COMPLETE？**是**

K1_STATUS = COMPLETE。立即停止，不进入 K2。
