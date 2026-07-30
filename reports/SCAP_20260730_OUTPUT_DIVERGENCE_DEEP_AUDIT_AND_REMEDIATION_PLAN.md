# SCAP 2026-07-30 上午输出差异深度审计与完整修改方案

> 审计日期：2026-07-30
> 范围：只读检查历史运行产物与当前代码；不修改策略、参数、执行、账户和报告逻辑；不启动新回测。
> 基准运行：`run20260729_103208`、`run20260729_115619`、`run20260729_234344`。
> 结论边界：所有运行均为 `development_audit`，研究门为 `blocked`，不得作为上线或盈利证明。

## 一、结论

30 日上午看到的结果差距不是一个原因造成，而是三层问题叠加：

1. **不可比运行被放在一起比较**：180 日与 338 日、E4/-18% 与 E4/-12%、不同代码状态和资本档案混在一起。
2. **运行身份没有覆盖真正改变交易路径的代码**：`scap_v3_lean.py`、`integer_action_optimizer.py` 等关键模块不在代码指纹清单中；同时输出目录又被错误放进运行身份哈希，使“同实验重复运行”必然得到不同身份。
3. **SCAP 动作链仍有确定的逻辑缺陷**：普通退出被正利润过滤器长期拒绝；战略目标、硬暴露上限与降仓确认来自不同状态机；权威优化器选择没有完整回写到利润审计和暴露账本。

按严重性排序，根因是：

| 优先级 | 根因 | 直接后果 |
|---|---|---|
| P0 | 代码指纹和实验身份不完整 | 不能证明复现，也不能确认哪次代码修改造成收益变化 |
| P0 | 普通 `exit` 被 `non_positive_robust_profit` 拒绝 | E4 大量软退出没有交易权，持仓路径、回撤和闭合交易数失真 |
| P0 | 暴露目标/硬上限/降仓确认状态机不一致 | 超出目标后可能既不降仓，也无法进行其他可行优化 |
| P1 | 优化器选择血缘在报告间断裂 | 漏斗、暴露账本和利润审计对“优化器选中”给出互相矛盾的答案 |
| P1 | 赢家加仓存在多重权限计算和重复阈值 | 一个字段接通即可改变整个后续复利路径，且难以做单变量归因 |
| P1 | 风险目标的期限和单位未完全统一 | 10 日利润与日协方差风险直接相减，风险惩罚缺少可审计的期限换算 |
| P2 | 报告中的基准超额、风险使用状态和退出统计语义混杂 | 数值本身可能可算，但容易被解释成错误的金融结论 |

## 二、运行可比性与差异分解

### 2.1 运行矩阵

| 运行 | 窗口 | 退出/止损 | 记录的代码指纹 | 收益 | 最大回撤 | 闭合交易 | PF |
|---|---|---|---|---:|---:|---:|---:|
| `run20260729_103208` | 2025-01-02→2025-09-25，180 日 | E4/-18% | `c6773cad...` | +43.3465% | -16.7328% | 17 | 2.1256 |
| `run20260729_115619` | 2025-01-02→2025-09-25，180 日 | E4/-18% | `c6773cad...` | +29.6451% | -18.2957% | 14 | 1.4576 |
| `run20260729_234344` | 2025-01-02→2026-05-29，338 日 | E4/-12% | `6b22d0b4...` | +22.9023% | -18.7246% | 37 | 1.7781 |

`103208` 与 `115619` 的日期、资本、费用、因子柜、随机种子、特征文件大小/时间和记录的代码指纹相同，但结果明显不同。WBS 历史记录已说明二者之间接通了 winner-add 字段；真正承载该变化的 `scap_v3_lean.py` 未纳入代码指纹。因此这不是随机市场差异，而是**身份系统漏记了行为相关代码变化**。

### 2.2 同一 338 日运行的时间分段

`run20260729_234344` 在 2025-09-25 的账户 NAV 为 27,499.46 元，相对 20,000 元初始资金为 **+37.4973%**；到 2026-05-29 降为 24,580.46 元，即后半段独立收益：

\[
R_{post}=\frac{24580.46}{27499.46}-1=-10.6147\%
\]

因此，“+37.50% 变成 +22.90%”有明确的窗口路径解释。它不能和 180 日的 +43.35% 或 +29.65%直接比较，因为最新运行还同时改变了止损档位、代码状态和资本档案。

### 2.3 winner-add 导致的首个实质分叉

`103208` 与 `115619` 的安全账本最早在 2025-02-06 出现一个提案数量差，但计划仍相同；首个改变交易路径的分叉发生在 **2025-03-27**：

- `103208`：没有 winner-add，计划暴露约 69.50%。
- `115619`：选中 `sz301300` 一手 winner-add，计划暴露约 83.63%。

此后现金、权重、退出、再买和费用全部成为内生路径变量。收益差不能简单解释为“这一笔加仓亏了多少”，更不能据此认定 winner-add 整体无效；当前只有极少加仓样本，统计功效不足。

## 三、代码模块审计

### 3.1 P0：运行身份与代码指纹失真

`runtime_identity.py` 当前只哈希少量固定文件。缺失的直接行为模块至少包括：

- `scap_v3_lean.py`
- `integer_action_optimizer.py`
- `scap_v31_authority.py`
- `capital_scaling.py`
- `action_utility.py`
- `runtime_integrity_audit.py`
- `pending_orders.py`
- `retail_execution.py`
- `functions/execution/` 下的交易规则与费用实现

同时 `output_dir` 被放进 `runtime_identity_hash`。结果是：

- 关键代码变了，代码指纹可能不变；
- 代码和配置完全相同，仅输出目录不同，运行身份却必然变化。

这使当前哈希既不能可靠证明“相同”，也不能可靠证明“不同”。

### 3.2 P0：普通退出被利润过滤器系统性拒绝

`scap_v3_lean._append_held_proposals()` 把一部分生命周期退出定义为普通 `exit`。只有包含 qualification、hard stop、loss containment、safety 等字样的退出才升级为强制 `hard_exit`。

`integer_action_optimizer.optimize_action_proposals()` 只把 `hard_exit` 和 `safety_exit` 放入 forced 集合；其余动作必须满足：

\[
V_i^{robust}-P_i^{authority}>0
\]

普通 `exit` 的稳健效用在持有预期为正时会得到 0，随后被拒绝为 `non_positive_robust_profit`。在最新 338 日运行中：

- **234 个交易日**出现至少一个普通退出被该理由拒绝；
- 真实卖出原因只有 `profit_hard_stop_exit` 20 笔、`loss_containment_exit` 14 笔、`safety_deleveraging` 3 笔；
- 大量 signal failure、thesis failure、profit giveback 等 E4 软退出并未形成实际卖出权。

这说明当前实现不是文档所描述的完整 E4，而更接近“硬止盈 + 硬损失控制 + 少量安全降仓”。这是会显著改变收益、回撤、持有期和 PF 的主路径缺陷。

### 3.3 P0：战略目标、硬上限与降仓确认不是同一状态机

`runner.py` 在 aggressive lean 模式下根据结构状态把战略预算设为 NORMAL/WEAK/HIGH 档；`scap_v3_lean._append_exposure_cap_safety_exits()` 却主要根据另一套 safety `risk_level`、hard freeze 和 trigger streak 决定是否强制降仓。

在 2026-02-02 和 2026-02-03：

- 结构状态为 weak；
- 战略预算/传入优化器的 ceiling 为 65%；
- 实际暴露约 76.8%/77.3%；
- safety `risk_level` 仍为 normal，降仓确认不成立；
- 没有 safety-exit 提案，空计划保持原仓位；
- 完整性审计最终报告 2 个授权失败日。

数学上，这是把同一个 65% 同时当成“希望达到的软目标”和“不可超过的硬约束”，但又不给系统足够的强制退出权限。正确设计必须拆分三种量：

\[
E_t^{desired},\quad E_t^{hard},\quad E_t^{de\_risk}
\]

- `desired`：软目标，不强迫交易；
- `hard`：灾难硬上限，必须满足或生成强制减仓；
- `de_risk`：经过状态确认后的阶段性降仓目标。

### 3.4 P1：权威选择血缘在三张表中互相矛盾

最新 338 日运行中：

- `governance_candidate_funnel_daily.csv` 的权威 optimizer-selected 累计为 **42**，registered entry buy 也为 **42**；
- `actual_exposure_ledger.csv` 的 `optimizer_selected_entry_count` 累计为 **4,846**；
- 两表在 **328/338 日**不一致；
- `scap_profit_summary.csv` 的 `optimizer_selected` 样本数为 **0**。

原因是：

- 暴露账本保留了进入 Lean 唯一 ActionPlan 前的旧候选选择口径；
- 漏斗使用 Lean 计划的真实选中口径；
- 利润审计读取候选行上的 `scap_optimizer_selected`，但 Lean 计划没有把最终 proposal/plan 选择回写到该审计输入。

因此目前不能用 `scap_profit_summary` 判断优化器是否创造价值，也不能用暴露账本的 4,846 解释真实交易。

### 3.5 P1：赢家加仓存在重复权限与失效默认值

当前链路大致为：

1. `position_lifecycle.py` 根据盈利触发、hold support、冷却、利润保护、单名上限和增量效用产生 `add_allowed`；
2. `scap_v3_lean.py` 再检查一次 4%/8% 硬编码触发、层数、review、A/B 权限；
3. 唯一整数优化器再做现金、暴露、集中度和风险判断。

问题包括：

- 生命周期读取 profile 阈值，Lean 又硬编码 4%/8%，参数改变后会出现双重口径；
- `winner_add_review_passed` 缺失时默认 `True`；
- `entry_authority_tier` 缺失时默认 `A`；
- `attach_scap_v31_authority()` 在 runner 和 Lean 内被重复调用，可能让生命周期证据、候选权限和最终提案权限不是同一快照；
- 加仓是高路径敏感动作，却没有独立的 `proposal→plan→fill→增量 PnL` 审计产品。

权限字段应 fail closed；生命周期只输出事实证据，最终交易权只能由一次 ActionPlan 决定。

### 3.6 P1：优化目标的数学单位和风险证据仍不完整

当前主利润期限约为 10 日，而协方差矩阵表示日收益协方差。组合风险惩罚使用：

\[
\Delta \sigma_{daily}\times NAV\times\lambda
\]

但未显式换算为 10 日：

\[
\Delta \sigma_H=\sqrt{H}\Delta \sigma_{daily}
\]

这会使风险厌恶系数缺乏稳定金融含义。另有以下问题：

- proposal downside 多使用固定 15% 名义压力，不是经验 CVaR；
- 协方差风险虽可能进入优化目标，但计划没有落盘边际风险金额，报告却显示 `covariance_risk_model_used=False`、风险贡献为 0；
- Pareto 缩减在组合协方差计算前执行，可能删除单看收益一般、但对组合分散有价值的候选；
- 替换动作的现金可行性没有明确把卖出净回款加入同一原子计划现金方程；
- ActionPlan 报告的 lexicographic rank 与求解器内部元组字段并不完全一致。

### 3.7 P2：报告金融口径需要明确

最新运行：

- 策略收益 +22.90%；
- 基准收益 +47.76%；
- 报告 `benchmark_excess_return=-25.39%`。

几何终值相对收益实际为：

\[
\frac{1.229023}{1.477568}-1=-16.82\%
\]

两者可能分别代表逐日主动收益复合与终值几何相对收益，但必须同时显示名称和公式，不能都简称“超额收益”。

## 四、金融解释

### 4.1 高集中度使路径差异被放大

SCAP 最多 5 只股票，最新期末 sleeve 有效 N 约 3.58，头号 sleeve 权重约 33.77%。名义上 4—5 只并不等于因子风险分散；同风格、同流动性和同涨跌停制度暴露可在极端日共振。

赢家加仓会把已经上涨的单名权重继续提高：

\[
w_{i,t}^{after}=w_{i,t}^{before}+\Delta w_{i,t}
\]

它同时放大趋势延续的右尾和拥挤反转的左尾。只看平均胜率无法判断是否值得，应比较加仓相对“不加仓但继续持有”的成本后增量财富分布。

### 4.2 更紧止损不必然降低回撤

从 -18% 改到 -12% 会同时改变：

- 卖出时点；
- 冷却和再入场；
- 现金占用；
- 之后可选股票；
- 交易成本；
- 未实现与已实现 PnL 的路径。

在跳空、涨跌停和 T+1 下，-12% 不是保证最大只亏 12%；更紧止损还可能增加震荡市反复止损。必须做同代码、同窗口、只改止损的 A/B，不能从现有运行直接归因。

### 4.3 PF、胜率和闭合交易数对退出缺陷高度敏感

当普通退出被拒绝时，闭合交易主要由硬止盈和硬止损构成，会产生选择性截断。此时 PF 与胜率不再代表设计中的完整 E4 策略。修复退出后交易数、平均持有期、盈亏比和最大回撤都会结构性变化，旧指标不能作为修复后基线。

## 五、完整修改方案

### Phase 0：冻结与可复现身份（必须先做）

1. 将现有 30 日相关运行标记为 `non_comparable_identity_incomplete`，保留产物，不删除、不回写。
2. 把身份拆成：
   - `experiment_spec_hash`：只含结果相关代码、完整有效配置、数据和模型内容；
   - `run_instance_id`：时间、PID、输出目录和恢复信息。
3. `experiment_spec_hash` 不得包含输出目录；相同实验写到不同目录必须相同。
4. 代码身份改为：
   - Git commit；
   - dirty patch hash；
   - SCAP 权威导入闭包中每个 `.py` 的 SHA256；
   - 无法解析导入闭包时，至少哈希 `functions/decision_council/`、`functions/execution/` 和直接配置文件。
5. 保存完整 resolved config：资本 profile 全字段、CLI 覆盖、控制开关、费用、止损、阈值、因子柜内容 SHA256、数据 schema/行数/内容指纹、随机种子、线程和包版本。
6. 增加确定性测试：
   - 同 spec 连跑两次，去掉 run id/时间字段后，逐日 proposal、plan、order、fill、NAV 哈希一致；
   - 修改任何权威模块，spec hash 必须变化；
   - 只改输出目录，spec hash 不变。

**Phase 0 验收门**：不能复现时禁止进入策略公式修改。

### Phase 1：重建退出和暴露状态机

1. 把动作分为：
   - `mandatory_exit`：灾难止损、资格失效、确认后的安全降仓；
   - `risk_reduction_exit`：为满足硬暴露上限所需；
   - `discretionary_exit`：利润回吐、信号/论点衰退、时间退出；
   - `new_entry`、`winner_add`、`replacement`。
2. `mandatory_exit` 和 `risk_reduction_exit` 不得经过“正利润”门；必须先进入 forced 集合。
3. `discretionary_exit` 比较同期限的：

\[
\Delta W_{sell-hold}
=CE(W_{sell})-CE(W_{hold})-TC_{sell}
\]

只有正增量价值才退出；若生命周期已经判为必须退出，就不能再标为 discretionary。
4. 拆分并单写：
   - `desired_exposure_target`
   - `hard_exposure_ceiling`
   - `confirmed_derisk_target`
   - `optimizer_planned_exposure`
   - `next_session_actual_exposure`
5. 超过硬上限时，ActionPlan 必须选择足够的可执行卖出，或以涨跌停/T+1/停牌等明确原因 fail closed；不得返回无解释的空计划。
6. 仅超过软目标、尚未确认降仓时：
   - 禁止继续增加总暴露；
   - 允许持有的非恶化空计划；
   - 完整性审计标记 `soft_target_overage_pending_confirmation`，不得误报为硬授权失败。

**Phase 1 验收门**：

- 构造所有 E1—E4 退出原因，mandatory 退出 100%进入计划；
- discretionary 退出有完整 sell-vs-hold 效用；
- 历史 2026-02-02/03 场景不再出现语义矛盾；
- `exit_state=True` 且连续被 `non_positive_robust_profit` 拒绝的天数必须为 0。

### Phase 2：统一赢家加仓权限

1. 生命周期只输出事实证据：
   - 当前收益、MFE/MAE、hold support、利润保护、冷却、最近加仓时间、当前股数；
   - 不直接授予交易权。
2. 删除 Lean 的硬编码 4%/8%，全部读取冻结 profile；缺字段一律 fail closed。
3. 每日只计算一次 authority snapshot，并给出 `authority_snapshot_id`；候选、生命周期、proposal 和 plan 均引用同一 ID。
4. 对每个可申请手数 \(q\) 计算：

\[
V_{add}(q)=Lq\mu^{LCB}
-TC(q)-\Delta RiskCE(q)-\Delta ConcentrationCE(q)
\]

5. 加仓后必须满足：
   - 现金缓冲；
   - 硬单名上限；
   - 硬组合暴露；
   - 风险形状不越界；
   - 边际稳健财富为正。
6. 新增独立消融：
   - winner-add off；
   - 当前触发；
   - 严格版：加仓后仍低于软单名上限且边际风险不恶化。

**Phase 2 验收门**：相同输入只产生一个 add proposal；缺少 review/authority 字段时不允许加仓；增加费用不得增加加仓手数。

### Phase 3：统一整数优化数学合同

1. 所有软动作统一为同期限、成本后、人民币增量确定性等价：

\[
CE_i(q)=E[\Delta W_{i,H}(q)]
-\kappa\cdot Risk_{i,H}(q)
-TC_i(q)
\]

2. 日协方差必须按持有期限换算；若 \(H=10\)，至少显式使用 \(\sqrt{10}\) 尺度并记录假设。
3. 每个计划只使用一个主要风险表达：
   - 有可靠收益分布时用增量 CVaR；
   - 只有协方差时用边际波动 CE；
   - 两者不足时只用保守硬上限。
4. 强制动作先满足；其余动作按稳健净财富最大化。广度和仓位缺口只能在主目标近优集合内做次级选择，不能复活负价值买单。
5. Pareto 缩减只允许删除在同动作、同股票、同手数域下被严格支配的提案；涉及协方差互补性的跨股票候选不得仅凭单体收益删除。
6. 替换现金方程必须包含卖出净回款，并保持买卖两腿原子性。
7. 使用账户真实 shares/lot size 构建 current lots，不再从权重反推作为权威事实。
8. 计划落盘全部目标分解：毛收益、费用、权限折扣、风险 CE、集中度 CE、主目标、次级目标、最优性状态和近似 gap。

### Phase 4：修复血缘、审计和报告

1. 新增规范化表：
   - `action_proposal_ledger`
   - `action_plan_ledger`
   - `order_lineage_ledger`
   - `fill_lineage_ledger`
   - `action_pnl_attribution`
2. 每个成交必须唯一连接：

`proposal_id → plan_id → order_id → fill_id → position_lot_id → closed/open PnL`

3. 删除/重命名旧的模糊 `optimizer_selected_entry_count`：
   - `preplan_candidate_selected_count`
   - `actionplan_new_entry_selected_count`
   - `registered_new_entry_count`
   - `filled_new_entry_count`
4. `scap_profit_summary` 按 proposal/plan 血缘生成，若存在已成交新入场而 optimizer-selected 样本为 0，保存阶段直接失败。
5. 风险报告必须显示优化器实际使用的风险模型、期限、pre/post risk、边际风险金额；禁止 runtime state 为 calibrated 而 used=False 且风险全为 0 时仍静默通过。
6. 超额收益同时显示：
   - `arithmetic_active_return_compounded`
   - `geometric_terminal_relative_return`
   并给出公式。
7. 拒绝原因保存为逐行表，不再把数百个拒绝拼成一个超长字符串。

### Phase 5：验证与经济复跑

按以下顺序，不得跳步：

1. 语法和静态调用图；
2. 动作、退出、暴露和费用的构造测试；
3. 性质/变形测试；
4. 同 spec 双跑确定性测试；
5. 20 日工程全链；
6. 固定 180 日开发窗回放；
7. 338 日只作长窗稳定性；
8. 滚动块、年度切片、成本压力和未触碰留出期；
9. 前瞻纸面运行。

必须预注册单变量 A/B：

| 实验 | 唯一变量 | 目的 |
|---|---|---|
| A0/A1 | 旧退出 vs 修复退出 | 测量 E4 真实增量效果 |
| B0/B1 | winner-add off/on | 测量加仓相对继续持有 |
| C0/C1 | -18%/-12% 灾难线 | 测量止损与跳空/反复交易 |
| D0/D1 | 软目标非恶化/确认后强制降仓 | 测量风险状态机 |
| E0/E1 | 协方差 CE/保守硬上限 | 测量风险模型增量价值 |

每组必须固定：experiment spec、日期、因子柜、资本、费用、PIT、数据快照和随机种子。比较输出包括终值、最大回撤、几何基准相对收益、成本、换手、有效 N、尾部损失、开放仓位 PnL 和逐动作增量 PnL。

## 六、建议施工顺序与文件映射

| 顺序 | 文件 | 修改职责 |
|---|---|---|
| 1 | `runtime_identity.py`、preflight/manifest | 双身份、完整代码/配置/数据指纹 |
| 2 | `scap_v2_contracts.py` | 新动作优先级、hard/soft 暴露字段、效用分解 schema |
| 3 | `position_lifecycle.py` | 只产出退出/加仓事实证据，明确 mandatory/discretionary |
| 4 | `scap_v3_lean.py` | 唯一 proposal factory、统一状态机、移除重复阈值 |
| 5 | `integer_action_optimizer.py` | forced exit、期限风险、原子现金、单一 CE 目标 |
| 6 | `runner.py` | 单次 authority snapshot、真实 shares、权威字段回写 |
| 7 | `pending_orders.py`、`execution_runtime.py` | lineage 与执行约束 |
| 8 | `runtime_integrity_audit.py` | hard/soft 暴露、退出可达、血缘一致性 |
| 9 | `scap_profit_objective.py`、`runner_summary.py` | 权威选择 cohort、几何/算术超额分列 |
| 10 | Web/monitor | 只消费规范化字段，不自行推导或回退为 0 |

## 七、最终验收标准

以下条件全部满足前，策略保持 blocked：

- 同 spec 双跑的规范化逐日账本哈希完全一致；
- 任一权威代码改变都会改变 experiment spec hash；
- 退出提案不存在错误的正利润过滤；
- hard exposure 超限日为 0，或每一天都有明确不可执行证据；
- proposal→plan→order→fill→PnL 唯一血缘覆盖率 100%；
- 漏斗、暴露账本和利润审计的 action-plan 选中数完全一致；
- 已成交新入场时 profit audit 的 selected 样本不得为 0；
- 风险模型使用状态与优化器目标分解一致；
- 20 日工程链通过后，180/338 日和留出期结果均按同一实验身份生成；
- 至少 30 笔成熟闭合交易、成本压力、年度切片和前瞻纸面证据满足预注册研究门。

## 八、当前判断

现有结果只能说明：

- 账户、T+1、整手和大部分成交账本可运行；
- winner-add 字段接通确实能改变路径；
- 2025-09-25 之后的新增区间对最新运行贡献约 -10.61%；
- 当前输出仍不能隔离因子、退出、加仓、风险和止损的独立因果效果。

在修复身份、退出权、暴露状态机和血缘之前，继续调因子权重或止损参数会把代码缺陷误当金融结论，增加过拟合风险。推荐先完成 Phase 0—1，经主人确认后再进入代码实施。
