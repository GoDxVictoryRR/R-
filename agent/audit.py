"""
Append-only audit log writer and reader.

Every state transition, LLM call (prompt redacted to save space, stored separately),
guardrail decision, tool call, and human approval/denial is logged here with timestamps.

Format: JSON Lines (.jsonl). Each line is one event. Never mutated — only appended.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "audit.jsonl"


class AuditLog:
    """Append-only, single-file JSON Lines event log."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = log_path or _DEFAULT_LOG_PATH

    def _append(self, event: dict[str, Any]) -> None:
        """Write one event line. Creates the file if needed."""
        event.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    # ------------------------------------------------------------------ #
    # Convenience writers — one per logical event type                     #
    # ------------------------------------------------------------------ #

    def log_state_transition(
        self,
        incident_id: str,
        from_state: str,
        to_state: str,
        detail: str = "",
    ) -> None:
        self._append(
            {
                "type": "STATE_TRANSITION",
                "incident_id": incident_id,
                "from": from_state,
                "to": to_state,
                "detail": detail,
            }
        )

    def log_diagnosis(
        self,
        incident_id: str,
        root_cause: str,
        confidence: float,
        proposed_action: str,
        reasoning: str,
    ) -> None:
        self._append(
            {
                "type": "LLM_DIAGNOSIS",
                "incident_id": incident_id,
                "root_cause": root_cause,
                "confidence": round(confidence, 4),
                "proposed_action": proposed_action,
                "reasoning": reasoning,
            }
        )

    def log_guardrail_decision(
        self,
        incident_id: str,
        action_type: str,
        outcome: str,
        reason: str,
    ) -> None:
        self._append(
            {
                "type": "GUARDRAIL_DECISION",
                "incident_id": incident_id,
                "action_type": action_type,
                "outcome": outcome,
                "reason": reason,
            }
        )

    def log_action_executed(
        self,
        incident_id: str,
        action_type: str,
        result: dict[str, Any],
    ) -> None:
        self._append(
            {
                "type": "ACTION_EXECUTED",
                "incident_id": incident_id,
                "action_type": action_type,
                "result": result,
            }
        )

    def log_verification(
        self,
        incident_id: str,
        verdict: str,
        metrics_after: dict[str, float],
    ) -> None:
        self._append(
            {
                "type": "VERIFICATION",
                "incident_id": incident_id,
                "verdict": verdict,        # "RESOLVED" or "STILL_DEGRADED"
                "metrics_after": metrics_after,
            }
        )

    def log_human_approval(
        self,
        incident_id: str,
        action_type: str,
        decision: str,         # "APPROVED" or "DENIED"
        by: str = "HUMAN",
    ) -> None:
        self._append(
            {
                "type": "HUMAN_APPROVAL",
                "incident_id": incident_id,
                "action_type": action_type,
                "decision": decision,
                "by": by,
            }
        )

    def log_incident_opened(
        self,
        incident_id: str,
        breach_reasons: list[str],
        metrics: dict[str, float],
    ) -> None:
        self._append(
            {
                "type": "INCIDENT_OPENED",
                "incident_id": incident_id,
                "breach_reasons": breach_reasons,
                "metrics": metrics,
            }
        )

    def log_incident_closed(
        self,
        incident_id: str,
        resolution: str,        # "RESOLVED" | "ESCALATED" | "MAX_LOOPS_REACHED"
    ) -> None:
        self._append(
            {
                "type": "INCIDENT_CLOSED",
                "incident_id": incident_id,
                "resolution": resolution,
            }
        )

    # ------------------------------------------------------------------ #
    # Reader                                                               #
    # ------------------------------------------------------------------ #

    def read_incident(self, incident_id: str) -> list[dict[str, Any]]:
        """Return all events for a given incident in chronological order."""
        if not self.log_path.exists():
            return []
        events = []
        with self.log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    if evt.get("incident_id") == incident_id:
                        events.append(evt)
                except json.JSONDecodeError:
                    continue
        return events

    def read_all(self) -> list[dict[str, Any]]:
        """Return every event in the log."""
        if not self.log_path.exists():
            return []
        events = []
        with self.log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events
