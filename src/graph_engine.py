"""
ShadowGraph — Graph + Behavioral-Synchrony Detection Engine
=============================================================
Loads transaction data and builds two independent graphs over the same
set of accounts:

  1. Identifier graph — edges where accounts share a device, IP, or card.
     Catches "naive" collusion rings.

  2. Behavioral-synchrony graph — edges where accounts show statistically
     unlikely correlation in transaction timing and amount, even when
     NO identifier is shared. Catches "evasive" collusion rings that
     deliberately avoid shared identifiers.

     Sync evidence is ADAPTIVELY WEIGHTED: a coincidence at a price point
     that's a statistical spike platform-wide (e.g. a flash sale) counts
     for much less than a coincidence at an ordinary, evenly-distributed
     price — because the former is common and expected, the latter isn't.

Both graphs are merged, connected clusters become candidate fraud rings,
and each cluster gets a suspicion score based on the evidence found.

Run directly to execute the full pipeline against data/transactions.csv
and write results to data/candidate_rings.json.
"""

import csv
import json
import itertools
from collections import defaultdict
from datetime import datetime

import networkx as nx

# ----------------------------- CONFIG ---------------------------------
TIME_BUCKET_SECONDS = 120   # window size for grouping "simultaneous" transactions
AMOUNT_TOLERANCE = 0.05     # 5% — how close two amounts must be to count as "mirrored"

# Adaptive weighting: a sync event is weighted DOWN if it happens at a
# price point that's an unusually POPULAR spike platform-wide (e.g. a
# flash sale price like ₹999 that far more people paid than any other
# price range — a statistical outlier in the amount distribution), and
# weighted at full strength otherwise. This is relative, not a fixed
# count: what counts as "a spike" depends on the dataset's own amount
# distribution, computed via mean + SPIKE_STD_MULTIPLIER standard
# deviations across all ₹AMOUNT_BIN_SIZE price buckets.
AMOUNT_BIN_SIZE = 100
SPIKE_STD_MULTIPLIER = 2.5
ADAPTIVE_SYNC_THRESHOLD = 2.0   # cumulative weighted score needed to flag a pair
# ------------------------------------------------------------------------


def load_transactions(path="data/transactions.csv"):
    """Reads the transactions CSV into a list of dicts, with proper types."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["amount"] = float(row["amount"])
            row["timestamp"] = datetime.fromisoformat(row["timestamp"])
            rows.append(row)
    return rows


def build_identifier_graph(transactions):
    """
    Builds a graph where an edge between two accounts means they share
    at least one device, IP, or card across any transaction. This catches
    naive collusion rings that don't bother rotating identifiers.
    """
    device_to_accounts = defaultdict(set)
    ip_to_accounts = defaultdict(set)
    card_to_accounts = defaultdict(set)

    for txn in transactions:
        device_to_accounts[txn["device_id"]].add(txn["account_id"])
        ip_to_accounts[txn["ip"]].add(txn["account_id"])
        card_to_accounts[txn["card_id"]].add(txn["account_id"])

    g = nx.Graph()

    def add_edges_for_shared(identifier_map, reason):
        for identifier, accs in identifier_map.items():
            if len(accs) < 2:
                continue  # only one account used this identifier — nothing to connect
            for a, b in itertools.combinations(accs, 2):
                if g.has_edge(a, b):
                    g[a][b]["reasons"].add(reason)
                else:
                    g.add_edge(a, b, reasons={reason})

    add_edges_for_shared(device_to_accounts, "shared_device")
    add_edges_for_shared(ip_to_accounts, "shared_ip")
    add_edges_for_shared(card_to_accounts, "shared_card")

    return g


def _amount_bin(amount):
    return int(amount // AMOUNT_BIN_SIZE)


def _build_amount_frequency(payments):
    """
    Counts how many payments, platform-wide, fall into each ₹100 price
    bucket, then computes the spike threshold (mean + N standard
    deviations) that marks a bucket as an unusually popular price point
    (like a flash sale), relative to this dataset's own distribution —
    not an arbitrary fixed number.
    """
    freq = defaultdict(int)
    for txn in payments:
        freq[_amount_bin(txn["amount"])] += 1

    counts = list(freq.values())
    if len(counts) < 2:
        return freq, float("inf")

    mean = sum(counts) / len(counts)
    variance = sum((c - mean) ** 2 for c in counts) / len(counts)
    std = variance ** 0.5
    spike_threshold = mean + SPIKE_STD_MULTIPLIER * std

    return freq, spike_threshold


def _event_weight(amount, amount_freq, spike_threshold):
    """
    Full weight (1.0) unless this price bucket is a statistical spike —
    far more populated than the dataset's typical bucket. In that case,
    weight is scaled down proportionally to how far above the spike
    threshold it is, since a coincidence at a genuinely popular price
    (flash sale, common subscription tier) carries much less evidence
    value than a coincidence at an ordinary, evenly-distributed price.
    """
    freq = amount_freq[_amount_bin(amount)]
    if freq <= spike_threshold:
        return 1.0
    return spike_threshold / freq


def build_synchrony_graph(transactions):
    """
    Builds a graph where an edge between two accounts means their PAYMENT
    transactions repeatedly land in the same short time window AND at
    mirrored amounts — even though they may share zero identifiers.

    Approach: bucket payments into fixed time windows (TIME_BUCKET_SECONDS).
    Within each bucket, compare every pair of transactions from DIFFERENT
    accounts. If their amounts are within AMOUNT_TOLERANCE of each other,
    it's a candidate sync event — but instead of counting it as a flat 1,
    it's WEIGHTED by how statistically common that price point is
    platform-wide (see _event_weight). A pair only gets an edge once their
    cumulative weighted score crosses ADAPTIVE_SYNC_THRESHOLD.
    """
    payments = [t for t in transactions if t["type"] == "payment"]
    amount_freq, spike_threshold = _build_amount_frequency(payments)

    buckets = defaultdict(list)
    for txn in payments:
        bucket_key = int(txn["timestamp"].timestamp() // TIME_BUCKET_SECONDS)
        buckets[bucket_key].append(txn)

    sync_scores = defaultdict(float)   # (acc_a, acc_b) -> cumulative weighted score
    sync_counts = defaultdict(int)     # (acc_a, acc_b) -> raw event count, kept for reporting

    for bucket_txns in buckets.values():
        if len(bucket_txns) < 2:
            continue
        for t1, t2 in itertools.combinations(bucket_txns, 2):
            if t1["account_id"] == t2["account_id"]:
                continue  # same account, not collusion between two parties
            amt1, amt2 = t1["amount"], t2["amount"]
            diff_ratio = abs(amt1 - amt2) / max(amt1, amt2)
            if diff_ratio <= AMOUNT_TOLERANCE:
                pair = tuple(sorted([t1["account_id"], t2["account_id"]]))
                weight = _event_weight((amt1 + amt2) / 2, amount_freq, spike_threshold)
                sync_scores[pair] += weight
                sync_counts[pair] += 1

    g = nx.Graph()
    for pair, score in sync_scores.items():
        if score >= ADAPTIVE_SYNC_THRESHOLD:
            a, b = pair
            g.add_edge(a, b, reasons={"behavioral_sync"},
                       sync_events=sync_counts[pair],
                       sync_weighted_score=round(score, 2))

    return g


def merge_graphs(identifier_graph, synchrony_graph):
    """
    Combines both graphs into one. If an edge exists in both, its reasons
    are merged and sync data is preserved — so a pair caught by BOTH
    identifier sharing and behavioral sync carries stronger evidence.
    """
    merged = nx.Graph()

    for u, v, data in identifier_graph.edges(data=True):
        merged.add_edge(u, v, reasons=set(data.get("reasons", set())),
                         sync_events=0, sync_weighted_score=0.0)

    for u, v, data in synchrony_graph.edges(data=True):
        if merged.has_edge(u, v):
            merged[u][v]["reasons"] |= data.get("reasons", set())
            merged[u][v]["sync_events"] = data.get("sync_events", 0)
            merged[u][v]["sync_weighted_score"] = data.get("sync_weighted_score", 0.0)
        else:
            merged.add_edge(u, v, reasons=set(data.get("reasons", set())),
                             sync_events=data.get("sync_events", 0),
                             sync_weighted_score=data.get("sync_weighted_score", 0.0))

    return merged


def score_cluster(cluster_accounts, merged_graph):
    """
    Produces a 0-100 suspicion score for a cluster of accounts, plus a
    human-readable evidence summary. This is intentionally simple and
    transparent — every point added is traceable to a specific signal,
    which matters when we hand this to the LLM agent to explain later.
    """
    subgraph = merged_graph.subgraph(cluster_accounts)

    has_shared_device = any("shared_device" in d["reasons"] for _, _, d in subgraph.edges(data=True))
    has_shared_ip = any("shared_ip" in d["reasons"] for _, _, d in subgraph.edges(data=True))
    has_shared_card = any("shared_card" in d["reasons"] for _, _, d in subgraph.edges(data=True))
    has_sync = any("behavioral_sync" in d["reasons"] for _, _, d in subgraph.edges(data=True))
    total_sync_events = sum(d.get("sync_events", 0) for _, _, d in subgraph.edges(data=True))
    total_weighted_score = sum(d.get("sync_weighted_score", 0.0) for _, _, d in subgraph.edges(data=True))

    score = 0
    evidence = []

    if has_shared_device:
        score += 25
        evidence.append("Multiple accounts share the same device fingerprint.")
    if has_shared_ip:
        score += 15
        evidence.append("Multiple accounts share the same IP address.")
    if has_shared_card:
        score += 25
        evidence.append("Multiple accounts share the same payment card.")
    if has_sync:
        sync_points = min(35, total_weighted_score * 5)
        score += sync_points
        evidence.append(
            f"Accounts show {total_sync_events} instances of correlated "
            f"transaction timing and mirrored amounts (adaptive suspicion "
            f"weight {total_weighted_score:.2f}, discounted for common "
            f"platform-wide price points), despite using distinct "
            f"devices/IPs/cards — a pattern consistent with coordinated "
            f"behavior designed to evade identifier-based detection."
        )

    score = min(100, score)

    return {
        "accounts": sorted(cluster_accounts),
        "size": len(cluster_accounts),
        "suspicion_score": score,
        "has_shared_identifier": has_shared_device or has_shared_ip or has_shared_card,
        "has_behavioral_sync_only": has_sync and not (has_shared_device or has_shared_ip or has_shared_card),
        "evidence": evidence,
    }


def run_pipeline(transactions_path="data/transactions.csv", output_path="data/candidate_rings.json"):
    transactions = load_transactions(transactions_path)

    identifier_graph = build_identifier_graph(transactions)
    synchrony_graph = build_synchrony_graph(transactions)
    merged = merge_graphs(identifier_graph, synchrony_graph)

    clusters = [c for c in nx.connected_components(merged) if len(c) >= 2]

    results = [score_cluster(c, merged) for c in clusters]
    results.sort(key=lambda r: r["suspicion_score"], reverse=True)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Identifier graph: {identifier_graph.number_of_nodes()} nodes, {identifier_graph.number_of_edges()} edges")
    print(f"Synchrony graph:  {synchrony_graph.number_of_nodes()} nodes, {synchrony_graph.number_of_edges()} edges")
    print(f"Candidate rings found: {len(results)}")
    for r in results:
        flag = "SYNC-ONLY (evasive)" if r["has_behavioral_sync_only"] else "identifier-linked"
        print(f"  score={r['suspicion_score']:>3}  size={r['size']}  [{flag}]  {r['accounts'][:2]}...")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    run_pipeline()