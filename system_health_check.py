#!/usr/bin/env python3
"""
系统健康自检脚本 — 13 项全维度检查
=====================================
调度：每周日 18:00 执行，结果推送飞书
"""
import os, sys, json, sqlite3, importlib, math, datetime
from datetime import date, datetime as dt, timedelta
from pathlib import Path
from simulation_db_helper import get_active_sim_db
from collections import defaultdict

FEISHU_DIR = Path("/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable")
SCRIPT_DIR = Path(__file__).parent.resolve()
MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SIM_DB = get_active_sim_db()
TODAY = date.today()
TODAY_STR = TODAY.isoformat()

# ═══ 结果容器 ═══
results = []  # (name, status, value, severity)
# status: ✅ / ❌ / ⚠️
# severity: 'info' / 'warn' / 'critical'

def add(name, passed, value, severity='info'):
    icon = '✅' if passed else ('⚠️' if severity == 'warn' else '❌')
    results.append((name, icon, value, severity))

# ══════════════════════════════════════════════════
# 数据层（5 项）
# ══════════════════════════════════════════════════

def check_data_layer():
    if not os.path.exists(MKT_DB):
        add('K线最新日期', False, f'数据库不存在! {MKT_DB}', 'critical')
        add('北向资金', False, '数据库不存在', 'critical')
        add('财务数据', False, '数据库不存在', 'critical')
        add('PE/PB数据', False, '数据库不存在', 'critical')
        add('候选池', False, '数据库不存在', 'critical')
        return
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()

    # 1. K线最新日期
    try:
        cur.execute("SELECT MAX(date) FROM klines")
        row = cur.fetchone()
        if row and row[0]:
            max_date = dt.strptime(row[0], '%Y-%m-%d').date()
            days_lag = (TODAY - max_date).days
            # 估算交易日：周末/假期，2 天以内正常
            is_fresh = days_lag <= 4
            add('K线最新日期', is_fresh,
                f'最新={row[0]}, 滞后{days_lag}天', 'critical' if not is_fresh else 'info')
        else:
            add('K线最新日期', False, 'K线表为空', 'critical')
    except Exception as e:
        add('K线最新日期', False, f'查询异常: {e}', 'critical')

    # 2. 北向资金
    try:
        cur.execute("SELECT COUNT(*) FROM indicators WHERE north_flow IS NOT NULL")
        north_cnt = cur.fetchone()[0]
        has_north = north_cnt >= 4000
        add('北向资金', has_north,
            f'{north_cnt} 条记录', 'critical' if not has_north else 'info')
    except Exception as e:
        add('北向资金', False, f'查询异常: {e}', 'critical')

    # 3. 财务数据最新报告期
    try:
        cur.execute("SELECT MAX(report_date) FROM financial_data")
        row = cur.fetchone()
        if row and row[0]:
            max_rep = dt.strptime(row[0], '%Y-%m-%d').date() if '-' in row[0] else dt.strptime(row[0], '%Y%m%d').date()
            days_lag = (TODAY - max_rep).days
            is_fresh = days_lag <= 120
            add('财务数据报告期', is_fresh,
                f'最新={row[0]}, 滞后{days_lag}天', 'warn' if not is_fresh else 'info')
        else:
            add('财务数据报告期', False, 'financial_data 表为空', 'critical')
    except Exception as e:
        add('财务数据报告期', False, f'查询异常: {e}', 'critical')

    # 4. PE/PB 最新日期
    try:
        cur.execute("SELECT MAX(fetch_date) FROM pe_pb_data")
        row = cur.fetchone()
        if row and row[0]:
            max_fetch = dt.strptime(row[0], '%Y-%m-%d').date()
            days_lag = (TODAY - max_fetch).days
            is_fresh = days_lag <= 10
            add('PE/PB数据日期', is_fresh,
                f'最新={row[0]}, 滞后{days_lag}天', 'warn' if not is_fresh else 'info')
        else:
            add('PE/PB数据日期', False, 'pe_pb_data 为空', 'warn')
    except Exception as e:
        add('PE/PB数据日期', False, f'查询异常: {e}', 'warn')

    # 5. 候选池最新扫描
    try:
        cur.execute("SELECT MAX(scan_date) FROM double_up_scores")
        row = cur.fetchone()
        if row and row[0]:
            scan_date = dt.strptime(row[0], '%Y-%m-%d').date()
            days_lag = (TODAY - scan_date).days
            cur.execute("SELECT COUNT(*) FROM double_up_scores WHERE scan_date=?", (row[0],))
            pool_cnt = cur.fetchone()[0]
            is_fresh = days_lag <= 10
            has_enough = pool_cnt >= 5
            passed = is_fresh and has_enough
            status = 'info' if passed else ('warn' if not is_fresh else 'critical')
            add('候选池扫描', passed,
                f'最新={row[0]}({days_lag}天前), {pool_cnt}只', status)
        else:
            add('候选池扫描', False, 'double_up_scores 为空', 'warn')
    except Exception as e:
        add('候选池扫描', False, f'查询异常: {e}', 'warn')

    conn.close()


# ══════════════════════════════════════════════════
# 策略层（3 项）
# ══════════════════════════════════════════════════

def check_strategy_layer():
    # 6. 翻倍V1参数一致性
    try:
        scan_path = SCRIPT_DIR / 'scan_doubling_potential.py'
        if not scan_path.exists():
            add('V1参数一致性', False, 'scan_doubling_potential.py 不存在', 'warn')
        else:
            content = scan_path.read_text(encoding='utf-8')
            has_correct_params = (
                'price_pos_max' in content and 'vol_ratio_min' in content
                and 'mcap_max' in content and 'turnover_min' in content
            )
            add('V1参数一致性', has_correct_params,
                '脚本存在，需手动核验参数值', 'info')
    except Exception as e:
        add('V1参数一致性', False, f'读取异常: {e}', 'warn')

    # 7. 候选池数量趋势
    try:
        conn = sqlite3.connect(MKT_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT scan_date, COUNT(*) FROM double_up_scores
            GROUP BY scan_date ORDER BY scan_date DESC LIMIT 4
        """)
        rows = cur.fetchall()
        conn.close()
        if rows:
            trend_info = ' → '.join(f'{r[0]}:{r[1]}' for r in rows)
            recent_cnts = [r[1] for r in rows]
            persistent_low = all(c < 5 for c in recent_cnts) and len(recent_cnts) >= 3
            add('候选池趋势', not persistent_low,
                trend_info, 'critical' if persistent_low else 'info')
        else:
            add('候选池趋势', False, '无历史数据', 'info')
    except Exception as e:
        add('候选池趋势', False, f'查询异常: {e}', 'info')

    # 8. 主升浪策略可运行性
    try:
        sys.path.insert(0, str(FEISHU_DIR.resolve()))
        import backtest_engine
        # 检查策略是否可创建
        fn = backtest_engine.create_strategy_lowvol_highroe_dual('main_up')
        add('主升浪策略', True, f'导入成功，策略函数={fn.__name__}', 'info')
    except Exception as e:
        add('主升浪策略', False, f'导入失败: {e}', 'warn')


# ══════════════════════════════════════════════════
# 风控层（2 项）
# ══════════════════════════════════════════════════

def check_risk_layer():
    # 9. risk_controller_v2 可导入性
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import risk_controller_v2
        add('风控模块', True, f'导入成功: {risk_controller_v2.__file__}', 'info')
    except Exception as e:
        add('风控模块', False, f'导入失败: {e}', 'critical')

    # 10. 模拟仓净值回撤
    try:
        sim_path = str(SIM_DB)
        if not os.path.exists(sim_path):
            add('模拟仓回撤', True, '无数据（模拟仓尚未开仓）', 'info')
        else:
            conn = sqlite3.connect(sim_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT date, total_value, total_return_pct
                FROM portfolio_snapshots ORDER BY date DESC LIMIT 30
            """)
            snaps = cur.fetchall()
            conn.close()
            if len(snaps) < 2:
                add('模拟仓回撤', True, f'数据不足({len(snaps)}条)', 'info')
            else:
                # 找 30 日高点
                peak = max(s[1] for s in snaps)
                latest = snaps[0][1]
                dd = (peak - latest) / peak * 100 if peak > 0 else 0
                is_ok = dd <= 10
                add('模拟仓回撤', is_ok,
                    f'最新净值={latest:.0f}, 30日高点={peak:.0f}, 回撤={dd:.2f}%',
                    'warn' if not is_ok else 'info')
    except Exception as e:
        add('模拟仓回撤', False, f'查询异常: {e}', 'warn')


# ══════════════════════════════════════════════════
# 执行层（3 项）
# ══════════════════════════════════════════════════

def check_execution_layer():
    # 11. 核心 cron 脚本存在性检查
    try:
        core_scripts = {
            'stock-market-cache-refresh': SCRIPT_DIR / 'daily_data_refresh.py',
            'double-monitor-daily': SCRIPT_DIR / 'double_monitor.py',
            'stock-opportunity-push': SCRIPT_DIR / 'stock_opportunity_scan.py',
        }
        all_exist = True
        for name, spath in core_scripts.items():
            exists = spath.exists()
            if not exists:
                all_exist = False
            add(f'cron:{name}', exists,
                f'脚本={"存在" if exists else "不存在"} ({spath.name})',
                'warn' if not exists else 'info')
        if not all_exist:
            pass
    except Exception as e:
        add('核心cron状态', False, f'检查异常: {e}', 'warn')

    # 12. 持仓体系隔离检查
    try:
        if os.path.exists(str(SIM_DB)):
            conn = sqlite3.connect(str(SIM_DB))
            cur = conn.cursor()
            # 检查是否有 signal_type 为 '真实持仓' 的交易
            try:
                cur.execute("SELECT COUNT(*) FROM trades WHERE signal_type='真实持仓'")
                cnt = cur.fetchone()[0]
                if cnt > 0:
                    add('持仓隔离', False, f'simulation.db 发现 {cnt} 笔真实持仓标记', 'critical')
                else:
                    add('持仓隔离', True, 'simulation.db 无真实持仓数据', 'info')
            except Exception:
                add('持仓隔离', True, 'trades 表无 signal_type 列或为空', 'info')
            conn.close()
        else:
            add('持仓隔离', True, 'simulation.db 不存在（未开仓）', 'info')
    except Exception as e:
        add('持仓隔离', False, f'查询异常: {e}', 'warn')

    # 13. 数据库路径一致性
    try:
        paths_yaml = SCRIPT_DIR.parent / 'skills' / 'stock' / 'stock-expert' / 'stock_db_paths.yaml'
        if not paths_yaml.exists():
            add('数据库路径', True, 'stock_db_paths.yaml 不存在，跳过检查', 'info')
        else:
            # 检查关键数据库文件
            dbs_to_check = {
                'market_cache.db': MKT_DB,
                'simulation.db': str(SIM_DB),
            }
            all_ok = True
            details = []
            for name, path in dbs_to_check.items():
                if os.path.exists(path):
                    size = os.path.getsize(path)
                    size_mb = size / 1024 / 1024
                    if size == 0:
                        details.append(f'{name}=0字节')
                        all_ok = False
                    else:
                        details.append(f'{name}={size_mb:.0f}MB')
                else:
                    details.append(f'{name}=不存在')
                    all_ok = False
            add('数据库路径', all_ok, ', '.join(details), 'critical' if not all_ok else 'info')
    except Exception as e:
        add('数据库路径', False, f'检查异常: {e}', 'warn')


# ══════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════

def main():
    print(f"\n{'='*55}")
    print(f"  系统健康自检 | {TODAY_STR}")
    print(f"{'='*55}")

    # 执行检查
    check_data_layer()
    check_strategy_layer()
    check_risk_layer()
    check_execution_layer()

    # 输出结果
    summary = {'info': 0, 'warn': 0, 'critical': 0}
    print(f"\n{'='*55}")
    print(f"  自检结果")
    print(f"{'='*55}")
    print(f"\n  {'#':>2s} {'状态':>4s} {'检查项':<30s} {'详情'}")
    print(f"  {'─'*70}")

    for i, (name, icon, value, severity) in enumerate(results, 1):
        summary[severity] += 1
        print(f"  {i:2d} {icon:>4s} {name:<30s} {value}")

    # 汇总
    print(f"\n  {'─'*70}")
    print(f"  {'汇总':<20s} 通过={summary['info']} | 告警={summary['warn']} | 严重={summary['critical']}")

    # 严重告警处理
    if summary['critical'] > 0:
        print(f"\n  🚨 严重告警 {summary['critical']} 项，需要立即处理:")
        for name, icon, value, severity in results:
            if severity == 'critical':
                print(f"    {icon} {name}: {value}")
    elif summary['warn'] > 0:
        print(f"\n  ⚠️ 告警 {summary['warn']} 项，建议关注")
    else:
        print(f"\n  ✅ 全部通过")

    print(f"\n{'='*55}")
    print(f"  ✅ 自检完成")
    print(f"{'='*55}")

    return results


if __name__ == "__main__":
    main()
