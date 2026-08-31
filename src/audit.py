"""
ShadowGraph — Audit Trail + Human-Gating Layer
==================================================
Every verdict from agent.py gets logged here permanently (append-only —
audit logs are never edited, only appended to). High-severity actions
(suspend_accounts, hold_payouts) are GATED: they cannot execute without
explicit human approval, logged alongside the original decision.

This is what makes the agent's actions "explainable and bounded" rather
than an automated black box that can freeze real money on its own.
"""

import json
import os
from datetime import datetime, timezone

AUDIT_LOG_PATH = "data/audit_log.jsonl"

# Actions that require a human to explicitly approve before they "execute".
# Lower-severity actions (monitor, flag_for_review) don't block on a human
# because they don't touch money or account access directly.
GATED_ACTIONS = {"suspend_accounts", "hold_payouts"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _next_entry_id():
    """Simple incrementing ID based on how many entries already exist."""
    if not os.path.exists(AUDIT_LOG_PATH):
        return 1
    with open(AUDIT_LOG_PATH) as f:
        return sum(1 for _ in f) + 1


def log_decision(ring_result):
    """
    Appends one audit entry for a single ring's verdict. If the
    recommended action is gated, status starts as 'pending_human_approval'
    and the action is NOT considered executed. If it's not gated, it's
    marked 'auto_approved' since low-severity actions don't need a human
    in the loop.
    """
    verdict = ring_result["verdict"]
    action = verdict["recommended_action"]
    is_gated = action in GATED_ACTIONS

    entry = {
        "entry_id": _next_entry_id(),
        "timestamp": _now(),
        "accounts": ring_result["accounts"],
        "suspicion_score": ring_result["suspicion_score"],
        "detection_method": ring_result["detection_method"],
        "evidence": ring_result["evidence"],
        "risk_level": verdict["risk_level"],
        "explanation": verdict["explanation"],
        "recommended_action": action,
        "confidence": verdict["confidence"],
        "adversarial_self_check": ring_result["adversarial_self_check"],
        "gated": is_gated,
        "status": "pending_human_approval" if is_gated else "auto_approved",
        "reviewed_by": None,
        "review_timestamp": None,
        "review_reason": None,
    }

    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def load_all_entries():
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    entries = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def review_decision(entry_id, decision, reviewer, reason):
    """
    Records a human's approval or override of a gated decision.
    Since the log is append-only, we don't edit the original entry —
    we append a NEW entry that references it, preserving full history
    of what was originally recommended vs. what a human actually decided.
    """
    assert decision in {"approved", "overridden"}, "decision must be 'approved' or 'overridden'"

    review_entry = {
        "entry_id": _next_entry_id(),
        "timestamp": _now(),
        "type": "human_review",
        "reviews_entry_id": entry_id,
        "decision": decision,
        "reviewed_by": reviewer,
        "reason": reason,
    }

    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(review_entry) + "\n")

    return review_entry


def print_pending_approvals():
    entries = load_all_entries()
    pending = [e for e in entries if e.get("status") == "pending_human_approval"]

    if not pending:
        print("No decisions pending human approval.")
        return

    print(f"\n{len(pending)} decision(s) awaiting human approval:\n")
    for e in pending:
        print(f"  Entry #{e['entry_id']} — {e['recommended_action'].upper()} "
              f"(risk: {e['risk_level']}, confidence: {e['confidence']}%)")
        print(f"    Accounts: {e['accounts']}")
        print(f"    Why: {e['explanation']}")
        print(f"    Known blind spot: {e['adversarial_self_check']}")
        print()


def main():
    """
    Loads all verdicts from agent.py's output, logs each one, then shows
    which ones are gated and awaiting human approval. This demonstrates
    the full loop: detection -> reasoning -> logged, bounded decision.
    """
    with open("data/verdicts.json") as f:
        ring_results = json.load(f)

    for ring_result in ring_results:
        entry = log_decision(ring_result)
        tag = "GATED — needs human approval" if entry["gated"] else "auto-approved (low severity)"
        print(f"Logged entry #{entry['entry_id']}: {entry['recommended_action']} [{tag}]")

def get_decision_entries_with_status():
    """
    Used by the dashboard: merges original decision entries with any
    later human_review entries that resolved them, producing one clean
    list where every decision shows its FINAL status (pending, approved,
    or overridden), who reviewed it, and why.
    """
    entries = load_all_entries()
    decisions = [e for e in entries if e.get("type") != "human_review"]
    reviews = [e for e in entries if e.get("type") == "human_review"]

    review_by_entry = {}
    for r in reviews:
        review_by_entry[r["reviews_entry_id"]] = r

    for d in decisions:
        review = review_by_entry.get(d["entry_id"])
        if review:
            d["final_status"] = review["decision"]
            d["reviewed_by"] = review["reviewed_by"]
            d["review_reason"] = review["reason"]
            d["review_timestamp"] = review["timestamp"]
        else:
            d["final_status"] = d["status"]

    decisions.sort(key=lambda d: d["entry_id"], reverse=True)
    return decisions

    print_pending_approvals()
    print(f"Full audit trail written to {AUDIT_LOG_PATH}")


if __name__ == "__main__":
    main()