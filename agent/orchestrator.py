"""
Orchestrator — the state machine binding all agent components together.

State machine: PERCEIVE -> DIAGNOSE -> PLAN -> GATE -> ACT -> VERIFY
  - No state may be skipped.
  - No action may bypass GATE.
  - If STILL_DEGRADED after VERIFY, loop back to DIAGNOSE exactly once.
  - If still unresolved after the second loop, force ESCALATE regardless of confidence.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from agent.audit import AuditLog
from agent.diagnosis import DiagnosisEngine
from agent.executor import ActionExecutor
from agent.guardrail import ActionProposal, GateOutcome, GuardrailEngine
from agent.perception import IncidentContext, PerceptionLayer


class AgentState(str, Enum):
    IDLE = "IDLE"
    PERCEIVE = "PERCEIVE"
    DIAGNOSE = "DIAGNOSE"
    PLAN = "PLAN"
    GATE = "GATE"
    ACT = "ACT"
    VERIFY = "VERIFY"
    CLOSED = "CLOSED"


@dataclass
class IncidentRecord:
    incident_id: str
    opened_at: datetime
    state: AgentState = AgentState.PERCEIVE
    diagnosis_loops: int = 0          # max 2 before forced escalation
    resolution: str = ""
    closed_at: Optional[datetime] = None


class Orchestrator:
    """
    Runs one full incident-response loop per call to run_once().

    The orchestrator wires: PerceptionLayer → DiagnosisEngine → GuardrailEngine
    → ActionExecutor → back to PerceptionLayer (VERIFY).

    Human approval: when GATE returns NEEDS_HUMAN_APPROVAL, the orchestrator
    calls the human_approval_fn callback (defaults to stdin prompt). The callback
    receives (incident_id, action_type) and returns True (approved) or False (denied).
    """

    MAX_DIAGNOSIS_LOOPS = 2
    VERIFY_DELAY_SECONDS = 3          # short for demo; increase for real use

    def __init__(
        self,
        toy_service_url: str = "http://127.0.0.1:8000",
        runbooks_dir: Optional[Path] = None,
        audit_log_path: Optional[Path] = None,
        human_approval_fn=None,
        verify_delay: float = VERIFY_DELAY_SECONDS,
    ) -> None:
        self.perception = PerceptionLayer(
            base_url=toy_service_url,
            runbooks_dir=runbooks_dir,
        )
        self.diagnosis = DiagnosisEngine()
        self.guardrail = GuardrailEngine()
        self.executor = ActionExecutor(toy_service_url=toy_service_url)
        self.audit = AuditLog(log_path=audit_log_path)
        self.verify_delay = verify_delay

        # Default human approval: interactive stdin prompt
        self.human_approval_fn = human_approval_fn or self._default_human_prompt

    # ------------------------------------------------------------------ #
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #

    def run_once(self, http_client: Optional[httpx.Client] = None) -> IncidentRecord:
        """
        Runs one full PERCEIVE → ... → CLOSED cycle.

        Returns the IncidentRecord with final resolution.
        """
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        record = IncidentRecord(
            incident_id=incident_id,
            opened_at=datetime.now(timezone.utc),
        )

        # ── PERCEIVE ──────────────────────────────────────────────────
        record.state = AgentState.PERCEIVE
        self.audit.log_state_transition(incident_id, "IDLE", "PERCEIVE")

        data = self.perception.poll_service(client=http_client)
        metrics = data["metrics"]
        deploy_logs = data["deploy_logs"]
        context = self.perception.evaluate_telemetry(metrics, deploy_logs)

        if not context.breached:
            record.state = AgentState.CLOSED
            record.resolution = "NO_BREACH"
            record.closed_at = datetime.now(timezone.utc)
            self.audit.log_state_transition(incident_id, "PERCEIVE", "CLOSED", "No SLO breach detected.")
            return record

        self.audit.log_incident_opened(incident_id, context.breach_reasons, metrics)
        self.audit.log_state_transition(incident_id, "PERCEIVE", "DIAGNOSE")

        # ── Diagnosis / GATE / ACT / VERIFY loop (max 2 iterations) ──
        while record.diagnosis_loops < self.MAX_DIAGNOSIS_LOOPS:
            record.diagnosis_loops += 1
            record.state = AgentState.DIAGNOSE

            # DIAGNOSE
            diagnosis = self.diagnosis.diagnose(
                metrics=context.metrics,
                deploy_logs=context.deploy_logs,
                breach_reasons=context.breach_reasons,
                runbook_title=context.runbook_title,
                runbook_snippet=context.runbook_content,
            )
            self.audit.log_diagnosis(
                incident_id,
                root_cause=diagnosis.root_cause,
                confidence=diagnosis.confidence,
                proposed_action=diagnosis.proposed_action,
                reasoning=diagnosis.reasoning,
            )
            self.audit.log_state_transition(incident_id, "DIAGNOSE", "PLAN")

            # PLAN — map proposed action (already allow-listed by DiagnosisEngine)
            record.state = AgentState.PLAN
            proposal = ActionProposal(
                incident_id=incident_id,
                action_type=diagnosis.proposed_action,
                confidence=diagnosis.confidence,
            )
            self.audit.log_state_transition(incident_id, "PLAN", "GATE")

            # GATE
            record.state = AgentState.GATE
            decision = self.guardrail.evaluate_action(proposal)
            self.audit.log_guardrail_decision(
                incident_id,
                action_type=decision.action_type,
                outcome=decision.outcome.value,
                reason=decision.reason,
            )

            if decision.outcome == GateOutcome.REJECTED:
                # Confidence too low or policy violation → escalate, do not ACT
                self.audit.log_state_transition(
                    incident_id, "GATE", "CLOSED", f"REJECTED: {decision.reason}"
                )
                record.state = AgentState.CLOSED
                record.resolution = "ESCALATED"
                record.closed_at = datetime.now(timezone.utc)
                self.audit.log_incident_closed(incident_id, "ESCALATED")
                return record

            if decision.outcome == GateOutcome.NEEDS_HUMAN_APPROVAL:
                approved = self.human_approval_fn(incident_id, decision.action_type)
                approval_str = "APPROVED" if approved else "DENIED"
                self.audit.log_human_approval(incident_id, decision.action_type, approval_str)

                if not approved:
                    self.audit.log_state_transition(
                        incident_id, "GATE", "CLOSED", "Human denied action."
                    )
                    record.state = AgentState.CLOSED
                    record.resolution = "HUMAN_DENIED"
                    record.closed_at = datetime.now(timezone.utc)
                    self.audit.log_incident_closed(incident_id, "HUMAN_DENIED")
                    return record

            # ACT — execute the (approved) action
            record.state = AgentState.ACT
            self.audit.log_state_transition(incident_id, "GATE", "ACT")

            action_result = self.executor.execute(
                action_type=decision.action_type,
                parameters=proposal.parameters,
            )
            self.audit.log_action_executed(incident_id, decision.action_type, action_result)
            self.audit.log_state_transition(incident_id, "ACT", "VERIFY")

            # VERIFY — re-check metrics after delay
            record.state = AgentState.VERIFY
            time.sleep(self.verify_delay)

            new_data = self.perception.poll_service(client=http_client)
            new_context = self.perception.evaluate_telemetry(
                new_data["metrics"], new_data["deploy_logs"]
            )

            verdict = "RESOLVED" if not new_context.breached else "STILL_DEGRADED"
            self.audit.log_verification(incident_id, verdict, new_data["metrics"])
            self.guardrail.mark_incident_verified(incident_id)

            if not new_context.breached:
                record.state = AgentState.CLOSED
                record.resolution = "RESOLVED"
                record.closed_at = datetime.now(timezone.utc)
                self.audit.log_state_transition(incident_id, "VERIFY", "CLOSED", "RESOLVED")
                self.audit.log_incident_closed(incident_id, "RESOLVED")
                return record

            # Still degraded: loop back to DIAGNOSE (with updated context) if loops remain
            context = new_context
            self.audit.log_state_transition(
                incident_id, "VERIFY", "DIAGNOSE",
                f"STILL_DEGRADED — loop {record.diagnosis_loops}/{self.MAX_DIAGNOSIS_LOOPS}"
            )

        # Reached max diagnosis loops without resolution → forced escalation
        record.state = AgentState.CLOSED
        record.resolution = "MAX_LOOPS_ESCALATED"
        record.closed_at = datetime.now(timezone.utc)
        self.audit.log_state_transition(
            incident_id, "VERIFY", "CLOSED", "Max diagnosis loops reached. Forced escalation."
        )
        self.audit.log_incident_closed(incident_id, "MAX_LOOPS_ESCALATED")
        return record

    # ------------------------------------------------------------------ #
    # Default human-approval callback (stdin)                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _default_human_prompt(incident_id: str, action_type: str) -> bool:
        """Interactive stdin prompt for human approval. Returns True if approved."""
        print(f"\n[HUMAN APPROVAL REQUIRED]")
        print(f"  Incident : {incident_id}")
        print(f"  Action   : {action_type}")
        response = input("  Approve? (yes/no): ").strip().lower()
        return response in ("yes", "y")
