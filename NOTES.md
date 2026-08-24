# Project Notes & Checkpoint Log

## Status
- **Phase 1 (Toy Service + Fault Injector)**: Completed. Verified determinism and endpoint controls across 8 unit tests.
- **Phase 2 (Perception Layer + Runbooks)**: Completed. 6 Runbooks created; keyword matcher and threshold evaluator verified across 5 unit tests (13 total passing).
- **Phase 3 (Diagnosis Module)**: PENDING HUMAN CHECKPOINT #1.

---

## Human Checkpoint #1 — LLM Provider & API Key
- **Required**: An API key and choice of provider (`openai` or `anthropic`).
- **Location**: `.env` at the repository root with:
  ```env
  LLM_PROVIDER=openai  # or anthropic
  LLM_API_KEY=sk-...
  ```
- **Reason**: Mandated by `.agents/human-checkpoints.md` #1 before building the diagnosis LLM call module.
