# SCAP 容量—仓位—执行闭环完整修复规格

日期：2026-08-09
状态：`implemented_20d_engineering_verified_long_window_gates_pending`
交易权限：无；本文只冻结接口、公式、埋点、交互、迁移与验收，不修改交易逻辑。
关联：`QUANT_SYSTEM_WBS.md`、`SCAP_20260804_INTERFACE_LEVEL_IMPROVEMENT_PLAN.md`、`SCAP_20260805_338D_DIAGNOSTIC_FIX_AND_REGIME_REDESIGN_PLAN.md`、`SCAP_20260805_338D_IMPLEMENTATION_AND_EVIDENCE_REPORT.md`。

## 1. 结论与修复边界

当前最高优先级不是重新调因子或放宽买入标准，而是修复仓位尺度合同。正式 82 日资本矩阵已经证明：20k/50k/100k/200k 的 `sizing_reference_positions` 中位数约为 6/16/32/32，但政策目标与实际平均持仓约为 6；`runner.py` 又使用 `preliminary_risk_cap * NAV / sizing_reference_positions` 生成 `target_position_cash`，再由 `scap_v31_authority.py` 的 A/B/C 乘数生成最大手数。资金越大，分母越大，单票授权越薄；盈利加仓交易权关闭时，“starter size”事实上成为最终仓位上限，导致 50k 以上 82/82 日条件暴露下界违约。

修复必须同时满足：

1. 容量只描述上限，不能充当政策目标或分仓分母；
2. 原始政策、条件可行边界、最终整数计划、订单和成交各有唯一字段与唯一生产者；
3. A/B/C/D 权威只表达证据和风险许可，不能在没有后续加仓路径时伪称“初始仓”；
4. 条件下界可行时，优化器必须满足；不可行时不强买负效用股票，并完整记录原因；
5. 执行层只验证硬事实，不重新解释软目标；
6. 资金规模变化不能仅因一个“可容纳名称数”分母而机械压低仓位；收益不要求随资金单调，但差异必须能由价格、整手、候选、成本、风险或执行事实解释；
7. 旧 338 日窗口已参与诊断和方案选择，只能作为 development/audit；生产准入仍需不少于 504 个正式 OOS 交易日及现有研究门条件。

本次不把“大盘状态因子选择”“买入 alpha 改造”“盈利加仓开启”混进同一交易实验。它们保留为后续独立消融，避免同时改变多个变量后无法归因。

## 2. 已核对的现状接口与错误链

### 2.1 当前生产链

```text
capital_scaling.resolve_position_capacity()
  -> PositionCapacity.sizing_reference_positions
  -> runner.scaled_position_weight_caps(effective_position_cap=reference)
  -> runner.attach_scap_v31_authority(
       target_position_cash=risk_cap * NAV / reference)
  -> scap_v31_authority._scaled_max_lots()
  -> candidate.scap_v31_max_lots
  -> scap_v3_lean.resolve_conditional_deployment_bounds()
  -> integer_action_optimizer.optimize_action_proposals()
  -> ActionPlan.target_lots_by_symbol
  -> pending/order/fill
  -> exposure ledger / summary / Web
```

### 2.2 明确的语义冲突

- `PositionCapacity` 注释把 `sizing_reference_positions` 视为报告参考，不是最低约束；`runner.py` 却把它用于单仓资金和动态单名上限，已经取得交易权。
- `PolicyBand.holding_target` 是约 6 只的产品目标；优化器消费它，但候选的 `scap_v31_max_lots` 已在更早阶段按 16/32 只分仓削薄，后端无法恢复。
- `entry_authority_role=evidence_discount_and_starter_size_only` 与实际权限不一致：盈利加仓关闭时，没有从 starter 到 final 的可达交易路径。
- 当前有 `DeploymentBounds` 和 `exposure_floor_violation`，但上游逐股票最大手数已经可能把可达暴露压低；报告发现违约，不能修复违约。
- Web 当前显示“经济容量/估仓位数”，容易把容量、目标和实际混为一个概念，也没有展示授权最大可达暴露与每层缺口。

## 3. 目标架构：七层不可变合同

```text
PortfolioFacts
  -> PolicyBand
  -> TradeCapacity
  -> PortfolioSizingIntent
  -> EntrySizingEnvelope[]
  -> DeploymentBounds + OptimizerConstraints/Preferences
  -> ActionPlan
  -> Order/Fill Reconciliation
```

每层只能收紧下游硬边界，不能回写上游事实或政策。每个对象包含 `contract_version`、`decision_id`、`source_snapshot_id` 和内容哈希。裸字段 `target_exposure`、`target_positions`、`position_cap` 在跨模块接口中逐步弃用。

## 4. 接口级修改

### 4.1 `PortfolioFacts`：当日事实快照

建议位置：`functions/decision_council/portfolio_constraint_contract.py`。

```python
@dataclass(frozen=True)
class PortfolioFacts:
    decision_id: str
    decision_date: pd.Timestamp
    nav_amount: float
    cash_amount: float
    invested_amount: float
    actual_exposure: float
    actual_holding_count: int
    current_lots_by_symbol: Mapping[str, int]
    cash_buffer_amount: float
    lot_size: int
    market_rule_snapshot_id: str
    fee_profile_id: str
    contract_version: str
```

不允许包含政策目标、搜索宽度或模型分数。校验：金额/比例 finite、NAV>0、现金及手数非负、`cash + marked_positions = NAV` 在容差内守恒。

### 4.2 `TradeCapacity`：仅保留金融上限

将 `PositionCapacity` 逐步更名为 `TradeCapacity`；第一阶段保留兼容适配器，不直接删除旧字段。

```python
@dataclass(frozen=True)
class TradeCapacity:
    mode: str
    user_hard_position_cap: int | None
    product_hard_position_cap: int
    search_cap: int
    eligible_symbol_count: int
    affordable_new_name_cap: int
    economic_order_new_name_cap: int
    effective_hard_holding_ceiling: int
    spendable_cash_amount: float
    risk_room_amount: float
    minimum_economic_order_amount: float
    median_one_lot_amount: float | None
    grandfathered_excess_names: int
    binding_reasons: tuple[str, ...]
    capacity_state: str
    contract_version: str
```

规则：

- `search_cap` 只控制计算量，永远不进入资金分配公式；
- `effective_hard_holding_ceiling` 是上限，不是目标；
- 旧 `sizing_reference_positions` 只以 `legacy_sizing_reference_positions` 影子落盘，禁止被交易模块读取；
- 当前用经济现金容量冒充 `risk_feasible_position_cap` 的字段弃用。真正风险容量缺失时返回 `unavailable`，不能填一个看似精确的数字。

### 4.3 `PolicyBand`：保留原始政策，不被可行性回写

沿用现有结构，补齐 `holding_ceiling` 和来源字段：

```python
PolicyBand(
    state,
    holding_floor,
    holding_target,
    holding_ceiling,
    exposure_lower,
    exposure_target,
    exposure_upper,
    disaster_ceiling,
    policy_version,
    state_authority,
    source_snapshot_id,
)
```

`safety_market_state` 可控制硬安全上限和政策带；`optional_regime_overlay` 在未授权时只作诊断，不能缩放本对象。缺失状态必须是 `unknown/degraded`，不能回填中性值。

### 4.4 新增 `PortfolioSizingIntent`：唯一组合尺度

建议新增模块：`functions/decision_council/position_sizing_contract.py`。

```python
@dataclass(frozen=True)
class PortfolioSizingIntent:
    decision_id: str
    policy_holding_floor: int
    policy_holding_target: int
    policy_exposure_lower: float
    policy_exposure_target: float
    hard_holding_ceiling: int
    hard_exposure_ceiling: float
    executable_target_holding_count: int
    executable_target_exposure: float
    target_gross_amount: float
    current_gross_amount: float
    incremental_target_amount: float
    target_new_name_count: int
    base_new_name_target_amount: float
    sizing_mode: str
    feasibility_state: str
    binding_reasons: tuple[str, ...]
    contract_version: str
```

核心公式：

```text
K_hard = min(policy holding ceiling, product/user/economic hard ceiling)
K_exec_target = min(policy holding target, K_hard)
E_hard = min(policy exposure upper, safety hard ceiling, cash hard ceiling)
E_exec_target = min(policy exposure target, E_hard)
A_target = E_exec_target * NAV
A_incremental = max(A_target - post_mandatory_invested_amount, 0)
K_new_target = max(K_exec_target - post_mandatory_holding_count, 0)
A_base_new_name = A_incremental / max(K_new_target, 1)
```

空仓时按政策可执行目标分仓；已有持仓时只对增量部署金额和缺少名称数分配。不能使用 `economic_position_cap` 或 `search_cap` 作为分母。若 `K_new_target=0`，新增入场金额为 0，已有持仓增仓另走 add proposal，不伪造新名称预算。

政策原值和可执行目标必须同时保存。`K_exec_target` 因硬顶降低不表示政策被修改，而是产生 `policy_to_executable_holding_gap`。

### 4.5 `AuthorityEvidence` 与 `EntrySizingEnvelope` 解耦

将 `attach_scap_v31_authority()` 拆成两步。

第一步只判断证据权限：

```python
attach_scap_v31_authority_evidence(
    candidates,
    *, horizon_days, authority_snapshot_id
) -> DataFrame
```

输出 `entry_authority_tier`、`authority_evidence_state`、`authority_fraction`、`authority_reason`、校准统计与证据快照；移除 `target_position_cash` 入参。

第二步统一解析每只股票的整数尺寸：

```python
resolve_entry_sizing_envelopes(
    candidates,
    *, facts: PortfolioFacts,
    intent: PortfolioSizingIntent,
    trade_capacity: TradeCapacity,
    per_name_hard_cap: float,
    authority_policy: AuthoritySizingPolicy,
) -> tuple[EntrySizingEnvelope, ...]
```

```python
@dataclass(frozen=True)
class EntrySizingEnvelope:
    decision_id: str
    symbol: str
    authority_tier: str
    authority_fraction: float
    one_lot_amount: float
    base_target_amount: float
    authority_target_amount: float
    cash_max_lots: int
    single_name_max_lots: int
    authority_max_lots: int
    final_max_lots: int
    maximum_exposure_delta: float
    binding_constraint: str
    final_size_reachable: bool
    sizing_contract_id: str
```

每票：

```text
authority_target_amount = base_new_name_target_amount * authority_fraction
authority_max_lots = floor(authority_target_amount / one_lot_amount)
final_max_lots = min(cash_max, single_name_max, authority_max, market_rule_max)
```

关键不变量：

- D 档始终 0 手；B/C 的组合探索上限继续保留；
- 若 `winner_pyramiding_trading_authorized=false`，则本轮尺寸必须明确为 `final_authorized_size`，不能标为 starter；
- 若未来开启加仓，必须另有可达的 `AddSizingEnvelope` 和授权状态机；未实现前不允许把 starter 未达政策下界当作正常；
- `authority_fraction<1` 导致组合最大可达暴露低于条件下界时，返回 `authority_sizing_floor_shortfall`，不得静默通过；但也不得越权提高档位或强买负效用股票。

### 4.6 `DeploymentBounds`：增加授权后可达性

在现有对象中新增：

```python
authority_attainable_holding_count: int
authority_attainable_exposure: float
integer_attainable_holding_count: int
integer_attainable_exposure: float
policy_floor_feasible_before_authority: bool
policy_floor_feasible_after_authority: bool
structural_shortfall_reasons: tuple[str, ...]
```

可行性必须基于成本后正价值且有交易权限的 proposal 和 `final_max_lots` 计算，不得使用原始候选数。原因枚举固定：

`candidate_shortfall`、`negative_robust_net_value`、`authority_tier_block`、`authority_size_cap`、`lot_granularity`、`cash_buffer`、`single_name_cap`、`hard_safety_cap`、`product_holding_cap`、`market_untradeable`、`pending_cash_reservation`、`search_truncation_unproven`。

### 4.7 优化器接口与目标层级

目标签名沿用既定接口重构：

```python
optimize_action_proposals(
    proposals,
    *,
    facts: PortfolioFacts,
    constraints: OptimizerConstraints,
    preferences: OptimizerPreferences,
    sizing_envelopes: Sequence[EntrySizingEnvelope],
    risk_inputs: RiskInputs,
    search_budget: OptimizerSearchBudget,
) -> ActionPlan
```

`OptimizerConstraints` 使用条件下界、硬顶、现金缓冲、单名/论点/风险预算、mandatory ids 和逐票整数手数域；`OptimizerPreferences` 使用政策目标、人民币近优容差、广度和换手偏好。

词典序：

1. P0：安全动作、现金非负、整手、T+1/市场规则、持仓/暴露硬顶、风险硬预算；
2. P1：若 `policy_floor_feasible_after_authority=true`，计划不得违反条件下界；若不可行，最小化短缺并保留结构化原因；
3. P2：最大化成本后稳健增量财富，不买负稳健净值股票；
4. P3：在财富近优集合内接近政策持仓/暴露目标并提高论点、行业、风险贡献广度；
5. P4：最小化费用、换手、订单数并确定性破同分。

不是“为了满仓而买”。floor 只对正价值、可交易、授权候选构成的事实可行集合生效。

### 4.8 `ActionPlan`、订单和成交

`ActionPlan.target_lots_by_symbol` 继续作为唯一权威计划。新增：

```text
sizing_contract_id
constraint_contract_version
policy_holding_target / policy_exposure_target
executable_target_holding_count / executable_target_exposure
authority_attainable_holding_count / authority_attainable_exposure
planned_holding_count / planned_exposure
holding_floor_slack / exposure_floor_slack
floor_feasibility_state / floor_shortfall_reasons
selected_action_symbol_count
objective_components_with_units
```

每张 proposal/order/fill 必须携带：`decision_id`、`proposal_id`、`plan_id`、`sizing_contract_id`、`constraint_version`、`authorized_lots`、`planned_lots`。执行层仅检查计划硬顶、现金、库存、整手、停复牌、涨跌停、T+1 和幂等性；不得因为未达到或超过软目标而二次否决。

执行失败写 `execution_shortfall_reason`，下一决策日重新进入事实层。禁止修改原 ActionPlan 掩盖成交失败。

## 5. 配置与兼容开关

新增配置必须进入 runtime identity、manifest 和启动确认：

```python
SCAP_SIZING_CONTRACT_VERSION = "scap_sizing_v2"
SCAP_SIZING_REFERENCE_MODE = "policy_executable_target"
SCAP_AUTHORITY_SIZING_MODE = "final_when_add_unavailable"
SCAP_FLOOR_VIOLATION_GATE_MODE = "audit"  # shadow -> strict 分阶段迁移
SCAP_LEGACY_SIZING_SHADOW_ENABLED = True
```

迁移期同时计算 v1/v2，但只有一个版本有交易权。旧输出读取器：缺新字段时显示 `legacy_contract_unavailable`，不填 0。禁止 Web 动态修改这些配置；任何修改都必须新建受控实验身份。

数值阈值（政策持仓数、暴露带、A/B/C 乘数）本批不改。先修语义，再用固定身份消融决定是否调数值。

## 6. 全链埋点与对账

### 6.1 每日组合级事件 `sizing_contract_daily`

主键：`run_id + decision_id`。字段至少包括：

- 事实：NAV、现金、投入金额、实际持仓/暴露、现金缓冲；
- 政策：原始 K floor/target/ceiling、E lower/target/upper/disaster、状态和权限；
- 容量：用户/产品/经济硬顶、可负担新增名称、旧参考值（仅影子）、绑定原因；
- 尺度：可执行 K/E 目标、目标总金额、增量金额、新名称数、单名称基础金额；
- 可达性：正价值授权候选数、授权最大 K/E、整数最大 K/E、前后 authority 的 floor 可行性；
- 计划：planned K/E、floor/target/hard-ceiling gaps、求解器和候选哈希；
- 执行：ordered/executed K/E、plan-to-order、order-to-fill、fill-to-policy gaps；
- 状态：`contract_version`、`sizing_contract_id`、reason codes、data quality flags。

### 6.2 候选/提案级事件 `entry_sizing_audit`

每个 `decision_id + symbol + proposal_id`：一手金额、基础目标金额、权限档位/乘数、现金/单名/权限/市场最大手数、最终最大手数、绑定约束、稳健净收益、费用、是否进入优化器、是否选中、拒绝原因。

### 6.3 订单/成交级事件 `sizing_execution_reconciliation`

记录授权手数、计划手数、注册手数、成交手数、预留现金、实际现金、预期/实际暴露变化、滑点、费用、阻塞原因、幂等键。恒等式：

```text
authorized >= planned >= registered >= filled >= 0
post_fill_cash = pre_fill_cash - buy_notional - fees + sell_net_receipts
post_fill_exposure = marked_position_value / post_fill_nav
```

卖单方向用绝对手数单独校验，不套买单不等式。

### 6.4 运行级指标与告警

核心指标：

- `legacy_reference_to_policy_target_ratio`；
- `authority_attainable_to_policy_target_exposure_ratio`；
- `planned_to_conditional_floor_ratio`；
- `executed_to_planned_exposure_ratio`；
- `floor_feasible_day_count`、`structural_floor_violation_days`、`execution_floor_violation_days`；
- `idle_cash_ratio`、`cash_drag_amount`、`minimum_commission_share`；
- 跨资本 `exposure_elasticity`、买入键 Jaccard、订单金额/NAV、one-lot/NAV。

告警分级：

- ERROR：硬顶穿透、现金/库存负数、同 decision 多个权威计划、字段不守恒；
- WARN：条件下界事实可行但计划违约、计划可达但执行无解释违约、同一原因连续多日；
- INFO：合同版本切换、绑定约束变化、保存阶段变化；
- DEBUG/TRACE：只在显式诊断模式采样，默认不逐候选高频写 SQLite。

“fail closed”含义：硬安全/账务错误阻止交易；研究质量违约阻止 run 获得研究/生产资格并明确告警，不自动买负价值股票，也不阻止必要安全卖出。

## 7. Web/API 完整交互

### 7.1 API/JSON

保留现有 `GET /state` 作为轻量实时快照，不改变轮询入口；新增接口全部只读：

| 方法与路径 | 用途 | 关键参数/约束 |
|---|---|---|
| `GET /state` | 当前运行进度、最新组合合同和曲线历史 | 响应增加`sizing_contract`；不得内嵌全候选明细 |
| `GET /api/sizing-contract` | 单日六层合同及对账 | `decision_id`或`date`二选一；不存在返回404和结构化状态 |
| `GET /api/sizing-audit` | 候选/提案尺寸审计分页 | `decision_id`必填，`symbol/reason/selected`可选，`limit/cursor`分页 |
| `GET /api/sizing-export` | 下载筛选后的CSV/JSON | `from/to/layer/reason/format`；只允许当前run manifest登记的产物 |
| `GET /api/comparable-runs` | 返回可比较run及身份差异 | 禁止只按目录名判断可比性 |
| `GET /api/sizing-compare` | 两个已完成run的资本/仓位合同对照 | `left_run_id/right_run_id`；身份不兼容返回409及差异字段 |

所有接口必须校验 run/artifact 白名单，禁止把查询参数直接拼成本地路径；只允许 GET，不增加修改配置或提交交易的 POST。大表使用 cursor 分页和响应大小上限，实时 `/state` 不因审计文件尚未完成而阻塞。

在现有 monitor payload 上增量加入：

```json
{
  "sizing_contract": {
    "version": "scap_sizing_v2",
    "id": "...",
    "status": "ok|degraded|legacy|failed",
    "policy": {},
    "capacity": {},
    "intent": {},
    "attainability": {},
    "plan": {},
    "execution": {},
    "binding_reasons": []
  },
  "chart_history": [{
    "date": "YYYY-MM-DD",
    "policy_holding_floor": 0,
    "policy_holding_target": 0,
    "hard_holding_ceiling": 0,
    "authority_attainable_holding_count": 0,
    "planned_holding_count": 0,
    "actual_holding_count": 0,
    "policy_exposure_lower": 0.0,
    "policy_exposure_target": 0.0,
    "hard_exposure_ceiling": 0.0,
    "authority_attainable_exposure": 0.0,
    "planned_exposure": 0.0,
    "actual_exposure": 0.0
  }]
}
```

0 是合法值；前端只能用 `??`/`Number.isFinite`，禁止 `|| default`。旧 schema 缺字段时为 null 并显示“历史合同无此字段”，不能画成 0。

### 7.2 风险页布局

新增“资本与仓位合同”卡片，固定六列漏斗：

```text
政策原值 -> 交易容量 -> 可执行尺度 -> 授权后可达 -> ActionPlan -> 实际成交
```

每列同时展示持仓数、暴露、金额、状态和绑定原因。原“经济容量/估仓位数”改为两个独立标签：“交易硬容量上限”“旧分仓参考（影子/弃用）”。

### 7.3 曲线

持仓数曲线增加“授权最大可达”一条；暴露曲线新增并列图。两图共享时间轴，支持 60/180/全部：

- 政策 lower/target/hard ceiling；
- 授权后 attainable；
- 优化器 planned；
- 实际 actual。

悬停同一天显示 NAV、现金、政策状态与权限、K/E 六层值、单名称基础目标金额、旧参考值、floor 可行性、绑定原因、计划/执行缺口。结构不可行与执行失败使用不同颜色和文案。

### 7.4 用户操作

- 时间范围：60/180/全部；
- 图层开关：政策/容量/授权/计划/实际；
- 单位：百分比/人民币；
- 状态筛选：normal/weak/high/crisis/unknown；
- 原因筛选：authority、candidate、cash、lot、risk、execution；
- 下载：当前过滤后的 CSV 和完整 JSON；
- 研究模式可选择两个“已完成且身份可比”的资本档 run 做对照；不可比时按钮禁用并展示差异字段；
- 页面只读，不提供“提高仓位”“切换权威乘数”等生产控制；未来若提供，必须跳转到独立实验配置、显示变更摘要并生成新 runtime identity。

### 7.5 状态与失败交互

- 运行中：显示计算、核心保存、审计保存、Excel、Web 五阶段及最后心跳；
- 合同降级：黄色横幅，列出缺失字段和回退版本；
- `policy_floor_feasible=true` 且 plan 违约：红色“计划合同失败”；
- plan 可行但 fill 违约：红色“执行缺口”，显示停牌/涨跌停/现金预留等事实原因；
- 附属报表失败不抹掉核心回测完成状态，展示最后成功 artifact 和可重试资格；
- 无数据、真实 0、旧 schema 缺失、尚未计算四种状态必须使用不同文案。

## 8. 实施批次与文件范围

### 批次 1：合同和影子埋点，不改变交易

1. 增加 `PortfolioFacts`、`TradeCapacity`、`PortfolioSizingIntent`、字段注册表；
2. v1/v2 双算，v1 继续有交易权，v2 仅影子；
3. 落盘每日 reconciliation 和 schema/version；
4. Web 先展示六层影子数据；
5. 专项性质测试、旧 run 兼容测试、5 日保存链。

完成条件：每个字段唯一生产者；338 日旧 run 可重建对账；影子 v2 能精确复现自身公式；交易/order/fill/NAV 与冻结基线逐日相同。

### 批次 2：授权尺寸解耦与唯一尺度接入

1. `attach_scap_v31_authority` 移除 `target_position_cash`；
2. 新增 `resolve_entry_sizing_envelopes`；
3. `runner.py` 和 `scap_v3_lean.py` 只消费 `PortfolioSizingIntent`；
4. `DeploymentBounds` 使用授权后整数可达暴露；
5. optimizer 消费统一逐票手数域；执行层移除软目标二次解释；
6. 5 日、20 日和 82 日受控资本矩阵。

完成条件：旧 `sizing_reference_positions` 无交易消费者；无加仓权时尺寸明确为 final；条件下界事实可行时计划违约为 0；任何不可行都有枚举原因。

### 批次 3：完整产品、消融与准入复核

1. summary/CSV/JSON/Excel/Web 全部接入六层字段；
2. 资本弹性、买入重合、结构/执行违约归因；
3. 338 日冻结身份 A/B 实验：A=当前代码，B=仅新尺度合同；
4. C=权威乘数版本、D=未来加仓授权只能作为独立实验，禁止与 B 混跑；
5. 年份/状态/资金/成本切片与故障注入；
6. 研究门、生产门独立复核。

完成条件：工程产品通过不等于交易准入；338 日仍是 development/audit。生产门只有在不少于 504 个正式 OOS 交易日、PIT、成本、模型权威、研究 gate 和纸面运行均通过后才可解除。

## 9. 验证矩阵

### 9.1 纯函数/性质测试

- 20k/50k/100k/200k、相同候选和相同比例政策：资金增大不能仅因容量参考分母造成目标暴露下降；
- 高价股只够一手、低价股多手、最小佣金、现金缓冲、已有持仓、空仓、强退后空仓；
- A/B/C/D、无加仓权、候选不足、全部负效用、停牌/涨跌停、单名硬顶、风险硬顶；
- 候选顺序扰动、复制候选、减少现金、提高费用、关闭某动作、同 Plan 重放；
- 0/None/NaN/Inf、min=max、旧 schema、重复 decision id；
- exact/beam 在小夹具上约束含义一致，beam 不得声称优于 exact。

### 9.2 链路测试

逐日核对：

```text
policy -> intent -> envelope -> proposal -> constraints -> plan
       -> pending -> order -> fill -> holdings/cash/NAV -> Web
```

每张成交可反查唯一 proposal/plan/sizing contract；每天只能有一个权威 ActionPlan；计划后不得再有软评分否决。

### 9.3 运行阶梯

1. `py_compile` 和专项验证；
2. 构造夹具；
3. 5 日 smoke：验证计算到全部保存，不作为盈利证据；
4. 20 日四资本档：验证整手、费用、对账、Web；
5. 82 日 20k/50k/100k/200k 单变量矩阵：验证本缺陷；
6. 338 日同身份 A/B：评估收益、回撤、仓位、闲置现金、买入质量、状态切片；
7. 不少于 504 日正式 OOS/纸面运行后再裁决生产门。

### 9.4 硬验收

- 无现金负数、库存下穿、零股订单、硬顶穿透；
- 安全退出 100% 不被持仓 floor 阻止；
- floor 事实可行时 ActionPlan 违约为 0；
- 不可行时不买负稳健净值股票且原因完整；
- `policy/intention/attainable/plan/execution` 金额与比例可独立重算，勾稽误差在统一容差内；
- v2 交易权开启前，v1 基线订单/成交/NAV 完全不变；
- Web 真实 0、缺失、旧 schema、失败状态显示正确；
- 82 日不得再出现“可行但静默 82/82 floor 违约”；若仍违约，必须精确归入结构或执行原因并阻止研究准入。

## 10. 迁移、回滚和 Git 策略

- 新合同用 feature flag 和版本号启用；v1/v2 先双写，不原地覆盖旧字段；
- 每一批独立 commit/PR：合同影子、交易接入、产品/Web、实验报告分开；
- 回滚只切回唯一交易权版本，保留 v2 影子与证据，不删除历史 run；
- 任何行为改变后必须产生新 code/runtime identity，旧结果不得与新结果伪装同实验；
- 若批次 2 出现硬约束/账务/执行回归，立即关闭 v2 交易权，不通过放宽门槛“修结果”；
- 若经济表现恶化但工程合同正确，保留工程修复，单独审查 alpha/权限乘数/加仓，不恢复语义错误。

## 11. 需要主人确认的设计决策

建议默认确认以下四项后再写交易代码：

1. 采用“容量是上限、政策可执行目标是唯一分仓尺度”，不再用容量名称数除 NAV；
2. 无盈利加仓权限时，A/B/C 尺寸命名并执行为最终授权尺寸；
3. floor 不强迫买负价值股票；可行但计划违约阻止研究准入，安全卖出永远优先；
4. 先批次 1 影子双写，再批次 2 切换交易权，最后批次 3 做长窗，不直接跑完整 338 日试错。

## 12. 客观建议

用户提出“更多钱反而赚得慢”是正确异常线索，但不能据此预设收益率必须随本金增加。A 股整手、单名上限、候选数量、冲击成本会产生真实容量效应。当前证据能证明的是：现有结果混入了不应存在的机械分母效应，因此不能用来判断策略真实容量。应先修合同并做受控资本矩阵，再讨论大盘信号、因子家族或买入质量。市场状态与因子家族研究已有 OOS 诊断产品，但在交易授权前仍要独立预注册、校准和验证，不能用本次仓位 bug 修复顺便上线。

## 13. 2026-08-09 实施与20日工程验收

- 批次1：新增`PortfolioSizingIntent`及候选`EntrySizingEnvelope`，A/B/C/D权限模块在正式链仅提供证据和折扣，不再拥有NAV分仓公式；旧`sizing_reference_positions`只保留影子披露。
- 批次2：runner、Lean单优化器、`DeploymentBounds`、ActionProposal/ActionPlan、pending order和fill统一携带`sizing_contract_id`；权限前、权限后、整数整手后K/E可达性分层，floor短缺区分结构不可行、最优计划违约和搜索未决。空候选/纯持有日ActionPlan由DecisionContext回填契约ID，不触发第二次优化。
- 批次3：新增`governance_entry_sizing_audit.csv`、summary聚合、只读`/api/sizing-contract`和`/api/sizing-export`，风险页增加持仓数与暴露六层合同曲线；0、缺失和legacy保持不同语义。
- 静态和数学复核：容量仅作上限；分仓基数为`max(E_target*NAV-current_gross,0)/max(K_target-current_K,0)`；单名硬上限为`NAV*per_name_cap`；权限、现金、单名上限取整数手数交集；安全退出优先，禁止为满足软floor强买负稳健净值标的；Lean仍恰好调用一次优化器。
- 正式20日目录：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260809_211446`，2025-01-02至2025-02-06共20个交易日，初始资金20,000元，最终NAV 20,198.32元，最终持仓6只；`COMPLETE.json`和artifact manifest均为complete，`holding_factor_products`内容/公式/渲染失败数均为0。
- 身份：`experiment_spec_hash/runtime_identity_hash=d2b65e4e04a5add1886ec620abe3a394443c7f80759e36c52730c28e309c9138`，`run_instance_hash=66ff39fc4ac72c4cd8cb110ddd541d1ad464985f52a7d9508723166d3b0b9a47`，`code_fingerprint=f3d704ece512411babfc0214e313e3282abf18d1d21b9eca694affe501e5316d`，固定74因子柜内容SHA256为`b8dd096a6706b63e6e960d01e23fa647763b7cd5113ace055db58e2395788b90`。
- 独立验收：`verify_scap_sizing_20d_output.py`验证20个唯一日契约、非负现金、持仓/暴露硬上限、floor分类完备、候选整数手数三重上限、proposal→plan→order→fill血缘、成交不超授权手数、工作簿校验及修复前后受控交易路径完全一致，9项全部通过。
- 边界：20日只证明工程闭环，不证明alpha、因子有效性或可生产。82日资本矩阵、338日development A/B与不少于504日正式OOS尚未执行；研究门与生产门继续`blocked`。
