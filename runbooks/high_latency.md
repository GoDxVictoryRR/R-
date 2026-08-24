# Runbook: High Latency Degradation

## Trigger Conditions
- `p99_latency_ms` > 200ms
- Elevated CPU utilization or downstream request queuing.

## Diagnosis
Inspect CPU load and active connection count. High latency typically indicates capacity saturation, thread pool starvation, or downstream congestion.

## Recommended Remediation
- Primary Action: `scale` (increase replicas/capacity to alleviate queuing).
- Secondary Action: `restart` (if latency is caused by hung worker processes).
