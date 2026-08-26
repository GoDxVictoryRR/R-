"""
Unit tests for the DiagnosisEngine.

These tests do NOT make real LLM API calls. They test:
  - Valid JSON parsing into a correct DiagnosisResult
  - Confidence clamping to [0, 1]
  - proposed_action enforcement against the allow-list
  - Graceful degradation when the LLM returns an unrecognised action
  - ValueError raised on non-JSON or empty root_cause responses
  - HTTP error propagation

Correctness of diagnosis (does the LLM pick the right root cause?) is the
benchmark's job, not a unit test's job — per testing-bar.md.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from agent.diagnosis import DiagnosisEngine, DiagnosisResult, ALLOWED_ACTIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> DiagnosisEngine:
    return DiagnosisEngine(
        api_key="test-key",
        base_url="https://test.api.nvidia.com/v1",
        model="test-model",
    )


def _mock_response(content: dict | str, status_code: int = 200):
    """Build a mock httpx.Response-like object."""
    mock = MagicMock()
    mock.status_code = status_code
    if isinstance(content, dict):
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps(content)}}]
        })
    else:
        # Let caller pass raw string for the choices content
        body = json.dumps({
            "choices": [{"message": {"content": content}}]
        })
    mock.json.return_value = json.loads(body)
    mock.text = body
    return mock


SAMPLE_METRICS = {
    "error_rate": 0.45,
    "p99_latency_ms": 1800.0,
    "cpu_utilization_pct": 30.0,
    "memory_utilization_pct": 40.0,
}

SAMPLE_DEPLOY_LOGS = [
    {"deployed_at": "2026-08-24T10:00:00Z", "version": "v1.2.0", "status": "SUCCESS", "notes": "baseline"},
    {"deployed_at": "2026-08-25T09:00:00Z", "version": "v1.3.0-broken", "status": "FAILED_HEALTHCHECKS", "notes": "regression"},
]


# ---------------------------------------------------------------------------
# Test: correct happy-path parsing
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_diagnose_happy_path(mock_client_cls):
    payload = {
        "root_cause": "Bad deploy v1.3.0 introduced a regression",
        "confidence": 0.87,
        "proposed_action": "rollback",
        "reasoning": "Error rate spiked immediately after deploy.",
    }
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)

    engine = _make_engine()
    result = engine.diagnose(
        metrics=SAMPLE_METRICS,
        deploy_logs=SAMPLE_DEPLOY_LOGS,
        breach_reasons=["Error rate 45%"],
        runbook_title="Bad Deployment Regression",
        runbook_snippet="rollback to stable",
    )

    assert isinstance(result, DiagnosisResult)
    assert result.proposed_action == "rollback"
    assert result.confidence == pytest.approx(0.87)
    assert "regression" in result.root_cause.lower()
    assert result.is_valid()


# ---------------------------------------------------------------------------
# Test: confidence clamped to [0, 1]
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_confidence_clamped_high(mock_client_cls):
    payload = {"root_cause": "Memory leak", "confidence": 1.5, "proposed_action": "restart", "reasoning": "Memory high"}
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)

    result = _make_engine().diagnose(SAMPLE_METRICS, [], ["memory high"])
    assert result.confidence == 1.0


@patch("agent.diagnosis.httpx.Client")
def test_confidence_clamped_low(mock_client_cls):
    payload = {"root_cause": "Memory leak", "confidence": -0.3, "proposed_action": "restart", "reasoning": "Memory high"}
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)

    result = _make_engine().diagnose(SAMPLE_METRICS, [], ["memory high"])
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Test: unrecognised action degrades to escalate
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_unknown_action_becomes_escalate(mock_client_cls):
    payload = {
        "root_cause": "Unknown issue",
        "confidence": 0.4,
        "proposed_action": "reboot_all_the_things",  # not in allow-list
        "reasoning": "Not sure.",
    }
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)

    result = _make_engine().diagnose(SAMPLE_METRICS, [], ["breach"])
    assert result.proposed_action == "escalate"
    assert result.proposed_action in ALLOWED_ACTIONS


# ---------------------------------------------------------------------------
# Test: all four allowed actions pass through unchanged
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_all_allowed_actions_accepted(mock_client_cls):
    for action in ALLOWED_ACTIONS:
        payload = {"root_cause": "cause", "confidence": 0.75, "proposed_action": action, "reasoning": "reason"}
        mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)
        result = _make_engine().diagnose(SAMPLE_METRICS, [], ["breach"])
        assert result.proposed_action == action


# ---------------------------------------------------------------------------
# Test: non-JSON response raises ValueError
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_non_json_raises(mock_client_cls):
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(
        "Sure! Here is my answer in plain text, no JSON for you."
    )
    with pytest.raises(ValueError, match="non-JSON"):
        _make_engine().diagnose(SAMPLE_METRICS, [], ["breach"])


# ---------------------------------------------------------------------------
# Test: empty root_cause raises ValueError
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_empty_root_cause_raises(mock_client_cls):
    payload = {"root_cause": "", "confidence": 0.9, "proposed_action": "restart", "reasoning": "fast"}
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(payload)

    with pytest.raises(ValueError, match="empty root_cause"):
        _make_engine().diagnose(SAMPLE_METRICS, [], ["breach"])


# ---------------------------------------------------------------------------
# Test: HTTP error raises ValueError
# ---------------------------------------------------------------------------

@patch("agent.diagnosis.httpx.Client")
def test_http_error_raises(mock_client_cls):
    err_mock = MagicMock()
    err_mock.status_code = 401
    err_mock.text = "Unauthorized"
    mock_client_cls.return_value.__enter__.return_value.post.return_value = err_mock

    with pytest.raises(ValueError, match="HTTP 401"):
        _make_engine().diagnose(SAMPLE_METRICS, [], ["breach"])
