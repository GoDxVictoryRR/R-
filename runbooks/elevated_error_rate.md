# Runbook: Elevated Error Rate

## Trigger Conditions
- `error_rate` > 0.05 (5% or higher 5xx HTTP response rate)
- Request failure burst.

## Diagnosis
Determine if failures are correlated with recent code changes or sudden traffic bursts overwhelming available capacity.

## Recommended Remediation
- Primary Action: `scale` (if caused by sudden traffic volume exceeding capacity).
- Alternative Action: `restart` (if internal connection pool or client state corrupted).
