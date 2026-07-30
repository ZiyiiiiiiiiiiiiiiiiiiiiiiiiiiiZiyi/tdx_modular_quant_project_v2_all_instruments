# SCAP-V3.2 29日最终运行：全输出、模型、代码与日期预检审计

> 审计对象：`run20260729_115619`
>
> 运行目录：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260729_115619`
>
> 运行身份：`small_capital_aggressive_profit_v3_2` / `small_capital_lean` / `aggressive_lean` / E4
>
> 交易窗口：2025-01-02 至 2025-09-25，180 个交易日，初始资金 20,000 元
>
> 因子身份：固定 74 因子柜 `pruned_run20260714_184846_581132_20260715_230524`
>
> 结论边界：这是开发审计窗口，不是独立留出期，也不满足生产上线门槛。

## 一、先给结论

这次结果不是“优化器又把组合压成两只股票”，也不是“目标仓位为零”。V3.2 已经恢复小资金激进版的主要行为：预热后平均仓位 81.41%，167 个可比较交易日中有 134 日持有 5 只股票，NORMAL 战略目标为 85%。工程全链完整，130 个 CSV 均可读、有表头，账户和订单账本可以逐项对上。

但它仍不能称为黄金版，主要有六个经济问题：

1. 策略收益 29.65%，低于预登记的流动性 Top-100 月调基准 32.28%；几何终值相对落后 1.99 个百分点。
2. 2025-04-07 单日下跌 13.85%，根因是 5 只股票同时暴露于相近小盘/反转风格；“名称数量=5”并不等于经济风险分散。
3. 入口角色确认层在 5/10/20 日均降低候选收益，严格入口与代理入口的边际回归系数也为负；当前入口权限映射需要消融复核。
4. 亏损控制卖出和安全卖出错过了明显反弹；利润硬止盈有效，但所有退出不能共享同一套强制卖出逻辑。
5. 74 个因子有 53 个被数值冗余审计标记，最大相关系数为 1，最大经验相关簇 22；等权投票使重复因子获得重复表决权。
6. 风险优化器接收了收缩协方差，但日常风险贡献报表仍走旧口径，导致“优化器在用什么”和“报表展示什么”没有完全接通。

工程状态为正，激进小资金行为基本恢复；经济质量为混合，生产资格为负。

## 二、最终绩效：金融含义与正负影响

| 指标 | 数值 | 判断 | 解释 |
|---|---:|---|---|
| 最终净值 | 1.296451 | 正 | 20,000 元账户取得正收益。 |
| 累计收益 | 29.6451% | 正 | 绝对收益显著为正。 |
| 年化收益 | 44.1254% | 正但不可外推 | 仅 180 日开发窗口年化，不能当作长期承诺。 |
| 年化波动 | 28.6507% | 负 | 激进策略的波动很高。 |
| Sharpe | 1.4242 | 正 | 窗口内风险调整收益尚可，但未做可靠的多重检验修正。 |
| 最大回撤 | -18.2957% | 负 | 仍低于产品灾难线，但主要由单日系统性风格冲击形成。 |
| 平均实际仓位 | 75.5322% | 中性偏正 | 包含 13 日建立仓位期；预热后为 81.4120%。 |
| 投入资本收益 | 44.8544% | 正 | 持仓资金本身效率较高。 |
| Top-100 月调基准 | 32.2809% | 对照 | 这是研究等权流动性基准，不是正式自由流通市值基准。 |
| 几何终值相对基准 | -1.9926% | 负 | 正确的终值比较为 `1.296451 / 1.322809 - 1`。 |
| 报表 active-return 累乘 | -10.8351% | 需改名 | 当前 `benchmark_excess_return` 是逐日算术主动收益再复利，不等于几何终值差。 |
| Beta | 0.3747 | 正/负取决于目标 | 下行暴露较低，但对于“激进追涨幅”也意味着市场上涨参与不足。 |
| 上行捕获 | 48.54% | 负 | 只吃到约一半基准上涨。 |
| 下行捕获 | 33.27% | 正 | 下跌时防守有效。 |
| 20/60/120日滚动胜率 | 57.5%/73.3%/71.7% | 正 | 中期相对表现较稳定；5 日只有约 49.7%，短期无优势。 |

敏感性基准改变结论：Top-50 同窗口约 +28.95%，策略领先约 0.69 个百分点；Top-300 约 +25.80%，策略领先约 3.84 个百分点；但预登记口径是 Top-100，所以主结论仍是略微跑输。不能事后挑选更容易战胜的基准。

## 三、仓位、股票数量与优化器

### 3.1 仓位公式

系统把五种概念分开：

\[
E_t^{exec}=\min(E_t^{desired},E_t^{risk},E_t^{signal},E_t^{lot})
\]

\[
Gap_t=\max(E_t^{exec}-E_t^{actual},0)
\]

- `desired`：NORMAL 下的战略希望仓位，当前为 85%；
- `risk`：风险状态允许的上限；
- `signal`：正净效用候选能够支持的仓位；
- `lot`：100 股整手、现金和涨跌停条件下可执行仓位；
- `actual`：真实成交后的仓位。

这意味着“目标 85%”不是无条件买满命令。负边际价值候选不能被仓位缺口奖励复活，否则优化器会退化成机械满仓器。

### 3.2 实际结果

- 持仓 1/2/3/4/5 只的交易日分别为 13/4/1/28/134 日。
- 预热后平均实际仓位 81.41%，相对 85% 平均缺口 3.94 个百分点。
- 最大单名账户权重约 30.63%，低于 40%灾难硬限制；研究软目标 25%仍多次被突破。
- 第 99 日（2025-06-04）`desired=85%`、`executable=85%`、`actual=75.49%`、缺口 9.51%，持仓 5 只，候选 15。
- 当日未补仓的直接原因是 10% catch-up 触发带：9.51% 被判为 `gap_below_trigger`。这不是目标为零，也不是没有候选。

正面影响：长期两股问题已消失；目标、可执行和实际仓位语义恢复。

负面影响：10%触发带是离散台阶，9.99%和10.00%的行为会突变。不过持仓已满 5 名时，额外部署只能对已有赢家加仓；若取消触发带，很可能增加集中度，而不是增加股票池广度。因此应做 6%/8%/10% 冻结参数消融，不能直接改成“有缺口就强买”。

### 3.3 整数动作优化器

对候选动作 \(i\)、整手数 \(q_i\)：

\[
V_i(q_i)=q_iL_i\mu_i^{LCB}-TC_i(q_i)-P_i^{authority}
\]

组合目标近似为：

\[
\max_q\left[
\sum_iV_i(q_i)
-\lambda_\Sigma\max(\sigma_{post}-\sigma_{pre},0)NAV
-\lambda_cNAV\sum_j(w_j-0.25)_+^2
-\lambda_gNAV(E^*-E(q))_+
\right]
\]

并用 `(robust value, -gap, breadth, expected return, -downside, -cost)` 做词典序择优。

硬约束包括：100 股整数手、现金缓冲、T+1、最多 5 名、单名 40%、风险压力预算、停牌/涨跌停、交易许可、持仓论点硬边界。

正面影响：

- 只生成一个 ActionPlan，避免连续权重优化和整数过滤互相打架。
- 现金可行层只淘汰 1 个候选，说明 2 万元整手约束不再是主要瓶颈。
- 19 个优化器入选新开仓动作符合最多 5 名和低换手产品设定，不能用“入选率低”单独判定过严。

负面影响：

- 协方差惩罚率约 0.05，按 2 万元 NAV 计算，日波动增量 2%只产生约 20 元惩罚，难以抵消高预期收益；4 月 7 日证实它对共同风格崩跌保护不足。
- 只惩罚新增风险，不主动降低继承的相关持仓风险。
- 报表的 `max_single_name_risk_contribution=1.0` 来自稀疏旧风险账本，不等于 V3.2 实际持仓协方差贡献；这是报表语义断链，不是“真实单股贡献一定100%”。

## 四、候选漏斗、A/B/C/D权限与入口状态机

### 4.1 漏斗

| 层 | 数量/比例 | 判断 |
|---|---:|---|
| 原始 universe/proposal | 1,141,152 | 全市场覆盖充分。 |
| 流动性通过 | 1,081,725；约94.99% | 不过严。 |
| 池内 Top-M | 35,433；约3.29% | 主动约简很强，但属于计算与候选预算设计。 |
| 入口确认通过 | 2,562；约7.23% | 最大信号瓶颈。 |
| 小资金/权限净价值通过 | 326；约12.72% | 第二大瓶颈。 |
| 原始 SCAP动作 | 35,381 | 动作生成正常。 |
| 结构可行 | 20,419；57.71% | 约束淘汰明显。 |
| 现金可行 | 20,418 | 现金不是核心问题。 |
| 槽位可行 | 16,094；78.82% | 5 名上限与关闭换仓有影响。 |
| 优化器新入选 | 19 | 受持仓状态与动作价值控制。 |

入口门诊断中，breakout 单项通过率约 2.77%，远低于 alpha 41.4%、flow 29.8%、market 70.5%、orderflow 58.9%、reversal 30.3%。这些诊断字段并非始终全 AND，但 breakout 明显是最严格的局部条件，应进入冻结消融。

### 4.2 权限

累计动作权限约为 A=1,400、B=0、C=34,769、D=56。

- A：最高可靠度和较宽初始手数；
- B：次高可靠度；
- C：不确定性更高，仍可一手起步；
- D：不可交易或仅审计。

正面影响：C 不再把整个组合限制在两只或 55%仓位，因而恢复 5 股组合。

负面影响：B 在整个窗口为 0，说明阈值不可达或状态晋级链没有形成有效分层。实盘行为几乎是 A/C 二元制；四级设计目前大部分是名义复杂度。

## 五、因子柜、数学有效性与冗余

### 5.1 组成

74 因子角色为：严格入口 6、入口代理 12、持有 12、流动性 12、风险 16、时机 16。按金融家族看，反转约 29、动量约 17、流动性约 11、规模约 6，价值、波动和其他家族占比较小。

正面影响：

- 74 个因子全部按固定 run id 加载，无缺失角色、模块或家族回退。
- 178 个因子×期限验证中 91 个通过，平均 rank IC 约 0.0354，105 个 top-bottom spread 为正。
- 时序隔离通过：上游分析标签最晚 2024-12-31，交易从 2025-01-02 开始。

负面影响：

- 53/74 因子被冗余报告标记，最大相关系数为 1，33 个经验簇中最大簇包含 22 个因子。
- 语义契约却把 74 个因子判成 74 个单成员近亲组，说明“名称/描述去重”没有识别“数值输出等价”。
- 当日权重全部为 \(1/74\)，reputation 关闭；重复矩阵变体会获得重复投票权。
- alpha diversification 总门失败，不能把“因子数量74”解释成“独立信息源74”。

建议数学处理不是简单删到几个因子，而是冻结历史柜后做两级消融：

1. 每个经验相关簇保留一个代表因子，簇权重总和固定；
2. 用 out-of-fold IC、符号稳定率和成本后 top-tail spread 分配簇内权重；
3. 比较原 74、簇平权 33、严格去冗余三组同身份结果。

### 5.2 角色边际

失败实验室显示：

- `L0全百分位 → L1角色确认` 在 5/10/20 日都降低平均收益：负面。
- `L1 → L2主入口Top3` 在三个期限均提高收益：正面。
- `L2 → L3真实买入` 在 5日和20日下降、10日上升；与 L0 比，三个期限都下降，且只有 15 个配对日：负面但样本较小。
- 严格入口和代理入口的边际回归系数为负；timing、liquidity、hold 大多为正：当前“谁有资格主导买入”的角色分配与经验边际相冲突。
- 6 个负控制均无告警：说明结果不是明显的标签随机噪声。
- 对抗漂移 AUC 0.5718，统计可检测但低于 0.65 的实质阈值：轻微漂移，不是主因。

## 六、买入、补仓、退出与换手

### 6.1 买入与补仓

- 普通买入 18 笔：5/10/20 日平均约 +3.30%/+2.59%/+8.52%，命中率约 66.7%/66.7%/76.5%，正面。
- 赢家加仓 2 笔：5/10 日约 -3.32%/-5.60%，20 日约 +3.73%；短期负面，但样本不足。
- `sz301300` 加仓后安全退出，总计约 -394.94 元。
- `sz300899` 加仓后期末仍持有，未实现盈利约 1,501.01 元。

结论：赢家加仓链已经真实接通，但“接通”不等于“有效”。仅两笔不允许继续针对本窗口调参，应冻结后积累更多事件。

### 6.2 退出

共 14 个闭合交易，10 胜 4 负，胜率 71.43%；实际盈利 1,073.53 元，PF=1.4576。平均盈利 341.94 元、平均亏损 -586.47 元、盈亏比仅 0.583，说明系统依靠高胜率覆盖大亏损。

| 卖出类型 | 笔数 | 已实现结果 | 卖出后10/20日表现 | 判断 |
|---|---:|---:|---|---|
| 利润硬止盈 | 9 | +3,119.76元 | 后续约 -8.28%/-8.06% | 正面，退出避开后跌。 |
| 亏损控制 | 3 | -1,950.95元 | 后续约 +15.67%/+22.86% | 明显负面，卖在反弹前。 |
| 安全降仓 | 2 | -95.28元 | 后续约 +4.75%/+23.39% | 负面，机会成本高。 |

反事实表中的 `avoided_loss_to_window_end` 会把负值截为 0；必须看 signed 字段。安全卖出的 signed window-end benefit 约 -1,966.79 元，不能被“避免损失=0”掩盖。

当前产品真实合同是：

- 主动换仓：关闭；
- 亏损摊平：关闭；
- 赢家加仓：开启；
- Alpha塌陷退出：开启，但本窗口对应诊断表为空；
- 不以维持换手率为目标。

启动页此前错误写成“主动换仓已开启”，本次已改为只读显示真实合同。该修正只改变界面说明，不改变29日交易结果。

## 七、巨额回撤的逐层解释

2025-04-07 账户单日收益 -13.8506%，前一日约 81.1%仓位，5 名持仓全部下跌：

| 股票 | 前一日账户权重 | 当日收益 | 对账户贡献 |
|---|---:|---:|---:|
| sz301300 | 29.87% | -16.66% | 约 -4.98pp |
| sz301233 | 20.85% | -16.54% | 约 -3.45pp |
| sz301189 | 11.04% | -19.97% | 约 -2.20pp |
| sz301587 | 10.55% | -19.79% | 约 -2.09pp |
| sh603163 | 11.38% | -9.98% | 约 -1.14pp |

数学上：

\[
r_{p,t}\approx\sum_iw_{i,t-1}r_{i,t}
\]

五项共同贡献几乎解释全部损失。因此根因不是持仓只有两只，也不是一个股票触发了40%硬限制，而是：

1. 小盘成长/反转风格高度相关；
2. 因子柜反转、动量家族占比高且数值冗余；
3. 25%只是软集中度惩罚，允许高确信股票达到约30%；
4. 协方差增量惩罚太弱；
5. 新增一手 `sz301300` 诊断上约增加 2.49 个百分点当日损失。

这也证明“强制股票池抗压”不能只规定股票数量，必须限制共同因子暴露、簇风险和压力场景损失。

## 八、费用、容量与小资金适配

- 35 个订单全部成交：买 21、卖 14。
- 成交名义金额约 109,870 元，总显式成本约 255.57 元。
- 佣金约 175 元、滑点约 54.94 元、印花税约 23.67 元，其余为转让费/冲击。
- 1x/5x/10x/20x 容量场景参与率均很低，10x容量门通过。
- 最低佣金与双倍市场成本压力下，闭合交易净利润仍为正。

正面影响：2 万元整手与最低佣金已真实进入执行，成本没有吞噬本窗口全部 alpha。

负面影响：冲击模型仍未正式校准，容量子模块通过不等于整个策略可上线；统一研究门仍以 `impact_model_calibrated_formal=false` 阻止。

## 九、PIT、泄漏与生产资格

- 特征时序隔离通过；训练标签最晚日早于交易起点。
- 日线数据采用 TDX 日收盘并在下一交易日执行，泄漏报告仍标记 `manual_review_required`，需要人工确认每个特征的 `t_close → t+1` 语义。
- PIT Level 1：4/4 数据源可用，但均不满足正式生产资格。
- PIT Level 2：3/3 数据源可用，但同样为 research-only。
- PBO、SPA、Deflated Sharpe 均因匹配变体/样本不足而不可用。
- 统一门失败项：failure lab、competing risk、multiple-testing/overfit、PIT L1、PIT L2、正式冲击模型。

因此绝对不能把“180日全链通过”写成“允许上线”。前者是工程完备性，后者需要时点数据、独立留出、过拟合与执行校准证据。

## 十、研究门之间的公式矛盾

`governance_research_gate_report.csv` 报告 10 日买入期望 +1.7706%，因为它按样本数对普通买入 18 笔和赢家加仓 2 笔加权：

\[
\bar r_w=\frac{\sum_g n_g\bar r_g}{\sum_gn_g}
\]

`governance_strategy_validation_matrix.csv` 却报告 -1.5030%，因为当前逻辑对“普通买入组均值”和“赢家加仓组均值”做简单平均：

\[
\bar r_{wrong}=\frac{\bar r_{normal}+\bar r_{add}}{2}
\]

这让 2 笔补仓获得与18笔普通买入相同权重，数学上不一致。正确主口径应使用逐笔加权；分组等权只能标为“reason-balanced sensitivity”，不能混叫总体买入期望。这是报表公式缺陷，不是交易策略本身突然从正变负。

## 十一、130个CSV输出的完整分类审计

### 11.1 非空核心输出：账户与仓位

`actual_exposure_ledger`、`constraint_allocation_ledger`、`governance_daily_result`、`governance_account_audit_ledger`、`governance_exposure_reconciliation`、`governance_holdings_ledger`、`governance_open_positions`、`governance_portfolio_constraint_report`、`governance_position_state_ledger`、`governance_position_lifecycle_report`、`ideal_portfolio_plan`、`safety_decision_ledger`、`scap_profit_audit`、`scap_profit_summary`。

作用：账户、持仓、生命周期、目标/实际仓位和约束对账。总体正面；发现软集中度超限、共同风格回撤和 catch-up 台阶。

### 11.2 非空核心输出：候选、决策与漏斗

`governance_alpha_proposals`、`governance_action_decision_ledger`、`governance_action_counterfactual_reward`、`governance_candidate_funnel_daily`、`governance_candidate_funnel_summary`、`governance_candidate_gate_audit`、`governance_candidate_gate_partition_index`、`governance_candidate_rejection_detail`、`governance_entry_confirmation_ledger`、`governance_entry_decision_audit`、`governance_entry_formula_audit`、`governance_entry_gate_policy`、`governance_entry_gate_summary`、`governance_entry_timing_diagnostics`、`governance_ideal_vs_executed`、`governance_retail_executable_rank`、`governance_selection_funnel_attribution`、`governance_cabinet_thesis_counterfactual`、`governance_defensive_sleeve_diagnostics`、`governance_module_role_summary`。

作用：解释从全市场到真实动作的每一层淘汰。正面是可追溯；负面是入口角色边际为负、breakout局部极严，且 `module_role_summary` 的部分旧字段不能完整表达 cabinet-native 路径。

### 11.3 非空核心输出：订单、成交、费用与退出

`executable_order_plan`、`pending_order_ledger`、`governance_execution_ledger`、`governance_retail_execution_diagnostics`、`governance_trade_pairs`、`governance_trade_pair_summary`、`governance_pnl_by_sell_reason`、`governance_entry_payoff_report`、`governance_entry_payoff_by_regime`、`governance_entry_failure_timing_report`、`governance_control_avoided_loss_ledger`、`governance_control_avoided_loss_summary`、`governance_control_opportunity_cost`、`governance_control_trigger_summary`、`governance_future_loss_duration_audit`、`governance_reward_ledger`、`governance_rollback_recommendation_ledger`、`scap_exit_stage_contract`、`governance_scap_admission_report`、`governance_scap_cost_stress_report`、`governance_capacity_stress_report`、`governance_corporate_action_ledger`、`governance_trading_evidence_report`。

作用：从提案到下一日成交、费用、闭环交易、退出反事实。订单链正面；亏损/安全退出负面；企业行为与正式交易证据仍不足。

### 11.4 非空核心输出：因子与时序

`governance_factor_cabinet_experiment_contracts`、`governance_factor_cabinet_module_mapping`、`governance_factor_cluster_report`、`governance_factor_ic_timeseries`、`governance_factor_ic_transfer_audit`、`governance_factor_redundancy_report`、`governance_factor_registry_snapshot`、`governance_factor_role_report`、`governance_factor_semantic_contract`、`governance_factor_source_report`、`governance_factor_validation_report`、`governance_factor_validation_runtime_audit`、`governance_factor_weight_ledger`、`governance_alpha_diversification_report`、`factor_temporal_lineage_evidence`、`reputation_ledger`、`governance_risk_contribution_ledger`。

作用：固定因子身份、IC、角色、冗余、权重、风险与时序。时序正面；冗余和等权重复投票负面；风险贡献账本与V3.2协方差路径语义不一致。

### 11.5 非空研究输出：消融、失败实验室与研究门

`governance_failure_lab_adversarial_drift_features`、`governance_failure_lab_adversarial_drift_importance`、`governance_failure_lab_adversarial_drift_summary`、`governance_failure_lab_competing_risk_curves`、`governance_failure_lab_competing_risk_events`、`governance_failure_lab_competing_risk_summary`、`governance_failure_lab_cost_capacity_scenarios`、`governance_failure_lab_cost_capacity_summary`、`governance_failure_lab_cost_capacity_trade_reconstruction`、`governance_failure_lab_layer_increment`、`governance_failure_lab_layer_increment_daily`、`governance_failure_lab_negative_control_audit`、`governance_failure_lab_overview`、`governance_failure_lab_permutation_report`、`governance_failure_lab_role_marginal_daily`、`governance_failure_lab_role_marginal_summary`、`governance_failure_lab_role_regression_diagnostics`、`governance_overfit_deflated_sharpe`、`governance_overfit_overview`、`governance_overfit_pbo`、`governance_overfit_spa`、`governance_research_gate_report`、`governance_strategy_validation_matrix`、`governance_unified_research_gate`、`governance_unified_research_gate_summary`。

作用：尝试证伪策略而非只展示收益。负控制和漂移正面；角色边际、竞争风险、过拟合证据和统一门为负。

### 11.6 非空结果解释、基准、报告和运行完整性输出

`governance_attribution_ledger`、`governance_bucket_attribution`、`governance_layer_validation_candidate_detail`、`governance_layer_validation_contract`、`governance_layer_validation_daily`、`governance_layer_validation_execution_gap`、`governance_layer_validation_score_report`、`governance_layer_validation_trade_review`、`governance_layer_validation_variant_report`、`governance_performance_benchmark`、`governance_performance_benchmark_sensitivity`、`governance_rolling_beat_report`、`governance_runtime_integrity_audit`、`governance_runtime_maturity`、`governance_strategy_summary`。

作用：归因、基准、滚动胜率、成熟度和运行完整性。工程正面；基准选择敏感、开发期不可外推。

### 11.7 有表头但无数据的输出

`governance_alpha_collapse_exit_diagnostics`、`governance_entry_calibration_report`、`governance_factor_layer_return_report`、`governance_factor_quantile_report`、`governance_v31_rolling_reliability_audit`、`shadow_portfolio_ledger`，以及8个 `governance_monthly_lgbm_*` 文件。

解释：

- shadow 关闭，所以影子组合空是预期；
- 最终运行是 `mainline_v3_cabinet_native`，不是 monthly LGBM hybrid，因此8个ML文件空是“不适用”，不是 ML 已验证；
- 入口概率校准为空是实质证据缺口；
- alpha-collapse 本窗口未触发不能证明该退出有效；
- V3.1 reliability 对 V3.2 不适用或未生成；
- 空表必须保留表头以保证全链 schema，不得把“文件存在”误判为“模块有证据”。

### 11.8 非CSV产物

`COMPLETE.json`、`run_checkpoint.json`、`artifact_manifest.json`、`environment_manifest.json`、`factor_runtime_audit.json`、`factor_semantic_contract_audit.json`、`factor_temporal_contract.json`、`fullchain_product_verification_v2.json`、`pit_runtime_audit.json`、`pit_level2_runtime_audit.json` 证明运行身份、完整性和PIT状态；Markdown和PNG只负责展示，不新增统计证据。

## 十二、启动页参数逐项解释

| 参数 | 实际作用 | 是否参与29日最终运行 |
|---|---|---|
| 开始 2024-01 / 结束 2026-05 | 治理任务请求范围；月末会归一到最后可观测交易日 | 否；29日最终运行实际固定为2025年起180日 |
| 最多交易日留空 | 不截断，使用月份范围内全部可观测交易日 | 仅影响新任务 |
| 月度ML最大融合权重0.20 | hybrid策略的预登记上限，不是固定权重 | 否；最终策略非ML hybrid |
| 绩效基准Top100/月调 | 研究归因与相对绩效 | 是 |
| 快速因子审判7000 | 因子研究任务候选预算 | 不直接改变本次治理回测 |
| PIT research | 缺失时降级并审计，禁止冒充formal | 是 |
| 最长运行秒数1,800,000 | worker超时上限 | 若确为秒，约20.83天；若想30分钟应填1800 |
| A500历史成员文件 | 仅严格指数成员宇宙需要 | 全A研究宇宙不需要 |

“0.20、5日入场、20日持有、逐轮NDCG、Top-5处理效应”只有选择 `mainline_v3_monthly_lgbm_hybrid` 并产生非空训练审计时才能验证。29日结果的8个ML表为空，因此不能用本次结果宣称月度ML有效或无效。

## 十三、`pit_membership_coverage_outside_requested_window` 根因与修复

### 13.1 为什么被阻止

- 特征数据范围：2018-01-02 至 2026-06-05；
- 2026-05 的最后可观测交易日：2026-05-29；
- A500 PIT成员 manifest 当前覆盖：2025-01-02 至 2026-05-29；
- 请求范围：2024-01-01 至 2026-05-31。

如果选择严格A500宇宙，2024年成员历史确实缺失，禁止把2025年的成员倒填到2024年，阻止是正确的。

但默认 `all_a_share_research` 在 `universe_registry.py` 中是：

```text
require_constituents=False
allow_fallback=True
```

运行器本来只在 `require_constituents and not allow_fallback` 时检查 PIT成员覆盖。旧启动页预检却不看宇宙类型，无条件检查A500 manifest，于是全A研究被无关输入误阻止。

### 13.2 修复

`main_launcher_web._governance_preflight()` 现在与 runner 合同一致：

\[
membership\_required=
\bigvee_u(require\_constituents_u\land\neg allow\_fallback_u)
\]

- 全A研究、ETF研究、允许fallback的宇宙：返回 `constituent_status=not_required`，不因A500历史缺口阻止；
- 严格A500等指数宇宙：继续检查，2024起点仍正确阻止；
- 2026-05-31仍归一为2026-05-29，不会误报周末月末。

这不是伪造或倒填2024年A500成员，只是移除了全A研究不消费的依赖。

## 十四、最终判断与下一步优先级

### 必须先修的报告/模型连接

1. 统一买入期望聚合公式，以逐笔样本权重为主口径，分组等权只作敏感性。
2. 把 V3.2 优化器使用的协方差矩阵、事前/事后波动、边际风险贡献写入同一日账本。
3. 将 factor semantic 去重升级为 empirical cluster 去重，防止重复投票。
4. 对入口角色确认层、breakout条件、A/B阈值做冻结消融，不能同时放松全部条件。

### 必须冻结验证的金融改动

1. catch-up阈值 6%/8%/10%；
2. 25%软集中度惩罚与协方差风险率；
3. 亏损控制/安全卖出的确认天数、滞回和再入场冷却；
4. 原74、簇平权33、严格去冗余柜；
5. 普通买入和赢家加仓分开评估，补仓至少积累30个独立事件。

### 不应做

- 不应把目标仓位改成无条件强买；
- 不应为了换手率重新开启主动换仓；
- 不应降低40%灾难硬上限；
- 不应把research PIT降级结果宣传为formal；
- 不应根据同一个180日窗口继续逐点调参数并称为样本外提升。

最终评级：

- 工程完整性：通过；
- 激进小资金仓位/广度：基本通过；
- 买入质量：普通开仓通过，赢家加仓证据不足；
- 退出质量：利润止盈通过，亏损/安全退出失败；
- 风险分散：失败；
- 相对基准：轻微失败；
- PIT/过拟合/正式执行：失败；
- 上线：禁止。
