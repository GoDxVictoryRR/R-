# Runbook: Memory Leak & Resource Exhaustion

## Trigger Conditions
- `memory_utilization_pct` > 80%
- Gradual latency climb accompanied by escalating resident memory footprint.

## Diagnosis
Unbounded memory retention or uncollected object references exhausting heap limits.

## Recommended Remediation
- Primary Action: `restart` (restarts processes to immediately flush memory allocations and restore operational capacity).
