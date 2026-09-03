"""
End-to-end integration test: inject each fault type, run the full orchestrator loop,
assert an audit log entry exists with a non-empty decision trail.

Per testing-bar.md: "One end-to-end test per fault type: inject the fault,
run the full orchestrator loop, assert an audit log entry exists with a
non-empty decision trail."

This test requires the toy service to be running at http://127.0.0.1:8000.
"""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.audit import AuditLog
from agent.orchestrator import Orchestrator
from toy_service.service import app
from toy_service.state import service_state


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_service_state():
    """Reset toy service to baseline before each test."""
    from fastapi.testclient import TestClient
    tc = TestClient(app)
    tc.post("/reset")
    yield
    tc.post("/reset")


def _run_e2e(fault_type: str, tmp_path: Path):
    """
    Injects fault_type, starts the orchestrator, runs one full loop.
    Returns (record, audit_events).
    """
    tc = TestClient(app)

    # Inject the fault so perception detects a breach
    tc.post("/inject_fault", json={"fault_type": fault_type, "seed": 42})

    audit_path = tmp_path / f"audit_{fault_type}.jsonl"
    orch = Orchestrator(
        toy_service_url="http://testserver",
        audit_log_path=audit_path,
        # auto-approve all human prompts in integration tests
        human_approval_fn=lambda inc, act: True,
        verify_delay=0,
    )

    # Patch PerceptionLayer to use the TestClient instead of real HTTP
    from unittest.mock import patch

    def _poll(client=None):
        metrics_resp = tc.get("/metrics")
        deploy_resp = tc.get("/deploy_logs")
        return {"metrics": metrics_resp.json(), "deploy_logs": deploy_resp.json()}

    def _execute(action_type, parameters=None):
        resp = tc.post(f"/control/{action_type}", json=parameters or {})
        return resp.json()

    with patch.object(orch.perception, "poll_service", side_effect=_poll), \
         patch.object(orch.executor, "execute", side_effect=_execute):
        record = orch.run_once()

    events = AuditLog(log_path=audit_path).read_incident(record.incident_id)
    return record, events


# ── Tests ─────────────────────────────────────────────────────────────────

def test_e2e_high_latency(tmp_path):
    record, events = _run_e2e("high_latency", tmp_path)
    event_types = [e["type"] for e in events]
    assert "INCIDENT_OPENED" in event_types
    assert "LLM_DIAGNOSIS" in event_types
    assert "GUARDRAIL_DECISION" in event_types
    assert "INCIDENT_CLOSED" in event_types
    assert len(events) >= 5, f"Expected full decision trail, got: {event_types}"


def test_e2e_elevated_error_rate(tmp_path):
    record, events = _run_e2e("elevated_error_rate", tmp_path)
    event_types = [e["type"] for e in events]
    assert "LLM_DIAGNOSIS" in event_types
    assert "GUARDRAIL_DECISION" in event_types
    assert "INCIDENT_CLOSED" in event_types


def test_e2e_memory_leak(tmp_path):
    record, events = _run_e2e("memory_leak", tmp_path)
    event_types = [e["type"] for e in events]
    assert "LLM_DIAGNOSIS" in event_types
    assert "GUARDRAIL_DECISION" in event_types
    assert "INCIDENT_CLOSED" in event_types


def test_e2e_bad_deploy(tmp_path):
    record, events = _run_e2e("bad_deploy", tmp_path)
    event_types = [e["type"] for e in events]
    # bad_deploy triggers rollback → human approval flow
    assert "LLM_DIAGNOSIS" in event_types
    assert "GUARDRAIL_DECISION" in event_types
    # Human auto-approved → ACTION_EXECUTED or HUMAN_APPROVAL should appear
    assert any(t in event_types for t in ("HUMAN_APPROVAL", "ACTION_EXECUTED", "INCIDENT_CLOSED"))
    assert "INCIDENT_CLOSED" in event_types
