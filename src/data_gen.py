"""
ShadowGraph — Synthetic Data Generator
========================================
Generates a synthetic payments dataset with three account populations:
normal, naive collusion rings (shared identifiers), and evasive collusion
rings (behavioral synchrony only, zero shared identifiers).
"""

import csv
import json
import random
import uuid
from datetime import datetime, timedelta

random.seed(42)  # fixed seed = same data every time we run this, reproducible

# ----------------------------- CONFIG ---------------------------------
N_NORMAL_ACCOUNTS = 400
N_NAIVE_RINGS = 4          # number of naive collusion rings
NAIVE_RING_SIZE = 4        # accounts per naive ring
N_EVASIVE_RINGS = 3        # number of evasive collusion rings
EVASIVE_RING_SIZE = 5      # accounts per evasive ring

SIM_START = datetime(2026, 6, 1)
SIM_DAYS = 30

OUTPUT_DIR = "data"
# ------------------------------------------------------------------------


def rand_timestamp(start=SIM_START, days=SIM_DAYS):
    """Returns a random datetime within the simulation window."""
    offset = random.uniform(0, days * 24 * 3600)
    return start + timedelta(seconds=offset)


def new_device():
    """Generates a fake unique device fingerprint ID."""
    return f"dev_{uuid.uuid4().hex[:10]}"


def new_ip():
    """Generates a random-looking fake IPv4 address."""
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def new_card():
    """Generates a fake tokenized card ID (never a real card number)."""
    return f"card_{uuid.uuid4().hex[:12]}"


def new_account():
    """Generates a fake unique account ID."""
    return f"acc_{uuid.uuid4().hex[:10]}"


accounts = []          # list of dicts: account_id, label, ring_id
transactions = []      # list of dicts
ground_truth = {"naive_rings": [], "evasive_rings": []}


def gen_normal_transactions(account_id, n_txns):
    """Independent, uncorrelated activity. Own device/ip/card, random timing."""
    device = new_device()
    ip = new_ip()
    card = new_card()
    for _ in range(n_txns):
        # small chance a normal user has a second device/ip (realistic noise)
        d = device if random.random() > 0.1 else new_device()
        i = ip if random.random() > 0.15 else new_ip()
        transactions.append({
            "txn_id": f"txn_{uuid.uuid4().hex[:12]}",
            "account_id": account_id,
            "timestamp": rand_timestamp().isoformat(),
            "amount": round(random.uniform(50, 5000), 2),
            "device_id": d,
            "ip": i,
            "card_id": card,
            "type": random.choices(["payment", "refund"], weights=[0.93, 0.07])[0],
            "status": "success",
        })


def gen_naive_ring(ring_id, size):
    """Accounts that SHARE identifiers directly — the easy-to-catch pattern."""
    shared_device = new_device()
    shared_ip = new_ip()
    shared_card = new_card()
    ring_accounts = [new_account() for _ in range(size)]

    for acc in ring_accounts:
        accounts.append({"account_id": acc, "label": "naive_ring", "ring_id": ring_id})
        n_txns = random.randint(4, 10)
        for _ in range(n_txns):
            transactions.append({
                "txn_id": f"txn_{uuid.uuid4().hex[:12]}",
                "account_id": acc,
                "timestamp": rand_timestamp().isoformat(),
                "amount": round(random.uniform(500, 3000), 2),
                "device_id": shared_device,   # <- shared, catchable via identifier graph
                "ip": shared_ip,
                "card_id": shared_card if random.random() > 0.3 else new_card(),
                "type": random.choices(["payment", "refund"], weights=[0.7, 0.3])[0],
                "status": "success",
            })

    ground_truth["naive_rings"].append({"ring_id": ring_id, "accounts": ring_accounts})


def gen_evasive_ring(ring_id, size):
    """
    Accounts that DO NOT share any identifier, but collude behaviorally:
      - transact in synchronized bursts (within a short shared time window)
      - mirror transaction amounts within a tight tolerance
      - refund in lockstep shortly after each burst

    This is the pattern that requires behavioral-synchrony detection,
    not identifier matching.
    """
    ring_accounts = [new_account() for _ in range(size)]
    devices = {acc: new_device() for acc in ring_accounts}
    ips = {acc: new_ip() for acc in ring_accounts}
    cards = {acc: new_card() for acc in ring_accounts}

    for acc in ring_accounts:
        accounts.append({"account_id": acc, "label": "evasive_ring", "ring_id": ring_id})

    n_bursts = random.randint(5, 9)
    for _ in range(n_bursts):
        burst_center = rand_timestamp()
        burst_amount = round(random.uniform(800, 4000), 2)

        for acc in ring_accounts:
            # tight jitter: all accounts fire within ~90 seconds of each other
            jitter = timedelta(seconds=random.uniform(-45, 45))
            ts = burst_center + jitter
            # mirrored amount within ~3% tolerance
            amt = round(burst_amount * random.uniform(0.97, 1.03), 2)

            transactions.append({
                "txn_id": f"txn_{uuid.uuid4().hex[:12]}",
                "account_id": acc,
                "timestamp": ts.isoformat(),
                "amount": amt,
                "device_id": devices[acc],   # distinct per account — no shared identifier
                "ip": ips[acc],
                "card_id": cards[acc],
                "type": "payment",
                "status": "success",
            })

            # lockstep refund shortly after, ~60% of the time
            if random.random() < 0.6:
                refund_ts = ts + timedelta(minutes=random.uniform(10, 90))
                transactions.append({
                    "txn_id": f"txn_{uuid.uuid4().hex[:12]}",
                    "account_id": acc,
                    "timestamp": refund_ts.isoformat(),
                    "amount": amt,
                    "device_id": devices[acc],
                    "ip": ips[acc],
                    "card_id": cards[acc],
                    "type": "refund",
                    "status": "success",
                })

    ground_truth["evasive_rings"].append({"ring_id": ring_id, "accounts": ring_accounts})


def main():
    # normal population
    for _ in range(N_NORMAL_ACCOUNTS):
        acc = new_account()
        accounts.append({"account_id": acc, "label": "normal", "ring_id": None})
        gen_normal_transactions(acc, random.randint(2, 12))

    # naive collusion rings (identifier-sharing)
    for i in range(N_NAIVE_RINGS):
        gen_naive_ring(f"naive_{i}", NAIVE_RING_SIZE)

    # evasive collusion rings (behavioral-synchrony only)
    for i in range(N_EVASIVE_RINGS):
        gen_evasive_ring(f"evasive_{i}", EVASIVE_RING_SIZE)

    random.shuffle(transactions)

    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(f"{OUTPUT_DIR}/accounts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["account_id", "label", "ring_id"])
        w.writeheader()
        w.writerows(accounts)

    with open(f"{OUTPUT_DIR}/transactions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "txn_id", "account_id", "timestamp", "amount",
            "device_id", "ip", "card_id", "type", "status"
        ])
        w.writeheader()
        w.writerows(transactions)

    with open(f"{OUTPUT_DIR}/ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"Accounts:      {len(accounts)}")
    print(f"Transactions:  {len(transactions)}")
    print(f"Naive rings:   {N_NAIVE_RINGS} (size {NAIVE_RING_SIZE})")
    print(f"Evasive rings: {N_EVASIVE_RINGS} (size {EVASIVE_RING_SIZE})")
    print(f"Written to ./{OUTPUT_DIR}/")


if __name__ == "__main__":
    main()