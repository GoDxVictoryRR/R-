"""
Tests for ActionExecutor.

Covers:
  - Correct /control/* endpoint dispatching.
  - Rejection of unrecognised action types.
  - Import-boundary test: no file other than executor.py may import /control/* paths.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.executor import ActionExecutor


def _mock_response(data: dict, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.text = str(data)
    return mock


# ── Correct endpoint dispatching ──────────────────────────────────────────

@patch("agent.executor.httpx.Client")
def test_restart_calls_correct_endpoint(mock_client_cls):
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(
        {"action": "restart", "status": "executed"}
    )
    executor = ActionExecutor(toy_service_url="http://test:8000")
    result = executor.execute("restart")
    call_url = mock_client_cls.return_value.__enter__.return_value.post.call_args[0][0]
    assert call_url == "http://test:8000/control/restart"
    assert result["action"] == "restart"


@patch("agent.executor.httpx.Client")
def test_scale_calls_correct_endpoint(mock_client_cls):
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(
        {"action": "scale", "replicas": 4}
    )
    executor = ActionExecutor(toy_service_url="http://test:8000")
    result = executor.execute("scale", parameters={"replicas": 4})
    call_url = mock_client_cls.return_value.__enter__.return_value.post.call_args[0][0]
    assert call_url == "http://test:8000/control/scale"
    assert result["replicas"] == 4


@patch("agent.executor.httpx.Client")
def test_rollback_calls_correct_endpoint(mock_client_cls):
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(
        {"action": "rollback", "version": "v1.2.0"}
    )
    executor = ActionExecutor(toy_service_url="http://test:8000")
    result = executor.execute("rollback")
    call_url = mock_client_cls.return_value.__enter__.return_value.post.call_args[0][0]
    assert call_url == "http://test:8000/control/rollback"


# ── Allow-list enforcement ────────────────────────────────────────────────

def test_unknown_action_raises_value_error():
    executor = ActionExecutor()
    with pytest.raises(ValueError, match="unrecognised action"):
        executor.execute("delete_database")


# ── HTTP error propagation ────────────────────────────────────────────────

@patch("agent.executor.httpx.Client")
def test_http_error_raises_runtime_error(mock_client_cls):
    mock_client_cls.return_value.__enter__.return_value.post.return_value = _mock_response(
        {}, status_code=500
    )
    executor = ActionExecutor(toy_service_url="http://test:8000")
    with pytest.raises(RuntimeError, match="HTTP 500"):
        executor.execute("restart")


# ── Import-boundary test ──────────────────────────────────────────────────

def test_no_other_file_imports_control_endpoints():
    """
    Scan non-test, non-toy-service .py files and assert that none make HTTP
    calls to /control/* endpoints. Only agent/executor.py is permitted to do so.

    toy_service/ defines these endpoints (legitimate).
    tests/ may reference URL strings in assertions (legitimate).
    The check is restricted to agent/ and benchmark/ source files.
    """
    repo_root = Path(__file__).resolve().parent.parent
    executor_path = repo_root / "agent" / "executor.py"

    # Only scan agent/ and benchmark/ — the directories where violations would matter
    scan_dirs = [repo_root / "agent", repo_root / "benchmark"]

    offending_files = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.rglob("*.py"):
            if py_file == executor_path:
                continue
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # Look for actual HTTP POST/GET calls to /control/ (not just string definitions)
            if "/control/" in content and ("httpx" in content or "requests" in content or "client.post" in content):
                offending_files.append(str(py_file.relative_to(repo_root)))

    assert offending_files == [], (
        f"The following agent files illegally call /control/* endpoints directly: {offending_files}. "
        "Only agent/executor.py may make these HTTP calls."
    )
