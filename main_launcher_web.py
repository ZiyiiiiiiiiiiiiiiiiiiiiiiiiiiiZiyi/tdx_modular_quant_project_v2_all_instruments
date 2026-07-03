"""Browser-based launcher and backtest result viewer for main.py.

This avoids Tk/Spyder event-loop conflicts by using the system browser.
"""
from __future__ import annotations

import csv
import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


TRADE_PAIR_PREFIX = "backtest_trade_pairs_"
OPEN_POSITION_PREFIX = "backtest_open_positions_"
METRICS_PREFIX = "backtest_metrics_"


RUN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>量化运行配置</title>
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
      max-width: 920px;
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
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
    }
    .head a {
      color: #fff3bd;
      font-size: 14px;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,0.35);
      border-radius: 999px;
      padding: 7px 11px;
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
    .progress-box {
      margin-top: 16px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffef9;
    }
    .progress-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .progress-track {
      height: 12px;
      background: #e8e1d2;
      border-radius: 999px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      background: #173f35;
      transition: width 0.3s ease;
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
    <div class="head"><span>量化运行配置</span><a href="/results" target="_blank">打开回测结果页</a></div>
    <div class="body">
      <div class="section-title">选择要运行的任务</div>
      <label class="item"><input type="checkbox" id="main_pipeline">主策略流水线/回测：使用下面账户参数运行普通策略路径。</label>
      <label class="item"><input type="checkbox" id="governance_active">治理主线单次运行：只跑默认股票池，适合观察弹窗监控和排查行为问题。</label>
      <label class="item recommended"><input type="checkbox" id="governance_layer_ablation_suite">增强模块诊断：一次运行核心基线、简单止盈止损、趋势/反转/订单流/突破模块、减模块测试、市场状态、校准诊断、复杂退出和主线对照。</label>
      <label class="item"><input type="checkbox" id="governance_layer_validation">层验证线：紧凑 8 因子等权测试，关闭声誉/影子组合和市场状态叠加，保留安全模块。用于先判断基础信号有没有边际收益。</label>
      <label class="item"><input type="checkbox" id="governance_mainline_review" checked>治理主线复核：模块诊断证明候选策略更干净后，再运行偏生产风格的复核。</label>
      <label class="item recommended"><input type="checkbox" id="fast_factor_judge">快速因子审判：只读现有特征和股票池，计算 IC/分层/换手成本/冗余，不跑状态机、不下单、不跑完整回测。</label>

      <div class="hint">
        当前建议：先运行“增强模块诊断”。<br>
        目的不是追求一次跑出好看收益，而是定位问题来自趋势、反转、订单流、突破、市场状态、校准诊断、简单退出、复杂退出，还是主线叠加。<br>
        “治理主线复核”建议在诊断结果明确后再跑。
      </div>

      <div class="section-title">回测账户</div>
      <div class="grid">
        <div class="field">
          <label for="capital_profile">资金档位</label>
          <select id="capital_profile">
            <option value="small_capital_branch" selected>小资金支线（2万，一手适配）</option>
            <option value="institutional_1m">100万基线账户</option>
            <option value="institutional_10m">1000万对照账户</option>
            <option value="retail_20k">2万小资金账户</option>
          </select>
        </div>
        <div class="field">
          <label for="initial_cash">初始资金，可选覆盖</label>
          <input type="number" id="initial_cash" min="1" step="1000" placeholder="留空=使用所选档位">
        </div>
        <div class="field">
          <label for="max_positions_account">最多买入/持有股票数量</label>
          <input type="number" id="max_positions_account" min="0" step="1" placeholder="小资金建议 3-5；留空=档位默认；0=不限制">
        </div>
        <div class="field">
          <label for="min_cash_buffer">现金缓冲，可选</label>
          <input type="number" id="min_cash_buffer" min="0" step="100" placeholder="留空=档位默认">
        </div>
        <div class="field">
          <label for="capital_usage_mode">资金使用模式</label>
          <select id="capital_usage_mode">
            <option value="allow_cash" selected>允许空余资金</option>
            <option value="force_deploy">强制提高资金使用率</option>
          </select>
        </div>
      </div>
      <div class="mini">
        这些账户设置影响主策略回测。2万小资金档位会限制持股数量并保留现金缓冲，让 A 股一手 100 股的买入约束真实暴露出来。
      </div>

      <div class="section-title">治理诊断参数</div>
      <label class="item"><input type="checkbox" name="universe" value="hs300_csi500_a500_strict" checked>hs300_csi500_a500_strict：沪深300 + 中证500 + A500，当前建议的宽研究池。</label>
      <label class="item"><input type="checkbox" name="universe" value="hs300_strict">hs300_strict：只看沪深300，偏防守的大盘对照池。第一次增强诊断可先不选以节省时间。</label>
      <label class="item"><input type="checkbox" name="universe" value="hs300_csi300_a500_strict">hs300_csi300_a500_strict：沪深300/CSI300 + A500 旧口径对照池。</label>
      <label class="item"><input type="checkbox" name="universe" value="csi500_strict">csi500_strict：只看中证500，适合第二层股票池隔离测试。</label>
      <div class="grid">
        <div class="field">
          <label for="governance_control_mode">控制层模式</label>
          <select id="governance_control_mode">
            <option value="normal" selected>正常治理：全部控制启用</option>
            <option value="factor_only">因子裸跑：暂停 reputation/regime/复杂卖出/冷却/硬止损</option>
            <option value="paper_controls">纸面控制：控制层只记录，不实际支配买卖</option>
            <option value="safe_factor_only">安全裸跑：因子裸跑，但保留硬止损</option>
          </select>
        </div>
        <div class="field">
          <label for="governance_alpha_bundle">治理主线因子包</label>
          <select id="governance_alpha_bundle">
            <option value="diversified_pre_screen_bundle_v2" selected>diversified_pre_screen_bundle_v2 - 24 candidate diversified alpha</option>
            <option value="pre_screen_promote_bundle">7月2号预筛产品化包（28个 cand 因子）</option>
            <option value="formal_defensive_bundle">旧正式因子防守复核包</option>
          </select>
        </div>
        <div class="field">
          <label for="start_month">开始月份</label>
          <input type="month" id="start_month" value="2021-01">
        </div>
        <div class="field">
          <label for="end_month">结束月份</label>
          <input type="month" id="end_month" value="2024-12">
        </div>
        <div class="field">
          <label for="max_days">最多交易日，可选</label>
          <input type="number" id="max_days" min="1" step="1" placeholder="留空=使用完整选择区间">
        </div>
        <div class="field">
          <label for="fast_factor_max_count">快速因子审判数量</label>
          <input type="number" id="fast_factor_max_count" min="1" step="100" value="10000" placeholder="10000=全矩阵候选；留空=全部注册池">
        </div>
      </div>
      <label class="item"><input type="checkbox" id="alpha_collapse_exit_enabled" checked>启用 Alpha 信号塌陷卖出：当买入理由消失时卖出；取消勾选后只记录纸面信号，不实际卖出。</label>
      <label class="item"><input type="checkbox" id="shadow_portfolios">启用单因子影子组合：非常慢的诊断模式。普通全历史复核建议关闭。</label>
      <label class="item"><input type="checkbox" id="timestamped_diagnostics" checked disabled>增强诊断后生成带时间戳的表格、图、增量贡献文件和 Markdown 报告。</label>
      <div class="mini">
        增强诊断输出保存在 results/governance/layer_ablation_diagnostics_suite_YYYYMMDD_HHMMSS。
        如果固定名称主线输出已存在，会先归档再覆盖。
      </div>
      <div class="hint">
        月份会在 main.py 中转换：开始月份变成当月第一天，结束月份变成当月最后一天。<br>
        快速模式仍会把治理运行限制到约 180 个交易日，适合调试。完整模式会尊重所选月份，除非设置了“最多交易日”。<br>
        影子组合会按因子数量放大运行时间，只建议短区间诊断时开启。
      </div>

      <div class="section-title">运行模式</div>
      <label class="item"><input type="radio" name="profile" value="fast" checked>快速模式：最近约 1 年，最多 180 个治理交易日，并关闭单因子影子回测。</label>
      <label class="item"><input type="radio" name="profile" value="full">完整模式：使用选择的月份。影子组合仍按上面的勾选决定，除非明确要慢速因子影子运行，否则建议关闭。</label>

      <div class="actions">
        <div>
          <button class="primary" onclick="submitSelected()">运行所选任务</button>
          <button class="primary" onclick="submitFastFactorJudge()">只运行快速因子审判</button>
          <button class="primary" onclick="submitDiagnosticSuite()">只运行增强诊断</button>
          <button class="secondary" onclick="submitLayerSuiteOnly()">只运行层消融套件</button>
          <button class="secondary" onclick="submitAll()">运行全部任务</button>
        </div>
        <button class="ghost" onclick="cancelLaunch()">取消</button>
      </div>
      <div id="status"></div>
      <div class="progress-box">
        <div class="progress-line">
          <span id="progress_title">Progress: waiting for task</span>
          <span id="progress_percent">0%</span>
        </div>
        <div class="progress-track"><div class="progress-fill" id="progress_fill"></div></div>
        <div class="mini" id="progress_detail">Step: -; ETA: -</div>
      </div>
    </div>
  </div>
  <script>
    window.addEventListener("DOMContentLoaded", () => {
      const capitalProfile = document.getElementById("capital_profile");
      if (capitalProfile) {
        Array.from(capitalProfile.options).forEach((option) => {
          option.selected = false;
          option.defaultSelected = false;
        });
        capitalProfile.value = "small_capital_branch";
      }
      startProgressPolling();
    });
    function currentProfile() {
      const node = document.querySelector('input[name="profile"]:checked');
      return node ? node.value : "full";
    }
    function backtestParams() {
      const capitalProfile = document.getElementById("capital_profile").value;
      const initialCash = document.getElementById("initial_cash").value.trim();
      const maxPositions = document.getElementById("max_positions_account").value.trim();
      const minCashBuffer = document.getElementById("min_cash_buffer").value.trim();
      const capitalUsageModeNode = document.getElementById("capital_usage_mode");
      const capitalUsageMode = capitalUsageModeNode ? capitalUsageModeNode.value : "allow_cash";
      if (initialCash && Number(initialCash) <= 0) {
        throw new Error("初始资金必须大于 0。");
      }
      if (maxPositions && Number(maxPositions) < 0) {
        throw new Error("最多持股数不能为负数。");
      }
      if (minCashBuffer && Number(minCashBuffer) < 0) {
        throw new Error("现金缓冲不能为负数。");
      }
      return {
        capital_profile: capitalProfile,
        initial_cash: initialCash,
        max_positions: maxPositions,
        min_cash_buffer: minCashBuffer,
        capital_usage_mode: capitalUsageMode
      };
    }
    function governanceParams(tasks) {
      const universes = Array.from(document.querySelectorAll('input[name="universe"]:checked')).map((node) => node.value);
      const startMonth = document.getElementById("start_month").value;
      const endMonth = document.getElementById("end_month").value;
      const maxDays = document.getElementById("max_days").value.trim();
      const fastFactorMaxCountNode = document.getElementById("fast_factor_max_count");
      const fastFactorMaxCount = fastFactorMaxCountNode ? fastFactorMaxCountNode.value.trim() : "";
      const shadowPortfolios = document.getElementById("shadow_portfolios").checked;
      const alphaCollapseExitNode = document.getElementById("alpha_collapse_exit_enabled");
      const alphaCollapseExitEnabled = alphaCollapseExitNode ? alphaCollapseExitNode.checked : true;
      const controlModeNode = document.getElementById("governance_control_mode");
      const controlMode = controlModeNode ? controlModeNode.value : "normal";
      const alphaBundleNode = document.getElementById("governance_alpha_bundle");
      const alphaBundle = alphaBundleNode ? alphaBundleNode.value : "diversified_pre_screen_bundle_v2";
      const touchesGovernance = tasks.some((task) => task === "governance_active" || task === "governance_mainline_review" || task === "governance_layer_validation" || task === "governance_layer_ablation_suite" || task === "fast_factor_judge");
      if (touchesGovernance && universes.length === 0) {
        throw new Error("请至少选择一个治理股票池。");
      }
      if (startMonth && endMonth && startMonth > endMonth) {
        throw new Error("开始月份不能晚于结束月份。");
      }
      return {
        universes,
        start_month: startMonth,
        end_month: endMonth,
        max_days: maxDays,
        fast_factor_max_count: fastFactorMaxCount,
        shadow_portfolios: shadowPortfolios,
        control_mode: controlMode,
        alpha_bundle: alphaBundle,
        alpha_collapse_exit_enabled: alphaCollapseExitEnabled
      };
    }
    async function sendPayload(payload) {
      const status = document.getElementById("status");
      status.textContent = "正在提交选择...";
      const response = await fetch("/submit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      status.textContent = result.message || "已提交。";
      if (response.ok) {
        startProgressPolling();
      }
    }
    function formatDuration(seconds) {
      if (seconds === null || seconds === undefined || seconds === "") return "-";
      const n = Number(seconds);
      if (!Number.isFinite(n)) return "-";
      if (n < 60) return `${Math.max(0, Math.round(n))}s`;
      const minutes = Math.floor(n / 60);
      const rest = Math.round(n % 60);
      if (minutes < 60) return `${minutes}m ${rest}s`;
      const hours = Math.floor(minutes / 60);
      return `${hours}h ${minutes % 60}m`;
    }
    async function loadProgressOnce() {
      const response = await fetch("/api/progress");
      const data = await response.json();
      const percent = Number(data.percent || 0);
      document.getElementById("progress_title").textContent = `${data.task_name || "task"} | ${data.status || "idle"} | ${data.message || ""}`;
      document.getElementById("progress_percent").textContent = `${percent.toFixed(1)}%`;
      document.getElementById("progress_fill").style.width = `${Math.max(0, Math.min(percent, 100))}%`;
      const countText = data.current && data.total ? `; count: ${data.current}/${data.total}` : "";
      document.getElementById("progress_detail").textContent = `Step: ${data.step || "-"}${countText}; detail: ${data.detail || "-"}; elapsed: ${formatDuration(data.elapsed_seconds)}; ETA: ${formatDuration(data.eta_seconds)}`;
      return data;
    }
    let progressTimer = null;
    function startProgressPolling() {
      if (progressTimer) clearInterval(progressTimer);
      loadProgressOnce().catch(() => {});
      progressTimer = setInterval(async () => {
        try {
          const data = await loadProgressOnce();
          if (["complete", "failed"].includes(String(data.status || ""))) {
            clearInterval(progressTimer);
            progressTimer = null;
          }
        } catch (err) {
          document.getElementById("progress_detail").textContent = `Progress read failed: ${err.message || err}`;
        }
      }, 2000);
    }
    async function submitSelected() {
      const tasks = [];
      ["main_pipeline", "governance_active", "governance_mainline_review", "governance_layer_validation", "governance_layer_ablation_suite", "fast_factor_judge"].forEach((id) => {
        const node = document.getElementById(id);
        if (node && node.checked) tasks.push(id);
      });
      if (tasks.length === 0) {
        document.getElementById("status").textContent = "请至少选择一个任务。";
        return;
      }
      try {
        await sendPayload({tasks, profile: currentProfile(), backtest: backtestParams(), governance: governanceParams(tasks), allow_multi_task: false});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitDiagnosticSuite() {
      const tasks = ["governance_layer_ablation_suite"];
      document.getElementById("governance_layer_ablation_suite").checked = true;
      document.getElementById("shadow_portfolios").checked = false;
      try {
        await sendPayload({tasks, profile: currentProfile(), backtest: backtestParams(), governance: governanceParams(tasks), allow_multi_task: false});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitLayerSuiteOnly() {
      const tasks = ["governance_layer_ablation_suite"];
      document.getElementById("shadow_portfolios").checked = false;
      try {
        await sendPayload({tasks, profile: currentProfile(), backtest: backtestParams(), governance: governanceParams(tasks), allow_multi_task: false});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitFastFactorJudge() {
      const tasks = ["fast_factor_judge"];
      const shadowNode = document.getElementById("shadow_portfolios");
      if (shadowNode) shadowNode.checked = false;
      const node = document.getElementById("fast_factor_judge");
      if (node) node.checked = true;
      try {
        await sendPayload({tasks, profile: currentProfile(), backtest: backtestParams(), governance: governanceParams(tasks), allow_multi_task: false});
      } catch (err) {
        document.getElementById("status").textContent = err.message || String(err);
      }
    }
    async function submitAll() {
      const tasks = ["main_pipeline", "governance_active", "governance_mainline_review", "governance_layer_validation", "governance_layer_ablation_suite", "fast_factor_judge"];
      if (!window.confirm("运行全部任务会启动主策略流水线、治理主线、主线复核、层验证和完整增强诊断，耗时可能很长。确认继续吗？")) {
        document.getElementById("status").textContent = "已取消运行全部任务。";
        return;
      }
      try {
        await sendPayload({tasks, profile: currentProfile(), backtest: backtestParams(), governance: governanceParams(tasks), allow_multi_task: true});
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


RESULTS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>回测盈亏结果</title>
  <style>
    :root {
      --bg: #eef1e8;
      --panel: #fffdf6;
      --line: #d2c9b4;
      --ink: #163a32;
      --muted: #706a5c;
      --good: #136f4b;
      --bad: #ad352d;
      --accent: #c9972e;
    }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(201,151,46,0.18), transparent 34rem),
        linear-gradient(150deg, #eef1e8 0%, #fbf4e7 50%, #e4eee7 100%);
      color: var(--ink);
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    }
    .wrap {
      max-width: 1180px;
      margin: 28px auto;
      padding: 0 18px 26px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      background: #163a32;
      color: #fff4c8;
      border-radius: 18px;
      padding: 18px 22px;
      box-shadow: 0 16px 36px rgba(22,58,50,0.14);
    }
    .hero h1 {
      margin: 0;
      font-size: 24px;
    }
    .hero a, button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
    }
    .hero a {
      color: #fff4c8;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,0.35);
    }
    .panel {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 14px 34px rgba(22,58,50,0.09);
    }
    .controls {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto auto;
      gap: 12px;
      align-items: end;
    }
    label {
      display: block;
      font-weight: 700;
      margin-bottom: 7px;
    }
    select, input {
      box-sizing: border-box;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: #fffaf0;
      color: var(--ink);
      font-size: 14px;
    }
    button.primary {
      background: #163a32;
      color: white;
    }
    button.secondary {
      background: #eadfca;
      color: var(--ink);
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 13px;
      background: #fffaf0;
    }
    .card .name {
      color: var(--muted);
      font-size: 12px;
    }
    .card .value {
      font-size: 22px;
      font-weight: 800;
      margin-top: 4px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid #e5dcc8;
      padding: 9px 8px;
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {
      text-align: left;
    }
    th {
      color: #5d594f;
      background: #f7efdf;
      position: sticky;
      top: 0;
    }
    .table-wrap {
      overflow: auto;
      max-height: 62vh;
      border: 1px solid var(--line);
      border-radius: 14px;
      margin-top: 12px;
    }
    .pos { color: var(--good); font-weight: 700; }
    .neg { color: var(--bad); font-weight: 700; }
    .muted { color: var(--muted); }
    #status {
      min-height: 20px;
      margin-top: 12px;
      color: var(--muted);
    }
    @media (max-width: 820px) {
      .controls, .cards {
        grid-template-columns: 1fr;
      }
      .hero {
        flex-direction: column;
        align-items: flex-start;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>回测盈亏结果</h1>
        <div class="muted">按“已平仓交易”和“未平仓持仓”分开统计，并按股票汇总总盈亏。</div>
      </div>
      <a href="/run" target="_blank">打开运行配置页</a>
    </div>

    <div class="panel">
      <div class="controls">
        <div>
          <label for="run_select">选择回测结果</label>
          <select id="run_select"></select>
        </div>
        <button class="secondary" onclick="loadRuns()">刷新列表</button>
        <button class="primary" onclick="loadDetail()">查看盈亏</button>
      </div>
      <div id="status"></div>
    </div>

    <div class="panel" id="summary_panel" style="display:none">
      <div class="cards">
        <div class="card"><div class="name">已平仓交易数</div><div class="value" id="closed_count">-</div></div>
        <div class="card"><div class="name">交易胜率</div><div class="value" id="win_rate">-</div></div>
        <div class="card"><div class="name">盈利因子</div><div class="value" id="profit_factor">-</div></div>
        <div class="card"><div class="name">盈亏比</div><div class="value" id="payoff_ratio">-</div></div>
        <div class="card"><div class="name">已实现盈亏</div><div class="value" id="realized_pnl">-</div></div>
        <div class="card"><div class="name">未实现盈亏</div><div class="value" id="unrealized_pnl">-</div></div>
        <div class="card"><div class="name">总盈利</div><div class="value" id="gross_profit">-</div></div>
        <div class="card"><div class="name">总亏损</div><div class="value" id="gross_loss">-</div></div>
        <div class="card"><div class="name">控制卖出次数</div><div class="value" id="control_exit_count">-</div></div>
        <div class="card"><div class="name">控制节省亏损</div><div class="value" id="control_avoided_loss">-</div></div>
        <div class="card"><div class="name">硬止损节省</div><div class="value" id="hard_stop_avoided_loss">-</div></div>
        <div class="card"><div class="name">Alpha塌陷节省</div><div class="value" id="alpha_collapse_avoided_loss">-</div></div>
        <div class="card"><div class="name">安全降仓节省</div><div class="value" id="safety_deleveraging_avoided_loss">-</div></div>
        <div class="card"><div class="name">Research Gate</div><div class="value" id="research_gate_status">-</div></div>
        <div class="card"><div class="name">Gate Fails</div><div class="value" id="research_gate_fail_count">-</div></div>
        <div class="card"><div class="name">Alpha Diversity</div><div class="value" id="alpha_diversification_pass">-</div></div>
        <div class="card"><div class="name">Range Grid Share</div><div class="value" id="range_grid_weight_share">-</div></div>
        <div class="card"><div class="name">Redundancy Ratio</div><div class="value" id="redundancy_flag_ratio">-</div></div>
        <div class="card"><div class="name">Trading Evidence</div><div class="value" id="has_trading_evidence">-</div></div>
        <div class="card"><div class="name">Factor Passes</div><div class="value" id="factor_validation_pass_count">-</div></div>
        <div class="card"><div class="name">Portfolio Constraint</div><div class="value" id="portfolio_constraint_pass">-</div></div>
        <div class="card"><div class="name">Effective N</div><div class="value" id="account_effective_n">-</div></div>
        <div class="card"><div class="name">Top1 Weight</div><div class="value" id="top1_account_weight">-</div></div>
        <div class="card"><div class="name">Top5 Weight</div><div class="value" id="top5_account_weight_sum">-</div></div>
      </div>
    </div>

    <div class="panel" id="stock_panel" style="display:none">
      <h2>每只股票汇总</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>股票</th><th>状态</th><th>总盈亏</th><th>已实现盈亏</th><th>未实现盈亏</th>
              <th>已平仓次数</th><th>胜率</th><th>未平仓股数</th><th>未平仓市值</th>
            </tr>
          </thead>
          <tbody id="stock_rows"></tbody>
        </table>
      </div>
    </div>

    <div class="panel" id="closed_panel" style="display:none">
      <h2>已平仓交易</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>股票</th><th>买入日期</th><th>卖出日期</th><th>加权成本</th><th>卖出净价</th>
              <th>股数</th><th>实现盈亏</th><th>收益率</th><th>是否盈利</th>
            </tr>
          </thead>
          <tbody id="closed_rows"></tbody>
        </table>
      </div>
    </div>

    <div class="panel" id="open_panel" style="display:none">
      <h2>未平仓持仓</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>股票</th><th>建仓日期</th><th>估值日期</th><th>加权成本</th><th>最新价</th>
              <th>股数</th><th>市值</th><th>未实现盈亏</th><th>收益率</th>
            </tr>
          </thead>
          <tbody id="open_rows"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    function money(value) {
      const n = Number(value || 0);
      return n.toLocaleString("zh-CN", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    function pct(value) {
      if (value === null || value === undefined || value === "") return "-";
      const n = Number(value);
      if (!Number.isFinite(n)) return "-";
      return (n * 100).toFixed(2) + "%";
    }
    function num(value) {
      if (value === null || value === undefined || value === "") return "-";
      const n = Number(value);
      if (!Number.isFinite(n)) return "-";
      return n.toFixed(3);
    }
    function textValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }
    function boolText(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (value === true || value === "True" || value === "true" || value === "1" || value === 1) return "PASS";
      if (value === false || value === "False" || value === "false" || value === "0" || value === 0) return "FAIL";
      return String(value);
    }
    function signedClass(value) {
      const n = Number(value || 0);
      return n > 0 ? "pos" : (n < 0 ? "neg" : "");
    }
    function setText(id, value, cls = "") {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = value;
      el.className = "value " + cls;
    }
    function updateResearchSummary(summary) {
      summary = summary || {};
      const gateStatus = textValue(summary.research_gate_status);
      const gateClass = gateStatus === "research_ready" ? "pos" : (gateStatus === "blocked" ? "neg" : "");
      const constraintText = boolText(summary.latest_portfolio_constraint_pass);
      const constraintClass = constraintText === "PASS" ? "pos" : (constraintText === "FAIL" ? "neg" : "");
      const alphaText = boolText(summary.alpha_diversification_pass);
      const alphaClass = alphaText === "PASS" ? "pos" : (alphaText === "FAIL" ? "neg" : "");
      const evidenceText = boolText(summary.has_trading_evidence);
      const evidenceClass = evidenceText === "PASS" ? "pos" : (evidenceText === "FAIL" ? "neg" : "");
      setText("research_gate_status", gateStatus, gateClass);
      setText("research_gate_fail_count", textValue(summary.research_gate_fail_count), Number(summary.research_gate_fail_count || 0) > 0 ? "neg" : "");
      setText("alpha_diversification_pass", alphaText, alphaClass);
      setText("range_grid_weight_share", pct(summary.range_grid_weight_share), Number(summary.range_grid_weight_share || 0) > 0.35 ? "neg" : "");
      setText("redundancy_flag_ratio", pct(summary.redundancy_flag_ratio), Number(summary.redundancy_flag_ratio || 0) > 0.40 ? "neg" : "");
      setText("has_trading_evidence", evidenceText, evidenceClass);
      setText("factor_validation_pass_count", textValue(summary.factor_validation_pass_count));
      setText("portfolio_constraint_pass", constraintText, constraintClass);
      setText("account_effective_n", num(summary.account_effective_n));
      setText("top1_account_weight", pct(summary.top1_account_weight));
      setText("top5_account_weight_sum", pct(summary.top5_account_weight_sum));
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[ch]));
    }
    function cell(value, cls = "") {
      const safeValue = value === null || value === undefined || value === "" ? "-" : escapeHtml(value);
      return `<td class="${cls}">${safeValue}</td>`;
    }
    async function loadRuns() {
      const status = document.getElementById("status");
      status.textContent = "正在读取 results 目录...";
      const response = await fetch("/api/results");
      const data = await response.json();
      const select = document.getElementById("run_select");
      select.innerHTML = "";
      if (!data.runs || data.runs.length === 0) {
        status.textContent = "没有找到 backtest_trade_pairs_*.csv。请先运行主策略回测。";
        return;
      }
      data.runs.forEach((run) => {
        const opt = document.createElement("option");
        opt.value = run.key;
        opt.textContent = `${run.strategy} | ${run.profile} | ${run.modified_time}`;
        select.appendChild(opt);
      });
      status.textContent = `找到 ${data.runs.length} 组回测结果。`;
      await loadDetail();
    }
    async function loadDetail() {
      const select = document.getElementById("run_select");
      if (!select.value) return;
      const status = document.getElementById("status");
      status.textContent = "正在汇总已平仓和未平仓盈亏...";
      const response = await fetch(`/api/result-detail?key=${encodeURIComponent(select.value)}`);
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.message || "读取失败。";
        return;
      }
      document.getElementById("summary_panel").style.display = "";
      document.getElementById("stock_panel").style.display = "";
      document.getElementById("closed_panel").style.display = "";
      document.getElementById("open_panel").style.display = "";
      document.getElementById("closed_count").textContent = data.summary.realized_trade_count;
      document.getElementById("win_rate").textContent = pct(data.summary.trade_win_rate);
      document.getElementById("profit_factor").textContent = num(data.summary.profit_factor);
      document.getElementById("payoff_ratio").textContent = num(data.summary.payoff_ratio);
      document.getElementById("realized_pnl").textContent = money(data.summary.realized_pnl_amount);
      document.getElementById("realized_pnl").className = "value " + signedClass(data.summary.realized_pnl_amount);
      document.getElementById("unrealized_pnl").textContent = money(data.summary.unrealized_pnl_amount);
      document.getElementById("unrealized_pnl").className = "value " + signedClass(data.summary.unrealized_pnl_amount);
      document.getElementById("gross_profit").textContent = money(data.summary.gross_profit);
      document.getElementById("gross_profit").className = "value " + signedClass(data.summary.gross_profit);
      document.getElementById("gross_loss").textContent = money(data.summary.gross_loss);
      document.getElementById("gross_loss").className = "value " + signedClass(data.summary.gross_loss);
      document.getElementById("control_exit_count").textContent = data.summary.control_exit_count || 0;
      document.getElementById("control_avoided_loss").textContent = money(data.summary.control_avoided_loss_to_window_low);
      document.getElementById("control_avoided_loss").className = "value " + signedClass(data.summary.control_avoided_loss_to_window_low);
      document.getElementById("hard_stop_avoided_loss").textContent = money(data.summary.hard_stop_avoided_loss_to_window_low);
      document.getElementById("hard_stop_avoided_loss").className = "value " + signedClass(data.summary.hard_stop_avoided_loss_to_window_low);
      document.getElementById("alpha_collapse_avoided_loss").textContent = money(data.summary.alpha_collapse_avoided_loss_to_window_low);
      document.getElementById("alpha_collapse_avoided_loss").className = "value " + signedClass(data.summary.alpha_collapse_avoided_loss_to_window_low);
      document.getElementById("safety_deleveraging_avoided_loss").textContent = money(data.summary.safety_deleveraging_avoided_loss_to_window_low);
      document.getElementById("safety_deleveraging_avoided_loss").className = "value " + signedClass(data.summary.safety_deleveraging_avoided_loss_to_window_low);
      updateResearchSummary(data.summary || {});
      renderStockRows(data.stock_summary || []);
      renderClosedRows(data.closed_trades || []);
      renderOpenRows(data.open_positions || []);
      status.textContent = `当前结果：${data.run.strategy}，资金档位 ${data.run.profile}。`;
    }
    function renderStockRows(rows) {
      document.getElementById("stock_rows").innerHTML = rows.map((r) => {
        const total = Number(r.total_pnl_amount || 0);
        return `<tr>${cell(r.symbol)}${cell(r.status)}${cell(money(total), signedClass(total))}${cell(money(r.realized_pnl_amount), signedClass(r.realized_pnl_amount))}${cell(money(r.unrealized_pnl_amount), signedClass(r.unrealized_pnl_amount))}${cell(r.closed_trade_count)}${cell(pct(r.win_rate))}${cell(money(r.open_shares))}${cell(money(r.open_market_value))}</tr>`;
      }).join("");
    }
    function renderClosedRows(rows) {
      document.getElementById("closed_rows").innerHTML = rows.map((r) => {
        return `<tr>${cell(r.symbol)}${cell(r.entry_date)}${cell(r.exit_date)}${cell(money(r.cost_basis))}${cell(money(r.exit_net_price))}${cell(money(r.exit_shares))}${cell(money(r.realized_pnl_amount), signedClass(r.realized_pnl_amount))}${cell(pct(r.realized_pnl_pct))}${cell(r.is_win ? "盈利" : "亏损")}</tr>`;
      }).join("");
    }
    function renderOpenRows(rows) {
      document.getElementById("open_rows").innerHTML = rows.map((r) => {
        return `<tr>${cell(r.symbol)}${cell(r.entry_date)}${cell(r.valuation_date)}${cell(money(r.avg_cost))}${cell(money(r.latest_price))}${cell(money(r.shares))}${cell(money(r.market_value))}${cell(money(r.unrealized_pnl_amount), signedClass(r.unrealized_pnl_amount))}${cell(pct(r.unrealized_pnl_pct))}</tr>`;
      }).join("");
    }
    async function fetchJsonWithTimeout(url, timeoutMs = 15000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, { signal: controller.signal });
        const text = await response.text();
        let data = {};
        try {
          data = text ? JSON.parse(text) : {};
        } catch (err) {
          throw new Error(`服务器返回的不是合法 JSON：${text.slice(0, 180)}`);
        }
        if (!response.ok) {
          throw new Error(data.message || `请求失败，HTTP ${response.status}`);
        }
        return data;
      } finally {
        clearTimeout(timer);
      }
    }
    loadRuns = async function() {
      const status = document.getElementById("status");
      const select = document.getElementById("run_select");
      status.textContent = "正在读取 results 目录...";
      select.innerHTML = "";
      try {
        const data = await fetchJsonWithTimeout("/api/results", 15000);
        if (!data.runs || data.runs.length === 0) {
          status.textContent = "没有找到回测盈亏结果。请先运行主策略回测或治理主线。";
          return;
        }
        data.runs.forEach((run) => {
          const opt = document.createElement("option");
          opt.value = run.key;
          opt.textContent = `${run.strategy} | ${run.profile} | ${run.modified_time}`;
          select.appendChild(opt);
        });
        status.textContent = `找到 ${data.runs.length} 组回测结果。`;
        await loadDetail();
      } catch (err) {
        status.textContent = `读取结果列表失败：${err.message || err}`;
      }
    };
    loadDetail = async function() {
      const select = document.getElementById("run_select");
      if (!select.value) return;
      const status = document.getElementById("status");
      status.textContent = "正在汇总已平仓和未平仓盈亏...";
      try {
        const data = await fetchJsonWithTimeout(`/api/result-detail?key=${encodeURIComponent(select.value)}`, 30000);
        document.getElementById("summary_panel").style.display = "";
        document.getElementById("stock_panel").style.display = "";
        document.getElementById("closed_panel").style.display = "";
        document.getElementById("open_panel").style.display = "";
        document.getElementById("closed_count").textContent = data.summary.realized_trade_count;
        document.getElementById("win_rate").textContent = pct(data.summary.trade_win_rate);
        document.getElementById("profit_factor").textContent = num(data.summary.profit_factor);
        document.getElementById("payoff_ratio").textContent = num(data.summary.payoff_ratio);
        document.getElementById("realized_pnl").textContent = money(data.summary.realized_pnl_amount);
        document.getElementById("realized_pnl").className = "value " + signedClass(data.summary.realized_pnl_amount);
        document.getElementById("unrealized_pnl").textContent = money(data.summary.unrealized_pnl_amount);
        document.getElementById("unrealized_pnl").className = "value " + signedClass(data.summary.unrealized_pnl_amount);
        document.getElementById("gross_profit").textContent = money(data.summary.gross_profit);
        document.getElementById("gross_profit").className = "value " + signedClass(data.summary.gross_profit);
        document.getElementById("gross_loss").textContent = money(data.summary.gross_loss);
        document.getElementById("gross_loss").className = "value " + signedClass(data.summary.gross_loss);
        document.getElementById("control_exit_count").textContent = data.summary.control_exit_count || 0;
        document.getElementById("control_avoided_loss").textContent = money(data.summary.control_avoided_loss_to_window_low);
        document.getElementById("control_avoided_loss").className = "value " + signedClass(data.summary.control_avoided_loss_to_window_low);
        document.getElementById("hard_stop_avoided_loss").textContent = money(data.summary.hard_stop_avoided_loss_to_window_low);
        document.getElementById("hard_stop_avoided_loss").className = "value " + signedClass(data.summary.hard_stop_avoided_loss_to_window_low);
        document.getElementById("alpha_collapse_avoided_loss").textContent = money(data.summary.alpha_collapse_avoided_loss_to_window_low);
        document.getElementById("alpha_collapse_avoided_loss").className = "value " + signedClass(data.summary.alpha_collapse_avoided_loss_to_window_low);
        document.getElementById("safety_deleveraging_avoided_loss").textContent = money(data.summary.safety_deleveraging_avoided_loss_to_window_low);
        document.getElementById("safety_deleveraging_avoided_loss").className = "value " + signedClass(data.summary.safety_deleveraging_avoided_loss_to_window_low);
        updateResearchSummary(data.summary || {});
        renderStockRows(data.stock_summary || []);
        renderClosedRows(data.closed_trades || []);
        renderOpenRows(data.open_positions || []);
        status.textContent = `当前结果：${data.run.strategy}，资金档位 ${data.run.profile}。`;
      } catch (err) {
        status.textContent = `读取盈亏明细失败：${err.message || err}`;
      }
    };
    window.addEventListener("load", loadRuns);
  </script>
</body>
</html>
"""


def _write_selection(state_path: Path, payload: dict) -> None:
    payload = _sanitize_selection_payload(payload)
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(state_path)


def _sanitize_selection_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    clean = dict(payload)
    tasks = clean.get("tasks")
    if not isinstance(tasks, list):
        return clean
    tasks = [str(task) for task in tasks]
    allow_multi_task = bool(clean.get("allow_multi_task", False))
    # Mainline review and the enhanced diagnostic suite are both long governance
    # jobs. If a stale browser page or checkbox state submits both, prefer the
    # explicitly requested mainline review unless the user clicked "run all".
    if (
        not allow_multi_task
        and "governance_mainline_review" in tasks
        and "governance_layer_ablation_suite" in tasks
    ):
        tasks = [task for task in tasks if task != "governance_layer_ablation_suite"]
        clean["sanitized_task_note"] = "removed_governance_layer_ablation_suite_when_mainline_review_selected"
    clean["tasks"] = tasks
    return clean


def _project_dir() -> Path:
    return Path(__file__).resolve().parent


def _results_dir() -> Path:
    return _project_dir() / "results"


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, body_text: str) -> None:
    data = body_text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except UnicodeDecodeError:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _result_identity(result_stem: str) -> tuple[str, str]:
    if "__" not in result_stem:
        return result_stem, "默认100万基线"
    strategy, profile = result_stem.split("__", 1)
    return strategy, profile


def _discover_result_runs() -> list[dict]:
    runs = []
    results_dir = _results_dir()
    if not results_dir.exists():
        return runs
    for trade_path in results_dir.glob(f"{TRADE_PAIR_PREFIX}*.csv"):
        result_stem = trade_path.stem[len(TRADE_PAIR_PREFIX):]
        strategy, profile = _result_identity(result_stem)
        open_path = results_dir / f"{OPEN_POSITION_PREFIX}{result_stem}.csv"
        metrics_path = results_dir / f"{METRICS_PREFIX}{result_stem}.csv"
        trade_rel = trade_path.relative_to(results_dir).as_posix()
        modified = max(
            [path.stat().st_mtime for path in [trade_path, open_path, metrics_path] if path.exists()],
            default=trade_path.stat().st_mtime,
        )
        runs.append(
            {
                "key": quote(trade_rel, safe=""),
                "result_ref": trade_rel,
                "result_stem": result_stem,
                "strategy": strategy,
                "profile": profile,
                "kind": "normal_backtest",
                "trade_rel": trade_rel,
                "open_rel": open_path.relative_to(results_dir).as_posix() if open_path.exists() else "",
                "trade_file": trade_path.name,
                "open_file": open_path.name if open_path.exists() else "",
                "metrics_file": metrics_path.name if metrics_path.exists() else "",
                "modified": modified,
                "modified_time": _format_timestamp(modified),
            }
        )
    for trade_path in results_dir.rglob("governance_trade_pairs.csv"):
        if "_archive" in trade_path.relative_to(results_dir).parts:
            continue
        run_dir = trade_path.parent
        open_path = run_dir / "governance_open_positions.csv"
        summary_path = run_dir / "governance_trade_pair_summary.csv"
        strategy_summary_path = run_dir / "governance_strategy_summary.csv"
        research_gate_path = run_dir / "governance_research_gate_report.csv"
        alpha_diversification_path = run_dir / "governance_alpha_diversification_report.csv"
        trading_evidence_path = run_dir / "governance_trading_evidence_report.csv"
        factor_validation_path = run_dir / "governance_factor_validation_report.csv"
        portfolio_constraint_path = run_dir / "governance_portfolio_constraint_report.csv"
        control_loss_path = run_dir / "governance_control_avoided_loss_summary.csv"
        trade_rel = trade_path.relative_to(results_dir).as_posix()
        strategy, profile = _governance_result_identity(run_dir, results_dir)
        modified = max(
            [
                path.stat().st_mtime
                for path in [
                    trade_path,
                    open_path,
                    summary_path,
                    strategy_summary_path,
                    research_gate_path,
                    alpha_diversification_path,
                    trading_evidence_path,
                    factor_validation_path,
                    portfolio_constraint_path,
                    control_loss_path,
                ]
                if path.exists()
            ],
            default=trade_path.stat().st_mtime,
        )
        runs.append(
            {
                "key": quote(trade_rel, safe=""),
                "result_ref": trade_rel,
                "result_stem": trade_rel,
                "strategy": strategy,
                "profile": profile,
                "kind": "governance",
                "trade_rel": trade_rel,
                "open_rel": open_path.relative_to(results_dir).as_posix() if open_path.exists() else "",
                "trade_file": trade_path.name,
                "open_file": open_path.name if open_path.exists() else "",
                "metrics_file": summary_path.name if summary_path.exists() else "",
                "modified": modified,
                "modified_time": _format_timestamp(modified),
            }
        )
    for manifest_path in results_dir.rglob("fast_factor_judge_manifest.csv"):
        if "_archive" in manifest_path.relative_to(results_dir).parts:
            continue
        run_dir = manifest_path.parent
        summary_path = run_dir / "fast_factor_summary.csv"
        validation_path = run_dir / "fast_factor_validation_report.csv"
        report_path = run_dir / "fast_factor_judge_report.md"
        manifest_rel = manifest_path.relative_to(results_dir).as_posix()
        strategy, profile = _fast_factor_judge_identity(run_dir, results_dir)
        modified = max(
            [
                path.stat().st_mtime
                for path in [manifest_path, summary_path, validation_path, report_path]
                if path.exists()
            ],
            default=manifest_path.stat().st_mtime,
        )
        runs.append(
            {
                "key": quote(manifest_rel, safe=""),
                "result_ref": manifest_rel,
                "result_stem": manifest_rel,
                "strategy": strategy,
                "profile": profile,
                "kind": "fast_factor_judge",
                "trade_rel": "",
                "open_rel": "",
                "manifest_rel": manifest_rel,
                "trade_file": "",
                "open_file": "",
                "metrics_file": summary_path.name if summary_path.exists() else "",
                "modified": modified,
                "modified_time": _format_timestamp(modified),
            }
        )
    return sorted(runs, key=lambda row: row["modified"], reverse=True)


def _governance_result_identity(run_dir: Path, results_dir: Path) -> tuple[str, str]:
    try:
        rel_parts = run_dir.relative_to(results_dir).parts
    except Exception:
        rel_parts = run_dir.parts
    if len(rel_parts) >= 5 and rel_parts[0] in {"governance", "decision_council"}:
        universe = rel_parts[1]
        variant = rel_parts[2]
        bundle = rel_parts[3]
        tail = list(rel_parts[4:])
        run_name = next((part for part in reversed(tail) if str(part).startswith("run")), tail[-1] if tail else "")
        profile_parts = [part for part in tail if part != run_name]
        profile_text = " / ".join(profile_parts) if profile_parts else "default"
        return f"{variant} / {bundle}", f"治理 | {universe} | {profile_text} | {run_name}"
    if len(rel_parts) >= 4:
        return f"{rel_parts[-3]} / {rel_parts[-2]}", f"治理 | {rel_parts[-1]}"
    return run_dir.name, "治理结果"

def _fast_factor_judge_identity(run_dir: Path, results_dir: Path) -> tuple[str, str]:
    try:
        rel_parts = run_dir.relative_to(results_dir).parts
    except Exception:
        rel_parts = run_dir.parts
    if "fast_factor_judge" in rel_parts:
        index = rel_parts.index("fast_factor_judge")
        universe = rel_parts[index + 1] if len(rel_parts) > index + 1 else "unknown_universe"
        run_name = rel_parts[index + 2] if len(rel_parts) > index + 2 else run_dir.name
        return "快速因子审判", f"{universe} | {run_name}"
    return "快速因子审判", run_dir.name


def _format_timestamp(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value, default: float = 0.0) -> float:
    if value in (None, "", "nan", "NaN", "<NA>"):
        return default
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def _safe_optional_float(value):
    if value in (None, "", "nan", "NaN", "<NA>"):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number if number == number else None


def _safe_bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "盈利"}


def _date_text(value) -> str:
    text = str(value or "").strip()
    if not text or text in {"NaT", "nan", "<NA>"}:
        return ""
    return text[:10]


def _result_detail(result_key: str) -> tuple[dict, int]:
    result_ref = unquote(result_key or "")
    available = {run["result_ref"]: run for run in _discover_result_runs()}
    if result_ref not in available:
        return {"message": "没有找到这组回测结果，请刷新列表。"}, 404

    run = available[result_ref]
    results_dir = _results_dir()
    if run.get("kind") == "fast_factor_judge":
        return _fast_factor_judge_detail(run, results_dir), 200
    trade_rows = _read_csv_rows(results_dir / run.get("trade_rel", ""))
    open_rows = _read_csv_rows(results_dir / run.get("open_rel", "")) if run.get("open_rel") else []
    control_loss_rows = []
    governance_research_rows = {}
    if run.get("kind") == "governance" and run.get("trade_rel"):
        run_dir = (results_dir / run["trade_rel"]).parent
        control_loss_path = run_dir / "governance_control_avoided_loss_summary.csv"
        control_loss_rows = _read_csv_rows(control_loss_path)
        governance_research_rows = {
            "strategy_summary": _read_csv_rows(run_dir / "governance_strategy_summary.csv"),
            "research_gate": _read_csv_rows(run_dir / "governance_research_gate_report.csv"),
            "alpha_diversification": _read_csv_rows(run_dir / "governance_alpha_diversification_report.csv"),
            "trading_evidence": _read_csv_rows(run_dir / "governance_trading_evidence_report.csv"),
            "factor_validation": _read_csv_rows(run_dir / "governance_factor_validation_report.csv"),
            "portfolio_constraints": _read_csv_rows(run_dir / "governance_portfolio_constraint_report.csv"),
        }
    latest_holding_by_symbol: dict[str, dict] = {}
    if run.get("kind") == "governance" and run.get("trade_rel"):
        holding_path = (results_dir / run["trade_rel"]).parent / "governance_holdings_ledger.csv"
        holding_rows = _read_csv_rows(holding_path)
        latest_date = max((_date_text(row.get("date")) for row in holding_rows), default="")
        for row in holding_rows:
            symbol = str(row.get("symbol", "")).strip()
            if symbol and _date_text(row.get("date")) == latest_date:
                latest_holding_by_symbol[symbol] = row
    stock_summary: dict[str, dict] = {}
    closed_trades = []

    for row in trade_rows:
        if str(row.get("close_reason", "")).strip() == "inventory_underflow":
            continue
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        pnl = _safe_float(row.get("realized_pnl_amount"))
        cost_basis = _safe_float(row.get("cost_basis"))
        shares = _safe_float(row.get("exit_shares"))
        bucket = stock_summary.setdefault(symbol, _empty_stock_bucket(symbol))
        bucket["realized_pnl_amount"] += pnl
        bucket["closed_trade_count"] += 1
        bucket["closed_cost_amount"] += max(cost_basis * shares, 0.0)
        if pnl > 0.0:
            bucket["winning_trade_count"] += 1
        closed_trades.append(
            {
                "symbol": symbol,
                "entry_date": _date_text(row.get("entry_date")),
                "exit_date": _date_text(row.get("exit_date")),
                "cost_basis": cost_basis,
                "exit_net_price": _safe_float(row.get("exit_net_price")),
                "exit_shares": shares,
                "realized_pnl_amount": pnl,
                "realized_pnl_pct": _safe_optional_float(row.get("realized_pnl_pct")),
                "is_win": _safe_bool(row.get("is_win")),
                "close_reason": str(row.get("close_reason", "")).strip(),
            }
        )

    open_positions = []
    for row in open_rows:
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        holding_fallback = latest_holding_by_symbol.get(symbol, {})
        shares = _safe_float(row.get("shares"))
        avg_cost = _safe_float(row.get("avg_cost"))
        latest_price = _safe_optional_float(row.get("latest_price"))
        if latest_price is None:
            latest_price = _safe_optional_float(holding_fallback.get("price"))
        market_value_opt = _safe_optional_float(row.get("market_value"))
        if market_value_opt is None:
            market_value_opt = _safe_optional_float(holding_fallback.get("market_value"))
        market_value = market_value_opt if market_value_opt is not None else 0.0
        pnl_opt = _safe_optional_float(row.get("unrealized_pnl_amount"))
        if pnl_opt is None and latest_price is not None and avg_cost > 0.0:
            pnl_opt = shares * (latest_price - avg_cost)
        pnl = pnl_opt if pnl_opt is not None else 0.0
        pnl_pct = _safe_optional_float(row.get("unrealized_pnl_pct"))
        if pnl_pct is None and avg_cost > 0.0 and shares > 0.0:
            pnl_pct = pnl / (shares * avg_cost)
        bucket = stock_summary.setdefault(symbol, _empty_stock_bucket(symbol))
        bucket["unrealized_pnl_amount"] += pnl
        bucket["open_shares"] += shares
        bucket["open_market_value"] += market_value
        open_positions.append(
            {
                "symbol": symbol,
                "entry_date": _date_text(row.get("entry_date")),
                "valuation_date": _date_text(row.get("valuation_date")),
                "avg_cost": avg_cost,
                "latest_price": latest_price if latest_price is not None else 0.0,
                "shares": shares,
                "market_value": market_value,
                "unrealized_pnl_amount": pnl,
                "unrealized_pnl_pct": pnl_pct,
            }
        )

    stock_rows = []
    for bucket in stock_summary.values():
        total = bucket["realized_pnl_amount"] + bucket["unrealized_pnl_amount"]
        closed_count = bucket["closed_trade_count"]
        bucket["win_rate"] = bucket["winning_trade_count"] / closed_count if closed_count else None
        bucket["total_pnl_amount"] = total
        bucket["status"] = _stock_status(bucket)
        stock_rows.append(bucket)

    all_closed_trades = list(closed_trades)
    closed_trades = sorted(closed_trades, key=lambda row: (row["exit_date"], row["symbol"]), reverse=True)[:1000]
    open_positions = sorted(open_positions, key=lambda row: row["unrealized_pnl_amount"])[:1000]
    stock_rows = sorted(stock_rows, key=lambda row: row["total_pnl_amount"])
    realized_trade_count = sum(row["closed_trade_count"] for row in stock_rows)
    winning_trade_count = sum(row["winning_trade_count"] for row in stock_rows)
    closed_pnls = [float(row["realized_pnl_amount"]) for row in all_closed_trades]
    gross_profit = sum(pnl for pnl in closed_pnls if pnl > 0.0)
    gross_loss = sum(pnl for pnl in closed_pnls if pnl < 0.0)
    winning_pnls = [pnl for pnl in closed_pnls if pnl > 0.0]
    losing_pnls = [pnl for pnl in closed_pnls if pnl < 0.0]
    avg_win = gross_profit / len(winning_pnls) if winning_pnls else None
    avg_loss = gross_loss / len(losing_pnls) if losing_pnls else None
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss and avg_loss < 0.0 else None
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0.0 else None
    control_loss_summary = _control_loss_summary_from_rows(control_loss_rows)
    governance_research_summary = _governance_research_summary_from_rows(governance_research_rows)
    summary = {
        "realized_trade_count": int(realized_trade_count),
        "winning_trade_count": int(winning_trade_count),
        "losing_trade_count": int(
            sum(max(row["closed_trade_count"] - row["winning_trade_count"], 0) for row in stock_rows)
        ),
        "trade_win_rate": winning_trade_count / realized_trade_count if realized_trade_count else None,
        "realized_pnl_amount": sum(row["realized_pnl_amount"] for row in stock_rows),
        "unrealized_pnl_amount": sum(row["unrealized_pnl_amount"] for row in stock_rows),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "profit_factor": profit_factor,
        "open_position_count": len(open_positions),
        **control_loss_summary,
        **governance_research_summary,
    }
    return {
        "run": run,
        "summary": summary,
        "stock_summary": stock_rows,
        "closed_trades": closed_trades,
        "open_positions": open_positions,
    }, 200


def _fast_factor_judge_detail(run: dict, results_dir: Path) -> dict:
    manifest_path = results_dir / run.get("manifest_rel", "")
    run_dir = manifest_path.parent
    manifest_rows = _read_csv_rows(manifest_path)
    summary_rows = _read_csv_rows(run_dir / "fast_factor_summary.csv")
    validation_rows = _read_csv_rows(run_dir / "fast_factor_validation_report.csv")
    contract_rows = _read_csv_rows(run_dir / "factor_pool_contract.csv")
    role_rows = _read_csv_rows(run_dir / "factor_role_coverage.csv")
    manifest = manifest_rows[0] if manifest_rows else {}
    verdict_counts: dict[str, int] = {}
    for row in summary_rows:
        verdict = str(row.get("verdict", "")).strip() or "unknown"
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    pass_count = sum(1 for row in validation_rows if _safe_optional_bool(row.get("pass_flag")) is True)
    summary = {
        "realized_trade_count": 0,
        "winning_trade_count": 0,
        "losing_trade_count": 0,
        "trade_win_rate": None,
        "realized_pnl_amount": 0.0,
        "unrealized_pnl_amount": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "avg_win": None,
        "avg_loss": None,
        "payoff_ratio": None,
        "profit_factor": None,
        "open_position_count": 0,
        "control_exit_count": 0,
        "control_avoided_loss_to_window_low": 0.0,
        "control_avoided_loss_to_window_end": 0.0,
        "hard_stop_avoided_loss_to_window_low": 0.0,
        "alpha_collapse_avoided_loss_to_window_low": 0.0,
        "safety_deleveraging_avoided_loss_to_window_low": 0.0,
        "research_gate_status": "fast_factor_judge",
        "research_gate_fail_count": verdict_counts.get("reject_or_rework", 0),
        "factor_validation_pass_count": pass_count,
        "latest_portfolio_constraint_pass": None,
        "account_effective_n": _safe_optional_float(manifest.get("symbol_count")),
        "top1_account_weight": None,
        "top5_account_weight_sum": None,
        "promote_candidate_count": verdict_counts.get("promote_candidate", 0),
        "watchlist_count": verdict_counts.get("watchlist", 0),
        "reject_or_rework_count": verdict_counts.get("reject_or_rework", 0),
        "factor_contract_count": len(contract_rows),
        "factor_role_count": len(role_rows),
        "row_count": _safe_optional_int(manifest.get("row_count")),
        "analysis_start_date": manifest.get("analysis_start_date") or manifest.get("start_date"),
        "analysis_end_date": manifest.get("analysis_end_date") or manifest.get("end_date"),
    }
    return {
        "run": run,
        "summary": summary,
        "stock_summary": [],
        "factor_role_coverage": role_rows[:50],
        "factor_pool_contract": contract_rows[:200],
        "closed_trades": [],
        "open_positions": [],
    }


def _empty_stock_bucket(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "status": "",
        "realized_pnl_amount": 0.0,
        "unrealized_pnl_amount": 0.0,
        "total_pnl_amount": 0.0,
        "closed_trade_count": 0,
        "winning_trade_count": 0,
        "win_rate": None,
        "open_shares": 0.0,
        "open_market_value": 0.0,
        "closed_cost_amount": 0.0,
    }


def _control_loss_summary_from_rows(rows: list[dict]) -> dict:
    summary = {
        "control_exit_count": 0,
        "control_avoided_loss_to_window_low": 0.0,
        "control_avoided_loss_to_window_end": 0.0,
        "hard_stop_avoided_loss_to_window_low": 0.0,
        "alpha_collapse_avoided_loss_to_window_low": 0.0,
        "safety_deleveraging_avoided_loss_to_window_low": 0.0,
    }
    for row in rows or []:
        reason = str(row.get("sell_reason", "")).strip()
        count = int(_safe_float(row.get("control_exit_count")))
        low = _safe_float(row.get("avoided_loss_to_window_low"))
        end = _safe_float(row.get("avoided_loss_to_window_end"))
        summary["control_exit_count"] += count
        summary["control_avoided_loss_to_window_low"] += low
        summary["control_avoided_loss_to_window_end"] += end
        if reason == "hard_stop_exit":
            summary["hard_stop_avoided_loss_to_window_low"] += low
        elif reason == "alpha_collapse_consensus":
            summary["alpha_collapse_avoided_loss_to_window_low"] += low
        elif reason == "safety_deleveraging":
            summary["safety_deleveraging_avoided_loss_to_window_low"] += low
    return summary


def _governance_research_summary_from_rows(rows_by_report: dict[str, list[dict]]) -> dict:
    summary = {
        "research_gate_status": "unknown",
        "research_gate_fail_count": None,
        "alpha_diversification_pass": None,
        "range_grid_weight_share": None,
        "redundancy_flag_ratio": None,
        "max_pairwise_rank_corr": None,
        "alpha_block_reasons": "",
        "has_trading_evidence": None,
        "trading_evidence_block_reason": "",
        "trading_evidence_avg_exposure": None,
        "factor_validation_pass_count": None,
        "latest_portfolio_constraint_pass": None,
        "account_effective_n": None,
        "top1_account_weight": None,
        "top5_account_weight_sum": None,
    }
    if not rows_by_report:
        return summary

    strategy_rows = rows_by_report.get("strategy_summary") or []
    strategy_row = strategy_rows[0] if strategy_rows else {}
    if strategy_row:
        summary["research_gate_status"] = str(strategy_row.get("research_gate_status") or "unknown")
        summary["research_gate_fail_count"] = _safe_optional_int(strategy_row.get("research_gate_fail_count"))
        summary["factor_validation_pass_count"] = _safe_optional_int(strategy_row.get("factor_validation_pass_count"))
        summary["latest_portfolio_constraint_pass"] = _safe_optional_bool(strategy_row.get("latest_portfolio_constraint_pass"))

    gate_rows = rows_by_report.get("research_gate") or []
    if gate_rows:
        status_values = [str(row.get("overall_status", "")).strip() for row in gate_rows if str(row.get("overall_status", "")).strip()]
        if status_values and summary["research_gate_status"] == "unknown":
            summary["research_gate_status"] = status_values[-1]
        if summary["research_gate_fail_count"] is None:
            summary["research_gate_fail_count"] = sum(1 for row in gate_rows if _safe_optional_bool(row.get("pass_flag")) is False)

    alpha_rows = rows_by_report.get("alpha_diversification") or []
    if alpha_rows:
        latest_alpha = alpha_rows[-1]
        summary["alpha_diversification_pass"] = _safe_optional_bool(latest_alpha.get("pass_flag"))
        summary["range_grid_weight_share"] = _safe_optional_float(latest_alpha.get("range_grid_weight_share"))
        summary["redundancy_flag_ratio"] = _safe_optional_float(latest_alpha.get("redundancy_flag_ratio"))
        summary["max_pairwise_rank_corr"] = _safe_optional_float(latest_alpha.get("max_pairwise_rank_corr"))
        summary["alpha_block_reasons"] = str(latest_alpha.get("block_reasons") or "")

    evidence_rows = rows_by_report.get("trading_evidence") or []
    if evidence_rows:
        latest_evidence = evidence_rows[-1]
        summary["has_trading_evidence"] = _safe_optional_bool(latest_evidence.get("has_trading_evidence"))
        summary["trading_evidence_block_reason"] = str(latest_evidence.get("block_reason") or "")
        summary["trading_evidence_avg_exposure"] = _safe_optional_float(latest_evidence.get("avg_actual_exposure"))

    validation_rows = rows_by_report.get("factor_validation") or []
    if validation_rows and summary["factor_validation_pass_count"] is None:
        summary["factor_validation_pass_count"] = sum(1 for row in validation_rows if _safe_optional_bool(row.get("pass_flag")) is True)

    constraint_rows = rows_by_report.get("portfolio_constraints") or []
    if constraint_rows:
        latest = sorted(constraint_rows, key=lambda row: _date_text(row.get("date")))[-1]
        if summary["latest_portfolio_constraint_pass"] is None:
            summary["latest_portfolio_constraint_pass"] = _safe_optional_bool(latest.get("constraint_pass"))
        summary["account_effective_n"] = _safe_optional_float(latest.get("account_effective_n"))
        summary["top1_account_weight"] = _safe_optional_float(latest.get("top1_account_weight"))
        summary["top5_account_weight_sum"] = _safe_optional_float(latest.get("top5_account_weight_sum"))

    return summary


def _safe_optional_int(value):
    number = _safe_optional_float(value)
    return int(number) if number is not None else None


def _safe_optional_bool(value):
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "pass", "passed"}:
        return True
    if text in {"false", "0", "no", "n", "fail", "failed"}:
        return False
    return None


def _stock_status(bucket: dict) -> str:
    has_closed = int(bucket.get("closed_trade_count", 0)) > 0
    has_open = float(bucket.get("open_shares", 0.0) or 0.0) > 0.0
    if has_closed and has_open:
        return "已平仓+未平仓"
    if has_closed:
        return "已平仓"
    if has_open:
        return "未平仓"
    return "无持仓"


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
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                _redirect(self, "/run")
                return
            if parsed.path == "/run":
                _html_response(self, RUN_HTML)
                return
            if parsed.path == "/results":
                _html_response(self, RESULTS_HTML)
                return
            if parsed.path == "/api/results":
                try:
                    _json_response(self, {"runs": _discover_result_runs()})
                except Exception as exc:
                    _json_response(self, {"message": f"读取结果列表失败：{exc}"}, status=500)
                return
            if parsed.path == "/api/result-detail":
                try:
                    key = parse_qs(parsed.query).get("key", [""])[0]
                    payload, status = _result_detail(key)
                    _json_response(self, payload, status=status)
                except Exception as exc:
                    _json_response(self, {"message": f"读取盈亏明细失败：{exc}"}, status=500)
                return
            if parsed.path == "/api/progress":
                try:
                    from functions.runtime_progress import read_progress

                    _json_response(self, read_progress())
                except Exception as exc:
                    _json_response(self, {"status": "unknown", "message": f"progress read failed: {exc}"}, status=500)
                return
            if parsed.path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed.path not in ("/", "/index.html"):
                self.send_error(404)
                return

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
            _json_response(self, {"message": "选择已记录，可以关闭本页面。"})
            stop_event.set()
            task_payload = payload if isinstance(payload, dict) else {}
            tasks = task_payload.get("tasks") if isinstance(task_payload, dict) else []
            if not tasks:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    run_url = f"http://127.0.0.1:{port}/run"
    results_url = f"http://127.0.0.1:{port}/results"
    print(f"运行配置页地址: {run_url}")
    print(f"回测结果页地址: {results_url}")
    try:
        opened = webbrowser.open(run_url, new=1)
    except Exception:
        opened = False
    if not opened:
        print("浏览器没有自动打开，请手动打开上面的两个地址。")

    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if not stop_event.is_set() and not state_path.exists():
            _write_selection(state_path, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
