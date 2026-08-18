#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实仓人工执行确认（Phase 6.5）
==============================
用户在平安证券人工成交后，用此 CLI 回写 Execution Record。

用法：
  # 确认买入/卖出已成交
  python3 confirm_execution.py --decision <decision_id> --status EXECUTED \
      --price 10.35 --quantity 1000 [--action BUY] [--time 2026-08-18T10:30:00]

  # 未成交
  python3 confirm_execution.py --decision <decision_id> --status NOT_EXECUTED

  # 部分成交
  python3 confirm_execution.py --decision <decision_id> --status PARTIAL \
      --price 10.2 --quantity 500

  # 记录卖出(退出) → 生成 Outcome
  python3 confirm_execution.py --execution <execution_id> --exit --exit-price 9.2 \
      --exit-quantity 1000 --exit-reason STOP_LOSS

  # 查看 execution
  python3 confirm_execution.py --show <execution_id>
"""
import sys, argparse
sys.path.insert(0, '/home/caojy/.hermes/scripts/cron')
from decision import execution as ex


def main():
    p = argparse.ArgumentParser(description='真实仓人工执行确认')
    p.add_argument('--decision', help='decision_id')
    p.add_argument('--execution', help='execution_id（exit/show 用）')
    p.add_argument('--status', choices=['EXECUTED', 'PARTIAL', 'REJECTED', 'NOT_EXECUTED', 'PLANNED'])
    p.add_argument('--price', type=float, help='实际成交价')
    p.add_argument('--quantity', type=float, help='实际成交数量')
    p.add_argument('--time', help='成交时间')
    p.add_argument('--action', help='action 标签')
    p.add_argument('--exit', action='store_true', help='记录卖出')
    p.add_argument('--exit-price', type=float)
    p.add_argument('--exit-quantity', type=float)
    p.add_argument('--exit-reason', default='MANUAL_EXIT')
    p.add_argument('--exit-time')
    p.add_argument('--show', help='显示 execution')
    p.add_argument('--generate-outcome', action='store_true', help='从 execution 生成 outcome')
    a = p.parse_args()

    if a.show:
        e = ex.get_execution(a.show)
        print(e or f'execution 不存在: {a.show}')
        return
    if a.exit:
        if not a.execution:
            print('❌ --exit 需要 --execution'); return
        eid = ex.record_exit(a.execution, a.exit_price, a.exit_quantity,
                             a.exit_time, a.exit_reason)
        print(f'✅ 已记录退出 → execution {eid}')
        if a.generate_outcome:
            o = ex.build_outcome_from_execution(a.execution)
            if o:
                from decision import outcome_store as store
                store.save_outcome(o)
                print(f'✅ 已生成 Outcome {o.outcome_id} action={o.action} ret={o.actual.return_pct}')
            else:
                print('⚠️ 信息不充分，未生成 Outcome（不推算）')
        return
    if a.decision and a.status:
        eid = ex.confirm_manual_execution(a.decision, a.price or 0, a.quantity or 0,
                                          a.time or '', a.status, notes=f'action={a.action or ""}')
        print(f'✅ 已确认 execution: {eid} (decision={a.decision}, status={a.status})')
        return
    print('用法：python3 confirm_execution.py --help')


if __name__ == '__main__':
    main()
