#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Decision Evidence Review Framework（Phase 8-C）
只读分析层，不改交易规则。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from decision.execution import (
    get_execution,
    find_executions_by_position_id,
    build_outcome_from_execution,
    _EXEC_DIR,
    EXECUTED,
    PARTIAL,
    NOT_EXECUTED,
    CLOSED,
    OPEN,
    UNKNOWN,
    SRC_SIM,
    SRC_MANUAL,
    SRC_SHADOW,
)
from decision.outcome import (
    SOURCE_DECISION,
    SOURCE_LEGACY,
    SOURCE_SHADOW,
    SOURCE_UNKNOWN,
)
from decision.outcome_store import _OUTCOME_DIR
from decision.snapshot import SNAP_DIR
from decision.observation_config import (
    OBSERVATION_START,
    CODE_VERSION,
    CONFIG_VERSION,
    STRATEGY_VERSION,
    DECISION_CONTRACT_VERSION,
)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

class EvidenceLevel:
    FACT = "FACT"
    EVIDENCE = "EVIDENCE"
    HYPOTHESIS = "HYPOTHESIS"

EXIT_REASONS = {
    "STOP_LOSS",
    "TAKE_PROFIT",
    "TRAILING_STOP",
    "MA20_EXIT",
    "PORTFOLIO_RISK",
    "MANUAL",
    "FORCED",
    "OTHER",
    "UNKNOWN",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_json_files(directory: Union[str, Path]) -> List[str]:
    d = Path(directory)
    if not d.exists():
        return []
    return sorted(str(p) for p in d.glob("*.json"))


def _load_json(path: str) -> Dict[str, Any]:
    try:
        return json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return {}

def _as_dict(obj):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "freeze"):
        return obj.freeze()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


def _as_dict(obj):
    if isinstance(obj, dict):
        return obj
    if obj is None:
        return {}
    if hasattr(obj, "freeze"):
        return obj.freeze()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


def _is_production(source: Optional[str], run_mode: Optional[str]) -> bool:
    if run_mode and str(run_mode).upper() == "PRODUCTION":
        return True
    if source and str(source).upper() == "MANUAL_CONFIRMATION":
        return True
    return False


# ---------------------------------------------------------------------------
# Attribution helpers
# ---------------------------------------------------------------------------

def _decision_quality(ex: Dict[str, Any], dec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "decision_id": ex.get("decision_id", ""),
        "symbol": ex.get("symbol", ""),
        "action": ex.get("action", ""),
        "strategy": ex.get("strategy", ""),
        "entry_regime": ex.get("entry_regime", "") or dec.get("market_regime", "") or dec.get("regime_label", ""),
        "candidate_score": ex.get("candidate_score", 0.0),
        "candidate_rank": ex.get("candidate_rank", 0),
        "level": EvidenceLevel.FACT,
    }


def _execution_quality(ex: Dict[str, Any]) -> Dict[str, Any]:
    planned = ex.get("planned", {}) or {}
    actual = ex.get("actual", {}) or {}
    price_slippage = 0.0
    qty_slippage = 0.0
    if planned.get("price") and actual.get("price"):
        price_slippage = round((actual["price"] - planned["price"]) / planned["price"], 6)
    if planned.get("quantity") and actual.get("quantity"):
        qty_slippage = actual["quantity"] - planned["quantity"]
    level = EvidenceLevel.FACT
    if price_slippage != 0 or qty_slippage != 0:
        level = EvidenceLevel.EVIDENCE
    return {
        "planned_price": planned.get("price"),
        "planned_quantity": planned.get("quantity"),
        "actual_price": actual.get("price"),
        "actual_quantity": actual.get("quantity"),
        "price_slippage": price_slippage,
        "quantity_slippage": qty_slippage,
        "execution_time": ex.get("execution_time", ""),
        "source": ex.get("source", ""),
        "status": ex.get("status", ""),
        "level": level,
    }


def _position_sizing_quality(ex: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "target_position": ex.get("planned", {}).get("position"),
        "actual_position": ex.get("actual", {}).get("position"),
        "position_status": ex.get("position_status", ""),
        "level": EvidenceLevel.FACT,
    }


def _exit_attribution(ex: Dict[str, Any]) -> Dict[str, Any]:
    segments = ex.get("exit_segments", []) or []
    exit_summary = ex.get("exit_summary", {}) or {}
    primary_exit = ex.get("exit", {}) or {}
    exit_decision_id = ""
    if primary_exit:
        exit_decision_id = primary_exit.get("exit_decision_id", "")
    if not exit_decision_id and segments:
        exit_decision_id = segments[-1].get("exit_decision_id", "")
    return {
        "exit_reason": primary_exit.get("reason", ""),
        "exit_price": primary_exit.get("price"),
        "exit_time": primary_exit.get("time"),
        "exit_regime": primary_exit.get("exit_regime", "") or (segments[0].get("exit_regime", "") if segments else ""),
        "exit_decision_id": exit_decision_id,
        "exit_execution_id": ex.get("entry_execution_id", ""),
        "segment_count": len(segments),
        "exit_summary": exit_summary,
        "level": EvidenceLevel.FACT,
    }


def _regime_evidence(ex: Dict[str, Any], outcome: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    entry_regime = ex.get("entry_regime", "")
    exit_regime = ""
    if outcome:
        exit_regime = _as_dict(outcome).get("exit_regime", "")
    if not exit_regime:
        exit_regime = (ex.get("exit", {}) or {}).get("exit_regime", "")
    transition = ""
    if entry_regime and exit_regime and entry_regime != exit_regime:
        transition = f"{entry_regime} -> {exit_regime}"
    return {
        "entry_regime": entry_regime,
        "exit_regime": exit_regime,
        "regime_transition": transition,
        "level": EvidenceLevel.FACT,
    }


def _permission_portfolio_evidence(ex: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "permission_status": ex.get("permission_status", ""),
        "permission": ex.get("permission", {}),
        "portfolio_assessment": ex.get("portfolio_assessment", {}),
        "portfolio_risk_flags": ex.get("portfolio_risk_flags", []),
        "drawdown": ex.get("portfolio_drawdown", 0.0),
        "level": EvidenceLevel.FACT,
    }


def _holding_period_evidence(ex: Dict[str, Any], outcome: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    entry_time = ex.get("execution_time", "") or (ex.get("actual", {}) or {}).get("entry_time", "")
    exit_time = ""
    if outcome:
        exit_time = outcome.get("exit_time", "")
    if not exit_time:
        exit_time = (ex.get("exit", {}) or {}).get("time", "")
    holding_days = 0
    if outcome:
        holding_days = _as_dict(outcome).get("holding_period_days", 0)
    if entry_time and exit_time:
        try:
            dt_entry = datetime.fromisoformat(entry_time)
            dt_exit = datetime.fromisoformat(exit_time)
            if holding_days == 0:
                holding_days = max(0, (dt_exit - dt_entry).days)
        except Exception:
            pass
    return {
        "actual_entry_time": entry_time,
        "final_exit_time": exit_time,
        "holding_period_days": holding_days,
        "level": EvidenceLevel.FACT,
    }


def _mae_mfe_evidence(outcome: Dict[str, Any]) -> Dict[str, Any]:
    excursion = (_as_dict(outcome).get("excursion", {}) or {})
    return {
        "mae": excursion.get("mae"),
        "mfe": excursion.get("mfe"),
        "max_drawdown": excursion.get("max_drawdown"),
        "max_profit": excursion.get("max_profit"),
        "mae_mfe_status": _as_dict(outcome).get("mae_mfe_status", ""),
        "level": EvidenceLevel.FACT,
    }


def _data_quality_evidence(ex: Dict[str, Any], outcome: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    flags = []
    for key in ("decision_snapshot_id", "portfolio_snapshot_id", "actual"):
        if not ex.get(key):
            flags.append(key)
    if outcome:
        if not outcome.get("decision_id"):
            flags.append("outcome_decision_id")
        if outcome.get("mae_mfe_status") == "UNKNOWN":
            flags.append("mae_mfe_unknown")
    return {
        "flags": flags,
        "data_quality": _as_dict(outcome).get("data_quality", "") if outcome else "",
        "level": EvidenceLevel.FACT if not flags else EvidenceLevel.EVIDENCE,
    }


def _no_trade_evidence(dec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "decision_id": dec.get("decision_id", ""),
        "blocking_layer": dec.get("blocking_layer", "") or dec.get("permission_status", ""),
        "reason_codes": list(dec.get("reason_codes", []) or []),
        "market_regime": dec.get("market_regime", "") or dec.get("regime_label", ""),
        "permission_status": dec.get("permission_status", ""),
        "candidate_score": dec.get("candidate_score"),
        "level": EvidenceLevel.FACT,
    }
    if "counterfactual" in dec:
        out["counterfactual"] = dec["counterfactual"]
    return out


# ---------------------------------------------------------------------------
# Evidence completeness
# ---------------------------------------------------------------------------

EVIDENCE_REQUIRED_KEYS = [
    "decision_quality",
    "execution_quality",
    "position_sizing_quality",
    "exit_attribution",
    "mae_mfe_evidence",
    "holding_period_evidence",
    "regime_evidence",
    "permission_portfolio_evidence",
    "data_quality_evidence",
]


def evidence_completeness(review: Dict[str, Any]) -> Dict[str, Any]:
    required_sections = [
        "decision_quality",
        "execution_quality",
        "position_sizing_quality",
        "exit_attribution",
        "regime_evidence",
        "permission_portfolio_evidence",
        "holding_period_evidence",
        "mae_mfe_evidence",
        "data_quality_evidence",
    ]
    facts = review.get("facts", {})
    present = [k for k in required_sections if k in facts]
    missing = [k for k in required_sections if k not in facts]
    complete = len(missing) == 0
    return {
        "complete": complete,
        "present_count": len(present),
        "missing_count": len(missing),
        "missing_sections": missing,
        "evidence_completeness": "EVIDENCE_COMPLETE" if complete else "PRODUCTION_PARTIAL",
    }


# ---------------------------------------------------------------------------
# Review record builders
# ---------------------------------------------------------------------------

def build_review_record_from_outcome(outcome: Union[Dict[str, Any], Any], ex: Optional[Dict[str, Any]] = None, decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ex = ex or {}
    outcome_dict = _as_dict(outcome)
    facts: Dict[str, Any] = {}
    facts["decision_quality"] = _decision_quality(ex, decision or {})
    facts["execution_quality"] = _execution_quality(ex)
    facts["position_sizing_quality"] = _position_sizing_quality(ex)
    facts["exit_attribution"] = _exit_attribution(ex)
    facts["regime_evidence"] = _regime_evidence(ex, outcome_dict)
    facts["permission_portfolio_evidence"] = _permission_portfolio_evidence(ex)
    facts["holding_period_evidence"] = _holding_period_evidence(ex, outcome_dict)
    facts["mae_mfe_evidence"] = _mae_mfe_evidence(outcome_dict)
    facts["data_quality_evidence"] = _data_quality_evidence(ex, outcome_dict)

    evidence: Dict[str, Any] = {}
    if facts["execution_quality"]["price_slippage"]:
        evidence["price_slippage"] = facts["execution_quality"]["price_slippage"]
    if facts["mae_mfe_evidence"]["mae"] is not None and facts["mae_mfe_evidence"]["mfe"] is not None:
        evidence["excursion"] = {
            "mae": facts["mae_mfe_evidence"]["mae"],
            "mfe": facts["mae_mfe_evidence"]["mfe"],
        }
    if facts["regime_evidence"]["regime_transition"]:
        evidence["regime_transition"] = facts["regime_evidence"]["regime_transition"]

    hypotheses: List[str] = []

    review = {
        "production_review_id": f"rev_{outcome_dict.get('outcome_id','')}",
        "outcome_id": outcome_dict.get("outcome_id", ""),
        "decision_id": outcome_dict.get("decision_id", ""),
        "execution_id": ex.get("execution_id", ""),
        "position_id": ex.get("position_id", ""),
        "review_time": _now_iso(),
        "facts": facts,
        "evidence": evidence,
        "hypotheses": hypotheses,
        "data_quality": outcome_dict.get("data_quality", ""),
        "attribution": {
            "decision_quality": facts["decision_quality"],
            "execution_quality": facts["execution_quality"],
            "position_sizing_quality": facts["position_sizing_quality"],
            "exit_quality": facts["exit_attribution"],
            "strategy_evidence": {"level": EvidenceLevel.FACT, "note": "Strategy evidence recorded only; no conclusion."},
        },
        "reviewer_status": "PENDING",
    }
    review.update(evidence_completeness(review))
    return review


def build_review_record_from_no_trade(decision: Dict[str, Any]) -> Dict[str, Any]:
    facts: Dict[str, Any] = {}
    facts["no_trade_evidence"] = _no_trade_evidence(decision)
    review = {
        "production_review_id": f"rev_{decision.get('decision_id','')}",
        "decision_id": decision.get("decision_id", ""),
        "review_time": _now_iso(),
        "facts": facts,
        "evidence": {},
        "hypotheses": [],
        "data_quality": decision.get("data_quality", ""),
        "attribution": {"no_trade_evidence": facts["no_trade_evidence"]},
        "reviewer_status": "PENDING",
    }
    return review


# ---------------------------------------------------------------------------
# Evaluation readiness
# ---------------------------------------------------------------------------

def evaluation_readiness(outcome: Union[Dict[str, Any], Any], ex: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    required = {
        "decision_id": bool(_as_dict(outcome).get("decision_id")),
        "execution_id": bool((ex or {}).get("execution_id")),
        "position_id": bool((ex or {}).get("position_id")),
        "outcome_id": bool(_as_dict(outcome).get("outcome_id")),
        "provenance": True,
        "strategy": bool((ex or {}).get("strategy")),
        "entry": bool((ex or {}).get("actual", {}).get("price")),
        "exit": bool((ex or {}).get("exit") or (ex or {}).get("exit_segments")),
    }
    complete = all(required.values())
    return {
        "production_evaluation_ready": complete,
        "readiness": "PRODUCTION_EVALUATION_READY" if complete else "PRODUCTION_PARTIAL",
        "missing_fields": [k for k, v in required.items() if not v],
    }


# ---------------------------------------------------------------------------
# Daily evidence summary
# ---------------------------------------------------------------------------

def build_daily_evidence_summary(observation_date: str) -> Dict[str, Any]:
    observation_date = observation_date or date.today().isoformat()
    decisions = _count_decisions()
    executions = _count_executions()
    outcomes = _count_outcomes()
    data_gaps = _count_data_gaps()
    reviewable = 0
    evidence_complete_count = 0
    for fp in _list_json_files(_OUTCOME_DIR):
        o = _load_json(fp)
        if not o:
            continue
        eid = o.get("execution_id", "")
        ex = get_execution(eid) if eid else None
        reviewable += 1
        if ex:
            review = build_review_record_from_outcome(o, ex)
            if review.get("evidence_completeness") == "EVIDENCE_COMPLETE":
                evidence_complete_count += 1
    return {
        "observation_date": observation_date,
        "observation_start": OBSERVATION_START,
        "code_version": CODE_VERSION,
        "config_version": CONFIG_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "decision_contract_version": DECISION_CONTRACT_VERSION,
        "generated_at": _now_iso(),
        "decision": decisions,
        "execution": executions,
        "outcome": outcomes,
        "data_gaps": data_gaps,
        "reviewable_outcomes": reviewable,
        "evidence_complete_outcomes": evidence_complete_count,
        "note": "Evidence summary only — no evaluation or strategy recommendation.",
    }


# ---------------------------------------------------------------------------
# Observation helpers (reuse observation layer counts for decisions/executions/outcomes)
# ---------------------------------------------------------------------------

def _count_decisions() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for fp in _list_json_files(SNAP_DIR):
        try:
            d = _load_json(fp)
        except Exception:
            continue
        a = d.get("action", "NO_TRADE")
        counts[a] = counts.get(a, 0) + 1
    return counts


def _count_executions() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for fp in _list_json_files(_EXEC_DIR):
        try:
            e = _load_json(fp)
        except Exception:
            continue
        s = e.get("status", UNKNOWN)
        counts[s] = counts.get(s, 0) + 1
    return counts


def _count_outcomes() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for fp in _list_json_files(_OUTCOME_DIR):
        try:
            o = _load_json(fp)
        except Exception:
            continue
        ls = o.get("lifecycle_status", "")
        if ls:
            counts[ls] = counts.get(ls, 0) + 1
    return counts


def _count_data_gaps() -> Dict[str, int]:
    gaps = {k: 0 for k in [
        "decision_without_execution", "buy_without_execution", "execution_without_position",
        "exit_without_decision", "closed_without_outcome", "outcome_without_decision",
        "missing_portfolio_snapshot", "missing_actual_execution", "missing_exit_regime", "missing_mae_mfe",
    ]}
    decision_ids = set()
    for fp in _list_json_files(SNAP_DIR):
        try:
            d = _load_json(fp)
        except Exception:
            continue
        did = d.get("decision_id")
        if not did:
            gaps["decision_without_snapshot"] = gaps.get("decision_without_snapshot", 0) + 1
            continue
        decision_ids.add(did)
        if d.get("action") in ("BUY", "ADD"):
            found = False
            for efp in _list_json_files(_EXEC_DIR):
                e = _load_json(efp)
                if e.get("decision_id") == did:
                    found = True
                    break
            if not found:
                gaps["decision_without_execution"] += 1
                gaps["buy_without_execution"] += 1
    for fp in _list_json_files(_EXEC_DIR):
        try:
            e = _load_json(fp)
        except Exception:
            continue
        if not e.get("actual", {}).get("price"):
            gaps["execution_without_position"] += 1
            gaps["missing_actual_execution"] += 1
        if e.get("position_status") == CLOSED and not e.get("outcome_id"):
            gaps["closed_without_outcome"] += 1
        if not e.get("exit_segments") and e.get("action", "").upper() in ("SELL", "REDUCE"):
            gaps["missing_exit_regime"] += 1
    for fp in _list_json_files(_OUTCOME_DIR):
        try:
            o = _load_json(fp)
        except Exception:
            continue
        if not o.get("decision_id"):
            gaps["outcome_without_decision"] += 1
        if (o.get("excursion", {}) or {}).get("mae_mfe_status") == "UNKNOWN":
            gaps["missing_mae_mfe"] += 1
    return gaps
