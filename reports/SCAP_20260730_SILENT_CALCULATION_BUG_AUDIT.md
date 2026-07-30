# SCAP 不报错但影响计算的缺陷审计（2026-07-30）

## 1. 审计边界

- 审计对象：`run20260730_200746` 及其当前代码路径。
- 本轮只读检查计算语义、金融单位、模型状态、ActionPlan 血缘和报表口径；未修改策略、参数、执行、账户或报表代码，未重新运行回测。
- 20 日运行的账户重建、成交股数、次日执行、订单唯一性和实际 ActionPlan 血缘均通过。以下问题属于“代码能运行、部分既有测试也通过，但计算值或字段含义不正确/不完整”。

## 2. 已影响本次 20 日产物

### P0-1 基准超额收益公式与字段名称不一致

`analytics.py` 将每日算术差 `r_account-r_benchmark` 复利为 `excess_net_value`。这不是组合相对基准的几何财富比；正确的相对财富应为 `NAV_account/NAV_benchmark`。

本次运行：

- 账户终值：`1.0219618770730023`
- 基准终值：`1.066736768162`
- 当前报表 `benchmark_excess_return`：`-5.1073387571%`
- 几何相对收益 `1.0219618770730023 / 1.066736768162 - 1`：约 `-4.19737019%`
- 简单总收益差：约 `-4.47748911%`

三个数含义不同。当前字段名没有揭示它是“每日收益差的复利链”，会直接影响策略相对基准的判断。

### P0-2 风险模型的“计划已使用”和“运行未使用”互相矛盾

- 20 个 ActionPlan 全部写 `risk_model_used=covariance`。
- 20 个实际暴露日全部处于 covariance `cold_start`，`covariance_risk_model_used=False`。
- 唯一买入日计划暴露约 `84.18%`，但 `marginal_risk_penalty_amount=0`。

根因是 ActionPlan 只要收到一个全局非空协方差矩阵就标记为已使用；它没有验证最终入选股票在矩阵中的覆盖率，也没有遵守 runtime maturity 的冷启动状态。计划字段因此把“矩阵存在”错误表达成“风险模型对所选方案有效”。

### P0-3 缺失协方差被填成 0，会系统性低估未知相关性风险

候选协方差只取前 80 个候选；历史不足的股票会被删列，缺失配对随后用 0 填充。0 协方差代表“已知不相关”，不是保守假设。对小资金、高集中度、最多 5 只股票的组合，这会降低联合选择的边际风险罚金。

### P1-1 有效部署目标并不真正“整数可行”

`integer_feasible_exposure` 的估算：

- 只检查每个候选单独是否买得起，没有逐笔扣减累计现金；
- 新候选可取 `top_n` 个，没有先扣除当前持仓已经占用的槽位；
- 使用成本内含的一手权重作为市场暴露。

因此该字段可能高于真正可由现金、槽位和整数手共同实现的暴露。优化器硬约束仍会阻止超买，但“部署缺口”罚金会基于不可实现目标参与排序。

### P1-2 signal-supported 暴露把实际上不可选的提案计为正信号

信号支持判断使用 `robust_profit > 0`；优化器实际准入使用 `robust_profit-authority_penalty > 0`。本次 20 日产物中有 82 个新开仓提案满足前者、但不满足后者。结果是信号支持暴露和部署目标被高估，进而影响现金缺口罚金。

### P1-3 ActionPlan 的目标值缺少完整分解

优化目标还扣除了 `soft_thesis_penalty`，但 ActionPlan 未保存该字段。唯一买入日：

- 入选提案稳健利润合计约 `74.9347` 元；
- authority penalty 约 `16.8356` 元；
- 未落盘的 soft thesis penalty 约 `1.6889` 元；
- 最终 `robust_net_profit_amount` 约 `56.4102` 元。

现有字段不能从账本完整复算目标值；而且 `robust_net_profit_amount` 实际是扣除多种组合罚金后的优化目标，不再是字面意义的“稳健净利润”。

### P1-4 “最优性已证明”只对启发式裁剪后的候选集成立

优化器先用 `_pareto_reduce` 把候选压到最多 24 个，再做穷举，并写 `solver_optimality_proven=1`。本次唯一买入日有 88 个可执行正收益候选，实际搜索集为 24 个。当前裁剪并非严格 Pareto 支配证明，而是按单位收益/排名/分数排序后截断。因此只能宣称“裁剪后集合内最优”，不能宣称原始可行提案全集最优。

## 3. 当前结果未触发、但配置或市场状态变化时会影响计算

### P0-4 唯一 ActionPlan 后仍存在 force-deploy 补单旁路

`runner.py` 在 Lean ActionPlan 生成后无条件调用 `_augment_force_deploy_diversify_orders`。当 `capital_usage_mode=force_deploy` 时，该函数可追加没有 ActionProposal/ActionPlan 血缘的买单。本次配置为 `allow_cash`，所以 4 个成交与 4 个 selected proposal 完全一致；但切换配置后唯一计划约束会失效。

### P0-5 卖出回款的成本单位错误

退出提案的 `cash_release_amount` 使用：

`当前权重 × NAV - cost`

其中 `cost` 来自候选的一手、往返成本。真实退出回款应按当前全部持股和卖出价计算，并只扣卖出侧费用。当前公式对多手持仓不按股数缩放；对一手持仓还会重复扣除已成为沉没成本的买入费。20 日窗口没有卖出，因此本次未触发。

### P0-6 计划中的“市场暴露”和“现金占用”使用同一成本内含量

`mainline_v3_one_lot_cash_required` 包含估算交易成本，但 Lean 同时把它用于：

- `exposure_delta`；
- 单股结构权重约束；
- 预期收益的本金；
- 生命周期加仓的名义本金。

金融上应拆为：

- 市场暴露：价格 × 股数；
- 买入现金需求：市场金额 + 买入侧精确费用；
- 收益本金：市场金额；
- 往返费用：作为独立扣减。

当前做法会小幅高估暴露和毛收益，并可能在约束边界改变方案。

### P0-7 持仓股票若不在当日候选表，槽位可能被漏计

Lean 的 `current_lots` 从候选行迭代中构造，精确手数也只在该循环内复制。若停牌、缺数或候选构建异常使已持仓股票不在当日候选表，该持仓不会进入优化器的槽位集合，优化器可能允许额外买入。实际权重仍可能留在账户中，但持仓数量硬约束已被低估。

### P1-5 loser add 绕过生命周期授权

开启 loser averaging 后，Lean 仅按未实现收益区间和层数生成 `loser_add`，没有要求生命周期模块的 `add_allowed`、`add_decision_type`、冷却、尾部风险、review 和 authority 快照。当前档案关闭 loser averaging，故本次未触发。

### P1-6 Lean 的 active replacement 授权没有对应提案生成器

Lean 会把 `active_replacement_enabled` 写入授权，但本模块没有生成 `replacement_buy/replacement_sell` 提案。旧 policy 路径有替换生成器，但 aggressive Lean 在入口处直接旁路旧 policy。因此在 Lean 模式打开替换开关可能只是“显示已开启、实际上无动作”。

### P1-7 authority 兼容兜底存在 fail-open

缺失正式校准字段时，`attach_scap_v31_authority` 可依据 legacy return/utility 合成 Tier A。该兼容行为适合构造测试，不应成为生产路径兜底；否则字段缺失不会报错，反而可能放行。

## 4. 审计型字段的命名风险

`scap_profit_objective.py` 使用决策日候选的 `forward_return_20d`、一手现金和估算成本，输出名却包含 `realized_net_profit`。它不是按次日真实成交价、真实费用和实际持有路径计算的成交实现盈亏，而是决策日口径的事后前瞻标签。应改名为 `counterfactual_forward_*_audit`，并与真实 fill/trade-pair PnL 分开。

`invested_capital_return` 也来自按日收益除以当日暴露的在线近似；代码注释承认它不是 fill-level 精确归因，但汇总字段没有显式标记 approximate。

## 5. 建议修复顺序

1. 先修 P0：相对基准公式、协方差实际覆盖/冷启动、卖出净回款、市场暴露与现金单位拆分、缺失持仓槽位、ActionPlan 后补单旁路。
2. 再修 P1：真正的整数可行目标、authority 后正收益口径、完整目标分解、最优性声明、loser add 授权、replacement 可达性和 authority fail-closed。
3. 最后修字段语义：区分几何相对收益/每日差收益链/简单收益差，区分反事实前瞻标签/真实成交盈亏，给近似归因加显式状态。
4. 每项必须先加失败测试，再改代码；测试至少覆盖多手退出、最低佣金、停牌持仓缺候选、协方差缺覆盖、force-deploy、原始候选裁剪、authority 缺字段和基准公式。
5. 修复后重新跑同一个 `experiment_spec_hash` 的 20 日窗口，再跑 180/338 日和滚动/留出期。修复前后属于不同代码状态，不得直接当作策略优劣实验。

## 6. 当前结论

账户执行和 NAV 重建在本次 20 日路径上是正确的，但计划目标、风险模型状态和报表相对收益仍存在会静默改变计算或解释的缺陷。当前结果继续只能标记为 `development_audit`，研究门和上线门应保持 `blocked`。
