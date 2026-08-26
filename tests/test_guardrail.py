"""
Unit tests for GuardrailEngine covering every policy rule and edge case.
"""

from datetime import datetime, timezone
import pytest
from agent.guardrail import ActionProposal, GateDecision, GateOutcome, GuardrailEngine


def test_confidence_threshold_exact():
    """Confidence exactly at 0.6 should pass; 0.59 should be REJECTED."""
    engine = GuardrailEngine()

    # 0.60 -> AUTO_APPROVE
    p_exact = ActionProposal(incident_id="inc-1", action_type="restart", confidence=0.60)
    res_exact = engine.evaluate_action(p_exact)
    assert res_exact.outcome == GateOutcome.AUTO_APPROVE

    # 0.59 -> REJECTED
    p_below = ActionProposal(incident_id="inc-2", action_type="restart", confidence=0.59)
    res_below = engine.evaluate_action(p_below)
    assert res_below.outcome == GateOutcome.REJECTED
    assert "below minimum threshold" in res_below.reason


def test_rollback_always_requires_human_approval():
    """Rollback requires human approval even with 1.0 (100%) confidence."""
    engine = GuardrailEngine()
    proposal = ActionProposal(incident_id="inc-1", action_type="rollback", confidence=1.0)
    res = engine.evaluate_action(proposal)

    assert res.outcome == GateOutcome.NEEDS_HUMAN_APPROVAL
    assert res.action_type == "rollback"
    assert "human approval" in res.reason.lower()


def test_restart_auto_approved():
    """Restart is auto-approved when confidence >= 0.6."""
    engine = GuardrailEngine()
    proposal = ActionProposal(incident_id="inc-1", action_type="restart", confidence=0.85)
    res = engine.evaluate_action(proposal)

    assert res.outcome == GateOutcome.AUTO_APPROVE
    assert res.action_type == "restart"


def test_scale_rate_limiting():
    """Scale actions are auto-approved up to cap, then require human approval."""
    engine = GuardrailEngine(max_scale_actions=3, window_seconds=600)

    # First 3 scale actions on different incidents should be auto-approved
    for i in range(3):
        p = ActionProposal(incident_id=f"inc-scale-{i}", action_type="scale", confidence=0.8)
        res = engine.evaluate_action(p)
        assert res.outcome == GateOutcome.AUTO_APPROVE

    # 4th scale action exceeds cap -> NEEDS_HUMAN_APPROVAL
    p_fourth = ActionProposal(incident_id="inc-scale-4", action_type="scale", confidence=0.9)
    res_fourth = engine.evaluate_action(p_fourth)
    assert res_fourth.outcome == GateOutcome.NEEDS_HUMAN_APPROVAL
    assert "Rate limit exceeded" in res_fourth.reason


def test_no_consecutive_action_without_verify():
    """Cannot run a second action on the same incident without a verify step between."""
    engine = GuardrailEngine()
    inc_id = "inc-double-action"

    # Action 1: restart -> AUTO_APPROVE
    p1 = ActionProposal(incident_id=inc_id, action_type="restart", confidence=0.8)
    res1 = engine.evaluate_action(p1)
    assert res1.outcome == GateOutcome.AUTO_APPROVE

    # Action 2 (unverified) -> REJECTED
    p2 = ActionProposal(incident_id=inc_id, action_type="scale", confidence=0.8)
    res2 = engine.evaluate_action(p2)
    assert res2.outcome == GateOutcome.REJECTED
    assert "prior action" in res2.reason

    # Mark incident verified -> Action 2 now allowed
    engine.mark_incident_verified(inc_id)
    res3 = engine.evaluate_action(p2)
    assert res3.outcome == GateOutcome.AUTO_APPROVE


def test_escalate_action_outcome():
    """Escalate action yields NEEDS_HUMAN_APPROVAL."""
    engine = GuardrailEngine()
    proposal = ActionProposal(incident_id="inc-esc", action_type="escalate", confidence=0.9)
    res = engine.evaluate_action(proposal)

    assert res.outcome == GateOutcome.NEEDS_HUMAN_APPROVAL
    assert res.action_type == "escalate"
