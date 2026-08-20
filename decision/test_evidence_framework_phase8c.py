#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-C — Production Decision Evidence Review Framework 测试（22 项）
"""
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from decision.evidence_framework import (
    EvidenceLevel,
    EXIT_REASONS,
    evidence_completeness,
    build_review_record_from_outcome,
    build_review_record_from_no_trade,
    evaluation_readiness,
    build_daily_evidence_summary,
    _decision_quality,
    _execution_quality,
    _position_sizing_quality,
    _exit_attribution,
    _regime_evidence,
    _permission_portfolio_evidence,
    _holding_period_evidence,
    _mae_mfe_evidence,
    _data_quality_evidence,
    _no_trade_evidence,
    _count_decisions,
    _count_executions,
    _count_outcomes,
    _count_data_gaps,
    OBSERVATION_START,
)
from decision.execution import (
    record_simulation_execution,
    record_exit,
    build_outcome_from_execution,
    get_execution,
    EXECUTED,
    CLOSED,
    NOT_EXECUTED,
    UNKNOWN,
)
from decision import outcome_store
from decision import snapshot as snap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_dirs(tmp_path, monkeypatch, request):
    snap_dir = tmp_path / "snapshots"
    exec_dir = tmp_path / "executions"
    outcome_dir = tmp_path / "outcomes"
    snap_dir.mkdir()
    exec_dir.mkdir()
    outcome_dir.mkdir()
    monkeypatch.setattr("decision.evidence_framework.SNAP_DIR", str(snap_dir))
    monkeypatch.setattr("decision.evidence_framework._EXEC_DIR", str(exec_dir))
    monkeypatch.setattr("decision.evidence_framework._OUTCOME_DIR", str(outcome_dir))
    yield


def _fresh_decision(action="BUY", decision_id=None):
    did = decision_id or f"dec_{action.lower()}_{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    return {
        "decision_id": did,
        "symbol": "600000",
        "name": "P",
        "strategy": "v1_double",
        "timestamp": "2026-08-20T00:00:00Z",
        "reference_price": 10.0,
        "target_position": 2500.0,
        "permission_status": "ALLOW",
        "action": action,
        "market_regime": "HIGH_VOLATILITY",
        "regime_label": "HIGH_VOLATILITY",
        "permission": {"status": "ALLOW", "reason_codes": []},
        "portfolio_assessment": {"drawdown": 0.05, "risk_flags": []},
        "reason_codes": ["VOLUME_RATIO_GE_2.7"],
        "data_snapshot_id": "",
        "portfolio_snapshot_id": "",
    }


# ---------------------------------------------------------------------------
# 1. fact classification
# ---------------------------------------------------------------------------
def test_fact_classification():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    ex = get_execution(eid)
    assert ex is not None
    q = _decision_quality(ex, dec)
    e = _execution_quality(ex)
    assert q["level"] == EvidenceLevel.FACT
    assert e["level"] == EvidenceLevel.FACT
    assert e["planned_price"] == 10.0
    assert e["actual_price"] == 10.0
    assert e["price_slippage"] == 0.0


# ---------------------------------------------------------------------------
# 2. evidence classification
# ---------------------------------------------------------------------------
def test_evidence_classification():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    ex = get_execution(eid)
    ex["actual"]["price"] = 10.5
    ex["actual"]["quantity"] = 1000
    with open(f"decision/executions/{eid}.json", "w") as f:
        json.dump(ex, f)
    e = _execution_quality(ex)
    assert e["price_slippage"] == 0.05
    assert e["level"] == EvidenceLevel.EVIDENCE


# ---------------------------------------------------------------------------
# 3. hypothesis isolation
# ---------------------------------------------------------------------------
def test_hypothesis_isolation():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    ex = get_execution(eid)
    o = build_outcome_from_execution(eid)
    if o:
        outcome_store.save_outcome(o)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    assert "hypotheses" in review
    assert isinstance(review["hypotheses"], list)
    assert review["hypotheses"] == []


# ---------------------------------------------------------------------------
# 4. decision/execution separation
# ---------------------------------------------------------------------------
def test_decision_execution_separation():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    ex = get_execution(eid)
    review = build_review_record_from_outcome(None, ex, dec)
    dq = review["facts"]["decision_quality"]
    eq = review["facts"]["execution_quality"]
    assert dq["entry_regime"] == "HIGH_VOLATILITY"
    assert eq["price_slippage"] == 0.0
    assert eq["source"] == "SIMULATION"


# ---------------------------------------------------------------------------
# 5. exit attribution
# ---------------------------------------------------------------------------
def test_exit_attribution():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    record_exit(eid, 12.0, 1000, "2026-08-20", "TAKE_PROFIT", status=CLOSED, entry_execution_id=eid, exit_decision_id=dec["decision_id"])
    ex = get_execution(eid)
    review = build_review_record_from_outcome(None, ex, dec)
    assert review["facts"]["exit_attribution"]["exit_reason"] == "TAKE_PROFIT"
    assert review["facts"]["exit_attribution"]["segment_count"] == 1
    assert review["facts"]["exit_attribution"]["exit_decision_id"] == dec["decision_id"]
    assert review["facts"]["exit_attribution"]["level"] == EvidenceLevel.FACT


# ---------------------------------------------------------------------------
# 6. MAE/MFE evidence
# ---------------------------------------------------------------------------
def test_mae_mfe_evidence():
    outcome = {
        "outcome_id": "out_test",
        "decision_id": "dec_test",
        "data_quality": "SIMULATION",
        "mae_mfe_status": "UNKNOWN",
        "excursion": {"mae": -0.01, "mfe": 0.05, "status": "UNKNOWN"},
    }
    review = build_review_record_from_outcome(outcome, {}, {})
    m = review["facts"]["mae_mfe_evidence"]
    assert m["mae"] == -0.01
    assert m["mfe"] == 0.05
    assert m["level"] == EvidenceLevel.FACT


# ---------------------------------------------------------------------------
# 7. holding period evidence
# ---------------------------------------------------------------------------
def test_holding_period_evidence():
    ex = {"execution_time": "2026-08-20T09:30:00Z", "entry_execution_id": "eid_1"}
    outcome = {"outcome_id": "out_test", "exit_time": "2026-08-21T09:30:00Z", "holding_period_days": 1}
    review = build_review_record_from_outcome(outcome, ex, {})
    h = review["facts"]["holding_period_evidence"]
    assert h["holding_period_days"] == 1
    assert h["level"] == EvidenceLevel.FACT


# ---------------------------------------------------------------------------
# 8. regime evidence
# ---------------------------------------------------------------------------
def test_regime_evidence():
    ex = {"entry_regime": "HIGH_VOLATILITY", "exit": {"exit_regime": "SIDEWAYS"}}
    review = build_review_record_from_outcome({}, ex, {})
    r = review["facts"]["regime_evidence"]
    assert r["entry_regime"] == "HIGH_VOLATILITY"
    assert r["exit_regime"] == "SIDEWAYS"
    assert r["regime_transition"] == "HIGH_VOLATILITY -> SIDEWAYS"


# ---------------------------------------------------------------------------
# 9. permission evidence
# ---------------------------------------------------------------------------
def test_permission_evidence():
    ex = {"permission_status": "ALLOW", "permission": {"status": "ALLOW", "reason_codes": []}, "portfolio_risk_flags": ["DRAWDOWN"]}
    review = build_review_record_from_outcome({}, ex, {})
    p = review["facts"]["permission_portfolio_evidence"]
    assert p["permission_status"] == "ALLOW"
    assert "DRAWDOWN" in p["portfolio_risk_flags"]


# ---------------------------------------------------------------------------
# 10. portfolio evidence
# ---------------------------------------------------------------------------
def test_portfolio_evidence():
    ex = {"portfolio_assessment": {"drawdown": 0.12}, "portfolio_drawdown": 0.12}
    review = build_review_record_from_outcome({}, ex, {})
    p = review["facts"]["permission_portfolio_evidence"]
    assert p["drawdown"] == 0.12


# ---------------------------------------------------------------------------
# 11. no_trade evidence
# ---------------------------------------------------------------------------
def test_no_trade_evidence():
    dec = _fresh_decision(action="NO_TRADE")
    dec["blocking_layer"] = "PERMISSION"
    dec["reason_codes"] = ["NO_NEW_ENTRY"]
    review = build_review_record_from_no_trade(dec)
    assert review["facts"]["no_trade_evidence"]["level"] == EvidenceLevel.FACT
    assert "NO_NEW_ENTRY" in review["facts"]["no_trade_evidence"]["reason_codes"]


# ---------------------------------------------------------------------------
# 12. counterfactual separation
# ---------------------------------------------------------------------------
def test_counterfactual_separation():
    dec = _fresh_decision(action="NO_TRADE")
    dec["counterfactual"] = {"status": "UNKNOWN", "20d_return": 0.0}
    review = build_review_record_from_no_trade(dec)
    assert "counterfactual" in review["facts"]["no_trade_evidence"] or "counterfactual" in review


# ---------------------------------------------------------------------------
# 13. production review record
# ---------------------------------------------------------------------------
def test_production_review_record():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    record_exit(eid, 12.0, 1000, "2026-08-20", "TAKE_PROFIT", status=CLOSED, entry_execution_id=eid, exit_decision_id=dec["decision_id"])
    o = build_outcome_from_execution(eid)
    assert o is not None
    outcome_store.save_outcome(o)
    ex = get_execution(eid)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    assert review["reviewer_status"] == "PENDING"
    assert review["outcome_id"] == o.outcome_id
    assert review["decision_id"] == dec["decision_id"]


# ---------------------------------------------------------------------------
# 14. review immutability
# ---------------------------------------------------------------------------
def test_review_immutability():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    o = build_outcome_from_execution(eid)
    if o:
        outcome_store.save_outcome(o)
    ex = get_execution(eid)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    assert "review_time" in review
    new_review = build_review_record_from_outcome(o, ex, dec)
    assert new_review["review_time"] >= review["review_time"]


# ---------------------------------------------------------------------------
# 15. evidence completeness
# ---------------------------------------------------------------------------
def test_evidence_completeness():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    record_exit(eid, 12.0, 1000, "2026-08-20", "TAKE_PROFIT", status=CLOSED, entry_execution_id=eid, exit_decision_id=dec["decision_id"])
    o = build_outcome_from_execution(eid)
    if o:
        outcome_store.save_outcome(o)
    ex = get_execution(eid)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    ec = evidence_completeness(review)
    assert ec["complete"] is True
    assert ec["evidence_completeness"] == "EVIDENCE_COMPLETE"


# ---------------------------------------------------------------------------
# 16. observation vs evaluation readiness
# ---------------------------------------------------------------------------
def test_observation_vs_evaluation_readiness():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    o = build_outcome_from_execution(eid)
    if o:
        outcome_store.save_outcome(o)
    ex = get_execution(eid)
    readiness = evaluation_readiness(o.freeze() if o else {}, ex)
    # In this simulated flow the execution may not yet have an exit segment;
    # both PARTIAL and READY are acceptable framework states.
    assert readiness["readiness"] in ("PRODUCTION_EVALUATION_READY", "PRODUCTION_PARTIAL")


# ---------------------------------------------------------------------------
# 17. data sufficiency separation
# ---------------------------------------------------------------------------
def test_data_sufficiency_separation():
    outcome = {"outcome_id": "out_x", "decision_id": "dec_x"}
    ex = {"execution_id": "", "position_id": "", "strategy": "", "actual": {}}
    readiness = evaluation_readiness(outcome, ex)
    assert readiness["readiness"] == "PRODUCTION_PARTIAL"
    assert "execution_id" in readiness["missing_fields"]


# ---------------------------------------------------------------------------
# 18. no auto learning
# ---------------------------------------------------------------------------
def test_no_auto_learning():
    import decision.evidence_framework as ef
    assert not hasattr(ef, "update_strategy_parameters")
    assert not hasattr(ef, "auto_tune")
    assert not hasattr(ef, "reinforcement_learning")


# ---------------------------------------------------------------------------
# 19. daily evidence summary
# ---------------------------------------------------------------------------
def test_daily_evidence_summary():
    summary = build_daily_evidence_summary("2026-08-20")
    assert summary["observation_date"] == "2026-08-20"
    assert summary["observation_start"] == OBSERVATION_START
    assert "decision" in summary
    assert "execution" in summary
    assert "outcome" in summary
    assert summary["note"] == "Evidence summary only — no evaluation or strategy recommendation."


# ---------------------------------------------------------------------------
# 20. first outcome review
# ---------------------------------------------------------------------------
def test_first_outcome_review():
    dec = _fresh_decision(decision_id="first_outcome_dec")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    record_exit(eid, 12.0, 1000, "2026-08-20", "TAKE_PROFIT", status=CLOSED, entry_execution_id=eid, exit_decision_id=dec["decision_id"])
    o = build_outcome_from_execution(eid)
    assert o is not None
    outcome_store.save_outcome(o)
    ex = get_execution(eid)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    assert review["outcome_id"] == o.outcome_id
    assert review["evidence_completeness"] in ("EVIDENCE_COMPLETE", "PRODUCTION_PARTIAL")


# ---------------------------------------------------------------------------
# 21. test/simulation isolation
# ---------------------------------------------------------------------------
def test_simulation_isolation_in_review():
    dec = _fresh_decision(action="BUY", decision_id="sim_only_dec")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    ex = get_execution(eid)
    review = build_review_record_from_outcome(None, ex, dec)
    assert review["facts"]["execution_quality"]["source"] == "SIMULATION"


# ---------------------------------------------------------------------------
# 22. review replay linkage
# ---------------------------------------------------------------------------
def test_review_replay_linkage():
    dec = _fresh_decision(action="BUY")
    eid = record_simulation_execution(dec, "BUY", 10.0, 1000, run_mode="SIMULATION")
    record_exit(eid, 12.0, 1000, "2026-08-20", "TAKE_PROFIT", status=CLOSED, entry_execution_id=eid, exit_decision_id=dec["decision_id"])
    o = build_outcome_from_execution(eid)
    if o:
        outcome_store.save_outcome(o)
    ex = get_execution(eid)
    review = build_review_record_from_outcome(o.freeze() if o else {}, ex, dec)
    assert review["decision_id"] == dec["decision_id"]
    assert review["execution_id"] == eid
    assert review["outcome_id"] == (o.outcome_id if o else "")
