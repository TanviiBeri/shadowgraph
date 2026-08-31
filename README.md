# ShadowGraph — Behavioral Collusion Detection Agent

**Razorpay AI Buildathon — Track 02: AI Risk Manager**

> ShadowGraph detects colluding fraud rings on payment platforms by correlating **behavioral synchrony** across accounts — not just shared identifiers. Most graph-based fraud detectors catch rings by matching shared devices, IPs, or cards. Real fraud rings know this and rotate identifiers to evade exactly that kind of detection. ShadowGraph adds a second detection layer that catches rings even when every identifier looks different, and red-teams its own verdicts before a human ever has to.

## The problem with standard fraud-ring detection

A basic fraud graph connects accounts that share a device, IP, or card. It works — until the ring knows it's being watched. A ring that rotates a fresh device, IP, and virtual card per account is **invisible** to identifier-matching, no matter how sophisticated the graph algorithm on top of it is.

ShadowGraph adds a second, independent detection layer: **behavioral synchrony**. Even with zero shared identifiers, a coordinated ring still has to coordinate — transactions land in the same short time window, amounts mirror each other, refunds happen in lockstep. That coordination itself is the signal.

## Architecture

1. **`src/data_gen.py`** — generates a seeded, reproducible synthetic dataset: 400 normal accounts, 4 "naive" collusion rings (shared identifiers), 3 "evasive" collusion rings (zero shared identifiers, behavioral synchrony only).
2. **`src/graph_engine.py`** — builds two graphs over the same accounts: an identifier graph (shared device/IP/card) and a behavioral-synchrony graph (correlated timing + mirrored amounts, bucketed and thresholded to avoid flagging single coincidences). Merges both, finds connected clusters, scores each 0-100 with traceable evidence.
3. **`src/agent.py`** — for each flagged cluster, an LLM produces an explainable verdict (risk level, plain-English reasoning, recommended action, confidence) **and** red-teams its own detection: given exactly how the system works, how would a smarter ring evade it? That blind spot is logged alongside every verdict.
4. **`src/audit.py`** — every decision is logged to an append-only trail. High-severity actions (`suspend_accounts`, `hold_payouts`) are **gated** — they cannot execute without explicit human approval, which is itself logged with a reviewer name and reason.
5. **`src/main.py`** — runs the full pipeline end-to-end in one command, ~11 seconds.

## Results

**Development set** (431 accounts, 3,207 transactions, 7 rings — thresholds were designed against this data):

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall | 100% |
| False positives | 0 / 400 normal accounts |

**Held-out test set** (381 accounts, 2,776 transactions, different random seed, different ring counts/sizes — detector thresholds used completely unchanged):

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall | 100% |
| False positives | 0 / 350 normal accounts |

Run `python3 tests/evaluate.py` (development set) or `python3 tests/holdout_eval.py` (held-out set) to reproduce.
Run `python3 tests/evaluate.py` to reproduce.

## Honest limitations

A perfect score on data we generated ourselves isn't the whole story. `tests/stress_test.py` deliberately stress-tests the synchrony detector against two false-positive risks: (1) a genuine flash sale — 40 fully independent accounts paying the same popular price within minutes, zero collusion — and (2) small groups of unrelated accounts that repeatedly, coincidentally collide on timing and price.

**Finding:** the detector adaptively weights synchrony evidence by how statistically common a price point is platform-wide (mean + 2.5 standard deviations across the dataset's own amount distribution). This correctly eliminates false positives from genuine high-volume events like flash sales — the scenario that matters most in production. It does **not** eliminate flags on small, *repeated* coincidences between the same specific accounts, even at an ordinary price — because that pattern is genuinely statistically unusual regardless of price popularity, and we judged it's still worth a human's attention (routed to `flag_for_review`, never an automatic high-severity action).

Run `python3 tests/stress_test.py` to reproduce.

## Setup

Requires Python 3.10+ and a free [Groq API key](https://console.groq.com/keys).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your GROQ_API_KEY
```

## Run it

```bash
python3 src/main.py
```

Runs the full pipeline: generates data, detects rings, gets LLM verdicts, logs to the audit trail. Takes about 10-15 seconds.

Then, optionally:
```bash
python3 tests/evaluate.py       # precision/recall against ground truth
python3 tests/stress_test.py    # false-positive stress test
```
## Dashboard (recommended)

Instead of reading raw JSON, run the risk-analyst dashboard:

```bash
python3 src/dashboard.py
```

Then open http://localhost:5000. It shows every flagged ring as a card — evidence, risk level, the agent's adversarial self-check — with real **Approve**/**Override** buttons for gated high-severity decisions. Every click writes directly to `data/audit_log.jsonl`, the same append-only trail described above. A "Run new detection pass" button re-triggers the full pipeline from the UI.

## What's next

- Replace synthetic data with a streaming pipeline for real-time detection instead of batch scoring
- Expand behavioral synchrony beyond timing/amount to include session-level signals (typing patterns, navigation flow)
- A lightweight review dashboard for the human-gated approval queue, instead of reading `audit_log.jsonl` directly

## License

MIT (see LICENSE)