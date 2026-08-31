"""
ShadowGraph — Stress Test: Coincidental Synchrony
=====================================================
Tests the synchrony detector against TWO kinds of false-positive risk:

  1. Small repeated coincidences — a handful of unrelated accounts that
     happen to collide on timing + amount 2+ times, at an otherwise
     ordinary (non-popular) price. These remain flagged, deliberately —
     repeated coincidence between the same specific accounts is genuinely
     statistically unusual regardless of price popularity, and worth a
     human's attention even if any single instance turns out benign.

  2. A genuine flash sale — dozens of fully independent accounts all
     paying the same popular price within a short window, once. This is
     the adaptive-weighting fix's target: real platform-wide events
     should NOT generate false fraud alerts just because many people
     acted at once.
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

random.seed(7)

COMMON_PRICES = [499.0, 999.0, 1499.0, 1999.0, 2999.0]
SIM_START = datetime(2026, 7, 1)
N_CLUSTERS = 6
CLUSTER_SIZE = 4


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def gen_coincidence_cluster(cluster_index, n_coincidental_events):
    """Small group of independent accounts, repeatedly colliding by chance."""
    accounts = [new_id("acc") for _ in range(CLUSTER_SIZE)]
    devices = {a: new_id("dev") for a in accounts}
    ips = {a: new_id("ip") for a in accounts}
    cards = {a: new_id("card") for a in accounts}
    transactions = []

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

    for _ in range(n_coincidental_events):
        price = random.choice(COMMON_PRICES)
        window_center = SIM_START + timedelta(seconds=random.uniform(0, 30 * 86400))
        for acc in accounts:
            jitter = timedelta(seconds=random.uniform(-45, 45))
            transactions.append({
                "txn_id": new_id("txn"),
                "account_id": acc,
                "timestamp": (window_center + jitter).isoformat(),
                "amount": price,
                "device_id": devices[acc],
                "ip": ips[acc],
                "card_id": cards[acc],
                "type": "payment",
                "status": "success",
            })

    return accounts, transactions


def gen_flash_sale(n_accounts=40):
    """
    A single large burst: n_accounts fully independent, unrelated accounts
    all buy the same ₹999 flash-sale item within a couple minutes of each
    other. Zero collusion — just a real sale.
    """
    accounts = [new_id("acc") for _ in range(n_accounts)]
    transactions = []
    window_center = SIM_START + timedelta(days=10)
    for acc in accounts:
        jitter = timedelta(seconds=random.uniform(-60, 60))
        transactions.append({
            "txn_id": new_id("txn"),
            "account_id": acc,
            "timestamp": (window_center + jitter).isoformat(),
            "amount": 999.0,
            "device_id": new_id("dev"),
            "ip": new_id("ip"),
            "card_id": new_id("card"),
            "type": "payment",
            "status": "success",
        })
    return accounts, transactions


def run_stress_test():
    all_transactions = []
    cluster_report = []

    # Load the real base dataset so amount-frequency stats are realistic —
    # a genuine flash sale only looks statistically "common" when measured
    # against real platform-wide volume.
    try:
        with open("data/transactions.csv", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["amount"] = float(row["amount"])
                all_transactions.append(row)
    except FileNotFoundError:
        print("Note: data/transactions.csv not found — run src/data_gen.py first for realistic frequency context.")

    for i in range(N_CLUSTERS):
        n_events = i
        accounts, txns = gen_coincidence_cluster(i, n_events)
        all_transactions.extend(txns)
        cluster_report.append({
            "cluster_id": i, "accounts": accounts,
            "coincidental_events": n_events, "type": "repeated_coincidence",
        })

    flash_accounts, flash_txns = gen_flash_sale()
    all_transactions.extend(flash_txns)
    cluster_report.append({
        "cluster_id": "flash_sale", "accounts": flash_accounts,
        "coincidental_events": 1, "type": "flash_sale (40 unrelated accounts, one-time)",
    })

    for t in all_transactions:
        if isinstance(t["timestamp"], str):
            t["timestamp"] = datetime.fromisoformat(t["timestamp"])

    identifier_graph = build_identifier_graph(all_transactions)
    synchrony_graph = build_synchrony_graph(all_transactions)
    merged = merge_graphs(identifier_graph, synchrony_graph)
    clusters = [c for c in nx.connected_components(merged) if len(c) >= 2]
    flagged_results = [score_cluster(c, merged) for c in clusters]
    flagged_accounts = set()
    for r in flagged_results:
        flagged_accounts.update(r["accounts"])

    print("=" * 75)
    print("SHADOWGRAPH — STRESS TEST: COINCIDENTAL SYNCHRONY (adaptive weighting)")
    print("=" * 75)
    print(f"{'Events':<10}{'Accounts':<10}{'Wrongly flagged?':<25}{'Scenario'}")
    print("-" * 75)

    false_positive_count = 0
    for cluster in cluster_report:
        any_flagged = any(acc in flagged_accounts for acc in cluster["accounts"])
        if any_flagged:
            false_positive_count += 1
        status = "YES — FALSE POSITIVE" if any_flagged else "no, correctly ignored"
        print(f"{str(cluster['coincidental_events']):<10}{len(cluster['accounts']):<10}{status:<25}{cluster['type']}")

    print("-" * 75)
    print(f"Total scenarios wrongly flagged: {false_positive_count}/{len(cluster_report)}")
    print("=" * 75)

    with open("data/stress_test_results.json", "w") as f:
        json.dump({
            "adaptive_sync_threshold": 2.0,
            "clusters_tested": [{k: v for k, v in c.items()} for c in cluster_report],
            "false_positive_scenarios": false_positive_count,
            "total_scenarios": len(cluster_report),
        }, f, indent=2, default=str)
    print("Written to data/stress_test_results.json")


if __name__ == "__main__":
    run_stress_test()