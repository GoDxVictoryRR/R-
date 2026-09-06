# Project Notes & Checkpoint Log

## Status
- **Phase 1 (Toy Service + Fault Injector)**: Complete. 8 unit tests.
- **Phase 2 (Perception Layer + Runbooks)**: Complete. 6 runbooks, 5 unit tests.
- **Phase 3 (Diagnosis Module)**: Complete. Live LLM verified on all 4 fault types, 8 unit tests.
- **Phase 4 (Guardrail Engine)**: Complete. 6 unit tests covering all policy rules.
- **Phase 5 (Executor + Orchestrator + Audit Log)**: Complete. 52 unit tests total, 4 e2e integration tests.
- **Phase 6 (Timeline CLI + Runner)**: Complete. `run_agent.py`, `agent/timeline.py`, 10 audit/timeline tests.
- **Phase 7 (Benchmark)**: Complete. 16 scenarios, 0 errors. Results in `benchmark/results/run_v2.json`.
- **Phase 8 (Final Review)**: PENDING Checkpoint #4.

---

## Benchmark Results (run_v2.json, 2026-09-06)

| Metric | Value |
|--------|-------|
| Diagnosis accuracy | 56% (9/16) |
| Correct gate rate | 75% (12/16) |
| False auto-action rate | 19% (3/16) |
| Mean time to gate decision | 6.4s |

Numbers are real, reproducible, and traceable to `benchmark/results/run_v2.json`.
Ground truth reviewed and approved at Checkpoint #3.

---

## Human Checkpoint #4 — Final Review (PENDING)

Required before project is marked complete.
See `.agents/human-checkpoints.md` §4 and `.agents/skills/final-review/SKILL.md`.

Action needed: human reads `guardrail.py` and `scenarios.py` end-to-end and
confirms they can explain every rule and every expected outcome without help.
