"""
Guardrail / policy engine for SentinelLoop.

This is the safety core of the agent. All actions proposed by the diagnosis module
MUST pass through evaluate_action() before execution. No state or debug override
may bypass these hardcoded rules.

Policy Outcomes:
  - AUTO_APPROVE           Action is pre-approved for execution.
  - NEEDS_HUMAN_APPROVAL   Action requires explicit human sign-off.
  - REJECTED               Action rejected due to policy bounds or low confidence.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class GateOutcome(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"
    REJECTED = "REJECTED"


@dataclass
class ActionProposal:
    incident_id: str
    action_type: str           # "restart", "scale", "rollback", "escalate"
    confidence: float          # 0.0 - 1.0
    proposed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parameters: Dict[str, str] = field(default_factory=dict)


@dataclass
class GateDecision:
    outcome: GateOutcome
    action_type: str
    reason: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GuardrailEngine:
    """
    Hard-coded, non-LLM safety policy engine governing agent execution.

    Rules enforced:
      1. Confidence < 0.6 -> REJECTED (escalate-only, no action taken).
      2. 'rollback' -> NEEDS_HUMAN_APPROVAL (always, regardless of confidence).
      3. 'restart' -> AUTO_APPROVE (if confidence >= 0.6).
      4. 'scale' -> AUTO_APPROVE capped at max_scale_actions within window_seconds.
      5. No action may run twice on the same incident without a VERIFY step between.
      6. Unknown or 'escalate' actions -> REJECTED / NEEDS_HUMAN_APPROVAL.
    """

    CONFIDENCE_THRESHOLD = 0.6

    def __init__(
        self,
        max_scale_actions: int = 3,
        window_seconds: int = 600,
    ) -> None:
        self.max_scale_actions = max_scale_actions
        self.window_seconds = window_seconds

        # Action execution tracking
        self._scale_history: List[datetime] = []
        self._last_action_per_incident: Dict[str, str] = {}
        self._verified_incidents: Dict[str, bool] = {}

    def mark_incident_verified(self, incident_id: str) -> None:
        """Call this after a VERIFY step completes to allow follow-up actions."""
        self._verified_incidents[incident_id] = True

    def evaluate_action(self, proposal: ActionProposal) -> GateDecision:
        """
        Evaluates a proposed action against safety policies.
        Returns a GateDecision indicating AUTO_APPROVE, NEEDS_HUMAN_APPROVAL, or REJECTED.
        """
        # Rule 1: Confidence < 0.6 threshold check
        if proposal.confidence < self.CONFIDENCE_THRESHOLD:
            return GateDecision(
                outcome=GateOutcome.REJECTED,
                action_type=proposal.action_type,
                reason=(
                    f"Confidence {proposal.confidence:.2f} is below minimum threshold "
                    f"{self.CONFIDENCE_THRESHOLD:.2f}. Forced escalation."
                ),
            )

        # Rule 5: Prevent consecutive unverified actions on the same incident
        last_action = self._last_action_per_incident.get(proposal.incident_id)
        has_verified = self._verified_incidents.get(proposal.incident_id, False)

        if last_action is not None and not has_verified:
            return GateDecision(
                outcome=GateOutcome.REJECTED,
                action_type=proposal.action_type,
                reason=(
                    f"Cannot execute '{proposal.action_type}' because prior action '{last_action}' "
                    f"has not completed a VERIFY step for incident '{proposal.incident_id}'."
                ),
            )

        # Rule 2: Rollback always requires human approval
        if proposal.action_type == "rollback":
            return GateDecision(
                outcome=GateOutcome.NEEDS_HUMAN_APPROVAL,
                action_type="rollback",
                reason="Policy rule: 'rollback' actions always require explicit human approval.",
            )

        # Rule 3: Restart is auto-approved
        if proposal.action_type == "restart":
            self._record_action_attempt(proposal)
            return GateDecision(
                outcome=GateOutcome.AUTO_APPROVE,
                action_type="restart",
                reason="Policy rule: 'restart' is auto-approved.",
            )

        # Rule 4: Scale is auto-approved but rate limited
        if proposal.action_type == "scale":
            now = datetime.now(timezone.utc)
            # Prune scale history outside window
            self._scale_history = [
                t for t in self._scale_history if (now - t).total_seconds() <= self.window_seconds
            ]

            if len(self._scale_history) >= self.max_scale_actions:
                return GateDecision(
                    outcome=GateOutcome.NEEDS_HUMAN_APPROVAL,
                    action_type="scale",
                    reason=(
                        f"Rate limit exceeded: {len(self._scale_history)} 'scale' actions in last "
                        f"{self.window_seconds}s (cap is {self.max_scale_actions}). Requires human approval."
                    ),
                )

            self._scale_history.append(now)
            self._record_action_attempt(proposal)
            return GateDecision(
                outcome=GateOutcome.AUTO_APPROVE,
                action_type="scale",
                reason=f"Policy rule: 'scale' auto-approved (capacity action {len(self._scale_history)}/{self.max_scale_actions}).",
            )

        # Escalate or unknown action
        if proposal.action_type == "escalate":
            return GateDecision(
                outcome=GateOutcome.NEEDS_HUMAN_APPROVAL,
                action_type="escalate",
                reason="Action is 'escalate'. Escalating to human operator.",
            )

        return GateDecision(
            outcome=GateOutcome.REJECTED,
            action_type=proposal.action_type,
            reason=f"Unrecognised action type '{proposal.action_type}'.",
        )

    def _record_action_attempt(self, proposal: ActionProposal) -> None:
        """Tracks the last attempted action and resets verification status for the incident."""
        self._last_action_per_incident[proposal.incident_id] = proposal.action_type
        self._verified_incidents[proposal.incident_id] = False
