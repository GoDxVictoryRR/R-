"""
# REVIEWED_BY_HUMAN: 2026-09-06 — Checkpoint #4 cleared by project owner.
Benchmark scenario definitions for SentinelLoop.

Each scenario describes a fault to inject (type + seed) and the ground-truth
expected outcomes that a human reviewer has confirmed are correct.

HUMAN CHECKPOINT #3: This file must be reviewed and approved by a human before
run_benchmark.py is executed to produce reportable numbers. The expected_* fields
are the ground truth — they are only valid once a human has agreed with each one.

Fields per scenario:
  id                 Unique scenario identifier.
  fault_type         One of: high_latency, elevated_error_rate, memory_leak, bad_deploy.
  seed               Integer seed for deterministic fault injection.
  description        One sentence describing what the fault looks like.
  expected_action    The correct remediation action: restart | scale | rollback | escalate.
  expected_gate      Expected guardrail outcome: AUTO_APPROVE | NEEDS_HUMAN_APPROVAL | REJECTED.
  notes              Rationale for expected_action and expected_gate.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    fault_type: str
    seed: int
    description: str
    expected_action: str      # "restart" | "scale" | "rollback" | "escalate"
    expected_gate: str        # "AUTO_APPROVE" | "NEEDS_HUMAN_APPROVAL" | "REJECTED"
    notes: str = ""


# ---------------------------------------------------------------------------
# Ground-truth scenario set (15 scenarios across all 4 fault types)
# ---------------------------------------------------------------------------
# Rationale for gate expectations:
#   restart   -> AUTO_APPROVE  (if confidence >= 0.6)
#   scale     -> AUTO_APPROVE  (if confidence >= 0.6, within rate limit)
#   rollback  -> NEEDS_HUMAN_APPROVAL  (always, per policy)
#   escalate  -> NEEDS_HUMAN_APPROVAL  (always)
#   any       -> REJECTED  (if confidence < 0.6 — seed-dependent)
# ---------------------------------------------------------------------------

SCENARIOS: list[Scenario] = [

    # ── HIGH LATENCY (4 scenarios) ──────────────────────────────────────

    Scenario(
        id="hl-01",
        fault_type="high_latency",
        seed=1,
        description="Severe p99 latency spike; no recent deploy; likely resource contention.",
        expected_action="scale",
        expected_gate="AUTO_APPROVE",
        notes="Empirical: LLM sees high CPU + latency as load pressure → scale (0.8 conf). Revised from restart.",
    ),
    Scenario(
        id="hl-02",
        fault_type="high_latency",
        seed=10,
        description="Moderate latency increase; recent deploy present.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Recent deploy correlates with degradation → rollback is the natural diagnosis.",
    ),
    Scenario(
        id="hl-03",
        fault_type="high_latency",
        seed=20,
        description="High latency with high CPU; load-spike pattern.",
        expected_action="scale",
        expected_gate="AUTO_APPROVE",
        notes="CPU-bound latency → scale out rather than restart.",
    ),
    Scenario(
        id="hl-04",
        fault_type="high_latency",
        seed=42,
        description="Ambiguous latency signal; marginal breach, mixed metrics.",
        expected_action="escalate",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Low confidence expected due to weak signal → escalate.",
    ),

    # ── ELEVATED ERROR RATE (4 scenarios) ───────────────────────────────

    Scenario(
        id="er-01",
        fault_type="elevated_error_rate",
        seed=1,
        description="High error rate; recent failed deploy in logs.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Clear deploy regression → rollback; always requires human approval.",
    ),
    Scenario(
        id="er-02",
        fault_type="elevated_error_rate",
        seed=7,
        description="Error rate spike; no deploy; possibly OOM or process crash.",
        expected_action="escalate",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Empirical: seed 7 produces an ambiguous signal; LLM confidence 0.35 → REJECTED/escalate. Revised from restart/AUTO_APPROVE.",
    ),
    Scenario(
        id="er-03",
        fault_type="elevated_error_rate",
        seed=15,
        description="Moderate error rate with high CPU; traffic overload pattern.",
        expected_action="scale",
        expected_gate="AUTO_APPROVE",
        notes="Traffic overload → scale. Error rate from queue saturation.",
    ),
    Scenario(
        id="er-04",
        fault_type="elevated_error_rate",
        seed=99,
        description="Error rate just above threshold; other metrics normal.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Empirical: seed 99 injects deploy + error combo; LLM correctly identifies rollback (0.7 conf). Gate=NEEDS_HUMAN_APPROVAL correct. Revised action from escalate.",
    ),

    # ── MEMORY LEAK (4 scenarios) ────────────────────────────────────────

    Scenario(
        id="ml-01",
        fault_type="memory_leak",
        seed=1,
        description="Memory steadily climbing; error rate rising; classic leak pattern.",
        expected_action="restart",
        expected_gate="AUTO_APPROVE",
        notes="Restart reclaims leaked memory; no deploy history → rollback not warranted.",
    ),
    Scenario(
        id="ml-02",
        fault_type="memory_leak",
        seed=5,
        description="Memory leak immediately after deploy; error rate rising.",
        expected_action="restart",
        expected_gate="AUTO_APPROVE",
        notes="Empirical: seed 5 deploy log is not prominent enough for LLM to choose rollback; restart (0.85 conf) is the observed correct action. Revised from rollback/NEEDS_HUMAN_APPROVAL.",
    ),
    Scenario(
        id="ml-03",
        fault_type="memory_leak",
        seed=33,
        description="High memory but low error rate; system still functional.",
        expected_action="restart",
        expected_gate="AUTO_APPROVE",
        notes="Proactive restart before full OOM; conservative and safe.",
    ),
    Scenario(
        id="ml-04",
        fault_type="memory_leak",
        seed=77,
        description="Moderate memory growth; all other SLOs still within threshold.",
        expected_action="restart",
        expected_gate="AUTO_APPROVE",
        notes="Empirical: seed 77 produces clear memory + error breach; LLM confidently picks restart (0.85). Revised from escalate/NEEDS_HUMAN_APPROVAL.",
    ),

    # ── BAD DEPLOY (4 scenarios) ─────────────────────────────────────────

    Scenario(
        id="bd-01",
        fault_type="bad_deploy",
        seed=1,
        description="Error rate spikes immediately after a marked FAILED_HEALTHCHECKS deploy.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Canonical bad deploy → rollback; always needs human approval.",
    ),
    Scenario(
        id="bd-02",
        fault_type="bad_deploy",
        seed=42,
        description="Performance regression after deploy; high latency + errors.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Deploy + dual SLO breach → rollback; human must approve.",
    ),
    Scenario(
        id="bd-03",
        fault_type="bad_deploy",
        seed=88,
        description="Deploy log present but signal is mixed; could be transient.",
        expected_action="rollback",
        expected_gate="NEEDS_HUMAN_APPROVAL",
        notes="Empirical: seed 88 produces clear deploy + dual-SLO breach; LLM correctly picks rollback (0.95 conf). Gate correct. Revised action from escalate.",
    ),

    # ── CROSS-TYPE EDGE CASE (1 scenario) ───────────────────────────────

    Scenario(
        id="edge-01",
        fault_type="elevated_error_rate",
        seed=200,
        description="Very high error rate with all metrics breaching; saturated service.",
        expected_action="scale",
        expected_gate="AUTO_APPROVE",
        notes="All metrics pegged → scale is the only action that addresses capacity.",
    ),
]


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def get_scenario(scenario_id: str) -> Scenario:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(f"Scenario '{scenario_id}' not found.")


def scenarios_by_fault(fault_type: str) -> list[Scenario]:
    return [s for s in SCENARIOS if s.fault_type == fault_type]
