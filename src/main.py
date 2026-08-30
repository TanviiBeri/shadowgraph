"""
ShadowGraph — End-to-End Pipeline
=====================================
Runs the full system in one command:
  1. Generate synthetic transaction data
  2. Run graph detection (identifier graph + behavioral synchrony graph)
  3. Run LLM agent reasoning (verdict + adversarial self-check) per ring
  4. Log every decision to the audit trail, gating high-severity actions

Usage:
    python3 src/main.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

import data_gen
import graph_engine
import agent
import audit


def banner(text):
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


def main():
    start = time.time()

    banner("STEP 1/4 — Generating synthetic transaction data")
    data_gen.main()

    banner("STEP 2/4 — Running graph detection engine")
    graph_engine.run_pipeline()

    banner("STEP 3/4 — Running LLM agent reasoning (verdict + adversarial self-check)")
    agent.main()

    banner("STEP 4/4 — Logging decisions to audit trail")
    with open("data/verdicts.json") as f:
        import json
        ring_results = json.load(f)
    for ring_result in ring_results:
        entry = audit.log_decision(ring_result)
        tag = "GATED — needs human approval" if entry["gated"] else "auto-approved (low severity)"
        print(f"Logged entry #{entry['entry_id']}: {entry['recommended_action']} [{tag}]")

    audit.print_pending_approvals()

    elapsed = time.time() - start
    banner(f"PIPELINE COMPLETE in {elapsed:.1f}s")
    print("Outputs written to:")
    print("  data/candidate_rings.json   — graph engine's flagged clusters")
    print("  data/verdicts.json          — agent's reasoning + adversarial self-check")
    print("  data/audit_log.jsonl        — full append-only decision log")
    print("\nRun 'python3 tests/evaluate.py' for precision/recall metrics.")
    print("Run 'python3 tests/stress_test.py' for the false-positive stress test.")


if __name__ == "__main__":
    main()