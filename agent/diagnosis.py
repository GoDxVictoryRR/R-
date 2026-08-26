"""
Diagnosis module: makes a single LLM call per incident and returns a structured
hypothesis containing root_cause, confidence (0-1), and proposed_action.

The proposed_action field is constrained to the allow-list defined in this module;
the LLM may not propose free-text actions.

Uses the NVIDIA Build OpenAI-compatible API via httpx (no openai SDK required).
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

# Load secrets from repo-root .env
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

# -----------------------------------------------------------------
# Allow-listed actions — the ONLY values proposed_action may take.
# -----------------------------------------------------------------
ALLOWED_ACTIONS = {"restart", "scale", "rollback", "escalate"}


@dataclass
class DiagnosisResult:
    """Structured output from a single LLM diagnosis call."""

    root_cause: str
    confidence: float          # 0.0 – 1.0
    proposed_action: str       # must be one of ALLOWED_ACTIONS
    reasoning: str             # brief free-text explanation (not acted on by the system)

    def is_valid(self) -> bool:
        """Returns True when all fields satisfy the schema contract."""
        return (
            bool(self.root_cause)
            and 0.0 <= self.confidence <= 1.0
            and self.proposed_action in ALLOWED_ACTIONS
        )


# -----------------------------------------------------------------
# Prompt template
# -----------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are an on-call incident-response assistant for a web service.
Your job is to analyse the telemetry and deployment context provided by the user
and return a JSON object with exactly these four fields:

{
  "root_cause": "<one concise sentence>",
  "confidence": <float between 0.0 and 1.0>,
  "proposed_action": "<one of: restart | scale | rollback | escalate>",
  "reasoning": "<two to four sentences explaining your diagnosis>"
}

Rules you must follow:
- proposed_action MUST be exactly one of: restart, scale, rollback, escalate.
  Do not invent other action names.
- Use "escalate" when confidence is low or the fault pattern is ambiguous.
- confidence must reflect how certain you are that the root_cause is correct.
- Return ONLY the JSON object — no markdown fences, no preamble, no trailing text.
"""


def _build_user_prompt(
    metrics: dict,
    deploy_logs: list,
    breach_reasons: list[str],
    runbook_title: Optional[str],
    runbook_snippet: Optional[str],
) -> str:
    """Assembles the user-turn prompt from current telemetry + context."""
    parts: list[str] = []

    parts.append("=== Current Metrics ===")
    for k, v in metrics.items():
        parts.append(f"  {k}: {v}")

    parts.append("\n=== Alert Reasons ===")
    for reason in breach_reasons:
        parts.append(f"  - {reason}")

    if deploy_logs:
        recent = deploy_logs[-3:]  # last 3 entries only to keep context tight
        parts.append("\n=== Recent Deploy History (newest last) ===")
        for entry in recent:
            parts.append(
                f"  [{entry.get('deployed_at', '?')}] {entry.get('version', '?')} "
                f"— {entry.get('status', '?')}: {entry.get('notes', '')}"
            )

    if runbook_title and runbook_snippet:
        # Truncate to first 600 chars to keep tokens bounded
        snippet = runbook_snippet[:600].strip()
        parts.append(f"\n=== Matched Runbook: {runbook_title} ===")
        parts.append(snippet)

    return "\n".join(parts)


# -----------------------------------------------------------------
# LLM client
# -----------------------------------------------------------------

class DiagnosisEngine:
    """Calls the configured LLM once per incident and returns a DiagnosisResult."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
        self.timeout = timeout

    def diagnose(
        self,
        metrics: dict,
        deploy_logs: list,
        breach_reasons: list[str],
        runbook_title: Optional[str] = None,
        runbook_snippet: Optional[str] = None,
    ) -> DiagnosisResult:
        """
        Makes one LLM call and returns a validated DiagnosisResult.

        Raises ValueError if the LLM response cannot be parsed into a valid
        schema-conformant hypothesis.
        """
        user_prompt = _build_user_prompt(
            metrics=metrics,
            deploy_logs=deploy_logs,
            breach_reasons=breach_reasons,
            runbook_title=runbook_title,
            runbook_snippet=runbook_snippet,
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,   # low temperature for reproducible structured output
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code != 200:
            raise ValueError(
                f"LLM API returned HTTP {response.status_code}: {response.text[:400]}"
            )

        raw = response.json()
        content = raw["choices"][0]["message"]["content"]
        return self._parse_response(content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(content: str) -> DiagnosisResult:
        """Parses raw LLM JSON output into a validated DiagnosisResult."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned non-JSON content: {content[:200]}") from exc

        # Coerce and validate fields
        root_cause = str(data.get("root_cause", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()

        try:
            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))  # clamp to [0,1]
        except (TypeError, ValueError):
            confidence = 0.0

        proposed_action = str(data.get("proposed_action", "")).strip().lower()
        if proposed_action not in ALLOWED_ACTIONS:
            # Degrade gracefully — treat unrecognised action as escalate
            proposed_action = "escalate"

        result = DiagnosisResult(
            root_cause=root_cause,
            confidence=confidence,
            proposed_action=proposed_action,
            reasoning=reasoning,
        )

        if not result.root_cause:
            raise ValueError(f"LLM returned empty root_cause. Raw: {content[:200]}")

        return result
