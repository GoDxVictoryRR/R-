"""
SentinelLoop standalone agent runner.

Starts the orchestrator against a running toy service, optionally injecting a
fault first for demonstration purposes.

Usage:
    # Start the agent loop against a running toy service (no fault injected):
    python run_agent.py

    # Inject a fault then run one orchestrator loop:
    python run_agent.py --inject high_latency

    # Run continuously, polling every 15 seconds:
    python run_agent.py --loop --interval 15

    # Use a custom toy service URL:
    python run_agent.py --url http://localhost:8000
"""

import argparse
import time
import sys

import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from agent.orchestrator import Orchestrator


def inject_fault(url: str, fault_type: str) -> None:
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(f"{url}/inject_fault", json={"fault_type": fault_type})
    if resp.status_code not in (200, 201):
        print(f"[warn] Fault injection returned HTTP {resp.status_code}: {resp.text[:200]}")
    else:
        print(f"[info] Injected fault: {fault_type}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_agent.py",
        description="SentinelLoop incident-response agent runner.",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Toy service base URL.")
    parser.add_argument(
        "--inject",
        choices=["high_latency", "elevated_error_rate", "memory_leak", "bad_deploy"],
        help="Fault type to inject before running.",
    )
    parser.add_argument("--loop", action="store_true", help="Run continuously (Ctrl-C to stop).")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds (--loop mode).")
    parser.add_argument("--log", default=None, help="Path to audit log (default: audit.jsonl at repo root).")
    args = parser.parse_args()

    log_path = Path(args.log) if args.log else None

    orch = Orchestrator(
        toy_service_url=args.url,
        audit_log_path=log_path,
        verify_delay=3,
    )

    if args.inject:
        inject_fault(args.url, args.inject)
        time.sleep(1)  # brief settle

    if args.loop:
        print(f"[info] Starting continuous loop (interval={args.interval}s). Press Ctrl-C to stop.")
        try:
            while True:
                record = orch.run_once()
                print(f"[info] Cycle complete — incident={record.incident_id} resolution={record.resolution}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[info] Agent stopped.")
    else:
        record = orch.run_once()
        print(f"[info] Done — incident={record.incident_id} resolution={record.resolution}")
        print(f"[info] View trail: python -m agent.timeline {record.incident_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
