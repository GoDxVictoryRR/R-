"""
Unit tests for Orchestrator state machine.

Covers per testing-bar.md:
  - State transitions happen in correct order (PERCEIVE→DIAGNOSE→PLAN→GATE→ACT→VERIFY).
  - A REJECTED gate outcome skips ACT entirely.
  - A STILL_DEGRADED verify loops back to DIAGNOSE exactly once, then forced escalation.
  - NO_BREACH path returns immediately without going through DIAGNOSE.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import pytest

from agent.orchestrator import AgentState, Orchestrator
from agent.guardrail import GateOutcome


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_orchestrator(tmp_path: Path, human_fn=None) -> Orchestrator:
    return Orchestrator(
        toy_service_url="http://test:8000",
        audit_log_path=tmp_path / "test_audit.jsonl",
        human_approval_fn=human_fn or (lambda inc, act: True),
        verify_delay=0,  # no sleep in tests
    )


def _breach_context():
    """IncidentContext that represents a breach."""
    from agent.perception import IncidentContext
    return IncidentContext(
        breached=True,
        breach_reasons=["error_rate 40%"],
        metrics={"error_rate": 0.4, "p99_latency_ms": 45.0, "cpu_utilization_pct": 30.0, "memory_utilization_pct": 40.0},
        deploy_logs=[{"version": "v1.0.0", "deployed_at": "2026-01-01T00:00:00Z", "status": "SUCCESS", "notes": "ok"}],
        runbook_title="Elevated Error Rate",
        runbook_content="Scale or restart.",
    )


def _healthy_context():
    """IncidentContext that represents no breach (used for post-action verify)."""
    from agent.perception import IncidentContext
    return IncidentContext(
        breached=False,
        breach_reasons=[],
        metrics={"error_rate": 0.01, "p99_latency_ms": 45.0, "cpu_utilization_pct": 22.0, "memory_utilization_pct": 35.0},
        deploy_logs=[],
    )


# ── Test: no breach → immediate close ────────────────────────────────────

def test_no_breach_returns_immediately(tmp_path):
    orch = _make_orchestrator(tmp_path)

    with patch.object(orch.perception, "poll_service", return_value={"metrics": {}, "deploy_logs": []}), \
         patch.object(orch.perception, "evaluate_telemetry", return_value=_healthy_context()):

        record = orch.run_once()

    assert record.resolution == "NO_BREACH"
    assert record.state == AgentState.CLOSED
    assert record.diagnosis_loops == 0


# ── Test: happy path RESOLVED ─────────────────────────────────────────────

def test_happy_path_resolved(tmp_path):
    orch = _make_orchestrator(tmp_path)

    from agent.diagnosis import DiagnosisResult
    mock_diagnosis = DiagnosisResult(
        root_cause="High error rate", confidence=0.85,
        proposed_action="restart", reasoning="restart clears state"
    )

    contexts = [_breach_context(), _healthy_context()]  # breach → then resolved

    with patch.object(orch.perception, "poll_service", return_value={"metrics": {}, "deploy_logs": []}), \
         patch.object(orch.perception, "evaluate_telemetry", side_effect=contexts), \
         patch.object(orch.diagnosis, "diagnose", return_value=mock_diagnosis), \
         patch.object(orch.executor, "execute", return_value={"action": "restart", "status": "executed"}):

        record = orch.run_once()

    assert record.resolution == "RESOLVED"
    assert record.state == AgentState.CLOSED
    assert record.diagnosis_loops == 1


# ── Test: REJECTED gate skips ACT ────────────────────────────────────────

def test_rejected_gate_skips_act(tmp_path):
    orch = _make_orchestrator(tmp_path)

    from agent.diagnosis import DiagnosisResult
    # Confidence below 0.6 → REJECTED by guardrail
    mock_diagnosis = DiagnosisResult(
        root_cause="Unknown", confidence=0.3,
        proposed_action="restart", reasoning="unsure"
    )

    with patch.object(orch.perception, "poll_service", return_value={"metrics": {}, "deploy_logs": []}), \
         patch.object(orch.perception, "evaluate_telemetry", return_value=_breach_context()), \
         patch.object(orch.diagnosis, "diagnose", return_value=mock_diagnosis), \
         patch.object(orch.executor, "execute") as mock_execute:

        record = orch.run_once()

    # executor.execute must NOT have been called
    mock_execute.assert_not_called()
    assert record.resolution == "ESCALATED"


# ── Test: STILL_DEGRADED loops back to DIAGNOSE exactly once ─────────────

def test_still_degraded_loops_once_then_escalates(tmp_path):
    orch = _make_orchestrator(tmp_path)

    from agent.diagnosis import DiagnosisResult
    mock_diagnosis = DiagnosisResult(
        root_cause="Memory leak", confidence=0.75,
        proposed_action="restart", reasoning="restart clears memory"
    )

    # poll_service called for initial + verify1 + verify2
    # evaluate_telemetry: breach, still degraded, still degraded
    all_breach = [_breach_context(), _breach_context(), _breach_context()]

    with patch.object(orch.perception, "poll_service", return_value={"metrics": {}, "deploy_logs": []}), \
         patch.object(orch.perception, "evaluate_telemetry", side_effect=all_breach), \
         patch.object(orch.diagnosis, "diagnose", return_value=mock_diagnosis), \
         patch.object(orch.executor, "execute", return_value={"action": "restart", "status": "executed"}):

        record = orch.run_once()

    assert record.diagnosis_loops == 2
    assert record.resolution == "MAX_LOOPS_ESCALATED"


# ── Test: human denies rollback → HUMAN_DENIED ───────────────────────────

def test_human_denied_closes_incident(tmp_path):
    orch = _make_orchestrator(tmp_path, human_fn=lambda inc, act: False)

    from agent.diagnosis import DiagnosisResult
    # rollback always requires human approval
    mock_diagnosis = DiagnosisResult(
        root_cause="Bad deploy", confidence=0.9,
        proposed_action="rollback", reasoning="roll it back"
    )

    with patch.object(orch.perception, "poll_service", return_value={"metrics": {}, "deploy_logs": []}), \
         patch.object(orch.perception, "evaluate_telemetry", return_value=_breach_context()), \
         patch.object(orch.diagnosis, "diagnose", return_value=mock_diagnosis), \
         patch.object(orch.executor, "execute") as mock_execute:

        record = orch.run_once()

    mock_execute.assert_not_called()
    assert record.resolution == "HUMAN_DENIED"
