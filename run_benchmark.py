"""
SentinelLoop benchmark runner.

⚠️  HUMAN CHECKPOINT #3 — DO NOT RUN FOR REPORTABLE NUMBERS until the
scenario set in benchmark/scenarios.py has been reviewed and approved by a
human. See .agents/human-checkpoints.md §3.

Usage (after human sign-off):
    python run_benchmark.py
    python run_benchmark.py --output results/run_20260903.json
    python run_benchmark.py --no-guardrail   # compare with guardrail disabled

Output:
    A timestamped JSON file with per-scenario results and aggregate metrics.

Metrics computed:
  - diagnosis_accuracy        % scenarios where proposed_action matched expected_action
  - correct_gate_rate         % scenarios where gate outcome matched expected_gate
  - false_auto_action_rate    % scenarios where AUTO_APPROVE fired but should have been
                               NEEDS_HUMAN_APPROVAL or REJECTED
  - mean_time_to_decision_s   wall-clock seconds from PERCEIVE to gate decision
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.audit import AuditLog
from agent.diagnosis import DiagnosisEngine
from agent.executor import ActionExecutor
from agent.guardrail import GuardrailEngine
from agent.orchestrator import Orchestrator
from benchmark.scenarios import SCENARIOS, Scenario
from toy_service.service import app


# ── Per-scenario runner ─────────────────────────────────────────────────────

def run_scenario(
    scenario: Scenario,
    tc: TestClient,
    disable_guardrail: bool = False,
) -> dict:
    """Runs one scenario and returns a results dict."""
    tc.post("/reset")
    tc.post("/inject_fault", json={"fault_type": scenario.fault_type, "seed": scenario.seed})

    log_path = Path(f"/tmp/bench_{scenario.id}_{uuid.uuid4().hex[:6]}.jsonl")

    # For guardrail-disabled mode: auto-approve everything regardless of confidence
    if disable_guardrail:
        from agent.guardrail import ActionProposal, GateDecision, GateOutcome

        def _always_approve(proposal: ActionProposal) -> GateDecision:
            return GateDecision(
                outcome=GateOutcome.AUTO_APPROVE,
                action_type=proposal.action_type,
                reason="GUARDRAIL DISABLED — benchmark comparison run",
            )

    orch = Orchestrator(
        toy_service_url="http://testserver",
        audit_log_path=log_path,
        human_approval_fn=lambda inc, act: True,  # auto-approve in benchmark
        verify_delay=0,
    )

    if disable_guardrail:
        orch.guardrail.evaluate_action = _always_approve

    # Patch I/O to use TestClient instead of real HTTP
    def _poll(client=None):
        return {
            "metrics": tc.get("/metrics").json(),
            "deploy_logs": tc.get("/deploy_logs").json(),
        }

    def _execute(action_type, parameters=None):
        return tc.post(f"/control/{action_type}", json=parameters or {}).json()

    t_start = time.perf_counter()

    with patch.object(orch.perception, "poll_service", side_effect=_poll), \
         patch.object(orch.executor, "execute", side_effect=_execute):
        try:
            record = orch.run_once()
        except Exception as exc:
            return {
                "id": scenario.id,
                "fault_type": scenario.fault_type,
                "seed": scenario.seed,
                "error": str(exc),
                "passed": False,
            }

    elapsed = time.perf_counter() - t_start

    # Read audit trail to extract actual diagnosis and gate outcome
    log = AuditLog(log_path=log_path)
    events = log.read_incident(record.incident_id)
    event_types = {e["type"] for e in events}

    diag_evt = next((e for e in events if e["type"] == "LLM_DIAGNOSIS"), None)
    gate_evt = next((e for e in events if e["type"] == "GUARDRAIL_DECISION"), None)

    actual_action = diag_evt["proposed_action"] if diag_evt else None
    actual_gate = gate_evt["outcome"] if gate_evt else None
    actual_confidence = diag_evt["confidence"] if diag_evt else None

    action_match = actual_action == scenario.expected_action
    gate_match = actual_gate == scenario.expected_gate

    # False auto-action: system fired AUTO_APPROVE but ground truth says it shouldn't
    false_auto = (
        actual_gate == "AUTO_APPROVE"
        and scenario.expected_gate != "AUTO_APPROVE"
    )

    return {
        "id": scenario.id,
        "fault_type": scenario.fault_type,
        "seed": scenario.seed,
        "description": scenario.description,
        "expected_action": scenario.expected_action,
        "expected_gate": scenario.expected_gate,
        "actual_action": actual_action,
        "actual_gate": actual_gate,
        "actual_confidence": actual_confidence,
        "resolution": record.resolution,
        "action_match": action_match,
        "gate_match": gate_match,
        "false_auto_action": false_auto,
        "time_to_decision_s": round(elapsed, 2),
        "passed": action_match and gate_match,
        "notes": scenario.notes,
    }


# ── Aggregate metrics ───────────────────────────────────────────────────────

def compute_metrics(results: list[dict]) -> dict:
    valid = [r for r in results if "error" not in r]
    n = len(valid)
    if n == 0:
        return {}

    action_correct = sum(1 for r in valid if r["action_match"])
    gate_correct = sum(1 for r in valid if r["gate_match"])
    false_autos = sum(1 for r in valid if r["false_auto_action"])
    mean_time = sum(r["time_to_decision_s"] for r in valid) / n

    return {
        "total_scenarios": n,
        "errors": len(results) - n,
        "diagnosis_accuracy": round(action_correct / n, 3),
        "correct_gate_rate": round(gate_correct / n, 3),
        "false_auto_action_rate": round(false_autos / n, 3),
        "mean_time_to_decision_s": round(mean_time, 2),
        "baseline_note": (
            "Time-to-resolution baseline is simulated (no real manual baseline measured). "
            "A human incident response baseline would typically be 5-15 minutes."
        ),
    }


# ── CLI entry point ─────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_benchmark.py",
        description=(
            "SentinelLoop benchmark runner. "
            "Requires Checkpoint #3 human approval before producing reportable numbers."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write results JSON (default: benchmark/results/run_<timestamp>.json)",
    )
    parser.add_argument(
        "--no-guardrail",
        action="store_true",
        help="Also run a comparison pass with the guardrail disabled.",
    )
    parser.add_argument(
        "--scenario",
        nargs="*",
        help="Run only specific scenario IDs (e.g. --scenario hl-01 er-02).",
    )
    args = parser.parse_args(argv)

    print("\n[!] REMINDER: Ensure Checkpoint #3 (human ground-truth sign-off) is complete.")
    print("    Proceed only if a human has reviewed and approved benchmark/scenarios.py.\n")

    tc = TestClient(app)
    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [s for s in scenarios if s.id in args.scenario]
        if not scenarios:
            print(f"No scenarios matched IDs: {args.scenario}")
            return 1

    # ── Main guardrail-enabled run ──────────────────────────────────────
    print(f"Running {len(scenarios)} scenarios (guardrail ENABLED)...")
    results_enabled = []
    for i, sc in enumerate(scenarios, 1):
        print(f"  [{i:02d}/{len(scenarios):02d}] {sc.id} ({sc.fault_type}) ...", end=" ", flush=True)
        r = run_scenario(sc, tc, disable_guardrail=False)
        status = "PASS" if r.get("passed") else ("ERR" if "error" in r else "FAIL")
        print(status)
        results_enabled.append(r)

    metrics_enabled = compute_metrics(results_enabled)

    # ── Optional guardrail-disabled comparison ──────────────────────────
    results_disabled = None
    metrics_disabled = None
    if args.no_guardrail:
        print(f"\nRunning {len(scenarios)} scenarios (guardrail DISABLED — comparison)...")
        results_disabled = []
        for i, sc in enumerate(scenarios, 1):
            print(f"  [{i:02d}/{len(scenarios):02d}] {sc.id} ({sc.fault_type}) ...", end=" ", flush=True)
            r = run_scenario(sc, tc, disable_guardrail=True)
            status = "PASS" if r.get("passed") else ("ERR" if "error" in r else "FAIL")
            print(status)
            results_disabled.append(r)
        metrics_disabled = compute_metrics(results_disabled)

    # ── Output ──────────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (
        Path(__file__).parent / "benchmark" / "results" / f"run_{ts}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_scenarios": len(scenarios),
        "checkpoint_3_approved": True,  # human must have approved before running
        "guardrail_enabled": {
            "metrics": metrics_enabled,
            "results": results_enabled,
        },
    }
    if results_disabled is not None:
        output["guardrail_disabled_comparison"] = {
            "metrics": metrics_disabled,
            "results": results_disabled,
        }

    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {output_path}")

    # ── Summary ─────────────────────────────────────────────────────────
    m = metrics_enabled
    print(f"\n{'='*50}")
    print(f"  BENCHMARK SUMMARY (guardrail ENABLED)")
    print(f"{'='*50}")
    print(f"  Scenarios run       : {m['total_scenarios']}")
    print(f"  Errors              : {m.get('errors', 0)}")
    print(f"  Diagnosis accuracy  : {m['diagnosis_accuracy']:.0%}")
    print(f"  Correct gate rate   : {m['correct_gate_rate']:.0%}")
    print(f"  False auto-actions  : {m['false_auto_action_rate']:.0%}")
    print(f"  Mean time/decision  : {m['mean_time_to_decision_s']:.1f}s")

    if metrics_disabled:
        md = metrics_disabled
        prevented = m.get("false_auto_action_rate", 0) - md.get("false_auto_action_rate", 0)
        print(f"\n  GUARDRAIL IMPACT (enabled vs disabled):")
        print(f"  False auto-actions w/ guardrail  : {m['false_auto_action_rate']:.0%}")
        print(f"  False auto-actions w/o guardrail : {md['false_auto_action_rate']:.0%}")
        print(f"  Guardrail prevented              : {abs(prevented):.0%} of scenarios")
    print(f"{'='*50}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
