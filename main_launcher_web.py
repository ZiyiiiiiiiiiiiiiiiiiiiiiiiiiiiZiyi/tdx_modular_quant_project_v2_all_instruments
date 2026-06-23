"""Browser-based launcher for main.py.

This avoids Tk/Spyder event-loop conflicts by using the system browser.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Main Launcher</title>
  <style>
    :root {
      --bg: #f5efe5;
      --panel: #fffdf7;
      --line: #d6cfbd;
      --ink: #173f35;
      --muted: #6c675d;
      --accent: #d4a84f;
      --danger: #b3403a;
    }
    body {
      margin: 0;
      background: linear-gradient(160deg, #efe4d2 0%%, #f7f3ea 45%%, #e7efe8 100%%);
      color: var(--ink);
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    }
    .wrap {
      max-width: 760px;
      margin: 32px auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 16px 40px rgba(23, 63, 53, 0.10);
      overflow: hidden;
    }
    .head {
      padding: 20px 24px;
      background: #173f35;
      color: #f7d774;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .body {
      padding: 22px 24px 26px;
    }
    .section-title {
      font-size: 16px;
      font-weight: 700;
      margin: 6px 0 12px;
    }
    .item {
      display: block;
      padding: 12px 14px;
      margin: 10px 0;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffef9;
    }
    .item.recommended {
      border-color: #c99a2e;
      background: linear-gradient(180deg, #fffaf0 0%, #fffdf7 100%);
      box-shadow: inset 4px 0 0 #c99a2e;
    }
    .item input {
      margin-right: 10px;
      transform: scale(1.15);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 10px 0 4px;
    }
    .field {
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffef9;
    }
    .field label {
      display: block;
      margin-bottom: 7px;
      font-weight: 700;
      font-size: 13px;
    }
    .field input, .field select {
      box-sizing: border-box;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 9px 10px;
      color: var(--ink);
      background: #fffdf7;
      font-size: 14px;
    }
    .hint {
      margin: 18px 0;
      padding: 14px 16px;
      background: #f8f2e4;
      border-left: 4px solid var(--accent);
      border-radius: 10px;
      color: var(--muted);
      line-height: 1.55;
    }
    .mini {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
      margin-top: 6px;
    }
    .actions {
      display: flex;
      gap: 10px;
      justify-content: space-between;
      margin-top: 22px;
    }
    button {
      border: 0;
      border-radius: 10px;
      padding: 12px 18px;
      font-size: 15px;
      cursor: pointer;
    }
    .primary {
      background: #173f35;
      color: #fff;
    }
    .secondary {
      background: #e8e1d2;
      color: #173f35;
    }
    .ghost {
      background: #f7f1e7;
      color: var(--danger);
    }
    #status {
      margin-top: 16px;
      color: var(--muted);
      min-height: 20px;
    }
    @media (max-width: 720px) {
      .wrap {
        margin: 12px;
      }
      .grid {
        grid-template-columns: 1fr;
      }
      .actions {
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">MAIN LAUNCHER</div>
    <div class="body">
      <div class="section-title">Select Tasks To Run</div>
      <label class="item"><input type="checkbox" id="main_pipeline">Main pipeline: full non-governance data and strategy pipeline.</label>
      <label class="item"><input type="checkbox" id="governance_active">Governance mainline: single governance run for the default universe, best for popup monitoring and behavior debugging.</label>
      <label class="item"><input type="checkbox" id="governance_mainline_review">Governance mainline review: runs hs300_csi500_a500_strict and hs300_strict, then builds the comparison report.</label>
      <label class="item"><input type="checkbox" id="governance_layer_validation">Layer validation line: compact 8-factor equal-weight test, reputation/shadow off, regime overlay off, safety on. Use this to prove whether the base signal works before adding complexity.</label>
      <label class="item recommended"><input type="checkbox" id="governance_layer_ablation_suite" checked>Layer ablation suite: one-click matrix for core base, +regime, +probability, +complex exits, and full mainline. It opens one shared monitor page and keeps shadow forced off for speed and attribution clarity.</label>

      <div class="hint">
        Current recommended choice: Layer ablation suite.<br>
        It is the fastest useful way to identify whether the problem is base factors, regime/rebound logic, probability calibration, complex exits, or full mainline overlays.<br>
        Governance mainline review is still available when you want the normal production-style comparison report.<br>
        Use Layer validation when you want a cleaner diagnostic run that can identify whether factors, not overlays, are producing edge.<br>
        Use Governance mainline only when you want a single-universe debug run. It uses the first selected stock pool below.
      </div>

      <div class="section-title">Governance Parameters</div>
      <label class="item"><input type="checkbox" name="universe" value="hs300_csi500_a500_strict" checked>hs300_csi500_a500_strict: HS300 + CSI500 + A500, current recommended broad research pool.</label>
      <label class="item"><input type="checkbox" name="universe" value="hs300_strict" checked>hs300_strict: HS300 only, defensive large-cap comparison pool.</label>
      <label class="item"><input type="checkbox" name="universe" value="hs300_csi300_a500_strict">hs300_csi300_a500_strict: HS300/CSI300 + A500 alias pool, kept for old comparison.</label>
      <label class="item"><input type="checkbox" name="universe" value="csi500_strict">csi500_strict: CSI500 only, useful for second-layer pool isolation tests.</label>
      <div class="grid">
        <div class="field">
          <label for="start_month">Start month</label>
          <input type="month" id="start_month" value="2021-01">
        </div>
        <div class="field">
          <label for="end_month">End month</label>
          <input type="month" id="end_month" value="2024-12">
        </div>
        <div class="field">
          <label for="max_days">Max trading days, optional</label>
          <input type="number" id="max_days" min="1" step="1" placeholder="Blank = use full selected period">
        </div>
      </div>
      <label class="item"><input type="checkbox" id="shadow_portfolios">Enable per-alpha shadow portfolios: very slow diagnostic mode. Leave off for normal full-history review.</label>
      <label class="item"><input type="checkbox" id="timestamped_diagnostics" checked disabled>Generate timestamped diagnostic tables, charts, and markdown reports after layer suite runs.</label>
      <div class="mini">
        Layer suite outputs are saved under results/governance/layer_ablation_diagnostics_suite_YYYYMMDD_HHMMSS.
        Mainline fixed-name outputs are archived before overwrite when that path already exists.
      </div>
      <div class="hint">
        Month selection is converted in main.py: start month becomes the first calendar day, end month becomes the last calendar day.<br>
        Fast lane still caps the run to about 180 governance days for debugging. Full lane respects the selected months unless Max trading days is set.<br>
        Shadow portfolios multiply runtime by the number of alpha factors; only enable them for a short diagnostic run.
      </div>

      <div class="section-title">Runtime Profile</div>
      <label class="item"><input type="radio" name="profile" value="fast" checked>Fast lane: last ~1 year, capped at 180 governance days, and disables per-alpha shadow backtests.</label>
      <label class="item"><input type="radio" name="profile" value="full">Full lane: use the selected months. Shadow portfolios still follow the checkbox above; leave them off unless you intentionally want a slow factor-shadow run.</label>

      <div class="actions">
        <div>
          <button class="primary" onclick="submitSelected()">Run selected</button>
          <button class="primary" onclick="submitDiagnosticSuite()">Run recommended diagnostics</button>
          <button class="secondary" onclick="submitLayerSuiteOnly()">Run layer suite only</button>
          <button class="secondary" onclick="submitAll()">Run all</button>
        </div>
        <button class="ghost" onclick="cancelLaunch()">Cancel</button>
      </div>
      <div id="status"></div>
    </div>
  </div>
  <script>
    function currentProfile() {
      const node = document.querySelector('input[name="profile"]:checked');
      return node ? node.value : "full";
    }
    function governanceParams(tasks) {
      const universes = Array.from(document.querySelectorAll('input[name="universe"]:checked')).map((node) => node.value);
      const startMonth = document.getElementById("start_month").value;
      const endMonth = document.getElementById("end_month").value;
      const maxDays = document.getElementById("max_days").value.trim();
      const shadowPortfolios = document.getElementById("shadow_portfolios").checked;
      const touchesGovernance = tasks.some((task) => task === "governance_active" || task === "governance_mainline_review" || task === "governance_layer_validation" || task === "governance_layer_ablation_suite");
      if (touchesGovernance && universes.length === 0) {
        throw new Error("Select at least one governance stock pool.");
      }
      if (startMonth && endMonth && startMonth > endMonth) {
        throw new Error("Start month cannot be later than end month.");
      }
      return {
        universes,
        start_month: startMonth,
        end_month: endMonth,
        max_days: maxDays,
        shadow_portfolios: shadowPortfolios
      };
    }
    async function sendPayload(payload) {
      const status = document.getElementById("status");
      status.textContent = "Submitting selection...";
      const response = await fetch("/submit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      status.textContent = result.message || "Submitted.";
      if (response.ok) {
        setTimeout(() => window.close(), 400);
      }
    }
    async function submitSelected() {
      const tasks = [];
      ["main_pipeline", "governance_active", "governance_mainline_review", "governance_layer_validation", "governance_layer_ablation_suite"].forEach((id) => {
        const node = document.getElementById(id);
        if (node && node.checked) tasks.push(id);
      });
      if (tasks.length === 0) {
        document.getElementById("status").textContent = "Select at least one task.";
        return;
      }
      try {
        await sendPayload({tasks, profile: currentProfile(), governance: governanceParams(tasks)});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitLayerSuiteOnly() {
      const tasks = ["governance_layer_ablation_suite"];
      try {
        await sendPayload({tasks, profile: currentProfile(), governance: governanceParams(tasks)});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitDiagnosticSuite() {
      const tasks = ["governance_layer_ablation_suite"];
      document.getElementById("governance_layer_ablation_suite").checked = true;
      document.getElementById("shadow_portfolios").checked = false;
      try {
        await sendPayload({tasks, profile: currentProfile(), governance: governanceParams(tasks)});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitAll() {
      const tasks = ["main_pipeline", "governance_active", "governance_mainline_review", "governance_layer_validation", "governance_layer_ablation_suite"];
      if (!window.confirm("Run all tasks will start the main pipeline, mainline review, validation line, and full layer suite. This can take a very long time. Continue?")) {
        document.getElementById("status").textContent = "Run all cancelled.";
        return;
      }
      try {
      await sendPayload({
        tasks,
        profile: currentProfile(),
        governance: governanceParams(tasks)
      });
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function cancelLaunch() {
      await sendPayload({});
    }
  </script>
</body>
</html>
"""


def _write_selection(state_path: Path, payload: dict) -> None:
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(state_path)


def _pick_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: main_launcher_web.py <selection_json_path>")
        return 1

    state_path = Path(argv[1])
    stop_event = threading.Event()
    port = _pick_port()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/submit":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {}
            _write_selection(state_path, payload if isinstance(payload, dict) else {})
            body = json.dumps({"message": "Selection recorded. You can close this page."}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            stop_event.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Main Launcher browser URL: {url}")
    try:
        opened = webbrowser.open(url, new=1)
    except Exception:
        opened = False
    if not opened:
        print("Browser did not open automatically. Open the URL above manually.")

    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if not stop_event.is_set() and not state_path.exists():
            _write_selection(state_path, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
