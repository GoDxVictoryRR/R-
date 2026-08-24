"""In-memory state container managing telemetry, deploy records, and health status for the toy service."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class Metrics:
    error_rate: float = 0.01
    p99_latency_ms: float = 45.0
    cpu_utilization_pct: float = 22.0
    memory_utilization_pct: float = 35.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "error_rate": round(self.error_rate, 4),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "cpu_utilization_pct": round(self.cpu_utilization_pct, 2),
            "memory_utilization_pct": round(self.memory_utilization_pct, 2),
        }


@dataclass
class DeployLog:
    version: str
    deployed_at: str
    status: str
    commit_sha: str
    notes: str


class ServiceState:
    def __init__(self) -> None:
        self.reset_baseline()

    def reset_baseline(self) -> None:
        self.is_healthy: bool = True
        self.active_fault: Optional[str] = None
        self.replicas: int = 2
        self.current_version: str = "v1.2.0"
        self.metrics = Metrics(
            error_rate=0.01,
            p99_latency_ms=45.0,
            cpu_utilization_pct=22.0,
            memory_utilization_pct=35.0,
        )
        self.deploy_logs: List[DeployLog] = [
            DeployLog(
                version="v1.2.0",
                deployed_at="2026-08-24T10:00:00Z",
                status="SUCCESS",
                commit_sha="a1b2c3d",
                notes="Stable baseline release",
            )
        ]

    def add_deploy_log(self, version: str, status: str, commit_sha: str, notes: str) -> None:
        log = DeployLog(
            version=version,
            deployed_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            commit_sha=commit_sha,
            notes=notes,
        )
        self.deploy_logs.append(log)
        self.current_version = version


# Global singleton instance for the toy service
service_state = ServiceState()
