"""Deterministic, seedable fault injector for simulating 4 incident scenarios against the toy service."""

import random
from typing import Any, Dict, Optional
from toy_service.state import ServiceState, service_state


class FaultInjector:
    """Injects reproducible faults into the target service state based on seed and fault type."""

    FAULT_TYPES = ["high_latency", "elevated_error_rate", "memory_leak", "bad_deploy"]

    def __init__(self, state: Optional[ServiceState] = None) -> None:
        self.state = state or service_state

    def inject(self, fault_type: str, seed: int = 42) -> Dict[str, Any]:
        if fault_type not in self.FAULT_TYPES:
            raise ValueError(f"Unknown fault type: {fault_type}. Must be one of {self.FAULT_TYPES}")

        rng = random.Random(seed)
        self.state.active_fault = fault_type
        self.state.is_healthy = False

        if fault_type == "high_latency":
            # Latency spikes to 800 - 2500 ms, cpu mildly elevated
            self.state.metrics.p99_latency_ms = rng.uniform(850.0, 2400.0)
            self.state.metrics.cpu_utilization_pct = rng.uniform(60.0, 85.0)
            self.state.metrics.error_rate = rng.uniform(0.02, 0.05)

        elif fault_type == "elevated_error_rate":
            # Error rate jumps to 15% - 65% (5xx errors)
            self.state.metrics.error_rate = rng.uniform(0.18, 0.65)
            self.state.metrics.p99_latency_ms = rng.uniform(80.0, 190.0)
            self.state.metrics.cpu_utilization_pct = rng.uniform(30.0, 50.0)

        elif fault_type == "memory_leak":
            # Memory utilization spikes to 85% - 98%, latency rises
            self.state.metrics.memory_utilization_pct = rng.uniform(88.0, 98.0)
            self.state.metrics.p99_latency_ms = rng.uniform(350.0, 750.0)
            self.state.metrics.error_rate = rng.uniform(0.05, 0.12)

        elif fault_type == "bad_deploy":
            # Log a faulty release and degrade metrics
            bad_version = f"v1.2.{rng.randint(1, 9)}-broken"
            commit_sha = f"{rng.randint(0x1000000, 0xFFFFFFF):x}"[:7]
            self.state.add_deploy_log(
                version=bad_version,
                status="FAILED_HEALTHCHECKS",
                commit_sha=commit_sha,
                notes="Regression in connection pool configuration causing request timeouts",
            )
            self.state.metrics.error_rate = rng.uniform(0.35, 0.75)
            self.state.metrics.p99_latency_ms = rng.uniform(1200.0, 3000.0)

        return {
            "status": "injected",
            "fault_type": fault_type,
            "seed": seed,
            "metrics": self.state.metrics.to_dict(),
            "current_version": self.state.current_version,
        }

    def clear(self) -> None:
        self.state.reset_baseline()
