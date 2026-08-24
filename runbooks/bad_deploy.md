# Runbook: Bad Deployment Regression

## Trigger Conditions
- Recent deployment status shows failure, error spike immediately following a release, or broken release version in deploy history.
- `error_rate` > 0.10 closely following deployment timestamp.

## Diagnosis
A regression introduced in a newly deployed artifact or faulty configuration file.

## Recommended Remediation
- Primary Action: `rollback` (revert immediately to the prior known-stable build version).
- Note: Policy mandates human approval for all rollback actions.
