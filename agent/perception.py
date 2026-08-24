"""Perception layer responsible for polling metrics, reading deploy history, detecting breaches, and matching runbooks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx


@dataclass
class IncidentContext:
    breached: bool
    breach_reasons: List[str]
    metrics: Dict[str, float]
    deploy_logs: List[Dict[str, Any]]
    runbook_title: Optional[str] = None
    runbook_content: Optional[str] = None


class PerceptionLayer:
    """Monitors toy service telemetry and finds matching runbooks using keyword search."""

    # Degradation alert thresholds
    LATENCY_THRESHOLD_MS = 200.0
    ERROR_RATE_THRESHOLD = 0.05
    MEMORY_THRESHOLD_PCT = 80.0
    CPU_THRESHOLD_PCT = 80.0

    def __init__(self, base_url: str = "http://127.0.0.1:8000", runbooks_dir: Optional[Path] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.runbooks_dir = runbooks_dir or (Path(__file__).resolve().parent.parent / "runbooks")

    def poll_service(self, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
        """Fetches telemetry metrics and deploy history from toy service."""
        c = client or httpx.Client(base_url=self.base_url, timeout=5.0)
        try:
            metrics_resp = c.get("/metrics")
            metrics = metrics_resp.json() if metrics_resp.status_code == 200 else {}

            deploy_resp = c.get("/deploy_logs")
            deploy_logs = deploy_resp.json() if deploy_resp.status_code == 200 else []

            return {"metrics": metrics, "deploy_logs": deploy_logs}
        finally:
            if not client:
                c.close()

    def evaluate_telemetry(self, metrics: Dict[str, float], deploy_logs: List[Dict[str, Any]]) -> IncidentContext:
        """Evaluates whether metrics violate operational SLOs and builds an IncidentContext."""
        breach_reasons: List[str] = []

        # Check for bad deployments
        if deploy_logs and ("FAILED" in deploy_logs[-1].get("status", "").upper() or "broken" in deploy_logs[-1].get("version", "").lower()):
            breach_reasons.append(f"Recent failed/broken deploy detected: {deploy_logs[-1].get('version')}")

        if metrics.get("error_rate", 0.0) > self.ERROR_RATE_THRESHOLD:
            breach_reasons.append(f"Error rate {metrics.get('error_rate'):.2%} exceeds threshold {self.ERROR_RATE_THRESHOLD:.2%}")

        if metrics.get("p99_latency_ms", 0.0) > self.LATENCY_THRESHOLD_MS:
            breach_reasons.append(f"p99 latency {metrics.get('p99_latency_ms'):.1f}ms exceeds threshold {self.LATENCY_THRESHOLD_MS}ms")

        if metrics.get("memory_utilization_pct", 0.0) > self.MEMORY_THRESHOLD_PCT:
            breach_reasons.append(f"Memory utilization {metrics.get('memory_utilization_pct'):.1f}% exceeds threshold {self.MEMORY_THRESHOLD_PCT}%")

        if metrics.get("cpu_utilization_pct", 0.0) > self.CPU_THRESHOLD_PCT:
            breach_reasons.append(f"CPU utilization {metrics.get('cpu_utilization_pct'):.1f}% exceeds threshold {self.CPU_THRESHOLD_PCT}%")

        is_breached = len(breach_reasons) > 0
        context = IncidentContext(
            breached=is_breached,
            breach_reasons=breach_reasons,
            metrics=metrics,
            deploy_logs=deploy_logs,
        )

        if is_breached:
            matched_name, matched_content = self.match_runbook(context)
            context.runbook_title = matched_name
            context.runbook_content = matched_content

        return context

    def match_runbook(self, context: IncidentContext) -> tuple[str, str]:
        """Matches the most appropriate runbook using keyword search over metrics and breach descriptions."""
        if not self.runbooks_dir.exists():
            return "No runbooks found", ""

        # Priority keyword heuristics
        # 1. Bad deploy takes precedence if deploy status is failed / broken
        if any("deploy" in r.lower() for r in context.breach_reasons):
            target = "bad_deploy.md"
        # 2. Memory leak
        elif context.metrics.get("memory_utilization_pct", 0.0) > self.MEMORY_THRESHOLD_PCT:
            target = "memory_leak.md"
        # 3. High latency vs CPU throttling vs elevated errors
        elif context.metrics.get("error_rate", 0.0) > self.ERROR_RATE_THRESHOLD:
            target = "elevated_error_rate.md"
        elif context.metrics.get("p99_latency_ms", 0.0) > self.LATENCY_THRESHOLD_MS:
            target = "high_latency.md"
        else:
            target = "high_latency.md"

        runbook_path = self.runbooks_dir / target
        if runbook_path.exists():
            content = runbook_path.read_text(encoding="utf-8")
            title_line = content.splitlines()[0].replace("#", "").strip() if content else target
            return title_line, content

        # Fallback to first available runbook file
        first_file = next(self.runbooks_dir.glob("*.md"), None)
        if first_file:
            return first_file.stem, first_file.read_text(encoding="utf-8")
        return "Unknown", ""
