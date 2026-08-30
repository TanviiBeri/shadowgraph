"""
ShadowGraph — Agent Reasoning Layer
======================================
Takes candidate fraud rings from the graph engine (data/candidate_rings.json)
and, for each one, asks an LLM to:
  1. Produce an explainable verdict (risk level, reasoning, recommended action)
  2. Run an adversarial self-check: how would a smarter ring evade this
     exact detection method? Logged as a "known blind spot" alongside
     every verdict — this is what makes the output trustworthy rather
     than a black-box flag.

Requires GROQ_API_KEY in a .env file at the project root.
"""

import os
import json
import time
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def load_candidate_rings(path="data/candidate_rings.json"):
    with open(path) as f:
        return json.load(f)


def call_model(prompt, max_retries=3):
    """
    Sends a prompt to Groq and returns the raw text response.
    Forces JSON-only output via response_format. Retries on transient
    server errors, but fails fast on rate-limit errors since retrying
    those immediately won't help.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from model")
            return content
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                raise  # rate limited — don't waste retries
            if attempt == max_retries:
                raise
            wait = attempt * 2
            print(f"    (retry {attempt}/{max_retries} after error: {e} — waiting {wait}s)")
            time.sleep(wait)


def parse_json_response(raw_text):
    return json.loads(raw_text.strip())


def build_combined_prompt(ring):
    evidence_text = "\n".join(f"- {e}" for e in ring["evidence"])
    return f"""You are a fraud risk analyst reviewing a candidate collusion ring
flagged by an automated graph-detection system.

RING DETAILS:
- Number of accounts involved: {ring['size']}
- Automated suspicion score (0-100): {ring['suspicion_score']}
- Detected via shared identifiers (device/IP/card): {ring['has_shared_identifier']}
- Detected via behavioral synchrony ONLY (no shared identifiers): {ring['has_behavioral_sync_only']}

EVIDENCE FROM THE DETECTION SYSTEM:
{evidence_text}

Do two things:

1. Produce a verdict as a risk analyst would: risk level, plain-English
   explanation for a non-technical risk manager, recommended action,
   and your confidence.

2. Then red-team your OWN verdict: assume you are an adversary who knows
   exactly how this detection system works (identifier matching + timing/
   amount synchrony correlation within a short time window). Describe the
   simplest way this ring could restructure itself to avoid triggering
   this exact detection in the future.

Respond with a JSON object with exactly these fields, nothing else:

{{
  "risk_level": one of "low", "medium", "high", "critical",
  "explanation": 2-3 sentences,
  "recommended_action": one of "monitor", "flag_for_review", "hold_payouts", "suspend_accounts",
  "confidence": a number from 0 to 100,
  "blind_spot": 2-3 sentences describing how a smarter ring evades this exact detection method
}}"""


def process_ring(ring, index, total):
    print(f"[{index}/{total}] Processing ring (score={ring['suspicion_score']}, size={ring['size']})...")

    raw = call_model(build_combined_prompt(ring))
    result = parse_json_response(raw)

    return {
        "accounts": ring["accounts"],
        "size": ring["size"],
        "suspicion_score": ring["suspicion_score"],
        "detection_method": "shared_identifier" if ring["has_shared_identifier"] else "behavioral_sync_only",
        "evidence": ring["evidence"],
        "verdict": {
            "risk_level": result["risk_level"],
            "explanation": result["explanation"],
            "recommended_action": result["recommended_action"],
            "confidence": result["confidence"],
        },
        "adversarial_self_check": result["blind_spot"],
    }


def main(input_path="data/candidate_rings.json", output_path="data/verdicts.json"):
    rings = load_candidate_rings(input_path)
    results = []

    for i, ring in enumerate(rings, start=1):
        try:
            result = process_ring(ring, i, len(rings))
            results.append(result)
        except Exception as e:
            print(f"  ERROR processing ring {i}: {e}")
            continue

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nProcessed {len(results)}/{len(rings)} rings successfully.")
    print(f"Written to {output_path}")

    for r in results:
        print(f"\n  Risk: {r['verdict']['risk_level'].upper()} "
              f"| Action: {r['verdict']['recommended_action']} "
              f"| Confidence: {r['verdict']['confidence']}%")
        print(f"  {r['verdict']['explanation']}")
        print(f"  Blind spot: {r['adversarial_self_check']}")


if __name__ == "__main__":
    main()