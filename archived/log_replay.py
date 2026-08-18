#!/usr/bin/env python3
"""
日志回放 — 调取指定日期的执行日志
用法: python3 log_replay.py YYYY-MM-DD
"""
import os, sys, json
from datetime import date, datetime
from pathlib import Path

def replay_log(target_date):
    log_dir = os.path.expanduser("~/.hermes/logs")
    cron_dir = os.path.expanduser("~/.hermes/scripts/cron")
    
    print("=" * 55)
    print(f"📋 日志回放 — {target_date}")
    print("=" * 55)
    
    found = False
    
    # 1. 查找该日期的cron输出
    output_dir = os.path.expanduser("~/.hermes/cron/output")
    if os.path.exists(output_dir):
        files = sorted(os.listdir(output_dir), reverse=True)
        for f in files:
            fp = os.path.join(output_dir, f)
            if os.path.isdir(fp):
                continue
            mtime = os.path.getmtime(fp)
            mdate = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
            if mdate == target_date:
                found = True
                size = os.path.getsize(fp) / 1024
                print(f"\n📄 找到日志: {f} ({size:.0f}KB)")
                with open(fp, 'r', errors='ignore') as lf:
                    content = lf.read()
                # 分段输出关键内容
                lines = content.split('\n')
                sections = ['信号', '模拟', '止盈', '止损', '新股', '健康', 'ERROR', 'Traceback', 'Error']
                for section in sections:
                    relevant = [l for l in lines if section in l]
                    if relevant:
                        print(f"\n  [{section}]")
                        for l in relevant[:10]:
                            print(f"    {l.strip()}")
                if len(lines) > 200:
                    print(f"\n  ... (共{len(lines)}行，已截取关键部分)")
    
    # 2. 查找当天日志文件
    if os.path.exists(log_dir):
        for f in sorted(os.listdir(log_dir), reverse=True):
            if target_date in f:
                fp = os.path.join(log_dir, f)
                found = True
                size = os.path.getsize(fp) / 1024
                print(f"\n📄 系统日志: {f} ({size:.0f}KB)")
                with open(fp, 'r', errors='ignore') as lf:
                    lines = lf.readlines()[-100:]  # 最后100行
                errors = [l for l in lines if 'ERROR' in l or 'Traceback' in l or 'Error' in l]
                if errors:
                    print(f"\n  ⚠️ 发现 {len(errors)} 条错误:")
                    for e in errors[:5]:
                        print(f"    {e.strip()}")
                else:
                    print(f"  ✅ 无错误")
    
    # 3. 健康检查日志
    health_log = os.path.join(cron_dir, "health_log.json")
    if os.path.exists(health_log):
        with open(health_log) as f:
            try:
                records = json.load(f)
                for r in records:
                    if target_date in r.get('time', ''):
                        found = True
                        print(f"\n📄 健康检查日志 ({r['time']}):")
                        print(f"  状态: {r['status']}")
                        if r.get('issues'):
                            for issue in r['issues']:
                                print(f"  ⚠️ {issue}")
            except:
                pass
    
    if not found:
        print(f"\n  ⚠️ 未找到 {target_date} 的日志记录")
        print(f"  可能原因: 该日未执行任务 / 日志已被清理 / 日期格式错误(应为YYYY-MM-DD)")
    
    print(f"\n{'='*55}")

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    replay_log(target)