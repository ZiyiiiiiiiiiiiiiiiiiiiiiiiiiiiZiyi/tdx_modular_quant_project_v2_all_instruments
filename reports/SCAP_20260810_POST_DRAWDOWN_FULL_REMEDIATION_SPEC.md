# SCAP 2026-03 后回撤完整修复规格

状态：`plan_frozen_awaiting_implementation`

日期：2026-08-10

依据：`run20260809_214739`、`SCAP_20260810_RUN20260809_214739_POST_20260308_ANALYSIS.md`、WBS-08.19/10/11/13/14/15/16，以及现有容量、状态语义、因子 OOS、买入质量和 Web 产品。

## 1. 决策与边界

本方案不重新修改已经完成的容量—持仓合同，也不把 2026-03—05 的 development 窗口当作调参后的盈利证明。修复目标只有四个：

1. 退出信号的“检测、纸面、控制开关、交易授权、订单、成交”语义完全一致。
2. 市场冲击解除后，仓位恢复必须同时尊重短期风险、长期水下状态和恢复滞回，不允许单靠 5 日信号瞬间恢复常态部署。
3. 校准缺失或漂移时，C 级 fallback 不能用低证据正分绕过统一净效用和模型权威。
4. 状态—因子证据必须使用已有全宇宙滚动 OOS 产品，并进入标准保存、API、Web 和研究门；条件候选统计永远不直接取得交易权。

本方案只冻结设计。没有实施交易公式、没有启动新回测、没有改变研究门或生产门；两门继续 `blocked`。

## 2. 已有实现复用与禁止重复建设

| 能力 | 当前状态 | 本方案处理 |
|---|---|---|
| `PortfolioSizingIntent`、权限后可达性、持仓数曲线 | 已实现并通过 20 日工程验收 | 保留，不改分仓公式 |
| `market_state_semantics.py` 的安全/overlay/基准权限分离 | 已实现 | 作为新状态向量的语义入口 |
| `regime_factor_diagnostics.py` | 已实现只读条件 IC/IR、Newey-West、BH-FDR | 接入标准保存和 Web，不重写统计器 |
| `full_universe_factor_oos.py` | 已实现 126 日训练、20 日 embargo、月度滚动 OOS | 作为唯一可进入研究门的状态—家族证据 |
| `buy_quality_diagnostics.py` | 已实现候选→提案→计划→订单→成交→交易配对 | 扩展权威字段，不另建第二条事实链 |
| `governance_action_proposal_ledger.csv`、唯一 ActionPlan | 已实现 | 新质量权限和状态授权只作为提案/计划输入 |
| `/state`、`/api/sizing-contract`、`/api/sizing-export`、因子页 | 已实现 | 保持兼容，新增只读端点 |
| 绩效基准与安全代理分离 | 已实现语义 | 新增机会集/风格匹配基准，不混用安全代理 |

禁止事项：不新增第二个优化器；不在执行层二次软否决；不把研究基准直接拿来控制仓位；不把安全 ETF 用作选股因子；不把缺失状态填成 neutral；不把 `drifted` 伪装成 calibrated；不在线修改生产阈值。

## 3. 目标调用链

```text
t 日 PIT 数据
  → BenchmarkBundle（四类基准，各自独立权限）
  → MarketStateVector（短期冲击 + 长期结构 + 恢复状态）
  → ExposureAuthorization（唯一部署上限）
  → EntryEvidenceSnapshot / ExitSignalObservation
  → EntryQualityAuthority / ExitAuthorityDecision
  → ActionProposal（仍无交易权）
  → 唯一整数 ActionPlan
  → 订单 / T+1 成交 / 会计
  → 事实账本 + 反事实账本 + 标准保存产品
  → ResearchGate → ProductionGate
```

所有新合同使用 `decision_id + decision_date + runtime_identity_hash + schema_version`，并且 `as_of_date <= decision_date`。任何 forward outcome 只能在保存后研究产品中出现，禁止进入当日决策对象。

## 4. 接口与数据模型

### 4.1 `BenchmarkBundle`

新增到 `contracts.py`，冻结为不可变对象：

```python
@dataclass(frozen=True)
class BenchmarkLeg:
    benchmark_id: str
    role: str                  # performance_primary/opportunity_set/style_matched/safety_proxy
    as_of_date: pd.Timestamp
    constituent_rule: str
    weighting_rule: str
    rebalance_rule: str
    return_valid: bool
    coverage_ratio: float
    degraded_reasons: tuple[str, ...]
    authority: str             # attribution_only/safety_cap_input/research_only

@dataclass(frozen=True)
class BenchmarkBundle:
    contract_id: str
    performance_primary: BenchmarkLeg
    opportunity_set: BenchmarkLeg
    style_matched: BenchmarkLeg
    safety_proxy: BenchmarkLeg
```

- `performance_primary`：保留当前前期流动性前 100 等权研究基准，继续用于长期绩效展示。
- `opportunity_set`：使用策略当日可投池的前期固定成分等权，衡量“是否错过可投资机会”。
- `style_matched`：按板块、流动性分位、规模代理和论点族在再平衡日前匹配，权重在周期内固定；匹配失败时 `degraded`，不得静默回退为业绩基准。
- `safety_proxy`：继续使用 sh510300 及现有严格回退链，只能进入安全上限。

### 4.2 `MarketStateVector`

替代把多个状态压成一个 `risk_level` 的使用方式，但保留旧字段双写：

```python
@dataclass(frozen=True)
class MarketStateVector:
    contract_id: str
    decision_date: pd.Timestamp
    safety_proxy_id: str
    fast_shock_state: str          # normal/warning/high/crisis/unknown
    structural_state: str          # bull/neutral/weak/bear/unknown
    recovery_state: str            # blocked/stabilizing/step1/step2/open/unknown
    fast_state_streak: int
    structural_state_streak: int
    recovery_streak: int
    return_5d: float | None
    return_20d: float | None
    drawdown_5d: float | None
    drawdown_20d: float | None
    underwater_from_peak: float | None
    liquidity_stress: float | None
    hard_safety_cap: float
    structural_multiplier: float
    recovery_cap: float
    effective_deployment_cap: float
    data_quality_state: str
    blocked_reasons: tuple[str, ...]
```

有效部署上限只在一个地方计算：

```text
structural_cap = base_policy_target × structural_multiplier
effective_deployment_cap
  = min(hard_safety_cap, structural_cap, recovery_cap, sizing_attainable_cap)
```

不再把 0.85 之类的结构预算作为高于 0.75 常态目标的无效绝对上限。结构参数解释为相对 `base_policy_target` 的乘数。

恢复状态机：

- `blocked`：fast state 为 high/crisis，或安全硬冻结；禁止增加总暴露。
- `stabilizing`：fast 冲击解除但 20 日收益仍负、或 underwater 仍越过 neutral 阈值；只允许减仓、持有和原子替换，不允许净增暴露。
- `step1/step2`：长期状态连续改善后分阶梯恢复；每日有效上限最多增加一个预注册步长。
- `open`：fast 与 structural 均满足恢复条件且连续确认完成。
- 任一状态恶化立即降级，不要求对称等待；恢复比降级慢。

具体确认日数、步长和乘数不从本次 338 日择优。批次 2 同时输出固定候选网格，批次 3 在 development 窗预注册比较后才冻结候选；正式生产仍需未触碰 OOS。

### 4.3 `ExitSignalObservation` 与 `ExitAuthorityDecision`

在 `position_lifecycle.py` 与 `decision_arbitration.py` 之间新增显式合同：

```python
@dataclass(frozen=True)
class ExitSignalObservation:
    decision_id: str
    symbol: str
    signal_type: str
    detected: bool
    detected_score: float | None
    first_detected_date: pd.Timestamp | None
    consecutive_count: int
    confirmation_required: int
    paper_active: bool
    control_enabled: bool
    evidence_as_of_date: pd.Timestamp
    data_quality_state: str

@dataclass(frozen=True)
class ExitAuthorityDecision:
    observation_id: str
    authority_active: bool
    selected_exit_reason: str | None
    veto_reasons: tuple[str, ...]
    superseded_by: str | None
    intended_exit_fraction: float
    earliest_execution_date: pd.Timestamp | None
    authority_contract_version: str
```

统一真值关系：

```text
authority_active
  = detected
  AND paper_active
  AND control_enabled
  AND confirmation_passed
  AND not vetoed
  AND not superseded_by_higher_authorized_reason
```

旧 `post_entry_failure_exit` 字段只做兼容，值必须等于 `authority_active`；新增 `paper_post_entry_failure_exit` 保存观察信号。禁止再以 raw signal 与 control flag 的简单 AND 命名为 exit。

退出模型分三层：

1. 硬安全/不可逆会计事实：保持现有高优先级交易授权。
2. signal/thesis/loss containment：保持当前 E 阶段授权和确认合同。
3. post-entry failure：批次 1 只修审计；批次 2 生成三种 shadow policy；批次 3 才允许一个预注册候选进入交易消融。

shadow policy 至少比较：连续确认、最低持有期、相对安全代理恶化、成交成本、卖后 5/10/20 日反事实。不能把检测到失败简单等同下一日全平。

### 4.4 `EntryEvidenceSnapshot` 与 `EntryQualityAuthority`

```python
@dataclass(frozen=True)
class EntryEvidenceSnapshot:
    decision_id: str
    symbol: str
    authority_tier: str
    calibration_state: str
    effective_sample_size: float
    unique_session_count: int
    forecast_rank_ic: float | None
    forecast_slope: float | None
    drift_streak: int
    fallback_contract: str | None
    fallback_family: str | None
    fallback_state: str | None
    full_universe_oos_status: str
    evidence_as_of_date: pd.Timestamp

@dataclass(frozen=True)
class EntryQualityAuthority:
    evidence_id: str
    trade_mode: str              # normal/degraded_exploration/shadow_only/blocked
    decision_return: float
    decision_return_basis: str
    maximum_lots: int
    maximum_notional: float
    risk_adjusted_ce_amount: float
    authority_reasons: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
```

统一人民币效用：

```text
CE_i(q)
  = q × notional_lot_i × mu_LCB_i
  - lifecycle_cost_i(q)
  - lambda_ES × incremental_ES_i(q)
  - model_uncertainty_CE_i(q)
  - opportunity_cost_i(q)
```

- 只有 `CE_i(q) > wealth_materiality_epsilon_amount` 才形成正效用提案。
- CVaR/ES 只在组合风险入口扣一次；不得在 proposal、authority penalty 和 optimizer 中重复扣减。
- 固定 15 元 robust hurdle 改为诊断兼容字段；主门槛使用上式和现有财富重要性 epsilon。若保留 15 元，必须明确是 hard gate 或纯 warning，不能同时存在两套模糊权威。
- `calibrated/recovering` 且样本充分：可进入 A/B 正常权限。
- C 级必须同时满足独立 PIT fallback、同家族同状态 full-universe OOS 合格、方向和时间隔离合格；否则 `shadow_only`。
- weak/bear 状态样本不足 30 个交易日、置信区间下界不正、FDR 未过或 OOS 缺失时，C 级不得取得新增暴露权。
- 已有持仓不会因为入场证据降级被强制卖出；退出仍由退出合同决定。

### 4.5 `RegimeFactorEvidence`

复用 `regime_factor_diagnostics.py` 和 `full_universe_factor_oos.py`，新增统一元数据：

```python
@dataclass(frozen=True)
class RegimeFactorEvidence:
    scope: str                  # proposal_conditional/candidate_conditional/full_universe_oos
    factor_or_family: str
    state_dimension: str
    state_label: str
    horizon_days: int
    train_start: pd.Timestamp | None
    train_end: pd.Timestamp | None
    embargo_days: int
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    observed_days: int
    observed_rows: int
    mean_rank_ic: float | None
    ic_ir: float | None
    positive_ic_ratio: float | None
    top_bottom_spread: float | None
    ci95_lower: float | None
    fdr_q_value: float | None
    authority: str             # diagnostic_only/research_eligible/trading_ineligible
    insufficiency_reasons: tuple[str, ...]
```

统计要求：日度横截面 Spearman IC；方向按因子注册表统一；重叠期限使用 Newey-West 或 block bootstrap；同一状态/期限内 BH-FDR；至少输出 5/10/20 日。训练数据必须早于测试月并保留 20 日 embargo。弱势样本不足时写 `insufficient_sample`，不做全状态均值的隐式生产回退。

动态因子权重只作为最后阶段 shadow 候选：

```text
raw_weight_f,s = base_weight_f × exp(eta × zscore(IC_LCB_f,s))
final_weight   = (1-rho) × base_weight + rho × normalized(raw_weight)
```

同时施加家族权重上限、日/月换手上限和 `rho` 上限。任何 winner-take-all 或根据同一 338 日选择最优家族的实现都不允许进入生产。

## 5. 配置与运行身份

新增 capital profile 配置，默认全部为诊断模式：

```python
scap_exit_authority_contract_version = "scap_exit_authority_v2"
scap_post_entry_failure_mode = "diagnostic"       # diagnostic/shadow/trading
scap_market_recovery_contract_version = "scap_market_recovery_v1"
scap_market_recovery_mode = "diagnostic"
scap_entry_quality_contract_version = "scap_entry_quality_v1"
scap_entry_quality_mode = "diagnostic"
scap_regime_factor_contract_version = "scap_regime_factor_oos_v1"
scap_regime_factor_mode = "diagnostic"
scap_benchmark_bundle_version = "scap_benchmark_bundle_v1"
```

所有候选确认日数、恢复步长、结构乘数、`lambda_ES`、最小 OOS 天数、FDR 门槛和动态权重参数必须进入 runtime identity、运行 manifest、摘要和 Web。未知枚举或拼写错误 fail closed；禁止自动回退为 trading。

## 6. 埋点和保存产品

### 6.1 每日组合级

新增 `governance_market_state_ledger.csv`，主键 `decision_id`：四类基准 ID、fast/structural/recovery 状态、状态连续天数、5/20 日收益与回撤、underwater、三类 cap、最终 cap、数据质量和降级原因。

新增 `governance_recovery_episode_ledger.csv`，主键 `recovery_episode_id + decision_date`：事件起点、前一风险峰值、当前阶段、允许暴露增量、实际增量、阻塞原因、重新恶化标志。

### 6.2 股票—退出信号级

新增 `governance_exit_signal_authority_ledger.csv`，主键 `decision_id + symbol + signal_type`，保存两个退出合同的全部字段，并连接 proposal/order/fill ID。

新增 `governance_exit_delay_counterfactual.csv`：检测日至授权日、订单日、成交日的延迟；检测价、授权价、成交净价；若在检测后第一个可执行日退出的 5/10/20 日反事实；实际与反事实成本；`right_censored` 标志。反事实只能诊断，不回写交易。

### 6.3 股票—入场级

扩展 `governance_action_proposal_ledger.csv`，新增 `entry_evidence_id`、`entry_quality_authority_id`、`trade_mode`、`full_universe_oos_status`、`risk_adjusted_ce_amount`、`quality_blocked_reasons`。

新增 `governance_entry_quality_authority.csv`，主键 `decision_id + symbol + lot_count`，保存校准、fallback、OOS、成本、ES、模型不确定性、CE 和最终权限；不得用 0 表示缺失概率。

### 6.4 因子和基准级

把已有派生产品接入标准保存：

- `governance_regime_factor_ic_daily.csv`
- `governance_regime_factor_summary.csv`
- `governance_regime_factor_family_summary.csv`
- `governance_regime_factor_stability.csv`
- `governance_regime_factor_manifest.json`
- `governance_benchmark_bundle.csv`
- `governance_benchmark_attribution.csv`

大表允许放入 `diagnostics/` 子目录，但 artifact manifest 必须记录路径、schema、行数、日期范围、SHA256、scope 和 authority。

### 6.5 运行级告警

新增指标：

- detected 但未授权退出数、平均/中位/P90 授权延迟、延迟损失金额。
- 状态恢复后 1/5/10 日新增暴露、恢复后买入 5/10/20 日命中率。
- drifted/unavailable 候选数、shadow-only 数、被 CE 拦截数、C 级新增暴露。
- 每个状态—家族 OOS 天数、最后训练日、FDR、置信区间和过期天数。
- performance/opportunity/style/safety 四基准的覆盖率与退化状态。

严重告警：字段语义不守恒、authority 为真但无 proposal、订单无法反查授权、forward label 日期不晚于信号日、状态 `unknown` 却取得交易权、full-universe OOS 缺失却标记 research eligible。

## 7. API 合同

所有接口只读；不新增 POST/PUT/PATCH。统一响应：

```json
{
  "status": "ok|pending|partial|legacy_unavailable|failed",
  "schema_version": "...",
  "run_id": "...",
  "as_of": "YYYY-MM-DD",
  "authority": "diagnostic_only|research_only|trading_authority",
  "data_quality": {"state": "complete|degraded|missing", "reasons": []},
  "data": {}
}
```

新增端点：

| 方法与路径 | 参数 | 内容 |
|---|---|---|
| `GET /api/market-state` | `from,to` | 状态向量、恢复 episode、三类上限 |
| `GET /api/benchmarks` | `from,to,role` | 四基准净值、收益、覆盖与角色 |
| `GET /api/exit-authority` | `symbol,from,to,signal_type` | 检测→授权→订单→成交链 |
| `GET /api/entry-quality` | `decision_id,symbol,trade_mode` | 证据、CE、权限和拒绝原因 |
| `GET /api/regime-factors` | `scope,level,state,horizon,metric` | 因子/家族状态统计 |
| `GET /api/gates` | 无 | 工程、研究、生产门和失败项 |
| `GET /api/diagnostic-export` | `product,format=json|csv` | 上述产品导出 |

错误语义：参数非法 400；未知 run/symbol 404；产物尚未完成 202；schema 不兼容 409；核心运行成功但附属诊断失败返回 `partial`，不得把整个回测伪装失败，也不得返回空 200。

保留 `/state`、`/api/sizing-contract`、`/api/sizing-export`。旧 payload 缺字段返回 `null + legacy_unavailable`，禁止填 0。

## 8. Web 页面与交互

风险页维持只读，增加五个区域；已有持仓数曲线不重复创建。

### 8.1 事件总览

- 账户、performance primary、opportunity set、style matched 四条净值及各自回撤。
- 安全 ETF 单独显示在“风险信号”，不与绩效基准混画成收益比较结论。
- 拖拽选择日期区间后，页面统一刷新窗口收益、超额、暴露、持仓和交易质量。
- 点击回撤点，所有面板同步定位到该日期。

### 8.2 市场状态与恢复

- 三行时间轴：fast shock、structural state、recovery state。
- 同图显示 base target、hard safety cap、structural cap、recovery cap、实际暴露。
- tooltip 显示 5/20 日收益、underwater、连续天数、输入基准、数据新鲜度和为何允许/阻止恢复。
- `unknown/degraded` 使用灰色斜纹，不得显示成 neutral。

### 8.3 持仓退出抽屉

- 点击持仓后展示每类信号的 detected、paper、control、confirmed、authorized、veto、order、fill 八阶段时间线。
- 明确显示“检测到但无交易权限”和阻塞原因。
- 可切换实际路径与“首个可执行日退出”反事实；反事实始终标记“事后诊断，不是可实现保证”。

### 8.4 买入质量表

- 列：股票、日期、A/B/C/D、校准状态、样本数、fallback 家族/状态、OOS 状态、mu LCB、成本、增量 ES、模型不确定性、CE、trade mode、最终动作。
- 默认把 `drifted + trading`、`p_win missing`、`CE<=epsilon`、`OOS insufficient` 置顶。
- 点击股票联动持仓路径和因子家族证据；点击 proposal ID 打开只读 JSON。

### 8.5 状态—因子研究页

- scope 必须显式选择：proposal conditional、candidate conditional、full-universe OOS。
- scope 切换时页面顶部始终显示权限徽章；只有 full-universe OOS 可能为 research eligible。
- 热力图维度：状态 × 家族；指标可切 IC、IR、正 IC 比例、spread、CI lower、FDR、样本天数。
- 样本不足格显示 `N不足`，不使用 0 颜色。
- 允许下载当前筛选 CSV/JSON，不允许页面直接“应用权重”。

### 8.6 门控中心

- 工程门、研究门、生产门三张独立卡片。
- 每个失败项显示证据文件、阈值、实际值、最后更新时间、是否改变交易。
- 运行/保存中显示 `pending`；附属产物失败显示 `partial` 和可重试入口，但重试只重建诊断产物。

交互状态写入 URL query，刷新可复现；键盘可访问；所有图表与表格支持空数据、旧 schema、运行中、失败、完整五态；浏览器控制台零错误。

## 9. 保存阶段与故障隔离

在 `_save()` 中调整为：

```text
core ledgers
→ trade pairing
→ exit/entry authority reconciliation
→ benchmark bundle
→ quality reports
→ regime-factor diagnostics（可独立失败）
→ summary/gates
→ Web products
→ holding factor products
```

manifest 分为 `core_complete`、`audit_complete`、`research_products_complete`、`web_complete`。状态—因子或 Excel 失败不能抹掉核心回测，但研究门自动 blocked。每阶段原子写临时文件后重命名，记录最后成功产物和可重试资格。

## 10. 三批次实施方案

### 批次 1：真值合同与埋点，不改变交易

修改：`contracts.py`、`position_lifecycle.py`、`decision_arbitration.py`、`runner.py`、`runner_summary.py`、schema/manifest、专项验证。

- 落地 ExitSignalObservation/ExitAuthorityDecision。
- 修正 `post_entry_failure_exit` 审计语义并双写 legacy 字段。
- 落地 BenchmarkBundle、MarketStateVector，但 mode=`diagnostic`，订单/NAV 必须与 control 逐日一致。
- 新增退出延迟反事实和权威对账。

批次门：静态调用链、单位/时序审查、py_compile、构造测试、旧账本迁移、5 日夹具、2026-03-09 至 04-03 的 20 交易日全保存。audit-only 与 control 的 proposal/plan/order/fill/NAV 必须在排除随机 UUID 后 `1e-12` 一致。

### 批次 2：影子模型、标准产品、API 与 Web，不改变交易

修改：`safety.py`、`market_state_semantics.py`、`scap_v31_authority.py`、`scap_v3_lean.py`、`action_utility.py`、现有 factor/buy-quality 模块、`live_monitor.py`、两个 Web 入口、保存链和验证脚本。

- 计算 recovery shadow cap、post-entry failure shadow exit、EntryQualityAuthority shadow、状态—家族 OOS 权威。
- 把已有 regime factor/full universe OOS/buy quality 接入标准产品。
- 实现全部 GET API、Web 联动与导出。
- 不改变 ActionPlan；shadow proposal 使用独立 ID 和 `diagnostic_only`。

批次门：性质测试、API schema、浏览器视觉/交互、CSV/JSON 勾稽、2026-03 事件 20 日全链；随后做 60 日只读重建，验证延迟损失、恢复路径和状态—因子覆盖。

### 批次 3：受控交易消融与准入，不直接合并最优组合

冻结日期、资金、成本、PIT、因子柜、容量合同和代码指纹，预注册：

1. control。
2. 只启用 post-entry failure 候选。
3. 只启用 recovery hysteresis 候选。
4. 只启用 entry quality fail-closed 候选。
5. 经前三项分别通过后，才测试组合候选。
6. 动态因子权重保持 shadow，除非 full-universe OOS 与多重检验门单独通过。

运行阶梯：5 日构造 → 20 日事件窗 → 60 日 03—05 development → 338 日 development A/B → 不少于 504 日未触碰 OOS 或前瞻 paper。不得用前一级最优结果反复调整同一级窗口。

## 11. 数学、金融与代码静态审查

每批代码完成后，在运行前执行：

- 时序：所有决策输入 `as_of<=decision_date`；成交最早 t+1；forward outcome 不进入决策对象。
- 单位：收益为无量纲，成本/CE/ES 为人民币，权重为 NAV 比例；禁止混加。
- 风险：CVaR/ES 只扣一次；相关/协方差缺失不得填 0；矩阵奇异使用已披露收缩回退。
- 现金：买入名义金额、费用、保留现金、最低佣金、替换净回款守恒。
- 权限：diagnostic/shadow 无订单权；唯一 ActionPlan；执行层只检查硬事实。
- 状态：风险恶化快、恢复慢；unknown 不获得增仓权；安全硬上限始终优先。
- 退出：未授权纸面信号不能遮蔽已授权低优先级退出。
- 统计：样本数按交易日和股票行分别披露；重叠标签使用 HAC/block bootstrap；多重比较校正。
- 基准：成分只使用前期信息；安全代理与绩效归因绝不互换。

## 12. 测试矩阵

新增建议脚本：

- `verify_exit_authority_truth_contract.py`
- `verify_post_entry_failure_audit_reconciliation.py`
- `verify_market_recovery_state_machine.py`
- `verify_market_state_no_trade_shadow_equivalence.py`
- `verify_entry_quality_authority.py`
- `verify_entry_quality_risk_unit_contract.py`
- `verify_regime_factor_standard_products.py`
- `verify_benchmark_bundle_contract.py`
- `verify_scap_diagnostic_api_contract.py`
- `verify_scap_drawdown_web_interactions.py`
- `verify_scap_post_drawdown_20d_output.py`

性质测试：增加成本不得提高 CE；提高 ES 不得扩大订单；减少现金不得增加买单；状态恶化不得提高 recovery cap；unknown 不得优于已知 neutral；关闭交易模式只删除对应动作；audit-only 不改变成交；同一计划重放不重复收费；复制候选不改变既有订单；旧 schema 缺字段保持 null。

## 13. 经济验收指标

主目标仍为成本后期末净利润；安全约束为最大回撤和压力损失预算。必须同时报告：

- 03-11 至 04-03 与 04-01 至 05-29 分段账户/机会集/风格匹配超额。
- post-entry failure 检测至成交延迟、延迟损失、误杀后的 5/10/20 日反弹。
- 新买入 5/10/20 日 gross、成本代理、相对机会集收益，按状态/权限/家族分组。
- PF、已实现/未实现 PnL、换手、成本、持仓数、实际暴露、现金拖累。
- 状态恢复后新增暴露的收益与尾部损失。
- block bootstrap 区间、有效样本、多重比较校正和 development/OOS 标签。

任何候选若只靠降低仓位改善回撤、却显著恶化成本后净利润或反弹捕获，不自动通过；任何候选若只在本次 338 日改善，也不取得生产权。

## 14. 迁移、回滚和发布

- schema 版本升级但旧字段双写至少一个发布周期；legacy 值由新权威字段派生。
- 新模式默认 diagnostic，合并工程代码不会改变交易。
- 批次 1、2、3 分支和提交独立；策略权变更不得与 Web/报告修复混提交。
- 回滚只关闭对应 mode，不删除新账本；运行身份仍保留模式和合同版本。
- 不删除原 run、失败 run 或派生证据；所有新长窗写新目录。

## 15. 最终完成定义

工程完成：合同、账本、API、Web、保存、兼容、故障隔离和 20 日事件窗全部通过，且 diagnostic 模式逐日等价。

研究完成：单变量消融、全宇宙滚动 OOS、统计功效、多重比较、成本/压力、未平仓和反事实均通过。

生产完成：不少于 504 个未被方案选择污染的 OOS 交易日或等价前瞻 paper、独立复现包、正式 PIT/公司行动/税务/可投资基准和生产门全部通过。

在此之前，正确状态始终是：工程方案可实施，研究门 `blocked`，生产门 `blocked`。
