# SCAP-V3 小资金激进精简版：完整模块闭环、消融与防复发方案

## 0. 决策摘要

建议新建独立研究身份：

```text
small_capital_aggressive_profit_v3_lean
control_mode = aggressive_lean
```

不要继续在现有SCAP-V2身份上原地叠补丁。V3 Lean的核心不是“把所有阈值调低”，而是：

1. 保留PIT、可交易性、现金、整手、T+1、库存、费用、单股灾难损失和数据完整性硬约束；
2. 删除重复选择器、连续分配前置交易权和多模块软门槛硬AND；
3. 新开仓、盈利加仓、亏损摊平、替换和软退出使用同一预测期限、同一激进风险折扣和同一人民币增量财富定义；
4. 所有动作先生成无交易权提案，每日只调用一次整数动作优化器；
5. 执行层只复核当日事实，不再读取评分、概率、趋势或“质量”二次否决；
6. 用开始日前PIT历史warm-up校准器，消除“回测起点决定前43日空仓”的路径依赖；
7. 以逐模块单变量消融决定哪些模块值得保留，不能凭最终收益一次性选择整套参数。

## 1. 用户目标与不可混淆的边界

### 1.1 目标

- 初始资金：20,000元。
- 无杠杆、现金不得为负。
- 接受较大净值波动。
- 主目标：成本后期末净利润。
- 风格：少量集中持股、允许等待、赢家优先加仓、允许一手离散精确搜索。
- 胜率不是主目标；盈亏比和PF是健康诊断。

### 1.2 “激进”的准确含义

激进应体现在：

- 模型不确定性惩罚较低；
- 更高但仍受授权的目标暴露；
- 更少持股、更高单股软上限；
- 赢家更快加仓；
- 在净效用覆盖完整成本时允许主动替换；
- 不因普通波动、单个软分数或机构式集中度门槛拒绝交易。

激进不等于：

- 用未来数据；
- 用未成熟标签；
- 忽略最低佣金、滑点和涨跌停；
- 强制满仓；
- 无条件摊低亏损；
- 允许负现金、T+0卖出或超过40%单股硬上限；
- 预测已经漂移仍继续最大化错误方向。

## 2. 推荐产品参数起点

这些是施工后的首个预注册研究起点，不是从历史最优网格挑出的“最佳参数”。

| 项目 | V3 Lean起点 | 性质 |
|---|---:|---|
| 初始现金 | 20,000元 | 固定 |
| 最多持股 | 5只 | 硬上限 |
| 软目标持股 | 4只 | 优化偏好，不强制 |
| 现金缓冲 | 1,000元 | 硬约束；以2,000元作单变量对照 |
| 单股结构上限 | 40% NAV | 硬约束 |
| 单股软惩罚起点 | 30% NAV | 软效用惩罚 |
| 正常市场战略暴露预算 | 90% | 风险预算，不是强制买入 |
| 弱市场战略暴露预算 | 65% | 风险预算 |
| 高风险市场战略暴露预算 | 35% | 风险预算 |
| 软动作期限 | 10个交易日 | 新开仓/加仓/替换统一 |
| 激进不确定性系数 | `kappa=0.50` | 所有软动作统一 |
| 新开仓手数域 | 1至结构上限内可行手数 | 优化器决定 |
| 赢家加仓 | 开启；每次1手，最多2层 | 默认 |
| 亏损摊平 | 默认关闭；最后单独消融 | 研究模块 |
| 主动替换 | 默认关闭；赢家加仓后单独消融 | 研究模块 |
| 单股灾难损失线 | -15%净收益附近，另做-12%对照 | 硬安全候选 |
| 账户回撤警报 | 30% | 披露/降低新增风险 |
| 新风险冻结 | 40%账户回撤 | 硬上限，不强制卖出现有仓 |

为何建议先把固定缓冲从2,000降为1,000：2万元账户的2,000元缓冲天然锁住10%资金，而且整手离散会产生额外现金碎片。1,000元仍覆盖费用和小额误差，但该变化必须与架构修复分开做单变量A/B。

为何亏损摊平不作为默认激进模块：提高对盈利持仓的资本暴露与扩大已证伪持仓的亏损不是同一种“激进”。前者顺着已观察到的价格/论点确认，后者可能放大错误模型。亏损摊平只有在独立消融证明成本后增量财富为正后才能进入默认版。

## 3. 唯一权威模块链

```text
运行身份 / PIT时点
  → 可投资与可交易事实
  → 因子柜 ScoreContract
  → PIT warm-up后的 ForecastDistribution
  → AccountSnapshot + PositionSnapshot
  → ActionProposalFactory
       ├─ hold/cash
       ├─ new_entry
       ├─ winner_add
       ├─ loser_add（实验）
       ├─ reduce/soft_exit
       └─ atomic_replacement_pair（实验）
  → 唯一 ExposureAuthorization
  → 每日唯一 IntegerActionOptimizer
  → 唯一 ActionPlan
  → CashReservationLedger
  → factual-only ExecutionAdapter
  → pending / fills / positions / cash / NAV
  → trade pairing / performance / ablation ledger / Web
```

### 3.1 每层的唯一写权限

| 语义 | 唯一写入者 | 其他模块权限 |
|---|---|---|
| 0—1候选排名分数 | `cabinet_native_scoring` | 只读 |
| 预测收益分布/权威状态 | `RollingEntryCalibrator`/forecast adapter | 只读 |
| 动作级人民币情景财富 | `ActionProposalFactory` | 只读 |
| 暴露/现金/压力预算 | `ExposureAuthorizationBuilder` | 只读 |
| 目标手数和选中提案 | `IntegerActionOptimizer` | 只读 |
| 订单注册 | `ExecutionAdapter` | 只接收ActionPlan |
| 现金预留 | `CashReservationLedger` | 不允许私有重算 |
| 现金、库存、NAV | 账户/执行引擎 | 报告只读 |

任何同一语义出现第二个写入者，启动时fail closed。

## 4. 模块保留、精简和移除交易权

### 4.1 保留

- `investable_universe.py`：PIT证券状态、板块权限、停牌/ST等事实。
- `cabinet_native_scoring.py`：因子角色和0—1排名分数。
- `entry_calibration.py`：改造为PIT warm-up和连续收缩权威。
- `action_utility.py`：统一增量财富，但由一个资金档位风险口径驱动。
- `scap_v2_contracts.py`：升级合同版本。
- `integer_action_optimizer.py`：保留为唯一策略权威。
- `cash_reservation_ledger.py`、`pending_orders.py`、`execution_runtime.py`：事实执行与幂等。
- `security_trading_rules.py`、费用与成本模块：事实硬约束。
- 账户、交易配对、报告和Web模块。

### 4.2 降级为证据或提案模块

| 当前模块/字段 | V3 Lean职责 |
|---|---|
| `mainline_v3.py` | 只生成ScoreContract、候选Pareto并集；不得写`entry_confirmed/target_weight` |
| `position_lifecycle.py` | 只生成PositionSnapshot、退出事实和动作特征；不得写`add_allowed`作为交易权 |
| `active_replacement.py` | 只生成原子替换提案对；不得先卖后判买 |
| `decision_arbitration.py` | 只处理不可比较的硬退出优先级和原因规范；软动作交给优化器 |
| `allocation.py` | 非SCAP继续使用；SCAP只做影子对照 |
| 市场状态模块 | 只输出ExposureAuthorization输入，不直接选股 |
| high-exposure research gate | 只决定风险预算上限，不分别否决新入场/加仓/替换 |

### 4.3 从SCAP实盘链移除

- `policy._select_scap_discrete_entries`的交易权；
- SCAP连续组合分配器的目标权重权威；
- `_apply_unique_action_plan`之前的任何整数选择；
- `entry_confirmed`作为SCAP交易权字段；
- `add_allowed`作为SCAP交易权字段；
- `force_deploy`买权；
- 订单形成后的评分、概率、趋势、支持分位数二次否决；
- 不同动作各自私有的point/LCB选择；
- 把目标仓位回写为实际仓位的循环公式。

旧函数暂不物理删除，先放到`legacy_shadow_only`路径；经过两次发布周期无调用后再由用户手工决定清理，避免批量删除。

## 5. 预测与校准

### 5.1 PIT warm-up

每次正式回测在`trade_start`前读取至少252个交易日的历史：

```text
warmup_start < trade_start
warmup期间：
  更新特征、候选快照、下一可成交开盘和成熟标签
  不更新现金、持仓、订单、成交、NAV或绩效
trade_start：
  冻结warmup manifest和calibrator_state_hash
  才允许产生ActionProposal
```

性质要求：给定相同数据截止、同一决策日和同一warm-up范围，仅改变绩效统计起点，不得改变ScoreContract、ForecastDistribution和ActionPlan。

### 5.2 连续收缩，不用“29条全禁、30条全开”

建议：

```text
trust = n_eff / (n_eff + 40)
mu_shrunk = trust * mu_bucket + (1-trust) * mu_global
se_cluster = 日期块标准误
robust_edge = mu_shrunk - 0.50 * se_cluster
```

- 全局成熟样本不足80：预测无交易权，但因子分数仍可审计。
- 桶样本不足：向全局/家族先验连续收缩，不硬切换。
- rank IC、校准斜率和ECE用滚动窗口报告。
- 单次rank IC≤0不立即冻结；连续3次月度评估且“IC上界≤0或斜率≤0”才撤权。
- `drift_warning`降低authority weight；`drifted`才撤权。
- 新开仓、两类加仓和替换共同读取：

```text
decision_return_basis = shrunk_point_minus_0.50_cluster_se
```

不得再出现新开仓point、补仓LCB。

## 6. 动作提案

所有软模块只能返回`ActionProposal[]`，不得返回订单或目标权重。

### 6.1 新开仓

为Pareto候选生成1至可行最大手数提案。软证据包括：

- 规则排名；
- 收缩后10日预期收益；
- 资金效率；
- 风险/流动性；
- 论点族相关性。

硬否决只有：

- 非PIT可投资；
- 无可靠价格；
- 市场/板块权限不允许；
- 一手超过40%结构上限；
- 数据或合同无效。

### 6.2 赢家加仓

默认开启。建议将+4%/+8%作为软触发中心，而不是硬门：

```text
winner_confirmation =
  sigmoid((unrealized_return - trigger) / scale)
  × thesis_retention
  × trend_persistence
```

它进入动作效用，不单独硬否决。硬约束只保留：

- 已持仓且非退出状态；
- 最大2个加仓层；
- 订单后不超过40%；
- ActionPlan后现金和压力预算可行。

### 6.3 亏损摊平

单独实验，默认关闭。若开启：

- 最多1层、1手；
- 只在-4%至-10%区间产生提案；
- 低于灾难线不允许摊平；
- 论点已明确失效、退市/ST风险或极端下跌尾部状态为硬否决；
- 其他趋势、支持分位、量价证据进入效用，不再硬AND。

### 6.4 软退出

继续持有是基线，卖出增量财富必须扣卖出成本和卖后机会成本。利润回撤、信号衰减、陈旧、趋势破坏均作为情景输入，不各自直接下单。

硬退出仅限：

- 不可继续持有的证券状态；
- 账户/数据安全；
- 预注册灾难损失线；
- 无法估值或重大公司行动失败时的fail-closed状态。

### 6.5 主动替换

只生成一个原子pair：

```text
DeltaWealth_replace
= challenger_after_cost
 - incumbent_hold_value
 - sell_cost - buy_cost
 - slippage_stress
```

同一pair进入一个ActionPlan；卖腿未成交，买腿不得执行。

## 7. 唯一整数动作优化

### 7.1 决策变量

直接优化订单后每只股票的整数手数，而不是先算连续权重再四舍五入。

### 7.2 字典序目标

```text
第一层：最大化全组合 robust_expected_net_profit_amount
第二层：在第一层0.5%或1元容差内，最小化downside_CVaR、灾难损失和论点集中
第三层：最小化完整交易成本
第四层：最小化无法组成一手的现金碎片
```

现金碎片永远不能补偿负净效用。

### 7.3 硬约束

- 现金非负且不低于缓冲；
- 无杠杆；
- 最多5只；
- 单股不超过40%；
- T+1库存；
- 日期/板块整手；
- 同股只能有一个最终方向；
- 替换pair原子；
- 组合压力损失不超过授权；
- 新风险冻结时不得增加总风险。

相关性使用Ledoit-Wolf式收缩协方差；样本不足时回退到论点族和单股压力上限，不允许零矩阵fail open。

### 7.4 一次调用断言

每个`decision_id`：

```text
optimizer_invocation_count == 1
action_plan_count == 1
selected_order.plan_id == action_plan.plan_id
```

任何违反均使当天fail closed，并生成可见错误。

## 8. 仓位语义

必须同时保留：

1. `strategic_exposure_budget`：市场/账户允许的风险预算；
2. `signal_supported_exposure`：正增量财富提案支持的期望仓位；
3. `integer_feasible_exposure`：整手、现金和槽位可达仓位；
4. `planned_exposure`：ActionPlan订单后预计仓位；
5. `actual_exposure`：成交后真实仓位。

严禁：

```text
没有信号 → desired = actual → gap = 0
```

正确披露：

```text
signal_cash_drag = strategic_budget - signal_supported
lot_cash_drag = signal_supported - integer_feasible
execution_drag = planned - actual
```

三项必须能够对账。

## 9. 精简后的开关数量

生产候选只保留五类经济开关：

| 开关 | 默认 |
|---|---|
| `winner_add` | on |
| `loser_add` | off |
| `soft_exit` | on |
| `active_replacement` | off |
| `market_exposure_overlay` | on |

不再把每个软指标都做布尔开关。趋势、量价、支持分位、不确定性、成本和集中度进入统一动作效用；只有事实硬约束是布尔门。

## 10. 完整消融方案

### 10.1 Correctness阶段：只验证接口，不比较收益

| 编号 | 唯一变化 | 验收 |
|---|---|---|
| C0 | 冻结26日上午可复现黄金运行 | 固定输出hash和关键账本 |
| C1 | Score/Forecast/Proposal/Plan双写 | 旧交易不变，单位合同全通过 |
| C2 | 加入PIT warm-up | 同一决策日起点不变性通过 |
| C3 | 所有动作统一`kappa=0.50` | 不再出现point/LCB分裂 |
| C4 | 新链影子提案 | 不下单，逐日对账所有动作 |
| C5 | 切换唯一优化器 | 每日调用一次，目标手数守恒 |
| C6 | factual-only执行 | Plan后无软否决 |
| C7 | 旧SCAP分配路径降级影子 | 实盘调用图只有一条 |

任一阶段失败不得进入收益消融。

### 10.2 经济模块消融：严格单变量累加

固定基础版`B0`：

```text
PIT warm-up + 规则/校准入场 + hold + 灾难硬退出
无赢家加仓、无亏损摊平、无主动替换、无普通软退出
```

顺序：

| 版本 | 相对上一版唯一变化 | 去留问题 |
|---|---|---|
| B0 | 基础版 | 入场本身是否有成本后优势 |
| B1 | +赢家加仓 | 是否提高终值且不恶化尾部过多 |
| B2 | +软退出 | 是否改善左尾/PF而不砍掉右尾 |
| B3 | +主动替换 | 完整成本后是否增加净利润 |
| B4 | +亏损摊平 | 是否真有增量价值；最后评估 |
| B5 | +市场暴露overlay | 是否改善跨状态稳定性 |

某模块未通过即从后续版本移除，不允许为了挽救它同时调另一个模块。

### 10.3 资本参数消融

只对经济模块已经冻结的版本依次比较：

1. 缓冲2,000元 → 1,000元；
2. 软目标持股5只 → 4只；
3. 单股软惩罚25% → 30%；
4. 正常市场战略预算85% → 90%。

硬上限始终为5只、40%、无杠杆。

### 10.4 因子消融

不对74个因子做2^74组合。按经济家族做leave-one-family-out：

- momentum；
- reversal；
- liquidity/orderflow；
- volatility/risk；
- value/quality；
- size/style；
- growth/cashflow。

若移除一个家族反而稳定提高成本后净利润，该家族降为诊断；相近因子先聚类，只对代表因子做替换实验。

### 10.5 窗口

- 构造性5日：强制覆盖新开仓、赢家加仓、亏损摊平、替换、退出和失败成交。
- 60日工程窗：验证warm-up、真实成交和中断保存。
- 多段180日development窗：牛/震荡/弱市至少各一段。
- 338日已污染窗口：只做回顾性鲁棒性，不称最终样本外。
- 冻结后至少60交易日前瞻纸面窗口：最终新增证据。

## 11. 评价与停止规则

### 11.1 主指标

```text
terminal_net_profit_after_all_costs
```

并列披露：

- 账户最大回撤；
- 压力成本后净利润；
- 闭合交易PF；
- 期末未平仓PnL；
- 实际平均仓位和现金拖累；
- 单股/论点集中；
- 换手与最低佣金占毛利润比例。

### 11.2 模块保留规则

模块进入下一阶段至少满足：

- 多段合并成本后净利润增量为正；
- stationary/block bootstrap增量利润中位数为正；
- 主要切片没有单一月份贡献绝大多数利润；
- 1/1.5/2倍滑点及0/1/5元最低佣金压力下不出现结构性崩溃；
- 没有PIT、现金、库存、订单、ActionPlan、公司行动或估值错误。

样本不足写“证据不足”，不得写“失败”或降低门槛求通过。

### 11.3 多重试验控制

- 每个实验登记`experiment_family_id`、父版本和唯一变化。
- 同一实验族所有尝试数进入PBO/DSR或Reality Check披露。
- 观察过的338日窗口不得再次承担最终选择职责。
- 预注册停止规则；达到预算后不继续试直到出现正结果。

## 12. 如何防止再次发生

### 12.1 WBS必须是状态机，不是叙述

每个末梢增加：

```text
status = proposed | implemented | verified | released | deprecated
code_owner
single_writer
input_contract
output_contract
unit
authority
tests
last_verified_code_fingerprint
```

“报告写已完成但代码仍两次调用”必须由自动检查阻断。

### 12.2 自动生成实际调用图

CI/验证脚本每天生成SCAP权威调用图，并断言：

- `optimize_action_proposals`实盘路径每日一次；
- `entry_confirmed/add_allowed/target_weight`不再是V3 Lean交易权；
- ActionPlan后没有软评分读取；
- 每张订单能反查唯一proposal和plan；
- 每个单位字段只有一个写入者。

### 12.3 变更预算

一次受控实验只允许：

- 一个经济模块开关；或
- 一个资本参数；或
- 一个正确性修复。

如果一次提交同时改变评分、预测、仓位和执行，必须拆分，不能出收益比较结论。

### 12.4 黄金回放与变形测试

固定至少三套黄金数据：

- 无交易；
- 一手新开仓→赢家加仓→退出；
- 替换卖腿失败→买腿不得执行。

性质测试至少包括：

- 候选行顺序改变，ActionPlan不变；
- 费用上升，买入数量不能增加；
- 可用现金下降，买入数量不能增加；
- 复制候选，不改变原提案选择；
- 关闭一个动作，只能删除该动作；
- 回测绩效起点改变但warm-up不变，同日决策不变；
- ActionPlan重放不重复成交、扣款或收费。

### 12.5 运行身份与结果隔离

运行身份必须包含：

- Git/code fingerprint；
- WBS版本；
- 因子柜hash；
- 数据/PIT manifest；
- warm-up范围与calibrator hash；
- 成本、资金、动作开关；
-优化器和合同版本；
- 污染状态、实验族和父版本。

身份不同的结果不得自动进入同一排名表。

### 12.6 中断可审计

每个交易日结束至少流式保存：

- ScoreContract摘要；
- Forecast authority；
- 所有ActionProposal及拒绝原因；
- 唯一ActionPlan；
- ExposureAuthorization；
- 现金预留；
- pending和成交；
- 五层仓位；
- NAV。

Ctrl+C后仍能回答“最后一天为什么没买、为什么没补、哪个模块否决”，不能依赖最终保存阶段才生成审计。

### 12.7 发布制度

只有同时满足以下条件才能把WBS状态从verified改为released：

- 接口/单位/调用图测试；
- 构造链；
- 60日工程链；
- 多窗经济消融；
- 成本压力；
- PBO/多重试验披露；
- 前瞻纸面观察；
- 人工审阅WBS与实际调用图一致。

## 13. 施工包

### Phase A：架构止血

- 新V3 Lean身份；
- 实际权威调用图；
- 禁止第二优化器和连续分配交易权；
- WBS状态字段。

### Phase B：校准与统一风险口径

- PIT warm-up；
- 连续收缩；
- `kappa=0.50`全动作统一；
- 起点不变性测试。

### Phase C：提案工厂

- 新开仓、赢家加仓、亏损摊平、退出、替换统一提案；
- position lifecycle只输出证据；
- 提案影子对账。

### Phase D：一次联合优化

- 直接优化目标手数；
- 收缩协方差/论点族回退；
- 单次调用、置换和现金单调性测试。

### Phase E：执行收口

- ActionPlan唯一订单入口；
- factual-only执行；
- 原子替换和幂等现金。

### Phase F：审计与Web

- 五层仓位；
- 动作漏斗；
- warm-up和authority；
- 中断后可读。

### Phase G：经济消融

- B0→B5；
- 资本参数；
- 因子家族；
- 多窗、成本压力、PBO/DSR；
- 冻结前瞻纸面版本。

## 14. 文献依据

- Busseti、Ryu、Boyd的风险约束Kelly把增长目标与回撤概率约束同时建模，支持“激进参数应降低风险厌恶，而不是删除风险边界”：https://web.stanford.edu/~boyd/papers/kelly.html
- Ledoit与Wolf指出样本协方差的估计误差会严重扰动组合优化，支持使用收缩协方差而非缺样本时零矩阵放行：https://ledoit.net/honey_abstract.htm
- Cai、Judd、Xu讨论交易成本下的动态组合优化和no-trade region，支持把成本放进统一动作目标而非多层阈值重复否决：https://www.nber.org/papers/w18709
- Niculescu-Mizil与Caruana展示模型分数不等于可靠概率、校准需要独立数据，支持分离ScoreContract和ForecastDistribution：https://doi.org/10.1145/1102351.1102430
- Politis与Romano的stationary bootstrap为弱依赖时间序列的标准误和置信区间提供方法依据：https://doi.org/10.1080/01621459.1994.10476870
- White的Reality Check针对数据反复使用和模型选择偏差：https://doi.org/10.1111/1468-0262.00152
- Bailey等人的PBO框架专门估计投资回测过拟合概率：https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253
- Bailey与López de Prado的Deflated Sharpe Ratio校正多重选择和非正态收益造成的表现膨胀：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

## 15. 最终建议

推荐目标版本不是“所有开关打开的E4”，而是：

```text
PIT warm-up
+ 因子柜/收缩预测
+ kappa=0.50统一激进效用
+ 一次整数ActionPlan
+ 1,000元缓冲
+ 最多5只/软目标4只
+ 40%硬上限/30%软惩罚
+ 赢家加仓
+ 简化软退出
+ factual-only执行
```

主动替换和亏损摊平分别作为后续独立模块；只有消融证明成本后增量为正才加入。这样仍然是集中、较高暴露、容忍较大波动的小资金激进策略，但不会再次依靠关闭校准、强制满仓或无条件补亏损仓来制造“看起来更激进”的假象。
