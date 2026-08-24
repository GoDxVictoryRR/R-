# Runbook: Service Crash and Process Termination

## Trigger Conditions
- Health endpoint status is `degraded` or unreachable.
- `error_rate` is elevated due to unavailable instances.

## Diagnosis
Process unhandled exception, OOM kill, or hung worker process.

## Recommended Remediation
- Primary Action: `restart` (restart instance processes immediately).
