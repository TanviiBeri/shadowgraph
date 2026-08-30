"""
ShadowGraph — Stress Test: Coincidental Synchrony
=====================================================
The base evaluation (evaluate.py) scored 100% precision/recall — but that
dataset only contains accounts that are either fully independent or
deliberately, heavily coordinated. Real production data has a messier
middle ground: genuinely independent users who coincidentally transact
around the same time at the same common price point (flash sales,
subscription prices like ₹999, top-of-the-hour cron-triggered charges).

This script generates several "coincidence clusters" — real independent
accounts, own devices/IPs/cards, that accidentally collide 1-4 times on
timing + amount — and checks whether our synchrony detector (MIN_SYNC_EVENTS
threshold) wrongly flags them as a fraud ring. This directly tests
threshold calibration, not just detection capability.
"""

import sys
import os
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from graph_engine import build_identifier_graph, build_synchrony_graph, merge_graphs, score_cluster
import networkx as nx

random.seed(7)  # different seed from data_gen.py — genuinely separate test

COMMON_PRICES = [499.0, 999.0, 1499.0, 1999.0, 2999.0]  # realistic round prices
SIM_START = datetime(2026, 7, 1)
N_CLUSTERS = 6
CLUSTER_SIZE = 4


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def gen_coincidence_cluster(cluster_index, n_coincidental_events):
    """
    Generates `CLUSTER_SIZE` fully independent accounts (own device/ip/card,
    like real normal users) that accidentally collide on timing + amount
    exactly `n_coincidental_events` times — simulating a flash sale or
    common subscription price, NOT collusion.
    """
    accounts = [new_id("acc") for _ in range(CLUSTER_SIZE)]
    devices = {a: new_id("dev") for a in accounts}
    ips = {a: new_id("ip") for a in accounts}
    cards = {a: new_id("card") for a in accounts}
    transactions = []

    # each account has its own independent normal activity
    for acc in accounts:
        for _ in range(random.randint(3, 8)):
            transactions.append({
                "txn_id": new_id("txn"),
                "account_id": acc,
                "timestamp": (SIM_START + timedelta(seconds=random.uniform(0, 30 * 86400))).isoformat(),
                "amount": round(random.uniform(50, 5000), 2),
                "device_id": devices[acc],
                "ip": ips[acc],
                "card_id": cards[acc],
                "type": "payment",
                "status": "success",
            })

    # the accidental collisions: shared round price, shared rough time window
    for _ in range(n_coincidental_events):
        price = random.choice(COMMON_PRICES)
        window_center = SIM_START + timedelta(seconds=random.uniform(0, 30 * 86400))
        for acc in accounts:
            jitter = timedelta(seconds=random.uniform(-45, 45))
            transactions.append({
                "txn_id": new_id("txn"),
                "account_id": acc,
                "timestamp": (window_center + jitter).isoformat(),
                "amount": price,  # exact same round price — realistic, not collusion
                "device_id": devices[acc],
                "ip": ips[acc],
                "card_id": cards[acc],
                "type": "payment",
                "status": "success",
            })

    return accounts, transactions


def run_stress_test():
    all_transactions = []
    cluster_report = []

    for i in range(N_CLUSTERS):
        n_events = i  # 0, 1, 2, 3, 4, 5 coincidental events — sweep across the threshold
        accounts, txns = gen_coincidence_cluster(i, n_events)
        all_transactions.extend(txns)
        cluster_report.append({"cluster_id": i, "accounts": accounts, "coincidental_events": n_events})

    # parse timestamps into datetime objects, matching graph_engine's expectations
    for t in all_transactions:
        t["timestamp"] = datetime.fromisoformat(t["timestamp"])

    identifier_graph = build_identifier_graph(all_transactions)
    synchrony_graph = build_synchrony_graph(all_transactions)
    merged = merge_graphs(identifier_graph, synchrony_graph)
    clusters = [c for c in nx.connected_components(merged) if len(c) >= 2]
    flagged_results = [score_cluster(c, merged) for c in clusters]
    flagged_accounts = set()
    for r in flagged_results:
        flagged_accounts.update(r["accounts"])

    print("=" * 60)
    print("SHADOWGRAPH — STRESS TEST: COINCIDENTAL SYNCHRONY")
    print("=" * 60)
    print(f"{'Coincidental events':<22}{'Accounts':<10}{'Wrongly flagged?'}")
    print("-" * 60)

    false_positive_count = 0
    for cluster in cluster_report:
        any_flagged = any(acc in flagged_accounts for acc in cluster["accounts"])
        if any_flagged:
            false_positive_count += 1
        status = "YES — FALSE POSITIVE" if any_flagged else "no, correctly ignored"
        print(f"{cluster['coincidental_events']:<22}{len(cluster['accounts']):<10}{status}")

    print("-" * 60)
    print(f"Total coincidence clusters wrongly flagged: {false_positive_count}/{N_CLUSTERS}")
    print("=" * 60)

    with open("data/stress_test_results.json", "w") as f:
        json.dump({
            "min_sync_events_threshold": 2,  # matches graph_engine.py's MIN_SYNC_EVENTS
            "clusters_tested": cluster_report,
            "false_positive_clusters": false_positive_count,
            "total_clusters": N_CLUSTERS,
        }, f, indent=2, default=str)
    print("Written to data/stress_test_results.json")


if __name__ == "__main__":
    run_stress_test()