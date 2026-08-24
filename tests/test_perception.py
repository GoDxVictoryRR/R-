"""Unit tests for agent perception layer and runbook keyword matcher."""

import pytest
from fastapi.testclient import TestClient
from agent.perception import PerceptionLayer
from toy_service.service import app
from toy_service.fault_injector import FaultInjector
from toy_service.state import service_state


@pytest.fixture(autouse=True)
def reset_service():
    client = TestClient(app)
    client.post("/reset")
    yield
    client.post("/reset")


def test_baseline_no_breach():
    client = TestClient(app)
    perception = PerceptionLayer()
    data = perception.poll_service(client=client)
    context = perception.evaluate_telemetry(data["metrics"], data["deploy_logs"])

    assert context.breached is False
    assert len(context.breach_reasons) == 0
    assert context.runbook_content is None


def test_match_high_latency_runbook():
    client = TestClient(app)
    injector = FaultInjector(service_state)
    injector.inject("high_latency", seed=42)

    perception = PerceptionLayer()
    data = perception.poll_service(client=client)
    context = perception.evaluate_telemetry(data["metrics"], data["deploy_logs"])

    assert context.breached is True
    assert "High Latency" in context.runbook_title
    assert "p99_latency_ms" in context.runbook_content


def test_match_elevated_error_rate_runbook():
    client = TestClient(app)
    injector = FaultInjector(service_state)
    injector.inject("elevated_error_rate", seed=10)

    perception = PerceptionLayer()
    data = perception.poll_service(client=client)
    context = perception.evaluate_telemetry(data["metrics"], data["deploy_logs"])

    assert context.breached is True
    assert "Elevated Error Rate" in context.runbook_title
    assert "error_rate" in context.runbook_content


def test_match_memory_leak_runbook():
    client = TestClient(app)
    injector = FaultInjector(service_state)
    injector.inject("memory_leak", seed=7)

    perception = PerceptionLayer()
    data = perception.poll_service(client=client)
    context = perception.evaluate_telemetry(data["metrics"], data["deploy_logs"])

    assert context.breached is True
    assert "Memory Leak" in context.runbook_title
    assert "memory_utilization_pct" in context.runbook_content


def test_match_bad_deploy_runbook():
    client = TestClient(app)
    injector = FaultInjector(service_state)
    injector.inject("bad_deploy", seed=88)

    perception = PerceptionLayer()
    data = perception.poll_service(client=client)
    context = perception.evaluate_telemetry(data["metrics"], data["deploy_logs"])

    assert context.breached is True
    assert "Bad Deployment" in context.runbook_title
    assert "rollback" in context.runbook_content.lower()
