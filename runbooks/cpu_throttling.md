# Runbook: CPU Throttling and Compute Saturation

## Trigger Conditions
- `cpu_utilization_pct` > 80%
- Increased latency due to CPU limits and compute throttling.

## Diagnosis
Compute bottleneck caused by heavy computation or surging throughput.

## Recommended Remediation
- Primary Action: `scale` (add additional worker instances or replicas).
