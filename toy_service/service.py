"""FastAPI application serving the toy target service with telemetry, deploy logs, and remediation control endpoints."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from toy_service.fault_injector import FaultInjector
from toy_service.state import service_state

app = FastAPI(title="SentinelLoop Toy Service", version="1.0.0")
injector = FaultInjector(service_state)


class FaultInjectionRequest(BaseModel):
    fault_type: str = Field(..., description="Type of fault to inject (e.g. high_latency, elevated_error_rate, memory_leak, bad_deploy)")
    seed: int = Field(default=42, description="Random seed for reproducible telemetry values")


class ScaleRequest(BaseModel):
    replicas: int = Field(default=4, description="Target replica count")


@app.get("/health")
def get_health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy" if service_state.is_healthy else "degraded",
        "active_fault": service_state.active_fault,
        "current_version": service_state.current_version,
        "replicas": service_state.replicas,
    }


@app.get("/metrics")
def get_metrics() -> Dict[str, Any]:
    """Telemetry endpoint returning synthetic error rate, latency, and resource metrics."""
    return service_state.metrics.to_dict()


@app.get("/deploy_logs")
def get_deploy_logs() -> List[Dict[str, Any]]:
    """Returns deployment history logs."""
    return [
        {
            "version": log.version,
            "deployed_at": log.deployed_at,
            "status": log.status,
            "commit_sha": log.commit_sha,
            "notes": log.notes,
        }
        for log in service_state.deploy_logs
    ]


@app.post("/control/restart")
def control_restart() -> Dict[str, str]:
    """Remediation endpoint: restarts service process/containers, resetting transient memory/state."""
    service_state.metrics.memory_utilization_pct = 35.0
    service_state.metrics.cpu_utilization_pct = 22.0
    if service_state.active_fault in ["memory_leak", "high_latency"]:
        service_state.metrics.p99_latency_ms = 45.0
        service_state.metrics.error_rate = 0.01
        service_state.is_healthy = True
        service_state.active_fault = None
    return {"action": "restart", "status": "executed", "message": "Service processes restarted successfully."}


@app.post("/control/scale")
def control_scale(req: Optional[ScaleRequest] = None) -> Dict[str, Any]:
    """Remediation endpoint: scales service capacity/replicas to absorb high load or elevated errors."""
    target_replicas = req.replicas if req and req.replicas > 0 else (service_state.replicas + 2)
    service_state.replicas = target_replicas
    if service_state.active_fault in ["high_latency", "elevated_error_rate"]:
        service_state.metrics.p99_latency_ms = 45.0
        service_state.metrics.error_rate = 0.01
        service_state.metrics.cpu_utilization_pct = 25.0
        service_state.is_healthy = True
        service_state.active_fault = None
    return {"action": "scale", "status": "executed", "replicas": service_state.replicas}


@app.post("/control/rollback")
def control_rollback() -> Dict[str, Any]:
    """Remediation endpoint: rolls back to previous stable release."""
    service_state.current_version = "v1.2.0"
    service_state.add_deploy_log(
        version="v1.2.0",
        status="ROLLED_BACK",
        commit_sha="a1b2c3d",
        notes="Rollback executed to stable release",
    )
    service_state.metrics.error_rate = 0.01
    service_state.metrics.p99_latency_ms = 45.0
    service_state.metrics.cpu_utilization_pct = 22.0
    service_state.metrics.memory_utilization_pct = 35.0
    service_state.is_healthy = True
    service_state.active_fault = None
    return {"action": "rollback", "status": "executed", "version": "v1.2.0"}


@app.post("/inject_fault")
def inject_fault(req: FaultInjectionRequest) -> Dict[str, Any]:
    """Fault injection endpoint for testing and benchmark runs."""
    try:
        return injector.inject(req.fault_type, seed=req.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/reset")
def reset_state() -> Dict[str, str]:
    """Resets service state to pristine baseline."""
    injector.clear()
    return {"status": "reset", "message": "Service state reset to baseline"}
