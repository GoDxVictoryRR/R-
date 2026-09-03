"""
Read-only timeline viewer for SentinelLoop audit logs.

Replays a past incident's full decision trail from audit.jsonl alone —
no other state or running service required.

Usage (CLI):
    python -m agent.timeline                          # list all incidents
    python -m agent.timeline <incident_id>            # full trail for one incident
    python -m agent.timeline --log path/to/audit.jsonl <incident_id>

Output is a formatted table showing every event in chronological order.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.audit import AuditLog, _DEFAULT_LOG_PATH


# ── Formatting helpers ─────────────────────────────────────────────────────

_COL_WIDTH = 80
_DIVIDER = "─" * _COL_WIDTH

_EVENT_LABELS = {
    "INCIDENT_OPENED":    "📂 INCIDENT OPENED",
    "STATE_TRANSITION":   "🔀 STATE",
    "LLM_DIAGNOSIS":      "🧠 DIAGNOSIS",
    "GUARDRAIL_DECISION": "🛡️  GUARDRAIL",
    "ACTION_EXECUTED":    "⚡ ACTION",
    "VERIFICATION":       "🔍 VERIFY",
    "HUMAN_APPROVAL":     "👤 HUMAN",
    "INCIDENT_CLOSED":    "✅ CLOSED",
}

_OUTCOME_COLORS = {
    "AUTO_APPROVE":           "\033[32m",   # green
    "NEEDS_HUMAN_APPROVAL":   "\033[33m",   # yellow
    "REJECTED":               "\033[31m",   # red
    "RESOLVED":               "\033[32m",
    "STILL_DEGRADED":         "\033[31m",
    "APPROVED":               "\033[32m",
    "DENIED":                 "\033[31m",
}
_RESET = "\033[0m"


def _colorize(text: str, color_key: str) -> str:
    color = _OUTCOME_COLORS.get(color_key, "")
    return f"{color}{text}{_RESET}" if color else text


def _fmt_event(evt: dict[str, Any]) -> list[str]:
    """Format a single audit event into a list of display lines."""
    label = _EVENT_LABELS.get(evt.get("type", ""), f"📋 {evt.get('type', '?')}")
    ts = evt.get("logged_at", "?")
    lines = [f"  {label}  [{ts}]"]

    t = evt.get("type", "")

    if t == "INCIDENT_OPENED":
        for reason in evt.get("breach_reasons", []):
            lines.append(f"    ⚠  {reason}")
        m = evt.get("metrics", {})
        if m:
            lines.append(
                f"    📊 error_rate={m.get('error_rate'):.3f}  "
                f"p99={m.get('p99_latency_ms'):.0f}ms  "
                f"mem={m.get('memory_utilization_pct'):.1f}%"
            )

    elif t == "STATE_TRANSITION":
        detail = f" — {evt['detail']}" if evt.get("detail") else ""
        lines.append(f"    {evt.get('from','?')} → {evt.get('to','?')}{detail}")

    elif t == "LLM_DIAGNOSIS":
        conf = evt.get("confidence", 0)
        action = evt.get("proposed_action", "?")
        lines.append(f"    Root cause : {evt.get('root_cause','?')}")
        lines.append(f"    Confidence : {conf:.0%}   Proposed action : {action}")
        if evt.get("reasoning"):
            lines.append(f"    Reasoning  : {evt['reasoning'][:120]}")

    elif t == "GUARDRAIL_DECISION":
        outcome = evt.get("outcome", "?")
        colored = _colorize(outcome, outcome)
        lines.append(f"    Action  : {evt.get('action_type','?')}")
        lines.append(f"    Outcome : {colored}")
        lines.append(f"    Reason  : {evt.get('reason','')}")

    elif t == "ACTION_EXECUTED":
        lines.append(f"    Action : {evt.get('action_type','?')}")
        result = evt.get("result", {})
        lines.append(f"    Result : {json.dumps(result)}")

    elif t == "VERIFICATION":
        verdict = evt.get("verdict", "?")
        colored = _colorize(verdict, verdict)
        lines.append(f"    Verdict : {colored}")
        m = evt.get("metrics_after", {})
        if m:
            lines.append(
                f"    Metrics : error_rate={m.get('error_rate',0):.3f}  "
                f"p99={m.get('p99_latency_ms',0):.0f}ms  "
                f"mem={m.get('memory_utilization_pct',0):.1f}%"
            )

    elif t == "HUMAN_APPROVAL":
        decision = evt.get("decision", "?")
        colored = _colorize(decision, decision)
        lines.append(f"    Action   : {evt.get('action_type','?')}")
        lines.append(f"    Decision : {colored}  (by {evt.get('by','?')})")

    elif t == "INCIDENT_CLOSED":
        resolution = evt.get("resolution", "?")
        colored = _colorize(resolution, resolution)
        lines.append(f"    Resolution : {colored}")

    return lines


# ── Public API ────────────────────────────────────────────────────────────

def print_incident_trail(incident_id: str, log: AuditLog) -> None:
    """Print the full decision trail for one incident."""
    events = log.read_incident(incident_id)
    if not events:
        print(f"No events found for incident '{incident_id}'.")
        return

    print()
    print(_DIVIDER)
    print(f"  INCIDENT TRAIL  —  {incident_id}")
    print(_DIVIDER)

    for evt in events:
        for line in _fmt_event(evt):
            print(line)
        print()

    print(_DIVIDER)
    print()


def print_incident_list(log: AuditLog) -> None:
    """Print a summary table of all incidents in the log."""
    all_events = log.read_all()
    if not all_events:
        print("Audit log is empty.")
        return

    # Group by incident_id
    incidents: dict[str, list[dict]] = {}
    for evt in all_events:
        iid = evt.get("incident_id")
        if iid:
            incidents.setdefault(iid, []).append(evt)

    print()
    print(_DIVIDER)
    print(f"  {'INCIDENT ID':<20}  {'EVENTS':>6}  {'RESOLUTION':<25}  {'OPENED AT'}")
    print(_DIVIDER)

    for iid, evts in incidents.items():
        opened = next((e.get("logged_at","?") for e in evts if e.get("type") == "INCIDENT_OPENED"), "?")
        closed = next((e for e in evts if e.get("type") == "INCIDENT_CLOSED"), None)
        resolution = closed.get("resolution", "IN PROGRESS") if closed else "IN PROGRESS"
        colored_res = _colorize(resolution, resolution)
        print(f"  {iid:<20}  {len(evts):>6}  {colored_res:<25}  {opened}")

    print(_DIVIDER)
    print()


# ── CLI entry point ────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.timeline",
        description="Replay SentinelLoop incident decision trails from the audit log.",
    )
    parser.add_argument("incident_id", nargs="?", help="Incident ID to replay (omit to list all).")
    parser.add_argument(
        "--log",
        default=str(_DEFAULT_LOG_PATH),
        help=f"Path to audit.jsonl (default: {_DEFAULT_LOG_PATH})",
    )
    args = parser.parse_args(argv)

    log = AuditLog(log_path=Path(args.log))

    if args.incident_id:
        print_incident_trail(args.incident_id, log)
    else:
        print_incident_list(log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
