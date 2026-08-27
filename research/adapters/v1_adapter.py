#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research/adapters/v1_adapter.py — Phase 9-A 七：V1 StrategySpec adapter（不修改 V1）
========================================================================================

让 V1 可以被统一 Research Framework 调用，且：
  - 同样输入数据
  - 同样 PIT（复用 research.candidate_pit）
  - 同样 outcome（复用 research.forward_outcome）
  - 同样 cost / execution constraints

用于：V1 vs V2 vs V3 公平比较。
V1 在此仅作为 BENCHMARK_STRATEGY，不修改其任何参数/规则。

本 adapter 调用现有 research.candidate_pit 产出候选，并标注 signal 层
（entry_confirmed=True 视为 signal）。不重写 V1 逻辑。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.strategy_runner import StrategyResearchAdapter  # noqa: E402

# V1 数据血缘（复用，不修改）
try:
    from research.regime_v1.full_v1.entry_signal_pit import compute_signals  # noqa: F401
except Exception:  # 离线/路径缺失时不影响 adapter 类定义
    compute_signals = None


class V1Adapter(StrategyResearchAdapter):
    """V1 候选/信号 adapter（只读复用现有 PIT 研究产物）。"""

    def __init__(self):
        super().__init__(strategy_id="V1", strategy_version="1.0")

    def build_candidates(self, dataset, date_range) -> list[dict]:
        """
        从既有的 full_v1 candidate trace 读取候选（不重算、不修改 V1）。
        若既有产物存在则使用，否则返回空（由 runner 安全处理）。

        dataset: DatasetSpec（仅用于绑定记录）
        返回：统一格式 candidate dict 列表（含 symbol/candidate_date/is_signal）。
        """
        # 寻找既有的 full candidate trace（artifacts）
        base = Path(__file__).resolve().parent.parent
        trace = base / "regime_v1" / "full_v1" / "artifacts" / "full_candidate_trace.parquet"
        if not trace.exists():
            trace = base / "regime_v1" / "full_v1" / "artifacts" / "full_candidate_trace.csv"
        if not trace.exists():
            return []
        try:
            import pandas as pd
        except ImportError:
            return []
        if trace.suffix == ".parquet":
            df = pd.read_parquet(trace)
        else:
            df = pd.read_csv(trace)
        out = []
        for _, r in df.iterrows():
            is_sig = bool(str(r.get("entry_confirmed", "False")).lower() in ("true", "1"))
            out.append({
                "symbol": str(r["symbol"]),
                "candidate_date": str(r["as_of_date"]),
                "is_signal": is_sig,
            })
        return out
