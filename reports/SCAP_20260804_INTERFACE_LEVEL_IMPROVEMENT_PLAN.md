# SCAP 持仓、仓位与优化器接口级完整提升方案（2026-08-04）

## 1. 范围、依据与禁止事项

本方案的依据仅为当前工作区源码、`run20260804_024413`保存产物及本地 Git 只读差异；不使用外部数据库解释参数，不依据字段英文名猜含义。本轮只形成方案，不修改生产代码、不运行回测、不改 Git 历史。

受影响主链为：

`config.py → runner.py → capital_scaling.py / exposure_contract.py / exposure_catchup.py → engine.py / contracts.py → scap_v3_lean.py → scap_v2_contracts.py → integer_action_optimizer.py → retail_execution.py → runner保存 → candidate_funnel_audit.py / runner_summary.py / live_monitor_*`

目标不是机械提高持仓，而是建立以下顺序：

1. 事实和安全退出不可伪造；
2. 产品硬边界、交易可行边界和计算资源边界彼此分离；
3. 强制退出后重新计算条件可行下界；
4. 优化器真正执行上下界；
5. 只在成本后正价值候选内恢复持仓；
6. 软目标只在近优集合中起作用；
7. 输出、审计、Web使用相同公式和字段。

## 2. 当前真实调用链问题

### 2.1 当前顺序

1. `runner.py`先以交易前实际仓位调用`decide_exposure_catchup()`。
2. `resolve_position_capacity()`生成当日`effective_position_cap`。
3. `DecisionContext.top_n`接收该动态上限，`soft_target_positions`接收容量模块的报告目标。
4. `scap_v3_lean.build_lean_decision()`构造强制退出和可选买入。
5. `optimize_action_proposals()`只接收`max_positions`、`risk_exposure_ceiling`、每日最大新增名称/仓位，没有最低持仓或最低仓位。
6. 优化后，`runner.py`才调用`_holding_target_contract()`和`build_holding_semantics()`构造最低、软目标、最大值并保存。

因此当前最低持仓不可能影响计划；这是接口缺失，不是参数调得不够大。

### 2.2 当前名称与真实意义

| 当前字段/参数 | 当前真实意义 | 当前决定交易吗 | 处理决定 |
|---|---|---:|---|
| `min_holdings` | profile输入；Lean配置为0，随后风险状态又生成0/2/3 | 主优化器否 | 废止双权威，迁移到状态政策表 |
| `soft_target_positions` | fixed模式容量报告目标；auto模式在`capital_scaling`返回0，后续又被状态目标覆盖 | 主优化器否 | 改为唯一`policy_soft_holding_target` |
| `max_positions` | fixed模式金融上限；Lean auto模式通常为None | 部分 | 不再跨模式复用 |
| `user_hard_position_cap` | Web/用户额外治理上限 | 是 | 保留并改名`product_user_position_ceiling` |
| `scap_search_position_cap` | 计算/搜索容量 | 间接影响金融结果 | 改名并移出金融容量结构 |
| `economic_position_cap` | 基于整手/经济订单可负担数量的动态上限 | 是 | 保留，明确为“当日新增后可持名称上限估计” |
| `risk_feasible_position_cap` | 当前直接等于`economic_cash_cap` | 是 | 先改名为别名或删除；真正风险求解完成后再恢复 |
| `maximum_allowed_holding_count` | 动态`effective_position_cap` | 是上限 | 改名`daily_effective_holding_ceiling` |
| `minimum_required_holding_count` | 优化后报告值 | 否 | 新实现前改名`reported_policy_holding_floor`；新实现后才可称required |
| `holding_shortfall_count` | 软目标减实际 | 否 | 改名`actual_to_soft_target_holding_gap` |
| `selected_position_count` | 选中动作涉及的名称数 | 否，计划结果 | 改名`selected_action_symbol_count` |
| `optimizer_planned_holding_count` | `target_lots_by_symbol`中lots>0的数量 | 是，计划事实 | 保留，作为唯一“计划持仓数” |
| `target_exposure` | 在不同阶段可能指战略期望、授权上限或计划仓位 | 多处 | 禁止继续复用，拆成明确字段 |
| `exposure_gap` | 追仓模块为下界减实际 | 是 | 改名`pretrade_lower_exposure_shortfall` |
| `strategic_exposure_gap` | 战略目标减实际 | 否 | 改名`actual_to_policy_target_exposure_gap` |
| `effective_deployment_target` | `min(strategic_budget, signal_supported, integer_feasible)` | 优化次级项 | 改名`pretrade_feasible_deployment_reference` |
| `catchup_rate` | 当前允许时1，否则0 | 否 | 改名`recovery_authorized`；删除伪rate |
| `_catchup_rate()` | 被计算但结果未进入返回/预算 | 否 | 消融，或另立经验证的恢复速度接口 |
| `accuracy_multiplier` | 计算并展示 | 否 | 移入shadow diagnostics，禁止暗示仓位缩放 |
| `recovery_window_sessions` | 传递和保存，未发现状态机消费 | 否 | 在恢复状态机实施前标记inactive |
| `breadth_near_optimal_tolerance_amount` | 授权对象保存但优化器未消费 | 否 | 接入人民币近优集合，否则删除 |
| `strategic_exposure_normal/weak/high` | config值；当前Lean状态带函数未读取 | 否 | 要么成为唯一政策表输入，要么删除 |

## 3. 新的单一语义模型

所有数量分为六层，禁止跨层覆盖：

1. `facts`：交易前事实；
2. `policy`：产品/风险状态希望达到的区间；
3. `mandatory_projection`：执行不可取消退出后的投影事实；
4. `feasibility`：现金、整手、候选、风险和交易规则决定的可行区间；
5. `plan`：唯一优化器计划；
6. `execution`：下一交易日真实成交和成交后事实。

### 3.1 统一公式

产品政策：

```text
K_policy_floor(state), K_policy_target(state), K_product_ceiling
E_policy_lower(state), E_policy_target(state), E_policy_upper(state), E_disaster_ceiling(state)
```

强制退出后事实：

```text
K_post_exit = count(projected_lots_after_mandatory_actions > 0)
E_post_exit = sum(projected_weights_after_mandatory_actions)
C_post_exit = current_cash + executable_mandatory_sell_proceeds
```

条件可行下界：

```text
K_hard_ceiling = min(K_product_ceiling, K_trade_feasible_ceiling)
E_hard_ceiling = min(E_disaster_ceiling, E_cash_trade_ceiling)

K_conditional_floor = min(
    K_policy_floor,
    K_hard_ceiling,
    K_post_exit + positive_feasible_new_name_count
)

E_conditional_floor = min(
    E_policy_lower,
    E_hard_ceiling,
    E_positive_feasible_ceiling
)
```

若可行候选不足，政策下界不能被改写；必须同时保存政策下界、条件下界、差额和原因。

优化计划必须满足：

```text
K_conditional_floor <= K_plan <= K_hard_ceiling
E_conditional_floor <= E_plan <= E_hard_ceiling
projected_cash >= cash_buffer
per-name / thesis / board / scenario risk hard constraints pass
```

安全退出永远优先。若安全退出与下界冲突，先执行安全退出，再把下界降低原因记录为`mandatory_safety_exit_capacity_shortfall`；不得为维持持仓数阻止灾难退出。

## 4. 接口级重构设计

### 接口A：`config.py`产品政策

新增唯一结构`scap_policy_bands`，每个状态显式提供：

```python
{
  "normal_neutral": {
    "holding_floor": 3,
    "holding_target": 4,
    "exposure_lower": 0.60,
    "exposure_target": 0.75,
    "exposure_upper": 0.85,
    "disaster_ceiling": 0.90,
  },
  "weak": {...},
  "high_risk": {...},
  "crisis": {...},
}
```

保留：`min_cash_buffer`、用户硬上限、单名硬上限、成本模型、组合ES硬预算。

拆分计算资源参数：

- `optimizer_prefilter_symbol_limit`：当前12；
- `optimizer_exact_symbol_limit`：当前决定穷举边界；
- `optimizer_beam_width`：当前256；
- `optimizer_search_holding_ceiling`：当前搜索容量。

废止或迁移：`min_holdings`、`soft_target_positions`、三个未消费`strategic_exposure_*`、伪`recovery_window_sessions`。迁移期只允许读取旧名并发出明确deprecated诊断，不得两个来源取最小/最大后静默覆盖。

配置校验新增：

```text
0 <= floor <= target <= product ceiling
0 <= exposure_lower <= exposure_target <= exposure_upper <= disaster_ceiling <= 1
cash_buffer < initial_cash
soft per-name cap <= hard per-name cap
所有0必须作为合法值，禁止`value or default`
```

### 接口B：`exposure_contract.py`政策解析

把`resolve_strategic_exposure_band()`改为只解析政策，不读取可行性：

```python
resolve_policy_band(
    *, risk_level, structural_regime_level, policy_bands
) -> PolicyBand
```

`PolicyBand`字段固定为：`state`、`holding_floor`、`holding_target`、`exposure_lower`、`exposure_target`、`exposure_upper`、`disaster_ceiling`、`policy_version`。

安全上限不得在此函数内静默裁剪政策值；裁剪属于后续`FeasibilityBounds`，从而保留“政策原值”和“当日可行值”的差异。

### 接口C：`capital_scaling.py`容量

将当前`PositionCapacity`拆成两个接口：

```python
resolve_trade_capacity(...) -> TradeCapacity
resolve_computation_budget(...) -> OptimizerSearchBudget
```

`TradeCapacity`只包含金融/交易事实：可用现金、风险空间、一手金额、整手可负担新增名称数、成本后正价值候选数、交易可行持仓上限、可行仓位上限及原因。

`OptimizerSearchBudget`只包含预筛数量、精确求解边界、beam宽度。任何搜索参数都不得写入`K_hard_ceiling`。

删除当前伪`risk_feasible_position_cap=economic_cash_cap`。若需要风险持仓上限，新增真正接口：

```python
resolve_structural_risk_capacity(
    projected_candidates, covariance, scenario_matrix, risk_budget
) -> StructuralRiskCapacity
```

证据不足时返回`state="unavailable"`，不能用现金容量冒充风险容量。

### 接口D：强制动作投影

在`scap_v3_lean.py`提案生成后、恢复授权前新增纯函数：

```python
project_mandatory_actions(
    *, current_lots, current_weights, current_cash,
    mandatory_proposals, execution_rules
) -> MandatoryProjection
```

输出：`post_exit_lots`、`post_exit_weights`、`post_exit_cash`、`post_exit_holding_count`、`post_exit_exposure`、`mandatory_ids`、`unexecutable_mandatory_ids`、`projection_reasons`。

只允许`must_execute`、`safety_exit`、`hard_exit`进入该投影；普通止盈、替换或软退出不得伪装成mandatory。

### 接口E：条件部署边界

新增：

```python
resolve_conditional_deployment_bounds(
    *, policy_band, mandatory_projection,
    trade_capacity, positive_feasible_proposals,
    product_hard_position_ceiling,
    structural_risk_capacity
) -> DeploymentBounds
```

输出必须同时保存：政策floor/target、条件floor、产品ceiling、交易可行ceiling、最终hard ceiling、政策与可行缺口、每项绑定原因。

`positive_feasible_proposals`定义为：权限允许、整手可买、现金可用、成本后保守净价值大于人民币epsilon、硬风险通过。不能使用原始信号数或预筛分数代替。

### 接口F：恢复状态机（替换`exposure_catchup.py`）

新的接口基于退出后投影：

```python
advance_recovery_state(
    *, prior_state, decision_date,
    mandatory_projection, deployment_bounds,
    positive_feasible_proposals,
    market_safety_state
) -> RecoveryAuthorization
```

字段：`authorized`、`episode_id`、`episode_day`、`holding_deficit`、`exposure_deficit`、`max_new_names_today`、`max_buy_exposure_today`、`deadline_sessions`、`block_reason`、`warning_only_metrics`。

`accuracy_multiplier`等未获得样本外授权的量只能进入`warning_only_metrics`，不得暗中缩放预算。五日窗口只有在状态持久化、逐日推进、完成/失败有终态时才可命名为五日恢复。

### 接口G：`DecisionContext`

删除语义模糊的`top_n`、`soft_target_positions`、`catchup_buy_budget`组合，改传强类型对象：

```python
DecisionContext(
    ...,
    portfolio_facts=PortfolioFacts(...),
    policy_band=PolicyBand(...),
    mandatory_projection=MandatoryProjection(...),
    deployment_bounds=DeploymentBounds(...),
    recovery_authorization=RecoveryAuthorization(...),
    search_budget=OptimizerSearchBudget(...),
)
```

`target_exposure_cap`改成明确的`execution_hard_exposure_ceiling`。engine只能进一步收紧硬顶，不得覆盖战略目标。

### 接口H：`ExposureAuthorization`

拆除混杂政策、硬约束和软诊断的现状，建议更名`OptimizerConstraints`：

```python
OptimizerConstraints(
    holding_floor,
    holding_ceiling,
    exposure_floor,
    exposure_ceiling,
    cash_buffer_amount,
    per_name_hard_cap,
    thesis_hard_cap,
    scenario_loss_budget_amount,
    max_new_names,
    max_incremental_buy_exposure,
    mandatory_proposal_ids,
    constraint_version,
)
```

软目标单独进入`OptimizerPreferences`：`holding_target`、`exposure_target`、人民币近优容差、广度目标、换手偏好。硬约束不得以penalty伪装，软偏好不得写进硬授权对象。

### 接口I：`optimize_action_proposals()`

新签名：

```python
optimize_action_proposals(
    proposals,
    *, facts, constraints, preferences,
    risk_inputs, search_budget
) -> ActionPlan
```

求解层级：

- P0：mandatory、安全、现金、整手、交易状态、硬仓位/持仓、硬风险；
- P1：只在事实性不可行时最小化并显式记录条件下界违反；正常情况下不允许违反；
- P2：最大化成本后保守增量财富；
- P3：在`best_wealth - epsilon_amount`近优集合内，最小化目标仓位/目标持仓缺口并提高板块、论点和风险贡献广度；
- P4：最小化成本、换手和订单数量。

禁止继续用原始浮点tuple逐位无限精度比较。`breadth_near_optimal_tolerance_amount`必须真正决定近优集合，建议名称`wealth_materiality_epsilon_amount`，单位明确为人民币。

精确与beam求解不能因持仓上限5/6自动改变金融逻辑。至少要求：同一候选集合在小规模夹具上beam结果不得优于精确结果且关键约束一致；生产保存`solver_mode`、`optimality_scope`、`candidate_universe_hash`。

### 接口J：`ActionPlan`

保留`target_lots_by_symbol`为唯一计划持仓事实。新增：

- `planned_holding_count`；
- `planned_exposure`；
- `holding_floor_slack`、`holding_ceiling_slack`；
- `exposure_floor_slack`、`exposure_ceiling_slack`；
- `mandatory_action_completion_pass`；
- `conditional_floor_binding_reason`；
- `wealth_optimality_gap_amount`；
- `constraint_contract_version`。

将现有`selected_position_count`改为`selected_action_symbol_count`。`objective_lexicographic_rank`改为结构化`objective_components`，每项带单位和方向。

### 接口K：`retail_execution.py`

执行层只能验证事实变化，不得重新解释战略目标。当前从`exposure_rows[-1]["target_exposure"]`读取目标并加`tolerance`拦截ActionPlan，可能把战略目标误当硬顶。

改为订单携带：`plan_hard_exposure_ceiling`、`plan_target_exposure`、`plan_id`、`constraint_version`。执行层仅按硬顶、现金、整手、停牌/涨跌停、T+1验证；不得用软目标拦截已经授权的ActionPlan。

成交失败后必须生成`execution_shortfall_reason`，下一决策日由事实层重新计算，不得篡改原计划。

### 接口L：保存、审计和Web

保存表按前缀分层：

- `fact_*`：交易前事实；
- `policy_*`：原始政策；
- `post_mandatory_*`：强制动作后投影；
- `feasible_*`：条件可行边界；
- `plan_*`：优化器计划；
- `executed_*`：实际成交后事实。

删除裸`target_exposure`和裸`exposure_gap`。至少替换为：

- `policy_exposure_target`；
- `policy_exposure_lower`；
- `pretrade_policy_target_gap`；
- `pretrade_policy_lower_shortfall`；
- `post_mandatory_lower_shortfall`；
- `plan_exposure`；
- `execution_to_plan_exposure_gap`。

`build_exposure_reconciliation()`不得自行选择公式，应调用与生产相同的纯函数或按上述字段做恒等式检查。Web不得使用JavaScript `||`为0回退；必须使用空值判断`??`或显式`Number.isFinite`。

Web展示固定为：政策最低/目标/上限/灾难顶、当日条件最低/硬顶、强退前实际、强退后投影、计划、成交后实际。持仓数同样六层展示，不能再只有“最低/目标/最大”三个容易混淆的数字。

## 5. 特殊值和金融合理性保护

1. 所有比例和金额入口先`isfinite`；NaN/Inf硬失败并保存字段名。
2. 0是合法值，所有`profile.get(... ) or default`改为显式空值处理。
3. 成本占毛收益比仅在`gross_profit > gross_epsilon_amount`时定义；否则使用绝对人民币净值门，比例字段标为`undefined_near_zero_gross`。
4. 60%硬门采用确定的闭区间定义并测试`threshold ± epsilon`。
5. 人民币目标比较做materiality量化，禁止浮点尾数改变计划。
6. 状态政策加入进入/退出滞回和最短驻留，但灾难安全状态不受滞回阻止。
7. 下界只对成本后正价值、真实可执行候选生效；不强买负价值标的。
8. 板块、论点和风险贡献集中度分开。当前单名集中惩罚不能替代301板块或`size_style`论点集中控制。
9. 最大回撤报告同时输出深度、水下期、恢复日期、上涨日参与率和现金拖累；避免再次把持续回撤误解为单日冲击。

## 6. 分阶段施工和每阶段验收

### Phase 0：冻结与语义注册

- 固定8月4日run、代码指纹、配置、数据/PIT、成本和因子柜；
- 新增机器可读字段注册表：名称、单位、生产者、消费者、公式、决策权、弃用版本；
- 先只修审计和展示语义，不改变交易。

验收：所有字段唯一生产者；`exposure_reconciliation`338日误差为0；旧run兼容读取但明确标记legacy。

### Phase 1：政策与容量拆分

- 实施`PolicyBand`、`TradeCapacity`、`OptimizerSearchBudget`；
- 移除双重最低/目标权威；
- 搜索参数不再进入金融上限。

验收：配置边界、0值、min=max、无用户上限、只够一手、无候选、已有持仓超过新上限等性质测试。

### Phase 2：强制动作投影

- 增加`MandatoryProjection`；
- 将追仓判断从交易前仓位移动到强制退出后投影。

验收：复现2026-03-23四只强退夹具；安全退出不被阻止；同日恢复授权按退出后0只/0仓位计算。

### Phase 3：条件硬下界进入优化器

- 增加`DeploymentBounds`和`OptimizerConstraints`；
- `K/E`上下界进入`_plan_key`可行性，不再只写报告。

验收：有足够正价值候选时不得低于条件floor；候选不足时不强买负价值且原因完整；硬顶永不突破。

### Phase 4：目标函数和求解器稳定化

- 人民币近优集合；
- 广度/部署仅在近优集合内比较；
- 精确/beam一致性和求解边界测试；
- 板块/论点集中度接入。

验收：成本比60%边界、gross≈0、人民币差1分钱、持仓5/6、候选12/13、相同候选顺序扰动均有确定结果。

### Phase 5：执行、保存、Web

- 执行层只验证硬事实；
- 新字段分层落盘；
- 审计复用生产公式；
- Web移除模糊字段和`||`零值回退。

验收：proposal→plan→pending→order→fill→position血缘完整；计划与执行缺口有唯一原因；所有页面数字可从CSV独立重算。

### Phase 6：性能

- 在经济/风险逻辑冻结后，分段记录候选成本、情景矩阵、求解、保存时间；
- 优先缓存重复一手成本、增量更新协方差/情景、按有效候选裁剪矩阵；
- 禁止为提速放宽成本或风险门。

验收：结果哈希不变的前提下比较耗时；分别报告计算和保存时间。

## 7. 测试、消融与最终338日实验

每个Phase顺序固定：静态代码审查 → 数学/金融审查 → `py_compile` → 纯函数夹具 → 专项回归 → 不运行代码的调用链复查。全部阶段完成后才运行20日从开始到保存全流程；20日只证明工程链，随后必须运行固定身份338日消融。

消融矩阵：

- A：冻结Git/8月4日基线；
- B：仅语义和审计；
- C：政策/容量拆分；
- D：退出后条件硬下界；
- E：人民币近优与广度；
- F：搜索参数恢复/变化；
- G：恢复速度1只/15%与候选可行自适应版本。

所有实验固定：日期、数据/PIT快照、资金、现金缓冲、成本、因子柜、状态输入、随机性、执行规则和报告版本。

硬验收：

- 安全退出100%不被最低持仓阻断；
- 计划持仓/仓位不突破硬顶；
- 在正价值可行候选足够时，计划不低于条件floor；
- 政策不足与可行不足原因完整；
- 全字段勾稽误差0；
- 无NaN/Inf；
- solver切换不改变约束含义；
- 研究门和生产门在338日、PIT、成本、账户勾稽、基准和独立复核完成前继续blocked。

经济评价同时报告：总收益、基准几何相对收益、最大回撤深度、最长水下期、恢复日数、最差单日、上涨日参与率、平均/分位仓位、持仓分布、低于条件floor日数、现金拖累、换手成本、论点/板块/风险贡献集中度和运行耗时。

## 8. 建议保留、放宽和消融

必须保留：安全退出、现金缓冲、整手、T+1、停牌/涨跌停、单名灾难硬顶、组合场景风险硬预算、成本后正净值门、不可变血缘。

应放宽或改造：恢复必须按退出后状态授权；每日1只/15%从无条件硬限制改为受政策、候选正价值和风险空间共同决定的恢复上限；广度改为财富近优集合内的偏好；候选搜索容量不能成为金融上限。

应消融：未消费的准确率乘数、伪catchup rate、未实现的五日窗口标签、伪风险可行持仓上限、重复目标仓位字段、未接入的近优参数、auto模式无效的soft target来源。

## 9. 最终建议

先做语义和接口重构，再调任何数值。当前最危险的不是参数偏保守，而是同名字段在不同层代表不同公式、报告值被误认为硬约束、执行层又重新解释目标。只有在六层语义和上下界接口建立后，才有资格讨论最低3只还是2只、目标75%还是其他数值。具体数值应通过固定身份消融决定，不能用字段名称或主观感觉直接设定。
