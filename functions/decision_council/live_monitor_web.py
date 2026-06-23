"""Browser-based governance live monitor.

Serves a local dashboard and polls a shared state file written by the main process.
This avoids Tk/Spyder event-loop failures.
"""
from __future__ import annotations

import json
import math
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Governance Live Monitor</title>
  <style>
    :root {
      --bg: #eef2ed;
      --panel: #fffdf8;
      --ink: #102d28;
      --muted: #69736f;
      --line: #d8ddcf;
      --gold: #c99a2e;
      --green: #0f7a55;
      --red: #b23a34;
      --blue: #246a9b;
      --slate: #23343b;
      --chart: #fbfaf4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top right, rgba(36,106,155,0.13), transparent 25%),
        radial-gradient(circle at 10% 5%, rgba(201,154,46,0.16), transparent 28%),
        linear-gradient(160deg, #edf0e7 0%, #f8f5ed 45%, #e8f0ec 100%);
      color: var(--ink);
      font-family: "Microsoft YaHei UI", "Aptos", "Segoe UI", sans-serif;
    }
    .header {
      padding: 18px 22px;
      background: linear-gradient(135deg, #102d28 0%, #173f35 55%, #284f48 100%);
      color: #f7d774;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .title {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0.06em;
    }
    .status {
      font-size: 13px;
      color: #f7f3e8;
      text-align: right;
      max-width: 50vw;
    }
    .shell {
      padding: 18px;
      display: grid;
      grid-template-columns: 1.2fr 0.9fr;
      gap: 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 12px 30px rgba(16,45,40,0.08);
      backdrop-filter: blur(2px);
    }
    .panel h3 {
      margin: 0;
      padding: 14px 16px 10px;
      font-size: 15px;
      border-bottom: 1px solid #ece5d7;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 14px;
    }
    .metric {
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(180deg, #fffef9 0%, #fbf8ee 100%);
      border-left: 4px solid rgba(36,106,155,0.28);
    }
    .metric .k {
      color: var(--muted);
      font-size: 12px;
    }
    .metric .v {
      margin-top: 6px;
      font: 700 18px Consolas, monospace;
      color: var(--ink);
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .chart-wrap {
      padding: 12px 14px 16px;
    }
    canvas {
      width: 100%;
      height: 420px;
      background: var(--chart);
      border-radius: 12px;
      border: 1px solid var(--line);
    }
    canvas.compact {
      height: 260px;
    }
    .section {
      padding: 12px 14px 16px;
    }
    .list-table {
      width: 100%;
      border-collapse: collapse;
      font: 13px Consolas, monospace;
    }
    .list-table td, .list-table th {
      border-bottom: 1px solid #f0eadc;
      padding: 6px 2px;
      text-align: left;
    }
    pre {
      margin: 0;
      padding: 12px 14px;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px Consolas, monospace;
      color: var(--ink);
      max-height: 260px;
      overflow: auto;
    }
    .progress {
      margin: 0 18px 18px;
      height: 14px;
      border-radius: 999px;
      background: #e9dfcf;
      overflow: hidden;
      border: 1px solid var(--line);
    }
    .progress > div {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--blue), var(--gold));
    }
    @media (max-width: 1200px) {
      .shell { grid-template-columns: 1fr; }
    }
    @media (max-width: 900px) {
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">GOVERNANCE LIVE MONITOR</div>
    <div class="status" id="status">Waiting for session...</div>
  </div>
  <div class="shell">
    <div>
      <div class="panel">
        <h3>Core Metrics</h3>
        <div class="metrics" id="metrics"></div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Performance: Account vs Top Strength 30% Benchmark</h3>
        <div class="chart-wrap">
          <canvas id="perfChart" width="900" height="420"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Excess NAV</h3>
        <div class="chart-wrap">
          <canvas id="excessChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>Benchmark & Excess</h3>
          <pre id="benchmarkText">Waiting for data...</pre>
        </div>
        <div class="panel">
          <h3>Exposure & Cash</h3>
          <pre id="exposureText">Waiting for data...</pre>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>Entry Gate</h3>
          <pre id="entryGateText">Waiting for data...</pre>
        </div>
        <div class="panel">
          <h3>Trade Quality</h3>
          <pre id="tradeQualityText">Waiting for data...</pre>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha Factor Weight Lines</h3>
        <div class="chart-wrap">
          <canvas id="factorChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha Module Weight Lines</h3>
        <div class="chart-wrap">
          <canvas id="moduleChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Current Holdings 90D Paths (Price Relative, Not Entry PnL)</h3>
        <div class="chart-wrap">
          <canvas id="holdingPathChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>Holdings</h3>
          <div class="section">
            <table class="list-table">
              <thead><tr><th>Symbol</th><th>Value</th><th>Weight</th></tr></thead>
              <tbody id="holdingsBody"></tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <h3>Candidates</h3>
          <pre id="candidatesText">Waiting for data...</pre>
        </div>
      </div>
    </div>
    <div>
      <div class="panel">
        <h3>Safety</h3>
        <pre id="safetyText">Waiting for data...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Risk Model</h3>
        <pre id="riskModelText">Waiting for data...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Orders</h3>
        <pre id="ordersText">Waiting for data...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Order Reasons</h3>
        <pre id="orderReasonText">Waiting for data...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Pending Orders</h3>
        <pre id="pendingText">Waiting for data...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha Module Weights</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>Module</th><th>Share</th><th>Factors</th><th>Pred</th></tr></thead>
            <tbody id="moduleWeightsBody"></tbody>
          </table>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha Factor Weights</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>Module</th><th>Role</th><th>Factor</th><th>Weight</th><th>Share</th><th>Delta</th><th>Pred</th><th>Why</th></tr></thead>
            <tbody id="factorWeightsBody"></tbody>
          </table>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Position Lifecycle</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>Symbol</th><th>Entry</th><th>Unreal</th><th>MFE</th><th>MAE</th><th>Giveback</th><th>Alert</th></tr></thead>
            <tbody id="lifecycleBody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
  <div class="progress"><div id="progressBar"></div></div>

  <script>
    const metricDefs = [
      ["total_return", "Account Return"],
      ["current_drawdown", "Current DD"],
      ["account_max_drawdown", "Account Max DD"],
      ["holding_max_drawdown", "Holding Max DD"],
      ["benchmark_max_drawdown", "Top30 Benchmark Max DD"],
      ["excess_max_drawdown", "Excess Max DD"],
      ["sharpe", "Annual Sharpe"],
      ["annual_volatility", "Annual Vol"],
      ["nav", "NAV"],
      ["cash", "Cash"],
      ["holdings", "Holdings"],
      ["risk_level", "Risk Level"],
      ["exposure_cap", "Exposure Cap"],
      ["target_exposure", "Target Exposure"],
      ["actual_exposure", "Actual Exposure"],
      ["exposure_gap", "Exposure Gap"],
      ["valid_invested_nav", "Holding/Invested NAV"],
      ["benchmark_nav", "Top30 Benchmark NAV"],
      ["excess_nav", "Excess NAV"],
      ["cash_drag", "Cash Drag"],
      ["buy_accuracy_5d", "Buy Acc 5D"],
      ["sell_accuracy_5d", "Sell Acc 5D"],
      ["candidate_count", "Candidates"],
      ["confirmed_count", "Confirmed"],
      ["order_count", "Orders"],
      ["lifecycle_alerts", "Lifecycle Alerts"],
      ["pending_orders", "Pending Orders"],
    ];
    const metricsRoot = document.getElementById("metrics");
    for (const [key, label] of metricDefs) {
      const div = document.createElement("div");
      div.className = "metric";
      div.innerHTML = `<div class="k">${label}</div><div class="v" id="m_${key}">--</div>`;
      metricsRoot.appendChild(div);
    }

    let history = [];
    let factorHistory = [];
    let moduleHistory = [];
    let totalDays = 1;
    let initialNav = 1.0;

    function fmtPct(v) {
      return Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : "--";
    }
    function fmtNum(v, d=2) {
      return Number.isFinite(v) ? v.toFixed(d) : "--";
    }
    function fmtMoney(v) {
      return Number.isFinite(v) ? v.toLocaleString(undefined, {maximumFractionDigits: 0}) : "--";
    }
    function normalizeNavMultiple(value, fallbackMultiple = 1.0) {
      const v = Number(value);
      if (!Number.isFinite(v) || v <= 0) return fallbackMultiple;
      // Back-end fields are not perfectly uniform: some are account-money
      // amounts, while attribution fields are already NAV multiples.
      // Values above 100 are treated as money amounts and normalized once.
      if (v > 100.0) return v / Math.max(initialNav, 1e-12);
      return v;
    }
    function setMetric(key, text, dir) {
      const el = document.getElementById(`m_${key}`);
      if (!el) return;
      el.textContent = text;
      el.style.color = dir > 0 ? "#147a54" : dir < 0 ? "#b3403a" : "#173f35";
    }
    function riskDir(level) {
      const x = String(level || "").toLowerCase();
      if (x === "normal") return 1;
      if (x === "warning") return -0.25;
      if (x === "high") return -0.6;
      if (x === "crisis") return -1.0;
      return 0;
    }
    function summaryLines(items, emptyText="none") {
      const rows = (items || []).slice(0, 8);
      if (!rows.length) return [emptyText];
      return rows.map(x => `${String(x.name || "").padEnd(28)} ${String(x.count ?? "").padStart(5)}  ${fmtPct(Number(x.share || 0)).padStart(8)}`);
    }
    function rollingBeatRatio(windowSize) {
      if (history.length <= windowSize) return NaN;
      let wins = 0;
      let count = 0;
      for (let i = windowSize; i < history.length; i++) {
        const accountRet = history[i].navMultiple / Math.max(history[i - windowSize].navMultiple, 1e-12) - 1.0;
        const benchmarkRet = history[i].benchmarkNav / Math.max(history[i - windowSize].benchmarkNav, 1e-12) - 1.0;
        if (Number.isFinite(accountRet) && Number.isFinite(benchmarkRet)) {
          count += 1;
          if (accountRet > benchmarkRet) wins += 1;
        }
      }
      return count > 0 ? wins / count : NaN;
    }
    function drawChart() {
      const canvas = document.getElementById("perfChart");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fffef9";
      ctx.fillRect(0, 0, w, h);
      if (history.length === 0) return;

      const left = 56, right = w - 18, top = 18, bottom = h - 24;
      const split = top + Math.floor((bottom - top) * 0.56);
      const lowerMid = split + Math.floor((bottom - split) * 0.52);
      ctx.strokeStyle = "#d6cfbd";
      ctx.beginPath();
      ctx.moveTo(left, split);
      ctx.lineTo(right, split);
      ctx.moveTo(left, lowerMid);
      ctx.lineTo(right, lowerMid);
      ctx.stroke();

      ctx.fillStyle = "#6c675d";
      ctx.font = "12px Microsoft YaHei UI";
      ctx.fillText("Account vs Top Strength 30% Benchmark", left, top + 2);
      ctx.fillStyle = "#147a54";
      ctx.fillText("Account", left, top + 18);
      ctx.fillStyle = "#b3403a";
      ctx.fillText("Top30 Bench", left + 78, top + 18);
      ctx.fillStyle = "#6c675d";
      ctx.fillText("Drawdown", left, split + 18);
      ctx.fillText("Cash vs Invested", left, lowerMid + 18);

      const nets = history.map(x => x.navMultiple);
      const benchmark = history.map(x => x.benchmarkNav);
      const dds = history.map(x => x.drawdown);
      const perfRange = paddedRange([...nets, ...benchmark, 1.0]);
      drawSeries(ctx, nets, left, right, top + 30, split - 10, "#147a54", 1.0, true, perfRange);
      drawSeries(ctx, benchmark, left, right, top + 30, split - 10, "#b3403a", 1.0, false, perfRange);
      drawSeries(ctx, dds, left, right, split + 28, lowerMid - 10, "#b3403a", 0.0);
      drawBar(ctx, history[history.length - 1], left, right, lowerMid + 28, bottom - 12);
    }
    function drawExcessChart() {
      const canvas = document.getElementById("excessChart");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fffef9";
      ctx.fillRect(0, 0, w, h);
      if (!history.length) return;
      const left = 56, right = w - 18, top = 24, bottom = h - 30;
      ctx.fillStyle = "#6c675d";
      ctx.font = "12px Microsoft YaHei UI";
      ctx.fillText("Excess NAV = Account NAV / Benchmark NAV", left, top - 6);
      drawSeries(ctx, history.map(x => x.excessNav), left, right, top + 14, bottom, "#2c7fb8", 1.0);
    }
    function paddedRange(values) {
      const finite = values.map(Number).filter(Number.isFinite);
      if (!finite.length) return {minVal: 0.995, maxVal: 1.005};
      let minVal = Math.min(...finite);
      let maxVal = Math.max(...finite);
      const padding = Math.max((maxVal - minVal) * 0.08, 0.005);
      return {minVal: minVal - padding, maxVal: maxVal + padding};
    }
    function drawSeries(ctx, values, left, right, top, bottom, color, baseline, showScale = true, fixedRange = null) {
      if (!values.length) return;
      let minVal = fixedRange ? Number(fixedRange.minVal) : Math.min(...values, baseline);
      let maxVal = fixedRange ? Number(fixedRange.maxVal) : Math.max(...values, baseline);
      if (!fixedRange) {
        const padding = Math.max((maxVal - minVal) * 0.08, 0.005);
        minVal -= padding;
        maxVal += padding;
      }
      const span = Math.max(maxVal - minVal, 1e-12);
      const baselineY = bottom - (baseline - minVal) / span * (bottom - top);
      ctx.strokeStyle = "#bdb6a5";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(left, baselineY);
      ctx.lineTo(right, baselineY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = values.length === 1 ? left : left + (right - left) * i / (values.length - 1);
        const y = bottom - (v - minVal) / span * (bottom - top);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      if (showScale) {
        ctx.fillStyle = "#8b8578";
        ctx.font = "11px Consolas";
        ctx.textAlign = "right";
        ctx.fillText(`${(maxVal * 100).toFixed(2)}%`, right - 4, top + 8);
        ctx.fillText(`${(minVal * 100).toFixed(2)}%`, right - 4, bottom - 2);
        ctx.textAlign = "left";
      }
    }
    function drawBar(ctx, point, left, right, top, bottom) {
      const cash = Number(point.cash || 0);
      const invested = Number(point.invested || 0);
      const total = Math.max(cash + invested, 1e-12);
      const cashRatio = Math.max(Math.min(cash / total, 1.0), 0.0);
      const barLeft = left + 20, barRight = right - 20;
      const width = barRight - barLeft;
      const cashEnd = barLeft + width * cashRatio;
      ctx.fillStyle = "#d4a84f";
      ctx.fillRect(barLeft, top + 10, cashEnd - barLeft, bottom - top - 18);
      ctx.fillStyle = "#2c7fb8";
      ctx.fillRect(cashEnd, top + 10, barRight - cashEnd, bottom - top - 18);
      ctx.strokeStyle = "#8b8578";
      ctx.strokeRect(barLeft, top + 10, barRight - barLeft, bottom - top - 18);
      ctx.fillStyle = "#8b8578";
      ctx.font = "12px Consolas";
      ctx.fillText(`Cash ${fmtMoney(cash)}`, barLeft, top);
      ctx.fillText(`Invested ${fmtMoney(invested)}`, barRight - 170, top);
    }

    function drawFactorChart() {
      const canvas = document.getElementById("factorChart");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fffef9";
      ctx.fillRect(0, 0, w, h);
      if (!factorHistory.length) {
        ctx.fillStyle = "#6c675d";
        ctx.font = "13px Microsoft YaHei UI";
        ctx.fillText("Waiting for alpha factor weights...", 24, 32);
        return;
      }
      const left = 58, right = w - 170, top = 24, bottom = h - 32;
      const latest = factorHistory[factorHistory.length - 1].weights || [];
      const topFactors = latest
        .slice()
        .sort((a, b) => Number(b.weight_share || 0) - Number(a.weight_share || 0))
        .slice(0, 8)
        .map(x => String(x.model_name));
      const values = [];
      for (const point of factorHistory) {
        const byName = Object.fromEntries((point.weights || []).map(x => [String(x.model_name), Number(x.weight_share || 0)]));
        for (const name of topFactors) values.push(Number(byName[name] || 0));
      }
      const maxVal = Math.max(...values, 0.01);
      const minVal = Math.min(...values, 0.0);
      const span = Math.max(maxVal - minVal, 1e-12);
      ctx.strokeStyle = "#d6cfbd";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = top + (bottom - top) * i / 4;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();
      }
      const palette = ["#147a54", "#b3403a", "#2c7fb8", "#d4a84f", "#8a5a44", "#4b7f52", "#a35f2a", "#465a7a"];
      topFactors.forEach((name, idx) => {
        ctx.strokeStyle = palette[idx % palette.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        factorHistory.forEach((point, i) => {
          const byName = Object.fromEntries((point.weights || []).map(x => [String(x.model_name), Number(x.weight_share || 0)]));
          const v = Number(byName[name] || 0);
          const x = factorHistory.length === 1 ? left : left + (right - left) * i / (factorHistory.length - 1);
          const y = bottom - (v - minVal) / span * (bottom - top);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.fillStyle = palette[idx % palette.length];
        ctx.font = "11px Consolas";
        ctx.fillText(name.slice(0, 20), right + 10, top + 15 + idx * 18);
      });
      ctx.fillStyle = "#8b8578";
      ctx.font = "11px Consolas";
      ctx.fillText(fmtPct(maxVal), 8, top + 4);
      ctx.fillText(fmtPct(minVal), 8, bottom);
    }

    function aggregateModuleWeights(weights) {
      const byModule = {};
      for (const item of (weights || [])) {
        const moduleName = String(item.factor_module || "unknown");
        if (!byModule[moduleName]) byModule[moduleName] = {factor_module: moduleName, weight_share: 0, weight: 0, factor_count: 0};
        byModule[moduleName].weight_share += Number(item.weight_share || 0);
        byModule[moduleName].weight += Number(item.weight || 0);
        byModule[moduleName].factor_count += 1;
      }
      return Object.values(byModule).sort((a, b) => Number(b.weight_share || 0) - Number(a.weight_share || 0));
    }

    function drawModuleChart() {
      const canvas = document.getElementById("moduleChart");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fffef9";
      ctx.fillRect(0, 0, w, h);
      if (!moduleHistory.length) {
        ctx.fillStyle = "#6c675d";
        ctx.font = "13px Microsoft YaHei UI";
        ctx.fillText("Waiting for alpha module weights...", 24, 32);
        return;
      }
      const left = 58, right = w - 170, top = 24, bottom = h - 32;
      const latest = moduleHistory[moduleHistory.length - 1].weights || [];
      const modules = latest.map(x => String(x.factor_module)).slice(0, 8);
      const values = [];
      for (const point of moduleHistory) {
        const byName = Object.fromEntries((point.weights || []).map(x => [String(x.factor_module), Number(x.weight_share || 0)]));
        for (const name of modules) values.push(Number(byName[name] || 0));
      }
      const maxVal = Math.max(...values, 0.01);
      const minVal = Math.min(...values, 0.0);
      const span = Math.max(maxVal - minVal, 1e-12);
      ctx.strokeStyle = "#d6cfbd";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = top + (bottom - top) * i / 4;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();
      }
      const palette = ["#147a54", "#b3403a", "#2c7fb8", "#d4a84f", "#8a5a44", "#4b7f52", "#a35f2a", "#465a7a"];
      modules.forEach((name, idx) => {
        ctx.strokeStyle = palette[idx % palette.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        moduleHistory.forEach((point, i) => {
          const byName = Object.fromEntries((point.weights || []).map(x => [String(x.factor_module), Number(x.weight_share || 0)]));
          const v = Number(byName[name] || 0);
          const x = moduleHistory.length === 1 ? left : left + (right - left) * i / (moduleHistory.length - 1);
          const y = bottom - (v - minVal) / span * (bottom - top);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.fillStyle = palette[idx % palette.length];
        ctx.font = "11px Consolas";
        ctx.fillText(name.slice(0, 20), right + 10, top + 15 + idx * 18);
      });
      ctx.fillStyle = "#8b8578";
      ctx.font = "11px Consolas";
      ctx.fillText(fmtPct(maxVal), 8, top + 4);
      ctx.fillText(fmtPct(minVal), 8, bottom);
    }

    function drawHoldingPathChart(paths) {
      const canvas = document.getElementById("holdingPathChart");
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fffef9";
      ctx.fillRect(0, 0, w, h);
      const usable = (paths || []).filter(x => (x.points || []).length >= 2).slice(0, 6);
      if (!usable.length) {
        ctx.fillStyle = "#6c675d";
        ctx.font = "13px Microsoft YaHei UI";
        ctx.fillText("No active holding paths yet.", 24, 32);
        return;
      }
      const left = 58, right = w - 170, top = 24, bottom = h - 32;
      const allValues = [];
      let maxLen = 0;
      for (const path of usable) {
        maxLen = Math.max(maxLen, path.points.length);
        for (const point of path.points) allValues.push(Number(point.value || 0));
      }
      const maxVal = Math.max(...allValues, 1.02);
      const minVal = Math.min(...allValues, 0.98);
      const span = Math.max(maxVal - minVal, 1e-12);
      ctx.strokeStyle = "#d6cfbd";
      for (let i = 0; i <= 4; i++) {
        const y = top + (bottom - top) * i / 4;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();
      }
      const baselineY = bottom - (1.0 - minVal) / span * (bottom - top);
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = "#8b8578";
      ctx.beginPath();
      ctx.moveTo(left, baselineY);
      ctx.lineTo(right, baselineY);
      ctx.stroke();
      ctx.setLineDash([]);
      const palette = ["#147a54", "#b3403a", "#2c7fb8", "#d4a84f", "#8a5a44", "#465a7a"];
      usable.forEach((path, idx) => {
        ctx.strokeStyle = palette[idx % palette.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        path.points.forEach((point, i) => {
          const v = Number(point.value || 0);
          const x = maxLen <= 1 ? left : left + (right - left) * i / (maxLen - 1);
          const y = bottom - (v - minVal) / span * (bottom - top);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
        const last = Number(path.points[path.points.length - 1].value || 1);
        ctx.fillStyle = palette[idx % palette.length];
        ctx.font = "11px Consolas";
        ctx.fillText(`${String(path.symbol).slice(0, 12)} ${fmtPct(last - 1)}`, right + 10, top + 15 + idx * 18);
      });
      ctx.fillStyle = "#8b8578";
      ctx.font = "11px Consolas";
      ctx.fillText(fmtPct(maxVal - 1), 8, top + 4);
      ctx.fillText(fmtPct(minVal - 1), 8, bottom);
    }

    function renderState(payload) {
      const cmd = String(payload.command || "update");
      if (cmd === "session") {
        totalDays = Math.max(Number(payload.total_days || 1), 1);
        initialNav = Math.max(Number(payload.initial_nav || 1.0), 1e-12);
        history = [];
        factorHistory = [];
        moduleHistory = [];
        document.title = payload.title || "Governance Live Monitor";
        document.getElementById("status").textContent = `Starting: ${payload.title || ""}`;
        document.getElementById("progressBar").style.width = "0%";
        return;
      }
      if (cmd === "finish") {
        document.getElementById("status").textContent = payload.message || "Completed.";
        document.getElementById("progressBar").style.width = "100%";
        return;
      }
      if (cmd === "close") {
        document.getElementById("status").textContent = "Monitor closed.";
        return;
      }
      if (cmd !== "update") return;

      const exposure = payload.exposure || {};
      const ms = payload.monitor_state || {};
      const holdings = payload.holdings || [];
      const dayIndex = Number(payload.day_index || 0);
      const navAmount = Number(exposure.liquidatable_nav || exposure.nominal_nav || 0);
      const fallbackNavMultiple = navAmount > 0 ? navAmount / Math.max(initialNav, 1e-12) : 1.0;
      const navMultiple = normalizeNavMultiple(ms.account_net_value, fallbackNavMultiple);
      const nav = navMultiple * initialNav;
      if (!(navMultiple > 0)) return;

      let peak = nav;
      if (history.length) peak = Math.max(...history.map(x => x.nav), nav);
      const drawdown = nav / peak - 1.0;
      const benchmarkNav = normalizeNavMultiple(ms.benchmark_nav, 1.0);
      const excessNav = normalizeNavMultiple(ms.excess_net_value, navMultiple / Math.max(benchmarkNav, 1e-12));
      history.push({
        date: String(payload.date || "").slice(0, 10),
        nav,
        navMultiple,
        benchmarkNav,
        excessNav,
        drawdown,
        cash: Number(exposure.cash || 0),
        invested: Number(exposure.invested_value || 0),
        actualExposure: Number(exposure.actual_exposure || 0),
      });
      if (history.length > 1200) history = history.slice(-1200);
      factorHistory.push({
        date: String(payload.date || "").slice(0, 10),
        weights: ms.factor_weights || [],
      });
      if (factorHistory.length > 1200) factorHistory = factorHistory.slice(-1200);
      moduleHistory.push({
        date: String(payload.date || "").slice(0, 10),
        weights: aggregateModuleWeights(ms.factor_weights || []),
      });
      if (moduleHistory.length > 1200) moduleHistory = moduleHistory.slice(-1200);

      const rets = [];
      for (let i = 1; i < history.length; i++) {
        if (history[i-1].nav > 0) rets.push(history[i].nav / history[i-1].nav - 1.0);
      }
      const totalReturn = navMultiple - 1.0;
      const actualExposure = Number(exposure.actual_exposure || ms.actual_exposure || 0);
      const targetExposure = Number(ms.target_exposure || 0);
      const exposureGap = Number(ms.exposure_gap || Math.max(targetExposure - actualExposure, 0));
      const latestRet = history.length >= 2 && history[history.length - 2].nav > 0
        ? nav / history[history.length - 2].nav - 1.0
        : 0.0;
      const validInvestedRet = actualExposure >= 0.05 ? latestRet / Math.max(actualExposure, 1e-12) : 0.0;
      const previousInvestedNav = history.length >= 2 ? Number(history[history.length - 2].validInvestedNav || 1.0) : 1.0;
      history[history.length - 1].validInvestedNav = previousInvestedNav * (1.0 + validInvestedRet);
      const cashDrag = validInvestedRet - latestRet;
      const maxDrawdown = Math.min(...history.map(x => x.drawdown));
      const holdingSeries = history.map(x => Number(x.validInvestedNav || 1.0));
      const benchmarkSeries = history.map(x => Number(x.benchmarkNav || 1.0));
      const excessSeries = history.map(x => Number(x.excessNav || 1.0));
      const holdingMaxDrawdown = Math.min(...holdingSeries.map((v, i) => v / Math.max(...holdingSeries.slice(0, i + 1)) - 1.0));
      const benchmarkMaxDrawdown = Math.min(...benchmarkSeries.map((v, i) => v / Math.max(...benchmarkSeries.slice(0, i + 1)) - 1.0));
      const excessMaxDrawdown = Math.min(...excessSeries.map((v, i) => v / Math.max(...excessSeries.slice(0, i + 1)) - 1.0));
      let annualVol = 0.0;
      let sharpe = NaN;
      if (rets.length >= 2) {
        const mean = rets.reduce((a,b)=>a+b,0) / rets.length;
        const variance = rets.reduce((a,b)=>a+((b-mean)**2),0) / rets.length;
        const dv = Math.sqrt(Math.max(variance, 0));
        annualVol = dv * Math.sqrt(252);
        sharpe = dv > 1e-12 ? mean / dv * Math.sqrt(252) : NaN;
      }

      setMetric("total_return", fmtPct(totalReturn), totalReturn);
      setMetric("current_drawdown", fmtPct(drawdown), drawdown);
      setMetric("account_max_drawdown", fmtPct(maxDrawdown), maxDrawdown);
      setMetric("holding_max_drawdown", fmtPct(holdingMaxDrawdown), holdingMaxDrawdown);
      setMetric("benchmark_max_drawdown", fmtPct(benchmarkMaxDrawdown), benchmarkMaxDrawdown);
      setMetric("excess_max_drawdown", fmtPct(excessMaxDrawdown), excessMaxDrawdown);
      setMetric("sharpe", fmtNum(sharpe), sharpe);
      setMetric("annual_volatility", fmtPct(annualVol), -annualVol);
      setMetric("nav", fmtNum(navMultiple, 4), totalReturn);
      setMetric("cash", fmtMoney(Number(exposure.cash || 0)), 0);
      setMetric("holdings", String(Number(exposure.holding_count || 0)), 0);
      setMetric("risk_level", String(ms.risk_level || "--").toUpperCase(), riskDir(ms.risk_level));
      setMetric("exposure_cap", fmtPct(Number(ms.exposure_cap || 0)), -Number(ms.exposure_cap || 0));
      setMetric("target_exposure", fmtPct(Number(ms.target_exposure || 0)), Number(ms.target_exposure || 0));
      setMetric("actual_exposure", fmtPct(actualExposure), actualExposure);
      setMetric("exposure_gap", fmtPct(exposureGap), -exposureGap);
      setMetric("valid_invested_nav", fmtNum(history[history.length - 1].validInvestedNav || 1.0, 4), (history[history.length - 1].validInvestedNav || 1.0) - 1.0);
      setMetric("benchmark_nav", fmtNum(benchmarkNav, 4), benchmarkNav - 1.0);
      setMetric("excess_nav", fmtNum(excessNav, 4), excessNav - 1.0);
      setMetric("cash_drag", fmtPct(cashDrag), -cashDrag);
      setMetric("buy_accuracy_5d", fmtPct(Number(ms.trailing_buy_accuracy_5d)), Number(ms.trailing_buy_accuracy_5d || 0) - 0.5);
      setMetric("sell_accuracy_5d", fmtPct(Number(ms.trailing_sell_accuracy_5d)), Number(ms.trailing_sell_accuracy_5d || 0) - 0.5);
      setMetric("candidate_count", String(Number(ms.candidate_count || 0)), 0);
      setMetric("confirmed_count", String(Number(ms.entry_confirmed_count || 0)), Number(ms.entry_confirmed_count || 0));
      setMetric("order_count", String(Number(ms.order_count || 0)), 0);
      setMetric("lifecycle_alerts", String(Number(ms.lifecycle_alert_count || 0)), -Number(ms.lifecycle_alert_count || 0));
      setMetric("pending_orders", String(Number(ms.pending_order_count || 0)), 0);

      const progress = Math.min((dayIndex + 1) / totalDays * 100, 100);
      document.getElementById("progressBar").style.width = `${progress.toFixed(1)}%`;
      document.getElementById("status").textContent = `${String(payload.date || "").slice(0,10)} | ${dayIndex + 1}/${totalDays} | ${progress.toFixed(1)}%`;

      document.getElementById("benchmarkText").textContent = [
        `account_nav            : ${fmtNum(navMultiple, 4)} (${fmtPct(totalReturn)})`,
        `benchmark_id           : top_strength_30pct_equal_weight`,
        `benchmark_nav          : ${fmtNum(benchmarkNav, 4)} (${fmtPct(benchmarkNav - 1.0)})`,
        `excess_nav             : ${fmtNum(excessNav, 4)} (${fmtPct(excessNav - 1.0)})`,
        `account_max_dd         : ${fmtPct(maxDrawdown)}`,
        `holding_max_dd         : ${fmtPct(holdingMaxDrawdown)}`,
        `benchmark_max_dd       : ${fmtPct(benchmarkMaxDrawdown)}`,
        `excess_max_dd          : ${fmtPct(excessMaxDrawdown)}`,
        `benchmark_return_5d    : ${fmtPct(Number(ms.benchmark_return_5d))}`,
        `benchmark_return_20d   : ${fmtPct(Number(ms.benchmark_return_20d))}`,
        `benchmark_drawdown_5d  : ${fmtPct(Number(ms.benchmark_drawdown_5d))}`,
        `benchmark_drawdown_20d : ${fmtPct(Number(ms.benchmark_drawdown_20d))}`,
        `underwater_from_peak   : ${fmtPct(Number(ms.benchmark_underwater_from_peak))}`,
        `beat_ratio_20d         : ${fmtPct(rollingBeatRatio(20))}`,
        `beat_ratio_60d         : ${fmtPct(rollingBeatRatio(60))}`,
        `beat_ratio_120d        : ${fmtPct(rollingBeatRatio(120))}`
      ].join("\\n");

      document.getElementById("exposureText").textContent = [
        `cash                   : ${fmtMoney(Number(exposure.cash || 0))}`,
        `invested               : ${fmtMoney(Number(exposure.invested_value || 0))}`,
        `actual_exposure        : ${fmtPct(actualExposure)}`,
        `target_exposure        : ${fmtPct(targetExposure)}`,
        `authorized_cap         : ${fmtPct(Number(ms.effective_target_exposure_cap || 0))}`,
        `exposure_gap           : ${fmtPct(exposureGap)}`,
        `cash_drag_latest       : ${fmtPct(cashDrag)}`,
        `normal_turnover_weight : ${fmtPct(Number(ms.normal_turnover_weight || 0))}`,
        `turnover_budget        : ${fmtPct(Number(ms.turnover_budget || 0))}`,
        `catchup_allowed        : ${String(Boolean(ms.catchup_allowed || false))}`,
        `catchup_tier           : ${String(ms.catchup_tier || "none")}`,
        `catchup_block          : ${String(ms.catchup_block_reason || "--")}`
      ].join("\\n");

      document.getElementById("entryGateText").textContent = [
        `candidate_count        : ${String(ms.candidate_count ?? 0)}`,
        `entry_confirmed_count  : ${String(ms.entry_confirmed_count ?? 0)}`,
        `confirmed_ratio        : ${fmtPct(Number(ms.candidate_count || 0) > 0 ? Number(ms.entry_confirmed_count || 0) / Number(ms.candidate_count || 1) : 0)}`,
        `trailing_buy_acc_5d    : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `auth_p_win_10d_mean    : ${fmtPct(Number(ms.authorization_p_win_10d_mean || 0))}`,
        `auth_edge_10d_mean     : ${fmtPct(Number(ms.authorization_expected_edge_10d_mean || 0))}`,
        `authorization_tier     : ${String(ms.exposure_authorization_tier || "--")}`,
        `authorization_blocks   : ${String(ms.exposure_authorization_block_reasons || "--")}`,
        "",
        "Block Reasons:",
        ...summaryLines(ms.entry_block_summary || [], "no block data")
      ].join("\\n");

      document.getElementById("tradeQualityText").textContent = [
        `trailing_buy_acc_5d    : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `trailing_sell_acc_5d   : ${fmtPct(Number(ms.trailing_sell_accuracy_5d))}`,
        `best_replacement_edge  : ${fmtPct(Number(ms.best_replacement_edge_10d || 0))}`,
        `replacement_sell_count : ${String(ms.replacement_opportunity_sell_count ?? 0)}`,
        `lifecycle_alert_count  : ${String(ms.lifecycle_alert_count ?? 0)}`,
        `planned_order_count    : ${String(ms.order_count ?? 0)}`,
        `pending_order_count    : ${String(ms.pending_order_count ?? 0)}`,
        "",
        "Order Reasons:",
        ...summaryLines(ms.order_reason_summary || [], "no order reasons")
      ].join("\\n");

      document.getElementById("riskModelText").textContent = [
        `cov_risk_model_used    : ${String(Boolean(ms.covariance_risk_model_used || false))}`,
        `portfolio_cov_vol      : ${fmtPct(Number(ms.portfolio_covariance_volatility || 0))}`,
        `max_risk_contribution  : ${fmtPct(Number(ms.max_risk_contribution || 0))}`,
        `avg_pairwise_corr      : ${fmtNum(Number(ms.avg_pairwise_correlation || 0), 3)}`,
        `condition_number       : ${fmtNum(Number(ms.covariance_condition_number || 0), 1)}`,
        `risk_level             : ${String(ms.risk_level || "--")}`,
        `raw_risk_level         : ${String(ms.raw_risk_level || "--")}`,
        `liquidity_stress       : ${fmtPct(Number(ms.market_liquidity_stress_ratio || 0))}`,
        `unresolved_safety_exp  : ${fmtPct(Number(ms.unresolved_safety_exposure || 0))}`,
        `planned_safety_sell    : ${fmtPct(Number(ms.planned_safety_sell_weight || 0))}`
      ].join("\\n");

      const body = document.getElementById("holdingsBody");
      body.innerHTML = "";
      const ranked = holdings
        .filter(x => String(x.symbol || "").trim())
        .map(x => ({symbol: String(x.symbol), market_value: Number(x.market_value || 0)}))
        .sort((a,b)=>b.market_value-a.market_value)
        .slice(0, 16);
      for (const item of ranked) {
        const tr = document.createElement("tr");
        const weight = nav > 0 ? item.market_value / nav : 0;
        tr.innerHTML = `<td>${item.symbol}</td><td>${fmtMoney(item.market_value)}</td><td>${fmtPct(weight)}</td>`;
        body.appendChild(tr);
      }
      if (!ranked.length) body.innerHTML = `<tr><td colspan="3">No holdings yet.</td></tr>`;

      const lifecycleBody = document.getElementById("lifecycleBody");
      lifecycleBody.innerHTML = "";
      const lifecycleRows = (ms.holding_lifecycle_preview || []).slice(0, 12);
      for (const item of lifecycleRows) {
        const alert = item.profit_giveback_flag ? "giveback" : item.post_entry_failure_flag ? "entry_fail" : "";
        const tr = document.createElement("tr");
        tr.innerHTML = [
          `<td>${String(item.symbol || "")}</td>`,
          `<td>${String(item.entry_date || "--")}</td>`,
          `<td>${fmtPct(Number(item.unrealized_return || 0))}</td>`,
          `<td>${fmtPct(Number(item.mfe || 0))}</td>`,
          `<td>${fmtPct(Number(item.mae || 0))}</td>`,
          `<td>${fmtPct(Number(item.giveback_from_peak || 0))}</td>`,
          `<td style="color:${alert ? "#b3403a" : "#173f35"}">${alert || "ok"}</td>`
        ].join("");
        lifecycleBody.appendChild(tr);
      }
      if (!lifecycleRows.length) lifecycleBody.innerHTML = `<tr><td colspan="7">No lifecycle records yet.</td></tr>`;

      const candidateLines = [`Top Candidates (${Number(ms.candidate_count || 0)})`, "", "symbol       score     pct    exp5d   conf   p10d  edge10  e/r"];
      for (const item of (ms.candidate_preview || [])) {
        candidateLines.push(
          `${String(item.symbol || "").padEnd(10)} ${fmtNum(Number(item.primary_score || 0),3).padStart(7)} ${fmtNum(Number(item.alpha_percentile || 0),2).padStart(6)} ${(Number(item.expected_return_5d || 0)*100).toFixed(2).padStart(6)}% ${fmtNum(Number(item.aggregate_confidence || 0),2).padStart(6)} ${fmtPct(Number(item.p_win_10d_calibrated || 0)).padStart(6)} ${fmtPct(Number(item.expected_edge_10d || 0)).padStart(7)} ${fmtNum(Number(item.edge_to_risk_10d || 0),2).padStart(5)}`
        );
      }
      if ((ms.candidate_preview || []).length === 0) candidateLines.push("No candidate preview available.");
      candidateLines.push("", `Confirmed Candidates (${Number(ms.entry_confirmed_count || 0)})`, "");
      for (const item of (ms.confirmed_preview || [])) {
        candidateLines.push(
          `${String(item.symbol || "").padEnd(10)} ${fmtNum(Number(item.primary_score || 0),3).padStart(7)} ${fmtNum(Number(item.alpha_percentile || 0),2).padStart(6)} ${(Number(item.expected_return_5d || 0)*100).toFixed(2).padStart(6)}% ${fmtNum(Number(item.aggregate_confidence || 0),2).padStart(6)} ${fmtPct(Number(item.p_win_10d_calibrated || 0)).padStart(6)} ${fmtPct(Number(item.expected_edge_10d || 0)).padStart(7)} ${fmtNum(Number(item.edge_to_risk_10d || 0),2).padStart(5)}`
        );
      }
      if ((ms.confirmed_preview || []).length === 0) candidateLines.push("No confirmed candidate preview available.");
      document.getElementById("candidatesText").textContent = candidateLines.join("\\n");

      const orderLines = ["Latest Planned Orders", ""];
      for (const item of (ms.order_preview || [])) {
        orderLines.push(`${String(item.side || "").toUpperCase().padEnd(4)} ${String(item.symbol || "").padEnd(10)} ${fmtPct(Number(item.delta_weight || 0)).padStart(8)}  p=${String(item.priority ?? "")}  ${String(item.reason || "")}`);
      }
      if ((ms.order_preview || []).length === 0) orderLines.push("No new orders on this refresh.");
      document.getElementById("ordersText").textContent = orderLines.join("\\n");

      const pendingLines = [`Pending Orders (${Number(ms.pending_order_count || 0)})`, ""];
      for (const item of (ms.pending_preview || [])) {
        pendingLines.push(`${String(item.side || "").toUpperCase().padEnd(4)} ${String(item.symbol || "").padEnd(10)} shares=${fmtNum(Number(item.remaining_shares || 0),0).padStart(10)} ${String(item.status || "").padEnd(14)} lock=${fmtNum(Number(item.lock_days || 0),0)} ${String(item.reason || "")}`);
      }
      if ((ms.pending_preview || []).length === 0) pendingLines.push("No active pending orders.");
      document.getElementById("pendingText").textContent = pendingLines.join("\\n");

      document.getElementById("orderReasonText").textContent = summaryLines(ms.order_reason_summary || [], "No planned orders.").join("\\n");

      const moduleBody = document.getElementById("moduleWeightsBody");
      moduleBody.innerHTML = "";
      const moduleRows = (ms.module_weights || [])
        .slice()
        .sort((a, b) => Number(b.weight_share || 0) - Number(a.weight_share || 0))
        .slice(0, 12);
      for (const item of moduleRows) {
        const tr = document.createElement("tr");
        tr.innerHTML = [
          `<td>${String(item.factor_module || "unknown").slice(0, 22)}</td>`,
          `<td>${fmtPct(Number(item.weight_share || 0))}</td>`,
          `<td>${String(item.factor_count ?? 0)}</td>`,
          `<td>${fmtPct(Number(item.avg_predicted_return_5d || 0))}</td>`
        ].join("");
        moduleBody.appendChild(tr);
      }
      if (!moduleRows.length) moduleBody.innerHTML = `<tr><td colspan="4">No module weights yet.</td></tr>`;

      const factorBody = document.getElementById("factorWeightsBody");
      factorBody.innerHTML = "";
      const factorRows = (ms.factor_weights || [])
        .slice()
        .sort((a, b) => Number(b.weight_share || 0) - Number(a.weight_share || 0))
        .slice(0, 16);
      for (const item of factorRows) {
        const delta = Number(item.weight_delta || 0);
        const tr = document.createElement("tr");
        tr.innerHTML = [
          `<td>${String(item.factor_module || "unknown").slice(0, 18)}</td>`,
          `<td>${String(item.factor_role || "entry_alpha").slice(0, 18)}</td>`,
          `<td>${String(item.model_name || "").slice(0, 24)}</td>`,
          `<td>${fmtNum(Number(item.weight || 0), 2)}</td>`,
          `<td>${fmtPct(Number(item.weight_share || 0))}</td>`,
          `<td style="color:${delta > 0 ? "#147a54" : delta < 0 ? "#b3403a" : "#173f35"}">${delta >= 0 ? "+" : ""}${fmtNum(delta, 3)}</td>`,
          `<td>${fmtPct(Number(item.avg_predicted_return_5d || 0))}</td>`,
          `<td style="color:${item.zero_trade_factor_warning ? "#b3403a" : "#173f35"}">${String(item.weight_explanation || "").slice(0, 32)}</td>`
        ].join("");
        factorBody.appendChild(tr);
      }
      if (!factorRows.length) factorBody.innerHTML = `<tr><td colspan="8">No factor weights yet.</td></tr>`;

      const safe = [
        "Safety State",
        "",
        `risk_level              : ${String(ms.risk_level || "--")}`,
        `raw_risk_level          : ${String(ms.raw_risk_level || "--")}`,
        `trigger_streak_days     : ${String(ms.trigger_streak_days ?? "--")}`,
        `trigger_source          : ${String(ms.trigger_source || "--")}`,
        `benchmark_drawdown_5d   : ${fmtPct(Number(ms.benchmark_drawdown_5d))}`,
        `benchmark_drawdown_20d  : ${fmtPct(Number(ms.benchmark_drawdown_20d))}`,
        `benchmark_return_5d     : ${fmtPct(Number(ms.benchmark_return_5d))}`,
        `benchmark_return_20d    : ${fmtPct(Number(ms.benchmark_return_20d))}`,
        `underwater_from_peak    : ${fmtPct(Number(ms.benchmark_underwater_from_peak))}`,
        `liquidity_stress_ratio  : ${fmtPct(Number(ms.market_liquidity_stress_ratio || 0))}`,
        `structural_regime       : ${String(ms.structural_regime_level || "--")}`,
        `regime_exposure_budget  : ${fmtPct(Number(ms.regime_exposure_budget || 0))}`,
        `safety_exposure_cap     : ${fmtPct(Number(ms.safety_exposure_cap || 0))}`,
        `hard_freeze_active      : ${String(Boolean(ms.hard_freeze_active || false))}`,
        `exposure_cap            : ${fmtPct(Number(ms.exposure_cap || 0))}`,
        `target_exposure         : ${fmtPct(Number(ms.target_exposure || 0))}`,
        `actual_exposure         : ${fmtPct(actualExposure)}`,
        `exposure_gap            : ${fmtPct(exposureGap)}`,
        `catchup_allowed         : ${String(Boolean(ms.catchup_allowed || false))}`,
        `catchup_tier            : ${String(ms.catchup_tier || "none")}`,
        `accuracy_multiplier     : ${fmtNum(Number(ms.accuracy_multiplier || 0), 2)}`,
        `catchup_block_reason    : ${String(ms.catchup_block_reason || "--")}`,
        `catchup_buy_budget      : ${fmtPct(Number(ms.catchup_buy_budget || 0))}`,
        `trailing_buy_acc_5d     : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `best_replacement_edge10 : ${fmtPct(Number(ms.best_replacement_edge_10d || 0))}`,
        `replacement_sell_count  : ${String(ms.replacement_opportunity_sell_count ?? 0)}`,
        `cov_risk_model_used     : ${String(Boolean(ms.covariance_risk_model_used || false))}`,
        `portfolio_cov_vol       : ${fmtPct(Number(ms.portfolio_covariance_volatility || 0))}`,
        `max_risk_contribution   : ${fmtPct(Number(ms.max_risk_contribution || 0))}`,
        `avg_pairwise_corr       : ${fmtNum(Number(ms.avg_pairwise_correlation || 0), 3)}`,
        `unresolved_safety_exp   : ${fmtPct(Number(ms.unresolved_safety_exposure || 0))}`,
        `planned_safety_sell     : ${fmtPct(Number(ms.planned_safety_sell_weight || 0))}`,
        `constraint_cash_reserve : ${fmtPct(Number(ms.constraint_cash_reserve || 0))}`,
        `normal_turnover_weight  : ${fmtPct(Number(ms.normal_turnover_weight || 0))}`,
        `total_target_drift      : ${fmtPct(Number(ms.total_target_drift || 0))}`,
        `regime                  : ${String(ms.regime || "--")}`,
        `base_exposure_by_regime : ${fmtPct(Number(ms.base_exposure_by_regime || 0))}`,
        `raw_safety_cap          : ${fmtPct(Number(ms.raw_safety_exposure_cap || 0))}`,
        `effective_target_cap    : ${fmtPct(Number(ms.effective_target_exposure_cap || 0))}`,
        `turnover_budget         : ${fmtPct(Number(ms.turnover_budget || 0))}`,
        `top_n                   : ${String(ms.top_n ?? "--")}`
      ];
      document.getElementById("safetyText").textContent = safe.join("\\n");

      drawChart();
      drawExcessChart();
      drawFactorChart();
      drawModuleChart();
      drawHoldingPathChart(ms.holding_price_paths || []);
    }

    async function poll() {
      try {
        const response = await fetch(`/state?ts=${Date.now()}`, {cache: "no-store"});
        if (response.ok) {
          const payload = await response.json();
          renderState(payload);
        }
      } catch (err) {
        document.getElementById("status").textContent = `Monitor connection issue: ${err}`;
      }
      setTimeout(poll, 1000);
    }
    poll();
  </script>
</body>
</html>
"""


def _pick_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_payload(state_path: Path) -> dict:
    if not state_path.exists():
        return {"command": "idle"}
    try:
        return json.loads(state_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"command": "idle", "error": str(exc)}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: live_monitor_web.py <state_json_path>")
        return 1

    state_path = Path(argv[1])
    stop_event = threading.Event()
    port = _pick_port()

    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/state"):
                body = json.dumps(_read_payload(state_path), ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            self._send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")

        def log_message(self, format, *args):
            return

    def shutdown_watcher(server: ThreadingHTTPServer) -> None:
        while not stop_event.is_set():
            payload = _read_payload(state_path)
            if str(payload.get("command", "")).lower() == "close":
                stop_event.set()
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            time.sleep(0.5)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=shutdown_watcher, args=(server,), daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"Governance Live Monitor browser URL: {url}")
    try:
      opened = webbrowser.open(url, new=1)
    except Exception:
      opened = False
    if not opened:
        print("Browser did not open automatically. Open the URL above manually.")

    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        stop_event.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
