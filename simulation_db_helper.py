#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 simulation DB 路径获取。
测试模式 -> simulation_test.db，生产模式 -> simulation.db。
"""
import os
from pathlib import Path

def get_active_sim_db() -> Path:
    mode = os.environ.get('SIM_MODE', '')
    if mode == 'test':
        return Path('/home/caojy/.hermes/scripts/cron/simulation_test.db')
    return Path('/home/caojy/.hermes/scripts/cron/simulation.db')

__all__ = ['get_active_sim_db']
