"""Browser-based governance live monitor.

Serves a local dashboard and polls a shared state file written by the main process.
This avoids Tk/Spyder event-loop failures.
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>治理实时监控</title>
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
    <div class="title">治理实时监控</div>
    <div class="status" id="status">等待运行会话...</div>
  </div>
  <div class="shell">
    <div>
      <div class="panel">
        <h3>核心指标</h3>
        <div class="metrics" id="metrics"></div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>账户表现 vs 固定 Top-N 流动性股票池基准</h3>
        <div class="chart-wrap">
          <canvas id="perfChart" width="900" height="420"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>超额净值</h3>
        <div class="chart-wrap">
          <canvas id="excessChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>基准与超额</h3>
          <pre id="benchmarkText">等待数据...</pre>
        </div>
        <div class="panel">
          <h3>仓位与现金</h3>
          <pre id="exposureText">等待数据...</pre>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>买入门控</h3>
          <pre id="entryGateText">等待数据...</pre>
        </div>
        <div class="panel">
          <h3>交易质量</h3>
          <pre id="tradeQualityText">等待数据...</pre>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha 因子权重曲线</h3>
        <div class="chart-wrap">
          <canvas id="factorChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha 模块权重曲线</h3>
        <div class="chart-wrap">
          <canvas id="moduleChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>当前持仓 180 日价格路径（点标买入日期；上方显示入场收益）</h3>
        <div class="chart-wrap">
          <canvas id="holdingPathChart" class="compact" width="900" height="260"></canvas>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="panel">
          <h3>持仓</h3>
          <div class="section">
            <table class="list-table">
              <thead><tr><th>代码</th><th>市值</th><th>账户权重</th></tr></thead>
              <tbody id="holdingsBody"></tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <h3>候选股票</h3>
          <pre id="candidatesText">等待数据...</pre>
        </div>
      </div>
    </div>
    <div>
      <div class="panel">
        <h3>安全状态</h3>
        <pre id="safetyText">等待数据...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>风险模型</h3>
        <pre id="riskModelText">等待数据...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>订单</h3>
        <pre id="ordersText">等待数据...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>订单原因</h3>
        <pre id="orderReasonText">等待数据...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>未完成订单</h3>
        <pre id="pendingText">等待数据...</pre>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha 模块权重</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>模块</th><th>占比</th><th>因子数</th><th>预测</th></tr></thead>
            <tbody id="moduleWeightsBody"></tbody>
          </table>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>Alpha 因子权重</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>模块</th><th>角色</th><th>因子</th><th>权重</th><th>占比</th><th>变化</th><th>预测</th><th>原因</th></tr></thead>
            <tbody id="factorWeightsBody"></tbody>
          </table>
        </div>
      </div>
      <div class="panel" style="margin-top:16px;">
        <h3>持仓生命周期</h3>
        <div class="section">
          <table class="list-table">
            <thead><tr><th>代码</th><th>入场</th><th>浮盈亏</th><th>MFE</th><th>MAE</th><th>回吐</th><th>趋势</th><th>峰衰</th><th>亏损风险</th><th>状态</th><th>警报</th></tr></thead>
            <tbody id="lifecycleBody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
  <div class="progress"><div id="progressBar"></div></div>

  <script>
    const metricDefs = [
      ["closed_trade_win_rate", "平仓胜率"],
      ["realized_pnl", "已实现盈亏"],
      ["gross_profit", "已平仓总盈利"],
      ["gross_loss", "已平仓总亏损"],
      ["profit_factor", "利润因子"],
      ["control_exit_count", "控制卖出次数"],
      ["control_avoided_loss", "控制节省亏损"],
      ["hard_stop_avoided_loss", "硬止损节省亏损"],
      ["alpha_collapse_avoided_loss", "Alpha塌陷节省亏损"],
      ["safety_deleveraging_avoided_loss", "安全降仓节省亏损"],
      ["retail_upgraded_to_one_lot_count", "小资金一手提升"],
      ["retail_lot_cash_insufficient_count", "买不起一手"],
      ["retail_state_block_count", "状态拦截买单"],
      ["surge_candidate_count", "急涨候选"],
      ["strong_starter_count", "强启动候选"],
      ["starter_2_lot_count", "两手首买候选"],
      ["diversify_1_lot_count", "分散补足候选"],
      ["exhaustion_block_count", "衰竭拦截"],
      ["empirical_distribution_score_mean", "经验分布均分"],
      ["tail_risk_proxy_mean", "尾部风险均值"],
      ["trend_direction_score_mean", "趋势方向均值"],
      ["peak_decay_score_mean", "峰值衰退均值"],
      ["future_loss_risk_score_mean", "未来亏损风险"],
      ["minimum_required_holding_count", "当日条件最低持仓"],
      ["soft_target_holding_count", "政策目标持仓"],
      ["maximum_allowed_holding_count", "当日有效持仓上限"],
      ["user_hard_position_cap", "Web治理硬上限"],
      ["economic_position_cap", "经济可行上限"],
      ["search_position_cap", "求解资源上限"],
      ["effective_position_cap", "当日有效上限"],
      ["selected_position_count", "选中动作涉及名称数"],
      ["incremental_expected_wealth_amount", "增量期望财富"],
      ["incremental_cvar_amount", "增量CVaR"],
      ["model_uncertainty_amount", "模型不确定性"],
      ["scenario_risk_penalty_amount", "情景风险罚金"],
      ["best_rejected_objective_amount", "最佳被拒目标"],
      ["holding_shortfall_count", "软目标不足数"],
      ["idle_cash_ratio", "闲置现金比例"],
      ["scap_v31_positive_c_fallback_count", "C级试探候选"],
      ["scap_v31_all_d_streak", "全D连续日"],
      ["scap_v31_normal_cash_zero_proposal_streak", "正常高现金零提案连续日"],
      ["defensive_eligible_count", "防守候选数"],
      ["downtrend_decay_count", "阴跌风险"],
      ["protecting_profit_count", "利润保护持仓"],
      ["buy_sell_conflict_cooldown_days", "买卖冲突冷却天数"],
      ["total_return", "账户收益"],
      ["current_drawdown", "当前回撤"],
      ["account_max_drawdown", "账户最大回撤"],
      ["holding_max_drawdown", "持仓最大回撤"],
      ["benchmark_max_drawdown", "前30强基准最大回撤"],
      ["excess_max_drawdown", "超额最大回撤"],
      ["sharpe", "年化夏普"],
      ["annual_volatility", "年化波动"],
      ["nav", "账户净值"],
      ["cash", "现金"],
      ["holdings", "持仓数"],
      ["risk_level", "风险等级"],
      ["exposure_cap", "仓位上限"],
      ["strategic_exposure_budget", "战略暴露预算"],
      ["signal_supported_exposure", "信号支持仓位"],
      ["integer_feasible_exposure", "整手可行仓位"],
      ["planned_exposure", "优化器计划仓位"],
      ["target_exposure", "战略期望仓位"],
      ["actual_exposure", "实际仓位"],
      ["exposure_gap", "交易前低于政策下界"],
      ["valid_invested_nav", "持仓/投入净值"],
      ["benchmark_nav", "前30强基准净值"],
      ["excess_nav", "超额净值"],
      ["cash_drag", "现金拖累"],
      ["buy_accuracy_5d", "买入5日准确率"],
      ["sell_accuracy_5d", "卖出5日准确率"],
      ["candidate_count", "候选数"],
      ["confirmed_count", "确认数"],
      ["order_count", "订单数"],
      ["lifecycle_alerts", "生命周期警报"],
      ["pending_orders", "未完成订单"],
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
    let activeRunId = "";
    let lastProgressPct = 0;

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
      ctx.fillText("账户 vs 固定Top-N流动性基准", left, top + 2);
      ctx.fillStyle = "#147a54";
      ctx.fillText("账户", left, top + 18);
      ctx.fillStyle = "#b3403a";
      ctx.fillText("前30基准", left + 78, top + 18);
      ctx.fillStyle = "#6c675d";
      ctx.fillText("回撤", left, split + 18);
      ctx.fillText("现金 vs 已投入", left, lowerMid + 18);

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
      ctx.fillText("超额净值 = 账户净值 / 基准净值", left, top - 6);
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
      ctx.fillText(`现金 ${fmtMoney(cash)}`, barLeft, top);
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
        ctx.fillText("等待 Alpha 因子权重数据...", 24, 32);
        return;
      }
      const left = 58, right = w - 250, top = 24, bottom = h - 32;
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
        ctx.fillText("等待 Alpha 模块权重数据...", 24, 32);
        return;
      }
      const left = 58, right = w - 28, top = 58, bottom = h - 32;
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
        ctx.fillText("暂无有效持仓路径。", 24, 32);
        return;
      }
      const left = 58, right = w - 28, top = 58, bottom = h - 32;
      const palette = ["#147a54", "#b3403a", "#2c7fb8", "#d4a84f", "#8a5a44", "#465a7a"];
      const allValues = [];
      let maxLen = 0;
      for (const path of usable) {
        maxLen = Math.max(maxLen, path.points.length);
        for (const point of path.points) allValues.push(Number(point.value || 0));
      }
      const maxVal = Math.max(...allValues, 1.02);
      const minVal = Math.min(...allValues, 0.98);
      const span = Math.max(maxVal - minVal, 1e-12);

      usable.forEach((path, idx) => {
        const last = Number(path.points[path.points.length - 1].value || 1);
        const entryRet = Number(path.unrealized_return);
        const entryText = Number.isFinite(entryRet) ? ` 入场${fmtPct(entryRet)}` : "";
        const entryDate = path.entry_date ? ` ${String(path.entry_date).slice(5)}` : "";
        const labelX = left + (idx % 3) * 260;
        const labelY = 18 + Math.floor(idx / 3) * 18;
        ctx.fillStyle = palette[idx % palette.length];
        ctx.font = "11px Microsoft YaHei UI";
        ctx.fillText(`${String(path.symbol).slice(0, 12)} 180日${fmtPct(last - 1)}${entryText}${entryDate}`, labelX, labelY);
      });

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

      usable.forEach((path, idx) => {
        ctx.strokeStyle = palette[idx % palette.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        let entryPointXY = null;
        path.points.forEach((point, i) => {
          const v = Number(point.value || 0);
          const x = maxLen <= 1 ? left : left + (right - left) * i / (maxLen - 1);
          const y = bottom - (v - minVal) / span * (bottom - top);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          if (Number(path.entry_index) === i) entryPointXY = {x, y};
        });
        ctx.stroke();
        if (entryPointXY) {
          const entryDateLabel = path.entry_date ? String(path.entry_date).slice(5) : "";
          ctx.fillStyle = palette[idx % palette.length];
          ctx.beginPath();
          ctx.arc(entryPointXY.x, entryPointXY.y, 4, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = "#173f35";
          ctx.font = "10px Microsoft YaHei UI";
          ctx.fillText(`买入 ${entryDateLabel}`, entryPointXY.x + 5, entryPointXY.y - 5);
        }
      });
      ctx.fillStyle = "#8b8578";
      ctx.font = "11px Consolas";
      ctx.fillText(fmtPct(maxVal - 1), 8, top + 4);
      ctx.fillText(fmtPct(minVal - 1), 8, bottom);
    }

    function renderState(payload) {
      const cmd = String(payload.command || "update");
      if (cmd === "session") {
        activeRunId = String(payload.run_id || "");
        lastProgressPct = 0;
        totalDays = Math.max(Number(payload.total_days || 1), 1);
        initialNav = Math.max(Number(payload.initial_nav || 1.0), 1e-12);
        history = [];
        factorHistory = [];
        moduleHistory = [];
        document.title = payload.title || "治理实时监控";
        document.getElementById("status").textContent = `正在开始：${payload.title || ""}`;
        document.getElementById("progressBar").style.width = "0%";
        return;
      }
      if (cmd === "finish") {
        const payloadRunId = String(payload.run_id || "");
        if (activeRunId && payloadRunId && payloadRunId !== activeRunId) return;
        const progress = Number.isFinite(Number(payload.progress_pct)) ? Number(payload.progress_pct) : lastProgressPct;
        lastProgressPct = Math.max(lastProgressPct, Math.min(Math.max(progress, 0), 100));
        document.getElementById("status").textContent = payload.message || "已完成。";
        document.getElementById("progressBar").style.width = `${lastProgressPct.toFixed(1)}%`;
        return;
        document.getElementById("status").textContent = payload.message || "已完成。";
        document.getElementById("progressBar").style.width = "100%";
        return;
      }
      if (cmd === "close") {
        document.getElementById("status").textContent = "监控已关闭。";
        return;
      }
      if (cmd !== "update") return;
      const payloadRunId = String(payload.run_id || "");
      if (payloadRunId && payloadRunId !== activeRunId) {
        activeRunId = payloadRunId;
        lastProgressPct = 0;
        history = [];
        factorHistory = [];
        moduleHistory = [];
      }
      const payloadTotalDays = Number(payload.total_days || 0);
      if (Number.isFinite(payloadTotalDays) && payloadTotalDays > 0) {
        totalDays = Math.max(payloadTotalDays, 1);
      }
      const payloadInitialNav = Number(payload.initial_nav || 0);
      if (Number.isFinite(payloadInitialNav) && payloadInitialNav > 0) {
        initialNav = Math.max(payloadInitialNav, 1e-12);
      }

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
      const targetExposure = Number(ms.policy_exposure_target ?? ms.target_exposure ?? 0);
      const exposureGap = Number(ms.pretrade_policy_lower_shortfall ?? ms.exposure_gap ?? 0);
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
      setMetric("strategic_exposure_budget", fmtPct(Number(ms.strategic_exposure_budget || 0)), Number(ms.strategic_exposure_budget || 0));
      setMetric("signal_supported_exposure", fmtPct(Number(ms.signal_supported_exposure || 0)), Number(ms.signal_supported_exposure || 0));
      setMetric("integer_feasible_exposure", fmtPct(Number(ms.integer_feasible_exposure || 0)), Number(ms.integer_feasible_exposure || 0));
      setMetric("planned_exposure", fmtPct(Number(ms.planned_exposure || 0)), Number(ms.planned_exposure || 0));
      setMetric("target_exposure", fmtPct(Number(ms.target_exposure || 0)), Number(ms.target_exposure || 0));
      setMetric("actual_exposure", fmtPct(actualExposure), actualExposure);
      setMetric("exposure_gap", fmtPct(exposureGap), -exposureGap);
      setMetric("valid_invested_nav", fmtNum(history[history.length - 1].validInvestedNav || 1.0, 4), (history[history.length - 1].validInvestedNav || 1.0) - 1.0);
      setMetric("benchmark_nav", fmtNum(benchmarkNav, 4), benchmarkNav - 1.0);
      setMetric("excess_nav", fmtNum(excessNav, 4), excessNav - 1.0);
      setMetric("cash_drag", fmtPct(cashDrag), -cashDrag);
      setMetric("buy_accuracy_5d", fmtPct(Number(ms.trailing_buy_accuracy_5d)), Number(ms.trailing_buy_accuracy_5d || 0) - 0.5);
      setMetric("sell_accuracy_5d", fmtPct(Number(ms.trailing_sell_accuracy_5d)), Number(ms.trailing_sell_accuracy_5d || 0) - 0.5);
      setMetric("closed_trade_win_rate", fmtPct(Number(ms.closed_trade_win_rate)), Number(ms.closed_trade_win_rate || 0) - 0.5);
      setMetric("realized_pnl", fmtMoney(Number(ms.realized_pnl || 0)), Number(ms.realized_pnl || 0));
      setMetric("gross_profit", fmtMoney(Number(ms.gross_profit || 0)), Number(ms.gross_profit || 0));
      setMetric("gross_loss", fmtMoney(Number(ms.gross_loss || 0)), Number(ms.gross_loss || 0));
      const grossProfit = Number(ms.gross_profit || 0);
      const grossLoss = Number(ms.gross_loss || 0);
      const reportedProfitFactor = Number(ms.profit_factor);
      const profitFactorText = Math.abs(grossLoss) <= 1e-12 && grossProfit > 0
        ? "∞"
        : fmtNum(reportedProfitFactor, 2);
      const profitFactorDirection = profitFactorText === "∞"
        ? 1.0
        : (Number.isFinite(reportedProfitFactor) ? reportedProfitFactor - 1.0 : 0.0);
      setMetric("profit_factor", profitFactorText, profitFactorDirection);
      setMetric("control_exit_count", String(Number(ms.control_exit_count || 0)), Number(ms.control_exit_count || 0));
      setMetric("control_avoided_loss", fmtMoney(Number(ms.avoided_loss_to_window_low || 0)), Number(ms.avoided_loss_to_window_low || 0));
      setMetric("hard_stop_avoided_loss", fmtMoney(Number(ms.hard_stop_avoided_loss_to_window_low || 0)), Number(ms.hard_stop_avoided_loss_to_window_low || 0));
      setMetric("alpha_collapse_avoided_loss", fmtMoney(Number(ms.alpha_collapse_avoided_loss_to_window_low || 0)), Number(ms.alpha_collapse_avoided_loss_to_window_low || 0));
      setMetric("safety_deleveraging_avoided_loss", fmtMoney(Number(ms.safety_deleveraging_avoided_loss_to_window_low || 0)), Number(ms.safety_deleveraging_avoided_loss_to_window_low || 0));
      setMetric("retail_upgraded_to_one_lot_count", String(Number(ms.retail_upgraded_to_one_lot_count || 0)), Number(ms.retail_upgraded_to_one_lot_count || 0));
      setMetric("retail_lot_cash_insufficient_count", String(Number(ms.retail_lot_cash_insufficient_count || 0)), -Number(ms.retail_lot_cash_insufficient_count || 0));
      setMetric("retail_state_block_count", String(Number(ms.retail_state_block_count || 0)), -Number(ms.retail_state_block_count || 0));
      setMetric("surge_candidate_count", String(Number(ms.surge_candidate_count || 0)), Number(ms.surge_candidate_count || 0));
      setMetric("strong_starter_count", String(Number(ms.strong_starter_count || 0)), Number(ms.strong_starter_count || 0));
      setMetric("starter_2_lot_count", String(Number(ms.starter_2_lot_count || 0)), Number(ms.starter_2_lot_count || 0));
      setMetric("diversify_1_lot_count", String(Number(ms.diversify_1_lot_count || 0)), Number(ms.diversify_1_lot_count || 0));
      setMetric("exhaustion_block_count", String(Number(ms.exhaustion_block_count || 0)), -Number(ms.exhaustion_block_count || 0));
      setMetric("empirical_distribution_score_mean", fmtNum(Number(ms.empirical_distribution_score_mean), 3), Number(ms.empirical_distribution_score_mean || 0) - 0.5);
      setMetric("tail_risk_proxy_mean", fmtNum(Number(ms.tail_risk_proxy_mean), 3), 0.5 - Number(ms.tail_risk_proxy_mean || 0));
      setMetric("trend_direction_score_mean", fmtNum(Number(ms.trend_direction_score_mean), 3), Number(ms.trend_direction_score_mean || 0) - 0.5);
      setMetric("peak_decay_score_mean", fmtNum(Number(ms.peak_decay_score_mean), 3), 0.5 - Number(ms.peak_decay_score_mean || 0));
      setMetric("future_loss_risk_score_mean", fmtNum(Number(ms.future_loss_risk_score_mean), 3), 0.5 - Number(ms.future_loss_risk_score_mean || 0));
      setMetric("minimum_required_holding_count", String(Number(ms.minimum_required_holding_count || 0)), 0);
      setMetric("soft_target_holding_count", String(Number(ms.soft_target_holding_count || 0)), 0);
      setMetric("maximum_allowed_holding_count", String(Number(ms.maximum_allowed_holding_count || 0)), 0);
      setMetric("user_hard_position_cap", Number.isFinite(Number(ms.user_hard_position_cap)) ? String(Number(ms.user_hard_position_cap)) : "未设置", 0);
      setMetric("economic_position_cap", String(Number(ms.economic_position_cap || 0)), 0);
      setMetric("search_position_cap", String(Number(ms.search_position_cap || 0)), 0);
      setMetric("effective_position_cap", String(Number(ms.effective_position_cap || 0)), 0);
      setMetric("selected_position_count", String(Number(ms.selected_position_count ?? 0)), 0);
      setMetric("incremental_expected_wealth_amount", fmtMoney(Number(ms.incremental_expected_wealth_amount || 0)), Number(ms.incremental_expected_wealth_amount || 0));
      setMetric("incremental_cvar_amount", fmtMoney(Number(ms.incremental_cvar_amount || 0)), -Number(ms.incremental_cvar_amount || 0));
      setMetric("model_uncertainty_amount", fmtMoney(Number(ms.model_uncertainty_amount || 0)), -Number(ms.model_uncertainty_amount || 0));
      setMetric("scenario_risk_penalty_amount", fmtMoney(Number(ms.scenario_risk_penalty_amount || 0)), -Number(ms.scenario_risk_penalty_amount || 0));
      setMetric("best_rejected_objective_amount", fmtMoney(Number(ms.best_rejected_objective_amount || 0)), Number(ms.best_rejected_objective_amount || 0));
      setMetric("holding_shortfall_count", String(Number(ms.holding_shortfall_count || 0)), -Number(ms.holding_shortfall_count || 0));
      setMetric("idle_cash_ratio", fmtPct(Number(ms.idle_cash_ratio)), -Number(ms.idle_cash_ratio || 0));
      setMetric("scap_v31_positive_c_fallback_count", String(Number(ms.scap_v31_positive_c_fallback_count || 0)), Number(ms.scap_v31_positive_c_fallback_count || 0));
      setMetric("scap_v31_all_d_streak", String(Number(ms.scap_v31_all_d_streak || 0)), -Number(ms.scap_v31_all_d_streak || 0));
      setMetric("scap_v31_normal_cash_zero_proposal_streak", String(Number(ms.scap_v31_normal_cash_zero_proposal_streak || 0)), -Number(ms.scap_v31_normal_cash_zero_proposal_streak || 0));
      setMetric("defensive_eligible_count", String(Number(ms.defensive_eligible_count || 0)), Number(ms.defensive_eligible_count || 0));
      setMetric("downtrend_decay_count", String(Number(ms.downtrend_decay_count || 0)), -Number(ms.downtrend_decay_count || 0));
      setMetric("protecting_profit_count", String(Number(ms.protecting_profit_count || 0)), Number(ms.protecting_profit_count || 0));
      setMetric("buy_sell_conflict_cooldown_days", String(Number(ms.buy_sell_conflict_cooldown_days || 0)), -Number(ms.buy_sell_conflict_cooldown_days || 0));
      setMetric("candidate_count", String(Number(ms.candidate_count || 0)), 0);
      setMetric("confirmed_count", String(Number(ms.entry_confirmed_count || 0)), Number(ms.entry_confirmed_count || 0));
      setMetric("order_count", String(Number(ms.order_count || 0)), 0);
      setMetric("lifecycle_alerts", String(Number(ms.lifecycle_alert_count || 0)), -Number(ms.lifecycle_alert_count || 0));
      setMetric("pending_orders", String(Number(ms.pending_order_count || 0)), 0);

      const payloadProgress = Number(payload.progress_pct);
      const progress = Number.isFinite(payloadProgress)
        ? Math.min(Math.max(payloadProgress, 0), 100)
        : Math.min((dayIndex + 1) / totalDays * 100, 100);
      lastProgressPct = progress;
      document.getElementById("progressBar").style.width = `${progress.toFixed(1)}%`;
      document.getElementById("status").textContent = `${String(payload.date || "").slice(0,10)} | ${dayIndex + 1}/${totalDays} | ${progress.toFixed(1)}%`;

      document.getElementById("benchmarkText").textContent = [
        `账户净值              : ${fmtNum(navMultiple, 4)} (${fmtPct(totalReturn)})`,
        `绩效基准ID            : ${String(ms.performance_benchmark_id || "top_liquidity_100_equal_weight_monthly")}`,
        `基准成分/收益覆盖      : ${Number(ms.performance_benchmark_member_count || 0)} / ${fmtPct(Number(ms.performance_benchmark_return_coverage || 0))}`,
        `本日重平衡/换手        : ${Boolean(ms.performance_benchmark_rebalanced) ? "是" : "否"} / ${fmtPct(Number(ms.performance_benchmark_turnover || 0))}`,
        `基准净值              : ${fmtNum(benchmarkNav, 4)} (${fmtPct(benchmarkNav - 1.0)})`,
        `超额净值              : ${fmtNum(excessNav, 4)} (${fmtPct(excessNav - 1.0)})`,
        `账户最大回撤          : ${fmtPct(maxDrawdown)}`,
        `持仓最大回撤          : ${fmtPct(holdingMaxDrawdown)}`,
        `基准最大回撤          : ${fmtPct(benchmarkMaxDrawdown)}`,
        `超额最大回撤          : ${fmtPct(excessMaxDrawdown)}`,
        `安全ETF(${String(ms.safety_benchmark_id || "sh510300")}) 5日收益 : ${fmtPct(Number(ms.benchmark_return_5d))}`,
        `安全ETF 20日收益      : ${fmtPct(Number(ms.benchmark_return_20d))}`,
        `安全ETF 5日回撤       : ${fmtPct(Number(ms.benchmark_drawdown_5d))}`,
        `安全ETF 20日回撤      : ${fmtPct(Number(ms.benchmark_drawdown_20d))}`,
        `安全ETF距峰值回撤     : ${fmtPct(Number(ms.benchmark_underwater_from_peak))}`,
        `20日跑赢比例          : ${fmtPct(rollingBeatRatio(20))}`,
        `60日跑赢比例          : ${fmtPct(rollingBeatRatio(60))}`,
        `120日跑赢比例         : ${fmtPct(rollingBeatRatio(120))}`
      ].join("\\n");

      document.getElementById("exposureText").textContent = [
        `现金                  : ${fmtMoney(Number(exposure.cash || 0))}`,
        `已投入市值            : ${fmtMoney(Number(exposure.invested_value || 0))}`,
        `实际仓位              : ${fmtPct(actualExposure)}`,
        `目标仓位              : ${fmtPct(targetExposure)}`,
        `授权仓位上限          : ${fmtPct(Number(ms.effective_target_exposure_cap || 0))}`,
        `仓位缺口              : ${fmtPct(exposureGap)}`,
        `最新现金拖累          : ${fmtPct(cashDrag)}`,
        `普通换手权重          : ${fmtPct(Number(ms.normal_turnover_weight || 0))}`,
        `换手预算              : ${fmtPct(Number(ms.turnover_budget || 0))}`,
        `允许追仓              : ${String(Boolean(ms.catchup_allowed || false))}`,
        `追仓档位              : ${String(ms.catchup_tier || "none")}`,
        `追仓拦截原因          : ${String(ms.catchup_block_reason || "--")}`
      ].join("\\n");

      document.getElementById("exposureText").textContent += [
        "",
        `Normal rebalance cadence : ${String(ms.portfolio_normal_rebalance_frequency || "--")} / ${String(ms.portfolio_normal_rebalance_anchor || "--")}`,
        `Plan execution window    : ${String(ms.monthly_plan_execution_window_sessions ?? 0)} sessions`,
        `Daily deployment cap     : ${String(ms.max_daily_new_names ?? 0)} names / ${fmtPct(Number(ms.max_daily_new_exposure_ratio || 0))}`,
        `Capacity cash/cost/risk  : ${String(ms.lot_cash_position_cap ?? 0)} / ${String(ms.cost_feasible_position_cap ?? 0)} / ${String(ms.risk_feasible_position_cap ?? 0)}`,
        `Effective K / legacy hold: ${String(ms.effective_position_cap ?? 0)} / ${String(ms.grandfathered_excess_names ?? 0)}`
      ].join("\\n");

      document.getElementById("entryGateText").textContent = [
        `候选数量              : ${String(ms.candidate_count ?? 0)}`,
        `买入确认数量          : ${String(ms.entry_confirmed_count ?? 0)}`,
        `确认比例              : ${fmtPct(Number(ms.candidate_count || 0) > 0 ? Number(ms.entry_confirmed_count || 0) / Number(ms.candidate_count || 1) : 0)}`,
        `订单流通过数          : ${String(ms.orderflow_candidate_pass_count ?? 0)}`,
        `反转通过数            : ${String(ms.reversal_confirm_pass_count ?? 0)}`,
        `突破通过数            : ${String(ms.breakout_gate_pass_count ?? 0)}`,
        `订单流均分            : ${fmtNum(Number(ms.orderflow_candidate_score_mean), 3)}`,
        `反转均分              : ${fmtNum(Number(ms.reversal_entry_score_mean), 3)}`,
        `突破均分              : ${fmtNum(Number(ms.breakout_gate_score_mean), 3)}`,
        `趋势持有均分          : ${fmtNum(Number(ms.trend_hold_score_mean), 3)}`,
        `模块候选均分          : ${fmtNum(Number(ms.module_candidate_score_mean), 3)}`,
        `模块买入均分          : ${fmtNum(Number(ms.module_entry_score_mean), 3)}`,
        `模块持有均分          : ${fmtNum(Number(ms.module_hold_score_mean), 3)}`,
        `总公式-Alpha均分       : ${fmtNum(Number(ms.entry_alpha_score_mean), 3)}`,
        `总公式-择时均分        : ${fmtNum(Number(ms.entry_timing_score_mean), 3)}`,
        `总公式-流动性均分      : ${fmtNum(Number(ms.entry_liquidity_score_mean), 3)}`,
        `总公式-矩阵均分        : ${fmtNum(Number(ms.entry_matrix_score_mean), 3)}`,
        `股票质量均分          : ${fmtNum(Number(ms.alpha_quality_score_mean), 3)}`,
        `急涨捕捉均分          : ${fmtNum(Number(ms.surge_capture_score_mean), 3)}`,
        `承接确认均分          : ${fmtNum(Number(ms.follow_through_score_mean), 3)}`,
        `冲高衰竭均分          : ${fmtNum(Number(ms.exhaustion_score_mean), 3)}`,
        `入场成功概率均分      : ${fmtPct(Number(ms.entry_success_probability_mean || 0))}`,
        `阴跌衰减均分          : ${fmtNum(Number(ms.downtrend_decay_score_mean), 3)}`,
        `买后表现失败均分      : ${fmtNum(Number(ms.post_entry_failure_score_mean), 3)}`,
        `急涨候选数量          : ${String(ms.surge_candidate_count ?? 0)}`,
        `强启动候选数量        : ${String(ms.strong_starter_count ?? 0)}`,
        `两手首买候选数量      : ${String(ms.starter_2_lot_count ?? 0)}`,
        `衰竭拦截数量          : ${String(ms.exhaustion_block_count ?? 0)}`,
        `阴跌风险数量          : ${String(ms.downtrend_decay_count ?? 0)}`,
        `利润保护持仓          : ${String(ms.protecting_profit_count ?? 0)}`,
        `买卖冲突冷却天数      : ${String(ms.buy_sell_conflict_cooldown_days ?? 0)}`,
        `买入5日准确率         : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `授权10日胜率均值      : ${fmtPct(Number(ms.authorization_p_win_10d_mean || 0))}`,
        `授权10日优势均值      : ${fmtPct(Number(ms.authorization_expected_edge_10d_mean || 0))}`,
        `授权档位              : ${String(ms.exposure_authorization_tier || "--")}`,
        `授权拦截              : ${String(ms.exposure_authorization_block_reasons || "--")}`,
        `市场状态叠加模式      : ${String(ms.regime_overlay_mode || "--")}`,
        `市场状态是否限幅      : ${String(Boolean(ms.regime_overlay_capped || false))}`,
        "",
        "拦截原因：",
        ...summaryLines(ms.entry_block_summary || [], "暂无拦截数据")
      ].join("\\n");

      if (String(ms.strategy_logic_version || "").startsWith("mainline_v3")) {
        document.getElementById("entryGateText").textContent += [
          "", `Cabinet-native v3 (${String(ms.strategy_logic_version || "not_initialized")})`,
          `Strict entry family : ${fmtNum(Number(ms.cabinet_strict_entry_score_mean), 3)}`,
          `Proxy entry family  : ${fmtNum(Number(ms.cabinet_proxy_entry_score_mean), 3)}`,
          `Timing role         : ${fmtNum(Number(ms.cabinet_timing_score_mean), 3)}`,
          `Liquidity health    : ${fmtNum(Number(ms.cabinet_liquidity_health_score_mean), 3)}`,
          `Risk safety         : ${fmtNum(Number(ms.cabinet_risk_safety_score_mean), 3)}`,
          `Hold support        : ${fmtNum(Number(ms.cabinet_hold_support_score_mean), 3)}`,
          `ML fusion weight    : ${fmtNum(Number(ms.monthly_lgbm_effective_weight || 0), 3)}`,
          `Temporal isolation  : ${String(ms.factor_temporal_isolation_status || "NOT_EVALUATED")}`,
          `Family replacement  : ${String(ms.factor_family_replacement_status || "NOT_EVALUATED")}`,
          `Causal audit        : ${String(ms.factor_causal_audit_status || "NOT_EVALUATED")}`,
          `PIT Level-2         : ${String(ms.pit_level2_runtime_state || "degraded")}`,
        ].join("\\n");
      }
      document.getElementById("tradeQualityText").textContent = [
        `买入5日准确率         : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `卖出5日准确率         : ${fmtPct(Number(ms.trailing_sell_accuracy_5d))}`,
        `最佳替换优势          : ${fmtPct(Number(ms.best_replacement_edge_10d || 0))}`,
        `替换卖出数量          : ${String(ms.replacement_opportunity_sell_count ?? 0)}`,
        `利润回吐观察数        : ${String(ms.profit_giveback_observation_count ?? 0)}`,
        `买后表现失败卖出数    : ${String(ms.post_entry_failure_exit_count ?? 0)}`,
        `趋势破坏观察数        : ${String(ms.trend_break_observation_count ?? 0)}`,
        `量能分布观察数        : ${String(ms.volume_distribution_observation_count ?? 0)}`,
        `生命周期警报数        : ${String(ms.lifecycle_alert_count ?? 0)}`,
        `计划订单数            : ${String(ms.order_count ?? 0)}`,
        `未完成订单数          : ${String(ms.pending_order_count ?? 0)}`,
        "",
        "订单原因：",
        ...summaryLines(ms.order_reason_summary || [], "暂无订单原因")
      ].join("\\n");

      document.getElementById("riskModelText").textContent = [
        `使用协方差风险模型    : ${String(Boolean(ms.covariance_risk_model_used || false))}`,
        `组合协方差波动        : ${fmtPct(Number(ms.portfolio_covariance_volatility || 0))}`,
        `最大风险贡献          : ${fmtPct(Number(ms.max_risk_contribution || 0))}`,
        `前5风险贡献（描述）   : ${fmtPct(Number(ms.top5_risk_contribution_sum || 0))}`,
        `头部20%风险贡献       : ${fmtPct(Number(ms.top20pct_risk_contribution_sum || 0))}`,
        `风险有效N/K           : ${fmtNum(Number(ms.risk_effective_n_ratio || 0), 3)}`,
        `风险HHI               : ${fmtNum(Number(ms.risk_contribution_hhi || 0), 3)}`,
        `风险门控通过          : ${String(Boolean(ms.risk_contribution_gate_pass ?? true))}`,
        `风险仓位缩放          : ${fmtNum(Number(ms.risk_contribution_exposure_scale || 1), 3)}`,
        `风险股票数            : ${String(ms.risk_symbol_count ?? 0)}`,
        `风险拦截原因          : ${String(ms.risk_contribution_block_reason || "--")}`,
        `新买入拦截            : ${String(Boolean(ms.risk_new_buy_block || false))}`,
        `新买入拦截已应用      : ${String(Boolean(ms.risk_new_buy_block_applied || false))}`,
        `追仓拦截              : ${String(Boolean(ms.risk_catchup_block || false))}`,
        `追仓拦截已应用        : ${String(Boolean(ms.risk_catchup_block_applied || false))}`,
        `被拦截新买入权重      : ${fmtPct(Number(ms.risk_blocked_new_buy_weight || 0))}`,
        `平均两两相关          : ${fmtNum(Number(ms.avg_pairwise_correlation || 0), 3)}`,
        `条件数                : ${fmtNum(Number(ms.covariance_condition_number || 0), 1)}`,
        `风险等级              : ${String(ms.risk_level || "--")}`,
        `原始风险等级          : ${String(ms.raw_risk_level || "--")}`,
        `流动性压力            : ${fmtPct(Number(ms.market_liquidity_stress_ratio || 0))}`,
        `未解决安全仓位        : ${fmtPct(Number(ms.unresolved_safety_exposure || 0))}`,
        `计划安全卖出          : ${fmtPct(Number(ms.planned_safety_sell_weight || 0))}`
      ].join("\\n");

      const body = document.getElementById("holdingsBody");
      body.innerHTML = "";
      const accountNavForWeights = Number(exposure.nominal_nav || exposure.liquidatable_nav || nav || 0);
      const ranked = holdings
        .filter(x => String(x.symbol || "").trim())
        .map(x => ({
          symbol: String(x.symbol),
          market_value: Number(x.market_value || 0),
          account_weight: Number(x.account_weight)
        }))
        .sort((a,b)=>b.market_value-a.market_value)
        .slice(0, 16);
      for (const item of ranked) {
        const tr = document.createElement("tr");
        const weight = Number.isFinite(item.account_weight)
          ? item.account_weight
          : (accountNavForWeights > 0 ? item.market_value / accountNavForWeights : 0);
        tr.innerHTML = `<td>${item.symbol}</td><td>${fmtMoney(item.market_value)}</td><td>${fmtPct(weight)}</td>`;
        body.appendChild(tr);
      }
      if (!ranked.length) body.innerHTML = `<tr><td colspan="3">暂无持仓。</td></tr>`;

      const lifecycleBody = document.getElementById("lifecycleBody");
      lifecycleBody.innerHTML = "";
      const lifecycleRows = (ms.holding_lifecycle_preview || []).slice(0, 12);
      for (const item of lifecycleRows) {
        const paperReasons = {profit_giveback_exit: "利润回吐", profit_hard_stop_exit: "利润保护", loss_containment_exit: "损失控制", signal_failure_exit: "信号失效", thesis_failure_exit: "投资逻辑失效", post_entry_failure_exit: "买后表现失败", stale_time_exit: "持仓陈旧"};
        const alert = item.position_exit_reason
          ? String(item.position_exit_reason)
          : item.paper_exit_reason
            ? `纸面观察：${paperReasons[item.paper_exit_reason] || item.paper_exit_reason}（未执行）`
            : item.profit_giveback_flag
              ? "利润回吐观察"
              : item.post_entry_failure_flag ? "买后表现失败观察" : "";
        const stateText = `${String(item.position_state || "--")}${item.add_allowed ? " / 可补仓" : ""}`;
        const tr = document.createElement("tr");
        tr.innerHTML = [
          `<td>${String(item.symbol || "")}</td>`,
          `<td>${String(item.entry_date || "--")}</td>`,
          `<td>${fmtPct(Number(item.unrealized_return || 0))}</td>`,
          `<td>${fmtPct(Number(item.mfe || 0))}</td>`,
          `<td>${fmtPct(Number(item.mae || 0))}</td>`,
          `<td>${item.giveback_armed ? fmtPct(Number(item.giveback_from_peak || 0)) : "--"}</td>`,
          `<td>${fmtNum(Number(item.trend_direction_score || 0), 2)}</td>`,
          `<td>${fmtNum(Number(item.peak_decay_score || 0), 2)}</td>`,
          `<td>${fmtNum(Number(item.future_loss_risk_score || 0), 2)}</td>`,
          `<td>${stateText}</td>`,
          `<td style="color:${alert ? "#b3403a" : "#173f35"}">${alert || "正常"}</td>`
        ].join("");
        lifecycleBody.appendChild(tr);
      }
      if (!lifecycleRows.length) lifecycleBody.innerHTML = `<tr><td colspan="11">暂无持仓生命周期记录。</td></tr>`;

      const candidateLines = [`排序候选预览（不等于拥有交易权，共${Number(ms.candidate_count || 0)}只）`, "", "代码         分数   权限  权限收益   人民币效用  状态       拦截/权限原因"];
      for (const item of (ms.candidate_preview || [])) {
        candidateLines.push(
          `${String(item.symbol || "").padEnd(10)} ${fmtNum(Number(item.primary_score || 0),3).padStart(7)} ${String(item.scap_v31_authority_tier || "D").padStart(4)} ${fmtPct(Number(item.scap_v31_decision_expected_return || 0)).padStart(9)} ${fmtMoney(Number(item.scap_candidate_utility || 0)).padStart(11)} ${String(item.position_state || "--").slice(0,10).padEnd(10)} ${String(item.entry_block_reason || item.scap_v31_authority_reason || item.add_block_reason || "").slice(0,30)}`
        );
      }
      if ((ms.candidate_preview || []).length === 0) candidateLines.push("暂无候选预览。");
      candidateLines.push("", `已确认候选（${Number(ms.entry_confirmed_count || 0)}）`, "");
      for (const item of (ms.confirmed_preview || [])) {
        candidateLines.push(
          `${String(item.symbol || "").padEnd(10)} ${fmtNum(Number(item.primary_score || 0),3).padStart(7)} ${fmtNum(Number(item.alpha_percentile || 0),2).padStart(6)} ${(Number(item.expected_return_5d || 0)*100).toFixed(2).padStart(6)}% ${fmtNum(Number(item.module_candidate_score || 0),2).padStart(6)} ${fmtNum(Number(item.module_entry_score || 0),2).padStart(5)} ${fmtNum(Number(item.breakout_gate_score || 0),2).padStart(5)} ${fmtNum(Number(item.trend_hold_score || 0),2).padStart(5)} ${String(item.entry_block_reason || "").slice(0,18)}`
        );
      }
      if ((ms.confirmed_preview || []).length === 0) candidateLines.push("暂无已确认候选预览。");
      document.getElementById("candidatesText").textContent = candidateLines.join("\\n");

      const orderLines = ["最新计划订单", ""];
      for (const item of (ms.order_preview || [])) {
        orderLines.push(`${String(item.side || "").toUpperCase().padEnd(4)} ${String(item.symbol || "").padEnd(10)} ${fmtPct(Number(item.delta_weight || 0)).padStart(8)}  p=${String(item.priority ?? "")}  ${String(item.reason || "")}`);
      }
      if ((ms.order_preview || []).length === 0) orderLines.push("本次刷新没有新订单。");
      document.getElementById("ordersText").textContent = orderLines.join("\\n");

      const pendingLines = [`未完成订单（${Number(ms.pending_order_count || 0)}）`, ""];
      for (const item of (ms.pending_preview || [])) {
        pendingLines.push(`${String(item.side || "").toUpperCase().padEnd(4)} ${String(item.symbol || "").padEnd(10)} shares=${fmtNum(Number(item.remaining_shares || 0),0).padStart(10)} ${String(item.status || "").padEnd(14)} lock=${fmtNum(Number(item.lock_days || 0),0)} policy=${String(item.order_execution_policy || "--")} age=${String(item.signal_age_sessions ?? "--")}/${String(item.maximum_age_sessions ?? "--")} 当前=${String(item.reason || "")} 历史=${String(item.reason_history || item.reason || "")}`);
      }
      if ((ms.pending_preview || []).length === 0) pendingLines.push("暂无有效未完成订单。");
      document.getElementById("pendingText").textContent = pendingLines.join("\\n");

      document.getElementById("orderReasonText").textContent = summaryLines(ms.order_reason_summary || [], "暂无计划订单。").join("\\n");

      const moduleBody = document.getElementById("moduleWeightsBody");
      moduleBody.innerHTML = "";
      const moduleRows = (ms.module_weights || [])
        .slice()
        .sort((a, b) => Number(b.weight_share || 0) - Number(a.weight_share || 0))
        .slice(0, 12);
      for (const item of moduleRows) {
        const tr = document.createElement("tr");
        tr.innerHTML = [
          `<td>${String(item.factor_module || "未知").slice(0, 22)}</td>`,
          `<td>${fmtPct(Number(item.weight_share || 0))}</td>`,
          `<td>${String(item.factor_count ?? 0)}</td>`,
          `<td>${fmtPct(Number(item.avg_predicted_return_5d || 0))}</td>`
        ].join("");
        moduleBody.appendChild(tr);
      }
      if (!moduleRows.length) moduleBody.innerHTML = `<tr><td colspan="4">暂无模块权重。</td></tr>`;

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
          `<td>${String(item.factor_module || "未知").slice(0, 18)}</td>`,
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
      if (!factorRows.length) factorBody.innerHTML = `<tr><td colspan="8">暂无因子权重。</td></tr>`;

      const safe = [
        "安全状态",
        "",
        `风险等级              : ${String(ms.risk_level || "--")}`,
        `原始风险等级          : ${String(ms.raw_risk_level || "--")}`,
        `触发连续天数          : ${String(ms.trigger_streak_days ?? "--")}`,
        `触发来源              : ${String(ms.trigger_source || "--")}`,
        `基准5日回撤           : ${fmtPct(Number(ms.benchmark_drawdown_5d))}`,
        `基准20日回撤          : ${fmtPct(Number(ms.benchmark_drawdown_20d))}`,
        `基准5日收益           : ${fmtPct(Number(ms.benchmark_return_5d))}`,
        `基准20日收益          : ${fmtPct(Number(ms.benchmark_return_20d))}`,
        `距峰值回撤            : ${fmtPct(Number(ms.benchmark_underwater_from_peak))}`,
        `流动性压力比例        : ${fmtPct(Number(ms.market_liquidity_stress_ratio || 0))}`,
        `结构性市场状态        : ${String(ms.structural_regime_level || "--")}`,
        `状态仓位预算          : ${fmtPct(Number(ms.regime_exposure_budget || 0))}`,
        `安全仓位上限          : ${fmtPct(Number(ms.safety_exposure_cap || 0))}`,
        `硬冻结                : ${String(Boolean(ms.hard_freeze_active || false))}`,
        `仓位上限              : ${fmtPct(Number(ms.exposure_cap || 0))}`,
        `目标仓位              : ${fmtPct(Number(ms.target_exposure || 0))}`,
        `实际仓位              : ${fmtPct(actualExposure)}`,
        `仓位缺口              : ${fmtPct(exposureGap)}`,
        `允许追仓              : ${String(Boolean(ms.catchup_allowed || false))}`,
        `追仓档位              : ${String(ms.catchup_tier || "none")}`,
        `准确率乘数            : ${fmtNum(Number(ms.accuracy_multiplier || 0), 2)}`,
        `追仓拦截原因          : ${String(ms.catchup_block_reason || "--")}`,
        `追仓买入预算          : ${fmtPct(Number(ms.catchup_buy_budget || 0))}`,
        `买入5日准确率         : ${fmtPct(Number(ms.trailing_buy_accuracy_5d))}`,
        `最佳替换10日优势      : ${fmtPct(Number(ms.best_replacement_edge_10d || 0))}`,
        `替换卖出数量          : ${String(ms.replacement_opportunity_sell_count ?? 0)}`,
        `使用协方差风险模型    : ${String(Boolean(ms.covariance_risk_model_used || false))}`,
        `组合协方差波动        : ${fmtPct(Number(ms.portfolio_covariance_volatility || 0))}`,
        `最大风险贡献          : ${fmtPct(Number(ms.max_risk_contribution || 0))}`,
        `平均两两相关          : ${fmtNum(Number(ms.avg_pairwise_correlation || 0), 3)}`,
        `未解决安全仓位        : ${fmtPct(Number(ms.unresolved_safety_exposure || 0))}`,
        `计划安全卖出          : ${fmtPct(Number(ms.planned_safety_sell_weight || 0))}`,
        `约束现金保留          : ${fmtPct(Number(ms.constraint_cash_reserve || 0))}`,
        `普通换手权重          : ${fmtPct(Number(ms.normal_turnover_weight || 0))}`,
        `总目标漂移            : ${fmtPct(Number(ms.total_target_drift || 0))}`,
        `运行状态              : ${String(ms.regime || "--")}`,
        `状态基础仓位          : ${fmtPct(Number(ms.base_exposure_by_regime || 0))}`,
        `原始安全上限          : ${fmtPct(Number(ms.raw_safety_exposure_cap || 0))}`,
        `有效目标上限          : ${fmtPct(Number(ms.effective_target_exposure_cap || 0))}`,
        `换手预算              : ${fmtPct(Number(ms.turnover_budget || 0))}`,
        `最大持股数            : ${String(ms.top_n ?? "--")}`
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
        document.getElementById("status").textContent = `监控连接异常：${err}`;
      }
      setTimeout(poll, 1000);
    }
    poll();
  </script>
</body>
</html>
"""

# Keep the HTTP/state transport stable while the dashboard presentation lives
# in a separate, testable template module. The fallback supports the production
# launcher, which executes this file directly rather than with ``python -m``.
try:
    from functions.decision_council.live_monitor_dashboard import HTML as PROFESSIONAL_HTML
except ModuleNotFoundError:
    from live_monitor_dashboard import HTML as PROFESSIONAL_HTML

HTML = PROFESSIONAL_HTML

try:
    from functions.decision_council.factor_curve_web import (
        FactorStore,
        HTML as FACTOR_HTML,
    )
    from functions.decision_council.holding_factor_products import (
        FACTOR_PRODUCT_DIRNAME,
        FACTOR_WORKBOOK_NAME,
    )
except ModuleNotFoundError:
    from factor_curve_web import FactorStore, HTML as FACTOR_HTML
    from holding_factor_products import (
        FACTOR_PRODUCT_DIRNAME,
        FACTOR_WORKBOOK_NAME,
    )


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
        print("用法: live_monitor_web.py <state_json_path>")
        return 1

    state_path = Path(argv[1])
    stop_event = threading.Event()
    port = _pick_port()
    factor_store_cache = {"data_dir": "", "store": None}

    def factor_product_paths() -> tuple[Path | None, Path | None]:
        payload = _read_payload(state_path)
        output_value = str(payload.get("output_dir", "") or "").strip()
        if not output_value:
            return None, None
        data_dir = Path(output_value) / FACTOR_PRODUCT_DIRNAME
        return data_dir, data_dir / FACTOR_WORKBOOK_NAME

    def factor_store():
        data_dir, _ = factor_product_paths()
        if data_dir is None:
            return None
        required = (
            data_dir / "holding_factor_scores_long.csv",
            data_dir / "holding_daily.csv",
        )
        if not all(path.is_file() for path in required):
            return None
        data_token = str(data_dir.resolve())
        if factor_store_cache["data_dir"] != data_token:
            factor_store_cache["store"] = FactorStore(data_dir)
            factor_store_cache["data_dir"] = data_token
        return factor_store_cache["store"]

    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/state":
                body = json.dumps(_read_payload(state_path), ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8")
                return
            if parsed.path in {"/factors", "/factors/"}:
                self._send_bytes(FACTOR_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/meta":
                store = factor_store()
                if store is None:
                    body = json.dumps(
                        {
                            "status": "pending",
                            "message": "运行尚未保存完成，逐因子曲线将在保存阶段自动生成。",
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    self.send_response(202)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._send_bytes(
                    json.dumps(store.meta(), ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if parsed.path == "/api/series":
                store = factor_store()
                if store is None:
                    self.send_error(404, "factor product is not ready")
                    return
                query = parse_qs(parsed.query)
                symbol = str(query.get("symbol", [store.symbols[0]])[0])
                metric = str(query.get("metric", ["predicted_return_5d"])[0])
                factors = [
                    item
                    for item in str(query.get("factors", [""])[0]).split("|")
                    if item
                ]
                if symbol not in store.symbols:
                    self.send_error(404, "unknown symbol")
                    return
                self._send_bytes(
                    json.dumps(
                        store.series(symbol, metric, factors),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if parsed.path == "/factor-workbook":
                _, workbook_path = factor_product_paths()
                if workbook_path is None or not workbook_path.is_file():
                    self.send_error(404, "factor workbook is not ready")
                    return
                body = workbook_path.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="SCAP_holding_factor_curves.xlsx"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path not in ("/", "/index.html"):
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
    endpoint_path = state_path.with_suffix(".endpoint.json")
    endpoint_path.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": os.getpid(),
                "url": url,
                "state_path": str(state_path),
                "started_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"治理实时监控浏览器地址: {url}")
    try:
      opened = webbrowser.open(url, new=1)
    except Exception:
      opened = False
    if not opened:
        print("浏览器没有自动打开，请手动打开上面的地址。")

    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        stop_event.set()
        server.server_close()
        try:
            endpoint_path.write_text(
                json.dumps({"status": "stopped", "pid": os.getpid(), "url": url}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
