#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 8-A.1 verification runner."""
import subprocess, sys, random, tempfile, os
from pathlib import Path

FULL_FILES = [
    'decision/test_decision_engine.py',
    'decision/test_portfolio.py',
    'decision/test_execution.py',
    'decision/test_outcome.py',
    'decision/test_lifecycle.py',
    'decision/test_real_position.py',
    'decision/test_real_portfolio.py',
    'decision/test_bypass.py',
    'decision/test_integrity_p67.py',
    'decision/test_backtest_validity.py',
    'decision/test_real_portfolio_phase75.py',
    'decision/test_daily_contract.py',
    'decision/test_real_readiness_phase76a.py',
    'decision/test_production_observation_phase8a.py',
    'decision/test_isolation_phase8a1.py',
]

def run(files, label):
    cmd = [sys.executable, '-m', 'pytest', '-v'] + files
    p = subprocess.run(cmd, capture_output=True, text=True)
    passed = 'passed' in p.stdout
    failed = 'failed' in p.stdout.lower()
    rc = p.returncode
    print(f'{label}: rc={rc}')
    if rc != 0:
        print(p.stdout[-1200:])
        print(p.stderr[-1200:])
    return rc == 0

print('=== 10x test_daily_contract.py ===')
for i in range(10):
    ok = run(['decision/test_daily_contract.py'], f'daily {i+1}/10')
    if not ok:
        print('STOP')
        sys.exit(1)
print('10x daily OK\n')

print('=== 3x full suite ===')
for i in range(3):
    order = FULL_FILES[:]
    random.shuffle(order)
    ok = run(order, f'full {i+1}/3')
    if not ok:
        print('STOP')
        sys.exit(1)
print('3x full random-order OK')
