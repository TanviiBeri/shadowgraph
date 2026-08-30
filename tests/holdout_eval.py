"""
ShadowGraph — Held-Out Test Set Evaluation
=============================================
Track 02's bar explicitly requires "measured precision and recall on a
held-out test set." Our earlier evaluation (tests/evaluate.py) scored
100%/100%, but it was run on the SAME dataset the detector's thresholds
(TIME_BUCKET_SECONDS, AMOUNT_TOLERANCE, MIN_SYNC_EVENTS in graph_engine.py)
were designed against — that's not a genuine held-out result.

This script generates a SEPARATE synthetic dataset — different random
seed, different population sizes, different ring counts/sizes — that the
detector's thresholds were never tuned against, runs detection against
it completely unchanged, and reports honest precision/recall on that
unseen data. This is the number that actually answers the brief.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import random
import data_gen
import graph_engine
from evaluate import load, evaluate, count_total_accounts

HOLDOUT_DIR = "data/holdout"


def generate_holdout_set():
    """
    Generates a genuinely different synthetic scenario: different seed,
    different account counts, different ring sizes. The graph engine's
    thresholds (set in src/graph_engine.py) were tuned against the
    ORIGINAL dataset (seed=42) and are used here completely unchanged —
    nothing is re-tuned against this new data.
    """
    random.seed(999)

    data_gen.accounts.clear()
    data_gen.transactions.clear()
    data_gen.ground_truth["naive_rings"].clear()
    data_gen.ground_truth["evasive_rings"].clear()

    data_gen.N_NORMAL_ACCOUNTS = 350
    data_gen.N_NAIVE_RINGS = 3
    data_gen.NAIVE_RING_SIZE = 5
    data_gen.N_EVASIVE_RINGS = 4
    data_gen.EVASIVE_RING_SIZE = 4
    data_gen.OUTPUT_DIR = HOLDOUT_DIR

    data_gen.main()


def main():
    print("Generating held-out test set (unseen scenario, different seed)...")
    generate_holdout_set()

    print("\nRunning detection engine (thresholds UNCHANGED from tuning set)...")
    graph_engine.run_pipeline(
        transactions_path=f"{HOLDOUT_DIR}/transactions.csv",
        output_path=f"{HOLDOUT_DIR}/candidate_rings.json",
    )

    print("\nEvaluating against held-out ground truth...")
    candidate_rings = load(f"{HOLDOUT_DIR}/candidate_rings.json")
    ground_truth = load(f"{HOLDOUT_DIR}/ground_truth.json")
    total_accounts = count_total_accounts(f"{HOLDOUT_DIR}/accounts.csv")

    results = evaluate(candidate_rings, ground_truth, total_accounts)

    print("=" * 50)
    print("SHADOWGRAPH — HELD-OUT TEST SET EVALUATION")
    print("=" * 50)
    print(f"Total accounts (held-out):      {results['total_accounts']}")
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
    print(f"False-positive rate (normal):   {results['false_positive_rate_on_normal_users']:.4%}")
    print("=" * 50)

    if results["false_negative_accounts"]:
        print(f"\nMissed on held-out set: {results['false_negative_accounts']}")
    else:
        print("\nNo missed fraud accounts on held-out set.")

    with open(f"{HOLDOUT_DIR}/evaluation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWritten to {HOLDOUT_DIR}/evaluation_results.json")


if __name__ == "__main__":
    main()