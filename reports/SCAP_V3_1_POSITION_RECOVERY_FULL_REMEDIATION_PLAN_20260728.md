# SCAP-V3.1 激进小资金仓位恢复完整修改方案

日期：2026-07-28
方案身份：`small_capital_aggressive_profit_v3_1_position_recovery`
诊断基线：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260728_122828`
当前状态：方案冻结；尚未修改交易代码；尚未取得研究或生产准入

## 0. 执行结论

本轮不通过“强制满仓”“取消止损”或“恢复亏损摊平”制造表面激进，而是修复四个已经有证据的P0断链：

1. ActionPlan空计划不是事实账户的恒等变换，错误产生0%计划后仓位；
2. 实时监控未传递目标持仓、闲置现金等字段，前端默认显示0；
3. A/B/C/D交易权在候选效用和Pareto缩减之后判定，C级回退被前置校准截断；
4. 因子柜负责排序，但旧`expected_return_5d`负责全柜方向否决，校准对象身份不一致。

修复后的激进含义为：在PIT、可交易、现金非负、整数手、T+1、费用、单股硬上限和安全风险上限内，让A/B/C分层正效用机会真实到达唯一整数优化器；现金仍是合法动作，但每一次不买必须有完整、可复算的原因。

## 1. 基线事实与问题分级

### 1.1 180日结果

| 指标 | `run20260728_122828` | 判断 |
|---|---:|---|
| 账户收益 | +7.6261% | 正收益，不足以证明策略有效 |
| 基准收益 | +32.2809% | 账户明显错过市场上涨 |
| 超额收益 | -20.4713% | 不符合激进小资金目标 |
| 最大回撤 | -20.3094% | 风险不低，低仓位没有换来足够保护 |
| Sharpe | 0.5516 | 较弱 |
| 平均实际仓位 | 34.1094% | 实际更接近防守档 |
| 闭合交易 | 5笔 | 远低于30笔准入证据 |
| 胜率 / PF | 40% / 1.899 | 被少量大赢家支撑 |
| 最后一次买入 | 2025-04-11 | 后续115个交易日无买入 |
| 连续全D | 97日 | 2025-05-13至2025-09-25 |

### 1.2 问题优先级

| 级别 | 问题 | 是否改变交易 |
|---|---|---|
| P0 | 空计划会计不守恒 | 先修事实；预期不应改变订单 |
| P0 | Web/实时字段缺失和错名 | 不改变交易 |
| P0 | Lean最低持仓0被`or`错误回退成2，软目标4又未进入监控 | 先修语义；不强制部署 |
| P0 | 权限判定晚于效用/Pareto | 会改变候选和订单 |
| P0 | 校准对象与因子柜身份错配 | 会改变A/B权威 |
| P0 | C级回退继承A/B非校准截断 | 会改变探索性一手买入 |
| P1 | 长期全D没有恢复与告警 | 会改变恢复速度 |
| P1 | 候选预览不披露权限/效用/拒绝层 | 不改变交易 |
| P1 | 目标仓位、计划仓位和实际仓位混称 | 不改变交易 |
| P2 | 普通损失退出可能过晚 | 本轮冻结，后续独立消融 |
| P2 | 主动替换、亏损摊平 | 继续关闭 |

## 2. 冻结不变量

以下合同在本轮不得顺手放松，否则无法判断修复是否有效：

- 初始资金20,000元；
- 现金缓冲1,000元；
- 最低佣金5元，候选、优化器、订单、成交和终端估值消费同一费用profile；
- 最大5只，软目标4只；
- 单股软上限30%，硬上限40%；
- normal/bull战略预算90%，weak 65%，high 35%，最终仍服从安全上限；
- A股实际一手规则、T+1、停牌、涨跌停和市场权限；
- 不使用杠杆，不允许负现金；
- E4退出、-12%灾难损失线和硬安全退出；
- 赢家加仓保留；亏损摊平和主动替换关闭；
- 同一日只有一个ActionPlan和一次整数优化器调用；
- 风险只使用一个人民币主惩罚表达；CVaR保留为压力硬约束，不重复从目标扣减；
- PIT、成熟标签和运行身份隔离不变。

## 3. 目标模块链

```text
PIT特征/因子柜身份
  ↓
同身份滚动校准与PIT可比回退分布
  ↓
A/B/C/D交易权判定
  ↓
按权威层选择决策收益
  ↓
人民币增量财富与精确逐腿费用
  ↓
事实硬门
  ↓
软证据惩罚
  ↓
Pareto候选缩减
  ↓
唯一整数ActionPlan优化器
  ↓
订单/T+1/成交/现金账
  ↓
六层仓位、拒绝血缘、Web与准入报告
```

任何下游模块不得重新调用旧`entry_confirmed`、旧概率、旧连续权重优化器或第二套费用函数否决Lean已经授权的动作。

## 4. 六层仓位合同

旧的单一`target_exposure`删除交易权威，仅作为兼容显示字段。正式合同为：

\[
E_t^{cap}
=\min(E_t^{regime},E_t^{safety})
\]

\[
E_t^{desired}=E_t^{cap}
\]

\[
E_t^{signal}
=\min\left(
E_t^{desired},
E_t^{actual}
+\sum_{i\in\mathcal A_t^{positive}}w_{i,t}^{one\ lot}
\right)
\]

\[
E_t^{integer}
=\max_{q\in\mathcal F_t^{cash,lot,slot}}E(q)
\]

\[
E_t^{plan}=E(q_t^\star),\qquad
E_{t+1}^{actual}
=\frac{\sum_i q_{i,t+1}L_{i,t+1}P_{i,t+1}}{NAV_{t+1}}
\]

页面和账本必须同时展示：

1. `risk_exposure_cap`：制度/安全上限；
2. `strategic_desired_exposure`：策略希望使用的预算；
3. `signal_supported_exposure`：正效用信号能支持的上限；
4. `integer_feasible_exposure`：现金、整手、槽位可实现上限；
5. `optimizer_planned_exposure`：ActionPlan后仓位；
6. `actual_exposure`：事实账户仓位。

持仓数量也必须拆开：

- `minimum_required_holdings=0`：Lean允许现金，不设强制最低持仓；
- `soft_target_holdings=4`：正效用机会充足时的优化目标；
- `maximum_allowed_holdings=5`：硬上限；
- `soft_holding_shortfall=max(4-actual_holding_count,0)`。

当前runner以`profile.get("min_holdings", 2) or 2`读取配置，把Lean显式配置的0错误替换成2；实时监控又因缺字段显示0，而优化器使用软目标4，形成0/2/4三套语义。修复后禁止用真值判断解析有效数值0，只能在字段缺失或`None`时使用缺省值。

对应差额：

\[
Drag_t^{signal}=E_t^{desired}-E_t^{signal}
\]

\[
Drag_t^{integer}=E_t^{signal}-E_t^{integer}
\]

\[
Drag_t^{optimizer}=E_t^{integer}-E_t^{plan}
\]

\[
Drag_t^{execution}=E_t^{plan}-E_{t+1}^{actual}
\]

所有差额统一截到有符号值，不允许一处使用战略目标、另一处使用计划目标后仍称为同一个`exposure_gap`。

## 5. 空计划会计修复

### 5.1 恒等合同

若选择动作集合为空：

\[
q_t^{plan}=q_t^{current}
\]

\[
C_t^{plan}=C_t^{current}
\]

\[
E_t^{plan}=E_t^{actual}
\]

\[
Risk_t^{plan}=Risk_t^{current}
\]

\[
Cost_t^{plan}=0
\]

不能再返回`projected_exposure=0`或`projected_cash=NAV×risk_cap`。

### 5.2 接口修改

`_empty_plan()`不得只接收`ExposureAuthorization`，至少应接收不可变的`CurrentPortfolioFacts`：

```text
current_cash_amount
current_lots_by_symbol
current_weights
current_exposure
current_stress_loss
current_thesis_counts
```

空计划和非空计划使用同一个`project_portfolio_after_actions()`函数，避免两套会计。

### 5.3 验收

- 空动作前后现金、股数、仓位、论点计数、风险完全相等；
- 只有市场价格变化才能在下一日改变实际仓位；
- 监控的计划后仓位不得为0，除非事实持仓为0或计划包含完整卖出；
- 该阶段与基线的订单、成交、现金、NAV逐日完全一致。

## 6. 校准预测身份修复

### 6.1 唯一预测身份

定义正式预测器：

\[
S_{i,t}^{cab}
=ScoreContract(
FactorCabinetID,
RoleMap,
FamilyAggregation,
Version
)
\]

校准器的排序、方向、斜率、漂移和收益估计必须全部消费同一`score_contract_id`。禁止使用旧`expected_return_5d`作为因子柜的全局否决字段。

必须保存：

```text
score_contract_id
factor_cabinet_run_id
factor_cabinet_hash
role_map_hash
score_column_identity
label_horizon
entry_price_basis
cost_profile_id
```

### 6.2 方向检验

对已成熟、PIT、按日期成块的样本：

\[
IC_t^{cab}
=Spearman(S_{i,\tau}^{cab},r_{i,\tau\rightarrow\tau+h}^{net})
\]

\[
\beta_t^{cab}
=\frac{Cov(S^{cab},r^{net})}{Var(S^{cab})}
\]

其中收益口径必须固定为下一可交易日开盘进入、\(h\)日收盘退出，并披露是否包含完整往返费用。排名分仅用于方向和排序，不能直接乘资金当收益。

### 6.3 双时间尺度恢复

为了避免一次下跌造成长期冻结，同时不在一日反弹时立刻恢复满权：

- `recent`：最近20个独立成熟会话；
- `stable`：最近60个独立成熟会话；
- `long`：最多252个独立成熟会话，只用于收缩先验；
- 撤销A权：连续3次成熟更新中`recent IC<0`且`recent slope<0`；
- 恢复B权：连续2次成熟更新方向非负，或recent 20日方向非负且PIT回退LCB为正；
- 恢复A权：recent与stable方向均正、样本和稳定性重新满足A合同；
- A/B失权期间C层不受该状态连带截断。

这里的2/3次是预登记初始值，只能通过滚动块和留出期调整，不能在同一180日窗口反复调优。

## 7. A/B/C/D权威与效用顺序

### 7.1 权威层

| 层级 | 证据 | 权限 |
|---|---|---|
| A | 有效样本≥80、独立会话≥60、同身份IC和斜率为正、非漂移 | 1—4手，仍受组合约束 |
| B | 有效样本30—79、独立会话≥20、方向非负、非漂移或处于受控恢复 | 每只最多1手，B暴露≤40% |
| C | A/B不可用，但独立PIT可比回退分布成本后LCB>0 | 每只1手，最多2个C层名字 |
| D | 负方向、漂移且无正回退、成本后非正或事实不可交易 | 无交易权 |

B+C探索暴露合计不超过55%。C级不是伪概率，也不继承A/B校准状态；它只消费独立PIT可比收益分布。

### 7.2 分层决策收益

\[
\mu_{i,t}^{A}
=\widehat\mu_{i,t}^{cab}
-0.50SE_{i,t}^{cluster}
\]

\[
\mu_{i,t}^{B}
=\widehat\mu_{i,t}^{cab}
-0.25SE_{i,t}^{cluster}
\]

\[
\mu_{i,t}^{C}
=LCB_{i,t}^{PITComparable}
\]

\[
\mu_{i,t}^{D}=0
\]

先确定层级，再将对应\(\mu^{tier}\)送入统一效用。禁止先用A层校准状态把效用归零，再尝试判C。

### 7.3 人民币增量财富

对动作\(a\)：

\[
\Delta W_{i,t}(a)
=N_{i,t}(a)\mu_{i,t}^{tier}
-Cost_{i,t}^{roundtrip}(a)
-CE_{i,t}^{soft}
\]

其中：

- \(N\)为事实成交名义金额；
- `Cost`使用统一5元最低佣金和逐腿税费；
- \(CE^{soft}\)只能包含未在组合层重复表达的软质量代价；
- 非正\(\Delta W\)不得买入；
- C层使用`calibration_state=pit_fallback_authorized`，不得被`state != calibrated`统一截成0。

## 8. 买入状态机

### 8.1 事实硬门

仅保留：

- PIT和时间隔离通过；
- 股票在研究股票池且市场权限允许；
- 非停牌、非不可买涨停；
- 价格有效、最小买入数量有效；
- 一手现金及1,000元缓冲可行；
- 单股硬上限40%；
- 组合最大5只；
- 安全硬冻结未开启；
- A/B/C权威存在；
- 成本后人民币增量财富为正。

### 8.2 软证据

以下不得再单独清空全部候选：

- 市场/趋势确认；
- 订单流、反转、突破；
- 波动和近期回撤；
- strict/proxy角色覆盖；
- 论点支持弱但尚未失效；
- 同论点第3只的集中风险。

软证据转换为人民币CE或排序次序：

\[
\Delta W_{soft}
=\Delta W
-N(\lambda_qPenalty_{quality}
+\lambda_tPenalty_{timing}
+\lambda_lPenalty_{liquidity})
\]

每项必须有上限，全部软惩罚之和不得超过候选毛期望财富的预登记比例；否则它仍会退化成隐藏硬门。

### 8.3 Pareto缩减

Pareto只缩减搜索规模，不拥有交易否决权。必须保留以下并集：

- 人民币效用Top-K；
- 资本效率Top-K；
- 每个论点族Top-2；
- 每个权威层至少Top-2；
- 所有赢家加仓和硬退出动作；
- 正PIT-LCB的C层候选至少Top-2。

未进入Pareto集合必须记录`pareto_reduced`，不得写成“排名不足”。

## 9. 补仓与趋势反转恢复

### 9.1 新仓补足

“持仓不足”只表示配置缺口，不强制购买。满足以下事实时，新仓必须能到达优化器：

```text
risk_level in {normal, warning}
actual_holding_count < soft_target_positions
current_cash - buffer >= one_lot_cash
authority in {A, B, C}
incremental_terminal_wealth > 0
no hard market/freeze block
```

若优化器仍选现金，必须由同一次优化器证明最佳买入计划不支配最佳不买计划。

### 9.2 赢家加仓

- 只允许锁定A层持仓；
- 入场后至少10个交易日复核；
- 每次最多1手；
- 加仓后单股≤40%，同论点硬上限≤3；
- 买入论点支持相对入场下降≥0.20、成本后LCB≤0或趋势转负时禁止；
- 不允许当日连续堆叠多层；
- 10日后的边际收益单独审计，不能与首买混为一个样本。

### 9.3 亏损摊平和主动替换

本轮继续关闭。修复“长期不补仓”不等于向亏损持仓继续投入。主动替换必须等新仓链恢复并积累足够闭合样本后单独研究。

### 9.4 风险恢复

安全状态从high恢复normal只恢复风险预算，不直接强制买入。交易恢复由A/B/C层决定：

- A未恢复时允许B/C一手探索；
- 新成熟结果持续正向后升级B/A；
- 结果转负则只撤回相应层，不影响独立C回退；
- 不允许单个全局`drifted`布尔值无限期冻结全部因子柜。

## 10. 整数ActionPlan优化器

### 10.1 目标

\[
\max_{q\in\mathbb Z}
\left[
\sum_a \Delta W_a
-\lambda_\Sigma
\left(
CE_\Sigma(w^{after})-CE_\Sigma(w^{before})
\right)
\right]
\]

\[
CE_\Sigma(w)
=NAV_t\sqrt{w^\top\Sigma_tw}
\]

协方差只在runner完成一次70/30收缩。优化器不得再次收缩，也不得把协方差当相关系数乘利润。

### 10.2 硬约束

\[
C_t^{after}\ge1,000
\]

\[
\sum_i1(q_i>0)\le5
\]

\[
0\le w_i^{after}\le0.40
\]

\[
E_t^{after}\le E_t^{cap}
\]

\[
Exposure_B\le0.40,\quad
Exposure_{B+C}\le0.55
\]

\[
Count_C\le2
\]

- 同论点2只是软上限，第3只支付人民币集中CE，3只是硬上限；
- 既有超限只禁止继续恶化，不阻断其他论点买入；
- CVaR只作为压力硬预算，不再次扣目标；
- 同一股票不同手数是互斥备选，不得累加。

### 10.3 liveness

只在同一次穷举中比较：

\[
Plan_{buy}^{best}
\succ
Plan_{nonbuy}^{best}
\]

若完整可行域和完整词典序目标下最佳买入计划严格支配最佳不买计划，而最终ActionPlan没有买入，才触发liveness错误。单候选毛效用正不能代替完整组合支配关系。

## 11. 实时监控与审计

### 11.1 必须显示

- 风险等级、风险上限、战略期望、信号支持、整数可行、计划后、实际仓位；
- 最低持仓0、软目标4、硬上限5、实际持仓和软目标缺口；
- 事实现金、缓冲、可交易现金、闲置现金比例；
- A/B/C/D数量与正效用数量；
- 原始→权威→正效用→结构→现金→槽位→Pareto→优化器→订单→成交漏斗；
- 最佳买入/不买目标和支配关系；
- 首个拒绝原因和全部拒绝原因；
- 连续全D天数、连续NORMAL高现金零提案天数；
- 候选预览必须标记“排序候选，不代表交易权”。

### 11.2 快照一致性

实时状态不得重新计算账本字段。runner完成当日事实行后，监控直接消费该事实行和ActionPlan审计行。对每个交易日：

```text
monitor_state[field] == governance_daily_result[field]
monitor_action[field] == constraint_allocation_ledger[field]
```

浮点误差容限`1e-10`，字符串和计数必须完全一致。

### 11.3 告警而非强制交易

- 连续3个NORMAL交易日、现金>50%、持仓少于软目标且全D：黄色告警；
- 连续5日：红色告警并保存完整候选证据；
- 连续10日且存在正PIT-LCB候选但raw=0：工程验收失败；
- 战略目标与计划目标混算导致缺口守恒失败：立即抛错；
- 空计划不是恒等变换：立即抛错。

## 12. 文件级修改清单

| 文件 | 修改 |
|---|---|
| `functions/decision_council/contracts.py` | 增加`CurrentPortfolioFacts`、六层仓位字段和单位合同 |
| `functions/decision_council/integer_action_optimizer.py` | 空计划恒等、统一投影函数、精确买/不买比较 |
| `functions/decision_council/runner.py` | 先权限后效用；唯一事实行进入监控；校准身份传递 |
| `functions/decision_council/entry_calibration.py` | 使用因子柜ScoreContract；双时间尺度漂移/恢复 |
| `functions/decision_council/scap_v31_authority.py` | A/B/C/D状态机、C独立回退、恢复原因 |
| `functions/decision_council/small_capital_aggressive.py` | 按权威层收益计算效用，移除非calibrated统一截断 |
| `functions/decision_council/mainline_v3.py` | 事实硬门、软证据、Pareto并集，不再前置清空C |
| `functions/decision_council/scap_v3_lean.py` | 分层提案、赢家加仓和精确liveness |
| `functions/decision_council/position_lifecycle.py` | 锁定入场权威/论点，10日赢家加仓复核 |
| `functions/decision_council/policy.py` | 唯一ActionPlan到订单，不增加第二优化器 |
| `functions/decision_council/live_monitor_web.py` | 六层仓位、权限漏斗、字段缺失显式NA |
| `functions/decision_council/live_monitor_dashboard.py` | 与Web使用相同字段词典 |
| `functions/decision_council/candidate_funnel_audit.py` | 单调漏斗、拒绝守恒、目标缺口守恒 |
| `functions/decision_council/runner_summary.py` | 新旧字段兼容与分层结果汇总 |
| `verify_scap_v31_position_recovery.py` | 新增核心性质测试 |
| `verify_scap_web_contract.py` | 实时与保存快照一致性 |
| `QUANT_SYSTEM_WBS.md` | 每阶段记录输入、输出、测试、run身份和结论 |

## 13. 分阶段施工与测试

### Phase 0：冻结基线

- 保存当前git状态、runtime identity、配置、因子柜和费用profile；
- 记录180日基线的逐日NAV、订单、成交和六层现有字段；
- 不运行新策略。

静态验收：

- 调用图确认唯一优化器；
- `py_compile`所有计划修改文件；
- 现有SCAP、费用、Web、执行、PIT测试全部通过。

### Phase 1：事实会计与监控

- 修空计划恒等；
- 建六层仓位字段；
- 修复最低0/软目标4/硬上限5三层持仓语义，禁止`or`覆盖合法0；
- 实时状态直接消费保存事实；
- 缺失值显示`--`，禁止静默0。

行为不变量：

- 与基线逐日订单、成交、现金、NAV完全一致；
- 只允许报告字段变化。

### Phase 2：校准身份

- 因子柜ScoreContract贯穿warm-up、方向、斜率和漂移；
- 保存recent/stable/long诊断；
- 仍不改变权限阈值，先验证对象同源。

专项性质：

- 改变旧`expected_return_5d`不得改变柜体方向；
- 改变因子柜ScoreContract必须改变对应校准身份；
- 未成熟未来标签不得进入校准。

### Phase 3：权限前置与C回退

- A/B/C/D先于效用；
- C使用独立PIT LCB；
- B/C暴露和手数约束生效；
- 前置Pareto保留分层候选。

核心性质：

- A/B漂移、C正LCB、事实可行 → 至少形成一手C提案；
- C的LCB≤0 → D且无提案；
- B每只最多一手；
- C最多2名、B+C不超55%；
- 无正效用时现金合法。

### Phase 4：恢复状态机与软证据

- 增加20/60/252双时间尺度；
- 实现3次撤A、2次恢复B的预登记状态机；
- 市场/订单流/反转/突破由硬门改为有上限软CE；
- 添加长期全D告警。

核心性质：

- 一次负更新不冻结全部柜体；
- 连续负方向可以撤权；
- 两次非负成熟更新可恢复B；
- C始终独立；
- 软惩罚不能把所有正毛效用候选无上限归零。

### Phase 5：补仓、赢家加仓与优化器

- 新仓不足时正效用候选可达；
- 赢家加仓只消费锁定A权威；
- 空计划与完整计划共用投影函数；
- 保留一次优化与精确liveness。

核心性质：

- NORMAL、1只持仓、80%现金、正效用不同论点一手候选 → 买入计划可达；
- 高协方差使买入不支配现金 → 合法不买；
- 已有同论点超限不阻断其他论点买入；
- 赢家10日前不能加仓，10日后满足条件最多加一手；
- 亏损摊平和主动替换始终无提案。

### Phase 6：产品闭环

每阶段先执行“不运行主流程”的代码检查和合成性质测试。全部通过后：

1. 5日smoke：启动、可见worker、进度、订单、成交、保存；
2. Ctrl+C：退出码130、checkpoint非陈旧；
3. 恢复：从checkpoint继续且订单唯一；
4. 20日全流程：从开始到原子保存、完整artifact和integrity audit；
5. 60日恢复窗：确认高风险后权限恢复；
6. 180日同口径消融。

20日只证明工程完整，不证明盈利。

## 14. 消融矩阵

必须按顺序，每次只增加一个行为变化：

| 组 | 变化 | 预期 |
|---|---|---|
| B0 | 当前基线 | 固定证据 |
| B1 | 仅空计划/监控修复 | 订单、成交、NAV与B0完全相同 |
| B2 | B1 + 校准对象同源 | 解释权变化，先观察A/B路径 |
| B3 | B2 + 权限前置/C回退 | 恢复一手探索，不能破坏硬约束 |
| B4 | B3 + 双时间尺度恢复 | 缩短全D冻结 |
| B5 | B4 + 软证据有界CE | 提高候选到达率 |
| B6 | B5 + 赢家10日复核 | 检验加仓边际 |

所有组固定：

- 同一日期、股票池、因子柜、PIT状态；
- 同一成本、缓冲、风险预算、最大持仓、退出阶段；
- 同一代码基线除目标单变量；
- 相同随机种子和输出身份；
- 不用开发窗结果反复调参后冒充样本外。

## 15. 验收标准

### 15.1 工程硬门

- 所有专项与回归测试退出0；
- runtime integrity全部通过；
- 现金、股数、费用、T+1、订单唯一和持仓上限守恒；
- 空计划恒等；
- 监控与CSV逐字段一致；
- 漏斗单调、拒绝原因守恒；
- 每日优化器调用恰好一次；
- 无未来标签泄漏。

### 15.2 激进小资金行为门

以下是工程行为门，不是盈利门：

- NORMAL且现金>50%、持仓不足、存在正C-LCB时，不得连续10日raw=0；
- 连续全D必须能由负同身份校准或无正回退分布解释；
- 最后一次买入后长期无交易必须有逐日可审计原因；
- 目标仓位不得再出现0%目标与正缺口并存；
- 候选预览不得把D级或负效用标成“可买候补”；
- 计划仓位、实际仓位和执行缺口可以复算。

平均仓位和交易数只作为诊断，不设置机械最低值，避免为了通过测试强制交易。

### 15.3 经济研究门

- 至少30笔闭合交易；
- 完整最低佣金和压力成本后终值利润为正；
- PF、胜率、payoff及其置信区间共同评估；
- 滚动126日/63日步长切片稳定；
- 相对基准和有效投入资金超额不持续为负；
- 最大回撤、CVaR和集中度在预登记边界内；
- 未触碰留出期或前瞻纸面窗口通过；
- PBO/SPA/deflated Sharpe、PIT Level 1/2和冲击模型准入通过。

## 16. 回滚

每个Phase独立提交、独立runtime identity、独立输出目录。出现以下任一项立即回滚到上一阶段：

- 负现金、超5只、单股超40%、T+1或订单唯一失败；
- 成本事实源分裂；
- 未来标签进入决策；
- 优化器调用超过一次；
- C级绕过负LCB或事实硬门；
- 监控字段与保存账本不一致；
- B1改变基线订单/NAV；
- 20日无法从启动完整保存。

回滚只回退本阶段提交，不删除历史run和审计证据。

## 17. 推荐施工顺序

```text
Phase 0 基线冻结
 → Phase 1 空计划与监控
 → Phase 2 校准对象同源
 → Phase 3 权限前置和C回退
 → Phase 4 快速恢复与软证据
 → Phase 5 补仓/赢家加仓/优化器
 → 5日 + Ctrl+C + 恢复
 → 20日全链
 → 60日恢复窗
 → 180日B0—B6消融
 → 未触碰留出期
```

当前最重要的原则是：先恢复候选到优化器的正确通路，再研究是否需要进一步放松参数。若Phase 3后仍长期低仓，应根据拒绝血缘判断是成本、风险CE、论点、现金还是收益校准造成，禁止再次凭感觉同时修改多个门槛。
