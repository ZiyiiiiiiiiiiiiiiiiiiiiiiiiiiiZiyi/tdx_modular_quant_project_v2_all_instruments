"""Professional, dependency-free dashboard template for governance monitoring."""
from __future__ import annotations


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>治理实时监控</title>
  <style>
    :root {
      --bg: #f2f4f1;
      --surface: #ffffff;
      --surface-soft: #f7f8f6;
      --ink: #17211f;
      --muted: #66716e;
      --line: #dce2de;
      --line-strong: #cbd3ce;
      --green: #087a55;
      --green-soft: #e9f5ef;
      --red: #bd3d39;
      --red-soft: #faeceb;
      --blue: #246b9e;
      --blue-soft: #eaf2f8;
      --gold: #a87518;
      --gold-soft: #f7f0df;
      --violet: #705a9f;
      --shadow: 0 1px 2px rgba(23,33,31,.04), 0 8px 24px rgba(23,33,31,.05);
    }
    * { box-sizing: border-box; }
    html { background: var(--bg); }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      letter-spacing: 0;
    }
    button { font: inherit; }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      color: #f7faf8;
      background: #1f2d29;
      border-bottom: 1px solid #34433f;
    }
    .topbar-main {
      min-height: 62px;
      padding: 10px 22px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    .brand { min-width: 0; }
    .brand-title { font-size: 18px; font-weight: 650; line-height: 1.25; }
    .brand-subtitle { margin-top: 3px; color: #aebbb6; font-size: 12px; }
    .run-state { min-width: 280px; text-align: right; }
    .run-state-line { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #82d5b1; box-shadow: 0 0 0 3px rgba(130,213,177,.14); }
    .status-text { color: #edf4f1; font-size: 13px; }
    .run-detail { margin-top: 4px; color: #aebbb6; font: 12px Consolas, monospace; }
    .progress-track { height: 3px; background: #354541; }
    .progress-fill { width: 0; height: 100%; background: #54b88f; transition: width .22s ease; }
    .workspace { width: min(1780px, 100%); margin: 0 auto; padding: 16px 18px 28px; }
    .kpi-grid { display: grid; grid-template-columns: repeat(8, minmax(120px, 1fr)); gap: 8px; }
    .kpi {
      min-height: 82px;
      padding: 11px 12px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 1px 2px rgba(23,33,31,.025);
    }
    .kpi-label { color: var(--muted); font-size: 11px; }
    .kpi-value { margin-top: 8px; font: 650 20px Consolas, monospace; white-space: nowrap; }
    .kpi-context { margin-top: 5px; color: #87918e; font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tabs {
      margin-top: 14px;
      display: flex;
      gap: 2px;
      border-bottom: 1px solid var(--line-strong);
    }
    .tab {
      border: 0;
      border-bottom: 2px solid transparent;
      padding: 10px 16px 9px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
    }
    .tab:hover { color: var(--ink); background: rgba(255,255,255,.55); }
    .tab.active { color: var(--ink); border-bottom-color: var(--green); font-weight: 600; }
    .tab-panel { display: none; padding-top: 12px; }
    .tab-panel.active { display: block; }
    .layout-main { display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(320px, .75fr); gap: 12px; }
    .layout-half { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
    .layout-third { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
    .panel {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: var(--shadow);
    }
    .panel-header {
      min-height: 46px;
      padding: 10px 13px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
    }
    .panel-title { font-size: 14px; font-weight: 600; }
    .panel-note { color: var(--muted); font-size: 11px; }
    .panel-body { padding: 12px 13px; }
    .chart-body { padding: 8px 10px 10px; }
    .chart { display: block; width: 100%; height: 350px; }
    .chart.medium { height: 270px; }
    .chart.small { height: 220px; }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; color: var(--muted); font-size: 11px; }
    .legend-item { display: inline-flex; align-items: center; gap: 5px; }
    .legend-line { width: 16px; height: 2px; background: var(--blue); }
    .legend-entry-dot { width: 7px; height: 7px; border-radius: 50%; box-shadow: 0 0 0 2px #fff, 0 0 0 3px currentColor; }
    .range-control { display: inline-flex; padding: 2px; background: var(--surface-soft); border: 1px solid var(--line); border-radius: 5px; }
    .range-button { min-width: 38px; padding: 4px 7px; border: 0; border-radius: 3px; color: var(--muted); background: transparent; cursor: pointer; font-size: 11px; }
    .range-button.active { color: var(--ink); background: #fff; box-shadow: 0 1px 2px rgba(23,33,31,.1); }
    .summary-list { margin: 0; display: grid; grid-template-columns: 1fr auto; gap: 0; }
    .summary-list dt, .summary-list dd { margin: 0; padding: 8px 0; border-bottom: 1px solid #edf0ee; }
    .summary-list dt { color: var(--muted); }
    .summary-list dd { font: 600 13px Consolas, monospace; text-align: right; }
    .exposure-row { margin-top: 10px; }
    .exposure-label { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px; }
    .exposure-bar { margin-top: 5px; height: 7px; overflow: hidden; background: #edf0ee; border-radius: 3px; }
    .exposure-bar > div { height: 100%; background: var(--blue); transition: width .2s ease; }
    .detail-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .detail-item { padding: 9px 10px; border-right: 1px solid #edf0ee; border-bottom: 1px solid #edf0ee; }
    .detail-item:nth-child(4n) { border-right: 0; }
    .detail-key { color: var(--muted); font-size: 11px; }
    .detail-value { margin-top: 5px; font: 600 13px Consolas, monospace; overflow-wrap: anywhere; }
    .text-report {
      margin: 0;
      min-height: 150px;
      max-height: 330px;
      padding: 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      color: #33413d;
      font: 12px/1.7 Consolas, "Microsoft YaHei UI", monospace;
    }
    .table-scroll { width: 100%; overflow: auto; max-height: 390px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { position: sticky; top: 0; z-index: 1; color: var(--muted); background: #f7f8f6; font-weight: 500; text-align: left; }
    th, td { padding: 8px 9px; border-bottom: 1px solid #e9edeb; white-space: nowrap; }
    td { font-family: Consolas, "Microsoft YaHei UI", monospace; }
    tbody tr:hover { background: #f6f8f6; }
    .positive { color: var(--green) !important; }
    .negative { color: var(--red) !important; }
    .neutral { color: var(--ink) !important; }
    .empty { padding: 22px; color: var(--muted); text-align: center; }
    @media (max-width: 1380px) {
      .kpi-grid { grid-template-columns: repeat(4, minmax(130px, 1fr)); }
      .detail-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .detail-item:nth-child(4n) { border-right: 1px solid #edf0ee; }
      .detail-item:nth-child(3n) { border-right: 0; }
    }
    @media (max-width: 980px) {
      .workspace { padding: 12px; }
      .layout-main, .layout-half, .layout-third { grid-template-columns: 1fr; }
      .run-state { min-width: 0; }
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .detail-item:nth-child(3n) { border-right: 1px solid #edf0ee; }
      .detail-item:nth-child(2n) { border-right: 0; }
    }
    @media (max-width: 600px) {
      .topbar-main { align-items: flex-start; flex-direction: column; padding: 11px 13px; }
      .run-state { width: 100%; text-align: left; }
      .run-state-line { justify-content: flex-start; }
      .tabs { overflow-x: auto; scrollbar-width: none; }
      .tabs::-webkit-scrollbar { display: none; }
      .tab { flex: 0 0 auto; }
      .chart { height: 290px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-main">
      <div class="brand">
        <div class="brand-title">治理实时监控</div>
        <div class="brand-subtitle" id="runTitle">等待治理运行会话</div>
      </div>
      <div class="run-state">
        <div class="run-state-line"><span class="status-dot" id="statusDot"></span><span class="status-text" id="status">正在连接运行状态</span></div>
        <div class="run-detail" id="runDetail">-- / --</div>
      </div>
    </div>
    <div class="progress-track"><div class="progress-fill" id="progressBar"></div></div>
  </header>

  <main class="workspace">
    <section class="kpi-grid" id="kpiGrid"></section>

    <nav class="tabs" aria-label="监控视图">
      <button class="tab active" data-tab="overview">总览</button>
      <button class="tab" data-tab="risk">风险与仓位</button>
      <button class="tab" data-tab="execution">候选与执行</button>
      <button class="tab" data-tab="factors">因子权重</button>
      <button class="tab" data-tab="holdings">持仓路径</button>
    </nav>

    <section class="tab-panel active" id="tab-overview">
      <div class="layout-main">
        <article class="panel">
          <div class="panel-header">
            <div><div class="panel-title">账户净值与基准</div><div class="panel-note">统一以 1.0000 为起点；不混用资金金额与净值倍数</div></div>
            <div class="range-control" aria-label="曲线区间">
              <button class="range-button" data-range="60">60</button>
              <button class="range-button active" data-range="180">180</button>
              <button class="range-button" data-range="0">全部</button>
            </div>
          </div>
          <div class="chart-body"><canvas class="chart" id="perfChart"></canvas></div>
          <div class="panel-body legend">
            <span class="legend-item"><i class="legend-line" style="background:#087a55"></i>账户净值</span>
            <span class="legend-item"><i class="legend-line" style="background:#246b9e"></i>前 30% 强度基准</span>
          </div>
        </article>
        <aside class="panel">
          <div class="panel-header"><div class="panel-title">当前账户状态</div><div class="panel-note" id="asOfDate">--</div></div>
          <div class="panel-body">
            <dl class="summary-list" id="accountSummary"></dl>
            <div class="exposure-row"><div class="exposure-label"><span>实际仓位</span><span id="actualExposureLabel">--</span></div><div class="exposure-bar"><div id="actualExposureBar"></div></div></div>
            <div class="exposure-row"><div class="exposure-label"><span>目标仓位</span><span id="targetExposureLabel">--</span></div><div class="exposure-bar"><div id="targetExposureBar" style="background:#a87518"></div></div></div>
          </div>
        </aside>
      </div>
      <div class="layout-half">
        <article class="panel"><div class="panel-header"><div><div class="panel-title">超额净值</div><div class="panel-note">账户净值 / 基准净值</div></div></div><div class="chart-body"><canvas class="chart medium" id="excessChart"></canvas></div></article>
        <article class="panel"><div class="panel-header"><div><div class="panel-title">账户回撤</div><div class="panel-note">相对历史净值峰值</div></div></div><div class="chart-body"><canvas class="chart medium" id="drawdownChart"></canvas></div></article>
      </div>
      <div class="panel" style="margin-top:12px"><div class="panel-header"><div class="panel-title">运营指标</div><div class="panel-note">详细指标保留，但不与主 KPI 争夺视觉优先级</div></div><div class="detail-grid" id="overviewDetails"></div></div>
    </section>

    <section class="tab-panel" id="tab-risk">
      <div class="panel"><div class="panel-header"><div class="panel-title">风险与仓位指标</div></div><div class="detail-grid" id="riskDetails"></div></div>
      <div class="layout-third">
        <article class="panel"><div class="panel-header"><div class="panel-title">安全状态</div></div><div class="panel-body"><pre class="text-report" id="safetyText">等待数据</pre></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">风险模型</div></div><div class="panel-body"><pre class="text-report" id="riskModelText">等待数据</pre></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">基准与超额</div></div><div class="panel-body"><pre class="text-report" id="benchmarkText">等待数据</pre></div></article>
      </div>
      <div class="panel" style="margin-top:12px"><div class="panel-header"><div class="panel-title">仓位与现金</div></div><div class="panel-body"><pre class="text-report" id="exposureText">等待数据</pre></div></div>
    </section>

    <section class="tab-panel" id="tab-execution">
      <div class="panel"><div class="panel-header"><div class="panel-title">候选与执行指标</div></div><div class="detail-grid" id="executionDetails"></div></div>
      <div class="layout-half">
        <article class="panel"><div class="panel-header"><div class="panel-title">买入门控</div></div><div class="panel-body"><pre class="text-report" id="entryGateText">等待数据</pre></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">交易质量</div></div><div class="panel-body"><pre class="text-report" id="tradeQualityText">等待数据</pre></div></article>
      </div>
      <div class="layout-third">
        <article class="panel"><div class="panel-header"><div class="panel-title">最新订单</div></div><div class="panel-body"><pre class="text-report" id="ordersText">暂无订单</pre></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">订单原因</div></div><div class="panel-body"><pre class="text-report" id="orderReasonText">暂无订单原因</pre></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">未完成订单</div></div><div class="panel-body"><pre class="text-report" id="pendingText">暂无未完成订单</pre></div></article>
      </div>
      <div class="panel" style="margin-top:12px"><div class="panel-header"><div class="panel-title">候选漏斗预览</div></div><div class="panel-body"><pre class="text-report" id="candidatesText">等待候选数据</pre></div></div>
    </section>

    <section class="tab-panel" id="tab-factors">
      <div class="layout-half">
        <article class="panel"><div class="panel-header"><div class="panel-title">Alpha 因子权重</div><div class="panel-note">当前权重前八项</div></div><div class="chart-body"><canvas class="chart medium" id="factorChart"></canvas></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">Alpha 模块权重</div><div class="panel-note">按经济模块聚合</div></div><div class="chart-body"><canvas class="chart medium" id="moduleChart"></canvas></div></article>
      </div>
      <div class="layout-half">
        <article class="panel"><div class="panel-header"><div class="panel-title">当前持仓</div></div><div class="table-scroll"><table><thead><tr><th>代码</th><th>市值</th><th>账户权重</th></tr></thead><tbody id="holdingsBody"></tbody></table></div></article>
        <article class="panel"><div class="panel-header"><div class="panel-title">模块权重明细</div></div><div class="table-scroll"><table><thead><tr><th>模块</th><th>占比</th><th>因子数</th><th>5 日预测</th></tr></thead><tbody id="moduleWeightsBody"></tbody></table></div></article>
      </div>
      <article class="panel" style="margin-top:12px"><div class="panel-header"><div class="panel-title">因子权重明细</div></div><div class="table-scroll"><table><thead><tr><th>模块</th><th>角色</th><th>因子</th><th>权重</th><th>占比</th><th>变化</th><th>5 日预测</th><th>说明</th></tr></thead><tbody id="factorWeightsBody"></tbody></table></div></article>
    </section>

    <section class="tab-panel" id="tab-holdings">
      <article class="panel">
        <div class="panel-header"><div><div class="panel-title">当前持仓价格路径</div><div class="panel-note">每只股票按实际入场价归一化为 1.0000；实心圆标记实际买入节点；最多展示市值前六只</div></div></div>
        <div class="chart-body"><canvas class="chart" id="holdingPathChart"></canvas></div>
        <div class="panel-body legend" id="holdingPathLegend"><span class="panel-note">尚无有效持仓路径</span></div>
      </article>
      <article class="panel" style="margin-top:12px"><div class="panel-header"><div class="panel-title">持仓生命周期</div><div class="panel-note">入场、浮盈亏和退出警报使用同一持仓状态快照</div></div><div class="table-scroll"><table><thead><tr><th>代码</th><th>入场</th><th>浮盈亏</th><th>MFE</th><th>MAE</th><th>回吐</th><th>趋势</th><th>峰值衰减</th><th>亏损风险</th><th>状态</th><th>警报</th></tr></thead><tbody id="lifecycleBody"></tbody></table></div></article>
    </section>
  </main>

  <script>
    const KPI_DEFS = [
      ["total_return", "账户收益", "自运行起点"], ["nav", "账户净值", "归一化净值"],
      ["excess_nav", "超额净值", "相对前 30% 基准"], ["current_drawdown", "当前回撤", "相对账户峰值"],
      ["actual_exposure", "实际仓位", "账户口径"], ["holdings", "持仓数", "当前有效持仓"],
      ["candidate_count", "候选数", "当日原始候选"], ["risk_level", "风险等级", "治理安全状态"],
    ];
    const DETAIL_GROUPS = {
      overviewDetails: [
        ["benchmark_nav","基准净值"],["valid_invested_nav","持仓/投入净值"],["account_max_drawdown","账户最大回撤"],
        ["holding_max_drawdown","持仓最大回撤"],["benchmark_max_drawdown","基准最大回撤"],["excess_max_drawdown","超额最大回撤"],
        ["sharpe","年化夏普"],["sortino","年化索提诺"],["annual_volatility","年化波动"],["cash","现金"],["cash_drag","现金拖累"],
        ["closed_trade_win_rate","平仓胜率"],["profit_factor","利润因子"],
      ],
      riskDetails: [
        ["risk_level","风险等级"],["exposure_cap","仓位上限"],["target_exposure","目标仓位"],["actual_exposure","实际仓位"],
        ["exposure_gap","仓位缺口"],["idle_cash_ratio","闲置现金比例"],["target_holding_count","目标持仓数"],
        ["holding_shortfall_count","持仓不足数"],["tail_risk_proxy_mean","尾部风险均值"],["future_loss_risk_score_mean","未来亏损风险"],
        ["empirical_distribution_score_mean","经验分布均分"],["trend_direction_score_mean","趋势方向均值"],["peak_decay_score_mean","峰值衰退均值"],
        ["defensive_eligible_count","防守候选数"],["downtrend_decay_count","阴跌风险"],["lifecycle_alerts","生命周期警报"],
        ["buy_sell_conflict_cooldown_days","买卖冲突冷却天数"],
      ],
      executionDetails: [
        ["candidate_count","候选数"],["confirmed_count","确认数"],["order_count","订单数"],["pending_orders","未完成订单"],
        ["buy_accuracy_5d","买入 5 日准确率"],["sell_accuracy_5d","卖出 5 日准确率"],["realized_pnl","已实现盈亏"],
        ["gross_profit","平仓总盈利"],["gross_loss","平仓总亏损"],["control_exit_count","控制卖出次数"],
        ["retail_lot_cash_insufficient_count","一手资金不足"],["retail_state_block_count","状态拦截买单"],
        ["surge_candidate_count","急涨候选"],["strong_starter_count","强启动候选"],["exhaustion_block_count","衰竭拦截"],
        ["protecting_profit_count","利润保护持仓"],["retail_upgraded_to_one_lot_count","小资金一手升级"],
        ["starter_2_lot_count","两手首买候选"],["diversify_1_lot_count","分散一手候选"],
        ["control_avoided_loss","控制避免亏损"],["hard_stop_avoided_loss","硬止损避免亏损"],
        ["alpha_collapse_avoided_loss","Alpha 塌陷避免亏损"],["safety_deleveraging_avoided_loss","安全降仓避免亏损"],
      ],
    };
    const metricValues = {};
    const metricDirections = {};
    let history = [], factorHistory = [], moduleHistory = [];
    let totalDays = 1, initialNav = 1, activeRunId = "", lastProgressPct = 0, chartRange = 180, hoverIndex = null;
    const palette = ["#087a55", "#246b9e", "#a87518", "#705a9f", "#bd3d39", "#427b75", "#8a5c3b", "#52627a"];

    function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
    function finite(value, fallback=0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
    function fmtPct(value) { const n = Number(value); return Number.isFinite(n) ? `${(n*100).toFixed(2)}%` : "--"; }
    function fmtNum(value, digits=2) { const n = Number(value); return Number.isFinite(n) ? n.toFixed(digits) : "--"; }
    function fmtMoney(value) { const n = Number(value); return Number.isFinite(n) ? n.toLocaleString("zh-CN", {maximumFractionDigits:0}) : "--"; }
    function normalizeNav(value, fallback=1) { const n = Number(value); if (!Number.isFinite(n) || n <= 0) return fallback; return n > 100 ? n / Math.max(initialNav, 1e-12) : n; }
    function tone(direction) { return direction > 1e-12 ? "positive" : direction < -1e-12 ? "negative" : "neutral"; }
    function setMetric(key, text, direction=0) {
      metricValues[key] = String(text);
      metricDirections[key] = Number(direction) || 0;
      for (const prefix of ["kpi_", "metric_"]) {
        const node = document.getElementById(prefix + key);
        if (node) { node.textContent = text; node.className = `${prefix === "kpi_" ? "kpi-value" : "detail-value"} ${tone(direction)}`; }
      }
    }
    function buildStaticUi() {
      const root = document.getElementById("kpiGrid");
      root.innerHTML = KPI_DEFS.map(([key,label,context]) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value" id="kpi_${key}">--</div><div class="kpi-context">${context}</div></div>`).join("");
      for (const [rootId, defs] of Object.entries(DETAIL_GROUPS)) {
        document.getElementById(rootId).innerHTML = defs.map(([key,label]) => `<div class="detail-item"><div class="detail-key">${label}</div><div class="detail-value" id="metric_${key}">--</div></div>`).join("");
      }
      document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === button));
        document.querySelectorAll(".tab-panel").forEach(x => x.classList.toggle("active", x.id === `tab-${button.dataset.tab}`));
        requestAnimationFrame(drawAllCharts);
      }));
      document.querySelectorAll(".range-button").forEach(button => button.addEventListener("click", () => {
        chartRange = Number(button.dataset.range || 0);
        document.querySelectorAll(".range-button").forEach(x => x.classList.toggle("active", x === button));
        drawAllCharts();
      }));
      window.addEventListener("resize", () => requestAnimationFrame(drawAllCharts));
      for (const id of ["perfChart","excessChart","drawdownChart"]) {
        document.getElementById(id).addEventListener("mousemove", event => {
          const rect = event.currentTarget.getBoundingClientRect();
          const points = visibleHistory();
          hoverIndex = points.length > 1 ? Math.round((event.clientX - rect.left - 58) / Math.max(rect.width - 78, 1) * (points.length - 1)) : 0;
          hoverIndex = Math.max(0, Math.min(hoverIndex, points.length - 1));
          drawAllCharts();
        });
        document.getElementById(id).addEventListener("mouseleave", () => { hoverIndex = null; drawAllCharts(); });
      }
    }
    function visibleHistory() { return chartRange > 0 ? history.slice(-chartRange) : history.slice(); }
    function prepareCanvas(id) {
      const canvas = document.getElementById(id); if (!canvas || canvas.offsetParent === null) return null;
      const rect = canvas.getBoundingClientRect(); const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(Math.round(rect.width*dpr), 1); canvas.height = Math.max(Math.round(rect.height*dpr), 1);
      const ctx = canvas.getContext("2d"); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,rect.width,rect.height);
      return {canvas,ctx,w:rect.width,h:rect.height};
    }
    function chartBounds(values, baseline=null) {
      const data = values.map(Number).filter(Number.isFinite); if (baseline !== null) data.push(baseline);
      if (!data.length) return {min:.995,max:1.005}; let min=Math.min(...data), max=Math.max(...data);
      const pad=Math.max((max-min)*.1, Math.abs(max||1)*.0025); return {min:min-pad,max:max+pad};
    }
    function drawFrame(ctx,w,h,bounds,dates,format=fmtNum) {
      const p={l:58,r:w-20,t:18,b:h-34}; ctx.font="11px Consolas"; ctx.lineWidth=1;
      for(let i=0;i<=4;i++){const y=p.t+(p.b-p.t)*i/4;ctx.strokeStyle="#e7ebe8";ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(p.r,y);ctx.stroke();ctx.fillStyle="#78827f";ctx.textAlign="right";ctx.fillText(format(bounds.max-(bounds.max-bounds.min)*i/4),p.l-8,y+4);}
      const tickCount=Math.min(5,dates.length); for(let i=0;i<tickCount;i++){const index=tickCount===1?0:Math.round((dates.length-1)*i/(tickCount-1));const x=dates.length===1?p.l:p.l+(p.r-p.l)*index/(dates.length-1);ctx.strokeStyle="#f0f2f1";ctx.beginPath();ctx.moveTo(x,p.t);ctx.lineTo(x,p.b);ctx.stroke();ctx.fillStyle="#78827f";ctx.textAlign=i===0?"left":i===tickCount-1?"right":"center";ctx.fillText(String(dates[index]||"").slice(5),x,p.b+20);}
      ctx.textAlign="left"; return p;
    }
    function drawLine(ctx,values,p,bounds,color,width=2) { ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin="round";ctx.lineCap="round";ctx.beginPath();values.forEach((v,i)=>{const x=values.length===1?p.l:p.l+(p.r-p.l)*i/(values.length-1);const y=p.b-(finite(v)-bounds.min)/Math.max(bounds.max-bounds.min,1e-12)*(p.b-p.t);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke(); }
    function drawHover(ctx,p,points,series) { if(hoverIndex===null || !points.length) return; const i=Math.min(hoverIndex,points.length-1); const x=points.length===1?p.l:p.l+(p.r-p.l)*i/(points.length-1);ctx.strokeStyle="#9aa4a0";ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x,p.t);ctx.lineTo(x,p.b);ctx.stroke();ctx.setLineDash([]);const lines=[points[i].date,...series.map(s=>`${s.label} ${s.format(s.values[i])}`)];ctx.font="11px Consolas";const width=Math.max(...lines.map(x=>ctx.measureText(x).width))+18;const boxX=x+width+10>p.r?x-width-8:x+8;ctx.fillStyle="rgba(31,45,41,.94)";ctx.fillRect(boxX,p.t+8,width,lines.length*17+8);lines.forEach((line,j)=>{ctx.fillStyle=j===0?"#aebbb6":"#fff";ctx.fillText(line,boxX+9,p.t+24+j*17);}); }
    function drawPerformance() { const c=prepareCanvas("perfChart"),points=visibleHistory();if(!c)return;const {ctx,w,h}=c;if(!points.length)return drawEmpty(ctx,"等待净值数据");const a=points.map(x=>x.navMultiple),b=points.map(x=>x.benchmarkNav),bounds=chartBounds([...a,...b],1),p=drawFrame(ctx,w,h,bounds,points.map(x=>x.date),v=>fmtNum(v,4));drawLine(ctx,a,p,bounds,"#087a55",2.2);drawLine(ctx,b,p,bounds,"#246b9e",1.8);drawHover(ctx,p,points,[{label:"账户",values:a,format:v=>fmtNum(v,4)},{label:"基准",values:b,format:v=>fmtNum(v,4)}]); }
    function drawExcess() { const c=prepareCanvas("excessChart"),points=visibleHistory();if(!c)return;const {ctx,w,h}=c;if(!points.length)return drawEmpty(ctx,"等待超额净值数据");const v=points.map(x=>x.excessNav),bounds=chartBounds(v,1),p=drawFrame(ctx,w,h,bounds,points.map(x=>x.date),x=>fmtNum(x,4));const y0=p.b-(1-bounds.min)/(bounds.max-bounds.min)*(p.b-p.t);ctx.strokeStyle="#b8c0bc";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(p.l,y0);ctx.lineTo(p.r,y0);ctx.stroke();ctx.setLineDash([]);drawLine(ctx,v,p,bounds,"#a87518",2.2);drawHover(ctx,p,points,[{label:"超额",values:v,format:x=>fmtNum(x,4)}]); }
    function drawDrawdown() { const c=prepareCanvas("drawdownChart"),points=visibleHistory();if(!c)return;const {ctx,w,h}=c;if(!points.length)return drawEmpty(ctx,"等待回撤数据");const v=points.map(x=>x.drawdown),bounds={min:Math.min(...v,-.01)*1.12,max:0},p=drawFrame(ctx,w,h,bounds,points.map(x=>x.date),fmtPct);drawLine(ctx,v,p,bounds,"#bd3d39",2);drawHover(ctx,p,points,[{label:"回撤",values:v,format:fmtPct}]); }
    function drawEmpty(ctx,text){ctx.fillStyle="#7c8783";ctx.font="12px Microsoft YaHei UI";ctx.fillText(text,18,28);}
    function annualizedSortino(returns,navMultiple,tradingDays){
      const values=(returns||[]).map(Number).filter(Number.isFinite),downside=values.filter(value=>value<0);
      const periods=Math.max(Math.floor(finite(tradingDays)),0);
      if(values.length<2||downside.length<2||periods<=1||!(finite(navMultiple)>0))return NaN;
      const annualReturn=Math.pow(finite(navMultiple),252/periods)-1;
      const downsideMean=downside.reduce((sum,value)=>sum+value,0)/downside.length;
      const downsideVariance=downside.reduce((sum,value)=>sum+(value-downsideMean)**2,0)/(downside.length-1);
      const annualDownsideVolatility=Math.sqrt(Math.max(downsideVariance,0))*Math.sqrt(252);
      return annualDownsideVolatility>1e-12?annualReturn/annualDownsideVolatility:NaN;
    }
    function aggregateModules(weights){const map={};for(const item of weights||[]){const key=String(item.factor_module||"unknown");if(!map[key])map[key]={factor_module:key,weight_share:0,weight:0,factor_count:0,avg_predicted_return_5d:0};map[key].weight_share+=finite(item.weight_share);map[key].weight+=finite(item.weight);map[key].factor_count+=1;map[key].avg_predicted_return_5d+=finite(item.avg_predicted_return_5d);}return Object.values(map).sort((a,b)=>b.weight_share-a.weight_share);}
    function drawMulti(id,points,nameKey,label){const c=prepareCanvas(id);if(!c)return;const {ctx,w,h}=c;if(!points.length)return drawEmpty(ctx,`等待${label}数据`);const latest=points[points.length-1].weights||[];const names=latest.slice().sort((a,b)=>finite(b.weight_share)-finite(a.weight_share)).slice(0,8).map(x=>String(x[nameKey]));const all=[];for(const point of points){const map=Object.fromEntries((point.weights||[]).map(x=>[String(x[nameKey]),finite(x.weight_share)]));names.forEach(n=>all.push(map[n]||0));}const bounds=chartBounds(all,0),p=drawFrame(ctx,w,h,bounds,points.map(x=>x.date),fmtPct);names.forEach((name,j)=>{const vals=points.map(point=>{const found=(point.weights||[]).find(x=>String(x[nameKey])===name);return finite(found&&found.weight_share);});drawLine(ctx,vals,p,bounds,palette[j%palette.length],1.7);ctx.fillStyle=palette[j%palette.length];ctx.font="10px Microsoft YaHei UI";ctx.fillText(name.slice(0,18),p.l+(j%4)*Math.max((p.r-p.l)/4,100),10+Math.floor(j/4)*12);});}
    function drawHoldingPaths(paths) {
      const c=prepareCanvas("holdingPathChart"); if(!c)return;
      const {ctx,w,h}=c,legend=document.getElementById("holdingPathLegend");
      const usable=(paths||[]).filter(x=>(x.points||[]).length>1).slice(0,6);
      if(!usable.length){
        if(legend)legend.innerHTML='<span class="panel-note">当前没有可绘制的持仓；成交并完成首日收盘标记后自动出现。</span>';
        return drawEmpty(ctx,"暂无有效持仓价格路径");
      }
      const values=usable.flatMap(x=>x.points.map(point=>finite(point.value,1)));
      const longest=usable.slice().sort((a,b)=>b.points.length-a.points.length)[0];
      const dates=longest.points.map(point=>point.date),bounds=chartBounds(values,1);
      const p=drawFrame(ctx,w,h,bounds,dates,value=>fmtNum(value,3));
      const y0=p.b-(1-bounds.min)/Math.max(bounds.max-bounds.min,1e-12)*(p.b-p.t);
      ctx.strokeStyle="#aeb7b3";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(p.l,y0);ctx.lineTo(p.r,y0);ctx.stroke();ctx.setLineDash([]);

      usable.forEach((path,j)=>{
        const color=palette[j%palette.length];
        const vals=path.points.map(point=>finite(point.value,1));
        drawLine(ctx,vals,p,bounds,color,2);
        const entryIndex=Number(path.entry_index);
        const entryVisible=Boolean(path.entry_visible!==false)&&Number.isInteger(entryIndex)&&entryIndex>=0&&entryIndex<vals.length;
        if(!entryVisible)return;

        const x=vals.length===1?p.l:p.l+(p.r-p.l)*entryIndex/(vals.length-1);
        const entryDate=String(path.entry_date||path.points[entryIndex].date||"").slice(5);
        const entryPrice=Number(path.entry_price);
        const label=`买入 ${entryDate}${Number.isFinite(entryPrice)?` @ ${entryPrice.toFixed(2)}`:""}`;
        ctx.save();
        ctx.strokeStyle=`${color}66`;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,p.t);ctx.lineTo(x,p.b);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle="#fff";ctx.beginPath();ctx.arc(x,y0,6,0,Math.PI*2);ctx.fill();
        ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y0,4,0,Math.PI*2);ctx.fill();
        ctx.font="10px Microsoft YaHei UI";
        const labelWidth=ctx.measureText(label).width+10;
        const labelX=Math.max(p.l,Math.min(x+7,p.r-labelWidth));
        const upperY=y0-12-(j%3)*16;
        const labelY=upperY>p.t+8?upperY:Math.min(y0+18+(j%3)*16,p.b-4);
        ctx.fillStyle="rgba(255,255,255,.92)";ctx.fillRect(labelX-3,labelY-11,labelWidth,15);
        ctx.fillStyle="#173f35";ctx.fillText(label,labelX+2,labelY);
        ctx.restore();
      });
      if(legend)legend.innerHTML=usable.map((path,j)=>{
        const color=palette[j%palette.length],entryDate=String(path.entry_date||"").slice(0,10);
        const entryPrice=Number(path.entry_price),outside=path.entry_visible===false?"（窗口外）":"";
        const entryText=entryDate?`买入 ${escapeHtml(entryDate)}${Number.isFinite(entryPrice)?` @ ${entryPrice.toFixed(2)}`:""}${outside}`:"买入信息缺失";
        return `<span class="legend-item" style="color:${color}"><i class="legend-line" style="background:${color}"></i><i class="legend-entry-dot" style="background:${color}"></i><span style="color:var(--muted)">${escapeHtml(String(path.symbol||""))} ${fmtPct(finite(path.unrealized_return))} · ${entryText}</span></span>`;
      }).join("");
    }
    function drawAllCharts(){drawPerformance();drawExcess();drawDrawdown();drawMulti("factorChart",factorHistory,"model_name","因子权重");drawMulti("moduleChart",moduleHistory,"factor_module","模块权重");drawHoldingPaths(window.latestHoldingPaths||[]);}
    function summaryLines(items,empty="暂无记录"){const rows=(items||[]).slice(0,10);return rows.length?rows.map(x=>`${String(x.name||"").padEnd(26)} ${String(x.count??"").padStart(5)} ${fmtPct(finite(x.share)).padStart(9)}`):[empty];}
    function renderTable(id,rows,columns,colspan){const body=document.getElementById(id);body.innerHTML=rows.length?rows.map(row=>`<tr>${columns.map(column=>`<td class="${column.tone?column.tone(row):""}">${column.render(row)}</td>`).join("")}</tr>`).join(""):`<tr><td colspan="${colspan}" class="empty">暂无数据</td></tr>`;}
    function updateReports(exposure,ms,computed){
      const {navMultiple,totalReturn,benchmarkNav,excessNav,maxDrawdown,actualExposure,targetExposure,exposureGap,cashDrag}=computed;
      document.getElementById("benchmarkText").textContent=[`账户净值              : ${fmtNum(navMultiple,4)} (${fmtPct(totalReturn)})`,`基准净值              : ${fmtNum(benchmarkNav,4)} (${fmtPct(benchmarkNav-1)})`,`超额净值              : ${fmtNum(excessNav,4)} (${fmtPct(excessNav-1)})`,`账户最大回撤          : ${fmtPct(maxDrawdown)}`,`基准 5 日收益         : ${fmtPct(finite(ms.benchmark_return_5d,NaN))}`,`基准 20 日收益        : ${fmtPct(finite(ms.benchmark_return_20d,NaN))}`,`基准水下幅度          : ${fmtPct(finite(ms.benchmark_underwater_from_peak,NaN))}`].join("\n");
      document.getElementById("exposureText").textContent=[`现金                  : ${fmtMoney(exposure.cash)}`,`已投入市值            : ${fmtMoney(exposure.invested_value)}`,`实际仓位              : ${fmtPct(actualExposure)}`,`目标仓位              : ${fmtPct(targetExposure)}`,`有效目标上限          : ${fmtPct(finite(ms.effective_target_exposure_cap))}`,`仓位缺口              : ${fmtPct(exposureGap)}`,`现金拖累              : ${fmtPct(cashDrag)}`,`换手预算              : ${fmtPct(finite(ms.turnover_budget))}`,`允许追仓              : ${Boolean(ms.catchup_allowed)}`,`追仓拦截原因          : ${ms.catchup_block_reason||"--"}`].join("\n");
      document.getElementById("entryGateText").textContent=[`候选数量              : ${ms.candidate_count??0}`,`买入确认数量          : ${ms.entry_confirmed_count??0}`,`确认比例              : ${fmtPct(finite(ms.candidate_count)>0?finite(ms.entry_confirmed_count)/finite(ms.candidate_count):0)}`,`订单流通过数          : ${ms.orderflow_candidate_pass_count??0}`,`反转通过数            : ${ms.reversal_confirm_pass_count??0}`,`突破通过数            : ${ms.breakout_gate_pass_count??0}`,`Entry Alpha 均分      : ${fmtNum(ms.entry_alpha_score_mean,3)}`,`Timing 均分           : ${fmtNum(ms.entry_timing_score_mean,3)}`,`Liquidity 均分        : ${fmtNum(ms.entry_liquidity_score_mean,3)}`,`Entry Matrix 均分     : ${fmtNum(ms.entry_matrix_score_mean,3)}`,`成功概率均值          : ${fmtPct(finite(ms.entry_success_probability_mean))}`,"","主要拦截原因",...summaryLines(ms.entry_block_summary,"暂无拦截记录")].join("\n");
      document.getElementById("tradeQualityText").textContent=[`买入 5 日准确率       : ${fmtPct(finite(ms.trailing_buy_accuracy_5d,NaN))}`,`卖出 5 日准确率       : ${fmtPct(finite(ms.trailing_sell_accuracy_5d,NaN))}`,`最佳替换优势          : ${fmtPct(finite(ms.best_replacement_edge_10d))}`,`替换卖出数量          : ${ms.replacement_opportunity_sell_count??0}`,`利润回吐观察数        : ${ms.profit_giveback_observation_count??0}`,`入场失败卖出数        : ${ms.post_entry_failure_exit_count??0}`,`生命周期警报数        : ${ms.lifecycle_alert_count??0}`,`计划订单数            : ${ms.order_count??0}`,`未完成订单数          : ${ms.pending_order_count??0}`,"","订单原因",...summaryLines(ms.order_reason_summary,"暂无订单原因")].join("\n");
      document.getElementById("riskModelText").textContent=[`协方差模型启用        : ${Boolean(ms.covariance_risk_model_used)}`,`组合协方差波动        : ${fmtPct(finite(ms.portfolio_covariance_volatility))}`,`最大风险贡献          : ${fmtPct(finite(ms.max_risk_contribution))}`,`前五风险贡献          : ${fmtPct(finite(ms.top5_risk_contribution_sum))}`,`风险门控通过          : ${Boolean(ms.risk_contribution_gate_pass??true)}`,`风险仓位缩放          : ${fmtNum(ms.risk_contribution_exposure_scale,3)}`,`风险股票数            : ${ms.risk_symbol_count??0}`,`平均两两相关          : ${fmtNum(ms.avg_pairwise_correlation,3)}`,`风险等级              : ${ms.risk_level||"--"}`,`流动性压力            : ${fmtPct(finite(ms.market_liquidity_stress_ratio))}`,`未解决安全仓位        : ${fmtPct(finite(ms.unresolved_safety_exposure))}`].join("\n");
      document.getElementById("safetyText").textContent=[`风险等级              : ${ms.risk_level||"--"}`,`原始风险等级          : ${ms.raw_risk_level||"--"}`,`触发连续天数          : ${ms.trigger_streak_days??"--"}`,`触发来源              : ${ms.trigger_source||"--"}`,`结构性市场状态        : ${ms.structural_regime_level||"--"}`,`状态仓位预算          : ${fmtPct(finite(ms.regime_exposure_budget))}`,`安全仓位上限          : ${fmtPct(finite(ms.safety_exposure_cap))}`,`硬冻结                : ${Boolean(ms.hard_freeze_active)}`,`允许追仓              : ${Boolean(ms.catchup_allowed)}`,`准确率乘数            : ${fmtNum(ms.accuracy_multiplier,2)}`,`运行状态              : ${ms.regime||"--"}`,`最大持股数            : ${ms.top_n??"--"}`].join("\n");
      const appendReport=(id,lines)=>{const node=document.getElementById(id);node.textContent+=`\n${lines.join("\n")}`;};
      appendReport("benchmarkText",[`基准 5 日回撤         : ${fmtPct(finite(ms.benchmark_drawdown_5d))}`,`基准 20 日回撤        : ${fmtPct(finite(ms.benchmark_drawdown_20d))}`]);
      appendReport("exposureText",[`基础状态仓位          : ${fmtPct(finite(ms.base_exposure_by_regime))}`,`原始安全上限          : ${fmtPct(finite(ms.raw_safety_exposure_cap))}`,`计划安全卖出          : ${fmtPct(finite(ms.planned_safety_sell_weight))}`,`约束现金保留          : ${fmtPct(finite(ms.constraint_cash_reserve))}`,`普通换手权重          : ${fmtPct(finite(ms.normal_turnover_weight))}`,`目标总漂移            : ${fmtPct(finite(ms.total_target_drift))}`,`追仓预算              : ${fmtPct(finite(ms.catchup_buy_budget))}`,`追仓档位              : ${ms.catchup_tier||"--"}`]);
      appendReport("entryGateText",[`订单流候选均分        : ${fmtNum(ms.orderflow_candidate_score_mean,3)}`,`反转入场均分          : ${fmtNum(ms.reversal_entry_score_mean,3)}`,`突破门控均分          : ${fmtNum(ms.breakout_gate_score_mean,3)}`,`趋势持有均分          : ${fmtNum(ms.trend_hold_score_mean,3)}`,`模块候选均分          : ${fmtNum(ms.module_candidate_score_mean,3)}`,`模块入场均分          : ${fmtNum(ms.module_entry_score_mean,3)}`,`模块持有均分          : ${fmtNum(ms.module_hold_score_mean,3)}`,`股票质量均分          : ${fmtNum(ms.alpha_quality_score_mean,3)}`,`急涨捕捉均分          : ${fmtNum(ms.surge_capture_score_mean,3)}`,`跟随确认均分          : ${fmtNum(ms.follow_through_score_mean,3)}`,`衰竭风险均分          : ${fmtNum(ms.exhaustion_score_mean,3)}`,`经验分布均分          : ${fmtNum(ms.empirical_distribution_score_mean,3)}`,`趋势方向均分          : ${fmtNum(ms.trend_direction_score_mean,3)}`,`峰值衰退均分          : ${fmtNum(ms.peak_decay_score_mean,3)}`,`阴跌衰减均分          : ${fmtNum(ms.downtrend_decay_score_mean,3)}`,`入场失败均分          : ${fmtNum(ms.post_entry_failure_score_mean,3)}`,`防守候选数            : ${ms.defensive_eligible_count??0}`]);
      appendReport("tradeQualityText",[`控制避免亏损        : ${fmtMoney(ms.avoided_loss_to_window_low)}`,`硬止损避免亏损        : ${fmtMoney(ms.hard_stop_avoided_loss_to_window_low)}`,`Alpha 塌陷避免亏损   : ${fmtMoney(ms.alpha_collapse_avoided_loss_to_window_low)}`,`安全降仓避免亏损      : ${fmtMoney(ms.safety_deleveraging_avoided_loss_to_window_low)}`,`趋势破坏观察数        : ${ms.trend_break_observation_count??0}`,`量价分布观察数        : ${ms.volume_distribution_observation_count??0}`,`一手升级数            : ${ms.retail_upgraded_to_one_lot_count??0}`,`两手首买候选          : ${ms.starter_2_lot_count??0}`,`分散一手候选          : ${ms.diversify_1_lot_count??0}`]);
      appendReport("riskModelText",[`风险拦截原因          : ${ms.risk_contribution_block_reason||"--"}`,`协方差条件数          : ${fmtNum(ms.covariance_condition_number,1)}`,`新买风险拦截          : ${Boolean(ms.risk_new_buy_block)}`,`新买拦截已应用        : ${Boolean(ms.risk_new_buy_block_applied)}`,`追仓风险拦截          : ${Boolean(ms.risk_catchup_block)}`,`追仓拦截已应用        : ${Boolean(ms.risk_catchup_block_applied)}`,`风险拦截买入权重      : ${fmtPct(finite(ms.risk_blocked_new_buy_weight))}`]);
      appendReport("safetyText",[`授权 10 日优势均值     : ${fmtPct(finite(ms.authorization_expected_edge_10d_mean))}`,`授权胜率均值          : ${fmtPct(finite(ms.authorization_p_win_10d_mean))}`,`授权档位              : ${ms.exposure_authorization_tier||"--"}`,`授权拦截原因          : ${ms.exposure_authorization_block_reasons||"--"}`,`市场状态叠加模式      : ${ms.regime_overlay_mode||"--"}`,`市场状态叠加封顶      : ${Boolean(ms.regime_overlay_capped)}`,`买卖冲突冷却天数      : ${ms.buy_sell_conflict_cooldown_days??0}`]);
    }
    function renderOperational(exposure,ms,holdings,nav){
      renderTable("holdingsBody",(holdings||[]).filter(x=>String(x.symbol||"").trim()).sort((a,b)=>finite(b.market_value)-finite(a.market_value)).slice(0,16),[
        {render:x=>escapeHtml(x.symbol)},{render:x=>fmtMoney(x.market_value)},{render:x=>fmtPct(Number.isFinite(Number(x.account_weight))?Number(x.account_weight):finite(x.market_value)/Math.max(nav,1e-12))}],3);
      const modules=(ms.module_weights&&ms.module_weights.length?ms.module_weights:aggregateModules(ms.factor_weights||[])).slice().sort((a,b)=>finite(b.weight_share)-finite(a.weight_share)).slice(0,12);
      renderTable("moduleWeightsBody",modules,[{render:x=>escapeHtml(String(x.factor_module||"unknown").slice(0,24))},{render:x=>fmtPct(x.weight_share)},{render:x=>String(x.factor_count??0)},{render:x=>fmtPct(x.avg_predicted_return_5d)}],4);
      const factors=(ms.factor_weights||[]).slice().sort((a,b)=>finite(b.weight_share)-finite(a.weight_share)).slice(0,18);
      renderTable("factorWeightsBody",factors,[{render:x=>escapeHtml(String(x.factor_module||"unknown").slice(0,18))},{render:x=>escapeHtml(String(x.factor_role||"entry_alpha").slice(0,18))},{render:x=>escapeHtml(String(x.model_name||"").slice(0,28))},{render:x=>fmtNum(x.weight,2)},{render:x=>fmtPct(x.weight_share)},{render:x=>`${finite(x.weight_delta)>=0?"+":""}${fmtNum(x.weight_delta,3)}`,tone:x=>tone(finite(x.weight_delta))},{render:x=>fmtPct(x.avg_predicted_return_5d)},{render:x=>escapeHtml(String(x.weight_explanation||"").slice(0,42))}],8);
      const lifecycle=(ms.holding_lifecycle_preview||[]).slice(0,14);
      renderTable("lifecycleBody",lifecycle,[{render:x=>escapeHtml(x.symbol)},{render:x=>escapeHtml(x.entry_date||"--")},{render:x=>fmtPct(x.unrealized_return),tone:x=>tone(finite(x.unrealized_return))},{render:x=>fmtPct(x.mfe)},{render:x=>fmtPct(x.mae)},{render:x=>fmtPct(x.giveback_from_peak)},{render:x=>fmtNum(x.trend_direction_score,2)},{render:x=>fmtNum(x.peak_decay_score,2)},{render:x=>fmtNum(x.future_loss_risk_score,2)},{render:x=>escapeHtml(x.position_state||"--")},{render:x=>escapeHtml(x.position_exit_reason||(x.profit_giveback_flag?"利润回吐":x.post_entry_failure_flag?"入场失败":"正常"))}],11);
      const candidates=[`候选股票前列（${ms.candidate_count??0}）`,"","代码       分数    矩阵    状态        5日预期   拦截原因"];
      for(const x of ms.candidate_preview||[]) candidates.push(`${String(x.symbol||"").padEnd(10)} ${fmtNum(x.primary_score,3).padStart(6)} ${fmtNum(x.entry_matrix_score,2).padStart(6)} ${String(x.position_state||"--").slice(0,10).padEnd(10)} ${fmtPct(finite(x.expected_return_5d)).padStart(9)} ${String(x.entry_block_reason||x.add_block_reason||"").slice(0,24)}`);
      if((ms.confirmed_preview||[]).length){candidates.push("","已确认候选","代码       分数    矩阵    状态        5日预期");for(const x of ms.confirmed_preview)candidates.push(`${String(x.symbol||"").padEnd(10)} ${fmtNum(x.primary_score,3).padStart(6)} ${fmtNum(x.entry_matrix_score,2).padStart(6)} ${String(x.position_state||"confirmed").slice(0,10).padEnd(10)} ${fmtPct(finite(x.expected_return_5d)).padStart(9)}`);}
      if(!(ms.candidate_preview||[]).length)candidates.push("暂无候选预览"); document.getElementById("candidatesText").textContent=candidates.join("\n");
      const orders=["最新计划订单",""];for(const x of ms.order_preview||[])orders.push(`${String(x.side||"").toUpperCase().padEnd(5)} ${String(x.symbol||"").padEnd(10)} ${fmtPct(finite(x.delta_weight)).padStart(9)}  P=${x.priority??""}  ${x.reason||""}`);if(!(ms.order_preview||[]).length)orders.push("本次刷新没有新订单");document.getElementById("ordersText").textContent=orders.join("\n");
      const pending=[`未完成订单（${ms.pending_order_count??0}）`,""];for(const x of ms.pending_preview||[])pending.push(`${String(x.side||"").toUpperCase().padEnd(5)} ${String(x.symbol||"").padEnd(10)} shares=${fmtNum(x.remaining_shares,0).padStart(8)} ${String(x.status||"").padEnd(14)} ${x.reason||""}`);if(!(ms.pending_preview||[]).length)pending.push("暂无未完成订单");document.getElementById("pendingText").textContent=pending.join("\n");
      document.getElementById("orderReasonText").textContent=summaryLines(ms.order_reason_summary,"暂无计划订单").join("\n");
      window.latestHoldingPaths=ms.holding_price_paths||[];
    }
    function hydrateChartHistory(rows){
      const restored=[];let peak=0,previousNav=0,validInvestedNav=1;
      for(const row of rows||[]){
        const date=String(row.date||"").slice(0,10),dayIndex=finite(row.day_index,-1);
        const navAmount=finite(row.nav,initialNav),navMultiple=normalizeNav(row.account_net_value,navAmount/initialNav),nav=navMultiple*initialNav;
        const benchmarkNav=normalizeNav(row.benchmark_nav,1),excessNav=normalizeNav(row.excess_net_value,navMultiple/Math.max(benchmarkNav,1e-12));
        const actualExposure=finite(row.actual_exposure),latestRet=previousNav>0?nav/previousNav-1:0,investedRet=actualExposure>=.05?latestRet/actualExposure:0;
        validInvestedNav*=1+investedRet;peak=Math.max(peak,nav);
        restored.push({key:`${dayIndex}|${date}`,date,nav,navMultiple,benchmarkNav,excessNav,drawdown:peak>0?nav/peak-1:0,cash:finite(row.cash),invested:finite(row.invested_value),actualExposure,validInvestedNav});
        previousNav=nav;
      }
      return restored.slice(-1200);
    }
    function renderState(payload){
      let command=String(payload.command||"update").toLowerCase();const stageCommand=command==="stage",finishCommand=command==="finish";
      if(command==="session"){activeRunId=String(payload.run_id||"");totalDays=Math.max(finite(payload.total_days,1),1);initialNav=Math.max(finite(payload.initial_nav,1),1e-12);history=[];factorHistory=[];moduleHistory=[];lastProgressPct=0;document.getElementById("runTitle").textContent=payload.title||"治理运行";document.title=payload.title||"治理实时监控";setStatus("准备运行",0,"session");drawAllCharts();return;}
      if(payload.title){document.getElementById("runTitle").textContent=payload.title;document.title=payload.title;}
      if((stageCommand||finishCommand)&&payload.exposure)command="update";
      else if(stageCommand){const progress=Math.max(lastProgressPct,Math.min(Math.max(finite(payload.progress_pct),0),100));setStatus(payload.message||payload.step||"准备数据",progress,payload.detail||payload.step||"");return;}
      else if(finishCommand){if(Array.isArray(payload.chart_history)&&payload.chart_history.length)history=hydrateChartHistory(payload.chart_history);setStatus(payload.message||"运行完成",Math.max(lastProgressPct,finite(payload.progress_pct,100)),"complete");document.getElementById("statusDot").style.background="#82d5b1";drawAllCharts();return;}
      if(command==="close"){setStatus("监控已关闭",lastProgressPct,"closed");return;}
      if(command!=="update")return;
      const runId=String(payload.run_id||"");if(runId&&runId!==activeRunId){activeRunId=runId;history=[];factorHistory=[];moduleHistory=[];}
      totalDays=Math.max(finite(payload.total_days,totalDays),1);initialNav=Math.max(finite(payload.initial_nav,initialNav),1e-12);
      const exposure=payload.exposure||{},ms=payload.monitor_state||{},holdings=payload.holdings||[],dayIndex=finite(payload.day_index);
      if(Array.isArray(payload.chart_history)&&payload.chart_history.length)history=hydrateChartHistory(payload.chart_history);
      const navAmount=finite(exposure.liquidatable_nav||exposure.nominal_nav,initialNav),navMultiple=normalizeNav(ms.account_net_value,navAmount/initialNav),nav=navMultiple*initialNav;if(!(navMultiple>0))return;
      const dateKey=String(payload.date||"").slice(0,10),pointKey=`${dayIndex}|${dateKey}`,hasCurrent=history.length&&history[history.length-1].key===pointKey,priorHistory=hasCurrent?history.slice(0,-1):history;
      const previousPeak=priorHistory.length?Math.max(...priorHistory.map(x=>x.nav)):nav,peak=Math.max(previousPeak,nav),drawdown=nav/peak-1;
      const benchmarkNav=normalizeNav(ms.benchmark_nav,1),excessNav=normalizeNav(ms.excess_net_value,navMultiple/Math.max(benchmarkNav,1e-12));
      const actualExposure=finite(exposure.actual_exposure||ms.actual_exposure),targetExposure=finite(ms.target_exposure),exposureGap=finite(ms.exposure_gap,Math.max(targetExposure-actualExposure,0));
      const latestRet=priorHistory.length&&priorHistory[priorHistory.length-1].nav>0?nav/priorHistory[priorHistory.length-1].nav-1:0,investedRet=actualExposure>=.05?latestRet/actualExposure:0,previousInvested=priorHistory.length?finite(priorHistory[priorHistory.length-1].validInvestedNav,1):1;
      const currentPoint={key:pointKey,date:dateKey,nav,navMultiple,benchmarkNav,excessNav,drawdown,cash:finite(exposure.cash),invested:finite(exposure.invested_value),actualExposure,validInvestedNav:previousInvested*(1+investedRet)};if(hasCurrent)history[history.length-1]=currentPoint;else history.push(currentPoint);if(history.length>1200)history=history.slice(-1200);
      const factorPoint={key:pointKey,date:dateKey,weights:ms.factor_weights||[]},modulePoint={key:pointKey,date:dateKey,weights:aggregateModules(ms.factor_weights||[])};if(factorHistory.length&&factorHistory[factorHistory.length-1].key===pointKey)factorHistory[factorHistory.length-1]=factorPoint;else factorHistory.push(factorPoint);if(moduleHistory.length&&moduleHistory[moduleHistory.length-1].key===pointKey)moduleHistory[moduleHistory.length-1]=modulePoint;else moduleHistory.push(modulePoint);if(factorHistory.length>1200)factorHistory=factorHistory.slice(-1200);if(moduleHistory.length>1200)moduleHistory=moduleHistory.slice(-1200);
      const returns=history.slice(1).map((x,i)=>x.nav/history[i].nav-1),mean=returns.length?returns.reduce((a,b)=>a+b,0)/returns.length:0,sd=returns.length>1?Math.sqrt(returns.reduce((a,b)=>a+(b-mean)**2,0)/returns.length):0;
      const totalReturn=navMultiple-1,maxDrawdown=Math.min(...history.map(x=>x.drawdown)),annualVol=sd*Math.sqrt(252),sharpe=sd>1e-12?mean/sd*Math.sqrt(252):NaN,sortino=annualizedSortino(returns,navMultiple,history.length),cashDrag=investedRet-latestRet;
      const seriesDrawdown=values=>Math.min(...values.map((v,i)=>v/Math.max(...values.slice(0,i+1))-1));
      const grossProfit=finite(ms.gross_profit),grossLoss=finite(ms.gross_loss),profitFactor=Math.abs(grossLoss)<=1e-12&&grossProfit>0?"∞":fmtNum(ms.profit_factor,2);
      const metrics={total_return:[fmtPct(totalReturn),totalReturn],nav:[fmtNum(navMultiple,4),totalReturn],excess_nav:[fmtNum(excessNav,4),excessNav-1],current_drawdown:[fmtPct(drawdown),drawdown],account_max_drawdown:[fmtPct(maxDrawdown),maxDrawdown],holding_max_drawdown:[fmtPct(seriesDrawdown(history.map(x=>x.validInvestedNav))),-1],benchmark_max_drawdown:[fmtPct(seriesDrawdown(history.map(x=>x.benchmarkNav))),-1],excess_max_drawdown:[fmtPct(seriesDrawdown(history.map(x=>x.excessNav))),-1],benchmark_nav:[fmtNum(benchmarkNav,4),benchmarkNav-1],valid_invested_nav:[fmtNum(history[history.length-1].validInvestedNav,4),history[history.length-1].validInvestedNav-1],sharpe:[fmtNum(sharpe,2),sharpe],sortino:[fmtNum(sortino,2),sortino],annual_volatility:[fmtPct(annualVol),-annualVol],cash:[fmtMoney(exposure.cash),0],cash_drag:[fmtPct(cashDrag),-cashDrag],holdings:[String(exposure.holding_count??0),0],risk_level:[String(ms.risk_level||"--").toUpperCase(),String(ms.risk_level||"").toLowerCase()==="normal"?1:-1],exposure_cap:[fmtPct(finite(ms.exposure_cap)),-finite(ms.exposure_cap)],target_exposure:[fmtPct(targetExposure),targetExposure],actual_exposure:[fmtPct(actualExposure),actualExposure],exposure_gap:[fmtPct(exposureGap),-exposureGap],idle_cash_ratio:[fmtPct(finite(ms.idle_cash_ratio)),-finite(ms.idle_cash_ratio)],target_holding_count:[String(ms.target_holding_count??0),0],holding_shortfall_count:[String(ms.holding_shortfall_count??0),-finite(ms.holding_shortfall_count)],tail_risk_proxy_mean:[fmtNum(ms.tail_risk_proxy_mean,3),.5-finite(ms.tail_risk_proxy_mean)],future_loss_risk_score_mean:[fmtNum(ms.future_loss_risk_score_mean,3),.5-finite(ms.future_loss_risk_score_mean)],downtrend_decay_count:[String(ms.downtrend_decay_count??0),-finite(ms.downtrend_decay_count)],lifecycle_alerts:[String(ms.lifecycle_alert_count??0),-finite(ms.lifecycle_alert_count)],candidate_count:[String(ms.candidate_count??0),0],confirmed_count:[String(ms.entry_confirmed_count??0),finite(ms.entry_confirmed_count)],order_count:[String(ms.order_count??0),0],pending_orders:[String(ms.pending_order_count??0),-finite(ms.pending_order_count)],buy_accuracy_5d:[fmtPct(finite(ms.trailing_buy_accuracy_5d,NaN)),finite(ms.trailing_buy_accuracy_5d)-.5],sell_accuracy_5d:[fmtPct(finite(ms.trailing_sell_accuracy_5d,NaN)),finite(ms.trailing_sell_accuracy_5d)-.5],closed_trade_win_rate:[fmtPct(finite(ms.closed_trade_win_rate,NaN)),finite(ms.closed_trade_win_rate)-.5],realized_pnl:[fmtMoney(ms.realized_pnl),finite(ms.realized_pnl)],gross_profit:[fmtMoney(grossProfit),grossProfit],gross_loss:[fmtMoney(grossLoss),grossLoss],profit_factor:[profitFactor,profitFactor==="∞"?1:finite(ms.profit_factor)-1],control_exit_count:[String(ms.control_exit_count??0),0],retail_lot_cash_insufficient_count:[String(ms.retail_lot_cash_insufficient_count??0),-finite(ms.retail_lot_cash_insufficient_count)],retail_state_block_count:[String(ms.retail_state_block_count??0),-finite(ms.retail_state_block_count)],surge_candidate_count:[String(ms.surge_candidate_count??0),finite(ms.surge_candidate_count)],strong_starter_count:[String(ms.strong_starter_count??0),finite(ms.strong_starter_count)],exhaustion_block_count:[String(ms.exhaustion_block_count??0),-finite(ms.exhaustion_block_count)],protecting_profit_count:[String(ms.protecting_profit_count??0),finite(ms.protecting_profit_count)]};
      Object.entries(metrics).forEach(([key,value])=>setMetric(key,value[0],value[1]));
      const parityMetrics={
        retail_upgraded_to_one_lot_count:[String(ms.retail_upgraded_to_one_lot_count??0),finite(ms.retail_upgraded_to_one_lot_count)],
        starter_2_lot_count:[String(ms.starter_2_lot_count??0),finite(ms.starter_2_lot_count)],diversify_1_lot_count:[String(ms.diversify_1_lot_count??0),finite(ms.diversify_1_lot_count)],
        empirical_distribution_score_mean:[fmtNum(ms.empirical_distribution_score_mean,3),finite(ms.empirical_distribution_score_mean)-.5],trend_direction_score_mean:[fmtNum(ms.trend_direction_score_mean,3),finite(ms.trend_direction_score_mean)-.5],
        peak_decay_score_mean:[fmtNum(ms.peak_decay_score_mean,3),.5-finite(ms.peak_decay_score_mean)],defensive_eligible_count:[String(ms.defensive_eligible_count??0),finite(ms.defensive_eligible_count)],
        buy_sell_conflict_cooldown_days:[String(ms.buy_sell_conflict_cooldown_days??0),-finite(ms.buy_sell_conflict_cooldown_days)],control_avoided_loss:[fmtMoney(ms.avoided_loss_to_window_low),finite(ms.avoided_loss_to_window_low)],
        hard_stop_avoided_loss:[fmtMoney(ms.hard_stop_avoided_loss_to_window_low),finite(ms.hard_stop_avoided_loss_to_window_low)],alpha_collapse_avoided_loss:[fmtMoney(ms.alpha_collapse_avoided_loss_to_window_low),finite(ms.alpha_collapse_avoided_loss_to_window_low)],
        safety_deleveraging_avoided_loss:[fmtMoney(ms.safety_deleveraging_avoided_loss_to_window_low),finite(ms.safety_deleveraging_avoided_loss_to_window_low)],
      };Object.entries(parityMetrics).forEach(([key,value])=>setMetric(key,value[0],value[1]));
      const progress=Number.isFinite(Number(payload.progress_pct))?finite(payload.progress_pct):Math.min((dayIndex+1)/totalDays*100,100);setStatus(String(payload.date||"").slice(0,10),progress,`${dayIndex+1} / ${totalDays} 个交易日`);document.getElementById("asOfDate").textContent=String(payload.date||"").slice(0,10);
      document.getElementById("accountSummary").innerHTML=[["账户资产",fmtMoney(nav)],["现金",fmtMoney(exposure.cash)],["已投入市值",fmtMoney(exposure.invested_value)],["风险等级",String(ms.risk_level||"--").toUpperCase()],["计划订单",String(ms.order_count??0)],["未完成订单",String(ms.pending_order_count??0)]].map(x=>`<dt>${x[0]}</dt><dd>${x[1]}</dd>`).join("");
      document.getElementById("actualExposureLabel").textContent=fmtPct(actualExposure);document.getElementById("actualExposureBar").style.width=`${Math.min(Math.max(actualExposure*100,0),100)}%`;document.getElementById("targetExposureLabel").textContent=fmtPct(targetExposure);document.getElementById("targetExposureBar").style.width=`${Math.min(Math.max(targetExposure*100,0),100)}%`;
      updateReports(exposure,ms,{navMultiple,totalReturn,benchmarkNav,excessNav,maxDrawdown,actualExposure,targetExposure,exposureGap,cashDrag});renderOperational(exposure,ms,holdings,nav);drawAllCharts();
      if(stageCommand){const progress=Math.max(lastProgressPct,Math.min(Math.max(finite(payload.progress_pct),0),100));setStatus(payload.message||payload.step||"准备数据",progress,payload.detail||payload.step||"");}
      if(finishCommand){setStatus(payload.message||"运行完成",Math.max(lastProgressPct,finite(payload.progress_pct,100)),"complete");document.getElementById("statusDot").style.background="#82d5b1";}
    }
    function setStatus(message,progress,detail){lastProgressPct=Math.max(0,Math.min(finite(progress),100));document.getElementById("status").textContent=message||"运行中";document.getElementById("runDetail").textContent=`${lastProgressPct.toFixed(1)}% · ${detail||""}`;document.getElementById("progressBar").style.width=`${lastProgressPct}%`;}
    async function poll(){try{const response=await fetch(`/state?ts=${Date.now()}`,{cache:"no-store"});if(response.ok)renderState(await response.json());else setStatus("状态接口异常",lastProgressPct,`HTTP ${response.status}`);}catch(error){setStatus("监控连接中断",lastProgressPct,String(error));document.getElementById("statusDot").style.background="#bd3d39";}setTimeout(poll,1000);}
    buildStaticUi(); drawAllCharts(); poll();
  </script>
</body>
</html>
"""
