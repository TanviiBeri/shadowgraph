"""
ShadowGraph — Precision/Recall Evaluation
============================================
Compares the graph engine's candidate rings (data/candidate_rings.json)
against the ground truth (data/ground_truth.json) that was kept
completely separate from detection logic. Computes honest precision,
recall, and false-positive cost — exactly what the brief asks for.
"""

import json


def load(path):
    with open(path) as f:
        return json.load(f)


def get_all_fraud_accounts(ground_truth):
    """Every account that is ACTUALLY part of a naive or evasive ring."""
    fraud_accounts = set()
    for ring in ground_truth["naive_rings"]:
        fraud_accounts.update(ring["accounts"])
    for ring in ground_truth["evasive_rings"]:
        fraud_accounts.update(ring["accounts"])
    return fraud_accounts


def get_all_flagged_accounts(candidate_rings):
    """Every account our detector flagged, across all candidate clusters."""
    flagged = set()
    for ring in candidate_rings:
        flagged.update(ring["accounts"])
    return flagged


def evaluate(candidate_rings, ground_truth, total_account_count):
    actual_fraud = get_all_fraud_accounts(ground_truth)
    flagged = get_all_flagged_accounts(candidate_rings)

    true_positives = flagged & actual_fraud
    false_positives = flagged - actual_fraud
    false_negatives = actual_fraud - flagged

    precision = len(true_positives) / len(flagged) if flagged else 0.0
    recall = len(true_positives) / len(actual_fraud) if actual_fraud else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    normal_accounts = total_account_count - len(actual_fraud)
    false_positive_rate = len(false_positives) / normal_accounts if normal_accounts else 0.0

    return {
        "total_accounts": total_account_count,
        "actual_fraud_accounts": len(actual_fraud),
        "flagged_accounts": len(flagged),
        "true_positives": len(true_positives),
        "false_positives": len(false_positives),
        "false_negatives": len(false_negatives),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "false_positive_rate_on_normal_users": round(false_positive_rate, 4),
        "false_positive_accounts": sorted(false_positives),
        "false_negative_accounts": sorted(false_negatives),
    }


def count_total_accounts(path="data/accounts.csv"):
    import csv
    with open(path, newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def main():
    candidate_rings = load("data/candidate_rings.json")
    ground_truth = load("data/ground_truth.json")
    total_accounts = count_total_accounts()

    results = evaluate(candidate_rings, ground_truth, total_accounts)

    print("=" * 50)
    print("SHADOWGRAPH — DETECTION EVALUATION")
    print("=" * 50)
    print(f"Total accounts in dataset:      {results['total_accounts']}")
    print(f"Actual fraud accounts:          {results['actual_fraud_accounts']}")
    print(f"Flagged accounts:               {results['flagged_accounts']}")
    print("-" * 50)
    print(f"True positives:                 {results['true_positives']}")
    print(f"False positives:                {results['false_positives']}")
    print(f"False negatives:                {results['false_negatives']}")
    print("-" * 50)
    print(f"Precision:                      {results['precision']:.2%}")
    print(f"Recall:                         {results['recall']:.2%}")
    print(f"F1 score:                       {results['f1_score']:.4f}")
    print(f"False-positive rate (normal users): {results['false_positive_rate_on_normal_users']:.4%}")
    print("=" * 50)

    if results["false_negative_accounts"]:
        print(f"\nMissed accounts (honest exceptions): {results['false_negative_accounts']}")
    else:
        print("\nNo missed fraud accounts on this synthetic dataset.")

    with open("data/evaluation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWritten to data/evaluation_results.json")


if __name__ == "__main__":
    main()