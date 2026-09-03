"""
Tests for the audit log writer (AuditLog) and timeline reader (print functions).

Verifies:
  - Each event type is correctly appended and round-trips through JSON.
  - read_incident returns only the events for the requested incident.
  - read_all returns events in insertion order.
  - An empty log returns empty lists without errors.
  - print_incident_trail and print_incident_list produce non-empty output.
"""

import json
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.audit import AuditLog
from agent.timeline import print_incident_trail, print_incident_list


# ── AuditLog unit tests ───────────────────────────────────────────────────

def test_log_and_read_incident(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-1", ["error_rate 40%"], {"error_rate": 0.4})
    log.log_state_transition("inc-1", "PERCEIVE", "DIAGNOSE")
    log.log_diagnosis("inc-1", "memory leak", 0.82, "restart", "restart clears state")
    log.log_guardrail_decision("inc-1", "restart", "AUTO_APPROVE", "auto-approved")
    log.log_action_executed("inc-1", "restart", {"status": "done"})
    log.log_verification("inc-1", "RESOLVED", {"error_rate": 0.01})
    log.log_incident_closed("inc-1", "RESOLVED")

    events = log.read_incident("inc-1")
    types = [e["type"] for e in events]

    assert "INCIDENT_OPENED" in types
    assert "STATE_TRANSITION" in types
    assert "LLM_DIAGNOSIS" in types
    assert "GUARDRAIL_DECISION" in types
    assert "ACTION_EXECUTED" in types
    assert "VERIFICATION" in types
    assert "INCIDENT_CLOSED" in types
    assert len(events) == 7


def test_read_incident_filters_by_id(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-A", ["latency"], {"error_rate": 0.1})
    log.log_incident_opened("inc-B", ["errors"], {"error_rate": 0.4})
    log.log_incident_closed("inc-A", "RESOLVED")
    log.log_incident_closed("inc-B", "ESCALATED")

    events_a = log.read_incident("inc-A")
    events_b = log.read_incident("inc-B")

    assert all(e["incident_id"] == "inc-A" for e in events_a)
    assert all(e["incident_id"] == "inc-B" for e in events_b)
    assert len(events_a) == 2
    assert len(events_b) == 2


def test_read_all_returns_all_events(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-1", [], {})
    log.log_incident_opened("inc-2", [], {})
    log.log_incident_closed("inc-1", "RESOLVED")

    all_events = log.read_all()
    assert len(all_events) == 3


def test_empty_log_returns_empty_lists(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit_empty.jsonl")
    # File doesn't exist yet
    assert log.read_all() == []
    assert log.read_incident("inc-none") == []


def test_human_approval_logged(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_human_approval("inc-1", "rollback", "APPROVED")
    events = log.read_all()
    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "HUMAN_APPROVAL"
    assert evt["decision"] == "APPROVED"


def test_events_are_valid_json_lines(tmp_path):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-1", ["breach"], {"error_rate": 0.5})
    log.log_incident_closed("inc-1", "RESOLVED")

    raw = (tmp_path / "audit.jsonl").read_text()
    for line in raw.strip().split("\n"):
        data = json.loads(line)  # must not raise
        assert "type" in data
        assert "logged_at" in data


# ── Timeline viewer tests ─────────────────────────────────────────────────

def test_print_incident_trail_non_empty(tmp_path, capsys):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-t1", ["latency"], {"error_rate": 0.2, "p99_latency_ms": 1500.0, "memory_utilization_pct": 60.0})
    log.log_state_transition("inc-t1", "PERCEIVE", "DIAGNOSE")
    log.log_diagnosis("inc-t1", "bad deploy", 0.9, "rollback", "version regression")
    log.log_guardrail_decision("inc-t1", "rollback", "NEEDS_HUMAN_APPROVAL", "requires human sign-off")
    log.log_human_approval("inc-t1", "rollback", "APPROVED")
    log.log_action_executed("inc-t1", "rollback", {"version": "v1.1.0"})
    log.log_verification("inc-t1", "RESOLVED", {"error_rate": 0.01, "p99_latency_ms": 60.0, "memory_utilization_pct": 35.0})
    log.log_incident_closed("inc-t1", "RESOLVED")

    print_incident_trail("inc-t1", log)

    captured = capsys.readouterr().out
    assert "inc-t1" in captured
    assert "bad deploy" in captured
    assert "RESOLVED" in captured
    assert "rollback" in captured


def test_print_incident_list_non_empty(tmp_path, capsys):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    log.log_incident_opened("inc-list-1", [], {})
    log.log_incident_closed("inc-list-1", "RESOLVED")
    log.log_incident_opened("inc-list-2", [], {})
    log.log_incident_closed("inc-list-2", "ESCALATED")

    print_incident_list(log)

    captured = capsys.readouterr().out
    assert "inc-list-1" in captured
    assert "inc-list-2" in captured
    assert "RESOLVED" in captured
    assert "ESCALATED" in captured


def test_print_trail_for_missing_incident(tmp_path, capsys):
    log = AuditLog(log_path=tmp_path / "audit.jsonl")
    print_incident_trail("inc-nonexistent", log)
    captured = capsys.readouterr().out
    assert "No events found" in captured


def test_print_list_empty_log(tmp_path, capsys):
    log = AuditLog(log_path=tmp_path / "audit_empty.jsonl")
    print_incident_list(log)
    captured = capsys.readouterr().out
    assert "empty" in captured.lower()
