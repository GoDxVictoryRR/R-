# Project Notes & Checkpoint Log

## Status
- **Phase 1 (Toy Service + Fault Injector)**: Completed. Verified determinism and endpoint controls across 8 unit tests.
- **Phase 2 (Perception Layer + Runbooks)**: Completed. 6 Runbooks created; keyword matcher and threshold evaluator verified across 5 unit tests.
- **Phase 3 (Diagnosis Module)**: Completed. LLM client integration in `agent/diagnosis.py` verified with live NVIDIA model (`openai/gpt-oss-20b`) and 8 unit tests.
- **Phase 4 (Guardrail Engine)**: Completed `agent/guardrail.py`. Enforces hardcoded safety rules (confidence >= 0.6, rollback human sign-off, scale rate limiting, no double-action without verify). 6 unit tests passing (27 total passing).
- **Phase 5 (Executor + Orchestrator)**: PENDING HUMAN CHECKPOINT #2.

---

## Human Checkpoint #2 — Guardrail Engine Sign-off
- **Required**: Human review and approval of [`agent/guardrail.py`](file:///c:/Users/hardi/Downloads/R-/agent/guardrail.py).
- **Reason**: Mandated by `.agents/human-checkpoints.md` #2 before building `executor.py` or `orchestrator.py`.
