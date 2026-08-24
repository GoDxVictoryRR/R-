"""Unit and endpoint tests for toy_service FastAPI app."""

from fastapi.testclient import TestClient
from toy_service.service import app
from toy_service.state import service_state

client = TestClient(app)


def setup_function():
    """Reset service state before each test."""
    client.post("/reset")


def test_baseline_health_and_metrics():
    """Verify default health and metric values."""
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"
    assert health_resp.json()["active_fault"] is None

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["error_rate"] == 0.01
    assert metrics["p99_latency_ms"] == 45.0


def test_inject_fault_and_restart():
    """Verify fault injection updates metrics and restart clears transient fault."""
    inject_resp = client.post("/inject_fault", json={"fault_type": "memory_leak", "seed": 42})
    assert inject_resp.status_code == 200

    health_resp = client.get("/health")
    assert health_resp.json()["status"] == "degraded"
    assert health_resp.json()["active_fault"] == "memory_leak"

    restart_resp = client.post("/control/restart")
    assert restart_resp.status_code == 200
    assert restart_resp.json()["action"] == "restart"

    health_after = client.get("/health")
    assert health_after.json()["status"] == "healthy"
    assert health_after.json()["active_fault"] is None


def test_inject_elevated_errors_and_scale():
    """Verify scaling relieves load and error state."""
    client.post("/inject_fault", json={"fault_type": "elevated_error_rate", "seed": 100})
    assert client.get("/health").json()["status"] == "degraded"

    scale_resp = client.post("/control/scale", json={"replicas": 6})
    assert scale_resp.status_code == 200
    assert scale_resp.json()["replicas"] == 6

    health_after = client.get("/health")
    assert health_after.json()["status"] == "healthy"


def test_inject_bad_deploy_and_rollback():
    """Verify bad deploy records deploy log and rollback restores stable state."""
    client.post("/inject_fault", json={"fault_type": "bad_deploy", "seed": 77})
    logs_resp = client.get("/deploy_logs")
    assert logs_resp.status_code == 200
    assert len(logs_resp.json()) >= 2
    assert "broken" in logs_resp.json()[-1]["version"]

    rollback_resp = client.post("/control/rollback")
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["version"] == "v1.2.0"

    health_after = client.get("/health")
    assert health_after.json()["status"] == "healthy"
