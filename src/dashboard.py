"""
ShadowGraph — Risk Analyst Dashboard
========================================
A real, working UI on top of the existing pipeline. Reads directly from
data/verdicts.json and data/audit_log.jsonl (via src/audit.py) — nothing
here is mocked or hardcoded. Approve/Override buttons call the actual
review_decision() function that writes to the append-only audit log.

Run:
    python3 src/dashboard.py
Then open http://localhost:5000
"""

import os
import sys
import json
import subprocess
import threading

from flask import Flask, jsonify, request, Response

sys.path.insert(0, os.path.dirname(__file__))
import audit

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__)

# tracks whether a pipeline run is currently in progress, so the UI can
# show a spinner and avoid double-triggering an expensive run
pipeline_status = {"running": False, "last_output": "", "error": None}


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/decisions")
def api_decisions():
    os.chdir(PROJECT_ROOT)
    decisions = audit.get_decision_entries_with_status()
    return jsonify(decisions)


@app.route("/api/review", methods=["POST"])
def api_review():
    os.chdir(PROJECT_ROOT)
    body = request.get_json(force=True)
    entry_id = body.get("entry_id")
    decision = body.get("decision")
    reviewer = body.get("reviewer", "unknown_reviewer")
    reason = body.get("reason", "")

    if decision not in {"approved", "overridden"}:
        return jsonify({"error": "decision must be 'approved' or 'overridden'"}), 400
    if not entry_id:
        return jsonify({"error": "entry_id required"}), 400

    entry = audit.review_decision(entry_id=entry_id, decision=decision, reviewer=reviewer, reason=reason)
    return jsonify(entry)


def _run_pipeline_background():
    pipeline_status["running"] = True
    pipeline_status["error"] = None
    try:
        result = subprocess.run(
            [sys.executable, "src/main.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        pipeline_status["last_output"] = result.stdout + result.stderr
        if result.returncode != 0:
            pipeline_status["error"] = f"Pipeline exited with code {result.returncode}"
    except Exception as e:
        pipeline_status["error"] = str(e)
    finally:
        pipeline_status["running"] = False


@app.route("/api/run-pipeline", methods=["POST"])
def api_run_pipeline():
    if pipeline_status["running"]:
        return jsonify({"error": "A pipeline run is already in progress."}), 409
    thread = threading.Thread(target=_run_pipeline_background)
    thread.start()
    return jsonify({"started": True})


@app.route("/api/pipeline-status")
def api_pipeline_status():
    return jsonify(pipeline_status)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ShadowGraph — Risk Analyst Dashboard</title>
<style>
  :root {
    --bg: #0d1117;
    --panel: #151b23;
    --border: #2a323d;
    --text: #e6edf3;
    --muted: #8b949e;
    --red: #f85149;
    --orange: #d29922;
    --green: #3fb950;
    --blue: #58a6ff;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0;
    padding: 24px;
  }
  h1 { font-size: 20px; margin: 0 0 4px 0; }
  .subtitle { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .toolbar {
    display: flex; gap: 12px; align-items: center;
    margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }
  button {
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }
  button:hover { border-color: var(--blue); }
  button.primary { background: var(--blue); color: #0d1117; border: none; font-weight: 600; }
  button.approve { background: var(--green); color: #0d1117; border: none; }
  button.override { background: var(--red); color: #fff; border: none; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  input, textarea {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 10px; font-size: 13px;
  }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px;
  }
  .card.gated-pending { border-color: var(--orange); }
  .card.gated-approved { border-color: var(--green); }
  .card.gated-overridden { border-color: var(--red); }
  .badge {
    display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px;
    border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em;
  }
  .badge.high, .badge.critical { background: rgba(248,81,73,0.15); color: var(--red); }
  .badge.medium { background: rgba(210,153,34,0.15); color: var(--orange); }
  .badge.low { background: rgba(63,185,80,0.15); color: var(--green); }
  .card-header { display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px; }
  .accounts { font-size: 11px; color: var(--muted); font-family: monospace; margin: 6px 0; }
  .explanation { font-size: 13px; line-height: 1.5; margin: 10px 0; }
  .blindspot {
    font-size: 12px; line-height: 1.5; color: var(--muted); background: rgba(88,166,255,0.06);
    border-left: 2px solid var(--blue); padding: 8px 10px; margin: 10px 0; border-radius: 4px;
  }
  .blindspot strong { color: var(--blue); }
  .action-row { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }
  .action-label { font-size: 12px; color: var(--muted); }
  .status-line { font-size: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
  .status-approved { color: var(--green); }
  .status-overridden { color: var(--red); }
  .status-pending { color: var(--orange); }
  .status-auto { color: var(--muted); }
  .btns { display: flex; gap: 8px; }
  #reviewer-bar { display: flex; gap: 8px; align-items: center; }
  .empty { color: var(--muted); padding: 40px; text-align: center; }
</style>
</head>
<body>
  <h1>ShadowGraph — Risk Analyst Dashboard</h1>
  <div class="subtitle">Live view of flagged collusion rings, agent verdicts, and the human-gated audit trail.</div>

  <div class="toolbar">
    <button class="primary" id="run-btn" onclick="runPipeline()">Run new detection pass</button>
    <span id="run-status" class="action-label"></span>
    <div style="flex:1"></div>
    <div id="reviewer-bar">
      <span class="action-label">Reviewer name:</span>
      <input id="reviewer-name" placeholder="your_name" value="analyst_1"/>
    </div>
    <button onclick="loadDecisions()">Refresh</button>
  </div>

  <div id="grid" class="grid"><div class="empty">Loading...</div></div>

<script>
async function loadDecisions() {
  const res = await fetch('/api/decisions');
  const decisions = await res.json();
  const grid = document.getElementById('grid');
  if (decisions.length === 0) {
    grid.innerHTML = '<div class="empty">No decisions logged yet. Run a detection pass to populate this dashboard.</div>';
    return;
  }
  grid.innerHTML = decisions.map(renderCard).join('');
}

function renderCard(d) {
  let statusClass = 'gated-pending';
  let statusHtml = '';
  if (d.gated) {
    if (d.final_status === 'approved') {
      statusClass = 'gated-approved';
      statusHtml = `<div class="status-line status-approved">✓ Approved by ${d.reviewed_by} — "${d.review_reason}"</div>`;
    } else if (d.final_status === 'overridden') {
      statusClass = 'gated-overridden';
      statusHtml = `<div class="status-line status-overridden">✗ Overridden by ${d.reviewed_by} — "${d.review_reason}"</div>`;
    } else {
      statusClass = 'gated-pending';
      statusHtml = `<div class="status-line status-pending">⧗ Awaiting human approval</div>`;
    }
  } else {
    statusClass = '';
    statusHtml = `<div class="status-line status-auto">Auto-approved (low severity, not gated)</div>`;
  }

  const actionBtns = (d.gated && d.final_status === 'pending_human_approval') ? `
    <div class="btns">
      <button class="approve" onclick="review(${d.entry_id}, 'approved')">Approve</button>
      <button class="override" onclick="review(${d.entry_id}, 'overridden')">Override</button>
    </div>` : '';

  return `
    <div class="card ${statusClass}">
      <div class="card-header">
        <span class="badge ${d.risk_level}">${d.risk_level}</span>
        <span class="action-label">#${d.entry_id} · score ${d.suspicion_score} · ${d.confidence}% confidence</span>
      </div>
      <div class="accounts">${d.accounts.join(', ')}</div>
      <div class="explanation">${d.explanation}</div>
      <div class="blindspot"><strong>Adversarial self-check:</strong> ${d.adversarial_self_check}</div>
      <div class="action-row">
        <span class="action-label">Recommended: <strong>${d.recommended_action}</strong></span>
        ${actionBtns}
      </div>
      ${statusHtml}
    </div>`;
}

async function review(entryId, decision) {
  const reviewer = document.getElementById('reviewer-name').value || 'unknown_reviewer';
  const reason = prompt(`Reason for ${decision === 'approved' ? 'approving' : 'overriding'} entry #${entryId}?`);
  if (reason === null) return;
  await fetch('/api/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({entry_id: entryId, decision, reviewer, reason})
  });
  loadDecisions();
}

async function runPipeline() {
  const btn = document.getElementById('run-btn');
  const statusEl = document.getElementById('run-status');
  btn.disabled = true;
  statusEl.textContent = 'Running full pipeline (data gen → detection → LLM verdicts → audit)... this takes ~15-30s';
  const res = await fetch('/api/run-pipeline', {method: 'POST'});
  if (res.status === 409) {
    statusEl.textContent = 'A run is already in progress.';
    btn.disabled = false;
    return;
  }
  poll();
}

async function poll() {
  const res = await fetch('/api/pipeline-status');
  const status = await res.json();
  const btn = document.getElementById('run-btn');
  const statusEl = document.getElementById('run-status');
  if (status.running) {
    setTimeout(poll, 1500);
  } else {
    btn.disabled = false;
    statusEl.textContent = status.error ? ('Error: ' + status.error) : 'Done.';
    loadDecisions();
  }
}

loadDecisions();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    app.run(debug=True, port=5000)