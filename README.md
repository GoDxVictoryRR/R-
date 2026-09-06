# SentinelLoop — Guarded Autonomous Incident Response Agent

![Build Status](https://img.shields.io/badge/tests-52%2F52%20passing-brightgreen?style=for-the-badge&logo=pytest)
![Architecture](https://img.shields.io/badge/architecture-6--State%20FSM-blue?style=for-the-badge)
![LLM Engine](https://img.shields.io/badge/LLM-DeepSeek--V4--Flash%20(NVIDIA%20NIM)-orange?style=for-the-badge)
![Safety Core](https://img.shields.io/badge/Safety-Air--Gapped%20Guardrail-red?style=for-the-badge)
![Benchmark](https://img.shields.io/badge/Benchmark-16%20Scenarios%20%7C%2075%25%20Gate%20Acc-purple?style=for-the-badge)

**SentinelLoop** is a production-grade portfolio project demonstrating an autonomous Site Reliability Engineering (SRE) incident response agent. It detects injected outages in a target microservice, diagnoses root causes via high-throughput LLM telemetry analysis, routes proposed actions through an air-gapped, deterministic policy engine, executes approved remediations, and verifies resolution—all tracked by an append-only compliance audit trail.

📄 **Comprehensive Project & Interview Guide**: [`SentinelLoop_Project_Summary_Interview_Guide.pdf`](SentinelLoop_Project_Summary_Interview_Guide.pdf)

---

## 💡 Overview & Core Philosophy

### The Industry Problem
When high-severity incidents strike distributed systems, Mean Time to Detect and Resolve (MTTD/MTTR) directly dictates business revenue losses. While Large Language Models (LLMs) excel at root-cause analysis from logs and metrics, engineering organizations strictly refuse to grant autonomous write-access to production systems.

Unconstrained LLMs suffer from well-known failure modes:
- **Hallucinated CLI flags & dangerous commands** (e.g., indiscriminate `rm -rf` or invalid kubectl syntax).
- **Non-deterministic compliance** (a safety rule followed 95% of the time leaves a catastrophic 5% blast-radius risk).
- **Flapping & thrashing state** (taking rapid back-to-back actions without waiting for system state to stabilize).

### The SentinelLoop Solution: Dual-Layer Architecture
SentinelLoop addresses the trust bottleneck by separating **stochastic reasoning** from **deterministic safety enforcement**:

> 🧠 **"AI Diagnoses, Deterministic Rules Decide"**

The LLM acts purely as an untrusted advisory component. It proposes a single action from a strictly closed allow-list. Before any change touches the target service, an **unbypassable, non-LLM Guardrail Engine** evaluates company safety policies, action blast radius, and historical rate limits in pure Python.

```
+-----------------------------------------------------------------------------------+
|                                   SENTINELLOOP                                    |
|                                                                                   |
|  +-------------------+      +-------------------+      +-----------------------+  |
|  |  Perception Layer | ---> | Diagnosis (LLM)   | ---> | Proposed Action       |  |
|  |  (Metrics & Logs) |      | (DeepSeek-V4-NIM) |      | (restart, scale, ...) |  |
|  +-------------------+      +-------------------+      +-----------------------+  |
|                                                                    |              |
|                                 ================================== | ===========  |
|                                 HARD AIR-GAP ARCHITECTURAL BOUNDARY |              |
|                                 ================================== v              |
|                                                        +-----------------------+  |
|                                                        | GUARDRAIL ENGINE      |  |
|                                                        | (Pure Python Rules)   |  |
|                                                        +-----------------------+  |
|                                                                    |              |
|                                      +-----------------------------+              |
|                                      |                                            |
|                                      v                                            v
|                             [ AUTO_APPROVE ]                            [ NEEDS_HUMAN ]
|                                      |                                            |
|                                      v                                            |
|                           +---------------------+                                 |
|                           | Sandboxed Executor  |                                 |
|                           +---------------------+                                 |
+--------------------------------------|--------------------------------------------+
                                       v
                             +-------------------+
                             | Target Service API|
                             +-------------------+
```

---

## 🛠️ Key Features & Capabilities

- ⚡ **6.4-Second Mean Time to Decision**: Automates detection, diagnosis, gating, and action in under 10 seconds (vs 5–15 min manual human baseline).
- 🛡️ **Air-Gapped Safety Guardrail**: Evaluates confidence floors, mandatory human approvals, rate-limiting, and anti-flapping invariants without LLM involvement.
- 🎯 **Closed Allow-List Execution**: Restricts remediations strictly to `restart`, `scale_up`, `scale_down`, `rollback`, or `noop`—zero OS subprocess execution.
- 📊 **Empirical 16-Scenario Benchmark**: Measures true diagnosis accuracy (56%), gate decision accuracy (75%), and safety impact (cut false auto-actions from 60% down to 18.8%).
- 🔬 **52/52 Passing Tests**: 48 unit tests + 4 live end-to-end integration tests connecting directly to NVIDIA NIM API.
- 📜 **Immutable Audit Logging**: Every telemetry capture, prompt hash, guardrail decision, and execution result is logged to append-only JSON Lines with a CLI replay timeline.

---

## 🏗️ System Architecture & 6-State FSM

SentinelLoop is implemented as a formal **Finite State Machine (FSM)**:

```
[1. PERCEIVE] ---> [2. DIAGNOSE] ---> [3. PLAN] ---> [4. GATE] ---> [5. ACT] ---> [6. VERIFY]
```

| State | Module File | Description & Operation |
|---|---|---|
| **1. PERCEIVE** | [`agent/perception.py`](agent/perception.py) | Polls `/health`, `/metrics`, `/logs`, `/deploys`. Triggers when p95 latency > 2000ms, error rate > 5%, or CPU > 85%. Matches relevant markdown runbooks. |
| **2. DIAGNOSE** | [`agent/diagnosis.py`](agent/diagnosis.py) | Formats prompt with telemetry & runbooks; calls NVIDIA NIM (`DeepSeek-V4-Flash`) with Pydantic JSON schema constraints (`confidence`, `root_cause`, `evidence`). |
| **3. PLAN** | [`agent/diagnosis.py`](agent/diagnosis.py) | Maps diagnosis hypothesis to a single candidate action from the closed allow-list (`restart`, `scale_up`, `scale_down`, `rollback`, `noop`). |
| **4. GATE** | [`agent/guardrail.py`](agent/guardrail.py) | **The Core Innovation**. Hard-coded Python policy engine evaluates proposal against company invariants, action history, and rate limits. |
| **5. ACT** | [`agent/executor.py`](agent/executor.py) | Sandboxed HTTP dispatcher. Only allowed file to call target service `/control/*` endpoints. *Forbidden from importing LLM code*. |
| **6. VERIFY** | [`agent/orchestrator.py`](agent/orchestrator.py) | Conducts post-remediation health check. If resolved, closes incident; if degraded, escalates to human on-call with audit trail. |

---

## 🛡️ The Guardrail Safety Engine (Core Innovation)

The Guardrail Engine ([`agent/guardrail.py`](agent/guardrail.py)) enforces 5 non-negotiable operational safety rules:

| Rule # | Condition | Outcome | Operational Rationale |
|---|---|---|---|
| **Rule 1** | `confidence < 0.60` | `REJECTED` | Low AI confidence forces immediate escalation to human on-call. Prevents guesswork under noisy telemetry. |
| **Rule 2** | Action == `rollback` | `NEEDS_HUMAN_APPROVAL` | Rollbacks carry high blast-radius (database schema mismatches, data loss). Requires human sign-off regardless of confidence. |
| **Rule 3** | Action == `restart` & `conf ≥ 0.6` | `AUTO_APPROVE` | Low-risk remediation for transient worker deadlocks or memory leaks. Resolves outages rapidly. |
| **Rule 4** | Action == `scale` (> 3 in 10m) | `REJECTED` (Rate-Limited) | Caps automated scaling events to prevent cloud bill explosions and runaway autoscaling loops. |
| **Rule 5** | Consecutive action without `VERIFY` | `REJECTED` | Prohibits taking back-to-back actions without verifying the health outcome of the previous remediation first. |

### Architectural Import Boundary
To guarantee safety invariants, [`agent/guardrail.py`](agent/guardrail.py) and [`agent/executor.py`](agent/executor.py) have a strict lint-enforced boundary: **they cannot import any LLM module or API client**. Even if the LLM experiences prompt injection or extreme hallucination, the guardrail engine remains unaffected.

---

## 📊 Empirical Evaluation & Benchmark Results

All numbers are derived from the frozen 16-scenario benchmark ([`benchmark/results/run_v2.json`](benchmark/results/run_v2.json)). Ground truth was committed and reviewed at **Human Checkpoint #3**.

### Benchmark Performance Summary

| Metric | Score | Detail |
|---|---|---|
| **Diagnosis Accuracy** | **56.2%** (9/16) | Exact match on root-cause action under complex multi-variable faults |
| **Correct Gate Decision Rate** | **75.0%** (12/16) | Guardrail selected the correct safety path (`AUTO_APPROVE` vs `NEEDS_HUMAN` vs `REJECTED`) |
| **False Auto-Action Rate** | **18.8%** (3/16) | Reduced from **60%** in unguarded baseline |
| **Mean Time to Decision** | **6.4 seconds** | From initial anomaly detection to gated action decision |
| **Automated Test Coverage** | **52 / 52 Passing** | 48 unit tests + 4 live end-to-end integration tests |

### Safety Impact Comparison

```
Unguarded LLM (Pilot):  [==================== 60% Unsafe Auto-Actions ====================]
Guarded Agent (v2):    [====== 18.8% ======] (68% Relative Reduction in Dangerous Actions)
```

### Failure Modes Analysis
Of the 7 failed scenarios in `run_v2.json`:
- **4 scenarios** were valid alternative mitigations (e.g., LLM chose `restart` over `scale` for high latency—both resolved the issue).
- **1 scenario** failed due to low LLM confidence $\rightarrow$ correctly **`REJECTED`** by Rule 1.
- **3 true false auto-actions** occurred where the LLM diagnosed high latency as thread starvation instead of a bad deployment, proposing `scale` at high confidence. The guardrail auto-approved the proposed action as designed, demonstrating that *diagnosis accuracy is the primary bottleneck, not safety enforcement*.

---

## 📁 Project Structure

```
.
├── agent/                      # Incident Response Agent Core
│   ├── audit.py                # Append-only JSON Lines event logging
│   ├── diagnosis.py            # NVIDIA NIM (DeepSeek-V4-Flash) structured LLM client
│   ├── executor.py             # Sandboxed HTTP control client (no subprocesses)
│   ├── guardrail.py            # Non-LLM deterministic policy engine
│   ├── orchestrator.py         # 6-stage finite state machine driver
│   ├── perception.py           # Metrics/logs scraping & runbook matcher
│   └── timeline.py             # CLI incident replay utility
├── benchmark/                  # Evaluation Harness & Ground Truth
│   ├── results/
│   │   ├── run_v2.json         # Authoritative 16-scenario benchmark dataset
│   │   └── run_initial.json    # Initial pilot comparison run dataset
│   └── scenarios.py            # 16 deterministic fault injection scenarios
├── runbooks/                   # Operational Runbooks (Markdown)
│   ├── bad_deploy.md           # Bad deployment rollback procedures
│   ├── cpu_spike.md            # Thread starvation & CPU scaling guide
│   ├── memory_leak.md          # OOM crash & restart runbook
│   └── upstream_timeout.md     # Circuit breaker & retry policy
├── scripts/                    # Utility & Document Generation Scripts
│   └── generate_pdf.py         # Playwright-based PDF summary generator
├── tests/                      # Pytest Suite (52/52 Passing)
│   ├── test_audit_timeline.py  # Audit logging unit tests
│   ├── test_diagnosis.py       # Structured output & schema validation tests
│   ├── test_executor.py        # Sandboxed dispatch & import boundary tests
│   ├── test_fault_injector.py  # Fault injection seed determinism tests
│   ├── test_guardrail.py       # Policy rule & rate limiting unit tests
│   ├── test_integration.py     # Live E2E integration tests (NVIDIA NIM)
│   ├── test_orchestrator.py    # FSM state transition tests
│   ├── test_perception.py     # Telemetry threshold & runbook tests
│   └── test_toy_service.py     # Microservice control & metrics tests
├── toy_service/                # Target Microservice Ecosystem
│   ├── fault_injector.py       # Seeded fault simulator (CPU, OOM, Deploys)
│   ├── service.py              # FastAPI microservice (`/health`, `/metrics`, `/control/*`)
│   └── state.py                # In-memory service state container
├── .env.example                # Environment variable template
├── NOTES.md                    # Explicit out-of-scope backlog & architectural notes
├── README.md                   # Project documentation
├── SentinelLoop_Project_Summary_Interview_Guide.pdf # Interview PDF guide
├── run_agent.py                # Single-incident CLI entrypoint
└── run_benchmark.py            # Evaluation benchmark runner CLI
```

---

## ⚡ Installation & Setup

### Prerequisites
- **Python 3.10+** (Tested on Python 3.13.7)
- **NVIDIA NIM API Key** (Free tier available at [build.nvidia.com](https://build.nvidia.com/))

### 1. Clone & Environment Setup
```bash
git clone https://github.com/GoDxVictoryRR/R-.git
cd R-

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install fastapi uvicorn httpx python-dotenv openai pytest playwright
```

### 2. Configure Credentials
Copy `.env.example` to `.env` and set your NVIDIA NIM credentials:
```bash
cp .env.example .env
```
Edit `.env`:
```ini
LLM_API_KEY=nvapi-your-nvidia-nim-key-here
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL_NAME=deepseek-ai/deepseek-v4-flash-0731
```

---

## 🚀 Quick Start & Usage

### Step 1: Start the Target Service
Launch the FastAPI microservice in one terminal:
```bash
uvicorn toy_service.service:app --port 8000 --reload
```

### Step 2: Trigger an Incident & Run Agent
In a second terminal, inject a fault and run the SentinelLoop agent:
```bash
# Inject a memory leak outage and run agent loop
python run_agent.py --inject memory_leak

# Other supported faults: bad_deploy, cpu_spike, upstream_timeout
python run_agent.py --inject bad_deploy
```

### Step 3: Inspect Audit Trail & Incident Timeline
View historical incidents recorded in the append-only log:
```bash
# List all recorded incidents
python -m agent.timeline

# Replay detailed step-by-step decision trail for a specific incident
python -m agent.timeline <incident_id>
```

### Step 4: Run the 16-Scenario Benchmark
Execute the complete evaluation suite against all fault scenarios:
```bash
python run_benchmark.py --output benchmark/results/my_run.json
```

---

## 🧪 Test Suite (52/52 Passing)

The project includes 52 automated tests covering unit logic and live integration.

```bash
# Run fast offline unit tests (48 tests)
pytest tests/ --ignore=tests/test_integration.py

# Run live E2E integration tests (requires valid LLM_API_KEY)
pytest tests/test_integration.py

# Run all 52 tests together
pytest tests/
```

| Module Test File | Tests | Functional Coverage |
|---|---|---|
| `test_toy_service.py` | 4 | Endpoint responses, fault injection resets |
| `test_fault_injector.py` | 4 | Seed determinism, state transitions |
| `test_perception.py` | 5 | SLA threshold breaches, runbook retrieval |
| `test_diagnosis.py` | 8 | Pydantic schema parsing, prompt formatting, fallbacks |
| `test_guardrail.py` | 6 | All 5 safety rules, sliding-window rate limiting |
| `test_executor.py` | 6 | Sandboxed HTTP dispatch, closed allow-list validation |
| `test_orchestrator.py` | 5 | FSM state machine transitions, retry loops |
| `test_audit_timeline.py` | 10 | Event serialization, CLI timeline replay |
| **`test_integration.py`** | **4** | **Live e2e loops with NVIDIA NIM API** |

---

## 🤝 Human Checkpoints & Compliance

To maintain safety during development, SentinelLoop enforced 4 mandatory human review gates (documented in [`.agents/human-checkpoints.md`](.agents/human-checkpoints.md)):

| # | Checkpoint | Status | Verification Detail |
|---|---|---|---|
| **1** | LLM API Key & Model Setup | ✅ Cleared | NVIDIA NIM endpoint validated with zero secrets in git. |
| **2** | Guardrail Engine Sign-off | ✅ Cleared | Policy rules & import boundary verified against spec. |
| **3** | Benchmark Ground Truth Sign-off | ✅ Cleared | Scenario labels frozen before running evaluation. |
| **4** | Final Code & Safety Review | ✅ Cleared | Complete code review, 52/52 tests passing, final audit. |

---

## 💼 Resume & Interview Reference Guide

For job applications and technical interviews, SentinelLoop provides a structured narrative:

- 📄 **PDF Download**: [`SentinelLoop_Project_Summary_Interview_Guide.pdf`](SentinelLoop_Project_Summary_Interview_Guide.pdf)
- 🛠️ **Re-generate PDF Script**: `python scripts/generate_pdf.py`

### 60-Second Interview Pitch
> *"SentinelLoop is an autonomous SRE agent I built to solve the trust bottleneck with AI in operations. While LLMs excel at root-cause diagnosis, engineering teams cannot risk unconstrained AI executing raw shell commands on production clusters. I built a dual-layer architecture: an LLM diagnoses outages from telemetry using operational runbooks, but a deterministic, non-LLM guardrail engine sits between the AI and the service. The guardrail enforces confidence cutoffs, mandatory human approvals for high-risk actions like rollbacks, and rate-limiting. On a 16-scenario benchmark, the agent delivered a 6.4-second mean time to decision and reduced false autonomous actions by 68%."*

---

## 📜 License & Safety Guarantee

Distributed under the **MIT License**.

⚠️ **Global Safety Invariant**: SentinelLoop is designed strictly for portfolio demonstration against the included toy FastAPI microservice. **It does not touch real cloud infrastructure or external production environments.**
