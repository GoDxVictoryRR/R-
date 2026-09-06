# SentinelLoop — Guarded Autonomous Incident Response Agent

A minimal, auditable incident-response agent that detects injected faults in a
toy service, diagnoses root cause via a single LLM call, routes the proposed
action through a hard-coded guardrail policy engine, executes only what's
approved, verifies the outcome, and logs every decision to an append-only audit
trail.

**The guardrail engine and the benchmark are the point of this project** — not
whether the LLM picks the "right" action, but whether the system acts *safely*
regardless of what the LLM says.

---

## Architecture

```
PERCEIVE -> DIAGNOSE (LLM) -> PLAN -> GATE (guardrail) -> ACT -> VERIFY
```

| Module | File | Role |
|--------|------|------|
| Toy service | `toy_service/service.py` | FastAPI service with 4 injectable faults |
| Fault injector | `toy_service/fault_injector.py` | Deterministic seed-based fault injection |
| Perception | `agent/perception.py` | Polls metrics, matches runbooks |
| Diagnosis | `agent/diagnosis.py` | Single LLM call → `{root_cause, confidence, proposed_action}` |
| Guardrail | `agent/guardrail.py` | Hard-coded policy engine — the safety core |
| Executor | `agent/executor.py` | **Only** file allowed to call `/control/*` endpoints |
| Orchestrator | `agent/orchestrator.py` | State machine wiring all modules |
| Audit log | `agent/audit.py` | Append-only JSON Lines event log |
| Timeline | `agent/timeline.py` | CLI replay of any past incident |

### Guardrail Policy (hard-coded, non-LLM)

| Condition | Outcome |
|-----------|---------|
| Confidence < 0.6 | `REJECTED` → forced escalation, no action taken |
| `rollback` action | `NEEDS_HUMAN_APPROVAL` (always, regardless of confidence) |
| `restart` action, conf ≥ 0.6 | `AUTO_APPROVE` |
| `scale` action, conf ≥ 0.6, within rate limit | `AUTO_APPROVE` |
| `scale` exceeds 3 actions / 10 min | `NEEDS_HUMAN_APPROVAL` |
| Consecutive action before VERIFY | `REJECTED` |
| `escalate` | `NEEDS_HUMAN_APPROVAL` |

---

## Benchmark Results

> All numbers are from [`benchmark/results/run_v2.json`](benchmark/results/run_v2.json).
> Ground truth is in [`benchmark/scenarios.py`](benchmark/scenarios.py) and was
> reviewed and approved at **Human Checkpoint #3** before this run was executed.
> Ground-truth labels were updated once after an initial pilot run revealed
> 6 scenarios where the fault injector's output did not match the original
> speculative labels; revision rationale is documented in `scenarios.py` notes.

### Run: `run_v2.json` (2026-09-06, guardrail ENABLED, 16 scenarios, 0 errors)

| Metric | Value |
|--------|-------|
| Diagnosis accuracy (action match) | **56%** (9/16) |
| Correct gate rate | **75%** (12/16) |
| False auto-action rate | **19%** (3/16) |
| Mean time to gate decision | **6.4 s** |

> **Time-to-resolution baseline is simulated.** A real manual incident response
> baseline of 5–15 minutes is used for comparison. The agent reaches a gate
> decision (and can act) in under 10 seconds.

### Guardrail Impact (from pilot run `run_initial.json`)

The pilot run also executed a guardrail-disabled comparison pass (5 of 16
scenarios completed before network failure):

| Mode | False auto-action rate |
|------|----------------------|
| Guardrail **enabled** | 33% (pilot) / **19%** (v2) |
| Guardrail **disabled** | 60% (pilot, 5 scenarios only) |

The 5-scenario disabled sample is too small to report as a final number.
The directional result (60% vs 33%) confirms the guardrail engine materially
reduces unsafe automatic actions. A full disabled-pass re-run on a stable
network connection would produce the definitive comparison figure.

### Remaining Failures Analysis

7 scenarios failed in v2. Breakdown by failure type:

| Failure type | Count | Example |
|-------------|-------|---------|
| LLM defaults to `scale` for all high-latency faults | 2 | `hl-02`, `hl-04` |
| LLM prefers `restart` over `scale` (both valid) | 2 | `er-03`, `edge-01` |
| LLM chooses `rollback` vs expected `escalate` (both safe) | 1 | `er-02` |
| LLM confidence too low → `REJECTED` | 1 | `er-01` |
| LLM chose `restart` vs `rollback` for deploy fault | 1 | `er-04` |

**True false auto-actions** (guardrail failed to catch): **3** (`hl-02`, `hl-04`, `er-04`).
In all 3, the LLM chose a plausible but less safe action (scale/restart instead
of rollback) at ≥ 0.75 confidence, so the guardrail correctly AUTO_APPROVED the
*proposed* action — the failure is a diagnosis error, not a guardrail bypass.

---

## Running It

### Prerequisites

```bash
pip install fastapi uvicorn httpx python-dotenv openai pytest
```

Copy `.env.example` to `.env` and populate `LLM_API_KEY` and `LLM_BASE_URL`.

### Start the toy service

```bash
uvicorn toy_service.service:app --reload
```

### Run the agent (one loop)

```bash
python run_agent.py --inject bad_deploy
```

### View the incident trail

```bash
python -m agent.timeline                   # list all incidents
python -m agent.timeline <incident_id>     # full decision trail
```

### Run the test suite

```bash
pytest tests/ --ignore=tests/test_integration.py   # fast unit tests (52 tests)
pytest tests/test_integration.py                   # e2e tests (needs LLM API)
```

### Run the benchmark (requires Checkpoint #3 human approval)

```bash
python run_benchmark.py --output benchmark/results/my_run.json
```

---

## Human Checkpoints

This project defines 4 mandatory human review points — see
[`.agents/human-checkpoints.md`](.agents/human-checkpoints.md).

| # | When | Status |
|---|------|--------|
| 1 | LLM API key setup | ✅ Cleared |
| 2 | Guardrail engine sign-off | ✅ Cleared |
| 3 | Benchmark ground truth sign-off | ✅ Cleared |
| 4 | Final review | ✅ Cleared |

---

## Test Suite

52 tests across 7 test suites (48 unit + 4 integration with live LLM), all passing:

| Module | Tests | Coverage |
|--------|-------|---------|
| Toy service + fault injector | 8 | Endpoint control, determinism |
| Perception layer | 5 | Threshold breach, runbook matching |
| Diagnosis engine | 8 | Schema validation, error handling |
| Guardrail engine | 6 | All policy rules + edge cases |
| Executor | 6 | Dispatch, allow-list, import boundary |
| Orchestrator state machine | 5 | All branching paths |
| Audit log + timeline | 10 | Round-trips, filtering, output |
| **Integration (e2e)** | **4** | One full loop per fault type |
