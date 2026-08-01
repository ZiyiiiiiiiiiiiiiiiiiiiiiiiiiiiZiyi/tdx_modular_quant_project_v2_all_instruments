# SCAP 2026-07-31 输出结果全链审计

## 1. 审计对象与结论

31日没有以 `run20260731_*` 命名的新运行。当天唯一完整保存的正式运行是：

`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260730_232541`

该运行于2026-07-30 23:25启动，2026-07-31 02:27保存完成。`COMPLETE.json`、`run_checkpoint.json`和`artifact_manifest.json`均为 `complete`，窗口为2025-01-02至2026-05-29，共338个交易日。

本轮只读审计的总判断：

1. 账户、成交和最终NAV账本在“已经实际成交的路径”上基本闭合。
2. 结果不能作为可上线收益证据。研究门明确为 `blocked`，且PIT、冲击模型、过拟合检验和基准完整性均未通过正式门槛。
3. 发现三个会直接影响结果解释或交易路径的高优先级问题：
   - 基准有62个不完整日，但这些日的缺失成员仍按零收益进入基准NAV复利；正式相对收益因此对缺失日处理高度敏感。
   - 唯一ActionPlan选中的13个买入没有进入pending或成交，原因是计划层使用卖出回款，注册层却只使用卖出前现金。
   - 20个ActionPlan的计划暴露高于其“硬暴露上限”，仍被标为 `optimal_*`；运行完整性审计也明确发现3个执行暴露越权日。
4. 协方差模型虽然278日显示 `calibrated`，但没有影响任何买入决策；风险报表又使用另一套固定70/30收缩模型，风险状态和风险贡献并非同一模型。
5. 成本压力模型对赢家加仓和公司行动的重建不正确，基础场景相对真实已实现PnL高估724.41元。
6. Excel工作簿存在一个明确的因子覆盖失败、卖出MAE整列空白、检查公式硬编码和关键运行失败未进入Checks页等问题。

## 2. 运行口径

| 项目 | 本次值 |
|---|---:|
| 初始资金 | 20,000元 |
| 资本档案 | `small_capital_lean__cashok` |
| 资金使用 | `allow_cash` |
| 最大持仓数 | 5 |
| 退出阶段 | E4 |
| 损失止损 | -12% |
| 因子柜 | 固定74因子 |
| 策略逻辑 | `mainline_v3_cabinet_native` |
| 样本角色 | `development_audit` |
| 代码指纹 | `0cdd3c3cbbd0d24c50fe12a6df9df3defade7b8e2dab0199b618586580b54430` |
| 运行身份 | `3a36fb1773d9a23b89dda796a2a89c707b58ef896aa820f445f5f8652023b8ed` |

该运行与30日20日工程窗口、旧的-18%止损运行以及其他最大持仓档案都不是同一实验口径，不能直接把收益差解释为单一代码修复或单一参数的因果效果。

## 3. 数学指标复算

### 3.1 账户结果

| 指标 | 保存值/复算值 |
|---|---:|
| 最终NAV | 30,783.70205699元 |
| 总收益 | +53.91851028% |
| 最大回撤 | -17.16452187% |
| 最大回撤日期 | 2026-04-03 |
| 年化波动率 | 约24.39% |
| Sharpe | 约1.446 |
| 平均实际暴露 | 74.42095791% |
| 中位实际暴露 | 80.77664880% |
| 最大实际暴露 | 96.78064492% |
| 最低现金 | 1,054.38元 |

`nominal_nav = cash + invested_value` 的最大绝对复算误差为 `7.28e-12`，可视为浮点误差，账户NAV恒等式通过。

### 3.2 已实现、未实现与终值

69笔闭合交易已实现PnL为11,612.1570元，期末3个未平仓头寸的未实现PnL为-828.4550元：

`11,612.1570 - 828.4550 = 10,783.7021`

与 `30,783.7021 - 20,000` 完全一致。若假设期末立即清仓，估计还需25.6891元退出费用，清算后利润约10,758.0130元。

因此账户结果本身没有出现“报表盈利但现金/持仓无法重建”的问题。

### 3.3 基准与相对收益：存在高敏感性

保存的研究基准收益为+47.75683136%。两种不同的相对指标为：

- 简单百分点差：`53.9185% - 47.7568% = 6.1617个百分点`
- 几何相对财富：`1.5391851 / 1.4775683 - 1 = +4.1701%`

这两个数都可成立，但回答的问题不同，不能混用。

更严重的问题是：338日中只有276日的基准成员收益覆盖为100%，62日覆盖只有98%或99%。`analytics.py`在缺失成员上填0，并继续把这些“不完整日”复利进 `benchmark_net_value`；`benchmark_return_valid=False`只影响部分归因字段，没有阻止基准NAV被污染。

只在276个基准完整日上同时复利账户和基准，诊断结果为：

- 账户共同有效日收益：+61.2355%
- 基准共同有效日收益：+66.4696%
- 共同有效日几何相对收益：-3.1441%

这不是建议用-3.1441%替换正式结果，而是证明：当前的+4.1701%会随缺失日处理改变方向。基准不完整时，任何“战胜基准”的结论都不稳健。对应模块为：

- `functions/decision_council/analytics.py`：缺失成员填0、无效日仍进入NAV链。
- `functions/decision_council/runner_summary.py`：读取“最后有效日”的NAV，但该NAV已经包含此前无效日。
- `governance_strategy_summary.csv`：`degradation_flags`仍为空，没有暴露62个不完整基准日。

## 4. 买入链审计

### 4.1 实际成交

实际成交共147笔：

| 类型 | 数量 |
|---|---:|
| 普通买入 | 72 |
| 赢家加仓 | 6 |
| 卖出 | 69 |
| 合计 | 147 |

所有成交均为次交易日执行；无同日成交、无重复order_id、无重复fill_id、无零股成交、无负现金。

实际成交费用合计1,231.2979元：

| 费用 | 金额 |
|---|---:|
| 佣金 | 735.0000 |
| 滑点 | 324.3135 |
| 印花税 | 160.1690 |
| 过户费 | 6.48627 |
| 市场冲击代理 | 5.32917 |

### 4.2 唯一ActionPlan与执行注册不一致

338日均有且仅有一个ActionPlan，提案43,272条且proposal_id全部唯一。计划最终选中160条：

| 动作 | 选中数 |
|---|---:|
| new_entry | 85 |
| hard_exit | 65 |
| safety_exit | 4 |
| winner_add | 6 |

卖出动作69条全部成交，赢家加仓6条全部成交。但85个新开仓只有72个进入pending并成交，13个被注册层以 `lot_size_cash_insufficient` 拒绝。

这13个买入不是优化器主动拒绝，而是已经写入唯一ActionPlan和 `executable_order_plan.csv` 后，在 `_register_orders()` 内被悄悄过滤。全部13个发生在同一计划同时包含卖出和新买入的日期。

根因链：

1. `integer_action_optimizer.py`允许把普通强制退出的 `cash_release_amount` 加入计划现金。
2. ActionPlan因此可以在同一天用预计卖出回款选择新买入。
3. `execution_runtime.py`只有带 `replacement_pair_id` 的原子替换才给予条件卖出现金。
4. 这些“强制退出+新买入”没有被标为replacement pair。
5. `retail_execution.py`按卖出前现金和1,000元缓冲再次检查买单，因此13笔买入变成0股并未注册。

直接影响：

- 优化目标与实际持仓路径不同。
- 13个计划选中股票没有贡献实际PnL。
- `scap_profit_summary.csv`的optimizer-selected反事实队列可能包含这些未成交选择。
- `governance_candidate_funnel_daily.csv`把85个计划买入同时记为85个“registered buy”，但真实pending和普通买入成交只有72个。
- `governance_runtime_integrity_audit.csv`的action lineage只检查proposal→`executable_order_plan`，没有检查plan→pending completeness，因此仍误报通过。

这是本次最明确、最直接影响实际交易路径的代码逻辑缺陷。

## 5. 卖出与退出逻辑

### 5.1 已实现结果按卖出原因

| 卖出原因 | 笔数 | 胜率 | 已实现PnL |
|---|---:|---:|---:|
| profit_giveback_exit | 37 | 94.59% | +18,043.12 |
| profit_hard_stop_exit | 3 | 100% | +655.09 |
| safety_deleveraging | 4 | 100% | +817.16 |
| thesis_failure_exit | 6 | 66.67% | +207.54 |
| signal_failure_exit | 8 | 12.50% | -2,064.57 |
| loss_containment_exit | 11 | 0% | -6,046.19 |

总体胜率68.12%、profit factor 2.251、平均盈利444.55元、平均亏损-421.90元、赔率比1.054。

总体利润高度依赖 `profit_giveback_exit`：该类别贡献18,043元，而所有其他卖出原因合计为-6,431元。前5大盈利交易占全部毛利润约46.44%。这说明结果不是各退出模块均匀有效，而是一个利润保护模块覆盖了其他退出模块的损失。

### 5.2 损失退出存在明显滞后

研究门已经给出 `entry_failure_sell_lag_ratio=45.83%`，高于30%阈值。11笔 `loss_containment_exit` 全部亏损，单笔平均约-549.65元。

反事实前向收益进一步显示：

- `signal_failure_exit` 后10日股票平均上涨约8.96%。
- `thesis_failure_exit` 后10日股票平均上涨约8.65%。
- `loss_containment_exit` 后10日股票平均上涨约2.75%。

卖出方向收益因而分别为负，说明这些退出经常发生在已经下跌后的局部低点附近。该结果带有事后和条件选择偏差，不能直接证明“不卖更好”，但足以说明退出阈值、确认期和恢复机制需要专项A/B，而不能只看总体PF。

### 5.3 赢家加仓证据弱

赢家加仓只有6次：

- 5日平均前向收益：-0.6525%
- 10日平均前向收益：+0.4380%
- 20日平均前向收益：-2.8493%

样本量很小，但现有证据没有显示加仓在20日尺度增加收益。6个带加仓的闭合交易也是后述成本压力重建误差的主要来源。

### 5.4 Excel卖出表不完整

Excel的 `Sell Diagnostics` 只有65行，排除了4个 `safety_deleveraging`；表名没有清楚说明它并非全部69笔卖出。其 `mae` 列65/65为空，但 `governance_position_lifecycle_report.csv`中对应MAE并不为空，说明Excel构建时没有把已有MAE字段正确映射进来。

## 6. 暴露与整数约束

### 6.1 持仓数和现金约束

- 最大持仓数始终不超过5。
- 258日持满5只。
- 其中114日即使持满5只，距离目标暴露仍超过5个百分点。
- 现金从未为负，最低现金1,054.38元，略高于1,000元缓冲。

这符合2万元、100股整数交易的金融直觉：股票数量已满不代表资金能精确部署，整手价格会产生不可消除的现金碎片。

### 6.2 “硬暴露上限”并未真正硬约束

按当日计划字段直接检查，20个ActionPlan的 `projected_exposure > hard_exposure_ceiling`。这些计划多数是空动作计划，仍被标记为 `optimal_full_universe_exhaustive`。

代码原因是：

- `_plan_key()`会拒绝暴露超过上限的组合并返回 `None`。
- 当强制动作集合本身不可行、又没有可用降仓提案时，`best_key`可能保持 `None`。
- 主函数仍继续构建计划，把 `robust_net_profit_amount`置0，并沿用“optimal”状态。
- `constraint_slacks["exposure"]`又用 `max(cap-exposure, 0)`，把负松弛截为0，无法区分“正好贴上限”和“已经越界”。

因此这些计划并非数学意义上的可行最优解，应标为“当前状态不可行/缺少降仓提案”，而不是optimal。

运行完整性审计以“前一日授权上限+最多10个百分点整手/跳空容忍”检查后，仍发现3个越权日，最大超额15.031个百分点：

- 2026-02-03
- 2026-02-04
- 2026-03-31

这已经使 `governance_runtime_integrity_audit.csv` 变成11/12通过，而非全部通过。

## 7. 风险模型

### 7.1 协方差成熟，但没有参与买入

运行状态：

| 协方差runtime状态 | 天数 |
|---|---:|
| cold_start | 20 |
| warming_up | 40 |
| calibrated | 278 |

但 `governance_daily_result.csv` 的 `covariance_risk_model_used` 338日全部为False。ActionPlan只在2日标为covariance：

- 2026-03-23：只有3个强制退出。
- 2026-03-26：空计划。

两天的边际协方差罚金都为0。也就是说，85个新开仓和6个赢家加仓没有一个实际受到协方差边际风险罚金影响。

金融含义：当前策略仍基本是“单名压力上限+thesis fallback”，不能把结果解释为协方差组合优化的成果。

### 7.2 风险报表使用另一套模型

`governance_risk_contribution_ledger.csv`来自 `quality_reports.py`，其代码：

- 对缺失协方差填0；
- 固定使用 `0.70*sample_cov + 0.30*diagonal`；
- 数据源为ideal plan，而非最终ActionPlan/实际持仓；
- 仅46个日期有输出。

这与运行身份中声明的 `adaptive_diagonal_shrinkage`、100%覆盖门和ActionPlan风险模型不是同一模型。

进一步的不一致：

- 日账本338日 `max_risk_contribution`全为0。
- 风险贡献表最大值为1。
- summary又保存 `max_risk_contribution_observed=1.0`。
- 日账本风险门338日全为True，但风险贡献表中只有6个日期为eligible。

因此风险贡献、风险门和ActionPlan风险标签当前不能当作一条统一可复算链。

## 8. 成本与容量模型

### 8.1 实际成交成本账本

实际执行费用1,231.30元可由成交明细分项复算，账户NAV也已包含这些费用，这部分是可信的。

### 8.2 成本压力重建错误

`cost_capacity_audit.py`和`scap_cost_stress.py`用：

`entry_shares × (sell_order_price - entry_order_price)`

重建每笔交易毛PnL。这在单次买入时近似成立，但对赢家加仓不成立：

- trade pair的 `entry_shares` 是加仓后的总股数；
- `entry_order_id`只指向一笔买单；
- 正确成本基础应为全部买腿的加权平均成本；
- 模型还没有把公司行动现金纳入压力重建。

6笔加仓交易的重建净PnL比真实账本高估1,077.41元；其他63笔因公司行动现金等因素合计低估353元；净结果仍高估724.41元。

因此基础成本压力场景显示的12,336.56元，不等于真实已实现11,612.16元；`break_even_cost_multiplier=11.59`、压力PF和“production_eligible=True”都不能作为正式容量证据。

此外市场冲击模型明确为 `uncalibrated_daily_proxy_requires_vwap_validation`，20倍资本压力通过只说明成交额占日成交额很小，不证明真实开盘冲击和滑点模型正确。

## 9. 因子与金融模型

### 9.1 因子数量不等于独立风险来源

74因子的冗余报告显示：

- 冗余标记比例75.68%；
- 最大成对秩相关为1.0；
- 10个因子集中在同一模块；
- 9个因子集中在同一经济family；
- alpha diversification gate失败。

同时summary显示 `avg_factor_entropy≈1`、`avg_factor_top1_share=1/74`。这是因为声誉加权关闭后因子被等权，熵接近1是构造结果，不代表74个独立alpha。大量完全或近乎完全重复因子被分别计数，会虚增“因子多样性”。

### 9.2 验证报告不是严格的当前74因子柜

`governance_factor_validation_report.csv`包含89个因子：

- 当前因子柜74个；
- 额外验证21个非柜内因子；
- 当前柜内有6个因子未进入该验证报告；
- summary的110个pass中，93个属于当前因子柜，17个来自柜外因子。

因此 `factor_validation_pass_count=110`不能命名或理解为“当前74因子柜通过110项”。虽然这不改变“至少5项”的研究门结果，但会高估当前组合的证据数量。

### 9.3 收益来源集中

按开仓thesis归因：

| thesis | 闭合交易 | 已实现PnL | 胜率 |
|---|---:|---:|---:|
| value | 11 | +5,986.45 | 90.91% |
| size_style | 36 | +4,207.61 | 63.89% |
| growth | 11 | +1,632.97 | 63.64% |
| momentum | 5 | +128.22 | 60.00% |
| reversal | 6 | -343.09 | 66.67% |

收益主要来自value和size_style，不能把结果解释为74因子普遍有效。

## 10. 全部CSV/Excel输出审计

### 10.1 CSV整体

运行目录及持仓因子子目录共154个CSV：

- 154/154可解析；
- 0个无列文件；
- 0个 `Unnamed:` 残留列；
- 0个完全重复行文件；
- 15个只有表头、无数据行的文件。

15个空表包括：

- 与本策略不适用而合理为空：8个monthly LGBM表、shadow ledger、V3.1 rolling reliability。
- 可能因窗口内无触发而为空：alpha collapse exit diagnostics。
- 会导致研究门缺证据：entry calibration report、entry gate policy。
- 因子诊断产出缺失：factor layer return、factor quantile report。

产品问题不是“空表一定错误”，而是这些空表只有表头，没有 `status/reason/not_applicable` 行；用户无法从表本身判断是未启用、无样本、失败还是保存遗漏。

### 10.2 研究和上线门

明确失败项包括：

- runtime integrity：11/12。
- failure lab：1/3。
- competing risk：失败/不确定。
- multiple-testing/overfit：0/3，因没有同口径v1/v2/v3收益矩阵。
- PIT Level 1/2：`research_only`。
- impact model：未校准。
- entry probability calibration：缺失。
- sell 10d directional expectancy：失败。
- maximum single-name risk contribution：失败。
- profit giveback unhandled ratio：失败。

所以即使总收益和PF看起来较好，研究门与上线门仍必须保持blocked。

## 11. Excel工作簿逐表审计

工作簿：

`holding_factor_curves/SCAP_持仓逐因子曲线.xlsx`

结构为60个工作表、108张图：

- Summary
- Daily Constraints
- Closed Trades
- Sell Diagnostics
- Factor Map
- 54个历史持仓股票页
- Checks

全部60页均成功渲染，未发现 `#REF!/#DIV0!/#VALUE!/#NAME?/#N/A/#NUM!` 等公式错误。

### 11.1 Summary

优点：

- 338日、初始/最终资金、总收益、平均仓位、闭合交易和已实现PnL均与CSV一致。
- “策略-基准收益差（百分点）”6.16%是简单收益差，标签基本准确。

问题：

- 没有同时显示几何相对财富+4.17%，容易与CSV summary的 `benchmark_excess_return`混淆。
- 没有显示基准62个无效日。
- 没有显示runtime integrity失败、13个计划买入未注册、20个计划超硬上限。
- 数据源长路径在正常缩放下可读性差。

### 11.2 Daily Constraints

包含NAV、现金、持仓数、实际暴露、漏斗和基准，但缺少：

- hard exposure ceiling；
- benchmark return valid/coverage；
- plan selected、pending registered、actual fill三层计数；
- covariance runtime/used；
- runtime integrity状态。

因此仅凭该表无法发现本次最关键的交易链和基准问题。

### 11.3 Closed Trades

69行与交易配对账本一致，已实现PnL求和一致。它适合核对已成交结果，但没有展开多次买入腿，无法单独审计赢家加仓后的加权成本。

### 11.4 Sell Diagnostics

- 65行只覆盖主动生命周期退出，不含4个safety deleveraging。
- `mae` 65行全部空白，但生命周期CSV有MAE，属于字段映射缺失。
- 表名和说明未披露“不是全部卖出”。

### 11.5 Factor Map

74因子数量正确。但部分角色在运行元数据中叫 `liquidity_filter`，Excel中显示 `liquidity_guard`，需要统一角色字典，避免同一角色两个名称。

### 11.6 54个股票页

- 每页两张图，共108张，绘制波动最大的12个因子。
- 右侧矩阵保留74因子，绝大多数日期完整。
- `sz300965`在2025-04-30只有一条全空占位行，缺74因子中的全部有效值。
- 全部74因子横向展开到CN附近，工作表极宽；在正常缩放下表头拥挤，跨股票人工比较困难。

### 11.7 Checks

Checks页明确显示：

`持仓-日期因子覆盖：1513 / 1514，FAIL`

缺口是 `sz300965 / 2025-04-30`。

另外，B2、B3、B5等“实际值”是 `=1513`、`=74`、`=54`这类常量公式，不是从源工作表实时统计。若源数据被修改，Checks不一定自动反映变化。Checks也没有纳入runtime integrity、基准完整性、ActionPlan→pending完整性和硬暴露约束。

## 12. 问题优先级和模块定位

### P0：先修，否则长窗结果不能稳定解释

1. **计划买入被注册层丢弃**
   - 模块：`integer_action_optimizer.py`、`execution_runtime.py`、`retail_execution.py`、`runtime_integrity_audit.py`、`candidate_funnel_audit.py`
   - 验收：selected buy必须逐条进入pending或保存明确、可审计的计划失效状态；普通卖出回款若用于买入，必须原子配对或延迟到卖腿确认成交后。

2. **不完整基准日仍进入基准NAV**
   - 模块：`analytics.py`、`runner_summary.py`、Web/Excel summary。
   - 验收：正式相对财富只能使用完整覆盖链，或显式采用可证明无偏的成员处理；无效日不得既标invalid又悄悄进入正式NAV。

3. **不可行计划标为optimal**
   - 模块：`integer_action_optimizer.py`、`scap_v3_lean.py`、运行完整性审计。
   - 验收：`best_key=None`必须返回明确infeasible状态；硬上限负松弛必须保存为负值/violation；存在硬超限时必须有降仓提案或阻断研究门。

### P1：风险、成本和退出模型

4. 统一ActionPlan协方差、实际风险贡献和summary风险门，删除 `quality_reports.py` 的独立70/30旧模型。
5. 成本压力按全部买腿、加权成本、公司行动现金和真实卖腿重建。
6. 对loss containment、signal failure、thesis failure和winner add做冻结同spec的退出阈值/确认期A/B。
7. 因子验证严格按当前因子柜输出，柜外因子单独列示；熵按去冗余簇或经济family计算。

### P2：报告和Excel

8. 空表必须写 `status/reason/not_applicable`。
9. Excel补全几何相对收益、基准覆盖、硬暴露、plan→pending→fill、runtime integrity和风险模型状态。
10. 修复MAE映射和缺失因子日；Checks改为真实公式或源审计表引用。
11. `runner_summary.py`不能把所有 `exposure_cap<1` 的普通风险预算日命名为“emergency deleveraging”。当前338日全部被计为emergency，实际只有4笔safety sell，字段名明显失真。

## 13. 最终判断

该运行证明：

- 长窗口可以完整运行和保存；
- 实际成交、现金、持仓与最终NAV能够复算；
- E4利润回吐退出在本样本中贡献了主要利润。

但它没有证明：

- 相对基准收益为稳定正值；
- 协方差风险模型真正参与了买入；
- 唯一ActionPlan与实际成交路径完全一致；
- 损失退出和赢家加仓有效；
- 74因子具有74个独立alpha来源；
- 成本/容量压力结果可用于生产；
- 策略可上线。

综合状态应为：账户账本 `verified`，计划到执行血缘、基准数学、风险模型和成本压力 `remediation_required`，研究门与上线门继续 `blocked`。
