"""
Action executor — the ONLY file in this repository permitted to make HTTP calls
to the toy service's /control/* endpoints.

This boundary is enforced by policy (see architecture.md) and verified by the
import-boundary test in tests/test_executor.py.

No other module may call /control/restart, /control/scale, or /control/rollback
under any circumstances, including "just for testing" or "just this once."
"""

from typing import Any

import httpx


# Canonical base URL — populated at runtime from the orchestrator or test fixtures.
_DEFAULT_TOY_SERVICE_URL = "http://127.0.0.1:8000"

# Allow-list of control actions this executor may call. Exists as a defence-in-depth
# check: even if somehow called with an unknown action name, nothing fires.
_ALLOWED_CONTROL_ACTIONS = {"restart", "scale", "rollback"}


class ActionExecutor:
    """Executes approved remediation actions against the toy service control endpoints."""

    def __init__(
        self,
        toy_service_url: str = _DEFAULT_TOY_SERVICE_URL,
        timeout: float = 10.0,
    ) -> None:
        self.toy_service_url = toy_service_url.rstrip("/")
        self.timeout = timeout

    def execute(self, action_type: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Calls the appropriate /control/* endpoint on the toy service.

        Args:
            action_type: One of "restart", "scale", "rollback".
            parameters:  Optional dict passed as JSON body (used by scale for replica count).

        Returns:
            The JSON response from the toy service.

        Raises:
            ValueError:  If action_type is not in the allow-list.
            RuntimeError: If the toy service returns a non-2xx status.
        """
        if action_type not in _ALLOWED_CONTROL_ACTIONS:
            raise ValueError(
                f"executor.execute() called with unrecognised action '{action_type}'. "
                f"Only {_ALLOWED_CONTROL_ACTIONS} are permitted."
            )

        url = f"{self.toy_service_url}/control/{action_type}"
        body = parameters or {}

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=body)

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Toy service /control/{action_type} returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        return response.json()
