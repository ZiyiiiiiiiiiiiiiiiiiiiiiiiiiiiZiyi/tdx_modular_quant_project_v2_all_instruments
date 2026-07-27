# SCAP-V2 小资金特殊版全链二次缺口审计与防冲突修改规格

版本：2026-07-26
状态：设计与施工合同，尚未修改交易代码
审计基线：`run20260726_191810`及`run20260725_230047`相同前180日
资本画像：20,000元、最多5只、无杠杆、允许较大回撤、成本后净利润第一

## 0. 执行摘要

现有问题不止`entry_matrix_score`被人民币效用覆盖。二次全链审计确认，旧规格提出的“统一提案→统一价值→整数手优化→唯一决策”没有完整落地，当前仍是：

```text
柜评分
→ 第一次V3评估（人民币效用覆盖评分）
→ 生命周期固定优先级/加仓布尔门
→ 第二次V3整手选择
→ policy第二次整手子集选择
→ 连续组合构造
→ 替换在组合构造后直接覆盖目标权重
→ 零售层再次按评分、状态、现金和仓位拒绝/放大
→ pending/执行
```

这条链同时存在评分单位污染、无样本概率伪装为已校准、两个整数选择器、固定动作优先级冒充统一效用仲裁、加仓/替换没有进入同一个组合优化器、相关性接口未接入、高仓位门禁未统一控制全部买权，以及保存阶段集中构造大表等问题。

因此不能只修一行评分赋值。正确方案是先建立不可混用的类型/单位合同，再把所有买卖动作统一成一份整数手`ActionPlan`，最后让执行层只检查事实可执行性。

## 1. 二次审计发现的问题

### P0-01 评分、收益率和人民币金额混用

`mainline_v3.py`把`scap_candidate_utility`写回`entry_matrix_score/final_entry_score/primary_score`。人民币效用随后被生命周期当0—1入场分、被policy排序、被零售执行计算订单优先分、被Web显示为Entry Matrix。

修复要求：评分、收益率、概率、人民币金额必须属于不同类型；任何跨类型赋值在运行时直接失败。

### P0-02 无样本先验被伪装成校准结果

`entry_calibration.py:_fallback_frame`在`sample_count=0`时仍生成`p_win`、平均盈利、平均亏损和期望；`small_capital_aggressive.py`只检查点估计和LCB非空，就把状态设为`calibrated`。

链路实际为：

```text
启发式先验
→ expected_edge
→ comparable_expected_alpha
→ “calibrated”
→ 人民币效用
→ 真买入
```

这不是未来函数，但属于概率语义错误。无成熟样本只能是`prior_only`，不得获得收益预测交易权。

### P0-03 校准标签与真实成交路径不一致

滚动校准以决策日候选价格为入场基准，在第H个索引日成熟；真实策略是`t`收盘决策、`t+1`最早可成交。正确标签必须使用决策之后首个事实可成交价格，停牌、涨跌停、无报价和无法成交保留状态，不能静默改用决策日收盘。

### P0-04 预测成本被重复扣除

`RollingEntryCalibrator.expected_edge`已经减固定`cost_buffer`；`ActionUtility`随后又减完整预计成本。替换链也把已含缓冲的edge再减配对成本。

修复要求：

- `gross_return_distribution`永远不含成本；
- `estimated_execution_cost_amount`只在动作估值层扣一次；
- 历史产物通过`cost_inclusion_state`明确标记。

### P0-05 “统一动作仲裁”仍是固定优先级

`arbitrate_position_actions(proposals: dict[str,bool])`只按：

```text
exit > replacement > loser_add > winner_add > new_entry > rebalance > hold
```

选择第一个提案。它不接收`ActionUtility`，也不决定交易；policy生成订单后再次调用它，主要作用是写标签。因此当前`unified_action_selected`是事后描述，不是交易权威。

### P0-06 两个整数选择器与一个连续组合器同时存在

当前同时运行：

- `mainline_v3.select_scap_one_lot_portfolio`；
- `policy._select_scap_discrete_entries`；
- `PortfolioConstructionCommittee.construct`。

这违反“一日一次最终组合优化”。第二选择器即使修正了第一选择器的仓位问题，也会形成新的权威冲突。

### P0-07 加仓没有进入整数手统一优化

生命周期只输出`add_allowed/add_budget`。其中`add_budget`仍使用通用20%上限而非小资金档40%，且没有成为最终整数约束；policy允许连续目标增加，retail再取整或升级。因此盈利加仓和亏损摊平仍是“布尔允许、连续定仓、整手执行”三套数学。

### P0-08 替换绕过最终组合约束

policy完成组合构造后，直接将原持仓目标设为0、挑战者设为一手权重，没有重新联合检查相关性、行业、风险贡献和总暴露。替换必须进入同一个整数动作优化器。

### P0-09 高仓位门禁不是统一买权总闸

SCAP关闭`regime_overlay`时授权直接返回安全上限；`high_exposure_research_gate`主要传给catch-up。正常新开仓、加仓和替换并不都消费同一门禁。26日晚已经出现门禁false、目标仍达85%—95%、替换仍继续。

### P0-10 相关性与行业惩罚名义存在、实际未接线

`select_scap_one_lot_portfolio`定义`correlation_matrix`，但`mainline_v3`调用没有传入；候选也没有稳定`industry`字段。相关性惩罚实际为0，行业惩罚可能不执行，结果也没有交互惩罚明细。

### P0-11 优化目标内部仍有量纲错误

当前目标为：

```text
人民币gross_utility
- 人民币interaction_penalty
- 0.05 × 无量纲fragment_penalty
```

最后一项直接把无量纲数从人民币金额中相减，且最多0.05，几乎无效。平效用时又优先选择花钱更多的组合，与`allow_cash`冲突。

### P0-12 保存阶段不是可恢复产品流水线

`runner._save`先把alpha proposals、候选详情、layer validation、failure lab、生存/漂移/归因/质量报告同时放在内存中，然后统一写CSV。26日晚在`layer_validation_audit`附近死亡后，前面已计算的extra没有形成完整顶层产物。

### P1-01 概率置信区间忽略日期聚类和重叠标签

同一天数百个候选共享市场冲击，10日标签彼此重叠。普通Wilson区间近似把它们当独立伯努利样本，会高估有效样本量。需要按信号日期聚类，并使用`n_eff=(Σw)^2/Σ(w²)`和日期块bootstrap/贝叶斯后验。

### P1-02 预测失效没有降权熔断

26日晚闭合交易中，预期收益与实际收益相关系数-0.255、LCB与实际收益-0.316、人民币效用与实际收益-0.281。系统仍继续最大化该预测，没有rank IC、校准斜率或高分档收益倒挂熔断。

### P1-03 绝对金额Top15预筛选偏向高价整手

低价、单位资本效率高但单手绝对利润较小的候选可能在组合优化前被删除。应使用多维Pareto候选集。

### P1-04 风险协方差不足时接近fail open

原始60日协方差可能奇异；少持仓时出现`insufficient_covariance_symbols`，但没有保守行业/单股压力代理接管。

### P1-05 固定现金缓冲与净值比例未分层

固定2,000元在2万元时为10%，盈利后比例下降、亏损后比例上升。它可以保留为当前受控基线，但应与比例缓冲做独立A/B，不能和评分修复同时修改。

### P1-06 替换条件现金可能重复占用

原子注册使用`cash-reserved_cash+conditional_sell_cash`，而`reserved_cash`已包含当前替换买腿，可能重复占用。应改为逐订单`CashReservationLedger`。

### P1-07 因子风格集中没有成为组合约束

26日晚118个入选日-标的中102个为`size_style`。名义5只并不等于有效分散，需要主论点/家族约束。

### P1-08 目标持仓和冲突标签语义仍错误

- `target_holding_count`混合动态可达/最低数量；
- `holding_shortfall_count=0`不能证明达到策略期望；
- 替换双腿被计入动作冲突，混淆原子配对和真实模块矛盾。

### P1-09 WBS与代码状态不一致

- WBS-05.09写标准化效用，代码已变人民币；
- WBS-10.17要求统一LCB仲裁，代码仍固定优先级，新开仓又用point；
- WBS-10.20引用尚不存在的独立优化器；
- WBS-11.04仍保留胜率/盈亏比控制，而WBS-13.12已取消；
- WBS-08.08写成单优化器，代码实际两次选择；
- 旧详细规格方向正确，但变更记录把部分实现误写为完成。

## 2. 小资金特化统一数学模型

### 2.1 分层目标

不再使用任意权重把“收益、回撤、仓位、现金利用”相加：

1. 最大化`RobustExpectedNetProfit`；
2. 在第一层最优值容差内，最小化尾部损失、集中和换手；
3. 再最小化不可使用的现金碎片。

### 2.2 执行对齐预测

对股票`i`、决策日`t`、统一软决策期限`H=10`：

```text
r(i,t,H) = P_exit(i,t,H) / P_entry(i,t+1 executable) - 1
```

使用按日期聚类、时间衰减的经验贝叶斯模型：

```text
mu_post = trust × mu_group + (1-trust) × mu_global
trust = n_eff / (n_eff + k)
p_win ~ Beta(a0+wins_eff, b0+losses_eff)
```

盈利/亏损幅度分别收缩，同时保留按日期块bootstrap得到的完整收益场景。

输出必须包含后验均值、标准误、收益分位、downside CVaR、有效样本、样本外rank IC、校准斜率/ECE和漂移状态。

### 2.3 激进但不裸点估计

```text
robust_edge_rate = mu_post - kappa_model × se_cluster
```

预注册对照：

- `kappa_model=0.50`：激进；
- `1.00`：中性；
- `1.96`：保守。

若`rank_ic_lower<=0`、校准斜率<=0、有效样本不足或漂移失败，则`forecast_authority_weight=0`，回退柜评分排序，不能继续最大化错误预测。

### 2.4 动作级净利润

对动作`a`和场景`s`：

```text
DeltaWealth(a,s)
= value_after_action(s)
- value_if_no_action(s)
- exact_incremental_cost(a)
- funding_opportunity_cost(a)
```

基线分别是：

- 新开仓：持有现金；
- 加仓：维持原股数；
- 退出：继续持有；
- 替换：继续持有原股票；
- 再平衡：保持当前股数。

成本只扣一次。

### 2.5 整数手组合优化

决策变量`x(i,a)`为整数手。统一求解约束：

- 订单后现金不低于缓冲；
- 最多5只、无杠杆；
- 板块/日期整手规则；
- T+1可卖库存；
- 同股一个最终方向；
- 替换卖买原子性；
- 组合暴露不超过唯一授权；
- 单股结构上限和压力损失预算；
- 同行业/主论点集中上限。

候选集使用柜评分、robust edge rate、绝对利润、每个主论点和一手资金效率的并集后做Pareto裁剪，禁止只按人民币Top15。

### 2.6 小资金尾部风险

采用单手账户压力损失：

```text
stress_loss_amount_i
= one_lot_notional_i
× max(historical_gap_cvar_i, board_limit_stress, model_downside_quantile)
```

具体30%/35%/40%结构上限及压力预算必须独立实验；正确性修复期间保留现有40%对照，不同时调参。

### 2.7 胜率和盈亏比

- 主目标：robust成本后净利润；
- 健康门槛：成本压力PF和正净利润；
- 胜率：概率校准诊断；
- 盈亏比：尾部/退出诊断。

两者不再形成重复硬门槛。

## 3. 新接口合同

### 3.1 `ScoreContract`

建议文件：`functions/decision_council/contracts/score_contract.py`

```python
@dataclass(frozen=True)
class ScoreContract:
    symbol: str
    as_of_date: pd.Timestamp
    ranking_score: float          # [0,1]
    score_authority: str
    coverage: float               # [0,1]
    thesis: str
    family_scores: dict[str, float]
    contract_version: str
```

禁止包含收益率、概率和人民币金额。

### 3.2 `ForecastDistribution`

```python
@dataclass(frozen=True)
class ForecastDistribution:
    symbol: str
    as_of_date: pd.Timestamp
    entry_price_basis: str
    horizon_sessions: int
    gross_return_mean: float
    gross_return_se: float
    gross_return_quantiles: dict[str, float]
    downside_cvar: float
    p_win_posterior_mean: float
    p_win_lower: float
    effective_sample_size: float
    rank_ic: float
    rank_ic_lower: float
    calibration_slope: float
    calibration_ece: float
    authority_weight: float
    state: str                    # calibrated/prior_only/drifted/insufficient
    cost_inclusion_state: str     # gross_only
    contract_version: str
```

### 3.3 `ActionProposal`

```python
@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    decision_id: str
    symbol: str
    action_type: str
    source_module: str
    requested_lots: int
    baseline_action: str
    horizon_sessions: int
    score_contract_id: str
    forecast_contract_id: str
    scenario_delta_wealth: tuple[float, ...]
    expected_net_profit_amount: float
    robust_net_profit_amount: float
    downside_cvar_amount: float
    exact_cost_amount: float
    funding_cash_amount: float
    hard_veto_reasons: tuple[str, ...]
    replacement_pair_id: str
    contract_version: str
```

模块只能提案，不能生成订单。

### 3.4 `ExposureAuthorization`

```python
@dataclass(frozen=True)
class ExposureAuthorization:
    decision_id: str
    risk_exposure_ceiling: float
    cash_buffer_amount: float
    per_name_structural_cap: float
    per_name_stress_budget_amount: float
    portfolio_stress_budget_amount: float
    new_entry_allowed: bool
    add_allowed: bool
    replacement_allowed: bool
    blocking_reasons: tuple[str, ...]
    covariance_state: str
    fallback_risk_model: str
    contract_version: str
```

所有买权消费同一实例。

### 3.5 `ActionPlan`

建议文件：`integer_action_optimizer.py`

```python
@dataclass(frozen=True)
class ActionPlan:
    decision_id: str
    selected_proposal_ids: tuple[str, ...]
    rejected_proposals: tuple[dict, ...]
    target_lots_by_symbol: dict[str, int]
    expected_net_profit_amount: float
    robust_net_profit_amount: float
    downside_cvar_amount: float
    exact_cost_amount: float
    projected_cash: float
    projected_exposure: float
    projected_stress_loss: float
    objective_lexicographic_rank: tuple[float, ...]
    constraint_slacks: dict[str, float]
    solver_status: str
    contract_version: str
```

这是唯一有交易权的策略产物。

### 3.6 `CashReservationLedger`

```python
reserve(order_id, amount, funding_type)
reserve_pair(pair_id, sell_floor_proceeds, buy_required)
release(order_id, reason)
settle(fill_id, actual_amount)
available_after_reservations()
```

### 3.7 执行层

```python
register_action_plan(
    plan: ActionPlan,
    market_rules: TradingRuleSnapshot,
    account: AccountSnapshot,
) -> RegistrationResult
```

执行层只允许因价格/交易状态变化、T+1库存、涨跌停/停牌、实际现金、数量规则或原子卖腿未成交而拒绝。禁止再次读取综合分、概率和趋势。

## 4. 防止引发新问题的迁移

### Phase 0 黄金重放

- 冻结运行身份；
- 建立日级、订单级、成交级黄金摘要；
- 先不改经济参数；
- 新增字段schema registry。

### Phase 1 单位与语义隔离

- 新增Score/Forecast合同；
- 旧字段双写并标记`legacy_read_only`；
- score恢复0—1；
- 金额统一`_amount`，收益统一`_rate`，概率统一`_probability`。

### Phase 2 校准修复

- 下一事实可成交时点标签；
- gross收益不扣成本；
- prior-only无交易预测权；
- 日期聚类有效样本和漂移熔断；
- 使用2025年前冻结校准样本，避免回测初期伪先验。

### Phase 3 提案影子链

- 所有模块只输出提案；
- 旧策略继续交易，新提案只写shadow ledger；
- 每个旧订单必须追溯提案，否则记`unowned_order`。

### Phase 4 唯一整数动作优化器

- 新优化器同时处理全部动作；
- 移除两次选择权；
- SCAP连续组合器只作诊断；
- 相关性、行业、主论点和压力场景真正接线；
- 使用分层目标。

### Phase 5 执行与现金预留

- 执行只消费ActionPlan；
- 引入现金预留账本；
- 替换使用条件现金和实际卖腿成交；
- 部分成交后重算剩余买腿；
- 重启/重放幂等。

### Phase 6 统一风险授权

- 新开仓、加仓、替换共同消费ExposureAuthorization；
- 协方差不足时使用保守代理；
- 研究准入、在线风险和硬安全退出分开；
- `allow_cash`不以“花钱更多”打破平局。

### Phase 7 报告、Web与保存

- 分开真实冲突与替换双腿；
- 重命名持仓目标字段；
- save改为产物DAG逐表构建、临时写入、原子改名和释放内存；
- `artifact_manifest.json`记录每项状态；
- 重审计可独立子进程。

### Phase 8 经济验证

按纯函数→5日→含买卖/替换/加仓的20日→同身份180日A/B→年份/状态切片→成本压力→未触碰前瞻顺序。每阶段只改变一个经济变量。

## 5. 验证矩阵

### 单位/接口

- score、probability范围；
- rate与amount不得直接相加；
- gross-only才能进入动作估值；
- schema不匹配fail closed；
- 缺失不得填0。

### 数学性质

- 候选行顺序置换不改变计划；
- 复制候选不能获得双重权；
- 同股买卖互斥；
- 成本增加不能提高效用；
- 不确定性增加不能提高robust profit；
- 预算收紧不能扩大可行集；
- 缺相关性/行业时明确fallback。

### 概率

- 样本0时authority=0；
- 成熟日前不进入历史；
- 日期聚类有效样本小于原始行数；
- 预测反向自动熔断；
- 报告ECE、Brier、斜率和rank IC；
- 重叠标签用block bootstrap。

### 动作/执行

- 硬安全退出优先；
- 软退出与持有同期限；
- 两类加仓独立条件校准；
- 替换覆盖双边成本；
- ActionPlan外无订单；
- T+1、涨跌停、最低佣金、部分成交、公司行动、现金/NAV/库存守恒。

### 产品

- 5日初始化到保存；
- 20日完整Excel/Web；
- 180日内存峰值/ETA；
- 保存故障注入；
- owner死亡；
- 附加审计失败但核心账本可用；
- 页面不把不完整run当完成。

## 6. WBS结论

现有WBS父级划分合理，不需要推倒重建；但缺少字段类型/单位、概率权威、唯一整数ActionPlan和流式原子保存末梢，部分末梢还把设计目标误写成已实现。

本次应新增或修订：

- WBS-00.08；
- WBS-05.09/05.10；
- WBS-06.10/06.11；
- WBS-08.08/08.14/08.15；
- WBS-09.13；
- WBS-10.15/10.17/10.20/10.21；
- WBS-11.04/11.07/11.08；
- WBS-14.17/14.18；
- WBS-15.12；
- WBS-16.17/16.18。

修订后的WBS可作为施工控制文件，但不表示代码已经完成。

## 7. 参考依据

- 概率输出需在独立校准数据上验证：[Niculescu-Mizil & Caruana, Predicting Good Probabilities with Supervised Learning](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)。
- 小资金最多5只、一手、成本和持仓数约束属于基数约束的组合优化：[Bienstock, Optimal Cardinality Constrained Portfolio Selection](https://pubsonline.informs.org/doi/pdf/10.1287/opre.2013.1170)。
- 接受较大回撤仍可保留增长—回撤概率约束：[Busseti, Ryu & Boyd, Risk-Constrained Kelly Gambling](https://web.stanford.edu/~boyd/papers/pdf/kelly.pdf)。
- 多次修改择优需要校正选择偏差：[Bailey & López de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)。

## 8. 最终建议

下一步不应直接继续运行当前180日版本，也不应只把point改回LCB。先实施Phase 1和Phase 2：单位隔离、prior-only禁权、成交标签对齐、成本只扣一次、预测倒挂降权。通过5日工程链后，再实施唯一ActionPlan。
